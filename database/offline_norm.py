"""Offline ishtirokchilarni solishtirish uchun matn normalizatsiyasi.

Bu modul faqat **solishtirish** uchun ishlatiladi: bazada va PDF'da asl
ism/kod saqlanadi. Normalizatsiya ism-familiyadagi apostrof, registr va
bo'shliq farqlarini tekislaydi — lekin hech qachon avtomatik birlashtirish
qarorini qabul qilmaydi (buni faqat admin tasdiqlaydi).
"""

from __future__ import annotations

import re
import unicodedata

_APOSTROPHES = {"‘": "'", "’": "'", "ʼ": "'", "`": "'", "´": "'"}
_SPACES_RE = re.compile(r"\s+")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")


def normalize_name(value: object) -> str:
    """Ism-familiyani solishtirish ko'rinishiga keltiradi."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    for source, target in _APOSTROPHES.items():
        text = text.replace(source, target)
    text = _SPACES_RE.sub(" ", text).strip().casefold()
    return text


def normalize_code(value: object) -> str:
    """`student_code` ni solishtirish ko'rinishiga keltiradi."""
    return normalize_name(value)


def normalize_username(value: object) -> str | None:
    """`@username` ni validatsiya qiladi va `@`siz qaytaradi.

    Noto'g'ri yoki bo'sh qiymat — `None` (ixtiyoriy maydon).
    """
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("@"):
        text = text[1:]
    if not _USERNAME_RE.fullmatch(text):
        return None
    return text


def clean_text(value: object, *, limit: int = 200) -> str:
    """Ko'rsatish uchun matnni tozalaydi (nazorat belgilarini olib tashlaydi)."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(char for char in text if char == "\n" or char >= " ")
    text = _SPACES_RE.sub(" ", text).strip()
    return text[:limit]
