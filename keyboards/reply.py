"""Eski (pastdagi) reply menyu matnlari — faqat moslik uchun.

Yangi menyuda pastdagi klaviatura **ishlatilmaydi**: barcha bo'limlar inline
menyuga ko'chirilgan (`keyboards.inline.webapp_kb`). Bu matn konstantalari
eski klaviaturasi hali qolgan foydalanuvchilarning tugmalari ishlashi uchun
saqlanadi (`F.text == ...` handler'lari).
"""

from __future__ import annotations

ANALYSIS_BUTTON = "🔍 Test tahlili"
HOME_BUTTON = "🏡 Asosiy menyu"
UPLOAD_SOLUTION_BUTTON = "🎬 Yechim yuklash"

__all__ = [
    "ANALYSIS_BUTTON",
    "HOME_BUTTON",
    "UPLOAD_SOLUTION_BUTTON",
]