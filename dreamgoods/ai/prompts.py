"""Профиль товара и промпты кадров.

Профиль составляет vision-модель по референсам; из профиля код собирает промпты по правилам ручных промптов
(описание, застёжки со сторонами, «идентично референсам», исключение для ценников, правило сторон, анатомия,
подробные сцены) и чек-лист проверки (базовый по категории + пункты артикула + заметки с ручной проверки).
"""
import re

from ..core.logs import log
from .polza import chat
from ..core.presets import BLOCK_ORDER, BLOCKS, plan_of
from .images import jpeg_data_url

DEFAULT_CHECKLIST = """Category: footwear (boots).
- Exact number of boots required by the shot (one boot, or one pair = 2 boots). No extra, missing, merged or duplicated boots.
- Toe shape, heel type and heel height match the references.
- Sole: thickness, tread/lug pattern and color match. Price stickers or labels on the sole in the references must be ignored and must NOT appear in the result.
- Shaft height relative to the leg (ankle, mid-calf, knee-high, over-the-knee) matches.
- Fastenings (zip, buckle, laces, straps) are present and on the same side as in the references; nothing added.
- Decor (rhinestones, metal toe caps, stitching, panels, chains) matches in placement and pattern.
- Color and material (smooth leather, suede, knit, mesh, patent, stretch) match.
- People: exactly one person with two legs and correct anatomy, boots worn naturally. Product-only shots: no people.
- No text, watermarks, invented logos, collages or grids."""

DEFAULT_LIBRARY = {  # заливается в таблицу category_checklists при первом запуске
    "footwear": {"name": "Обувь", "checklist": DEFAULT_CHECKLIST},
    "clothing": {"name": "Одежда", "checklist": """Category: clothing.
- Garment type, cut, length, fit and silhouette match the references (sleeve length, neckline, collar, hem).
- Color, print/pattern scale and placement, fabric texture (knit, denim, satin, fur) match.
- Closures (buttons, zip, lacing) are present in the same number and position; pockets, seams, pleats, ruffles match.
- Labels, prints and embroidery are not distorted; no invented logos or text.
- Worn naturally: realistic folds and drape, garment not merged with skin or background.
- People: correct anatomy, exactly one person unless the task says otherwise.
- No watermarks, captions, collages or grids."""},
    "bags_accessories": {"name": "Сумки и аксессуары", "checklist": """Category: bags and accessories (bags, belts, wallets, hats, scarves, glasses, watches).
- Shape, size proportions and structure match (rigid/soft, number of compartments, flap shape).
- Hardware (clasps, buckles, rings, chains, zips) matches in number, color (gold/silver) and position.
- Straps/handles: same number, length and attachment points.
- Logos, embossing and monograms are not distorted and not invented.
- Color, material and texture (leather grain, quilting, weave) match.
- If worn or held: correct anatomy, natural grip, realistic scale relative to the body.
- No watermarks, captions, collages or grids."""},
    "jewelry": {"name": "Украшения", "checklist": """Category: jewelry.
- Metal color (yellow/white/rose gold, silver), finish and thickness match.
- Stones: same number, cut, color, size and setting; pattern of stones is identical.
- Shape and proportions match; clasps and links match.
- Realistic scale on the body (ring on a finger, earrings on ears); correct anatomy, five fingers per hand.
- No invented engravings, logos or text; no watermarks, captions, collages or grids."""},
    "cosmetics": {"name": "Косметика и парфюмерия", "checklist": """Category: cosmetics and perfume.
- Packaging shape, cap, pump/dropper and proportions match.
- ALL text on the packaging (brand, product name, volume) is identical and readable; no invented or garbled letters.
- Colors of packaging and of the product itself (cream, liquid, powder shade) match.
- Exact number of product units as required by the task.
- If held or applied: correct hands (five fingers), natural grip, realistic scale.
- No watermarks, captions, collages or grids."""},
    "electronics": {"name": "Электроника", "checklist": """Category: electronics and gadgets.
- Shape, proportions, number and position of buttons, ports, cameras, LEDs and grilles match.
- Logos and markings are not distorted and not invented; screens show no garbled text.
- Color and finish (matte, glossy, metal) match.
- Cables and accessories only if present in the references.
- Correct hands and anatomy if a person holds the device.
- No watermarks, captions, collages or grids."""},
    "home": {"name": "Товары для дома", "checklist": """Category: home goods (decor, kitchenware, textiles, furniture).
- Shape, proportions, number of parts (legs, handles, lids) and their position match.
- Color, pattern, material and texture match.
- Realistic scale relative to the interior and other objects; product stands on a surface, not floating.
- Exact number of product units as required by the task.
- No invented logos or text; no watermarks, captions, collages or grids."""},
    "kids_toys": {"name": "Детские товары и игрушки", "checklist": """Category: kids goods and toys.
- Shape, proportions, colors and number of parts match; faces of toys are not distorted.
- Prints and text on the product/packaging are identical and readable.
- Exact number of product units as required by the task.
- If a person is present: correct anatomy; no unsafe or inappropriate context.
- No watermarks, captions, collages or grids."""},
    "other": {"name": "Другое", "checklist": """Category: general product.
- Shape, proportions, color, material and every visible detail match the references.
- Logos and text are identical and readable; nothing invented.
- Exact number of product units as required by the task; realistic scale; not floating.
- Correct anatomy if people are present.
- No watermarks, captions, collages or grids."""},
}


PROFILE_PROMPT = """You are an assistant of a product photographer who makes marketplace product cards (any category).
You get reference photos of ONE product (one SKU). Study every photo carefully and fill a product profile. From it, a program
assembles very detailed prompts for an image generator that must recreate EXACTLY this product in new photos, and an inspector
checks the results against it. Be as precise and concrete as the EXAMPLE below — vague words produce wrong products.

Rules:
- Describe only the product itself. Price stickers, hang tags, barcodes, store labels, hands of the photographer, packaging film
  and background are NOT part of the product: list them in "ignore".
- Be precise about what generators get wrong: fastenings and EXACTLY on which side they are (inner side = facing the other leg/item),
  where they start and end; number of buttons/stones/straps; logos and text (quote exactly); patterns; sole/base; hardware color.
- If a part looks different from different views, describe each view (e.g. "sole edge seen from the side: black; bottom: beige leather").
- "category" must be one of: {categories}.
- "subcategory_ru": the narrower product type in Russian, plural, 1-2 words, as a shop would name a catalog section
  (e.g. «Ботфорты», «Сапоги», «Ботинки», «Кроссовки», «Платья», «Худи», «Кружки», «Свечи»).
- If the product is worn or held, choose a person, outfit, location and mood that fit its target audience and character,
  described as concretely as in the example. If the product is not used by a person (e.g. a vase), set "person" to "".
- Shots: invent the shots that show THIS product best, each as concrete as the example shots.
  studio_shots — product only on white background, each from a different useful angle (one item, front, back, the set/pair...).
  detail_shots — macro close-ups of the most important details (material texture, hardware, sole, print, seams).
  usage_shots — close-ups of the product in use (worn or held). scene_shots — full-body / wider photos with the person.
  lifestyle_shots — the product alone in a styled setting that fits its audience (interior, still life), no people.
  If a list must have 0 items, return an empty list.
- check_items: what an inspector can verify from the outside, with the view where it is visible.
- All fields in English except those ending with _ru.

EXAMPLE (black over-the-knee stocking boots):
{{"category": "footwear", "category_ru": "Обувь", "subcategory_ru": "Ботфорты", "summary_ru": "Чёрные ботфорты-чулки на шпильке со стразами на носке",
 "object": "pair of black stretch over-the-knee stocking boots", "noun": "boots", "is_pair": true,
 "unit": "exactly one pair of boots (two boots in total, one on each foot)",
 "description": "black stretch over-the-knee stocking boots, pointed toe, thin stiletto heel, crisscross rhinestone straps over the toe",
 "identity_parts": "shape, toe, heel, sole, material, color",
 "fastenings": "a long zip on the inner side of the shaft, from the ankle up to about knee height; the upper part of the shaft has no zip; no other fastenings",
 "asymmetric_details": "zip, lacing, buckle, strap, pull tab, decorative insert",
 "key_details": ["crisscross rhinestone straps over the toe of each boot", "thin black stiletto heel"],
 "ignore": ["white price sticker on the sole"], "shadow": "the sole",
 "usage": "worn on the legs of a woman", "person_noun": "woman", "body_focus": "legs, knees and feet",
 "close_up": "close-up of an adult woman's legs wearing these exact boots, framed from mid-thigh down",
 "person": "a strikingly beautiful adult woman, 25 years old, model appearance, slim toned figure, long legs, long glossy dark brown hair, flawless natural makeup, confident and alluring expression",
 "outfit": "a fitted black satin mini dress", "outfit_visibility": "with the hem above the top of the boots so the whole boot is visible",
 "location": "a luxurious hotel lobby with dark marble floors and warm bokeh lights",
 "mood": "bold, glamorous poses that emphasize long legs",
 "bold_pose": "Bold and dynamic pose: strong hip shift, one leg forward and slightly bent, elongated legs, confident direct gaze, high-fashion editorial energy.",
 "studio_shots": ["one boot, outer side view, standing upright", "one boot, front view, toe facing the camera",
   "one boot, back view, showing the heel and all back details (zip, seams, decor)", "a pair of boots, three-quarter front view, one slightly behind the other"],
 "usage_shots": ["side view, a pose that shows the full silhouette of the boot and heel", "three-quarter front view, taking a step forward"],
 "scene_shots": ["three-quarter front view, standing, weight on one leg, strong hip shift, a pose that emphasizes the legs and the boots"],
 "detail_shots": ["macro of the rhinestone straps over the toe, three-quarter front angle"],
 "lifestyle_shots": ["the pair standing on a dark marble floor next to a velvet armchair, warm evening light"],
 "check_items": ["zip on the inner side of each boot — visible in inner side and back views", "rhinestone straps over the toe — visible in front and side views"]}}

Reply with ONLY one JSON object with exactly these fields, no markdown. Exact number of items: studio_shots: {n_studio},
detail_shots: {n_detail}, usage_shots: {n_worn}, scene_shots: {n_full}, lifestyle_shots: {n_lifestyle}."""

TAIL_GENERIC = ("Photorealistic, high resolution. One single photo: no grid, no collage, "
                "no text, no numbers, no labels, no watermarks, no frames.")
TAIL_PRINTED = ("Photorealistic, high resolution. One single photo: no grid, no collage, no added text, numbers, labels or "
                "watermarks, no frames; only the text and logos that are printed on the product itself, exactly as in the references.")

PROFILE_TEXT = ("category", "category_ru", "subcategory_ru", "summary_ru", "object", "noun", "unit", "description", "identity_parts", "fastenings",
                "asymmetric_details", "shadow", "usage", "person_noun", "body_focus", "close_up", "person", "outfit",
                "outfit_visibility", "location", "mood", "bold_pose", "style")
PROFILE_LISTS = ("key_details", "ignore", "check_items", "studio_shots", "detail_shots", "usage_shots", "scene_shots",
                 "lifestyle_shots")


def _lines(v):
    if isinstance(v, str):
        v = v.splitlines()
    return [str(x).strip(" -•\t") for x in (v or []) if str(x).strip(" -•\t")]


def _no_person(prof):
    u = (prof.get("usage") or "").strip().lower()
    return not (prof.get("person") or "").strip() or u in ("", "none", "no", "n/a")


def _dot(s):
    s = (s or "").strip()
    return s if not s or s[-1] in ".!?" else s + "."


# запасные кадры, если в профиле меньше кадров нужного вида, чем в плане пресета
FILLER = {
    "studio": ["front view", "side view", "back view", "three-quarter front view", "top view", "three-quarter back view",
               "the product at a slight angle showing its depth", "detail-revealing angle from below"],
    "detail": ["macro of the most distinctive detail", "macro of the material texture", "macro of the hardware or fastening",
               "macro of the sole, base or edge"],
    "worn": ["close-up in use, three-quarter front view", "close-up in use, side view", "close-up in use, in motion",
             "close-up in use, back view", "close-up in use, from slightly above", "close-up in use, relaxed natural pose"],
    "full": ["full-body, standing, three-quarter front view", "full-body, walking towards the camera",
             "full-body, side view, confident pose", "full-body, seated, relaxed pose"],
    "lifestyle": ["the product in a styled setting that fits its audience, soft daylight",
                  "the product on a surface with a few complementary props, top-down view",
                  "the product in a cozy interior, warm evening light", "the product outdoors in a natural setting"],
}


def _fill(shots, key, n):
    shots = list(shots)[:n]
    for extra in FILLER[key]:
        if len(shots) >= n:
            break
        if extra not in shots:
            shots.append(extra)
    return shots


def _ctx(prof):
    """Общие части промптов кадра из профиля: фиксация товара (lock), анатомия, хвост и т. п."""
    noun = prof.get("noun") or prof.get("object") or "product"
    desc = (prof.get("description") or prof.get("object") or "").strip().rstrip(".")
    lock = f"Product reference: the attached photos show {desc}."
    fast = (prof.get("fastenings") or "").strip().rstrip(".")
    if fast:
        lock += f" Fastenings of this model: {fast}."
    if prof.get("key_details"):
        lock += " Key details that must be preserved exactly: " + "; ".join(x.rstrip(".") for x in prof["key_details"]) + "."
    parts = prof.get("identity_parts") or "shape, proportions, material, color"
    be = "are" if prof.get("is_pair") or noun.endswith("s") else "is"
    usage = f"{prof.get('usage') or ''} {prof.get('body_focus') or ''} {prof.get('close_up') or ''}".lower()
    shadow = prof.get("shadow") or "the product"
    clean = f"{shadow} must look clean" if shadow != "the product" else "the product must look clean"
    m = re.search(r"\b(legs?|feet|foot|hands?|ears?|arms?|wrists?|fingers?)\b", usage)
    limb = {"legs": "leg", "feet": "foot", "hands": "hand", "ears": "ear", "arms": "arm", "wrists": "wrist",
            "fingers": "finger"}.get(m.group(1), m.group(1)) if m else ""
    other = f"the side facing the other {limb}" if limb else "the side facing the other one"
    verb = ("wearing" if re.search(r"\b(worn|wear|wearing|on the (legs|feet|body|head|wrist|neck|ears))\b", usage) else
            "holding" if re.search(r"\b(held|hold|holding|in (a|the) hand)\b", usage) else "using")
    lock += (f" The {noun} must be identical to the reference photos: same {parts} and every detail. "
             "Do not add, remove or change any elements. Exception: if there is a price sticker, barcode or store sticker, "
             f"price tag or a hang tag on a string anywhere on the {noun} in the reference photos, ignore it: it is not part of the product, "
             f"do not reproduce it, {clean}.")
    if prof.get("ignore"):
        lock += " Also ignore, do not reproduce: " + "; ".join(x.rstrip(".") for x in prof["ignore"]) + "."
    asym = (prof.get("asymmetric_details") or "").strip()
    if asym or fast:
        examples = asym or "zip, lacing, buckle, strap, pull tab, decorative insert"
        if prof.get("is_pair"):
            lock += (f" Fastenings and asymmetric details ({examples}) must stay exactly on the same side and in the same "
                     f"position as in the reference photos. Left and right {noun} are mirror images of each other: a detail on "
                     f"the inner side ({other}) stays on the inner side of both {noun}, a detail on the outer side "
                     f"stays on the outer side, a detail at the back stays at the back. Do not move, add, duplicate or invent fastenings.")
        else:
            lock += (f" Fastenings and asymmetric details ({examples}) must stay exactly on the same side and in the same "
                     "position as in the reference photos: left stays left, right stays right, front stays front, back stays back. "
                     "Do not move, add, duplicate or invent fastenings.")
    unit = prof.get("unit") or f"exactly one {noun}"
    person_noun = prof.get("person_noun") or "person"
    body = prof.get("body_focus") or "arms, hands, legs and feet"
    anatomy = (f"Anatomy: exactly one {person_noun} with a natural body — one head, two arms, two legs, five fingers on each "
               f"hand — {verb} {unit}. Natural, anatomically correct {body}; limbs are not intertwined and do not merge.")
    location = prof.get("location") or "a bright neutral interior"
    mood = prof.get("mood") or prof.get("style") or "natural, elegant"
    nobody = _no_person(prof)
    printed = re.search(r"\btext\b|\blogo|\bprint|\blettering|\bbrand name|['\"«]",
                        " ".join([prof.get("description") or ""] + list(prof.get("key_details") or [])), re.I)
    TAIL = TAIL_PRINTED if printed else TAIL_GENERIC
    return dict(noun=noun, lock=lock, be=be, shadow=shadow, unit=unit, anatomy=anatomy, location=location, mood=mood,
                nobody=nobody, TAIL=TAIL)


def build_prompts(prof, plan=None, market=None):
    """Промпты кадров из профиля — по тем же правилам, что и ручные промпты для сапог:
    описание + застёжки со сторонами + «идентично референсам» + исключение для ценников/бирок + правило сторон
    + блок кадра (белый фон / крупно в использовании / общий план) + анатомия + единый хвост.
    Защитные правила вставляет код, а не модель."""
    c = _ctx(prof)
    noun, lock, be, shadow, unit, anatomy = c["noun"], c["lock"], c["be"], c["shadow"], c["unit"], c["anatomy"]
    location, mood, nobody, TAIL = c["location"], c["mood"], c["nobody"], c["TAIL"]
    plan = plan or {k: len(prof.get(BLOCKS[k][1]) or []) for k in BLOCK_ORDER}
    shots = {k: _fill(prof.get(BLOCKS[k][1]) or [], k, plan.get(k, 0)) for k in BLOCK_ORDER}
    rows = []
    cover = bool(market and market.get("cover") and shots["studio"])
    for n, s in enumerate(shots["studio"]):
        if n == 0 and cover:      # обложка карточки по правилам площадки
            extra = (market.get("cover_extra") or "").strip().rstrip(".")
            rows.append(f"{lock} Main marketplace cover photo (the first photo of the product card for {market.get('name')}): "
                        f"{market.get('cover_bg') or 'a pure white background (#FFFFFF)'}, soft even studio lighting, "
                        f"subtle natural shadow under {shadow}, the {noun} centered and filling {market.get('cover_fill') or 'most of the frame'}, "
                        f"no props, no people{', ' + extra if extra else ''}. Shot: {_dot(s)} {TAIL}")
            continue
        rows.append(f"{lock} Vertical e-commerce product photo on a pure white background (#FFFFFF), soft even studio lighting, "
                    f"subtle natural shadow under {shadow}, product centered and filling most of the frame, no people. "
                    f"Shot: {_dot(s)} {TAIL}")
    for s in shots["detail"]:
        rows.append(f"{lock} Vertical macro close-up product photo of a detail of the {noun}: clean light neutral background, "
                    f"soft studio lighting, shallow depth of field, the detail in sharp focus and true to the references, "
                    f"no people. Shot: {_dot(s)} {TAIL}")
    for s in shots["worn"]:
        if nobody:
            rows.append(f"{lock} Vertical close-up lifestyle product photo: {unit} placed naturally in {location}. "
                        f"Mood: {mood}. No people. The {noun} {be} sharp and fully visible. Shot: {_dot(s)} {TAIL}")
        else:
            close = prof.get("close_up") or f"close-up of the product in use: {prof.get('usage')}"
            rows.append(f"{lock} Vertical fashion photo: {close.rstrip('.')}. Location: {location}. Mood: {mood}. "
                        f"The {noun} {be} always sharp and fully visible. Editorial fashion quality. {anatomy} "
                        f"Shot: {_dot(s)} {TAIL}")
    for s in shots["full"]:
        if nobody:
            rows.append(f"{lock} Vertical wide lifestyle photo: {unit} in {location}. Mood: {mood}. No people. "
                        f"The {noun} {be} the clear focus, sharp and fully visible. Shot: {_dot(s)} {TAIL}")
        else:
            outfit = prof.get("outfit") or ""
            vis = prof.get("outfit_visibility") or f"so that the {noun} {be} fully visible"
            out_txt = f" Outfit: {outfit.rstrip('.')}, {vis.rstrip('.')}." if outfit else ""
            bold = _dot(prof.get("bold_pose") or "Bold and dynamic pose, confident direct gaze, high-fashion editorial energy.")
            rows.append(f"{lock} Vertical full-body fashion photo. Model: {prof.get('person')}, tasteful high-fashion editorial style."
                        f"{out_txt} Location: {location}. Mood: {mood}, dynamic high-fashion energy. "
                        f"The {noun} {be} sharp and fully visible. {anatomy} Shot: {_dot(s)} {bold} {TAIL}")
    for s in shots["lifestyle"]:
        rows.append(f"{lock} Vertical styled lifestyle still life photo: {unit} in {location}. Mood: {mood}. No people. "
                    f"The {noun} {be} the clear focus, sharp and fully visible, realistic scale. Shot: {_dot(s)} {TAIL}")
    return rows


def build_manual(prof, items, market=None):
    """Ручной план: свои методы съёмки клиента. Текст метода вставляется как «Shot:», а фиксацию товара, анатомию
    и правила обложки добавляет код. Возвращает [(промпт, подпись, ключ блока, модель)]."""
    c = _ctx(prof)
    noun, lock, be, anatomy, nobody, TAIL = c["noun"], c["lock"], c["be"], c["anatomy"], c["nobody"], c["TAIL"]
    person = (prof.get("person") or "an adult model").strip().rstrip(".")
    rows, first = [], True
    for it in items:
        text = it["prompt"].replace("{товар}", f"the {noun}").replace("{product}", f"the {noun}").strip().rstrip(".")
        for i in range(1, it["count"] + 1):
            var = (f" Variant {i} of {it['count']}: vary the camera angle and pose slightly, keep the same idea."
                   if it["count"] > 1 else "")
            b = it["block"]
            if b == "studio" and first and market and market.get("cover"):
                extra = (market.get("cover_extra") or "").strip().rstrip(".")
                head = (f"Main marketplace cover photo (the first photo of the product card for {market.get('name')}): "
                        f"{market.get('cover_bg') or 'a pure white background (#FFFFFF)'}, the {noun} centered and filling "
                        f"{market.get('cover_fill') or 'most of the frame'}, no people{', ' + extra if extra else ''}.")
            elif b == "studio":
                head = "Vertical e-commerce product photo, no people."
            elif b == "detail":
                head = (f"Vertical macro close-up product photo of a detail of the {noun}: the detail in sharp focus and true "
                        "to the references, no people.")
            elif b == "lifestyle" or nobody:
                head = (f"Vertical styled lifestyle still life photo, no people. The {noun} {be} the clear focus, sharp and "
                        "fully visible, realistic scale.")
            elif b == "worn":
                head = (f"Vertical fashion photo of the product in use. Model: {person}, tasteful high-fashion editorial style. "
                        f"The {noun} {be} always sharp and fully visible. {anatomy}")
            else:
                head = (f"Vertical full-body fashion photo. Model: {person}, tasteful high-fashion editorial style. "
                        f"The {noun} {be} sharp and fully visible. {anatomy}")
            rows.append((f"{lock} {head} Shot: {text}.{var} {TAIL}", it["title"], b, it.get("model") or ""))
            first = False
    return rows


def frame_label(prompt):
    pl = prompt.lower()
    if "main marketplace cover" in pl:
        block = "Обложка"
    elif "macro close-up" in pl:
        block = "Деталь"
    elif "fashion photo of the product in use" in pl:
        block = "На человеке"
    elif "lifestyle still life" in pl:
        block = "Лайфстайл"
    elif "white background" in pl:
        block = "Белый фон"
    elif "e-commerce product photo" in pl:
        block = "Товар"
    elif "wide lifestyle" in pl:
        block = "Общий план"
    elif "close-up lifestyle" in pl:
        block = "В использовании"
    elif "full-body" in pl or "full body" in pl:
        block = "Общий план"
    elif "legs" in pl:
        block = "На ноге"
    else:
        block = "Кадр"
    m = re.search(r"Shot:\s*([^.]*)", prompt)
    return block, (m.group(1).strip() if m else "")

def block_of(prompt):
    """Блок кадра по тексту промпта: studio | detail | usage | scene | lifestyle."""
    b, _ = frame_label(prompt)
    return {"Белый фон": "studio", "Обложка": "studio", "Товар": "studio", "Деталь": "detail", "Общий план": "scene", "Лайфстайл": "lifestyle"}.get(
        b, "usage" if b != "Кадр" else "")


def make_profile(st, sku, refs, categories, label_hint, trace, person_hint="", style_hint=""):
    """refs: [bytes] выбранных фото. categories: {key: name}. Возвращает словарь профиля и стоимость."""
    if not refs:
        raise RuntimeError("не выбрано ни одного фото-референса")
    plan = plan_of(st)
    system = PROFILE_PROMPT.format(categories=", ".join(categories), **{f"n_{k}": plan[k] for k in BLOCK_ORDER})
    content = [{"type": "text", "text": f"Reference photos of the product (SKU '{sku}'):"
                + (f"\nText read from the product's label/tag photos (use it for brand, article, color and material names; "
                   f"do NOT draw the label): {label_hint}" if label_hint else "")
                + (f"\nThe client's model (the person in all usage and scene shots) is fixed: {person_hint}. "
                   "If the product is worn or held, write this exact person into \"person\" and \"person_noun\", "
                   "and choose the outfit, location, mood and poses that suit this person and the product." if person_hint else "")
                + (f"\nThe client's visual style for the photos: {style_hint}. Choose locations, mood and lifestyle scenes "
                   "that fit this style." if style_hint else "")}]
    for data in refs[:8]:
        content.append({"type": "image_url", "image_url": {"url": jpeg_data_url(data, 1024)}})
    model = (st.get("profile_model") or "").strip() or st.get("qc_model")
    log.info("%s → профиль товара: %s · фото %d", trace, model, min(len(refs), 8))
    res, cost, secs = chat(st, model, system, content, trace, "профиль", 5000, "none")
    cat = str(res.get("category") or "other").strip().lower()
    if cat not in categories:
        cat = "other" if "other" in categories else next(iter(categories))
    prof = {k: str(res.get(k) or "").strip() for k in PROFILE_TEXT}
    prof.update({k: _lines(res.get(k)) for k in PROFILE_LISTS})
    prof["category"] = cat
    prof["category_ru"] = prof["category_ru"] or categories.get(cat, cat)
    prof["is_pair"] = bool(res.get("is_pair"))
    for k in BLOCK_ORDER:
        prof[BLOCKS[k][1]] = _fill(prof[BLOCKS[k][1]], k, plan[k])
    log.info("%s профиль за %.1f с, %.2f ₽: %s · %s · застёжки: %s · деталей %d, игнор %d, кадров %d+%d+%d",
             trace, secs, cost, prof["category_ru"], prof["object"], prof["fastenings"][:80] or "—", len(prof["key_details"]),
             len(prof["ignore"]), *[len(prof[BLOCKS[k][1]]) for k in ("studio", "worn", "full")])
    log.info("%s кадров по плану: %s", trace, " · ".join(f"{BLOCKS[k][0].split(',')[0].split(' (')[0]} {len(prof[BLOCKS[k][1]])}"
                                                      for k in BLOCK_ORDER if plan[k]))
    return prof, cost, model


def checklist_text(base, prof, notes):
    """Чек-лист для проверки. notes: [(kind, text)] — замечания с ручной проверки этого артикула."""
    out = base
    if prof:
        extra = list(prof.get("key_details") or []) + list(prof.get("check_items") or [])
        if prof.get("fastenings"):
            extra.insert(0, "fastenings: " + prof["fastenings"])
        if extra:
            out += "\n\nSKU-specific items (" + (prof.get("object") or "this product") + "):\n" + "\n".join(f"- {x}" for x in extra)
        if prof.get("ignore"):
            out += "\nIgnore (not part of the product, must NOT appear in the result): " + "; ".join(prof["ignore"])
    fa = [t for k, t in notes if k == "false_alarm"][-8:]
    ms = [t for k, t in notes if k == "missed"][-8:]
    nt = [t for k, t in notes if k == "note"][-5:]
    if fa:
        out += ("\n\nHUMAN REVIEWER NOTES for this SKU — these were FALSE ALARMS in previous frames, do NOT report such things "
                "as defects (notes are in Russian):\n" + "\n".join(f"- {x}" for x in fa))
    if ms:
        out += ("\n\nHUMAN REVIEWER NOTES — defects the inspector MISSED before, check them carefully:\n"
                + "\n".join(f"- {x}" for x in ms))
    if nt:
        out += "\n\nOther reviewer notes:\n" + "\n".join(f"- {x}" for x in nt)
    return out


SUBCAT_PROMPT = """You sort products of an online shop into catalog sections. For each product give "subcategory_ru": the narrower
product type in Russian, plural, 1-2 words (e.g. «Сапоги», «Ботинки», «Ботфорты», «Кроссовки», «Платья», «Кружки»).
Use the SAME wording for products of the same type so they group together.
Reply with ONLY JSON: {"items": [{"id": <id>, "subcategory_ru": "..."}]}"""


def subcategories(st, items, trace):
    """items: [{id, category, summary}] → {id: подраздел}. Один текстовый запрос на всю пачку."""
    text = "\n".join(f"{x['id']}: {x['category']} — {x['summary']}" for x in items)
    res, cost, _ = chat(st, st.get("profile_model") or st.get("qc_model"), SUBCAT_PROMPT,
                        [{"type": "text", "text": "Products:\n" + text}], trace, "подразделы", 60 * len(items) + 300, "none")
    out = {}
    for it in res.get("items") or []:
        try:
            sub = str(it.get("subcategory_ru") or "").strip()
            if sub:
                out[int(it.get("id"))] = sub[:60]
        except (TypeError, ValueError, AttributeError):
            continue
    return out, cost


# ───────── правка готового фото по промпту ─────────

def edit_prompt(instruction, n_product, person=False):
    """Промпт правки: фото 1 — текущая версия кадра, фото 2…N — настоящие фото товара (чтобы товар не «поплыл»)."""
    refs = (f" Photos 2–{n_product + 1} are photos of the real product: use them ONLY to keep the product exactly accurate "
            "(shape, color, materials, stitching, logos, proportions) — do not copy their background or composition."
            if n_product else "")
    keep_person = (" Keep the same person: identical face, hair, body, skin tone, outfit and pose unless the edit asks "
                   "otherwise." if person else "")
    return ("Edit photo 1 — a finished marketplace product photo. Apply ONLY this change, requested by the user "
            f"(the request may be in Russian): «{instruction.strip()}».\n"
            "Everything not mentioned in the request must stay exactly as in photo 1: composition, framing, camera "
            "angle, crop, lighting, colors, background and props. The product must remain identical to the real product "
            "— never redesign, recolor, simplify or invent details of it." + keep_person + refs +
            "\nReturn one photorealistic photo with the same aspect ratio, no text, no watermarks, no collages.")
