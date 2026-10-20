"""Item statistikasi (p → b) testlari — `services/item_statistics.py`.

Tekshiriladi:
    1. sof funksiya: `calculate_item_difficulty` (p→b, clip, N=0, blank maxrajda);
    2. 55 element: 1..35 + 36a..45b (item_difficulty_stats ga yoziladi);
    3. N = barcha qatnashchilar (bo'shlar ham) — `22/(22+45)` EMAS;
    4. `p = correct/N` va `b = ln((1-p)/p)`;
    5. idempotent qayta hisoblash (regrade);
    6. admin hisobot formati (N=, Correct=, Wrong=, Blank=, p=, b=);
    7. `sessions_needing_stats` (avtomatik hisoblash uchun);
    8. chegara: `b ∈ [B_MIN, B_MAX]` (±4.6), `is_at_limit`, hisobotda `⚠️ chegara`;
    9. shrinkaj: `w = N/(N+K)`, `b = w·b_auto + (1−w)·b_teacher` (K = 30);
    10. hisobotda `b_used` (baholashda ishlatilgan `b`) ham ko'rsatiladi.

Ishga tushirish:
    python tests/test_item_statistics.py
"""

from __future__ import annotations

import asyncio
import json
import math
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database.db import Database  # noqa: E402
from database.models import User  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import exam_service, item_statistics  # noqa: E402

ADMIN_ID = 777_000_501
N = 100
CLIP_MIN = item_statistics.CLIP_MIN
CLIP_MAX = item_statistics.CLIP_MAX


def part_labels() -> list[str]:
    """36a…45b (20 ta qism)."""
    return [f"{position}{part}" for position in range(36, 46) for part in ("a", "b")]


def numeric_spec() -> str:
    """`answer_spec` (sonli savol)."""
    return json.dumps({"kind": "numeric", "accepted": [], "tolerance": 1e-6})


def form_questions() -> list[dict]:
    """1–32 (mcq4) + 33–35 (mcq6) + 36a…45b (numeric) = 55 element."""
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
    for position in range(36, 46):
        for part in ("a", "b"):
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


def answer_key_text() -> str:
    """35 variant + 20 qismli kalit (statistika uchun mazmuni muhim emas)."""
    letters = "".join(
        f"{position}"
        f"{('ABCD' if position <= 32 else 'ABCDEF')[(position - 1) % (4 if position <= 32 else 6)]}"
        for position in range(1, 36)
    )
    block = ",".join(f"{label}:1" for label in part_labels())
    return f"{letters}|{block}"


def build_plan() -> dict[str, tuple[int, int]]:
    """Har bir element uchun (correct, wrong) taqsimoti; qolganlari — blank."""
    plan = {
        label: (50, 25)
        for label in [str(position) for position in range(1, 36)] + part_labels()
    }
    plan["1"] = (100, 0)  # hamma to'g'ri → p=1 → clip 0.99
    plan["2"] = (0, 0)  # hamma bo'sh → p=0 → clip 0.01
    plan["36a"] = (22, 45)  # misol: 22 to'g'ri, 45 noto'g'ri, 33 bo'sh (N=100)
    plan["36b"] = (0, 100)  # hamma noto'g'ri
    return plan


async def make_form_and_session(repos: Repositories) -> tuple[int, int, int]:
    """55 elementli forma + baholangan sessiya; `(form_id, version_id, session_id)`."""
    form_id, version_id = await repos.forms.create_full_form(
        title="Item stat test",
        test_code="ITEMSTAT1",
        total_questions=45,
        answer_key=answer_key_text(),
        questions=form_questions(),
        parts=part_labels(),
        created_by=ADMIN_ID,
    )
    now = exam_service.utc_now()
    session_id = await repos.sessions.create(
        form_id=form_id,
        start_time=exam_service.to_db_time(now - timedelta(hours=2)),
        end_time=exam_service.to_db_time(now - timedelta(hours=1)),
        result_time=exam_service.to_db_time(now),
        title="Item stat sessiya",
        created_by=ADMIN_ID,
    )
    await repos.sessions.set_status(
        session_id, "graded", graded_at=exam_service.now_db()
    )
    return form_id, version_id, session_id


async def add_participant_snapshot(
    repos: Repositories,
    *,
    form_items: dict[str, dict],
    attempt_id: int,
    form_version_id: int,
    session_id: int,
    plan: dict[str, tuple[int, int]],
    index: int,
) -> None:
    """Bitta qatnashchi uchun yakuniy snapshot yozadi (plan: C/W/B bo'yicha)."""
    rows: list[tuple] = []
    for label, form_item in form_items.items():
        correct, wrong = plan[label]
        if index < correct:
            capture, score = "answered", 1.0
        elif index < correct + wrong:
            capture, score = "answered", 0.0
        else:
            capture, score = "blank", 0.0
        rows.append(
            (
                int(form_item["form_item_id"]),
                int(form_item["item_id"]),
                int(form_item["item_version_id"]),
                str(form_item["display_label"]),
                int(form_item["position"]),
                None,
                0.0,
                "default",
                0.0,
                0.25,
                "A",
                1,
                "teacher",
                "option" if str(form_item["part"]) == "" else "numeric",
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
    await repos.snapshots.save(
        attempt_id=attempt_id,
        form_version_id=form_version_id,
        theta=0.0,
        theta_se=0.5,
        log_likelihood=-3.0,
        raw_score=sum(1 for row in rows if row[16] == 1.0),
        total_items=len(rows),
        omitted_count=sum(1 for row in rows if row[20] == "blank"),
        not_reached_count=0,
        scaled_score=50.0,
        scaled_min=0.0,
        scaled_max=100.0,
        theta_bound=3.0,
        engine_version="1.0",
        session_id=session_id,
        computed_by="system",
        is_final=True,
        items=rows,
    )


async def seed_participants(
    repos: Repositories,
    *,
    form_items: dict[str, dict],
    form_version_id: int,
    session_id: int,
    plan: dict[str, tuple[int, int]],
) -> None:
    """N ta qatnashchi uchun urinish + yakuniy snapshot yozadi."""
    now = exam_service.now_db()
    for index in range(N):
        user_id = 900_000 + index
        await repos.users.upsert(
            User(user_id=user_id, full_name=f"O'quvchi {index}", username=None)
        )
        attempt_id = await repos.attempts.get_or_create(
            session_id=session_id,
            user_id=user_id,
            form_version_id=form_version_id,
            started_at=now,
        )
        await add_participant_snapshot(
            repos,
            form_items=form_items,
            attempt_id=attempt_id,
            form_version_id=form_version_id,
            session_id=session_id,
            plan=plan,
            index=index,
        )



def check_pure_function() -> None:
    """Sof funksiya: p→b, clip, N=0 va 'bo'shlar maxrajda' qoidasi."""
    assert item_statistics.calculate_item_difficulty(0, 0) is None

    b = item_statistics.calculate_item_difficulty(22, 100)
    assert b is not None and math.isclose(b, math.log(0.78 / 0.22), rel_tol=1e-12), b
    # Bo'shlar maxrajda: 22/(22+45+33) == 22/100
    b_with_blanks = item_statistics.calculate_item_difficulty(22, 22 + 45 + 33)
    assert b_with_blanks is not None and math.isclose(b_with_blanks, b, rel_tol=1e-12)
    # NOTO'G'RI variant 22/(22+45) — boshqa natija beradi
    assert not math.isclose(b, math.log((1 - 22 / 67) / (22 / 67)), rel_tol=1e-6)

    top = item_statistics.calculate_item_difficulty(100, 100)
    assert top is not None and math.isclose(
        top, math.log((1 - CLIP_MAX) / CLIP_MAX), rel_tol=1e-12
    )
    bottom = item_statistics.calculate_item_difficulty(0, 100)
    assert bottom is not None and math.isclose(
        bottom, math.log((1 - CLIP_MIN) / CLIP_MIN), rel_tol=1e-12
    )

    # --- chegara: b hech qachon ±B_MAX dan oshmaydi ---
    assert item_statistics.B_MIN == -4.6 and item_statistics.B_MAX == 4.6
    assert top is not None and item_statistics.B_MIN <= top <= item_statistics.B_MAX
    assert bottom is not None and item_statistics.B_MIN <= bottom <= item_statistics.B_MAX
    # Chegara belgisi: ekstremal itemlar True, o'rtadagi (36a, 22%) — False
    assert item_statistics.is_at_limit(top) is True
    assert item_statistics.is_at_limit(bottom) is True
    assert item_statistics.is_at_limit(b) is False
    assert item_statistics.is_at_limit(None) is False
    print("[OK] Chegara: b ∈ [-4.6, +4.6], is_at_limit (ekstremal=True, o'rta=False)")
    print("[OK] Sof funksiya: p=correct/N (bo'shlar ham), clip, b=ln((1-p)/p), N=0→None")


def check_blend() -> None:
    """Shrinkaj: `w = N/(N+K)`, `b = w·b_auto + (1−w)·b_teacher` (empirik Bayes)."""
    K = item_statistics.K_SHRINK
    assert K == 30.0, K

    # --- `w = N/(N+K)` asosiy nuqtalari ---
    assert item_statistics.shrinkage_weight(0) == 0.0
    assert math.isclose(item_statistics.shrinkage_weight(30), 0.5, rel_tol=1e-12)
    assert math.isclose(item_statistics.shrinkage_weight(5), 5 / 35, rel_tol=1e-12)
    assert math.isclose(item_statistics.shrinkage_weight(200), 200 / 230, rel_tol=1e-12)
    # `k <= 0` chekkasi
    assert item_statistics.shrinkage_weight(10, 0) == 1.0
    assert item_statistics.shrinkage_weight(0, 0) == 0.0

    b_auto = math.log((1 - 0.40) / 0.40)  # 40% yechilgan → +0.4055
    b_teacher = 0.0

    # N kichik → deyarli o'qituvchiniki
    small = item_statistics.blend_difficulty(b_auto, b_teacher, 5)
    assert small is not None and math.isclose(small, (5 / 35) * b_auto, rel_tol=1e-12)
    # N katta → deyarli ma'lumotniki; tartib: o'qituvchi ≤ aralashma ≤ ma'lumot
    big = item_statistics.blend_difficulty(b_auto, b_teacher, 200)
    assert big is not None and math.isclose(big, (200 / 230) * b_auto, rel_tol=1e-12)
    assert small < big < b_auto
    # N = K → teng vazn
    mid = item_statistics.blend_difficulty(b_auto, b_teacher, 30)
    assert mid is not None and math.isclose(mid, b_auto / 2, rel_tol=1e-12)

    # Chekka holat yumshatiladi: N=10, hech kim yechmadi (b_auto ≈ +4.6), o'qituvchi 0
    extreme_auto = item_statistics.calculate_item_difficulty(0, 10)
    assert extreme_auto is not None and item_statistics.is_at_limit(extreme_auto) is True
    softened = item_statistics.blend_difficulty(extreme_auto, 0.0, 10)
    assert softened is not None and math.isclose(
        softened, 0.25 * extreme_auto, rel_tol=1e-12
    )
    assert softened < extreme_auto

    # O'qituvchi adashsa ham, katta N da ma'lumot yutadi
    wrong_teacher = math.log((1 - 0.90) / 0.90)  # -2.197 (90% deb o'ylagan)
    fixed = item_statistics.blend_difficulty(b_auto, wrong_teacher, 200)
    assert fixed is not None and abs(fixed - b_auto) < abs(wrong_teacher - b_auto)

    # Ikkalasi mos tushsa → natija o'zgarmaydi
    same = item_statistics.blend_difficulty(b_auto, b_auto, 7)
    assert same is not None and math.isclose(same, b_auto, rel_tol=1e-12)

    # `None` holatlari (prior/ma'lumot yo'q)
    assert item_statistics.blend_difficulty(None, None, 10) is None
    assert item_statistics.blend_difficulty(None, 1.5, 0) == 1.5
    assert item_statistics.blend_difficulty(0.7, None, 20) == 0.7

    # `blended_b_map`: `{kalit: (N, W)}` → `{kalit: b_final}` (jamlanma)
    counts = {"1": (50, 20), "2": (10, 0), "3": (0, 0)}
    teachers = {"1": 0.0, "2": 0.0}
    mapped = item_statistics.blended_b_map(counts, teachers.get, 30)
    assert set(mapped) == {"1", "2"}, mapped  # N=0 tushib qoladi
    assert math.isclose(mapped["1"], 0.625 * math.log(1.5), rel_tol=1e-12), mapped
    assert math.isclose(
        mapped["2"],
        0.25 * item_statistics.calculate_item_difficulty(0, 10),
        rel_tol=1e-12,
    ), mapped
    # O'qituvchi bahosi yo'q → faqat ma'lumot (prior yo'q)
    mapped_none = item_statistics.blended_b_map({"1": (50, 20)}, lambda key: None, 30)
    assert math.isclose(mapped_none["1"], math.log(1.5), rel_tol=1e-12), mapped_none

    print(
        "[OK] Shrinkaj: w=N/(N+30); kichik N→o'qituvchi, katta N→ma'lumot, "
        "chekka yumshatiladi"
    )


async def check_pipeline(repos: Repositories) -> None:
    """To'liq oqim: 55 element, N (bo'shlar bilan), yozish, hisobot, idempotentlik."""
    _form_id, version_id, session_id = await make_form_and_session(repos)
    form_items = await repos.forms.items_by_label(version_id)
    assert len(form_items) == 55, len(form_items)

    # Statistika hali yo'q → sessiya "hisoblanishi kerak" ro'yxatida bo'lishi shart
    assert session_id in await repos.item_difficulty.sessions_needing_stats()

    plan = build_plan()
    await seed_participants(
        repos,
        form_items=form_items,
        form_version_id=version_id,
        session_id=session_id,
        plan=plan,
    )

    rows = await item_statistics.build_item_statistics(repos, session_id)
    assert len(rows) == 55, len(rows)
    by_no = {row["item_no"]: row for row in rows}

    # --- 36a: asosiy misol (22 to'g'ri / 45 noto'g'ri / 33 bo'sh, N=100) ---
    item = by_no["36a"]
    assert item["total_participants"] == 100, item
    assert (item["correct_count"], item["wrong_count"], item["blank_count"]) == (
        22,
        45,
        33,
    ), item
    assert item["percent_correct"] == 22.0, item
    expected = math.log((1 - 0.22) / 0.22)
    assert math.isclose(item["b_value"], expected, rel_tol=1e-9), item["b_value"]
    print(
        f"[OK] 36a: N=100, C=22, W=45, B=33, p=22.0%, b={item['b_value']:.3f}"
    )

    # --- clip holatlari ---
    all_correct = by_no["1"]
    assert all_correct["correct_count"] == 100 and all_correct["percent_correct"] == 100.0
    assert math.isclose(
        all_correct["b_value"], math.log((1 - CLIP_MAX) / CLIP_MAX), rel_tol=1e-9
    )
    all_blank = by_no["2"]
    assert all_blank["blank_count"] == 100 and all_blank["correct_count"] == 0
    assert math.isclose(
        all_blank["b_value"], math.log((1 - CLIP_MIN) / CLIP_MIN), rel_tol=1e-9
    )
    print("[OK] clip: p→0.99 (b≈-4.595), p→0.01 (b≈+4.595)")

    # --- tartib: 1..35, keyin 36a..45b ---
    assert rows[0]["item_no"] == "1" and rows[-1]["item_no"] == "45b", (rows[0], rows[-1])
    print("[OK] Tartib: 1..35, 36a..45b (55 element)")

    # --- DB jadval ---
    assert await repos.item_difficulty.count() == 55
    stored = await repos.item_difficulty.list_for_test(session_id)
    assert len(stored) == 55 and stored[0]["item_no"] == "1"

    # --- idempotent qayta hisoblash (regrade) ---
    again = await item_statistics.build_item_statistics(repos, session_id)
    assert len(again) == 55 and await repos.item_difficulty.count() == 55
    print("[OK] Idempotent: qayta hisoblashda 55 qator (dublikat yo'q)")

    # --- statistika yozilgach, sessiya ro'yxatdan chiqadi ---
    assert session_id not in await repos.item_difficulty.sessions_needing_stats()

    # --- admin hisobot formati ---
    report = "\n".join(item_statistics.render_admin_report(rows, title="ITEMSTAT1"))
    for needle in (
        "36a-savol",
        "N=100",
        "Correct=22",
        "Wrong=45",
        "Blank=33",
        "p=22.0%",
        "b=1.266",
    ):
        assert needle in report, (needle, report[:400])
    print("[OK] Hisobot formati: N / Correct / Wrong / Blank / p / b")

    # --- chegara: b chegaralar ichida va hisobotda ⚠️ belgisi ---
    for row in rows:
        if row["b_value"] is not None:
            assert (
                item_statistics.B_MIN <= row["b_value"] <= item_statistics.B_MAX
            ), row
    # hamma to'g'ri (1-savol) → b=-4.595; hech kim (2-savol) → b=+4.595
    assert "-4.595  ⚠️ chegara" in report, report[:400]
    assert "4.595  ⚠️ chegara" in report, report[:400]
    # Baholashda ishlatilgan `b` (snapshot `b_used`, bu testda 0.0) ham ko'rinadi
    assert "b_used=0.000" in report, report[:400]
    block_36a = next(
        block for block in report.split("\n\n") if block.startswith("36a-savol")
    )
    assert "chegara" not in block_36a, block_36a  # 36a (22%) — o'rtada, belgisiz
    print("[OK] Chegara belgisi: ekstremal item ⚠️, o'rta (36a) belgisiz")
    print("-" * 72)
    print(next(block for block in report.split("\n\n") if block.startswith("36a-savol")))
    print("-" * 72)


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_item_stats_"))
    db = Database(tmp_dir / "item_stats_test.db")
    await db.connect()
    repos = Repositories(db)

    await repos.users.upsert(
        User(user_id=ADMIN_ID, full_name="Olim Ustoz", username="ustoz")
    )

    print("=" * 72)
    print("Item statistikasi (p → b) testlari")
    print("=" * 72)
    try:
        check_pure_function()
        check_blend()
        await check_pipeline(repos)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha item statistika tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())

