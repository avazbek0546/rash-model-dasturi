"""O'qituvchi uchun `/new_exam` ustasi: yangi imtihon yaratish.

Har qadamda bitta ma'lumot so'raladi va darhol tekshiriladi (xato bo'lsa
qadam takrorlanadi). Yakunda xulosa ko'rsatilib, tasdiqlangandan keyin imtihon
bazaga yoziladi. Ustani istalgan qadamda `/cancel` yoki «❌ Bekor qilish»
tugmasi bilan to'xtatish mumkin.

Kalit formati (ikkalasi ham item-level)
---------------------------------------
* **Oddiy A–D** kalit (`1A2B3C…`) → `exams` yozuvi **va** item-level forma
  (`forms`, `form_versions`, `form_items`, `items`, `item_versions`) hamda
  `exam_sessions` yaratiladi. Sonli savollar (36–45) kalitda bo'lmaydi —
  ular `answer_spec.accepted = []` bilan saqlanadi (ixtiyoriy, "noto'g'ri").
* **MVP** kalit (`1A…35F|36:12.5,37:3`) → xuddi shu oqim, faqat 36–45 uchun
  qiymatlar kalitda ko'rsatiladi.
  `FormBuildError` o'qituvchiga o'zbekcha ko'rsatiladi.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
import texts
from database.repository import Repositories
from handlers.access import is_admin, log_denied
from keyboards.inline import ExamAdminCallback, cancel_kb, exam_confirm_kb
from services import answer_key, exam_service, form_builder, form_layout
from states import ExamCreateStates

logger = logging.getLogger(__name__)

router = Router(name="admin_exam")

SKIP_WORDS = {"-", "—", "skip", "yo'q", "yoq", "0.0", "none"}

#: Xulosada nechta savolning juftligi ko'rsatiladi (qolganlari "…" bilan).
PREVIEW_LIMIT = 8


def _format_difficulties_preview(values: Sequence[float]) -> str:
    """Logitlarni o'qituvchi tushunadigan ko'rinishga keltiradi.

    Ko'rinish: ``90%→-2.20, 75%→-1.10, …`` — ya'ni kiritilgan foiz (teskari
    o'tkazish orqali) va undan hosil bo'lgan logit. Savollar ko'p bo'lsa faqat
    birinchi ``PREVIEW_LIMIT`` tasi ko'rsatiladi.
    """
    items = list(values)
    parts = [
        f"{exam_service.logit_to_percent(value):.0f}%→{value:+.2f}"
        for value in items[:PREVIEW_LIMIT]
    ]
    if len(items) > PREVIEW_LIMIT:
        parts.append("…")
    return ", ".join(parts)


def _state_logits(data: dict[str, Any]) -> list[float] | None:
    """FSM holatidagi JSON logitlarni FormBuilder kutgan ro'yxatga aylantiradi.

    Ustada logitlar `exam_service.difficulties_to_json()` orqali JSON satr
    ko'rinishida saqlanadi (masalan ``"[0.0, 0.0, …]"``), `form_builder` esa
    sonlar ro'yxatini kutadi. Bo'sh yoki buzuq qiymatda `None` qaytariladi —
    builder uni o'zi qayta tekshiradi.
    """
    raw = str(data.get("difficulty_logits") or "").strip()
    if not raw:
        return None
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(values, (int, float)):
        return [float(values)]
    if isinstance(values, list):
        try:
            return [float(value) for value in values]
        except (TypeError, ValueError):
            return None
    return None


async def _prepare_session(
    repos: Repositories,
    data: dict[str, Any],
    form_result: form_builder.FormBuildResult,
    user_id: int,
) -> int | None:
    """MVP forma uchun `exam_sessions` yozuvini tayyorlaydi (vaqt oynasi).

    Jadval vaqtlari ustada allaqachon tekshirilgan (UTC ISO). Sessiya yozuvi
    yaratilmasa ham forma + legacy imtihon saqlanib qoladi — shu sababli xato
    yutiladi va faqat logga yoziladi.
    """
    try:
        return await repos.sessions.create(
            form_id=form_result.form_id,
            start_time=str(data.get("start_time")),
            end_time=str(data.get("end_time")),
            result_time=str(data.get("result_time")),
            title=str(data.get("title")),
            created_by=user_id,
        )
    except Exception:  # sessiya ixtiyoriy — asosiy oqimni to'xtatmaymiz
        logger.exception(
            "exam_sessions yozuvi yaratilmadi (form_id=%s)", form_result.form_id
        )
        return None


async def _ask(message: Message, state: FSMContext, step: Any, prompt: str) -> None:
    """Holatni o'rnatadi va keyingi savolni yuboradi."""
    await state.set_state(step)
    await message.answer(prompt, reply_markup=cancel_kb())


async def _start_wizard(target: Message, state: FSMContext, user_id: int) -> None:
    """Ustani boshidan boshlaydi."""
    await state.clear()
    await state.update_data(created_by=user_id)
    await _ask(target, state, ExamCreateStates.title, texts.new_exam_intro())


@router.message(Command("new_exam"))
async def cmd_new_exam(message: Message, state: FSMContext) -> None:
    """`/new_exam` — yangi imtihon yaratish ustasini boshlaydi."""
    if message.from_user is None:
        return
    if not is_admin(message.from_user.id):
        log_denied("/new_exam", message.from_user.id, message.from_user.full_name)
        await message.answer(texts.not_admin())
        return

    await _start_wizard(message, state, message.from_user.id)


@router.callback_query(ExamAdminCallback.filter(F.action == "new"))
async def new_exam_callback(call: CallbackQuery, state: FSMContext) -> None:
    """Callback: yangi imtihon ustasini boshlash (eski xabarlardagi tugma uchun).

    Asosiy menyuda «➕ Yangi imtihon» tugmasi endi ko'rsatilmaydi — imtihon
    Mini App'dagi «⚙️ Test yaratish» panelida yoki `/new_exam` bilan yaratiladi.
    """
    if call.message is None:
        await call.answer()
        return
    if not is_admin(call.from_user.id):
        log_denied("new_exam:tugma", call.from_user.id, call.from_user.full_name)
        await call.answer(texts.not_admin(), show_alert=True)
        return

    await call.answer()
    await _start_wizard(call.message, state, call.from_user.id)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Ustani bekor qiladi (istalgan qadamda)."""
    current = await state.get_state()
    await state.clear()
    if current is None:
        await message.answer("ℹ️ Bekor qilinadigan jarayon yo'q.")
        return
    await message.answer(texts.wizard_cancelled())


# ---------------------------------------------------------------------------
# Usta qadamlari
# ---------------------------------------------------------------------------
@router.message(ExamCreateStates.title)
async def step_title(message: Message, state: FSMContext) -> None:
    """1-qadam: imtihon nomi."""
    try:
        title = exam_service.validate_title(message.text or "")
    except ValueError as exc:
        await message.answer(texts.input_error(str(exc)))
        return

    await state.update_data(title=title)
    await _ask(
        message,
        state,
        ExamCreateStates.test_code,
        texts.ask_test_code(config.MIN_TEST_CODE_LENGTH),
    )


@router.message(ExamCreateStates.test_code)
async def step_test_code(message: Message, state: FSMContext, repos: Repositories) -> None:
    """2-qadam: test kodi (unikal bo'lishi shart)."""
    try:
        code = exam_service.validate_test_code(message.text or "")
    except ValueError as exc:
        await message.answer(texts.input_error(str(exc)))
        return

    if await repos.exams.code_exists(code):
        await message.answer(
            texts.input_error(f"«{code}» kodi allaqachon ishlatilgan — boshqa kod tanlang.")
        )
        return

    await state.update_data(test_code=code)
    await _ask(message, state, ExamCreateStates.total_questions, texts.ask_total_questions())


@router.message(ExamCreateStates.total_questions)
async def step_total_questions(message: Message, state: FSMContext) -> None:
    """3-qadam: savollar soni."""
    raw = " ".join((message.text or "").split())
    if not raw.isdigit() or not 1 <= int(raw) <= 100:
        await message.answer(
            texts.input_error("Savollar soni 1 dan 100 gacha butun son bo'lishi kerak.")
        )
        return

    total = int(raw)
    await state.update_data(total_questions=total)
    await _ask(message, state, ExamCreateStates.answer_key, texts.ask_answer_key(total))


def parse_answer_key_input(raw: str, total: int) -> str:
    """Kiritilgan kalitni kanonik (saqlanadigan) ko'rinishga aylantiradi.

    Uch format qo'llab-quvvatlanadi:

    * **qismli** — ``1A…35F|36a:√5,36b:3/7`` → `parse_labeled_key` + `build_canonical`
      (belgilar saqlanadi: `36a`, `36b`);
    * **MVP** — ``1A…35F|36:12.5,37:3`` → `parse_key` + `build_canonical`;
    * **legacy** — ``1A2B3C…`` → `format_compact` (xulq o'zgarmagan).

    Raises:
        answer_key.AnswerKeyError: kalit formati buzuq bo'lsa.
    """
    if form_layout.is_labeled_key(raw):
        letters, numeric = form_layout.parse_labeled_key(raw, total)
        return form_layout.build_canonical(letters, numeric)
    if form_layout.is_mvp_key(raw):
        letters, numeric = form_layout.parse_key(raw, total)
        return form_layout.build_canonical(letters, numeric)
    letters = answer_key.parse_answer_key(raw, total)
    return answer_key.format_compact(letters)


@router.message(ExamCreateStates.answer_key)
async def step_answer_key(message: Message, state: FSMContext) -> None:
    """4-qadam: javoblar kaliti.

    Uch format qabul qilinadi (opt-in):
      * qismli: `1A…35F|36a:√5,36b:3/7` — 36–45 har bir qism alohida savol;
      * MVP: `1A…35F|36:12.5,37:3` — 1–32 A–D, 33–35 A–F, 36–45 sonli;
      * eski: `1A2B3C…` — faqat A–D harflar (xulq o'zgarmagan).
    """
    data = await state.get_data()
    total = int(data.get("total_questions", 0))
    raw = message.text or ""

    try:
        stored = parse_answer_key_input(raw, total)
    except (answer_key.AnswerKeyError, ValueError) as exc:
        await message.answer(texts.input_error(str(exc)))
        return

    await state.update_data(answer_key=stored)
    await _ask(
        message,
        state,
        ExamCreateStates.difficulties,
        texts.ask_difficulties(total),
    )


@router.message(ExamCreateStates.difficulties)
async def step_difficulties(message: Message, state: FSMContext) -> None:
    """5-qadam: qiyinchilik foizda (bo'sh bo'lsa — 0.0; logit avtomatik hisoblanadi)."""
    data = await state.get_data()
    total = int(data.get("total_questions", 0))

    raw = " ".join((message.text or "").split())
    if raw.lower() in SKIP_WORDS:
        raw = ""

    try:
        values = exam_service.parse_difficulties_input(raw, total)
    except ValueError as exc:
        await message.answer(texts.input_error(str(exc)))
        return

    if any(values):
        shown = _format_difficulties_preview(values)
    else:
        shown = f"0.0 (barcha {total} savol)"

    await state.update_data(
        difficulty_logits=exam_service.difficulties_to_json(values),
        difficulties_text=shown,
    )
    await _ask(message, state, ExamCreateStates.start_time, texts.ask_start_time())


@router.message(ExamCreateStates.start_time)
async def step_start_time(message: Message, state: FSMContext) -> None:
    """6-qadam: javob qabul qilish boshlanishi."""
    try:
        moment = exam_service.parse_local_datetime(message.text or "")
    except ValueError as exc:
        await message.answer(texts.input_error(str(exc)))
        return

    await state.update_data(start_time=exam_service.to_db_time(moment))
    await _ask(message, state, ExamCreateStates.end_time, texts.ask_end_time())


@router.message(ExamCreateStates.end_time)
async def step_end_time(message: Message, state: FSMContext) -> None:
    """7-qadam: javob qabul qilish tugashi."""
    try:
        moment = exam_service.parse_local_datetime(message.text or "")
    except ValueError as exc:
        await message.answer(texts.input_error(str(exc)))
        return

    data = await state.get_data()
    start = exam_service.parse_db_time(str(data.get("start_time")))
    try:
        exam_service.validate_schedule(start, moment, moment)
    except ValueError as exc:
        await message.answer(texts.input_error(str(exc)))
        return

    await state.update_data(end_time=exam_service.to_db_time(moment))
    await _ask(message, state, ExamCreateStates.result_time, texts.ask_result_time())


@router.message(ExamCreateStates.result_time)
async def step_result_time(message: Message, state: FSMContext) -> None:
    """8-qadam: natijalar e'lon qilinishi va xulosa."""
    try:
        moment = exam_service.parse_local_datetime(message.text or "")
    except ValueError as exc:
        await message.answer(texts.input_error(str(exc)))
        return

    data = await state.get_data()
    start = exam_service.parse_db_time(str(data.get("start_time")))
    end = exam_service.parse_db_time(str(data.get("end_time")))
    try:
        exam_service.validate_schedule(start, end, moment)
    except ValueError as exc:
        await message.answer(texts.input_error(str(exc)))
        return

    result_db = exam_service.to_db_time(moment)
    await state.update_data(result_time=result_db)
    await state.set_state(ExamCreateStates.confirm)

    await message.answer(
        texts.exam_summary(
            title=str(data.get("title")),
            test_code=str(data.get("test_code")),
            total_questions=int(data.get("total_questions", 0)),
            answer_key=str(data.get("answer_key")),
            difficulties=str(data.get("difficulties_text")),
            start_local=exam_service.format_local(str(data.get("start_time"))),
            end_local=exam_service.format_local(str(data.get("end_time"))),
            result_local=exam_service.format_local(result_db),
        ),
        reply_markup=exam_confirm_kb(),
    )


# ---------------------------------------------------------------------------
# Tasdiqlash / bekor qilish
# ---------------------------------------------------------------------------
@router.callback_query(ExamAdminCallback.filter(F.action == "confirm"), ExamCreateStates.confirm)
async def confirm_exam(call: CallbackQuery, state: FSMContext, repos: Repositories) -> None:
    """«✅ Yaratish» — imtihonni va item-level formani yozadi.

    Oqim (kalit formatidan qat'i nazar bir xil):
        1. `exams` yozuvi yaratiladi (legacy baholash manbasi).
        2. `form_builder.create_form()` chaqirilib `forms` + `form_versions` +
           `form_items` + `items` + `item_versions` yaratiladi va
           `exam_sessions` metadatasi tayyorlanadi.
        3. `FormBuildError` bo'lsa — o'qituvchiga o'zbekcha ko'rsatiladi va
           qisman yozuv qolmasligi uchun imtihon o'chiriladi.
    """
    if call.message is None:
        await call.answer()
        return
    if not is_admin(call.from_user.id):
        log_denied("new_exam:confirm", call.from_user.id, call.from_user.full_name)
        await call.answer(texts.not_admin(), show_alert=True)
        return

    data = await state.get_data()
    await state.clear()
    await call.answer("Imtihon yaratilmoqda…")

    # 1) Legacy imtihon yozuvi (`exams`) — eski oqim o'zgarmagan holda saqlanadi.
    try:
        exam_id = await repos.exams.create(
            title=str(data.get("title")),
            test_code=str(data.get("test_code")),
            start_time=str(data.get("start_time")),
            end_time=str(data.get("end_time")),
            result_time=str(data.get("result_time")),
            total_questions=int(data.get("total_questions", 0)),
            answer_key=str(data.get("answer_key")),
            difficulty_logits=str(data.get("difficulty_logits")),
            created_by=call.from_user.id,
        )
    except Exception:  # baza xatosi (masalan, kod band bo'lib qolgan)
        logger.exception("Imtihon yaratishda xatolik")
        await call.message.answer(
            "⚠️ Imtihonni saqlashda xatolik yuz berdi.\nQaytadan urinib ko'ring: /new_exam"
        )
        return

    # 2) Kalit formatidan QAT'I NAZAR item-level forma + sessiya yaratiladi.
    #    Legacy A–D ham, MVP (`|` blokli) ham bir xil oqimdan o'tadi: aks holda
    #    `exam_sessions` yaratilmaydi va `/api/v2/*` 404 qaytaradi (M1).
    answer_key_text = str(data.get("answer_key") or "")
    form_result: form_builder.FormBuildResult | None = None
    session_id: int | None = None
    try:
        form_result = await form_builder.create_form(
            repos,
            title=str(data.get("title")),
            test_code=str(data.get("test_code")),
            total_questions=int(data.get("total_questions", 0)),
            answer_key=answer_key_text,
            difficulty_logits=_state_logits(data),
            created_by=call.from_user.id,
        )
    except form_builder.FormBuildError as exc:
        # Kiritish xatosi — o'qituvchiga o'zbekcha ko'rsatiladi; qisman
        # saqlanib qolmasligi uchun legacy imtihon ham o'chiriladi.
        logger.warning("Item-level forma yaratilmadi (FormBuildError): %s", exc)
        await repos.exams.delete(exam_id)
        await call.message.edit_text(texts.form_build_error(str(exc)))
        return
    except Exception:  # kutilmagan baza xatosi
        logger.exception("Item-level formani yaratishda kutilmagan xatolik")
        await repos.exams.delete(exam_id)
        await call.message.edit_text(
            texts.form_build_error("Formani saqlashda texnik xatolik yuz berdi.")
        )
        return

    # exam_sessions uchun metadata: forma + jadval vaqtlari asosida sessiya.
    session_id = await _prepare_session(repos, data, form_result, call.from_user.id)

    logger.info(
        "Yangi imtihon yaratildi: exam_id=%s, kod=%s, admin=%s, form_id=%s, session_id=%s",
        exam_id,
        data.get("test_code"),
        call.from_user.id,
        form_result.form_id if form_result is not None else None,
        session_id,
    )

    message = texts.exam_created(
        exam_id=exam_id,
        title=str(data.get("title")),
        test_code=str(data.get("test_code")),
        total_questions=int(data.get("total_questions", 0)),
        start_local=exam_service.format_local(str(data.get("start_time"))),
        end_local=exam_service.format_local(str(data.get("end_time"))),
        result_local=exam_service.format_local(str(data.get("result_time"))),
    )
    if form_result is not None:
        version_row = await repos.forms.get_version(form_result.form_version_id)
        version_no = int(version_row.get("version_no") or 1) if version_row else 1
        message += "\n\n" + texts.form_created(
            form_id=form_result.form_id,
            form_version_id=form_result.form_version_id,
            version_no=version_no,
            total_questions=form_result.total_questions,
            kinds=form_result.kinds,
            session_id=session_id,
        )
    await call.message.edit_text(message)


@router.callback_query(ExamAdminCallback.filter(F.action == "cancel"))
async def cancel_wizard(call: CallbackQuery, state: FSMContext) -> None:
    """«❌ Bekor qilish» tugmasi."""
    await state.clear()
    await call.answer()
    if call.message is not None:
        await call.message.edit_text(texts.wizard_cancelled())
