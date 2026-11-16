"""EAP + per-item item bank regressiya testi.

Tekshiriladi:
    1. `data/item_banks/m3rash25.json` — 55 item, 35 algebra + 20 geometriya;
    2. `ScoringContext.from_exam()` per-item `b` bo'lsa **EAP** ni tanlaydi;
    3. `36a` va `36b` **alohida** `b` oladi (pozitsiya `b` sini meros olmaydi);
    4. 55/55 → ≈90.86 (production 90.78 atrofida; EAP, chekli), 0/55 → 9.00,
       48/55 → 91 emas;
    5. 45 pozitsiyali eski `b` — MLE (orqaga moslik);
    6. `build_report()` `total_items=55`, `raw_score` va `scaled_score` to'g'ri.

Ishga tushirish:
    python tests/test_eap_item_bank.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database.models import Exam, ExamSubmission  # noqa: E402
from services import form_layout, grading, item_bank, scoring, subjects  # noqa: E402

BANK_PATH = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "item_banks"
    / "m3rash25.json"
)
TOTAL = 45


def make_key() -> str:
    letters = [
        "ABCD"[(p - 1) % 4] if p <= 32 else "ABCDEF"[(p - 1) % 6]
        for p in range(1, 36)
    ]
    parts = {f"{p}{part}": "1" for p in range(36, 46) for part in ("a", "b")}
    return form_layout.build_canonical(letters, parts)


def make_exam(difficulty_logits: str, *, total: int = TOTAL) -> Exam:
    return Exam(
        exam_id=1,
        title="m3rash25",
        test_code="m3rash25",
        start_time="2026-01-01T00:00:00+00:00",
        end_time="2026-01-01T00:00:00+00:00",
        result_time="2026-01-01T00:00:00+00:00",
        total_questions=total,
        answer_key=make_key() if total == TOTAL else "1A2B3C4D",
        difficulty_logits=difficulty_logits,
    )


def test_bank_structure() -> None:
    bank = item_bank.load_item_bank(BANK_PATH)
    bank.validate_labels(TOTAL)
    assert bank.item_count == 55, bank.item_count
    assert bank.b_by_label["36a"] != bank.b_by_label["36b"]
    assert bank.b_by_label["41b"] == 3.318, bank.b_by_label["41b"]
    print("[OK] Item bank: 55 item, 36a/36b alohida, b saqlangan")


def test_per_item_context_uses_eap() -> None:
    bank = item_bank.load_item_bank(BANK_PATH)
    exam = make_exam(bank.b_json())
    context = scoring.ScoringContext.from_exam(exam)
    assert context.theta_method == "eap", context.theta_method
    assert len(context.b_by_key) == 55, len(context.b_by_key)
    assert context.difficulty_of("36a") == 0.135
    assert context.difficulty_of("36b") == 2.142
    assert context.difficulty_of("45b") == 3.184
    scoring.validate_context(context)
    print("[OK] Per-item b → EAP; 36a/36b/45b alohida b; context valid")


def test_scores() -> None:
    bank = item_bank.load_item_bank(BANK_PATH)
    exam = make_exam(bank.b_json())
    context = scoring.ScoringContext.from_exam(exam)
    letters = [
        "ABCD"[(p - 1) % 4] if p <= 32 else "ABCDEF"[(p - 1) % 6]
        for p in range(1, 36)
    ]
    parts = {f"{p}{part}": "1" for p in range(36, 46) for part in ("a", "b")}

    perfect = scoring.build_item_results(
        context, form_layout.build_canonical(letters, parts)
    )
    perfect_estimate = scoring.estimate_theta(perfect, context)
    assert perfect_estimate.raw_score == 55 and perfect_estimate.total_items == 55
    assert 90.0 <= perfect_estimate.scaled_score <= 91.0, perfect_estimate.scaled_score
    assert perfect_estimate.standard_error is not None
    assert perfect_estimate.is_extreme is True
    print(
        f"[OK] 55/55 → θ={perfect_estimate.theta:.3f}, "
        f"ball={perfect_estimate.scaled_score:.2f} (EAP, chekli)"
    )

    empty = scoring.build_item_results(context, form_layout.build_canonical([], {}))
    empty_estimate = scoring.estimate_theta(empty, context)
    assert empty_estimate.raw_score == 0
    assert 9.0 <= empty_estimate.scaled_score <= 10.0, empty_estimate.scaled_score
    print(f"[OK] 0/55 → {empty_estimate.scaled_score:.2f} (pastki chegara)")

    half_parts = dict(list(parts.items())[:13])
    half = scoring.build_item_results(
        context, form_layout.build_canonical(letters, half_parts)
    )
    half_estimate = scoring.estimate_theta(half, context)
    assert half_estimate.raw_score == 48, half_estimate.raw_score
    assert half_estimate.scaled_score < 90.0, half_estimate.scaled_score
    assert half_estimate.scaled_score > 70.0, half_estimate.scaled_score
    print(
        f"[OK] 48/55 → {half_estimate.scaled_score:.2f} (91 emas; "
        f"θ={half_estimate.theta:.3f})"
    )

    summary = subjects.summarize(
        (result.question_number, result.is_correct) for result in perfect
    )
    assert [(row["code"], row["total"]) for row in summary] == [
        ("algebra", 35),
        ("geometry", 20),
    ], summary
    balls = subjects.allocate_total_ball(90.78, summary)
    assert abs((balls["algebra"] + balls["geometry"]) - 90.8) < 1e-9, balls
    print(f"[OK] Fanlar: algebra 35, geometriya 20; ballar {balls}")


def test_legacy_45_positions_stays_mle() -> None:
    exam = make_exam(json.dumps([0.0] * TOTAL))
    context = scoring.ScoringContext.from_exam(exam)
    assert context.theta_method == "mle", context.theta_method
    assert len(context.b_by_key) == TOTAL, len(context.b_by_key)
    print("[OK] 45 pozitsiyali eski b → MLE (orqaga moslik)")


def test_55_value_array_maps_labels() -> None:
    bank = item_bank.load_item_bank(BANK_PATH)
    labels = item_bank.labels_for(TOTAL)
    values = [bank.b_by_label[label] for label in labels]
    exam = make_exam(json.dumps(values))
    context = scoring.ScoringContext.from_exam(exam)
    assert context.theta_method == "eap"
    assert context.difficulty_of("36a") == 0.135
    assert context.difficulty_of("36b") == 2.142
    print("[OK] 55 qiymatli massiv → label xaritasi (36a/36b alohida)")


def test_report_total_items() -> None:
    bank = item_bank.load_item_bank(BANK_PATH)
    exam = make_exam(bank.b_json())
    submission = ExamSubmission(
        user_id=1,
        exam_id=1,
        submitted_answers=make_key(),
        theta=2.45,
        scaled_score=90.78,
        raw_score=55,
    )
    report = grading.build_report(exam, submission)
    assert report["total_items"] == 55, report["total_items"]
    assert report["total_questions"] == 45
    assert report["raw_score"] == 55
    assert report["scaled_score"] == 90.78
    print("[OK] build_report: total_items=55, raw=55, scaled=90.78")


def main() -> int:
    print("=" * 72)
    print("EAP + item bank regressiya testi")
    print("=" * 72)
    test_bank_structure()
    test_per_item_context_uses_eap()
    test_scores()
    test_legacy_45_positions_stays_mle()
    test_55_value_array_maps_labels()
    test_report_total_items()
    print("=" * 72)
    print("Barcha EAP/item-bank testlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
