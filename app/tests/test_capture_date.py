# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""capture_date：用手工拼出的小二进制样本测拍摄时间读取（不依赖真实照片）。"""
import os
import struct
from datetime import datetime

import pytest

import capture_date as cd

D = datetime(2026, 11, 14, 9, 30, 5)


def ascii_val(text: str) -> bytes:
    return text.encode("ascii") + b"\x00"


def build_tiff(entries0, exif_entries=None, sub_entries=None, endian="<", magic=42, pad=0) -> bytes:
    """entries: [(tag, type, bytes值)]。IFD0 → (可选) ExifIFD、SubIFD。值超过 4 字节放在 IFD 后面的数据区。"""
    e = endian
    parts = {}           # 名称 -> 条目列表
    parts["ifd0"] = list(entries0)
    layout = []          # (name, entries)
    if exif_entries is not None:
        parts["ifd0"].append((0x8769, 4, "PTR:exif"))
    if sub_entries is not None:
        parts["ifd0"].append((0x014A, 4, "PTR:sub"))
    order = [("ifd0", parts["ifd0"])]
    if exif_entries is not None:
        order.append(("exif", list(exif_entries)))
    if sub_entries is not None:
        order.append(("sub", list(sub_entries)))
    # 先算每个 IFD 的偏移
    offs, cur = {}, 8 + pad
    for name, ents in order:
        offs[name] = cur
        cur += 2 + 12 * len(ents) + 4
    data_area = bytearray()
    out = bytearray(b"II" if e == "<" else b"MM")
    out += struct.pack(e + "H", magic) + struct.pack(e + "I", offs["ifd0"])
    out += b"\x00" * pad
    body = bytearray()
    for name, ents in order:
        body += struct.pack(e + "H", len(ents))
        for tag, typ, val in ents:
            if isinstance(val, str) and val.startswith("PTR:"):
                body += struct.pack(e + "HHII", tag, typ, 1, offs[val[4:]])
                continue
            if typ == 2:
                n = len(val)
            else:
                n = 1
            if len(val) <= 4:
                body += struct.pack(e + "HHI", tag, typ, n) + val.ljust(4, b"\x00")
            else:
                ptr = cur + len(data_area)
                body += struct.pack(e + "HHII", tag, typ, n, ptr)
                data_area += val
        body += struct.pack(e + "I", 0)
    return bytes(out + body + data_area)


def tiff_with(text, tag=0x9003, endian="<", where="exif", **kw):
    v = (tag, 2, ascii_val(text))
    if where == "exif":
        return build_tiff([(0x0100, 3, struct.pack(endian + "H", 5))], exif_entries=[v], endian=endian, **kw)
    if where == "ifd0":
        return build_tiff([v], endian=endian, **kw)
    return build_tiff([(0x0100, 3, struct.pack(endian + "H", 5))], sub_entries=[v], endian=endian, **kw)


def jpeg_with(tiff: bytes, extra_app: bool = True) -> bytes:
    out = b"\xff\xd8"
    if extra_app:
        out += b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    body = b"Exif\x00\x00" + tiff
    out += b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body
    out += b"\xff\xdb" + struct.pack(">H", 4) + b"\x00\x00" + b"\xff\xda\x00\x02" + b"\x00" * 10 + b"\xff\xd9"
    return out


def write(tmp_path, name, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return p


# ---------------------------------------------------------------- 解析
@pytest.mark.parametrize("raw,expect", [
    (b"2026:11:14 09:30:05\x00", D),
    ("2026:11:14 09:30:05", D),
    (b"2026-11-14T09:30:05", D),
    (b"2026:11:14 09:30", datetime(2026, 11, 14, 9, 30)),
    (b"2026:11:14    :  :  ", datetime(2026, 11, 14)),
    (b"0000:00:00 00:00:00\x00", None),
    (b"2026:00:10 00:00:00", None),
    (b"2026:13:10 00:00:00", None),
    (b"2026:02:30 10:00:00", None),
    (b"2026:11:14 25:00:00", None),
    (b"1800:01:01 00:00:00", None),
    (b"    :  :     :  :  ", None),
    (b"", None),
    (b"garbage", None),
    (None, None),
    (123, None),
])
def test_parse_exif_datetime(raw, expect):
    assert cd.parse_exif_datetime(raw) == expect


# ---------------------------------------------------------------- JPEG
@pytest.mark.parametrize("endian", ["<", ">"])
def test_jpeg_exif_datetime_original(tmp_path, endian):
    p = write(tmp_path, "a.jpg", jpeg_with(tiff_with("2026:11:14 09:30:05", endian=endian)))
    assert cd.capture_datetime(p) == D
    assert cd.capture_datetime(str(p)) == D


def test_jpeg_without_extra_app_segment(tmp_path):
    p = write(tmp_path, "a.jpg", jpeg_with(tiff_with("2026:11:14 09:30:05"), extra_app=False))
    assert cd.capture_datetime(p) == D


def test_jpeg_falls_back_to_digitized_then_ifd0_datetime(tmp_path):
    dig = write(tmp_path, "d.jpg", jpeg_with(tiff_with("2025:05:06 07:08:09", tag=0x9004)))
    assert cd.capture_datetime(dig) == datetime(2025, 5, 6, 7, 8, 9)
    top = write(tmp_path, "t.jpg", jpeg_with(tiff_with("2024:01:02 03:04:05", tag=0x0132, where="ifd0")))
    assert cd.capture_datetime(top) == datetime(2024, 1, 2, 3, 4, 5)


def test_original_wins_over_ifd0_datetime(tmp_path):
    t = build_tiff([(0x0132, 2, ascii_val("2020:01:01 00:00:00"))],
                   exif_entries=[(0x9003, 2, ascii_val("2026:11:14 09:30:05"))])
    assert cd.capture_datetime(write(tmp_path, "a.jpg", jpeg_with(t))) == D


def test_invalid_original_falls_back_to_next_valid_tag(tmp_path):
    t = build_tiff([(0x0132, 2, ascii_val("2020:01:01 00:00:00"))],
                   exif_entries=[(0x9003, 2, ascii_val("0000:00:00 00:00:00"))])
    assert cd.capture_datetime(write(tmp_path, "a.jpg", jpeg_with(t))) == datetime(2020, 1, 1)


def test_jpeg_year_zero_is_none(tmp_path):
    p = write(tmp_path, "z.jpg", jpeg_with(tiff_with("0000:00:00 00:00:00")))
    assert cd.capture_datetime(p) is None


def test_jpeg_without_exif_or_with_exif_after_scan_start(tmp_path):
    plain = b"\xff\xd8\xff\xe0\x00\x04\x00\x00\xff\xda\x00\x02" + b"\x00" * 40 + b"\xff\xd9"
    assert cd.capture_datetime(write(tmp_path, "p.jpg", plain)) is None


def test_jpeg_truncated_in_the_middle_of_segment(tmp_path):
    data = jpeg_with(tiff_with("2026:11:14 09:30:05"))
    p = write(tmp_path, "cut.jpg", data[:30])
    assert cd.capture_datetime(p) is None


# ---------------------------------------------------------------- TIFF 系
@pytest.mark.parametrize("endian", ["<", ">"])
@pytest.mark.parametrize("ext", ["arw", "cr2", "nef", "nrw", "dng", "tif", "tiff"])
def test_tiff_family_exif_ifd(tmp_path, endian, ext):
    p = write(tmp_path, f"x.{ext}", tiff_with("2026:11:14 09:30:05", endian=endian))
    assert cd.capture_datetime(p) == D


@pytest.mark.parametrize("magic,name", [(0x4F52, "x.orf"), (0x5352, "y.orf"), (0x55, "z.rw2")])
def test_orf_and_rw2_magic(tmp_path, magic, name):
    p = write(tmp_path, name, tiff_with("2026:11:14 09:30:05", magic=magic))
    assert cd.capture_datetime(p) == D


def test_tiff_ifd0_datetime_only(tmp_path):
    p = write(tmp_path, "a.tif", tiff_with("2023:03:04 05:06:07", tag=0x0132, where="ifd0"))
    assert cd.capture_datetime(p) == datetime(2023, 3, 4, 5, 6, 7)


def test_tiff_subifd_is_consulted(tmp_path):
    p = write(tmp_path, "a.dng", tiff_with("2022:02:03 04:05:06", where="sub"))
    assert cd.capture_datetime(p) == datetime(2022, 2, 3, 4, 5, 6)


def test_tiff_with_padding_before_ifd(tmp_path):
    p = write(tmp_path, "a.arw", tiff_with("2026:11:14 09:30:05", pad=100))
    assert cd.capture_datetime(p) == D


def test_tiff_ifd_loop_does_not_hang(tmp_path):
    # IFD0 指向自己，下一 IFD 也指回自己
    data = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 0) + struct.pack("<I", 8)
    assert cd.capture_datetime(write(tmp_path, "loop.tif", data)) is None


def test_tiff_wild_offsets_are_harmless(tmp_path):
    data = b"MM\x00*" + struct.pack(">I", 0xFFFFFF00) + b"\x00" * 16
    assert cd.capture_datetime(write(tmp_path, "w.tif", data)) is None
    bad_value = build_tiff([], exif_entries=[(0x9003, 2, ascii_val("2026:11:14 09:30:05"))])
    broken = bytearray(bad_value)
    broken[-20:] = b"\xff" * 20                                       # 破坏数据区
    cd.capture_datetime(write(tmp_path, "b.tif", bytes(broken)))     # 只要不抛异常


# ---------------------------------------------------------------- RAF
def raf_with(jpeg: bytes, header_offset=True, junk=200) -> bytes:
    head = bytearray(b"FUJIFILMCCD-RAW 0201FF383501" + b"\x00" * 120)
    off = 160 + junk
    if header_offset:
        head[84:88] = struct.pack(">I", off)
    return bytes(head) + b"\x00" * junk + jpeg


@pytest.mark.parametrize("header_offset", [True, False])
def test_raf_embedded_jpeg(tmp_path, header_offset):
    jpeg = jpeg_with(tiff_with("2026:11:14 09:30:05", endian=">"))
    p = write(tmp_path, "a.raf", raf_with(jpeg, header_offset))
    assert cd.capture_datetime(p) == D


def test_raf_without_jpeg_is_none(tmp_path):
    assert cd.capture_datetime(write(tmp_path, "a.raf", b"FUJIFILMCCD-RAW 0201" + b"\x00" * 300)) is None


# ---------------------------------------------------------------- HEIC / CR3
def box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), typ) + payload


def heic_with(tiff: bytes, with_item_tables=True) -> bytes:
    ftyp = box(b"ftyp", b"heic\x00\x00\x00\x00mif1heic")
    exif_payload = struct.pack(">I", 6) + b"Exif\x00\x00" + tiff
    infe = box(b"infe", b"\x02\x00\x00\x00" + struct.pack(">H", 7) + b"\x00\x00" + b"Exif" + b"\x00")
    iinf = box(b"iinf", b"\x00\x00\x00\x00" + struct.pack(">H", 1) + infe)
    # 先放一个占位 iloc 算出 mdat 偏移
    def iloc_with(offset):
        item = (struct.pack(">H", 7) + struct.pack(">H", 0) + struct.pack(">H", 1)
                + struct.pack(">I", offset) + struct.pack(">I", len(exif_payload)))
        return box(b"iloc", b"\x00\x00\x00\x00" + bytes([0x44, 0x00]) + struct.pack(">H", 1) + item)
    meta_fn = lambda off: box(b"meta", b"\x00\x00\x00\x00" + iinf + iloc_with(off))
    if not with_item_tables:
        return ftyp + box(b"meta", b"\x00\x00\x00\x00") + box(b"mdat", exif_payload)
    off = len(ftyp) + len(meta_fn(0)) + 8
    return ftyp + meta_fn(off) + box(b"mdat", exif_payload)


def test_heic_exif_item(tmp_path):
    p = write(tmp_path, "a.heic", heic_with(tiff_with("2026:11:14 09:30:05", endian=">")))
    assert cd.capture_datetime(p) == D


def test_heic_exif_item_found_through_iinf_and_iloc_not_the_fallback():
    data = heic_with(tiff_with("2026:11:14 09:30:05", endian=">"))
    assert cd._heif_exif_item(data) == D


def test_heic_item_tables_missing_falls_back_to_exif_marker(tmp_path):
    p = write(tmp_path, "a.heif", heic_with(tiff_with("2026:11:14 09:30:05"), with_item_tables=False))
    assert cd.capture_datetime(p) == D


def test_heic_without_exif_is_none(tmp_path):
    data = box(b"ftyp", b"heic\x00\x00\x00\x00mif1heic") + box(b"meta", b"\x00\x00\x00\x00") + box(b"mdat", b"\x00" * 64)
    assert cd.capture_datetime(write(tmp_path, "n.heic", data)) is None


def test_cr3_cmt_boxes(tmp_path):
    exif_tiff = build_tiff([(0x9003, 2, ascii_val("2026:11:14 09:30:05"))])        # CMT2：IFD0 就是 ExifIFD
    cmt1 = build_tiff([(0x0132, 2, ascii_val("2020:01:01 00:00:00"))])
    uuid = box(b"uuid", bytes.fromhex("85c0b687820f11e08111f4ce462b6a48") + box(b"CMT1", cmt1) + box(b"CMT2", exif_tiff))
    data = box(b"ftyp", b"crx \x00\x00\x00\x01crx isom") + box(b"moov", uuid)
    assert cd.capture_datetime(write(tmp_path, "a.cr3", data)) == D


def test_bmff_garbage_boxes_do_not_crash(tmp_path):
    data = box(b"ftyp", b"heic") + b"\xff\xff\xff\xff" + b"meta" + os.urandom(40)
    assert cd.capture_datetime(write(tmp_path, "g.heic", data)) is None


# ---------------------------------------------------------------- 其他
def test_png_empty_short_missing_and_directory(tmp_path):
    assert cd.capture_datetime(write(tmp_path, "a.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)) is None
    assert cd.capture_datetime(write(tmp_path, "empty.jpg", b"")) is None
    assert cd.capture_datetime(write(tmp_path, "tiny.arw", b"II")) is None
    assert cd.capture_datetime(tmp_path / "nope.jpg") is None
    assert cd.capture_datetime(tmp_path) is None
    assert cd.capture_datetime(None) is None


def test_format_detected_by_content_not_extension(tmp_path):
    p = write(tmp_path, "renamed.dat", jpeg_with(tiff_with("2026:11:14 09:30:05")))
    assert cd.capture_datetime(p) == D


@pytest.mark.parametrize("seed", range(20))
def test_random_garbage_with_valid_magic_never_raises(tmp_path, seed):
    import random
    rnd = random.Random(seed)
    base = [jpeg_with(tiff_with("2026:11:14 09:30:05")), tiff_with("2026:11:14 09:30:05", endian=">"),
            heic_with(tiff_with("2026:11:14 09:30:05")), raf_with(jpeg_with(tiff_with("2026:11:14 09:30:05")))][seed % 4]
    data = bytearray(base)
    for _ in range(12):
        data[rnd.randrange(len(data))] = rnd.randrange(256)
    cd.capture_datetime(write(tmp_path, f"fuzz{seed}.bin", bytes(data)))          # 只要不抛


def test_only_the_head_of_a_big_file_is_read(tmp_path):
    p = write(tmp_path, "big.arw", tiff_with("2026:11:14 09:30:05") + b"\x00" * (3 * 1024 * 1024))
    assert cd.capture_datetime(p) == D


# ---------------------------------------------------------------- date_folder
def test_date_folder_uses_capture_date(tmp_path):
    p = write(tmp_path, "a.jpg", jpeg_with(tiff_with("2026:11:14 23:59:59")))
    assert cd.date_folder(p, 0) == "2026/2026-11-14"


def test_date_folder_falls_back_to_mtime_local_time(tmp_path):
    p = write(tmp_path, "a.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    mt = datetime(2025, 3, 9, 12, 0, 0).timestamp()
    assert cd.date_folder(p, mt) == "2025/2025-03-09"


def test_date_folder_invalid_exif_year_uses_mtime(tmp_path):
    p = write(tmp_path, "a.jpg", jpeg_with(tiff_with("0000:00:00 00:00:00")))
    mt = datetime(2021, 12, 31, 8, 0, 0).timestamp()
    assert cd.date_folder(p, mt) == "2021/2021-12-31"


@pytest.mark.parametrize("bad", [None, float("nan"), 1e30, -1e30, "x"])
def test_date_folder_survives_bad_mtime(tmp_path, bad):
    p = write(tmp_path, "a.png", b"\x89PNG\r\n\x1a\n")
    out = cd.date_folder(p, bad)
    assert len(out) == 15 and out[4] == "/" and out[:4] == out[5:9]
