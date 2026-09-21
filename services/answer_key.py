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
from typing import Sequence

import config
from database.models import SKIPPED

OPTIONS: frozenset[str] = frozenset(config.ANSWER_OPTIONS)


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

    Raises:
        AnswerKeyError: format noto'g'ri bo'lsa yoki `require_full=True` da
            biror savol javobsiz qolsa.
    """
    if total_questions <= 0:
        raise AnswerKeyError("Savollar soni noldan katta bo'lishi kerak.")

    cleaned = compact(text)
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

    invalid = sorted({letter for letter in letters if letter not in OPTIONS and letter != SKIPPED})
    if invalid:
        if require_full:
            raise AnswerKeyError(
                f"{label}: ruxsat etilmagan variant(lar): {', '.join(invalid)}. "
                f"Faqat {', '.join(config.ANSWER_OPTIONS)} harflari qabul qilinadi."
            )
        letters = [letter if letter in OPTIONS else SKIPPED for letter in letters]

    if require_full:
        missing = [str(index + 1) for index, letter in enumerate(letters) if letter == SKIPPED]
        if missing:
            raise AnswerKeyError(
                f"{label}: quyidagi savollar uchun javob ko'rsatilmagan — {', '.join(missing)}."
            )

    return letters


def parse_answer_key(text: str, total_questions: int) -> list[str]:
    """O'qituvchi kiritgan kalitni tekshirib, harflar ro'yxatiga aylantiradi."""
    return parse_letters(text, total_questions, require_full=True, label="Javoblar kaliti")


def parse_submitted(text: str, total_questions: int) -> list[str]:
    """O'quvchi yuborgan javoblarni tahlil qiladi (yetishmaganlari — "X")."""
    return parse_letters(text, total_questions, require_full=False, label="Javoblar")


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
