-- ===========================================================================
-- 001_item_bank.sql — Item Bank poydevori (docs/11 §5.5: items, item_versions)
-- ===========================================================================
-- Maqsad : global item identifikatsiyasi (matn saqlanmaydi!) va versiyalangan
--          kalit (answer_spec) ni joriy qilish.
-- Nega   : item statistikasi faqat barqaror `item_ref` + `item_version` bo'yicha
--          uzluksiz yig'iladi; pozitsiya identifikatsiya emas (audit C-1).
-- Idempotentlik: barcha buyruqlar IF NOT EXISTS bilan (qayta ishga tushirish
--          xavfsiz).
-- Bog'lanishlar: items -> users(created_by)
--                item_versions -> items, users, item_versions(superseded_by)
-- Diqqat : `items.current_version_id` ATAYLAB foreign key EMAS — `item_versions`
--          ga aylanma bog'lanish bo'lardi (SQLite'da ALTER bilan keyin ham
--          qo'shib bo'lmaydi). U oddiy ko'rsatkich (pointer) sifatida saqlanadi.
-- Vaqt    : yangi jadvallar UTC ISO-8601 (`...T...:...+00:00`) — mavjud
--          `exam_service.DB_TIME_FORMAT` bilan mos.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS items (
    item_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_ref           TEXT    NOT NULL,               -- barqaror identifikator ("NS2026-MATH-37a")
    subject_code       TEXT,                          -- fan kodi (masalan "MATH")
    program_code       TEXT,                          -- yo'nalish/daraja kodi (masalan "MATH-A")
    testlet_ref        TEXT,                          -- umumiy matn belgisi (36a/36b uchun majburiy)
    status             TEXT    NOT NULL DEFAULT 'active'
                               CHECK (status IN ('active', 'flagged', 'retired')),
    current_version_id INTEGER,                       -- item_versions.item_version_id (FK emas)
    created_by         INTEGER REFERENCES users (user_id),
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    deleted_at         TEXT                            -- soft delete (audit talabi)
);

-- Bitta item_ref faqat bir marta (o'chirilmaganlar orasida)
CREATE UNIQUE INDEX IF NOT EXISTS ux_items_ref
    ON items (item_ref) WHERE deleted_at IS NULL;

-- Fan/yo'nalish bo'yicha ro'yxat va status filtri
CREATE INDEX IF NOT EXISTS ix_items_subject
    ON items (subject_code, status);

-- Testlet (36a/36b) juftliklarini tez topish uchun
CREATE INDEX IF NOT EXISTS ix_items_testlet
    ON items (testlet_ref);

CREATE TABLE IF NOT EXISTS item_versions (
    item_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items (item_id) ON DELETE CASCADE,
    version_no      INTEGER NOT NULL CHECK (version_no > 0),
    item_type       TEXT    NOT NULL
                            CHECK (item_type IN ('mcq4', 'mcq6', 'numeric', 'text')),
    -- MCQ uchun to'g'ri variant; numeric/text uchun NULL (kalit `answer_spec` da)
    correct_option  TEXT    CHECK (correct_option IS NULL
                                   OR correct_option IN ('A','B','C','D','E','F')),
    -- Kalit + baholash qoidasi (JSON): mcq -> {"kind":"option",...}
    --                                    numeric -> {"kind":"numeric","accepted":[12],...}
    answer_spec     TEXT    NOT NULL DEFAULT '{}',
    max_score       REAL    NOT NULL DEFAULT 1.0,     -- polytomous readiness
    is_current      INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by   INTEGER REFERENCES item_versions (item_version_id),
    key_source      TEXT    NOT NULL DEFAULT 'teacher'
                            CHECK (key_source IN ('teacher', 'official', 'admin_fix', 'import')),
    created_by      INTEGER REFERENCES users (user_id),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    deleted_at      TEXT,
    UNIQUE (item_id, version_no)
);

-- Har bir item uchun faqat BITTA "joriy" versiya bo'lishi mumkin
CREATE UNIQUE INDEX IF NOT EXISTS ux_item_versions_current
    ON item_versions (item_id) WHERE is_current = 1 AND deleted_at IS NULL;

-- Item bo'yicha versiyalar tarixi (admin ko'rinishi uchun)
CREATE INDEX IF NOT EXISTS ix_item_versions_item
    ON item_versions (item_id, version_no DESC);
