"""«Mening natijalarim» bo'limi."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import config
import texts
from database.repository import Repositories
from keyboards.inline import MenuCallback, back_kb

router = Router(name="results")


async def _send_results(target: Message, user_id: int, full_name: str, repos: Repositories) -> None:
    """Natijalar va statistikani yuboradi."""
    results = await repos.results.last_for_user(user_id, config.RESULT_HISTORY_LIMIT)
    stats = await repos.results.stats_for_user(user_id)
    await target.answer(
        texts.results_history(results, stats, full_name),
        reply_markup=back_kb(),
    )


@router.callback_query(MenuCallback.filter(F.action == "results"))
async def my_results(call: CallbackQuery, repos: Repositories) -> None:
    """Menyudan «📊 Mening natijalarim» tugmasi."""
    await call.answer()
    if call.message is None:
        return
    await _send_results(call.message, call.from_user.id, call.from_user.full_name, repos)


@router.message(Command("results"))
async def results_command(message: Message, repos: Repositories) -> None:
    """`/results` komandasi."""
    if message.from_user is None:
        return
    await _send_results(message, message.from_user.id, message.from_user.full_name, repos)