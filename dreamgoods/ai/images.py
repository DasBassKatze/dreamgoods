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


def fit_side(data, side, tag="", hard=0):
    """Кадр меньше нужного разрешения (модель не умеет заказанный уровень) → увеличение до side px по короткой стороне.
    Небольшую недостачу (до 3 %, например 1792 вместо 1800) не трогаем, если кадр не меньше hard — минимума площадки
    (его техпроверка требует строго). Возвращает байты PNG или исходные байты."""
    if not side:
        return data
    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
        if min(w, h) >= side * 0.97 and min(w, h) >= hard:
            return data
        k = side / min(w, h)
        nw, nh = round(w * k), round(h * k)
        out = io.BytesIO()
        ImageOps.exif_transpose(im).convert("RGB").resize((nw, nh), Image.LANCZOS).save(out, "PNG")
    from ..core.logs import log
    log.info("%s модель вернула %d×%d — меньше разрешения пресета, увеличено до %d×%d", tag, w, h, nw, nh)
    return out.getvalue()
