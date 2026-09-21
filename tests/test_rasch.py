"""Rasch modeli (services/rasch.py) uchun o'z-o'zini tekshirish testlari.

Ishga tushirish:
    python tests/test_rasch.py            # pytest kerak emas
    python -m pytest tests/test_rasch.py  # pytest o'rnatilgan bo'lsa

Testlar sof Python `assert` lar bilan yozilgan, shuning uchun qo'shimcha
kutubxona talab qilmaydi.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows konsoli (cp1251) θ, ▰ kabi belgilarni chiqara olmaydi — UTF-8 ga o'tamiz
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from database.models import Question  # noqa: E402
from services import rasch  # noqa: E402

TOL = 1e-6
WRONG_LETTER = {"A": "B", "B": "A", "C": "A", "D": "A"}


def make_question(question_id: int, difficulty: float, correct: str = "A") -> Question:
    """Test uchun sun'iy savol yaratadi (matni muhim emas)."""
    return Question(
        question_id=question_id,
        question_text=f"Savol #{question_id}",
        option_a="a",
        option_b="b",
        option_c="c",
        option_d="d",
        correct_option=correct,
        difficulty_b=difficulty,
        topic="test",
    )


def make_questions(count: int, start: float = -2.0, step: float = 0.4) -> list[Question]:
    """Turli qiyinchilikdagi savollar to'plamini yaratadi."""
    return [make_question(i, start + step * (i - 1)) for i in range(1, count + 1)]


def answers_for(questions: list[Question], correct_count: int) -> dict[int, str]:
    """Birinchi `correct_count` ta savolga to'g'ri, qolganlariga noto'g'ri javob."""
    answers: dict[int, str] = {}
    for index, question in enumerate(questions):
        if index < correct_count:
            answers[question.question_id] = question.correct_option
        else:
            answers[question.question_id] = WRONG_LETTER[question.correct_option]
    return answers


def responses_for(questions: list[Question], correct_count: int) -> list[rasch.ItemResponse]:
    """`answers_for` natijasini ItemResponse ro'yxatiga aylantiradi."""
    return rasch.build_responses(questions, answers_for(questions, correct_count))


# ---------------------------------------------------------------------------
# 1. Logistik funksiya xossalari
# ---------------------------------------------------------------------------
def test_probability_properties() -> None:
    # θ = b bo'lganda to'g'ri javob ehtimoli aynan 0.5
    assert abs(rasch.probability(0.0, 0.0) - 0.5) < TOL
    assert abs(rasch.probability(1.7, 1.7) - 0.5) < TOL

    # Simmetriya: P(b + d) = 1 - P(b - d)
    for delta in (0.5, 1.0, 2.7, 5.0):
        high = rasch.probability(delta, 0.0)
        low = rasch.probability(-delta, 0.0)
        assert abs(high + low - 1.0) < TOL, f"delta={delta}"

    # Monotonlik: θ oshsa ehtimol ham oshadi
    values = [rasch.probability(t, 0.3) for t in (-3, -1, 0, 1, 3)]
    assert values == sorted(values)
    print("[OK] Logistik funksiya: P(b) = 0.5, simmetriya, monotonlik")


# ---------------------------------------------------------------------------
# 2. MLE: analitik ma'lum yechim (barcha savollar b = 0, 5/10 to'g'ri)
# ---------------------------------------------------------------------------
def test_mle_known_solution() -> None:
    questions = [make_question(i, 0.0) for i in range(1, 11)]
    estimate = rasch.evaluate(questions, answers_for(questions, 5))

    assert abs(estimate.theta) < 1e-4, f"θ = {estimate.theta}"
    assert estimate.standard_error is not None
    # SE = 1 / sqrt(n · 0.25) = 1 / sqrt(2.5)
    assert abs(estimate.standard_error - 1.0 / math.sqrt(2.5)) < 1e-4
    assert estimate.raw_score == 5 and estimate.total_items == 10
    assert estimate.converged and not estimate.is_extreme
    print(f"[OK] MLE analitik yechim: θ = {estimate.theta:.6f}, SE = {estimate.standard_error:.4f}")


# ---------------------------------------------------------------------------
# 3. MLE sharti: topilgan θ da log-likelihood gradienti ≈ 0
# ---------------------------------------------------------------------------
def test_gradient_is_zero_at_mle() -> None:
    questions = make_questions(12, start=-1.0, step=0.35)
    checked = 0
    for correct_count in range(1, len(questions)):
        estimate = rasch.evaluate(questions, answers_for(questions, correct_count))
        # θ qidiruv chegarasiga urilgan bo'lsa (11/12, 1/12 kabi deyarli chekka
        # holatlar) gradient nolga aylanmaydi — bunday holatlar tekshirilmaydi.
        if abs(estimate.theta) >= config.THETA_BOUND - 1e-9:
            assert estimate.is_extreme is True, "chegaraviy baho belgilanmagan"
            continue
        slope = rasch.gradient(estimate.theta, responses_for(questions, correct_count))
        assert abs(slope) < 1e-4, f"gradient = {slope} (u = {correct_count})"
        assert estimate.is_extreme is False
        checked += 1
    assert checked >= 6, f"juda kam ichki holat tekshirildi: {checked}"
    print(f"[OK] MLE sharti: gradient(θ_MLE) ≈ 0 ({checked} ta xom ball uchun)")


# ---------------------------------------------------------------------------
# 4a. Xom ball yetarli statistika: bir xil to'plamda bir xil xom ball = bir xil θ
# ---------------------------------------------------------------------------
def test_raw_score_is_sufficient_statistic() -> None:
    questions = make_questions(10)
    correct = {q.question_id: q.correct_option for q in questions}
    wrong = {q.question_id: WRONG_LETTER[q.correct_option] for q in questions}

    # Bir xil 5/10 natija beradigan uch xil javob "naqshi"
    pattern_a = {**{q.question_id: correct[q.question_id] for q in questions[:5]},
                 **{q.question_id: wrong[q.question_id] for q in questions[5:]}}
    pattern_b = {**{q.question_id: wrong[q.question_id] for q in questions[:5]},
                 **{q.question_id: correct[q.question_id] for q in questions[5:]}}
    pattern_c = {
        q.question_id: (correct[q.question_id] if index % 2 == 0 else wrong[q.question_id])
        for index, q in enumerate(questions)
    }

    thetas = [
        round(rasch.evaluate(questions, pattern).theta, 6)
        for pattern in (pattern_a, pattern_b, pattern_c)
    ]
    assert len(set(thetas)) == 1, thetas
    print(f"[OK] Yetarli statistika: bir xil 5/10 → bir xil θ = {thetas[0]:+.3f} (naqsh muhim emas)")


# ---------------------------------------------------------------------------
# 4b. Savollar qiyinligi: bir xil xom ball, turli to'plam → turli θ
# ---------------------------------------------------------------------------
def test_same_raw_score_on_easy_and_hard_tests() -> None:
    easy_set = make_questions(10, start=-2.5, step=0.2)  # b: -2.5 ... -0.7
    hard_set = make_questions(10, start=0.5, step=0.2)  # b: +0.5 ... +2.3

    easy_theta = rasch.evaluate(easy_set, answers_for(easy_set, 5)).theta
    hard_theta = rasch.evaluate(hard_set, answers_for(hard_set, 5)).theta

    assert hard_theta > easy_theta + 1.0, (easy_theta, hard_theta)
    print(
        f"[OK] Bir xil 5/10 natija: oson to'plamda θ = {easy_theta:+.2f}, "
        f"qiyin to'plamda θ = {hard_theta:+.2f}"
    )


# ---------------------------------------------------------------------------
# 4c. Monotonlik: xom ball oshsa θ ham oshadi
# ---------------------------------------------------------------------------
def test_monotonic_in_raw_score() -> None:
    questions = make_questions(10)
    thetas = [
        rasch.evaluate(questions, answers_for(questions, count)).theta
        for count in range(1, 10)
    ]
    assert thetas == sorted(thetas), thetas
    print("[OK] Monotonlik: xom ball oshgani sari θ ham oshadi")


# ---------------------------------------------------------------------------
# 5. Chekka holatlar (barchasi to'g'ri / barchasi noto'g'ri)
# ---------------------------------------------------------------------------
def test_extreme_cases() -> None:
    questions = make_questions(10)

    best = rasch.evaluate(questions, answers_for(questions, len(questions)))
    assert best.is_extreme and best.standard_error is None
    assert abs(best.theta - config.THETA_BOUND) < TOL
    assert abs(best.scaled_score - 100.0) < TOL

    worst = rasch.evaluate(questions, answers_for(questions, 0))
    assert worst.is_extreme and worst.standard_error is None
    assert abs(worst.theta + config.THETA_BOUND) < TOL
    assert abs(worst.scaled_score - 0.0) < TOL

    # Javob berilmagan savollar ham noto'g'ri (u = 0) hisoblanadi
    blank = rasch.evaluate(questions, {})
    assert blank.raw_score == 0
    assert rasch.build_responses(questions, {})[0].skipped is True
    print("[OK] Chekka holatlar: 0/10 → θ = -3.0, 10/10 → θ = +3.0 (SE yo'q)")


# ---------------------------------------------------------------------------
# 6. θ → 0..100 shkala
# ---------------------------------------------------------------------------
def test_scaled_score_mapping() -> None:
    assert abs(rasch.theta_to_scaled(0.0) - 50.0) < TOL
    assert abs(rasch.theta_to_scaled(-config.THETA_BOUND) - 0.0) < TOL
    assert abs(rasch.theta_to_scaled(config.THETA_BOUND) - 100.0) < TOL
    assert abs(rasch.theta_to_scaled(-1.5) - 25.0) < TOL
    assert abs(rasch.theta_to_scaled(1.5) - 75.0) < TOL

    # Chegaradan tashqaridagi θ qiymatlari 0..100 ga siqiladi
    assert rasch.theta_to_scaled(-9.9) == 0.0
    assert rasch.theta_to_scaled(9.9) == 100.0

    # Teskari o'tkazish ham to'g'ri ishlaydi
    for theta in (-2.5, -1.0, 0.0, 1.0, 2.5):
        assert abs(rasch.scaled_to_theta(rasch.theta_to_scaled(theta)) - theta) < 1e-9
    print("[OK] Scaled score: θ = -3 → 0, θ = 0 → 50, θ = +3 → 100")


# ---------------------------------------------------------------------------
# 7. Izoh yordamchilari
# ---------------------------------------------------------------------------
def test_labels() -> None:
    assert rasch.difficulty_label(-2.0) == "juda oson"
    assert rasch.difficulty_label(0.0) == "o'rtacha"
    assert rasch.difficulty_label(2.0) == "juda qiyin"
    assert rasch.ability_level(30.0) == "boshlang'ich daraja"
    assert rasch.ability_level(90.0) == "yuqori daraja"
    print("[OK] Izoh yordamchilari (qiyinchilik va daraja yorliqlari)")


# ---------------------------------------------------------------------------
# 8. Test sessiyasi: javoblar oqimi va takroriy tugmalar
# ---------------------------------------------------------------------------
def test_session_flow() -> None:
    from services.test_session import TestSessionStore

    store = TestSessionStore()
    questions = make_questions(3)
    session = store.start(1, questions)

    assert session.current_question is not None
    first = session.current_question
    assert session.register_answer(first.question_id, "A") is True
    # Eskirgan/takroriy tugma bosilishi rad etiladi
    assert session.register_answer(first.question_id, "B") is False

    while not session.is_finished:
        assert session.register_answer(session.current_question.question_id, "A") is True

    assert session.answered_count == 3
    assert session.correct_count == 3  # barcha sun'iy savollarda to'g'ri javob "A"
    assert store.is_active(1) is False
    assert store.pop(1) is session
    assert store.get(1) is None
    print("[OK] Test sessiyasi: javoblar oqimi va takroriy tugmalar nazorati")


def main() -> int:
    tests = [
        test_probability_properties,
        test_mle_known_solution,
        test_gradient_is_zero_at_mle,
        test_monotonic_in_raw_score,
        test_raw_score_is_sufficient_statistic,
        test_same_raw_score_on_easy_and_hard_tests,
        test_extreme_cases,
        test_scaled_score_mapping,
        test_labels,
        test_session_flow,
    ]
    print("=" * 72)
    print("Rasch modeli — o'z-o'zini tekshirish testlari")
    print("=" * 72)
    for test in tests:
        test()
    print("=" * 72)
    print(f"Barcha {len(tests)} ta test muvaffaqiyatli o'tdi ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())