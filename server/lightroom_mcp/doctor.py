"""Self check (``lrmcp doctor`` and the ``lr_doctor`` tool). Every result says what is wrong and what to do."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__, config
from .bridge import Bridge


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def _lightroom_running() -> bool | None:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Lightroom.exe", "/NH"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return "Lightroom.exe" in out


def _file_mentions(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def run_checks(bridge: Bridge | None, busy_message: str | None = None, wait_plugin: float = 0.0) -> list[Check]:
    checks: list[Check] = []
    checks.append(Check("服务版本", True, f"lightroom_mcp {__version__}"))

    running = _lightroom_running()
    if running is None:
        checks.append(Check("Lightroom 是否在运行", False, "无法检查进程列表", "手动确认 Lightroom Classic 已打开"))
    else:
        checks.append(
            Check(
                "Lightroom 是否在运行",
                running,
                "Lightroom.exe 正在运行" if running else "没有找到 Lightroom.exe",
                "" if running else "请先打开 Lightroom Classic",
            )
        )

    if bridge is None:
        checks.append(Check("本机通信端口", False, busy_message or "桥接服务没有启动", "关闭另一个 Claude/Codex 会话里的 Lightroom MCP，或重启它们"))
    else:
        checks.append(Check("本机通信端口", True, f"已监听 {config.HOST}:{bridge.port}（只在本机）"))
        if wait_plugin and not bridge.connected:
            bridge.wait_connected(wait_plugin)
        if bridge.connected:
            ver = bridge.plugin_version or "未知"
            ago = time.time() - bridge.last_seen
            checks.append(Check("Lightroom 插件已连上", True, f"插件版本 {ver}，最近一次联系 {ago:.0f} 秒前"))
        else:
            checks.append(
                Check(
                    "Lightroom 插件已连上",
                    False,
                    "最近没有收到插件的联系",
                    "确认 Lightroom 已打开；在 文件→增效工具管理器 里看 LrMCP 是否已启用，必要时点“重新载入增效工具”",
                )
            )

    token = config.TOKEN_FILE
    if token.is_file():
        checks.append(Check("口令文件", True, f"{token}"))
    else:
        checks.append(Check("口令文件", False, "没有找到口令文件", "重启 Claude/Codex 会话，让服务重新生成"))

    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = config.DATA_DIR / ".write_test"
        probe.write_text("x")
        probe.unlink()
        checks.append(Check("数据目录可写", True, str(config.DATA_DIR)))
    except OSError as e:
        checks.append(Check("数据目录可写", False, f"{config.DATA_DIR}：{e}", "检查该文件夹的权限"))

    try:
        import PIL  # noqa: F401

        checks.append(Check("图片处理组件", True, "Pillow 可用"))
    except ImportError:
        checks.append(Check("图片处理组件", False, "缺少 Pillow", "重新安装 Lightroom MCP"))

    home = Path.home()
    codex_cfg = home / ".codex" / "config.toml"
    claude_cfg = home / ".claude.json"
    codex_ok = _file_mentions(codex_cfg, "lightroom_mcp")
    claude_ok = _file_mentions(claude_cfg, "lightroom_mcp")
    checks.append(
        Check(
            "客户端登记",
            codex_ok or claude_ok,
            f"Claude Code：{'已登记' if claude_ok else '未发现'}；Codex：{'已登记' if codex_ok else '未发现'}",
            "" if (codex_ok or claude_ok) else "运行 lrmcp register（或重新运行安装程序）",
        )
    )
    return checks


def format_report(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        mark = "✅" if c.ok else "❌"
        lines.append(f"{mark} {c.name}：{c.detail}")
        if not c.ok and c.fix:
            lines.append(f"   → {c.fix}")
    bad = sum(1 for c in checks if not c.ok)
    lines.append("")
    lines.append("全部正常。" if bad == 0 else f"有 {bad} 项需要处理。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Command line ``lrmcp doctor``: starts the bridge for a few seconds to see if the plug-in shows up."""
    from .bridge import BridgeBusy

    bridge: Bridge | None = Bridge()
    busy: str | None = None
    try:
        bridge.start()
    except BridgeBusy as e:
        bridge, busy = None, str(e)
    try:
        print(format_report(run_checks(bridge, busy, wait_plugin=15.0)))
    finally:
        if bridge is not None:
            bridge.stop()
    return 0
