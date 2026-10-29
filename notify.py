"""O'quvchiga bot orqali bildirishnoma yuborish.

Ikki xil xabar bor:
1. **Qabul xabari** (`send_submission_accepted`) — javob yuborilgandan keyin
   darhol. Unda **faqat** ✅/❌ belgilari (qaysi savol to'g'ri/xato) bo'ladi;
   to'g'ri javob varianti, θ va ball **ko'rsatilmaydi** — kalit `result_time`
   gacha yopiq qoladi.
2. **Natija xabari** (`send_result_ready`) — faqat `result_time` kelgach,
   `notify_due_results` fon vazifasi orqali. Ball, daraja, θ va 95% interval
   ko'rsatiladi; xabar bir marta ketadi (`user_answers.notified_at`).

Dizayn qoidasi: javob kaliti hech qachon oshkor qilinmaydi.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Sequence

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
from services import admin_chat, exam_service, grading

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
    marks: Sequence[tuple[str, bool]] | None = None,
) -> bool:
    """Javob qabul qilinganini tasdiqlaydi (+ ixtiyoriy ✅/❌ ro'yxati).

    Xabar minimal: sarlavha va har bir savol uchun **alohida qatorda** ✅/❌
    (`marks` — `services.feedback` dan). Xabar `result_time` dan oldin ketadi,
    shuning uchun kalit, θ va ball **qo'shilmaydi** — faqat qaysi savol
    to'g'ri, qaysi biri xato ekani ko'rsatiladi.
    `marks` berilmasa — faqat sarlavha (feedback hisoblanmagan holat).
    """
    text = texts.submission_accepted(marks=marks)
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=results_keyboard(),
        )
    except TelegramAPIError:
        logger.warning(
            "Qabul xabarini yuborib bo'lmadi: user_id=%s",
            user_id,
            exc_info=True,
        )
        return False
    logger.info(
        "Qabul xabari yuborildi: user_id=%s, savollar=%d",
        user_id,
        len(marks or ()),
    )
    return True


async def send_admin_participant(
    bot: Bot | None,
    *,
    repos: Repositories,
    exam: Exam,
    user: dict[str, Any],
    submitted_local: str | None = None,
) -> bool:
    """Yangi qatnashchi haqida admin chatga xabar yuboradi.

    Admin chat `/admin_chat` orqali bog'lanmagan bo'lsa — hech narsa
    qilmaydi (`False`). Xabar yuborilmasa ham o'quvchining javobi saqlanib
    qoladi: chaqiruvchi (`web/api.py`) xatolikni yutadi.
    """
    if bot is None:
        return False

    chat_id = await admin_chat.chat_id(repos)
    if chat_id is None:
        return False

    user_id = int(user.get("user_id") or 0)
    saved = await repos.users.get(user_id) if user_id else None
    full_name = (
        (saved.full_name if saved and saved.full_name else "")
        or str(user.get("full_name") or "")
        or "O'quvchi"
    )
    username = (saved.username if saved and saved.username else None) or user.get(
        "username"
    )
    count = await repos.answers.count_for_exam(exam.exam_id)
    stamp = submitted_local or exam_service.format_local(exam_service.utc_now())

    text = texts.admin_participant(
        title=str(exam.title),
        test_code=str(exam.test_code),
        full_name=full_name,
        username=str(username) if username else None,
        user_id=user_id,
        submitted_local=stamp,
        count=count,
    )

    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except TelegramForbiddenError:
        logger.warning(
            "Admin chatga yuborib bo'lmadi (bot chiqarilgan yoki huquq yo'q): "
            "chat_id=%s, user_id=%s",
            chat_id,
            user_id,
        )
        return False
    except TelegramRetryAfter as exc:
        logger.warning(
            "Admin chat rate-limit: retry_after=%s (chat_id=%s)",
            exc.retry_after,
            chat_id,
        )
        return False
    except TelegramAPIError:
        logger.warning(
            "Admin chatga xabar yuborilmadi: chat_id=%s, user_id=%s",
            chat_id,
            user_id,
            exc_info=True,
        )
        return False

    logger.info(
        "Admin chatga qatnashchi yuborildi: chat_id=%s, user_id=%s, exam_id=%s, jami=%d",
        chat_id,
        user_id,
        exam.exam_id,
        count,
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
        "Natija yuborildi: user_id=%s, exam_id=%s, theta=%+.3f",
        user_id,
        exam.exam_id,
        float(report.get("theta") or 0.0),
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
