"""Domen modellari: `users`, `questions`, `test_results` hamda yangi
imtihon platformasining `exams`, `user_answers` jadvallari uchun dataclass'lar."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

OPTIONS: Final[tuple[str, ...]] = ("A", "B", "C", "D")
SKIPPED: Final[str] = "X"  # o'quvchi "Bilmayman" tugmasini bosgan holat
PART_WHOLE: Final[str] = ""  # savol qismlarga bo'linmagan (A/B qismsiz)
PART_OPTIONS: Final[tuple[str, ...]] = (PART_WHOLE, "a", "b")  # ruxsat etilgan qismlar


def normalize_part(part: str | None) -> str:
    """A/B qism belgisini normallashtiradi ("" | "a" | "b").

    Raises:
        ValueError: ruxsat etilmagan belgi berilsa (masalan "c").
    """
    cleaned = (part or "").strip().lower()
    if cleaned not in PART_OPTIONS:
        allowed = ", ".join(repr(option) for option in PART_OPTIONS)
        raise ValueError(f"Qism faqat {allowed} bo'lishi mumkin, berilgan: {part!r}")
    return cleaned


@dataclass(slots=True)
class User:
    """`users` jadvalining bir satri."""

    user_id: int
    full_name: str
    username: str | None = None
    created_at: str | None = None

    @property
    def mention(self) -> str:
        """Foydalanuvchini qulay ko'rsatish uchun matn."""
        if self.username:
            return f"{self.full_name} (@{self.username})"
        return self.full_name


@dataclass(slots=True)
class Question:
    """`questions` jadvalining bir satri.

    `difficulty_b` — Rasch modelidagi qiyinchilik parametri (logit).
    b katta bo'lsa savol qiyin, kichik (manfiy) bo'lsa oson.
    """

    question_id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: str
    difficulty_b: float
    topic: str | None = None

    def options(self) -> dict[str, str]:
        """Variantlarni {"A": "...", "B": "...", ...} ko'rinishida qaytaradi."""
        return {
            "A": self.option_a,
            "B": self.option_b,
            "C": self.option_c,
            "D": self.option_d,
        }

    def option_text(self, letter: str) -> str:
        """Berilgan harf bo'yicha variant matnini qaytaradi."""
        return self.options().get(letter.upper(), "—")

    def is_correct(self, letter: str | None) -> bool:
        """Javob to'g'rimi? (None yoki "X" — noto'g'ri hisoblanadi)."""
        return bool(letter) and letter.upper() == self.correct_option


@dataclass(slots=True)
class TestResult:
    """`test_results` jadvalining bir satri."""

    user_id: int
    raw_score: int
    theta_score: float
    final_scaled_score: float
    total_questions: int = 0
    date: str | None = None
    result_id: int | None = None

    @property
    def percentage(self) -> float:
        """Xom ballning foizdagi ko'rinishi."""
        if not self.total_questions:
            return 0.0
        return 100.0 * self.raw_score / self.total_questions


@dataclass(slots=True)
class UserStats:
    """Bir o'quvchining umumiy statistikasi (hisobot uchun)."""

    attempts: int = 0
    best_scaled: float | None = None
    average_scaled: float | None = None
    best_theta: float | None = None
    total_correct: int = 0
    total_questions: int = 0
    dates: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Imtihon platformasi modellari (exams / user_answers)
# ---------------------------------------------------------------------------
class ExamStatus(str, Enum):
    """Imtihonning joriy vaqtga nisbatan holati.

    UPCOMING  — javob topshirish hali boshlanmagan (kutilayotgan);
    ACTIVE    — start_time ≤ now < end_time (javob topshirish mumkin);
    CLOSED    — end_time ≤ now < result_time (qabul tugagan, natija kutilmoqda);
    PUBLISHED — now ≥ result_time (natijalar e'lon qilingan).
    """

    UPCOMING = "upcoming"
    ACTIVE = "active"
    CLOSED = "closed"
    PUBLISHED = "published"


@dataclass(slots=True)
class Exam:
    """`exams` jadvalining bir satri (o'qituvchi yaratgan imtihon)."""

    exam_id: int
    title: str
    test_code: str
    start_time: str  # UTC ISO-8601
    end_time: str  # UTC ISO-8601
    result_time: str  # UTC ISO-8601
    total_questions: int
    answer_key: str  # masalan "1A2B3C4D"
    difficulty_logits: str  # JSON massiv satri, masalan "[0.0, 1.2, -0.5]"
    created_by: int | None = None
    created_at: str | None = None
    graded_at: str | None = None

    @property
    def difficulties(self) -> list[float]:
        """`difficulty_logits` JSON satrini sonlar ro'yxatiga aylantiradi.

        Buzilgan/bo'sh qiymat bo'lsa — bo'sh ro'yxat qaytariladi (chaqiruvchi
        tomon buni "logit kiritilmagan" deb talqin qiladi va 0.0 oladi).
        """
        try:
            raw = json.loads(self.difficulty_logits or "[]")
        except (TypeError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        return [float(value) for value in raw]

    @property
    def is_graded(self) -> bool:
        """Imtihon bo'yicha baholash tugaganmi?"""
        return self.graded_at is not None


@dataclass(slots=True)
class ExamSubmission:
    """`user_answers` jadvalining bir satri (o'quvchining imtihon javoblari)."""

    user_id: int
    exam_id: int
    submitted_answers: str
    theta: float | None = None  # θ (logit), None — hali baholanmagan
    scaled_score: float | None = None  # 0..100, None — hali baholanmagan
    raw_score: int | None = None  # to'g'ri javoblar soni
    submitted_at: str | None = None
    submission_id: int | None = None
    notified_at: str | None = None  # natija xabari yuborilgan vaqt (UTC ISO)

    # JOIN orqali to'ldiriladigan maydonlar (natijalar tarixi uchun qulaylik)
    exam_title: str | None = None
    total_questions: int | None = None
    result_time: str | None = None

    @property
    def is_graded(self) -> bool:
        """Bu javob uchun θ hisoblanganmi?"""
        return self.theta is not None


# ---------------------------------------------------------------------------
# «🔍 Test tahlili» modellari (solutions)
# ---------------------------------------------------------------------------
class SolutionType(str, Enum):
    """Yechim qanday ko'rinishda saqlanganini bildiradi.

    Barcha turlar Telegram `file_id` orqali saqlanadi (matnli yechim
    qo'llanmaydi — faqat video va rasm).

    VIDEO / PHOTO — asosiy (o'qituvchi yuklaydigan) turlar;
    DOCUMENT — rasm/video «fayl sifatida» yuborilganda;
    ANIMATION / AUDIO — eski yozuvlar uchun (yangi yuklashda qabul qilinmaydi).
    """

    VIDEO = "video"
    PHOTO = "photo"
    DOCUMENT = "document"
    ANIMATION = "animation"
    AUDIO = "audio"

    @property
    def title(self) -> str:
        """O'zbekcha nomi (xabarlarda ko'rsatiladi)."""
        return SOLUTION_TYPE_TITLES.get(self, self.value)

    @property
    def icon(self) -> str:
        """Xabar sarlavhasidagi belgi (`🎬`, `🖼`, ...)."""
        return SOLUTION_TYPE_ICONS.get(self, "📎")


SOLUTION_TYPE_TITLES: Final[dict[SolutionType, str]] = {
    SolutionType.VIDEO: "video yechim",
    SolutionType.PHOTO: "rasm yechim",
    SolutionType.DOCUMENT: "fayl ko'rinishidagi yechim",
    SolutionType.ANIMATION: "animatsiya ko'rinishidagi yechim",
    SolutionType.AUDIO: "audio yechim",
}

SOLUTION_TYPE_ICONS: Final[dict[SolutionType, str]] = {
    SolutionType.VIDEO: "🎬",
    SolutionType.PHOTO: "🖼",
    SolutionType.DOCUMENT: "📄",
    SolutionType.ANIMATION: "🎞",
    SolutionType.AUDIO: "🔊",
}


@dataclass(slots=True)
class Solution:
    """`solutions` jadvalining bir satri (bitta savolning yechimi).

    `part` — A/B qismli savollar uchun: `PART_WHOLE` (""), "a" yoki "b".
    Ya'ni 36-savolning ikkita qismi ikki alohida satr bo'lib saqlanadi.
    """

    exam_id: int
    question_number: int
    solution_type: str = SolutionType.VIDEO.value
    part: str = PART_WHOLE
    solution_file_id: str | None = None
    created_by: int | None = None
    updated_at: str | None = None
    solution_id: int | None = None

    @property
    def type(self) -> SolutionType:
        """`solution_type` satrini `SolutionType` ga aylantiradi.

        Bazada eski (`text`) yoki noma'lum turdagi yozuv qolgan bo'lsa — VIDEO
        ga keltiriladi; bunday yozuvda `solution_file_id` yo'q, shu sababli
        `is_file` `False` bo'lib, u yechim sifatida ko'rsatilmaydi.
        """
        try:
            return SolutionType(self.solution_type)
        except ValueError:
            return SolutionType.VIDEO

    @property
    def is_file(self) -> bool:
        """Yechim Telegram fayli (`file_id`) bilan saqlanganmi?

        Matnli (eski) yozuvlarda fayl bo'lmaydi — ular yechim hisoblanmaydi.
        """
        return bool(self.solution_file_id)

    @property
    def label(self) -> str:
        """Savolning belgisi: "3" yoki A/B qismli savol uchun "36a"."""
        return f"{self.question_number}{self.part}"
