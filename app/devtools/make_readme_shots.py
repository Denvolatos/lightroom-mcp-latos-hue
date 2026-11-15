# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""生成 README 用的界面示例截图（开发工具，不属于 pytest，也不会被打进安装包）。

做法：用 app/tests/ui_common.py 里的假 pywebview.api，加载真实的前端页面（app/web），喂示例数据，
用无头 Edge 截图。不启动软件窗口、不启动 Lightroom、不碰任何真实照片目录、不调用模型。

示例照片：全部由本脚本用代码现场画出（渐变天空、云、远山、太阳、草地/水面），不是真实照片、不是网上的图，也不是任何人的作品。
同一个场景有“改前”和“改后”两版：改后天空更蓝更通透、云的亮部被压住、暗部提亮、饱和度略高，
与示例的“本次调整”表（高光 0→-35、阴影 0→+28、自然饱和度 0→+12、对比度 0→+8）大体吻合。
文件名（DSC00001.ARW 等）、相机和拍摄参数、路径（D:\\示例\\照片库）、对话内容都是示例值，不含个人信息。

用法（在 PowerShell 里运行；需要 numpy 和 Pillow，例如 conda base 环境）：
    python app/devtools/make_readme_shots.py <输出目录>
输出：readme_main.png  readme_pick.png  readme_themes.png  readme_settings.png
（中间的原始截图和改前/改后示例图放在系统临时目录里，路径会打印出来，可以删除。）
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from ui_common import FAKE_API, HELPERS, WEB, Server, edge  # noqa: E402
from web_source import inject_stub  # noqa: E402

W, H = 1500, 1000          # 示例照片的像素尺寸（3:2）
MAIN = 7                   # 主界面里被选中的那张（0 起算）
SCENE_OF = [1, 2, 3, 4, 5, 6, 7, 0, 8, 9]   # 第 i 张照片用哪个场景（让第 8 张是“草地+远山”那幅）


# ---------------------------------------------------------------- 示例照片（程序画出来的风光图）
def _fbm2(w, h, rng, octaves=5, base=3):
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        n = base * 2 ** o
        a = rng.random((max(2, n * h // w + 1), n + 1)).astype(np.float32)
        im = Image.fromarray((a * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        out += amp * np.asarray(im, np.float32) / 255.0
        tot += amp
        amp *= 0.5
    return out / tot


def _ridge(w, rng, base, amp, rough=0.55, octaves=6, cells=4):
    xs = np.arange(w, dtype=np.float32)
    y = np.zeros(w, np.float32)
    a, tot = 1.0, 0.0
    for o in range(octaves):
        n = cells * 2 ** o
        pts = rng.random(n + 2).astype(np.float32)
        y += a * np.interp(xs, np.linspace(0, w - 1, n + 2), pts)
        tot += a
        a *= rough
    y /= tot
    return base + amp * (y - 0.5) * 2


def _mix(a, b, t):
    return a + (b - a) * t


# 每个场景：seed、地平线位置、天空上/下色、太阳(x,y,半径,颜色)、远山颜色层、前景类型
SCENES = [
    dict(seed=11, hor=0.62, top=(0.30, 0.52, 0.84), low=(0.78, 0.86, 0.93), sun=(0.72, 0.30, 0.05, (1.0, 0.97, 0.88)), peaks=3, ground="meadow", cloud=0.55, tint=(0.58, 0.70, 0.86)),
    dict(seed=23, hor=0.66, top=(0.20, 0.38, 0.70), low=(0.95, 0.72, 0.52), sun=(0.30, 0.58, 0.06, (1.0, 0.86, 0.60)), peaks=2, ground="water", cloud=0.40, tint=(0.80, 0.55, 0.52)),
    dict(seed=37, hor=0.60, top=(0.36, 0.58, 0.88), low=(0.84, 0.90, 0.95), sun=(0.55, 0.22, 0.04, (1.0, 0.98, 0.92)), peaks=4, ground="snow", cloud=0.35, tint=(0.66, 0.74, 0.88)),
    dict(seed=41, hor=0.70, top=(0.26, 0.48, 0.80), low=(0.88, 0.84, 0.74), sun=(0.80, 0.38, 0.05, (1.0, 0.94, 0.80)), peaks=1, ground="dunes", cloud=0.25, tint=(0.80, 0.68, 0.56)),
    dict(seed=53, hor=0.64, top=(0.40, 0.58, 0.80), low=(0.86, 0.90, 0.88), sun=(0.25, 0.35, 0.04, (1.0, 0.98, 0.90)), peaks=5, ground="forest", cloud=0.60, tint=(0.60, 0.72, 0.74)),
    dict(seed=67, hor=0.68, top=(0.16, 0.26, 0.55), low=(0.96, 0.66, 0.40), sun=(0.60, 0.62, 0.07, (1.0, 0.80, 0.50)), peaks=2, ground="sea", cloud=0.30, tint=(0.78, 0.56, 0.48)),
    dict(seed=71, hor=0.63, top=(0.34, 0.54, 0.84), low=(0.82, 0.88, 0.92), sun=(0.18, 0.28, 0.04, (1.0, 0.97, 0.90)), peaks=3, ground="fields", cloud=0.50, tint=(0.62, 0.72, 0.86)),
    dict(seed=89, hor=0.65, top=(0.28, 0.50, 0.82), low=(0.80, 0.87, 0.93), sun=(0.68, 0.27, 0.05, (1.0, 0.96, 0.86)), peaks=4, ground="water", cloud=0.55, tint=(0.56, 0.68, 0.84)),
    dict(seed=97, hor=0.67, top=(0.22, 0.30, 0.58), low=(0.74, 0.62, 0.70), sun=(0.45, 0.52, 0.05, (1.0, 0.90, 0.78)), peaks=3, ground="water", cloud=0.35, tint=(0.60, 0.56, 0.72)),
    dict(seed=101, hor=0.62, top=(0.32, 0.54, 0.84), low=(0.90, 0.84, 0.70), sun=(0.82, 0.30, 0.05, (1.0, 0.95, 0.82)), peaks=4, ground="autumn", cloud=0.45, tint=(0.70, 0.68, 0.76)),
]


def _render_base(p, w=W, h=H):
    """返回 (图像 float32 HxWx3 0..1, 天空掩码 HxW 0..1)。"""
    rng = np.random.default_rng(p["seed"])
    hor = int(h * p["hor"])
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    xx = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
    top, low = np.array(p["top"], np.float32), np.array(p["low"], np.float32)
    t = np.clip(yy / p["hor"], 0, 1) ** 1.6
    img = _mix(top, low, t) * np.ones((1, w, 1), np.float32)
    # 太阳光晕
    sx, sy, sr, sc = p["sun"]
    d = np.sqrt(((xx - sx) * w) ** 2 + ((yy - sy) * h) ** 2)
    glow = np.exp(-(d / (0.22 * w)) ** 2) * 0.55 + np.exp(-(d / (0.06 * w)) ** 2) * 0.5
    disc = np.clip((sr * w - d) / 3.0, 0, 1)
    img = img + glow * (np.array(sc, np.float32) - img) * 0.55
    img = _mix(img, np.array(sc, np.float32), disc)
    # 云：低频噪声 + 阈值，越靠地平线越薄
    n = _fbm2(w, h, rng, 6, 3)
    cl = np.clip((n - (1 - p["cloud"]) * 0.78) * 4.0, 0, 1) * np.clip(1.25 - yy[..., 0] / p["hor"] * 0.75, 0, 1)
    shade = 0.80 + 0.20 * _fbm2(w, h, rng, 4, 6)
    cloud_col = np.array([1.0, 0.99, 0.97], np.float32) * shade[..., None]
    img = _mix(img, cloud_col, (cl * 0.85)[..., None])
    sky_mask = np.ones((h, w), np.float32)
    # 远山：由远到近，大气透视（远处偏雾蓝、近处更深）
    haze = np.array(p["tint"], np.float32)
    ys = np.arange(h, dtype=np.float32)[:, None]
    layers = p["peaks"]
    for i in range(layers):
        k = i / max(1, layers - 1) if layers > 1 else 0.5
        base_y = hor - (0.10 - 0.07 * k) * h - (1 - k) * 0.03 * h
        amp = (0.10 + 0.06 * (1 - k)) * h * (1.2 if p["ground"] in ("snow", "forest") else 0.8)
        ridge = _ridge(w, rng, base_y, amp * 0.5, rough=0.58 + 0.04 * (1 - k), cells=3 + i)
        if p["ground"] == "dunes":
            ridge = _ridge(w, rng, hor - 0.05 * h, 0.04 * h, rough=0.4, octaves=3, cells=2)
        mask = np.clip((ys - ridge[None, :]) / 2.0, 0, 1)
        col = _mix(haze * 0.95 + 0.06, haze * 0.40, k ** 0.9)
        tex = 0.92 + 0.12 * _fbm2(w, h, rng, 4, 10)
        if p["ground"] == "snow" and i < layers - 1:
            snow = np.clip((ridge[None, :] + 0.10 * h - ys) / (0.10 * h), 0, 1) ** 0.7
            colmap = _mix(np.broadcast_to(col, (h, w, 3)), np.array([0.94, 0.96, 1.0], np.float32), (snow * 0.8)[..., None])
        else:
            colmap = np.broadcast_to(col, (h, w, 3))
        img = _mix(img, colmap * tex[..., None], mask[..., None])
        sky_mask = np.minimum(sky_mask, 1 - mask)
    # 地面
    g = p["ground"]
    ground_y = ys - hor
    gm = np.clip(ground_y / 2.0, 0, 1)
    if g in ("water", "sea"):
        world = img.copy()
        refl = np.zeros_like(img)
        rrng = np.random.default_rng(p["seed"] + 5)
        rip = _fbm2(w, h, rrng, 4, 14)
        for y in range(hor, h):
            src = hor - (y - hor) * 1.0
            src = int(np.clip(src - (rip[y, 0] - 0.5) * 6, 0, hor - 1))
            row = world[src]
            shift = int((np.sin(y * 0.35) + (rip[y, w // 2] - 0.5) * 4) * (1 + (y - hor) * 0.04))
            refl[y] = np.roll(row, shift, axis=0)
        wcol = np.array(p["low"], np.float32) * 0.45 + np.array(p["top"], np.float32) * 0.35
        depth = np.clip(ground_y / (h - hor), 0, 1)
        water = _mix(refl * 0.85, wcol, 0.25 + 0.30 * depth[..., None])
        streak = (_fbm2(w, h, rrng, 3, 40)[..., None] - 0.5) * 0.10
        water = water + streak
        img = _mix(img, water, gm[..., None])
        sky_mask = sky_mask * (1 - gm)
    else:
        gr = np.random.default_rng(p["seed"] + 9)
        depth = np.clip(ground_y / (h - hor), 0, 1)[..., None]
        if g in ("meadow", "fields", "forest", "autumn"):
            far, near = {"meadow": ((0.46, 0.60, 0.34), (0.20, 0.36, 0.14)), "fields": ((0.78, 0.70, 0.36), (0.42, 0.46, 0.16)),
                         "forest": ((0.30, 0.46, 0.34), (0.08, 0.20, 0.12)), "autumn": ((0.78, 0.50, 0.20), (0.44, 0.24, 0.08))}[g]
        elif g == "snow":
            far, near = (0.90, 0.93, 0.98), (0.70, 0.76, 0.88)
        else:  # dunes
            far, near = (0.90, 0.72, 0.46), (0.66, 0.44, 0.24)
        col = _mix(np.array(far, np.float32), np.array(near, np.float32), depth ** 0.8)
        # 近大远小的纹理（草丛 / 垄 / 风纹）
        tex = _fbm2(w, h, gr, 5, 12)
        stripes = np.sin((xx[..., 0] * (30 + 400 * depth[..., 0] ** 1.5)) + tex * 8)[..., None] * 0.04 * depth
        col = col * (0.88 + 0.24 * tex[..., None]) + stripes
        if g == "dunes":
            wave = np.sin(yy[..., 0] * 40 + _ridge(w, gr, 0, 3, 0.5, 4, 2)[None, :] * 4)[..., None]
            col = col * (1 + 0.06 * wave)
        img = _mix(img, col, gm[..., None])
        sky_mask = sky_mask * (1 - gm)
    # 太阳在水面/地面上的反光不再单独画；加极轻的胶片颗粒
    img = img + (np.random.default_rng(p["seed"] + 3).standard_normal((h, w, 1)).astype(np.float32) * 0.008)
    return np.clip(img, 0, 1), np.clip(sky_mask, 0, 1)


def _lum(a):
    return (a * np.array([0.2126, 0.7152, 0.0722], np.float32)).sum(-1, keepdims=True)


def make_pair(idx, w=W, h=H):
    """返回 (改前, 改后) 两张 PIL 图。改前：天空偏灰白、亮部偏亮、暗部偏暗、颜色偏淡；改后：用调整表里的方向修回来。"""
    base, sky = _render_base(SCENES[idx], w, h)
    m = sky[..., None]
    # 改前（刻意平淡）
    lum = _lum(base)
    before = lum + (base - lum) * 0.80                       # 饱和度偏低
    before = before ** 1.12 * 0.96                           # 暗部偏沉
    veil = np.array([0.93, 0.95, 0.98], np.float32)
    before = _mix(before, veil, 0.30 * m)                    # 天空发白
    before = np.clip(before + 0.08 * m * np.clip(before - 0.6, 0, 1) * 3, 0, 1)   # 亮部偏亮
    # 改后：压高光（-35）、提阴影（+28）、自然饱和度（+12）、对比度（+8）
    x = before
    hi = np.clip((_lum(x) - 0.55) / 0.45, 0, 1)
    x = x - 0.20 * hi * (x - 0.55)                            # 高光压下去
    lo = np.clip((0.45 - _lum(x)) / 0.45, 0, 1)
    x = x + 0.22 * lo * (1 - x)                               # 阴影提亮
    l2 = _lum(x)
    sat = 1 + 0.30 + 0.30 * m                                 # 全图略增，天空多一点
    x = l2 + (x - l2) * sat
    blue = np.array([0.70, 0.90, 1.12], np.float32)
    x = _mix(x, x * blue, 0.55 * m)                           # 天空更蓝
    x = (x - 0.5) * 1.08 + 0.5                                # 对比度 +8
    after = np.clip(x, 0, 1)
    to_img = lambda a: Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.4))
    return to_img(before), to_img(after)


def _jpeg(im, q=88):
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q)
    return b.getvalue()


# ---------------------------------------------------------------- 示例数据
def build_data():
    """photos / 图片字节。id 用 '101'… 这类简单编号（示例）。"""
    names = [f"DSC{n:05d}.ARW" for n in range(1, 11)]
    for i in (2, 6, 9):               # 少数 JPG，更像真实库
        names[i] = names[i].replace(".ARW", ".JPG")
    stars = [3, 0, 4, 2, 0, 5, 0, 4, 1, 3]
    flags = ["pick", "none", "pick", "none", "none", "pick", "reject", "pick", "none", "none"]
    labels = [None, None, "green", None, None, "red", None, None, None, "blue"]
    photos = []
    for i, n in enumerate(names):
        g = "2026/2026-11-01" if i < 5 else "2026/2026-11-08"
        day = "2026-11-01" if i < 5 else "2026-11-08"
        photos.append(dict(id=str(101 + i), name=n, group=g, format="ARW" if n.endswith("ARW") else "JPG", rating=stars[i], flag=flags[i],
                           captured=f"{day} {10 + (i % 5) * 2:02d}:{(i * 7) % 60:02d}", w=6000, h=4000, vc=False, added=True, missing=False,
                           size=24_000_000 + i * 310_000, mtime=1793000000 + i * 3600, label=labels[i], edited=i in (7, 2, 5), added_at=f"2026-11-1{i % 5}T10:00:00",
                           color=None))
    extra, thumbs = {}, {}
    for i in range(10):
        before, after = make_pair(SCENE_OF[i])
        shown = after if i == MAIN else before                 # 被修过的那张，缩略图显示修后的样子
        t = shown.resize((360, 240), Image.LANCZOS)
        extra[f"/t/{i}.jpg"] = (_jpeg(t, 84), "image/jpeg")
        thumbs[str(101 + i)] = f"/t/{i}.jpg"
        if i in (MAIN, 2, 5, 7, 0):
            extra[f"/img/b{i}.jpg"] = (_jpeg(before, 90), "image/jpeg")
            extra[f"/img/a{i}.jpg"] = (_jpeg(after, 90), "image/jpeg")
    # 挑片放大图用的路径（/b/…）不会被点开，不用生成
    return photos, thumbs, extra


ROWS = [
    dict(rid="r1", label="高光", reason="压低云和天空的亮部", before="0", after="-35", status="已应用", edit_id="e1"),
    dict(rid="r2", label="阴影", reason="提亮远山和草地的暗部", before="0", after="+28", status="已应用", edit_id="e2"),
    dict(rid="r3", label="自然饱和度", reason="天空更蓝，只加一点", before="0", after="+12", status="已应用", edit_id="e3"),
    dict(rid="r4", label="对比度", reason="整体稍微通透", before="0", after="+8", status="已应用", edit_id="e4"),
]
USER_MSG = "天空再蓝一点，别太重"
AI_MSG = ("好的，我做了四处小调整：高光降 35，云的亮部不再发白；阴影提 28，远山和草地的暗处看得清了；"
          "自然饱和度加 12，天空蓝一些但不会很艳；对比度加 8，画面稍微通透。还想再蓝的话，我可以再加一点点。")


def pick_result():
    rk = [
        dict(rank=1, photo_id="108", name="DSC00008.ARW", score=8.6, stars=5, flag="pick", reason="天空层次好，远山与草地层次清楚", old_rating=4, old_flag="pick"),
        dict(rank=2, photo_id="101", name="DSC00001.ARW", score=7.8, stars=4, flag="pick", reason="日落色调好看，倒影干净，暗部偏重", old_rating=3, old_flag="pick"),
        dict(rank=3, photo_id="106", name="DSC00006.ARW", score=7.1, stars=3, flag="none", reason="田野有引导线，构图简洁，天空略平", old_rating=5, old_flag="pick"),
        dict(rank=4, photo_id="105", name="DSC00005.ARW", score=5.9, stars=2, flag="none", reason="主体不突出，前景偏暗", old_rating=0, old_flag="none"),
    ]
    return dict(type="pick_done", status="ok", n=4, criterion_label="综合观感", count_label="全部排序",
                summary="整体来看第 8 张最完整：天空、远山和草地的层次最清楚。第 1 张色调好看，但暗部偏重，可以先提亮阴影再比较。（示例结果）",
                ranking=rk, dropped=[], extra=0, elapsed=42, tokens=None, cost=None, message="", raw="")


# ---------------------------------------------------------------- 页面
OVERRIDE = r"""<script>
(function(){
  const q = new URLSearchParams(location.search), D = %DATA%, S = q.get('s') || 'main';
  const base = window.pywebview.api, A = {ok:true};
  const selIds = S === 'pick' ? ['101','105','106','108'] : ['108'];
  const sel = selIds.map(i => D.photos.find(p => p.id === i));
  const state = () => ({ok:true, state:'ready', message:'', base:'D:\\示例\\照片库', base_exists:true, in_catalog:true, lr_connected:true, total:D.photos.length, limit:2000,
    truncated:false, truncated_message:'', not_added:0, missing:0, photos:D.photos, thumbs:D.thumbs, failed:{}, selection:{ids:selIds, active:selIds[selIds.length-1]}, add:null,
    max_select:50, sort:'captured', order:'desc'});
  const P108 = D.photos.find(p => p.id === '108');
  const prev = () => S === 'pick' ? {type:'preview', state:'none', message:''} : {type:'preview', state:'ok',
    photo:{id:'108', name:P108.name, camera:'Sony ILCE-7M3', iso:'ISO 100', aperture:'ƒ / 8.0', shutter:'1/800 秒', focal:'20 mm', format:'RAW', size:'6000 × 4000', captured:P108.captured},
    initial:{url:'/img/b7.jpg', w:1500, h:1000, version:'v0'}, current:{url:'/img/a7.jpg', w:1500, h:1000, version:'v1'}, same:false, edge:1600};
  const o = {
    library_state: () => Promise.resolve(JSON.parse(JSON.stringify(state()))),
    library_thumbnails: ids => { const t = {}; ids.forEach(i => { if (D.thumbs[i]) t[i] = {url:D.thumbs[i]}; }); return Promise.resolve({ok:true, thumbs:t, pending:[]}); },
    library_select: (ids, active) => Promise.resolve({ok:true, status:'selected', message:'', selected:ids, active:active, not_selected:[]}),
    library_refresh: () => Promise.resolve(A),
    selection_state: () => Promise.resolve({count:sel.length, active_id:selIds[selIds.length-1], photos:sel.map(p => ({id:p.id, name:p.name}))}),
    status: () => Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'108', name:P108.name}}),
    preview_state: () => Promise.resolve(prev()),
    pick_state: () => Promise.resolve({stage:'done', n:4, result:D.pick, thumbs:Object.fromEntries(D.pick.ranking.map(r => [r.photo_id, D.thumbs[r.photo_id]]))}),
    pick_apply_state: () => Promise.resolve({stage:'idle', results:[], summary:null}),
  };
  window.pywebview.api = new Proxy(o, {get:(t, k) => (k in t) ? t[k] : base[k]});
})();
</script>"""

TAIL = r"""<script>
window.dispatchEvent(new Event('pywebviewready'));
(async()=>{
  const q = new URLSearchParams(location.search), S = q.get('s') || 'main', D = window.__DATA__;
  await wait(1500);
  if (S === 'main') {
    const m = document.getElementById('msgs'); m.innerHTML = '';
    say(D.user, 'me');
    window.onClaudeEvent({type:'text', text:D.ai});
    window.onClaudeEvent({type:'adjust', rows:D.rows});
    await wait(600);
  }
  if (S === 'pick') { openPick(); await wait(900); }
  if (S === 'settings') { document.getElementById('setbtn').click(); await wait(1200); }
})();
</script>"""


def build_page(data: dict) -> bytes:
    html = WEB.read_text(encoding="utf-8")
    ov = OVERRIDE.replace("%DATA%", json.dumps(data, ensure_ascii=False))
    ov += "<script>window.__DATA__ = " + json.dumps(data, ensure_ascii=False) + ";</script>"
    html = inject_stub(html, FAKE_API + HELPERS + ov)
    html = html.replace("</body>", TAIL + "</body>")
    return html.encode("utf-8")


# ---------------------------------------------------------------- 后处理
def _font(size):
    for f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def save_png(im: Image.Image, path: Path, limit=690_000):
    """先无损优化；超过上限就逐步减少颜色（带抖动）直到小于上限。"""
    im = im.convert("RGB")
    im.save(path, optimize=True)
    if path.stat().st_size <= limit:
        return
    for colors in (256, 192, 128, 96, 64):
        q = im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
        q.save(path, optimize=True)
        if path.stat().st_size <= limit:
            return


def themes_sheet(shots: dict[str, Path], out: Path):
    width, gap, pad = 1440, 24, 24
    cw = (width - 2 * pad - 2 * gap) // 3
    ch = round(cw * 900 / 1440)
    labels = [("paper", "浅色纸感"), ("glass", "夜蓝玻璃"), ("dark", "暗室")]
    sheet = Image.new("RGB", (width, pad + ch + 70), (244, 244, 242))
    d = ImageDraw.Draw(sheet)
    f = _font(26)
    for i, (key, name) in enumerate(labels):
        x = pad + i * (cw + gap)
        im = Image.open(shots[key]).convert("RGB").resize((cw, ch), Image.LANCZOS)
        sheet.paste(im, (x, pad))
        d.rectangle([x - 1, pad - 1, x + cw, pad + ch], outline=(200, 200, 196))
        tw = d.textlength(name, font=f)
        d.text((x + (cw - tw) / 2, pad + ch + 14), name, font=f, fill=(50, 52, 56))
    save_png(sheet, out)


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    import tempfile
    raw = Path(tempfile.mkdtemp(prefix="readme_shots_raw_"))       # 原始截图放临时目录，不污染输出目录
    print("原始截图目录：", raw)
    photos, thumbs, extra = build_data()
    data = dict(photos=photos, thumbs=thumbs, rows=ROWS, user=USER_MSG, ai=AI_MSG, pick=pick_result())
    srv = Server(build_page(data), extra)
    try:
        jobs = {"main_paper": "s=main&theme=paper&pw=300,400", "main_glass": "s=main&theme=glass&pw=300,400", "main_dark": "s=main&theme=dark&pw=300,400",
                "pick": "s=pick&theme=paper", "settings": "s=settings&theme=dark"}
        for name, qs in jobs.items():
            edge(f"{srv.base}?{qs}&pv=ok", 1440, 900, shot=raw / f"{name}.png", budget=9000)
            print("截图", name)
    finally:
        srv.close()
    save_png(Image.open(raw / "main_paper.png"), out / "readme_main.png")
    save_png(Image.open(raw / "pick.png"), out / "readme_pick.png")
    save_png(Image.open(raw / "settings.png"), out / "readme_settings.png")
    themes_sheet({"paper": raw / "main_paper.png", "glass": raw / "main_glass.png", "dark": raw / "main_dark.png"}, out / "readme_themes.png")
    # 示例图本身也存一份，方便肉眼检查（改前/改后）
    for i in (MAIN,):
        for tag, key in (("before", f"/img/b{i}.jpg"), ("after", f"/img/a{i}.jpg")):
            (raw / f"scene{i}_{tag}.jpg").write_bytes(extra[key][0])
    for p in sorted(out.glob("readme_*.png")):
        print(p.name, Image.open(p).size, p.stat().st_size // 1024, "KB")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
