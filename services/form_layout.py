"""MVP imtihon formasi joylashuvi va javoblar formati (1–45 savol).

MVP formasi uch bo'limdan iborat (dizayn qarori — ma'lumotlar bazasi sxemasi
**o'zgarmaydi**):

    1–32    →  ``A B C D``        (4 variantli yopiq savol)
    33–35   →  ``A B C D E F``    (6 variantli yopiq savol)
    36–45   →  ``OPEN_NUMERIC``   (ochiq, sonli javob)

Modul ikki joyda ishlatiladi:
    1. ``POST /api/verify-code`` — Web App kartochkalari uchun joylashuvni
       beradi (``layout_ranges``);
    2. ``POST /api/submit`` — tuzilgan javoblarni tahlil qilib, bazadagi
       kanonik matnga aylantiradi (``parse_structured_answers`` +
       ``build_canonical``).

Diqqat: bu modul taqdimot qoidalaridan tashqari baholash **qoidasini ham**
belgilaydi (`score_items`). Sonli javoblar kanonik matnning ``|`` dan keyin
saqlanadi va ``services.answer_key`` bu qismni o'qimaydi — Rasch esa avvalgidek
``ItemOutcome`` ro'yxati bilan ishlaydi (faqat `is_correct` va `difficulty`).

Baholash yo'llari (opt-in)
--------------------------
* **Legacy** (o'zgarishsiz): ``1A2B…`` + ``|36:12.5`` — pozitsiya bo'yicha
  bitta sonli javob (``36``);
* **MVP**: 1–32 → ``A–D``, 33–35 → ``A–F``, 36–45 → sonli;
* **Qismli** (Phase 3, Step 3): ``|36a:√5,36b:3/7`` — har bir belgi
  (``36a``, ``36b``) **mustaqil** savol. Savollar to'plamini kalitdagi belgilar
  beradi (masalan 35 variant + 20 qism = 55 savol), shu sababli xom ball va
  Rasch to'plami barqaror qoladi.

Eslatma (eski cheklov — qismli kalitda hal qilindi)
--------------------------------------------------
Kalit formati endi MVP formasida ``A–F`` va sonli javoblarni ham biladi;
qismli kalitda (``36a``) esa har bir qism **alohida** baholanadi.

* 33–35 savollarning ``E``/``F`` javoblari MVP kalitida baholanadi;
* 36–45 sonli javoblar ham baholanadi — qismli kalitda (``36a``, ``36b``)
  har bir qism alohida savol, shu sababli xom ball va Rasch to'plami ham
  55 savolga mos bo'ladi.
"""

from __future__ import annotations

import re
from typing import Any, Final, Mapping, NamedTuple, Sequence

import config
from database.models import SKIPPED
from services import answer_key, math_expr

# Kartochka turlari (`kind` maydoni — Web App shu qiymatlar bo'yicha chizadi).
OPTION_KIND: Final[str] = "option"
NUMERIC_KIND: Final[str] = "numeric"

# Variantlar to'plami.
MCQ_OPTIONS_4: Final[tuple[str, ...]] = ("A", "B", "C", "D")
MCQ_OPTIONS_6: Final[tuple[str, ...]] = ("A", "B", "C", "D", "E", "F")

# (boshlanish, tugash, variantlar) — `None` → sonli (ochiq) javob.
_SECTIONS: Final[tuple[tuple[int, int, tuple[str, ...] | None], ...]] = (
    (1, 32, MCQ_OPTIONS_4),
    (33, 35, MCQ_OPTIONS_6),
    (36, 45, None),
)

# Sonli javob formati: "12", "-3.5", "12,5" (vergul nuqtaga almashtiriladi).
# Phase 2: kasr xonalar 15 tagacha (matematik ifodalar aniq hisoblanadi).
_NUMERIC_RE: Final[re.Pattern[str]] = re.compile(r"^-?\d{1,7}(?:[.,]\d{1,15})?$")


def options_of(position: int) -> tuple[str, ...]:
    """Savol pozitsiyasi uchun ruxsat etilgan variantlar (sonli savolda — bo'sh)."""
    for start, end, options in _SECTIONS:
        if start <= position <= end:
            return options or ()
    return ()


# --- Qismlar (a/b) — Phase 3: 36–45 uchun YAGONA MANBA ----------------------
# Test qog'ozida ham ochiq savollar (`36–45`) **ikki qismdan** iborat: `a)` va
# `b)`. Shu sababli forma yaratishda har bir pozitsiya **doim** ikkita savolga
# bo'linadi (`36a`, `36b`) — kalitda qiymat bo'lmasa ham. Qiymatsiz qism
# baholashda doim "noto'g'ri" hisoblanadi (`answer_spec.accepted = []`).
_PART_SECTIONS: Final[tuple[tuple[int, int, tuple[str, ...]], ...]] = (
    (36, 45, ("a", "b")),
)


def parts_of(position: int) -> tuple[str, ...]:
    """Pozitsiya qismlari: `36` → `("a", "b")`; `1` → `("",)`.

    Bo'sh bo'lmagan qism faqat ochiq (sonli) savollarda bo'ladi va har bir
    qism **mustaqil savol** (o'z `b` si bilan). Qism bo'lmasa — `("",)`.
    """
    for start, end, parts in _PART_SECTIONS:
        if start <= position <= end:
            return parts
    return ("",)


# --- Savol belgisi (label) — Phase 3: tahlil va baholash qatlami -------------
# Legacy o'qish uchun `label == str(position)`; qismli savolda `"36a"`/`"36b"`.
# `score_items` qismli kalitda har bir belgini **mustaqil** baholaydi
# (`score_labeled_items`), legacy kalitda esa xulq avvalgidek qoladi.
def label_of(position: int, part: str | None = None) -> str:
    """Savol belgisi: `(36, None)` → `"36"`; `(36, "a")` → `"36a"`.

    Raises:
        ValueError: pozitsiya musbat butun son bo'lmasa yoki qism noto'g'ri.
    """
    return answer_key.label_of(position, part)


def split_label(label: str) -> tuple[int, str | None]:
    """Belgidan pozitsiya va qismni ajratadi: `"36a"` → `(36, "a")`.

    `"36"` → `(36, None)`; noto'g'ri belgi — `ValueError` (xavfsiz to'xtaydi).
    """
    return answer_key.split_label(label)


def layout_ranges(total_questions: int) -> list[dict[str, Any]]:
    """Imtihon savollari bo'yicha taqdimot bo'limlarini qaytaradi.

    Har bir bo'lim: ``{"from": 1, "to": 32, "kind": "option", "options": [...]}``.
    Faqat ``total_questions`` ichida qolgan pozitsiyalar kiritiladi.
    """
    total = int(total_questions)
    ranges: list[dict[str, Any]] = []
    for start, end, options in _SECTIONS:
        last = min(end, total)
        if last < start:
            break
        ranges.append(
            {
                "from": start,
                "to": last,
                "kind": OPTION_KIND if options else NUMERIC_KIND,
                "options": list(options) if options else [],
            }
        )
    return ranges


def layout_with_parts(
    total_questions: int, parts: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """Joylashuv + (ixtiyoriy) **qismlar**: 36–45 → ``"parts": ["a","b"]``.

    Bu — Web App kartochkalari uchun **yagona manba**: ham v1
    (``/api/verify-code``), ham ``/api/v2/*`` shu funksiyadan foydalanadi.
    Ilgari mantiq faqat v2'da bor edi va sessiyasiz imtihonlarda a/b
    kataklari **yo'qolib qolardi**.

    ``parts`` bo'sh bo'lsa — ``layout_ranges`` natijasi **aynan** qaytadi
    (legacy imtihonlar o'zgarmaydi). ``parts`` (masalan ``["36a","36b"]``)
    berilsa, sonli bo'lim pozitsiyalar bo'yicha qism to'plamiga ko'ra
    bo'linadi va har bir bo'lakka ``parts`` qo'shiladi.
    """
    ranges = layout_ranges(int(total_questions))

    position_parts: dict[int, list[str]] = {}
    for label in parts or ():
        try:
            number, part = split_label(str(label))
        except ValueError:
            continue
        if part:
            position_parts.setdefault(number, []).append(part)
    if not position_parts:
        return ranges

    expanded: list[dict[str, Any]] = []
    for rng in ranges:
        groups: list[dict[str, Any]] = []
        for position in range(int(rng["from"]), int(rng["to"]) + 1):
            key = sorted(set(position_parts.get(position, ())))
            if groups and groups[-1]["parts"] == key:
                groups[-1]["to"] = position
            else:
                groups.append({"from": position, "to": position, "parts": key})
        for group in groups:
            entry: dict[str, Any] = {
                "from": group["from"],
                "to": group["to"],
                "kind": rng["kind"],
                "options": list(rng["options"]),
            }
            if group["parts"]:
                entry["parts"] = list(group["parts"])
            expanded.append(entry)
    return expanded


def normalize_numeric(raw: Any) -> str:
    """Sonli javobni tekshiradi va normallashtiradi (``"12,5"`` → ``"12.5"``).

    Raises:
        ValueError: qiymat son emas yoki ruxsat etilgan formatda bo'lmasa.
    """
    text = str(raw).strip().replace(",", ".")
    if not _NUMERIC_RE.match(text):
        raise ValueError(f"Sonli javob noto'g'ri: {raw!r}. Masalan: 12 yoki 12.5")
    return text


def _split_answer_key(key: Any, total: int) -> tuple[int, str | None]:
    """Javob kalitini (`36` yoki `36a`) → `(pozitsiya, qism)` ga ajratadi.

    Raises:
        ValueError: kalit son emas, oraliqdan tashqarida yoki qism noto'g'ri.
    """
    text = str(key).strip()
    try:
        number, part = split_label(text)
    except ValueError as exc:
        raise ValueError(f"Savol raqami son emas: {key!r}") from exc
    if not 1 <= number <= int(total):
        raise ValueError(
            f"Savol raqami oraliqdan tashqarida: {number}. 1 dan {total} gacha."
        )
    return number, part


def parse_structured_answers(
    raw: Mapping[Any, Any], total_questions: int
) -> tuple[list[str], dict[int | str, str]]:
    """Web App yuborgan javoblar xaritasini tahlil qiladi.

    Kalit **pozitsiya** (``36``) yoki **belgi** (``36a``, ``36b``) bo'lishi
    mumkin: qismli savollarda ``a``/``b`` **alohida** saqlanadi (``numeric``
    kaliti — belgi), ``build_canonical`` esa ularni ``|36a:…,36b:…``
    ko'rinishida yozadi. Qismsiz (legacy) oqim **o'zgarmaydi**.

    Qaytaradi: ``(harflar, sonli_javoblar)``. Harflar ro'yxati uzunligi
    ``total_questions`` ga teng, javob berilmagan o'rinlar ``SKIPPED`` ("X").

    Raises:
        ValueError: pozitsiya/belgi oraliqdan tashqarida, variant ruxsat
            etilmagan yoki sonli javob formati noto'g'ri bo'lsa.
    """
    total = int(total_questions)
    letters = [SKIPPED] * total
    numeric: dict[int | str, str] = {}

    for key, value in raw.items():
        position, part = _split_answer_key(key, total)

        text = "" if value is None else str(value).strip()
        if not text or text.upper() == SKIPPED:
            continue

        if part:
            # Qism (`36a`/`36b`) — faqat ochiq (sonli) savollarda bo'ladi.
            if options_of(position):
                raise ValueError(
                    f"{position}-savol qismlarga bo'linmaydi (belgi: {key!r})."
                )
            numeric[label_of(position, part)] = normalize_numeric(text)
            continue

        options = options_of(position)
        if options:
            letter = text.upper()
            if letter not in options:
                raise ValueError(
                    f"{position}-savol uchun ruxsat etilmagan javob: {text!r}. "
                    f"Ruxsat etilganlar: {', '.join(options)}."
                )
            letters[position - 1] = letter
        else:
            numeric[position] = normalize_numeric(text)

    return letters, numeric


def build_canonical(letters: Sequence[str], numeric: Mapping[int | str, Any]) -> str:
    """Harflar va sonli javoblarni bazadagi kanonik matnga aylantiradi.

    Masalan: ``"1A2B...45X|36:12.5,37:3"``. ``|`` dan keyingi qism MVP
    formatining belgisi (opt-in) bo'lib, eski kalitlarda umuman bo'lmaydi.

    Phase 3 Step 3: `numeric` kalitlari **pozitsiya** (int) yoki **belgi**
    (str) bo'lishi mumkin — ``36 → "36:12.5"``, ``"36a" → "36a:√5"``. Tartib
    barqaror (avval pozitsiya, so'ng qism), shu sababli int kalitlar uchun
    natija **avvalgidek** qoladi.
    """
    base = answer_key.format_compact(letters)
    if not numeric:
        return base
    block = answer_key.format_labeled_block(
        {
            key if isinstance(key, str) else str(int(key)): _canonical_number_text(value)
            for key, value in numeric.items()
        }
    )
    return f"{base}{answer_key.NUMERIC_SECTION_SEPARATOR}{block}"


# ---------------------------------------------------------------------------
# MVP baholash (opt-in) — kalitni o'qish va savollarni baholash
# ---------------------------------------------------------------------------
# Sonli javoblarni taqqoslash tolerantligi (float yozuvidagi kichik farqlar
# uchun: 12.5 va 12.50 bir xil hisoblanadi).
NUMERIC_TOLERANCE: Final[float] = 1e-6


class ItemOutcome(NamedTuple):
    """Bitta savol bo'yicha baholash natijasi (hisobot va ✅/❌ uchun).

    `label` — Phase 3 Step 3: savol belgisi (`"36"`, `"36a"`, `"36b"`).
    Legacy (qismsiz) yo'lda bo'sh satr (`""`) qoladi — o'quvchi tomonida
    `label or str(position)` ishlatiladi, shu sababli eski xulq **o'zgarmaydi**.
    """

    position: int
    kind: str  # OPTION_KIND | NUMERIC_KIND
    correct_display: str  # kalitdagi qiymat matni ("B" yoki "12.5")
    given_display: str | None  # o'quvchi javobi (javobsiz — None)
    is_correct: bool
    label: str = ""  # "36" | "36a" | "36b" (legacy — "")


def _canonical_number_text(value: Any) -> str:
    """Kanonik kalit/javob uchun son matni (aniqlikni saqlaydi).

    Matn (masalan `12.5` yoki allaqachon normallashtirilgan qiymat) o'z holida
    qaytariladi; natural ifoda (`√5`, `3/7`) ham o'z holida saqlanadi — uni
    baholashda `math_expr` hisoblaydi (Phase 3 Step 3: qismli bloklar);
    son esa to'liq aniqlikda yoziladi (`math_expr.format_number`).

    Raises:
        ValueError: qiymat bo'sh bo'lsa (matn formati buzuq).
    """
    if isinstance(value, str):
        try:
            return normalize_numeric(value)
        except ValueError:
            text = value.strip()
            if not text:
                raise
            return text
    return math_expr.format_number(value)


def _number_text(value: Any) -> str:
    """Sonli qiymatni kalitdagi qulay matnga aylantiradi (``12.5``, ``3``)."""
    if isinstance(value, str):
        return normalize_numeric(value)
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def is_mvp_key(key_text: str) -> bool:
    """Kalitda sonli blok (`|`) bormi? — MVP baholash yoqilganini bildiradi.

    Bu **opt-in** shart: eski (A–D, harfli) kalitlar avvalgidek baholanadi.
    """
    return answer_key.NUMERIC_SECTION_SEPARATOR in (key_text or "")


# Qismli kalit belgisi: `36a:` / `36b:` (`36:` — legacy, qismsiz). Faqat shu
# shakl kalitni **label-aware** baholash yo'liga o'tkazadi.
_LABELED_KEY_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|,)\s*\d+[A-Za-z]\s*:")


def is_labeled_key(key_text: str) -> bool:
    """Kalitdagi sonli blok **qism belgilarini** (`36a`, `36b`) ishlatadimi?

    Legacy kalit (``|36:12.5``) uchun `False` — baholash yo'li o'zgarmaydi
    (`36` ≠ `36a`). Kalit buzuq bo'lsa ham bu funksiya xato bermaydi
    (validatsiya — `parse_key`/`parse_labeled_key` ishi).
    """
    block = (key_text or "").partition(answer_key.NUMERIC_SECTION_SEPARATOR)[2]
    return bool(_LABELED_KEY_RE.search(block))


def part_labels(key_text: str, total_questions: int) -> list[str]:
    """Kalitdagi **qism belgilari** (``["36a","36b",…]``) — qismli kalitda.

    Legacy kalit (``|36:12.5``) yoki sonli bloki yo'q kalit uchun — bo'sh
    ro'yxat (qismsiz oqim **o'zgarmaydi**).

    Bu ro'yxat Mini App'ga qismli joylashuv berish uchun ishlatiladi
    (:func:`layout_with_parts`) va u **kalitdan** olinadi — shu sababli
    imtihonda `exam_sessions` yozuvi bo'lmasa ham (ya'ni item-level v2 oqimi
    ishlamasa ham) ``a``/``b`` kataklari **yo'qolmaydi**.
    """
    if not is_labeled_key(key_text):
        return []
    total = int(total_questions)
    seen: set[tuple[int, str]] = set()
    for label in answer_key.parse_labeled_block(key_text):
        try:
            number, part = split_label(label)
        except ValueError:
            continue
        if part and 1 <= number <= total:
            seen.add((number, part))
    return [label_of(number, part) for number, part in sorted(seen)]


def allowed_options(total_questions: int) -> tuple[str, ...]:
    """Joylashuvdagi barcha variant harflari (1–32 → A–D, 33–35 → A–F)."""
    letters: list[str] = []
    for section in layout_ranges(total_questions):
        for option in section["options"]:
            if option not in letters:
                letters.append(option)
    return tuple(letters)


def numeric_positions(total_questions: int) -> set[int]:
    """Sonli (ochiq) savollar pozitsiyalari (MVP formasi: 36–45)."""
    positions: set[int] = set()
    for section in layout_ranges(total_questions):
        if section["kind"] == NUMERIC_KIND:
            positions.update(range(int(section["from"]), int(section["to"]) + 1))
    return positions


def _key_number(position: int, raw: str) -> float:
    """Kalitdagi sonli qiymatni o'qiydi (natural ifoda ham bo'lishi mumkin).

    Phase 2: kalit `12.5` yoki `√5`, `3/7`, `π/2`, `|3-8|` ko'rinishida
    bo'lishi mumkin — barchasi aniq songa hisoblanadi. Xato —
    `AnswerKeyError`.
    """
    value = math_expr.evaluate(raw)
    if value is None:
        raise answer_key.AnswerKeyError(
            f"Javoblar kaliti: {position}-savol uchun sonli javob noto'g'ri: {raw!r}. "
            "Masalan: 36:12.5 yoki 36:\u221a5"
        )
    return value


def parse_key(key_text: str, total_questions: int) -> tuple[list[str], dict[int, float]]:
    """MVP (opt-in) kalitini o'qiydi: variant harflari + sonli javoblar.

    Faqat ``is_mvp_key(key_text)`` rost bo'lganda chaqiriladi. Har bir sonli
    pozitsiya uchun kalitda qiymat bo'lishi shart.

    Raises:
        answer_key.AnswerKeyError: kalit formati buzuq bo'lsa yoki sonli
            savollar uchun javob ko'rsatilmagan bo'lsa.
    """
    total = int(total_questions)
    letters = answer_key.parse_answer_key(
        key_text,
        total,
        allowed_options=allowed_options(total),
        optional_positions=numeric_positions(total),
    )
    sections = numeric_positions(total)

    numeric: dict[int, float] = {}
    for position, raw in answer_key.parse_numeric_block(key_text).items():
        if not 1 <= position <= total:
            raise answer_key.AnswerKeyError(
                f"Javoblar kaliti: sonli savol raqami oraliqdan tashqarida ({position})."
            )
        if position not in sections:
            raise answer_key.AnswerKeyError(
                f"Javoblar kaliti: {position}-savol sonli emas — unga variant harfi yozing."
            )
        numeric[position] = _key_number(position, raw)

    missing = sorted(position for position in sections if position not in numeric)
    if missing:
        raise answer_key.AnswerKeyError(
            "Javoblar kaliti: quyidagi sonli savollar uchun javob ko'rsatilmagan — "
            + ", ".join(map(str, missing))
            + "."
        )
    return letters, numeric


def parse_labeled_key(
    key_text: str, total_questions: int
) -> tuple[list[str], dict[str, float]]:
    """Qismli kalitni o'qiydi: variant harflari + **belgi** bo'yicha sonli javoblar.

    `parse_key` dan farqi: sonli blok kalitlari qismni saqlaydi
    (``"36a"``, ``"36b"``), shu sababli bir pozitsiyadagi qismlar
    **to'qnashmaydi**. Qaytaradi: ``(harflar, {label: qiymat})`` —
    ``{"36a": 2.2360679..., "36b": 0.42857...}``.

    Raises:
        answer_key.AnswerKeyError: kalit formati buzuq bo'lsa, belgi
            oraliqdan tashqarida bo'lsa yoki sonli bo'limga tegishli bo'lmasa.
    """
    total = int(total_questions)
    letters = answer_key.parse_answer_key(
        key_text,
        total,
        allowed_options=allowed_options(total),
        optional_positions=numeric_positions(total),
    )
    sections = numeric_positions(total)

    labeled: dict[str, float] = {}
    for label, raw in answer_key.parse_labeled_block(key_text).items():
        number, _part = answer_key.split_label(label)
        if not 1 <= number <= total:
            raise answer_key.AnswerKeyError(
                f"Javoblar kaliti: {label} belgisi oraliqdan tashqarida "
                f"(1 dan {total} gacha)."
            )
        if number not in sections:
            raise answer_key.AnswerKeyError(
                f"Javoblar kaliti: {label} belgisi sonli savol emas — "
                "unga variant harfi yozing."
            )
        labeled[label] = _key_number(number, raw)

    if not labeled:
        raise answer_key.AnswerKeyError(
            "Javoblar kaliti: qismli blok bo'sh. Masalan: |36a:\u221a5,36b:3/7"
        )
    return letters, labeled


def score_items(
    key_text: str, submitted_text: str, total_questions: int
) -> list[ItemOutcome]:
    """MVP kaliti va o'quvchi javoblari bo'yicha har bir savolni baholaydi.

    * variant savollar (1–35): harf mosligi (`A`…`E`/`F`);
    * sonli savollar (36–45): `NUMERIC_TOLERANCE` bilan qiymat tengligi;
    * **qismli kalit** (`36a`, `36b`): har bir qism — mustaqil savol
      (`score_labeled_items`); legacy kalit (`|36:12.5`) avvalgidek baholanadi.

    Raises:
        answer_key.AnswerKeyError: kalit yoki javob bloki formati buzuq bo'lsa.
    """
    if is_labeled_key(key_text):
        return score_labeled_items(key_text, submitted_text, total_questions)

    total = int(total_questions)
    correct_letters, correct_numeric = parse_key(key_text, total)
    given_letters = answer_key.parse_submitted(
        submitted_text, total, allowed_options=allowed_options(total)
    )
    given_numeric = answer_key.parse_numeric_block(submitted_text)
    sections = numeric_positions(total)

    outcomes: list[ItemOutcome] = []
    for position in range(1, total + 1):
        if position in sections:
            correct_value = correct_numeric.get(position)
            given_value: float | None = None
            raw_given = given_numeric.get(position)
            if raw_given is not None:
                # Phase 2: javob ham ifoda bo'lishi mumkin (`√5`, `6/14`, `π/2`).
                given_value = math_expr.evaluate(raw_given)
            outcomes.append(
                ItemOutcome(
                    position=position,
                    kind=NUMERIC_KIND,
                    correct_display=(
                        "—" if correct_value is None else _number_text(correct_value)
                    ),
                    given_display=None if given_value is None else _number_text(given_value),
                    is_correct=(
                        correct_value is not None
                        and given_value is not None
                        and math_expr.equivalent(
                            given_value,
                            correct_value,
                            absolute_tolerance=config.NUMERIC_ABSOLUTE_TOLERANCE,
                            relative_tolerance=config.NUMERIC_RELATIVE_TOLERANCE,
                        )
                    ),
                )
            )
            continue

        correct = correct_letters[position - 1]
        given = given_letters[position - 1]
        outcomes.append(
            ItemOutcome(
                position=position,
                kind=OPTION_KIND,
                correct_display=correct,
                given_display=None if given == SKIPPED else given,
                is_correct=given != SKIPPED and given == correct,
            )
        )
    return outcomes


# --- Qismli (label-aware) baholash — Phase 3, Step 3 -------------------------
# `36a` va `36b` — bir pozitsiyaning (36) ikki **mustaqil** savoli. Savollar
# to'plamini kalit belgilaydi, shu sababli savollar soni o'quvchiga bog'liq
# emas (Rasch uchun barqaror to'plam).
def _labeled_order(labeled: Mapping[str, float]) -> list[tuple[str, float]]:
    """`{label: qiymat}` xaritasini barqaror tartibga keltiradi.

    Tartib: avval pozitsiya, so'ng qism (`None` < `"a"` < `"b"`) — ya'ni
    ``36b`` dan keyin ``37a`` keladi.
    """
    ordered = [(*answer_key.split_label(label), value) for label, value in labeled.items()]
    ordered.sort(key=lambda item: (item[0], item[1] or ""))
    return [(answer_key.label_of(number, part), value) for number, part, value in ordered]


def score_labeled_items(
    key_text: str, submitted_text: str, total_questions: int
) -> list[ItemOutcome]:
    """Qismli kalit bo'yicha baholaydi: `36a` va `36b` — ikki alohida savol.

    Item to'plami — **kalitdagi belgilar** (`36a`, `36b`, ...). O'quvchi javob
    bermagan qism ham natijaga kiradi (javobsiz = noto'g'ri), shu sababli
    xom ball va savollar soni (masalan 35 variant + 20 qism = 55) barqaror.

    Sonli javoblar `math_expr.equivalent` bilan solishtiriladi — `√5`,
    `(√20)/2`, `6/14`, `3/7` ekvivalent hisoblanadi. Variant savollar
    (36–45 dan tashqari pozitsiyalar) avvalgi qoida bilan baholanadi.

    Raises:
        answer_key.AnswerKeyError: kalit yoki javob bloki formati buzuq bo'lsa.
    """
    total = int(total_questions)
    correct_letters, correct_labeled = parse_labeled_key(key_text, total)
    given_letters = answer_key.parse_submitted(
        submitted_text, total, allowed_options=allowed_options(total)
    )
    given_labeled = answer_key.parse_labeled_block(submitted_text)
    sections = numeric_positions(total)

    outcomes: list[ItemOutcome] = []
    for position in range(1, total + 1):
        if position in sections:
            continue
        correct = correct_letters[position - 1]
        given = given_letters[position - 1]
        outcomes.append(
            ItemOutcome(
                position=position,
                kind=OPTION_KIND,
                correct_display=correct,
                given_display=None if given == SKIPPED else given,
                is_correct=given != SKIPPED and given == correct,
                label=str(position),
            )
        )

    for label, correct_value in _labeled_order(correct_labeled):
        number, _part = answer_key.split_label(label)
        raw_given = given_labeled.get(label)
        # Phase 2: javob ham ifoda bo'lishi mumkin (`√5`, `6/14`, `π/2`).
        given_value = math_expr.evaluate(raw_given) if raw_given is not None else None
        outcomes.append(
            ItemOutcome(
                position=number,
                kind=NUMERIC_KIND,
                correct_display=_number_text(correct_value),
                given_display=None if given_value is None else _number_text(given_value),
                is_correct=(
                    given_value is not None
                    and math_expr.equivalent(
                        given_value,
                        correct_value,
                        absolute_tolerance=config.NUMERIC_ABSOLUTE_TOLERANCE,
                        relative_tolerance=config.NUMERIC_RELATIVE_TOLERANCE,
                    )
                ),
                label=label,
            )
        )
    return outcomes
