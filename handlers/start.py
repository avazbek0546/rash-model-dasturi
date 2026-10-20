"""Bosh menyu: `/start`, `/help` va inline menyu.

Pastdagi (reply) klaviatura **ishlatilmaydi** — barcha bo'limlar bitta inline
menyuda. Tartib: «📝 Javoblarni belgilash» (Mini App) → «🔍 Test tahlili» →
«🏡 Asosiy menyu» → (admin tugmalari) → «ℹ️ Yordam».

Eski foydalanuvchilarda qolib ketgan reply klaviatura `/start` da
`ReplyKeyboardRemove` bilan tozalanadi (yuborilgan xabar darhol o'chiriladi).
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import config
import texts
from database.repository import Repositories
from handlers.access import is_admin
from handlers.admin_solution import start_target_upload
from keyboards.inline import AppCallback, MenuCallback, back_kb, webapp_kb
from keyboards.reply import HOME_BUTTON

logger = logging.getLogger(__name__)

router = Router(name="start")


async def _clear_reply_keyboard(target: Message) -> None:
    """Eski pastdagi (reply) menyuni olib tashlaydi.

    Telegram reply klaviaturasi xabar bilan birga yuboriladi — uni olib
    tashlash uchun `ReplyKeyboardRemove` bilan bitta xabar yuborish kerak.
    Foydalanuvchi ko'rmasligi uchun bu xabar darhol o'chiriladi.
    """
    try:
        cleanup = await target.answer(
            "🧭 Menyu yangilandi", reply_markup=ReplyKeyboardRemove()
        )
        await target.bot.delete_message(
            chat_id=cleanup.chat.id, message_id=cleanup.message_id
        )
    except TelegramBadRequest:
        logger.debug("Eski reply menyuni olib tashlab bo'lmadi", exc_info=True)


async def send_main_menu(
    target: Message,
    *,
    user_id: int,
    full_name: str,
    edit: bool = False,
) -> None:
    """Asosiy inline menyuni yuboradi (yoki mavjud xabarni tahrirlaydi)."""
    admin = is_admin(user_id)
    text = texts.webapp_welcome(full_name, webapp_ready=bool(config.WEBAPP_URL))
    markup = webapp_kb(is_admin=admin)

    if edit:
        try:
            await target.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest as exc:
            # Menyu allaqachon shu ko'rinishda bo'lsa — dublikat xabar yubormaymiz.
            if "message is not modified" in str(exc):
                return
            # Xabar media bo'lsa — yangi xabar yuboriladi.
            logger.debug("Menyuni tahrirlab bo'lmadi — yangi xabar", exc_info=True)

    await target.answer(text, reply_markup=markup)


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

    await _clear_reply_keyboard(message)
    await send_main_menu(
        message, user_id=message.from_user.id, full_name=message.from_user.full_name
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Yordam xabari (`/help`)."""
    if message.from_user is None:
        return

    admin = is_admin(message.from_user.id)
    await message.answer(
        texts.help_text(is_admin=admin),
        reply_markup=webapp_kb(is_admin=admin),
    )


@router.message(F.text == HOME_BUTTON)
async def reply_home(message: Message) -> None:
    """Eski reply menyudagi «🏡 Asosiy menyu» (moslik uchun qoldirilgan)."""
    if message.from_user is None:
        return

    await _clear_reply_keyboard(message)
    await send_main_menu(
        message, user_id=message.from_user.id, full_name=message.from_user.full_name
    )


@router.callback_query(MenuCallback.filter(F.action == "back"))
@router.callback_query(AppCallback.filter(F.action == "home"))
async def back_to_main_menu(call: CallbackQuery) -> None:
    """Inline menyudagi «🏡 Asosiy menyu» tugmasi — xabarni yangilaydi."""
    await call.answer()
    if call.message is None:
        return

    await send_main_menu(
        call.message,
        user_id=call.from_user.id,
        full_name=call.from_user.full_name,
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
async def show_help(call: CallbackQuery) -> None:
    """«ℹ️ Yordam» tugmasi."""
    await call.answer()
    if call.message is None:
        return

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

