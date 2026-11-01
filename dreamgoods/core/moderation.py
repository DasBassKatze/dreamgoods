"""Модерация: запрещённое законодательством РФ содержание в запросах и кадрах.

Три линии защиты:
1. текст пользователя (пожелания, промпты, правки, описания моделей и оформления) — стоп-список ниже, до генерации;
2. готовый кадр — пункт «запрещённое содержание» в ИИ-проверке (ai/qc.py): такой кадр не показывается пользователю;
3. загруженные фото товара и оформления — тот же пункт при разборе фото (профиль товара, разбор оформления).

Стоп-список намеренно узкий: ловит однозначные формулировки, а не отдельные слова вроде «радуга» или «флаг»,
чтобы не мешать обычным товарам (радужный — это ещё и расцветка). Спорное ловит ИИ-проверка готового кадра.
"""
import re

# (категория, сообщение пользователю, шаблоны). Шаблоны — по словам, без учёта регистра, ё = е.
CATEGORIES = [
    ("lgbt", "символика и пропаганда ЛГБТ (движение признано в РФ экстремистским)", [
        r"лгбт\w*", r"lgbt\w*", r"lgbtq\w*", r"квир\w*", r"queer", r"гей[\s-]*(?:пар|флаг|прайд|символ)\w*",
        r"(?:радужн\w*|rainbow)\s+(?:флаг\w*|flag\w*)", r"(?:флаг\w*|flag\w*)\s+(?:радуг\w*|rainbow|прайд\w*|pride)",
        r"прайд\w*", r"pride\s+(?:flag|parade|month)", r"гей[\s-]?парад\w*", r"gay\s+(?:couple|pride|flag|kiss)",
        r"лесби\w*", r"lesbian\w*", r"трансгендер\w*", r"transgender\w*", r"однопол\w*", r"same[\s-]sex",
        r"(?:два|две|двое|пара)\s+(?:мужчин|парн|девуш|девочек|женщин)\w*\s+(?:\w+\s+)?(?:целу|обнима|держ\w*\s+за\s+рук)\w*",
        r"two\s+(?:men|women|guys|girls)\s+(?:\w+\s+)?(?:kiss|hug|holding\s+hands)\w*",
        r"смен\w*\s+пол[аеуы]?\b", r"трансфлаг\w*", r"бисексуал\w*", r"bisexual\w*"]),
    ("nazi", "нацистская и экстремистская символика", [
        r"свастик\w*", r"swastika\w*", r"нацист\w*", r"nazi\w*", r"гитлер\w*", r"hitler\w*", r"третий\s+рейх",
        r"third\s+reich", r"(?:руны?|руническ\w*)\s+(?:сс|ss)\b", r"\bss[\s-]?(?:runes?|uniform)", r"зиг\s*хайл\w*", r"sieg\s*heil",
        r"коловрат\w*", r"wolfsangel", r"вольфсангель\w*", r"мертвая\s+голова\s+сс", r"тотенкопф\w*", r"totenkopf",
        r"\bауе\b", r"\bigil\b", r"\bигил\b", r"\bisis\b", r"исламское\s+государство", r"талибан\w*", r"taliban",
        r"колумбайн\w*", r"columbine"]),
    ("drugs", "наркотики и их пропаганда", [
        r"наркотик\w*", r"\bdrugs?\b", r"кокаин\w*", r"cocaine", r"героин\w*", r"heroin", r"марихуан\w*", r"marijuana",
        r"каннабис\w*", r"cannabis", r"(?:лист\w*|листья)\s+(?:конопли|марихуаны|каннабиса)", r"weed\s+leaf",
        r"косяк\w*\s+с\s+травой", r"\bмефедрон\w*", r"\bамфетамин\w*", r"\blsd\b", r"экстази"]),
    ("nudity", "обнажённые и откровенные изображения", [
        r"гол(?:ый|ая|ое|ые|ых|ым|ую|ыми)\b(?!\s+(?:ног|стоп|ступн|кож|пятк|рук|плеч|ладон|запяст|щиколот))", r"обнаж[её]нн\w*", r"\bnude\w*", r"\bnaked\b", r"без\s+(?:одежды|белья|трусов|бюстгальтера)",
        r"topless", r"топлес\w*", r"порн\w*", r"\bporn\w*", r"эротик\w*", r"erotic\w*", r"\bnsfw\b", r"\bsexy\s+nude",
        r"раздень\w*", r"раздеть\w*", r"undress\w*"]),
    ("minors", "сексуализация несовершеннолетних", [
        r"(?:ребен\w*|детск\w*|девочк\w*|мальчик\w*|подрост\w*|школьниц\w*|child|kid|teen\w*|minor)\W+(?:\w+\W+){0,3}"
        r"(?:сексуальн\w*|эротич\w*|соблазн\w*|sexy|seductive|lingerie|нижн\w+\s+бель\w*)",
        r"(?:сексуальн\w*|эротич\w*|sexy|seductive)\W+(?:\w+\W+){0,3}(?:ребен\w*|девочк\w*|школьниц\w*|child|kid|teen\w*)"]),
    ("army", "дискредитация армии и надругательство над госсимволами", [
        r"дискредит\w*", r"(?:сжига\w*|топч\w*|рв[её]т\w*|порван\w*)\s+(?:флаг\w*\s+росси\w*|российск\w+\s+флаг\w*|герб\w*)",
        r"burn\w*\s+(?:the\s+)?russian\s+flag", r"нет\s+войне", r"no\s+to\s+war"]),
    ("extremist_orgs", "символика запрещённых организаций", [
        r"фбк", r"\bfbk\b", r"полк\w*\s+азов\w*", r"azov\s+(?:regiment|battalion)", r"правый\s+сектор", r"right\s+sector", r"свидетел\w+\s+иегов\w*",
        r"jehovah'?s?\s+witness\w*", r"\bаум\s+синрике", r"\bхизб\s*ут[\s-]*тахрир"]),
]

_COMPILED = [(cat, msg, re.compile(r"(?<![\wа-яё])(?:" + "|".join(pats) + r")", re.IGNORECASE))
             for cat, msg, pats in CATEGORIES]
TITLES = {cat: msg for cat, msg, _ in CATEGORIES}
TITLES.update(image="запрещённое содержание на готовом кадре", photo="запрещённое содержание на загруженном фото")


def _norm(text):
    return (text or "").replace("ё", "е").replace("Ё", "Е")


def find(text):
    """Первое совпадение: (категория, текст совпадения) или None."""
    t = _norm(text)
    if not t.strip():
        return None
    for cat, _, rx in _COMPILED:
        m = rx.search(t)
        if m:
            return cat, m.group(0)
    return None


def scan(*texts):
    """Проверяет несколько текстов (и вложенные dict/list — например, профиль товара или ручной план пресета)."""
    for t in texts:
        for s in _strings(t):
            hit = find(s)
            if hit:
                return hit
    return None


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _strings(x)


# пункт для ИИ-проверки готового кадра и разбора загруженных фото (по-английски — так модели точнее)
PROHIBITED_RULE = (
    "PROHIBITED CONTENT (Russian law) — report it in \"prohibited\" if ANY of these is visible anywhere in the image, "
    "including prints on the product, patches, tattoos, posters and backgrounds: the LGBT rainbow pride flag or its "
    "variants (six or more horizontal rainbow stripes as a flag, banner, badge or patch; the progress pride flag; the "
    "transgender pink-blue-white flag), LGBT slogans or symbols, two people of the same sex kissing or in a romantic pose; "
    "swastika or other Nazi symbols (SS runes, Totenkopf, Wolfsangel, Nazi flags); symbols of terrorist organizations; "
    "drugs or drug symbols (cannabis leaf, syringes with drugs); nudity or sexual content; a minor in a sexualized way. "
    "A product that is simply multicolored is NOT prohibited; stripes count only if they clearly form the pride flag pattern.")
PROHIBITED_FIELD = '"prohibited": "<what prohibited content is visible and where, in Russian; empty string if none>"'
