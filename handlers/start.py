"""Bosh menyu: `/start`, `/help` va inline menyu.

Pastdagi (reply) klaviatura **ishlatilmaydi** — barcha bo'limlar bitta inline
menyuda. Tartib: «📝 Javoblarni belgilash» (Mini App) → «🔍 Test tahlili» →
«🏡 Asosiy menyu» → (admin tugmalari) → «ℹ️ Yordam».

Birinchi kirishda `/start` foydalanuvchidan **ism va familiyani** so'raydi
(`handlers.registration`). Profil saqlangandan keyingina test bo'limi
(«📝 Javoblarni belgilash») ochiladi.

Eski foydalanuvchilarda qolib ketgan reply klaviatura `/start` da
`ReplyKeyboardRemove` bilan tozalanadi (yuborilgan xabar darhol o'chiriladi).
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import texts
from database.repository import Repositories
from handlers.access import is_admin
from handlers.admin_solution import start_target_upload
from handlers.menu import clear_reply_keyboard, send_main_menu
from handlers.registration import is_registered, require_registration
from keyboards.inline import AppCallback, MenuCallback, back_kb, webapp_kb
from keyboards.reply import HOME_BUTTON

logger = logging.getLogger(__name__)

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, repos: Repositories
) -> None:
    """O'quvchini kutib oladi; **admin** deep-link'i bo'lsa — yuklash holatini yoqadi."""
    if message.from_user is None:  # pragma: no cover - Telegram har doim yuboradi
        return

    # Panel deep-link'i (`/start s_<kod>_<belgi>`) — faqat admin uchun ishlaydi.
    if await start_target_upload(message, state, repos, text=message.text or ""):
        return

    await clear_reply_keyboard(message)
    if not await require_registration(message, state, repos):
        return

    profile = await repos.profiles.get(message.from_user.id)
    full_name = (
        profile.full_name if profile is not None else message.from_user.full_name
    )
    await send_main_menu(
        message,
        user_id=message.from_user.id,
        full_name=full_name,
        repos=repos,
    )


@router.message(Command("help"))
async def cmd_help(
    message: Message, state: FSMContext, repos: Repositories
) -> None:
    """Yordam xabari (`/help`)."""
    if message.from_user is None:
        return

    if not await require_registration(message, state, repos):
        return

    admin = is_admin(message.from_user.id)
    await message.answer(
        texts.help_text(is_admin=admin),
        reply_markup=webapp_kb(is_admin=admin),
    )


@router.message(F.text == HOME_BUTTON)
async def reply_home(
    message: Message, state: FSMContext, repos: Repositories
) -> None:
    """Eski reply menyudagi «🏡 Asosiy menyu» (moslik uchun qoldirilgan)."""
    if message.from_user is None:
        return

    await clear_reply_keyboard(message)
    if not await require_registration(message, state, repos):
        return

    profile = await repos.profiles.get(message.from_user.id)
    full_name = (
        profile.full_name if profile is not None else message.from_user.full_name
    )
    await send_main_menu(
        message,
        user_id=message.from_user.id,
        full_name=full_name,
        repos=repos,
    )


@router.callback_query(MenuCallback.filter(F.action == "back"))
@router.callback_query(AppCallback.filter(F.action == "home"))
async def back_to_main_menu(call: CallbackQuery, repos: Repositories) -> None:
    """Inline menyudagi «🏡 Asosiy menyu» tugmasi — xabarni yangilaydi."""
    if call.message is None:
        await call.answer()
        return

    if not is_admin(call.from_user.id) and not await is_registered(
        repos, call.from_user.id
    ):
        await call.answer(texts.registration_required(), show_alert=True)
        return

    await call.answer()
    profile = await repos.profiles.get(call.from_user.id)
    full_name = (
        profile.full_name if profile is not None else call.from_user.full_name
    )
    await send_main_menu(
        call.message,
        user_id=call.from_user.id,
        full_name=full_name,
        repos=repos,
        edit=True,
    )


@router.callback_query(AppCallback.filter(F.action == "upload"))
async def show_upload_help(call: CallbackQuery) -> None:
    """«🎬 Yechim yuklash» — video/rasm yuklash yo'riqnomasi (faqat admin)."""
    if not is_admin(call.from_user.id):
        await call.answer(texts.not_admin(), show_alert=True)
        return

    await call.answer()
    if call.message is None:
        return

    await call.message.answer(texts.solution_admin_intro(), reply_markup=back_kb())


@router.callback_query(AppCallback.filter(F.action == "help"))
async def show_help(call: CallbackQuery, repos: Repositories) -> None:
    """«ℹ️ Yordam» tugmasi."""
    if call.message is None:
        await call.answer()
        return

    if not is_admin(call.from_user.id) and not await is_registered(
        repos, call.from_user.id
    ):
        await call.answer(texts.registration_required(), show_alert=True)
        return

    await call.answer()
    await call.message.answer(
        texts.help_text(is_admin=is_admin(call.from_user.id)),
        reply_markup=webapp_kb(is_admin=is_admin(call.from_user.id)),
    )


@router.callback_query(AppCallback.filter(F.action == "missing"))
async def webapp_not_configured(call: CallbackQuery) -> None:
    """Web App manzili sozlanmagan bo'lsa — ogohlantiradi."""
    message = texts.webapp_button_missing()
    await call.answer(message[:200], show_alert=True)
    if call.message is not None:
        await call.message.answer(message)

