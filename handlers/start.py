"""Bosh menyu: `/start`, `/help`, reply menyu va Web App tugmasi.

Ilova Telegram Web App (Mini App) ko'rinishida ishlaydi. `/start` da ikki
xabar yuboriladi:
    1. pastdagi (reply) menyu — «🔍 Test tahlili», «🏡 Asosiy menyu»
       (+ admin uchun «🎬 Yechim yuklash»);
    2. asosiy inline menyu — Web App tugmasi va admin boshqaruv tugmalari.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

import config
import texts
from handlers.access import is_admin
from keyboards.inline import AppCallback, MenuCallback, webapp_kb
from keyboards.reply import HOME_BUTTON, main_reply_kb

logger = logging.getLogger(__name__)

router = Router(name="start")


async def send_main_menu(target: Message, *, user_id: int, full_name: str) -> None:
    """Reply menyuni va asosiy inline menyuni yuboradi."""
    admin = is_admin(user_id)
    await target.answer(texts.reply_menu_hint(), reply_markup=main_reply_kb(is_admin=admin))
    await target.answer(
        texts.webapp_welcome(full_name, webapp_ready=bool(config.WEBAPP_URL)),
        reply_markup=webapp_kb(is_admin=admin),
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """O'quvchini kutib oladi, reply va Web App menyularini ko'rsatadi."""
    if message.from_user is None:  # pragma: no cover - Telegram har doim yuboradi
        return

    await send_main_menu(
        message, user_id=message.from_user.id, full_name=message.from_user.full_name
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Yordam xabari (`/help`)."""
    if message.from_user is None:
        return

    admin = is_admin(message.from_user.id)
    await message.answer(texts.reply_menu_hint(), reply_markup=main_reply_kb(is_admin=admin))
    await message.answer(texts.help_text(), reply_markup=webapp_kb(is_admin=admin))


@router.message(F.text == HOME_BUTTON)
async def reply_home(message: Message) -> None:
    """Reply menyudagi «🏡 Asosiy menyu» tugmasi."""
    if message.from_user is None:
        return

    await send_main_menu(
        message, user_id=message.from_user.id, full_name=message.from_user.full_name
    )


@router.callback_query(MenuCallback.filter(F.action == "back"))
@router.callback_query(AppCallback.filter(F.action == "home"))
async def back_to_main_menu(call: CallbackQuery) -> None:
    """Inline menyudagi «🏠/🏡 Asosiy menyu» tugmasi."""
    await call.answer()
    if call.message is None:
        return

    await send_main_menu(
        call.message, user_id=call.from_user.id, full_name=call.from_user.full_name
    )


@router.callback_query(AppCallback.filter(F.action == "help"))
async def show_help(call: CallbackQuery) -> None:
    """«ℹ️ Yordam» tugmasi."""
    await call.answer()
    if call.message is None:
        return

    await call.message.answer(
        texts.help_text(),
        reply_markup=webapp_kb(is_admin=is_admin(call.from_user.id)),
    )


@router.callback_query(AppCallback.filter(F.action == "missing"))
async def webapp_not_configured(call: CallbackQuery) -> None:
    """Web App manzili sozlanmagan bo'lsa — ogohlantiradi."""
    message = texts.webapp_button_missing()
    await call.answer(message[:200], show_alert=True)
    if call.message is not None:
        await call.message.answer(message)
