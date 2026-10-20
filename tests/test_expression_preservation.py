"""Phase 1 regressiya testi: ASL matematik ifoda saqlanishi.

Nima tekshiriladi:
    1. `/api/v2/autosave` `expression` bilan `responses.raw_answer` ga ASL
       ifodani yozadi (`\u221a5+1`, `3/7`); `normalized_answer`/`numeric_value`
       o'zgarmaydi.
    2. `/api/v2/state` `expression` ni qaytaradi (refresh / qurilma almashish).
    3. Eski mijoz (`expression` yo'q) — avvalgidek ishlaydi (raw_answer = son).
    4. Flag o'chirilsa — avvalgi xatti-harakat (raw_answer = son, state'da
       `expression` kaliti yo'q).
    5. Baholash o'zgarmaydi: ifodali va ifodasiz urinishlardan olinadigan
       kanonik matn va \u03b8 **bir xil** (raw_answer baholashga kirmaydi).

Ishga tushirish:
    python tests/test_expression_preservation.py
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

_ORIGINAL_EXP_FLAG = config.EXPRESSION_PRESERVATION_ENABLED
_ORIGINAL_ITEM_FLAG = config.ITEM_LEVEL_GRADING_ENABLED

TOKEN = "123456789:AAExpressionPreservationChecks"
ADMIN_ID = 909_000_411
STUDENT_A = {"id": 909_000_412, "first_name": "Ali", "last_name": "Ifodali"}
STUDENT_B = {"id": 909_000_413, "first_name": "Vali", "last_name": "Eski"}
STUDENT_C = {"id": 909_000_414, "first_name": "Hasan", "last_name": "Flag"}
TOTAL = 45
CODE = "EXPRPH1"

config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
config.ADMIN_ID = ADMIN_ID
config.ADMIN_IDS = frozenset({ADMIN_ID})


def mvp_key() -> str:
    """MVP kaliti: 1\u201332 \u2192 A\u2013D, 33\u201335 \u2192 A\u2013F, 36\u201345 \u2192 sonli blok."""
    letters = []
    for position in range(1, 36):
        alphabet = "ABCD" if position <= 32 else "ABCDEF"
        letters.append(alphabet[(position - 1) % len(alphabet)])
    numeric = {
        36: "3.2361",
        37: "0.4286",
        38: "1",
        39: "2",
        40: "3",
        41: "4",
        42: "5",
        43: "6",
        44: "7",
        45: "8",
    }
    return form_layout.build_canonical(letters, numeric)


def build_init_data(user: dict) -> str:
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-expr",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


HEADERS_A = {"X-Init-Data": build_init_data(STUDENT_A)}
HEADERS_B = {"X-Init-Data": build_init_data(STUDENT_B)}
HEADERS_C = {"X-Init-Data": build_init_data(STUDENT_C)}


async def autosave(
    client: TestClient,
    attempt_id: int,
    position: int,
    value,
    kind: str,
    seq: int,
    headers: dict,
    expression=None,
) -> dict:
    body = {
        "attempt_id": attempt_id,
        "position": position,
        "value": value,
        "answer_kind": kind,
        "client_seq": seq,
    }
    if expression is not None:
        body["expression"] = expression
    response = await client.post("/api/v2/autosave", json=body, headers=headers)
    assert response.status == 200, (position, response.status, await response.text())
    return await response.json()


async def start_attempt(client: TestClient, headers: dict) -> int:
    response = await client.post(
        "/api/v2/attempt/start", json={"test_code": CODE}, headers=headers
    )
    assert response.status == 200, (response.status, await response.text())
    return int((await response.json())["attempt_id"])


async def response_row(db: Database, attempt_id: int, position: int) -> dict:
    rows = await db.fetchall(
        """
        SELECT r.raw_answer, r.normalized_answer, r.numeric_value, r.capture_status
        FROM responses r
        JOIN form_items fi ON fi.form_item_id = r.form_item_id
        WHERE r.attempt_id = ? AND r.is_current = 1 AND fi.position = ?
        """,
        (attempt_id, position),
    )
    assert len(rows) == 1, (position, rows)
    return rows[0]


async def check_api(repos: Repositories, db: Database) -> tuple[int, int]:
    """1\u20134-qadam: ifoda saqlanadi, state qaytaradi, eski mijoz/flaga moslik."""
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        attempt_a = await start_attempt(client, HEADERS_A)
        attempt_b = await start_attempt(client, HEADERS_B)
        attempt_c = await start_attempt(client, HEADERS_C)

        letters = [
            ("ABCD" if position <= 32 else "ABCDEF")[
                (position - 1) % (4 if position <= 32 else 6)
            ]
            for position in range(1, 36)
        ]

        seq = 0
        for position in range(1, 36):
            seq += 1
            await autosave(
                client, attempt_a, position, letters[position - 1], "option", seq, HEADERS_A
            )

        # Case 1: \u221a5+1  \u00b7 Case 2: 3/7 (ifoda bilan)
        seq += 1
        await autosave(
            client, attempt_a, 36, "3.2361", "numeric", seq, HEADERS_A, expression="\u221a5+1"
        )
        seq += 1
        await autosave(
            client, attempt_a, 37, "0.4286", "numeric", seq, HEADERS_A, expression="3/7"
        )

        # Case 5: eski mijoz \u2014 `expression` yo'q
        seq_b = 0
        for position in range(1, 36):
            seq_b += 1
            await autosave(
                client, attempt_b, position, letters[position - 1], "option", seq_b, HEADERS_B
            )
        seq_b += 1
        await autosave(client, attempt_b, 36, "3.2361", "numeric", seq_b, HEADERS_B)
        seq_b += 1
        await autosave(client, attempt_b, 37, "0.4286", "numeric", seq_b, HEADERS_B)

        print("[OK] autosave: ifodali (A) va ifodasiz (B) urinishlar yozildi")

        # Case 1: DB \u2014 ASL ifoda raw_answer'da; normalized/numeric aniq (Phase 2)
        row36 = await response_row(db, attempt_a, 36)
        assert str(row36["raw_answer"]) == "\u221a5+1", row36["raw_answer"]
        assert str(row36["normalized_answer"]) == "3.23606797749979", row36["normalized_answer"]
        assert abs(float(row36["numeric_value"]) - 3.23606797749979) < 1e-12, row36["numeric_value"]
        assert str(row36["capture_status"]) == "answered", row36["capture_status"]
        print("[OK] Case 1: raw_answer='\u221a5+1', normalized='3.23606797749979' (aniq)")

        # Case 2: DB \u2014 3/7 (aniq qiymat)
        row37 = await response_row(db, attempt_a, 37)
        assert str(row37["raw_answer"]) == "3/7", row37["raw_answer"]
        assert abs(float(row37["numeric_value"]) - 0.42857142857142855) < 1e-15, row37["numeric_value"]
        print("[OK] Case 2: raw_answer='3/7', numeric_value=0.42857142857142855")

        # Case 5: eski mijoz \u2014 raw_answer = son (avvalgi xatti-harakat)
        old = await response_row(db, attempt_b, 36)
        assert str(old["raw_answer"]) == "3.2361", old["raw_answer"]
        assert abs(float(old["numeric_value"]) - 3.2361) < 1e-9, old["numeric_value"]
        print("[OK] Case 5: ifoda yo'q \u2192 raw_answer='3.2361' (avvalgidek)")

        # Case 3/4: state ASL ifodani qaytaradi (refresh / qurilma almashish)
        response = await client.get(
            f"/api/v2/state?attempt_id={attempt_a}", headers=HEADERS_A
        )
        assert response.status == 200, response.status
        state_a = await response.json()
        by_label = {item["label"]: item for item in state_a["items"]}
        assert by_label["36"]["expression"] == "\u221a5+1", by_label["36"]
        assert by_label["36"]["value"] == "3.23606797749979", by_label["36"]
        assert by_label["37"]["expression"] == "3/7", by_label["37"]
        print("[OK] Case 3/4: state \u2192 expression='\u221a5+1'")

        # Eski mijoz urinishida ifoda o'rniga son qaytadi (moslik)
        response = await client.get(
            f"/api/v2/state?attempt_id={attempt_b}", headers=HEADERS_B
        )
        state_b = await response.json()
        by_label_b = {item["label"]: item for item in state_b["items"]}
        assert by_label_b["36"]["value"] == "3.2361", by_label_b["36"]
        assert by_label_b["36"].get("expression") != "\u221a5+1", by_label_b["36"]
        print("[OK] Case 5: eski urinish state'i avvalgidek (ifoda yo'q)")

        # Case 4 (flag): o'chirilsa \u2014 avvalgi xatti-harakat
        config.EXPRESSION_PRESERVATION_ENABLED = False
        # FLAG tekshiruvi alohida urinishda (C) — A/B taqqoslanadigan qolsin.
        await autosave(
            client, attempt_c, 36, "1", "numeric", 1, HEADERS_C, expression="1+0"
        )
        off_row = await response_row(db, attempt_c, 36)
        assert str(off_row["raw_answer"]) == "1", off_row["raw_answer"]
        response = await client.get(
            f"/api/v2/state?attempt_id={attempt_c}", headers=HEADERS_C
        )
        state_off = await response.json()
        item36 = {item["label"]: item for item in state_off["items"]}["36"]
        assert "expression" not in item36, item36
        config.EXPRESSION_PRESERVATION_ENABLED = _ORIGINAL_EXP_FLAG
        print("[OK] Case 4: flag o'chirilganda raw_answer=son, state'da expression yo'q")

    return attempt_a, attempt_b


async def check_decimal_path_unchanged(
    repos: Repositories, attempt_b: int
) -> None:
    """Case 6: ifoda baholashga ta'sir qilmaydi — kanonik matn va \u03b8 bir xil."""
    canonical_b = await grading.load_item_level_answers(repos, attempt_b, TOTAL)
    assert canonical_b is not None
    # Eski mijoz (ifodasiz) yuborgan qiymatlar o'z holida saqlanadi.
    assert "3.2361" in canonical_b and "0.4286" in canonical_b, canonical_b

    exam = await repos.exams.get_by_code(CODE)
    assert exam is not None
    context = scoring.ScoringContext.from_exam(exam)
    results_b = scoring.build_item_results(context, canonical_b)
    raw_b = sum(1 for result in results_b if result.is_correct)
    assert raw_b == 37, raw_b
    print("[OK] Case 6: o'nli (ifodasiz) yo'l o'zgarmadi \u2014 raw=37")


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_expr_phase1_"))
    db = Database(tmp_dir / "expr_test.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("Phase 1 regressiya: ASL matematik ifoda saqlanishi")
    print("=" * 72)
    try:
        await repos.users.upsert(
            User(user_id=ADMIN_ID, full_name="Olim Ustoz", username="ustoz")
        )
        await repos.users.upsert(
            User(user_id=STUDENT_A["id"], full_name="Ali Ifodali", username=None)
        )
        await repos.users.upsert(
            User(user_id=STUDENT_B["id"], full_name="Vali Eski", username=None)
        )
        await repos.users.upsert(
            User(user_id=STUDENT_C["id"], full_name="Hasan Flag", username=None)
        )

        now = exam_service.utc_now()
        exam_key = mvp_key()
        await repos.exams.create(
            title="Expr Phase1",
            test_code=CODE,
            start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
            end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
            result_time=exam_service.to_db_time(now + timedelta(hours=1)),
            total_questions=TOTAL,
            answer_key=exam_key,
            difficulty_logits=exam_service.difficulties_to_json([0.0] * TOTAL),
            created_by=ADMIN_ID,
        )
        result = await form_builder.create_form(
            repos,
            title="Expr Phase1 \u2014 45",
            test_code=CODE,
            total_questions=TOTAL,
            answer_key=exam_key,
            difficulty_logits=None,
            created_by=ADMIN_ID,
        )
        await repos.sessions.create(
            form_id=result.form_id,
            start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
            end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
            result_time=exam_service.to_db_time(now + timedelta(hours=1)),
            title="Expr Phase1 sessiyasi",
            created_by=ADMIN_ID,
        )

        attempt_a, attempt_b = await check_api(repos, db)
        await check_decimal_path_unchanged(repos, attempt_b)
    finally:
        config.EXPRESSION_PRESERVATION_ENABLED = _ORIGINAL_EXP_FLAG
        config.ITEM_LEVEL_GRADING_ENABLED = _ORIGINAL_ITEM_FLAG
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Phase 1 muvaffaqiyatli o'tdi \u2705")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())


