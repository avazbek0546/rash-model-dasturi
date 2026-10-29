"""Yakunlashdan keyingi tezkor tekshiruv (`services.feedback`) testlari.

Tekshiriladi:
    1. **Legacy kalit** (`exams.answer_key`): ✅/❌ kalit bo'yicha hisoblanadi,
       javobsiz savol ❌ bo'ladi (Rasch bo'yicha u 0 ball);
    2. **Item-level kalit** (`form_versions.answer_key`) legacy kalitdan farq
       qilsa ham, baholash bilan **aynan bir xil** manba/kalit ishlatiladi —
       aks holda hozir ✅ ko'rsatilib, yakunda ❌ chiqishi mumkin edi;
    3. Tekshiruvdagi to'g'ri javoblar soni yakuniy `grade_exam` xom balliga mos;
    4. Kalit buzuq bo'lsa — javob baribir qabul qilinadi, bot oddiy (belgisiz)
       xabar yuboradi (feedback hech qachon submit'ni buzmaydi);
    5. Oshkor qilinmaslik: `theta`/`scaled_score` NULL qoladi, xabarda kalit,
       to'g'ri javob varianti va θ yo'q.

Ishga tushirish:
    python tests/test_submission_feedback.py
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
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from database.db import Database  # noqa: E402
from database.models import User  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import (  # noqa: E402
    exam_service,
    feedback,
    form_builder,
    grading,
    webapp_auth,
)
from web.server import create_app  # noqa: E402

TOKEN = "123456789:AASubmissionFeedback"
ADMIN_ID = 707_000_222
STUDENT = {"id": 707_000_111, "first_name": "Ali", "last_name": "Valiyev"}

config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
config.ADMIN_ID = ADMIN_ID
config.ADMIN_IDS = frozenset({ADMIN_ID})
# Item-level manba (`responses`) ustun bo'lishi uchun — baholash bilan bir xil.
config.ITEM_LEVEL_GRADING_ENABLED = True


class FakeBot:
    """`bot.send_message` ni ushlab qoluvchi soxta bot (tarmoqsiz)."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(
        self, chat_id: int, text: str, reply_markup: object = None, **kwargs: object
    ) -> None:
        self.messages.append(
            {"chat_id": int(chat_id), "text": text, "reply_markup": reply_markup}
        )


def build_init_data(user: dict) -> str:
    """Imzolangan `initData` satri (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-feedback",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


HEADERS = {"X-Init-Data": build_init_data(STUDENT)}


def _grid(message: str) -> str:
    """Xabardagi `<code>` panjarasini ajratib oladi."""
    return message.split("<code>", 1)[1].split("</code>", 1)[0]


def check_text_no_leak(message: str, key_letters: str) -> None:
    """Xabarda kalit/javob/θ oshkor emasligini tekshiradi."""
    assert "<code>" in message and "</code>" in message, message
    grid = _grid(message)
    for letter in key_letters:
        assert letter not in grid, (letter, grid)
    assert "ball" not in message and "θ" not in message, message
    assert "javob:" not in message, message


async def make_exam(
    repos: Repositories, *, code: str, key: str, total: int = 5
) -> int:
    """Faol imtihon yaratadi (natija vaqti kelajakda)."""
    now = exam_service.utc_now()
    return await repos.exams.create(
        title=f"Tekshiruv — {code}",
        test_code=code,
        start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
        result_time=exam_service.to_db_time(now + timedelta(hours=1)),
        total_questions=total,
        answer_key=key,
        difficulty_logits=exam_service.difficulties_to_json([0.0] * total),
        created_by=ADMIN_ID,
    )


async def check_legacy_feedback(repos: Repositories) -> None:
    """1-qadam: legacy kalit — ✅/❌, javobsiz ❌, yakuniy ball bilan mos."""
    bot = FakeBot()
    code = "FBLEG1"
    key = "1A2B3C4D5A"
    exam_id = await make_exam(repos, code=code, key=key)
    exam = await repos.exams.get(exam_id)
    assert exam is not None

    app = create_app(repos, bot=bot)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/submit",
            headers=HEADERS,
            # 5-savol **belgilanmagan** (kalit 5A) — u ham ❌ bo'lishi kerak.
            json={"test_code": code, "answers": "1A2B3C4D"},
        )
        assert response.status == 200, (response.status, await response.text())
        payload = await response.json()
        assert payload["answered"] == 4, payload

    assert len(bot.messages) == 1, bot.messages
    ack = bot.messages[0]["text"]
    assert "Javoblaringiz qabul qilindi" in ack, ack
    assert "✅ To'g'ri: <b>4</b>" in ack, ack
    assert "❌ Xato: <b>1</b>" in ack, ack
    assert "1 ✅" in ack and "4 ✅" in ack and "5 ❌" in ack, ack
    check_text_no_leak(ack, "ABCD")

    # θ/ball hali hisoblanmagan — natija vaqti kelmagan.
    submission = await repos.answers.get(STUDENT["id"], exam_id)
    assert submission is not None
    assert submission.theta is None and submission.scaled_score is None, submission

    data = await feedback.build_submission_feedback(repos, exam, submission)
    assert data.correct == 4 and data.total == 5 and data.wrong == 1, data
    assert [item.label for item in data.items] == ["1", "2", "3", "4", "5"], data.items
    assert [item.is_correct for item in data.items] == [True, True, True, True, False]

    # Yakuniy baholash bilan mosligi (kalit o'zgarmasa).
    await grading.grade_exam(repos, exam, regrade=True)
    graded = await repos.answers.get(STUDENT["id"], exam_id)
    assert graded is not None and graded.raw_score == data.correct, graded
    assert graded.theta is not None, graded
    print(
        f"[OK] Legacy kalit: ✅ {data.correct}/{data.total} — yakuniy xom ball "
        f"{graded.raw_score} bilan mos (javobsiz ❌)"
    )


async def check_item_level_key(repos: Repositories) -> None:
    """2-qadam: item-level kalit legacy kalitdan ustun (baholash bilan bir xil)."""
    bot = FakeBot()
    code = "FBITEM"
    legacy_key = "1A2A3A4A5A"  # ataylab "noto'g'ri" legacy kalit
    form_key = "1B2C3D4A5B"  # haqiqiy kalit — faqat formada
    exam_id = await make_exam(repos, code=code, key=legacy_key)
    exam = await repos.exams.get(exam_id)
    assert exam is not None

    now = exam_service.utc_now()
    built = await form_builder.create_form(
        repos,
        title=f"Tekshiruv — {code}",
        test_code=code,
        total_questions=5,
        answer_key=form_key,
        difficulty_logits=None,
        created_by=ADMIN_ID,
    )
    await repos.sessions.create(
        form_id=built.form_id,
        start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
        result_time=exam_service.to_db_time(now + timedelta(hours=1)),
        title=f"Sessiya — {code}",
        created_by=ADMIN_ID,
    )

    answers = "1B2C3D4A5B"
    app = create_app(repos, bot=bot)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/v2/attempt/start", json={"test_code": code}, headers=HEADERS
        )
        assert response.status == 200, (response.status, await response.text())
        attempt_id = int((await response.json())["attempt_id"])

        for position, letter in enumerate("BCDAB", start=1):
            response = await client.post(
                "/api/v2/autosave",
                json={
                    "attempt_id": attempt_id,
                    "position": position,
                    "value": letter,
                    "answer_kind": "option",
                    "client_seq": position,
                },
                headers=HEADERS,
            )
            assert response.status == 200, (
                position,
                response.status,
                await response.text(),
            )

        response = await client.post(
            "/api/submit",
            headers=HEADERS,
            json={"test_code": code, "answers": answers},
        )
        assert response.status == 200, (response.status, await response.text())

    assert len(bot.messages) == 1, bot.messages
    ack = bot.messages[0]["text"]
    # Legacy kalit bilan bu yerda faqat 1 ta ✅ bo'lardi (4-savol = A).
    assert "✅ To'g'ri: <b>5</b>" in ack, ack
    assert "❌ Xato: <b>0</b>" in ack, ack
    check_text_no_leak(ack, "ABCD")

    submission = await repos.answers.get(STUDENT["id"], exam_id)
    assert submission is not None
    marks = await feedback.build_submission_feedback(repos, exam, submission)
    assert marks.correct == 5, marks

    await grading.grade_exam(repos, exam)
    graded = await repos.answers.get(STUDENT["id"], exam_id)
    assert graded is not None and graded.raw_score == marks.correct, graded
    print(
        "[OK] Item-level kalit: forma kaliti ishlatildi (legacy kalit bilan "
        f"1/5 bo'lardi) — ✅ {marks.correct}/5, yakuniy ball mos"
    )


async def check_broken_key(repos: Repositories) -> None:
    """3-qadam: kalit buzuq bo'lsa — javob baribir qabul qilinadi (belgisiz)."""
    bot = FakeBot()
    code = "FBBROK"
    exam_id = await make_exam(repos, code=code, key="1A2B")  # 5 savolga yetmaydi

    app = create_app(repos, bot=bot)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/submit",
            headers=HEADERS,
            json={"test_code": code, "answers": "1A2B3C4D5A"},
        )
        assert response.status == 200, (response.status, await response.text())

    assert len(bot.messages) == 1, bot.messages
    ack = bot.messages[0]["text"]
    assert "Javoblaringiz qabul qilindi" in ack, ack
    assert "<code>" not in ack and "To'g'ri:" not in ack, ack  # belgilarsiz

    submission = await repos.answers.get(STUDENT["id"], exam_id)
    assert submission is not None, "javob saqlanishi kerak (fail-open)"
    print("[OK] Buzuq kalit: javob qabul qilindi, xabar belgisiz (submit buzilmadi)")


async def main() -> None:
    print("=" * 72)
    print("Yakunlashdan keyingi tezkor tekshiruv — testlar")
    print("=" * 72)
    tmp_dir = tempfile.mkdtemp(prefix="rash-feedback-")
    db = Database(Path(tmp_dir) / "feedback.db")
    await db.connect()
    repos = Repositories(db)
    await repos.users.upsert(
        User(user_id=ADMIN_ID, full_name="Olim Ustoz", username="ustoz")
    )
    await repos.users.upsert(
        User(user_id=STUDENT["id"], full_name="Ali Valiyev", username=None)
    )
    try:
        await check_legacy_feedback(repos)
        await check_item_level_key(repos)
        await check_broken_key(repos)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
