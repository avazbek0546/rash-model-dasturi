"""O'qituvchi paneli: `/stats`, `/exams` va imtihonlarni o'chirish.

Barcha handler'lar `handlers.access.is_admin()` orqali tekshiriladi — admin
bo'lmagan foydalanuvchi hech narsa ko'rmaydi (faqat log yoziladi).
"""

from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import texts
from database.models import Exam
from database.repository import Repositories
from handlers.access import is_admin, log_denied
from keyboards.inline import (
    ExamAdminCallback,
    exam_admin_kb,
    exam_delete_confirm_kb,
)
from services import exam_service, grading, item_statistics, report_data, report_pdf
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
            solution_files=await repos.solutions.count_files(),
        )
    )


@router.message(Command("itemstats"))
async def cmd_itemstats(message: Message, repos: Repositories) -> None:
    """Item qiyinchilik hisoboti: `/itemstats <test_kodi>` (faqat admin).

    Test yopilib baholangach, har bir element uchun N / Correct / Wrong / Blank
    / p / b ko'rsatiladi (`services/item_statistics.py`). Hisobot topilmasa —
    o'sha zahoti hisoblanadi.
    """
    if message.from_user is None:
        return

    if not is_admin(message.from_user.id):
        log_denied("/itemstats", message.from_user.id, message.from_user.full_name)
        await message.answer(texts.not_admin())
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "Ishlatish: <code>/itemstats TEST_KODI</code>\n"
            "Masalan: <code>/itemstats MATH2026</code>\n\n"
            "Element qiyinchiligi (p → b) hisoboti ko'rsatiladi."
        )
        return

    code = parts[1].strip()
    session = await repos.sessions.get_by_test_code(code)
    if session is None:
        await message.answer(f"«{escape(code)}» test kodi topilmadi.")
        return

    session_id = int(session["session_id"])
    rows = await item_statistics.build_item_statistics(repos, session_id)
    if not rows:
        await message.answer(
            "Bu test uchun baholangan natijalar hali yo'q.\n"
            "Test yopilib, o'quvchilar baholangandan keyin hisobot paydo bo'ladi."
        )
        return

    title = str(session.get("form_title") or code)
    logger.info(
        "Item hisoboti: test_code=%s, session_id=%s, elementlar=%d, admin=%s",
        code,
        session_id,
        len(rows),
        message.from_user.id,
    )
    for chunk in item_statistics.render_admin_report(rows, title=escape(title)):
        await message.answer(chunk)


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
    """«🗑» tugmasi — avval tasdiqlash oynasini ko'rsatadi (o'chirmaydi)."""
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

    submissions = await repos.answers.count_for_exam(exam.exam_id)
    await call.answer()
    await call.message.answer(
        texts.exam_delete_confirm(
            title=exam.title,
            test_code=exam.test_code,
            submissions=submissions,
        ),
        reply_markup=exam_delete_confirm_kb(exam.exam_id),
    )


@router.callback_query(ExamAdminCallback.filter(F.action == "delete_confirm"))
async def delete_exam_confirm(
    call: CallbackQuery, callback_data: ExamAdminCallback, repos: Repositories
) -> None:
    """Tasdiqlangan o'chirish: imtihon + javoblar (CASCADE) o'chadi."""
    if call.message is None:
        await call.answer()
        return

    if not is_admin(call.from_user.id):
        log_denied("exams:delete_confirm", call.from_user.id, call.from_user.full_name)
        await call.answer(texts.not_admin(), show_alert=True)
        return

    exam = await repos.exams.get(callback_data.exam_id)
    if exam is None:
        await call.answer("Bu imtihon allaqachon o'chirilgan.", show_alert=True)
        return

    try:
        await repos.exams.delete(exam.exam_id)
    except Exception:
        logger.exception("Imtihonni o'chirishda xatolik: exam_id=%s", exam.exam_id)
        await call.answer(
            "⚠️ O'chirishda xatolik yuz berdi. Qayta urinib ko'ring.",
            show_alert=True,
        )
        return

    logger.info(
        "Imtihon o'chirildi: exam_id=%s, kod=%s, admin=%s",
        exam.exam_id,
        exam.test_code,
        call.from_user.id,
    )
    await call.answer(texts.exam_deleted(exam.title)[:200], show_alert=True)
    await _send_exam_list(call.message, repos)


# ---------------------------------------------------------------------------
# Qayta baholash (regrade): kalit yoki `b` tuzatilgach natijalarni yangilash
# ---------------------------------------------------------------------------
async def _regrade(admin_id: int, exam: Exam, repos: Repositories) -> int:
    """Imtihon javoblarini qayta baholaydi va qayta hisoblangan sonni qaytaradi.

    Eski natijalar o'chirilmaydi — yangi snapshot versiyasi yaratiladi
    (`is_final` almashadi), shu sababli bu amal xavfsiz.
    """
    graded = await grading.grade_exam(repos, exam, regrade=True)
    logger.info(
        "Qayta baholash: exam_id=%s, kod=%s, javoblar=%d, admin=%s",
        exam.exam_id,
        exam.test_code,
        graded,
        admin_id,
    )
    return graded


def _regrade_message(exam: Exam, graded: int) -> str:
    """Qayta baholash natijasi xabari (html)."""
    title = escape(str(exam.title))
    code = escape(str(exam.test_code))
    if graded <= 0:
        return (
            f"🔄 «{title}» ({code}) uchun baholanadigan javob topilmadi.\n"
            "Hali hech kim javob yubormagan bo'lishi mumkin."
        )
    return (
        "🔄 <b>Qayta baholash bajarildi</b>\n"
        f"«{title}» ({code})\n"
        f"Qayta hisoblangan javoblar: <b>{graded}</b> ta\n\n"
        "Natijalar yangilandi; eski natijalar tarixda saqlanadi."
    )


@router.message(Command("regrade"))
async def cmd_regrade(message: Message, repos: Repositories) -> None:
    """Qayta baholash: `/regrade TEST_KODI` (faqat admin).

    Savol kaliti yoki qiyinchilik (`b`) tuzatilgach, natijalar (θ va 0–100 ball)
    qaytadan hisoblanadi.
    """
    if message.from_user is None:
        return

    if not is_admin(message.from_user.id):
        log_denied("/regrade", message.from_user.id, message.from_user.full_name)
        await message.answer(texts.not_admin())
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "Ishlatish: <code>/regrade TEST_KODI</code>\n"
            "Masalan: <code>/regrade MATH2026</code>\n\n"
            "Kalit yoki qiyinchilik tuzatilgach, natijalar qayta hisoblanadi."
        )
        return

    code = parts[1].strip()
    exam = await repos.exams.get_by_code(code)
    if exam is None:
        await message.answer(f"«{escape(code)}» test kodi topilmadi.")
        return

    try:
        graded = await _regrade(message.from_user.id, exam, repos)
    except Exception:
        logger.exception("Qayta baholashda xatolik: exam_id=%s", exam.exam_id)
        await message.answer(
            "⚠️ Qayta baholashda xatolik yuz berdi. Kalit va "
            "<code>b</code> larni tekshiring."
        )
        return

    await message.answer(_regrade_message(exam, graded))


@router.callback_query(ExamAdminCallback.filter(F.action == "regrade"))
async def regrade_exam(
    call: CallbackQuery, callback_data: ExamAdminCallback, repos: Repositories
) -> None:
    """«🔄 Baholash» tugmasi — imtihonni qayta baholaydi."""
    if call.message is None:
        await call.answer()
        return

    if not is_admin(call.from_user.id):
        log_denied("exams:regrade", call.from_user.id, call.from_user.full_name)
        await call.answer(texts.not_admin(), show_alert=True)
        return

    exam = await repos.exams.get(callback_data.exam_id)
    if exam is None:
        await call.answer(
            "Bu imtihon topilmadi (o'chirilgan bo'lishi mumkin).", show_alert=True
        )
        return

    await call.answer()
    try:
        graded = await _regrade(call.from_user.id, exam, repos)
    except Exception:
        logger.exception("Qayta baholashda xatolik: exam_id=%s", exam.exam_id)
        await call.message.answer(
            "⚠️ Qayta baholashda xatolik yuz berdi. Kalit va "
            "<code>b</code> larni tekshiring."
        )
        return

    await call.message.answer(_regrade_message(exam, graded))
    await _send_exam_list(call.message, repos)


# ---------------------------------------------------------------------------
# O'quvchilar natijalari PDF hisoboti (faqat admin chatiga yuboriladi)
# ---------------------------------------------------------------------------
@router.message(Command("report"))
async def cmd_report(message: Message, repos: Repositories) -> None:
    """`/report TEST_KODI` — o'quvchilar natijalari PDF ini yuboradi (faqat admin).

    Fayl **adminga shaxsiy chatda** yuboriladi; o'quvchilarga admin o'zi kanalga
    joylaydi. Natija saqlanmaydi — har so'ralganda qaytadan yasaladi.
    """
    if message.from_user is None:
        return

    if not is_admin(message.from_user.id):
        log_denied("/report", message.from_user.id, message.from_user.full_name)
        await message.answer(texts.not_admin())
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "Ishlatish: <code>/report TEST_KODI</code>\n"
            "Masalan: <code>/report MATH2026</code>\n\n"
            "O'quvchilar natijalari PDF ko'rinishida yuboriladi."
        )
        return

    code = parts[1].strip()
    exam = await repos.exams.get_by_code(code)
    if exam is None:
        await message.answer(f"«{escape(code)}» test kodi topilmadi.")
        return

    try:
        report = await report_data.build_exam_report(repos, exam)
        data = report_pdf.build_results_pdf(
            title=report.title,
            test_code=report.test_code,
            date_text=report.date_text,
            participants=report.participants,
            students=report.students,
        )
    except report_pdf.ReportError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}")
        return
    except Exception:
        logger.exception("PDF hisobot yasalmadi: exam_id=%s", exam.exam_id)
        await message.answer(
            "⚠️ Hisobotni yasashda xatolik yuz berdi. Keyinroq qayta urinib ko'ring."
        )
        return

    logger.info(
        "PDF hisobot yuborildi: exam_id=%s, kod=%s, o'quvchilar=%d, admin=%s",
        exam.exam_id,
        exam.test_code,
        report.participants,
        message.from_user.id,
    )
    await message.answer_document(
        BufferedInputFile(data, filename=f"natijalar-{exam.test_code}.pdf"),
        caption=(
            f"📄 «{escape(str(exam.title))}» — natijalar\n"
            f"O'quvchilar: <b>{report.participants}</b> ta"
        ),
    )
