"""Admin chat: qatnashchilar jurnali va unga kirishni qo'riqlash.

Vazifalari
----------
* `/admin_chat` — guruhni qatnashchilar jurnali (admin chat) sifatida ulash;
  `/admin_chat off` — uzish. Bog'lanish `bot_settings.admin_chat_id` da
  saqlanadi, shu sababli qayta ishga tushirishda yo'qolmaydi.
* `chat_member` — admin chatga qo'shilgan **admin bo'lmagan** odamni darhol
  chiqarib yuborish (bot guruhda «Foydalanuvchilarni chetlatish» huquqi bilan
  administrator bo'lishi kerak).
* `chat_join_request` — admin bo'lmagan odamning qo'shilish so'rovini rad
  etish (guruh «so'rov bilan qo'shilish» rejimida bo'lsa).

Nega bot guruhni o'zi yaratmaydi? Telegram Bot API'da bunday metod yo'q.
Shu sababli guruhni admin yaratadi, bot esa uni ulaydi va qo'riqlaydi.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import ChatJoinRequest, ChatMemberUpdated, Message

import config
import texts
from database.repository import Repositories
from handlers.access import is_admin, log_denied
from services import admin_chat

logger = logging.getLogger(__name__)

router = Router(name="admin_chat")

#: Guruh turi (guruh va superguruh) — qolganlari (shaxsiy/kanal) rad etiladi.
GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}

#: Admin chatga kira oladigan holatlar (qolganlari chiqariladi).
ALLOWED_STATUSES = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}

#: `/admin_chat off` uchun qabul qilinadigan so'zlar.
OFF_WORDS = {"off", "uz", "uzish", "o'chirish", "ochirish", "o`chirish"}


@router.message(Command("admin_chat"))
async def cmd_admin_chat(message: Message, repos: Repositories, bot: Bot) -> None:
    """`/admin_chat` — guruhni ulash yoki yo'riqnoma ko'rsatish."""
    if message.from_user is None:
        return

    if not is_admin(message.from_user.id):
        log_denied(
            "/admin_chat", message.from_user.id, message.from_user.full_name
        )
        await message.answer(texts.not_admin())
        return

    parts = (message.text or "").split(maxsplit=1)
    argument = parts[1].strip().lower() if len(parts) > 1 else ""

    if argument in OFF_WORDS:
        removed = await admin_chat.unbind(repos)
        if removed:
            logger.info(
                "Admin chat uzildi: chat_id=%s, admin=%s",
                message.chat.id,
                message.from_user.id,
            )
            await message.answer(texts.admin_chat_unbound())
        else:
            await message.answer(
                texts.admin_chat_instructions(await admin_chat.chat_id(repos))
            )
        return

    if message.chat.type == ChatType.PRIVATE:
        await message.answer(
            texts.admin_chat_instructions(await admin_chat.chat_id(repos))
        )
        return

    if message.chat.type not in GROUP_TYPES:
        await message.answer(texts.admin_chat_group_only())
        return

    # Guruhni faqat uning administratori (va bot admini) bog'lashi mumkin.
    try:
        sender_member = await bot.get_chat_member(
            chat_id=message.chat.id, user_id=message.from_user.id
        )
    except TelegramAPIError:
        logger.exception(
            "Guruh a'zoligini tekshirib bo'lmadi: chat_id=%s", message.chat.id
        )
        await message.answer(
            "⚠️ Guruh ma'lumotini olib bo'lmadi. Bot guruhda administrator "
            "ekanini tekshiring."
        )
        return

    if sender_member.status not in ALLOWED_STATUSES:
        await message.answer(texts.admin_chat_group_admin_required())
        return

    try:
        me = await bot.get_me()
        bot_member = await bot.get_chat_member(
            chat_id=message.chat.id, user_id=me.id
        )
    except TelegramAPIError:
        logger.exception(
            "Botning guruhdagi huquqlarini tekshirib bo'lmadi: chat_id=%s",
            message.chat.id,
        )
        await message.answer(texts.admin_chat_bot_admin_required())
        return

    if bot_member.status not in ALLOWED_STATUSES:
        await message.answer(texts.admin_chat_bot_admin_required())
        return

    await admin_chat.bind(repos, message.chat.id)
    logger.info(
        "Admin chat bog'landi: chat_id=%s, title=%r, admin=%s",
        message.chat.id,
        message.chat.title,
        message.from_user.id,
    )
    await message.answer(
        texts.admin_chat_bound(message.chat.title or "", message.chat.id)
    )
    if not getattr(bot_member, "can_restrict_members", True):
        await message.answer(texts.admin_chat_restrict_warning())


@router.chat_member()
async def on_chat_member(
    update: ChatMemberUpdated, repos: Repositories, bot: Bot
) -> None:
    """Admin chatga qo'shilgan admin bo'lmagan odamni chiqarib yuboradi."""
    if update.chat.type not in GROUP_TYPES:
        return
    if not await admin_chat.is_admin_chat(repos, update.chat.id):
        return

    member = update.new_chat_member
    if member.user.is_bot:
        return
    if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
        return
    if config.is_admin(member.user.id):
        return

    # Guruh administratorini bot chiqara olmaydi — faqat ogohlantiramiz.
    if member.status in ALLOWED_STATUSES:
        logger.warning(
            "Admin chatda admin bo'lmagan guruh administratori: chat_id=%s, "
            "user_id=%s",
            update.chat.id,
            member.user.id,
        )
        return

    try:
        await bot.ban_chat_member(
            chat_id=update.chat.id, user_id=member.user.id
        )
        # Ban'ni darhol olib tashlaymiz — bu «chiqarib yuborish» bo'ladi,
        # keyinchalik odam admin qilinsa, qayta qo'shila oladi.
        await bot.unban_chat_member(
            chat_id=update.chat.id, user_id=member.user.id
        )
    except TelegramAPIError:
        logger.warning(
            "Admin chatdan chiqarib bo'lmadi (huquq yetarli emas?): "
            "chat_id=%s, user_id=%s",
            update.chat.id,
            member.user.id,
            exc_info=True,
        )
        return

    logger.info(
        "Admin chatdan chiqarildi: chat_id=%s, user_id=%s, name=%r",
        update.chat.id,
        member.user.id,
        member.user.full_name,
    )
    try:
        await bot.send_message(
            chat_id=update.chat.id,
            text=texts.admin_chat_kicked(member.user.full_name),
        )
    except TelegramAPIError:  # xabar ketmasa ham chiqarish bajarildi
        logger.debug("Chiqarilgan odam haqida xabar yuborilmadi", exc_info=True)


@router.chat_join_request()
async def on_chat_join_request(
    update: ChatJoinRequest, repos: Repositories, bot: Bot
) -> None:
    """Admin bo'lmagan odamning admin chatga qo'shilish so'rovini rad etadi."""
    if update.chat.type not in GROUP_TYPES:
        return
    if not await admin_chat.is_admin_chat(repos, update.chat.id):
        return
    if config.is_admin(update.from_user.id):
        return

    try:
        await bot.decline_chat_join_request(
            chat_id=update.chat.id, user_id=update.from_user.id
        )
    except TelegramAPIError:
        logger.warning(
            "Qo'shilish so'rovini rad etib bo'lmadi: chat_id=%s, user_id=%s",
            update.chat.id,
            update.from_user.id,
            exc_info=True,
        )
        return
    logger.info(
        "Admin chatga qo'shilish so'rovi rad etildi: chat_id=%s, user_id=%s",
        update.chat.id,
        update.from_user.id,
    )