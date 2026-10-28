"""Web App (Mini App) bilan bog'liq handler'lar: `/app` komandasi.

Mini App'ning o'zi `webapp/` papkasidagi SPA — bu yerda faqat uni Telegram
ichida ochish uchun tugma beriladi.

Ro'yxatdan o'tmagan **o'quvchi** `/app` orqali test bo'limiga kira olmaydi:
avval ism va familiya so'raladi. Adminlar Mini App'dagi boshqaruv panelidan
foydalanishi uchun bu tekshiruvdan ozod qilingan.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import config
import texts
from database.repository import Repositories
from handlers.access import is_admin
from handlers.registration import begin_registration, is_registered
from keyboards.inline import webapp_kb

router = Router(name="webapp")


@router.message(Command("app"))
async def cmd_app(
    message: Message, state: FSMContext, repos: Repositories
) -> None:
    """`/app` — imtihon ilovasini ochish uchun tugma yuboradi."""
    if message.from_user is None:
        return

    admin = is_admin(message.from_user.id)
    if not admin and not await is_registered(repos, message.from_user.id):
        await begin_registration(message, state)
        return

    if not config.WEBAPP_URL:
        await message.answer(texts.webapp_button_missing(), reply_markup=webapp_kb(is_admin=admin))
        return

    profile = await repos.profiles.get(message.from_user.id)
    saved = await repos.users.get(message.from_user.id)
    full_name = (
        saved.full_name
        if saved is not None and saved.full_name.strip()
        else (profile.full_name if profile is not None else message.from_user.full_name)
    )
    await message.answer(
        texts.webapp_welcome(full_name, webapp_ready=True),
        reply_markup=webapp_kb(is_admin=admin),
    )