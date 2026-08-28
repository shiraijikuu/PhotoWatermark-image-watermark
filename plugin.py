# -*- coding: utf-8 -*-
"""图片水印插件：上传自定义图片作为水印，内置预设水印图（支持 PNG/JPG/GIF）。
- GIF 等动图只取第一帧（静态水印，不播放动画）
- 仅用于普通图片，RAW 自动跳过（避免加载过久）
- 大小 / 位置(X,Y偏移) / 旋转 / 不透明度 用滑块调整（「导出」页 -> 「插件设置」）
"""
import os
from PIL import Image

import photo
try:
    import app
    _FONTS_DIR = app.FONTS_DIR
except Exception:  # 极端加载顺序：回退默认字体目录
    app = None
    _FONTS_DIR = None

PLUGIN_NAME = 'image-watermark'
PLUGIN_VERSION = '1.2.1'
_HERE = os.path.dirname(os.path.abspath(__file__))
PRESETS_DIR = os.path.join(_HERE, 'presets')
CUSTOM_LABEL = '自定义文件'


def _list_presets():
    """列出预设目录里的图片（presets/）"""
    names = []
    if os.path.isdir(PRESETS_DIR):
        try:
            for fn in sorted(os.listdir(PRESETS_DIR)):
                if fn.lower().endswith(('.gif', '.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                    names.append(fn)
        except Exception:
            pass
    return names


def register(api):
    presets = _list_presets()
    options = [CUSTOM_LABEL] + presets
    default_preset = presets[0] if presets else CUSTOM_LABEL

    gallery_options = [{'label': fn, 'image': os.path.join(PRESETS_DIR, fn)} for fn in presets]
    gallery_options.append({'label': '自定义', 'image': None})
    api.add_setting('preset', '预设水印图 (Preset)', 'gallery', default_preset, options=gallery_options)
    api.add_setting('image', '自定义图片文件 (Custom file)', 'file', '')
    api.add_setting('size', '水印大小 % 宽 (Size)', 'range', 15, min=2, max=60, step=1)
    api.add_setting('offset_x', '水平位置 % (X offset)', 'range', 50, min=0, max=100, step=1)
    api.add_setting('offset_y', '垂直位置 % (Y offset)', 'range', 88, min=0, max=100, step=1)
    api.add_setting('rotation', '旋转角度 (Rotation)', 'range', 0, min=-180, max=180, step=1)
    api.add_setting('opacity', '不透明度 0-100 (Opacity)', 'range', 100, min=0, max=100, step=1)
    api.add_setting('layout', '与文字对齐 (Align with text)', 'select', default='none',
                    options=['none', 'left-right', 'right-left', 'top-bottom', 'bottom-top'])
    api.add_setting('gap', '间距 %宽 (Gap)', 'range', 1.5, min=0, max=10, step=0.1)

    def render(img, settings, values):
        # RAW 不加水印，避免加载过久
        if values.get('raw'):
            return img

        vals = (settings.get('plugin_values') or {}).get(PLUGIN_NAME, {})
        # 选预设 或 自定义文件
        preset = str(vals.get('preset', '') or '')
        if preset and preset != CUSTOM_LABEL:
            path = os.path.join(PRESETS_DIR, preset)
        else:
            path = str(vals.get('image', '') or '').strip()
        if not path or not os.path.exists(path):
            return img

        try:
            logo = Image.open(path)
            logo.seek(0)   # GIF 等多帧图片只取第一帧（静态水印，不播放动画）
            logo = logo.convert('RGBA')
        except Exception:
            return img

        def fval(key, default):
            try:
                return float(vals.get(key, default))
            except (TypeError, ValueError):
                return default

        # 大小：占图片宽度百分比
        size_pct = fval('size', 15)
        target_w = max(1, int(img.width * size_pct / 100))
        ratio = target_w / float(logo.width)
        logo = logo.resize((target_w, max(1, int(logo.height * ratio))), Image.LANCZOS)

        # 旋转
        angle = fval('rotation', 0)
        if angle:
            logo = logo.rotate(angle, expand=True, resample=Image.BICUBIC)

        # 不透明度
        opacity = max(0.0, min(1.0, fval('opacity', 100) / 100.0))
        if opacity < 1.0:
            alpha = logo.split()[3].point(lambda x: int(x * opacity))
            logo.putalpha(alpha)

        w, h = logo.size
        # ---- 文字-图片组合布局：优先与文字水印对齐/对称/间距 ----
        # 仅默认文字水印模式（主程序已画文字水印）生效。
        # 透明 logo 用 getbbox() 不透明内容区计算间距（透明边缘不干扰对齐）；
        # 越界时先翻到反方向（文字与 logo 始终成对），双向放不下再与文字中心对齐 clamp 贴边。
        content = logo.getbbox() or (0, 0, w, h)     # 不透明内容区域
        cw = content[2] - content[0]
        ch = content[3] - content[1]
        cxo, cyo = content[0], content[1]            # 内容在画布内的偏移

        layout = str(vals.get('layout', 'none') or 'none')
        gap_px = img.width * fval('gap', 1.5) / 100.0
        rect = None
        try:
            rect = photo.watermark_rect(img, settings, values, fonts_dir=_FONTS_DIR)
        except Exception:
            rect = None

        def _place(dirn, gpx):
            """按方向计算 logo 画布左上角（内容与文字边缘相距 gpx）。返回 (x,y) 或 None。"""
            if not rect:
                return None
            tx0, ty0, tx1, ty1 = rect
            tw, th = tx1 - tx0, ty1 - ty0
            if dirn == 'left-right':      # 文字左 logo 右，内容垂直居中
                x = tx1 + gpx - cxo
                y = ty0 + (th - ch) / 2.0 - cyo
            elif dirn == 'right-left':    # logo 左 文字右
                x = tx0 - gpx - cw - cxo
                y = ty0 + (th - ch) / 2.0 - cyo
            elif dirn == 'top-bottom':    # 文字上 logo 下，内容水平居中
                x = tx0 + (tw - cw) / 2.0 - cxo
                y = ty1 + gpx - cyo
            else:                         # bottom-top：logo 上 文字下
                x = tx0 + (tw - cw) / 2.0 - cxo
                y = ty0 - gpx - ch - cyo
            if 0 <= x and 0 <= y and x + w <= img.width and y + h <= img.height:
                return (x, y)
            return None

        placed = False
        if layout != 'none' and rect:
            # 依次尝试：原方向 → 反方向（保证文字与 logo 不重叠、始终成对）
            FLIP = {'left-right': 'right-left', 'right-left': 'left-right',
                    'top-bottom': 'bottom-top', 'bottom-top': 'top-bottom'}
            for dirn in (layout, FLIP.get(layout, layout)):
                p = _place(dirn, gap_px)
                if p:
                    img = img.convert('RGB')
                    img.paste(logo, (int(round(p[0])), int(round(p[1]))), logo)
                    placed = True
                    break
            if not placed:
                # 双向都放不下（如文字居中且 logo 过大）：与文字中心对齐后 clamp 贴边
                tx0, ty0, tx1, ty1 = rect
                tw, th = tx1 - tx0, ty1 - ty0
                if layout in ('left-right', 'right-left'):
                    x = tx0 + tw / 2.0 - cw / 2.0 - cxo     # 与文字水平中心对齐
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
            # 原独立定位逻辑（offset_x/offset_y 百分比），保持现状
            ox = max(0.0, min(100.0, fval('offset_x', 50)))
            oy = max(0.0, min(100.0, fval('offset_y', 88)))
            x = int((img.width - w) * ox / 100.0)
            y = int((img.height - h) * oy / 100.0)
            x = max(0, min(img.width - w, x))
            y = max(0, min(img.height - h, y))
            img = img.convert('RGB')
            img.paste(logo, (x, y), logo)
        return img

    api.add_watermark_style('image_watermark', '图片水印（插件）', render)
