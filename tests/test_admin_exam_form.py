"""`/new_exam` ustasi + FormBuilder integratsiyasi testi (Telegram'siz).

Tekshiriladi (`handlers/admin_exam.py` → `confirm_exam`):

    1. **MVP kalit** (33–35 A–F + 36–45 sonli blok) → legacy `exams` yozuvi
       bilan birga `services.form_builder` orqali item-level forma yaratiladi:
       `forms` + `form_versions` + `form_items` + `items` + `item_versions`,
       hamda `exam_sessions` metadatasi tayyorlanadi; xabaridagi statistika
       (`form_id`, `version_no`, `mcq4`/`mcq6`/`numeric`) to'g'ri.
    2. **Oddiy A–D kalit** → eski oqim o'zgarmagan: faqat `exams` yozuvi,
       hech qanday forma yaratilmaydi.
    3. **Xato (qo'llab-quvvatlanmaydigan) MVP kalit** → `FormBuildError`
       o'qituvchiga o'zbekcha ko'rsatiladi va qisman yozuv qolmaydi
       (legacy imtihon ham o'chiriladi).

Ishga tushirish:
    python tests/test_admin_exam_form.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import tempfile
import time
from collections import Counter
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
    EditMessageText,
    GetMe,
    SendDocument,
    SendMessage,
    SendPhoto,
    SendVideo,
)
from aiogram.types import Message, Update  # noqa: E402
from aiogram.types import User as TgUser  # noqa: E402

import config  # noqa: E402
from database.db import Database  # noqa: E402
from database.repository import Repositories  # noqa: E402
from database.seed import seed_questions  # noqa: E402
from handlers import setup_routers  # noqa: E402
from middlewares import UserSyncMiddleware  # noqa: E402
from services.test_session import TestSessionStore  # noqa: E402

TOKEN = "123456789:TEST_TOKEN_FOR_OFFLINE_CHECKS"
BOT_ID = 123456789
USER_ID = 777_000_444
FULL_NAME = "Test O'qituvchi"
NOW = int(time.time())

USER_JSON = {
    "id": USER_ID,
    "is_bot": False,
    "first_name": "Test",
    "last_name": "O'qituvchi",
    "username": "teacher",
}
BOT_JSON = {"id": BOT_ID, "is_bot": True, "first_name": "TestBot", "username": "test_bot"}

config.ADMIN_ID = USER_ID
config.ADMIN_IDS = frozenset({USER_ID})
config.WEBAPP_URL = "https://exam.example.uz"


class FakeSession(BaseSession):
    """Tarmoqsiz session: chaqirilgan API metodlarini yozib boradi."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[object] = []

    async def make_request(self, bot, method, timeout=None):  # type: ignore[override]
        self.calls.append(method)
        return self._result(bot, method)

    def _result(self, bot, method):
        if isinstance(method, (SendMessage, SendVideo, SendPhoto, SendDocument)):
            return Message.model_validate(
                {
                    "message_id": len(self.calls),
                    "date": NOW,
                    "chat": {"id": method.chat_id, "type": "private"},
                    "from": BOT_JSON,
                    "text": getattr(method, "text", None)
                    or getattr(method, "caption", None)
                    or "",
                },
                context={"bot": bot},
            )
        if isinstance(method, GetMe):
            return TgUser.model_validate(BOT_JSON)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def close(self) -> None:
        return None

    def last_edit(self) -> EditMessageText:
        edits = [call for call in self.calls if isinstance(call, EditMessageText)]
        assert edits, "xabar tahrirlanmadi"
        return edits[-1]


class ErrorCollector(logging.Handler):
    """Handler ichidagi ERROR loglarini yig'adi (yashirin istisnolar uchun)."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def message_update(bot: Bot, update_id: int, text: str) -> Update:
    """Foydalanuvchi yuborgan matnli xabarni imitatsiya qiladi."""
    message: dict = {
        "message_id": update_id,
        "date": NOW,
        "chat": {"id": USER_ID, "type": "private"},
        "from": USER_JSON,
        "text": text,
    }
    if text.startswith("/"):
        message["entities"] = [
            {"type": "bot_command", "offset": 0, "length": len(text)}
        ]
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


def mvp_key(total: int) -> str:
    """`total` savol uchun MVP kalitini quradi (`1A…35F|36:…`)."""
    letters = "".join(f"{pos}{'ABCD'[(pos - 1) % 4]}" for pos in range(1, 36))
    if total > 35:
        letters += "".join(
            f"{pos}{'ABCDEF'[(pos - 36) % 6]}" for pos in range(36, total + 1)
        )
    numeric = ",".join(f"{pos}:{pos}" for pos in range(36, min(total, 45) + 1))
    return f"{letters}|{numeric}"


async def run_wizard(
    bot: Bot,
    session: FakeSession,
    dp: Dispatcher,
    update_id: int,
    *,
    title: str,
    code: str,
    total: int,
    key: str,
    start: str,
    end: str,
    result: str,
    difficulty: str = "-",
) -> int:
    """Ustani 8 qadam bo'ylab o'tkazadi va keyingi `update_id` ni qaytaradi.

    `difficulty` — 5-qadamdagi qiyinchilik kiritishi (`"-"` — o'tkazib
    yuborish; foiz yoki logit qiymatlari ham bo'lishi mumkin).
    """
    steps = ["/new_exam", title, code, str(total), key, difficulty, start, end, result]
    for index, text in enumerate(steps):
        await dp.feed_update(bot, message_update(bot, update_id + index, text))
    return update_id + len(steps)


async def check_mvp_key(bot: Bot, session: FakeSession, dp: Dispatcher, db: Database) -> None:
    """MVP kalit → item-level forma + sessiya + legacy imtihon."""
    total = 45
    key = mvp_key(total)
    next_id = await run_wizard(
        bot,
        session,
        dp,
        100,
        title="Matematika — MVP forma",
        code="MVPFORM45",
        total=total,
        key=key,
        start="15.01.2027 09:00",
        end="15.01.2027 10:30",
        result="15.01.2027 12:00",
    )
    await dp.feed_update(bot, callback_update(bot, next_id, "exam:confirm:0"))
    created = session.last_edit()

    assert "Imtihon yaratildi" in created.text and "MVPFORM45" in created.text
    assert "Item-level forma yaratildi" in created.text, created.text
    assert "mcq4: <b>32</b>" in created.text, created.text
    assert "mcq6: <b>3</b>" in created.text, created.text
    # 36–45 ochiq savollar `a`/`b` ga bo'linadi: 35 variant + 20 qism = 55 item.
    assert "numeric: <b>20</b>" in created.text, created.text
    assert "versiya: <b>1</b>" in created.text, created.text
    assert "Savollar: <b>45</b>" in created.text, created.text

    forms = await db.fetchall("SELECT * FROM forms")
    assert len(forms) == 1, f"forms: {len(forms)}"
    form_id = int(forms[0]["form_id"])
    assert forms[0]["test_code"] == "MVPFORM45"

    versions = await db.fetchall(
        "SELECT * FROM form_versions WHERE form_id = ?", (form_id,)
    )
    assert len(versions) == 1 and int(versions[0]["version_no"]) == 1
    form_version_id = int(versions[0]["form_version_id"])
    assert int(forms[0]["current_version_id"]) == form_version_id

    expected_items = total + 10  # 36–45: 10 pozitsiya → 20 qism (a/b)
    form_items = await db.fetchall(
        "SELECT * FROM form_items WHERE form_version_id = ?", (form_version_id,)
    )
    assert len(form_items) == expected_items, len(form_items)
    assert all(row["item_version_id"] is not None for row in form_items)

    item_versions = await db.fetchall("SELECT * FROM item_versions")
    assert len(item_versions) == expected_items, len(item_versions)
    kinds = Counter(row["item_type"] for row in item_versions)
    assert kinds == {"mcq4": 32, "mcq6": 3, "numeric": 20}, kinds

    items = await db.fetchall("SELECT * FROM items")
    assert len(items) == expected_items, len(items)

    # Operatsion `b` (logit) — `item_parameters` ga yoziladi. O'qituvchi
    # qiyinchilikni o'tkazib yuborgan ("-"), shu sababli manba 'default'.
    parameters = await db.fetchall(
        "SELECT * FROM item_parameters ORDER BY item_version_id"
    )
    assert len(parameters) == expected_items, f"item_parameters: {len(parameters)}"
    assert all(float(row["b_value"]) == 0.0 for row in parameters), parameters[:3]
    assert {str(row["source"]) for row in parameters} == {"default"}, parameters[:3]
    assert all(str(row["status"]) == "provisional" for row in parameters)
    assert all(row["valid_to"] is None for row in parameters)
    print(
        "[OK] item_parameters: %d savol uchun operatsion `b` yozildi "
        "(b=0.0, source=default, status=provisional)" % len(parameters)
    )

    session_rows = await db.fetchall("SELECT * FROM exam_sessions")
    assert len(session_rows) == 1, session_rows
    assert int(session_rows[0]["form_id"]) == form_id
    assert str(session_rows[0]["title"]) == "Matematika — MVP forma"
    assert (
        f"🗓 Sessiya: <code>{int(session_rows[0]['session_id'])}</code>" in created.text
    ), created.text

    exams = await db.fetchall("SELECT * FROM exams WHERE test_code = 'MVPFORM45'")
    assert len(exams) == 1, "legacy exams yozuvi yo'q"
    print(
        "[OK] MVP kalit → form_id=%s, versiya=1, savollar=45 "
        "(55 item: mcq4=32, mcq6=3, numeric=20), sessiya=%s, legacy exam=%s"
        % (form_id, int(session_rows[0]["session_id"]), exams[0]["exam_id"])
    )


async def check_plain_key(bot: Bot, session: FakeSession, dp: Dispatcher, db: Database) -> None:
    """Oddiy A–D kalit → legacy `exams` **va** item-level forma + sessiya (M1 fix)."""
    forms_before = len(await db.fetchall("SELECT * FROM forms"))
    sessions_before = len(await db.fetchall("SELECT * FROM exam_sessions"))

    next_id = await run_wizard(
        bot,
        session,
        dp,
        200,
        title="Matematika — oddiy",
        code="PLAIN4",
        total=4,
        key="1A2B3C4D",
        start="16.01.2027 09:00",
        end="16.01.2027 10:00",
        result="16.01.2027 11:00",
    )
    await dp.feed_update(bot, callback_update(bot, next_id, "exam:confirm:0"))
    created = session.last_edit()

    assert "Imtihon yaratildi" in created.text and "PLAIN4" in created.text
    # M1 fix: legacy A–D kalitida ham item-level forma + sessiya yaratiladi.
    assert "Item-level forma yaratildi" in created.text, created.text

    forms = await db.fetchall("SELECT * FROM forms WHERE test_code = 'PLAIN4'")
    assert len(forms) == 1, "legacy kalit uchun forma yaratilmadi"
    assert len(await db.fetchall("SELECT * FROM forms")) == forms_before + 1
    sessions = await db.fetchall("SELECT * FROM exam_sessions")
    assert len(sessions) == sessions_before + 1, "legacy kalit uchun sessiya yaratilmadi"

    form_items = await db.fetchall(
        "SELECT * FROM form_items WHERE form_version_id = ?",
        (int(forms[0]["current_version_id"]),),
    )
    assert len(form_items) == 4, form_items
    assert all(row["item_version_id"] is not None for row in form_items)

    exams = await db.fetchall("SELECT * FROM exams WHERE test_code = 'PLAIN4'")
    assert len(exams) == 1 and exams[0]["answer_key"] == "1A2B3C4D"
    print(
        "[OK] Oddiy A–D kalit → exams + item-level forma (savol=%d) + sessiya=%d"
        % (len(form_items), len(sessions))
    )


async def check_bad_key(bot: Bot, session: FakeSession, dp: Dispatcher, db: Database) -> None:
    """Qo'llab-quvvatlanmaydigan MVP kalit → FormBuildError (qisman yozuv yo'q)."""
    exams_before = await db.fetchall("SELECT * FROM exams")
    forms_before = await db.fetchall("SELECT * FROM forms")

    next_id = await run_wizard(
        bot,
        session,
        dp,
        300,
        title="Matematika — xato",
        code="BADKEY46",
        total=46,  # MVP joylashuvi faqat 45 savolgacha
        key=mvp_key(46),
        start="17.01.2027 09:00",
        end="17.01.2027 10:00",
        result="17.01.2027 11:00",
    )
    await dp.feed_update(bot, callback_update(bot, next_id, "exam:confirm:0"))
    created = session.last_edit()

    assert "Item-level formani yaratib bo'lmadi" in created.text, created.text
    assert "45 savolgacha" in created.text, created.text

    assert await db.fetchall("SELECT * FROM exams") == exams_before, "imtihon qoldi"
    assert await db.fetchall("SELECT * FROM forms") == forms_before, "forma qoldi"
    print("[OK] Xato MVP kalit → FormBuildError ko'rsatildi, bazaga hech narsa yozilmadi")


async def check_percent_difficulty(
    bot: Bot, session: FakeSession, dp: Dispatcher, db: Database
) -> None:
    """Foiz kiritilganda `b` avtomatik hisoblanadi (`b = ln((1-p)/p)`).

    Tekshiriladi: (a) `exams.difficulty_logits` ga konvertatsiya qilingan
    logitlar tushadi; (b) `item_parameters` ga `source='legacy_expert'`
    (o'qituvchining oldindan bahosi) bilan yoziladi.
    """
    total = 45
    next_id = await run_wizard(
        bot,
        session,
        dp,
        300,
        title="Matematika — foiz bilan",
        code="MVPPCT45",
        total=total,
        key=mvp_key(total),
        start="17.01.2027 09:00",
        end="17.01.2027 10:30",
        result="17.01.2027 12:00",
        difficulty="75",
    )
    await dp.feed_update(bot, callback_update(bot, next_id, "exam:confirm:0"))

    exams = await db.fetchall("SELECT * FROM exams WHERE test_code = 'MVPPCT45'")
    assert len(exams) == 1, exams
    logits = json.loads(exams[0]["difficulty_logits"])
    assert len(logits) == total, len(logits)
    expected = -1.0986  # ln((1-0.75)/0.75)
    assert all(abs(value - expected) < 1e-3 for value in logits), logits[:3]

    parameters = await db.fetchall(
        "SELECT * FROM item_parameters ORDER BY item_version_id"
    )
    converted = [
        row for row in parameters if abs(float(row["b_value"]) - expected) < 1e-3
    ]
    expected_items = total + 10  # 36–45: 10 pozitsiya → 20 qism (a/b)
    assert len(converted) == expected_items, (
        f"legacy_expert parametrlar: {len(converted)}"
    )
    assert {str(row["source"]) for row in converted} == {"legacy_expert"}
    print(
        "[OK] Foiz «75» → b=%.4f (%d item), item_parameters.source=legacy_expert"
        % (expected, len(converted))
    )


async def main() -> None:
    """Dispatcher'ni `main.py` kabi tuzadi va yangilanishlarni tarmoqsiz uzatadi."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_admin_form_"))
    db = Database(tmp_dir / "admin_form_test.db")
    await db.connect()
    repos = Repositories(db)
    await seed_questions(repos.questions)

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    session = FakeSession()
    bot.session = session

    dp = Dispatcher(storage=MemoryStorage())
    dp.workflow_data.update(repos=repos, sessions=TestSessionStore())
    dp.update.middleware(UserSyncMiddleware())
    dp.include_router(setup_routers())

    collector = ErrorCollector()
    logging.getLogger().addHandler(collector)
    logging.getLogger().setLevel(logging.WARNING)

    print("=" * 72)
    print("Admin /new_exam + FormBuilder integratsiyasi testi (Telegram'siz)")
    print("=" * 72)
    try:
        await check_mvp_key(bot, session, dp, db)
        await check_plain_key(bot, session, dp, db)
        await check_bad_key(bot, session, dp, db)
        await check_percent_difficulty(bot, session, dp, db)
    finally:
        await bot.session.close()
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    assert not collector.records, (
        "Handler ichida ERROR logi: " + collector.records[0].getMessage()
    )
    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())