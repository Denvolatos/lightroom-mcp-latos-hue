# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Run the plug-in's real Bridge.lua (poller + manager) against a fake Lightroom SDK, in a Lua 5.1 interpreter.
Covers the 0.14 reconnect fix: after a 401 / refused connection the poller re-reads the announcement at once.
Skipped when the optional package ``lupa`` is not installed."""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa.lua51")

PLUGIN = Path(__file__).resolve().parents[2] / "plugin" / "lrmcp.lrdevplugin"

FAKE_SDK = r"""
local read_plugin_file = ...

local DIR = "C:/Users/test/LrMcp"
local INFO = DIR .. "/servers/58770.txt"
FAKE = { files = {}, sleeps = {}, requests = {}, logs = {}, handler = nil, INFO = INFO }

function ANNOUNCE(token, pid) FAKE.files[INFO] = "port=58770\ntoken=" .. token .. "\npid=" .. pid .. "\nversion=x\n" end
function REMOVE() FAKE.files[INFO] = nil end

local modules = {
  LrDate = { currentTime = function() return 1 end },
  LrFileUtils = {
    exists = function(p)
      if p == DIR .. "/servers" then return "directory" end
      return FAKE.files[p] and "file" or false
    end,
    readFile = function(p) return FAKE.files[p] end,
    files = function(dir)
      local list = {}
      for p in pairs(FAKE.files) do list[#list + 1] = p end
      local i = 0
      return function() i = i + 1 return list[i] end
    end,
  },
  LrHttp = {
    get = function(url, headers)
      local token
      for _, h in ipairs(headers) do if h.field == "Authorization" then token = h.value:gsub("^Bearer ", "") end end
      FAKE.requests[#FAKE.requests + 1] = token
      return FAKE.handler(token, #FAKE.requests)
    end,
    post = function() end,
  },
  LrLogger = function() return { enable = function() end, info = function(_, text) FAKE.logs[#FAKE.logs + 1] = text end } end,
  LrPathUtils = {
    child = function(a, b) return a .. "/" .. b end,
    getStandardFilePath = function() return "C:/Users/test" end,
    leafName = function(p) return (p:match("([^/]+)$")) end,
  },
  LrTasks = {
    -- tasks run to completion at once; the manager's own sleep(2) ends the test run
    startAsyncTask = function(fn) fn() end,
    sleep = function(s)
      FAKE.sleeps[#FAKE.sleeps + 1] = s
      if s == 2 and FAKE.manager_ready and not FAKE.no_auto_stop then _G.LrMcp.stop = true end
    end,
    pcall = pcall,
  },
}
function import(name) return assert(modules[name], "no fake for " .. name) end

local overrides = {
  ["Commands.lua"] = { run = function() return {} end },
  ["Version.lua"] = "9.9.9",
}
local cache = {}
function require(name)
  if overrides[name] ~= nil then return overrides[name] end
  if cache[name] == nil then
    local chunk, err = loadstring(read_plugin_file(name), "@" .. name)
    assert(chunk, err)
    cache[name] = chunk()
  end
  return cache[name]
end

function LOAD()
  FAKE.manager_ready = true
  require("Bridge.lua")
end
function JOINED(list) local t = {} for i, v in ipairs(list) do t[i] = tostring(v) end return table.concat(t, ",") end
function SERVERS_LEFT() local n = 0 for _ in pairs(_G.LrMcp.servers) do n = n + 1 end return n end
function LOG_TEXT() return table.concat(FAKE.logs, "\n") end
"""


@pytest.fixture
def lr():
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(FAKE_SDK, lambda name: (PLUGIN / name).read_text(encoding="utf-8"))
    return runtime, runtime.globals()


def test_401_after_a_restart_switches_to_the_new_token_without_waiting(lr):
    runtime, g = lr
    g.ANNOUNCE("OLDTOKEN", 1)
    runtime.execute(
        """
        FAKE.handler = function(token, n)
          if token == "OLDTOKEN" then ANNOUNCE("NEWTOKEN", 2) return "unauthorized", { status = 401 } end
          REMOVE() -- the new server answers once, then it is gone too
          return "none", { status = 200 }
        end
        """
    )
    g.LOAD()
    assert g.JOINED(g.FAKE["requests"]) == "OLDTOKEN,NEWTOKEN"
    # the only sleep is the manager's own 2 s; the poller did not wait before using the new token
    assert g.JOINED(g.FAKE["sleeps"]) == "2"
    assert g.SERVERS_LEFT() == 0


def test_refused_connection_with_a_new_announcement_retries_at_once(lr):
    runtime, g = lr
    g.ANNOUNCE("OLDTOKEN", 1)
    runtime.execute(
        """
        FAKE.handler = function(token, n)
          if n == 1 then ANNOUNCE("NEWTOKEN", 2) return nil, { error = { errorCode = "cannotConnectToHost" } } end
          REMOVE()
          return "none", { status = 200 }
        end
        """
    )
    g.LOAD()
    assert g.JOINED(g.FAKE["requests"]) == "OLDTOKEN,NEWTOKEN"
    assert g.JOINED(g.FAKE["sleeps"]) == "2"


def test_announcement_gone_after_a_failure_ends_the_poller_without_sleeping(lr):
    runtime, g = lr
    g.ANNOUNCE("OLDTOKEN", 1)
    runtime.execute(
        """
        FAKE.handler = function(token, n) REMOVE() return "unauthorized", { status = 401 } end
        """
    )
    g.LOAD()
    assert g.JOINED(g.FAKE["requests"]) == "OLDTOKEN"
    assert g.JOINED(g.FAKE["sleeps"]) == "2"
    assert g.SERVERS_LEFT() == 0
    assert "stopped polling port 58770" in g.LOG_TEXT()


def test_a_new_announcement_after_a_normal_poll_is_picked_up(lr):
    runtime, g = lr
    g.ANNOUNCE("OLDTOKEN", 1)
    runtime.execute(
        """
        FAKE.handler = function(token, n)
          if n == 1 then ANNOUNCE("NEWTOKEN", 2) return "none", { status = 200 } end -- old server woken by stop()
          REMOVE()
          return "none", { status = 200 }
        end
        """
    )
    g.LOAD()
    assert g.JOINED(g.FAKE["requests"]) == "OLDTOKEN,NEWTOKEN"
    assert g.JOINED(g.FAKE["sleeps"]) == "2"


def test_same_token_still_unauthorized_backs_off(lr):
    runtime, g = lr
    g.ANNOUNCE("TOKEN", 1)
    runtime.execute(
        """
        FAKE.no_auto_stop = true -- a 2 s back-off must not be mistaken for the manager's sleep
        FAKE.handler = function(token, n)
          if n >= 3 then REMOVE() _G.LrMcp.stop = true end
          return "unauthorized", { status = 401 }
        end
        """
    )
    g.LOAD()
    # no hot loop: back-off 1+fails seconds between attempts (2, then the file is gone), then the manager's 2
    assert g.JOINED(g.FAKE["requests"]) == "TOKEN,TOKEN,TOKEN"
    assert g.JOINED(g.FAKE["sleeps"]) == "2,3,2"


def test_the_token_is_never_written_to_the_log(lr):
    runtime, g = lr
    g.ANNOUNCE("SECRETTOKEN", 1)
    runtime.execute(
        """
        FAKE.handler = function(token, n)
          if n == 1 then ANNOUNCE("SECRETTOKEN2", 2) return nil, { status = 401 } end
          REMOVE() return "none", { status = 200 }
        end
        """
    )
    g.LOAD()
    assert "changed" in g.LOG_TEXT()
    assert "SECRETTOKEN" not in g.LOG_TEXT()
