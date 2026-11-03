"""Схема данных (PostgreSQL).

Организация (агентство или магазин)
  └─ клиенты → проекты (настройки генерации и проверки) → товары (артикулы)
        товар: фото (референсы, этикетки) · профили (версии) · кадры
  └─ модели клиента (люди для съёмки «в использовании»): свои фото или сгенерированный образ
  └─ референсы оформления клиента: фото-пример стиля (свет, цвет, фон, композиция) + краткое описание
        кадр: генерации (каждая попытка) → проверки ИИ → ручная разметка
Сквозные: файлы (assets, в S3), очередь заданий, журнал расходов (основа биллинга), сессии импорта.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
                        JSON, Numeric, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONT = JSON().with_variant(JSONB(), "postgresql")


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TS:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


# ───────────── организация, пользователи, клиенты, проекты ─────────────

class Organization(TS, Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict] = mapped_column(JSONT, default=dict)       # общие настройки (модели, ключи по умолчанию)


class PolzaKey(TS, Base):
    """Ключ API Polza. shared — в общем пуле (клиенты без своего ключа распределяются по пулу);
    иначе ключ работает только у клиентов, за которыми закреплён."""
    __tablename__ = "polza_keys"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    secret: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    shared: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")


class User(TS, Base):
    """Учётная запись сайта. master — мастер-аккаунт (всё видит, заводит пользователей, пополняет балансы);
    user — личный кабинет: видит только проекты своего клиента (client_id)."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)       # логин (почта или любое имя)
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default="user")     # master | user
    password_hash: Mapped[str] = mapped_column(Text, default="")
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # почта подтверждена (регистрация на сайте); у учётных записей, заведённых мастером, — время создания
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)      # sha256 токена (сам токен — только в cookie)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str] = mapped_column(String(64), default="")
    agent: Mapped[str] = mapped_column(String(300), default="")


class EmailToken(Base):
    """Одноразовые ссылки из писем: подтверждение почты (verify). В базе — только sha256 токена."""
    __tablename__ = "email_tokens"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="verify")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LegalDocument(TS, Base):
    """Юридический документ сервиса (политика, согласия, соглашение) — версии. Текущая — наибольшая version по kind.
    Новая версия обязательного документа — пользователи принимают её заново при входе."""
    __tablename__ = "legal_documents"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))                    # privacy | pd_consent | terms | cross_border | marketing | persona_photo
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    required: Mapped[bool] = mapped_column(Boolean, default=True)     # без согласия пользоваться сервисом нельзя
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    __table_args__ = (UniqueConstraint("org_id", "kind", "version"),)


class Consent(TS, Base):
    """Журнал согласий (только добавление): кто, на что, какой версии документа, когда, откуда. Отзыв — новая запись
    с granted=False. Действующее согласие — последняя запись по (пользователь, kind, ref)."""
    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    email: Mapped[str] = mapped_column(String(200), default="")      # логин на момент согласия (запись живёт и без учётки)
    kind: Mapped[str] = mapped_column(String(30))
    doc_version: Mapped[int] = mapped_column(Integer, default=0)
    granted: Mapped[bool] = mapped_column(Boolean, default=True)      # False — отзыв
    source: Mapped[str] = mapped_column(String(20), default="")      # register | login | account | persona | master
    subject: Mapped[str] = mapped_column(String(300), default="")    # чьё согласие подтверждено (для фото людей — имя модели)
    ref: Mapped[str] = mapped_column(String(120), default="")        # к чему относится: persona:12
    ip: Mapped[str] = mapped_column(String(64), default="")
    agent: Mapped[str] = mapped_column(String(300), default="")
    __table_args__ = (Index("ix_consents_user_kind", "user_id", "kind"),)


class Client(TS, Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    contact: Mapped[str] = mapped_column(String(300), default="")
    balance_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), default=0.0)   # внутренний баланс клиента, ₽
    billing: Mapped[bool] = mapped_column(Boolean, default=False)     # True — генерации списываются с баланса
    markup: Mapped[float | None] = mapped_column(Numeric(18, 6, asdecimal=False), nullable=True)  # наценка; None — общая из настроек мастера
    key_id: Mapped[int | None] = mapped_column(ForeignKey("polza_keys.id", ondelete="SET NULL"), nullable=True)
    plan: Mapped[str] = mapped_column(String(20), default="start")      # тариф (core/plans.py)
    plan_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # до какого дня действует
    __table_args__ = (UniqueConstraint("org_id", "name"),)


class TopupRequest(TS, Base):
    """Заявка пользователя на пополнение баланса (пока нет онлайн-оплаты: мастер зачисляет вручную после оплаты)."""
    __tablename__ = "topup_requests"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    amount_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False))
    bonus_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), default=0.0)
    method: Mapped[str] = mapped_column(String(20), default="card")       # card | sbp | invoice
    status: Mapped[str] = mapped_column(String(20), default="new")        # new | paid | cancelled
    note: Mapped[str] = mapped_column(Text, default="")                    # пожелания / реквизиты для счёта
    plan: Mapped[str] = mapped_column(String(20), default="")              # заявка на тариф: какой
    months: Mapped[int] = mapped_column(Integer, default=0)                # и на сколько месяцев
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BalanceEntry(TS, Base):
    """Журнал баланса клиента: пополнения мастером и списания за операции (с себестоимостью Polza)."""
    __tablename__ = "balance_ledger"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))                       # topup | charge | adjust
    amount_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False))
    cost_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), default=0.0)
    balance_after: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), default=0.0)
    what: Mapped[str] = mapped_column(String(200), default="")
    ref: Mapped[str] = mapped_column(String(120), default="")


class Project(TS, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict] = mapped_column(JSONT, default=dict)       # модель, провайдер, формат, проверка, план кадров
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    client: Mapped["Client"] = relationship()
    __table_args__ = (UniqueConstraint("client_id", "name"),)


class GenerationPreset(TS, Base):
    """Пресет генерации: уровень качества + план кадров по блокам. Общий для организации (всех клиентов и проектов)."""
    __tablename__ = "generation_presets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    quality: Mapped[str] = mapped_column(String(20), default="standard")   # draft | standard | premium | custom
    custom: Mapped[dict] = mapped_column(JSONT, default=dict)              # переопределения для quality=custom
    plan: Mapped[dict] = mapped_column(JSONT, default=dict)                # {studio, detail, worn, full, lifestyle}: кадров
    market: Mapped[dict] = mapped_column(JSONT, default=dict)              # площадка: {key, cover, …} — формат и обложка
    strictness: Mapped[str] = mapped_column(String(20), default="normal")  # строгость проверки: strict | normal | critical
    plan_mode: Mapped[str] = mapped_column(String(10), default="auto")     # auto — блоки по профилю | manual — свои методы
    manual: Mapped[list] = mapped_column(JSONT, default=list)              # [{title, prompt, block, count, model}]
    block_models: Mapped[dict] = mapped_column(JSONT, default=dict)        # {studio: модель, …} — модель на блок
    brief: Mapped[str] = mapped_column(Text, default="", server_default="")  # пожелания к генерации (режим «Авто»), по-русски
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=True)  # None — общий
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class CategoryChecklist(TS, Base):
    """Библиотека чек-листов категорий. org_id = NULL — общая библиотека сервиса."""
    __tablename__ = "category_checklists"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    key: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    checklist: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("org_id", "key"),)


# ───────────── файлы (S3) ─────────────

class Asset(TS, Base):
    """Любой файл в S3. Ключ строится по sha256 — одинаковые файлы хранятся один раз."""
    __tablename__ = "assets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))        # photo | output | import | export
    storage_key: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime: Mapped[str] = mapped_column(String(50))
    bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_name: Mapped[str] = mapped_column(String(300), default="")
    shot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ───────────── товары ─────────────

class Product(TS, Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(120))                 # артикул = имя папки в выдаче
    name: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(50), default="")
    label_data: Mapped[dict] = mapped_column(JSONT, default=dict)  # прочитано с этикеток: артикулы, бренд, состав
    current_profile_id: Mapped[int | None] = mapped_column(ForeignKey("product_profiles.id", ondelete="SET NULL",
                                                                      use_alter=True, name="fk_products_current_profile"), nullable=True)
    # пресет генерации товара (качество + план кадров); NULL — как в проекте
    preset_id: Mapped[int | None] = mapped_column(ForeignKey("generation_presets.id", ondelete="SET NULL",
                                                             name="fk_products_preset"), nullable=True)
    # референс оформления для кадров товара; NULL — как в проекте
    style_ref_id: Mapped[int | None] = mapped_column(ForeignKey("style_refs.id", ondelete="SET NULL",
                                                                name="fk_products_style_ref"), nullable=True)
    # модель (человек) для кадров этого товара; NULL — как в проекте
    persona_id: Mapped[int | None] = mapped_column(ForeignKey("personas.id", ondelete="SET NULL", name="fk_products_persona"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    project: Mapped["Project"] = relationship()
    __table_args__ = (UniqueConstraint("project_id", "sku"),)


class Persona(TS, Base):
    """Модель клиента — человек, который «носит» товары на кадрах. Принадлежит клиенту: доступна во всех его проектах
    (и в будущем личном кабинете). Источник — фото клиента (upload) или образ, сгенерированный по описанию (generated)."""
    __tablename__ = "personas"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    brief: Mapped[str] = mapped_column(Text, default="")            # пожелания клиента (рус.): пол, возраст, внешность
    description: Mapped[str] = mapped_column(Text, default="")      # внешность для генератора (англ.), без одежды
    style: Mapped[dict] = mapped_column(JSONT, default=dict)        # стиль: makeup, hair_styling, clothing_style, accessories, vibe, expression
    source: Mapped[str] = mapped_column(String(20), default="generated")   # upload | generated
    status: Mapped[str] = mapped_column(String(20), default="draft")       # draft | ready | archived
    consent: Mapped[bool] = mapped_column(Boolean, default=False)   # клиент подтвердил согласие человека на фото
    groups: Mapped[list] = mapped_column(JSONT, default=list)       # группы товаров: «Обувь», «Обувь / Ботфорты» — снимать на этой модели


class PersonaPhoto(TS, Base):
    __tablename__ = "persona_photos"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="photo")   # candidate | main | sheet | photo (загружено)
    view: Mapped[str] = mapped_column(String(40), default="")        # portrait | full front | three-quarter | side
    position: Mapped[int] = mapped_column(Integer, default=0)
    cost_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), default=0.0)
    spec: Mapped[dict] = mapped_column(JSONT, default=dict)          # паспорт образа этого варианта (внешность + стиль + наряд)
    asset: Mapped["Asset"] = relationship()


class StyleRef(TS, Base):
    """Референс оформления клиента: 1–3 фото-примера + что в них нравится. ИИ разбирает стиль (свет, цветовая гамма,
    фон и обстановка, композиция, настроение, обработка); фото идут генератору как пример оформления —
    без копирования предметов, людей и текста. Общий для всех проектов клиента."""
    __tablename__ = "style_refs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")             # что взять из примера (рус., от клиента)
    description: Mapped[str] = mapped_column(Text, default="")      # разбор стиля для генератора (англ., ИИ)
    blocks: Mapped[list] = mapped_column(JSONT, default=list)       # к каким блокам кадров применять
    status: Mapped[str] = mapped_column(String(20), default="draft")   # draft | ready | archived


class StyleRefPhoto(TS, Base):
    __tablename__ = "style_ref_photos"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    style_ref_id: Mapped[int] = mapped_column(ForeignKey("style_refs.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    asset: Mapped["Asset"] = relationship()


class ProductPhoto(TS, Base):
    __tablename__ = "product_photos"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), default="product")   # product | label | packaging
    is_reference: Mapped[bool] = mapped_column(Boolean, default=True)    # отправлять генератору как референс
    position: Mapped[int] = mapped_column(Integer, default=0)
    view: Mapped[str] = mapped_column(String(40), default="", server_default="")         # ракурс: front | back | outer side | … (ИИ, один раз)
    view_note: Mapped[str] = mapped_column(String(400), default="", server_default="")   # какие детали видны на этом фото
    asset: Mapped["Asset"] = relationship()


class ProductProfile(TS, Base):
    """Профиль товара (версии): описание, застёжки, детали, сцены, ракурсы — из него собираются промпты и чек-лист."""
    __tablename__ = "product_profiles"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSONT, default=dict)
    source: Mapped[str] = mapped_column(String(20), default="ai")      # ai | manual | legacy
    model: Mapped[str] = mapped_column(String(120), default="")
    cost_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), default=0.0)


# ───────────── кадры, генерации, проверки, разметка ─────────────

class Frame(TS, Base):
    """Слот кадра товара: промпт + текущий результат."""
    __tablename__ = "frames"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)                     # 1..N (имя файла 01.png в выдаче)
    block: Mapped[str] = mapped_column(String(30), default="")         # studio | detail | usage | scene | lifestyle
    title: Mapped[str] = mapped_column(String(80), default="", server_default="")    # подпись ручного метода съёмки
    model: Mapped[str] = mapped_column(String(120), default="", server_default="")   # своя модель ручного метода
    prompt: Mapped[str] = mapped_column(Text)
    shot_reference_id: Mapped[int | None] = mapped_column(ForeignKey("style_refs.id", ondelete="SET NULL"), nullable=True)
    prompt_source: Mapped[str] = mapped_column(String(20), default="profile")   # profile | manual | legacy
    prompt_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    current_generation_id: Mapped[int | None] = mapped_column(ForeignKey("generations.id", ondelete="SET NULL",
                                                                         use_alter=True, name="fk_frames_current_generation"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="missing")
    # missing | unchecked | pass | review | accepted | rejected
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("product_id", "position"),)


class Generation(TS, Base):
    """Каждая попытка генерации (оплачена). Итоговая — frames.current_generation_id; остальные — история и брак."""
    __tablename__ = "generations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frame_id: Mapped[int] = mapped_column(ForeignKey("frames.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    model: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(80), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")              # промпт, реально ушедший в генератор
    status: Mapped[str] = mapped_column(String(20), default="ok")      # ok | error | pending (ждём результат Polza)
    error: Mapped[str] = mapped_column(Text, default="")
    output_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), default="")       # current | rejected | archived
    cost_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), default=0.0)
    seconds: Mapped[float] = mapped_column(Float, default=0.0)
    paid_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    external_id: Mapped[str] = mapped_column(String(120), default="")  # id задачи Polza
    instruction: Mapped[str] = mapped_column(Text, default="")         # правка: что просили изменить на фото
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # правка: исходная версия кадра
    output_asset: Mapped["Asset"] = relationship()


class QCCheck(TS, Base):
    __tablename__ = "qc_checks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frame_id: Mapped[int] = mapped_column(ForeignKey("frames.id", ondelete="CASCADE"), index=True)
    generation_id: Mapped[int | None] = mapped_column(ForeignKey("generations.id", ondelete="CASCADE"), nullable=True,
                                                      index=True)
    model: Mapped[str] = mapped_column(String(120), default="")
    passed: Mapped[bool] = mapped_column(Boolean)
    reasons: Mapped[list] = mapped_column(JSONT, default=list)
    tech: Mapped[list] = mapped_column(JSONT, default=list)
    counts: Mapped[dict | None] = mapped_column(JSONT, nullable=True)
    info: Mapped[dict] = mapped_column(JSONT, default=dict)            # размер, резкость, токены
    cost_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), default=0.0)
    source: Mapped[str] = mapped_column(String(20), default="gen")    # gen | check | legacy


class Review(TS, Base):
    """Ручное решение человека по кадру. Из этого считается точность проверки (эталон) и берутся заметки для проверки."""
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frame_id: Mapped[int] = mapped_column(ForeignKey("frames.id", ondelete="CASCADE"), index=True)
    generation_id: Mapped[int | None] = mapped_column(ForeignKey("generations.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verdict: Mapped[str] = mapped_column(String(10))                   # ok | bad
    ai_verdict: Mapped[str] = mapped_column(String(10), default="")    # pass | fail | ""
    comment: Mapped[str] = mapped_column(Text, default="")
    note_kind: Mapped[str] = mapped_column(String(20), default="")    # false_alarm | missed | note


class ModerationEvent(TS, Base):
    """Запрещённое содержание, которое сервис остановил: запрос пользователя, готовый кадр или загруженное фото.
    Журнал для мастера — показывает, что сервис фильтрует запрещённое."""
    __tablename__ = "moderation_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    frame_id: Mapped[int | None] = mapped_column(ForeignKey("frames.id", ondelete="SET NULL"), nullable=True)
    source: Mapped[str] = mapped_column(String(20))                   # text | frame | photo
    where: Mapped[str] = mapped_column(String(60), default="")        # пожелания к запуску, правка кадра, профиль товара…
    category: Mapped[str] = mapped_column(String(30), default="")     # lgbt | nazi | drugs | nudity | minors | army | …
    excerpt: Mapped[str] = mapped_column(Text, default="")            # что именно найдено
    action: Mapped[str] = mapped_column(String(20), default="blocked")  # blocked | rejected | hidden


class SpecCache(TS, Base):
    """Ожидания по тексту задания (сколько людей/товара) — кэш, чтобы не платить повторно."""
    __tablename__ = "spec_cache"
    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONT)


# ───────────── очередь, расходы, импорт ─────────────

class Job(TS, Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("budget_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))                      # generate | check | profile | import
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | done | error | cancelled
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    frame_id: Mapped[int | None] = mapped_column(ForeignKey("frames.id", ondelete="CASCADE"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONT, default=dict)
    note: Mapped[str] = mapped_column(String(200), default="")         # «попытка 2/3», «проверка»
    error: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    worker: Mapped[str] = mapped_column(String(60), default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("ix_jobs_queue", "status", "priority", "id"),
        Index("uq_jobs_active_frame", "frame_id", unique=True,
              postgresql_where=text("frame_id IS NOT NULL AND status IN ('queued','running','cancelling','paused')"),
              sqlite_where=text("frame_id IS NOT NULL AND status IN ('queued','running','cancelling','paused')")),
        Index("uq_jobs_active_profile", "product_id", unique=True,
              postgresql_where=text("kind = 'profile' AND status IN ('queued','running','cancelling','paused')"),
              sqlite_where=text("kind = 'profile' AND status IN ('queued','running','cancelling','paused')")),
    )


class Instance(Base):
    """Запущенные копии сервера/воркеров. Сердцебиение раз в 15 с; задания «молчащей» копии считаются прерванными."""
    __tablename__ = "instances"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    host: Mapped[str] = mapped_column(String(200), default="")
    pid: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class UsageEntry(TS, Base):
    """Журнал расходов: каждая оплаченная операция. Основа себестоимости и биллинга клиентов."""
    __tablename__ = "usage_ledger"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    frame_id: Mapped[int | None] = mapped_column(ForeignKey("frames.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))      # generation | qc | count | spec | profile | sort
    model: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(80), default="")
    amount_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), default=0.0)
    tokens: Mapped[dict] = mapped_column(JSONT, default=dict)
    ref: Mapped[str] = mapped_column(String(120), default="")


class ImportSession(TS, Base):
    __tablename__ = "import_sessions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="upload")  # upload | analyzing | ready | applying | done | error
    options: Mapped[dict] = mapped_column(JSONT, default=dict)
    progress: Mapped[list] = mapped_column(JSONT, default=lambda: [0, 0])
    groups: Mapped[list] = mapped_column(JSONT, default=list)
    result: Mapped[dict] = mapped_column(JSONT, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    cost_rub: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), default=0.0)


class ImportFile(TS, Base):
    __tablename__ = "import_files"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("import_sessions.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    rel_path: Mapped[str] = mapped_column(String(500))
    analysis: Mapped[dict] = mapped_column(JSONT, default=dict)       # роль, группа, артикул, текст с этикетки
    asset: Mapped["Asset"] = relationship()
    __table_args__ = (UniqueConstraint("session_id", "rel_path"),)



class BudgetBatch(TS, Base):
    __tablename__ = 'budget_batches'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id',ondelete='CASCADE'),index=True)
    title: Mapped[str] = mapped_column(String(200),default='Генерация')
    budget_rub: Mapped[float|None] = mapped_column(Numeric(18,6,asdecimal=False),nullable=True)
    retry_budget_rub: Mapped[float|None] = mapped_column(Numeric(18,6,asdecimal=False),nullable=True)
    state: Mapped[str] = mapped_column(String(20),default='active')
    pause_reason: Mapped[str] = mapped_column(Text,default='')


class PaidOperation(TS, Base):
    __tablename__ = 'paid_operations'
    id: Mapped[str] = mapped_column(String(36),primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey('clients.id',ondelete='CASCADE'),index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id',ondelete='CASCADE'),index=True)
    job_id: Mapped[int|None] = mapped_column(ForeignKey('jobs.id',ondelete='SET NULL'),nullable=True,index=True)
    batch_id: Mapped[int|None] = mapped_column(ForeignKey('budget_batches.id',ondelete='SET NULL'),nullable=True,index=True)
    product_id: Mapped[int|None] = mapped_column(ForeignKey('products.id',ondelete='SET NULL'),nullable=True)
    frame_id: Mapped[int|None] = mapped_column(ForeignKey('frames.id',ondelete='SET NULL'),nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(120),default='')
    status: Mapped[str] = mapped_column(String(20),default='reserved',index=True)
    external_id: Mapped[str] = mapped_column(String(120),default='')
    reserved_rub: Mapped[float] = mapped_column(Numeric(18,6,asdecimal=False),default=0)
    charged_rub: Mapped[float] = mapped_column(Numeric(18,6,asdecimal=False),default=0)
    cost_rub: Mapped[float] = mapped_column(Numeric(18,6,asdecimal=False),default=0)
    markup: Mapped[float] = mapped_column(Numeric(18,6,asdecimal=False),default=1)
    billable: Mapped[bool] = mapped_column(Boolean,default=True)
    is_retry: Mapped[bool] = mapped_column(Boolean,default=False)
    note: Mapped[str] = mapped_column(Text,default='')
