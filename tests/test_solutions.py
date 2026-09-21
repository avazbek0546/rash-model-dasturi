"""«🔍 Test tahlili» bo'limi va video yechimlar (`solutions`) testi.

Tekshiriladi:
    1. `solutions` jadvali va `Solution` modeli (`solution_file_id`,
       `solution_type`, `solution_text`, A/B `part`);
    2. admin izohini tahlil qilish: «rashtest1612 3», «#rashtest1612-3», «36a»;
    3. repository: upsert (qayta yuklashda yangilanadi), A/B qismlar, o'chirish,
       imtihon o'chirilganda CASCADE;
    4. savol tugmalari belgilari («✅ 1», «❌ 3», «✅ 36a», «❌ 36b») va hashtag;
    5. sahifalash: «Sahifa 1/2 (jami: 7 ta test)» va «⬅️/➡️» sahifa chegaralari;
    6. imtihon tugmasi: «📊 RASH EXAM 12-fevral tahlili»;
    7. tahlil ro'yxatiga faqat javob yuborilgan va natijasi e'lon qilingan
       imtihonlar tushishi.

Ishga tushirish:
    python tests/test_solutions.py
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database.db import Database  # noqa: E402
from database.models import (  # noqa: E402
    PART_WHOLE,
    Exam,
    Solution,
    SolutionType,
    User,
    normalize_part,
)
from database.repository import Repositories  # noqa: E402
from services import exam_service, solutions  # noqa: E402

USER = 777_000_111
ADMIN = 555_000_999
TEST_CODE = "RASHTEST1612"
KEY = "1A2B3C4D"
QUESTIONS = 4


def make_exam(
    *,
    exam_id: int = 1,
    start_time: str = "2026-02-12T05:00:00+00:00",
    total_questions: int = QUESTIONS,
    answer_key: str = KEY,
    title: str = "RASH EXAM — 12-fevral",
) -> Exam:
    """Test uchun imtihon obyekti (vaqtlar ahamiyatsiz joylarda)."""
    return Exam(
        exam_id=exam_id,
        title=title,
        test_code=TEST_CODE,
        start_time=start_time,
        end_time="2026-02-12T07:00:00+00:00",
        result_time="2026-02-12T09:00:00+00:00",
        total_questions=total_questions,
        answer_key=answer_key,
        difficulty_logits="[]",
    )


async def check_schema(db: Database) -> None:
    """`solutions` jadvali va ustunlari joyidami?"""
    names = [row["name"] for row in await db.fetchall("SELECT name FROM sqlite_master")]
    assert "solutions" in names, "solutions jadvali yaratilmadi"

    columns = {row["name"] for row in await db.fetchall("PRAGMA table_info(solutions)")}
    assert {
        "solution_id",
        "exam_id",
        "question_number",
        "part",
        "solution_type",
        "solution_file_id",
        "solution_text",
        "created_by",
        "created_at",
        "updated_at",
    } <= columns, columns

    video = Solution(
        exam_id=1,
        question_number=36,
        part="a",
        solution_type=SolutionType.VIDEO.value,
        solution_file_id="FILE-ID-1",
    )
    assert video.label == "36a" and video.type is SolutionType.VIDEO and video.is_file

    text = Solution(exam_id=1, question_number=1, solution_type="text", solution_text="yechim")
    assert text.label == "1" and text.type is SolutionType.TEXT and not text.is_file
    assert SolutionType.VIDEO.title == "video yechim"
    assert SolutionType.PHOTO.title == "rasm yechim"
    assert normalize_part(None) == PART_WHOLE and normalize_part(" A ") == "a"
    try:
        normalize_part("c")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("normalize_part noto'g'ri qismni qabul qildi")
    print("[OK] Sxema va model: solutions jadvali (file_id/type/text/part) tayyor")


def check_captions() -> None:
    """Admin izohini tahlil qilish (barcha qabul qilinadigan ko'rinishlar)."""
    cases: dict[str, tuple[str, int, str]] = {
        "rashtest1612 3": ("RASHTEST1612", 3, ""),
        "  rashtest1612-3  ": ("RASHTEST1612", 3, ""),
        "#rashtest1612-3": ("RASHTEST1612", 3, ""),
        "rashtest1612:12": ("RASHTEST1612", 12, ""),
        "RASHTEST1612_36A": ("RASHTEST1612", 36, "a"),
        "rashtest1612 36b": ("RASHTEST1612", 36, "b"),
        "#javob-rashtest1612-3b": ("RASHTEST1612", 3, "b"),
    }
    for text, expected in cases.items():
        target = solutions.parse_solution_caption(text)
        assert target is not None, f"format tanilmadi: {text!r}"
        assert (target.test_code, target.question_number, target.part) == expected, text

    invalid = ["", "salom", "rashtest1612", "rashtest1612 0", "3", "#javob-", "afds 9999"]
    for text in invalid:
        assert solutions.parse_solution_caption(text) is None, f"noto'g'ri format qabul qilindi: {text!r}"

    # Matnli yechim: «test kodi + savol raqami» + qolgan matn
    parsed = solutions.parse_solution_target("rashtest1612 3 2x+5=13 → x=4")
    assert parsed is not None
    target, rest = parsed
    assert target.label == "3" and rest == "2x+5=13 → x=4", (target, rest)
    print("[OK] Izoh tahlili: «rashtest1612 3», «#rashtest1612-3», «36a», «36b»")


def check_labels_and_pagination() -> None:
    """Savol belgilari, hashtag va sahifalash mantig'i."""
    assert solutions.solution_hashtag(TEST_CODE, 3) == "#javob-rashtest1612-3"
    assert solutions.solution_hashtag(TEST_CODE, 36, "a") == "#javob-rashtest1612-36a"

    # Imtihon tugmasi matni
    exam = make_exam(start_time="2026-02-12T05:00:00+00:00")
    label = solutions.exam_label(exam)
    local = exam_service.to_local(exam.start_time)
    assert label == f"📊 RASH EXAM {local.day}-{solutions.UZ_MONTHS[local.month - 1]} tahlili"
    assert re.fullmatch(r"📊 RASH EXAM \d{1,2}-[a-z]+ tahlili", label), label
    if exam_service.local_zone().utcoffset(None) == timedelta(hours=5):
        assert label == "📊 RASH EXAM 12-fevral tahlili", label

    broken = make_exam(start_time="")
    assert "RASH EXAM" in solutions.exam_label(broken)

    # Sahifalash: 7 ta imtihon → 2 sahifa (6 + 1)
    exams = [make_exam(exam_id=index) for index in range(1, 8)]
    first = solutions.paginate(exams, page=1)
    assert len(first.items) == 6 and first.total_pages == 2 and first.total_items == 7
    assert first.title == "Sahifa 1/2 (jami: 7 ta test)", first.title
    assert first.has_next and not first.has_prev and first.next_page == 2

    second = solutions.paginate(exams, page=2)
    assert len(second.items) == 1 and second.has_prev and not second.has_next
    assert second.title == "Sahifa 2/2 (jami: 7 ta test)"

    # Sahifa raqami chegaralanadi (5 → 2, 0 → 1)
    assert solutions.paginate(exams, page=5).page == 2
    assert solutions.paginate(exams, page=0).page == 1
    empty = solutions.paginate([], page=3)
    assert empty.total_pages == 1 and empty.items == () and not empty.has_next
    print("[OK] Belgilar/sahifalash: «✅ 36a», «#javob-rashtest1612-3», «Sahifa 1/2»")


def check_question_units() -> None:
    """✅/❌ belgilari va A/B qismli savollar gridi."""
    from database.models import ExamSubmission

    exam = make_exam()
    submission = ExamSubmission(
        user_id=USER, exam_id=1, submitted_answers="1A2B3X4D", submitted_at="2026-02-12T07:00:00"
    )
    assert solutions.question_marks(exam, submission) == [True, True, False, True]
    assert solutions.raw_score(exam, submission) == 3

    units = solutions.build_question_units(exam, submission)
    assert [unit.label for unit in units] == ["✅ 1", "✅ 2", "❌ 3", "✅ 4"], [
        unit.label for unit in units
    ]

    # 36-savolni qismlarga bo'lamiz (a va b alohida tugma bo'ladi)
    big = make_exam(total_questions=36, answer_key="".join(["A"] * 36))
    big_submission = ExamSubmission(
        user_id=USER, exam_id=2, submitted_answers=answer_key_text(36, wrong={"3", "36"})
    )
    part_units = solutions.build_question_units(big, big_submission, {36: ["a", "b"]})
    labels = [unit.label for unit in part_units]
    assert labels[0] == "✅ 1" and labels[2] == "❌ 3", labels[:3]
    assert labels[-2:] == ["❌ 36a", "❌ 36b"], labels[-2:]
    assert solutions.grid_rows(part_units) == 8  # 37 ta tugma / 5 ustun

    # Buzuq kalit — hamma savol «noto'g'ri» (tahlil ishlashda davom etadi)
    broken = make_exam(answer_key="buzilgan")
    assert solutions.question_marks(broken, submission) == [False] * QUESTIONS
    print("[OK] Savol tugmalari: «✅ 1», «❌ 3», «✅ 36a», «❌ 36b»")


def answer_key_text(total: int, *, wrong: set[str] | None = None) -> str:
    """«1A2B3C…» ko'rinishidagi javoblar varag'i (ba'zilari ataylab xato)."""
    wrong = wrong or set()
    return "".join(
        f"{index}{'B' if str(index) in wrong else 'A'}" for index in range(1, total + 1)
    )


async def check_repository(repos: Repositories) -> None:
    """`solutions` repository: upsert, qismlar, o'chirish va CASCADE."""
    exam_id = await repos.exams.create(
        title="RASH EXAM — 12-fevral",
        test_code=TEST_CODE,
        start_time=exam_service.to_db_time(exam_service.utc_now() - timedelta(hours=3)),
        end_time=exam_service.to_db_time(exam_service.utc_now() - timedelta(hours=2)),
        result_time=exam_service.to_db_time(exam_service.utc_now() - timedelta(hours=1)),
        total_questions=36,
        answer_key="".join(["A"] * 36),
        difficulty_logits="[]",
        created_by=ADMIN,
    )

    solution_id = await repos.solutions.upsert(
        exam_id=exam_id,
        question_number=3,
        solution_type=SolutionType.VIDEO.value,
        solution_file_id="FILE-ID-1",
        created_by=ADMIN,
    )
    assert solution_id > 0
    saved = await repos.solutions.get(exam_id, 3)
    assert saved is not None and saved.solution_file_id == "FILE-ID-1"
    assert saved.type is SolutionType.VIDEO and saved.is_file and saved.label == "3"

    # Qayta yuklash — dublikat emas, mavjud yozuv yangilanadi
    again = await repos.solutions.upsert(
        exam_id=exam_id,
        question_number=3,
        solution_type=SolutionType.VIDEO.value,
        solution_file_id="FILE-ID-2",
        created_by=ADMIN,
    )
    assert again == solution_id, "upsert dublikat yaratdi"
    assert await repos.solutions.count_for_exam(exam_id) == 1
    refreshed = await repos.solutions.get(exam_id, 3)
    assert refreshed is not None and refreshed.solution_file_id == "FILE-ID-2"

    # A/B qismli savol (36a va 36b — ikki alohida yozuv)
    await repos.solutions.upsert(
        exam_id=exam_id,
        question_number=36,
        part="a",
        solution_type=SolutionType.PHOTO.value,
        solution_file_id="PHOTO-36A",
        created_by=ADMIN,
    )
    await repos.solutions.upsert(
        exam_id=exam_id,
        question_number=36,
        part="b",
        solution_type=SolutionType.TEXT.value,
        solution_text="36b yechimi: ...",
        created_by=ADMIN,
    )
    parts = await repos.solutions.parts_for_exam(exam_id)
    assert parts == {36: ["a", "b"]}, parts
    assert await repos.solutions.count_for_exam(exam_id) == 3
    assert await repos.solutions.count() == 3

    listed = await repos.solutions.list_for_exam(exam_id)
    assert [item.label for item in listed] == ["3", "36a", "36b"], [i.label for i in listed]

    # Noto'g'ri qism rad etiladi
    try:
        await repos.solutions.upsert(
            exam_id=exam_id, question_number=5, part="c", solution_type="video"
        )
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("noto'g'ri qism («c») bazaga yozildi")

    # O'chirish
    await repos.solutions.delete(exam_id, 3)
    assert await repos.solutions.get(exam_id, 3) is None
    assert await repos.solutions.count_for_exam(exam_id) == 2

    # Imtihon o'chirilsa — yechimlar ham CASCADE bilan o'chadi
    await repos.exams.delete(exam_id)
    assert await repos.solutions.list_for_exam(exam_id) == []
    assert await repos.solutions.count() == 0
    print("[OK] Repository: upsert (yangilanadi), 36a/36b qismlar, o'chirish, CASCADE")


async def check_published_listing(repos: Repositories) -> None:
    """«Test tahlili» ro'yxati: faqat javob yuborilgan va e'lon qilinganlar."""
    await repos.users.upsert(User(user_id=USER, full_name="Aziz Karimov", username="aziz"))

    now = exam_service.utc_now()
    published_ids: list[int] = []
    for hours_ago in (3, 27):  # ikkita natijasi e'lon qilingan imtihon
        published_ids.append(
            await repos.exams.create(
                title=f"RASH EXAM ({hours_ago} soat oldin)",
                test_code=f"RASH{hours_ago}",
                start_time=exam_service.to_db_time(now - timedelta(hours=hours_ago)),
                end_time=exam_service.to_db_time(now - timedelta(hours=hours_ago - 1)),
                result_time=exam_service.to_db_time(now - timedelta(hours=hours_ago - 2)),
                total_questions=QUESTIONS,
                answer_key=KEY,
                difficulty_logits="[]",
            )
        )
    upcoming_id = await repos.exams.create(
        title="RASH EXAM (kelasi hafta)",
        test_code="RASHFUTURE",
        start_time=exam_service.to_db_time(now + timedelta(hours=1)),
        end_time=exam_service.to_db_time(now + timedelta(hours=2)),
        result_time=exam_service.to_db_time(now + timedelta(hours=3)),
        total_questions=QUESTIONS,
        answer_key=KEY,
        difficulty_logits="[]",
    )

    for exam_id in (*published_ids, upcoming_id):
        await repos.answers.submit(
            user_id=USER, exam_id=exam_id, submitted_answers="1A2B3X4D"
        )

    current = exam_service.now_db()
    listed = await repos.exams.list_published_for_user(USER, current)
    assert [exam.exam_id for exam in listed] == published_ids, [e.exam_id for e in listed]
    assert await repos.exams.count_published_for_user(USER, current) == 2
    assert await repos.exams.count_published_for_user(USER + 1, current) == 0

    # Tahlil bo'limining to'liq zanjiri: ro'yxat → savollar gridi
    window = solutions.paginate(listed, page=1)
    assert window.items[0].exam_id == published_ids[0]
    exam = window.items[0]
    submission = await repos.answers.get(USER, exam.exam_id)
    units = solutions.build_question_units(
        exam, submission, await repos.solutions.parts_for_exam(exam.exam_id)
    )
    assert [unit.label for unit in units] == ["✅ 1", "✅ 2", "❌ 3", "✅ 4"], [
        unit.label for unit in units
    ]
    print("[OK] Ro'yxat: faqat javob yuborilgan va natijasi e'lon qilingan imtihonlar")


async def main() -> None:
    """Testlarni ketma-ket ishga tushiradi (tarmoqsiz, vaqtinchalik baza)."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_solutions_"))
    db = Database(tmp_dir / "solutions_test.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("«🔍 Test tahlili» va video yechimlar testi (tarmoqsiz)")
    print("=" * 72)
    try:
        await check_schema(db)
        check_captions()
        check_labels_and_pagination()
        check_question_units()
        await check_repository(repos)
        await check_published_listing(repos)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())