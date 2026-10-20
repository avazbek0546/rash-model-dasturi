-- ===========================================================================
-- 003_delivery.sql — O'tkazish va javoblar (docs/11 §5.2, §5.3, §5.5)
--                    exam_sessions, attempts, responses
-- ===========================================================================
-- Maqsad : sessiya (vaqt oynasi), urinish (attempt) va ITEM darajasidagi
--          append-only javob logini joriy qilish.
-- Nega   : `responses` — tizimning yagona haqiqati (docs/11 §1). Javob yo'qolmasligi,
--          tarix, apellyatsiya va kelajakdagi tahlil shu jadvalga tayanadi.
-- Bog'lanishlar: exam_sessions -> forms, users
--                attempts      -> exam_sessions, users, form_versions
--                responses     -> attempts, form_items, items, item_versions
-- Diqqat : `responses` da `is_correct` / `score_awarded` YO'Q (docs/11 §5.2) —
--          baholash natijasi `scoring_snapshot_items` da muzlatiladi (004 fayl).
--          Javobsizlik `capture_status` bilan ifodalanadi (answered/blank/not_reached).
-- ===========================================================================

CREATE TABLE IF NOT EXISTS exam_sessions (
    session_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    form_id     INTEGER NOT NULL REFERENCES forms (form_id) ON DELETE RESTRICT,
    title       TEXT,
    start_time  TEXT    NOT NULL,                      -- UTC ISO (javob qabul boshlanishi)
    end_time    TEXT    NOT NULL,                      -- UTC ISO (javob qabul tugashi)
    result_time TEXT    NOT NULL,                      -- UTC ISO (natija e'loni)
    status      TEXT    NOT NULL DEFAULT 'scheduled'
                CHECK (status IN ('scheduled', 'active', 'closed',
                                  'graded', 'published', 'cancelled')),
    graded_at   TEXT,                                  -- baholash tugagan vaqt (NULL — hali emas)
    created_by  INTEGER REFERENCES users (user_id),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    updated_at  TEXT,
    deleted_at  TEXT,
    CHECK (end_time > start_time),
    CHECK (result_time >= end_time)
);

-- "Navbat" ro'yxati: vaqt oynasi bo'yicha tanlash
CREATE INDEX IF NOT EXISTS ix_exam_sessions_window
    ON exam_sessions (start_time, end_time);

-- Fon vazifasi va API: holat + tugash vaqti
CREATE INDEX IF NOT EXISTS ix_exam_sessions_status
    ON exam_sessions (status, end_time);

-- Forma bo'yicha sessiyalar (bir forma qayta ishlatilishi mumkin — docs/11 §11.2)
CREATE INDEX IF NOT EXISTS ix_exam_sessions_form
    ON exam_sessions (form_id, start_time DESC);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        INTEGER NOT NULL REFERENCES exam_sessions (session_id) ON DELETE RESTRICT,
    user_id           INTEGER NOT NULL REFERENCES users (user_id) ON DELETE RESTRICT,
    form_version_id   INTEGER NOT NULL REFERENCES form_versions (form_version_id),
    status            TEXT    NOT NULL DEFAULT 'in_progress'
                      CHECK (status IN ('in_progress', 'submitted', 'submitted_late',
                                        'graded', 'invalid')),
    submit_mode       TEXT    CHECK (submit_mode IS NULL
                                     OR submit_mode IN ('manual', 'auto_timeout', 'admin')),
    started_at        TEXT    NOT NULL,
    last_seen_at      TEXT,                            -- oxirgi autosave (online belgisi)
    submitted_at      TEXT,
    duration_seconds  INTEGER,                         -- speededness va izoh uchun
    -- `not_reached` ni ARZON aniqlash: o'quvchi eng uzoq qaysi pozitsiyaga tegdi
    last_interaction_position INTEGER,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    revision          INTEGER NOT NULL DEFAULT 0,      -- autosave paketlari hisoblagichi
    raw_score         INTEGER,                         -- rasmiy xom ball (blank = 0 siyosati)
    raw_score_strict  INTEGER,                         -- not_reached ham 0 bo'lgan variant
    n_answered        INTEGER,
    n_omitted         INTEGER,
    n_not_reached     INTEGER,
    theta             REAL,                            -- θ (logit) — baholangach
    theta_se          REAL,                            -- standart xato
    scaled_score      REAL,                            -- 0..100
    is_extreme_low    INTEGER NOT NULL DEFAULT 0 CHECK (is_extreme_low IN (0, 1)),
    is_extreme_high   INTEGER NOT NULL DEFAULT 0 CHECK (is_extreme_high IN (0, 1)),
    engine_version    TEXT,                            -- qaysi hisoblash bilan baholangan
    deleted_at        TEXT,                            -- soft delete (kalibrlashda filtr)
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    updated_at        TEXT
);

-- Bir o'quvchi + bir sessiya = bir urinish (o'chirilmaganlar orasida)
CREATE UNIQUE INDEX IF NOT EXISTS ux_attempts_session_user
    ON attempts (session_id, user_id) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_attempts_user
    ON attempts (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_attempts_session_status
    ON attempts (session_id, status);

-- ============================ Javob logi (append-only) =====================
-- Har bir o'zgarish YANGI satr (revision) — UPDATE/DELETE yo'q (docs/11 §9, I3).
-- "Joriy" holat = `is_current = 1` (partial unique index bilan kafolatlanadi).

CREATE TABLE IF NOT EXISTS responses (
    response_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id      INTEGER NOT NULL REFERENCES attempts (attempt_id) ON DELETE RESTRICT,
    item_id         INTEGER NOT NULL REFERENCES items (item_id),
    item_version_id INTEGER NOT NULL REFERENCES item_versions (item_version_id),
    form_item_id    INTEGER NOT NULL REFERENCES form_items (form_item_id),
    position        INTEGER NOT NULL,                  -- taqdimot tartibi (snapshot)
    display_label   TEXT    NOT NULL,                  -- "7", "36a"
    part            TEXT    NOT NULL DEFAULT '' CHECK (part IN ('', 'a', 'b')),
    testlet_ref     TEXT,                              -- LD uchun (arzon + qaytarilmas)
    revision        INTEGER NOT NULL CHECK (revision > 0),
    superseded_by   INTEGER REFERENCES responses (response_id),  -- keyingi revision
    is_current      INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    event_type      TEXT    NOT NULL DEFAULT 'capture'
                    CHECK (event_type IN ('capture', 'clear', 'finalize', 'admin_fix')),
    capture_status  TEXT    NOT NULL DEFAULT 'answered'
                    CHECK (capture_status IN ('answered', 'blank', 'not_reached')),
    answer_kind     TEXT    NOT NULL DEFAULT 'option'
                    CHECK (answer_kind IN ('option', 'numeric', 'text')),
    selected_option TEXT    CHECK (selected_option IS NULL
                                   OR selected_option IN ('A','B','C','D','E','F')),
    raw_answer      TEXT,                              -- o'quvchi kiritgani AYNAN (qaytarilmas)
    normalized_answer TEXT,                            -- normallashtirilgan qiymat
    numeric_value   REAL,                              -- numeric javob (tolerantlik hisobi)
    source          TEXT    NOT NULL DEFAULT 'webapp'
                    CHECK (source IN ('webapp', 'bot', 'admin', 'system')),
    client_seq      INTEGER,                           -- idempotentlik (takror paket himoyasi)
    recorded_at     TEXT    NOT NULL,                  -- SERVER vaqti (haqiqat)
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    UNIQUE (attempt_id, form_item_id, revision)
);

-- Bitta savol uchun faqat BITTA "joriy" javob
CREATE UNIQUE INDEX IF NOT EXISTS ux_responses_current
    ON responses (attempt_id, form_item_id) WHERE is_current = 1;

-- Bir xil `client_seq` ikki marta yozilmaydi (tarmoq qayta urinishi)
CREATE UNIQUE INDEX IF NOT EXISTS ux_responses_client_seq
    ON responses (attempt_id, client_seq) WHERE client_seq IS NOT NULL;

-- Holatni yuklash (state) va hisobot uchun
CREATE INDEX IF NOT EXISTS ix_responses_attempt
    ON responses (attempt_id, position);

-- Kalibrlash/statistika uchun item bo'yicha tanlash
CREATE INDEX IF NOT EXISTS ix_responses_item
    ON responses (item_version_id, created_at);

