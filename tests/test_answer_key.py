"""Javoblar kaliti (`services/answer_key.py`) va Rasch kengaytmasi testlari.

Tekshiriladi:
    1. kalit va javoblarning barcha qo'llab-quvvatlanadigan formatlari;
    2. noto'g'ri kiritishlarning rad etilishi (xato matnlari bilan);
    3. `rasch.estimate_from_letters()` natijasi eski (Question obyektlari) yo'li
       bilan aynan bir xil bo'lishi;
    4. Newton-Raphson yechimining mustaqil to'r (brute-force) qidiruvi bilan
       mos kelishi.

Ishga tushirish:
    python tests/test_answer_key.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from database.models import SKIPPED, Question  # noqa: E402
from services import answer_key, rasch  # noqa: E402


def check_parsing() -> None:
    """Kalit/javob formatlarini tekshiradi."""
    assert answer_key.parse_answer_key("1A2B3C4D", 4) == ["A", "B", "C", "D"]
    assert answer_key.parse_answer_key("1A 2B 3C", 3) == ["A", "B", "C"]
    assert answer_key.parse_answer_key("1:A, 2:B; 3:C", 3) == ["A", "B", "C"]
    assert answer_key.parse_answer_key("ABCD", 4) == ["A", "B", "C", "D"]
    assert answer_key.parse_answer_key("abcd", 4) == ["A", "B", "C", "D"]
    assert answer_key.parse_answer_key("3C1A2B", 3) == ["A", "B", "C"], "tartib tuzatilmadi"
    print("[OK] Kalit formatlari: 1A2B3C / bo'sh joy / ajratuvchi / ABCD / kichik harf")

    partial = answer_key.parse_submitted("10D1A", 10)
    assert partial[0] == "A" and partial[9] == "D", partial
    assert partial[1:9] == [SKIPPED] * 8
    assert answer_key.parse_submitted("1A2B", 4) == ["A", "B", SKIPPED, SKIPPED]
    assert answer_key.parse_submitted("", 3) == [SKIPPED] * 3
    assert answer_key.parse_submitted("1A2E3C", 3) == ["A", SKIPPED, "C"], "noto'g'ri harf → X"
    print("[OK] O'quvchi javoblari: raqam bo'yicha joylashdi, yetishmaganlari X bo'ldi")

    for text, total, title in (
        ("1A2B", 3, "kalit to'liq emas"),
        ("1A2B3E", 3, "ruxsat etilmagan harf"),
        ("1A2B3C", -1, "savollar soni noto'g'ri"),
        ("", 3, "bo'sh kalit"),
        ("1A1B2C", 3, "takroriy raqam"),
        ("1A2B4D", 3, "oraliqdan tashqaridagi raqam"),
    ):
        try:
            answer_key.parse_answer_key(text, total)
        except answer_key.AnswerKeyError as exc:
            print(f"[OK] Rad etildi ({title}): {exc}")
        else:  # pragma: no cover
            raise AssertionError(f"{title}: xato kutilgan edi — {text!r}")

    assert answer_key.compare(["A", "B"], ["A", "C"]) == [True, False]
    assert answer_key.score(["A", "B", "C"], ["A", "X", "C"]) == 2
    assert answer_key.format_compact(["A", "B", "C"]) == "1A2B3C"
    assert answer_key.format_compact(["A", "B"], with_numbers=False) == "AB"
    print("[OK] compare / score / format_compact ishlaydi")


def check_rasch_letters() -> None:
    """`estimate_from_letters` va eski yo'l natijalarini solishtiradi."""
    difficulties = [0.0, 0.0, 0.0, 0.0]
    key = ["A", "B", "C", "D"]

    all_right = rasch.estimate_from_letters(difficulties, key, key)
    assert all_right.is_extreme and all_right.theta == config.THETA_BOUND
    assert abs(all_right.scaled_score - 100.0) < 1e-9

    all_wrong = rasch.estimate_from_letters(difficulties, key, ["X"] * 4)
    assert all_wrong.is_extreme and all_wrong.theta == -config.THETA_BOUND
    assert abs(all_wrong.scaled_score) < 1e-9

    half = rasch.estimate_from_letters(difficulties, key, ["A", "B", "X", "X"])
    assert half.raw_score == 2 and abs(half.theta) < 1e-6
    assert abs(half.scaled_score - 50.0) < 1e-6
    print(
        f"[OK] Logitlar asosida baho: 0/4 → θ={all_wrong.theta:+.2f}, "
        f"2/4 → θ={half.theta:+.2f}, 4/4 → θ={all_right.theta:+.2f}"
    )

    questions = [
        Question(
            question_id=index + 1,
            question_text=f"S{index + 1}",
            option_a="a",
            option_b="b",
            option_c="c",
            option_d="d",
            correct_option=key[index],
            difficulty_b=difficulties[index],
        )
        for index in range(4)
    ]
    legacy = rasch.evaluate(questions, {1: "A", 2: "B", 3: "D", 4: "D"})
    modern = rasch.estimate_from_letters(difficulties, key, ["A", "B", "D", "D"])
    assert legacy.theta == modern.theta, (legacy.theta, modern.theta)
    assert legacy.standard_error == modern.standard_error
    assert legacy.scaled_score == modern.scaled_score
    print(f"[OK] Eski va yangi yo'l bir xil natija: θ = {modern.theta:+.4f}")

    try:
        rasch.estimate_from_letters([0.0, 1.0], ["A", "B"], ["A"])
    except ValueError as exc:
        print(f"[OK] Uzunlik mos kelmasa xatolik: {exc}")
    else:  # pragma: no cover
        raise AssertionError("ValueError kutilgan edi")


def check_against_grid() -> None:
    """Newton-Raphson natijasini to'r (brute-force) qidiruvi bilan solishtiradi."""
    difficulties = [-1.5, -0.4, 0.3, 1.1, 2.0, 0.0, -0.9, 1.4]
    key = list("ABCDABCD")
    given = list("ABXDABXX")

    estimate = rasch.estimate_from_letters(difficulties, key, given)
    responses = rasch.responses_from_letters(difficulties, key, given)

    best_theta, best_ll = 0.0, float("-inf")
    steps = 60001
    for index in range(steps):
        theta = -config.THETA_BOUND + 2 * config.THETA_BOUND * index / (steps - 1)
        value = rasch.log_likelihood(theta, responses)
        if value > best_ll:
            best_theta, best_ll = theta, value

    assert abs(estimate.theta - best_theta) < 0.01, (estimate.theta, best_theta)
    print(
        f"[OK] Mustaqil tekshiruv: Newton-Raphson θ = {estimate.theta:+.4f} ≈ "
        f"to'r bo'yicha θ = {best_theta:+.4f} "
        f"(SE = {estimate.standard_error:.3f}, 0–100 ball = {estimate.scaled_score:.1f})"
    )


def main() -> None:
    """Testlarni ketma-ket ishga tushiradi."""
    print("=" * 72)
    print("Javoblar kaliti va Rasch kengaytmasi testlari")
    print("=" * 72)
    check_parsing()
    check_rasch_letters()
    check_against_grid()
    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    main()
