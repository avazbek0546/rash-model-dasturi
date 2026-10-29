"""Imtihon yaratish — bot ustasi va Web App admin paneli uchun **YAGONA manba**.

`/new_exam` ustasi ham, Mini App'dagi «⚙️ Test yaratish» paneli ham shu moduldan
foydalanadi — yaratish mantig'i **ikki joyda takrorlanmaydi**.

Oqim (kalit formatidan qat'i nazar bir xil)::

    1. `exams` yozuvi — legacy baholash manbasi va admin ro'yxati uchun;
    2. `form_builder.create_form()` → `forms` + `form_versions` + `form_items`
       + `items` + `item_versions`;
    3. `exam_sessions` yozuvi — o'quvchi Web App oqimi uchun vaqt oynasi.

`form_builder.FormBuildError` bo'lsa — qisman yozuv qolmasligi uchun `exams`
yozuvi o'chiriladi va xatolik :class:`ExamAdminError` ko'rinishida uzatiladi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Sequence

from database.repository import Repositories
from services import exam_service, form_builder

logger = logging.getLogger(__name__)

#: Savollar soni chegaralari (kiritish tekshiruvi).
MIN_TOTAL_QUESTIONS: int = 1
MAX_TOTAL_QUESTIONS: int = 200


class ExamAdminError(ValueError):
    """Imtihon yaratishdagi kiritish xatosi (foydalanuvchiga ko'rsatiladi)."""


@dataclass(frozen=True, slots=True)
class CreatedExam:
    """Yaratilgan imtihon haqida qisqa natija (bot va Web App uchun)."""

    exam_id: int
    test_code: str
    title: str
    total_questions: int
    form_id: int | None
    form_version_id: int | None
    session_id: int | None
    kinds: dict[str, int]


@dataclass(frozen=True, slots=True)
class UpdatedSchedule:
    """Vaqti o'zgartirilgan imtihon haqida qisqa natija."""

    exam_id: int
    test_code: str
    session_id: int | None
    start_time: str
    end_time: str
    result_time: str


def normalize_difficulties(raw: Any, total_questions: int) -> list[float]:
    """Qiyinchilikni **logitlar ro'yxatiga** aylantiradi (validatsiya bilan).

    Qabul qiladi:

    * `None`/`""` → hamma savol uchun `0.0` (ma'lumot yo'q);
    * **matn** — foiz (`"90, 75, 50, 25"`) yoki logit (`"-1.2 0 1.1"`); bitta
      qiymat berilsa — barcha savolga qo'llanadi (`parse_difficulties_input`);
    * **ro'yxat** — tayyor logitlar (bitta qiymat → barchasiga).

    Raises:
        ExamAdminError: qiymatlar soni savollar soniga mos kelmasa.
    """
    total = int(total_questions)
    if raw in (None, ""):
        return [0.0] * total

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        try:
            values = [float(value) for value in raw]
        except (TypeError, ValueError) as exc:
            raise ExamAdminError("Qiyinchilik qiymatlari son bo'lishi kerak.") from exc
    else:
        try:
            return exam_service.parse_difficulties_input(str(raw), total)
        except ValueError as exc:
            raise ExamAdminError(str(exc)) from exc

    if len(values) == 1:
        values = values * total
    if len(values) != total:
        raise ExamAdminError(
            "Qiyinchilik qiymatlari soni savollar soniga teng bo'lishi kerak "
            f"({len(values)} ≠ {total})."
        )
    return values


async def _create_session(
    repos: Repositories,
    form_result: form_builder.FormBuildResult,
    *,
    title: str,
    start_time: str,
    end_time: str,
    result_time: str,
    created_by: int,
) -> int | None:
    """`exam_sessions` yozuvini yaratadi (ixtiyoriy — xato yutilsin)."""
    try:
        return await repos.sessions.create(
            form_id=form_result.form_id,
            start_time=str(start_time),
            end_time=str(end_time),
            result_time=str(result_time),
            title=title,
            created_by=created_by,
        )
    except Exception:  # sessiya ixtiyoriy — asosiy oqimni to'xtatmaymiz
        logger.exception(
            "exam_sessions yozuvi yaratilmadi (form_id=%s)", form_result.form_id
        )
        return None


async def create_exam(
    repos: Repositories,
    *,
    title: str,
    test_code: str,
    total_questions: int,
    answer_key: str,
    difficulty: Any = None,
    start_time: str,
    end_time: str,
    result_time: str,
    created_by: int,
) -> CreatedExam:
    """Imtihon + item-level forma + sessiyani yaratadi.

    `start_time`/`end_time`/`result_time` — **bazaga yoziladigan** (UTC ISO)
    qiymatlar; ularni chaqiruvchi tekshiradi (`exam_service.validate_schedule`).

    Raises:
        ExamAdminError: kiritish yoki forma yaratishdagi xatolik.
    """
    clean_title = exam_service.validate_title(title)
    code = exam_service.validate_test_code(test_code)
    total = int(total_questions)
    if not (MIN_TOTAL_QUESTIONS <= total <= MAX_TOTAL_QUESTIONS):
        raise ExamAdminError(
            f"Savollar soni {MIN_TOTAL_QUESTIONS}–{MAX_TOTAL_QUESTIONS} "
            "orasida bo'lishi kerak."
        )
    if not str(answer_key or "").strip():
        raise ExamAdminError("Javoblar kaliti bo'sh.")

    logits = normalize_difficulties(difficulty, total)

    exam_id = await repos.exams.create(
        title=clean_title,
        test_code=code,
        start_time=str(start_time),
        end_time=str(end_time),
        result_time=str(result_time),
        total_questions=total,
        answer_key=str(answer_key),
        difficulty_logits=exam_service.difficulties_to_json(logits),
        created_by=created_by,
    )

    try:
        form_result = await form_builder.create_form(
            repos,
            title=clean_title,
            test_code=code,
            total_questions=total,
            answer_key=str(answer_key),
            difficulty_logits=logits,
            created_by=created_by,
        )
    except form_builder.FormBuildError as exc:
        await repos.exams.delete(exam_id)  # qisman yozuv qolmasin
        logger.warning("Item-level forma yaratilmadi (FormBuildError): %s", exc)
        raise ExamAdminError(str(exc)) from exc
    except Exception as exc:  # kutilmagan baza xatosi
        await repos.exams.delete(exam_id)
        logger.exception("Item-level formani yaratishda kutilmagan xatolik")
        raise ExamAdminError("Formani saqlashda texnik xatolik yuz berdi.") from exc

    session_id = await _create_session(
        repos,
        form_result,
        title=clean_title,
        start_time=start_time,
        end_time=end_time,
        result_time=result_time,
        created_by=created_by,
    )

    logger.info(
        "Imtihon yaratildi: exam_id=%s, kod=%s, admin=%s, form_id=%s, session_id=%s",
        exam_id,
        code,
        created_by,
        form_result.form_id,
        session_id,
    )
    return CreatedExam(
        exam_id=exam_id,
        test_code=code,
        title=clean_title,
        total_questions=total,
        form_id=form_result.form_id,
        form_version_id=form_result.form_version_id,
        session_id=session_id,
        kinds=dict(form_result.kinds),
    )


async def update_exam_times(
    repos: Repositories,
    *,
    exam_id: int,
    start_time: str,
    end_time: str,
    result_time: str,
) -> UpdatedSchedule:
    """Yaratilgan imtihonning vaqt oynasini o'zgartiradi.

    Ikki jadval birga yangilanadi:

    * `exams` — botdagi `/exams`, eski v1 API va PDF hisobot manbasi;
    * `exam_sessions` — Web App item-level oqimi (`/api/v2/*`) vaqt oynasi.

    Agar yangi `end_time` hali kelmagan bo'lsa (imtihon qayta ochiladi),
    `graded_at` tozalanadi — fon baholash keyin qo'shilgan javoblarni ham
    hisoblashi uchun. Avvalgi o'quvchilarning natijalari o'chmaydi.

    Args:
        start_time, end_time, result_time: bazaga yoziladigan **UTC ISO**
            qiymatlar; tartib `exam_service.validate_schedule` bilan
            tekshiriladi.

    Raises:
        ExamAdminError: imtihon topilmasa yoki vaqt tartibi noto'g'ri bo'lsa.
    """
    exam = await repos.exams.get(int(exam_id))
    if exam is None:
        raise ExamAdminError("Imtihon topilmadi (o'chirilgan bo'lishi mumkin).")

    try:
        start_dt = exam_service.parse_db_time(str(start_time))
        end_dt = exam_service.parse_db_time(str(end_time))
        result_dt = exam_service.parse_db_time(str(result_time))
        exam_service.validate_schedule(start_dt, end_dt, result_dt)
    except ValueError as exc:
        raise ExamAdminError(str(exc)) from exc

    now = exam_service.now_db()
    reset_graded = str(end_time) > now

    await repos.exams.update_schedule(
        exam.exam_id,
        start_time=str(start_time),
        end_time=str(end_time),
        result_time=str(result_time),
        reset_graded_at=reset_graded,
    )

    session = await repos.sessions.get_by_test_code(exam.test_code)
    session_id: int | None = None
    if session is not None:
        session_id = int(session["session_id"])
        await repos.sessions.update_schedule(
            session_id,
            start_time=str(start_time),
            end_time=str(end_time),
            result_time=str(result_time),
            reset_graded_at=reset_graded,
        )

    logger.info(
        "Imtihon vaqti o'zgartirildi: exam_id=%s, kod=%s, start=%s, end=%s, "
        "result=%s, session_id=%s, graded_reset=%s",
        exam.exam_id,
        exam.test_code,
        start_time,
        end_time,
        result_time,
        session_id,
        reset_graded,
    )
    return UpdatedSchedule(
        exam_id=exam.exam_id,
        test_code=exam.test_code,
        session_id=session_id,
        start_time=str(start_time),
        end_time=str(end_time),
        result_time=str(result_time),
    )
