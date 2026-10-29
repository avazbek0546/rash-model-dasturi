"""Yakunlashdan keyingi **tezkor tekshiruv** (bot xabari uchun).

Modul javob yuborilgandan keyin darhol ishlaydi va bitta savolga javob beradi:
*qaysi savol to'g'ri, qaysi biri noto'g'ri*. Bu yerda **ataylab** yo'q:

* to'g'ri javob varianti (`correct_answer`) — kalit `result_time` gacha yopiq;
* o'quvchi javobi (`given_answer`) — xabarda takrorlashning hojati yo'q;
* θ (logit) va 0–100 ball — ular faqat baholashda (`grade_exam`) hisoblanadi.

Shu sababli xabar kalitni oshkor qilmaydi: o'quvchi faqat ✅/❌ ko'radi.
Javobsiz (`X` / belgilanmagan) savol ham **❌** bo'ladi — Rasch bo'yicha u 0
ball, ya'ni yakuniy natijaga mos.

Manba va kalit tanlovi **baholash bilan aynan bir xil**
(`grading.resolve_grading_answers`): aks holda hozir ✅ ko'rsatilgan savol
yakuniy hisobda ❌ bo'lib chiqishi mumkin edi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from database.models import Exam, ExamSubmission
from database.repository import Repositories
from services import grading, scoring

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ItemMark:
    """Bitta savolning tezkor belgisi (kalitsiz)."""

    label: str  # savol belgisi: "7", "36a", "36b"
    number: int  # pozitsiya (1 dan boshlab)
    is_correct: bool  # ✅ / ❌


@dataclass(frozen=True, slots=True)
class SubmissionFeedback:
    """Bitta javob varag'i bo'yicha tezkor tekshiruv natijasi."""

    items: tuple[ItemMark, ...]
    correct: int
    total: int

    @property
    def wrong(self) -> int:
        """Xato savollar soni — **javobsizlar ham shu ichida** (`total - correct`)."""
        return self.total - self.correct


async def build_submission_feedback(
    repos: Repositories, exam: Exam, submission: ExamSubmission
) -> SubmissionFeedback:
    """Javob varag'ini kalitsiz tekshiradi (bazaga hech narsa yozmaydi).

    `scoring.build_item_results` dan **faqat** `label` va `is_correct` olinadi:
    to'g'ri javob, o'quvchi javobi, qiyinchilik va ehtimollik tashqariga
    chiqarilmaydi (ma'lumot oqishi yo'q).

    Raises:
        answer_key.AnswerKeyError: kalit yoki javoblar formati buzuq bo'lsa.
            Chaqiruvchi (API) buni ushlab, oddiy qabul xabarini yuboradi.
    """
    answers, context = await grading.resolve_grading_answers(repos, exam, submission)
    results = scoring.build_item_results(context, answers)
    items = tuple(
        ItemMark(
            label=result.label or str(result.question_number),
            number=result.question_number,
            is_correct=result.is_correct,
        )
        for result in results
    )
    return SubmissionFeedback(
        items=items,
        correct=sum(1 for item in items if item.is_correct),
        total=len(items),
    )
