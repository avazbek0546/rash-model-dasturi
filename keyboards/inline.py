"""Inline klaviaturalar (aiogram 3 `CallbackData` factory'lari bilan).

Callback ma'lumotlarini "menu:start_test" kabi matn sifatida emas, balki
tiplashtirilgan factory'lar orqali uzatamiz — bu xatolarga chidamli usul.
"""

from __future__ import annotations

from typing import Any, Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from database.models import SKIPPED, Exam, Question
from services import solutions


class MenuCallback(CallbackData, prefix="menu"):
    """Asosiy menyu va navigatsiya tugmalari.

    action: start_test | results | about | back | finish
    """

    action: str


class AnswerCallback(CallbackData, prefix="ans"):
    """Javob tugmalari: qaysi savolga (`question_id`) qanday variant (`option`)."""

    question_id: int
    option: str


def _short(text: str, limit: int = 28) -> str:
    """Tugma matnini qisqartiradi (Telegram tugma matni 64 belgidan oshmasligi kerak)."""
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def menu_kb() -> InlineKeyboardMarkup:
    """Bosh menyu klaviaturasi."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Testni boshlash", callback_data=MenuCallback(action="start_test"))
    builder.button(text="📊 Mening natijalarim", callback_data=MenuCallback(action="results"))
    builder.button(text="ℹ️ Rasch modeli haqida", callback_data=MenuCallback(action="about"))
    builder.adjust(1)
    return builder.as_markup()


def answer_kb(question: Question) -> InlineKeyboardMarkup:
    """Javob variantlari klaviaturasi (A, B, C, D + «Bilmayman» + «Yakunlash»)."""
    builder = InlineKeyboardBuilder()
    for letter, text in question.options().items():
        builder.button(
            text=f"{letter}) {_short(text)}",
            callback_data=AnswerCallback(question_id=question.question_id, option=letter),
        )
    builder.button(
        text="❓ Bilmayman",
        callback_data=AnswerCallback(question_id=question.question_id, option=SKIPPED),
    )
    builder.button(text="🛑 Testni yakunlash", callback_data=MenuCallback(action="finish"))
    builder.adjust(1, 1, 1, 1, 1, 1)
    return builder.as_markup()


def after_test_kb() -> InlineKeyboardMarkup:
    """Test yakunlangandan keyingi tugmalar."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Yana test topshirish", callback_data=MenuCallback(action="start_test"))
    builder.button(text="📊 Natijalarim", callback_data=MenuCallback(action="results"))
    builder.button(text="🏠 Bosh menyu", callback_data=MenuCallback(action="back"))
    builder.adjust(1)
    return builder.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    """Orqaga (bosh menyuga) tugmasi."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Bosh menyu", callback_data=MenuCallback(action="back"))
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Imtihon platformasi tugmalari (Web App + o'qituvchi boshqaruvi)
# ---------------------------------------------------------------------------
class AppCallback(CallbackData, prefix="app"):
    """Web App bo'limlari uchun tugmalar.

    action: help | missing
    """

    action: str


class ExamAdminCallback(CallbackData, prefix="exam"):
    """O'qituvchi panelidagi tugmalar.

    action: new | list | confirm | cancel | delete
    exam_id: o'chirish uchun imtihon ID si (kerak bo'lmasa 0).
    """

    action: str
    exam_id: int = 0


def webapp_kb(*, is_admin: bool) -> InlineKeyboardMarkup:
    """Bosh menyu: Web App tugmasi (+ admin uchun boshqaruv tugmalari)."""
    builder = InlineKeyboardBuilder()
    if config.WEBAPP_URL:
        builder.button(
            text="🚀 Imtihonlar ilovasi",
            web_app=WebAppInfo(url=f"{config.WEBAPP_URL}/"),
        )
    else:
        builder.button(
            text="🚀 Imtihonlar ilovasi (manzil sozlanmagan)",
            callback_data=AppCallback(action="missing"),
        )

    if is_admin:
        builder.button(text="➕ Yangi imtihon", callback_data=ExamAdminCallback(action="new"))
        builder.button(text="📋 Imtihonlar ro'yxati", callback_data=ExamAdminCallback(action="list"))

    builder.button(text="ℹ️ Yordam", callback_data=AppCallback(action="help"))
    builder.adjust(1)
    return builder.as_markup()


def exam_confirm_kb() -> InlineKeyboardMarkup:
    """Usta oxirida: imtihonni tasdiqlash yoki bekor qilish."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Yaratish", callback_data=ExamAdminCallback(action="confirm"))
    builder.button(text="❌ Bekor qilish", callback_data=ExamAdminCallback(action="cancel"))
    builder.adjust(2)
    return builder.as_markup()


def exam_admin_kb(exams: list[Exam], *, status_titles: dict[int, str] | None = None) -> InlineKeyboardMarkup:
    """Admin ro'yxati: har bir imtihon uchun o'chirish tugmasi.

    Tugma matni: "🗑 #12 Matematika — Faol". `status_titles` — holat nomlari.
    """
    titles = status_titles or {}
    builder = InlineKeyboardBuilder()
    for exam in exams[:10]:  # tugmalar sonini cheklaymiz
        status = titles.get(exam.exam_id)
        label = f"🗑 #{exam.exam_id} {_short(exam.title, 22)}"
        if status:
            label += f" — {_short(status, 14)}"
        builder.button(
            text=label,
            callback_data=ExamAdminCallback(action="delete", exam_id=exam.exam_id),
        )
    builder.button(text="➕ Yangi imtihon", callback_data=ExamAdminCallback(action="new"))
    builder.adjust(1)
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    """Usta davomida bekor qilish tugmasi."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Bekor qilish", callback_data=ExamAdminCallback(action="cancel"))
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# «🔍 Test tahlili» bo'limi (o'quvchi) — imtihonlar, savollar va yechimlar
# ---------------------------------------------------------------------------
HOME_BUTTON = "🏡 Asosiy menyu"


class AnalysisCallback(CallbackData, prefix="tahlil"):
    """«🔍 Test tahlili» tugmalari.

    action: page   — sahifani almashtirish (`page` maydoni ishlatiladi);
            exam   — imtihonni tanlash (savollar gridi ochiladi);
            question — savol (yoki uning A/B qismi) yechimini olish;
            home   — asosiy menyuga qaytish.
    """

    action: str
    exam_id: int = 0
    question: int = 0
    part: str = ""
    page: int = 1


def analysis_home_kb() -> InlineKeyboardMarkup:
    """Faqat «🏡 Asosiy menyu» tugmasidan iborat klaviatura."""
    builder = InlineKeyboardBuilder()
    builder.button(text=HOME_BUTTON, callback_data=AnalysisCallback(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def analysis_exams_kb(window: Any) -> InlineKeyboardMarkup:
    """Imtihonlar ro'yxati: har biri alohida qatorda + sahifalash tugmalari.

    `window` — `services.solutions.PageWindow` (joriy sahifa va undagi imtihonlar).
    """
    builder = InlineKeyboardBuilder()
    for exam in window.items:
        builder.button(
            text=solutions.exam_label(exam),
            callback_data=AnalysisCallback(action="exam", exam_id=exam.exam_id, page=window.page),
        )
    if window.has_prev:
        builder.button(
            text="⬅️ Oldingi", callback_data=AnalysisCallback(action="page", page=window.prev_page)
        )
    if window.has_next:
        builder.button(
            text="Keyingi ➡️", callback_data=AnalysisCallback(action="page", page=window.next_page)
        )
    builder.button(text=HOME_BUTTON, callback_data=AnalysisCallback(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def analysis_questions_kb(
    units: Sequence[solutions.QuestionUnit], *, exam_id: int, page: int = 1
) -> InlineKeyboardMarkup:
    """Savollar gridi (✅/❌ belgilari bilan) + ro'yxatga qaytish va asosiy menyu.

    Grid CHAPDAN O'NGGA to'ldiriladi: bir qatorda `QUESTION_GRID` ta tugma.
    """
    builder = InlineKeyboardBuilder()
    for unit in units:
        builder.button(
            text=unit.label,
            callback_data=AnalysisCallback(
                action="question",
                exam_id=exam_id,
                question=unit.number,
                part=unit.part,
                page=page,
            ),
        )
    builder.button(
        text="⬅️ Testlar ro'yxati",
        callback_data=AnalysisCallback(action="page", page=page),
    )
    builder.button(text=HOME_BUTTON, callback_data=AnalysisCallback(action="home"))
    # Diqqat: aiogram'da `adjust` tugmalar qo'shilgandan KEYIN chaqirilishi kerak
    # (u shu paytdagi tugmalar bo'yicha qatorlarni darhol tuzadi).
    builder.adjust(*solutions.grid_pattern(len(units)))
    return builder.as_markup()