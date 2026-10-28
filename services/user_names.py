"""Foydalanuvchi ismi va familiyasini normallashtirish/tekshirish.

Botda ism va familiya alohida so'raladi. Tekshiruv **yagona joyda** turadi:
handler ham, testlar ham faqat shu moduldan foydalanadi.

Qoidalar
--------
* faqat harflar, bo'sh joy, apostrof va chiziqcha;
* raqam, emoji va boshqa belgilar qabul qilinmaydi;
* kamida 2 ta harf, ko'pi bilan 50 belgi;
* ortiqcha bo'shliqlar tozalanadi, apostrof turlari bitta ko'rinishga
  keltiriladi (``G‘ofur`` → ``G'ofur``).
"""

from __future__ import annotations

import re
from typing import Final

#: Ism/familiya uzunligi chegaralari (belgi hisobida).
NAME_MIN_LENGTH: Final[int] = 2
NAME_MAX_LENGTH: Final[int] = 50

#: Apostrofning turli ko'rinishlari — bitta ASCII apostrofga keltiriladi.
_APOSTROPHE_TRANSLATION: Final[dict[str, str]] = str.maketrans(
    {
        "\u2018": "'",  # ‘
        "\u2019": "'",  # ’
        "\u02bb": "'",  # ʻ
        "\u02bc": "'",  # ʼ
        "`": "'",
        "\u00b4": "'",  # ´
    }
)

#: Ism ichida ruxsat etilgan ajratuvchilar.
_ALLOWED_SEPARATORS: Final[frozenset[str]] = frozenset({" ", "-", "'"})

#: So'zlarni ajratish (bo'sh joy, chiziqcha va apostrof bo'yicha).
_WORD_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[\s\-']+")


class InvalidNameError(ValueError):
    """Ism yoki familiya talabga mos emas (foydalanuvchiga ko'rsatiladi)."""


def normalize_name(raw: str) -> str:
    """Ism/familiyani tozalaydi: apostrof turi va ortiqcha bo'shliqlar."""
    text = str(raw or "").translate(_APOSTROPHE_TRANSLATION)
    text = " ".join(text.split())
    # "Ali - Vali" → "Ali-Vali" (chiziqcha atrofidagi bo'shliqlar olib tashlanadi).
    return re.sub(r"\s*-\s*", "-", text)


def validate_name(raw: str, *, field: str) -> str:
    """Ism/familiyani tekshiradi va normallashtirilgan qiymatni qaytaradi.

    Args:
        raw: foydalanuvchi kiritgan matn.
        field: xato matnida ko'rsatiladigan maydon nomi ("Ism"/"Familiya").

    Raises:
        InvalidNameError: qiymat bo'sh, juda qisqa/uzun yoki ruxsat etilmagan
            belgilardan iborat bo'lsa.
    """
    name = normalize_name(raw)
    if len(name) < NAME_MIN_LENGTH:
        raise InvalidNameError(
            f"{field} kamida {NAME_MIN_LENGTH} ta harfdan iborat bo'lishi kerak."
        )
    if len(name) > NAME_MAX_LENGTH:
        raise InvalidNameError(
            f"{field} {NAME_MAX_LENGTH} belgidan oshmasligi kerak."
        )

    letters = 0
    for char in name:
        if char.isalpha():
            letters += 1
            continue
        if char in _ALLOWED_SEPARATORS:
            continue
        raise InvalidNameError(
            f"{field} faqat harflar, bo'sh joy, apostrof va chiziqchadan "
            "iborat bo'lishi kerak. Raqam va boshqa belgilar ishlatilmaydi."
        )

    if letters < NAME_MIN_LENGTH:
        raise InvalidNameError(
            f"{field} kamida {NAME_MIN_LENGTH} ta harfdan iborat bo'lishi kerak."
        )

    # Har bir bo'lakda kamida bitta harf bo'lishi shart ("Ali -- Vali" kabi
    # holatlarda bo'sh bo'laklar qolmasligi uchun).
    words = [word for word in _WORD_SPLIT_RE.split(name) if word]
    if not words or any(not any(char.isalpha() for char in word) for word in words):
        raise InvalidNameError(f"{field} to'g'ri kiritilmagan. Qaytadan urinib ko'ring.")

    return name
