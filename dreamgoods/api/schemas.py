"""Схемы запросов API (Pydantic): проверка входных данных и документация в /docs."""
from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    client: str = ""
    name: str = ""


class Selection(BaseModel):
    """Какие товары/кадры. Пусто — все в проекте. brief/market/aspect — пожелания к этому запуску (поверх пресета)."""
    product_ids: list[int] | None = None
    frame_ids: list[int] | None = None
    limit: int = Field(0, ge=0)
    brief: str = Field("", max_length=1500)
    market: str = ""
    aspect: str = ""


class QuickAction(BaseModel):
    action: Literal["upscale", "remove_bg"]


class CheckRequest(Selection):
    only_unchecked: bool = True


class ReviewRequest(BaseModel):
    verdict: Literal["ok", "bad"]
    comment: str = ""
    regen: bool = False


class PromptUpdate(BaseModel):
    text: str


class EditRequest(BaseModel):
    instruction: str = Field(..., max_length=1500, description="что изменить на фото, своими словами")
    source_id: int | None = Field(None, description="какую версию править; по умолчанию — текущую")


class RestoreRequest(BaseModel):
    generation_id: int


class ParallelUpdate(BaseModel):
    n: int = Field(..., ge=1, le=200)


class RefsUpdate(BaseModel):
    selected: list[str]


class ProfileUpdate(BaseModel):
    profile: dict
    build: bool = False


class ProfileGenerate(BaseModel):
    product_ids: list[int] | None = None     # None — все товары без промптов
    build: bool = True


class ImportAnalyze(BaseModel):
    group_mode: Literal["auto", "folders", "none"] = "auto"     # none — без ИИ: по папкам, всё — фото товара
    label_mode: Literal["read", "skip", "keep"] = "read"
    sort_rule: str = Field("", max_length=1000)                 # своё правило раскладки словами (для ИИ)


class ImportGroup(BaseModel):
    name: str
    photos: list[tuple[str, str]]             # [имя файла, роль: product | packaging | label | junk]
    description: str = Field("", max_length=2000)   # описание товара словами (необязательно) — подсказка для профиля
    sort_error: bool = False                        # пользователь отметил ошибку раскладки ИИ


class ImportApply(BaseModel):
    groups: list[ImportGroup]
    label_mode: Literal["read", "skip", "keep"] = "read"
    auto_profile: bool = True


class PersonaCreate(BaseModel):
    name: str = ""
    brief: str = ""                                   # пожелания по-русски: пол, возраст, внешность
    source: Literal["upload", "generated"] = "generated"


class PersonaUpdate(BaseModel):
    name: str | None = None
    brief: str | None = None
    description: str | None = None
    style: dict | None = None                         # makeup, hair_styling, clothing_style, accessories, vibe, expression
    groups: list[str] | None = None                   # группы товаров для этой модели: «Обувь», «Обувь / Ботфорты»
    consent: bool | None = None


class PersonaCandidates(BaseModel):
    count: int = Field(2, ge=1, le=4)
    brief: str | None = None                          # новые пожелания (если меняются)


class PersonaChoice(BaseModel):
    photo_id: int | None = None
    persona_id: int | None = None


class PersonaEdit(BaseModel):
    request: str                                      # что изменить, по-русски
    count: int = Field(2, ge=1, le=4)


class PresetSave(BaseModel):
    name: str = ""
    description: str = ""
    quality: Literal["draft", "standard", "premium", "custom"] = "standard"
    custom: dict = {}                                 # для «Своего»: model, providers, resolution, qc_retries, qc_count, qc_model
    plan: dict = {}                                   # {studio, detail, worn, full, lifestyle}: число кадров (режим auto)
    market: dict = {}                                 # {key: none|wb|ozon|ymarket|avito|custom, cover: bool, …для custom: aspect, min_side, cover_bg, cover_fill, cover_extra}
    strictness: Literal["strict", "normal", "critical"] = "normal"
    plan_mode: Literal["auto", "manual"] = "auto"     # auto — кадры придумывает ИИ по блокам; manual — свои методы съёмки
    manual: list[dict] = []                           # [{title, prompt, block, count, model}]
    block_models: dict = {}                           # {studio|detail|worn|full|lifestyle: модель генерации}
    brief: str = Field("", max_length=1500)           # пожелания к генерации (режим «Авто»), по-русски
    # только для мастера: пресет студии — виден всем кабинетам и на сайте («Цены и оплата»). По умолчанию — нет:
    # новый пресет мастера хранится в кабинете открытого проекта, как у любого пользователя
    shared: bool | None = None


class PresetApply(BaseModel):
    product_ids: list[int] | None = None
    categories: list[str] | None = None               # «Обувь», «Обувь / Сапоги», «Без профиля»…
    everything: bool = False
    make_default: bool = False                        # сделать пресетом проекта (для новых товаров)
    rebuild: bool = True                              # пересобрать промпты кадров
    dry_run: bool = False


class StyleRefCreate(BaseModel):
    name: str = ""
    note: str = ""                                    # что взять из примера, по-русски
    blocks: list[str] | None = None                   # studio | detail | usage | scene | lifestyle (обложка — никогда)


class StyleRefUpdate(BaseModel):
    name: str | None = None
    note: str | None = None
    description: str | None = None
    blocks: list[str] | None = None


class StyleRefChoice(BaseModel):
    style_ref_id: int | None = None
