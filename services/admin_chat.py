"""Admin chat (faqat adminlar) — qatnashchilar jurnalining manzili.

Nega kerak
----------
O'qituvchi «testda necha kishi qatnashdi va kimlar?» degan savolga tez javob
olishi kerak. Buning uchun bot alohida guruhga (yoki kanalga) har bir yangi
qatnashchi haqida xabar yuboradi — xabarlar o'sha chatda tarix bo'lib qoladi.

Bot Telegram'da guruh **yara olmaydi** (Bot API bunday metod bermaydi). Shu
sababli oqim quyidagicha:

    1. Admin o'zi (faqat o'zi) guruh yaratadi va botni administrator qiladi;
    2. Guruhda `/admin_chat` yozadi — bot chat ID sini `bot_settings` ga
       yozadi (`admin_chat_id`);
    3. Shu paytdan boshlab har bir javob shu chatga ham yuboriladi;
    4. Bot guruhga qo'shilgan har bir **admin bo'lmagan** odamni darhol
       chiqarib yuboradi (`handlers/admin_chat.py`).

`.env` dagi `ADMIN_CHAT_ID` — zaxira variant (masalan kanal uchun). Bazadagi
qiymat undan ustun turadi.
"""

from __future__ import annotations

import logging

import config
from database.repository import Repositories

logger = logging.getLogger(__name__)

#: `bot_settings` dagi kalit nomi.
ADMIN_CHAT_KEY = "admin_chat_id"


async def chat_id(repos: Repositories) -> int | None:
    """Bog'langan admin chat ID sini qaytaradi (bo'lmasa — `None`).

    Prioritet: bazadagi `admin_chat_id` → `.env` dagi `ADMIN_CHAT_ID`.
    Buzuq qiymat bo'lsa log yoziladi va env zaxirasiga o'tiladi.
    """
    try:
        raw = await repos.settings.get(ADMIN_CHAT_KEY)
    except Exception:  # baza xatosi botni to'xtatmasin
        logger.exception("admin_chat_id ni o'qib bo'lmadi")
        raw = None

    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning("bot_settings.admin_chat_id buzuq: %r", raw)
    return config.ADMIN_CHAT_ID


async def is_admin_chat(repos: Repositories, chat: int | str | None) -> bool:
    """`chat` bog'langan admin chatmi?"""
    if chat is None:
        return False
    current = await chat_id(repos)
    try:
        return current is not None and int(chat) == int(current)
    except (TypeError, ValueError):
        return False


async def bind(repos: Repositories, chat: int) -> None:
    """Chatni admin chat sifatida saqlaydi (qayta ishga tushganda ham qoladi)."""
    await repos.settings.set(ADMIN_CHAT_KEY, str(int(chat)))


async def unbind(repos: Repositories) -> bool:
    """Bog'lanishni o'chiradi.

    Returns:
        True — baza yozuvi o'chirildi; False — baza bo'sh edi (env qiymati
        bo'lsa, u kuchda qoladi).
    """
    return await repos.settings.delete(ADMIN_CHAT_KEY)
