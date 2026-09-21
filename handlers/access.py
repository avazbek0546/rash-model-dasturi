"""O'qituvchi (admin) huquqini tekshirish.

`ADMIN_ID` / `ADMIN_IDS` `.env` da ko'rsatilgan Telegram ID'lar admin
hisoblanadi. Admin komandalari (`/new_exam`, `/exams`, `/stats`) faqat shular
uchun ishlaydi — boshqalarga hech narsa oshkor qilinmaydi.
"""

from __future__ import annotations

import logging

import config

logger = logging.getLogger(__name__)


def is_admin(user_id: int | None) -> bool:
    """Foydalanuvchi admin ro'yxatida bormi?"""
    return config.is_admin(user_id)


def log_denied(where: str, user_id: int | None, full_name: str = "") -> None:
    """Ruxsatsiz urinishni logga yozadi (foydalanuvchiga hech narsa ko'rsatilmaydi)."""
    logger.info("Ruxsatsiz admin urinishi (%s): %s (%s)", where, full_name, user_id)