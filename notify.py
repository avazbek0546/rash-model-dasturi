"""O'quvchiga bot orqali bildirishnoma yuborish.

Ikki xil xabar bor:
1. **Qabul xabari** (`send_submission_accepted`) — javob yuborilgandan keyin
   darhol. Unda to'g'ri/xato sanoq **yo'q** (imtihon tozaligi).
2. **Natija xabari** (`send_result_ready`) — faqat `result_time` kelgach,
   `notify_due_results` fon vazifasi orqali. Ball, daraja, θ va 95% interval
   ko'rsatiladi; xabar bir marta ketadi (`user_answers.notified_at`).

Dizayn qoidasi: javob kaliti hech qachon oshkor qilinmaydi.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

import config
import texts
from database.models import Exam, ExamSubmission
from database.repository import Repositories
from keyboards.inline import AnalysisCallback
from services import exam_service, grading

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Klaviaturalar
# ---------------------------------------------------------------------------
def results_keyboard() -> InlineKeyboardMarkup | None:
    """«📊 Natijalar» — Mini App'ning aynan Natijalar bo'limini ochadi."""
    if not config.WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Natijalar",
                    web_app=WebAppInfo(url=config.webapp_url(tab="results")),
                    style="success",
                )
            ]
        ]
    )


def result_keyboard(exam_id: int) -> InlineKeyboardMarkup:
    """Natija kartasi ostidagi tugmalar: ilova + savollar tahlili."""
    rows: list[list[InlineKeyboardButton]] = []
    if config.WEBAPP_URL:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📊 Batafsil tahlil",
                    web_app=WebAppInfo(url=config.webapp_url(tab="results")),
                    style="success",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔍 Savollar tahlili",
                callback_data=AnalysisCallback(
                    action="exam", exam_id=exam_id
                ).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_submission_accepted(
    bot: Bot,
    *,
    user_id: int,
    full_name: str,
    exam: Exam,
    answered: int,
) -> bool:
    """Javob qabul qilinganini tasdiqlaydi — natija sanoqlarisiz.

    Bu xabar `result_time` dan oldin yuboriladi, shuning uchun unda
    to'g'ri/xato ma'lumoti bo'lmasligi shart.
    """
    text = texts.submission_accepted(
        title=exam.title,
        full_name=full_name,
        answered=answered,
        total=exam.total_questions,
        result_local=exam_service.format_local(exam.result_time),
    )
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=results_keyboard(),
        )
    except TelegramAPIError:
        logger.warning(
            "Qabul xabarini yuborib bo'lmadi: user_id=%s, exam_id=%s",
            user_id,
            exam.exam_id,
            exc_info=True,
        )
        return False
    logger.info(
        "Qabul xabari yuborildi: user_id=%s, exam_id=%s, javob=%d/%d",
        user_id,
        exam.exam_id,
        answered,
        exam.total_questions,
    )
    return True


async def send_result_ready(
    bot: Bot,
    *,
    user_id: int,
    full_name: str,
    exam: Exam,
    submission: ExamSubmission,
) -> bool:
    """Natija e'lon qilinganda boy kartani yuboradi (ball, daraja, θ, interval).

    Qaytaradi:
        True — xabar yuborildi YOKI foydalanuvchi botni bloklagan (qayta
        urinish foydasiz); False — vaqtinchalik xato (keyingi sikl qayta urinadi).
    """
    try:
        report = grading.build_report(exam, submission)
    except Exception:
        logger.exception(
            "Natija hisobotini qurib bo'lmadi: user_id=%s, exam_id=%s",
            user_id,
            exam.exam_id,
        )
        return False

    text = texts.result_ready(
        title=exam.title,
        full_name=full_name,
        report=report,
    )
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=result_keyboard(exam.exam_id),
        )
    except TelegramForbiddenError:
        # Foydalanuvchi botni bloklagan — qayta urinish kerak emas.
        logger.info(
            "Natija yuborilmadi (bot bloklangan): user_id=%s, exam_id=%s",
            user_id,
            exam.exam_id,
        )
        return True
    except TelegramRetryAfter as exc:
        logger.warning(
            "Telegram rate-limit: retry_after=%s (user_id=%s)",
            exc.retry_after,
            user_id,
        )
        return False
    except TelegramAPIError:
        logger.warning(
            "Natija xabarini yuborib bo'lmadi: user_id=%s, exam_id=%s",
            user_id,
            exam.exam_id,
            exc_info=True,
        )
        return False

    logger.info(
        "Natija yuborildi: user_id=%s, exam_id=%s, ball=%.2f",
        user_id,
        exam.exam_id,
        float(report.get("scaled_score") or 0.0),
    )
    return True


# ---------------------------------------------------------------------------
# Fon vazifasi: result_time kelgan natijalarni yuborish
# ---------------------------------------------------------------------------
async def notify_due_results(
    repos: Repositories,
    bot: Bot,
    *,
    limit: int = 200,
) -> int:
    """Natijasi e'lon qilingan, ammo xabari yuborilmagan javoblarni yuboradi.

    Har bir javob uchun `notified_at` belgilanadi — xabar ikki marta ketmaydi.
    Qaytaradi: yuborilgan (yoki bloklangan deb belgilangan) xabarlar soni.
    """
    now = exam_service.now_db()
    due = await repos.answers.list_due_notifications(now, limit=limit)
    if not due:
        return 0

    sent = 0
    for submission in due:
        if submission.submission_id is None:
            continue

        exam = await repos.exams.get(submission.exam_id)
        if exam is None:
            await repos.answers.mark_notified(submission.submission_id, now)
            continue

        user = await repos.users.get(submission.user_id)
        full_name = user.full_name if user and user.full_name else "O'quvchi"

        delivered = await send_result_ready(
            bot,
            user_id=submission.user_id,
            full_name=full_name,
            exam=exam,
            submission=submission,
        )
        if delivered:
            await repos.answers.mark_notified(submission.submission_id, now)
            sent += 1

    return sent


async def result_notification_loop(
    repos: Repositories,
    bot: Bot,
    interval: int | None = None,
) -> None:
    """Fon vazifasi: har `interval` sekundda tayyor natijalarni tekshiradi."""
    delay = int(interval or config.RESULT_NOTIFY_INTERVAL)
    logger.info(
        "Natija bildirishnomasi fon vazifasi ishga tushdi (har %d sekundda)",
        delay,
    )
    while True:
        try:
            sent = await notify_due_results(repos, bot)
            if sent:
                logger.info("Natija bildirishnomasi: %d ta xabar yuborildi", sent)
        except asyncio.CancelledError:
            logger.info("Natija bildirishnomasi fon vazifasi to'xtatildi")
            raise
        except Exception:  # sikl hech qachon to'xtab qolmasligi kerak
            logger.exception("Natija bildirishnomasi siklida kutilmagan xatolik")
        await asyncio.sleep(delay)
