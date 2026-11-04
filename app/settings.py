"""软件设置：读写 ~/LrMcp/app_settings.json，并校验每个字段。

- 原子写入（先写临时文件再替换），带 schema 版本；
- 读取时逐字段校验，坏文件/缺字段/非法值一律回退默认值，不崩溃；未知字段原样保留；
- 不保存任何口令、密钥或登录信息；文件仅当前用户可读写（与 server 的 restrict_to_current_user 同一做法，
  server/ 不可改，因此在这里实现同样的 icacls 调用）。
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from lr_autostart import valid_lightroom_path

SCHEMA_VERSION = 1
SETTINGS_FILE = Path.home() / "LrMcp" / "app_settings.json"
APP_VERSION = "0.13.0"                  # 桌面软件 Latos Hue 的版本（开发中，尚未发布；首个发布版本为 1.0.0）
PROJECT_URL = "https://github.com/Denvolatos/lightroom-mcp-win"
DATA_DIR_TEXT = "~/LrMcp"

EDGE_CHOICES = (768, 1024, 1536, 2048)  # 与界面里"预览清晰度"的可选档位一致
DEFAULT_PROVIDER = "claude"

# 导出对话框的默认值与取值范围（服务端 export_photo_for_app 的范围相同）
EXPORT_FORMATS = ("jpeg", "tiff")
EXPORT_METADATA = ("minimal", "all")
EXPORT_BIT_DEPTHS = (8, 16)
EXPORT_QUALITY_RANGE = (40, 100)
EXPORT_EDGE_RANGE = (256, 20000)         # 长边像素；0 表示原始尺寸


def default_base_folder() -> str:
    return str(Path.home() / "Pictures" / "修图助手")


def defaults() -> dict:
    return {"schema": SCHEMA_VERSION, "base_folder": default_base_folder(), "provider": DEFAULT_PROVIDER,
            "confirm_default": True, "preview_edge": 1024,
            "export_last_folder": "", "export_format": "jpeg", "export_size": 0, "export_quality": 92,
            "export_bit_depth": 16, "export_metadata": "minimal", "ai_use_notes": True,
            "auto_launch_lightroom": False, "lightroom_path": ""}


# ---------------------------------------------------------------- 文件夹校验
def _protected_roots() -> list[Path]:
    """系统/程序目录：软件文件夹不能位于其中（或等于它们）。"""
    roots = []
    for var in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"):
        v = os.environ.get(var)
        if v:
            roots.append(Path(v))
    sysdrive = os.environ.get("SystemDrive", "C:")
    roots += [Path(sysdrive + "\\Windows"), Path(sysdrive + "\\Program Files"), Path(sysdrive + "\\Program Files (x86)"),
              Path(sysdrive + "\\ProgramData")]
    return roots


def _norm(p: Path) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _is_within(child: Path, parent: Path) -> bool:
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def validate_folder(path: str) -> dict:
    """返回 {"ok": bool, "message": 中文原因, "exists": bool, "path": 规范化后的路径}。
    不存在但位置合法时 ok=True、exists=False（由界面询问是否创建）。"""
    raw = (path or "").strip().strip('"')
    bad = lambda msg: {"ok": False, "message": msg, "exists": False, "path": raw}
    if not raw:
        return bad("请选择软件文件夹。")
    if raw.startswith("\\\\") or raw.startswith("//"):
        return bad("不支持网络路径，请选择本机文件夹。")
    p = Path(raw)
    if not p.is_absolute() or not p.drive:
        return bad("请填写完整的本机路径（例如 C:\\Users\\用户名\\Pictures\\修图助手）。")
    try:
        p = Path(os.path.abspath(raw))
    except (OSError, ValueError):
        return bad("路径无效。")
    if p.parent == p:
        return bad("不能使用磁盘根目录，请选择一个文件夹。")
    for root in _protected_roots():
        if _is_within(p, root):
            return bad("不能使用系统或程序目录，请选择其他位置。")
    if p.exists():
        if not p.is_dir():
            return bad("该路径是文件，不是文件夹。")
        if not _writable(p):
            return bad("该文件夹不可写入，请选择有写入权限的文件夹。")
        return {"ok": True, "message": "", "exists": True, "path": str(p)}
    # 不存在：向上找到最近的已存在目录，确认可写，才允许"创建"
    anc = p.parent
    while not anc.exists() and anc.parent != anc:
        anc = anc.parent
    if not anc.exists() or not anc.is_dir():
        return bad("路径所在的磁盘不存在。")
    if not _writable(anc):
        return bad("无法在该位置创建文件夹（没有写入权限）。")
    return {"ok": True, "message": "", "exists": False, "path": str(p)}


def _writable(directory: Path) -> bool:
    try:
        with tempfile.TemporaryFile(dir=str(directory)):
            return True
    except OSError:
        return False


def create_folder(path: str) -> dict:
    v = validate_folder(path)
    if not v["ok"]:
        return v
    try:
        Path(v["path"]).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "message": f"创建文件夹失败：{e.strerror or e}", "exists": False, "path": v["path"]}
    return validate_folder(v["path"])


# ---------------------------------------------------------------- 字段校验
def _clean_edge(v):
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n in EDGE_CHOICES else None


def _clean_int(v, lo=None, hi=None, allowed=None, zero_ok=False):
    """整数校验：布尔、浮点小数、字符串一律不接受（字符串数字除外不接受）；不合法返回 None。"""
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    if zero_ok and v == 0:
        return 0
    if allowed is not None:
        return v if v in allowed else None
    return v if lo <= v <= hi else None


def clean_lightroom_path(v) -> str:
    """用户自选的 Lightroom 路径：空串表示自动探测；非空必须是本机真实存在的 Lightroom.exe，否则回退空串。"""
    if not isinstance(v, str) or not v.strip():
        return ""
    return valid_lightroom_path(v) or ""


def clean_export_field(key: str, v):
    """导出相关字段的单项校验：合法返回规范值，不合法返回 None（export_size 的合法值 0 也会返回 0，故用 is None 判断）。"""
    if key == "export_format":
        return v if isinstance(v, str) and v in EXPORT_FORMATS else None
    if key == "export_metadata":
        return v if isinstance(v, str) and v in EXPORT_METADATA else None
    if key == "export_size":
        return _clean_int(v, *EXPORT_EDGE_RANGE, zero_ok=True)
    if key == "export_quality":
        return _clean_int(v, *EXPORT_QUALITY_RANGE)
    if key == "export_bit_depth":
        return _clean_int(v, allowed=EXPORT_BIT_DEPTHS)
    if key == "export_last_folder":
        if not isinstance(v, str):
            return None
        v = v.strip()
        if not v:
            return ""
        return os.path.abspath(v) if validate_folder(v)["ok"] else None
    return None


EXPORT_FIELD_LABELS = {"export_last_folder": "导出文件夹", "export_format": "导出格式", "export_size": "导出大小",
                       "export_quality": "JPEG 质量", "export_bit_depth": "TIFF 位深", "export_metadata": "元数据"}


def sanitize(data) -> dict:
    """把读到的内容整理成合法设置：非法/缺失字段回退默认值，未知字段保留。"""
    out = dict(data) if isinstance(data, dict) else {}
    d = defaults()
    out["schema"] = SCHEMA_VERSION
    bf = out.get("base_folder")
    out["base_folder"] = bf.strip() if isinstance(bf, str) and bf.strip() and validate_folder(bf)["ok"] else d["base_folder"]
    pv = out.get("provider")
    out["provider"] = pv if isinstance(pv, str) and pv else d["provider"]
    out["confirm_default"] = out["confirm_default"] if isinstance(out.get("confirm_default"), bool) else d["confirm_default"]
    out["preview_edge"] = _clean_edge(out.get("preview_edge")) or d["preview_edge"]
    out["ai_use_notes"] = out["ai_use_notes"] if isinstance(out.get("ai_use_notes"), bool) else d["ai_use_notes"]
    out["auto_launch_lightroom"] = (out["auto_launch_lightroom"] if isinstance(out.get("auto_launch_lightroom"), bool)
                                    else d["auto_launch_lightroom"])
    out["lightroom_path"] = clean_lightroom_path(out.get("lightroom_path"))
    for k in EXPORT_FIELD_LABELS:
        c = clean_export_field(k, out.get(k))
        out[k] = d[k] if c is None else c
    return out


def restrict_to_current_user(path: Path) -> None:
    """尽力而为：仅当前用户可读写（Windows ACL），做法同 server/lightroom_mcp/bridge.py。"""
    user = os.environ.get("USERNAME")
    if os.name != "nt" or not user:
        return
    try:
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(M)"],
                       capture_output=True, check=False, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


class SettingsStore:
    def __init__(self, path: Path | None = None, restrict=restrict_to_current_user):
        self.path = Path(path) if path is not None else SETTINGS_FILE
        self._restrict = restrict
        self.data = self.load()

    def load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        return sanitize(raw)

    def save(self, data: dict) -> None:
        text = json.dumps(data, ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        self._restrict(tmp)
        os.replace(tmp, self.path)
        self.data = data

    def update(self, changes: dict, *, selectable=lambda pid: pid == DEFAULT_PROVIDER, create_missing: bool = False) -> dict:
        """校验并保存。返回 {"ok", "errors": {字段: 中文原因}, "needs_create": bool, "settings": 当前设置}。
        只处理 changes 里出现的字段；任一字段校验失败则整体不保存。"""
        new = dict(self.data)
        errors: dict[str, str] = {}
        needs_create = False
        if "base_folder" in changes:
            v = validate_folder(str(changes["base_folder"] or ""))
            if not v["ok"]:
                errors["base_folder"] = v["message"]
            elif not v["exists"]:
                if create_missing:
                    c = create_folder(v["path"])
                    if c["ok"]:
                        new["base_folder"] = c["path"]
                    else:
                        errors["base_folder"] = c["message"]
                else:
                    needs_create = True
                    errors["base_folder"] = "该文件夹尚不存在。"
            else:
                new["base_folder"] = v["path"]
        if "provider" in changes:
            pid = changes["provider"]
            if not isinstance(pid, str) or not selectable(pid):
                errors["provider"] = "该 AI 来源后续提供，暂不可选。"
            else:
                new["provider"] = pid
        if "confirm_default" in changes:
            if isinstance(changes["confirm_default"], bool):
                new["confirm_default"] = changes["confirm_default"]
            else:
                errors["confirm_default"] = "请选择开或关。"
        if "preview_edge" in changes:
            e = _clean_edge(changes["preview_edge"])
            if e is None:
                errors["preview_edge"] = "预览清晰度只能选择 " + "、".join(str(x) for x in EDGE_CHOICES) + " 之一。"
            else:
                new["preview_edge"] = e
        if "ai_use_notes" in changes:
            if isinstance(changes["ai_use_notes"], bool):
                new["ai_use_notes"] = changes["ai_use_notes"]
            else:
                errors["ai_use_notes"] = "请选择开或关。"
        if "auto_launch_lightroom" in changes:
            if isinstance(changes["auto_launch_lightroom"], bool):
                new["auto_launch_lightroom"] = changes["auto_launch_lightroom"]
            else:
                errors["auto_launch_lightroom"] = "请选择开或关。"
        if "lightroom_path" in changes:
            lp = changes["lightroom_path"]
            ok = valid_lightroom_path(lp) if isinstance(lp, str) else None
            if isinstance(lp, str) and not lp.strip():
                new["lightroom_path"] = ""
            elif ok:
                new["lightroom_path"] = ok
            else:
                errors["lightroom_path"] = "请选择名为 Lightroom.exe 的程序文件（本机磁盘上）。"
        for k, label in EXPORT_FIELD_LABELS.items():
            if k in changes:
                c = clean_export_field(k, changes[k])
                if c is None:
                    errors[k] = f"{label}的取值无效。"
                else:
                    new[k] = c
        if errors:
            return {"ok": False, "errors": errors, "needs_create": needs_create, "settings": dict(self.data)}
        try:
            self.save(new)
        except OSError as e:
            return {"ok": False, "errors": {"_": f"设置保存失败：{e.strerror or e}"}, "needs_create": False,
                    "settings": dict(self.data)}
        return {"ok": True, "errors": {}, "needs_create": False, "settings": dict(self.data)}
