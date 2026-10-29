"""Imtihon platformasi oqimi testi: sxema → repository → xizmatlar → baholash.

Tekshiriladi:
    1. yangi `exams` / `user_answers` jadvallari va domen modellari;
    2. vaqt konvertatsiyasi (mahalliy ↔ UTC ISO) va kiritishlarni tekshirish;
    3. imtihon hayot sikli: kutilayotgan → faol → yopilgan → e'lon qilingan;
    4. javob yuborish, takroriy yuborishning rad etilishi;
    5. `end_time` dan keyin Rasch bo'yicha baholash (θ, SE, 0–100 ball);
    6. natijalar faqat `result_time` dan keyin ko'rinishi;
    7. "Navbat" ro'yxati, hisoblagichlar va CASCADE o'chirish.

Ishga tushirish:
    python tests/test_exam_flow.py
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database.db import Database  # noqa: E402
from database.models import Exam, ExamStatus, User  # noqa: E402
from database.repository import AlreadySubmittedError, Repositories  # noqa: E402
from services import exam_service, grading, scoring  # noqa: E402

USER = 111_000_222
QUESTIONS = 4
KEY_TEXT = "1A2B3C4D"


async def check_schema(db: Database) -> None:
    """Jadval ustunlari va domen modellarini tekshiradi."""
    names = [row["name"] for row in await db.fetchall("SELECT name FROM sqlite_master")]
    for expected in ("exams", "user_answers", "users", "questions", "test_results"):
        assert expected in names, f"{expected} jadvali yo'q"

    exam_columns = {row["name"] for row in await db.fetchall("PRAGMA table_info(exams)")}
    assert {
        "exam_id",
        "title",
        "test_code",
        "start_time",
        "end_time",
        "result_time",
        "total_questions",
        "answer_key",
        "difficulty_logits",
        "created_by",
        "graded_at",
    } <= exam_columns, exam_columns

    answer_columns = {row["name"] for row in await db.fetchall("PRAGMA table_info(user_answers)")}
    assert {
        "id",
        "user_id",
        "exam_id",
        "submitted_answers",
        "theta",
        "scaled_score",
        "raw_score",
        "submitted_at",
    } <= answer_columns, answer_columns

    exam = Exam(
        exam_id=1,
        title="Model tekshiruvi",
        test_code="ABC123",
        start_time="2026-01-01T05:00:00+00:00",
        end_time="2026-01-01T06:00:00+00:00",
        result_time="2026-01-01T07:00:00+00:00",
        total_questions=3,
        answer_key="1A2B3C",
        difficulty_logits="[0.0, 1.5, -0.5]",
    )
    assert exam.difficulties == [0.0, 1.5, -0.5]
    assert exam.is_graded is False and ExamStatus.ACTIVE.value == "active"

    # `b_source` — `b` qayerdan olinganini bildiradi: o'qituvchi foiz kiritgan
    # bo'lsa (noldan farqli `b` bor) — `legacy_expert`, aks holda `default`.
    assert scoring.ScoringContext.from_exam(exam).b_source == "legacy_expert"

    flat = Exam(
        exam_id=3,
        title="Nol logitlar",
        test_code="ZERO123",
        start_time="",
        end_time="",
        result_time="",
        total_questions=3,
        answer_key="1A2B3C",
        difficulty_logits="[0.0, 0.0, 0.0]",
    )
    assert scoring.ScoringContext.from_exam(flat).b_source == "default"
    print("[OK] b_source: foizli logitlar → legacy_expert, nollar → default")

    broken = Exam(
        exam_id=2,
        title="Buzuq",
        test_code="BROKEN",
        start_time="",
        end_time="",
        result_time="",
        total_questions=1,
        answer_key="1A",
        difficulty_logits="buzilgan",
    )
    assert broken.difficulties == [], "buzuq logitlar bo'sh ro'yxat bo'lishi kerak"
    print("[OK] Sxema va modellar: exams/user_answers ustunlari, JSON logitlar tahlili")


def check_inputs() -> None:
    """Kiritishlarni tekshirish (kod, logitlar, vaqt)."""
    assert exam_service.validate_test_code("  math2026 ") == "MATH2026"
    for bad in ("ab", "mat h", "mat-h"):
        try:
            exam_service.validate_test_code(bad)
        except ValueError as exc:
            print(f"[OK] Test kodi rad etildi ({bad!r}): {exc}")
        else:  # pragma: no cover
            raise AssertionError(bad)

    assert exam_service.parse_difficulties_input("", QUESTIONS) == [0.0] * QUESTIONS
    assert exam_service.parse_difficulties_input("0", QUESTIONS) == [0.0] * QUESTIONS
    assert exam_service.parse_difficulties_input("0.5", QUESTIONS) == [0.5] * QUESTIONS
    assert exam_service.parse_difficulties_input("-1, 0, 0.5; 1.2", QUESTIONS) == [
        -1.0,
        0.0,
        0.5,
        1.2,
    ]
    try:
        exam_service.parse_difficulties_input("0.1 0.2", QUESTIONS)
    except ValueError as exc:
        print(f"[OK] Logitlar soni mos kelmasa xato: {exc}")
    else:  # pragma: no cover
        raise AssertionError("ValueError kutilgan edi")
    print("[OK] Logit kiritilmasa standart 0.0 olinadi (tasdiqlangan talab)")

    # --- Foiz → logit (yangi yo'l: `b = ln((1-p)/p)`) ----------------------
    percent = exam_service.parse_difficulties_input("90, 75, 50, 25", QUESTIONS)
    assert [round(value, 4) for value in percent] == [
        -2.1972,
        -1.0986,
        0.0,
        1.0986,
    ], percent

    marked = exam_service.parse_difficulties_input("75%", QUESTIONS)
    assert marked == [percent[1]] * QUESTIONS, marked

    assert exam_service.parse_difficulties_input("100", QUESTIONS) == [
        -exam_service.config.THETA_BOUND
    ] * QUESTIONS

    for value, expected_percent in zip(percent, (90, 75, 50, 25), strict=True):
        assert round(exam_service.logit_to_percent(value)) == expected_percent

    try:
        exam_service.parse_difficulties_input("150", QUESTIONS)
    except ValueError as exc:
        print(f"[OK] Foiz 0-100 dan tashqarida bo'lsa xato: {exc}")
    else:  # pragma: no cover
        raise AssertionError("ValueError kutilgan edi")

    print(
        "[OK] Foiz → logit: 90/75/50/25 → -2.1972/-1.0986/0.0/+1.0986 "
        "(teskari o'tkazish ham ishlaydi)"
    )

    local = exam_service.parse_local_datetime("15.01.2026 09:00")
    assert exam_service.to_db_time(local) == "2026-01-15T04:00:00+00:00", exam_service.to_db_time(local)
    assert exam_service.format_local("2026-01-15T04:00:00+00:00") == "15.01.2026 09:00"
    assert exam_service.parse_local_datetime("2026-01-15 09:00") == local
    print(
        f"[OK] Vaqt: «15.01.2026 09:00» (mahalliy) → {exam_service.to_db_time(local)} (UTC) → "
        f"{exam_service.format_local('2026-01-15T04:00:00+00:00')} (ko'rinish)"
    )


async def check_lifecycle(repos: Repositories) -> None:
    """Imtihonning to'liq hayot sikli: yaratish → javob → baholash → natija."""
    await repos.users.upsert(User(user_id=USER, full_name="Ali Valiyev", username="ali"))

    base = datetime(2026, 1, 15, 9, 0, tzinfo=exam_service.local_zone())
    exam_id = await repos.exams.create(
        title="Matematika — 1-bosqich",
        test_code="math2026",
        start_time=exam_service.to_db_time(base),
        end_time=exam_service.to_db_time(base + timedelta(hours=1)),
        result_time=exam_service.to_db_time(base + timedelta(hours=2)),
        total_questions=QUESTIONS,
        answer_key=KEY_TEXT,
        difficulty_logits=exam_service.difficulties_to_json([0.0] * QUESTIONS),
        created_by=999,
    )
    exam = await repos.exams.get(exam_id)
    assert exam is not None and exam.test_code == "MATH2026"
    assert await repos.exams.get_by_code("math2026") is not None
    assert await repos.exams.code_exists("MATH2026")
    assert await repos.exams.code_exists("BOSHQA") is False
    print(
        f"[OK] Imtihon yaratildi: id={exam_id}, kod={exam.test_code}, "
        f"logitlar={exam.difficulties}, savollar={exam.total_questions}"
    )

    for moment, expected in (
        (base - timedelta(minutes=1), ExamStatus.UPCOMING),
        (base + timedelta(minutes=30), ExamStatus.ACTIVE),
        (base + timedelta(minutes=70), ExamStatus.CLOSED),
        (base + timedelta(minutes=130), ExamStatus.PUBLISHED),
    ):
        now = exam_service.to_db_time(moment)
        actual = exam_service.status_of(exam, now)
        assert actual is expected, (moment, actual, expected)
        print(f"[OK] {exam_service.format_local(moment)} → {exam_service.status_title(actual)}")

    allowed, reason = exam_service.can_submit(
        exam, exam_service.to_db_time(base - timedelta(minutes=5))
    )
    assert not allowed and "boshlanmagan" in reason
    active = exam_service.to_db_time(base + timedelta(minutes=10))
    allowed, reason = exam_service.can_submit(exam, active)
    assert allowed, reason
    left = exam_service.seconds_left(exam, active)
    assert 0 < left <= 3600, left
    print(f"[OK] Faol oynada ruxsat: {reason} (qolgan {left} sekund)")

    closed_reason = exam_service.can_submit(
        exam, exam_service.to_db_time(base + timedelta(minutes=70))
    )[1]
    assert "tugagan" in closed_reason
    print(f"[OK] Yopiq oynada rad etildi: {closed_reason}")

    submission_id = await repos.answers.submit(
        user_id=USER, exam_id=exam_id, submitted_answers="1A2B3X4D"
    )
    assert submission_id > 0
    saved = await repos.answers.get(USER, exam_id)
    assert saved is not None
    assert saved.theta is None and saved.scaled_score is None, "muddatdan oldin natija yozildi!"
    assert saved.submitted_answers == "1A2B3X4D"
    print("[OK] Javob saqlandi, θ hali hisoblanmagan (natija yopiq)")

    try:
        await repos.answers.submit(user_id=USER, exam_id=exam_id, submitted_answers="1A2B3C4D")
    except AlreadySubmittedError as exc:
        print(f"[OK] Takroriy yuborish rad etildi: {exc}")
    else:  # pragma: no cover
        raise AssertionError("AlreadySubmittedError kutilgan edi")

    assert not await repos.exams.list_pending_grading(active)
    after_end = exam_service.to_db_time(base + timedelta(minutes=70))
    assert await repos.exams.list_pending_grading(after_end)
    assert await grading.grade_pending(repos) == 1
    exam = await repos.exams.get(exam_id)
    assert exam is not None and exam.is_graded
    saved = await repos.answers.get(USER, exam_id)
    assert saved is not None and saved.raw_score == 3, saved.raw_score
    assert saved.theta is not None and saved.scaled_score is not None
    print(
        f"[OK] Baholandi: {saved.raw_score}/{QUESTIONS} → θ = {saved.theta:+.4f}, "
        f"0–100 ball = {saved.scaled_score}"
    )

    await grading.ensure_graded(repos, exam)
    after = await repos.answers.get(USER, exam_id)
    assert after is not None and after.theta == saved.theta
    assert await grading.grade_pending(repos) == 0, "baholash idempotent emas"
    print("[OK] ensure_graded / grade_pending takror chaqiruvda natijani o'zgartirmadi")

    # Batafsil hisobot (Web App "Natijalar" oynasi uchun)
    report = grading.build_report(exam, saved)
    assert len(report["items"]) == QUESTIONS
    assert sum(1 for item in report["items"] if item["is_correct"]) == 3
    assert report["items"][2]["given_answer"] is None
    assert report["items"][2]["correct_answer"] == "C"
    assert 0.0 < report["items"][0]["probability"] < 1.0
    # Foydalanuvchi hisoboti faqat θ (logit) shkalasida — 0–100 maydonlari yo'q.
    assert report["theta_interval"] is not None and report["standard_error"] is not None
    assert "scaled_score" not in report and "scaled_interval" not in report, report
    print(
        f"[OK] Hisobot: {report['ability_level']}, SE = {report['standard_error']}, "
        f"95% interval = {report['theta_interval']} (logit)"
    )

    # "Navbat" ro'yxati: faol imtihon birinchi turadi
    upcoming_id = await repos.exams.create(
        title="Fizika (kelasi hafta)",
        test_code="PHYS01",
        start_time=exam_service.to_db_time(base + timedelta(days=7)),
        end_time=exam_service.to_db_time(base + timedelta(days=7, hours=1)),
        result_time=exam_service.to_db_time(base + timedelta(days=7, hours=2)),
        total_questions=2,
        answer_key="1A2B",
        difficulty_logits=exam_service.difficulties_to_json([0.0, 0.0]),
    )
    relevant = await repos.exams.list_relevant(active)
    assert [item.exam_id for item in relevant][0] == exam_id
    assert upcoming_id in [item.exam_id for item in relevant]
    published_only = await repos.exams.list_relevant(
        exam_service.to_db_time(base + timedelta(hours=3))
    )
    assert [item.exam_id for item in published_only] == [upcoming_id]
    print("[OK] «Navbat»: faol imtihon birinchi, natijasi e'lon qilinganlari ro'yxatdan chiqadi")

    # Hisoblagichlar (profil va /stats uchun)
    assert await repos.answers.count_for_user(USER) == 1
    assert await repos.answers.count_for_exam(exam_id) == 1
    assert await repos.answers.count() == 1
    assert await repos.exams.count() == 2
    assert (await repos.exams.list_all(limit=5))[0].exam_id == upcoming_id
    print("[OK] Hisoblagichlar (profil, /stats) va admin ro'yxati to'g'ri ishlaydi")

    # O'chirish — javoblar ham CASCADE bilan o'chadi
    await repos.exams.delete(exam_id)
    assert await repos.exams.get(exam_id) is None
    assert await repos.answers.get(USER, exam_id) is None
    print("[OK] Imtihon o'chirilganda javoblar ham o'chdi (CASCADE)")


async def main() -> None:
    """Testlarni ketma-ket ishga tushiradi."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_exam_"))
    db = Database(tmp_dir / "exam_test.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("Imtihon platformasi oqimi testi (tarmoqsiz)")
    print("=" * 72)
    try:
        await check_schema(db)
        check_inputs()
        await check_lifecycle(repos)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
