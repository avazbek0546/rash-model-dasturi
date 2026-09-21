"""Video/media yechimlarni bazaga yuklash (faqat o'qituvchi uchun).

Eng sodda oqim
--------------
1. Admin botga <b>video</b> (yoki rasm, hujjat, audio, animatsiya) yuboradi;
2. xabar izohida (caption) test kodi va savol raqami yoziladi:
       `rashtest1612 3`   ·   `#rashtest1612-3`   ·   `rashtest1612 36a`
3. bot faylning Telegram `file_id` sini avtomatik olib, bazadagi tegishli
   imtihon + savol raqamiga biriktiradi (`solutions` jadvali) va natijani
   adminga xabar qiladi.

Matnli tahlil uchun: `/add_solution rashtest1612 3 yechim matni…`.
Bir savolga qayta yuklansa — eski yozuv yangilanadi (dublikat yaratilmaydi).
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

import texts
from database.models import Exam, SolutionType
from database.repository import Repositories
from handlers.access import is_admin, log_denied
from keyboards.reply import UPLOAD_SOLUTION_BUTTON
from services import solutions as solution_service

logger = logging.getLogger(__name__)

router = Router(name="admin_solution")

# Qaysi xabar maydonidan qanday tur aniqlanadi (aiogram maydonlari).
MEDIA_FIELDS: tuple[tuple[str, str], ...] = (
    ("video", SolutionType.VIDEO.value),
    ("photo", SolutionType.PHOTO.value),
    ("document", SolutionType.DOCUMENT.value),
    ("animation", SolutionType.ANIMATION.value),
    ("audio", SolutionType.AUDIO.value),
)


def media_type_of(message: Message) -> str | None:
    """Xabardagi media turini qaytaradi (media bo'lmasa — None)."""
    for field, kind in MEDIA_FIELDS:
        if getattr(message, field, None) is not None:
            return kind
    return None


def media_file_id_of(message: Message) -> str | None:
    """Xabardagi faylning Telegram `file_id` sini qaytaradi."""
    if message.video is not None:
        return message.video.file_id
    if message.photo:
        return message.photo[-1].file_id  # eng katta o'lchamdagi rasm
    if message.document is not None:
        return message.document.file_id
    if message.animation is not None:
        return message.animation.file_id
    if message.audio is not None:
        return message.audio.file_id
    return None


class AdminMediaFilter(BaseFilter):
    """Faqat ADMIN yuborgan media xabarlarini o'tkazadi.

    Admin bo'lmagan foydalanuvchining media xabari bu filter'ga tushmaydi va
    odatdagi `fallback` handler'iga o'tadi (ular uchun hech narsa o'zgarmaydi).
    """

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None or not is_admin(message.from_user.id):
            return False
        return media_type_of(message) is not None


async def _resolve_exam(
    message: Message, repos: Repositories, target: solution_service.SolutionTarget
) -> Exam | None:
    """Test kodini topadi; topilmasa sababini xabar qilib None qaytaradi."""
    exam = await repos.exams.get_by_code(target.test_code)
    if exam is None:
        await message.answer(texts.solution_exam_not_found(target.test_code))
        return None
    if not 1 <= target.question_number <= exam.total_questions:
        await message.answer(
            texts.solution_out_of_range(
                test_code=exam.test_code,
                number=target.question_number,
                total=exam.total_questions,
            )
        )
        return None
    return exam


async def _save_solution(
    message: Message,
    repos: Repositories,
    *,
    exam_id: int,
    test_code: str,
    question_number: int,
    part: str,
    solution_type: str,
    file_id: str | None,
    solution_text: str | None,
) -> None:
    """Yechimni bazaga yozadi va adminga tasdiq xabarini yuboradi."""
    solution_id = await repos.solutions.upsert(
        exam_id=exam_id,
        question_number=question_number,
        part=part,
        solution_type=solution_type,
        solution_file_id=file_id,
        solution_text=solution_text,
        created_by=message.from_user.id if message.from_user else None,
    )
    label = f"{question_number}{part}"
    await message.answer(
        texts.solution_saved(
            test_code=test_code,
            label=label,
            kind=SolutionType(solution_type).title,
        )
    )
    logger.info(
        "Yechim saqlandi: solution_id=%s, exam_id=%s, savol=%s, turi=%s, admin=%s",
        solution_id,
        exam_id,
        label,
        solution_type,
        message.from_user.id if message.from_user else None,
    )


@router.message(Command("add_solution"))
async def cmd_add_solution(message: Message, repos: Repositories) -> None:
    """`/add_solution` — yo'riqnoma yoki matnli yechim yuklash."""
    if message.from_user is None:
        return
    if not is_admin(message.from_user.id):
        log_denied("/add_solution", message.from_user.id, message.from_user.full_name)
        await message.answer(texts.not_admin())
        return

    payload = (message.text or "").partition(" ")[2].strip()
    if not payload:
        await message.answer(texts.solution_admin_intro())
        return

    parsed = solution_service.parse_solution_target(payload)
    if parsed is None:
        await message.answer(texts.solution_caption_error())
        return

    target, body = parsed
    if not body:
        await message.answer(texts.solution_text_required())
        return

    exam = await _resolve_exam(message, repos, target)
    if exam is None:
        return

    await _save_solution(
        message,
        repos,
        exam_id=exam.exam_id,
        test_code=exam.test_code,
        question_number=target.question_number,
        part=target.part,
        solution_type=SolutionType.TEXT.value,
        file_id=None,
        solution_text=body,
    )


@router.message(AdminMediaFilter())
async def upload_media_solution(message: Message, repos: Repositories) -> None:
    """Admin yuborgan video/rasm/hujjatdan yechimni saqlaydi."""
    if message.from_user is None:
        return
    if not is_admin(message.from_user.id):  # filter'ga qo'shimcha himoya
        log_denied("add_solution:media", message.from_user.id, message.from_user.full_name)
        return

    target = solution_service.parse_solution_caption(message.caption or "")
    if target is None:
        await message.answer(texts.solution_caption_error())
        return

    exam = await _resolve_exam(message, repos, target)
    if exam is None:
        return

    await _save_solution(
        message,
        repos,
        exam_id=exam.exam_id,
        test_code=exam.test_code,
        question_number=target.question_number,
        part=target.part,
        solution_type=media_type_of(message) or SolutionType.VIDEO.value,
        file_id=media_file_id_of(message),
        solution_text=None,
    )


@router.message(F.text == UPLOAD_SOLUTION_BUTTON)
async def upload_solution_button(message: Message) -> None:
    """Reply menyudagi «🎬 Yechim yuklash» tugmasi."""
    if message.from_user is None:
        return
    if not is_admin(message.from_user.id):
        log_denied("add_solution:tugma", message.from_user.id, message.from_user.full_name)
        return
    await message.answer(texts.solution_admin_intro())