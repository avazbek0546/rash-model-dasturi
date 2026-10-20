"""M1 regressiya testi: legacy (A–D) imtihonlarda item-level oqim ishlaydi.

Nima tekshiriladi:
    1. Legacy A–D kalit (45 savol, `|` blokisiz) → `form_builder.create_form`
       forma yaratadi: `mcq4=32, mcq6=3, numeric=20`; sonli savollar (36–45)
       **doim** `a`/`b` ga bo'linadi (qism kafolati — `form_layout.parts_of`)
       va javobsiz qismlar `answer_spec.accepted = []` bilan saqlanadi.
    2. Legacy imtihon uchun `exam_sessions` yaratiladi va
       `/api/v2/verify-code` + `/api/v2/attempt/start` **404 bermaydi** (M1).
    3. `/api/v2/autosave` 1–35 (harflar) va 36–45 (`blank`) uchun `responses`
       ga yozadi; `/api/v2/state` ularni qaytaradi.
    4. `ITEM_LEVEL_GRADING_ENABLED=1` da baholash `responses` dan o'qiydi:
       v1 `user_answers` ga ataylab **noto'g'ri** javob yozib, item-level manba
       ustunligi isbotlanadi (raw ball farqi bilan).
    5. Legacy `user_answers` oqimi (v1 submit) o'zgarishsiz ishlaydi.

Ishga tushirish:
    python tests/test_legacy_item_level.py
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
    form_builder,
    form_layout,
    grading,
    scoring,
    webapp_auth,
)
from web.server import create_app  # noqa: E402

_ORIGINAL_FLAG = config.ITEM_LEVEL_GRADING_ENABLED

TOKEN = "123456789:AALegacyItemLevelChecks"
ADMIN_ID = 909_000_222
STUDENT = {"id": 909_000_111, "first_name": "Ali", "last_name": "Valiyev"}
TOTAL = 45
#: QISM KAFOLATI: 36–45 har biri `a`/`b` → 35 variant + 20 qism = 55 element.
SPLIT_TOTAL = 35 + 2 * (TOTAL - 35)
CODE = "LEGACY45"

config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
config.ADMIN_ID = ADMIN_ID
config.ADMIN_IDS = frozenset({ADMIN_ID})


def legacy_key(total: int = TOTAL) -> str:
    """Legacy (A–D, `|` blokisiz) kalit: `1A2B…` (45 ta)."""
    return "".join(f"{position}{'ABCD'[(position - 1) % 4]}" for position in range(1, total + 1))


def key_letters(total: int = TOTAL) -> list[str]:
    """Kalitdagi harflar (`1–45` uchun A–D tsikli) — `legacy_key` bilan bir xil."""
    return ["ABCD"[(position - 1) % 4] for position in range(1, total + 1)]


def build_init_data(user: dict) -> str:
    """Imzolangan `initData` (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-legacy",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


STUDENT_HEADERS = {"X-Init-Data": build_init_data(STUDENT)}


async def check_legacy_form(repos: Repositories, db: Database) -> tuple[int, int]:
    """1-qadam: legacy A–D kalit → item-level forma + `exam_sessions` (M1 fix)."""
    await repos.users.upsert(User(user_id=ADMIN_ID, full_name="Olim Ustoz", username="ustoz"))
    await repos.users.upsert(
        User(user_id=STUDENT["id"], full_name="Ali Valiyev", username=None)
    )

    now = exam_service.utc_now()
    key = legacy_key()
    assert "|" not in key, "kalit legacy bo'lishi kerak (`|` yo'q)"

    exam_id = await repos.exams.create(
        title="Legacy 45 — A–D",
        test_code=CODE,
        start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
        result_time=exam_service.to_db_time(now + timedelta(hours=1)),
        total_questions=TOTAL,
        answer_key=key,
        difficulty_logits=exam_service.difficulties_to_json([0.0] * TOTAL),
        created_by=ADMIN_ID,
    )

    result = await form_builder.create_form(
        repos,
        title="Legacy 45 — A–D",
        test_code=CODE,
        total_questions=TOTAL,
        answer_key=key,
        difficulty_logits=None,
        created_by=ADMIN_ID,
    )
    assert result.kinds == {"mcq4": 32, "mcq6": 3, "numeric": 20}, result.kinds

    session_id = await repos.sessions.create(
        form_id=result.form_id,
        start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
        result_time=exam_service.to_db_time(now + timedelta(hours=1)),
        title="Legacy 45 sessiyasi",
        created_by=ADMIN_ID,
    )

    rows = await db.fetchall(
        """
        SELECT fi.position, iv.item_type, iv.answer_spec
        FROM form_items fi
        JOIN item_versions iv ON iv.item_version_id = fi.item_version_id
        WHERE fi.form_version_id = ?
        ORDER BY fi.position
        """,
        (result.form_version_id,),
    )
    assert len(rows) == SPLIT_TOTAL, len(rows)
    numeric = [row for row in rows if str(row["item_type"]) == "numeric"]
    assert len(numeric) == 20, len(numeric)  # 36–45 × (a, b)
    assert sorted({int(row["position"]) for row in numeric}) == list(range(36, 46))
    for row in numeric:
        spec = json.loads(str(row["answer_spec"]))
        assert spec["kind"] == "numeric" and spec["accepted"] == [], spec
    print(
        "[OK] Legacy kalit → forma: mcq4=32, mcq6=3, numeric=20 (36–45 → a/b, "
        f"accepted=[]), sessiya={session_id}"
    )
    return exam_id, result.form_version_id


async def check_api(repos: Repositories) -> int:
    """2-qadam: legacy imtihonda v2 endpointlari ishlaydi (404 emas) va to'ladi."""
    app = create_app(repos)
    letters = key_letters()
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/v2/verify-code", json={"test_code": CODE}, headers=STUDENT_HEADERS
        )
        assert response.status == 200, (response.status, await response.text())
        info = await response.json()
        assert info["can_start"] is True, info
        print("[OK] /api/v2/verify-code → 200 (M1: avval 404 edi)")

        response = await client.post(
            "/api/v2/attempt/start", json={"test_code": CODE}, headers=STUDENT_HEADERS
        )
        assert response.status == 200, (response.status, await response.text())
        attempt_id = int((await response.json())["attempt_id"])
        print(f"[OK] /api/v2/attempt/start → attempt_id={attempt_id}")

        seq = 0
        for position in range(1, 36):  # 1–35: majburiy (harflar)
            seq += 1
            response = await client.post(
                "/api/v2/autosave",
                json={
                    "attempt_id": attempt_id,
                    "position": position,
                    "value": letters[position - 1],
                    "answer_kind": "option",
                    "client_seq": seq,
                },
                headers=STUDENT_HEADERS,
            )
            assert response.status == 200, (position, response.status, await response.text())
        for position in range(36, 46):  # 36–45: `a`/`b` qismlar, ixtiyoriy (blank)
            for part in ("a", "b"):
                seq += 1
                response = await client.post(
                    "/api/v2/autosave",
                    json={
                        "attempt_id": attempt_id,
                        "position": position,
                        "part": part,
                        "value": None,
                        "answer_kind": "numeric",
                        "client_seq": seq,
                    },
                    headers=STUDENT_HEADERS,
                )
                assert response.status == 200, (
                    position,
                    part,
                    response.status,
                    await response.text(),
                )
        print("[OK] /api/v2/autosave → 55 ta yozuv (35 harf + 20 blank qism)")

        response = await client.get(
            f"/api/v2/state?attempt_id={attempt_id}", headers=STUDENT_HEADERS
        )
        assert response.status == 200, response.status
        state = await response.json()
        assert len(state["items"]) == SPLIT_TOTAL, len(state["items"])
        assert state["answered_count"] == 35, state["answered_count"]
        print(
            f"[OK] /api/v2/state → savol={len(state['items'])}, "
            f"javob={state['answered_count']} (36a–45b blank)"
        )

        response = await client.post(
            "/api/v2/submit", json={"attempt_id": attempt_id}, headers=STUDENT_HEADERS
        )
        assert response.status == 200, (response.status, await response.text())
        status = (await response.json())["status"]
        assert status in {"submitted", "submitted_late"}, status
        print(f"[OK] /api/v2/submit → {status}")

    return attempt_id


async def check_grading(repos: Repositories, exam_id: int, attempt_id: int, db: Database) -> None:
    """3-qadam: item-level manba (`responses`) ustunligini isbotlaydi.

    `user_answers` ga ataylab **noto'g'ri** javob yoziladi: legacy yo'l 34 ball
    beradi, `responses` esa 35. Baholash 35 chiqsa — manba `responses` (M1 fix).
    """
    letters = key_letters()
    wrong = "D" if letters[0] == "A" else "A"

    answers_v1 = {str(position): letters[position - 1] for position in range(1, 36)}
    answers_v1["1"] = wrong
    given_letters, given_numeric = form_layout.parse_structured_answers(answers_v1, TOTAL)
    legacy_canonical = form_layout.build_canonical(given_letters, given_numeric)

    exam = await repos.exams.get(exam_id)
    assert exam is not None
    context = scoring.ScoringContext.from_exam(exam)
    legacy_raw = sum(
        1 for result in scoring.build_item_results(context, legacy_canonical) if result.is_correct
    )
    assert legacy_raw == 34, legacy_raw

    await repos.answers.submit(
        user_id=STUDENT["id"], exam_id=exam_id, submitted_answers=legacy_canonical
    )

    config.ITEM_LEVEL_GRADING_ENABLED = True
    graded = await grading.grade_exam(repos, exam)
    assert graded >= 1, graded

    submission = await repos.answers.get(STUDENT["id"], exam_id)
    assert submission is not None and submission.theta is not None

    snapshot = await repos.snapshots.get_final(attempt_id)
    assert snapshot is not None, "item-level snapshot yozilmadi"
    item_rows = await db.fetchall(
        "SELECT COUNT(*) AS n FROM scoring_snapshot_items WHERE attempt_id = ?",
        (attempt_id,),
    )
    # DIQQAT (arxitektura chegarasi): snapshot savollari soni **kalit**dan keladi
    # (`ScoringContext` — `exams.answer_key` / `form_versions.answer_key`). Bu
    # testda kalit legacy (belgilanmagan), shu sababli baholash konteksti
    # avvalgidek 45 savol (`36`, `37`, …) — legacy xulq saqlanadi.
    # QISM KAFOLATI (a/b) **baholashda ham** to'liq bo'lishi uchun kalit ham
    # belgilangan bo'lishi kerak (`36a:…,36b:…`); admin paneli (Grid) va
    # qismli wizard doim shunday kalit yaratadi (`test_parts_authoring` ga qarang).
    assert int(item_rows[0]["n"]) == TOTAL, item_rows

    assert int(submission.raw_score) == 35, (
        f"item-level manba ishlatimadi: raw={submission.raw_score} (legacy bo'lsa 34)"
    )
    print(
        "[OK] Baholash `responses` dan o'qidi: raw=35 (legacy yo'l 34 berardi), "
        f"θ={submission.theta}, ball={submission.scaled_score}, "
        f"snapshot savollari={int(item_rows[0]['n'])}"
    )


async def main() -> None:
    """Testlarni ketma-ket ishga tushiradi."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_legacy_m1_"))
    db = Database(tmp_dir / "legacy_test.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("M1 regressiya: legacy (A–D) imtihonda item-level oqim")
    print("=" * 72)
    try:
        exam_id, _form_version_id = await check_legacy_form(repos, db)
        attempt_id = await check_api(repos)
        await check_grading(repos, exam_id, attempt_id, db)
    finally:
        config.ITEM_LEVEL_GRADING_ENABLED = _ORIGINAL_FLAG
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("M1 regressiya muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
