"""«🔍 Test tahlili» bo'limi va video yechimlarni yuklash mantig'i.

Bu modul Telegram'ga bog'liq emas (`aiogram` import qilinmaydi): tugma
belgilari (✅/❌, A-B qismlar), sahifalash va hashtag qurish shu yerda
bajariladi. Yechim faqat **video yoki rasm** (`file_id`) ko'rinishida bo'ladi —
matnli yechim qo'llanmaydi. Handler'lar faqat tayyor natijalarni ko'rsatadi.

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
from services import answer_key, exam_service, scoring

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
def _short_label(text: str, limit: int) -> str:
    """Tugma matni uchun qisqartirish (Telegram 64 belgi chegarasi)."""
    clean = " ".join(str(text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def exam_label(exam: Exam) -> str:
    """Imtihon tugmasidagi matn: «📊 12-fevral · RASH EXAM · EXAM01».

    Sana imtihon boshlanish vaqtidan (mahalliy zona, `config.TIMEZONE`)
    olinadi. Sana buzuq bo'lsa — faqat nom va kod ko'rsatiladi. Nom va kod
    qisqartiriladi: bir kunda bir nechta test bo'lsa ham tugmalar farqlanadi.
    """
    title = _short_label(exam.title, 20)
    code = _short_label(exam.test_code, 12)
    try:
        local = exam_service.to_local(exam.start_time)
    except (TypeError, ValueError):
        return f"📊 {title} · {code}"
    return f"📊 {local.day}-{UZ_MONTHS[local.month - 1]} · {title} · {code}"


def result_locked(exam: Exam, now_iso: str) -> bool:
    """Yechimlar hali e'lon qilinmaganmi? (`result_time` kelmagunicha — True).

    Yechim to'g'ri javobni ko'rsatadi, shu sababli natijalar e'lon qilingunicha
    ochilmasligi kerak (imtihon tozaligi). «Yakunlash»dan keyin kelgan natija
    xabaridagi tugmalar ham shu qulf orqali himoyalanadi.
    """
    return exam.result_time > now_iso


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

    Media izohi (caption) shu funksiya orqali o'qiladi; undan keyin ortiqcha
    matn qolsa — format noto'g'ri hisoblanadi (`parse_solution_caption`).
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

    @property
    def style(self) -> str:
        """Tugma rangi (Bot API `InlineKeyboardButton.style`).

        To'g'ri javob — yashil («success»), xato javob — qizil («danger»).
        Eski Telegram ilovalarida rang ko'rinmasa ham, matndagi ✅/❌ belgi
        saqlanadi (zaxira).
        """
        return "success" if self.is_correct else "danger"


def _item_results(
    exam: Exam, submission: ExamSubmission | None
) -> tuple[scoring.ItemScoreResult, ...]:
    """`build_item_results` natijalari (kalit buzuq bo'lsa — bo'sh to'plam)."""
    submitted = submission.submitted_answers if submission is not None else ""
    try:
        context = scoring.ScoringContext.from_exam(exam)
        return scoring.build_item_results(context, submitted)
    except answer_key.AnswerKeyError:
        return ()


def question_marks(exam: Exam, submission: ExamSubmission | None) -> list[bool]:
    """Har bir savol uchun to'g'ri (True) / noto'g'ri (False) natijalar ro'yxati.

    Hisoblash **`services/scoring.py`** da (yagona nuqta) — baholash va hisobot
    bilan aynan bir xil qoida ishlatiladi: 1–32/33–35 → variant harfi
    (A–F), 36–45 → sonli qiymat; eski kalitlarda esa A–D harflar.

    Kalit yoki o'quvchi javoblari buzuq bo'lsa — barcha savollar «noto'g'ri»
    deb olinadi (tahlil bo'limi ishlashda davom etadi).
    """
    total = max(int(exam.total_questions or 0), 0)
    if total == 0:
        return []

    results = _item_results(exam, submission)
    if not results:
        return [False] * total
    return [result.is_correct for result in results]


def raw_score(exam: Exam, submission: ExamSubmission | None) -> int:
    """O'quvchining shu imtihondagi to'g'ri javoblari soni."""
    return sum(question_marks(exam, submission))


def _labeled_marks(exam: Exam, submission: ExamSubmission | None) -> list[tuple[str, int, bool]]:
    """Har bir savol uchun ``(label, position, is_correct)`` ro'yxati.

    Kalit buzuq bo'lsa — barcha savollar «noto'g'ri» (`question_marks` bilan
    bir xil qoida), belgilar esa pozitsiya ko'rinishida bo'ladi.
    """
    total = max(int(exam.total_questions or 0), 0)
    if total == 0:
        return []
    results = _item_results(exam, submission)
    if not results:
        return [(str(position), position, False) for position in range(1, total + 1)]
    return [
        (
            result.label or str(result.question_number),
            result.question_number,
            result.is_correct,
        )
        for result in results
    ]


def build_question_units(
    exam: Exam,
    submission: ExamSubmission | None,
    parts: Mapping[int, Sequence[str]] | None = None,
) -> list[QuestionUnit]:
    """Savol tugmalari ro'yxatini quradi.

    Qismli savollar **alohida** tugma bo'ladi: «✅ 36a», «❌ 36b». Qismlar
    baholash natijasidagi belgi (`36a`, `36b`) bo'yicha aniqlanadi — shu sababli
    har bir qism o'z ✅/❌ belgisini oladi.

    Eski (qismsiz) imtihonlarda xulq **avvalgidek**: qismlar `parts` xaritasidan
    olinadi (`SolutionRepository.parts_for_exam`) va ikkala qism bir xil belgi
    oladi (`user_answers.submitted_answers` savol uchun bitta javob saqlaydi).
    """
    parts = parts or {}
    marks = _labeled_marks(exam, submission)
    units: list[QuestionUnit] = []

    if not any(label != str(position) for label, position, _ in marks):
        # Legacy (qismsiz): savol raqami + `parts` xaritasi — o'zgarishsiz.
        for index, (_label, _position, is_correct) in enumerate(marks, start=1):
            unit_parts = sorted(
                {normalize_part(part) for part in parts.get(index, ()) if part}
            )
            if not unit_parts:
                units.append(QuestionUnit(number=index, is_correct=is_correct))
                continue
            for part in unit_parts:
                units.append(
                    QuestionUnit(number=index, part=part, is_correct=is_correct)
                )
        return units

    # Qismli forma: har bir belgi (`36a`, `36b`) — alohida tugma.
    for label, position, is_correct in marks:
        try:
            number, part = answer_key.split_label(label)
        except ValueError:  # kutilmagan belgi — pozitsiya bo'yicha qoldiramiz
            number, part = position, None
        units.append(
            QuestionUnit(number=number, part=part or PART_WHOLE, is_correct=is_correct)
        )
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