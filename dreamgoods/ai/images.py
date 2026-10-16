"""Подготовка картинок для запросов к моделям."""
import base64
import io
import threading
from collections import OrderedDict

from PIL import Image, ImageOps

# Фото товаров бывают огромными (8000×3700 = ~90 МБ в памяти после распаковки). Когда параллельно идут сотни заданий,
# одновременная распаковка таких фото съедает гигабайты. Поэтому: (1) JPEG распаковывается сразу в уменьшенном
# масштабе (draft — декодер сам пропускает лишние пиксели); (2) не больше DECODE_SLOTS распаковок одновременно;
# (3) готовые референсы кэшируются — одни и те же фото товара идут во все его кадры.
DECODE_SLOTS = threading.BoundedSemaphore(4)
# Готовая картинка в полном размере (при 4K — десятки МБ) живёт в памяти от скачивания до записи в хранилище и
# подготовки к проверке. Когда результаты приходят пачкой, одновременно держим не больше POST_LIMIT таких картинок.
POST_LIMIT = 8
_post = threading.BoundedSemaphore(POST_LIMIT)


class PostSlot:
    """Место для обработки готовой картинки; release() можно звать сколько угодно раз."""
    def __init__(self):
        self.held = False

    def acquire(self):
        if not self.held:
            _post.acquire()
            self.held = True

    def release(self):
        if self.held:
            self.held = False
            _post.release()
_refs, _refs_lock = OrderedDict(), threading.Lock()
REF_CACHE = 300


def open_small(data, side):
    """Открывает картинку; JPEG — сразу в уменьшенном масштабе (не меньше side по обеим сторонам)."""
    im = Image.open(io.BytesIO(data))
    if side and im.format == "JPEG":
        im.draft("RGB", (side, side))
    return im


def jpeg_data_url(data, side, quality=85):
    """Байты картинки → data URL в JPEG, уменьшенный до side по длинной стороне."""
    with DECODE_SLOTS:
        with open_small(data, side) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((side, side), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def ref_payload(data, side):
    """Референс для генерации: JPEG до side px в формате Polza."""
    return {"type": "base64", "data": jpeg_data_url(data, side, quality=88)}


def ref_for(asset, side):
    """Референс по файлу хранилища — с кэшем (файлы адресуются по содержимому и не меняются)."""
    from ..core import storage
    k = (asset.storage_key, side)
    with _refs_lock:
        if k in _refs:
            _refs.move_to_end(k)
            return _refs[k]
    v = ref_payload(storage.get(asset), side)
    with _refs_lock:
        _refs[k] = v
        while len(_refs) > REF_CACHE:
            _refs.popitem(last=False)
    return v


def _fit_side(data, side, tag="", hard=0):
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


def fit_side(data, side, tag="", hard=0):
    with DECODE_SLOTS:
        return _fit_side(data, side, tag, hard)
