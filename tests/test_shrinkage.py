"""Shrinkaj integratsiyasi: `grading._apply_shrinkage`.

Bu test **DB'siz** ishlaydi: `session`/`form_version_id` berilmagani uchun
`_resolve_answers` legacy yo'lni tanlaydi va `repos` ga murojaat qilmaydi.

Tekshiriladi:
    1. Har bir savol uchun `N` va `W` barcha urinishlardan to'g'ri sanaladi;
    2. Yakuniy `b = w·b_auto + (1−w)·b_teacher`, `w = N/(N+K)`, `K = 30`;
    3. O'qituvchi bahosi kichik `N` da ustunlik qiladi (prior);
    4. Asl kontekst **o'zgarmaydi** (immutable) — yangi kontekst qaytadi.

Ishga tushirish:
    python tests/test_shrinkage.py
"""

from __future__ import annotations

import asyncio
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import grading, item_statistics, scoring  # noqa: E402

TOTAL = 4
KEY = "1A2B3C4D"
# Kalit: 1A, 2B, 3C, 4D. To'g'ri sonlar: savol1→3, savol2→2, savol3→1, savol4→0.
SUBMISSIONS = ["1A2B3C4X", "1A2B3X4X", "1A2X3X4X", "1X2X3X4X"]


@dataclass(slots=True)
class _Submission:
    """`ExamSubmission` o'rnini bosuvchi minimal obyekt (faqat `user_id`, javoblar)."""

    user_id: int
    submitted_answers: str


@dataclass(slots=True)
class _Exam:
    """`Exam` o'rnini bosuvchi minimal obyekt (faqat `exam_id`, savollar soni)."""

    exam_id: int
    total_questions: int


def _context(teacher_b: dict[str, float] | None = None) -> scoring.ScoringContext:
    """Legacy kontekst: kalit A–D, `b_by_key` o'qituvchi qiymatlaridan."""
    base = {str(position): 0.0 for position in range(1, TOTAL + 1)}
    if teacher_b:
        base.update(teacher_b)
    return scoring.ScoringContext(
        exam_id=1,
        total_questions=TOTAL,
        answer_key=KEY,
        b_by_key=base,
        mode=scoring.ScoringMode.LETTERS,
    )


def _submissions() -> list[_Submission]:
    return [
        _Submission(user_id=index + 1, submitted_answers=text)
        for index, text in enumerate(SUBMISSIONS)
    ]


async def check_apply_shrinkage() -> None:
    """`b` o'qituvchi (0.0) va javob ma'lumoti o'rtasida to'g'ri aralashadi."""
    context = _context()
    new_context, new_item_level = await grading._apply_shrinkage(
        None,  # type: ignore[arg-type]  (session yo'q — repos ishlatilmaydi)
        _Exam(exam_id=1, total_questions=TOTAL),
        _submissions(),
        context,
        None,
        session=None,
        form_version_id=None,
    )
    assert new_item_level is None

    w = 4 / (4 + item_statistics.K_SHRINK)  # N=4, K=30 → 4/34
    expected = {
        "1": w * math.log((1 - 0.75) / 0.75),  # W=3 → p=0.75
        "2": w * math.log((1 - 0.50) / 0.50),  # W=2 → p=0.50
        "3": w * math.log((1 - 0.25) / 0.25),  # W=1 → p=0.25
        "4": w * item_statistics.calculate_item_difficulty(0, 4),  # W=0 → chegara
    }
    for key, value in expected.items():
        assert math.isclose(new_context.b_by_key[key], value, rel_tol=1e-9), (
            key,
            new_context.b_by_key[key],
            value,
        )
    # O'qituvchi b=0 → oson savol manfiy, qiyin savol musbat tomonga suriladi
    assert new_context.b_by_key["4"] > 0.0 > new_context.b_by_key["1"]
    # Asl kontekst o'zgarmaydi (immutable)
    assert context.b_by_key["1"] == 0.0 and context.b_by_key["4"] == 0.0
    print("[OK] _apply_shrinkage: N=4 da b = w·b_auto + (1−w)·b_teacher (o'qituvchi 0)")


async def check_teacher_prior_dominates() -> None:
    """Kichik `N` da natija o'qituvchi bahosiga yaqin (prior ustun)."""
    teacher_b = {"4": 3.0}  # o'qituvchi: 4-savol juda qiyin
    new_context, _ = await grading._apply_shrinkage(
        None,  # type: ignore[arg-type]
        _Exam(exam_id=1, total_questions=TOTAL),
        _submissions(),
        _context(teacher_b),
        None,
        session=None,
        form_version_id=None,
    )
    value = new_context.b_by_key["4"]
    auto = item_statistics.calculate_item_difficulty(0, 4)  # ≈ +4.595
    # Aralashma o'qituvchi qiymatiga (3.0) ma'lumotnikidan (4.595) yaqinroq
    assert abs(value - 3.0) < abs(value - auto), (value, auto)
    print("[OK] Kichik N: natija o'qituvchi bahosiga yaqin (prior ustun)")


async def main() -> None:
    print("=" * 72)
    print("Shrinkaj integratsiyasi testi (grading._apply_shrinkage)")
    print("=" * 72)
    await check_apply_shrinkage()
    await check_teacher_prior_dominates()
    print("=" * 72)
    print("Barcha shrinkaj tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
