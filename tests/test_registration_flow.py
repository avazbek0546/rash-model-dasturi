"""Botda majburiy ro'yxatdan o'tish oqimini Telegram'siz sinaydi.

Tekshiriladi
------------
1. `/start` → ism so'raladi → familiya so'raladi → menyu ochiladi;
2. noto'g'ri ism/familiya (raqam, belgi, juda qisqa) qabul qilinmaydi;
3. ro'yxatdan o'tgandan keyin `/start` ismni qayta so'ramaydi;
4. `/app` ro'yxatdan o'tmagan o'quvchini test bo'limiga kiritmaydi;
5. middleware Telegram ismi o'zgarganda o'quvchi kiritgan ism-familiyani
   ustidan yozmaydi (faqat `username` yangilanadi);
6. `services.user_names` apostrof/bo'shliq va harf tekshiruvi.

Ishga tushirish:
    python tests/test_registration_flow.py
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.methods import DeleteMessage, GetMe, SendMessage  # noqa: E402
from aiogram.types import Message, Update  # noqa: E402
from aiogram.types import User as TgUser  # noqa: E402

import config  # noqa: E402
from database.db import Database  # noqa: E402
from database.repository import Repositories  # noqa: E402
from handlers import setup_routers  # noqa: E402
from middlewares import UserSyncMiddleware  # noqa: E402
from services import user_names  # noqa: E402

TOKEN = "123456789:AARegistrationFlowChecks"
BOT_ID = 123456789
ADMIN_ID = 999_000_001
USER_ID = 999_000_002
USER2_ID = 999_000_003
NOW = int(time.time())

config.BOT_TOKEN = TOKEN
config.ADMIN_ID = ADMIN_ID
config.ADMIN_IDS = frozenset({ADMIN_ID})
config.WEBAPP_URL = "https://exam.example.uz"
config.WEBAPP_DEV_MODE = False


def user_json(user_id: int, first_name: str, last_name: str, username: str) -> dict:
    """Telegram `from` obyekti ko'rinishi."""
    return {
        "id": user_id,
        "is_bot": False,
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
    }


BOT_JSON = {"id": BOT_ID, "is_bot": True, "first_name": "TestBot", "username": "test_bot"}


class FakeSession(BaseSession):
    """Tarmoqsiz session: Telegram API chaqiruvlarini yozib boradi."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[object] = []

    async def make_request(self, bot, method, timeout=None):  # type: ignore[override]
        self.calls.append(method)
        return self._result(bot, method)

    def _result(self, bot, method):
        if isinstance(method, (SendMessage,)):
            return Message.model_validate(
                {
                    "message_id": len(self.calls),
                    "date": NOW,
                    "chat": {"id": method.chat_id, "type": "private"},
                    "from": BOT_JSON,
                    "text": getattr(method, "text", "") or "",
                },
                context={"bot": bot},
            )
        if isinstance(method, GetMe):
            return TgUser.model_validate(BOT_JSON)
        return True  # DeleteMessage va boshqalar

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def close(self) -> None:
        return None

    # -- yordamchilar -------------------------------------------------------
    def last(self) -> object:
        assert self.calls, "Telegram API chaqirilmadi"
        return self.calls[-1]

    def sent_texts(self) -> list[str]:
        return [call.text for call in self.calls if isinstance(call, SendMessage)]


class ErrorCollector(logging.Handler):
    """Handler ichidagi ERROR loglarini yig'adi."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def message_update(
    bot: Bot, update_id: int, text: str, *, sender: dict
) -> Update:
    """Foydalanuvchi xabarini imitatsiya qiladi."""
    message: dict = {
        "message_id": update_id,
        "date": NOW,
        "chat": {"id": sender["id"], "type": "private"},
        "from": sender,
        "text": text,
    }
    if text.startswith("/"):
        message["entities"] = [
            {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
        ]
    return Update.model_validate(
        {"update_id": update_id, "message": message}, context={"bot": bot}
    )


def check_name_service() -> None:
    """`services.user_names` qoidalarini tekshiradi."""
    assert user_names.validate_name("  G‘ofur  ", field="Ism") == "G'ofur"
    assert user_names.normalize_name("Ali   -   Vali") == "Ali-Vali"
    assert user_names.validate_name("Абдулла", field="Ism") == "Абдулла"
    assert user_names.validate_name("O‘ktam-ali", field="Ism") == "O'ktam-ali"

    for bad in ("A", "Ali1", "!!!", "Ali@", "   ", "Ali_Vali"):
        try:
            user_names.validate_name(bad, field="Ism")
        except user_names.InvalidNameError:
            continue
        raise AssertionError(f"InvalidNameError kutilgan edi: {bad!r}")
    print("[OK] Ism validatsiyasi: harflar/apostrof/chiziqcha, raqam va belgilar rad etildi")


async def check_registration(bot, session, dp, repos: Repositories) -> None:
    """Asosiy ro'yxatdan o'tish oqimi."""
    sender = user_json(USER_ID, "Telegram", "Name", "telegram_user")

    # 1) /start → ism so'raladi, menyu ko'rsatilmaydi.
    await dp.feed_update(bot, message_update(bot, 1, "/start", sender=sender))
    first = session.last()
    assert isinstance(first, SendMessage), type(first)
    assert "Ismingizni" in first.text, first.text
    assert first.reply_markup is None, "profil yo'q bo'lsa menyu ko'rsatilmasligi kerak"
    assert not await repos.profiles.exists(USER_ID)

    # 2) Noto'g'ri ism → xato, holat o'zgarmaydi.
    await dp.feed_update(bot, message_update(bot, 2, "Ali1", sender=sender))
    assert "noto'g'ri kiritildi" in session.last().text
    assert not await repos.profiles.exists(USER_ID)

    # 3) To'g'ri ism → familiya so'raladi.
    await dp.feed_update(bot, message_update(bot, 3, "Ali", sender=sender))
    assert "Familiyangizni" in session.last().text

    # 4) Noto'g'ri familiya → xato.
    await dp.feed_update(bot, message_update(bot, 4, "!!!", sender=sender))
    assert "noto'g'ri kiritildi" in session.last().text

    # 5) To'g'ri familiya → profil saqlanadi va menyu ochiladi.
    await dp.feed_update(bot, message_update(bot, 5, "Karimov", sender=sender))
    assert any("Ro'yxatdan o'tdingiz" in text for text in session.sent_texts())
    menu = session.last()
    assert isinstance(menu, SendMessage), type(menu)
    assert menu.reply_markup is not None, "menyu tugmalari yo'q"
    labels = [row[0].text for row in menu.reply_markup.inline_keyboard]
    assert labels[0] == "📝 Javoblarni belgilash", labels
    assert menu.reply_markup.inline_keyboard[0][0].web_app is not None

    profile = await repos.profiles.get(USER_ID)
    user = await repos.users.get(USER_ID)
    assert profile is not None and profile.full_name == "Ali Karimov"
    assert user is not None and user.full_name == "Ali Karimov"
    print("[OK] /start → ism → familiya → profil saqlandi va test bo'limi ochildi")

    # 6) Qayta /start → ism so'ralmaydi.
    await dp.feed_update(bot, message_update(bot, 6, "/start", sender=sender))
    again = session.last()
    assert isinstance(again, SendMessage) and "Assalomu alaykum" in again.text, again
    assert "Ismingizni" not in again.text
    print("[OK] Qayta /start: ism/familiya qayta so'ralmadi")

    # 7) Middleware Telegram ismi o'zgarganda profil ismini ustidan yozmaydi.
    renamed = user_json(USER_ID, "Changed", "Telegram", "new_username")
    await dp.feed_update(bot, message_update(bot, 7, "/help", sender=renamed))
    saved = await repos.users.get(USER_ID)
    assert saved is not None and saved.full_name == "Ali Karimov", saved
    assert saved.username == "new_username", saved
    print("[OK] Middleware: Telegram ismi o'zgardi, profil ismi saqlanib qoldi")


async def check_app_gate(bot, session, dp, repos: Repositories) -> None:
    """Ro'yxatdan o'tmagan o'quvchi /app orqali testga kira olmaydi."""
    sender = user_json(USER2_ID, "Vali", "Telegram", "vali")

    await dp.feed_update(bot, message_update(bot, 10, "/app", sender=sender))
    last = session.last()
    assert isinstance(last, SendMessage) and "Ismingizni" in last.text, last
    assert last.reply_markup is None, "ro'yxatdan o'tmasdan Web App tugmasi berildi"
    assert not await repos.profiles.exists(USER2_ID)

    await dp.feed_update(bot, message_update(bot, 11, "Vali", sender=sender))
    await dp.feed_update(bot, message_update(bot, 12, "Valiyev", sender=sender))
    app_menu = session.last()
    assert isinstance(app_menu, SendMessage) and "Assalomu alaykum" in app_menu.text
    assert app_menu.reply_markup is not None
    assert app_menu.reply_markup.inline_keyboard[0][0].web_app is not None
    print("[OK] /app: ro'yxatdan o'tmaguncha bloklandi, keyin Web App ochildi")


async def main() -> None:
    """Dispatcher'ni `main.py` kabi tuzadi va oqimlarni tekshiradi."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_registration_"))
    db = Database(tmp_dir / "registration_test.db")
    await db.connect()
    repos = Repositories(db)

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    session = FakeSession()
    bot.session = session

    dp = Dispatcher(storage=MemoryStorage())
    dp.workflow_data.update(repos=repos)
    dp.update.middleware(UserSyncMiddleware())
    dp.include_router(setup_routers())

    collector = ErrorCollector()
    logging.getLogger().addHandler(collector)
    logging.getLogger().setLevel(logging.WARNING)

    print("=" * 72)
    print("Ro'yxatdan o'tish oqimi testi (Telegram'siz)")
    print("=" * 72)
    try:
        check_name_service()
        await check_registration(bot, session, dp, repos)
        await check_app_gate(bot, session, dp, repos)
    finally:
        await bot.session.close()
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    assert not collector.records, (
        "Handler ichida istisno yuz berdi: " + collector.records[0].getMessage()
    )
    print("=" * 72)
    print(f"Jami {len(session.calls)} ta soxta Telegram API chaqiruvi — xatosiz ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
