# 02 — To'liq Database Schema (SQLite MVP + PostgreSQL)

> ⚠️ **MVP tarkibi bo'yicha ustun hujjat: [`docs/11-FINAL-MVP-DATABASE-MODEL.md`](11-FINAL-MVP-DATABASE-MODEL.md).**
> Bu hujjatdagi **§2 katalog (34 jadval)**, **§7 «MVP uchun minimal jadvallar»**
> va **§4 (MVP-1/MVP-2)** bo'limlari `docs/10` audit qarorlariga ko'ra
> **`docs/11` bilan almashtirilgan**: 16 jadval MVP'da qoladi, 8 → PHASE-2,
> 3 → FUTURE, 8 + 1 view → **REMOVE**. Sxema (DDL) shakli va PostgreSQL
> bo'limlari (§5, §6) **o'z kuchida qoladi** — faqat **jadval tarkibi**
> `docs/11` ga qarab o'qiladi. O'zgarishlar ro'yxati: `docs/11` §10.1.

## 1. Umumiy tamoyillar

| Tamoyil | Qoida |
|---|---|
| Nomi | jadval — `snake_case`, ko'plik (`form_items`); PK — `<birlik>_id` (`form_item_id`) |
| PK turi | SQLite: `INTEGER PRIMARY KEY AUTOINCREMENT`; PostgreSQL: `bigint GENERATED ALWAYS AS IDENTITY` |
| Vaqt | Bazada **UTC ISO-8601**: `2026-03-01T05:00:00+00:00` (`services/exam_service.DB_TIME_FORMAT`). PG'da `timestamptz` |
| Vaqtni kim to'ldiradi | Ilova (`exam_service.now_db()`); SQLite'da `DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))` zaxira |
| Soft delete | Barcha o'zgaruvchan jadvallarda `deleted_at TEXT NULL`; o'chirish = `deleted_at` yozish |
| Append-only | `responses`, `attempt_events`, `audit_log`, `item_statistics`, `scoring_snapshots` — faqat INSERT |
| Immutable | `item_versions`, `form_versions`, `result_versions`, `calibration_runs` — yozilgach o'zgartirilmaydi |
| Enum | `TEXT` + `CHECK (col IN (...))` (SQLite va PG'da bir xil ishlaydi) |
| FK | `ON DELETE RESTRICT` (asosiy) / `ON DELETE CASCADE` (faqat "bola" jadvallar: `form_items`, `responses`) |
| JSON | SQLite: `TEXT` (JSON satri); PG: `jsonb` |
| Kalit | `answer_key` va `b` hech qachon API'ga chiqmaydi (faqat server ichida o'qiladi) |

## 2. Jadval katalogi (34 jadval + 1 view)

### A. Identity va huquqlar
| Jadval | Vazifasi |
|---|---|
| `users` | O'quvchilar va xodimlar (mavjud jadval kengaytiriladi) |
| `staff_roles` | Rol berish tarixi (`student`, `teacher`, `admin`, `analyst`) |

### B. Question Bank
| Jadval | Vazifasi |
|---|---|
| `subjects` | Fanlar (Matematika, Ona tili, Fizika…) |
| `exam_programs` | Milliy sertifikat yo'nalishlari (fan + daraja) |
| `topics` | Mavzular daraxti |
| `tags` | Teglar (manba, ko'nikma, daraja) |
| `items` | **Item** — savolning bazadagi "obyekti" (matnsiz!) |
| `item_versions` | **Item Version** — kalit, variantlar soni, qism (immutable) |
| `item_tags` | Item ↔ teg |
| `item_status_history` | **Item Status** tarixi (`draft → active → retired → flagged`) |
| `answer_key_imports` | Kalit kiritish/yuklash tarixi (audit + qayta tahlil) |

### C. Struktura va formalar
| Jadval | Vazifasi |
|---|---|
| `exam_structures` | **Exam Structure** — test shabloni (bo'limlar, savollar soni, vaqt) |
| `exam_structure_sections` | Shablon bo'limlari |
| `forms` | **Form** — test varianti; **test kodi shu yerda** |
| `form_versions` | **Form** ning snapshot'i: kalit + savollar tartibi (immutable) |
| `form_items` | Formadagi pozitsiya → `item_version` bog'lanishi |

### D. O'tkazish (delivery) va javoblar
| Jadval | Vazifasi |
|---|---|
| `exam_sessions` | **Session** — vaqt oynasi (start/end/result) |
| `attempts` | **Attempt** — o'quvchining bitta urinishi |
| `attempt_attributes` | Urinish konteksti (hudud, til, qurilma) — kelajakda DIF uchun |
| `attempt_events` | Urinish hodisalari (immutable timeline) |
| `responses` | **Item-level response** — har bir savolga javob (append-only!) |

### E. Statistika va kalibrlash
| Jadval | Vazifasi |
|---|---|
| `item_parameter_sets` | `b` qiymatlari to'plami (snapshot scoring "kaliti") |
| `item_parameters` | **Item** ning operatsion `b` qiymati (versiyalangan) |
| `item_statistics` | **Item Statistics** — `n`, `p`, `b`, `SE`, flag, davr |
| `scoring_snapshots` | Hisoblash natijasi (θ, SE, raw, scaled) — qayta ishlab chiqarish uchun |
| `result_versions` | **Result versioning** — e'lon qilingan natija versiyalari |
| `calibration_runs` | **Calibration run** — kalibrlash tarixi |
| `calibration_run_items` | Run ichidagi har bir item natijasi |
| `anchor_items` | **Anchor items** — qotirilgan `b` (equating uchun) |
| `equatings` | **Equating** — ikki parametrlar to'plami orasidagi o'girish |

### F. Audit va operatsiya
| Jadval | Vazifasi |
|---|---|
| `audit_log` | **Audit log** — barcha muhim amallar (before/after) |
| `notification_outbox` | Yuborilishi kerak bo'lgan xabarlar navbati |
| `app_settings` | Tizim sozlamalari (kalibrlash chegaralari va h.k.) |
| `schema_migrations` | Migratsiya versiyalari |

## 3. MVP-0 — eng minimal sxema (11 jadval)

Bu bosqich **bugunoq ishlaydi** va audit talablarining asosiy qismini qondiradi
(soft delete, append-only javoblar, audit log, item statistikasi). Bu yerda
Question Bank hali "yengil": `form_items` ning o'zi kalitni saqlaydi, `b` esa
`form_item_id` bo'yicha yoziladi. MVP-1 ga o'tishda hech narsa yo'qolmaydi
(5-bo'limga qarang).

```sql
-- ======================= MVP-0 (SQLite) =======================
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,                     -- Telegram user id
    full_name   TEXT    NOT NULL,
    username    TEXT,
    role        TEXT    NOT NULL DEFAULT 'student'
                        CHECK (role IN ('student','teacher','admin','analyst')),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    updated_at  TEXT,
    deleted_at  TEXT
);

CREATE TABLE IF NOT EXISTS forms (
    form_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    test_code       TEXT    NOT NULL,                    -- o'quvchi kiritadigan kod
    program_code    TEXT,                                -- "MATH-A", "UZ-B" ...
    total_questions INTEGER NOT NULL CHECK (total_questions > 0),
    options_count   INTEGER NOT NULL DEFAULT 4 CHECK (options_count BETWEEN 2 AND 6),
    parts_json      TEXT    NOT NULL DEFAULT '[]',       -- ["36a","36b"] qismli savollar
    current_version_id INTEGER,                          -- form_versions.form_version_id
    created_by      INTEGER REFERENCES users (user_id),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    updated_at      TEXT,
    deleted_at      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_forms_test_code
    ON forms (test_code) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS form_versions (
    form_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    form_id         INTEGER NOT NULL REFERENCES forms (form_id) ON DELETE CASCADE,
    version_no      INTEGER NOT NULL CHECK (version_no > 0),
    answer_key      TEXT    NOT NULL,                    -- "1A2B3C4D" (SNAPSHOT!)
    total_questions INTEGER NOT NULL CHECK (total_questions > 0),
    change_reason   TEXT,
    status          TEXT    NOT NULL DEFAULT 'published'
                            CHECK (status IN ('draft','published','retired')),
    created_by      INTEGER REFERENCES users (user_id),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    published_at    TEXT,
    UNIQUE (form_id, version_no)
);

CREATE TABLE IF NOT EXISTS form_items (
    form_item_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    form_version_id INTEGER NOT NULL REFERENCES form_versions (form_version_id) ON DELETE CASCADE,
    position        INTEGER NOT NULL CHECK (position > 0),   -- savol raqami (1..N)
    part            TEXT    NOT NULL DEFAULT '' CHECK (part IN ('','a','b')),
    correct_option  TEXT    NOT NULL CHECK (correct_option IN ('A','B','C','D')),
    options_count   INTEGER NOT NULL DEFAULT 4,
    section_no      INTEGER,
    points          REAL    NOT NULL DEFAULT 1.0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    UNIQUE (form_version_id, position, part)
);
CREATE INDEX IF NOT EXISTS ix_form_items_version ON form_items (form_version_id, position);

CREATE TABLE IF NOT EXISTS exam_sessions (
    session_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    form_id         INTEGER NOT NULL REFERENCES forms (form_id) ON DELETE RESTRICT,
    title           TEXT,
    start_time      TEXT    NOT NULL,                    -- UTC ISO
    end_time        TEXT    NOT NULL,
    result_time     TEXT    NOT NULL,
    timezone        TEXT    NOT NULL DEFAULT 'Asia/Tashkent',
    status          TEXT    NOT NULL DEFAULT 'scheduled'
                            CHECK (status IN ('scheduled','active','closed',
                                              'graded','published','cancelled')),
    graded_at       TEXT,
    created_by      INTEGER REFERENCES users (user_id),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    updated_at      TEXT,
    deleted_at      TEXT,
    CHECK (end_time > start_time),
    CHECK (result_time >= end_time)
);
CREATE INDEX IF NOT EXISTS ix_sessions_window ON exam_sessions (start_time, end_time);
CREATE INDEX IF NOT EXISTS ix_sessions_status ON exam_sessions (status, end_time);
```

```sql
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        INTEGER NOT NULL REFERENCES exam_sessions (session_id) ON DELETE RESTRICT,
    user_id           INTEGER NOT NULL REFERENCES users (user_id) ON DELETE RESTRICT,
    form_version_id   INTEGER NOT NULL REFERENCES form_versions (form_version_id),
    parameter_set_id  INTEGER,                        -- snapshot: qaysi b to'plami
    status            TEXT    NOT NULL DEFAULT 'in_progress'
                              CHECK (status IN ('in_progress','submitted','submitted_late',
                                                'graded','expired','invalid','cancelled')),
    started_at        TEXT    NOT NULL,
    last_seen_at      TEXT,
    submitted_at      TEXT,
    revision          INTEGER NOT NULL DEFAULT 0,     -- javoblar revision'i (optimistik qulf)
    device_json       TEXT,
    ip_hash           TEXT,                           -- to'liq IP saqlanmaydi (maxfiylik)
    raw_score         INTEGER,
    omitted_count     INTEGER,
    theta             REAL,
    theta_se          REAL,
    scaled_score      REAL,
    graded_at         TEXT,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    updated_at        TEXT,
    deleted_at        TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_attempts_session_user
    ON attempts (session_id, user_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_attempts_session_status ON attempts (session_id, status);
CREATE INDEX IF NOT EXISTS ix_attempts_user ON attempts (user_id, created_at DESC);

-- ============ Item-level javoblar: APPEND-ONLY (immutable history) ============
CREATE TABLE IF NOT EXISTS responses (
    response_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id      INTEGER NOT NULL REFERENCES attempts (attempt_id) ON DELETE RESTRICT,
    form_item_id    INTEGER NOT NULL REFERENCES form_items (form_item_id) ON DELETE RESTRICT,
    item_version_id INTEGER,                          -- MVP-1 da to'ldiriladi
    position        INTEGER NOT NULL,                 -- denormalizatsiya (tez hisoblash)
    part            TEXT    NOT NULL DEFAULT '',
    given_option    TEXT    CHECK (given_option IS NULL OR given_option IN ('A','B','C','D')),
    response_state  TEXT    NOT NULL DEFAULT 'answered'
                            CHECK (response_state IN ('answered','omitted','cleared')),
    is_correct      INTEGER CHECK (is_correct IS NULL OR is_correct IN (0,1)),
    revision        INTEGER NOT NULL CHECK (revision > 0),
    client_seq      INTEGER,                          -- qurilma tomonidan berilgan ketma-ketlik
    source          TEXT    NOT NULL DEFAULT 'webapp'
                            CHECK (source IN ('webapp','bot','import','admin','system')),
    is_current      INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    superseded_by   INTEGER REFERENCES responses (response_id),   -- keyingi revision
    answered_at     TEXT    NOT NULL,                 -- qurilma vaqti (client)
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    ip_hash         TEXT,
    UNIQUE (attempt_id, form_item_id, revision)
);
-- Bitta savol uchun faqat BITTA "joriy" javob bo'lishi mumkin (partial unique index)
CREATE UNIQUE INDEX IF NOT EXISTS ux_responses_current
    ON responses (attempt_id, form_item_id) WHERE is_current = 1;
-- Idempotentlik: bir xil client_seq ikki marta kelmaydi
CREATE UNIQUE INDEX IF NOT EXISTS ux_responses_client_seq
    ON responses (attempt_id, client_seq) WHERE client_seq IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_responses_attempt ON responses (attempt_id, position);
CREATE INDEX IF NOT EXISTS ix_responses_item ON responses (form_item_id, is_current);
```

**Joriy javoblarni tez o'qish uchun view:**

```sql
CREATE VIEW IF NOT EXISTS attempt_response_current AS
SELECT r.attempt_id,
       r.form_item_id,
       r.position,
       r.part,
       r.given_option,
       r.response_state,
       r.is_correct,
       r.revision,
       r.answered_at
FROM responses r
WHERE r.is_current = 1;
```

```sql
-- ===== Operatsion b (MVP-0: form_item bo'yicha; MVP-1: item_version bo'yicha) =====
CREATE TABLE IF NOT EXISTS item_parameters (
    item_parameter_id INTEGER PRIMARY KEY AUTOINCREMENT,
    form_item_id      INTEGER REFERENCES form_items (form_item_id),
    item_version_id   INTEGER,                        -- MVP-1 da to'ldiriladi
    parameter_set_id  INTEGER,                        -- MVP-1: item_parameter_sets
    b_value           REAL    NOT NULL DEFAULT 0.0,   -- logit (TIZIM hisoblaydi!)
    b_se              REAL,
    source            TEXT    NOT NULL DEFAULT 'default'
                              CHECK (source IN ('default','classical','guessing_corrected',
                                                'rasch','anchor','legacy_expert')),
    status            TEXT    NOT NULL DEFAULT 'provisional'
                              CHECK (status IN ('provisional','operational','frozen','retired')),
    is_anchor         INTEGER NOT NULL DEFAULT 0 CHECK (is_anchor IN (0,1)),
    anchor_b          REAL,
    calibration_run_id INTEGER,
    n_used            INTEGER,                        -- hisoblashda ishlatilgan javoblar soni
    valid_from        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    valid_to          TEXT,                           -- NULL = hozir amalda
    created_by        INTEGER,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    CHECK (form_item_id IS NOT NULL OR item_version_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_item_parameters_item
    ON item_parameters (form_item_id, valid_from DESC);
CREATE INDEX IF NOT EXISTS ix_item_parameters_current
    ON item_parameters (valid_to, item_version_id, form_item_id);

-- ===== Item Statistics: har bir hisoblash tarixi (append-only) =====
CREATE TABLE IF NOT EXISTS item_statistics (
    stat_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    form_item_id     INTEGER REFERENCES form_items (form_item_id),
    item_version_id  INTEGER,                         -- MVP-1 da to'ldiriladi
    scope            TEXT    NOT NULL DEFAULT 'session'
                             CHECK (scope IN ('session','form','program','global')),
    session_id       INTEGER REFERENCES exam_sessions (session_id),
    window_start     TEXT,
    window_end       TEXT,
    n_presented      INTEGER NOT NULL DEFAULT 0,      -- savol taqdim etilgan urinishlar
    n_answered       INTEGER NOT NULL DEFAULT 0,      -- javob belgilangan (X emas)
    n_correct        INTEGER NOT NULL DEFAULT 0,      -- to'g'ri javoblar
    n_omitted        INTEGER NOT NULL DEFAULT 0,      -- javobsiz qoldirilgan
    p_raw            REAL,                            -- c / n_answered
    p_used           REAL,                            -- hisoblashda ishlatilgan p (tekislangan)
    guessing_c       REAL,                            -- taxmin ehtimoli (1/k)
    b_raw            REAL,                            -- ln((1-p)/p)
    b_adjusted       REAL,                            -- guruhga moslangan (mean-mean)
    b_final          REAL,                            -- shrinkajdan keyingi yakuniy b
    b_se             REAL,                            -- standart xato
    group_mean_theta REAL,                            -- guruhning o'rtacha θ si
    prior_b          REAL,                            -- ishlatilgan prior (old b yoki 0)
    shrinkage_weight REAL,                            -- w = n/(n+K)
    method           TEXT    NOT NULL DEFAULT 'classical_logit'
                             CHECK (method IN ('classical_logit','guessing_corrected',
                                               'rasch_jmle','anchor_linking','imported')),
    flags            TEXT    NOT NULL DEFAULT '[]',   -- JSON: ["insufficient_n","key_suspect"]
    calibration_run_id INTEGER,
    is_current       INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    computed_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    computed_by      TEXT    NOT NULL DEFAULT 'system'
                             CHECK (computed_by IN ('system','admin','import'))
);
CREATE INDEX IF NOT EXISTS ix_item_stats_item ON item_statistics (form_item_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS ix_item_stats_session ON item_statistics (session_id, is_current);
```

```sql
-- ===== Snapshot scoring: hisoblash natijasi (qayta ishlab chiqarish uchun) =====
CREATE TABLE IF NOT EXISTS scoring_snapshots (
    snapshot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id        INTEGER NOT NULL REFERENCES attempts (attempt_id) ON DELETE CASCADE,
    form_version_id   INTEGER NOT NULL REFERENCES form_versions (form_version_id),
    parameter_set_id  INTEGER,
    model             TEXT    NOT NULL DEFAULT 'rasch_1pl'
                              CHECK (model IN ('raw','classical_logit','rasch_1pl','rasch_2pl')),
    theta             REAL,
    theta_se          REAL,
    log_likelihood    REAL,
    raw_score         INTEGER NOT NULL DEFAULT 0,
    total_items       INTEGER NOT NULL DEFAULT 0,
    omitted_count     INTEGER NOT NULL DEFAULT 0,
    scaled_score      REAL,
    scaled_min        REAL    NOT NULL DEFAULT 0.0,
    scaled_max        REAL    NOT NULL DEFAULT 100.0,
    theta_bound       REAL    NOT NULL DEFAULT 3.0,
    engine_version    TEXT    NOT NULL DEFAULT '1.0',
    b_checksum        TEXT,                            -- ishlatilgan b lar hashi (reproducibility)
    is_final          INTEGER NOT NULL DEFAULT 1 CHECK (is_final IN (0,1)),
    supersedes_id     INTEGER REFERENCES scoring_snapshots (snapshot_id),
    computed_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    computed_by       TEXT    NOT NULL DEFAULT 'system'
                              CHECK (computed_by IN ('system','admin','regrade'))
);
CREATE INDEX IF NOT EXISTS ix_snapshots_attempt ON scoring_snapshots (attempt_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS ix_snapshots_params ON scoring_snapshots (parameter_set_id);

-- ===== Audit log: har bir muhim amal (append-only) =====
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id  INTEGER,                            -- Telegram id (bo'lsa)
    actor_role     TEXT,
    action         TEXT    NOT NULL,                   -- 'form.create','key.update','item.freeze'...
    entity_type    TEXT    NOT NULL,                   -- 'form','item_version','attempt','b'...
    entity_id      TEXT,
    before_json    TEXT,
    after_json     TEXT,
    request_id     TEXT,
    source         TEXT    NOT NULL DEFAULT 'bot'
                           CHECK (source IN ('bot','webapp','admin_api','migration','system')),
    ip_hash        TEXT,
    note           TEXT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_log (entity_type, entity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_actor ON audit_log (actor_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_created ON audit_log (created_at DESC);
```

> **MVP-0 da ataylab yo'q:** Question Bank (`items`, `item_versions`),
> parametrlar to'plami, `result_versions`, `calibration_runs`, `anchor_items`,
> `equatings`, `notification_outbox`. Bularning barchasi **MVP-1** da qo'shiladi
> va MVP-0 ma'lumotlari to'liq ko'chiriladi (05-hujjat).

## 4. MVP-1 — to'liq sxema (Question Bank + kalibrlash)

```sql
-- ============ Fan / yo'nalish / mavzu / teglar ============
CREATE TABLE IF NOT EXISTS subjects (
    subject_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,               -- 'MATH','UZ','PHYS'
    title       TEXT    NOT NULL,                      -- 'Matematika'
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS exam_programs (
    program_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id  INTEGER NOT NULL REFERENCES subjects (subject_id),
    code        TEXT    NOT NULL UNIQUE,               -- 'MATH-A'
    title       TEXT    NOT NULL,                      -- 'Matematika (A-daraja)'
    level       TEXT,                                  -- 'A','B','C'
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);

CREATE TABLE IF NOT EXISTS topics (
    topic_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id      INTEGER NOT NULL REFERENCES subjects (subject_id),
    parent_topic_id INTEGER REFERENCES topics (topic_id),
    code            TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    UNIQUE (subject_id, code)
);

CREATE TABLE IF NOT EXISTS tags (
    tag_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_group  TEXT    NOT NULL DEFAULT 'general'
                       CHECK (tag_group IN ('general','source','skill','level','topic')),
    code       TEXT    NOT NULL UNIQUE,
    title      TEXT    NOT NULL
);

-- ============ QUESTION BANK: Item va Item Version ============
CREATE TABLE IF NOT EXISTS items (
    item_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id     INTEGER NOT NULL REFERENCES exam_programs (program_id),
    topic_id       INTEGER REFERENCES topics (topic_id),
    item_ref       TEXT    NOT NULL,                   -- 'NS2026-MATH-37' (manbadagi belgi)
    content_hash   TEXT,                               -- savol matni SHA-256 (matn saqlanmaydi!)
    media_ref      TEXT,                               -- PDF/manba havolasi yoki Telegram file_id
    options_count  INTEGER NOT NULL DEFAULT 4 CHECK (options_count BETWEEN 2 AND 6),
    part           TEXT    NOT NULL DEFAULT '' CHECK (part IN ('','a','b')),
    status         TEXT    NOT NULL DEFAULT 'active'
                           CHECK (status IN ('draft','active','flagged','retired')),
    current_version_id INTEGER,
    created_by     INTEGER REFERENCES users (user_id),
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    updated_at     TEXT,
    deleted_at     TEXT,
    UNIQUE (program_id, item_ref, part)
);
CREATE INDEX IF NOT EXISTS ix_items_program ON items (program_id, status);
CREATE INDEX IF NOT EXISTS ix_items_hash ON items (content_hash);

CREATE TABLE IF NOT EXISTS item_versions (
    item_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items (item_id) ON DELETE CASCADE,
    version_no      INTEGER NOT NULL CHECK (version_no > 0),
    correct_option  TEXT    NOT NULL CHECK (correct_option IN ('A','B','C','D')),
    key_source      TEXT    NOT NULL DEFAULT 'teacher'
                            CHECK (key_source IN ('teacher','official','admin_fix','import')),
    stem_hash       TEXT,
    note            TEXT,
    is_current      INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    superseded_by   INTEGER REFERENCES item_versions (item_version_id),
    status          TEXT    NOT NULL DEFAULT 'active'
                            CHECK (status IN ('draft','active','flagged','retired')),
    created_by      INTEGER REFERENCES users (user_id),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    deleted_at      TEXT,
    UNIQUE (item_id, version_no)
);

CREATE TABLE IF NOT EXISTS item_tags (
    item_id    INTEGER NOT NULL REFERENCES items (item_id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags (tag_id) ON DELETE CASCADE,
    created_by INTEGER,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    PRIMARY KEY (item_id, tag_id)
);

CREATE TABLE IF NOT EXISTS item_status_history (
    history_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      INTEGER NOT NULL REFERENCES items (item_id) ON DELETE CASCADE,
    old_status   TEXT,
    new_status   TEXT    NOT NULL,
    reason       TEXT,
    changed_by   INTEGER,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
```

```sql
-- ============ Exam Structure: test shabloni ============
CREATE TABLE IF NOT EXISTS exam_structures (
    structure_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id       INTEGER NOT NULL REFERENCES exam_programs (program_id),
    code             TEXT    NOT NULL UNIQUE,          -- 'MATH-A-40'
    title            TEXT    NOT NULL,
    total_questions  INTEGER NOT NULL CHECK (total_questions > 0),
    duration_minutes INTEGER,
    options_count    INTEGER NOT NULL DEFAULT 4,
    rules_json       TEXT    NOT NULL DEFAULT '{}',    -- qismlar, baholash qoidalari
    status           TEXT    NOT NULL DEFAULT 'active'
                             CHECK (status IN ('draft','active','retired')),
    created_by       INTEGER REFERENCES users (user_id),
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    updated_at       TEXT,
    deleted_at       TEXT
);

CREATE TABLE IF NOT EXISTS exam_structure_sections (
    section_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    structure_id     INTEGER NOT NULL REFERENCES exam_structures (structure_id) ON DELETE CASCADE,
    section_no       INTEGER NOT NULL,
    title            TEXT    NOT NULL,
    from_position    INTEGER NOT NULL,
    to_position      INTEGER NOT NULL,
    question_count   INTEGER NOT NULL,
    points_per_item  REAL    NOT NULL DEFAULT 1.0,
    UNIQUE (structure_id, section_no),
    CHECK (to_position >= from_position)
);

-- MVP-0 dagi form_items ga Item Version bog'lanishi qo'shiladi
ALTER TABLE form_items ADD COLUMN item_version_id INTEGER REFERENCES item_versions (item_version_id);

-- ============ Kalit kiritish/yuklash tarixi (audit + qayta tahlil) ============
CREATE TABLE IF NOT EXISTS answer_key_imports (
    import_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    form_id     INTEGER REFERENCES forms (form_id) ON DELETE CASCADE,
    source      TEXT    NOT NULL DEFAULT 'text'
                        CHECK (source IN ('text','csv','xlsx','pdf_ocr','bot_wizard')),
    raw_text    TEXT,
    parsed_json TEXT    NOT NULL DEFAULT '{}',
    status      TEXT    NOT NULL DEFAULT 'ok'
                        CHECK (status IN ('ok','partial','failed')),
    errors_json TEXT    NOT NULL DEFAULT '[]',
    created_by  INTEGER REFERENCES users (user_id),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);

-- ============ Parametrlar to'plami (snapshot scoring "kaliti") ============
CREATE TABLE IF NOT EXISTS item_parameter_sets (
    parameter_set_id INTEGER PRIMARY KEY AUTOINCREMENT,
    code             TEXT    NOT NULL UNIQUE,          -- 'PS-2026-03-01'
    title            TEXT,
    description      TEXT,
    item_count       INTEGER NOT NULL DEFAULT 0,
    method           TEXT    NOT NULL DEFAULT 'classical_logit',
    is_default       INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    status           TEXT    NOT NULL DEFAULT 'active'
                             CHECK (status IN ('draft','active','archived')),
    calibration_run_id INTEGER,
    created_by       INTEGER REFERENCES users (user_id),
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    published_at     TEXT
);
```

```sql
-- ============ Kalibrlash (calibration runs) ============
CREATE TABLE IF NOT EXISTS calibration_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL UNIQUE,           -- 'CAL-2026-03-15-01'
    scope           TEXT    NOT NULL DEFAULT 'global'
                            CHECK (scope IN ('session','form','program','global')),
    scope_id        INTEGER,
    method          TEXT    NOT NULL DEFAULT 'classical_logit'
                            CHECK (method IN ('classical_logit','guessing_corrected',
                                              'rasch_jmle','anchor_linking','mean_mean')),
    parameter_set_from INTEGER REFERENCES item_parameter_sets (parameter_set_id),
    parameter_set_to   INTEGER REFERENCES item_parameter_sets (parameter_set_id),
    item_count      INTEGER NOT NULL DEFAULT 0,
    response_count  INTEGER NOT NULL DEFAULT 0,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    convergence     TEXT    CHECK (convergence IN ('converged','max_iter','failed','n/a')),
    iterations      INTEGER,
    max_abs_delta   REAL,
    log_likelihood  REAL,
    status          TEXT    NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running','finished','failed','rolled_back')),
    notes           TEXT,
    created_by      INTEGER REFERENCES users (user_id),
    started_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS calibration_run_items (
    run_item_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES calibration_runs (run_id) ON DELETE CASCADE,
    form_item_id    INTEGER REFERENCES form_items (form_item_id),
    item_version_id INTEGER,
    b_before        REAL,
    b_after         REAL,
    b_se            REAL,
    delta           REAL,
    n_used          INTEGER,
    status          TEXT    NOT NULL DEFAULT 'updated'
                            CHECK (status IN ('updated','frozen','excluded','anchor')),
    reason          TEXT
);
CREATE INDEX IF NOT EXISTS ix_calib_run_items_run ON calibration_run_items (run_id, status);

-- ============ Anchor items (equating uchun qotirilgan b) ============
CREATE TABLE IF NOT EXISTS anchor_items (
    anchor_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    item_version_id INTEGER NOT NULL REFERENCES item_versions (item_version_id),
    anchor_b        REAL    NOT NULL,                  -- kalibrlashda o'zgarmaydi
    anchor_se       REAL,
    source          TEXT    NOT NULL DEFAULT 'prior_calibration'
                            CHECK (source IN ('expert','prior_calibration','national_standard')),
    locked          INTEGER NOT NULL DEFAULT 1 CHECK (locked IN (0,1)),
    valid_from      TEXT,
    valid_to        TEXT,                              -- NULL = amalda
    note            TEXT,
    created_by      INTEGER REFERENCES users (user_id),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS ix_anchor_items_current ON anchor_items (valid_to, item_version_id);

-- ============ Equating (ikki parametrlar to'plami orasida o'girish) ============
CREATE TABLE IF NOT EXISTS equatings (
    equating_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_parameter_set INTEGER NOT NULL REFERENCES item_parameter_sets (parameter_set_id),
    to_parameter_set   INTEGER NOT NULL REFERENCES item_parameter_sets (parameter_set_id),
    method             TEXT    NOT NULL DEFAULT 'mean_mean'
                               CHECK (method IN ('mean_mean','haebara','stocking_lord','fixed_b')),
    anchor_count       INTEGER NOT NULL DEFAULT 0,
    constant_slope     REAL    NOT NULL DEFAULT 1.0,   -- θ_new = slope·θ_old + intercept
    constant_intercept REAL    NOT NULL DEFAULT 0.0,
    anchor_fit         TEXT,                           -- JSON: anchor itemlar mosligi
    status             TEXT    NOT NULL DEFAULT 'applied'
                               CHECK (status IN ('draft','applied','rejected')),
    notes              TEXT,
    created_by         INTEGER REFERENCES users (user_id),
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
```

```sql
-- ============ Result versioning: e'lon qilingan natija versiyalari ============
CREATE TABLE IF NOT EXISTS result_versions (
    result_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id     INTEGER NOT NULL REFERENCES attempts (attempt_id) ON DELETE CASCADE,
    version_no     INTEGER NOT NULL CHECK (version_no > 0),
    snapshot_id    INTEGER NOT NULL REFERENCES scoring_snapshots (snapshot_id),
    visible_from   TEXT    NOT NULL,                   -- natija ko'rinadigan vaqt
    published_at   TEXT,
    published_by   INTEGER,
    channel_json   TEXT    NOT NULL DEFAULT '[]',      -- ["bot","webapp"]
    payload_json   TEXT    NOT NULL DEFAULT '{}',      -- yuborilgan xabar "nusxasi"
    reason         TEXT,                               -- nega yangi versiya (regrade / key fix)
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    UNIQUE (attempt_id, version_no)
);
CREATE INDEX IF NOT EXISTS ix_result_versions_active ON result_versions (attempt_id, is_active);

-- ============ Urinish konteksti (kelajakda DIF / hududiy tahlil uchun) ============
CREATE TABLE IF NOT EXISTS attempt_attributes (
    attribute_id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id   INTEGER NOT NULL REFERENCES attempts (attempt_id) ON DELETE CASCADE,
    attr_key     TEXT    NOT NULL,                     -- 'region','language','device','center'
    attr_value   TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    UNIQUE (attempt_id, attr_key)
);

-- ============ Urinish hodisalari (immutable timeline) ============
CREATE TABLE IF NOT EXISTS attempt_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id  INTEGER NOT NULL REFERENCES attempts (attempt_id) ON DELETE CASCADE,
    event_type  TEXT    NOT NULL
                        CHECK (event_type IN ('started','opened','saved','submitted',
                                              'timeout','autosaved','restored','resumed',
                                              'admin_override','invalidated','regraded')),
    payload_json TEXT   NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS ix_attempt_events_attempt ON attempt_events (attempt_id, created_at);

-- ============ Xabar navbati (ishonchli yetkazish) ============
CREATE TABLE IF NOT EXISTS notification_outbox (
    outbox_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    chat_id      INTEGER,
    kind         TEXT    NOT NULL
                         CHECK (kind IN ('result_ready','submitted','admin_report',
                                         'item_flagged','calibration_done','system')),
    payload_json TEXT    NOT NULL DEFAULT '{}',
    dedup_key    TEXT,                                 -- takroriy yuborishning oldini oladi
    status       TEXT    NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','sending','sent','failed','cancelled')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    sent_at      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_outbox_dedup ON notification_outbox (dedup_key);
CREATE INDEX IF NOT EXISTS ix_outbox_pending ON notification_outbox (status, created_at);

-- ============ Rollar tarixi ============
CREATE TABLE IF NOT EXISTS staff_roles (
    staff_role_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    role          TEXT    NOT NULL
                          CHECK (role IN ('student','teacher','admin','analyst')),
    granted_by    INTEGER,
    valid_from    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    valid_to      TEXT,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS ix_staff_roles_user ON staff_roles (user_id, valid_to);

-- ============ Tizim sozlamalari (o'qituvchi EMAS, tizim/admin boshqaradi) ============
CREATE TABLE IF NOT EXISTS app_settings (
    setting_key   TEXT    PRIMARY KEY,
    value_json    TEXT    NOT NULL,
    description   TEXT,
    updated_by    INTEGER,
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);

-- ============ Migratsiya versiyalari ============
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT    PRIMARY KEY,                   -- 'MVP0_001', 'MVP1_004'
    name        TEXT    NOT NULL,
    checksum    TEXT,
    applied_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
    duration_ms INTEGER
);
```

### Boshlang'ich (seed) sozlamalar

| `setting_key` | Qiymat | Ma'nosi |
|---|---|---|
| `calibration.min_n` | `30` | Shundan kam javobda `b` yangilanmaydi |
| `calibration.k_shrink` | `30` | Shrinkaj konstantasi `K` |
| `calibration.guessing` | `"auto"` | `auto` = `1/options_count` |
| `calibration.se_freeze` | `0.30` | `frozen` ga o'tish `SE` chegarasi |
| `calibration.b_bound` | `4.0` | `|b|` uchun qat'iy chegara (logit) |
| `calibration.drift_z` | `3.0` | Drift aniqlash uchun z-chegarasi |
| `calibration.key_suspect_p` | `0.20` | Shundan past `p` → kalit xatosi gumoni |
| `scoring.theta_bound` | `3.0` | θ chegarasi (mavjud `THETA_BOUND` bilan bir xil) |

## 5. PostgreSQL arxitekturasi

### 5.1. Sxemalar (namespaces)

```sql
CREATE SCHEMA IF NOT EXISTS core;    -- users, items, forms, sessions, attempts, responses
CREATE SCHEMA IF NOT EXISTS stats;   -- item_statistics, item_parameters, calibration_runs, anchor_items, equatings
CREATE SCHEMA IF NOT EXISTS audit;   -- audit_log, item_status_history, attempt_events, result_versions
CREATE SCHEMA IF NOT EXISTS ops;     -- notification_outbox, app_settings, schema_migrations, answer_key_imports
```

| Sxema | Kim yozadi | Kim o'qiydi |
|---|---|---|
| `core` | `app_rw` (INSERT/UPDATE, soft delete) | `app_rw`, `analyst_ro` |
| `stats` | `app_worker` | `app_worker`, `analyst_ro` |
| `audit` | `app_rw` (faqat INSERT), `app_worker` | `analyst_ro` (faqat SELECT) |
| `ops` | `app_rw`, `app_worker` | `analyst_ro` |

### 5.2. Kengaytmalar va konvensiyalar

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid(), digest()
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- item_ref bo'yicha qidiruv
```

| SQLite | PostgreSQL | Izoh |
|---|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY` | `id` qiymatlari 1:1 ko'chiriladi |
| `TEXT` (vaqt) | `timestamptz` | UTC ISO satri → `timestamptz` |
| `TEXT` (JSON) | `jsonb` | `jsonb_typeof` tekshiruvlari qo'shiladi |
| `INTEGER` (0/1) | `boolean` | `is_current`, `is_anchor`, `locked` |
| `REAL` | `numeric(8,4)` (b, p, θ, SE) / `real` (ball) | Aniqlik uchun `numeric` |
| `CHECK (col IN (...))` | `text` + `CHECK` yoki `CREATE TYPE ... AS ENUM` | Enum o'zgartirish qiyin — `CHECK` tavsiya etiladi |
| `strftime('%Y-%m-%dT%H:%M:%S+00:00','now')` | `now()` (UTC) | |

### 5.3. PostgreSQL DDL — core (asosiy qism)

```sql
-- ---------- Identity ----------
CREATE TABLE core.users (
    user_id     bigint PRIMARY KEY,                      -- Telegram user id
    full_name   text NOT NULL,
    username    text,
    role        text NOT NULL DEFAULT 'student'
                CHECK (role IN ('student','teacher','admin','analyst')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz,
    deleted_at  timestamptz
);

-- ---------- Question Bank ----------
CREATE TABLE core.subjects (
    subject_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        text NOT NULL UNIQUE,
    title       text NOT NULL,
    is_active   boolean NOT NULL DEFAULT true
);

CREATE TABLE core.exam_programs (
    program_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject_id  bigint NOT NULL REFERENCES core.subjects (subject_id),
    code        text NOT NULL UNIQUE,
    title       text NOT NULL,
    level       text,
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE core.topics (
    topic_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject_id      bigint NOT NULL REFERENCES core.subjects (subject_id),
    parent_topic_id bigint REFERENCES core.topics (topic_id),
    code            text NOT NULL,
    title           text NOT NULL,
    UNIQUE (subject_id, code)
);

CREATE TABLE core.tags (
    tag_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tag_group text NOT NULL DEFAULT 'general'
              CHECK (tag_group IN ('general','source','skill','level','topic')),
    code      text NOT NULL UNIQUE,
    title     text NOT NULL
);

CREATE TABLE core.items (
    item_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    program_id    bigint NOT NULL REFERENCES core.exam_programs (program_id),
    topic_id      bigint REFERENCES core.topics (topic_id),
    item_ref      text NOT NULL,                         -- 'NS2026-MATH-37'
    content_hash  char(64),                              -- SHA-256 (savol matni saqlanmaydi!)
    media_ref     text,
    options_count smallint NOT NULL DEFAULT 4 CHECK (options_count BETWEEN 2 AND 6),
    part          text NOT NULL DEFAULT '' CHECK (part IN ('','a','b')),
    status        text NOT NULL DEFAULT 'active'
                  CHECK (status IN ('draft','active','flagged','retired')),
    current_version_id bigint,
    created_by    bigint REFERENCES core.users (user_id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz,
    deleted_at    timestamptz
);
CREATE UNIQUE INDEX ux_items_ref ON core.items (program_id, item_ref, part) WHERE deleted_at IS NULL;
CREATE INDEX ix_items_program ON core.items (program_id, status) WHERE deleted_at IS NULL;

CREATE TABLE core.item_versions (
    item_version_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id         bigint NOT NULL REFERENCES core.items (item_id) ON DELETE CASCADE,
    version_no      integer NOT NULL CHECK (version_no > 0),
    correct_option  char(1) NOT NULL CHECK (correct_option IN ('A','B','C','D')),
    key_source      text NOT NULL DEFAULT 'teacher'
                    CHECK (key_source IN ('teacher','official','admin_fix','import')),
    stem_hash       char(64),
    note            text,
    is_current      boolean NOT NULL DEFAULT true,
    superseded_by   bigint REFERENCES core.item_versions (item_version_id),
    status          text NOT NULL DEFAULT 'active'
                    CHECK (status IN ('draft','active','flagged','retired')),
    created_by      bigint REFERENCES core.users (user_id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz,
    UNIQUE (item_id, version_no)
);
CREATE UNIQUE INDEX ux_item_versions_current
    ON core.item_versions (item_id) WHERE is_current AND deleted_at IS NULL;
```

```sql
-- ---------- Exam Structure ----------
CREATE TABLE core.exam_structures (
    structure_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    program_id       bigint NOT NULL REFERENCES core.exam_programs (program_id),
    code             text NOT NULL UNIQUE,
    title            text NOT NULL,
    total_questions  integer NOT NULL CHECK (total_questions > 0),
    duration_minutes integer,
    options_count    smallint NOT NULL DEFAULT 4,
    rules_json       jsonb NOT NULL DEFAULT '{}'::jsonb,
    status           text NOT NULL DEFAULT 'active'
                     CHECK (status IN ('draft','active','retired')),
    created_by       bigint REFERENCES core.users (user_id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz,
    deleted_at       timestamptz
);

CREATE TABLE core.exam_structure_sections (
    section_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    structure_id    bigint NOT NULL REFERENCES core.exam_structures (structure_id) ON DELETE CASCADE,
    section_no      integer NOT NULL,
    title           text NOT NULL,
    from_position   integer NOT NULL,
    to_position     integer NOT NULL,
    question_count  integer NOT NULL,
    points_per_item numeric(6,2) NOT NULL DEFAULT 1.0,
    UNIQUE (structure_id, section_no),
    CHECK (to_position >= from_position)
);

-- ---------- Formalar ----------
CREATE TABLE core.forms (
    form_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title             text NOT NULL,
    test_code         text NOT NULL,
    structure_id      bigint REFERENCES core.exam_structures (structure_id),
    program_id        bigint REFERENCES core.exam_programs (program_id),
    total_questions   integer NOT NULL CHECK (total_questions > 0),
    options_count     smallint NOT NULL DEFAULT 4 CHECK (options_count BETWEEN 2 AND 6),
    parts_json        jsonb NOT NULL DEFAULT '[]'::jsonb,
    current_version_id bigint,
    created_by        bigint REFERENCES core.users (user_id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz,
    deleted_at        timestamptz
);
CREATE UNIQUE INDEX ux_forms_test_code ON core.forms (upper(test_code)) WHERE deleted_at IS NULL;

CREATE TABLE core.form_versions (
    form_version_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form_id         bigint NOT NULL REFERENCES core.forms (form_id) ON DELETE CASCADE,
    version_no      integer NOT NULL CHECK (version_no > 0),
    -- KALIT: nusxa sifatida saqlanadi (audit), API orqali HECH QACHON berilmaydi
    answer_key      text NOT NULL,
    key_hash        char(64),                            -- sha256(answer_key) — tekshirish uchun
    total_questions integer NOT NULL CHECK (total_questions > 0),
    change_reason   text,
    status          text NOT NULL DEFAULT 'published'
                    CHECK (status IN ('draft','published','retired')),
    created_by      bigint REFERENCES core.users (user_id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    published_at    timestamptz,
    UNIQUE (form_id, version_no)
);

CREATE TABLE core.form_items (
    form_item_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form_version_id bigint NOT NULL REFERENCES core.form_versions (form_version_id) ON DELETE CASCADE,
    position        integer NOT NULL CHECK (position > 0),
    part            text NOT NULL DEFAULT '' CHECK (part IN ('','a','b')),
    correct_option  char(1) NOT NULL CHECK (correct_option IN ('A','B','C','D')),
    options_count   smallint NOT NULL DEFAULT 4,
    item_version_id bigint REFERENCES core.item_versions (item_version_id),
    section_no      integer,
    points          numeric(6,2) NOT NULL DEFAULT 1.0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (form_version_id, position, part)
);
CREATE INDEX ix_form_items_version ON core.form_items (form_version_id, position);
CREATE INDEX ix_form_items_item_version ON core.form_items (item_version_id);

-- ---------- Sessiyalar ----------
CREATE TABLE core.exam_sessions (
    session_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form_id     bigint NOT NULL REFERENCES core.forms (form_id) ON DELETE RESTRICT,
    title       text,
    start_time  timestamptz NOT NULL,
    end_time    timestamptz NOT NULL,
    result_time timestamptz NOT NULL,
    timezone    text NOT NULL DEFAULT 'Asia/Tashkent',
    status      text NOT NULL DEFAULT 'scheduled'
                CHECK (status IN ('scheduled','active','closed','graded','published','cancelled')),
    graded_at   timestamptz,
    created_by  bigint REFERENCES core.users (user_id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz,
    deleted_at  timestamptz,
    CHECK (end_time > start_time),
    CHECK (result_time >= end_time)
);
CREATE INDEX ix_sessions_open ON core.exam_sessions (end_time) WHERE status IN ('scheduled','active');
```

```sql
-- ---------- Urinishlar ----------
CREATE TABLE core.attempts (
    attempt_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id       bigint NOT NULL REFERENCES core.exam_sessions (session_id) ON DELETE RESTRICT,
    user_id          bigint NOT NULL REFERENCES core.users (user_id) ON DELETE RESTRICT,
    form_version_id  bigint NOT NULL REFERENCES core.form_versions (form_version_id),
    parameter_set_id bigint,                       -- snapshot: qaysi b to'plami ishlatilgan
    status           text NOT NULL DEFAULT 'in_progress'
                     CHECK (status IN ('in_progress','submitted','submitted_late',
                                       'graded','expired','invalid','cancelled')),
    started_at       timestamptz NOT NULL,
    last_seen_at     timestamptz,
    submitted_at     timestamptz,
    revision         integer NOT NULL DEFAULT 0,
    device_json      jsonb,
    ip_hash          char(64),
    raw_score        integer,
    omitted_count    integer,
    theta            numeric(8,4),
    theta_se         numeric(8,4),
    scaled_score     numeric(6,2),
    graded_at        timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz,
    deleted_at       timestamptz
);
CREATE UNIQUE INDEX ux_attempts_session_user
    ON core.attempts (session_id, user_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_attempts_session_status ON core.attempts (session_id, status);
CREATE INDEX ix_attempts_user ON core.attempts (user_id, created_at DESC);

-- ---------- Item-level javoblar: APPEND-ONLY, partitioning bilan ----------
CREATE TABLE core.responses (
    response_id     bigint GENERATED ALWAYS AS IDENTITY,
    attempt_id      bigint NOT NULL,
    form_item_id    bigint NOT NULL,
    item_version_id bigint,
    position        integer NOT NULL,
    part            text NOT NULL DEFAULT '',
    given_option    char(1) CHECK (given_option IS NULL OR given_option IN ('A','B','C','D')),
    response_state  text NOT NULL DEFAULT 'answered'
                    CHECK (response_state IN ('answered','omitted','cleared')),
    is_correct      boolean,
    revision        integer NOT NULL CHECK (revision > 0),
    client_seq      bigint,
    source          text NOT NULL DEFAULT 'webapp'
                    CHECK (source IN ('webapp','bot','import','admin','system')),
    is_current      boolean NOT NULL DEFAULT true,
    superseded_by   bigint,
    answered_at     timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    ip_hash         char(64),
    PRIMARY KEY (response_id, created_at)
) PARTITION BY RANGE (created_at);

-- Sessiya bo'yicha partition yaratish (kalibrlash davriga mos)
CREATE TABLE core.responses_2026_03 PARTITION OF core.responses
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

CREATE UNIQUE INDEX ux_responses_revision
    ON core.responses (attempt_id, form_item_id, revision, created_at);
CREATE UNIQUE INDEX ux_responses_current
    ON core.responses (attempt_id, form_item_id) WHERE is_current;
CREATE UNIQUE INDEX ux_responses_client_seq
    ON core.responses (attempt_id, client_seq) WHERE client_seq IS NOT NULL;
CREATE INDEX ix_responses_item ON core.responses (form_item_id, is_current);
```

> Partition'li jadvalda PK `(response_id, created_at)` ko'rinishida bo'lishi shart.
> `attempts` va `form_items` ga FK qo'yilmaydi (partition'larda FK ishlamaydi) —
> o'rniga `audit`/`stats` tekshiruv so'rovlari va haftalik `CHECK` SQL ishlatiladi.

**Javoblarni himoyalash (immutability trigger):**

```sql
CREATE OR REPLACE FUNCTION core.forbid_response_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'responses jadvali append-only: UPDATE/DELETE taqiqlanadi';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_responses_no_update
    BEFORE UPDATE OR DELETE ON core.responses
    FOR EACH ROW EXECUTE FUNCTION core.forbid_response_mutation();

-- Yagona istisno: eski revision'ni "joriy emas" qilib belgilash
-- (bu ham UPDATE ni taqiqlaydi — shuning uchun `is_current` ni partial index
--  bilan emas, quyidagi SECURITY DEFINER funksiya orqali yangilaymiz)
CREATE OR REPLACE FUNCTION core.retire_previous_response(
    p_attempt_id bigint, p_form_item_id bigint, p_new_response_id bigint
) RETURNS void AS $$
BEGIN
    UPDATE core.responses
       SET is_current = false, superseded_by = p_new_response_id
     WHERE attempt_id = p_attempt_id
       AND form_item_id = p_form_item_id
       AND is_current
       AND response_id <> p_new_response_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

> SQLite'da trigger oddiyroq: `CREATE TRIGGER ... BEFORE UPDATE ON responses
> WHEN OLD.is_current = 1 AND NEW.is_current = 1 BEGIN SELECT RAISE(ABORT, ...); END;`
> — ya'ni "eski revision'ni nafaqat joriy holatga qaytarish mumkin emas".

### 5.4. PostgreSQL DDL — stats, audit, ops

```sql
-- ---------- Parametrlar ----------
CREATE TABLE stats.item_parameter_sets (
    parameter_set_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code             text NOT NULL UNIQUE,                -- 'PS-2026-03-01'
    title            text,
    description      text,
    item_count       integer NOT NULL DEFAULT 0,
    method           text NOT NULL DEFAULT 'classical_logit',
    is_default       boolean NOT NULL DEFAULT false,
    status           text NOT NULL DEFAULT 'active'
                     CHECK (status IN ('draft','active','archived')),
    calibration_run_id bigint,
    created_by       bigint REFERENCES core.users (user_id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    published_at     timestamptz
);
CREATE UNIQUE INDEX ux_parameter_sets_default
    ON stats.item_parameter_sets (is_default) WHERE is_default AND status = 'active';

CREATE TABLE stats.item_parameters (
    item_parameter_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form_item_id      bigint REFERENCES core.form_items (form_item_id),
    item_version_id   bigint REFERENCES core.item_versions (item_version_id),
    parameter_set_id  bigint REFERENCES stats.item_parameter_sets (parameter_set_id),
    b_value           numeric(8,4) NOT NULL DEFAULT 0.0,  -- logit (TIZIM hisoblaydi)
    b_se              numeric(8,4),
    source            text NOT NULL DEFAULT 'default'
                      CHECK (source IN ('default','classical','guessing_corrected',
                                        'rasch','anchor','legacy_expert')),
    status            text NOT NULL DEFAULT 'provisional'
                      CHECK (status IN ('provisional','operational','frozen','retired')),
    is_anchor         boolean NOT NULL DEFAULT false,
    anchor_b          numeric(8,4),
    calibration_run_id bigint,
    n_used            integer,
    valid_from        timestamptz NOT NULL DEFAULT now(),
    valid_to          timestamptz,                        -- NULL = hozir amalda
    created_by        bigint,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (form_item_id IS NOT NULL OR item_version_id IS NOT NULL)
);
CREATE UNIQUE INDEX ux_item_parameters_current
    ON stats.item_parameters (coalesce(item_version_id, -form_item_id))
    WHERE valid_to IS NULL AND status <> 'retired';

-- ---------- Item Statistics ----------
CREATE TABLE stats.item_statistics (
    stat_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form_item_id     bigint REFERENCES core.form_items (form_item_id),
    item_version_id  bigint REFERENCES core.item_versions (item_version_id),
    scope            text NOT NULL DEFAULT 'session'
                     CHECK (scope IN ('session','form','program','global')),
    session_id       bigint REFERENCES core.exam_sessions (session_id),
    window_start     timestamptz,
    window_end       timestamptz,
    n_presented      integer NOT NULL DEFAULT 0,
    n_answered       integer NOT NULL DEFAULT 0,
    n_correct        integer NOT NULL DEFAULT 0,
    n_omitted        integer NOT NULL DEFAULT 0,
    p_raw            numeric(6,4),
    p_used           numeric(6,4),
    guessing_c       numeric(6,4),
    b_raw            numeric(8,4),
    b_adjusted       numeric(8,4),
    b_final          numeric(8,4),
    b_se             numeric(8,4),
    group_mean_theta numeric(8,4),
    prior_b          numeric(8,4),
    shrinkage_weight numeric(6,4),
    method           text NOT NULL DEFAULT 'classical_logit'
                     CHECK (method IN ('classical_logit','guessing_corrected',
                                       'rasch_jmle','anchor_linking','imported')),
    flags            jsonb NOT NULL DEFAULT '[]'::jsonb,
    calibration_run_id bigint,
    is_current       boolean NOT NULL DEFAULT true,
    computed_at      timestamptz NOT NULL DEFAULT now(),
    computed_by      text NOT NULL DEFAULT 'system'
                     CHECK (computed_by IN ('system','admin','import'))
);
CREATE INDEX ix_item_stats_item ON stats.item_statistics (item_version_id, computed_at DESC);
CREATE INDEX ix_item_stats_session ON stats.item_statistics (session_id) WHERE is_current;

-- ---------- Snapshot scoring ----------
CREATE TABLE stats.scoring_snapshots (
    snapshot_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    attempt_id       bigint NOT NULL REFERENCES core.attempts (attempt_id) ON DELETE CASCADE,
    form_version_id  bigint NOT NULL REFERENCES core.form_versions (form_version_id),
    parameter_set_id bigint REFERENCES stats.item_parameter_sets (parameter_set_id),
    model            text NOT NULL DEFAULT 'rasch_1pl'
                     CHECK (model IN ('raw','classical_logit','rasch_1pl','rasch_2pl')),
    theta            numeric(8,4),
    theta_se         numeric(8,4),
    log_likelihood   numeric(12,4),
    raw_score        integer NOT NULL DEFAULT 0,
    total_items      integer NOT NULL DEFAULT 0,
    omitted_count    integer NOT NULL DEFAULT 0,
    scaled_score     numeric(6,2),
    scaled_min       numeric(6,2) NOT NULL DEFAULT 0.0,
    scaled_max       numeric(6,2) NOT NULL DEFAULT 100.0,
    theta_bound      numeric(6,2) NOT NULL DEFAULT 3.0,
    engine_version   text NOT NULL DEFAULT '1.0',
    b_checksum       char(64),
    is_final         boolean NOT NULL DEFAULT true,
    supersedes_id    bigint REFERENCES stats.scoring_snapshots (snapshot_id),
    computed_at      timestamptz NOT NULL DEFAULT now(),
    computed_by      text NOT NULL DEFAULT 'system'
                     CHECK (computed_by IN ('system','admin','regrade'))
);
CREATE INDEX ix_snapshots_attempt ON stats.scoring_snapshots (attempt_id, computed_at DESC);
```

```sql
-- ---------- Kalibrlash ----------
CREATE TABLE stats.calibration_runs (
    run_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code             text NOT NULL UNIQUE,
    scope            text NOT NULL DEFAULT 'global'
                     CHECK (scope IN ('session','form','program','global')),
    scope_id         bigint,
    method           text NOT NULL DEFAULT 'classical_logit'
                     CHECK (method IN ('classical_logit','guessing_corrected',
                                       'rasch_jmle','anchor_linking','mean_mean')),
    parameter_set_from bigint REFERENCES stats.item_parameter_sets (parameter_set_id),
    parameter_set_to   bigint REFERENCES stats.item_parameter_sets (parameter_set_id),
    item_count       integer NOT NULL DEFAULT 0,
    response_count   integer NOT NULL DEFAULT 0,
    attempt_count    integer NOT NULL DEFAULT 0,
    convergence      text CHECK (convergence IN ('converged','max_iter','failed','n/a')),
    iterations       integer,
    max_abs_delta    numeric(8,4),
    log_likelihood   numeric(14,4),
    status           text NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running','finished','failed','rolled_back')),
    notes            text,
    created_by       bigint REFERENCES core.users (user_id),
    started_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz
);

CREATE TABLE stats.calibration_run_items (
    run_item_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          bigint NOT NULL REFERENCES stats.calibration_runs (run_id) ON DELETE CASCADE,
    form_item_id    bigint REFERENCES core.form_items (form_item_id),
    item_version_id bigint REFERENCES core.item_versions (item_version_id),
    b_before        numeric(8,4),
    b_after         numeric(8,4),
    b_se            numeric(8,4),
    delta           numeric(8,4),
    n_used          integer,
    status          text NOT NULL DEFAULT 'updated'
                    CHECK (status IN ('updated','frozen','excluded','anchor')),
    reason          text
);
CREATE INDEX ix_calib_run_items_run ON stats.calibration_run_items (run_id, status);

-- ---------- Anchor items va equating ----------
CREATE TABLE stats.anchor_items (
    anchor_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_version_id bigint NOT NULL REFERENCES core.item_versions (item_version_id),
    anchor_b        numeric(8,4) NOT NULL,
    anchor_se       numeric(8,4),
    source          text NOT NULL DEFAULT 'prior_calibration'
                    CHECK (source IN ('expert','prior_calibration','national_standard')),
    locked          boolean NOT NULL DEFAULT true,
    valid_from      timestamptz,
    valid_to        timestamptz,
    note            text,
    created_by      bigint REFERENCES core.users (user_id),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_anchor_items_current
    ON stats.anchor_items (item_version_id) WHERE valid_to IS NULL;

CREATE TABLE stats.equatings (
    equating_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_parameter_set bigint NOT NULL REFERENCES stats.item_parameter_sets (parameter_set_id),
    to_parameter_set   bigint NOT NULL REFERENCES stats.item_parameter_sets (parameter_set_id),
    method             text NOT NULL DEFAULT 'mean_mean'
                       CHECK (method IN ('mean_mean','haebara','stocking_lord','fixed_b')),
    anchor_count       integer NOT NULL DEFAULT 0,
    constant_slope     numeric(8,4) NOT NULL DEFAULT 1.0,
    constant_intercept numeric(8,4) NOT NULL DEFAULT 0.0,
    anchor_fit         jsonb,
    status             text NOT NULL DEFAULT 'applied'
                       CHECK (status IN ('draft','applied','rejected')),
    notes              text,
    created_by         bigint REFERENCES core.users (user_id),
    created_at         timestamptz NOT NULL DEFAULT now()
);
```

```sql
-- ---------- Audit (partition'li, faqat INSERT) ----------
CREATE TABLE audit.audit_log (
    audit_id      bigint GENERATED ALWAYS AS IDENTITY,
    actor_user_id bigint,
    actor_role    text,
    action        text NOT NULL,
    entity_type   text NOT NULL,
    entity_id     text,
    before_json   jsonb,
    after_json    jsonb,
    request_id    text,
    source        text NOT NULL DEFAULT 'bot'
                  CHECK (source IN ('bot','webapp','admin_api','migration','system')),
    ip_hash       char(64),
    note          text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (audit_id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE audit.audit_log_2026_03 PARTITION OF audit.audit_log
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

CREATE INDEX ix_audit_entity ON audit.audit_log (entity_type, entity_id, created_at DESC);
CREATE INDEX ix_audit_actor  ON audit.audit_log (actor_user_id, created_at DESC);
CREATE INDEX ix_audit_action ON audit.audit_log (action, created_at DESC);

REVOKE UPDATE, DELETE ON audit.audit_log FROM app_rw, app_worker;
```

### 5.5. PG'da qolgan jadvallar

Quyidagilar SQLite DDL dagi ustunlar bilan **bir xil** — faqat 5.2 dagi
konversiya qoidalari qo'llanadi (`0/1` → `boolean`, `TEXT` vaqt → `timestamptz`,
`TEXT` JSON → `jsonb`, `REAL` → `numeric(8,4)`):

| Sxema | Jadvallar |
|---|---|
| `core` | `item_tags`, `item_status_history`, `attempt_attributes`, `attempt_events` |
| `audit` | `result_versions` |
| `ops` | `staff_roles`, `answer_key_imports`, `notification_outbox`, `app_settings`, `schema_migrations` |

### 5.6. Rollar va RLS namunasi

```sql
CREATE ROLE app_rw     LOGIN PASSWORD '***';
CREATE ROLE app_worker LOGIN PASSWORD '***';
CREATE ROLE analyst_ro LOGIN PASSWORD '***';

GRANT USAGE ON SCHEMA core, stats, audit, ops TO app_rw, app_worker, analyst_ro;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA core  TO app_rw;
GRANT SELECT, INSERT         ON ALL TABLES IN SCHEMA audit TO app_rw;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA stats TO app_worker;
GRANT SELECT                 ON ALL TABLES IN SCHEMA core, stats, audit, ops TO analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT SELECT, INSERT, UPDATE TO app_rw;

-- O'quvchi faqat o'z urinishini ko'radi (API ustidan qo'shimcha himoya)
ALTER TABLE core.attempts ENABLE ROW LEVEL SECURITY;
CREATE POLICY attempts_self ON core.attempts
    FOR SELECT USING (user_id = current_setting('app.user_id', true)::bigint);
```

> API qatlami har bir so'rovda `SET LOCAL app.user_id = <telegram_id>` bajaradi;
> RLS API'dagi mantiqiy xatolarni ham to'sadi (ikki qavatli himoya).

## 6. Audit talablari ↔ jadval mosligi (checklist)

| Talab | Qanday qondiriladi |
|---|---|
| Question Bank | `items`, `item_versions`, `topics`, `subjects`, `exam_programs` |
| Item | `items` (matnsiz: `item_ref` + `content_hash` + `media_ref`) |
| Item Version | `item_versions` (immutable, `is_current`, `superseded_by`) |
| Item Statistics | `item_statistics` (append-only, davr bo'yicha, `is_current`) |
| Item Status | `items.status` + `item_status_history` (to'liq tarix) |
| Item Tags | `tags`, `item_tags` |
| Exam Structure | `exam_structures`, `exam_structure_sections` |
| Form | `forms`, `form_versions`, `form_items` |
| Session | `exam_sessions` |
| Attempt | `attempts` + `attempt_events` |
| Response System | `responses` (append-only, `revision`, `client_seq`, `source`) |
| Item-level responses | `responses` (`form_item_id`, `position`, `part`) — javob bitta savolga bitta satr |
| Snapshot scoring | `attempts.parameter_set_id` + `scoring_snapshots` (θ, SE, raw, `b_checksum`) |
| Immutable response history | `revision` + `is_current` + `superseded_by` + UPDATE/DELETE trigger |
| Security | rollar, RLS, `ip_hash`, `answer_key`/`b` faqat server ichida |
| Soft delete | barcha asosiy jadvalda `deleted_at` + partial unique indekslar |
| Audit log | `audit_log` (before/after JSON, `request_id`, `source`, `actor_role`) |
| Result versioning | `result_versions` (`version_no`, `is_active`, `visible_from`, `reason`) |
| Anchor items | `anchor_items` (`locked`, `anchor_b`, `valid_from/to`) |
| Calibration runs | `calibration_runs`, `calibration_run_items` |
| Equating readiness | `equatings` (`constant_slope`, `constant_intercept`, `anchor_fit`) |
| PostgreSQL readiness | 5-bo'lim: bir xil mantiqiy sxema + konversiya jadvali + partitioning + RLS |

## 7. MVP uchun minimal jadvallar (yakuniy ro'yxat)

**MVP-0 (11 jadval + 1 view)** — birinchi sprintda ishga tushadigan minimal:

| # | Jadval | Nega kerak |
|---|---|---|
| 1 | `users` | Kim javob yuborayotganini bilish, rol |
| 2 | `forms` | Test kodi va metadata |
| 3 | `form_versions` | Kalit snapshot'i (audit) |
| 4 | `form_items` | Har bir savol pozitsiyasi (kalit + variantlar soni) |
| 5 | `exam_sessions` | Vaqt oynasi (start/end/result) |
| 6 | `attempts` | Urinish holati va snapshot bog'lanishlari |
| 7 | `responses` | Item-level javoblar (append-only) |
| 8 | `item_parameters` | Operatsion `b` (default 0.0 → hisoblanadi) |
| 9 | `item_statistics` | `n`, `p`, `b`, `SE`, flag — hisoblash tarixi |
| 10 | `scoring_snapshots` | θ/raw/scaled natijasi (qayta ishlab chiqarish) |
| 11 | `audit_log` | Audit talabi |

**MVP-1 (+8 jadval)** — Question Bank va kalibrlash to'liq:
`subjects`, `exam_programs`, `items`, `item_versions`,
`item_parameter_sets`, `result_versions`, `calibration_runs`, `anchor_items`.

**MVP-2 (+15 jadval)** — kengaytma va audit to'liq:
`topics`, `tags`, `item_tags`, `item_status_history`, `exam_structures`,
`exam_structure_sections`, `answer_key_imports`, `attempt_attributes`,
`attempt_events`, `calibration_run_items`, `equatings`, `staff_roles`,
`notification_outbox`, `app_settings`, `schema_migrations`.

## 8. Muhim so'rovlar (kalibrlash uchun tayyor SQL)

```sql
-- 1) Item bo'yicha xom statistika (davr = bitta sessiya)
SELECT fi.form_item_id,
       COUNT(*)                                              AS n_presented,
       SUM(CASE WHEN r.given_option IS NOT NULL THEN 1 ELSE 0 END) AS n_answered,
       SUM(CASE WHEN r.given_option = fi.correct_option THEN 1 ELSE 0 END) AS n_correct,
       SUM(CASE WHEN r.given_option IS NULL THEN 1 ELSE 0 END)      AS n_omitted
  FROM responses r
  JOIN form_items fi ON fi.form_item_id = r.form_item_id
  JOIN attempts  a   ON a.attempt_id    = r.attempt_id
 WHERE r.is_current = 1                 -- faqat joriy javoblar
   AND a.status IN ('submitted','submitted_late','graded')
   AND a.deleted_at IS NULL
   AND a.session_id = ?                 -- davr (yoki NULL = hamma davr)
 GROUP BY fi.form_item_id;

-- 2) Guruhning o'rtacha θ si (mean-mean moslash uchun)
SELECT AVG(s.theta) AS group_mean_theta
  FROM scoring_snapshots s
  JOIN attempts a ON a.attempt_id = s.attempt_id
 WHERE s.is_final = 1 AND a.session_id = ?;

-- 3) Joriy operatsion b lar to'plami (scoring snapshot uchun)
SELECT fi.form_item_id,
       COALESCE(ip.b_value, 0.0) AS b_value
  FROM form_items fi
  JOIN form_versions fv ON fv.form_version_id = fi.form_version_id
  LEFT JOIN item_parameters ip
         ON ip.form_item_id = fi.form_item_id AND ip.valid_to IS NULL
 WHERE fv.form_version_id = ?;

-- 4) Drift tekshiruvi: ikki davr orasida p farqi (z-test)
SELECT s1.form_item_id, s1.p_raw AS p1, s2.p_raw AS p2,
       (s2.p_raw - s1.p_raw) /
       NULLIF(SQRT( (s1.p_raw*(1-s1.p_raw)/s1.n_presented) +
                    (s2.p_raw*(1-s2.p_raw)/s2.n_presented) ), 0) AS z
  FROM item_statistics s1
  JOIN item_statistics s2
    ON s2.form_item_id = s1.form_item_id AND s2.is_current = 1
 WHERE s1.is_current = 1 AND s1.session_id = ? AND s2.session_id = ?;
```

> **Diqqat:** `responses` dan statistika yig'ishda faqat `is_current = 1`
> satrlar olinadi (ya'ni o'quvchi oxirgi tanlovi). Tarix esa to'liq saqlanadi —
> kelajakda "javobni necha marta o'zgartirgan" kabi tahlillar ham mumkin.

