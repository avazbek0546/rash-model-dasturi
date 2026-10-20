"""«🔍 Test tahlili» bo'limi (o'quvchi uchun).

Oqim
----
1. Asosiy inline menyudagi «🔍 Test tahlili» tugmasi (yoki eski reply
   tugmasi / `/tahlil`) → o'quvchi topshirgan va natijasi e'lon qilingan
   imtihonlar ro'yxati (sahifalash bilan);
2. imtihon tanlanadi → savollar gridi (✅/❌ belgilari bilan; A/B qismli
   savollar «✅ 36a», «❌ 36b» ko'rinishida);
3. savol tanlanadi → bazadagi video yoki rasm yechim (`file_id`) yuboriladi;
   post oxiriga «#javob-rashtest1612-3» hashtagi qo'shiladi. Matnli yechim
   qo'llanmaydi — yechim faqat video yoki rasm bo'ladi.

Savol-javoblar `user_answers` jadvalidan, yechimlar `solutions` jadvalidan
olinadi — handler'lar SQL yozmaydi (faqat repository).
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramEntityTooLarge
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import texts
from database.models import Exam, SolutionType
from database.repository import Repositories
from handlers.start import send_main_menu
from keyboards.inline import (
    AnalysisCallback,
    AppCallback,
    analysis_exams_kb,
    analysis_home_kb,
    analysis_questions_kb,
    analysis_solution_kb,
)
from keyboards.reply import ANALYSIS_BUTTON
from services import exam_service, solutions

logger = logging.getLogger(__name__)

router = Router(name="analysis")


async def _render(target: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    """Mavjud xabarni tahrirlaydi; iloji bo'lmasa — yangisini yuboradi."""
    try:
        await target.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return  # ko'rinish o'zgarmadi — dublikat yubormaymiz
        # Eski xabar media bo'lsa (matn yo'q) — yangi xabar yuboriladi.
        await target.answer(text, reply_markup=markup)


async def _published_exams(user_id: int, repos: Repositories) -> list[Exam]:
    """O'quvchi qatnashgan va natijasi e'lon qilingan imtihonlar."""
    return await repos.exams.list_published_for_user(
        user_id, exam_service.now_db(), limit=solutions.MAX_ANALYSIS_EXAMS
    )


async def _send_exam_list(
    target: Message,
    *,
    user_id: int,
    full_name: str,
    page: int,
    repos: Repositories,
    edit: bool = False,
) -> None:
    """Imtihonlar ro'yxatini (sahifalab) yuboradi yoki mavjud xabarni tahrirlaydi."""
    exams = await _published_exams(user_id, repos)
    if not exams:
        text, markup = texts.analysis_empty(full_name), analysis_home_kb()
    else:
        window = solutions.paginate(exams, page)
        text, markup = texts.analysis_list(window, full_name), analysis_exams_kb(window)

    if edit:
        await _render(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.callback_query(AppCallback.filter(F.action == "analysis"))
async def open_analysis(call: CallbackQuery, repos: Repositories) -> None:
    """Asosiy menyudagi «🔍 Test tahlili» — ro'yxatni shu xabarda ochadi."""
    await call.answer()
    if call.message is None:
        return

    await _send_exam_list(
        call.message,
        user_id=call.from_user.id,
        full_name=call.from_user.full_name,
        page=1,
        repos=repos,
        edit=True,
    )


@router.message(Command("tahlil"))
@router.message(F.text == ANALYSIS_BUTTON)
async def show_test_analysis(message: Message, repos: Repositories) -> None:
    """«🔍 Test tahlili» tugmasi (yoki `/tahlil`) — imtihonlar ro'yxati."""
    if message.from_user is None:
        return

    await _send_exam_list(
        message,
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        page=1,
        repos=repos,
    )


@router.callback_query(AnalysisCallback.filter(F.action == "page"))
async def change_page(
    call: CallbackQuery, callback_data: AnalysisCallback, repos: Repositories
) -> None:
    """«⬅️ Oldingi», «Keyingi ➡️» va «⬅️ Testlar ro'yxati» tugmalari."""
    if call.message is None:
        await call.answer()
        return

    await call.answer()
    exams = await _published_exams(call.from_user.id, repos)
    if not exams:
        await _render(
            call.message, texts.analysis_empty(call.from_user.full_name), analysis_home_kb()
        )
        return

    window = solutions.paginate(exams, callback_data.page)
    await _render(
        call.message,
        texts.analysis_list(window, call.from_user.full_name),
        analysis_exams_kb(window),
    )


@router.callback_query(AnalysisCallback.filter(F.action == "exam"))
async def show_questions(
    call: CallbackQuery, callback_data: AnalysisCallback, repos: Repositories
) -> None:
    """Imtihon tanlandi → savollar gridi (✅/❌ belgilari bilan)."""
    if call.message is None:
        await call.answer()
        return

    exam = await repos.exams.get(callback_data.exam_id)
    submission = await repos.answers.get(call.from_user.id, callback_data.exam_id)

    if exam is None:
        await call.answer("Bu imtihon topilmadi (o'chirilgan bo'lishi mumkin).", show_alert=True)
        return
    if submission is None:
        await call.answer("Siz bu imtihonda qatnashmagansiz.", show_alert=True)
        return
    if exam.result_time > exam_service.now_db():
        await call.answer(
            "Natijalar hali e'lon qilinmagan.\n"
            f"E'lon qilinishi: {exam_service.format_local(exam.result_time)}",
            show_alert=True,
        )
        return

    await call.answer()
    parts = await repos.solutions.parts_for_exam(exam.exam_id)
    units = solutions.build_question_units(exam, submission, parts)

    await _render(
        call.message,
        texts.analysis_questions(
            label=solutions.exam_label(exam),
            title=exam.title,
            correct=solutions.raw_score(exam, submission),
            total=exam.total_questions,
        ),
        analysis_questions_kb(units, exam_id=exam.exam_id, page=callback_data.page),
    )


async def _send_media(
    target: Message,
    solution_type: str,
    file_id: str,
    caption: str,
    markup: InlineKeyboardMarkup,
    *,
    label: str,
) -> None:
    """Yechimni turiga mos Telegram metodi bilan yuboradi (klaviatura bilan).

    `file_id` eskirgan yoki fayl o'chirilgan bo'lsa — avval hujjat sifatida
    qayta uriniladi, u ham bo'lmasa o'quvchiga tushunarli xabar beriladi.
    """
    try:
        if solution_type == SolutionType.VIDEO.value:
            await target.answer_video(file_id, caption=caption, reply_markup=markup)
        elif solution_type == SolutionType.PHOTO.value:
            await target.answer_photo(file_id, caption=caption, reply_markup=markup)
        elif solution_type == SolutionType.ANIMATION.value:
            await target.answer_animation(file_id, caption=caption, reply_markup=markup)
        elif solution_type == SolutionType.AUDIO.value:
            await target.answer_audio(file_id, caption=caption, reply_markup=markup)
        else:  # document yoki noma'lum tur — hujjat sifatida
            await target.answer_document(file_id, caption=caption, reply_markup=markup)
    except (TelegramBadRequest, TelegramEntityTooLarge):
        logger.warning(
            "Yechimni yuborib bo'lmadi, hujjat sifatida qayta urinamiz: "
            "turi=%s, savol=%s",
            solution_type,
            label,
            exc_info=True,
        )
        try:
            await target.answer_document(file_id, caption=caption, reply_markup=markup)
            return
        except (TelegramBadRequest, TelegramEntityTooLarge):
            logger.error(
                "Yechim fayli yaroqsiz (file_id eskirgan bo'lishi mumkin): "
                "turi=%s, savol=%s",
                solution_type,
                label,
            )
        await target.answer(
            texts.solution_unavailable(label=label), reply_markup=markup
        )


@router.callback_query(AnalysisCallback.filter(F.action == "question"))
async def send_solution(
    call: CallbackQuery, callback_data: AnalysisCallback, repos: Repositories
) -> None:
    """Savol tugmasi bosildi → video yoki rasm yechimni yuborish.

    Matnli yechim qo'llanmaydi: bazada `file_id` bo'lmasa (eski `text` yozuv
    yoki yechim yuklanmagan bo'lsa) — «yechim hali yuklanmagan» xabari chiqadi.
    """
    if call.message is None:
        await call.answer()
        return

    exam = await repos.exams.get(callback_data.exam_id)
    if exam is None:
        await call.answer("Bu imtihon topilmadi (o'chirilgan bo'lishi mumkin).", show_alert=True)
        return

    # Qulf: natijalar e'lon qilinmaguncha yechim ochilmaydi (kalit himoyasi).
    # Ayniqsa «Yakunlash»dan keyin kelgan natija xabari tugmalari uchun muhim.
    if solutions.result_locked(exam, exam_service.now_db()):
        await call.answer(
            texts.solution_locked(result_time=exam_service.format_local(exam.result_time)),
            show_alert=True,
        )
        return

    label = f"{callback_data.question}{callback_data.part}"
    solution = await repos.solutions.get(
        exam.exam_id, callback_data.question, callback_data.part
    )
    hashtag = solutions.solution_hashtag(exam.test_code, callback_data.question, callback_data.part)
    await call.answer()

    # Yechim ostidagi klaviatura: «⬅️ Savollar ro'yxati» (shu imtihon gridiga)
    # va «🏡 Asosiy menyu». Shu tufayli o'quvchi tahlil oqimidan chiqib ketmaydi.
    nav_kb = analysis_solution_kb(exam_id=exam.exam_id, page=callback_data.page)

    if solution is None or not solution.is_file:
        await call.message.answer(
            texts.analysis_no_solution(label=label), reply_markup=nav_kb
        )
        return

    kind = solution.type
    caption = texts.solution_post(
        label=label,
        kind=kind.title,
        icon=kind.icon,
        hashtag=hashtag,
    )
    await _send_media(
        call.message,
        str(solution.solution_type),
        str(solution.solution_file_id),
        caption,
        nav_kb,
        label=label,
    )
    logger.info(
        "Yechim yuborildi: user_id=%s, exam_id=%s, savol=%s, turi=%s",
        call.from_user.id,
        exam.exam_id,
        label,
        solution.solution_type,
    )


@router.callback_query(AnalysisCallback.filter(F.action == "home"))
async def back_home(call: CallbackQuery) -> None:
    """«🏡 Asosiy menyu» tugmasi — reply va inline menyuni qaytaradi."""
    await call.answer()
    if call.message is None:
        return

    await send_main_menu(
        call.message,
        user_id=call.from_user.id,
        full_name=call.from_user.full_name,
        edit=True,
    )