"""Phase 3, Step 2 regressiya testi: qismli (36a/36b) mustaqil saqlash/tiklash.

Tekshiriladi:
    1. 36a va 36b mustaqil autosave qilinadi (turli response/form_item).
    2. Autosave javobi `label`/`part` qaytaradi.
    3. `/api/v2/state` har bir qismni alohida tiklaydi (to'qnashuv yo'q).
    4. Expression Preservation (Phase 1) qismlarda ham saqlanadi.
    5. Legacy (qismsiz) imtihon 100% o'zgarmaydi.
    6. `layout` qismli bo'lsa `parts` qaytaradi.
    7. **Sessiyasiz** qismli imtihonda ham v1 (verify-code + submit) a/b ni
       saqlaydi — takrorlanib kelgan xatoning regressiya qo'riqchisi.

Ishga tushirish:
    python tests/test_parts_capture.py
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
from services import exam_service, webapp_auth  # noqa: E402
from web.server import create_app  # noqa: E402

_ORIGINAL_ITEM_FLAG = config.ITEM_LEVEL_GRADING_ENABLED

TOKEN = "123456789:AAPartsCaptureChecks"
ADMIN_ID = 909_000_611
STUDENT = {"id": 909_000_612, "first_name": "Ali", "last_name": "Qismli"}
TOTAL = 36
CODE_PARTS = "PART36"
CODE_LEGACY = "LEGCY36"
CODE_V1 = "PARTV1"  # sessiyasiz qismli imtihon (v1 oqimi) — regressiya qo'riqchisi
STUDENT_V1 = {"id": 909_000_613, "first_name": "Vali", "last_name": "V1"}

config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
config.ADMIN_ID = ADMIN_ID
config.ADMIN_IDS = frozenset({ADMIN_ID})


def key_letters() -> str:
    """1–32 → A–D, 33–35 → A–F (35 ta juftlik)."""
    return "".join(
        f"{position}{('ABCD' if position <= 32 else 'ABCDEF')[(position - 1) % (4 if position <= 32 else 6)]}"
        for position in range(1, 36)
    )


def answer_for(position: int) -> str:
    """Pozitsiya uchun kalitdagi harf (1–32 → A–D, 33–35 → A–F)."""
    options = "ABCD" if position <= 32 else "ABCDEF"
    return options[(position - 1) % len(options)]


def _numeric_spec() -> str:
    return json.dumps({"kind": "numeric", "accepted": [], "tolerance": 1e-6})


def part_questions() -> list[dict]:
    """1–35 (mcq4) + 36a/36b (numeric) — qismli forma."""
    questions: list[dict] = []
    for position in range(1, 36):
        questions.append(
            {
                "position": position,
                "display_label": str(position),
                "part": "",
                "section_no": 1,
                "item_type": "mcq4",
                "correct_option": "A",
                "options_count": 4,
                "answer_spec": json.dumps({"kind": "option"}),
                "points": 1.0,
                "difficulty": 0.0,
            }
        )
    for part in ("a", "b"):
        questions.append(
            {
                "position": 36,
                "display_label": f"36{part}",
                "part": part,
                "section_no": 3,
                "item_type": "numeric",
                "correct_option": None,
                "options_count": 0,
                "answer_spec": _numeric_spec(),
                "points": 1.0,
                "difficulty": 0.0,
            }
        )
    return questions


def legacy_questions() -> list[dict]:
    """1–35 (mcq4) + 36 (numeric, qismsiz) — legacy forma."""
    questions = part_questions()[:35]
    questions.append(
        {
            "position": 36,
            "display_label": "36",
            "part": "",
            "section_no": 3,
            "item_type": "numeric",
            "correct_option": None,
            "options_count": 0,
            "answer_spec": _numeric_spec(),
            "points": 1.0,
            "difficulty": 0.0,
        }
    )
    return questions


def build_init_data(user: dict) -> str:
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-parts",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


HEADERS = {"X-Init-Data": build_init_data(STUDENT)}


async def start_attempt(client: TestClient, code: str) -> dict:
    response = await client.post(
        "/api/v2/attempt/start", json={"test_code": code}, headers=HEADERS
    )
    assert response.status == 200, (code, response.status, await response.text())
    return await response.json()


async def autosave(
    client: TestClient,
    attempt_id: int,
    position: int,
    part: str,
    value,
    seq: int,
    expression=None,
) -> dict:
    body = {
        "attempt_id": attempt_id,
        "position": position,
        "part": part,
        "value": value,
        "answer_kind": "numeric",
        "client_seq": seq,
    }
    if expression is not None:
        body["expression"] = expression
    response = await client.post("/api/v2/autosave", json=body, headers=HEADERS)
    assert response.status == 200, (part, response.status, await response.text())
    return await response.json()


async def check_parts(repos: Repositories, db: Database) -> None:
    """1–4-qadam: 36a/36b mustaqil saqlanadi va tiklanadi."""
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        started = await start_attempt(client, CODE_PARTS)
        attempt_id = int(started["attempt_id"])

        part_ranges = [rng for rng in started["layout"] if rng.get("parts")]
        assert part_ranges and part_ranges[-1]["parts"] == ["a", "b"], started["layout"]
        print("[OK] layout: qismli bo'lim parts=['a','b'] qaytardi")

        first = await autosave(client, attempt_id, 36, "a", "2.2361", 1, expression="\u221a5")
        second = await autosave(client, attempt_id, 36, "b", "0.4286", 2, expression="3/7")
        assert first["label"] == "36a" and first["part"] == "a", first
        assert second["label"] == "36b" and second["part"] == "b", second
        assert first["response_id"] != second["response_id"], (first, second)
        print("[OK] autosave: 36a va 36b mustaqil (turli response_id, label/part qaytdi)")

        rows = await db.fetchall(
            """
            SELECT r.display_label, r.part, r.form_item_id, r.raw_answer,
                   r.normalized_answer, r.numeric_value
            FROM responses r
            WHERE r.attempt_id = ? AND r.is_current = 1 AND r.position = 36
            ORDER BY r.part
            """,
            (attempt_id,),
        )
        assert len(rows) == 2, rows
        by_part = {str(row["part"]): row for row in rows}
        assert set(by_part) == {"a", "b"}, by_part
        assert by_part["a"]["form_item_id"] != by_part["b"]["form_item_id"]
        assert str(by_part["a"]["raw_answer"]) == "\u221a5", by_part["a"]
        assert str(by_part["b"]["raw_answer"]) == "3/7", by_part["b"]
        assert abs(float(by_part["a"]["numeric_value"]) - 2.23606797749979) < 1e-12
        assert abs(float(by_part["b"]["numeric_value"]) - 0.42857142857142855) < 1e-15
        print("[OK] DB: ikki satr (36a, 36b), turli form_item, raw_answer saqlandi")

        response = await client.get(
            f"/api/v2/state?attempt_id={attempt_id}", headers=HEADERS
        )
        assert response.status == 200, response.status
        state = await response.json()
        by_label = {item["label"]: item for item in state["items"]}
        assert by_label["36a"]["value"] == "2.23606797749979", by_label.get("36a")
        assert by_label["36a"]["expression"] == "\u221a5", by_label.get("36a")
        assert by_label["36b"]["value"] == "0.428571428571429", by_label.get("36b")
        assert by_label["36b"]["expression"] == "3/7", by_label.get("36b")
        assert state["responses"]["36a"] == "2.23606797749979"
        assert state["responses"]["36b"] == "0.428571428571429"
        print("[OK] state: 36a=\u221a5, 36b=3/7 — to'qnashuv yo'q (refresh/reconnect)")


async def check_legacy(repos: Repositories, db: Database) -> None:
    """5-qadam: qismsiz (legacy) imtihon avvalgidek ishlaydi."""
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        started = await start_attempt(client, CODE_LEGACY)
        assert not [rng for rng in started["layout"] if rng.get("parts")], started["layout"]
        attempt_id = int(started["attempt_id"])

        result = await autosave(client, attempt_id, 36, "", "2.5", 1)
        assert result["label"] == "36" and result["part"] == "", result

        response = await client.get(
            f"/api/v2/state?attempt_id={attempt_id}", headers=HEADERS
        )
        state = await response.json()
        labels = {item["label"] for item in state["items"]}
        assert "36" in labels, labels
        assert state["responses"].get("36") == "2.5", state["responses"]
        print("[OK] legacy: qismsiz imtihon o'zgarmadi (label='36', parts yo'q)")


async def check_v1_parts_without_session(repos: Repositories) -> None:
    """7-qadam: **sessiyasiz** qismli imtihonda ham a/b saqlanadi (v1 oqimi).

    Regressiya qo'riqchisi: ilgari qismlar (`36a`/`36b`) faqat v2 (sessiya)
    yo'lida berilardi — shu sababli `exam_sessions` yozuvi bo'lmagan imtihonda
    36–45 kataklari **bitta** bo'lib qolardi va `b` javobi yo'qolardi. Endi
    qismlar **kalitdan** olinadi (`form_layout.part_labels`) va v1 ham ularni
    alohida saqlaydi.
    """
    now = exam_service.utc_now()
    answer_key = f"{key_letters()}|36a:2.236,36b:0.429"
    # Diqqat: `exam_sessions` **yaratilmaydi** — aynan shu holat muammoni
    # keltirib chiqargan edi (v2 oqimi ishlamaydi).
    exam_id = await repos.exams.create(
        title="Sessiyasiz qismli imtihon",
        test_code=CODE_V1,
        start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
        result_time=exam_service.to_db_time(now + timedelta(hours=1)),
        total_questions=TOTAL,
        answer_key=answer_key,
        difficulty_logits="[]",
        created_by=ADMIN_ID,
    )

    headers = {"X-Init-Data": build_init_data(STUDENT_V1)}
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        verified = await client.post(
            "/api/verify-code", json={"test_code": CODE_V1}, headers=headers
        )
        assert verified.status == 200, (verified.status, await verified.text())
        payload = await verified.json()
        part_ranges = [rng for rng in payload["layout"] if rng.get("parts")]
        assert part_ranges, payload["layout"]
        assert part_ranges[-1]["parts"] == ["a", "b"], part_ranges
        print("[OK] v1 verify-code (sessiyasiz): 36 → parts=['a','b'] qaytdi")

        answers = {str(position): answer_for(position) for position in range(1, 36)}
        answers["36a"] = "2.236"
        answers["36b"] = "0.429"
        submitted = await client.post(
            "/api/submit", json={"test_code": CODE_V1, "answers": answers}, headers=headers
        )
        assert submitted.status == 200, (submitted.status, await submitted.text())

    stored = await repos.answers.get(STUDENT_V1["id"], exam_id)
    assert stored is not None, "javob saqlanmadi"
    canonical = stored.submitted_answers
    assert "|36a:2.236" in canonical and "36b:0.429" in canonical, canonical
    print(f"[OK] v1 /api/submit: a/b alohida saqlandi → …{canonical[-16:]}")


async def make_form(
    repos: Repositories, code: str, questions: list[dict], parts: list[str], answer_key: str
) -> None:
    form_id, _version = await repos.forms.create_full_form(
        title=f"Capture {code}",
        test_code=code,
        total_questions=TOTAL,
        answer_key=answer_key,
        questions=questions,
        parts=parts,
        created_by=ADMIN_ID,
    )
    now = exam_service.utc_now()
    await repos.sessions.create(
        form_id=form_id,
        start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
        result_time=exam_service.to_db_time(now + timedelta(hours=1)),
        title=f"Sessiya {code}",
        created_by=ADMIN_ID,
    )


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_parts_capture_"))
    db = Database(tmp_dir / "parts_capture.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("Phase 3 Step 2: qismli (36a/36b) mustaqil saqlash va tiklash")
    print("=" * 72)
    try:
        await repos.users.upsert(
            User(user_id=ADMIN_ID, full_name="Olim Ustoz", username="ustoz")
        )
        await repos.users.upsert(
            User(user_id=STUDENT["id"], full_name="Ali Qismli", username=None)
        )
        await repos.users.upsert(
            User(user_id=STUDENT_V1["id"], full_name="Vali V1", username=None)
        )

        await make_form(
            repos,
            CODE_PARTS,
            part_questions(),
            ["36a", "36b"],
            f"{key_letters()}|36a:\u221a5,36b:3/7",
        )
        await make_form(
            repos,
            CODE_LEGACY,
            legacy_questions(),
            [],
            f"{key_letters()}|36:2.5",
        )

        await check_parts(repos, db)
        await check_legacy(repos, db)
        await check_v1_parts_without_session(repos)
    finally:
        config.ITEM_LEVEL_GRADING_ENABLED = _ORIGINAL_ITEM_FLAG
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Phase 3 Step 2 muvaffaqiyatli o'tdi \u2705")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())


