# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""读取照片的拍摄时间（1.2.0）：纯 Python，只读文件头部，不依赖 Pillow 对 RAW 的支持。

从 EXIF 的 DateTimeOriginal（0x9003）读取，没有则退到 DateTimeDigitized（0x9004），再退到 IFD0 的 DateTime（0x0132）。
按文件内容识别格式（不看扩展名）：
  - JPEG：APP1 里的 Exif 段；
  - TIFF 系 RAW（ARW/CR2/NEF/NRW/DNG/ORF/RW2/TIF/TIFF）：直接按 TIFF 头解析，看 IFD0、ExifIFD（0x8769）、SubIFD（0x014A）；
  - RAF（富士）：里面内嵌一张 JPEG，按 JPEG 处理（只读前 256 KB）；
  - HEIC/HEIF/CR3（ISO-BMFF）：只在前 1 MB 里找 Exif 数据（HEIF 的 Exif 项、CR3 的 CMT 盒）；找不到返回 None；
  - PNG 等其他格式：None。
日期按相机本地时间原样使用，不做时区换算。任何异常（文件损坏、格式不对、权限）一律返回 None，绝不抛出。
"""
from __future__ import annotations

import re
import struct
from datetime import datetime

HEAD_BYTES = 256 * 1024                 # RAF / 一般“看头部”的读取量
BMFF_BYTES = 1024 * 1024                # HEIC/CR3 只看前 1 MB
JPEG_WALK_LIMIT = 4 * 1024 * 1024       # JPEG 段表最多走这么远（只读段头，跳过段内容）
MAX_IFDS = 16
MAX_ENTRIES = 2000
MIN_YEAR, MAX_YEAR = 1900, 2200

TAG_DT_ORIGINAL, TAG_DT_DIGITIZED, TAG_DATETIME = 0x9003, 0x9004, 0x0132
TAG_EXIF_IFD, TAG_SUB_IFDS = 0x8769, 0x014A
_PRIORITY = (TAG_DT_ORIGINAL, TAG_DT_DIGITIZED, TAG_DATETIME)
_TIFF_MAGICS = (42, 0x4F52, 0x5352, 0x55)       # 标准 TIFF、ORF（两种）、RW2
_DATE_RE = re.compile(rb"^\s*(\d{4})[:\-/.](\d{2})[:\-/.](\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?")
_CANON_UUID = bytes.fromhex("85c0b687820f11e08111f4ce462b6a48")


def parse_exif_datetime(raw) -> datetime | None:
    """EXIF 日期文本（"2026:11:14 09:30:05"）-> datetime；全零、月日越界、年份不合理都判无效。时间部分空白时按 00:00:00。"""
    if isinstance(raw, str):
        raw = raw.encode("latin-1", "replace")
    if not isinstance(raw, (bytes, bytearray)):
        return None
    m = _DATE_RE.match(bytes(raw).split(b"\x00", 1)[0])
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4) or 0)
    mm = int(m.group(5) or 0)
    ss = int(m.group(6) or 0)
    if not MIN_YEAR <= y <= MAX_YEAR:
        return None
    try:
        return datetime(y, mo, d, hh, mm, ss)
    except ValueError:
        return None


# ---------------------------------------------------------------- TIFF / EXIF
class _Buf:
    """对 bytes 或文件的随机读取：read(offset, n) 越界返回更短的字节串。"""

    def __init__(self, data: bytes | None = None, fh=None, base: int = 0, size: int | None = None):
        self.data, self.fh, self.base, self.size = data, fh, base, size

    def read(self, off: int, n: int) -> bytes:
        if off < 0 or n < 0 or n > 1 << 20:
            return b""
        if self.data is not None:
            return self.data[off:off + n]
        if self.size is not None and self.base + off >= self.size:
            return b""
        self.fh.seek(self.base + off)
        return self.fh.read(n)


_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 13: 4}


def _tiff_dates(buf: _Buf) -> dict[int, datetime]:
    """遍历 IFD0、ExifIFD、SubIFD，返回 {标签: 有效的 datetime}。结构不对时返回已读到的部分。"""
    head = buf.read(0, 8)
    if len(head) < 8 or head[:2] not in (b"II", b"MM"):
        return {}
    e = "<" if head[:2] == b"II" else ">"
    if struct.unpack(e + "H", head[2:4])[0] not in _TIFF_MAGICS:
        return {}
    found: dict[int, datetime] = {}
    todo = [(struct.unpack(e + "I", head[4:8])[0], True)]          # (IFD 偏移, 是否 IFD0/SubIFD：看 0x0132)
    seen: set[int] = set()
    while todo and len(seen) < MAX_IFDS:
        off, top = todo.pop(0)
        if off in seen or off < 8:
            continue
        seen.add(off)
        cnt_raw = buf.read(off, 2)
        if len(cnt_raw) < 2:
            continue
        count = min(struct.unpack(e + "H", cnt_raw)[0], MAX_ENTRIES)
        table = buf.read(off + 2, count * 12)
        for i in range(len(table) // 12):
            tag, typ, n = struct.unpack(e + "HHI", table[i * 12:i * 12 + 8])
            val = table[i * 12 + 8:i * 12 + 12]
            if tag in _PRIORITY and typ == 2 and 0 < n <= 64:
                if tag == TAG_DATETIME and not top:
                    continue
                raw = val[:n] if n <= 4 else buf.read(struct.unpack(e + "I", val)[0], n)
                dt = parse_exif_datetime(raw)
                if dt is not None and tag not in found:
                    found[tag] = dt
            elif tag == TAG_EXIF_IFD and typ in (4, 13) and n == 1:
                todo.append((struct.unpack(e + "I", val)[0], False))
            elif tag == TAG_SUB_IFDS and typ in (4, 13) and 0 < n <= 8:
                offs = val if n == 1 else buf.read(struct.unpack(e + "I", val)[0], 4 * n)
                for j in range(min(n, len(offs) // 4)):
                    todo.append((struct.unpack(e + "I", offs[j * 4:j * 4 + 4])[0], True))
        if TAG_DT_ORIGINAL in found:
            break
    return found


def _pick(found: dict[int, datetime]) -> datetime | None:
    for tag in _PRIORITY:
        if tag in found:
            return found[tag]
    return None


def _from_tiff_bytes(data: bytes) -> datetime | None:
    return _pick(_tiff_dates(_Buf(data=data)))


# ---------------------------------------------------------------- JPEG
def _jpeg_date(fh, start: int, size: int) -> datetime | None:
    """从 start 处的 JPEG（FFD8）里找 APP1 Exif 段。只读段头；段内容只读 Exif 那一段。"""
    pos = start + 2
    limit = min(size, start + JPEG_WALK_LIMIT)
    while pos + 4 <= limit:
        fh.seek(pos)
        hdr = fh.read(4)
        if len(hdr) < 4 or hdr[0] != 0xFF:
            return None
        marker = hdr[1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if marker in (0xD9, 0xDA):                      # 图像结束 / 图像数据开始：不会再有 Exif
            return None
        seg_len = struct.unpack(">H", hdr[2:4])[0]
        if seg_len < 2:
            return None
        if marker == 0xE1 and seg_len >= 14:
            body = fh.read(min(seg_len - 2, 65533))
            if body[:6] == b"Exif\x00\x00":
                dt = _from_tiff_bytes(body[6:])
                if dt is not None:
                    return dt
        pos += 2 + seg_len
    return None


# ---------------------------------------------------------------- ISO-BMFF（HEIC/HEIF/CR3）
def _boxes(data: bytes, start: int, end: int):
    """产生 (类型, 内容起点, 内容终点)。盒大小超出缓冲区时截到缓冲区末尾（只读了前 1 MB）。"""
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack(">I4s", data[pos:pos + 8])
        hdr = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr:
            return
        yield typ, pos + hdr, min(pos + size, end)
        pos += size


def _walk_bmff(data: bytes, start: int, end: int, depth: int = 0):
    """递归产生所有盒（容器：moov/trak/meta/iprp/uuid(Canon)）。"""
    if depth > 6:
        return
    for typ, a, b in _boxes(data, start, end):
        yield typ, a, b
        if typ in (b"moov", b"trak", b"iprp", b"ipco", b"mdia", b"minf", b"stbl"):
            yield from _walk_bmff(data, a, b, depth + 1)
        elif typ == b"iinf":
            skip = 6 if data[a] == 0 else 8                        # FullBox 4 字节 + 项数（版本 0 为 2 字节，否则 4 字节）
            yield from _walk_bmff(data, a + skip, b, depth + 1)
        elif typ == b"meta":
            yield from _walk_bmff(data, a + 4, b, depth + 1)        # meta 是 FullBox：先跳过 4 字节版本/标志
        elif typ == b"uuid" and data[a:a + 16] == _CANON_UUID:
            yield from _walk_bmff(data, a + 16, b, depth + 1)


def _heif_exif_item(data: bytes) -> datetime | None:
    """HEIF：iinf 里找类型为 Exif 的项，再用 iloc 取它的数据位置。"""
    item_id = None
    iloc = None
    for typ, a, b in _walk_bmff(data, 0, len(data)):
        if typ == b"infe" and item_id is None:
            ver = data[a]
            if ver >= 2 and b - a >= 12:
                iid_len = 2 if ver == 2 else 4
                iid = int.from_bytes(data[a + 4:a + 4 + iid_len], "big")
                if data[a + 4 + iid_len + 2:a + 4 + iid_len + 6] == b"Exif":
                    item_id = iid
        elif typ == b"iloc":
            iloc = (a, b)
    if item_id is None or iloc is None:
        return None
    a, b = iloc
    ver = data[a]
    sizes = data[a + 4]
    off_size, len_size = sizes >> 4, sizes & 15
    base_size, idx_size = data[a + 5] >> 4, (data[a + 5] & 15) if ver in (1, 2) else 0
    p = a + 6
    if ver < 2:
        n_items, p = int.from_bytes(data[p:p + 2], "big"), p + 2
    else:
        n_items, p = int.from_bytes(data[p:p + 4], "big"), p + 4
    for _ in range(min(n_items, 4096)):
        if ver < 2:
            iid, p = int.from_bytes(data[p:p + 2], "big"), p + 2
        else:
            iid, p = int.from_bytes(data[p:p + 4], "big"), p + 4
        if ver in (1, 2):
            p += 2                                                # construction_method
        p += 2                                                    # data_reference_index
        base = int.from_bytes(data[p:p + base_size], "big") if base_size else 0
        p += base_size
        ext_n, p = int.from_bytes(data[p:p + 2], "big"), p + 2
        first = None
        for _e in range(min(ext_n, 64)):
            p += idx_size
            eo = int.from_bytes(data[p:p + off_size], "big") if off_size else 0
            p += off_size
            el = int.from_bytes(data[p:p + len_size], "big") if len_size else 0
            p += len_size
            if first is None:
                first = (eo, el)
        if iid == item_id and first is not None:
            off, ln = base + first[0], first[1]
            payload = data[off:off + min(ln, 1 << 20)]
            if len(payload) < 8:
                return None
            skip = 4 + struct.unpack(">I", payload[:4])[0]       # Exif 项开头：到 TIFF 头的偏移
            return _from_tiff_bytes(payload[skip:])
    return None


def _bmff_date(data: bytes) -> datetime | None:
    dt = None
    try:
        dt = _heif_exif_item(data)
    except (IndexError, struct.error, ValueError):
        dt = None
    if dt is not None:
        return dt
    # CR3：moov/uuid 下的 CMT1（IFD0）、CMT2（ExifIFD）本身就是 TIFF 数据
    found: dict[int, datetime] = {}
    for typ, a, b in _walk_bmff(data, 0, len(data)):
        if typ in (b"CMT1", b"CMT2", b"CMT3"):
            found.update({k: v for k, v in _tiff_dates(_Buf(data=data[a:b])).items() if k not in found})
    dt = _pick(found)
    if dt is not None:
        return dt
    # 兜底：找 "Exif\0\0" 后面紧跟 TIFF 头的位置
    i = 0
    for _ in range(8):
        i = data.find(b"Exif\x00\x00", i)
        if i < 0:
            break
        dt = _from_tiff_bytes(data[i + 6:i + 6 + 65536])
        if dt is not None:
            return dt
        i += 6
    return None


# ---------------------------------------------------------------- 入口
def capture_datetime(path) -> datetime | None:
    """拍摄时间（相机本地时间，无时区）；读不到、格式不认识或文件有问题返回 None，不抛异常。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
            if len(head) < 8:
                return None
            fh.seek(0, 2)
            size = fh.tell()
            if head[:2] == b"\xff\xd8":
                return _jpeg_date(fh, 0, size)
            if head[:2] in (b"II", b"MM") and struct.unpack("<H" if head[:2] == b"II" else ">H", head[2:4])[0] in _TIFF_MAGICS:
                return _pick(_tiff_dates(_Buf(fh=fh, size=size)))
            if head.startswith(b"FUJIFILMCCD-RAW"):
                fh.seek(0)
                data = fh.read(HEAD_BYTES)
                off = struct.unpack(">I", data[84:88])[0] if len(data) >= 88 else 0
                if not (0 < off < len(data) - 2 and data[off:off + 2] == b"\xff\xd8"):
                    off = data.find(b"\xff\xd8\xff")
                if off < 0:
                    return None
                return _jpeg_date(fh, off, min(size, HEAD_BYTES))
            if head[4:8] == b"ftyp":
                fh.seek(0)
                return _bmff_date(fh.read(BMFF_BYTES))
            return None                                              # PNG 及其他
    except Exception:                                                # noqa: BLE001 - 契约：任何问题都返回 None
        return None


def date_folder(path, mtime) -> str:
    """照片应放入的日期文件夹（相对库）："yyyy/yyyy-mm-dd"。取不到拍摄时间用文件修改时间（本地时间）；都不可用给 1970。"""
    dt = capture_datetime(path)
    if dt is None:
        try:
            dt = datetime.fromtimestamp(float(mtime))
        except (OSError, OverflowError, ValueError, TypeError):
            dt = datetime(1970, 1, 1)
    return f"{dt.year:04d}/{dt:%Y-%m-%d}"

