"""Teacher Analytics testlari (`services/analytics.py` + `/api/v2/admin/...`).

Qamrov:
    1. **bo'sh sessiya** — qatnashchi yo'q: o'rtachalar `None`, savollar 0 bilan;
    2. **1 ta qatnashchi** — jamlanma va savol statistikasi (correct/incorrect/
       omitted/not_reached va `p_value`);
    3. **ko'p qatnashchi** — o'rtacha/min/max va savollar bo'yicha yig'indi;
    4. **regrade qilingan snapshotlar** — faqat eng yangi yakuniy hisobga olinadi;
    5. **faqat final snapshotlar** — `is_final = 0` bo'lganlar tashlab yuboriladi;
    6. **yangi API** — `GET /api/v2/admin/session/{id}/summary|items`
       (admin 200, oddiy foydalanuvchi 403, yo'q sessiya 404).

Ishga tushirish:
    python tests/test_analytics.py
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
from services import analytics, exam_service, webapp_auth  # noqa: E402
from web.server import create_app  # noqa: E402

TOKEN = "123456789:AATestTokenForAnalyticsChecks"
ADMIN_ID = 555_000_111
ADMIN = {"id": ADMIN_ID, "first_name": "Olim", "last_name": "Ustoz", "username": "ustoz"}
STUDENT = {"id": 555_000_222, "first_name": "Aziz", "last_name": "Karimov"}
TOTAL = 5

config.BOT_TOKEN = TOKEN
config.WEBAPP_DEV_MODE = False
config.ADMIN_ID = ADMIN_ID
config.ADMIN_IDS = frozenset({ADMIN_ID})


def build_init_data(user: dict) -> str:
    """Imzolangan `initData` satrini yasaydi (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-analytics",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


ADMIN_HEADERS = {"X-Init-Data": build_init_data(ADMIN)}
STUDENT_HEADERS = {"X-Init-Data": build_init_data(STUDENT)}


def question_rows(total: int = TOTAL) -> list[dict]:
    """`create_full_form` kutgan savollar ro'yxati (oddiy mcq4)."""
    return [
        {
            "position": position,
            "display_label": str(position),
            "part": "",
            "section_no": 1,
            "item_type": "mcq4",
            "correct_option": "A",
            "options_count": 4,
            "answer_spec": json.dumps({"kind": "option", "correct": "A"}),
            "points": 1.0,
        }
        for position in range(1, total + 1)
    ]


async def make_form(repos: Repositories, *, code: str, title: str) -> tuple[int, int]:
    """Test formasi yaratadi va `(form_id, form_version_id)` qaytaradi."""
    return await repos.forms.create_full_form(
        title=title,
        test_code=code,
        total_questions=TOTAL,
        answer_key="1A2B3C4D5A",
        questions=question_rows(),
        created_by=ADMIN_ID,
    )


async def make_session(repos: Repositories, form_id: int, title: str) -> int:
    """Sessiya (vaqt oynasi) yaratadi."""
    now = exam_service.utc_now()
    return await repos.sessions.create(
        form_id=form_id,
        start_time=exam_service.to_db_time(now - timedelta(hours=2)),
        end_time=exam_service.to_db_time(now - timedelta(hours=1)),
        result_time=exam_service.to_db_time(now),
        title=title,
        created_by=ADMIN_ID,
    )


async def make_attempt(
    repos: Repositories,
    *,
    session_id: int,
    user_id: int,
    form_version_id: int,
    submitted: bool = True,
) -> int:
    """Foydalanuvchi + urinish yaratadi (`submitted=True` — topshirilgan)."""
    await repos.users.upsert(
        User(user_id=user_id, full_name=f"O'quvchi {user_id}", username=None)
    )
    now = exam_service.now_db()
    attempt_id = await repos.attempts.get_or_create(
        session_id=session_id,
        user_id=user_id,
        form_version_id=form_version_id,
        started_at=now,
    )
    if submitted:
        await repos.attempts.mark_submitted(
            attempt_id, submitted_at=now, submit_mode="manual"
        )
    return attempt_id


async def add_snapshot(
    repos: Repositories,
    *,
    form_items: dict[int, dict],
    attempt_id: int,
    form_version_id: int,
    session_id: int,
    theta: float,
    scaled: float,
    raw: int,
    correct: set[int],
    omitted: set[int] | None = None,
    not_reached: set[int] | None = None,
    is_final: bool = True,
) -> int:
    """Bitta urinish uchun snapshot (va savol natijalari) yozadi."""
    omitted = omitted or set()
    not_reached = not_reached or set()
    rows: list[tuple] = []
    for position, form_item in form_items.items():
        if position in correct:
            capture, score = "answered", 1.0
        elif position in omitted:
            capture, score = "blank", 0.0
        elif position in not_reached:
            capture, score = "not_reached", 0.0
        else:
            capture, score = "answered", 0.0
        rows.append(
            (
                int(form_item["form_item_id"]),
                int(form_item["item_id"]),
                int(form_item["item_version_id"]),
                str(form_item["display_label"]),
                int(position),
                None,
                0.0,
                "default",
                float(theta),
                0.25,
                "A",
                1,
                "teacher",
                "option",
                None,
                None,
                float(score),
                1.0,
                "auto_scored",
                "exact",
                capture,
                "1.0",
            )
        )
    return await repos.snapshots.save(
        attempt_id=attempt_id,
        form_version_id=form_version_id,
        theta=theta,
        theta_se=0.5,
        log_likelihood=-3.0,
        raw_score=raw,
        total_items=len(rows),
        omitted_count=len(omitted),
        not_reached_count=len(not_reached),
        scaled_score=scaled,
        scaled_min=0.0,
        scaled_max=100.0,
        theta_bound=3.0,
        engine_version="1.0",
        session_id=session_id,
        computed_by="system",
        is_final=is_final,
        items=rows,
    )


def _item(items: list[dict], position: int) -> dict:
    """Savol statistikasidan pozitsiya bo'yicha yozuvni oladi."""
    found = next((row for row in items if row["question_number"] == position), None)
    assert found is not None, f"{position}-savol statistikada yo'q"
    return found


async def check_empty_session(repos: Repositories) -> int:
    """Bo'sh sessiya: qatnashchi yo'q, o'rtachalar `None`, savollar 0 bilan."""
    form_id, _version_id = await make_form(
        repos, code="EMPTY01", title="Bo'sh sessiya formasi"
    )
    session_id = await make_session(repos, form_id, "Bo'sh sessiya")

    summary = await analytics.build_session_summary(repos, session_id)
    assert summary["participants_count"] == 0
    assert summary["submitted_count"] == 0
    assert summary["graded_count"] == 0
    assert summary["average_theta"] is None
    assert summary["average_scaled_score"] is None
    assert summary["average_raw_score"] is None
    assert summary["min_scaled_score"] is None and summary["max_scaled_score"] is None

    items = await analytics.build_item_statistics(repos, session_id)
    assert len(items) == TOTAL, items
    assert all(row["attempts"] == 0 for row in items)
    assert all(row["p_value"] is None for row in items)
    assert all(row["answer_type"] == "mcq4" for row in items)

    try:
        await analytics.build_session_summary(repos, 999_999)
    except analytics.AnalyticsError as exc:
        assert "topilmadi" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("yo'q sessiya xato bermadi")

    print("[OK] Bo'sh sessiya → 0 qatnashchi, o'rtachalar None, savollar 0 bilan")
    return session_id


async def check_one_participant(repos: Repositories) -> int:
    """1 ta qatnashchi: correct / incorrect / omitted / not_reached va p_value."""
    form_id, version_id = await make_form(
        repos, code="ONE01", title="Bitta qatnashchi formasi"
    )
    session_id = await make_session(repos, form_id, "Bitta qatnashchi sessiyasi")
    form_items = await repos.forms.items_by_position(version_id)
    attempt_id = await make_attempt(
        repos, session_id=session_id, user_id=901, form_version_id=version_id
    )
    await add_snapshot(
        repos,
        form_items=form_items,
        attempt_id=attempt_id,
        form_version_id=version_id,
        session_id=session_id,
        theta=0.5,
        scaled=60.0,
        raw=2,
        correct={1, 2},
        omitted={3},
        not_reached={4},
    )

    summary = await analytics.build_session_summary(repos, session_id)
    assert summary["participants_count"] == 1
    assert summary["submitted_count"] == 1
    assert summary["graded_count"] == 1
    assert summary["average_theta"] == 0.5
    assert summary["average_scaled_score"] == 60.0
    assert summary["average_raw_score"] == 2.0
    assert summary["min_scaled_score"] == 60.0 and summary["max_scaled_score"] == 60.0

    items = await analytics.build_item_statistics(repos, session_id)
    first = _item(items, 1)
    assert first["attempts"] == 1 and first["correct_count"] == 1
    assert first["incorrect_count"] == 0 and first["omitted_count"] == 0
    assert first["p_value"] == 1.0 and first["answer_type"] == "mcq4"

    third = _item(items, 3)
    assert third["attempts"] == 1 and third["correct_count"] == 0
    assert third["omitted_count"] == 1 and third["p_value"] == 0.0

    fourth = _item(items, 4)
    assert fourth["attempts"] == 0 and fourth["not_reached_count"] == 1
    assert fourth["p_value"] is None, "not_reached hisobga olinmasligi kerak"

    fifth = _item(items, 5)
    assert fifth["attempts"] == 1 and fifth["incorrect_count"] == 1
    assert fifth["p_value"] == 0.0

    print(
        "[OK] 1 qatnashchi → θ=0.5, ball=60.0, xom=2; "
        "p¹=1.0, omitted³=1, not_reached⁴ hisobdan chiqarilgan"
    )
    return session_id


async def check_many_participants(repos: Repositories) -> int:
    """Ko'p qatnashchi: o'rtacha/min/max va savollar bo'yicha yig'indi."""
    form_id, version_id = await make_form(
        repos, code="MANY01", title="Ko'p qatnashchi formasi"
    )
    session_id = await make_session(repos, form_id, "Ko'p qatnashchi sessiyasi")
    form_items = await repos.forms.items_by_position(version_id)

    plan = [
        (1101, 0.5, 60.0, 2, {1, 2}),
        (1102, -0.5, 40.0, 1, {1}),
        (1103, 1.5, 80.0, 3, {1, 2, 3}),
    ]
    for user_id, theta, scaled, raw, correct in plan:
        attempt_id = await make_attempt(
            repos, session_id=session_id, user_id=user_id, form_version_id=version_id
        )
        await add_snapshot(
            repos,
            form_items=form_items,
            attempt_id=attempt_id,
            form_version_id=version_id,
            session_id=session_id,
            theta=theta,
            scaled=scaled,
            raw=raw,
            correct=correct,
        )

    # 4-qatnashchi urinishni boshladi, lekin topshirmadi (snapshot yo'q).
    await make_attempt(
        repos,
        session_id=session_id,
        user_id=1104,
        form_version_id=version_id,
        submitted=False,
    )

    summary = await analytics.build_session_summary(repos, session_id)
    assert summary["participants_count"] == 4, summary
    assert summary["submitted_count"] == 3, summary
    assert summary["graded_count"] == 3, summary
    assert summary["average_theta"] == 0.5, summary
    assert summary["average_scaled_score"] == 60.0, summary
    assert summary["average_raw_score"] == 2.0, summary
    assert summary["min_scaled_score"] == 40.0 and summary["max_scaled_score"] == 80.0

    items = await analytics.build_item_statistics(repos, session_id)
    first, second, third = _item(items, 1), _item(items, 2), _item(items, 3)
    assert (first["attempts"], first["correct_count"], first["p_value"]) == (3, 3, 1.0)
    assert (second["attempts"], second["correct_count"]) == (3, 2)
    assert second["p_value"] == round(2 / 3, 4)
    assert (third["attempts"], third["correct_count"]) == (3, 1)
    assert third["p_value"] == round(1 / 3, 4)
    assert _item(items, 4)["incorrect_count"] == 3
    assert _item(items, 5)["incorrect_count"] == 3

    print(
        "[OK] Ko'p qatnashchi → 4 qatnashchi, 3 topshirgan, 3 baholangan; "
        "θ̄=0.5, ball̄=60.0, min=40.0, max=80.0; p¹=1.0, p²=0.6667, p³=0.3333"
    )
    return session_id


async def check_regrade(repos: Repositories, db: Database) -> int:
    """Regrade: faqat eng yangi YAKUNIY snapshot hisobga olinadi."""
    form_id, version_id = await make_form(
        repos, code="REGRADE1", title="Regrade formasi"
    )
    session_id = await make_session(repos, form_id, "Regrade sessiyasi")
    form_items = await repos.forms.items_by_position(version_id)
    attempt_id = await make_attempt(
        repos, session_id=session_id, user_id=1201, form_version_id=version_id
    )

    # 1-versiya (eski yakuniy) — keyin regrade paytida is_final = 0 bo'ladi.
    await add_snapshot(
        repos,
        form_items=form_items,
        attempt_id=attempt_id,
        form_version_id=version_id,
        session_id=session_id,
        theta=0.1,
        scaled=10.0,
        raw=1,
        correct={1},
    )
    # 2-versiya (yangi yakuniy, regrade).
    await add_snapshot(
        repos,
        form_items=form_items,
        attempt_id=attempt_id,
        form_version_id=version_id,
        session_id=session_id,
        theta=1.0,
        scaled=90.0,
        raw=5,
        correct={1, 2, 3, 4, 5},
    )

    rows = await db.fetchall(
        "SELECT is_final FROM scoring_snapshots WHERE attempt_id = ? ORDER BY snapshot_id",
        (attempt_id,),
    )
    assert len(rows) == 2, "regrade ikkita snapshot yozishi kerak"
    assert [int(row["is_final"]) for row in rows] == [0, 1], rows

    summary = await analytics.build_session_summary(repos, session_id)
    assert summary["graded_count"] == 1, "faqat yakuniy snapshot sanalishi kerak"
    assert summary["average_theta"] == 1.0, summary
    assert summary["average_scaled_score"] == 90.0, summary
    assert summary["average_raw_score"] == 5.0, summary

    items = await analytics.build_item_statistics(repos, session_id)
    assert all(row["p_value"] == 1.0 for row in items), items
    assert all(row["attempts"] == 1 for row in items), items

    print(
        "[OK] Regrade → 2 snapshot yozildi, faqat yakuniy (is_final=1) hisobga "
        "olindi (θ=1.0, ball=90.0)"
    )
    return session_id


async def check_api(repos: Repositories, session_id: int) -> None:
    """Yangi admin API endpoint'lari (aiohttp test client — tarmoqsiz)."""
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        url = f"/api/v2/admin/session/{session_id}"

        response = await client.get(f"{url}/summary", headers=ADMIN_HEADERS)
        assert response.status == 200, response.status
        payload = await response.json()
        assert payload["ok"] is True and payload["session_id"] == session_id
        assert payload["participants_count"] == 4 and payload["graded_count"] == 3
        assert payload["average_scaled_score"] == 60.0
        assert payload["min_scaled_score"] == 40.0
        assert payload["max_scaled_score"] == 80.0
        print(
            "[OK] GET /summary → 200: qatnashchilar=4, baholangan=3, "
            f"ball̄={payload['average_scaled_score']}"
        )

        response = await client.get(f"{url}/items", headers=ADMIN_HEADERS)
        assert response.status == 200, response.status
        payload = await response.json()
        assert payload["ok"] is True and payload["total_questions"] == TOTAL
        assert len(payload["items"]) == TOTAL
        first = payload["items"][0]
        assert set(first) >= {
            "question_number",
            "answer_type",
            "attempts",
            "correct_count",
            "incorrect_count",
            "omitted_count",
            "p_value",
        }, first
        assert first["p_value"] == 1.0 and first["answer_type"] == "mcq4"
        print(
            f"[OK] GET /items → 200: {len(payload['items'])} savol, "
            f"p¹={first['p_value']}, tur={first['answer_type']}"
        )

        response = await client.get(f"{url}/summary", headers=STUDENT_HEADERS)
        assert response.status == 403, response.status
        print(f"[OK] Oddiy foydalanuvchi rad etildi: {(await response.json())['error']}")

        response = await client.get(f"{url}/items", headers=STUDENT_HEADERS)
        assert response.status == 403, response.status

        response = await client.get(f"{url}/summary")
        assert response.status == 401, response.status

        response = await client.get(
            "/api/v2/admin/session/999999/summary", headers=ADMIN_HEADERS
        )
        assert response.status == 404, response.status
        print(f"[OK] Yo'q sessiya → 404: {(await response.json())['error']}")

        response = await client.get(
            "/api/v2/admin/session/abc/summary", headers=ADMIN_HEADERS
        )
        assert response.status == 400, response.status
        print("[OK] Noto'g'ri session_id → 400")


async def main() -> None:
    """Testlarni ketma-ket ishga tushiradi."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_analytics_"))
    db = Database(tmp_dir / "analytics_test.db")
    await db.connect()
    repos = Repositories(db)

    # `forms.created_by` FK → users: o'qituvchi va o'quvchini oldindan yozamiz.
    await repos.users.upsert(
        User(user_id=ADMIN_ID, full_name="Olim Ustoz", username="ustoz")
    )
    await repos.users.upsert(
        User(user_id=STUDENT["id"], full_name="Aziz Karimov", username=None)
    )

    print("=" * 72)
    print("Teacher Analytics testlari (snapshot asosida, tarmoqsiz)")
    print("=" * 72)
    try:
        await check_empty_session(repos)
        await check_one_participant(repos)
        many_session_id = await check_many_participants(repos)
        await check_regrade(repos, db)
        await check_api(repos, many_session_id)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha analitika tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())