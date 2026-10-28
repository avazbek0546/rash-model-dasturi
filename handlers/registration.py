"""Birinchi kirishda ism va familiyani so'rash (majburiy ro'yxatdan o'tish).

Oqim
----
1. `/start` (yoki test bo'limiga kirish urinishi) → profil yo'q bo'lsa
   `RegistrationStates.first_name` holati yoqiladi;
2. ism tekshiriladi va vaqtincha FSM'da saqlanadi → familiya so'raladi;
3. familiya tekshiriladi → `user_profiles` + `users.full_name` yoziladi;
4. asosiy menyu yuboriladi — «📝 Javoblarni belgilash» (Web App) ochiladi.

Ro'yxatdan o'tganlik belgisi — `user_profiles` qatorining mavjudligi. Shu
sababli keyingi `/start` larda ism/familiya qayta so'ralmaydi.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import texts
from database.repository import Repositories
from handlers.menu import send_main_menu
from services import user_names
from states import RegistrationStates

logger = logging.getLogger(__name__)

router = Router(name="registration")

FIRST_NAME_FIELD = "Ism"
LAST_NAME_FIELD = "Familiya"

#: FSM ichida ismni vaqtincha saqlash kaliti (admin ustasi bilan to'qnashmasin).
FIRST_NAME_KEY = "registration_first_name"


async def begin_registration(message: Message, state: FSMContext) -> None:
    """Ro'yxatdan o'tishni boshidan boshlaydi va ismni so'raydi."""
    await state.clear()
    await state.set_state(RegistrationStates.first_name)
    await message.answer(texts.ask_first_name())


async def is_registered(repos: Repositories, user_id: int) -> bool:
    """Foydalanuvchi ism/familiyani kiritib ro'yxatdan o'tganmi?"""
    return await repos.profiles.exists(user_id)


async def require_registration(
    message: Message, state: FSMContext, repos: Repositories
) -> bool:
    """Profil borligini tekshiradi; yo'q bo'lsa ro'yxatdan o'tishni boshlaydi.

    Returns:
        `True` — profil mavjud, davom etish mumkin;
        `False` — ro'yxatdan o'tish boshlandi (chaqiruvchi to'xtashi kerak).
    """
    if message.from_user is None:
        return False
    if await is_registered(repos, message.from_user.id):
        return True
    await begin_registration(message, state)
    return False


@router.message(RegistrationStates.first_name, F.text, ~F.text.startswith("/"))
async def process_first_name(message: Message, state: FSMContext) -> None:
    """1-qadam: ismni qabul qiladi va familiyani so'raydi."""
    try:
        first_name = user_names.validate_name(message.text or "", field=FIRST_NAME_FIELD)
    except user_names.InvalidNameError as exc:
        await message.answer(texts.invalid_name(FIRST_NAME_FIELD, str(exc)))
        return

    await state.update_data({FIRST_NAME_KEY: first_name})
    await state.set_state(RegistrationStates.last_name)
    await message.answer(texts.ask_last_name(first_name))


@router.message(RegistrationStates.last_name, F.text, ~F.text.startswith("/"))
async def process_last_name(
    message: Message, state: FSMContext, repos: Repositories
) -> None:
    """2-qadam: familiyani qabul qiladi, profilni saqlaydi va menyuni ochadi."""
    if message.from_user is None:  # pragma: no cover - Telegram har doim yuboradi
        return

    try:
        last_name = user_names.validate_name(message.text or "", field=LAST_NAME_FIELD)
    except user_names.InvalidNameError as exc:
        await message.answer(texts.invalid_name(LAST_NAME_FIELD, str(exc)))
        return

    data = await state.get_data()
    first_name = str(data.get(FIRST_NAME_KEY) or "").strip()
    if not first_name:
        # Holat yo'qolgan (masalan, bot qayta ishga tushgan) — boshidan boshlaymiz.
        await begin_registration(message, state)
        return

    try:
        profile = await repos.profiles.save(
            message.from_user.id, first_name, last_name
        )
    except Exception:
        logger.exception(
            "Foydalanuvchi profilini saqlashda xatolik: user_id=%s",
            message.from_user.id,
        )
        await message.answer(texts.registration_save_error())
        return

    await state.clear()
    await message.answer(texts.registration_completed(profile.full_name))
    await send_main_menu(
        message,
        user_id=message.from_user.id,
        full_name=profile.full_name,
        repos=repos,
    )
    logger.info(
        "Foydalanuvchi ro'yxatdan o'tdi: user_id=%s, ism-familiya=%r",
        message.from_user.id,
        profile.full_name,
    )


@router.message(Command("cancel"), RegistrationStates.first_name)
@router.message(Command("cancel"), RegistrationStates.last_name)
async def cancel_registration(message: Message, state: FSMContext) -> None:
    """Ro'yxatdan o'tishni bekor qiladi (keyin /start bilan davom etish mumkin)."""
    await state.clear()
    await message.answer(texts.registration_cancelled())
