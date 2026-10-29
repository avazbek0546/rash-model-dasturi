"""Admin chat (`/admin_chat`) va kirishni qo'riqlash testi (tarmoqsiz).

Tekshiriladi:
    1. Admin guruhda `/admin_chat` → chat ID bazaga yoziladi;
    2. Admin bo'lmagan odam buyruqni yuborsa — bog'lanmaydi;
    3. Admin guruh administratori bo'lmasa — bog'lanmaydi;
    4. Admin chatga qo'shilgan admin bo'lmagan odam chiqarib yuboriladi;
    5. Admin (yoki bot) tegilmaydi;
    6. `chat_join_request` — begona odamning so'rovi rad etiladi.

Ishga tushirish:
    python tests/test_admin_chat.py
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from aiogram.enums import ChatMemberStatus, ChatType  # noqa: E402
from database.db import Database  # noqa: E402
from database.repository import Repositories  # noqa: E402
from handlers import admin_chat as admin_chat_handler  # noqa: E402
from services import admin_chat  # noqa: E402

ADMIN_ID = 911_000_001
OTHER_ID = 911_000_002
BOT_ID = 911_000_999
CHAT_ID = -100_911_000_001

config.ADMIN_ID = ADMIN_ID
config.OWNER_ADMIN_IDS = frozenset({ADMIN_ID})
config.set_db_admins(frozenset())
config.ADMIN_IDS = frozenset({ADMIN_ID})


class FakeBot:
    """Handler'lar chaqiradigan Bot metodlarini yozib boruvchi soxta bot."""

    def __init__(self) -> None:
        self.banned: list[tuple[int, int]] = []
        self.unbanned: list[tuple[int, int]] = []
        self.declined: list[tuple[int, int]] = []
        self.messages: list[dict] = []
        self.sender_status = ChatMemberStatus.ADMINISTRATOR
        self.bot_status = ChatMemberStatus.ADMINISTRATOR

    async def get_me(self):
        return SimpleNamespace(id=BOT_ID, username="test_bot")

    async def get_chat_member(self, chat_id: int, user_id: int):
        status = (
            self.bot_status if int(user_id) == BOT_ID else self.sender_status
        )
        return SimpleNamespace(status=status, can_restrict_members=True)

    async def ban_chat_member(self, chat_id: int, user_id: int):
        self.banned.append((int(chat_id), int(user_id)))
        return True

    async def unban_chat_member(self, chat_id: int, user_id: int):
        self.unbanned.append((int(chat_id), int(user_id)))
        return True

    async def decline_chat_join_request(self, chat_id: int, user_id: int):
        self.declined.append((int(chat_id), int(user_id)))
        return True

    async def send_message(self, chat_id: int, text: str, **kwargs: object):
        self.messages.append({"chat_id": int(chat_id), "text": text})
        return True


def make_message(text: str, *, user_id: int, chat_id: int = CHAT_ID):
    """Handler kutgan minimal `Message` o'rinbosari."""
    answers: list[str] = []

    async def answer(reply: str, **kwargs: object) -> None:
        answers.append(reply)

    return SimpleNamespace(
        from_user=SimpleNamespace(
            id=user_id, full_name="Test Admin", username="test_admin"
        ),
        chat=SimpleNamespace(
            id=chat_id, type=ChatType.SUPERGROUP, title="Adminlar guruhi"
        ),
        text=text,
        answer=answer,
        answers=answers,
    )


async def check_bind(repos: Repositories) -> None:
    """`/admin_chat` faqat admin + guruh administratori uchun ishlaydi."""
    bot = FakeBot()

    # Begona odam: hech narsa bog'lanmaydi.
    stranger = make_message("/admin_chat", user_id=OTHER_ID)
    await admin_chat_handler.cmd_admin_chat(stranger, repos, bot)
    assert await admin_chat.chat_id(repos) is None
    assert stranger.answers and "faqat" in stranger.answers[-1].lower()
    print("[OK] Admin bo'lmagan odam /admin_chat qila olmadi")

    # Admin, lekin guruh administratori emas.
    bot.sender_status = ChatMemberStatus.MEMBER
    member = make_message("/admin_chat", user_id=ADMIN_ID)
    await admin_chat_handler.cmd_admin_chat(member, repos, bot)
    assert await admin_chat.chat_id(repos) is None
    assert member.answers and "administrator" in member.answers[-1].lower()
    print("[OK] Guruh administratori bo'lmagan admin bog'lay olmadi")

    # Admin + guruh administratori — bog'lanadi.
    bot.sender_status = ChatMemberStatus.ADMINISTRATOR
    owner = make_message("/admin_chat", user_id=ADMIN_ID)
    await admin_chat_handler.cmd_admin_chat(owner, repos, bot)
    assert await admin_chat.chat_id(repos) == CHAT_ID
    assert owner.answers and "bog'landi" in owner.answers[-1]
    print("[OK] /admin_chat guruhni bog'ladi (bot_settings.admin_chat_id)")

    # Uzish.
    off = make_message("/admin_chat off", user_id=ADMIN_ID)
    await admin_chat_handler.cmd_admin_chat(off, repos, bot)
    assert await admin_chat.chat_id(repos) is None
    print("[OK] /admin_chat off bog'lanishni uzdi")


async def check_guard(repos: Repositories) -> None:
    """Guruhga qo'shilgan begona odam chiqariladi, admin esa qoladi."""
    await admin_chat.bind(repos, CHAT_ID)
    bot = FakeBot()

    update = SimpleNamespace(
        chat=SimpleNamespace(id=CHAT_ID, type=ChatType.SUPERGROUP),
        new_chat_member=SimpleNamespace(
            user=SimpleNamespace(id=OTHER_ID, is_bot=False, full_name="Begona"),
            status=ChatMemberStatus.MEMBER,
        ),
    )
    await admin_chat_handler.on_chat_member(update, repos, bot)
    assert bot.banned == [(CHAT_ID, OTHER_ID)], bot.banned
    assert bot.unbanned == [(CHAT_ID, OTHER_ID)], bot.unbanned
    print("[OK] Admin chatga qo'shilgan begona odam chiqarildi")

    bot_again = FakeBot()
    admin_update = SimpleNamespace(
        chat=SimpleNamespace(id=CHAT_ID, type=ChatType.SUPERGROUP),
        new_chat_member=SimpleNamespace(
            user=SimpleNamespace(id=ADMIN_ID, is_bot=False, full_name="Admin"),
            status=ChatMemberStatus.MEMBER,
        ),
    )
    await admin_chat_handler.on_chat_member(admin_update, repos, bot_again)
    assert bot_again.banned == []
    print("[OK] Admin chatga qo'shilgan admin tegilmaydi")

    request = SimpleNamespace(
        chat=SimpleNamespace(id=CHAT_ID, type=ChatType.SUPERGROUP),
        from_user=SimpleNamespace(id=OTHER_ID),
    )
    await admin_chat_handler.on_chat_join_request(request, repos, bot_again)
    assert bot_again.declined == [(CHAT_ID, OTHER_ID)], bot_again.declined
    print("[OK] Begona odamning qo'shilish so'rovi rad etildi")


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="admin_chat_"))
    db = Database(tmp_dir / "admin_chat.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("Admin chat testi (/admin_chat + kirishni qo'riqlash)")
    print("=" * 72)
    try:
        await check_bind(repos)
        await check_guard(repos)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha admin chat tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
