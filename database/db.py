"""SQLite bilan ishlash uchun yupqa asinxron qatlam (`aiosqlite` asosida).

Butun loyihada bitta `Database` obyekti yaratilib, handler'larga
`Dispatcher(workflow_data=...)` orqali uzatiladi.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Sequence

import aiosqlite

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sxema: users / questions / test_results (eski mashq rejimi) va
#        exams / user_answers (yangi imtihon platformasi)
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,            -- Telegram user id
    full_name  TEXT    NOT NULL,
    username   TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS questions (
    question_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    question_text  TEXT    NOT NULL,
    option_a       TEXT    NOT NULL,
    option_b       TEXT    NOT NULL,
    option_c       TEXT    NOT NULL,
    option_d       TEXT    NOT NULL,
    correct_option TEXT    NOT NULL CHECK (correct_option IN ('A', 'B', 'C', 'D')),
    difficulty_b   REAL    NOT NULL,           -- Rasch qiyinchiligi (logit)
    topic          TEXT,
    is_active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS test_results (
    result_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    raw_score          INTEGER NOT NULL,       -- to'g'ri javoblar soni
    total_questions    INTEGER NOT NULL,       -- testdagi savollar soni
    theta_score        REAL    NOT NULL,       -- Rasch bo'yicha θ (logit)
    final_scaled_score REAL    NOT NULL,       -- 0..100 standart shkala
    date               TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_test_results_user ON test_results (user_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_questions_active ON questions (is_active);

-- ---------------------------------------------------------------------------
-- Yangi imtihon platformasi (o'qituvchi boshqaradigan, Telegram Web App)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS exams (
    exam_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT    NOT NULL,            -- imtihon nomi
    test_code         TEXT    NOT NULL UNIQUE,     -- o'quvchi Web App'da kiritadigan kod
    start_time        TEXT    NOT NULL,            -- javob topshirish boshlanishi (UTC ISO)
    end_time          TEXT    NOT NULL,            -- javob topshirish tugashi (UTC ISO)
    result_time       TEXT    NOT NULL,            -- natijalar e'lon qilinishi (UTC ISO)
    total_questions   INTEGER NOT NULL CHECK (total_questions > 0),
    answer_key        TEXT    NOT NULL,            -- javoblar kaliti, masalan "1A2B3C4D"
    difficulty_logits TEXT    NOT NULL,            -- JSON massiv: [b1, b2, ...] (logit)
    created_by        INTEGER,                     -- o'qituvchi (Telegram ID)
    created_at        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    graded_at         TEXT                         -- baholash tugagan vaqt (NULL — hali emas)
);

CREATE TABLE IF NOT EXISTS user_answers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    exam_id           INTEGER NOT NULL REFERENCES exams (exam_id) ON DELETE CASCADE,
    submitted_answers TEXT    NOT NULL,            -- o'quvchi javoblari, masalan "1A2B3C"
    theta             REAL,                        -- θ (logit), NULL — hali baholanmagan
    scaled_score      REAL,                        -- 0..100 standart shkala, NULL — hali emas
    raw_score         INTEGER,                     -- to'g'ri javoblar soni (baholangach)
    submitted_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (user_id, exam_id)                      -- bir o'quvchi bir imtihonga bir marta
);

CREATE INDEX IF NOT EXISTS idx_user_answers_exam ON user_answers (exam_id);
CREATE INDEX IF NOT EXISTS idx_user_answers_user ON user_answers (user_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_exams_result_time ON exams (result_time);

-- O'qituvchi yuklaydigan video/media/matn yechimlar («🔍 Test tahlili» bo'limi).
-- `solution_file_id` — Telegram file_id (video/rasm/hujjat), `solution_type` —
-- fayl turi ("video", "photo", "document", "animation", "audio", "text"),
-- `solution_text` — matnli tahlil (fayl bo'lmasa ham bo'ladi).
-- `part` — A/B qismli savollar uchun: '' (butun savol), 'a' yoki 'b'.
CREATE TABLE IF NOT EXISTS solutions (
    solution_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id          INTEGER NOT NULL REFERENCES exams (exam_id) ON DELETE CASCADE,
    question_number  INTEGER NOT NULL CHECK (question_number > 0),
    part             TEXT    NOT NULL DEFAULT ''
                     CHECK (part IN ('', 'a', 'b')),
    solution_type    TEXT    NOT NULL DEFAULT 'video'
                     CHECK (solution_type IN (
                         'video', 'photo', 'document', 'animation', 'audio', 'text'
                     )),
    solution_file_id TEXT,                          -- Telegram file_id
    solution_text    TEXT,                          -- matnli tahlil (ixtiyoriy)
    created_by       INTEGER,                       -- yuklagan o'qituvchi (Telegram ID)
    created_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (exam_id, question_number, part)         -- bir savolga bitta yechim
);

CREATE INDEX IF NOT EXISTS idx_solutions_exam ON solutions (exam_id, question_number);
"""


class Database:
    """SQLite ulanishini boshqaradi va oddiy query yordamchilarini beradi."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    # -- hayot sikli ---------------------------------------------------------
    async def connect(self) -> None:
        """Bazaga ulanadi, jadvallarni (agar yo'q bo'lsa) yaratadi."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        logger.info("Ma'lumotlar bazasi tayyor: %s", self.path)

    async def close(self) -> None:
        """Ulanishni yopadi (bot to'xtaganda chaqiriladi)."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("Ma'lumotlar bazasi ulanishi yopildi")

    @property
    def connection(self) -> aiosqlite.Connection:
        """Ochiq ulanishni qaytaradi (ochilmagan bo'lsa — xatolik)."""
        if self._conn is None:
            raise RuntimeError("Database.connect() chaqirilmagan")
        return self._conn

    # -- query yordamchilari -------------------------------------------------
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """INSERT/UPDATE/DELETE bajaradi va `lastrowid` ni qaytaradi."""
        cursor = await self.connection.execute(sql, params)
        await self.connection.commit()
        return cursor.lastrowid or 0

    async def execute_many(self, sql: str, params_seq: Iterable[Sequence[Any]]) -> None:
        """Bir xil so'rovni ko'p marta bajaradi (executemany)."""
        await self.connection.executemany(sql, params_seq)
        await self.connection.commit()

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        """Bitta satrni lug'at ko'rinishida qaytaradi (topilmasa — None)."""
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row is not None else None

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Barcha satrlarni lug'atlar ro'yxati sifatida qaytaradi."""
        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in rows]

    async def fetchvalue(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        """Bitta ustunning qiymatini qaytaradi (COUNT/AVG kabi so'rovlar uchun)."""
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return default
        value = row[0]
        return default if value is None else value

    async def execute_script(self, script: str) -> None:
        """Bir nechta SQL buyruqni bajaradi (masalan, testlar uchun)."""
        await self.connection.executescript(script)
        await self.connection.commit()