-- ===========================================================================
-- 011_offline_mock.sql — Offline mock import (qog'oz natijalarini botga qo'shish)
-- ===========================================================================
-- Maqsad : bitta imtihon uchun offline (Excel) natijalarni alohida saqlash,
--          ularni mavjud Rasch hisobi bilan baholash va online natijalar bilan
--          yagona reytingga birlashtirish.
-- Nega   : `users` / `user_answers` / `attempts` Telegram foydalanuvchisiga
--          bog'langan. Offline o'quvchi botda ro'yxatdan o'tmagan bo'lishi
--          mumkin, shu sababli ularni soxta user/attempt sifatida yozib bo'lmaydi.
-- Diqqat : mavjud jadvallar O'ZGARMAYDI. Bu fayl faqat yangi jadvallar va
--          indekslarni qo'shadi.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS offline_import_batches (
    batch_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id           INTEGER NOT NULL REFERENCES exams (exam_id) ON DELETE CASCADE,
    form_version_id   INTEGER NOT NULL REFERENCES form_versions (form_version_id) ON DELETE RESTRICT,
    batch_no          INTEGER NOT NULL CHECK (batch_no > 0),
    uploaded_by       INTEGER NOT NULL,
    file_name         TEXT    NOT NULL,
    file_sha256       TEXT    NOT NULL,
    file_size         INTEGER NOT NULL DEFAULT 0,
    status            TEXT    NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft', 'validated', 'committed', 'void')),
    rows_total        INTEGER NOT NULL DEFAULT 0,
    rows_valid        INTEGER NOT NULL DEFAULT 0,
    rows_invalid      INTEGER NOT NULL DEFAULT 0,
    template_version  TEXT    NOT NULL DEFAULT '1',
    key_fingerprint   TEXT    NOT NULL,
    b_checksum        TEXT    NOT NULL,
    b_source          TEXT    NOT NULL DEFAULT 'default',
    engine_version    TEXT    NOT NULL DEFAULT '1.0',
    offline_test_date TEXT,
    note              TEXT,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    validated_at      TEXT,
    committed_at      TEXT,
    voided_at         TEXT,
    voided_by         INTEGER,
    void_reason       TEXT,
    UNIQUE (exam_id, batch_no)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_offline_batches_file
    ON offline_import_batches (exam_id, file_sha256)
    WHERE status IN ('draft', 'validated', 'committed');

CREATE INDEX IF NOT EXISTS ix_offline_batches_exam
    ON offline_import_batches (exam_id, created_at DESC);

CREATE TABLE IF NOT EXISTS offline_import_rows (
    row_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id          INTEGER NOT NULL REFERENCES offline_import_batches (batch_id) ON DELETE CASCADE,
    row_no            INTEGER NOT NULL,
    student_code      TEXT    NOT NULL,
    student_code_norm TEXT    NOT NULL,
    full_name         TEXT    NOT NULL,
    full_name_norm    TEXT    NOT NULL,
    class_label       TEXT    NOT NULL DEFAULT '',
    telegram_username TEXT,
    answers_json      TEXT    NOT NULL,
    row_status        TEXT    NOT NULL DEFAULT 'valid'
                      CHECK (row_status IN ('valid', 'warning', 'error')),
    error_code        TEXT,
    error_message     TEXT,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    UNIQUE (batch_id, row_no)
);

CREATE INDEX IF NOT EXISTS ix_offline_rows_batch
    ON offline_import_rows (batch_id, row_no);

CREATE INDEX IF NOT EXISTS ix_offline_rows_code
    ON offline_import_rows (batch_id, student_code_norm);

CREATE TABLE IF NOT EXISTS offline_import_issues (
    issue_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      INTEGER NOT NULL REFERENCES offline_import_batches (batch_id) ON DELETE CASCADE,
    row_no        INTEGER,
    column_name   TEXT,
    code          TEXT    NOT NULL,
    message       TEXT    NOT NULL,
    severity      TEXT    NOT NULL DEFAULT 'error'
                  CHECK (severity IN ('warning', 'error')),
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

CREATE INDEX IF NOT EXISTS ix_offline_issues_batch
    ON offline_import_issues (batch_id, severity, row_no);

CREATE TABLE IF NOT EXISTS offline_participants (
    participant_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id           INTEGER NOT NULL REFERENCES exams (exam_id) ON DELETE CASCADE,
    student_code      TEXT    NOT NULL,
    student_code_norm TEXT    NOT NULL,
    full_name         TEXT    NOT NULL,
    full_name_norm    TEXT    NOT NULL,
    class_label       TEXT    NOT NULL DEFAULT '',
    telegram_username TEXT,
    matched_user_id   INTEGER REFERENCES users (user_id) ON DELETE SET NULL,
    match_status      TEXT    NOT NULL DEFAULT 'unmatched'
                      CHECK (match_status IN ('unmatched', 'suggested', 'confirmed', 'conflict', 'rejected')),
    match_method      TEXT,
    match_confidence  REAL,
    confirmed_by      INTEGER,
    confirmed_at      TEXT,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    updated_at        TEXT,
    UNIQUE (exam_id, student_code_norm)
);

CREATE INDEX IF NOT EXISTS ix_offline_participants_exam
    ON offline_participants (exam_id, match_status);

CREATE INDEX IF NOT EXISTS ix_offline_participants_user
    ON offline_participants (exam_id, matched_user_id);

CREATE TABLE IF NOT EXISTS offline_participant_links (
    link_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id INTEGER NOT NULL REFERENCES offline_participants (participant_id) ON DELETE CASCADE,
    user_id        INTEGER NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'confirmed'
                   CHECK (status IN ('proposed', 'confirmed', 'rejected', 'revoked')),
    method         TEXT    NOT NULL DEFAULT 'manual',
    confidence     REAL,
    proposed_by    INTEGER,
    confirmed_by   INTEGER,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    confirmed_at   TEXT,
    revoked_at     TEXT,
    note           TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_offline_link_active
    ON offline_participant_links (participant_id)
    WHERE status = 'confirmed' AND revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_offline_link_user
    ON offline_participant_links (user_id, status);

CREATE TABLE IF NOT EXISTS offline_attempts (
    offline_attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id           INTEGER NOT NULL REFERENCES offline_import_batches (batch_id) ON DELETE CASCADE,
    participant_id     INTEGER NOT NULL REFERENCES offline_participants (participant_id) ON DELETE CASCADE,
    exam_id            INTEGER NOT NULL REFERENCES exams (exam_id) ON DELETE CASCADE,
    form_version_id    INTEGER NOT NULL REFERENCES form_versions (form_version_id) ON DELETE RESTRICT,
    raw_score          INTEGER NOT NULL DEFAULT 0,
    total_items        INTEGER NOT NULL DEFAULT 0,
    theta              REAL    NOT NULL,
    theta_se           REAL,
    scaled_score       REAL    NOT NULL,
    level              TEXT    NOT NULL,
    is_extreme         INTEGER NOT NULL DEFAULT 0 CHECK (is_extreme IN (0, 1)),
    included_in_ranking INTEGER NOT NULL DEFAULT 1 CHECK (included_in_ranking IN (0, 1)),
    exclusion_reason   TEXT,
    status             TEXT    NOT NULL DEFAULT 'valid'
                       CHECK (status IN ('valid', 'void')),
    engine_version     TEXT    NOT NULL,
    b_checksum         TEXT    NOT NULL,
    b_source           TEXT    NOT NULL DEFAULT 'default',
    key_fingerprint    TEXT    NOT NULL,
    computed_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    computed_by        TEXT    NOT NULL DEFAULT 'system'
                       CHECK (computed_by IN ('system', 'admin')),
    UNIQUE (batch_id, participant_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_offline_attempt_valid
    ON offline_attempts (exam_id, participant_id)
    WHERE status = 'valid';

CREATE INDEX IF NOT EXISTS ix_offline_attempts_exam
    ON offline_attempts (exam_id, status);

CREATE INDEX IF NOT EXISTS ix_offline_attempts_batch
    ON offline_attempts (batch_id, status);

CREATE TABLE IF NOT EXISTS offline_responses (
    response_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    offline_attempt_id INTEGER NOT NULL REFERENCES offline_attempts (offline_attempt_id) ON DELETE CASCADE,
    form_item_id       INTEGER NOT NULL REFERENCES form_items (form_item_id) ON DELETE RESTRICT,
    item_version_id    INTEGER NOT NULL REFERENCES item_versions (item_version_id) ON DELETE RESTRICT,
    position           INTEGER NOT NULL,
    display_label      TEXT    NOT NULL,
    is_correct         INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
    b_used             REAL    NOT NULL,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    UNIQUE (offline_attempt_id, form_item_id)
);

CREATE INDEX IF NOT EXISTS ix_offline_responses_attempt
    ON offline_responses (offline_attempt_id, position);

CREATE INDEX IF NOT EXISTS ix_offline_responses_item
    ON offline_responses (item_version_id);

CREATE TABLE IF NOT EXISTS exam_ranking_decisions (
    decision_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id             INTEGER NOT NULL REFERENCES exams (exam_id) ON DELETE CASCADE,
    subject_type        TEXT    NOT NULL
                        CHECK (subject_type IN ('offline_participant', 'telegram_user')),
    subject_id          INTEGER NOT NULL,
    source              TEXT    NOT NULL CHECK (source IN ('offline', 'online')),
    included_in_ranking INTEGER NOT NULL CHECK (included_in_ranking IN (0, 1)),
    reason              TEXT    NOT NULL,
    decided_by          INTEGER,
    decided_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ranking_decision_active
    ON exam_ranking_decisions (exam_id, subject_type, subject_id)
    WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS ix_ranking_decisions_exam
    ON exam_ranking_decisions (exam_id, is_active, source);
