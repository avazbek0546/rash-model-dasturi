"""Test rejimi: savollarni ketma-ket chiqarish va Rasch bo'yicha baholash.

Oqim:
    1. «Testni boshlash» → bazadan tasodifiy savollar tanlanadi (oson → qiyin);
    2. har bir javob Inline tugma orqali qabul qilinadi va keyingi savol chiqadi;
    3. oxirgi javobdan keyin θ (MLE) hisoblanadi, natija bazaga yoziladi va
       o'quvchiga batafsil izoh ko'rsatiladi.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
import texts
from database.models import SKIPPED, TestResult
from database.repository import Repositories
from keyboards.inline import (
    AnswerCallback,
    MenuCallback,
    after_test_kb,
    answer_kb,
    back_kb,
)
from services.test_session import TestSession, TestSessionStore
from states import TestStates

logger = logging.getLogger(__name__)

router = Router(name="test")


async def _send_question(
    target: Message, session: TestSession, *, edit: bool = False
) -> None:
    """Joriy savolni yuboradi (yoki mavjud xabarni tahrirlab yangilaydi)."""
    question = session.current_question
    if question is None:
        return

    text = texts.question(
        index=session.position,
        total=session.total,
        question=question,
        progress=session.progress_bar(),
        answered=session.answered_count,
    )
    markup = answer_kb(question)

    if edit:
        try:
            await target.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            logger.debug("Xabarni tahrirlab bo'lmadi — yangi savol xabari yuboriladi")

    await target.answer(text, reply_markup=markup)


async def _begin_test(
    target: Message,
    user_id: int,
    state: FSMContext,
    repos: Repositories,
    sessions: TestSessionStore,
    *,
    edit: bool = False,
) -> None:
    """Yangi test boshlaydi va birinchi savolni ko'rsatadi."""
    questions = await repos.questions.pick_random(config.QUESTIONS_PER_TEST)
    if not questions:
        await target.answer(texts.no_questions(), reply_markup=back_kb())
        return

    session = sessions.start(user_id, questions)
    await state.set_state(TestStates.in_progress)
    logger.info("Test boshlandi: user=%s, savollar=%s", user_id, session.total)
    await _send_question(target, session, edit=edit)


@router.callback_query(MenuCallback.filter(F.action == "start_test"))
async def start_test_callback(
    call: CallbackQuery,
    state: FSMContext,
    repos: Repositories,
    sessions: TestSessionStore,
) -> None:
    """«📝 Testni boshlash» tugmasi."""
    await call.answer()
    if call.message is None:
        return
    # Menyu xabarini birinchi savolga aylantiramiz (chat toza qoladi)
    await _begin_test(call.message, call.from_user.id, state, repos, sessions, edit=True)


@router.message(Command("test"))
async def start_test_command(
    message: Message,
    state: FSMContext,
    repos: Repositories,
    sessions: TestSessionStore,
) -> None:
    """`/test` komandasi."""
    if message.from_user is None:
        return
    await _begin_test(message, message.from_user.id, state, repos, sessions)


async def _finish_test(
    target: Message,
    user_id: int,
    session: TestSession,
    state: FSMContext,
    repos: Repositories,
    sessions: TestSessionStore,
) -> None:
    """Testni yakunlaydi: Rasch bahosi, bazaga yozish va natijani ko'rsatish."""
    estimate = session.evaluate()

    await repos.results.add(
        TestResult(
            user_id=user_id,
            raw_score=estimate.raw_score,
            total_questions=estimate.total_items,
            theta_score=estimate.theta,
            final_scaled_score=estimate.scaled_score,
        )
    )
    logger.info(
        "Test yakunlandi: user=%s, %s/%s to'g'ri, theta=%.3f, scaled=%.1f, chegara=%s",
        user_id,
        estimate.raw_score,
        estimate.total_items,
        estimate.theta,
        estimate.scaled_score,
        estimate.is_extreme,
    )

    sessions.clear(user_id)
    await state.clear()

    # Oxirgi savol kartochkasidagi tugmalarni olib tashlaymiz
    try:
        await target.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        logger.debug("Tugmalarni olib tashlab bo'lmadi (xabar eski bo'lishi mumkin)")

    await target.answer(
        texts.result_summary(estimate, session.questions, session.answers),
        reply_markup=after_test_kb(),
    )
    for chunk in texts.result_breakdown(estimate, session.questions, session.answers):
        await target.answer(chunk)


@router.callback_query(AnswerCallback.filter(), TestStates.in_progress)
async def handle_answer(
    call: CallbackQuery,
    callback_data: AnswerCallback,
    state: FSMContext,
    repos: Repositories,
    sessions: TestSessionStore,
) -> None:
    """A/B/C/D yoki «Bilmayman» tugmasi bosilganda."""
    if call.message is None:
        await call.answer()
        return

    session = sessions.get(call.from_user.id)
    if session is None:
        await call.answer()
        await state.clear()
        await call.message.answer(texts.session_lost(), reply_markup=back_kb())
        return

    current = session.current_question
    if current is None or current.question_id != callback_data.question_id:
        # Eskirgan tugma (o'quvchi eski xabardagi variantni bosgan)
        await call.answer(texts.stale_button(), show_alert=False)
        return

    if not session.register_answer(callback_data.question_id, callback_data.option):
        await call.answer(texts.stale_button(), show_alert=False)
        return

    # Javob to'g'ri yoki noto'g'riligi test davomida AYTILMAYDI —
    # aks holda keyingi savollarga ta'sir qiladi (o'lchov tozaligi uchun).
    if callback_data.option.upper() == SKIPPED:
        await call.answer(texts.skipped_notice(), show_alert=False)
    else:
        await call.answer()

    if session.is_finished:
        await _finish_test(call.message, call.from_user.id, session, state, repos, sessions)
    else:
        await _send_question(call.message, session, edit=True)


@router.callback_query(MenuCallback.filter(F.action == "finish"), TestStates.in_progress)
async def finish_test_early(
    call: CallbackQuery,
    state: FSMContext,
    repos: Repositories,
    sessions: TestSessionStore,
) -> None:
    """«🛑 Testni yakunlash» tugmasi — qolgan savollar noto'g'ri hisoblanadi."""
    if call.message is None:
        await call.answer()
        return

    session = sessions.get(call.from_user.id)
    if session is None:
        await call.answer()
        await state.clear()
        await call.message.answer(texts.session_lost(), reply_markup=back_kb())
        return

    if session.answered_count == 0:
        await call.answer(
            "Siz hali birorta savolga javob bermadingiz — avval javob tanlang.",
            show_alert=True,
        )
        return

    await call.answer()
    await _finish_test(call.message, call.from_user.id, session, state, repos, sessions)