# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""设置页“安全 / 维护 / 关于”用到的后台功能（1.3.0）：只读开关、清理缓存、诊断包、恢复默认设置、关于信息。

原则：
- 所有路径都由调用方注入（测试里全用 tmp_path），本模块不读写真实的 ~/LrMcp；
- 清理缓存只动软件自己的缓存（内存里的缩略图/预览缓存、计时日志），不碰照片、设置、经验库、收藏、版本数据、Lightroom 目录；
- 诊断包只含脱敏后的文字：不含照片、缩略图、文件名、经验库/收藏内容、对话内容，设置里的路径只留“是否已设置”。
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
import zipfile
from pathlib import Path

LOG_TAIL_LINES = 500
TIMING_TAIL_ROWS = 200

ABOUT_STATIC = {
    "name": "Latos Hue 修图助手",
    "license": "AGPL-3.0-only",
    "homepage": "https://github.com/Denvolatos/lightroom-mcp-latos-hue",
    "authors": [{"name": "Denvolatos", "role": "发起与主要开发", "key": "denvolatos", "url": "https://github.com/Denvolatos"},
                {"name": "Galio1991", "role": "共同开发", "key": "galio1991", "url": "https://github.com/Galio1991"}],
    "disclaimer": "本软件不含任何 Adobe 软件，也不是 Adobe 官方产品。",
    "tagline": "让 AI 帮你在一个窗口里挑片、修图、导出。",
}


# 页面只能传 key，网址只在这里：白名单之外一律不打开
LINKS = {"homepage": ABOUT_STATIC["homepage"], "denvolatos": "https://github.com/Denvolatos",
         "galio1991": "https://github.com/Galio1991"}


def open_link(key, opener=None) -> dict:
    """按 key 在默认浏览器里打开白名单里的网址。返回 {"ok","message"}；失败时 message 带网址方便手动访问。"""
    url = LINKS.get(key) if isinstance(key, str) else None
    if url is None:
        return {"ok": False, "message": "无法打开：未知的链接。"}
    try:
        if opener is None:
            import webbrowser                               # noqa: PLC0415
            opener = webbrowser.open
        ok = opener(url)
    except Exception:                                       # noqa: BLE001
        ok = False
    if ok is False:
        return {"ok": False, "message": f"无法打开，请手动访问：{url}"}
    return {"ok": True, "message": ""}


def about_info(version: str, plugin_version) -> dict:
    out = json.loads(json.dumps(ABOUT_STATIC))              # 深拷贝，调用方改动不会污染常量
    out["version"] = version
    out["plugin_version"] = plugin_version if isinstance(plugin_version, str) and plugin_version else None
    return out


# ---------------------------------------------------------------- 只读开关
def readonly_state(readonly_file: Path, environ=None) -> dict:
    env = (environ if environ is not None else os.environ).get("LRMCP_READONLY") == "1"
    try:
        has_file = Path(readonly_file).exists()
    except OSError:
        has_file = False
    return {"file": has_file, "env": env, "on": has_file or env}


def set_readonly(on, readonly_file: Path, environ=None) -> dict:
    """创建/删除只读开关文件（服务端与插件都认它）。返回 {"ok","readonly","message"}。"""
    if not isinstance(on, bool):
        return {"ok": False, "readonly": readonly_state(readonly_file, environ)["on"], "message": "请选择开或关。"}
    f = Path(readonly_file)
    try:
        if on:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("read-only mode: delete this file to allow changes\n", encoding="utf-8")
        else:
            f.unlink(missing_ok=True)
    except OSError as e:
        st = readonly_state(f, environ)["on"]
        why = e.strerror or str(e)
        return {"ok": False, "readonly": st,
                "message": ("无法开启只读模式：" if on else "无法关闭只读模式：") + why + "。请检查数据文件夹的权限后重试。"}
    state = readonly_state(f, environ)
    if on:
        return {"ok": True, "readonly": True, "message": "只读模式已开启：Lightroom 里的照片不会被修改。"}
    if state["env"]:
        return {"ok": True, "readonly": True,
                "message": "只读开关文件已删除，但环境变量 LRMCP_READONLY=1 仍然让只读模式保持开启。"
                           "要完全关闭，请在系统设置里删除这个环境变量。"}
    return {"ok": True, "readonly": False, "message": "只读模式已关闭。"}


# ---------------------------------------------------------------- 清理缓存
def human_size(n: int) -> str:
    n = max(int(n), 0)
    if n < 1024:
        return f"{n} B"
    for unit, div in (("KB", 1024), ("MB", 1024 ** 2), ("GB", 1024 ** 3)):
        if n < div * 1024 or unit == "GB":
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def clear_cache(thumb_store, preview_store, timing_log: Path) -> dict:
    """清空缩略图缓存、预览缓存（都在内存里）并删除计时日志。其余文件一概不碰。"""
    items = []
    for name, store in (("图库缩略图缓存", thumb_store), ("预览缓存", preview_store)):
        n = size = 0
        if store is not None:
            n, size = store.clear()
        items.append({"name": name, "bytes": int(size)})
    log_bytes = 0
    p = Path(timing_log)
    try:
        if p.is_file() and not p.is_symlink():
            log_bytes = p.stat().st_size
            p.unlink()
    except OSError:
        log_bytes = 0
    items.append({"name": "计时日志", "bytes": log_bytes})
    total = sum(i["bytes"] for i in items)
    msg = f"已清理缓存，释放约 {human_size(total)}。缩略图和预览会在需要时重新读取，照片和设置不受影响。"
    return {"ok": True, "freed_bytes": total, "freed_text": human_size(total), "items": items, "message": msg}


# ---------------------------------------------------------------- 脱敏
PATH_KEYS = ("base_folder", "export_last_folder", "lightroom_path")
SAFE_SETTING_KEYS = ("schema", "provider", "provider_chosen", "confirm_default", "preview_edge", "export_format",
                     "export_size", "export_quality", "export_bit_depth", "export_metadata", "ai_use_notes",
                     "auto_launch_lightroom", "wizard_done", "check_updates", "gallery_sort", "gallery_order",
                     "theme", "font_size", "panel_widths", "preview_zoom")

_WIN_PATH = re.compile(r"[A-Za-z]:[\\/][^\r\n\"'<>|*?]*")            # 盘符路径：到行尾/引号为止（路径里可能有空格）
_UNC_PATH = re.compile(r"\\\\[^\r\n\"'<>|*?]+")
_NIX_PATH = re.compile(r"(?<![\w:/])/(?:Users|home|var|tmp|private|Volumes|mnt)/[^\r\n\"'<>|*?]*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SECRET_KV = re.compile(r"(?i)\b([\w-]*(?:token|secret|password|passwd|pwd|api[_-]?key|authorization|口令|密码)[\w-]*\s*[=:：]\s*)\S+")
_BEARER = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_LONG_KEY = re.compile(r"\b(?:sk-|ghp_|gho_|xox[bp]-)[A-Za-z0-9_-]{10,}|\b[A-Za-z0-9_-]{32,}\b")
_PHOTO_FILE = re.compile(r"[\w\-.]*\w\.(?:cr2|cr3|crw|nef|nrw|arw|dng|raf|orf|rw2|pef|srw|heic|heif|jpe?g|tiff?|png|webp|xmp|lrcat|lrdata)\b",
                         re.IGNORECASE)


def scrub_text(text, extra_names=()) -> str:
    """把用户名、路径、邮箱、口令样式的内容换成占位符。顺序：先整段路径（路径里常含用户名），再逐项。"""
    s = str(text)
    s = _UNC_PATH.sub("<path>", s)
    s = _WIN_PATH.sub("<path>", s)
    s = _NIX_PATH.sub("<path>", s)
    s = _EMAIL.sub("<email>", s)
    s = _BEARER.sub(lambda m: m.group(1) + " <redacted>", s)
    s = _SECRET_KV.sub(lambda m: m.group(1) + "<redacted>", s)
    s = _PHOTO_FILE.sub("<file>", s)
    s = _LONG_KEY.sub("<redacted>", s)
    names = {n for n in extra_names if isinstance(n, str) and len(n) >= 2}
    for env in ("USERNAME", "USER", "LOGNAME"):
        v = os.environ.get(env)
        if v and len(v) >= 2:
            names.add(v)
    try:
        names.add(Path.home().name)
    except (RuntimeError, OSError):
        pass
    for n in sorted((n for n in names if len(n) >= 2), key=len, reverse=True):
        s = re.sub(re.escape(n), "<user>", s, flags=re.IGNORECASE)
    return s


def safe_settings(settings: dict) -> dict:
    """诊断包里的设置：只保留白名单里的开关/选项；路径只写“已设置/未设置”；其他任何字段（含将来加的口令、邮箱）一概不写。"""
    out = {}
    if not isinstance(settings, dict):
        return out
    for k in SAFE_SETTING_KEYS:
        if k in settings:
            v = settings[k]
            if isinstance(v, (bool, int, float)) or v is None:
                out[k] = v
            elif isinstance(v, str) and len(v) <= 40 and not _EMAIL.search(v) and "\\" not in v and "/" not in v:
                out[k] = v
            elif isinstance(v, dict):
                out[k] = {kk: vv for kk, vv in v.items() if isinstance(vv, (bool, int, float))}
    for k in PATH_KEYS:
        v = settings.get(k)
        out[k] = "已设置" if isinstance(v, str) and v.strip() else "未设置"
    return out


def tail_lines(path, n: int = LOG_TAIL_LINES) -> list[str]:
    try:
        p = Path(path)
        if not p.is_file():
            return []
        size = p.stat().st_size
        with p.open("rb") as f:
            f.seek(max(size - 2_000_000, 0))              # 只看最后约 2MB，够 500 行
            data = f.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()[-n:]


def timing_summary(path, rows: int = TIMING_TAIL_ROWS) -> dict:
    """计时日志摘要：只统计数字，不带工具名、对话内容。"""
    vals: dict[str, list[float]] = {"total_ms": [], "startup_ms": [], "model_ms": [], "tools_ms": []}
    modes: dict[str, int] = {}
    n = 0
    for line in tail_lines(path, rows):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        n += 1
        m = row.get("mode")
        if isinstance(m, str) and len(m) <= 20:
            modes[m] = modes.get(m, 0) + 1
        for k in vals:
            v = row.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals[k].append(float(v))
    out: dict = {"rows": n, "modes": modes}
    for k, xs in vals.items():
        if xs:
            xs.sort()
            out[k] = {"count": len(xs), "median": round(xs[len(xs) // 2], 1), "max": round(xs[-1], 1)}
    return out


def webview_runtime_version() -> str:
    """Edge WebView2 运行时版本（读注册表；读不到写“未知”）。"""
    try:
        import winreg                                       # noqa: PLC0415 - 只在 Windows 上有
    except ImportError:
        return "未知"
    guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root, sub in ((winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
                      (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
                      (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}")):
        try:
            with winreg.OpenKey(root, sub) as k:
                v = winreg.QueryValueEx(k, "pv")[0]
            if v:
                return str(v)
        except OSError:
            continue
    return "未知"


def environment_info() -> dict:
    pyweb = "未知"
    try:
        import webview                                      # noqa: PLC0415
        pyweb = str(getattr(webview, "__version__", "") or "未知")
    except Exception:                                       # noqa: BLE001
        pass
    return {"os": platform.platform(), "python": sys.version.split()[0], "pywebview": pyweb,
            "webview2_runtime": webview_runtime_version()}


README_TEXT = """Latos Hue 诊断包
生成时间：{when}

这个压缩包用来帮助排查问题，内容已经去掉了个人信息。你可以先自己打开看看，再决定要不要发给别人。

【包里有什么】
- diagnostics.json：软件版本、插件/服务端版本、系统与 Python/WebView 版本、环境检查各项的状态、
  Lightroom 连接状态、设置（只保留开关和选项；路径只写“已设置/未设置”）、计时摘要（只有数字）。
- log-tail.txt：最近最多 {lines} 行软件日志。里面的用户名已替换为 <user>，磁盘路径替换为 <path>，
  邮箱、口令样式的内容、照片文件名也已替换。

【包里没有什么】
- 没有照片、缩略图、预览图，没有照片文件名或文件夹路径。
- 没有经验库、收藏、版本数据，没有你和 AI 的对话内容。
- 没有任何账号、口令、令牌或邮箱。

脱敏是按规则自动做的，不能保证百分之百；发出去之前请自己看一眼 log-tail.txt。
"""


def build_diagnostics(folder, info: dict, *, settings: dict, wizard_items, connection: dict, log_files=(), timing_log=None,
                      now=None, extra_names=()) -> dict:
    """在 folder 里写 LatosHue-diagnostics-<时间>.zip。info：版本等（app_version, plugin_version, server_version, system, readonly）。
    全部输入由调用方给；返回 {"ok","path","bytes","message"}。"""
    folder = Path(folder)
    try:
        if not folder.is_dir():
            return {"ok": False, "path": "", "bytes": 0, "message": "所选位置不是文件夹。"}
        t = now if now is not None else time.localtime()
        stamp = time.strftime("%Y%m%d-%H%M%S", t)
        when = time.strftime("%Y-%m-%d %H:%M:%S", t)

        def sc(x):
            return scrub_text(x, extra_names)
        items = []
        for it in wizard_items or []:
            if isinstance(it, dict):
                items.append({"id": str(it.get("id", "")), "state": str(it.get("state", "")), "text": sc(it.get("text", ""))})
        conn = {}
        for k in ("state", "connected", "app", "side", "claude_alive"):
            if k in (connection or {}):
                v = connection[k]
                conn[k] = v if isinstance(v, (bool, int, float)) or v is None else sc(v)
        pv, sv = info.get("plugin_version"), info.get("server_version")
        data = {"generated": when,
                "versions": {"app": sc(info.get("app_version", "")), "plugin": sc(pv) if pv else None,
                             "server": sc(sv) if sv else None},
                "system": {k: sc(v) for k, v in (info.get("system") or {}).items()},
                "environment_check": items, "lightroom_connection": conn,
                "readonly": bool(info.get("readonly")), "settings": safe_settings(settings),
                "timing": timing_summary(timing_log) if timing_log else {}}
        log_lines: list[str] = []
        for lf in log_files:
            ls = tail_lines(lf)
            if ls:
                log_lines += [f"# {Path(lf).name}"] + [sc(x) for x in ls]
        out = folder / f"LatosHue-diagnostics-{stamp}.zip"
        n = 2
        while out.exists():
            out = folder / f"LatosHue-diagnostics-{stamp}-{n}.zip"
            n += 1
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("README.txt", README_TEXT.format(when=when, lines=LOG_TAIL_LINES))
            z.writestr("diagnostics.json", json.dumps(data, ensure_ascii=False, indent=2))
            z.writestr("log-tail.txt", "\n".join(log_lines) + "\n" if log_lines else "（没有日志文件）\n")
        size = out.stat().st_size
    except OSError as e:
        return {"ok": False, "path": "", "bytes": 0, "message": f"生成诊断包失败：{e.strerror or e}"}
    return {"ok": True, "path": str(out), "bytes": size,
            "message": "诊断包已生成（已去掉个人信息，不含照片和对话）。发出去之前可以先打开看看。"}


# ---------------------------------------------------------------- 恢复默认设置
KEEP_ON_RESET = ("base_folder", "provider", "provider_chosen")


def reset_settings(store, now=None) -> dict:
    """先备份旧设置为 app_settings.json.reset-<时间>.bak，再写回默认值，但保留照片库位置与已选的 AI 来源。
    store 是 settings.SettingsStore。返回 {"ok","message"}。"""
    import settings as appsettings                          # noqa: PLC0415
    stamp = time.strftime("%Y%m%d-%H%M%S", now if now is not None else time.localtime())
    with store._lock:
        old = dict(store.data)
        new = appsettings.defaults()
        for k in KEEP_ON_RESET:
            new[k] = old.get(k, new[k])
        new = appsettings.sanitize(new)
        bak = store.path.with_name(f"{store.path.name}.reset-{stamp}.bak")
        try:
            store.path.parent.mkdir(parents=True, exist_ok=True)
            if store.path.is_file():
                bak.write_bytes(store.path.read_bytes())
            else:
                bak.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
            store.save(new)
        except OSError as e:
            return {"ok": False, "message": f"恢复默认设置失败：{e.strerror or e}"}
    return {"ok": True, "message": "已恢复默认设置（照片库位置和 AI 来源保留）。原来的设置已备份。", "backup": bak.name}
