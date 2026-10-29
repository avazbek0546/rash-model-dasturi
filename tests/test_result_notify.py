"""Natija bildirishnomalari testi (tarmoqsiz).

Tekshiriladi:
    1. `texts.submission_accepted` — markssiz oddiy qabul xabari; marks bilan
       esa faqat ✅/❌ (to'g'ri javob varianti YO'Q);
    2. `texts.result_ready` — boy natija kartasi (ball, daraja, θ, interval);
    3. `notify.send_result_ready` — xabar + WebApp/«Savollar tahlili» tugmalari;
    4. `POST /api/submit` — qabul xabari + kalitsiz ✅/❌ belgilari;
    5. `notify.notify_due_results` — `result_time` kelgach bir marta yuboradi
       va `notified_at` ni belgilaydi.

Tarmoqqa chiqilmaydi: `aiohttp.test_utils` ilovani xotirada ko'taradi,
Telegram esa soxta bot (`FakeBot`) bilan almashtiriladi.

Ishga tushirish:
    python tests/test_result_notify.py
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
import notify  # noqa: E402
import texts  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from database.db import Database  # noqa: E402
from database.models import Exam, ExamSubmission  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import exam_service, grading, solutions, webapp_auth  # noqa: E402
from web.server import create_app  # noqa: E402

TOKEN = "123456789:AATestTokenForResultNotify"
USER = {"id": 808_222_333, "first_name": "Dilnoza", "last_name": "Karimova", "username": "dilnoza"}
CODE = "EXAM01"
KEY = "1A2B3C4D5A"
TOTAL = 5

# Server `config.BOT_TOKEN` bilan imzoni tekshiradi — testda o'zimiznikini qo'yamiz.
config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
# Web App tugmalari (Natijalar / Batafsil tahlil) paydo bo'lishi uchun.
config.WEBAPP_URL = "https://exam.example.uz"


class FakeBot:
    """`bot.send_message` ni ushlab qoluvchi soxta bot (tarmoqsiz)."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(
        self, chat_id: int, text: str, reply_markup: object = None, **kwargs: object
    ) -> None:
        """Xabarni (klaviaturasi bilan) yozib qo'yadi — Telegram'ga yubormaydi."""
        self.messages.append(
            {"chat_id": int(chat_id), "text": text, "reply_markup": reply_markup}
        )


def build_init_data(user: dict, *, token: str = TOKEN) -> str:
    """Imzolangan `initData` satrini yasaydi (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-result-notify",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, token)
    return urlencode(payload)


HEADERS = {"X-Init-Data": build_init_data(USER)}


def make_exam() -> Exam:
    """Test uchun imtihon obyekti (vaqtlar ahamiyatsiz joylarda)."""
    return Exam(
        exam_id=1,
        title="RASH EXAM — 12-fevral",
        test_code=CODE,
        start_time="2026-02-12T05:00:00+00:00",
        end_time="2026-02-12T07:00:00+00:00",
        result_time="2026-02-12T09:00:00+00:00",
        total_questions=4,
        answer_key="1A2B3C4D",
        difficulty_logits="[]",
    )


def check_text_builder() -> None:
    """Qabul xabari: faqat sarlavha + bir ustunli ✅/❌ ro'yxati."""
    # 1) markssiz (feedback hisoblanmagan) — faqat sarlavha, ortiqcha matn yo'q.
    accepted = texts.submission_accepted()
    assert accepted == "✅ <b>Javoblaringiz qabul qilindi</b>", accepted

    # 2) marks bilan — har bir savol ALOHIDA qatorda, boshqa matn YO'Q.
    marked = texts.submission_accepted(
        marks=[("1", True), ("2", True), ("3", True), ("4", False), ("5", False)]
    )
    head, sep, body = marked.partition("\n\n")
    assert head == "✅ <b>Javoblaringiz qabul qilindi</b>", head
    assert sep == "\n\n", marked
    assert body.splitlines() == ["1 ✅", "2 ✅", "3 ✅", "4 ❌", "5 ❌"], body
    for letter in ("A", "B", "C", "D"):
        assert f" {letter}" not in body, body  # javob varianti oshkor emas
    assert KEY not in marked, marked

    # 3) Juda ko'p savol (kutilmagan holat) — xabar Telegram limitidan oshmaydi.
    huge = texts.submission_accepted(
        marks=[(str(index), index % 2 == 0) for index in range(1, 901)]
    )
    assert len(huge) <= texts.MESSAGE_LIMIT, len(huge)
    assert huge.endswith("…"), huge[-20:]

    report = {
        "scaled_score": 57.0,
        "ability_level": "B",
        "theta": 0.42,
        "raw_score": 3,
        "total_questions": 5,
        "scaled_interval": [49.6, 64.4],
        "advice": "Sertifikat B darajasi. Qiyinroq savollar ustida ishlang.",
    }
    ready = texts.result_ready(
        title="RASH EXAM — 12-fevral",
        full_name="Dilnoza Karimova",
        report=report,
    )
    assert "Natijangiz e'lon qilindi" in ready, ready
    assert "57.0 / 100 ball" in ready, ready
    assert "Daraja: <b>B</b>" in ready, ready
    assert "3 / 5" in ready and "θ" in ready, ready
    assert "49.6 – 64.4" in ready, ready
    assert KEY not in ready and "A2B3" not in ready, ready
    print("[OK] Matnlar: qabul xabari (markssiz) sanoqsiz; marks bilan faqat ✅/❌")


def check_result_locked() -> None:
    """Qulf: natijalar e'lon qilinmaguncha yechim yopiq, keyin ochiq."""
    exam = make_exam()  # result_time = 2026-02-12T09:00:00+00:00
    assert solutions.result_locked(exam, "2026-02-12T08:00:00+00:00") is True
    assert solutions.result_locked(exam, "2026-02-12T09:00:00+00:00") is False
    assert solutions.result_locked(exam, "2026-02-12T10:00:00+00:00") is False
    print("[OK] Qulf: e'lon qilinguncha yechim yopiq, e'lon qilingach ochiq")


async def check_notify_send() -> None:
    """Qabul xabari va natija kartasi soxta botga yuboriladi (kalitsiz)."""
    bot = FakeBot()
    exam = make_exam()
    submission = ExamSubmission(
        user_id=USER["id"],
        exam_id=1,
        submitted_answers="1A2B3X4D",
        submitted_at="x",
        theta=0.5,
        scaled_score=60.0,
        raw_score=3,
        total_questions=4,
    )

    accepted = await notify.send_submission_accepted(
        bot,
        user_id=USER["id"],
        marks=[("1", True), ("2", False)],
    )
    assert accepted is True, accepted
    assert len(bot.messages) == 1, bot.messages
    ack = bot.messages[0]
    assert ack["text"].startswith("✅ <b>Javoblaringiz qabul qilindi</b>"), ack
    assert ack["text"].splitlines()[2:] == ["1 ✅", "2 ❌"], ack["text"]
    assert KEY not in ack["text"], ack
    assert ack["reply_markup"] is not None, ack
    ack_buttons = [b for row in ack["reply_markup"].inline_keyboard for b in row]
    assert any(b.text == "📊 Natijalar" for b in ack_buttons), ack_buttons
    assert any(
        b.web_app is not None and "tab=results" in b.web_app.url for b in ack_buttons
    ), ack_buttons

    bot.messages.clear()
    sent = await notify.send_result_ready(
        bot,
        user_id=USER["id"],
        full_name="Dilnoza Karimova",
        exam=exam,
        submission=submission,
    )
    assert sent is True, sent
    assert len(bot.messages) == 1, bot.messages
    message = bot.messages[0]
    assert message["chat_id"] == USER["id"], message
    assert "Natijangiz e'lon qilindi" in message["text"], message
    assert "ball" in message["text"] and "Daraja:" in message["text"], message
    assert KEY not in message["text"], message
    buttons = [b for row in message["reply_markup"].inline_keyboard for b in row]
    assert any(b.text == "🔍 Savollar tahlili" for b in buttons), buttons
    assert any(
        b.web_app is not None and "tab=results" in b.web_app.url for b in buttons
    ), buttons
    print("[OK] notify: qabul xabari minimal (✅/❌), natija kartasi boy va kalitsiz")


async def check_submit_and_notify(repos: Repositories) -> None:
    """Submit → faqat ack; result_time kelgach → boy natija, bir marta."""
    bot = FakeBot()
    now = exam_service.utc_now()
    exam_id = await repos.exams.create(
        title="RASH EXAM — 12-fevral",
        test_code=CODE,
        start_time=exam_service.to_db_time(now - timedelta(hours=1)),
        end_time=exam_service.to_db_time(now + timedelta(hours=1)),
        result_time=exam_service.to_db_time(now + timedelta(hours=2)),
        total_questions=TOTAL,
        answer_key=KEY,
        difficulty_logits="[]",
        created_by=1,
    )

    app = create_app(repos, bot=bot)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/submit",
            headers=HEADERS,
            json={"test_code": CODE, "answers": "1A2B3X4D5A"},
        )
        assert response.status == 200, (response.status, await response.text())

    # 1) Submitda qisqa qabul xabari + kalitsiz ✅/❌ (har biri alohida qatorda).
    assert len(bot.messages) == 1, bot.messages
    ack = bot.messages[0]
    text = ack["text"]
    head, sep, body = text.partition("\n\n")
    assert head == "✅ <b>Javoblaringiz qabul qilindi</b>", text
    assert sep == "\n\n", text
    assert body.splitlines() == ["1 ✅", "2 ✅", "3 ❌", "4 ✅", "5 ✅"], text
    assert KEY not in text, text
    assert "ball" not in text and "θ" not in text, text
    ack_buttons = [b for row in ack["reply_markup"].inline_keyboard for b in row]
    assert any(
        b.web_app is not None and "tab=results" in b.web_app.url for b in ack_buttons
    ), ack_buttons
    print("[OK] /api/submit → qisqa xabar + kalitsiz ✅/❌ (har biri alohida qatorda)")

    # 2) Natija vaqti kelgach: baholash + fon bildirishnomasi.
    await repos.exams.update_times(
        exam_id,
        end_time=exam_service.to_db_time(now - timedelta(hours=2)),
        result_time=exam_service.to_db_time(now - timedelta(hours=1)),
    )
    exam = await repos.exams.get(exam_id)
    assert exam is not None
    await grading.grade_exam(repos, exam)

    sent = await notify.notify_due_results(repos, bot)
    assert sent == 1, sent
    assert len(bot.messages) == 2, bot.messages
    result = bot.messages[-1]
    assert "Natijangiz e'lon qilindi" in result["text"], result
    assert "ball" in result["text"] and "Daraja:" in result["text"], result
    assert KEY not in result["text"], result
    print("[OK] notify_due_results → boy natija kartasi yuborildi (kalitsiz)")

    # 3) Idempotentlik: ikkinchi chaqiruvda dublikat ketmaydi.
    assert await notify.notify_due_results(repos, bot) == 0
    assert len(bot.messages) == 2, bot.messages
    submission = await repos.answers.get(USER["id"], exam_id)
    assert submission is not None and submission.notified_at, submission
    print("[OK] notified_at belgilandi — takroriy xabar yuborilmadi")


async def main() -> None:
    print("=" * 72)
    print("Natija bildirishnomalari testi (tarmoqsiz)")
    print("=" * 72)
    tmp_dir = tempfile.mkdtemp(prefix="rash-notify-")
    db = Database(Path(tmp_dir) / "notify.db")
    await db.connect()
    try:
        check_text_builder()
        check_result_locked()
        await check_notify_send()
        await check_submit_and_notify(Repositories(db))
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
