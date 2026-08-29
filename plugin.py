# -*- coding: utf-8 -*-
"""图片水印插件 v1.3.0：支持 1-5 个图片水印同时叠加，每个水印独立设置。
- 每个水印：预设图 / 自定义文件、大小、位置(X/Y 百分比)、旋转、不透明度
- 水印 1 支持与文字水印对齐/对称（layout + gap），水印 2-5 独立定位
- 图片缓存：同一路径只加载一次，避免重复 IO（预览拖动时流畅）
- 向后兼容：v1.2.x 单水印设置（preset/size/offset_x...）自动映射到水印 1
- 仅用于普通图片，RAW 自动跳过
"""
import os
from PIL import Image
import photo
try:
    import app
    _FONTS_DIR = app.FONTS_DIR
except Exception:
    app = None
    _FONTS_DIR = None

PLUGIN_NAME = 'image-watermark'
PLUGIN_VERSION = '1.4.0'
_HERE = os.path.dirname(os.path.abspath(__file__))
PRESETS_DIR = os.path.join(_HERE, 'presets')
CUSTOM_LABEL = '自定义文件'
DLC_MANIFEST_URL = 'https://cdn.jsdelivr.net/gh/shiraijikuu/camera-watermark-dlc-assets@main/dji-models.json'
DLC_SUBDIR = 'dji'   # 下载到 presets/dji/
MAX_WATERMARKS = 5

# layout 旧值→新值（汉化）映射
_LAYOUT_COMPAT = {
    'none': '无',
    'left-right': '文字左-图右',
    'right-left': '图左-文字右',
    'top-bottom': '文字上-图下',
    'bottom-top': '图上-文字下',
}
_LAYOUT_OPTIONS = ['无', '文字左-图右', '图左-文字右', '文字上-图下', '图上-文字下']

# 图片缓存：path -> PIL.Image（原始 RGBA），每次返回 copy 避免修改缓存
_IMG_CACHE = {}


def _list_presets():
    """递归扫描 presets 目录（支持 DLC 子目录），返回相对 presets 的路径列表。"""
    items = []
    if os.path.isdir(PRESETS_DIR):
        try:
            for root, _dirs, files in os.walk(PRESETS_DIR):
                for fn in sorted(files):
                    if fn.lower().endswith(('.gif', '.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                        full = os.path.join(root, fn)
                        rel = os.path.relpath(full, PRESETS_DIR).replace('\\', '/')
                        items.append(rel)
        except Exception:
            pass
    return sorted(items)


def _load_image(path):
    """带缓存的图片加载。返回 RGBA 图的 copy（调用方可自由缩放/旋转）。"""
    if path not in _IMG_CACHE:
        try:
            logo = Image.open(path)
            logo.seek(0)
            logo = logo.convert('RGBA')
        except Exception:
            return None
        _IMG_CACHE[path] = logo
    return _IMG_CACHE[path].copy()


def _fval(vals, key, default):
    try:
        return float(vals.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_watermark_image(vals, i):
    """获取第 i 个水印的图片路径（预设或自定义），兼容旧版单水印设置。"""
    if i == 1:
        preset = str(vals.get('wm1_preset') or vals.get('preset') or '')
        custom = str(vals.get('wm1_image') or vals.get('image') or '').strip()
    else:
        preset = str(vals.get('wm%d_preset' % i) or '')
        custom = str(vals.get('wm%d_image' % i) or '').strip()
    if preset and preset != CUSTOM_LABEL:
        path = os.path.join(PRESETS_DIR, preset)
    else:
        path = custom
    if not path or not os.path.exists(path):
        return None
    return path


def _render_one(img, vals, i, settings, values, is_first):
    """渲染单个水印。is_first=True 时支持与文字对齐。返回修改后的 img。"""
    path = _get_watermark_image(vals, i)
    if not path:
        return img
    logo = _load_image(path)
    if logo is None:
        return img

    sk = 'wm%d_' % i
    # 兼容旧版参数名（仅水印 1）
    def _compat(key, default):
        if i == 1:
            return vals.get(sk + key, vals.get(key, default))
        return vals.get(sk + key, default)

    size_pct = _fval(vals, sk + 'size', _fval(vals, 'size', 15) if i == 1 else 15)
    target_w = max(1, int(img.width * size_pct / 100))
    ratio = target_w / float(logo.width)
    logo = logo.resize((target_w, max(1, int(logo.height * ratio))), Image.LANCZOS)

    angle = _fval(vals, sk + 'rotation', _fval(vals, 'rotation', 0) if i == 1 else 0)
    if angle:
        logo = logo.rotate(angle, expand=True, resample=Image.BICUBIC)

    opacity = max(0.0, min(1.0, _fval(vals, sk + 'opacity', _fval(vals, 'opacity', 100) if i == 1 else 100) / 100.0))
    if opacity < 1.0:
        alpha = logo.split()[3].point(lambda x: int(x * opacity))
        logo.putalpha(alpha)

    w, h = logo.size

    # ---- 定位 ----
    layout = str(vals.get('layout', '无') or '无')
    layout = _LAYOUT_COMPAT.get(layout, layout)

    placed = False
    if is_first and layout != '无':
        content = logo.getbbox() or (0, 0, w, h)
        cw = content[2] - content[0]
        ch = content[3] - content[1]
        cxo, cyo = content[0], content[1]
        gap_px = img.width * _fval(vals, 'gap', 1.5) / 100.0
        rect = None
        try:
            rect = photo.watermark_rect(img, settings, values, fonts_dir=_FONTS_DIR)
        except Exception:
            rect = None

        def _place(dirn, gpx):
            if not rect:
                return None
            tx0, ty0, tx1, ty1 = rect
            tw, th = tx1 - tx0, ty1 - ty0
            if dirn == '文字左-图右':
                x = tx1 + gpx - cxo
                y = ty0 + (th - ch) / 2.0 - cyo
            elif dirn == '图左-文字右':
                x = tx0 - gpx - cw - cxo
                y = ty0 + (th - ch) / 2.0 - cyo
            elif dirn == '文字上-图下':
                x = tx0 + (tw - cw) / 2.0 - cxo
                y = ty1 + gpx - cyo
            else:
                x = tx0 + (tw - cw) / 2.0 - cxo
                y = ty0 - gpx - ch - cyo
            if 0 <= x and 0 <= y and x + w <= img.width and y + h <= img.height:
                return (x, y)
            return None

        FLIP = {'文字左-图右': '图左-文字右', '图左-文字右': '文字左-图右',
                '文字上-图下': '图上-文字下', '图上-文字下': '文字上-图下'}
        for dirn in (layout, FLIP.get(layout, layout)):
            p = _place(dirn, gap_px)
            if p:
                img = img.convert('RGB')
                img.paste(logo, (int(round(p[0])), int(round(p[1]))), logo)
                placed = True
                break
        if not placed and rect:
            tx0, ty0, tx1, ty1 = rect
            tw, th = tx1 - tx0, ty1 - ty0
            if layout in ('文字左-图右', '图左-文字右'):
                x = tx0 + tw / 2.0 - cw / 2.0 - cxo
                y = ty0 + (th - ch) / 2.0 - cyo
            else:
                x = tx0 + (tw - cw) / 2.0 - cxo
                y = ty0 + th / 2.0 - ch / 2.0 - cyo
            x = max(0, min(img.width - w, x))
            y = max(0, min(img.height - h, y))
            img = img.convert('RGB')
            img.paste(logo, (int(round(x)), int(round(y))), logo)
            placed = True

    if not placed:
        ox = max(0.0, min(100.0, _fval(vals, sk + 'offset_x', _fval(vals, 'offset_x', 50) if i == 1 else 50)))
        oy = max(0.0, min(100.0, _fval(vals, sk + 'offset_y', _fval(vals, 'offset_y', 88) if i == 1 else 88)))
        x = int((img.width - w) * ox / 100.0)
        y = int((img.height - h) * oy / 100.0)
        x = max(0, min(img.width - w, x))
        y = max(0, min(img.height - h, y))
        img = img.convert('RGB')
        img.paste(logo, (x, y), logo)

    return img


def register(api):
    presets = _list_presets()
    default_preset = presets[0] if presets else CUSTOM_LABEL
    gallery_options = [{'label': os.path.basename(rel), 'image': os.path.join(PRESETS_DIR, rel),
                        'value': rel} for rel in presets]
    gallery_options.append({'label': '自定义', 'image': None})

    # ---- 共用设置 ----
    api.add_setting('_hdr_common', '共用设置', 'header', '')
    api.add_setting('count', '水印数量', 'select', default='1',
                    options=[str(n) for n in range(1, MAX_WATERMARKS + 1)])
    api.add_setting('layout', '与文字对齐（仅水印1）', 'select', default='无',
                    options=_LAYOUT_OPTIONS)
    api.add_setting('gap', '与文字间距 %宽', 'range', 1.5, min=0, max=10, step=0.1)

    # ---- 每个水印的设置（循环生成）----
    for i in range(1, MAX_WATERMARKS + 1):
        api.add_setting('_hdr_wm%d' % i, '水印 %d' % i, 'header', '')
        api.add_setting('wm%d_preset' % i, '预设图', 'gallery', default_preset, options=gallery_options)
        api.add_setting('wm%d_image' % i, '自定义文件', 'file', '')
        api.add_setting('wm%d_size' % i, '大小 %宽', 'range', 15, min=2, max=60, step=1)
        api.add_setting('wm%d_offset_x' % i, '水平位置 %', 'range', 50, min=0, max=100, step=1)
        api.add_setting('wm%d_offset_y' % i, '垂直位置 %', 'range', 88, min=0, max=100, step=1)
        api.add_setting('wm%d_rotation' % i, '旋转角度', 'range', 0, min=-180, max=180, step=1)
        api.add_setting('wm%d_opacity' % i, '不透明度', 'range', 100, min=0, max=100, step=1)

    def render(img, settings, values):
        if values.get('raw'):
            return img
        vals = (settings.get('plugin_values') or {}).get(PLUGIN_NAME, {})
        count = int(max(1, min(MAX_WATERMARKS, _fval(vals, 'count', 1))))
        for i in range(1, count + 1):
            img = _render_one(img, vals, i, settings, values, is_first=(i == 1))
        return img

    api.add_dlc_source(PLUGIN_NAME, '添加更多水印…', DLC_MANIFEST_URL, DLC_SUBDIR)
    api.add_watermark_style('image_watermark', '图片水印（插件）', render)
