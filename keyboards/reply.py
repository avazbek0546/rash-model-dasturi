"""Reply (pastdagi) menyu klaviaturasi.

Reply tugmalari matn sifatida yuboriladi — shu sababli ularni handler'larda
`F.text == ...` orqali ushlaymiz (matnlar shu yerda, bitta joyda saqlanadi).

Bo'limlar:
    🔍 Test tahlili   — topshirilgan imtihonlarning savol-savol tahlili
    🎬 Yechim yuklash — (faqat admin) video/media yechim yuklash yo'riqnomasi
    🏡 Asosiy menyu   — Web App tugmasi va imtihon ro'yxatiga qaytish
"""

from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

ANALYSIS_BUTTON = "🔍 Test tahlili"
HOME_BUTTON = "🏡 Asosiy menyu"
UPLOAD_SOLUTION_BUTTON = "🎬 Yechim yuklash"


def main_reply_kb(*, is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Pastdagi doimiy menyu (admin uchun qo'shimcha tugma bilan)."""
    builder = ReplyKeyboardBuilder()
    builder.button(text=ANALYSIS_BUTTON)
    if is_admin:
        builder.button(text=UPLOAD_SOLUTION_BUTTON)
    builder.button(text=HOME_BUTTON)
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


__all__ = [
    "ANALYSIS_BUTTON",
    "HOME_BUTTON",
    "UPLOAD_SOLUTION_BUTTON",
    "main_reply_kb",
]