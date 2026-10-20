"""Kutilmagan xabarlar va eskirgan tugmalar uchun javob.

Bu router ENG OXIRGI bo'lib ulanadi (`handlers/__init__.py` ga qarang),
aks holda u boshqa router'larning komandalarini "yutib yuboradi".
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, Message

import texts
from handlers.access import is_admin
from keyboards.inline import webapp_kb

router = Router(name="fallback")


@router.message()
async def unexpected_message(message: Message) -> None:
    """Komandaga mos kelmagan xabarga yordam va menyu bilan javob beradi."""
    if message.from_user is None:
        return

    await message.answer(
        texts.help_text(is_admin=is_admin(message.from_user.id)),
        reply_markup=webapp_kb(is_admin=is_admin(message.from_user.id)),
    )


@router.callback_query()
async def unexpected_callback(call: CallbackQuery) -> None:
    """Eskirgan (hech bir handler'ga mos kelmagan) callback tugmalari."""
    await call.answer(
        "Bu tugma eskirgan. /start buyrug'i bilan menyuni yangilang.",
        show_alert=False,
    )