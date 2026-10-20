"""Video va rasm yechimlarni bazaga yuklash (faqat o'qituvchi uchun).

Oqim
----
1. Admin botga **video** yoki **rasm** yuboradi (matnli yechim qo'llanmaydi;
   audio, animatsiya va dumaloq video ham qabul qilinmaydi);
2. xabar izohida (caption) test kodi va savol raqami yoziladi:
       `rashtest1612 3`   ·   `#rashtest1612-3`   ·   `rashtest1612 36a`
3. yoki Mini App panelidagi «🎬 Yechimlar» → savol → yuklash tugmasi deep-link
   ochadi (`/start s_<kod>_<belgi>`) va media **izohsiz** qabul qilinadi;
4. bot faylning Telegram `file_id` sini avtomatik olib, bazadagi tegishli
   imtihon + savol raqamiga biriktiradi (`solutions` jadvali).

Bir savolga qayta yuklansa — eski yozuv yangilanadi (dublikat yaratilmaydi).
"""

from __future__ import annotations

import logging
import re
from typing import Final

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import texts
from database.models import Exam, SolutionType, normalize_part
from database.repository import Repositories
from handlers.access import is_admin, log_denied
from keyboards.reply import UPLOAD_SOLUTION_BUTTON
from services import solutions as solution_service
from states import SolutionUploadStates

logger = logging.getLogger(__name__)

router = Router(name="admin_solution")

#: Panel deep-link'i prefiksi: `/start s_<kod>_<belgi>` (masalan `s_MATH2026_36a`).
DEEP_LINK_PREFIX = "s_"

#: Savol belgisi: `12` yoki `36a`.
_LABEL_RE = re.compile(r"^(\d{1,3})([abAB]?)$")

#: Telegram Bot API (bulutli) tavsiya etilgan chegaralari — UI ogohlantirishi uchun.
MAX_VIDEO_MB: Final[int] = 50
MAX_PHOTO_MB: Final[int] = 10

# Qaysi xabar maydonidan qanday tur aniqlanadi (aiogram maydonlari).
MEDIA_FIELDS: tuple[tuple[str, str], ...] = (
    ("video", SolutionType.VIDEO.value),
    ("photo", SolutionType.PHOTO.value),
    ("document", SolutionType.DOCUMENT.value),
)

#: «Fayl sifatida» yuborilgan rasm/video uchun MIME prefikslari.
DOCUMENT_MIME_PREFIXES: Final[tuple[str, ...]] = ("image/", "video/")

#: MIME ko'rsatilmagan bo'lsa — fayl kengaytmasi bo'yicha tekshiriladi.
DOCUMENT_EXTENSIONS: Final[tuple[str, ...]] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".heic",
    ".heif",
    ".gif",
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".mkv",
)

#: Qo'llanmaydigan media maydonlari (aniq ogohlantirish uchun).
UNSUPPORTED_MEDIA_FIELDS: Final[tuple[str, ...]] = (
    "animation",
    "audio",
    "video_note",
    "voice",
    "sticker",
)


def document_is_media(document: object) -> bool:
    """Hujjat rasm yoki video ekanini aniqlaydi (MIME yoki kengaytma bo'yicha)."""
    mime = str(getattr(document, "mime_type", "") or "").lower()
    if mime:
        return mime.startswith(DOCUMENT_MIME_PREFIXES)
    name = str(getattr(document, "file_name", "") or "").lower()
    return name.endswith(DOCUMENT_EXTENSIONS)


def media_type_of(message: Message) -> str | None:
    """Xabardagi yechim turini qaytaradi (mos media bo'lmasa — None).

    Qabul qilinadi: **video**, **rasm** (`photo`) va rasm/video «fayl sifatida»
    yuborilgan `document`. Boshqa hujjat (PDF, DOCX, ...) yechim hisoblanmaydi.
    """
    for field, kind in MEDIA_FIELDS:
        payload = getattr(message, field, None)
        if payload is None:
            continue
        if field == "document" and not document_is_media(payload):
            return None
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
    return None


def media_size_mb_of(message: Message) -> float | None:
    """Fayl hajmi (MB) — Telegram metadatasidan (fayl yuklab olinmaydi)."""
    size = None
    if message.video is not None:
        size = message.video.file_size
    elif message.photo:
        size = message.photo[-1].file_size
    elif message.document is not None:
        size = message.document.file_size
    if not size:
        return None
    return round(float(size) / (1024 * 1024), 1)


class AdminMediaFilter(BaseFilter):
    """Faqat ADMIN yuborgan video/rasm/hujjat xabarlarini o'tkazadi."""

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None or not is_admin(message.from_user.id):
            return False
        return media_type_of(message) is not None


class AdminUnsupportedMediaFilter(BaseFilter):
    """Admin yuborgan, lekin yechim sifatida qabul qilinmaydigan media."""

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None or not is_admin(message.from_user.id):
            return False
        if media_type_of(message) is not None:
            return False  # qo'llanadigan media — `upload_media_solution` ishlaydi
        if message.document is not None:
            # PDF/DOCX kabi hujjatlar yechim emas (faqat rasm/video fayli).
            return not document_is_media(message.document)
        return any(
            getattr(message, field, None) is not None
            for field in UNSUPPORTED_MEDIA_FIELDS
        )


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
    file_id: str,
) -> None:
    """Yechimni bazaga yozadi va adminga tasdiq xabarini yuboradi.

    Fayl hajmi Telegram tavsiya etgan chegaradan katta bo'lsa yechim baribir
    saqlanadi, lekin o'qituvchi ogohlantiriladi (qayta yuborish `file_id`
    orqali odatda ishlaydi, ammo rasmiy kafolat yo'q).
    """
    solution_id = await repos.solutions.upsert(
        exam_id=exam_id,
        question_number=question_number,
        part=part,
        solution_type=solution_type,
        solution_file_id=file_id,
        created_by=message.from_user.id if message.from_user else None,
    )
    label = f"{question_number}{part}"
    kind = SolutionType(solution_type)
    await message.answer(
        texts.solution_saved(test_code=test_code, label=label, kind=kind.title)
    )
    logger.info(
        "Yechim saqlandi: solution_id=%s, exam_id=%s, savol=%s, turi=%s, "
        "hajm=%s MB, admin=%s",
        solution_id,
        exam_id,
        label,
        solution_type,
        media_size_mb_of(message),
        message.from_user.id if message.from_user else None,
    )
    limit = MAX_PHOTO_MB if kind is SolutionType.PHOTO else MAX_VIDEO_MB
    size_mb = media_size_mb_of(message)
    if size_mb is not None and size_mb > limit:
        await message.answer(
            texts.solution_size_warning(size_mb=size_mb, limit_mb=limit)
        )


# ---------------------------------------------------------------------------
# Panel deep-link'i: `/start s_<kod>_<belgi>` → holatni yoqish (izohsiz yuklash)
# ---------------------------------------------------------------------------
def parse_deep_link_payload(text: str) -> tuple[str, str] | None:
    """`/start s_<kod>_<belgi>` dan `(kod, belgi)` ni ajratadi.

    Qaytaradi: `("MATH2026", "36a")`; payload bu turdagi bo'lmasa — `None`.
    Test kodida `-` va `_` bo'lishi mumkin (`MS-MATH-2603`), shuning uchun
    ajratish **oxirgi** `_` bo'yicha qilinadi.
    """
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return None
    payload = parts[1].strip()
    if not payload.lower().startswith(DEEP_LINK_PREFIX):
        return None
    rest = payload[len(DEEP_LINK_PREFIX) :]
    code, separator, label = rest.rpartition("_")
    if not separator or not code or not label:
        return None
    return code, label


async def start_target_upload(
    message: Message, state: FSMContext, repos: Repositories, *, text: str
) -> bool:
    """Panel deep-link'i bo'yicha «keyingi mediani yuklash» holatini yoqadi.

    Qaytaradi: `True` — payload shu turdagi (javob berildi); `False` — tegishli
    emas (chaqiruvchi odatdagi `/start` menyusini ko'rsatadi).
    """
    if message.from_user is None:
        return False
    parsed = parse_deep_link_payload(text)
    if parsed is None:
        return False
    if not is_admin(message.from_user.id):
        log_denied("solution_link", message.from_user.id, message.from_user.full_name)
        return False

    code, label = parsed
    match = _LABEL_RE.match(label)
    number = int(match.group(1)) if match is not None else 0
    if match is None or number < 1:
        return False

    target = solution_service.SolutionTarget(
        test_code=code.upper(), question_number=number, part=normalize_part(match.group(2))
    )
    exam = await repos.exams.get_by_code(target.test_code)
    if exam is None:
        await message.answer(texts.solution_exam_not_found(target.test_code))
        return True
    if not 1 <= target.question_number <= int(exam.total_questions):
        await message.answer(
            texts.solution_out_of_range(
                test_code=exam.test_code,
                number=target.question_number,
                total=exam.total_questions,
            )
        )
        return True

    await state.set_state(SolutionUploadStates.awaiting_upload)
    await state.update_data(
        solution_exam_id=exam.exam_id,
        solution_test_code=exam.test_code,
        solution_number=target.question_number,
        solution_part=target.part,
    )
    await message.answer(
        texts.solution_link_prompt(
            title=exam.title, test_code=exam.test_code, label=target.label
        )
    )
    logger.info(
        "Deep-link: yuklash holati yoqildi (exam_id=%s, savol=%s, admin=%s)",
        exam.exam_id,
        target.label,
        message.from_user.id,
    )
    return True


@router.message(Command("add_solution"))
async def cmd_add_solution(message: Message) -> None:
    """`/add_solution` — video/rasm yechim yuklash yo'riqnomasi.

    Matnli yechim qo'llanmaydi: yechim faqat botga yuborilgan video yoki rasm
    (`file_id`) ko'rinishida saqlanadi.
    """
    if message.from_user is None:
        return
    if not is_admin(message.from_user.id):
        log_denied("/add_solution", message.from_user.id, message.from_user.full_name)
        await message.answer(texts.not_admin())
        return

    await message.answer(texts.solution_admin_intro())


@router.message(AdminMediaFilter())
async def upload_media_solution(
    message: Message, repos: Repositories, state: FSMContext
) -> None:
    """Admin yuborgan video/rasmdan yechimni saqlaydi.

    Belgilash ikki yo'l bilan bo'ladi: **(1)** izoh orqali (`rashtest1612 3`) —
    eski oqim o'zgarmaydi; **(2)** panel deep-link'i yoqgan holat orqali —
    **izohsiz** (`/start s_<kod>_<belgi>`).
    """
    if message.from_user is None:
        return
    if not is_admin(message.from_user.id):  # filter'ga qo'shimcha himoya
        log_denied("add_solution:media", message.from_user.id, message.from_user.full_name)
        return

    target = solution_service.parse_solution_caption(message.caption or "")
    if target is None:
        # Deep-link (panel) yoqilgan bo'lsa — maqsadni holatdan olamiz.
        data = await state.get_data()
        if data.get("solution_exam_id"):
            target = solution_service.SolutionTarget(
                test_code=str(data.get("solution_test_code") or ""),
                question_number=int(data.get("solution_number") or 0),
                part=str(data.get("solution_part") or ""),
            )
    if target is None:
        await message.answer(texts.solution_caption_error())
        return

    exam = await _resolve_exam(message, repos, target)
    if exam is None:
        return

    file_id = media_file_id_of(message)
    if not file_id:
        await message.answer(texts.solution_media_required())
        return

    await _save_solution(
        message,
        repos,
        exam_id=exam.exam_id,
        test_code=exam.test_code,
        question_number=target.question_number,
        part=target.part,
        solution_type=media_type_of(message) or SolutionType.VIDEO.value,
        file_id=file_id,
    )
    # Holat bir marta ishlatiladi — keyingi media yana izoh orqali bo'ladi.
    await state.clear()


@router.message(AdminUnsupportedMediaFilter())
async def reject_unsupported_media(message: Message) -> None:
    """Admin audio/animatsiya/dumaloq video yuborsa — aniq ogohlantirish."""
    if message.from_user is None:
        return
    if not is_admin(message.from_user.id):  # filter'ga qo'shimcha himoya
        log_denied("add_solution:media", message.from_user.id, message.from_user.full_name)
        return
    await message.answer(texts.solution_media_required())


@router.message(F.text == UPLOAD_SOLUTION_BUTTON)
async def upload_solution_button(message: Message) -> None:
    """Reply menyudagi «🎬 Yechim yuklash» tugmasi."""
    if message.from_user is None:
        return
    if not is_admin(message.from_user.id):
        log_denied("add_solution:tugma", message.from_user.id, message.from_user.full_name)
        return
    await message.answer(texts.solution_admin_intro())