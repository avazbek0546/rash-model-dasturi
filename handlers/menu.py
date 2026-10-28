"""Asosiy inline menyu va eski reply klaviaturani tozalash.

Bu modul `start` va `registration` router'lari tomonidan birgalikda
ishlatiladi — aylanma import bo'lmasligi uchun alohida ajratilgan.
"""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, ReplyKeyboardRemove

import config
import texts
from database.repository import Repositories
from handlers.access import is_admin
from keyboards.inline import webapp_kb

logger = logging.getLogger(__name__)


async def clear_reply_keyboard(target: Message) -> None:
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
    repos: Repositories | None = None,
    edit: bool = False,
) -> None:
    """Asosiy inline menyuni yuboradi (yoki mavjud xabarni tahrirlaydi).

    `repos` berilsa, foydalanuvchi kiritgan ism-familiya (agar mavjud bo'lsa)
    Telegram ismidan ustun turadi.
    """
    if repos is not None:
        profile = await repos.profiles.get(user_id)
        if profile is not None:
            # `users.full_name` — ko'rsatish uchun asosiy manba: Web App'dagi
            # «Profil» bo'limi ham shu maydonni yangilaydi. Profil jadvali
            # ro'yxatdan o'tganlik va tuzilgan ism/familiya uchun saqlanadi.
            user = await repos.users.get(user_id)
            full_name = (
                user.full_name
                if user is not None and user.full_name.strip()
                else profile.full_name
            )

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
