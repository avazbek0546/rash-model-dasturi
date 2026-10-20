"""Phase 2 regressiya testi: matematik ekvivalentlik (symbolic equivalence).

Tekshiriladi:
    1. `services/math_expr` — ifodalarni hisoblash (√5, 3/7, π/2, |3-8|,
       (1+2)*3, yashirin ko'paytma) va ekvivalentlik.
    2. `form_layout.score_items` — kalit va javob natural ifoda bo'lishi
       mumkin; ekvivalent shakllar tan olinadi, boshqalari rad etiladi.
    3. Eski (faqat o'nli) imtihonlar o'zgarmaydi.
    4. To'liq API oqimi: autosave `expression` → server aniq hisoblaydi →
       baholash to'g'ri (raw_answer saqlanadi).
    5. Rasch: ifodali javob bilan olingan θ aniq o'nli javob bilan bir xil.

Ishga tushirish:
    python tests/test_symbolic_equivalence.py
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
from database.models import SKIPPED, User  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import (  # noqa: E402
    exam_service,
    form_builder,
    form_layout,
    grading,
    math_expr,
    scoring,
    webapp_auth,
)
from web.server import create_app  # noqa: E402

_ORIGINAL_ITEM_FLAG = config.ITEM_LEVEL_GRADING_ENABLED

TOKEN = "123456789:AASymbolicEquivalenceChecks"
ADMIN_ID = 909_000_511
STUDENT_A = {"id": 909_000_512, "first_name": "Ali", "last_name": "Ifodali"}
STUDENT_C = {"id": 909_000_513, "first_name": "Vali", "last_name": "Aniq"}
TOTAL = 41
CODE = "SYMBO41"

config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
config.ADMIN_ID = ADMIN_ID
config.ADMIN_IDS = frozenset({ADMIN_ID})


def letters_for(total: int) -> list[str]:
    """1–32 → A–D, 33–35 → A–F, sonli pozitsiyalar → SKIPPED (\"X\")."""
    out: list[str] = []
    for position in range(1, total + 1):
        if position <= 32:
            out.append("ABCD"[(position - 1) % 4])
        elif position <= 35:
            out.append("ABCDEF"[(position - 1) % 6])
        else:
            out.append(SKIPPED)
    return out


def key_letters_block(total: int = 36) -> str:
    """`1A2B…` ko'rinishidagi harflar bloki (sonli pozitsiyalarsiz, 1–35)."""
    return "".join(
        f"{position}{('ABCD' if position <= 32 else 'ABCDEF')[(position - 1) % (4 if position <= 32 else 6)]}"
        for position in range(1, min(total, 35) + 1)
    )


def key_with(numeric_text: str, total: int = 36) -> str:
    """Bitta sonli savolli kalit: `1A2B\u202635F|36:<numeric_text>`."""
    return f"{key_letters_block(total)}|36:{numeric_text}"


def submitted_with(given: str) -> str:
    """O'quvchi javobi: `1A2B…|36:<given>`."""
    return f"{key_letters_block(36)}|36:{given}"


def correct(outcomes, position: int = 36) -> bool:
    return outcomes[position - 1].is_correct


def check_math_expr() -> None:
    """1-qadam: hisoblash va ekvivalentlik (birlik)."""
    assert math_expr.evaluate("\u221a5") is not None
    assert abs(math_expr.evaluate("\u221a5") - 2.23606797749979) < 1e-12
    assert abs(math_expr.evaluate("3/7") - 0.42857142857142855) < 1e-15
    assert abs(math_expr.evaluate("\u03c0/2") - 1.5707963267948966) < 1e-15
    assert abs(math_expr.evaluate("\u221a5+1") - 3.23606797749979) < 1e-12
    assert abs(math_expr.evaluate("(1+2)*3") - 9.0) < 1e-15
    assert abs(math_expr.evaluate("|3-8|") - 5.0) < 1e-15
    assert abs(math_expr.evaluate("2\u03c0") - 6.283185307179586) < 1e-12
    assert abs(math_expr.evaluate("\u221b8") - 2.0) < 1e-12
    assert abs(math_expr.evaluate("2^10") - 1024.0) < 1e-9
    assert abs(math_expr.evaluate("3,5") - 3.5) < 1e-15
    assert math_expr.evaluate("\u221a5+") is None  # tugallanmagan
    print("[OK] math_expr: hisoblash (\u221a5, 3/7, \u03c0/2, |3-8|, 2\u03c0, \u221b8, 2^10)")

    # Ekvivalent (kalit \u221a5)
    assert math_expr.equivalent("\u221a5", "\u221a5")
    assert math_expr.equivalent("\u221a5", "2.236067977")
    assert math_expr.equivalent("\u221a5", "2.2360679")
    assert math_expr.equivalent("\u221a5", "2.236067")
    assert math_expr.equivalent("\u221a5", "2.236068")
    assert math_expr.equivalent("\u221a5", "(\u221a20)/2")
    # Ekvivalent emas
    assert not math_expr.equivalent("\u221a5", "2.23")
    assert not math_expr.equivalent("\u221a5", "2.2")
    print("[OK] math_expr: \u221a5 \u2261 {2.236067977, 2.2360679, (\u221a20)/2}; 2.23 rad etildi")

    assert math_expr.equivalent("3/7", "6/14")
    assert math_expr.equivalent("3/7", "0.428571428571")
    assert math_expr.equivalent("3/7", "0.428571")
    assert not math_expr.equivalent("3/7", "0.43")
    assert math_expr.equivalent("1/2", "2/4")
    print("[OK] math_expr: 3/7 \u2261 6/14 \u2261 0.428571; 0.43 rad etildi")

    assert math_expr.equivalent("\u03c0/2", "1.57079632679")
    assert math_expr.equivalent("\u03c0/2", "3.1415926535/2")
    assert math_expr.equivalent("\u221a5+1", "3.2360679")
    print("[OK] math_expr: \u03c0/2 \u2261 1.57079632679 \u2261 3.1415926535/2; \u221a5+1 \u2261 3.2360679")


def check_score_items() -> None:
    """2/3-qadam: kalit va javob natural ifoda bo'lishi mumkin."""
    def is_correct(key_text: str, given: str) -> bool:
        return correct(form_layout.score_items(key_text, submitted_with(given), 36))

    key = key_with("\u221a5")
    assert is_correct(key, "\u221a5")
    assert is_correct(key, "2.236067977")
    assert is_correct(key, "2.2360679")
    assert is_correct(key, "2.236067")
    assert is_correct(key, "2.236068")
    assert is_correct(key, "(\u221a20)/2")
    assert not is_correct(key, "2.23")
    print("[OK] score_items: kalit \u221a5 \u2192 ekvivalentlar o'tdi; 2.23 rad etildi")

    key = key_with("3/7")
    assert is_correct(key, "3/7")
    assert is_correct(key, "6/14")
    assert is_correct(key, "0.428571428571")
    assert is_correct(key, "0.428571")
    assert not is_correct(key, "0.43")
    print("[OK] score_items: kalit 3/7 \u2192 6/14 va o'nli shakllar; 0.43 rad etildi")

    key = key_with("\u03c0/2")
    assert is_correct(key, "\u03c0/2")
    assert is_correct(key, "1.57079632679")
    assert is_correct(key, "3.1415926535/2")
    assert not is_correct(key, "1.57")
    print("[OK] score_items: kalit \u03c0/2 \u2192 1.57079632679 va 3.1415926535/2")

    key = key_with("\u221a5+1")
    assert is_correct(key, "\u221a5+1")
    assert is_correct(key, "3.2360679")
    assert not is_correct(key, "3.24")
    print("[OK] score_items: kalit \u221a5+1 \u2192 o'zi va 3.2360679")

    key = key_with("|3-8|")
    assert is_correct(key, "|3-8|")
    assert is_correct(key, "5")
    assert not is_correct(key, "4")
    print("[OK] score_items: kalit |3-8| = 5; 4 rad etildi")

    key = key_with("(1+2)*3")
    assert is_correct(key, "9")
    assert is_correct(key, "(1+2)*3")
    assert not is_correct(key, "6")
    print("[OK] score_items: kalit (1+2)*3 = 9; 6 rad etildi")

    # D) teskari yo'nalish: kalit o'nli, javob ifoda
    key = key_with("2.23606797749979")
    assert is_correct(key, "\u221a5")
    assert is_correct(key, "(\u221a20)/2")
    assert not is_correct(key, "2.23")
    print("[OK] score_items: kalit o'nli \u2192 javob \u221a5 o'tdi (teskari yo'nalish)")

    # Eski (faqat o'nli) imtihonlar o'zgarmaydi: 1e-6 qoidasi saqlanadi
    key = key_with("12.5")
    assert is_correct(key, "12.5")
    assert is_correct(key, "12.50")
    assert not is_correct(key, "12.4")
    assert not is_correct(key, "12.6")
    key = key_with("2.23606797749979")
    assert not is_correct(key, "2.2361")  # farq 3.2e-5 > 1e-6 (avvalgidek)
    print("[OK] score_items: o'nli imtihonlar o'zgarmadi (12.5; farq > 1e-6 rad)")


def form_key() -> str:
    """Forma kaliti: 36:\u221a5, 37:3/7, 38:\u03c0/2, 39:\u221a5+1, 40:|3-8|, 41:12.5."""
    block = ",".join(
        f"{position}:{value}"
        for position, value in (
            (36, "\u221a5"),
            (37, "3/7"),
            (38, "\u03c0/2"),
            (39, "\u221a5+1"),
            (40, "|3-8|"),
            (41, "12.5"),
        )
    )
    return f"{key_letters_block(TOTAL)}|{block}"


def build_init_data(user: dict) -> str:
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-sym",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


HEADERS_A = {"X-Init-Data": build_init_data(STUDENT_A)}
HEADERS_C = {"X-Init-Data": build_init_data(STUDENT_C)}

# O'quvchi C — aniq o'nli javoblar (ifodasiz).
EXACT_DECIMALS = {
    36: "2.23606797749979",
    37: "0.428571428571429",
    38: "1.5707963267949",
    39: "3.23606797749979",
    40: "5",
    41: "12.5",
}


async def start_attempt(client: TestClient, headers: dict) -> int:
    response = await client.post(
        "/api/v2/attempt/start", json={"test_code": CODE}, headers=headers
    )
    assert response.status == 200, (response.status, await response.text())
    return int((await response.json())["attempt_id"])


async def autosave(
    client: TestClient,
    attempt_id: int,
    position: int,
    value,
    kind: str,
    seq: int,
    headers: dict,
    expression=None,
) -> None:
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
    """4-qadam: autosave `expression` \u2192 server aniq hisoblaydi + raw_answer."""
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        attempt_a = await start_attempt(client, HEADERS_A)
        attempt_c = await start_attempt(client, HEADERS_C)
        letters = [
            ("ABCD" if position <= 32 else "ABCDEF")[
                (position - 1) % (4 if position <= 32 else 6)
            ]
            for position in range(1, 36)
        ]
        expressions = {
            36: "\u221a5", 37: "3/7", 38: "\u03c0/2",
            39: "\u221a5+1", 40: "|3-8|", 41: "12.5",
        }
        client_values = {
            36: "2.2361", 37: "0.4286", 38: "1.5708",
            39: "3.2361", 40: "5", 41: "12.5",
        }

        seq = 0
        for position in range(1, 36):
            seq += 1
            await autosave(
                client, attempt_a, position, letters[position - 1], "option", seq, HEADERS_A
            )
        for position in range(36, 42):
            seq += 1
            await autosave(
                client, attempt_a, position, client_values[position], "numeric", seq,
                HEADERS_A, expression=expressions[position],
            )
        await client.post(
            "/api/v2/submit", json={"attempt_id": attempt_a}, headers=HEADERS_A
        )

        seq = 0
        for position in range(1, 36):
            seq += 1
            await autosave(
                client, attempt_c, position, letters[position - 1], "option", seq, HEADERS_C
            )
        for position in range(36, 42):
            seq += 1
            await autosave(
                client, attempt_c, position, EXACT_DECIMALS[position], "numeric", seq, HEADERS_C
            )
        await client.post(
            "/api/v2/submit", json={"attempt_id": attempt_c}, headers=HEADERS_C
        )

        row = await response_row(db, attempt_a, 36)
        assert str(row["raw_answer"]) == "\u221a5", row["raw_answer"]
        assert str(row["normalized_answer"]) == "2.23606797749979", row["normalized_answer"]
        assert abs(float(row["numeric_value"]) - 2.23606797749979) < 1e-12
        row_40 = await response_row(db, attempt_a, 40)
        assert str(row_40["raw_answer"]) == "|3-8|", row_40["raw_answer"]
        assert abs(float(row_40["numeric_value"]) - 5.0) < 1e-12
        print("[OK] API: 36 \u2192 raw_answer='\u221a5', normalized='2.23606797749979'; 40 \u2192 '|3-8|'=5")

    return attempt_a, attempt_c


async def check_grading(
    repos: Repositories, attempt_a: int, attempt_c: int, answer_key: str
) -> None:
    """5-qadam: baholash va Rasch \u2014 ifodali \u2261 aniq o'nli."""
    canonical_a = await grading.load_item_level_answers(repos, attempt_a, TOTAL)
    canonical_c = await grading.load_item_level_answers(repos, attempt_c, TOTAL)
    assert canonical_a is not None and canonical_c is not None
    assert canonical_a == canonical_c, (canonical_a, canonical_c)

    context = scoring.ScoringContext(
        exam_id=1,
        total_questions=TOTAL,
        answer_key=answer_key,
        b_by_key={str(position): 0.0 for position in range(1, TOTAL + 1)},
        mode=scoring.ScoringMode.ITEM_LEVEL,
    )
    results_a = scoring.build_item_results(context, canonical_a)
    results_c = scoring.build_item_results(context, canonical_c)
    raw_a = sum(1 for result in results_a if result.is_correct)
    raw_c = sum(1 for result in results_c if result.is_correct)
    assert raw_a == TOTAL, raw_a
    assert raw_c == TOTAL, raw_c
    theta_a = scoring.estimate_theta(results_a, context)
    theta_c = scoring.estimate_theta(results_c, context)
    assert abs(theta_a.theta - theta_c.theta) < 1e-12, (theta_a.theta, theta_c.theta)
    print(
        f"[OK] Baholash: ifodali raw={raw_a}/{TOTAL}, aniq o'nli raw={raw_c}/{TOTAL}, "
        f"theta bir xil={theta_a.theta:.6f}"
    )


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_symbolic_"))
    db = Database(tmp_dir / "symbolic_test.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("Phase 2 regressiya: matematik ekvivalentlik (symbolic equivalence)")
    print("=" * 72)
    try:
        check_math_expr()
        check_score_items()

        await repos.users.upsert(User(user_id=ADMIN_ID, full_name="Olim Ustoz", username="ustoz"))
        await repos.users.upsert(User(user_id=STUDENT_A["id"], full_name="Ali Ifodali", username=None))
        await repos.users.upsert(User(user_id=STUDENT_C["id"], full_name="Vali Aniq", username=None))

        now = exam_service.utc_now()
        exam_key = form_key()
        result = await form_builder.create_form(
            repos,
            title="Symbolic 41",
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
            title="Symbolic sessiya",
            created_by=ADMIN_ID,
        )

        attempt_a, attempt_c = await check_api(repos, db)
        await check_grading(repos, attempt_a, attempt_c, result.answer_key)
    finally:
        config.ITEM_LEVEL_GRADING_ENABLED = _ORIGINAL_ITEM_FLAG
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Phase 2 muvaffaqiyatli o'tdi \u2705")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())



