"""Repository qatlami — jadvallar bilan barcha CRUD amallari shu yerda.

Handler'lar SQL yozmaydi, faqat repository metodlarini chaqiradi.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

from database.db import Database
from database.models import (
    PART_WHOLE,
    Exam,
    ExamSubmission,
    Question,
    Solution,
    TestResult,
    User,
    UserStats,
    normalize_part,
)

logger = logging.getLogger(__name__)


def _to_user(row: dict) -> User:
    return User(
        user_id=row["user_id"],
        full_name=row["full_name"],
        username=row["username"],
        created_at=row["created_at"],
    )


def _to_question(row: dict) -> Question:
    return Question(
        question_id=row["question_id"],
        question_text=row["question_text"],
        option_a=row["option_a"],
        option_b=row["option_b"],
        option_c=row["option_c"],
        option_d=row["option_d"],
        correct_option=row["correct_option"],
        difficulty_b=float(row["difficulty_b"]),
        topic=row["topic"],
    )


def _to_result(row: dict) -> TestResult:
    return TestResult(
        result_id=row["result_id"],
        user_id=row["user_id"],
        raw_score=row["raw_score"],
        total_questions=row["total_questions"],
        theta_score=float(row["theta_score"]),
        final_scaled_score=float(row["final_scaled_score"]),
        date=row["date"],
    )


class UserRepository:
    """`users` jadvali bilan ishlash."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, user: User) -> None:
        """O'quvchini qo'shadi yoki ma'lumotlarini yangilaydi."""
        await self._db.execute(
            """
            INSERT INTO users (user_id, full_name, username)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                full_name = excluded.full_name,
                username  = excluded.username
            """,
            (user.user_id, user.full_name, user.username),
        )

    async def get(self, user_id: int) -> User | None:
        row = await self._db.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return _to_user(row) if row else None

    async def update_full_name(self, user_id: int, full_name: str) -> None:
        """Faqat ism-familiyani yangilaydi (Web App "Profil" bo'limi uchun).

        `upsert` dan farqli o'laroq `username` ga tegmaydi.
        """
        await self._db.execute(
            "UPDATE users SET full_name = ? WHERE user_id = ?",
            (" ".join(full_name.split()), user_id),
        )

    async def count(self) -> int:
        return int(await self._db.fetchvalue("SELECT COUNT(*) FROM users", default=0))


class QuestionRepository:
    """`questions` jadvali bilan ishlash."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def count(self, only_active: bool = True) -> int:
        sql = "SELECT COUNT(*) FROM questions"
        if only_active:
            sql += " WHERE is_active = 1"
        return int(await self._db.fetchvalue(sql, default=0))

    async def get(self, question_id: int) -> Question | None:
        row = await self._db.fetchone(
            "SELECT * FROM questions WHERE question_id = ?", (question_id,)
        )
        return _to_question(row) if row else None

    async def pick_random(self, limit: int) -> list[Question]:
        """Tasodifiy `limit` ta savolni oladi va oson → qiyin tartibda qaytaradi."""
        rows = await self._db.fetchall(
            "SELECT * FROM questions WHERE is_active = 1 ORDER BY RANDOM() LIMIT ?",
            (limit,),
        )
        questions = [_to_question(row) for row in rows]
        questions.sort(key=lambda question: question.difficulty_b)
        return questions

    async def all(self, only_active: bool = True) -> list[Question]:
        sql = "SELECT * FROM questions"
        if only_active:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY difficulty_b"
        rows = await self._db.fetchall(sql)
        return [_to_question(row) for row in rows]

    async def add(
        self,
        *,
        question_text: str,
        option_a: str,
        option_b: str,
        option_c: str,
        option_d: str,
        correct_option: str,
        difficulty_b: float,
        topic: str | None = None,
    ) -> int:
        """Bitta savol qo'shadi va uning `question_id` sini qaytaradi."""
        return await self._db.execute(
            """
            INSERT INTO questions (
                question_text, option_a, option_b, option_c, option_d,
                correct_option, difficulty_b, topic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question_text,
                option_a,
                option_b,
                option_c,
                option_d,
                correct_option.upper(),
                float(difficulty_b),
                topic,
            ),
        )

    async def add_many(self, rows: Iterable[dict]) -> None:
        """Bir nechta savolni bitta tranzaksiyada qo'shadi."""
        payload: Sequence[Sequence[object]] = [
            (
                row["question_text"],
                row["option_a"],
                row["option_b"],
                row["option_c"],
                row["option_d"],
                row["correct_option"].upper(),
                float(row["difficulty_b"]),
                row.get("topic"),
            )
            for row in rows
        ]
        if not payload:
            return
        await self._db.execute_many(
            """
            INSERT INTO questions (
                question_text, option_a, option_b, option_c, option_d,
                correct_option, difficulty_b, topic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )


class ResultRepository:
    """`test_results` jadvali bilan ishlash."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, result: TestResult) -> int:
        """Test natijasini saqlaydi va `result_id` ni qaytaradi."""
        return await self._db.execute(
            """
            INSERT INTO test_results (
                user_id, raw_score, total_questions, theta_score, final_scaled_score
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                result.user_id,
                result.raw_score,
                result.total_questions,
                round(result.theta_score, 4),
                round(result.final_scaled_score, 2),
            ),
        )

    async def last_for_user(self, user_id: int, limit: int = 5) -> list[TestResult]:
        """O'quvchining oxirgi `limit` ta natijasini (eng yangisidan) qaytaradi."""
        rows = await self._db.fetchall(
            """
            SELECT * FROM test_results
            WHERE user_id = ?
            ORDER BY date DESC, result_id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [_to_result(row) for row in rows]

    async def stats_for_user(self, user_id: int) -> UserStats:
        """O'quvchi bo'yicha umumiy statistika (urinishlar, eng yaxshi natija)."""
        row = await self._db.fetchone(
            """
            SELECT
                COUNT(*)                 AS attempts,
                MAX(final_scaled_score)  AS best_scaled,
                AVG(final_scaled_score)  AS avg_scaled,
                MAX(theta_score)         AS best_theta,
                SUM(raw_score)           AS total_correct,
                SUM(total_questions)     AS total_questions
            FROM test_results
            WHERE user_id = ?
            """,
            (user_id,),
        )
        dates = await self._db.fetchall(
            "SELECT date FROM test_results WHERE user_id = ? ORDER BY date DESC LIMIT 5",
            (user_id,),
        )
        if not row or not row["attempts"]:
            return UserStats()
        return UserStats(
            attempts=int(row["attempts"]),
            best_scaled=float(row["best_scaled"]) if row["best_scaled"] is not None else None,
            average_scaled=float(row["avg_scaled"]) if row["avg_scaled"] is not None else None,
            best_theta=float(row["best_theta"]) if row["best_theta"] is not None else None,
            total_correct=int(row["total_correct"] or 0),
            total_questions=int(row["total_questions"] or 0),
            dates=[item["date"] for item in dates],
        )

    async def count(self) -> int:
        return int(await self._db.fetchvalue("SELECT COUNT(*) FROM test_results", default=0))

    async def average_scaled(self) -> float | None:
        """Barcha o'quvchilar bo'yicha o'rtacha scaled ball."""
        value = await self._db.fetchvalue("SELECT AVG(final_scaled_score) FROM test_results")
        return float(value) if value is not None else None


class AlreadySubmittedError(RuntimeError):
    """O'quvchi bu imtihonga allaqachon javob yuborgan (UNIQUE buzilishi)."""


def _to_exam(row: dict) -> Exam:
    return Exam(
        exam_id=row["exam_id"],
        title=row["title"],
        test_code=row["test_code"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        result_time=row["result_time"],
        total_questions=row["total_questions"],
        answer_key=row["answer_key"],
        difficulty_logits=row["difficulty_logits"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        graded_at=row["graded_at"],
    )


def _to_submission(row: dict) -> ExamSubmission:
    return ExamSubmission(
        submission_id=row["id"],
        user_id=row["user_id"],
        exam_id=row["exam_id"],
        submitted_answers=row["submitted_answers"],
        theta=float(row["theta"]) if row["theta"] is not None else None,
        scaled_score=float(row["scaled_score"]) if row["scaled_score"] is not None else None,
        raw_score=row["raw_score"],
        submitted_at=row["submitted_at"],
        notified_at=row.get("notified_at"),
        exam_title=row.get("exam_title"),
        total_questions=row.get("total_questions"),
        result_time=row.get("result_time"),
    )


class ExamRepository:
    """`exams` jadvali bilan ishlash.

    Vaqt maydonlari UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SS+00:00`) formatida
    saqlanadi — shu sababli SQL ichida satr sifatida taqqoslash to'g'ri
    ishlaydi (konvertatsiya `services.exam_service` da).
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        title: str,
        test_code: str,
        start_time: str,
        end_time: str,
        result_time: str,
        total_questions: int,
        answer_key: str,
        difficulty_logits: str,
        created_by: int | None = None,
    ) -> int:
        """Yangi imtihon qo'shadi va `exam_id` ni qaytaradi."""
        return await self._db.execute(
            """
            INSERT INTO exams (
                title, test_code, start_time, end_time, result_time,
                total_questions, answer_key, difficulty_logits, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                test_code.strip().upper(),
                start_time,
                end_time,
                result_time,
                int(total_questions),
                answer_key,
                difficulty_logits,
                created_by,
            ),
        )

    async def get(self, exam_id: int) -> Exam | None:
        """`exam_id` bo'yicha imtihonni qaytaradi."""
        row = await self._db.fetchone("SELECT * FROM exams WHERE exam_id = ?", (exam_id,))
        return _to_exam(row) if row else None

    async def get_by_code(self, test_code: str) -> Exam | None:
        """Test kodi bo'yicha imtihonni topadi (kod katta harfda saqlanadi)."""
        row = await self._db.fetchone(
            "SELECT * FROM exams WHERE test_code = ?", (test_code.strip().upper(),)
        )
        return _to_exam(row) if row else None

    async def code_exists(self, test_code: str) -> bool:
        """Bunday test kodi band qilinganmi?"""
        count = await self._db.fetchvalue(
            "SELECT COUNT(*) FROM exams WHERE test_code = ?",
            (test_code.strip().upper(),),
            default=0,
        )
        return int(count) > 0

    async def list_all(self, limit: int = 100) -> list[Exam]:
        """Barcha imtihonlar (eng yangisidan) — admin ro'yxati uchun."""
        rows = await self._db.fetchall(
            "SELECT * FROM exams ORDER BY start_time DESC, exam_id DESC LIMIT ?", (limit,)
        )
        return [_to_exam(row) for row in rows]

    async def list_relevant(self, now_iso: str, limit: int = 50) -> list[Exam]:
        """Natijasi hali e'lon qilinmagan imtihonlar ("Navbat" bo'limi uchun).

        Ya'ni `result_time > now`: kutilayotgan, faol va qabul tugagan
        imtihonlar. Faol imtihon birinchi turadi.
        """
        rows = await self._db.fetchall(
            """
            SELECT * FROM exams
            WHERE result_time > ?
            ORDER BY (start_time <= ? AND end_time > ?) DESC, start_time ASC
            LIMIT ?
            """,
            (now_iso, now_iso, now_iso, limit),
        )
        return [_to_exam(row) for row in rows]

    async def list_published_for_user(
        self, user_id: int, now_iso: str, limit: int = 100, offset: int = 0
    ) -> list[Exam]:
        """O'quvchi qatnashgan va natijasi E'LON QILINGAN imtihonlar.

        «🔍 Test tahlili» bo'limi uchun: faqat javob yuborilgan hamda
        `result_time <= now` bo'lgan imtihonlar (eng yangisidan).
        """
        rows = await self._db.fetchall(
            """
            SELECT e.* FROM user_answers ua
            JOIN exams e ON e.exam_id = ua.exam_id
            WHERE ua.user_id = ? AND e.result_time <= ?
            ORDER BY e.start_time DESC, e.exam_id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, now_iso, limit, offset),
        )
        return [_to_exam(row) for row in rows]

    async def count_published_for_user(self, user_id: int, now_iso: str) -> int:
        """O'quvchi qatnashgan, natijasi e'lon qilingan imtihonlar soni."""
        return int(
            await self._db.fetchvalue(
                """
                SELECT COUNT(*) FROM user_answers ua
                JOIN exams e ON e.exam_id = ua.exam_id
                WHERE ua.user_id = ? AND e.result_time <= ?
                """,
                (user_id, now_iso),
                default=0,
            )
        )

    async def list_pending_grading(self, now_iso: str) -> list[Exam]:
        """Javob qabul qilish tugagan, ammo hali baholanmagan imtihonlar."""
        rows = await self._db.fetchall(
            """
            SELECT * FROM exams
            WHERE graded_at IS NULL AND end_time <= ?
            ORDER BY end_time ASC
            """,
            (now_iso,),
        )
        return [_to_exam(row) for row in rows]

    async def mark_graded(self, exam_id: int, graded_at: str) -> None:
        """Imtihonni "baholandi" deb belgilaydi (fon vazifasi idempotentligi)."""
        await self._db.execute(
            "UPDATE exams SET graded_at = ? WHERE exam_id = ?", (graded_at, exam_id)
        )

    async def count(self) -> int:
        """Jami imtihonlar soni."""
        return int(await self._db.fetchvalue("SELECT COUNT(*) FROM exams", default=0))

    async def update_times(
        self,
        exam_id: int,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        result_time: str | None = None,
    ) -> None:
        """Imtihon vaqtlarini tanlab yangilaydi (masalan, muddatni uzaytirish).

        Faqat `None` bo'lmagan maydonlar yoziladi.
        """
        fields: list[str] = []
        params: list[object] = []
        for column, value in (
            ("start_time", start_time),
            ("end_time", end_time),
            ("result_time", result_time),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                params.append(value)
        if not fields:
            return
        params.append(exam_id)
        await self._db.execute(f"UPDATE exams SET {', '.join(fields)} WHERE exam_id = ?", params)

    async def delete(self, exam_id: int) -> None:
        """Imtihonni o'chiradi (javoblar ham CASCADE bilan o'chadi)."""
        await self._db.execute("DELETE FROM exams WHERE exam_id = ?", (exam_id,))


class ExamAnswerRepository:
    """`user_answers` jadvali bilan ishlash (javoblar va natijalar)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def submit(self, *, user_id: int, exam_id: int, submitted_answers: str) -> int:
        """O'quvchi javoblarini saqlaydi va `id` ni qaytaradi.

        Raises:
            AlreadySubmittedError: bu o'quvchi allaqachon javob yuborgan bo'lsa.
        """
        try:
            return await self._db.execute(
                """
                INSERT INTO user_answers (user_id, exam_id, submitted_answers)
                VALUES (?, ?, ?)
                """,
                (user_id, exam_id, submitted_answers),
            )
        except sqlite3.IntegrityError as exc:
            raise AlreadySubmittedError(
                f"user_id={user_id} allaqachon exam_id={exam_id} ga javob yuborgan"
            ) from exc

    async def get(self, user_id: int, exam_id: int) -> ExamSubmission | None:
        """Bitta o'quvchining bitta imtihon bo'yicha javobini qaytaradi."""
        row = await self._db.fetchone(
            """
            SELECT ua.*, e.title AS exam_title, e.total_questions AS total_questions,
                   e.result_time AS result_time
            FROM user_answers ua
            JOIN exams e ON e.exam_id = ua.exam_id
            WHERE ua.user_id = ? AND ua.exam_id = ?
            """,
            (user_id, exam_id),
        )
        return _to_submission(row) if row else None

    async def list_for_user(self, user_id: int, limit: int = 50) -> list[ExamSubmission]:
        """O'quvchining barcha javoblari (eng yangisidan) — "Natijalar" bo'limi."""
        rows = await self._db.fetchall(
            """
            SELECT ua.*, e.title AS exam_title, e.total_questions AS total_questions,
                   e.result_time AS result_time
            FROM user_answers ua
            JOIN exams e ON e.exam_id = ua.exam_id
            WHERE ua.user_id = ?
            ORDER BY e.start_time DESC, ua.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [_to_submission(row) for row in rows]

    async def list_for_exam(self, exam_id: int) -> list[ExamSubmission]:
        """Imtihonga tegishli barcha javoblar (baholash uchun)."""
        rows = await self._db.fetchall(
            "SELECT * FROM user_answers WHERE exam_id = ? ORDER BY id", (exam_id,)
        )
        return [_to_submission(row) for row in rows]

    async def list_ungraded(self, exam_id: int) -> list[ExamSubmission]:
        """Hali θ hisoblanmagan javoblar (faqat shu imtihon bo'yicha)."""
        rows = await self._db.fetchall(
            "SELECT * FROM user_answers WHERE exam_id = ? AND theta IS NULL ORDER BY id",
            (exam_id,),
        )
        return [_to_submission(row) for row in rows]

    async def list_due_notifications(
        self, now: str, limit: int = 200
    ) -> list[ExamSubmission]:
        """Natijasi e'lon qilingan, ammo xabar hali yuborilmagan javoblar.

        Shartlar: `result_time` o'tgan, imtihon baholangan (`graded_at`),
        javobda θ bor va `notified_at` bo'sh. Har bir javob — bir marta.
        """
        rows = await self._db.fetchall(
            """
            SELECT ua.*, e.title AS exam_title, e.total_questions AS total_questions,
                   e.result_time AS result_time
            FROM user_answers ua
            JOIN exams e ON e.exam_id = ua.exam_id
            WHERE ua.notified_at IS NULL
              AND ua.theta IS NOT NULL
              AND e.graded_at IS NOT NULL
              AND e.result_time <= ?
            ORDER BY e.result_time ASC, ua.id ASC
            LIMIT ?
            """,
            (now, int(limit)),
        )
        return [_to_submission(row) for row in rows]

    async def mark_notified(self, submission_id: int, now: str) -> None:
        """Natija xabari yuborilganini belgilaydi (idempotent)."""
        await self._db.execute(
            """
            UPDATE user_answers SET notified_at = ?
            WHERE id = ? AND notified_at IS NULL
            """,
            (now, int(submission_id)),
        )

    async def save_score(
        self,
        submission_id: int,
        *,
        theta: float,
        scaled_score: float,
        raw_score: int,
    ) -> None:
        """Bitta javob uchun θ, 0–100 ball va xom ballni yozadi."""
        await self._db.execute(
            """
            UPDATE user_answers
            SET theta = ?, scaled_score = ?, raw_score = ?
            WHERE id = ?
            """,
            (round(float(theta), 4), round(float(scaled_score), 2), int(raw_score), submission_id),
        )

    async def save_scores(self, rows: Iterable[Sequence[object]]) -> None:
        """Bir nechta javob natijasini bitta tranzaksiyada yozadi."""
        payload = list(rows)
        if not payload:
            return
        await self._db.execute_many(
            "UPDATE user_answers SET theta = ?, scaled_score = ?, raw_score = ? WHERE id = ?",
            payload,
        )

    async def count_for_user(self, user_id: int) -> int:
        """O'quvchi nechta imtihonga javob yuborgan (profil uchun)."""
        return int(
            await self._db.fetchvalue(
                "SELECT COUNT(*) FROM user_answers WHERE user_id = ?", (user_id,), default=0
            )
        )

    async def count_for_exam(self, exam_id: int) -> int:
        """Imtihonga nechta o'quvchi javob yuborgan."""
        return int(
            await self._db.fetchvalue(
                "SELECT COUNT(*) FROM user_answers WHERE exam_id = ?", (exam_id,), default=0
            )
        )

    async def count(self) -> int:
        """Jami yuborilgan javoblar soni (barcha imtihonlar bo'yicha)."""
        return int(await self._db.fetchvalue("SELECT COUNT(*) FROM user_answers", default=0))


def _to_solution(row: dict) -> Solution:
    return Solution(
        solution_id=row["solution_id"],
        exam_id=row["exam_id"],
        question_number=row["question_number"],
        part=row["part"] or PART_WHOLE,
        solution_type=row["solution_type"],
        solution_file_id=row["solution_file_id"],
        created_by=row["created_by"],
        updated_at=row["updated_at"],
    )


class SolutionRepository:
    """`solutions` jadvali — savollarning video/rasm yechimlari.

    Har bir yozuv «imtihon + savol raqami (+ A/B qismi)» juftligiga bog'lanadi.
    O'qituvchi bir savolga yechimni qayta yuklasa — mavjud yozuv yangilanadi
    (`upsert`), ya'ni dublikat yaratilmaydi.

    Yechim faqat Telegram fayli (`file_id`) ko'rinishida saqlanadi — matnli
    yechim qo'llanmaydi (faqat video va rasm).
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self,
        *,
        exam_id: int,
        question_number: int,
        solution_type: str,
        part: str = PART_WHOLE,
        solution_file_id: str | None = None,
        created_by: int | None = None,
    ) -> int:
        """Yechimni saqlaydi (mavjud bo'lsa — yangilaydi) va `solution_id` qaytaradi.

        Raises:
            ValueError: qism noto'g'ri yoki `file_id` berilmagan bo'lsa.
        """
        part = normalize_part(part)
        file_id = str(solution_file_id or "").strip()
        if not file_id:
            raise ValueError("Yechim faqat Telegram fayli (file_id) bilan saqlanadi")
        await self._db.execute(
            """
            INSERT INTO solutions (
                exam_id, question_number, part, solution_type,
                solution_file_id, created_by
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (exam_id, question_number, part) DO UPDATE SET
                solution_type    = excluded.solution_type,
                solution_file_id = excluded.solution_file_id,
                created_by       = excluded.created_by,
                updated_at       = datetime('now', 'localtime')
            """,
            (
                int(exam_id),
                int(question_number),
                part,
                str(solution_type),
                file_id,
                created_by,
            ),
        )
        row = await self._db.fetchone(
            """
            SELECT solution_id FROM solutions
            WHERE exam_id = ? AND question_number = ? AND part = ?
            """,
            (int(exam_id), int(question_number), part),
        )
        return int(row["solution_id"]) if row else 0

    async def get(
        self, exam_id: int, question_number: int, part: str = PART_WHOLE
    ) -> Solution | None:
        """Bitta savol (yoki uning qismi) bo'yicha yechimni qaytaradi."""
        row = await self._db.fetchone(
            """
            SELECT * FROM solutions
            WHERE exam_id = ? AND question_number = ? AND part = ?
            """,
            (int(exam_id), int(question_number), normalize_part(part)),
        )
        return _to_solution(row) if row else None

    async def list_for_exam(self, exam_id: int) -> list[Solution]:
        """Imtihondagi barcha yechimlar (savol raqami bo'yicha tartiblangan)."""
        rows = await self._db.fetchall(
            """
            SELECT * FROM solutions
            WHERE exam_id = ?
            ORDER BY question_number ASC, part ASC
            """,
            (int(exam_id),),
        )
        return [_to_solution(row) for row in rows]

    async def parts_for_exam(self, exam_id: int) -> dict[int, list[str]]:
        """A/B qismli savollar xaritasi: {36: ["a", "b"], ...}.

        Faqat qismlarga bo'lingan yechimlar hisobga olinadi ("" — butun savol
        xaritaga kirmaydi).
        """
        rows = await self._db.fetchall(
            """
            SELECT DISTINCT question_number, part FROM solutions
            WHERE exam_id = ? AND part <> ''
            ORDER BY question_number ASC, part ASC
            """,
            (int(exam_id),),
        )
        parts: dict[int, list[str]] = {}
        for row in rows:
            parts.setdefault(int(row["question_number"]), []).append(str(row["part"]))
        return parts

    async def count_for_exam(self, exam_id: int) -> int:
        """Imtihon bo'yicha yuklangan yechimlar soni."""
        return int(
            await self._db.fetchvalue(
                "SELECT COUNT(*) FROM solutions WHERE exam_id = ?", (int(exam_id),), default=0
            )
        )

    async def count(self) -> int:
        """Jami yechim yozuvlari soni (eski matnli yozuvlar ham kiradi)."""
        return int(await self._db.fetchvalue("SELECT COUNT(*) FROM solutions", default=0))

    async def count_files(self) -> int:
        """Faqat faylli (video/rasm) yechimlar soni — statistika uchun.

        Bazada eski matnli yozuvlar qolgan bo'lsa ular hisobga olinmaydi:
        matnli yechim qo'llanmaydi (`is_file` False).
        """
        return int(
            await self._db.fetchvalue(
                "SELECT COUNT(*) FROM solutions WHERE solution_file_id IS NOT NULL "
                "AND solution_file_id <> ''",
                default=0,
            )
        )

    async def delete(self, exam_id: int, question_number: int, part: str = PART_WHOLE) -> None:
        """Bitta savol (yoki qism) yechimini o'chiradi."""
        await self._db.execute(
            """
            DELETE FROM solutions
            WHERE exam_id = ? AND question_number = ? AND part = ?
            """,
            (int(exam_id), int(question_number), normalize_part(part)),
        )


# ---------------------------------------------------------------------------
# MVP item-level qatlam (docs/11) — forms, sessions, attempts, responses,
# scoring snapshots. Hozirgi `exams`/`user_answers` oqimi O'ZGARMAYDI: ikkala
# oqim parallel ishlaydi (eski API v1 va Web App tegilmaydi).
#
# Izoh: bu jadvallar uchun dataclass modellar hali `database/models.py` da
# yo'q, shu sababli o'qish metodlari **xom `dict` satrlarni** qaytaradi
# (modellar keyingi bosqichda qo'shiladi). Yozish metodlari qat'iy tipli.
# ---------------------------------------------------------------------------

SESSION_STATUSES: frozenset[str] = frozenset(
    {"scheduled", "active", "closed", "graded", "published", "cancelled"}
)
ATTEMPT_STATUSES: frozenset[str] = frozenset(
    {"in_progress", "submitted", "submitted_late", "graded", "invalid"}
)
SUBMIT_MODES: frozenset[str] = frozenset({"manual", "auto_timeout", "admin"})


def _check_allowed(value: str, allowed: frozenset[str], *, label: str) -> str:
    """Qiymat ruxsat etilganlar ichida ekanini tekshiradi.

    Raises:
        ValueError: qiymat ro'yxatda bo'lmasa (DB `CHECK` xatosi o'rniga).
    """
    if value not in allowed:
        options = ", ".join(sorted(allowed))
        raise ValueError(
            f"{label} quyidagilardan biri bo'lishi kerak: {options}. Berilgan: {value!r}"
        )
    return value


class FormRepository:
    """`forms`, `form_versions`, `form_items` — test formasi, kalit va savollar.

    Kalit `form_versions` ga **snapshot** sifatida yoziladi (eski urinishlar
    kalit keyin tuzatilishidan zarar ko'rmasligi uchun).
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_with_version(
        self,
        *,
        title: str,
        test_code: str,
        total_questions: int,
        answer_key: str,
        items: Iterable[Sequence[object]] = (),
        subject_code: str | None = None,
        options_count: int = 4,
        parts: Sequence[str] = (),
        status: str = "published",
        created_by: int | None = None,
    ) -> tuple[int, int]:
        """Forma + 1-versiya + savollarni **bitta tranzaksiyada** yaratadi.

        Args:
            title: forma nomi.
            test_code: o'quvchi kiritadigan kod.
            total_questions: savollar soni.
            answer_key: kanonik kalit (`1A2B…35F|36:12.5`).
            items: savollar satrlari; har biri —
                ``(position, display_label, part, section_no, correct_option,
                options_count, item_version_id, points)``.
            subject_code: fan kodi (ixtiyoriy).
            options_count: standart variantlar soni.
            parts: qismli savollar belgilari (`["36a", "36b"]`).
            status: `form_versions.status` (`draft`/`published`/`retired`).
            created_by: o'qituvchi (Telegram ID).

        Qaytaradi:
            ``(form_id, form_version_id)``.

        Raises:
            ValueError: biror savol satrida `item_version_id` bo'sh bo'lsa
                (yozuv boshlanmaydi — forma ham, savollar ham yaratilmaydi).
            sqlite3.IntegrityError: test kodi band bo'lsa.
        """
        rows = [tuple(row) for row in items]
        # Item-level bog'lanish MAJBURIY (docs/11, 4.2-bo'lim): `item_version_id`
        # NULL yozilsa, keyinchalik autosave har bir javobni rad etardi (M2
        # latent nuqsoni). Tekshiruv ATAYLAB yozuvdan OLDIN: hech qanday INSERT
        # boshlanmaydi, tranzaksiya ochilmaydi va qisman yozuv qolmaydi.
        for offset, row in enumerate(rows, start=1):
            if len(row) < 7:
                raise ValueError(
                    f"{offset}-savol satri to'liq emas: 8 ta element kutilgan "
                    "(position, display_label, part, section_no, correct_option, "
                    "options_count, item_version_id, points), berilgan: "
                    f"{len(row)} ta."
                )
            if row[6] is None:
                raise ValueError(
                    f"{row[0]}-savolda `item_version_id` yo'q — item-level "
                    "bog'lanish majburiy (forma yaratilmadi, bazaga hech narsa "
                    "yozilmadi). Avval `items`/`item_versions` ni yaratib, keyin "
                    "formani yarating."
                )

        conn = self._db.connection

        cursor = await conn.execute(
            """
            INSERT INTO forms (
                title, test_code, subject_code, total_questions, options_count,
                parts_json, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                test_code.strip().upper(),
                subject_code,
                int(total_questions),
                int(options_count),
                json.dumps(list(parts), ensure_ascii=False),
                created_by,
            ),
        )
        form_id = int(cursor.lastrowid or 0)

        cursor = await conn.execute(
            """
            INSERT INTO form_versions (
                form_id, version_no, answer_key, total_questions, status, created_by,
                published_at
            ) VALUES (?, 1, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
            """,
            (form_id, answer_key, int(total_questions), status, created_by),
        )
        form_version_id = int(cursor.lastrowid or 0)

        await conn.execute(
            "UPDATE forms SET current_version_id = ? WHERE form_id = ?",
            (form_version_id, form_id),
        )

        if rows:
            await conn.executemany(
                """
                INSERT INTO form_items (
                    form_version_id, position, display_label, part, section_no,
                    correct_option, options_count, item_version_id, points
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        form_version_id,
                        int(row[0]),
                        str(row[1]),
                        str(row[2] or ""),
                        None if row[3] is None else int(row[3]),
                        None if row[4] is None else str(row[4]),
                        int(row[5]) if row[5] is not None else int(options_count),
                        None if row[6] is None else int(row[6]),
                        float(row[7]) if row[7] is not None else 1.0,
                    )
                    for row in rows
                ],
            )

        await conn.commit()
        logger.debug(
            "Forma yaratildi: form_id=%s, versiya=%s, savollar=%d",
            form_id,
            form_version_id,
            len(rows),
        )
        return form_id, form_version_id

    async def create_full_form(
        self,
        *,
        title: str,
        test_code: str,
        total_questions: int,
        answer_key: str,
        questions: Iterable[Mapping[str, Any]],
        subject_code: str | None = None,
        item_ref_prefix: str | None = None,
        options_count: int = 4,
        parts: Sequence[str] = (),
        status: str = "published",
        created_by: int | None = None,
    ) -> tuple[int, int]:
        """Forma + versiya + savollarni **item-level bog'lanish bilan** yozadi.

        Har bir savol uchun `items` + `item_versions` satrlari yaratiladi
        (kalit, `item_type` va `answer_spec` shu yerda saqlanadi) va
        `form_items.item_version_id` o'sha versiyaga bog'lanadi.

        `questions` elementlari (kalitlar bo'yicha):
            ``position``, ``display_label``, ``part``, ``section_no``,
            ``item_type`` (mcq4/mcq6/numeric/text), ``correct_option``,
            ``options_count``, ``answer_spec`` (JSON satri), ``points``.

        Hamma yozuv **bitta tranzaksiyada**: biror qadam yiqilsa hammasi
        qaytariladi va hech narsa saqlanmaydi.

        Qaytaradi:
            ``(form_id, form_version_id)``.

        Raises:
            sqlite3.IntegrityError: cheklov buzilsa (test kodi band, `item_ref`
                takrorlangan va h.k.) — yozuvlar saqlanmaydi.
        """
        rows = [dict(question) for question in questions]
        conn = self._db.connection

        try:
            cursor = await conn.execute(
                """
                INSERT INTO forms (
                    title, test_code, subject_code, total_questions, options_count,
                    parts_json, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    test_code.strip().upper(),
                    subject_code,
                    int(total_questions),
                    int(options_count),
                    json.dumps(list(parts), ensure_ascii=False),
                    created_by,
                ),
            )
            form_id = int(cursor.lastrowid or 0)

            cursor = await conn.execute(
                """
                INSERT INTO form_versions (
                    form_id, version_no, answer_key, total_questions, status, created_by,
                    published_at
                ) VALUES (?, 1, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
                """,
                (form_id, answer_key, int(total_questions), status, created_by),
            )
            form_version_id = int(cursor.lastrowid or 0)

            prefix = (item_ref_prefix or str(test_code).strip().upper()).strip()
            form_items: list[tuple[Any, ...]] = []

            for question in rows:
                position = int(question["position"])
                # Phase 3 Step 2: qismli savolda `item_ref` ham noyob bo'lishi
                # kerak (36a va 36b — bir pozitsiya, ikki item). Legacy
                # `part = ""` da natija avvalgidek qoladi.
                part = str(question.get("part") or "")
                item_ref = f"{prefix}-{form_id}-{position}{part}"
                cursor = await conn.execute(
                    """
                    INSERT INTO items (item_ref, subject_code, status, created_by)
                    VALUES (?, ?, 'active', ?)
                    """,
                    (item_ref, subject_code, created_by),
                )
                item_id = int(cursor.lastrowid or 0)

                points = (
                    float(question["points"])
                    if question.get("points") is not None
                    else 1.0
                )
                raw_options = question.get("options_count")
                option_total = (
                    int(raw_options) if raw_options is not None else int(options_count)
                )
                cursor = await conn.execute(
                    """
                    INSERT INTO item_versions (
                        item_id, version_no, item_type, correct_option, answer_spec,
                        max_score, is_current, key_source, created_by
                    ) VALUES (?, 1, ?, ?, ?, ?, 1, 'teacher', ?)
                    """,
                    (
                        item_id,
                        str(question.get("item_type") or "mcq4"),
                        question.get("correct_option"),
                        str(question.get("answer_spec") or "{}"),
                        points,
                        created_by,
                    ),
                )
                item_version_id = int(cursor.lastrowid or 0)

                # Operatsion `b` (logit) — o'qituvchi foizidan hisoblangan
                # (`exam_service.percent_to_logit`). `source` qiymati
                # `item_parameters.source` CHECK lug'atidan olinadi:
                # o'qituvchi bahosi — 'legacy_expert' ("muallif bahosi"),
                # ma'lumot bo'lmasa — 'default'.
                b_value = float(question.get("difficulty") or 0.0)
                await conn.execute(
                    """
                    INSERT INTO item_parameters (
                        item_version_id, b_value, source, status, valid_from
                    ) VALUES (?, ?, ?, 'provisional',
                              strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
                    """,
                    (
                        item_version_id,
                        b_value,
                        "legacy_expert" if abs(b_value) > 0.0 else "default",
                    ),
                )

                form_items.append(
                    (
                        form_version_id,
                        position,
                        str(question.get("display_label") or position),
                        str(question.get("part") or ""),
                        None
                        if question.get("section_no") is None
                        else int(question["section_no"]),
                        question.get("correct_option"),
                        option_total,
                        item_version_id,
                        points,
                    )
                )

            if form_items:
                await conn.executemany(
                    """
                    INSERT INTO form_items (
                        form_version_id, position, display_label, part, section_no,
                        correct_option, options_count, item_version_id, points
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    form_items,
                )

            await conn.execute(
                "UPDATE forms SET current_version_id = ? WHERE form_id = ?",
                (form_version_id, form_id),
            )
        except Exception:
            # Tranzaksiya to'liq qaytariladi: forms, form_versions, form_items,
            # items va item_versions — hech biri saqlanmaydi.
            await conn.rollback()
            logger.exception("Forma yaratilmadi (tranzaksiya qaytarildi): %s", test_code)
            raise

        await conn.commit()
        logger.debug(
            "Item-level forma yaratildi: form_id=%s, versiya=%s, savollar=%d",
            form_id,
            form_version_id,
            len(form_items),
        )
        return form_id, form_version_id

    async def get_by_test_code(self, test_code: str) -> dict[str, Any] | None:
        """O'chirilmagan formani test kodi bo'yicha qaytaradi."""
        return await self._db.fetchone(
            "SELECT * FROM forms WHERE test_code = ? AND deleted_at IS NULL",
            (test_code.strip().upper(),),
        )

    async def get_form(self, form_id: int) -> dict[str, Any] | None:
        """Forma satri."""
        return await self._db.fetchone(
            "SELECT * FROM forms WHERE form_id = ?", (int(form_id),)
        )

    async def get_version(self, form_version_id: int) -> dict[str, Any] | None:
        """Kalit snapshot'i (versiya satri)."""
        return await self._db.fetchone(
            "SELECT * FROM form_versions WHERE form_version_id = ?",
            (int(form_version_id),),
        )

    async def current_version_id(self, form_id: int) -> int | None:
        """Formaning joriy versiyasi (yo'q bo'lsa — `None`)."""
        value = await self._db.fetchvalue(
            "SELECT current_version_id FROM forms WHERE form_id = ?", (int(form_id),)
        )
        return int(value) if value is not None else None

    async def list_items(self, form_version_id: int) -> list[dict[str, Any]]:
        """Versiyadagi savollar (pozitsiya bo'yicha, `item_id` bilan birga).

        `form_items` da `item_id` yo'q — u `item_versions` orqali olinadi
        (item-level javoblarni yozishda kerak bo'ladi).
        """
        return await self._db.fetchall(
            """
            SELECT fi.*, iv.item_id AS item_id
            FROM form_items fi
            LEFT JOIN item_versions iv ON iv.item_version_id = fi.item_version_id
            WHERE fi.form_version_id = ?
            ORDER BY fi.position ASC, fi.part ASC
            """,
            (int(form_version_id),),
        )

    async def items_by_position(self, form_version_id: int) -> dict[int, dict[str, Any]]:
        """`{position: savol satri}` xaritasi (MVP: har pozitsiyaga bitta qism)."""
        rows = await self.list_items(form_version_id)
        return {int(row["position"]): row for row in rows}

    async def items_by_label(self, form_version_id: int) -> dict[str, dict[str, Any]]:
        """`{label: savol satri}` xaritasi (Phase 3 Step 2).

        Label — `display_label` + `part` (takrorlanmasdan): `"36"` (legacy) yoki
        `"36a"` / `"36b"` (qismli). Qismli savolda 36a va 36b ikki xil satrga
        ishora qiladi — shu sababli ular mustaqil yoziladi.
        """
        rows = await self.list_items(form_version_id)
        return {_response_label(row): row for row in rows}

    async def count_forms(self) -> int:
        """O'chirilmagan formalar soni."""
        return int(
            await self._db.fetchvalue(
                "SELECT COUNT(*) FROM forms WHERE deleted_at IS NULL", default=0
            )
        )


class ExamSessionRepository:
    """`exam_sessions` — vaqt oynasi (start / end / result)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        form_id: int,
        start_time: str,
        end_time: str,
        result_time: str,
        title: str | None = None,
        status: str = "scheduled",
        created_by: int | None = None,
    ) -> int:
        """Sessiya yaratadi va `session_id` ni qaytaradi (vaqtlar — UTC ISO).

        Raises:
            ValueError: holat ruxsat etilmagan bo'lsa.
            sqlite3.IntegrityError: vaqt tartibi buzilgan bo'lsa (`CHECK`).
        """
        _check_allowed(status, SESSION_STATUSES, label="Sessiya holati")
        return await self._db.execute(
            """
            INSERT INTO exam_sessions (
                form_id, title, start_time, end_time, result_time, status, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(form_id),
                title,
                start_time,
                end_time,
                result_time,
                status,
                created_by,
            ),
        )

    async def get(self, session_id: int) -> dict[str, Any] | None:
        """Sessiya satri."""
        return await self._db.fetchone(
            "SELECT * FROM exam_sessions WHERE session_id = ?", (int(session_id),)
        )

    async def get_by_test_code(self, test_code: str) -> dict[str, Any] | None:
        """Test kodi bo'yicha eng yangi sessiya (+ forma va joriy versiya).

        Natijada `form_version_id`, `total_questions`, `options_count`,
        `parts_json` ham bo'ladi — kod tekshirish uchun qulay.
        """
        return await self._db.fetchone(
            """
            SELECT s.*, f.title AS form_title, f.test_code AS test_code,
                   f.total_questions AS total_questions,
                   f.options_count AS options_count,
                   f.parts_json AS parts_json,
                   f.current_version_id AS form_version_id
            FROM exam_sessions s
            JOIN forms f ON f.form_id = s.form_id
            WHERE f.test_code = ? AND f.deleted_at IS NULL AND s.deleted_at IS NULL
            ORDER BY s.start_time DESC
            LIMIT 1
            """,
            (test_code.strip().upper(),),
        )

    async def set_status(
        self, session_id: int, status: str, *, graded_at: str | None = None
    ) -> None:
        """Sessiya holatini yangilaydi (`graded_at` berilsa — yoziladi)."""
        _check_allowed(status, SESSION_STATUSES, label="Sessiya holati")
        await self._db.execute(
            """
            UPDATE exam_sessions
            SET status = ?,
                graded_at = COALESCE(?, graded_at),
                updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
            WHERE session_id = ?
            """,
            (status, graded_at, int(session_id)),
        )

    async def list_pending_grading(self, now_db: str) -> list[dict[str, Any]]:
        """Muddati tugagan, hali baholanmagan sessiyalar (`end_time <= now`)."""
        return await self._db.fetchall(
            """
            SELECT s.*, f.current_version_id AS form_version_id
            FROM exam_sessions s
            JOIN forms f ON f.form_id = s.form_id
            WHERE s.end_time <= ?
              AND s.graded_at IS NULL
              AND s.deleted_at IS NULL
              AND s.status IN ('active', 'closed')
            ORDER BY s.end_time ASC
            """,
            (now_db,),
        )


class AttemptRepository:
    """`attempts` — bitta o'quvchining bitta sessiyadagi urinishi.

    Bir o'quvchi + bir sessiya = bir urinish (partial unique indeks
    `ux_attempts_session_user`), shu sababli `get_or_create` **idempotent**.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_or_create(
        self,
        *,
        session_id: int,
        user_id: int,
        form_version_id: int,
        started_at: str,
    ) -> int:
        """Mavjud urinishni qaytaradi yoki yangisini yaratadi (`attempt_id`)."""
        existing = await self.get_for_user(session_id, user_id)
        if existing is not None:
            return int(existing["attempt_id"])

        try:
            return await self._db.execute(
                """
                INSERT INTO attempts (session_id, user_id, form_version_id, started_at,
                                      last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(session_id), int(user_id), int(form_version_id), started_at, started_at),
            )
        except sqlite3.IntegrityError:
            # Parallel so'rov yaratib ulgurgan bo'lishi mumkin — mavjudini olamiz.
            existing = await self.get_for_user(session_id, user_id)
            if existing is None:  # pragma: no cover - boshqa integrity sababi
                raise
            return int(existing["attempt_id"])

    async def get(self, attempt_id: int) -> dict[str, Any] | None:
        """Urinish satri."""
        return await self._db.fetchone(
            "SELECT * FROM attempts WHERE attempt_id = ?", (int(attempt_id),)
        )

    async def get_for_user(self, session_id: int, user_id: int) -> dict[str, Any] | None:
        """O'quvchining shu sessiyadagi o'chirilmagan urinishi."""
        return await self._db.fetchone(
            """
            SELECT * FROM attempts
            WHERE session_id = ? AND user_id = ? AND deleted_at IS NULL
            """,
            (int(session_id), int(user_id)),
        )

    async def touch(
        self,
        attempt_id: int,
        last_seen_at: str,
        *,
        revision: int | None = None,
        interaction_count: int | None = None,
        last_interaction_position: int | None = None,
    ) -> None:
        """Autosave "heartbeat": oxirgi ko'rilgan vaqt va hisoblagichlar."""
        await self._db.execute(
            """
            UPDATE attempts
            SET last_seen_at = ?,
                revision = COALESCE(?, revision),
                interaction_count = COALESCE(?, interaction_count),
                last_interaction_position = COALESCE(?, last_interaction_position),
                updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
            WHERE attempt_id = ?
            """,
            (
                last_seen_at,
                revision,
                interaction_count,
                last_interaction_position,
                int(attempt_id),
            ),
        )

    async def mark_submitted(
        self,
        attempt_id: int,
        *,
        submitted_at: str,
        submit_mode: str,
        duration_seconds: int | None = None,
        status: str = "submitted",
    ) -> None:
        """Urinishni yakunlaydi (javob qabul qilish tugadi).

        Raises:
            ValueError: `submit_mode` yoki `status` ruxsat etilmagan bo'lsa.
        """
        _check_allowed(status, ATTEMPT_STATUSES, label="Urinish holati")
        _check_allowed(submit_mode, SUBMIT_MODES, label="Yakunlash usuli")
        await self._db.execute(
            """
            UPDATE attempts
            SET status = ?, submit_mode = ?, submitted_at = ?,
                duration_seconds = COALESCE(?, duration_seconds),
                updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
            WHERE attempt_id = ?
            """,
            (status, submit_mode, submitted_at, duration_seconds, int(attempt_id)),
        )

    async def set_status(self, attempt_id: int, status: str) -> None:
        """Urinish holatini yangilaydi (masalan `graded`).

        Raises:
            ValueError: holat ruxsat etilmagan bo'lsa.
        """
        _check_allowed(status, ATTEMPT_STATUSES, label="Urinish holati")
        await self._db.execute(
            """
            UPDATE attempts
            SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
            WHERE attempt_id = ?
            """,
            (status, int(attempt_id)),
        )

    async def save_result(
        self,
        attempt_id: int,
        *,
        theta: float,
        theta_se: float | None,
        scaled_score: float,
        raw_score: int,
        n_answered: int,
        n_omitted: int,
        n_not_reached: int,
        engine_version: str,
        is_extreme_low: bool = False,
        is_extreme_high: bool = False,
    ) -> None:
        """Baholash natijasini urinishga yozadi (item-level oqim uchun)."""
        await self._db.execute(
            """
            UPDATE attempts
            SET theta = ?, theta_se = ?, scaled_score = ?, raw_score = ?,
                n_answered = ?, n_omitted = ?, n_not_reached = ?,
                engine_version = ?, is_extreme_low = ?, is_extreme_high = ?,
                status = 'graded',
                updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
            WHERE attempt_id = ?
            """,
            (
                float(theta),
                None if theta_se is None else float(theta_se),
                float(scaled_score),
                int(raw_score),
                int(n_answered),
                int(n_omitted),
                int(n_not_reached),
                engine_version,
                1 if is_extreme_low else 0,
                1 if is_extreme_high else 0,
                int(attempt_id),
            ),
        )

    async def count_for_session(self, session_id: int) -> int:
        """Sessiyadagi o'chirilmagan urinishlar soni."""
        return int(
            await self._db.fetchvalue(
                """
                SELECT COUNT(*) FROM attempts
                WHERE session_id = ? AND deleted_at IS NULL
                """,
                (int(session_id),),
                default=0,
            )
        )

    async def list_for_session(self, session_id: int) -> list[dict[str, Any]]:
        """Sessiyadagi o'chirilmagan urinishlar (qatnashchilar), tartibi bo'yicha.

        O'qituvchi analitikasi (`services.analytics`) qatnashchilar soni va
        holatlarini shu yerdan oladi; snapshot'lar esa
        `repos.snapshots.get_final(attempt_id)` orqali o'qiladi.
        """
        return await self._db.fetchall(
            """
            SELECT * FROM attempts
            WHERE session_id = ? AND deleted_at IS NULL
            ORDER BY attempt_id ASC
            """,
            (int(session_id),),
        )


RESPONSE_CAPTURE_STATUSES: frozenset[str] = frozenset({"answered", "blank", "not_reached"})
RESPONSE_ANSWER_KINDS: frozenset[str] = frozenset({"option", "numeric", "text"})
RESPONSE_EVENT_TYPES: frozenset[str] = frozenset(
    {"capture", "clear", "finalize", "admin_fix"}
)
RESPONSE_SOURCES: frozenset[str] = frozenset({"webapp", "bot", "admin", "system"})
SELECTED_OPTIONS: frozenset[str] = frozenset({"A", "B", "C", "D", "E", "F"})


def _response_label(row: Mapping[str, Any]) -> str:
    """Satrdan (`form_items` / `responses`) yagona savol belgisini oladi: "36", "36a".

    Phase 3 Step 2: qismli javoblar kaliti `(position, part)` dan yig'iladi.
    `display_label` allaqachon qismni o'z ichiga olishi mumkin ("36a") — shu
    sababli `part` faqat yetishmagan holatda qo'shiladi (takrorlanmaydi).
    Legacy yozuvlarda (`part = ''`) natija `str(position)` — avvalgidek.
    """
    label = str(row.get("display_label") or "").strip()
    part = str(row.get("part") or "").strip()
    if part and not label.endswith(part):
        label = f"{label}{part}"
    if not label:
        label = f"{int(row.get('position') or 0)}{part}"
    return label


class ResponseRepository:
    """`responses` — **append-only** javob logi (har o'zgarish = yangi revision).

    "Joriy" holat `is_current = 1` bilan o'qiladi (partial unique indeks
    kafolatlaydi). Revision zanjiri (`superseded_by`) MVP'da to'ldirilmaydi —
    joriy holat yetarli; to'liq zanjir P2 ishi.

    Diqqat: `responses.item_id` va `item_version_id` majburiy (FK), shuning
    uchun ular `form_items`/`item_versions` dan olinib beriladi.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def append(
        self,
        *,
        attempt_id: int,
        form_item_id: int,
        item_id: int,
        item_version_id: int,
        position: int,
        display_label: str,
        recorded_at: str,
        part: str = "",
        event_type: str = "capture",
        capture_status: str = "answered",
        answer_kind: str = "option",
        selected_option: str | None = None,
        raw_answer: str | None = None,
        normalized_answer: str | None = None,
        numeric_value: float | None = None,
        source: str = "webapp",
        client_seq: int | None = None,
    ) -> int:
        """Yangi revision yozadi va `response_id` ni qaytaradi.

        `client_seq` berilgan va ilgari yozilgan bo'lsa — **yangi satr
        yozilmaydi** (tarmoq qayta urinishi idempotent), mavjud `response_id`
        qaytariladi.

        Raises:
            ValueError: status/tur/manba qiymatlari ruxsat etilmagan bo'lsa.
            sqlite3.IntegrityError: `client_seq` yoki revision to'qnashsa.
        """
        _check_allowed(event_type, RESPONSE_EVENT_TYPES, label="Hodisa turi")
        _check_allowed(capture_status, RESPONSE_CAPTURE_STATUSES, label="Qabul holati")
        _check_allowed(answer_kind, RESPONSE_ANSWER_KINDS, label="Javob turi")
        _check_allowed(source, RESPONSE_SOURCES, label="Manba")
        if selected_option is not None:
            selected_option = str(selected_option).upper()
            _check_allowed(selected_option, SELECTED_OPTIONS, label="Tanlangan variant")

        if client_seq is not None:
            existing = await self.get_by_client_seq(attempt_id, client_seq)
            if existing is not None:
                return int(existing["response_id"])

        revision = int(
            await self._db.fetchvalue(
                """
                SELECT COALESCE(MAX(revision), 0) + 1 FROM responses
                WHERE attempt_id = ? AND form_item_id = ?
                """,
                (int(attempt_id), int(form_item_id)),
                default=1,
            )
        )

        conn = self._db.connection
        # Eski "joriy" satrni yopamiz va yangi revisionni yozamiz — atomar:
        # partial unique indeks bir vaqtda faqat bitta `is_current = 1` ga yo'l qo'yadi.
        await conn.execute(
            """
            UPDATE responses SET is_current = 0
            WHERE attempt_id = ? AND form_item_id = ? AND is_current = 1
            """,
            (int(attempt_id), int(form_item_id)),
        )
        cursor = await conn.execute(
            """
            INSERT INTO responses (
                attempt_id, item_id, item_version_id, form_item_id, position,
                display_label, part, revision, is_current, event_type,
                capture_status, answer_kind, selected_option, raw_answer,
                normalized_answer, numeric_value, source, client_seq, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(attempt_id),
                int(item_id),
                int(item_version_id),
                int(form_item_id),
                int(position),
                str(display_label),
                part,
                revision,
                event_type,
                capture_status,
                answer_kind,
                selected_option,
                raw_answer,
                normalized_answer,
                None if numeric_value is None else float(numeric_value),
                source,
                client_seq,
                recorded_at,
            ),
        )
        response_id = int(cursor.lastrowid or 0)
        await conn.commit()
        return response_id

    async def get(self, response_id: int) -> dict[str, Any] | None:
        """Bitta javob satri (revision tarixidan)."""
        return await self._db.fetchone(
            "SELECT * FROM responses WHERE response_id = ?", (int(response_id),)
        )

    async def get_by_client_seq(self, attempt_id: int, client_seq: int) -> dict[str, Any] | None:
        """Idempotentlik: qurilma yuborgan ketma-ketlik bo'yicha javob."""
        return await self._db.fetchone(
            """
            SELECT * FROM responses
            WHERE attempt_id = ? AND client_seq = ?
            """,
            (int(attempt_id), int(client_seq)),
        )

    async def current_for_item(self, attempt_id: int, form_item_id: int) -> dict[str, Any] | None:
        """Bitta savolning **joriy** javobi."""
        return await self._db.fetchone(
            """
            SELECT * FROM responses
            WHERE attempt_id = ? AND form_item_id = ? AND is_current = 1
            """,
            (int(attempt_id), int(form_item_id)),
        )

    async def list_current(self, attempt_id: int) -> list[dict[str, Any]]:
        """Urinishning barcha joriy javoblari (pozitsiya bo'yicha)."""
        return await self._db.fetchall(
            """
            SELECT * FROM responses
            WHERE attempt_id = ? AND is_current = 1
            ORDER BY position ASC, part ASC
            """,
            (int(attempt_id),),
        )

    async def current_by_label(self, attempt_id: int) -> dict[str, dict[str, Any]]:
        """`{"36": satr, "36a": satr}` ko'rinishidagi joriy javoblar xaritasi.

        Qismli savollarda kalit `display_label + part` bo'ladi.
        """
        rows = await self.list_current(attempt_id)
        return {_response_label(row): row for row in rows}

    async def count_current(self, attempt_id: int) -> int:
        """Joriy javoblar soni (autosave holati/progress uchun)."""
        return int(
            await self._db.fetchvalue(
                """
                SELECT COUNT(*) FROM responses
                WHERE attempt_id = ? AND is_current = 1
                """,
                (int(attempt_id),),
                default=0,
            )
        )


class ScoringSnapshotRepository:
    """`scoring_snapshots` + `scoring_snapshot_items` — baholash haqiqati (muzlatiladi).

    Bu — `services/scoring.py` dagi `ScoringSnapshotWriter` interfeysining
    kelajakdagi manzili: yozuvchi `save()` ni chaqiradi (snapshot + savollar
    bitta tranzaksiyada). Hozircha hech kim chaqirmaydi — oqim avvalgidek
    `user_answers` ga yoziladi.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(
        self,
        *,
        attempt_id: int,
        form_version_id: int,
        theta: float,
        theta_se: float | None,
        log_likelihood: float | None,
        raw_score: int,
        total_items: int,
        omitted_count: int,
        not_reached_count: int,
        scaled_score: float,
        scaled_min: float,
        scaled_max: float,
        theta_bound: float,
        engine_version: str,
        b_checksum: str | None = None,
        session_id: int | None = None,
        model: str = "rasch_1pl",
        is_final: bool = True,
        computed_by: str = "system",
        items: Iterable[Sequence[object]] = (),
    ) -> int:
        """Snapshot va (ixtiyoriy) savol natijalarini yozadi; `snapshot_id` qaytaradi.

        `items` satrlari ustunlar tartibida bo'lishi kerak (jami 22 ta):
            ``(form_item_id, item_id, item_version_id, display_label, position,
            testlet_ref, b_used, b_source, theta_used, guessing_c, key_used,
            key_version_no, key_source, answer_kind, raw_answer,
            normalized_answer, score_awarded, max_score, score_status,
            match_rule, capture_status, engine_version)``

        `snapshot_id`, `attempt_id`, `session_id`, `form_version_id` har bir
        satrga avtomatik qo'shiladi. Yangi yakuniy snapshot yozilganda avvalgi
        yakuniy snapshot(lar) `is_final = 0` qilinadi (regrade zanjiri).

        Qaytaradi:
            `snapshot_id`.
        """
        rows = [tuple(row) for row in items]
        conn = self._db.connection

        cursor = await conn.execute(
            """
            INSERT INTO scoring_snapshots (
                attempt_id, form_version_id, model, theta, theta_se, log_likelihood,
                raw_score, total_items, omitted_count, not_reached_count,
                scaled_score, scaled_min, scaled_max, theta_bound, engine_version,
                b_checksum, is_final, computed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(attempt_id),
                int(form_version_id),
                model,
                float(theta),
                None if theta_se is None else float(theta_se),
                None if log_likelihood is None else float(log_likelihood),
                int(raw_score),
                int(total_items),
                int(omitted_count),
                int(not_reached_count),
                float(scaled_score),
                float(scaled_min),
                float(scaled_max),
                float(theta_bound),
                engine_version,
                b_checksum,
                1 if is_final else 0,
                computed_by,
            ),
        )
        snapshot_id = int(cursor.lastrowid or 0)

        if is_final:
            await conn.execute(
                """
                UPDATE scoring_snapshots SET is_final = 0
                WHERE attempt_id = ? AND snapshot_id <> ? AND is_final = 1
                """,
                (int(attempt_id), snapshot_id),
            )

        if rows:
            await conn.executemany(
                """
                INSERT INTO scoring_snapshot_items (
                    snapshot_id, attempt_id, session_id, form_version_id,
                    form_item_id, item_id, item_version_id, display_label, position,
                    testlet_ref, b_used, b_source, theta_used, guessing_c, key_used,
                    key_version_no, key_source, answer_kind, raw_answer,
                    normalized_answer, score_awarded, max_score, score_status,
                    match_rule, capture_status, engine_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        int(attempt_id),
                        session_id,
                        int(form_version_id),
                        *row,
                    )
                    for row in rows
                ],
            )

        await conn.commit()
        logger.debug(
            "Snapshot yozildi: snapshot_id=%s, attempt_id=%s, savollar=%d",
            snapshot_id,
            attempt_id,
            len(rows),
        )
        return snapshot_id

    async def get(self, snapshot_id: int) -> dict[str, Any] | None:
        """Snapshot satri."""
        return await self._db.fetchone(
            "SELECT * FROM scoring_snapshots WHERE snapshot_id = ?", (int(snapshot_id),)
        )

    async def get_final(self, attempt_id: int) -> dict[str, Any] | None:
        """Urinishning yakuniy (eng yangi) snapshot'i."""
        return await self._db.fetchone(
            """
            SELECT * FROM scoring_snapshots
            WHERE attempt_id = ? AND is_final = 1
            ORDER BY computed_at DESC, snapshot_id DESC
            LIMIT 1
            """,
            (int(attempt_id),),
        )

    async def list_items(self, snapshot_id: int) -> list[dict[str, Any]]:
        """Snapshot'dagi savol natijalari (pozitsiya bo'yicha)."""
        return await self._db.fetchall(
            """
            SELECT * FROM scoring_snapshot_items
            WHERE snapshot_id = ?
            ORDER BY position ASC, display_label ASC
            """,
            (int(snapshot_id),),
        )

    async def count(self) -> int:
        """Jami snapshotlar soni."""
        return int(
            await self._db.fetchvalue("SELECT COUNT(*) FROM scoring_snapshots", default=0)
        )

    async def count_items(self, snapshot_id: int) -> int:
        """Snapshot'dagi savol natijalari soni."""
        return int(
            await self._db.fetchvalue(
                "SELECT COUNT(*) FROM scoring_snapshot_items WHERE snapshot_id = ?",
                (int(snapshot_id),),
                default=0,
            )
        )


class ItemParameterRepository:
    """`item_parameters` — savolning **joriy operatsion `b`** qiymati (logit).

    Bu qatlam hozircha **faqat o'qish** uchun: `b` qiymatini kalibrovka
    bosqichi yangilaydi (`source`, `status`, `valid_from`/`valid_to` tarixi
    bilan). Baholash esa o'zgarmagan — `scoring` `b` ni
    `exams.difficulty_logits` dan oladi. Shu sababli bu o'quvchi hozircha
    hech qayerdan chaqirilmaydi (keyingi bosqich uchun tayyor ulanish nuqtasi).
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def current_b(self, item_version_ids: Sequence[int]) -> dict[int, float]:
        """`{item_version_id: b_value}` — faqat **amaldagi** qatorlar.

        Amaldagi qator: `valid_to IS NULL` va `status <> 'retired'`
        (`ux_item_parameters_current` indeksi har bir item uchun bittasini
        kafolatlaydi). Noma'lum id lar javobda bo'lmaydi.
        """
        ids = sorted({int(value) for value in item_version_ids})
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        rows = await self._db.fetchall(
            f"""
            SELECT item_version_id, b_value FROM item_parameters
            WHERE valid_to IS NULL AND status <> 'retired'
              AND item_version_id IN ({placeholders})
            """,
            tuple(ids),
        )
        return {int(row["item_version_id"]): float(row["b_value"]) for row in rows}

    async def get_current_b(self, item_version_id: int) -> float | None:
        """Bitta item uchun amaldagi `b` (topilmasa — `None`)."""
        row = await self._db.fetchone(
            """
            SELECT b_value FROM item_parameters
            WHERE item_version_id = ? AND valid_to IS NULL AND status <> 'retired'
            ORDER BY valid_from DESC
            LIMIT 1
            """,
            (int(item_version_id),),
        )
        return None if row is None else float(row["b_value"])

    async def count(self) -> int:
        """Jami `b` yozuvlari (tarix bilan birga) — statistika uchun."""
        return int(
            await self._db.fetchvalue("SELECT COUNT(*) FROM item_parameters", default=0)
        )


class ItemDifficultyStatsRepository:
    """`item_difficulty_stats` — vaqtinchalik item statistikasi (`p → b`).

    `services/item_statistics.py` yozadi/o'qiydi. Manba — **yakuniy** baholash
    snapshot'lari (`scoring_snapshot_items` + `scoring_snapshots.is_final = 1`).

    * `test_id` — `exam_sessions.session_id` (bot oqimida "test" = sessiya);
    * `item_no` — `display_label`: `"1"`…`"35"`, `"36a"`…`"45b"`.

    Bu qatlam mavjud `item_statistics` (004) jadvaliga **tegmaydi**.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def aggregate(self, test_id: int) -> list[dict[str, Any]]:
        """Item bo'yicha xom hisoblagichlar (yakuniy snapshotlardan).

        Qaytaradi: `[{item_no, position, correct_count, wrong_count, blank_count}]`.
        `not_reached` satrlari sanalmaydi (hozir umuman yozilmaydi ham) — ya'ni
        N = `correct + wrong + blank` (bo'sh javoblar ham kiradi).
        """
        return await self._db.fetchall(
            """
            SELECT si.display_label AS item_no,
                   MIN(si.position)  AS position,
                   SUM(CASE WHEN si.capture_status = 'answered'
                             AND si.score_awarded >= si.max_score THEN 1 ELSE 0 END)
                       AS correct_count,
                   SUM(CASE WHEN si.capture_status = 'answered'
                             AND si.score_awarded <  si.max_score THEN 1 ELSE 0 END)
                       AS wrong_count,
                   SUM(CASE WHEN si.capture_status = 'blank' THEN 1 ELSE 0 END)
                       AS blank_count
            FROM scoring_snapshot_items si
            JOIN scoring_snapshots ss
              ON ss.snapshot_id = si.snapshot_id AND ss.is_final = 1
            WHERE si.session_id = ?
            GROUP BY si.display_label
            ORDER BY MIN(si.position) ASC, si.display_label ASC
            """,
            (int(test_id),),
        )

    async def participants_count(self, test_id: int) -> int:
        """Baholangan qatnashchilar soni (yakuniy snapshot'i bor urinishlar)."""
        return int(
            await self._db.fetchvalue(
                """
                SELECT COUNT(*) FROM scoring_snapshots ss
                JOIN attempts a ON a.attempt_id = ss.attempt_id
                WHERE a.session_id = ? AND ss.is_final = 1 AND a.deleted_at IS NULL
                """,
                (int(test_id),),
                default=0,
            )
        )

    async def replace(
        self, test_id: int, rows: Sequence[Mapping[str, Any]]
    ) -> None:
        """Shu test statistikasini o'chirib, yangisini yozadi (idempotent)."""
        conn = self._db.connection
        await conn.execute(
            "DELETE FROM item_difficulty_stats WHERE test_id = ?", (int(test_id),)
        )
        payload = [
            (
                int(test_id),
                str(row["item_no"]),
                int(row["total_participants"]),
                int(row["correct_count"]),
                int(row["wrong_count"]),
                int(row["blank_count"]),
                None
                if row.get("percent_correct") is None
                else float(row["percent_correct"]),
                None if row.get("b_value") is None else float(row["b_value"]),
            )
            for row in rows
        ]
        if payload:
            await conn.executemany(
                """
                INSERT INTO item_difficulty_stats (
                    test_id, item_no, total_participants, correct_count,
                    wrong_count, blank_count, percent_correct, b_value
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
        await conn.commit()

    async def list_for_test(self, test_id: int) -> list[dict[str, Any]]:
        """Shu test uchun saqlangan statistikalar (item tartibida: 1..35, 36a..45b)."""
        return await self._db.fetchall(
            """
            SELECT * FROM item_difficulty_stats
            WHERE test_id = ?
            ORDER BY CAST(item_no AS INTEGER) ASC, item_no ASC
            """,
            (int(test_id),),
        )

    async def used_b_values(self, test_id: int) -> dict[str, float]:
        """Har bir element uchun baholashda **ISHLATILGAN** `b` (muzlatilgan).

        Manba — `scoring_snapshot_items.b_used` (yakuniy snapshotlar,
        `is_final = 1`). `θ` aynan shu `b` bilan hisoblangan; shrinkaj yoqilganda
        bu — aralashma qiymati (`w·b_auto + (1−w)·b_teacher`). Shu sababli hisobot
        baholash natijasi bilan izchil bo'ladi.
        """
        rows = await self._db.fetchall(
            """
            SELECT si.display_label AS item_no,
                   MAX(si.b_used)    AS b_used
            FROM scoring_snapshot_items si
            JOIN scoring_snapshots ss
              ON ss.snapshot_id = si.snapshot_id AND ss.is_final = 1
            WHERE si.session_id = ? AND si.b_used IS NOT NULL
            GROUP BY si.display_label
            """,
            (int(test_id),),
        )
        return {str(row["item_no"]): float(row["b_used"]) for row in rows}

    async def sessions_needing_stats(self) -> list[int]:
        """Statistika hisoblanishi/yangilanishi kerak bo'lgan sessiyalar.

        Shart: sessiya baholangan (`graded_at` bor), lekin uning statistikasi
        baholashdan **keyin** hisoblanmagan (yoki regrade tufayli eskirgan).
        """
        rows = await self._db.fetchall(
            """
            SELECT s.session_id
            FROM exam_sessions s
            WHERE s.graded_at IS NOT NULL
              AND s.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM item_difficulty_stats d
                  WHERE d.test_id = s.session_id
                    AND d.created_at >= s.graded_at
              )
            ORDER BY s.session_id ASC
            """
        )
        return [int(row["session_id"]) for row in rows]

    async def count(self) -> int:
        """Jami saqlangan statistik satrlar (testlar bo'ylab)."""
        return int(
            await self._db.fetchvalue(
                "SELECT COUNT(*) FROM item_difficulty_stats", default=0
            )
        )


class Repositories:
    """Barcha repository'larni bitta joyda saqlovchi konteyner.

    Handler'larga `repos: Repositories` ko'rinishida uzatiladi, ya'ni
    `repos.users`, `repos.questions`, `repos.results` mavjud bo'ladi.
    Yangi imtihon platformasi uchun `repos.exams` va `repos.answers` ham bor.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.questions = QuestionRepository(db)
        self.results = ResultRepository(db)
        self.exams = ExamRepository(db)
        self.answers = ExamAnswerRepository(db)
        self.solutions = SolutionRepository(db)
        # MVP item-level qatlam (docs/11) — eski oqimga tegmaydi.
        self.forms = FormRepository(db)
        self.sessions = ExamSessionRepository(db)
        self.attempts = AttemptRepository(db)
        self.responses = ResponseRepository(db)
        self.snapshots = ScoringSnapshotRepository(db)
        # Operatsion `b` (item_parameters) — faqat o'qish uchun tayyor qatlam.
        self.item_parameters = ItemParameterRepository(db)
        # Vaqtinchalik item statistikasi (p → b) — `services/item_statistics.py`.
        self.item_difficulty = ItemDifficultyStatsRepository(db)
