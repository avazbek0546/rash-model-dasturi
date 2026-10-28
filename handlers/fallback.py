"""Kutilmagan xabarlar va eskirgan tugmalar uchun javob.

Bu router ENG OXIRGI bo'lib ulanadi (`handlers/__init__.py` ga qarang),
aks holda u boshqa router'larning komandalarini "yutib yuboradi".
"""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import texts
from database.repository import Repositories
from handlers.access import is_admin
from handlers.registration import begin_registration, is_registered
from keyboards.inline import webapp_kb

router = Router(name="fallback")


@router.message()
async def unexpected_message(
    message: Message, state: FSMContext, repos: Repositories
) -> None:
    """Komandaga mos kelmagan xabarga yordam va menyu bilan javob beradi."""
    if message.from_user is None:
        return

    admin = is_admin(message.from_user.id)
    if not admin and not await is_registered(repos, message.from_user.id):
        await begin_registration(message, state)
        return

    profile = await repos.profiles.get(message.from_user.id)
    full_name = (
        profile.full_name if profile is not None else message.from_user.full_name
    )
    await message.answer(
        texts.help_text(is_admin=admin),
        reply_markup=webapp_kb(is_admin=admin),
    )


@router.callback_query()
async def unexpected_callback(call: CallbackQuery, repos: Repositories) -> None:
    """Eskirgan (hech bir handler'ga mos kelmagan) callback tugmalari."""
    if not is_admin(call.from_user.id) and not await is_registered(
        repos, call.from_user.id
    ):
        await call.answer(texts.registration_required(), show_alert=True)
        return

    await call.answer(
        "Bu tugma eskirgan. /start buyrug'i bilan menyuni yangilang.",
        show_alert=False,
    )