"""Подготовка картинок для запросов к моделям."""
import base64
import io

from PIL import Image, ImageOps


def jpeg_data_url(data, side, quality=85):
    """Байты картинки → data URL в JPEG, уменьшенный до side по длинной стороне."""
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((side, side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def ref_payload(data, side):
    """Референс для генерации: JPEG до side px в формате Polza."""
    return {"type": "base64", "data": jpeg_data_url(data, side, quality=88)}
