"""Hisobot uchun ma'lumot yig'ish (bot va Web App admin paneli uchun).

`grading.build_report()` dan foydalanadi — har bir o'quvchi uchun **umumiy
(sertifikat) ball**, **θ (logit)**, **daraja**, **algebra/geometriya balli**
va **to'g'ri javoblar soni** olinadi.
Natijalar **θ bo'yicha kamayish tartibida** saralanadi (u umumiy ball bilan
bir xil tartibni beradi).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from database.repository import Repositories
from services import exam_service, grading
from services.report_pdf import StudentRow

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExamReport:
    """Bitta imtihon hisoboti (PDF yasash uchun tayyor)."""

    title: str
    test_code: str
    date_text: str
    participants: int
    students: list[StudentRow]


def _subject_ball(report: dict, code: str) -> float | None:
    """Hisobotdan fan ballini oladi (`None` bo'lsa — `None`)."""
    value = (report.get("subject_balls") or {}).get(code)
    return None if value is None else float(value)


async def build_exam_report(repos: Repositories, exam) -> ExamReport:
    """Imtihon uchun barcha o'quvchilar natijalarini yig'adi.

    Ism `users` dan olinadi; o'quvchi topilmasa — `#user_id`. Bitta satr
    yasalmay qolsa, u **o'tkazib yuboriladi** (butun hisobot to'xtamaydi).
    """
    submissions = await repos.answers.list_for_exam(exam.exam_id)
    students: list[StudentRow] = []
    for submission in submissions:
        try:
            report = grading.build_report(exam, submission)
        except Exception:  # bitta buzuq javob hisobotni to'xtatmasin
            logger.exception(
                "Hisobot satri yasalmadi: exam_id=%s, user_id=%s",
                exam.exam_id,
                submission.user_id,
            )
            continue
        user = await repos.users.get(submission.user_id)
        students.append(
            StudentRow(
                name=(user.full_name if user else f"#{submission.user_id}"),
                # Umumiy (sertifikat) bali — asosiy ko'rsatkich (0..100).
                total_ball=float(report["scaled_score"]),
                theta=float(report["theta"]),
                level=str(report["ability_level"]),
                algebra=_subject_ball(report, "algebra"),
                geometry=_subject_ball(report, "geometry"),
                correct=int(report["raw_score"]),
                total=int(report["total_questions"]),
            )
        )

    # θ bo'yicha kamayish tartibida (umumiy ball bilan bir xil tartib).
    students.sort(key=lambda row: row.theta, reverse=True)
    return ExamReport(
        title=str(exam.title),
        test_code=str(exam.test_code),
        date_text=exam_service.format_local(exam.start_time),
        participants=len(students),
        students=students,
    )
