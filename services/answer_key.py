"""Imtihon javoblar kaliti va o'quvchi javoblarini tahlil qilish.

O'qituvchi ham, o'quvchi ham javoblarni bir xil "erkin" uslubda yozishi mumkin.
Quyidagi formatlarning barchasi qabul qilinadi:

    1A2B3C          — savol raqami + variant harfi (asosiy tavsiya etilgan format)
    1A 2B 3C        — bo'sh joy bilan ajratilgan
    1:A, 2:B; 3:C   — ikki nuqta/vergul/qavs kabi ajratuvchilar bilan
    ABCD            — savol raqamisiz, harflar ketma-ketligi

Bu modul `services.exam_service`, `services.grading` va admin ustasi uchun
yagona ishonchli tahlil nuqtasi hisoblanadi (SQL/handler'lar bu formatlarni
o'zi tahlil qilmaydi).
"""

from __future__ import annotations

import re
from typing import Collection, Final, Mapping, Sequence

import config
from database.models import SKIPPED

OPTIONS: frozenset[str] = frozenset(config.ANSWER_OPTIONS)

# Kanonik matnda sonli (ochiq) javoblar shu belgidan KEYIN saqlanadi, masalan
# "1A2B...45X|36:12.5". Harflar bo'yicha tahlil (baholash) bu qismni o'qimaydi —
# shuning uchun eski imtihonlar ham, yangi MVP formasi ham bir xil ishlaydi.
NUMERIC_SECTION_SEPARATOR: Final[str] = "|"


class AnswerKeyError(ValueError):
    """Javoblar kaliti yoki o'quvchi javoblari formati noto'g'ri bo'lganda."""


# "1A", "10B", "1:A" kabi juftliklarni topadi (ikki nuqtadan keyin ham).
_PAIR_RE = re.compile(r"(\d+)\s*([A-Za-z])")

# Ajratuvchi va ortiqcha belgilar (bo'sh joy, tinish belgilari, uzun tire va h.k.)
# `compact()` da faqat harf va raqamlar qoldiriladi — bu barcha kutilgan
# ajratuvchi uslublarni bir xilda tahlil qilishning eng ishonchli yo'li.
def compact(text: str) -> str:
    """Matnni faqat harf va raqamlardan iborat, katta harfli ko'rinishga keltiradi.

    Barcha bo'sh joylar, tinish belgilari va boshqa ajratuvchilar olib tashlanadi:
        "1A, 2B; 3:C" → "1A2B3C"
    """
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


def parse_letters(
    text: str,
    total_questions: int,
    *,
    require_full: bool = True,
    label: str = "Javoblar",
    allowed_options: Collection[str] | None = None,
    optional_positions: Collection[int] = (),
) -> list[str]:
    """Erkin formatdagi javoblar matnini harflar ro'yxatiga aylantiradi.

    Qaytaradi: uzunligi `total_questions` ga teng ro'yxat. Javob berilmagan
    o'rinlar `SKIPPED` ("X") bilan to'ldiriladi.

    Args:
        text: o'qituvchi kaliti yoki o'quvchi javoblari.
        total_questions: imtihondagi savollar soni.
        require_full: True bo'lsa hamma savolga javob bo'lishi shart
            (o'qituvchi kaliti uchun); False bo'lsa yetishmaganlari "X"
            (o'quvchi javoblari uchun).
        label: xato xabarida ko'rsatiladigan nom.
        allowed_options: ruxsat etilgan variant harflari (opt-in). `None`
            bo'lsa `config.ANSWER_OPTIONS` (A–D) ishlatiladi — ya'ni eski
            xulq o'zgarmaydi. MVP formasi 33–35 uchun `A–F` uzatadi.
        optional_positions: `require_full=True` bo'lganda ham harfsiz
            qolishiga yo'l qo'yiladigan pozitsiyalar (MVP formasida 36–45 —
            ularning javobi sonli blokda saqlanadi).

    Raises:
        AnswerKeyError: format noto'g'ri bo'lsa yoki `require_full=True` da
            biror savol javobsiz qolsa.
    """
    if total_questions <= 0:
        raise AnswerKeyError("Savollar soni noldan katta bo'lishi kerak.")

    options = (
        frozenset(OPTIONS)
        if not allowed_options
        else frozenset(str(option).upper() for option in allowed_options)
    )

    # Sonli javoblar bloki (| dan keyin) baholashda hisobga olinmaydi.
    cleaned = compact((text or "").split(NUMERIC_SECTION_SEPARATOR, 1)[0])
    if not cleaned:
        if require_full:
            raise AnswerKeyError(f"{label} bo'sh bo'lishi mumkin emas.")
        return [SKIPPED] * total_questions

    letters: list[str]
    if any(ch.isdigit() for ch in cleaned):
        pairs = [(int(number), letter.upper()) for number, letter in _PAIR_RE.findall(cleaned)]
        if not pairs:
            raise AnswerKeyError(
                f"{label} formati noto'g'ri: {text!r}. Masalan: 1A2B3C yoki 1A 2B 3C."
            )

        leftover = _PAIR_RE.sub("", cleaned)
        if leftover and require_full:
            raise AnswerKeyError(
                f"{label} formati noto'g'ri — tushunarsiz belgilar: {leftover!r}. "
                "Masalan: 1A2B3C yoki 1A 2B 3C."
            )

        numbers = [number for number, _ in pairs]
        if len(set(numbers)) != len(numbers):
            raise AnswerKeyError(f"{label}: savol raqamlari takrorlangan.")

        out_of_range = sorted({number for number in numbers if not 1 <= number <= total_questions})
        if out_of_range and require_full:
            shown = ", ".join(map(str, out_of_range))
            raise AnswerKeyError(
                f"{label}: savol raqami oraliqdan tashqarida ({shown}). "
                f"1 dan {total_questions} gacha bo'lishi kerak."
            )

        letters = [SKIPPED] * total_questions
        for number, letter in pairs:
            if 1 <= number <= total_questions:
                letters[number - 1] = letter
    else:
        letters = list(cleaned)
        if len(letters) > total_questions:
            raise AnswerKeyError(
                f"{label} soni {len(letters)} ta, imtihonda esa {total_questions} ta savol bor."
            )
        letters += [SKIPPED] * (total_questions - len(letters))

    invalid = sorted({letter for letter in letters if letter not in options and letter != SKIPPED})
    if invalid:
        if require_full:
            raise AnswerKeyError(
                f"{label}: ruxsat etilmagan variant(lar): {', '.join(invalid)}. "
                f"Faqat {', '.join(sorted(options))} harflari qabul qilinadi."
            )
        letters = [letter if letter in options else SKIPPED for letter in letters]

    if require_full:
        optional = {int(position) for position in optional_positions}
        missing = [
            str(index + 1)
            for index, letter in enumerate(letters)
            if letter == SKIPPED and (index + 1) not in optional
        ]
        if missing:
            raise AnswerKeyError(
                f"{label}: quyidagi savollar uchun javob ko'rsatilmagan — {', '.join(missing)}."
            )

    return letters


def parse_answer_key(
    text: str,
    total_questions: int,
    *,
    allowed_options: Collection[str] | None = None,
    optional_positions: Collection[int] = (),
) -> list[str]:
    """O'qituvchi kiritgan kalitni tekshirib, harflar ro'yxatiga aylantiradi.

    `allowed_options` / `optional_positions` — opt-in (MVP formasi: 33–35 →
    A–F, 36–45 sonli). Standart chaqiruvda xulq o'zgarmaydi (A–D, to'liq).
    """
    return parse_letters(
        text,
        total_questions,
        require_full=True,
        label="Javoblar kaliti",
        allowed_options=allowed_options,
        optional_positions=optional_positions,
    )


def parse_submitted(
    text: str, total_questions: int, *, allowed_options: Collection[str] | None = None
) -> list[str]:
    """O'quvchi yuborgan javoblarni tahlil qiladi (yetishmaganlari — "X").

    `allowed_options` — opt-in (MVP formasida A–F). Standart chaqiruvda xulq
    o'zgarmaydi: faqat A–D qabul qilinadi, boshqalari "X" bo'ladi.
    """
    return parse_letters(
        text,
        total_questions,
        require_full=False,
        label="Javoblar",
        allowed_options=allowed_options,
    )


def parse_numeric_block(text: str) -> dict[int, str]:
    """Kanonik matnning `|` dan keyingi sonli qismini o'qiydi.

    Masalan ``"1A2B...45X|36:12.5,45:3"`` → ``{36: "12.5", 45: "3"}``.
    Blok bo'lmasa — bo'sh lug'at (eski formatlar uchun xavfsiz).

    Raises:
        AnswerKeyError: blok formati buzilgan bo'lsa (raqam:qiymat jufti emas,
            raqam takrorlangan va h.k.).
    """
    raw = (text or "").partition(NUMERIC_SECTION_SEPARATOR)[2].strip()
    if not raw:
        return {}

    values: dict[int, str] = {}
    for chunk in raw.split(","):
        piece = chunk.strip()
        if not piece:
            continue
        position_text, separator, value_text = piece.partition(":")
        position_text = position_text.strip()
        value_text = value_text.strip()
        if not separator or not position_text.isdigit() or not value_text:
            raise AnswerKeyError(
                f"Sonli javoblar bloki buzilgan: {piece!r}. Masalan: |36:12.5,37:3"
            )
        position = int(position_text)
        if position in values:
            raise AnswerKeyError(f"Sonli javoblar bloki: {position} raqami takrorlangan.")
        values[position] = value_text
    return values


# ---------------------------------------------------------------------------
# Label (qismli savol belgisi) — Phase 3, Step 1: faqat TAHLIL qatlami.
#   "36"  → legacy (butun savol)          → (36, None)
#   "36a" → 36-savolning "a" qismi         → (36, "a")
#   "36b" → 36-savolning "b" qismi         → (36, "b")
# Baholash hali qismlarni bilmaydi — bu qatlam faqat belgini TANIYDI.
# ---------------------------------------------------------------------------

# Belgi: raqam + ixtiyoriy BITTA harf (masalan "36", "36a", "36b").
_LABEL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<position>[0-9]{1,7})(?P<part>[A-Za-z])?$"
)

# Ruxsat etilgan qismlar (sxema: `form_items.part IN ('', 'a', 'b')`).
ALLOWED_PARTS: Final[frozenset[str]] = frozenset({"a", "b"})


def normalize_part(part: str | None) -> str:
    """Qism belgisini normallashtiradi: `None`/`""` → `""`; `"A"` → `"a"`.

    Raises:
        ValueError: qism ruxsat etilmagan bo'lsa (faqat `''`, `'a'`, `'b'`).
    """
    text = "" if part is None else str(part).strip().lower()
    if text and text not in ALLOWED_PARTS:
        raise ValueError(
            f"Qism belgisi noto'g'ri: {part!r}. Ruxsat etilgan: '', 'a', 'b'."
        )
    return text


def label_of(position: int, part: str | None = None) -> str:
    """`(36, None)` → `"36"`; `(36, "a")` → `"36a"`; `(36, "b")` → `"36b"`.

    Raises:
        ValueError: pozitsiya musbat butun son bo'lmasa yoki qism noto'g'ri.
    """
    try:
        number = int(position)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Pozitsiya butun son bo'lishi kerak: {position!r}.") from exc
    if number <= 0:
        raise ValueError(f"Pozitsiya musbat bo'lishi kerak: {number}.")
    return f"{number}{normalize_part(part)}"


def split_label(label: str) -> tuple[int, str | None]:
    """`"36"` → `(36, None)`; `"36a"` → `(36, "a")`; `"36b"` → `(36, "b")`.

    Noto'g'ri belgi **xavfsiz** to'xtaydi — `ValueError`.

    Raises:
        ValueError: belgi bo'sh, raqamsiz, ortiqcha belgili yoki ruxsat
            etilmagan qismli bo'lsa (`"36c"`, `"a36"`, `"36ab"`, `""`).
    """
    text = "" if label is None else str(label).strip()
    match = _LABEL_RE.match(text) if text else None
    if match is None:
        raise ValueError(
            f"Belgi formati noto'g'ri: {label!r}. Masalan: 36, 36a, 36b."
        )
    number = int(match.group("position"))
    if number <= 0:
        raise ValueError(f"Belgi pozitsiyasi musbat bo'lishi kerak: {label!r}.")
    part = match.group("part")
    if part is None:
        return number, None
    return number, normalize_part(part) or None


def parse_labeled_block(text: str) -> dict[str, str]:
    """Kanonik matnning `|` dan keyingi blokini **LABEL** kalitlari bilan o'qiydi.

    Legacy:  ``"1A2B...|36:12.5,37:3"``  → ``{"36": "12.5", "37": "3"}``.
    Qismli:  ``"1A2B...|36a:√5,36b:3/7"`` → ``{"36a": "√5", "36b": "3/7"}``.

    `parse_numeric_block` dan farqi: kalitlar **matn (label)** ko'rinishida
    qaytadi — shu sababli qism belgilari yo'qolmaydi. Blok bo'lmasa — bo'sh
    lug'at (eski formatlar uchun xavfsiz).

    Raises:
        AnswerKeyError: blok formati buzilgan bo'lsa (kalit:qiymat jufti emas,
            belgi noto'g'ri yoki belgi takrorlangan).
    """
    raw = (text or "").partition(NUMERIC_SECTION_SEPARATOR)[2].strip()
    if not raw:
        return {}

    values: dict[str, str] = {}
    for chunk in raw.split(","):
        piece = chunk.strip()
        if not piece:
            continue
        label_text, separator, value_text = piece.partition(":")
        label_text = label_text.strip()
        value_text = value_text.strip()
        if not separator or not label_text or not value_text:
            raise AnswerKeyError(
                f"Javoblar bloki buzilgan: {piece!r}. Masalan: |36a:\u221a5,36b:3/7"
            )
        try:
            number, part = split_label(label_text)
        except ValueError as exc:
            raise AnswerKeyError(str(exc)) from exc
        label = label_of(number, part)
        if label in values:
            raise AnswerKeyError(f"Javoblar bloki: {label} belgisi takrorlangan.")
        values[label] = value_text
    return values


def format_labeled_block(values: Mapping[str, str]) -> str:
    """Label → qiymat xaritasini kanonik blok matniga aylantiradi.

    Kalitlar `"36"` yoki `"36a"` bo'lishi mumkin; tartib **barqaror**
    (avval pozitsiya, so'ng qism). Bo'sh xarita → bo'sh satr.
    """
    ordered: list[tuple[int, str, str]] = []
    for key, value in values.items():
        number, part = split_label(key)
        ordered.append((number, part or "", str(value)))
    ordered.sort(key=lambda item: (item[0], item[1]))
    return ",".join(
        f"{label_of(number, part or None)}:{value}"
        for number, part, value in ordered
    )


def compare(correct_letters: Sequence[str], given_letters: Sequence[str]) -> list[bool]:
    """Har bir savol bo'yicha to'g'ri/noto'g'ri natija ro'yxatini qaytaradi."""
    if len(correct_letters) != len(given_letters):
        raise AnswerKeyError(
            f"Kalit va javoblar uzunligi mos emas: {len(correct_letters)} ≠ {len(given_letters)}."
        )
    return [
        given.upper() == correct.upper()
        for correct, given in zip(correct_letters, given_letters, strict=True)
    ]


def score(correct_letters: Sequence[str], given_letters: Sequence[str]) -> int:
    """To'g'ri javoblar soni (xom ball)."""
    return sum(compare(correct_letters, given_letters))


def format_compact(letters: Sequence[str], *, with_numbers: bool = True) -> str:
    """Harflar ro'yxatini o'qishga qulay ko'rinishga aylantiradi.

    with_numbers=True → "1A2B3C";  False → "ABC".
    """
    if with_numbers:
        return "".join(f"{index}{letter}" for index, letter in enumerate(letters, start=1))
    return "".join(letters)
