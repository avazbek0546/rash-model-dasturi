"""Standart `p → b` qiyinchilik xaritasi testi.

Tekshiriladi:
    1. `services/default_difficulty.py` — 55 item, `b = ln((1-p)/p)`;
    2. `exam_service.b_by_key()`:
       * `difficulty_logits` bo'sh → standart xarita (EAP);
       * aniq 55 qiymatli massiv → o'sha qiymatlar (EAP);
       * eski 45 pozitsiyali massiv → o'sha qiymatlar (MLE, orqaga moslik);
    3. 24/55 natijasi standart xarita bilan **C+** (≈51 ball);
    4. 36a/36b alohida `b` oladi.

Ishga tushirish:
    python tests/test_default_difficulty.py
"""

from __future__ import annotations

import asyncio
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database.db import Database  # noqa: E402
from database.models import Exam, User  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import (  # noqa: E402
    default_difficulty,
    exam_service,
    form_layout,
    grading,
    rasch,
    scoring,
)

TOTAL = 45


def make_exam(difficulty_logits: str, *, total: int = TOTAL) -> Exam:
    """Test uchun minimal `Exam` yozuvi."""
    return Exam(
        exam_id=1,
        title="default-p-test",
        test_code="DEFP1",
        start_time="2026-01-01T00:00:00+00:00",
        end_time="2026-01-01T00:00:00+00:00",
        result_time="2026-01-01T00:00:00+00:00",
        total_questions=total,
        answer_key="1A2B",
        difficulty_logits=difficulty_logits,
    )


def make_55_key() -> str:
    """35 variant + 20 qism (36a..45b) kaliti."""
    letters = ["A"] * 35
    parts = {f"{p}{part}": "1" for p in range(36, 46) for part in ("a", "b")}
    return form_layout.build_canonical(letters, parts)


def test_default_map() -> None:
    """Xarita 55 item, formula to'g'ri, 36a/36b alohida."""
    assert len(default_difficulty.DEFAULT_PERCENT_BY_LABEL) == 55
    assert len(default_difficulty.DEFAULT_B_BY_LABEL) == 55
    assert math.isclose(
        default_difficulty.percent_to_b(70), -0.8472978603872034, rel_tol=1e-12
    )
    assert default_difficulty.percent_to_b(50) == 0.0
    assert math.isclose(
        default_difficulty.percent_to_b(4), 3.1780538303479453, rel_tol=1e-12
    )
    by_key = default_difficulty.default_b_by_key()
    assert "36a" in by_key and "36b" in by_key and "36" in by_key
    assert by_key["36a"] != by_key["36b"]
    print("[OK] default xarita: 55 item, b=ln((1-p)/p), 36a/36b alohida")


def test_blank_exam_uses_default() -> None:
    """`difficulty_logits` bo'sh → standart xarita va EAP."""
    exam = make_exam("")
    mapping = exam_service.b_by_key(exam)
    expected = default_difficulty.default_b_by_key()
    assert math.isclose(mapping["1"], expected["1"], abs_tol=1e-6)
    assert math.isclose(mapping["36a"], expected["36a"], abs_tol=1e-6)
    context = scoring.ScoringContext.from_exam(exam)
    assert context.theta_method == "eap", context.theta_method
    print("[OK] bo'sh `b` → standart xarita; θ usuli EAP")


def test_explicit_55_array_wins() -> None:
    """Aniq 55 qiymatli massiv standart xaritadan ustun."""
    labels = exam_service.item_labels(TOTAL)
    values = [0.5] * len(labels)
    exam = make_exam(json.dumps(values))
    mapping = exam_service.b_by_key(exam)
    assert len(mapping) >= 55
    assert mapping["1"] == 0.5 and mapping["36a"] == 0.5
    context = scoring.ScoringContext.from_exam(exam)
    assert context.theta_method == "eap", context.theta_method
    print("[OK] aniq 55 qiymatli massiv → o'sha `b` qiymatlari (EAP)")


def test_legacy_45_array_preserved() -> None:
    """Eski 45 pozitsiyali massiv o'zgarmaydi (MLE)."""
    values = [0.25] * TOTAL
    exam = make_exam(json.dumps(values))
    mapping = exam_service.b_by_key(exam)
    assert mapping["1"] == 0.25 and mapping["45"] == 0.25
    context = scoring.ScoringContext.from_exam(exam)
    assert context.theta_method == "mle", context.theta_method
    print("[OK] eski 45 pozitsiyali massiv → o'zgarmagan (MLE)")


def test_has_per_item_difficulty() -> None:
    """Per-item va legacy `b` farqlanadi."""
    legacy = make_exam(json.dumps([0.0] * TOTAL))
    assert grading.has_per_item_difficulty(legacy) is False
    per_item = make_exam(json.dumps({"1": 0.5, "36a": 0.5, "36b": 0.5}))
    assert grading.has_per_item_difficulty(per_item) is True
    labels = exam_service.item_labels(TOTAL)
    array_55 = make_exam(json.dumps([0.5] * len(labels)))
    assert grading.has_per_item_difficulty(array_55) is True
    blank = make_exam("")
    assert grading.has_per_item_difficulty(blank) is False
    print("[OK] has_per_item_difficulty: legacy/bo'sh → False; 55 item → True")


async def test_regrade_applies_default() -> None:
    """Legacy imtihonni regrade standart `p → b` bilan yangilaydi."""
    tmp_dir = tempfile.mkdtemp(prefix="rash-default-")
    db = Database(Path(tmp_dir) / "default.db")
    await db.connect()
    try:
        repos = Repositories(db)
        await repos.users.upsert(
            User(user_id=1, full_name="Test User", username=None)
        )
        exam_id = await repos.exams.create(
            title="Legacy exam",
            test_code="LEGACY1",
            start_time="2026-01-01T00:00:00+00:00",
            end_time="2026-01-01T01:00:00+00:00",
            result_time="2026-01-01T02:00:00+00:00",
            total_questions=TOTAL,
            answer_key=make_55_key(),
            difficulty_logits=json.dumps([0.0] * TOTAL),
            created_by=1,
        )
        await repos.answers.submit(
            user_id=1,
            exam_id=exam_id,
            submitted_answers=form_layout.build_canonical(
                ["A"] * 24 + ["B"] * 11, {}
            ),
        )
        exam = await repos.exams.get(exam_id)
        assert exam is not None
        assert grading.has_per_item_difficulty(exam) is False

        graded, applied = await grading.regrade_with_default_difficulty(repos, exam)
        assert applied is True, "standart xarita qo'llanmadi"
        assert graded == 1, graded

        refreshed = await repos.exams.get(exam_id)
        assert refreshed is not None
        assert grading.has_per_item_difficulty(refreshed) is True
        assert "36a" in str(refreshed.difficulty_logits)

        submission = await repos.answers.get(1, exam_id)
        assert submission is not None
        assert submission.raw_score == 24, submission.raw_score
        assert submission.scaled_score is not None
        assert submission.scaled_score > 46.0, submission.scaled_score
        assert (
            rasch.ability_level(float(submission.scaled_score)) == "C+"
        ), submission.scaled_score

        # Ikkinchi chaqiruvda per-item `b` ustidan yozilmaydi.
        graded2, applied2 = await grading.regrade_with_default_difficulty(
            repos, refreshed
        )
        assert applied2 is False, "per-item b ustidan yozildi"
        assert graded2 == 1, graded2
        print(
            f"[OK] regrade standart p→b: applied={applied}, "
            f"24/55 → {submission.scaled_score:.2f} "
            f"({rasch.ability_level(float(submission.scaled_score))})"
        )
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_24_of_55_is_c_plus() -> None:
    """Standart xarita bilan 24/55 ≈ 51 ball (C+)."""
    exam = make_exam("", total=TOTAL)
    exam.answer_key = make_55_key()
    context = scoring.ScoringContext.from_exam(exam)
    submission = form_layout.build_canonical(["A"] * 24 + ["B"] * 11, {})
    results = scoring.build_item_results(context, submission)
    estimate = scoring.estimate_theta(results, context)
    assert estimate.raw_score == 24, estimate.raw_score
    assert estimate.total_items == 55, estimate.total_items
    assert estimate.scaled_score > 46.0, estimate.scaled_score
    assert rasch.ability_level(estimate.scaled_score) == "C+", estimate.scaled_score
    print(
        f"[OK] 24/55 → θ={estimate.theta:.4f}, ball={estimate.scaled_score:.2f} "
        f"({rasch.ability_level(estimate.scaled_score)})"
    )


def main() -> None:
    print("=" * 72)
    print("Standart `p → b` xaritasi testi")
    print("=" * 72)
    test_default_map()
    test_blank_exam_uses_default()
    test_explicit_55_array_wins()
    test_legacy_45_array_preserved()
    test_has_per_item_difficulty()
    test_24_of_55_is_c_plus()
    asyncio.run(test_regrade_applies_default())
    print("=" * 72)
    print("Barcha standart `p → b` tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    main()
