"""Foydalanuvchilarni ma'lumotlar bazasi bilan sinxronlashtiruvchi middleware.

Har bir yangilanishda (message/callback) Telegram'dan kelgan foydalanuvchi
`users` jadvaliga yoziladi — lekin har safar emas: ism o'zgargan holatdagina
UPDATE bo'ladi (keraksiz SQL yozuvlaridan qochish uchun).

Muhim qoida: botda ism/familiyani kiritib **ro'yxatdan o'tgan** foydalanuvchi
uchun `full_name` o'zgartirilmaydi — Telegram profili nomi o'zgarsa ham
o'quvchi kiritgan qiymat saqlanib qoladi. Bunday foydalanuvchida faqat
`username` yangilanadi.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from database.models import User
from database.repository import Repositories

logger = logging.getLogger(__name__)


class UserSyncMiddleware(BaseMiddleware):
    """`users` jadvalini joriy holatda saqlaydi."""

    def __init__(self) -> None:
        # user_id → oxirgi ma'lum bo'lgan ism (kesh)
        self._known: dict[int, str] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user") or getattr(event, "from_user", None)
        repos: Repositories | None = data.get("repos")

        if tg_user is not None and repos is not None and not tg_user.is_bot:
            full_name = tg_user.full_name or tg_user.first_name or "Noma'lum"
            # DIQQAT: telegram User obyektida id maydoni `.id` deb nomlanadi
            # (bizning database.models.User da esa `.user_id`).
            if self._known.get(tg_user.id) != full_name:
                if await repos.profiles.exists(tg_user.id):
                    # Ro'yxatdan o'tgan: ism/familiya o'quvchi kiritgan qiymat.
                    await repos.users.update_username(tg_user.id, tg_user.username)
                else:
                    await repos.users.upsert(
                        User(
                            user_id=tg_user.id,
                            full_name=full_name,
                            username=tg_user.username,
                        )
                    )
                self._known[tg_user.id] = full_name
                logger.debug("Foydalanuvchi sinxronlashtirildi: %s (%s)", full_name, tg_user.id)

        return await handler(event, data)