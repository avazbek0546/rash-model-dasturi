"""Adminlarni boshqarish: `/admins` paneli (faqat o'qituvchi uchun).

Imkoniyatlar
------------
* **Ro'yxat** — `.env` dagi "egasi" adminlar va bot ichidan qo'shilganlar;
* **Qo'shish** — yangi odamning xabarini **forward** qilish kifoya (ID qidirish
  shart emas); zaxira sifatida ID raqamini yozish ham qabul qilinadi;
* **O'chirish** — har bir admin yonidagi «🗑» tugmasi, tasdiqlash bilan;
* **Himoya** — `.env` orqali berilgan "egasi" adminlar o'chirilmaydi
  (lock-out: hech kim barcha adminlarni o'chirib qo'ya olmaydi).

O'zgarishlar bazaga (`bot_admins`) yoziladi va darhol xotiraga
(`config.add_admin` / `config.remove_admin`) qo'llanadi — qayta deploy kerak
emas. Bot qayta ishga tushganda `main.py` ro'yxatni bazadan tiklaydi.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommandScopeChat, CallbackQuery, Message

import bot_commands
import config
import texts
from database.models import BotAdmin
from database.repository import Repositories
from handlers.access import is_admin, log_denied
from keyboards.inline import (
    AdminManageCallback,
    admin_add_confirm_kb,
    admin_delete_confirm_kb,
    admins_panel_kb,
)
from states import AdminManageStates

logger = logging.getLogger(__name__)

router = Router(name="admin_manage")

#: FSM ma'lumotlarida nomzod (`forward` qilingan odam) saqlanadigan kalit.
CANDIDATE_KEY = "admin_candidate"


def _mention(full_name: str | None, username: str | None, user_id: int) -> str:
    """Odamni xabarda ko'rsatish uchun matn: «Ism (@username)» yoki «ID …»."""
    name = (full_name or "").strip() or f"ID {user_id}"
    return f"{name} (@{username})" if username else name


def _panel_text(admins: list[BotAdmin]) -> str:
    """Panel matnini tayyorlaydi (egasi adminlar + bazadagilar)."""
    return texts.admin_manage_panel(
        owners=[f"ID {uid}" for uid in sorted(config.OWNER_ADMIN_IDS)],
        extras=[{"user_id": item.user_id, "mention": item.mention} for item in admins],
    )


async def _send_panel(message: Message, repos: Repositories) -> None:
    """Adminlar panelini yuboradi (ro'yxat + tugmalar)."""
    admins = await repos.admins.list_all()
    await message.answer(_panel_text(admins), reply_markup=admins_panel_kb(admins))


def _candidate_from_message(message: Message) -> tuple[int, str | None, str | None] | None:
    """Xabardan nomzodni ajratib oladi: `(user_id, full_name, username)`.

    Avval **forward** ma'lumoti tekshiriladi (Bot API 7+ `forward_origin`,
    keyin eski `forward_from`), oxirida — oddiy ID raqami. Aniqlanmasa `None`.
    """
    origin = getattr(message, "forward_origin", None)
    if origin is not None and getattr(origin, "type", "") == "user":
        sender = getattr(origin, "sender_user", None)
        if sender is not None:
            return sender.id, sender.full_name, sender.username

    sender = getattr(message, "forward_from", None)  # eski maydonlar (moslik)
    if sender is not None:
        return sender.id, sender.full_name, sender.username

    raw = (message.text or "").strip()
    if raw.isdigit() and len(raw) >= 5:
        return int(raw), None, None
    return None


@router.message(Command("admins"))
async def cmd_admins(
    message: Message, state: FSMContext, repos: Repositories
) -> None:
    """`/admins` — adminlar paneli (faqat admin uchun)."""
    if message.from_user is None:
        return

    await state.clear()  # oldingi "forward kutish" holatini yopamiz
    if not is_admin(message.from_user.id):
        log_denied("/admins", message.from_user.id, message.from_user.full_name)
        return  # oddiy o'quvchiga hech narsa ko'rsatilmaydi

    await _send_panel(message, repos)


@router.callback_query(AdminManageCallback.filter(F.action == "add"))
async def cb_add(call: CallbackQuery, state: FSMContext) -> None:
    """«➕ Admin qo'shish» — forward kutish holatini yoqadi."""
    if call.from_user is None:
        return
    if not is_admin(call.from_user.id):
        log_denied("admins:add", call.from_user.id, call.from_user.full_name)
        await call.answer(texts.not_admin(), show_alert=True)
        return

    await state.set_state(AdminManageStates.waiting_forward)
    await state.update_data(**{CANDIDATE_KEY: None})
    await call.answer()
    if isinstance(call.message, Message):
        await call.message.answer(texts.admin_add_prompt())


def _is_not_command(message: Message) -> bool:
    """Holat ichida buyruqlarni (`/start`, `/admins`...) o'tkazib yubormaydi."""
    return not (message.text or "").startswith("/")


@router.message(StateFilter(AdminManageStates.waiting_forward), _is_not_command)
async def on_candidate(
    message: Message, state: FSMContext, repos: Repositories
) -> None:
    """Forward qilingan xabar (yoki ID raqami) → tasdiqlash so'rovi."""
    if message.from_user is None:
        return
    if not is_admin(message.from_user.id):
        log_denied("admin qo'shish", message.from_user.id, message.from_user.full_name)
        await state.clear()
        return

    candidate = _candidate_from_message(message)
    if candidate is None:
        await message.answer(texts.admin_add_unknown())
        return

    user_id, full_name, username = candidate
    mention = _mention(full_name, username, user_id)
    already = is_admin(user_id) or await repos.admins.exists(user_id)

    await state.update_data(
        **{
            CANDIDATE_KEY: {
                "user_id": user_id,
                "full_name": full_name,
                "username": username,
            }
        }
    )
    await state.set_state(None)  # keyingi qadam — tugma bilan tasdiqlash
    await message.answer(
        texts.admin_add_confirm(mention, user_id, already=already),
        reply_markup=None if already else admin_add_confirm_kb(user_id),
    )


async def _replace_and_refresh(
    query: CallbackQuery, repos: Repositories, text: str
) -> None:
    """Tasdiq xabarini natija matniga almashtiradi va panelni yangilab yuboradi."""
    if not isinstance(query.message, Message):
        return
    try:
        await query.message.edit_text(text)
    except TelegramBadRequest:  # pragma: no cover - eskirgan xabar / bir xil matn
        await query.message.answer(text)
    admins = await repos.admins.list_all()
    await query.message.answer(_panel_text(admins), reply_markup=admins_panel_kb(admins))


async def _apply_admin_commands(bot: Bot, user_id: int) -> None:
    """Yangi adminga «/» komandalar menyusini o'rnatadi (imkon bo'lsa).

    Foydalanuvchi botga hali yozmagan bo'lsa Telegram xato qaytarishi mumkin —
    bu muhim emas: u `/start` bosganda komandalar baribir ko'rinadi.
    """
    try:
        await bot.set_my_commands(
            list(bot_commands.ADMIN_COMMANDS),
            scope=BotCommandScopeChat(chat_id=user_id),
        )
    except Exception:  # pragma: no cover - tarmoq/Telegram cheklovi
        logger.debug(
            "Yangi admin uchun komandalar o'rnatilmadi: %s", user_id, exc_info=True
        )


@router.callback_query(AdminManageCallback.filter(F.action == "confirm_add"))
async def cb_confirm_add(
    query: CallbackQuery, state: FSMContext, repos: Repositories, bot: Bot
) -> None:
    """Tasdiqlangach: bazaga yozadi, xotiraga qo'shadi, yangi adminni xabardor qiladi."""
    if query.from_user is None:
        return
    if not is_admin(query.from_user.id):
        log_denied("admins:confirm_add", query.from_user.id, query.from_user.full_name)
        await query.answer(texts.not_admin(), show_alert=True)
        return

    pressed = AdminManageCallback.unpack(query.data or "")
    data: dict[str, Any] = await state.get_data()
    candidate = data.get(CANDIDATE_KEY) or {}
    user_id = int(candidate.get("user_id") or pressed.user_id)

    full_name = candidate.get("full_name")
    username = candidate.get("username")
    mention = _mention(full_name, username, user_id)

    added_to_db = await repos.admins.add(
        user_id,
        full_name=full_name,
        username=username,
        added_by=query.from_user.id,
    )
    config.add_admin(user_id)
    await state.clear()
    await query.answer()

    if not added_to_db:
        await _replace_and_refresh(
            query, repos, texts.admin_add_confirm(mention, user_id, already=True)
        )
        return

    await _apply_admin_commands(bot, user_id)

    # Yangi adminni xabardor qilamiz (botni bloklagan bo'lsa — jim o'tamiz).
    try:
        me = await bot.me()
        await bot.send_message(user_id, texts.admin_new_notice(me.full_name))
    except Exception:  # pragma: no cover - bloklangan foydalanuvchi
        logger.info("Yangi adminga xabar yuborilmadi: %s", user_id)

    logger.info(
        "Yangi admin qo'shildi: %s (%s), qo'shgan: %s",
        mention,
        user_id,
        query.from_user.id,
    )
    await _replace_and_refresh(query, repos, texts.admin_added(mention))


@router.callback_query(AdminManageCallback.filter(F.action == "delete"))
async def cb_delete(query: CallbackQuery, repos: Repositories) -> None:
    """«🗑» — o'chirishdan oldin tasdiqlash so'raydi (tasodifiy bosishdan himoya)."""
    if query.from_user is None:
        return
    if not is_admin(query.from_user.id):
        log_denied("admins:delete", query.from_user.id, query.from_user.full_name)
        await query.answer(texts.not_admin(), show_alert=True)
        return

    user_id = AdminManageCallback.unpack(query.data or "").user_id
    if config.is_owner(user_id):
        await query.answer(texts.admin_owner_protected(), show_alert=True)
        return

    admin = await repos.admins.get(user_id)
    if admin is None:
        await query.answer(texts.admin_not_found(), show_alert=True)
        return

    await query.answer()
    if isinstance(query.message, Message):
        confirm_text = texts.admin_remove_confirm(admin.mention, user_id)
        try:
            await query.message.edit_text(
                confirm_text, reply_markup=admin_delete_confirm_kb(user_id)
            )
        except TelegramBadRequest:  # pragma: no cover
            await query.message.answer(
                confirm_text, reply_markup=admin_delete_confirm_kb(user_id)
            )


@router.callback_query(AdminManageCallback.filter(F.action == "confirm_delete"))
async def cb_confirm_delete(
    query: CallbackQuery, repos: Repositories, bot: Bot
) -> None:
    """Tasdiqlangach: bazadan va xotiradan o'chiradi."""
    if query.from_user is None:
        return
    if not is_admin(query.from_user.id):
        log_denied(
            "admins:confirm_delete", query.from_user.id, query.from_user.full_name
        )
        await query.answer(texts.not_admin(), show_alert=True)
        return

    user_id = AdminManageCallback.unpack(query.data or "").user_id
    if config.is_owner(user_id):
        await query.answer(texts.admin_owner_protected(), show_alert=True)
        return

    admin = await repos.admins.get(user_id)
    if admin is None or not await repos.admins.remove(user_id):
        await query.answer(texts.admin_not_found(), show_alert=True)
        return

    config.remove_admin(user_id)
    mention = admin.mention
    await query.answer()

    # O'chirilgan foydalanuvchidan admin komandalar menyusini olib tashlaymiz.
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=user_id))
    except Exception:  # pragma: no cover - tarmoq/Telegram xatosi
        logger.debug("Komandalar tozalanmadi: %s", user_id, exc_info=True)

    logger.info(
        "Admin o'chirildi: %s (%s), o'chirgan: %s",
        mention,
        user_id,
        query.from_user.id,
    )
    await _replace_and_refresh(query, repos, texts.admin_removed(mention))


@router.callback_query(AdminManageCallback.filter(F.action == "list"))
async def cb_list(query: CallbackQuery, state: FSMContext, repos: Repositories) -> None:
    """Panelni qayta ko'rsatish / bekor qilish."""
    if query.from_user is None:
        return
    if not is_admin(query.from_user.id):
        log_denied("admins:list", query.from_user.id, query.from_user.full_name)
        await query.answer(texts.not_admin(), show_alert=True)
        return

    await state.clear()
    await query.answer()
    if isinstance(query.message, Message):
        admins = await repos.admins.list_all()
        try:
            await query.message.edit_text(
                _panel_text(admins), reply_markup=admins_panel_kb(admins)
            )
        except TelegramBadRequest:  # pragma: no cover - matn o'zgarmagan
            logger.debug("Panelni tahrirlab bo'lmadi", exc_info=True)


