"""«Rasch modeli haqida» bo'limi."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import texts
from keyboards.inline import MenuCallback, back_kb

router = Router(name="about")


@router.callback_query(MenuCallback.filter(F.action == "about"))
async def show_about(call: CallbackQuery) -> None:
    """Menyudan «ℹ️ Rasch modeli haqida» tugmasi."""
    await call.answer()
    if call.message is None:
        return
    await call.message.edit_text(texts.about(), reply_markup=back_kb())


@router.message(Command("about"))
async def about_command(message: Message) -> None:
    """`/about` komandasi."""
    await message.answer(texts.about(), reply_markup=back_kb())