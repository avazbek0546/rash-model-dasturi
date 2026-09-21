"""Web App (Mini App) bilan bog'liq handler'lar: `/app` komandasi.

Mini App'ning o'zi `webapp/` papkasidagi SPA — bu yerda faqat uni Telegram
ichida ochish uchun tugma beriladi.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import config
import texts
from handlers.access import is_admin
from keyboards.inline import webapp_kb

router = Router(name="webapp")


@router.message(Command("app"))
async def cmd_app(message: Message) -> None:
    """`/app` — imtihon ilovasini ochish uchun tugma yuboradi."""
    if message.from_user is None:
        return

    admin = is_admin(message.from_user.id)
    if not config.WEBAPP_URL:
        await message.answer(texts.webapp_button_missing(), reply_markup=webapp_kb(is_admin=admin))
        return

    await message.answer(
        texts.webapp_welcome(message.from_user.full_name, webapp_ready=True),
        reply_markup=webapp_kb(is_admin=admin),
    )