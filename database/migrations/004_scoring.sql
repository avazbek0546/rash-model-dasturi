-- ===========================================================================
-- 004_scoring.sql — Statistika va baholash (docs/11 §5.4, §5.5, §8)
--                   item_parameters, item_statistics, scoring_snapshots,
--                   scoring_snapshot_items, result_versions
-- ===========================================================================
-- Maqsad : (a) tizim hisoblaydigan operatsion `b` va uning tarixi;
--          (b) urinish darajasida va ITEM darajasida MUZLATILGAN baholash;
--          (c) natija versiyalari (regrade eskisini o'zgartirmaydi).
-- Nega   : docs/11 §8 — Rasch uchun `b_used`, `theta_used`, `key_used`,
--          `guessing_c`, `engine_version` muzlatilishi SHART; aks holda
--          apellyatsiya, regrade va fit/DIF tahlili tiklanmaydi (audit C-4).
-- Bog'lanishlar: item_parameters -> item_versions
--                item_statistics -> item_versions, exam_sessions
--                scoring_snapshots -> attempts, form_versions, scoring_snapshots
--                scoring_snapshot_items -> scoring_snapshots, items, item_versions, form_items
--                result_versions -> attempts, scoring_snapshots
-- Diqqat : `p_hat` / `residual` / `information` ATAYLAB YO'Q — ular
--          `theta_used` va `b_used` dan formula bilan qayta hisoblanadi (docs/10 §8).
-- ===========================================================================

CREATE TABLE IF NOT EXISTS item_parameters (
    item_parameter_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_version_id   INTEGER NOT NULL REFERENCES item_versions (item_version_id),
    -- Joriy operatsion qiyinchilik (logit). Yangi item 0.0 dan boshlanadi (docs/11 §11.2)
    b_value           REAL    NOT NULL DEFAULT 0.0,
    b_se              REAL,                            -- standart xato (aniqlik)
    source            TEXT    NOT NULL DEFAULT 'default'
                      CHECK (source IN ('default', 'classical', 'guessing_corrected',
                                        'anchor', 'legacy_expert')),
    status            TEXT    NOT NULL DEFAULT 'provisional'
                      CHECK (status IN ('provisional', 'operational', 'frozen', 'retired')),
    n_used            INTEGER,                         -- hisoblashda ishlatilgan javob soni
    valid_from        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    valid_to          TEXT,                            -- NULL — hozir amalda
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

-- Item bo'yicha `b` tarixi (drift va regrade uchun)
CREATE INDEX IF NOT EXISTS ix_item_parameters_item
    ON item_parameters (item_version_id, valid_from DESC);

-- Har bir item uchun faqat BITTA amaldagi `b` (valid_to IS NULL, retired emas)
CREATE UNIQUE INDEX IF NOT EXISTS ux_item_parameters_current
    ON item_parameters (item_version_id)
    WHERE valid_to IS NULL AND status <> 'retired';

CREATE TABLE IF NOT EXISTS item_statistics (
    stat_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_version_id  INTEGER NOT NULL REFERENCES item_versions (item_version_id),
    session_id       INTEGER REFERENCES exam_sessions (session_id),   -- davr (sessiya)
    n_presented      INTEGER NOT NULL DEFAULT 0,       -- taqdim etilganlar
    n_answered       INTEGER NOT NULL DEFAULT 0,       -- javob berganlar
    n_correct        INTEGER NOT NULL DEFAULT 0,       -- to'g'ri javob berganlar
    n_omitted        INTEGER NOT NULL DEFAULT 0,       -- ko'rib, javob bermaganlar
    n_not_reached    INTEGER NOT NULL DEFAULT 0,       -- ko'rmaganlar (θ dan chiqariladi)
    p_used           REAL,                             -- hisoblashda ishlatilgan p (tekislangan)
    guessing_c       REAL,                             -- tasodif ehtimoli (mcq4: 0.25, mcq6: 0.1667, open: 0)
    b_raw            REAL,                             -- tuzatishsiz p -> b
    b_final          REAL,                             -- shrinkaj/tuzatishdan keyingi b
    b_se             REAL,                             -- standart xato
    group_mean_theta REAL,                             -- guruh o'rtacha θ (mean-mean uchun)
    prior_b          REAL,                             -- ishlatilgan prior qiymat
    shrinkage_weight REAL,                             -- shrinkaj vazni w
    method           TEXT    NOT NULL DEFAULT 'classical_logit'
                     CHECK (method IN ('classical_logit', 'guessing_corrected',
                                       'rasch_jmle', 'imported')),
    flags            TEXT    NOT NULL DEFAULT '[]',    -- JSON: ["key_suspect","too_easy",...]
    is_current       INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    computed_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    computed_by      TEXT    NOT NULL DEFAULT 'system'
                     CHECK (computed_by IN ('system', 'admin', 'import'))
);

-- Item bo'yicha hisoblash tarixi (drift monitoring)
CREATE INDEX IF NOT EXISTS ix_item_stats_item
    ON item_statistics (item_version_id, computed_at DESC);

-- Sessiya bo'yicha statistika (kalibrlash va hisobot)
CREATE INDEX IF NOT EXISTS ix_item_stats_session
    ON item_statistics (session_id, is_current);

-- ==== QISM-2 (snapshotlar va natija versiyalari) ====

CREATE TABLE IF NOT EXISTS scoring_snapshots (
    snapshot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id        INTEGER NOT NULL REFERENCES attempts (attempt_id) ON DELETE RESTRICT,
    form_version_id   INTEGER NOT NULL REFERENCES form_versions (form_version_id),
    model             TEXT    NOT NULL DEFAULT 'rasch_1pl'
                      CHECK (model IN ('raw', 'rasch_1pl')),
    theta             REAL,                            -- θ (logit)
    theta_se          REAL,                            -- SE(θ)
    log_likelihood    REAL,
    raw_score         INTEGER NOT NULL DEFAULT 0,      -- rasmiy xom ball
    total_items       INTEGER NOT NULL DEFAULT 0,
    omitted_count     INTEGER NOT NULL DEFAULT 0,
    not_reached_count INTEGER NOT NULL DEFAULT 0,
    scaled_score      REAL,                            -- 0..100
    scaled_min        REAL    NOT NULL DEFAULT 0.0,
    scaled_max        REAL    NOT NULL DEFAULT 100.0,
    theta_bound       REAL    NOT NULL DEFAULT 3.0,    -- config.THETA_BOUND snapshot'i
    engine_version    TEXT    NOT NULL DEFAULT '1.0',  -- reproducibility
    b_checksum        TEXT,                            -- ishlatilgan `b` to'plami hashi
    is_final          INTEGER NOT NULL DEFAULT 1 CHECK (is_final IN (0, 1)),
    supersedes_id     INTEGER REFERENCES scoring_snapshots (snapshot_id),
    computed_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    computed_by       TEXT    NOT NULL DEFAULT 'system'
                      CHECK (computed_by IN ('system', 'admin', 'regrade'))
);

-- Urinish bo'yicha snapshotlar tarixi (regrade zanjiri)
CREATE INDEX IF NOT EXISTS ix_snapshots_attempt
    ON scoring_snapshots (attempt_id, computed_at DESC);

-- ITEM DARAJASIDAGI baholash haqiqati (muzlatilgan — UPDATE/DELETE mumkin emas).
-- Shu jadval apellyatsiya, regrade va kelajakdagi fit/DIF tahlilining yagona dalili.
CREATE TABLE IF NOT EXISTS scoring_snapshot_items (
    snapshot_item_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id       INTEGER NOT NULL REFERENCES scoring_snapshots (snapshot_id) ON DELETE RESTRICT,
    attempt_id        INTEGER NOT NULL REFERENCES attempts (attempt_id),
    session_id        INTEGER REFERENCES exam_sessions (session_id),
    form_version_id   INTEGER NOT NULL REFERENCES form_versions (form_version_id),
    form_item_id      INTEGER NOT NULL REFERENCES form_items (form_item_id),
    item_id           INTEGER NOT NULL REFERENCES items (item_id),
    item_version_id   INTEGER NOT NULL REFERENCES item_versions (item_version_id),
    display_label     TEXT    NOT NULL,
    position          INTEGER NOT NULL,
    testlet_ref       TEXT,                            -- LD tahlili uchun
    b_used            REAL,                            -- baholashda ishlatilgan `b` (MUZLATILGAN)
    b_source          TEXT,                            -- default/classical/guessing_corrected/anchor
    theta_used        REAL,                            -- P̂ ni qayta hisoblash imkoni
    guessing_c        REAL,                            -- 1/k (mcq4: 0.25, mcq6: 0.1667, open: 0)
    key_used          TEXT,                            -- o'sha paytdagi kalit (option yoki qiymat)
    key_version_no    INTEGER,                         -- item_versions.version_no snapshot'i
    key_source        TEXT,
    answer_kind       TEXT    NOT NULL,                -- option/numeric/text (turi)
    raw_answer        TEXT,                            -- o'quvchi kiritgani (apellyatsiya dalili)
    normalized_answer TEXT,
    score_awarded     REAL,                            -- 0.0 / 1.0 (kelajakda qismiy ball)
    max_score         REAL    NOT NULL DEFAULT 1.0,
    score_status      TEXT    NOT NULL DEFAULT 'auto_scored'
                      CHECK (score_status IN ('auto_scored', 'pending_review', 'manual_scored')),
    match_rule        TEXT,                            -- exact/tolerance/normalized/manual
    capture_status    TEXT    NOT NULL,                -- not_reached ni tahlildan chiqarish
    engine_version    TEXT    NOT NULL,                -- reproducibility
    scored_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    scored_by         TEXT,                            -- kim baholadi (system/admin)
    UNIQUE (snapshot_id, form_item_id)
);

CREATE INDEX IF NOT EXISTS ix_snapshot_items_item
    ON scoring_snapshot_items (item_version_id);

CREATE TABLE IF NOT EXISTS result_versions (
    result_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id     INTEGER NOT NULL REFERENCES attempts (attempt_id) ON DELETE RESTRICT,
    version_no     INTEGER NOT NULL CHECK (version_no > 0),
    snapshot_id    INTEGER NOT NULL REFERENCES scoring_snapshots (snapshot_id),
    visible_from   TEXT    NOT NULL,                   -- natija ko'rinadigan vaqt (result_time)
    published_at   TEXT,
    published_by   INTEGER,
    channel_json   TEXT    NOT NULL DEFAULT '[]',      -- ["bot","webapp"]
    payload_json   TEXT    NOT NULL DEFAULT '{}',      -- yuborilgan xabar nusxasi
    reason         TEXT,                               -- nega yangi versiya (regrade/kalit tuzatildi)
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    UNIQUE (attempt_id, version_no)
);

-- Natijani tez olish (faqat amaldagi versiya)
CREATE INDEX IF NOT EXISTS ix_result_versions_active
    ON result_versions (attempt_id, is_active);

