"""Imtihon javoblarini Rasch modeli bo'yicha baholash.

Oqim
----
1. O'quvchi Web App orqali javob yuboradi (`user_answers.submitted_answers`),
   θ hali hisoblanmaydi (`theta = NULL`) — muddatdan oldin natija oshkor
   bo'lmasligi uchun.
2. `end_time` kelgach javob qabul qilish to'xtaydi va fon vazifasi
   (`grading_loop`) imtihonni baholaydi: har bir javob uchun θ (MLE),
   standart xato va 0–100 shkala hisoblanib bazaga yoziladi.
3. Natijalar faqat `result_time` kelgach ko'rsatiladi (`exam_service`).

Fon vazifasidan tashqari "lazy" zaxira ham bor: natija so'ralganda imtihon
hali baholanmagan bo'lsa, o'sha zahoti baholanadi (`ensure_graded`).
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import config
from database.models import SKIPPED, Exam, ExamSubmission
from database.repository import Repositories
from services import answer_key, exam_service, rasch

logger = logging.getLogger(__name__)


def build_estimate(exam: Exam, submitted_answers: str) -> rasch.RaschEstimate:
    """Bitta o'quvchi javobini Rasch modeli bo'yicha baholaydi."""
    difficulties = exam_service.effective_difficulties(exam)
    correct_letters = answer_key.parse_answer_key(exam.answer_key, exam.total_questions)
    given_letters = answer_key.parse_submitted(submitted_answers, exam.total_questions)
    return rasch.estimate_from_letters(difficulties, correct_letters, given_letters)


async def grade_exam(repos: Repositories, exam: Exam, *, regrade: bool = False) -> int:
    """Imtihon bo'yicha baholanmagan javoblarni hisoblab, bazaga yozadi.

    Qaytaradi: baholangan javoblar soni. `regrade=True` bo'lsa avval
    hisoblangan natijalar ham qayta hisoblanadi.

    Raises:
        AnswerKeyError: imtihon kaliti buzuq bo'lsa (masalan, bazaga qo'lda
            noto'g'ri yozilgan bo'lsa).
    """
    if regrade:
        submissions = await repos.answers.list_for_exam(exam.exam_id)
    else:
        submissions = await repos.answers.list_ungraded(exam.exam_id)

    difficulties = exam_service.effective_difficulties(exam)
    correct_letters = answer_key.parse_answer_key(exam.answer_key, exam.total_questions)

    rows: list[tuple[float, float, int, int]] = []
    for submission in submissions:
        given_letters = answer_key.parse_submitted(
            submission.submitted_answers, exam.total_questions
        )
        estimate = rasch.estimate_from_letters(difficulties, correct_letters, given_letters)
        rows.append(
            (
                round(estimate.theta, 4),
                round(estimate.scaled_score, 2),
                estimate.raw_score,
                int(submission.submission_id or 0),
            )
        )

    await repos.answers.save_scores(rows)
    await repos.exams.mark_graded(exam.exam_id, exam_service.now_db())
    logger.info(
        "Imtihon baholandi: exam_id=%s, javoblar=%d, savollar=%d",
        exam.exam_id,
        len(rows),
        exam.total_questions,
    )
    return len(rows)


async def grade_pending(repos: Repositories) -> int:
    """Muddati tugagan, ammo baholanmagan imtihonlarni baholaydi.

    Qaytaradi: jami baholangan javoblar soni.
    """
    exams = await repos.exams.list_pending_grading(exam_service.now_db())
    graded = 0
    for exam in exams:
        try:
            graded += await grade_exam(repos, exam)
        except Exception:  # bitta buzuq imtihon butun siklini to'xtatmasin
            logger.exception("Imtihonni baholashda xatolik: exam_id=%s", exam.exam_id)
    return graded


async def grading_loop(repos: Repositories, interval: int | None = None) -> None:
    """Fon vazifasi: har `interval` sekundda baholanishi kerak bo'lgan imtihonlarni tekshiradi.

    `main.py` da `asyncio.create_task(...)` orqali ishga tushiriladi va bot
    to'xtaganda `task.cancel()` bilan to'xtatiladi.
    """
    delay = int(interval or config.GRADING_INTERVAL)
    logger.info("Baholash fon vazifasi ishga tushdi (har %d sekundda)", delay)
    while True:
        try:
            graded = await grade_pending(repos)
            if graded:
                logger.info("Fon baholash: %d ta javob hisoblandi", graded)
        except asyncio.CancelledError:
            logger.info("Baholash fon vazifasi to'xtatildi")
            raise
        except Exception:  # sikl hech qachon to'xtab qolmasligi kerak
            logger.exception("Baholash siklida kutilmagan xatolik")
        await asyncio.sleep(delay)


async def ensure_graded(repos: Repositories, exam: Exam) -> Exam:
    """Zaxira baholash: `end_time` o'tgan bo'lsa natijani o'sha zahoti hisoblaydi.

    Bu fon vazifasi ishlamay qolgan holatda ham o'quvchi natijani ko'rishi
    uchun kerak (API qatlami chaqiradi).
    """
    if exam.graded_at is not None or exam.end_time > exam_service.now_db():
        return exam

    await grade_exam(repos, exam)
    refreshed = await repos.exams.get(exam.exam_id)
    return refreshed or exam


def build_report(exam: Exam, submission: ExamSubmission) -> dict[str, Any]:
    """Bitta javob uchun batafsil hisobot (Web App "Natijalar" oynasi uchun).

    Diqqat: hisobot javoblar kalitini ochib beradi — shu sababli uni faqat
    `result_time` kelgandan keyin chaqirish kerak (API qatlami tekshiradi).
    """
    difficulties = exam_service.effective_difficulties(exam)
    correct_letters = answer_key.parse_answer_key(exam.answer_key, exam.total_questions)
    given_letters = answer_key.parse_submitted(submission.submitted_answers, exam.total_questions)
    theta = float(submission.theta or 0.0)

    responses = rasch.responses_from_letters(difficulties, correct_letters, given_letters)
    info = rasch.information(theta, responses)
    standard_error = (1.0 / math.sqrt(info)) if info > rasch.EPS else None
    scaled_error = standard_error * config.scaled_span() if standard_error else None
    scaled_score = float(submission.scaled_score or 0.0)

    scaled_interval: tuple[float, float] | None = None
    if scaled_error is not None:
        delta = 1.96 * scaled_error
        scaled_interval = (
            round(max(config.SCALED_MIN, scaled_score - delta), 2),
            round(min(config.SCALED_MAX, scaled_score + delta), 2),
        )

    items: list[dict[str, Any]] = []
    for index, (difficulty, key_letter, given_letter) in enumerate(
        zip(difficulties, correct_letters, given_letters, strict=True), start=1
    ):
        items.append(
            {
                "number": index,
                "difficulty": round(float(difficulty), 3),
                "difficulty_label": rasch.difficulty_label(float(difficulty)),
                "correct_answer": key_letter,
                "given_answer": None if given_letter == SKIPPED else given_letter,
                "is_correct": given_letter == key_letter,
                "probability": round(rasch.probability(theta, float(difficulty)), 4),
            }
        )

    return {
        "exam_id": exam.exam_id,
        "title": exam.title,
        "total_questions": exam.total_questions,
        "raw_score": int(submission.raw_score or 0),
        "theta": round(theta, 4),
        "standard_error": round(standard_error, 4) if standard_error else None,
        "scaled_score": round(scaled_score, 2),
        "scaled_error": round(scaled_error, 2) if scaled_error else None,
        "scaled_interval": scaled_interval,
        "ability_level": rasch.ability_level(scaled_score),
        "advice": rasch.level_advice(scaled_score),
        "submitted_at": submission.submitted_at,
        "items": items,
    }
