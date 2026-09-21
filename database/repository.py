"""Repository qatlami — jadvallar bilan barcha CRUD amallari shu yerda.

Handler'lar SQL yozmaydi, faqat repository metodlarini chaqiradi.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Sequence

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
        solution_text=row["solution_text"],
        created_by=row["created_by"],
        updated_at=row["updated_at"],
    )


class SolutionRepository:
    """`solutions` jadvali — savollarning video/rasm/matn yechimlari.

    Har bir yozuv «imtihon + savol raqami (+ A/B qismi)» juftligiga bog'lanadi.
    O'qituvchi bir savolga yechimni qayta yuklasa — mavjud yozuv yangilanadi
    (`upsert`), ya'ni dublikat yaratilmaydi.
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
        solution_text: str | None = None,
        created_by: int | None = None,
    ) -> int:
        """Yechimni saqlaydi (mavjud bo'lsa — yangilaydi) va `solution_id` qaytaradi."""
        part = normalize_part(part)
        await self._db.execute(
            """
            INSERT INTO solutions (
                exam_id, question_number, part, solution_type,
                solution_file_id, solution_text, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (exam_id, question_number, part) DO UPDATE SET
                solution_type    = excluded.solution_type,
                solution_file_id = excluded.solution_file_id,
                solution_text    = excluded.solution_text,
                created_by       = excluded.created_by,
                updated_at       = datetime('now', 'localtime')
            """,
            (
                int(exam_id),
                int(question_number),
                part,
                str(solution_type),
                solution_file_id,
                solution_text,
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
        """Jami yuklangan yechimlar soni (statistika uchun)."""
        return int(await self._db.fetchvalue("SELECT COUNT(*) FROM solutions", default=0))

    async def delete(self, exam_id: int, question_number: int, part: str = PART_WHOLE) -> None:
        """Bitta savol (yoki qism) yechimini o'chiradi."""
        await self._db.execute(
            """
            DELETE FROM solutions
            WHERE exam_id = ? AND question_number = ? AND part = ?
            """,
            (int(exam_id), int(question_number), normalize_part(part)),
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
