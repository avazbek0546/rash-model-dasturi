"""Offline + online natijalarni yagona reytingga yig'ish.

Mavjud online `user_answers` va yangi `offline_attempts` bitta
`StudentRow` ro'yxatiga keltiriladi. Offline rasmiy; tasdiqlangan link
orqali bog'langan online natija reytingdan chiqariladi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

import config
from database.models import Exam
from database.repository import Repositories
from services import exam_service, grading, offline_scoring, report_pdf, subjects

logger = logging.getLogger(__name__)


class OfflineReportError(RuntimeError):
    """Hisobot yasash mumkin emasligi."""


@dataclass(frozen=True, slots=True)
class UnifiedReport:
    title: str
    test_code: str
    date_text: str
    participants: int
    offline_count: int
    online_count: int
    excluded_count: int
    students: tuple[report_pdf.StudentRow, ...]
    meta: report_pdf.ReportMeta


def _row_key(row: report_pdf.StudentRow) -> tuple[float, int, str, str, str]:
    return (
        -float(row.theta),
        -int(row.correct),
        str(row.name).casefold(),
        str(row.source),
        str(row.student_code),
    )


def _rank_rows(rows: list[report_pdf.StudentRow]) -> list[report_pdf.StudentRow]:
    """Competition ranking: teng natijalar bir xil o'rin oladi."""
    ordered = sorted(rows, key=_row_key)
    ranked: list[report_pdf.StudentRow] = []
    previous: tuple[Any, ...] | None = None
    previous_rank = 0
    for index, row in enumerate(ordered, start=1):
        current = (round(float(row.theta), 4), int(row.correct))
        rank = previous_rank if previous is not None and current == previous else index
        previous, previous_rank = current, rank
        ranked.append(replace(row, rank=rank))
    return ranked


async def _online_rows(
    repos: Repositories, exam: Exam, *, total_items: int = 55
) -> tuple[list[report_pdf.StudentRow], int]:
    rows: list[report_pdf.StudentRow] = []
    excluded = 0
    for submission in await repos.answers.list_for_exam(exam.exam_id):
        if submission.theta is None:
            continue
        try:
            report = grading.build_report(exam, submission)
        except Exception:
            logger.exception(
                "Online hisobot satri yasalmadi: exam_id=%s, user_id=%s",
                exam.exam_id,
                submission.user_id,
            )
            continue
        user = await repos.users.get(submission.user_id)
        is_excluded = await repos.offline_decisions.is_excluded(
            exam.exam_id, "telegram_user", submission.user_id
        )
        if is_excluded:
            excluded += 1
        subject_balls = report.get("subject_balls") or {}
        rows.append(
            report_pdf.StudentRow(
                name=(user.full_name if user else f"#{submission.user_id}"),
                total_ball=float(report.get("scaled_score") or 0.0),
                theta=float(report.get("theta") or 0.0),
                level=str(report.get("ability_level") or "NC"),
                algebra=(
                    None
                    if subject_balls.get("algebra") is None
                    else float(subject_balls["algebra"])
                ),
                geometry=(
                    None
                    if subject_balls.get("geometry") is None
                    else float(subject_balls["geometry"])
                ),
                correct=int(report.get("raw_score") or 0),
                total=int(total_items),
                source="online",
                standard_error=(
                    None
                    if report.get("standard_error") is None
                    else float(report["standard_error"])
                ),
                included=not is_excluded,
            )
        )
    return rows, excluded


async def _offline_rows(
    repos: Repositories, exam: Exam
) -> list[report_pdf.StudentRow]:
    rows: list[report_pdf.StudentRow] = []
    for attempt in await repos.offline_attempts.list_for_exam(exam.exam_id):
        responses = await repos.offline_attempts.list_responses(
            int(attempt["offline_attempt_id"])
        )
        summaries = subjects.summarize(
            (int(item.get("position") or 0), bool(int(item.get("is_correct") or 0)))
            for item in responses
        )
        balls = subjects.allocate_total_ball(
            float(attempt.get("scaled_score") or 0.0), summaries
        )
        rows.append(
            report_pdf.StudentRow(
                name=str(attempt.get("full_name") or ""),
                total_ball=float(attempt.get("scaled_score") or 0.0),
                theta=float(attempt.get("theta") or 0.0),
                level=str(attempt.get("level") or "NC"),
                algebra=(
                    None if balls.get("algebra") is None else float(balls["algebra"])
                ),
                geometry=(
                    None if balls.get("geometry") is None else float(balls["geometry"])
                ),
                correct=int(attempt.get("raw_score") or 0),
                total=int(attempt.get("total_items") or 55),
                source="offline",
                student_code=str(attempt.get("student_code") or ""),
                standard_error=(
                    None
                    if attempt.get("theta_se") is None
                    else float(attempt["theta_se"])
                ),
                included=str(attempt.get("status")) == "valid",
            )
        )
    return rows


async def _meta(
    repos: Repositories,
    exam: Exam,
    readiness: offline_scoring.OfflineReadiness,
    *,
    subtitle: str,
    students: list[report_pdf.StudentRow],
    excluded: int,
) -> report_pdf.ReportMeta:
    batches = await repos.offline_batches.list_batches(exam.exam_id)
    batch_ids = ", ".join(
        f"#{int(row['batch_no'])}"
        for row in batches
        if str(row.get("status")) == "committed"
    )
    offline_count = sum(1 for row in students if row.source == "offline")
    online_count = sum(1 for row in students if row.source == "online")
    return report_pdf.ReportMeta(
        title=str(exam.title),
        test_code=str(exam.test_code),
        date_text=exam_service.format_local(exam.start_time),
        subtitle=subtitle,
        participants=len(students),
        offline_count=offline_count,
        online_count=online_count,
        excluded_count=excluded,
        b_source=readiness.b_source,
        b_checksum=readiness.b_checksum,
        key_fingerprint=readiness.key_fingerprint,
        engine_version=readiness.engine_version,
        form_version_id=readiness.form_version_id,
        batch_ids=batch_ids or "—",
        ranking_rule=(
            f"{config.OFFLINE_RANKING_RULE_VERSION}: θ↓, xom ball↓, ism↑; "
            "teng natija — bir xil o'rin"
        ),
        generated_at=exam_service.format_local(exam_service.now_db()),
    )


async def _ensure(repos: Repositories, exam_id: int) -> int:
    """Hisobotdan oldin nomzodlarni yangilaydi va reyting qarorlarini qo'llaydi.

    Offline import paytida o'quvchi hali botda ro'yxatdan o'tmagan bo'lishi
    mumkin. Keyin u online qatnashsa, username endi mavjud bo'ladi — shu
    bosqichda qayta qidirish offline natijani online bilan bog'laydi va
    reytingda dublikat paydo bo'lmaydi.
    """
    from services import offline_import

    await offline_import.refresh_suggestions(repos, exam_id)
    return await offline_import.ensure_ranking_decisions(repos, exam_id)


async def build_combined_report(
    repos: Repositories, exam: Exam
) -> UnifiedReport:
    """Online + offline umumiy reyting."""
    readiness = await offline_scoring.check_readiness(repos, exam)
    if not readiness.ready:
        raise OfflineReportError(
            "Bu imtihonni birlashtirib bo'lmaydi: " + readiness.reason
        )
    await _ensure(repos, exam.exam_id)
    online_rows, excluded = await _online_rows(
        repos, exam, total_items=len(readiness.items)
    )
    offline_rows = await _offline_rows(repos, exam)
    included = [row for row in online_rows + offline_rows if row.included]
    students = _rank_rows(included)
    meta = await _meta(
        repos, exam, readiness,
        subtitle="Umumiy reyting — offline va online",
        students=students, excluded=excluded,
    )
    return UnifiedReport(
        title=str(exam.title),
        test_code=str(exam.test_code),
        date_text=meta.date_text,
        participants=len(students),
        offline_count=meta.offline_count,
        online_count=meta.online_count,
        excluded_count=excluded,
        students=tuple(students),
        meta=meta,
    )


async def build_offline_report(
    repos: Repositories, exam: Exam
) -> UnifiedReport:
    """Faqat offline ishtirokchilar reytingi."""
    readiness = await offline_scoring.check_readiness(repos, exam)
    if not readiness.ready:
        raise OfflineReportError(
            "Bu imtihon uchun offline hisobot yasab bo'lmaydi: " + readiness.reason
        )
    await _ensure(repos, exam.exam_id)
    offline_rows = await _offline_rows(repos, exam)
    students = _rank_rows([row for row in offline_rows if row.included])
    meta = await _meta(
        repos, exam, readiness,
        subtitle="Faqat offline ishtirokchilar",
        students=students, excluded=0,
    )
    return UnifiedReport(
        title=str(exam.title),
        test_code=str(exam.test_code),
        date_text=meta.date_text,
        participants=len(students),
        offline_count=meta.offline_count,
        online_count=0,
        excluded_count=0,
        students=tuple(students),
        meta=meta,
    )
