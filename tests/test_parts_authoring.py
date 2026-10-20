"""Phase 3 Step 6 regressiya testi: admin wizard orqali qismli (a/b) forma.

Tekshiriladi
------------
    1. Wizard qismli kalitni qabul qiladi (`parse_answer_key_input`) va kanonik
       ko'rinishda saqlaydi (`36a:…`, `36b:…`).
    2. `form_builder` qismli kalitdan forma yaratadi:
       `forms.parts_json` = `["36a","36b",…]`, `form_items.part` = `a`/`b`,
       `display_label` = `36a`/`36b`, har bir qism alohida `item`/`item_version`.
    3. Qismlar uchun `b` authoring qilinmaydi: `item_parameters.b_value = 0.0`,
       `source='default'`, `status='provisional'`.
    4. Mini App `layout` qismli bo'limni beradi (`parts=["a","b"]`) — frontend
       (`queue.js` `expandLayout`) 36a/36b ni **alohida katak** qiladi.
    5. **QISM KAFOLATI**: belgilanmagan (legacy `1A2B…` / qismsiz `|36:12.5`)
       kalitlarda ham 36–45 **doim** `a`/`b` ga bo'linadi (`form_layout.parts_of`
       — yagona manba); qiymatsiz qism `accepted = []` → doim "noto'g'ri".
       Belgilanmagan `36:12.5` qiymati `36a` qismiga tushadi.

Ishga tushirish:
    python tests/test_parts_authoring.py
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
from handlers.admin_exam import parse_answer_key_input  # noqa: E402
from services import (  # noqa: E402
    answer_key,
    exam_service,
    form_builder,
    form_layout,
    webapp_auth,
)
from web.server import create_app  # noqa: E402

TOKEN = "123456789:AAPartsAuthoringChecks"
ADMIN_ID = 909_000_911
STUDENT = {"id": 909_000_912, "first_name": "Ali", "last_name": "Authoring"}
TOTAL = 45
CODE_PARTS = "AUTH45P"
CODE_LEGACY = "AUTH36L"
CODE_MVP = "AUTH45M"

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


def part_labels() -> list[str]:
    """Belgilar tartibi: 36a, 36b, 37a, … 45b."""
    return [f"{position}{part}" for position in range(36, 46) for part in ("a", "b")]


def labeled_key() -> str:
    """Qismli kalit (admin wizard kiritadigan ko'rinish)."""
    return f"{key_letters()}|" + ",".join(
        f"{label}:{value}" for label, value in part_values().items()
    )


def mvp_key() -> str:
    """Qismsiz MVP kaliti: 35 harf + `|36:36.5,37:37.5,…` (36–45 sonli)."""
    numeric = ",".join(f"{position}:{position}.5" for position in range(36, 46))
    return f"{key_letters()}|{numeric}"


def legacy_key(total: int = 36) -> str:
    """Eski A–D kaliti (`|` blokisiz)."""
    return "".join(f"{p}{'ABCD'[(p - 1) % 4]}" for p in range(1, total + 1))


def build_init_data(user: dict) -> str:
    """Imzolangan `initData` (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-parts-authoring",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, TOKEN)
    return urlencode(payload)


def check_wizard_parsing() -> None:
    """1-qadam: wizard qismli kalitni qabul qiladi va kanonik saqlaydi."""
    stored = parse_answer_key_input(labeled_key(), TOTAL)
    assert form_layout.is_labeled_key(stored), stored
    assert "36a:" in stored and "36b:" in stored, stored[-60:]
    block = answer_key.parse_labeled_block(stored)
    assert list(block) == part_labels(), list(block)
    assert abs(float(block["36a"]) - 2.23606797749979) < 1e-12, block["36a"]
    print("[OK] Wizard: qismli kalit qabul qilindi (36a…45b, 20 qism)")

    mvp_stored = parse_answer_key_input(mvp_key(), TOTAL)
    assert not form_layout.is_labeled_key(mvp_stored), mvp_stored
    assert "|36:36.5,37:37.5" in mvp_stored, mvp_stored[-40:]
    assert mvp_stored.endswith("45:45.5"), mvp_stored[-20:]
    assert "36a" not in mvp_stored, mvp_stored[-30:]
    print("[OK] Wizard: qismsiz MVP kaliti avvalgidek saqlandi (`|36:36.5,…`)")

    legacy_stored = parse_answer_key_input(legacy_key(), 36)
    assert legacy_stored == legacy_key(), legacy_stored
    print("[OK] Wizard: legacy A–D kaliti o'zgarmadi (format_compact)")

    for bad in ("1A2B|36c:5", "1A2B|36a:", "1A2B|"):
        try:
            parse_answer_key_input(bad, TOTAL)
        except answer_key.AnswerKeyError:
            continue
        raise AssertionError(f"AnswerKeyError kutilgan edi: {bad!r}")
    print("[OK] Wizard: buzuq qismli kalitlar → AnswerKeyError")


async def check_labeled_authoring(repos: Repositories, db: Database) -> None:
    """2–4-qadam: qismli forma, `parts_json`, `item_parameters`, Mini App layout."""
    result = await form_builder.create_form(
        repos,
        title="Authoring — qismli 45",
        test_code=CODE_PARTS,
        total_questions=TOTAL,
        answer_key=labeled_key(),
        difficulty_logits=[0.0] * TOTAL,
        created_by=ADMIN_ID,
    )
    assert len(result.questions) == 55, len(result.questions)
    assert result.kinds == {"mcq4": 32, "mcq6": 3, "numeric": 20}, result.kinds
    print("[OK] FormBuilder: 35 variant + 20 qism = 55 spetsifikatsiya")

    form = await repos.forms.get_form(result.form_id)
    assert form is not None
    assert json.loads(str(form["parts_json"])) == part_labels(), form["parts_json"]
    print("[OK] forms.parts_json: 36a…45b (20 ta belgi) yozildi")

    version = await repos.forms.get_version(result.form_version_id)
    assert version is not None
    stored_key = str(version["answer_key"])
    assert "36a:" in stored_key and "36b:" in stored_key, stored_key[-60:]
    print("[OK] form_versions.answer_key: qismli belgilar saqlandi")

    rows = await repos.forms.list_items(result.form_version_id)
    assert len(rows) == 55, len(rows)
    by_label = {
        f"{int(row['position'])}{str(row['part'] or '')}": row for row in rows
    }
    assert set(by_label) == set(part_labels()) | {str(p) for p in range(1, 36)}
    for label in ("36a", "36b"):
        row = by_label[label]
        assert str(row["part"]) == label[-1], row
        assert str(row["display_label"]) == label, row
        assert row["item_version_id"] is not None, row
    assert int(by_label["36a"]["form_item_id"]) != int(by_label["36b"]["form_item_id"])
    print("[OK] form_items: `36a`/`36b` alohida satr (part, display_label, item_version)")

    parameters = await db.fetchall(
        """
        SELECT b_value, source, status FROM item_parameters
        WHERE item_version_id IN (?, ?)
        """,
        (
            int(by_label["36a"]["item_version_id"]),
            int(by_label["36b"]["item_version_id"]),
        ),
    )
    assert len(parameters) == 2, parameters
    assert all(float(row["b_value"]) == 0.0 for row in parameters), parameters
    assert {str(row["source"]) for row in parameters} == {"default"}, parameters
    assert {str(row["status"]) for row in parameters} == {"provisional"}, parameters
    print("[OK] item_parameters: qismlar uchun b=0.0, source='default', status='provisional'")

    refs = {
        str(row["item_ref"])
        for row in await db.fetchall(
            "SELECT item_ref FROM items WHERE item_ref LIKE ?",
            (f"%-{result.form_id}-36%",),
        )
    }
    assert f"{CODE_PARTS}-{result.form_id}-36a" in refs, refs
    assert f"{CODE_PARTS}-{result.form_id}-36b" in refs, refs
    print("[OK] items.item_ref: 36a/36b uchun noyob (qism bilan)")

    await make_session(repos, result.form_id, CODE_PARTS)
    headers = {"X-Init-Data": build_init_data(STUDENT)}
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/v2/attempt/start", json={"test_code": CODE_PARTS}, headers=headers
        )
        assert response.status == 200, (response.status, await response.text())
        started = await response.json()

        numeric_ranges = [rng for rng in started["layout"] if rng["kind"] == "numeric"]
        assert len(numeric_ranges) == 1, numeric_ranges
        numeric_range = numeric_ranges[0]
        assert (int(numeric_range["from"]), int(numeric_range["to"])) == (36, 45), numeric_range
        assert numeric_range["parts"] == ["a", "b"], numeric_range
        assert all("parts" not in rng for rng in started["layout"] if rng["kind"] == "option")
        print(
            "[OK] Mini App layout: 36–45 bo'limi parts=['a','b'] "
            "→ frontend 36a/36b ni alohida katak qiladi"
        )

        attempt_id = int(started["attempt_id"])
        saved = await client.post(
            "/api/v2/autosave",
            json={
                "attempt_id": attempt_id,
                "position": 36,
                "part": "a",
                "value": "2.2361",
                "answer_kind": "numeric",
                "expression": "\u221a5",
                "client_seq": 1,
            },
            headers=headers,
        )
        assert saved.status == 200, (saved.status, await saved.text())
        saved_payload = await saved.json()
        assert saved_payload["label"] == "36a", saved_payload
        assert saved_payload["part"] == "a", saved_payload

        state_response = await client.get(
            f"/api/v2/state?attempt_id={attempt_id}", headers=headers
        )
        assert state_response.status == 200, state_response.status
        payload = await state_response.json()

    by_label = {str(item["label"]): item for item in payload["items"]}
    assert "36a" in by_label, by_label
    assert abs(float(by_label["36a"]["value"]) - 2.23606797749979) < 1e-12, by_label["36a"]
    assert by_label["36a"]["expression"] == "\u221a5", by_label["36a"]
    print("[OK] autosave/state: `36a` alohida javob katagi (label='36a', ifoda saqlandi)")


async def make_session(repos: Repositories, form_id: int, code: str) -> None:
    """Forma uchun vaqt oynasi (sessiya) yaratadi."""
    now = exam_service.utc_now()
    await repos.sessions.create(
        form_id=form_id,
        start_time=exam_service.to_db_time(now - timedelta(minutes=10)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
        result_time=exam_service.to_db_time(now + timedelta(hours=1)),
        title=f"Sessiya {code}",
        created_by=ADMIN_ID,
    )


async def check_legacy_unchanged(repos: Repositories, db: Database) -> None:
    """5-qadam: QISM KAFOLATI — belgilanmagan kalitda ham 36–45 a/b bo'linadi.

    Yangi qoida (`form_layout.parts_of` — yagona manba): test qog'ozida ochiq
    savollar `a)`/`b)` dan iborat, shu sababli forma yaratishda **har doim**
    ikkita savol yaratiladi. Kalitda qiymat bo'lmasa — qism javobsiz
    (`accepted = []`) → baholashda doim "noto'g'ri".
    """
    legacy = await form_builder.create_form(
        repos,
        title="Authoring — legacy 36",
        test_code=CODE_LEGACY,
        total_questions=36,
        answer_key=legacy_key(),
        difficulty_logits=[-0.5] * 36,
        created_by=ADMIN_ID,
    )
    form = await repos.forms.get_form(legacy.form_id)
    assert form is not None
    assert json.loads(str(form["parts_json"])) == ["36a", "36b"], form["parts_json"]
    rows = await repos.forms.list_items(legacy.form_version_id)
    assert len(rows) == 37, len(rows)  # 35 variant + 36a + 36b
    labels = [str(row["display_label"]) for row in rows]
    assert labels == [str(p) for p in range(1, 36)] + ["36a", "36b"], labels
    parameters = await db.fetchall(
        """
        SELECT b_value, source FROM item_parameters
        WHERE item_version_id IN (
            SELECT item_version_id FROM form_items WHERE form_version_id = ?
        )
        """,
        (legacy.form_version_id,),
    )
    assert len(parameters) == 37, len(parameters)
    assert {float(row["b_value"]) for row in parameters} == {-0.5}, parameters[:2]
    assert {str(row["source"]) for row in parameters} == {"legacy_expert"}, parameters[:2]
    print("[OK] Legacy forma: 36 → 36a/36b (37 satr), b=-0.5 (legacy_expert)")

    mvp = await form_builder.create_form(
        repos,
        title="Authoring — MVP 45",
        test_code=CODE_MVP,
        total_questions=TOTAL,
        answer_key=mvp_key(),
        difficulty_logits=[0.0] * TOTAL,
        created_by=ADMIN_ID,
    )
    mvp_form = await repos.forms.get_form(mvp.form_id)
    assert mvp_form is not None
    assert json.loads(str(mvp_form["parts_json"])) == part_labels(), mvp_form["parts_json"]
    mvp_rows = await repos.forms.list_items(mvp.form_version_id)
    assert len(mvp_rows) == 55, len(mvp_rows)  # 35 variant + 20 qism
    assert {
        f"{int(row['position'])}{str(row['part'] or '')}" for row in mvp_rows
    } == set(part_labels()) | {str(p) for p in range(1, 36)}
    # Belgilanmagan kalitdagi `36:36.5` qiymati `36a` qismiga tushadi;
    # `36b` javobsiz → `accepted = []` (baholashda doim noto'g'ri) ✅
    spec_rows = await db.fetchall(
        """
        SELECT fi.display_label AS label, iv.answer_spec AS spec
        FROM form_items fi
        JOIN item_versions iv ON iv.item_version_id = fi.item_version_id
        WHERE fi.form_version_id = ? AND fi.part <> ''
        """,
        (mvp.form_version_id,),
    )
    spec = {str(row["label"]): str(row["spec"]) for row in spec_rows}
    assert "36.5" in spec["36a"], spec["36a"]
    assert json.loads(spec["36b"])["accepted"] == [], spec["36b"]
    print(
        "[OK] MVP (qismsiz) forma: `36:36.5` → `36a`, `36b` javobsiz "
        "(accepted=[]), 55 satr"
    )

    await make_session(repos, mvp.form_id, CODE_MVP)
    headers = {"X-Init-Data": build_init_data(STUDENT)}
    app = create_app(repos)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/v2/attempt/start", json={"test_code": CODE_MVP}, headers=headers
        )
        assert response.status == 200, (response.status, await response.text())
        started = await response.json()
    numeric_ranges = [rng for rng in started["layout"] if rng["kind"] == "numeric"]
    assert len(numeric_ranges) == 1, numeric_ranges
    assert numeric_ranges[0]["parts"] == ["a", "b"], numeric_ranges[0]
    print("[OK] MVP layout: 36–45 bo'limi parts=['a','b'] → 36a/36b alohida katak")


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_parts_authoring_"))
    db = Database(tmp_dir / "parts_authoring.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("Phase 3 Step 6: admin wizard orqali qismli (a/b) forma yaratish")
    print("=" * 72)
    try:
        await repos.users.upsert(
            User(user_id=ADMIN_ID, full_name="Olim Ustoz", username="ustoz")
        )
        await repos.users.upsert(
            User(user_id=STUDENT["id"], full_name="Ali Authoring", username=None)
        )

        check_wizard_parsing()
        await check_labeled_authoring(repos, db)
        await check_legacy_unchanged(repos, db)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Phase 3 Step 6 muvaffaqiyatli o'tdi \u2705")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())