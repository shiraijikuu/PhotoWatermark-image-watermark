# -*- coding: utf-8 -*-
"""图片水印插件：上传自定义图片作为水印，内置预设水印图（支持 PNG/JPG/GIF）。
- GIF 等动图只取第一帧（静态水印，不播放动画）
- 仅用于普通图片，RAW 自动跳过（避免加载过久）
- 大小 / 位置(X,Y偏移) / 旋转 / 不透明度 用滑块调整（「导出」页 -> 「插件设置」）
"""
import os
from PIL import Image

PLUGIN_NAME = 'image-watermark'
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

    api.add_setting('preset', '预设水印图 (Preset)', 'select', default_preset, options=options)
    api.add_setting('image', '自定义图片文件 (Custom file)', 'file', '')
    api.add_setting('size', '水印大小 % 宽 (Size)', 'range', 15, min=2, max=60, step=1)
    api.add_setting('offset_x', '水平位置 % (X offset)', 'range', 50, min=0, max=100, step=1)
    api.add_setting('offset_y', '垂直位置 % (Y offset)', 'range', 88, min=0, max=100, step=1)
    api.add_setting('rotation', '旋转角度 (Rotation)', 'range', 0, min=-180, max=180, step=1)
    api.add_setting('opacity', '不透明度 0-100 (Opacity)', 'range', 100, min=0, max=100, step=1)

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

        # 位置：0-100 百分比（0=左/上，50=居中，100=右/下）
        w, h = logo.size
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
