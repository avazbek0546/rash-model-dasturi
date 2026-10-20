"""Phase 3 Step 4 regressiya testi: qismli savollar (36a/36b) to'liq oqimi.

Tekshiriladi
------------
    1. Qismli formada snapshot har bir qismni **alohida** yozadi (36a, 36b).
    2. 36a va 36b **har xil** `form_item_id` oladi — `UNIQUE(snapshot_id,
       form_item_id)` buzilmaydi.
    3. `display_label` = `36a` / `36b` (`position` esa 36 bo'lib qoladi).
    4. Snapshot yozilmasa ham `attempts` natijasi saqlanadi va **qisman**
       snapshot commit bo'lmaydi.
    5. Analytics, report va solutions da 36a / 36b alohida ko'rinadi.
    6. Legacy (qismsiz) forma snapshot/report/analytics jihatidan o'zgarmaydi.

Ishga tushirish:
    python tests/test_parts_snapshot.py
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
from typing import Any
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
    analytics,
    exam_service,
    grading,
    math_expr,
    solutions,
    webapp_auth,
)
from web.server import create_app  # noqa: E402

TOKEN = "123456789:AAPartsSnapshotChecks"
ADMIN_ID = 909_000_811
STUDENT = {"id": 909_000_812, "first_name": "Ali", "last_name": "Snapshot"}
STUDENT_B = {"id": 909_000_813, "first_name": "Vali", "last_name": "Snapshot"}
TOTAL = 45
LEGACY_TOTAL = 36
CODE_PARTS = "SNAP45P"
CODE_PARTS_BROKEN = "SNAP45B"
CODE_LEGACY = "SNAP36L"

config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
config.ADMIN_ID = ADMIN_ID
config.ADMIN_IDS = frozenset({ADMIN_ID})


def key_letters(total: int = 35) -> str:
    """Kalit harflari: 1–32 → A–D, 33–35 → A–F."""
    return "".join(
        f"{position}{('ABCD' if position <= 32 else 'ABCDEF')[(position - 1) % (4 if position <= 32 else 6)]}"
        for position in range(1, total + 1)
    )


def part_values() -> dict[str, str]:
    """Qismli kalit qiymatlari — 36a…45b (20 ta qism)."""
    values: dict[str, str] = {"36a": "\u221a5", "36b": "3/7", "37a": "12", "37b": "\u03c0/2"}
    for position in range(38, 46):
        values[f"{position}a"] = str(position)
        values[f"{position}b"] = str(position * 2)
    return values


def part_given() -> dict[str, str]:
    """O'quvchi javoblari — 36a/36b ekvivalent shakllarda (hammasi to'g'ri)."""
    given = dict(part_values())
    given["36a"] = "(\u221a20)/2"
    given["36b"] = "6/14"
    return given


def part_labels() -> list[str]:
    """Belgilar tartibi: 36a, 36b, 37a, … 45b."""
    return [f"{position}{part}" for position in range(36, 46) for part in ("a", "b")]


def parts_key() -> str:
    """Qismli kalit: 35 variant + 20 qism."""
    return f"{key_letters()}|" + ",".join(
        f"{label}:{value}" for label, value in part_values().items()
    )


def legacy_key() -> str:
    """Legacy kalit: 35 variant + `|36:12.5` (qismsiz)."""
    return f"{key_letters()}|36:12.5"


def numeric_spec() -> str:
    """`answer_spec` (sonli savol)."""
    return json.dumps({"kind": "numeric", "accepted": [], "tolerance": 1e-6})


def form_questions(with_parts: bool, total: int) -> list[dict]:
    """1–32 (mcq4) + 33–35 (mcq6) + 36…total (sonli; qismli bo'lsa a/b)."""
    questions: list[dict] = []
    for position in range(1, 36):
        options = "ABCD" if position <= 32 else "ABCDEF"
        questions.append(
            {
                "position": position,
                "display_label": str(position),
                "part": "",
                "section_no": 1 if position <= 32 else 2,
                "item_type": "mcq4" if position <= 32 else "mcq6",
                "correct_option": options[(position - 1) % len(options)],
                "options_count": len(options),
                "answer_spec": json.dumps({"kind": "option"}),
                "points": 1.0,
                "difficulty": 0.0,
            }
        )
    for position in range(36, max(total, 35) + 1):
        for part in ("a", "b") if with_parts else ("",):
            questions.append(
                {
                    "position": position,
                    "display_label": f"{position}{part}",
                    "part": part,
                    "section_no": 3,
                    "item_type": "numeric",
                    "correct_option": None,
                    "options_count": 0,
                    "answer_spec": numeric_spec(),
                    "points": 1.0,
                    "difficulty": 0.0,
                }
            )
    return questions


def build_init_data(user: dict) -> str:
    """Imzolangan `initData` (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-parts-snapshot",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


def headers_for(user: dict) -> dict[str, str]:
    """Foydalanuvchi uchun `X-Init-Data` sarlavhasi."""
    return {"X-Init-Data": build_init_data(user)}


async def start_attempt(client: TestClient, code: str, user: dict) -> dict:
    """`/api/v2/attempt/start` — urinishni boshlaydi."""
    response = await client.post(
        "/api/v2/attempt/start", json={"test_code": code}, headers=headers_for(user)
    )
    assert response.status == 200, (code, response.status, await response.text())
    return await response.json()


async def autosave(
    client: TestClient,
    attempt_id: int,
    position: int,
    part: str,
    value: Any,
    seq: int,
    *,
    user: dict,
    expression: str | None = None,
    answer_kind: str = "numeric",
) -> dict:
    """`/api/v2/autosave` — bitta javob (idempotent, `client_seq` bilan)."""
    body: dict[str, Any] = {
        "attempt_id": attempt_id,
        "position": position,
        "part": part,
        "value": value,
        "answer_kind": answer_kind,
        "client_seq": seq,
    }
    if expression is not None:
        body["expression"] = expression
    response = await client.post(
        "/api/v2/autosave", json=body, headers=headers_for(user)
    )
    assert response.status == 200, (position, part, response.status, await response.text())
    return await response.json()


async def fill_attempt(
    client: TestClient,
    attempt_id: int,
    user: dict,
    *,
    with_parts: bool,
    total: int,
) -> None:
    """Barcha savollarga to'g'ri javob yozadi (variantlar + sonli/qismli)."""
    seq = 0
    for position in range(1, 36):
        options = "ABCD" if position <= 32 else "ABCDEF"
        seq += 1
        await autosave(
            client,
            attempt_id,
            position,
            "",
            options[(position - 1) % len(options)],
            seq,
            user=user,
            answer_kind="option",
        )
    given = part_given() if with_parts else {"36": "12.5"}
    for position in range(36, max(total, 35) + 1):
        for part in ("a", "b") if with_parts else ("",):
            expression = given[f"{position}{part}"]
            value = math_expr.format_number(math_expr.evaluate(expression))
            seq += 1
            await autosave(
                client,
                attempt_id,
                position,
                part,
                value,
                seq,
                user=user,
                expression=expression,
            )


async def make_form(
    repos: Repositories,
    *,
    code: str,
    total: int,
    with_parts: bool,
    answer_key_text: str,
) -> int:
    """Item-level forma + sessiya + legacy `exams` yozuvi; `exam_id` qaytaradi."""
    parts = part_labels() if with_parts else []
    form_id, _version = await repos.forms.create_full_form(
        title=f"Snapshot {code}",
        test_code=code,
        total_questions=total,
        answer_key=answer_key_text,
        questions=form_questions(with_parts, total),
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
    return await repos.exams.create(
        title=f"Snapshot {code}",
        test_code=code,
        start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
        result_time=exam_service.to_db_time(now + timedelta(hours=1)),
        total_questions=total,
        answer_key=answer_key_text,
        difficulty_logits=exam_service.difficulties_to_json([0.0] * total),
        created_by=ADMIN_ID,
    )


async def check_parts_snapshot(repos: Repositories, db: Database) -> None:
    """1–3, 5 va regrade: 36a/36b snapshot/analytics/report/solutions da alohida."""
    exam_id = await make_form(
        repos, code=CODE_PARTS, total=TOTAL, with_parts=True, answer_key_text=parts_key()
    )
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        started = await start_attempt(client, CODE_PARTS, STUDENT)
        attempt_id = int(started["attempt_id"])
        await fill_attempt(client, attempt_id, STUDENT, with_parts=True, total=TOTAL)
        canonical = await grading.load_item_level_answers(repos, attempt_id, TOTAL)
        assert canonical is not None

    await repos.answers.submit(
        user_id=STUDENT["id"], exam_id=exam_id, submitted_answers=canonical
    )
    exam = await repos.exams.get(exam_id)
    assert exam is not None

    config.ITEM_LEVEL_GRADING_ENABLED = True
    graded = await grading.grade_exam(repos, exam)
    assert graded == 1, graded

    session = await repos.sessions.get_by_test_code(CODE_PARTS)
    assert session is not None
    form_items = await repos.forms.items_by_label(int(session["form_version_id"]))

    snapshot = await repos.snapshots.get_final(attempt_id)
    assert snapshot is not None, "snapshot yozilmadi"
    assert int(snapshot["total_items"]) == 55, snapshot["total_items"]
    rows = await repos.snapshots.list_items(int(snapshot["snapshot_id"]))
    assert len(rows) == 55, len(rows)
    labels = [str(row["display_label"]) for row in rows]
    assert labels[:35] == [str(position) for position in range(1, 36)], labels[:35]
    assert labels[35:] == part_labels(), labels[35:]
    print("[OK] Snapshot: 35 variant + 20 qism = 55 qator (36a\u202645b alohida)")

    two = [row for row in rows if int(row["position"]) == 36]
    assert len(two) == 2, two
    assert {str(row["display_label"]) for row in two} == {"36a", "36b"}
    ids = [int(row["form_item_id"]) for row in two]
    assert ids[0] != ids[1], ids
    for row in two:
        label = str(row["display_label"])
        assert int(row["form_item_id"]) == int(form_items[label]["form_item_id"])
        assert int(row["item_version_id"]) == int(form_items[label]["item_version_id"])
    print("[OK] 36a/36b: har xil form_item_id (form_items satriga mos) — UNIQUE buzilmadi")

    attempt = await db.fetchone(
        """
        SELECT theta, raw_score, n_answered, engine_version, status
        FROM attempts WHERE attempt_id = ?
        """,
        (attempt_id,),
    )
    assert attempt is not None and attempt["theta"] is not None
    assert int(attempt["raw_score"]) == 55 and int(attempt["n_answered"]) == 55, attempt
    assert str(attempt["status"]) == "graded", attempt
    print("[OK] attempts: theta/raw_score/n_answered yozildi (55 savol)")

    submission = await repos.answers.get(STUDENT["id"], exam_id)
    assert submission is not None

    report = grading.build_report(exam, submission)
    assert len(report["items"]) == 55, len(report["items"])
    assert "label" not in report["items"][0], report["items"][0]
    by_label = {item.get("label"): item for item in report["items"]}
    assert "36a" in by_label and "36b" in by_label, sorted(by_label)
    assert by_label["36a"]["number"] == 36 and by_label["36b"]["number"] == 36
    assert all(item["is_correct"] for item in report["items"])
    print("[OK] Report: 36a/36b alohida yozuvlar (legacy savolda `label` yo'q)")

    units = solutions.build_question_units(exam, submission)
    unit_labels = [unit.label for unit in units]
    assert len(units) == 55, len(units)
    assert unit_labels[35:37] == ["\u2705 36a", "\u2705 36b"], unit_labels[35:37]
    assert unit_labels[-1] == "\u2705 45b", unit_labels[-1]
    assert solutions.raw_score(exam, submission) == 55
    print("[OK] Solutions: 55 tugma, «\u2705 36a» va «\u2705 36b» alohida")

    stats = await analytics.build_item_statistics(repos, int(session["session_id"]))
    assert len(stats) == 55, len(stats)
    part_rows = [row for row in stats if "label" in row]
    plain_rows = [row for row in stats if "label" not in row]
    assert [row["label"] for row in part_rows] == part_labels(), part_rows[:3]
    assert [row["question_number"] for row in plain_rows] == list(range(1, 36))
    part_by_label = {row["label"]: row for row in part_rows}
    for label in ("36a", "36b"):
        row = part_by_label[label]
        assert row["question_number"] == 36 and row["attempts"] == 1, row
        assert row["correct_count"] == 1 and row["p_value"] == 1.0, row
    print("[OK] Analytics: 36a/36b alohida yozuv (o'z hisoblagichlari bilan)")

    await grading.grade_exam(repos, exam, regrade=True)
    finals = await db.fetchall(
        "SELECT snapshot_id, is_final FROM scoring_snapshots WHERE attempt_id = ?",
        (attempt_id,),
    )
    assert sum(1 for row in finals if int(row["is_final"]) == 1) == 1, finals
    final = await repos.snapshots.get_final(attempt_id)
    assert final is not None
    assert len(await repos.snapshots.list_items(int(final["snapshot_id"]))) == 55
    print("[OK] Regrade: bitta yakuniy snapshot, 55 qator (dublikatsiz)")


async def check_failure_isolation(repos: Repositories, db: Database) -> None:
    """4-qadam: snapshot xatosi `attempts` ni bloklamaydi, qisman yozuv qolmaydi."""
    exam_id = await make_form(
        repos,
        code=CODE_PARTS_BROKEN,
        total=TOTAL,
        with_parts=True,
        answer_key_text=parts_key(),
    )
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        started = await start_attempt(client, CODE_PARTS_BROKEN, STUDENT_B)
        attempt_id = int(started["attempt_id"])
        await fill_attempt(client, attempt_id, STUDENT_B, with_parts=True, total=TOTAL)
        canonical = await grading.load_item_level_answers(repos, attempt_id, TOTAL)
        assert canonical is not None

    await repos.answers.submit(
        user_id=STUDENT_B["id"], exam_id=exam_id, submitted_answers=canonical
    )
    exam = await repos.exams.get(exam_id)
    assert exam is not None

    config.ITEM_LEVEL_GRADING_ENABLED = True
    assert await grading.grade_exam(repos, exam) == 1

    before = await repos.snapshots.get_final(attempt_id)
    assert before is not None
    assert len(await repos.snapshots.list_items(int(before["snapshot_id"]))) == 55

    # 36b ning item-level bog'lanishini buzamiz: snapshot qatori qurilmaydi.
    session = await repos.sessions.get_by_test_code(CODE_PARTS_BROKEN)
    assert session is not None
    await db.execute(
        """
        UPDATE form_items SET item_version_id = NULL
        WHERE form_version_id = ? AND display_label = '36b'
        """,
        (int(session["form_version_id"]),),
    )

    assert await grading.grade_exam(repos, exam, regrade=True) == 1

    snapshots = await db.fetchall(
        """
        SELECT snapshot_id, is_final, total_items FROM scoring_snapshots
        WHERE attempt_id = ?
        """,
        (attempt_id,),
    )
    assert len(snapshots) == 1, snapshots  # yangi (qisman) snapshot yozilmadi
    assert int(snapshots[0]["is_final"]) == 1
    assert int(snapshots[0]["total_items"]) == 55
    items = await repos.snapshots.list_items(int(snapshots[0]["snapshot_id"]))
    assert len(items) == 55, len(items)  # qisman yozuv yo'q (rollback)

    attempt = await db.fetchone(
        "SELECT theta, raw_score FROM attempts WHERE attempt_id = ?", (attempt_id,)
    )
    assert attempt is not None and attempt["theta"] is not None
    assert int(attempt["raw_score"]) == 55
    print("[OK] Snapshot xatosi: `attempts` saqlandi, qisman snapshot yozilmadi (rollback)")


async def check_legacy_snapshot(repos: Repositories, db: Database) -> None:
    """6-qadam: legacy forma — snapshot/report/analytics/solutions o'zgarmaydi."""
    exam_id = await make_form(
        repos,
        code=CODE_LEGACY,
        total=LEGACY_TOTAL,
        with_parts=False,
        answer_key_text=legacy_key(),
    )
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        started = await start_attempt(client, CODE_LEGACY, STUDENT)
        attempt_id = int(started["attempt_id"])
        await fill_attempt(client, attempt_id, STUDENT, with_parts=False, total=LEGACY_TOTAL)
        canonical = await grading.load_item_level_answers(repos, attempt_id, LEGACY_TOTAL)
        assert canonical is not None
        assert canonical.endswith("|36:12.5"), canonical

    await repos.answers.submit(
        user_id=STUDENT["id"], exam_id=exam_id, submitted_answers=canonical
    )
    exam = await repos.exams.get(exam_id)
    assert exam is not None

    config.ITEM_LEVEL_GRADING_ENABLED = True
    assert await grading.grade_exam(repos, exam) == 1

    snapshot = await repos.snapshots.get_final(attempt_id)
    assert snapshot is not None
    rows = await repos.snapshots.list_items(int(snapshot["snapshot_id"]))
    assert len(rows) == LEGACY_TOTAL, len(rows)
    labels = [str(row["display_label"]) for row in rows]
    assert labels == [str(position) for position in range(1, LEGACY_TOTAL + 1)], labels
    assert len({int(row["form_item_id"]) for row in rows}) == LEGACY_TOTAL
    print("[OK] Legacy snapshot: 36 qator, belgilar `1`…`36` (o'zgarmagan)")

    submission = await repos.answers.get(STUDENT["id"], exam_id)
    assert submission is not None
    report = grading.build_report(exam, submission)
    assert len(report["items"]) == LEGACY_TOTAL, len(report["items"])
    assert all("label" not in item for item in report["items"])
    print("[OK] Legacy report: 36 yozuv, `label` maydoni qo'shilmagan")

    session = await repos.sessions.get_by_test_code(CODE_LEGACY)
    assert session is not None
    stats = await analytics.build_item_statistics(repos, int(session["session_id"]))
    assert [row["question_number"] for row in stats] == list(
        range(1, LEGACY_TOTAL + 1)
    ), stats[:3]
    assert all("label" not in row for row in stats)
    print("[OK] Legacy analytics: 36 yozuv, `label` maydoni qo'shilmagan")

    units = solutions.build_question_units(exam, submission)
    assert [unit.label for unit in units] == [
        f"\u2705 {position}" for position in range(1, LEGACY_TOTAL + 1)
    ], [unit.label for unit in units][:5]
    print("[OK] Legacy solutions: 36 tugma, belgilar o'zgarmagan")


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_parts_snapshot_"))
    db = Database(tmp_dir / "parts_snapshot.db")
    await db.connect()
    repos = Repositories(db)
    original_flag = config.ITEM_LEVEL_GRADING_ENABLED

    print("=" * 72)
    print("Phase 3 Step 4: qismli savollar snapshot/analytics/report/solutions")
    print("=" * 72)
    try:
        await repos.users.upsert(
            User(user_id=ADMIN_ID, full_name="Olim Ustoz", username="ustoz")
        )
        await repos.users.upsert(
            User(user_id=STUDENT["id"], full_name="Ali Snapshot", username=None)
        )
        await repos.users.upsert(
            User(user_id=STUDENT_B["id"], full_name="Vali Snapshot", username=None)
        )

        await check_parts_snapshot(repos, db)
        await check_failure_isolation(repos, db)
        await check_legacy_snapshot(repos, db)
    finally:
        config.ITEM_LEVEL_GRADING_ENABLED = original_flag
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Phase 3 Step 4 (snapshot fix) muvaffaqiyatli o'tdi \u2705")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
