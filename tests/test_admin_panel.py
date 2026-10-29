"""Admin panelining yangi imkoniyatlari (tarmoqsiz).

Tekshiriladi:
    1. `010_bot_settings` migratsiyasi va `bot_settings` repository'si;
    2. yaratilgan test vaqtini o'zgartirish (`POST .../schedule`) —
       `exams` va `exam_sessions` birga yangilanadi, noto'g'ri tartib 400;
    3. qatnashchilar ro'yxati (`GET .../participants`) — soni va ismi;
    4. admin chat: bog'langan chatga yangi qatnashchi xabari yuboriladi;
    5. admin bo'lmagan foydalanuvchi bu endpoint'larni ko'rmaydi (403).

Ishga tushirish:
    python tests/test_admin_panel.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
import texts  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from database.db import Database  # noqa: E402
from database.models import User  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import exam_service, webapp_auth  # noqa: E402
from web.server import create_app  # noqa: E402

TOKEN = "123456789:AAAdminPanelChecks"
ADMIN = {"id": 909_000_001, "first_name": "Olim", "last_name": "Ustoz"}
STUDENT = {"id": 909_000_002, "first_name": "Ali", "last_name": "Valiyev", "username": "ali"}
ADMIN_CHAT_ID = -100_900_000_001

config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
config.ADMIN_ID = ADMIN["id"]
config.OWNER_ADMIN_IDS = frozenset({ADMIN["id"]})
config.set_db_admins(frozenset())
config.ADMIN_IDS = frozenset({ADMIN["id"]})


class FakeBot:
    """`send_message` ni ushlab qoluvchi soxta bot (tarmoqsiz)."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: object = None,
        **kwargs: object,
    ) -> None:
        self.messages.append(
            {
                "chat_id": int(chat_id),
                "text": text,
                "reply_markup": reply_markup,
                **kwargs,
            }
        )


def init_data(user: dict) -> str:
    """Imzolangan `initData` (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-admin-panel",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


ADMIN_HEADERS = {"X-Init-Data": init_data(ADMIN)}
STUDENT_HEADERS = {"X-Init-Data": init_data(STUDENT)}


def local_input(moment) -> str:
    """`datetime` ni admin formasidagi mahalliy matnga aylantiradi."""
    return exam_service.format_local(moment, "%d.%m.%Y %H:%M")


async def check_repository(repos: Repositories) -> None:
    """Migratsiya va `bot_settings` repository'si."""
    tables = await repos.db.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'bot_settings'"
    )
    assert tables, "010 migratsiyasi qo'llanmadi (bot_settings yo'q)"

    assert await repos.settings.get("admin_chat_id") is None
    await repos.settings.set("admin_chat_id", str(ADMIN_CHAT_ID))
    assert await repos.settings.get("admin_chat_id") == str(ADMIN_CHAT_ID)
    await repos.settings.set("admin_chat_id", "123")
    assert await repos.settings.get("admin_chat_id") == "123"
    assert await repos.settings.delete("admin_chat_id") is True
    assert await repos.settings.get("admin_chat_id") is None
    print("[OK] bot_settings: migratsiya + set/get/delete")


async def check_api(repos: Repositories, bot: FakeBot) -> None:
    """Vaqtni tahrirlash, qatnashchilar va admin chat xabari."""
    app = create_app(repos, bot=bot)
    async with TestClient(TestServer(app)) as client:
        now = exam_service.utc_now()
        body = {
            "title": "Admin panel testi",
            "test_code": "PANEL01",
            "total_questions": 3,
            "answer_key": "1A2B3C",
            "difficulty": "90, 75, 50",
            "start_time": local_input(now - timedelta(hours=1)),
            "end_time": local_input(now + timedelta(hours=1)),
            "result_time": local_input(now + timedelta(hours=2)),
        }
        created = await client.post(
            "/api/v2/admin/exams", json=body, headers=ADMIN_HEADERS
        )
        assert created.status == 200, (created.status, await created.text())
        exam_id = int((await created.json())["exam_id"])

        exam = await repos.exams.get(exam_id)
        assert exam is not None
        session = await repos.sessions.get_by_test_code("PANEL01")
        assert session is not None
        session_id = int(session["session_id"])
        print("[OK] Test yaratildi (PANEL01 + exam_sessions)")

        # Ro'yxatda vaqt va datetime-local qiymatlari bo'lishi kerak.
        listed = await (
            await client.get("/api/v2/admin/exams", headers=ADMIN_HEADERS)
        ).json()
        row = [item for item in listed["exams"] if item["test_code"] == "PANEL01"][0]
        assert row["start_local"] and row["end_local"] and row["result_local"], row
        assert row["start_input"] and "T" in row["start_input"], row
        print("[OK] Ro'yxatda vaqtlar va tahrirlash qiymatlari bor")

        # 2) Vaqtni o'zgartirish: ikkala jadval ham yangilanadi. Oldin
        # "baholangan" deb belgilaymiz — qayta ochilganda `graded_at` tozalanishi
        # kerak (yangi javoblar ham baholanishi uchun).
        await repos.exams.mark_graded(exam_id, exam_service.now_db())
        await repos.sessions.set_status(
            session_id, "graded", graded_at=exam_service.now_db()
        )
        new_start = now - timedelta(hours=2)
        new_end = now + timedelta(hours=3)
        new_result = now + timedelta(hours=4)
        updated = await client.post(
            f"/api/v2/admin/exams/{exam_id}/schedule",
            json={
                "start_time": local_input(new_start),
                "end_time": local_input(new_end),
                "result_time": local_input(new_result),
            },
            headers=ADMIN_HEADERS,
        )
        assert updated.status == 200, (updated.status, await updated.text())
        exam = await repos.exams.get(exam_id)
        session = await repos.sessions.get(session_id)
        assert exam is not None and session is not None
        assert exam.end_time == session["end_time"], (exam.end_time, session["end_time"])
        assert exam.result_time == session["result_time"]
        assert exam.end_time > exam_service.now_db(), exam.end_time
        assert exam.graded_at is None and session["graded_at"] is None, (
            exam.graded_at,
            session["graded_at"],
        )
        print(
            "[OK] Vaqt o'zgartirildi: exams + exam_sessions birga yangilandi, "
            "graded_at tozalandi"
        )

        # Noto'g'ri tartib (tugash < boshlanish) → 400.
        bad = await client.post(
            f"/api/v2/admin/exams/{exam_id}/schedule",
            json={
                "start_time": local_input(now + timedelta(hours=3)),
                "end_time": local_input(now + timedelta(hours=2)),
                "result_time": local_input(now + timedelta(hours=4)),
            },
            headers=ADMIN_HEADERS,
        )
        assert bad.status == 400, (bad.status, await bad.text())
        print("[OK] Noto'g'ri vaqt tartibi 400 bilan rad etildi")

        # Oddiy o'quvchi vaqtni o'zgartira olmaydi.
        denied = await client.post(
            f"/api/v2/admin/exams/{exam_id}/schedule",
            json={
                "start_time": local_input(new_start),
                "end_time": local_input(new_end),
                "result_time": local_input(new_result),
            },
            headers=STUDENT_HEADERS,
        )
        assert denied.status == 403, denied.status

        # 3) Admin chatni bog'laymiz va o'quvchi javob yuboradi.
        await repos.settings.set("admin_chat_id", str(ADMIN_CHAT_ID))
        submitted = await client.post(
            "/api/submit",
            json={"test_code": "PANEL01", "answers": "1A2B3C"},
            headers=STUDENT_HEADERS,
        )
        assert submitted.status == 200, (submitted.status, await submitted.text())

        admin_messages = [
            message for message in bot.messages if message["chat_id"] == ADMIN_CHAT_ID
        ]
        assert len(admin_messages) == 1, bot.messages
        assert "Yangi qatnashchi" in admin_messages[0]["text"], admin_messages[0]
        assert "Ali Valiyev" in admin_messages[0]["text"], admin_messages[0]
        assert "<b>1</b> ta qatnashchi" in admin_messages[0]["text"], admin_messages[0]
        print("[OK] Admin chatga yangi qatnashchi xabari yuborildi")

        # 4) Qatnashchilar ro'yxati (admin).
        participants = await (
            await client.get(
                f"/api/v2/admin/exams/{exam_id}/participants",
                headers=ADMIN_HEADERS,
            )
        ).json()
        assert participants["count"] == 1, participants
        person = participants["participants"][0]
        assert person["user_id"] == STUDENT["id"], person
        assert person["full_name"] == "Ali Valiyev", person
        assert person["username"] == "ali", person
        assert person["graded"] is False, person
        print("[OK] Qatnashchilar: soni 1, ism/@username to'g'ri")

        denied_participants = await client.get(
            f"/api/v2/admin/exams/{exam_id}/participants",
            headers=STUDENT_HEADERS,
        )
        assert denied_participants.status == 403, denied_participants.status
        print("[OK] Qatnashchilar endpoint'i o'quvchiga 403 qaytardi")

        # 5) Xabar matni bo'laklarga bo'linadi va sanoqni ko'rsatadi.
        chunks = texts.participants_chunks(
            title=exam.title,
            test_code=exam.test_code,
            participants=await repos.answers.list_participants(exam_id),
            total_questions=exam.total_questions,
        )
        assert chunks and "Jami: <b>1</b>" in chunks[0], chunks
        print("[OK] `texts.participants_chunks` sanoqni ko'rsatdi")


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="admin_panel_"))
    db = Database(tmp_dir / "admin_panel.db")
    await db.connect()
    repos = Repositories(db)
    await repos.users.upsert(
        User(user_id=ADMIN["id"], full_name="Olim Ustoz", username="ustoz")
    )
    await repos.users.upsert(
        User(user_id=STUDENT["id"], full_name="Ali Valiyev", username="ali")
    )

    print("=" * 72)
    print("Admin panel testi (vaqtni tahrirlash + qatnashchilar + admin chat)")
    print("=" * 72)
    try:
        await check_repository(repos)
        await check_api(repos, FakeBot())
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha admin panel tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
