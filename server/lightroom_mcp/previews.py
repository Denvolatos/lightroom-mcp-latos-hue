"""Preview file handling and picture statistics (Lightroom's SDK has no histogram API, so we compute it)."""
from __future__ import annotations

import time
from pathlib import Path

import colorsys
import io

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

from . import config

# Rule-of-thumb thresholds (heuristics, not measured standards).
DARK_MEAN = 85
BRIGHT_MEAN = 170
CLIP_HIGHLIGHT_PERCENT = 2.0
CRUSHED_SHADOW_PERCENT = 5.0
CAST_PERCENT = 6.0
COMPARISON_KEYS = ("mean_brightness_0_255", "highlight_clipped_percent",
                   "shadow_crushed_percent", "warm_cool_index_percent")


def compare_stats(before: dict, after: dict) -> dict:
    """Numeric after-minus-before changes for two rendered previews."""
    return {key: round(after[key] - before[key], 2) for key in COMPARISON_KEYS}


# ---- where in the picture: a 3x3 grid and the sky-like blue ---------------------------------------------------------
_HUE_NAMES = ((20, "红"), (45, "橙"), (70, "黄"), (160, "绿"), (190, "青"), (250, "蓝"), (290, "紫"), (340, "洋红"), (361, "红"))


def hue_name(degrees: float) -> str:
    for upper, name in _HUE_NAMES:
        if degrees < upper:
            return name
    return "红"


def _regions(small) -> list[dict]:
    w, h = small.size
    cells = []
    for row in range(3):
        for col in range(3):
            box = (col * w // 3, row * h // 3, (col + 1) * w // 3, (row + 1) * h // 3)
            r, g, b = ImageStat.Stat(small.crop(box)).mean[:3]
            hh, ss, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            cells.append({
                "row": row, "col": col, "brightness": round(0.299 * r + 0.587 * g + 0.114 * b, 1),
                "mean_rgb": [round(r), round(g), round(b)], "hue_deg": round(hh * 360), "hue_name": hue_name(hh * 360),
                "saturation_percent": round(ss * 100, 1),
            })
    return cells


def _sky_like(small) -> dict | None:
    """Pixels that are cyan-to-blue (170 to 260 degrees), saturated (> 20%) and not dark: usually the sky."""
    hue, sat, val = small.convert("HSV").split()
    mask = ImageChops.multiply(
        ImageChops.multiply(hue.point(lambda x: 255 if 121 <= x <= 184 else 0), sat.point(lambda x: 255 if x > 51 else 0)),
        val.point(lambda x: 255 if x > 64 else 0),
    )
    count = mask.histogram()[255]
    total = small.size[0] * small.size[1]
    if count < total * 0.005:
        return None
    h_mean = ImageStat.Stat(hue, mask).mean[0] * 360 / 255
    return {
        "share_percent": round(count * 100.0 / total, 1),
        "mean_hue_deg": round(h_mean), "mean_hue_name": hue_name(h_mean),
        "mean_saturation_percent": round(ImageStat.Stat(sat, mask).mean[0] * 100 / 255, 1),
        "mean_brightness": round(ImageStat.Stat(val, mask).mean[0], 1),
    }


def analyze(path: Path) -> dict:
    """Return brightness / clipping / colour-balance numbers for a JPEG, plus short Chinese notes."""
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        width, height = rgb.size
        gray = rgb.convert("L")
        hist = gray.histogram()
        total = float(sum(hist)) or 1.0
        mean = sum(i * c for i, c in enumerate(hist)) / total
        highlights = sum(hist[250:]) * 100.0 / total
        shadows = sum(hist[:6]) * 100.0 / total
        bins = [round(sum(hist[i * 16 : (i + 1) * 16]) * 100.0 / total, 1) for i in range(16)]
        r_hist, g_hist, b_hist = rgb.histogram()[:256], rgb.histogram()[256:512], rgb.histogram()[512:768]

        def channel_mean(h):
            return sum(i * c for i, c in enumerate(h)) / total

        r, g, b = channel_mean(r_hist), channel_mean(g_hist), channel_mean(b_hist)
        small = rgb.copy()
        small.thumbnail((512, 512))
        regions = _regions(small)
        sky = _sky_like(small)

    cast = (r - b) * 100.0 / max(mean, 1.0)
    notes: list[str] = []
    if mean < DARK_MEAN:
        notes.append("整体偏暗")
    elif mean > BRIGHT_MEAN:
        notes.append("整体偏亮")
    else:
        notes.append("整体亮度适中")
    if highlights > CLIP_HIGHLIGHT_PERCENT:
        notes.append(f"高光有约 {highlights:.1f}% 的像素接近纯白，可能过曝")
    if shadows > CRUSHED_SHADOW_PERCENT:
        notes.append(f"暗部有约 {shadows:.1f}% 的像素接近纯黑，细节可能丢失")
    if cast > CAST_PERCENT:
        notes.append("色调偏暖（红多于蓝）")
    elif cast < -CAST_PERCENT:
        notes.append("色调偏冷（蓝多于红）")
    if sky and sky["share_percent"] >= 8:
        notes.append(f"疑似天空的蓝色区域约占 {sky['share_percent']:.0f}%，平均色相约 {sky['mean_hue_deg']}°（{sky['mean_hue_name']}），"
                     f"饱和度 {sky['mean_saturation_percent']:.0f}%")
    return {
        "width": width,
        "height": height,
        "mean_brightness_0_255": round(mean, 1),
        "highlight_clipped_percent": round(highlights, 2),
        "shadow_crushed_percent": round(shadows, 2),
        "brightness_histogram_16_bins_percent": bins,
        "channel_means": {"r": round(r, 1), "g": round(g, 1), "b": round(b, 1)},
        "warm_cool_index_percent": round(cast, 1),
        "notes_heuristic": notes,
        "regions_3x3": regions,          # row 0 is the top, col 0 is the left; hue of a grey cell means little
        "sky_like_blue": sky,            # None when there is no such blue
    }


def compose_side_by_side(images: list[bytes], labels: list[str], height: int = 360) -> bytes:
    """Put JPEGs next to each other, each with a big letter in its corner, and return one JPEG."""
    if not images or len(images) != len(labels):
        raise ValueError("images and labels must be non-empty and the same length")
    tiles = []
    for data in images:
        with Image.open(io.BytesIO(data)) as im:
            rgb = im.convert("RGB")
            tiles.append(rgb.resize((max(1, round(rgb.width * height / rgb.height)), height)))
    gap = 8
    canvas = Image.new("RGB", (sum(t.width for t in tiles) + gap * (len(tiles) - 1), height), (24, 24, 24))
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:  # old Pillow: no size argument, the small default font is used
        font = ImageFont.load_default()
    x = 0
    for tile, label in zip(tiles, labels):
        canvas.paste(tile, (x, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((x + 6, 6, x + 6 + 14 * len(label) + 18, 42), fill=(0, 0, 0))
        draw.text((x + 14, 8), label, fill=(255, 255, 255), font=font)
        x += tile.width + gap
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=88)
    return out.getvalue()


def clean_old(directory: Path = config.PREVIEW_DIR, max_age: float = config.PREVIEW_MAX_AGE_SECONDS) -> int:
    """Delete preview files older than ``max_age`` seconds. Returns how many were removed."""
    removed = 0
    if not directory.is_dir():
        return removed
    limit = time.time() - max_age
    for f in directory.glob("*.jpg"):
        try:
            if f.stat().st_mtime < limit:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed
