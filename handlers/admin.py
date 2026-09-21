"""O'qituvchi paneli: `/stats`, `/exams` va imtihonlarni o'chirish.

Barcha handler'lar `handlers.access.is_admin()` orqali tekshiriladi — admin
bo'lmagan foydalanuvchi hech narsa ko'rmaydi (faqat log yoziladi).
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import texts
from database.models import Exam
from database.repository import Repositories
from handlers.access import is_admin, log_denied
from keyboards.inline import ExamAdminCallback, exam_admin_kb
from services import exam_service
from services.test_session import TestSessionStore

logger = logging.getLogger(__name__)

router = Router(name="admin")


async def _collect(repos: Repositories) -> tuple[list[Exam], list[dict], dict[int, str]]:
    """Imtihonlar, ular uchun matn qatorlari va holat nomlarini yig'adi."""
    exams = await repos.exams.list_all(limit=10)
    now = exam_service.now_db()
    rows: list[dict] = []
    titles: dict[int, str] = {}

    for exam in exams:
        status_title = exam_service.status_title(exam_service.status_of(exam, now))
        titles[exam.exam_id] = status_title
        rows.append(
            {
                "exam_id": exam.exam_id,
                "title": exam.title,
                "test_code": exam.test_code,
                "total_questions": exam.total_questions,
                "answer_key": exam.answer_key,
                "status_title": status_title,
                "start_local": exam_service.format_local(exam.start_time),
                "end_local": exam_service.format_local(exam.end_time),
                "result_local": exam_service.format_local(exam.result_time),
                "submissions": await repos.answers.count_for_exam(exam.exam_id),
            }
        )
    return exams, rows, titles


async def _send_exam_list(message: Message, repos: Repositories) -> None:
    """Imtihonlar ro'yxatini (o'chirish tugmalari bilan) yuboradi."""
    exams, rows, titles = await _collect(repos)
    markup = exam_admin_kb(exams, status_titles=titles) if exams else None
    await message.answer(texts.exam_list(rows), reply_markup=markup)


@router.message(Command("stats"))
async def cmd_stats(
    message: Message, repos: Repositories, sessions: TestSessionStore
) -> None:
    """Botning umumiy statistikasi (faqat admin)."""
    if message.from_user is None:
        return

    if not is_admin(message.from_user.id):
        log_denied("/stats", message.from_user.id, message.from_user.full_name)
        return  # oddiy o'quvchilarga hech narsa ko'rsatmaymiz

    await message.answer(
        texts.admin_stats(
            users=await repos.users.count(),
            questions=await repos.questions.count(),
            attempts=await repos.results.count(),
            average_scaled=await repos.results.average_scaled(),
            active_sessions=sessions.active_count(),
            exams=await repos.exams.count(),
            submissions=await repos.answers.count(),
            solution_files=await repos.solutions.count(),
        )
    )


@router.message(Command("exams"))
async def cmd_exams(message: Message, repos: Repositories) -> None:
    """Imtihonlar ro'yxati va o'chirish tugmalari (faqat admin)."""
    if message.from_user is None:
        return

    if not is_admin(message.from_user.id):
        log_denied("/exams", message.from_user.id, message.from_user.full_name)
        await message.answer(texts.not_admin())
        return

    await _send_exam_list(message, repos)


@router.callback_query(ExamAdminCallback.filter(F.action == "list"))
async def list_exams_callback(call: CallbackQuery, repos: Repositories) -> None:
    """«📋 Imtihonlar ro'yxati» tugmasi."""
    if call.message is None:
        await call.answer()
        return

    if not is_admin(call.from_user.id):
        log_denied("exams:tugma", call.from_user.id, call.from_user.full_name)
        await call.answer(texts.not_admin(), show_alert=True)
        return

    await call.answer()
    await _send_exam_list(call.message, repos)


@router.callback_query(ExamAdminCallback.filter(F.action == "delete"))
async def delete_exam(
    call: CallbackQuery, callback_data: ExamAdminCallback, repos: Repositories
) -> None:
    """Imtihonni o'chiradi (unga tegishli javoblar ham CASCADE bilan o'chadi)."""
    if call.message is None:
        await call.answer()
        return

    if not is_admin(call.from_user.id):
        log_denied("exams:delete", call.from_user.id, call.from_user.full_name)
        await call.answer(texts.not_admin(), show_alert=True)
        return

    exam = await repos.exams.get(callback_data.exam_id)
    if exam is None:
        await call.answer("Bu imtihon topilmadi (o'chirilgan bo'lishi mumkin).", show_alert=True)
        return

    await repos.exams.delete(exam.exam_id)
    logger.info("Imtihon o'chirildi: exam_id=%s, admin=%s", exam.exam_id, call.from_user.id)
    await call.answer(texts.exam_deleted(exam.title)[:200], show_alert=True)
    await _send_exam_list(call.message, repos)
