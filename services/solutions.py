"""«🔍 Test tahlili» bo'limi va video yechimlarni yuklash mantig'i.

Bu modul Telegram'ga bog'liq emas (`aiogram` import qilinmaydi): matn tahlili,
tugma belgilari (✅/❌, A-B qismlar), sahifalash va hashtag qurish shu yerda
bajariladi. Handler'lar faqat tayyor natijalarni ko'rsatadi.

Ikki oqim
---------
1. **O'quvchi** (tahlil): natijasi e'lon qilingan imtihonlar ro'yxati →
   savollar gridi (`✅ 1`, `❌ 3`, `✅ 36a`) → tanlangan savolning yechimi.
2. **O'qituvchi** (yuklash): sarlavhadagi «test kodi + savol raqami»
   (`rashtest1612 3`, `#rashtest1612-3`, `rashtest1612 36a`) tahlil qilinadi va
   fayl (`file_id`) bazadagi shu savolga biriktiriladi.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Final, Mapping, Sequence

from database.models import PART_WHOLE, Exam, ExamSubmission, normalize_part
from services import answer_key, exam_service

# Bir sahifada ko'rsatiladigan imtihonlar soni (sahifalash uchun).
PAGE_SIZE: Final[int] = 6

# Savol tugmalari bir qatorda nechta bo'ladi (Inline Grid).
QUESTION_GRID: Final[int] = 5

# «Test tahlili» bo'limida bir marta o'qiladigan imtihonlar chegarasi.
MAX_ANALYSIS_EXAMS: Final[int] = 100

# Oylarning o'zbekcha nomlari (imtihon tugmasi matni uchun): 12-fevral.
UZ_MONTHS: Final[tuple[str, ...]] = (
    "yanvar",
    "fevral",
    "mart",
    "aprel",
    "may",
    "iyun",
    "iyul",
    "avgust",
    "sentabr",
    "oktabr",
    "noyabr",
    "dekabr",
)


# ---------------------------------------------------------------------------
# Imtihon tugmasi va sahifalash
# ---------------------------------------------------------------------------
def exam_label(exam: Exam) -> str:
    """Imtihon tugmasidagi matn: «📊 RASH EXAM 12-fevral tahlili».

    Sana imtihon boshlanish vaqtidan (mahalliy zona, `config.TIMEZONE`)
    olinadi. Vaqt buzuq bo'lsa — imtihon nomi ishlatiladi.
    """
    try:
        local = exam_service.to_local(exam.start_time)
    except (TypeError, ValueError):
        return f"📊 RASH EXAM ({exam.title}) tahlili"
    return f"📊 RASH EXAM {local.day}-{UZ_MONTHS[local.month - 1]} tahlili"


@dataclass(frozen=True, slots=True)
class PageWindow:
    """Sahifalash natijasi (joriy sahifa va undagi imtihonlar)."""

    page: int
    total_pages: int
    total_items: int
    items: tuple[Exam, ...] = ()

    @property
    def title(self) -> str:
        """Klaviatura ustidagi sarlavha: «Sahifa 1/2 (jami: 7 ta test)»."""
        return f"Sahifa {self.page}/{self.total_pages} (jami: {self.total_items} ta test)"

    @property
    def has_prev(self) -> bool:
        """Oldingi sahifa bormi?"""
        return self.page > 1

    @property
    def has_next(self) -> bool:
        """Keyingi sahifa bormi?"""
        return self.page < self.total_pages

    @property
    def prev_page(self) -> int:
        """Oldingi sahifa raqami (1 dan kichik bo'lmaydi)."""
        return max(1, self.page - 1)

    @property
    def next_page(self) -> int:
        """Keyingi sahifa raqami (oxirgi sahifadan oshmaydi)."""
        return min(self.total_pages, self.page + 1)


def paginate(items: Sequence[Exam], page: int = 1, page_size: int = PAGE_SIZE) -> PageWindow:
    """Ro'yxatni sahifalarga bo'ladi (sahifa raqami 1 dan boshlanadi).

    Raises:
        ValueError: `page_size` noldan kichik yoki teng bo'lsa.
    """
    if page_size <= 0:
        raise ValueError("page_size noldan katta bo'lishi kerak")

    total_items = len(items)
    total_pages = max(1, math.ceil(total_items / page_size))
    current = min(max(int(page), 1), total_pages)
    start = (current - 1) * page_size
    return PageWindow(
        page=current,
        total_pages=total_pages,
        total_items=total_items,
        items=tuple(items[start : start + page_size]),
    )


# ---------------------------------------------------------------------------
# Admin yuklaydigan sarlavha: «test kodi + savol raqami»
# ---------------------------------------------------------------------------
# Qabul qilinadigan ko'rinishlar:
#     rashtest1612 3      rashtest1612-3      #rashtest1612-3
#     RASHTEST1612 36a    rashtest1612 36b    #javob-rashtest1612-3
_TARGET_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*#?\s*(?:javob[\s\-–—:./_]+)?"
    r"(?P<code>[A-Za-z0-9]+)[\s\-–—:./_]+"
    r"(?P<number>\d{1,3})(?P<part>[abAB])?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SolutionTarget:
    """Sarlavhadan olingan maqsad: qaysi test, qaysi savol (va qaysi qism)."""

    test_code: str
    question_number: int
    part: str = PART_WHOLE

    @property
    def label(self) -> str:
        """Savol belgisi: «3» yoki A/B qismli savol uchun «36a»."""
        return f"{self.question_number}{self.part}"


def parse_solution_target(text: str) -> tuple[SolutionTarget, str] | None:
    """Matn boshidagi «test kodi + savol raqami» ni ajratib oladi.

    Qaytaradi:
        (maqsad, matnning qolgan qismi) — format tanilgan bo'lsa;
        None — tanilmagan bo'lsa (savol raqami yo'q, raqam 0 va h.k.).

    Matnli yechim ham shu yo'l bilan o'qiladi:
        «/add_solution rashtest1612 3 — 2x+5=13 → x=4» → matn qismi qoladi.
    """
    raw = text or ""
    match = _TARGET_RE.match(raw)
    if match is None:
        return None

    number = int(match.group("number"))
    if number < 1:
        return None

    target = SolutionTarget(
        test_code=match.group("code").upper(),
        question_number=number,
        part=normalize_part(match.group("part")),
    )
    return target, raw[match.end() :].strip()


def parse_solution_caption(text: str) -> SolutionTarget | None:
    """Faqat «test kodi + savol raqami» dan iborat sarlavhani tahlil qiladi.

    Masalan: «rashtest1612 3», «#rashtest1612-3», «rashtest1612 36a».
    Ortiqcha matn bo'lsa yoki format tanilmasa — None qaytaradi (handler
    foydalanuvchiga to'g'ri formatni ko'rsatadi).
    """
    parsed = parse_solution_target(text)
    if parsed is None:
        return None
    target, rest = parsed
    return target if not rest else None


def solution_hashtag(test_code: str, question_number: int, part: str = PART_WHOLE) -> str:
    """Yechim posti ostiga qo'shiladigan hashtag.

    Masalan: «#javob-rashtest1612-3», qismli savol uchun «#javob-rashtest1612-36a».
    """
    code = "".join(ch for ch in (test_code or "").lower() if ch.isalnum())
    return f"#javob-{code}-{int(question_number)}{normalize_part(part)}"


# ---------------------------------------------------------------------------
# Savol tugmalari (✅/❌ belgilari bilan)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class QuestionUnit:
    """Bitta savol tugmasi: butun savol yoki uning A/B qismi."""

    number: int
    part: str = PART_WHOLE
    is_correct: bool = False

    @property
    def label(self) -> str:
        """Tugma matni: «✅ 1», «❌ 3», «✅ 36a», «❌ 36b»."""
        return f"{'✅' if self.is_correct else '❌'} {self.number}{self.part}"


def question_marks(exam: Exam, submission: ExamSubmission | None) -> list[bool]:
    """Har bir savol uchun to'g'ri (True) / noto'g'ri (False) natijalar ro'yxati.

    Kalit yoki o'quvchi javoblari buzuq bo'lsa — barcha savollar «noto'g'ri»
    deb olinadi (tahlil bo'limi ishlashda davom etadi).
    """
    total = max(int(exam.total_questions or 0), 0)
    if total == 0:
        return []

    try:
        correct = answer_key.parse_answer_key(exam.answer_key, total)
        given = answer_key.parse_submitted(
            submission.submitted_answers if submission is not None else "", total
        )
    except answer_key.AnswerKeyError:
        return [False] * total
    return answer_key.compare(correct, given)


def raw_score(exam: Exam, submission: ExamSubmission | None) -> int:
    """O'quvchining shu imtihondagi to'g'ri javoblari soni."""
    return sum(question_marks(exam, submission))


def build_question_units(
    exam: Exam,
    submission: ExamSubmission | None,
    parts: Mapping[int, Sequence[str]] | None = None,
) -> list[QuestionUnit]:
    """Savol tugmalari ro'yxatini quradi.

    A/B qismli savollar alohida tugma bo'ladi: «✅ 36a», «❌ 36b» (qismlar
    `parts` xaritasidan olinadi — `SolutionRepository.parts_for_exam`).

    Izoh: `user_answers.submitted_answers` har bir savol uchun bitta harf
    saqlaydi, shu sababli 36-savolning ikkala qismi bir xil belgi oladi
    (qismlar bo'yicha alohida javob saqlash — keyingi bosqich ishi).
    """
    parts = parts or {}
    units: list[QuestionUnit] = []

    for index, is_correct in enumerate(question_marks(exam, submission), start=1):
        unit_parts = sorted({normalize_part(part) for part in parts.get(index, ()) if part})
        if not unit_parts:
            units.append(QuestionUnit(number=index, is_correct=is_correct))
            continue
        for part in unit_parts:
            units.append(QuestionUnit(number=index, part=part, is_correct=is_correct))

    return units


def grid_rows(units: Sequence[QuestionUnit], columns: int = QUESTION_GRID) -> int:
    """Savol tugmalari nechta qatorni egallaydi (Inline Grid uchun).

    Raises:
        ValueError: `columns` noldan kichik yoki teng bo'lsa.
    """
    if columns <= 0:
        raise ValueError("columns noldan katta bo'lishi kerak")
    return max(1, math.ceil(len(units) / columns))


def grid_pattern(
    units_count: int, columns: int = QUESTION_GRID, extra: int = 2
) -> tuple[int, ...]:
    """Klaviatura qatorlari o'lchamlari ketma-ketligi (`adjust` uchun).

    Savol tugmalari `columns` tadan qatorlarga bo'linadi, oxirgi (to'liq
    bo'lmagan) qator saqlanadi; undan keyin `extra` o'lchamdagi alohida qator
    qo'shiladi (masalan «⬅️ Testlar ro'yxati» + «🏡 Asosiy menyu»).

    Masalan: 4 ta savol → (4, 2); 37 ta savol → (5, 5, 5, 5, 5, 5, 5, 2, 2).
    """
    if columns <= 0:
        raise ValueError("columns noldan katta bo'lishi kerak")
    count = max(int(units_count), 0)
    sizes = [columns] * (count // columns)
    if count % columns:
        sizes.append(count % columns)
    sizes.append(max(int(extra), 1))
    return tuple(sizes)