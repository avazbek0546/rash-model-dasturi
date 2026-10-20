-- ===========================================================================
-- 002_forms.sql — Formalar (docs/11 §5.5: forms, form_versions, form_items)
-- ===========================================================================
-- Maqsad : test varianti (test kodi) + kalit snapshot'i + pozitsiya -> item
--          bog'lanishini joriy qilish.
-- Nega   : kalit keyin tuzatilsa, eski urinishlar buzilmasligi kerak (audit) —
--          shuning uchun kalit `form_versions` da SNAPSHOT sifatida saqlanadi.
-- Bog'lanishlar: forms -> users(created_by)
--                form_versions -> forms, users
--                form_items -> form_versions, item_versions
-- Diqqat : `forms.current_version_id` ATAYLAB foreign key EMAS (aylanma
--          bog'lanishdan qochish uchun — 001 faylidagi items bilan bir xil).
--          `form_items.item_version_id` MVP'da TO'LDIRILISHI SHART (docs/11 §4.2),
--          lekin texnik jihatdan NULL bo'lishiga yo'l qo'yiladi (bosqichma-bosqich
--          o'tish uchun) — majburiylik keyingi bosqichda ilova darajasida.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS forms (
    form_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title              TEXT    NOT NULL,
    test_code          TEXT    NOT NULL,               -- o'quvchi kiritadigan kod
    subject_code       TEXT,
    total_questions    INTEGER NOT NULL CHECK (total_questions > 0),
    options_count      INTEGER NOT NULL DEFAULT 4 CHECK (options_count BETWEEN 2 AND 6),
    parts_json         TEXT    NOT NULL DEFAULT '[]',  -- qismli savollar: ["36a","36b"]
    current_version_id INTEGER,                        -- form_versions.form_version_id (FK emas)
    created_by         INTEGER REFERENCES users (user_id),
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    updated_at         TEXT,
    deleted_at         TEXT
);

-- Test kodi faqat bir marta (o'chirilmaganlar orasida)
CREATE UNIQUE INDEX IF NOT EXISTS ux_forms_test_code
    ON forms (test_code) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS form_versions (
    form_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    form_id         INTEGER NOT NULL REFERENCES forms (form_id) ON DELETE CASCADE,
    version_no      INTEGER NOT NULL CHECK (version_no > 0),
    answer_key      TEXT    NOT NULL,                  -- kanonik kalit ("1A2B3C4D")
    total_questions INTEGER NOT NULL CHECK (total_questions > 0),
    status          TEXT    NOT NULL DEFAULT 'published'
                            CHECK (status IN ('draft', 'published', 'retired')),
    change_reason   TEXT,                              -- nega yangi versiya (kalit tuzatildi va h.k.)
    created_by      INTEGER REFERENCES users (user_id),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    published_at    TEXT,
    UNIQUE (form_id, version_no)
);

-- Formaning barcha versiyalari (admin tarixi uchun)
CREATE INDEX IF NOT EXISTS ix_form_versions_form
    ON form_versions (form_id, version_no DESC);

CREATE TABLE IF NOT EXISTS form_items (
    form_item_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    form_version_id INTEGER NOT NULL REFERENCES form_versions (form_version_id) ON DELETE CASCADE,
    position        INTEGER NOT NULL CHECK (position > 0),   -- PDF tartibi (FAQAT taqdimot)
    display_label   TEXT    NOT NULL,                        -- "1", "36a" — inson belgisi
    part            TEXT    NOT NULL DEFAULT '' CHECK (part IN ('', 'a', 'b')),
    section_no      INTEGER,                                 -- bo'lim (guruhlash belgisi)
    -- Kalit snapshot'i shu yerda ham turadi (tez baholash uchun);
    -- numeric/text savollarda NULL bo'ladi (kalit `answer_spec` da).
    correct_option  TEXT    CHECK (correct_option IS NULL
                                   OR correct_option IN ('A','B','C','D','E','F')),
    options_count   INTEGER NOT NULL DEFAULT 4,
    item_version_id INTEGER REFERENCES item_versions (item_version_id),
    points          REAL    NOT NULL DEFAULT 1.0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    UNIQUE (form_version_id, position, part)
);

-- Pozitsiya bo'yicha tez o'qish (formani yuklash)
CREATE INDEX IF NOT EXISTS ix_form_items_version
    ON form_items (form_version_id, position);

-- Inson belgisi ("36a") bo'yicha tez topish
CREATE INDEX IF NOT EXISTS ix_form_items_label
    ON form_items (form_version_id, display_label);

-- Item statistikasidan formaga qaytish (qaysi formalarda ishlatilgan)
CREATE INDEX IF NOT EXISTS ix_form_items_item_version
    ON form_items (item_version_id);
