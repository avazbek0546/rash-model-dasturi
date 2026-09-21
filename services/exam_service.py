"""Imtihon hayot sikli: holat, vaqt konvertatsiyasi va kiritishlarni tekshirish.

Vaqt bilan ishlash qoidasi
--------------------------
* Bazada (va SQL taqqoslashlarida) — **UTC ISO-8601**: "2026-01-01T05:00:00+00:00".
  Format qat'iy bir xil bo'lgani uchun satrlarni bevosita taqqoslash to'g'ri
  natija beradi (`end_time <= ?` kabi shartlar ishlaydi).
* O'qituvchi kiritadigan va foydalanuvchiga ko'rsatiladigan vaqtlar —
  `config.TIMEZONE` zonasida (standart: Asia/Tashkent, UTC+5).
* Agar tizimda IANA vaqt zonasi bazasi (`tzdata` paketi) bo'lmasa (Windows'da
  ko'p uchraydi), qat'iy UTC+5 ofseti ishlatiladi — O'zbekistonda yozgi vaqt
  qo'llanilmaydi, shu sababli natija bir xil bo'ladi.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from typing import Sequence

import config
from database.models import Exam, ExamStatus

logger = logging.getLogger(__name__)

# Barcha vaqtlar bazada shu formatda saqlanadi (UTC, qat'iy uzunlik).
DB_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"

# O'qituvchi kiritishida qabul qilinadigan formatlar (birinchisi mos kelsa olinadi).
LOCAL_INPUT_FORMATS: tuple[str, ...] = (
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)

DEFAULT_TZ_OFFSET_HOURS = 5  # Asia/Tashkent (yozgi vaqtsiz)


@lru_cache(maxsize=4)
def local_zone() -> tzinfo:
    """`config.TIMEZONE` zonasini qaytaradi (tzdata bo'lmasa — UTC+5)."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(config.TIMEZONE)
    except Exception:  # muhitga bog'liq: tzdata paketi bo'lmasa
        logger.warning(
            "Vaqt zonasi %r topilmadi (tzdata paketi yo'q bo'lishi mumkin) — UTC+%d ishlatiladi",
            config.TIMEZONE,
            DEFAULT_TZ_OFFSET_HOURS,
        )
        return timezone(timedelta(hours=DEFAULT_TZ_OFFSET_HOURS), name="UTC+5")


def utc_now() -> datetime:
    """Hozirgi vaqt (UTC, timezone-aware)."""
    return datetime.now(timezone.utc)


def to_db_time(moment: datetime) -> str:
    """`datetime` ni bazadagi UTC ISO satriga aylantiradi."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime(DB_TIME_FORMAT)


def now_db() -> str:
    """Hozirgi vaqtni bazadagi formatda qaytaradi (SQL taqqoslash uchun)."""
    return to_db_time(utc_now())


def parse_db_time(value: str) -> datetime:
    """Bazadagi vaqt satrini `datetime` ga aylantiradi (UTC)."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def to_local(value: str | datetime) -> datetime:
    """UTC vaqtni (satr yoki datetime) mahalliy zonaga o'tkazadi."""
    moment = parse_db_time(value) if isinstance(value, str) else value
    return moment.astimezone(local_zone())


def format_local(value: str | datetime, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Vaqtni foydalanuvchi ko'radigan mahalliy ko'rinishga keltiradi."""
    return to_local(value).strftime(fmt)


def parse_local_datetime(text: str) -> datetime:
    """O'qituvchi kiritgan vaqtni mahalliy zonadagi `datetime` ga aylantiradi.

    Raises:
        ValueError: format tanib olinmasa.
    """
    cleaned = " ".join((text or "").strip().replace("T", " ").replace(",", " ").split())
    for fmt in LOCAL_INPUT_FORMATS:
        try:
            moment = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        if fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            moment = moment.replace(hour=0, minute=0)
        return moment.replace(tzinfo=local_zone())
    raise ValueError(
        f"Vaqt formati tushunarli emas: {text!r}. "
        "Masalan: 15.01.2026 09:00 yoki 2026-01-15 09:00"
    )


# ---------------------------------------------------------------------------
# Holat mantig'i
# ---------------------------------------------------------------------------
STATUS_TITLES: dict[ExamStatus, str] = {
    ExamStatus.UPCOMING: "Kutilayotgan",
    ExamStatus.ACTIVE: "Faol",
    ExamStatus.CLOSED: "Yakunlandi (natija kutilmoqda)",
    ExamStatus.PUBLISHED: "Natija e'lon qilindi",
}


def status_of(exam: Exam, now: str | None = None) -> ExamStatus:
    """Imtihonning joriy vaqtga nisbatan holatini aniqlaydi."""
    reference = now or now_db()
    if reference < exam.start_time:
        return ExamStatus.UPCOMING
    if reference < exam.end_time:
        return ExamStatus.ACTIVE
    if reference < exam.result_time:
        return ExamStatus.CLOSED
    return ExamStatus.PUBLISHED


def status_title(status: ExamStatus) -> str:
    """Holatning o'zbekcha nomi (bot va Web App uchun)."""
    return STATUS_TITLES.get(status, status.value)


def results_published(exam: Exam, now: str | None = None) -> bool:
    """Natijalar e'lon qilinganmi?"""
    return status_of(exam, now) is ExamStatus.PUBLISHED


def can_submit(exam: Exam, now: str | None = None) -> tuple[bool, str]:
    """Javob yuborish mumkinmi? Qaytaradi: (ruxsat, sabab/xabar matni)."""
    status = status_of(exam, now)
    if status is ExamStatus.UPCOMING:
        return False, (
            f"«{exam.title}» imtihoni hali boshlanmagan. "
            f"Boshlanish vaqti: {format_local(exam.start_time)}"
        )
    if status is ExamStatus.ACTIVE:
        return True, f"Javoblar {format_local(exam.end_time)} gacha qabul qilinadi."
    return False, (
        f"«{exam.title}» imtihoni uchun javob qabul qilish tugagan "
        f"({format_local(exam.end_time)})."
    )


def seconds_left(exam: Exam, now: str | None = None) -> int:
    """Javob qabul qilish tugashiga qolgan sekund (faol imtihon uchun 0+)."""
    reference = now or now_db()
    if reference >= exam.end_time:
        return 0
    return int((parse_db_time(exam.end_time) - parse_db_time(reference)).total_seconds())


# ---------------------------------------------------------------------------
# Kiritishlarni tekshirish (admin ustasi va API uchun)
# ---------------------------------------------------------------------------
def validate_test_code(code: str) -> str:
    """Test kodini tekshiradi va normallashtiradi (katta harf).

    Raises:
        ValueError: kod juda qisqa yoki ruxsat etilmagan belgilar bo'lsa.
    """
    cleaned = " ".join((code or "").split()).upper()
    if len(cleaned) < config.MIN_TEST_CODE_LENGTH:
        raise ValueError(
            f"Test kodi kamida {config.MIN_TEST_CODE_LENGTH} belgidan iborat bo'lishi kerak."
        )
    if not cleaned.isalnum():
        raise ValueError(
            "Test kodida faqat harflar va raqamlar bo'lishi mumkin "
            "(bo'sh joy va tinish belgilarisiz)."
        )
    return cleaned


def validate_title(title: str) -> str:
    """Imtihon nomini tekshiradi."""
    cleaned = " ".join((title or "").split())
    if len(cleaned) < 3:
        raise ValueError("Imtihon nomi kamida 3 belgidan iborat bo'lishi kerak.")
    if len(cleaned) > 120:
        raise ValueError("Imtihon nomi 120 belgidan oshmasligi kerak.")
    return cleaned


def validate_schedule(start: datetime, end: datetime, result: datetime) -> None:
    """Boshlanish → tugash → natija tartibini tekshiradi.

    Raises:
        ValueError: tartib buzilgan bo'lsa.
    """
    if end <= start:
        raise ValueError("Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak.")
    if result < end:
        raise ValueError(
            "Natija vaqti javob qabul qilish tugashidan oldin bo'lishi mumkin emas."
        )


def parse_difficulties_input(text: str, total_questions: int) -> list[float]:
    """O'qituvchi kiritgan logitlarni o'qiydi.

    Qabul qilinadi:
      * bo'sh matn → hamma savol uchun 0.0 (standart qiymat);
      * "0.5" (bitta qiymat) → barcha savollar uchun shu qiymat;
      * "0.5, -1.2, 1.0" → savollar soniga teng qiymatlar ro'yxati.

    Raises:
        ValueError: qiymatlar soni savollar soniga mos kelmasa yoki son bo'lmasa.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return [0.0] * total_questions

    normalized = cleaned.replace(";", " ").replace(",", " ").replace("|", " ")
    parts = [part for part in normalized.split() if part]
    values: list[float] = []
    for part in parts:
        try:
            values.append(float(part))
        except ValueError as exc:
            raise ValueError(
                f"Logit qiymati son emas: {part!r}. Masalan: 0.5, -1.2, 1.0"
            ) from exc

    if len(values) == 1 and total_questions > 1:
        return [values[0]] * total_questions
    if len(values) != total_questions:
        raise ValueError(
            f"Logitlar soni ({len(values)}) savollar soniga ({total_questions}) teng emas. "
            "Bitta qiymat kiritsangiz — u hamma savolga qo'llaniladi."
        )
    return values


def difficulties_to_json(values: Sequence[float]) -> str:
    """Logitlar ro'yxatini bazaga yoziladigan JSON satriga aylantiradi."""
    return json.dumps([round(float(value), 4) for value in values], ensure_ascii=False)


def effective_difficulties(exam: Exam) -> list[float]:
    """Imtihon logitlari (buzilgan yoki to'liq bo'lmasa — 0.0 bilan to'ldiriladi)."""
    values = list(exam.difficulties)
    if len(values) < exam.total_questions:
        values += [0.0] * (exam.total_questions - len(values))
    return values[: exam.total_questions]


def average_difficulty(exam: Exam) -> float | None:
    """Imtihondagi savollarning o'rtacha qiyinligi (logit)."""
    values = effective_difficulties(exam)
    return sum(values) / len(values) if values else None

