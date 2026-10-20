"""`/admins` paneli testi — admin qo'shish/o'chirish (Telegram'siz).

Tekshiriladi:
    1. Migratsiya: `bot_admins` jadvali yaratiladi (008).
    2. Repository: qo'shish, dublikat, ro'yxat, o'chirish.
    3. `config`: xotiraga qo'shish/o'chirish va "egasi" adminni himoya qilish.
    4. To'liq bot oqimi (soxta session bilan):
       `/admins` → «➕ Admin qo'shish» → **forward** → tasdiqlash → baza+xotira;
       so'ng «🗑» → tasdiqlash → o'chirish; egasi adminni o'chirib bo'lmaydi;
       admin bo'lmagan foydalanuvchi panelni ko'rmaydi.

Ishga tushirish:
    python tests/test_admin_manage.py
"""

from __future__ import annotations

import asyncio
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
from aiogram.methods import (  # noqa: E402
    AnswerCallbackQuery,
    EditMessageText,
    GetMe,
    SendMessage,
    SetMyCommands,
)
from aiogram.types import Message, Update  # noqa: E402
from aiogram.types import User as TgUser  # noqa: E402

import config  # noqa: E402
from database.db import Database  # noqa: E402
from database.models import BotAdmin  # noqa: E402
from database.repository import Repositories  # noqa: E402
from handlers import setup_routers  # noqa: E402
from keyboards.inline import AdminManageCallback  # noqa: E402
from middlewares import UserSyncMiddleware  # noqa: E402
from services.test_session import TestSessionStore  # noqa: E402

TOKEN = "123456789:TEST_TOKEN_FOR_ADMIN_MANAGE"
BOT_ID = 123456789
USER_ID = 555_000_333          # egasi (`.env` admini)
NEW_ADMIN_ID = 777_000_111     # qo'shiladigan yangi admin
NOW = int(time.time())

BOT_JSON = {"id": BOT_ID, "is_bot": True, "first_name": "TestBot", "username": "test_bot"}
USER_JSON = {
    "id": USER_ID,
    "is_bot": False,
    "first_name": "Aziz",
    "last_name": "Karimov",
    "username": "aziz",
}
NEW_JSON = {
    "id": NEW_ADMIN_ID,
    "is_bot": False,
    "first_name": "Yangi",
    "last_name": "Admin",
    "username": "yangi_admin",
}

# Test sharoiti: joriy foydalanuvchi — "egasi" admin.
config.ADMIN_ID = USER_ID
config.OWNER_ADMIN_IDS = frozenset({USER_ID})
config.set_db_admins(frozenset())


class FakeSession(BaseSession):
    """Tarmoqsiz session: chaqirilgan API metodlarini yozib boradi."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[object] = []

    async def make_request(self, bot, method, timeout=None):  # type: ignore[override]
        self.calls.append(method)
        if isinstance(method, (SendMessage,)):
            return Message.model_validate(
                {
                    "message_id": len(self.calls),
                    "date": NOW,
                    "chat": {"id": method.chat_id, "type": "private"},
                    "from": BOT_JSON,
                    "text": getattr(method, "text", None) or "",
                },
                context={"bot": bot},
            )
        if isinstance(method, GetMe):
            return TgUser.model_validate(BOT_JSON)
        return True  # EditMessageText, AnswerCallbackQuery, SetMyCommands, ...

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def close(self) -> None:
        return None

    # -- yordamchilar -------------------------------------------------------
    def sent_texts(self) -> list[str]:
        return [call.text for call in self.calls if isinstance(call, SendMessage)]

    def last_sent(self) -> SendMessage:
        messages = [call for call in self.calls if isinstance(call, SendMessage)]
        assert messages, "xabar yuborilmadi"
        return messages[-1]

    def last_edit(self) -> EditMessageText:
        edits = [call for call in self.calls if isinstance(call, EditMessageText)]
        assert edits, "xabar tahrirlanmadi"
        return edits[-1]

    def last_answer(self) -> AnswerCallbackQuery:
        answers = [call for call in self.calls if isinstance(call, AnswerCallbackQuery)]
        assert answers, "callback'ga javob berilmadi"
        return answers[-1]


def message_update(
    bot: Bot,
    update_id: int,
    text: str,
    *,
    user_json: dict | None = None,
    forward_origin: dict | None = None,
) -> Update:
    """Foydalanuvchi yuborgan xabarni imitatsiya qiladi (forward ham bo'ladi)."""
    message: dict = {
        "message_id": update_id,
        "date": NOW,
        "chat": {"id": USER_ID, "type": "private"},
        "from": user_json or USER_JSON,
        "text": text,
    }
    if text.startswith("/"):
        message["entities"] = [
            {"type": "bot_command", "offset": 0, "length": len(text)}
        ]
    if forward_origin is not None:
        message["forward_origin"] = forward_origin
    return Update.model_validate(
        {"update_id": update_id, "message": message}, context={"bot": bot}
    )


def callback_update(bot: Bot, update_id: int, data: str) -> Update:
    """Inline tugma bosilishini imitatsiya qiladi."""
    return Update.model_validate(
        {
            "update_id": update_id,
            "callback_query": {
                "id": f"cb-{update_id}",
                "from": USER_JSON,
                "chat_instance": "1",
                "data": data,
                "message": {
                    "message_id": update_id,
                    "date": NOW,
                    "chat": {"id": USER_ID, "type": "private"},
                    "from": BOT_JSON,
                    "text": "oldingi xabar",
                },
            },
        },
        context={"bot": bot},
    )


async def check_repository() -> None:
    """Migratsiya 008 va `bot_admins` repository'si."""
    tmpdir = tempfile.mkdtemp(prefix="rash_admins_")
    db = Database(Path(tmpdir) / "admins.db")
    try:
        await db.connect()
        repos = Repositories(db)

        tables = await db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_admins'"
        )
        assert tables, "008 migratsiyasi qo'llanmadi (bot_admins yo'q)"
        assert await repos.admins.count() == 0

        assert (
            await repos.admins.add(
                700_001, full_name="Ali Valiyev", username="ali", added_by=USER_ID
            )
            is True
        )
        assert (
            await repos.admins.add(700_001, full_name="Ali") is False
        ), "dublikat qo'shildi"
        assert await repos.admins.list_ids() == {700_001}

        admin = await repos.admins.get(700_001)
        assert isinstance(admin, BotAdmin), admin
        assert admin.mention == "Ali Valiyev (@ali)", admin.mention

        assert await repos.admins.remove(700_001) is True
        assert await repos.admins.remove(700_001) is False
        assert await repos.admins.count() == 0
        print("[OK] Migratsiya 008 + repository: qo'shish / dublikat / o'chirish")
    finally:
        await db.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


def check_config() -> None:
    """`config` xotirasi: qo'shish/o'chirish va "egasi" himoyasi."""
    config.set_db_admins(frozenset())
    assert config.is_owner(USER_ID) is True
    assert config.is_admin(USER_ID) is True

    assert config.add_admin(800_001) is True
    assert config.is_admin(800_001) is True
    assert config.add_admin(800_001) is False, "takror qo'shildi"
    assert config.add_admin(USER_ID) is False, "egasi qayta qo'shildi"
    assert config.remove_admin(USER_ID) is False, "egasi o'chirildi (lock-out)!"

    assert config.remove_admin(800_001) is True
    assert config.is_admin(800_001) is False

    config.set_db_admins({900_001})
    assert config.is_admin(900_001) is True
    config.set_db_admins(frozenset())
    assert config.is_admin(900_001) is False
    print("[OK] config: xotiraga qo'shish/o'chirish, egasi himoyasi")


async def check_bot_flow() -> None:
    """To'liq oqim: `/admins` → forward → tasdiq → o'chirish."""
    tmpdir = tempfile.mkdtemp(prefix="rash_admins_flow_")
    db = Database(Path(tmpdir) / "flow.db")
    await db.connect()
    repos = Repositories(db)
    config.set_db_admins(frozenset())

    bot = Bot(
        TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=FakeSession(),
    )
    session = bot.session
    assert isinstance(session, FakeSession)
    dp = Dispatcher(storage=MemoryStorage())
    dp.workflow_data.update(repos=repos, sessions=TestSessionStore())
    dp.update.middleware(UserSyncMiddleware())
    dp.include_router(setup_routers())

    try:
        # 1) Panel
        await dp.feed_update(bot, message_update(bot, 1, "/admins"))
        panel = session.last_sent()
        assert "Adminlar" in panel.text, panel.text
        labels = [
            button.text for row in panel.reply_markup.inline_keyboard for button in row
        ]
        assert labels[0] == "➕ Admin qo'shish", labels
        print("[OK] /admins: panel va «➕ Admin qo'shish» tugmasi ko'rsatildi")

        # 2) «➕ Admin qo'shish» → forward so'rovi
        await dp.feed_update(
            bot, callback_update(bot, 2, AdminManageCallback(action="add").pack())
        )
        assert "Yangi admin qo'shish" in session.last_sent().text
        print("[OK] «➕ Admin qo'shish»: forward so'rovi yuborildi")

        # 3) Forward qilingan xabar → tasdiqlash
        await dp.feed_update(
            bot,
            message_update(
                bot,
                3,
                "Salom, men o'qituvchiman",
                forward_origin={"type": "user", "date": NOW, "sender_user": NEW_JSON},
            ),
        )
        confirm = session.last_sent()
        assert "Shu odamni admin qilaymi" in confirm.text, confirm.text
        assert str(NEW_ADMIN_ID) in confirm.text
        assert confirm.reply_markup is not None, "tasdiqlash tugmalari yo'q"
        print("[OK] Forward → nomzod aniqlandi va tasdiqlash so'raldi")

        # 4) Tasdiqlash → baza + xotira + komandalar
        await dp.feed_update(
            bot,
            callback_update(
                bot,
                4,
                AdminManageCallback(
                    action="confirm_add", user_id=NEW_ADMIN_ID
                ).pack(),
            ),
        )
        assert await repos.admins.exists(NEW_ADMIN_ID), "bazaga yozilmadi"
        assert config.is_admin(NEW_ADMIN_ID), "xotiraga qo'shilmadi"
        assert "admin qilib qo'shildi" in session.last_edit().text
        assert any(isinstance(call, SetMyCommands) for call in session.calls), (
            "yangi admin uchun komandalar o'rnatilmadi"
        )
        assert any(
            isinstance(call, SendMessage) and call.chat_id == NEW_ADMIN_ID
            for call in session.calls
        ), "yangi adminga xabar yuborilmadi"
        print("[OK] Tasdiq: baza + xotira + komandalar + yangi adminga xabar")

        # 5) Yangi admin panelda ko'rinadi
        assert any(
            "Yangi Admin (@yangi_admin)" in text for text in session.sent_texts()
        )
        print("[OK] Panel yangilandi: yangi admin ro'yxatda ko'rindi")

        # 6) «🗑» → tasdiq → o'chirish
        await dp.feed_update(
            bot,
            callback_update(
                bot,
                6,
                AdminManageCallback(action="delete", user_id=NEW_ADMIN_ID).pack(),
            ),
        )
        assert "Adminlikdan o'chiraymi" in session.last_edit().text
        await dp.feed_update(
            bot,
            callback_update(
                bot,
                7,
                AdminManageCallback(
                    action="confirm_delete", user_id=NEW_ADMIN_ID
                ).pack(),
            ),
        )
        assert not await repos.admins.exists(NEW_ADMIN_ID), "bazadan o'chirilmadi"
        assert not config.is_admin(NEW_ADMIN_ID), "xotiradan o'chirilmadi"
        assert "adminlikdan o'chirildi" in session.last_edit().text
        print("[OK] «🗑»: tasdiqdan keyin admin o'chirildi (baza + xotira)")

        # 7) Egasi admin himoyasi
        await dp.feed_update(
            bot,
            callback_update(
                bot,
                8,
                AdminManageCallback(action="delete", user_id=USER_ID).pack(),
            ),
        )
        assert "asosiy admin" in (session.last_answer().text or "")
        print("[OK] Egasi adminni o'chirib bo'lmaydi (lock-out himoyasi)")

        # 8) Admin bo'lmagan foydalanuvchi panelni ko'rmaydi
        config.ADMIN_IDS = frozenset()
        sent_before = len(session.sent_texts())
        await dp.feed_update(bot, message_update(bot, 9, "/admins"))
        assert len(session.sent_texts()) == sent_before, "ruxsatsiz panelni ko'rdi"
        print("[OK] Ruxsat nazorati: admin bo'lmagan /admins ga javob olmadi")
    finally:
        config.ADMIN_IDS = config.OWNER_ADMIN_IDS
        await db.close()
        await bot.session.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    print("=" * 72)
    print("Admin boshqaruvi (/admins) — o'z-o'zini tekshirish testlari")
    print("=" * 72)
    try:
        asyncio.run(check_repository())
        check_config()
        asyncio.run(check_bot_flow())
    finally:
        config.set_db_admins(frozenset())
        config.ADMIN_IDS = config.OWNER_ADMIN_IDS
    print("=" * 72)
    print("Barcha 3 ta test muvaffaqiyatli o'tdi ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
