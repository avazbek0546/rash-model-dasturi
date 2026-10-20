# 05 — Migratsiya rejasi (mavjud tizim → yangi sxema → PostgreSQL)

## 1. Tamoyillar

| Tamoyil | Qoida |
|---|---|
| **Additive first** | Avval faqat **yangi jadvallar** qo'shiladi. Mavjud `exams`, `user_answers`, `questions` **o'chirilmaydi** |
| **Backward compatible** | Eski kod, eski `/api/*`, eski Mini App ishlab turadi (bir vaqtda ikki oqim) |
| **Reversible** | Har bir bosqichda orqaga qaytish yo'li bor (`down` SQL yoki zaxira nusxa) |
| **Idempotent** | Migratsiya ikki marta ishga tushsa ham bir xil natija (`CREATE TABLE IF NOT EXISTS`, `ON CONFLICT DO NOTHING`) |
| **Audit-friendly** | Ko'chirilgan ma'lumot `audit_log` ga `source='migration'` bilan yoziladi |
| **Dry-run** | `--dry-run` rejimi: nima o'zgarishini ko'rsatadi, yozmaydi |
| **Backup before each step** | `data/math_bot.db` fayli nusxalanadi: `data/backup/math_bot_YYYYMMDD_HHMM.db` |

## 2. Migratsiya infratuzilmasi

Yangi kutubxona **qo'shilmaydi** (loyiha minimal bog'liqlik siyosati).
`database/migrations/` papkasi va kichik runner:

```
database/migrations/
  MVP0_001_core_tables.sql        # users (ALTER), forms, form_versions, form_items
  MVP0_002_sessions_attempts.sql  # exam_sessions, attempts
  MVP0_003_responses.sql          # responses + view + trigger
  MVP0_004_stats.sql              # item_parameters, item_statistics, scoring_snapshots
  MVP0_005_audit.sql              # audit_log
  MVP1_006_question_bank.sql      # subjects, exam_programs, items, item_versions, ALTER form_items
  MVP1_007_parameter_sets.sql     # item_parameter_sets, result_versions
  MVP1_008_calibration.sql        # calibration_runs, calibration_run_items, anchor_items, equatings
  MVP2_009_extras.sql             # topics, tags, item_tags, item_status_history, attempt_events, ...
  MVP2_010_backfill.sql           # eski exams/user_answers → yangi jadvallar
```

Runner xatti-harakati (`database/migrate.py`):

```
 1. schema_migrations jadvalini yaratadi (yo'q bo'lsa)
 2. migrations/*.sql ni nom bo'yicha tartiblaydi
 3. har bir fayl uchun: agar version allaqachon yozilgan bo'lsa — o'tkazib yuboradi
 4. SHA-256 checksum tekshiradi (o'zgargan fayl → xatolik, qo'lda tasdiq talab qilinadi)
 5. tranzaksiyada bajaradi: sql + INSERT INTO schema_migrations(...)
 6. --dry-run: faqat bajariladigan fayllar ro'yxatini chiqaradi
 7. --to MVP0_004: shu versiyaga qadar bajaradi
```

`main.py` ishga tushganda runner **avtomatik** chaqiriladi (hozirgi
`executescript(SCHEMA_SQL)` o'rnida) — shu bilan yangi jadval qo'shish
xavfsiz bo'ladi.

## 3. Bosqichlar

### M0 — Infratuzilma (1–2 kun)

| Vazifa | Natija |
|---|---|
| `database/migrations/` + `migrate.py` yozish | `schema_migrations` jadvali ishlaydi |
| `db.py` dagi `SCHEMA_SQL` → migratsiya orqali | Mavjud baza buzilmaydi |
| Zaxira skripti (`data/backup/`) | Har bir migratsiyadan oldin nusxa |
| **Chiqish mezoni** | `python main.py` xatosiz ishga tushadi, eski testlar o'tadi |

### M1 — Yangi jadvallar (MVP-0, 1 hafta)

| Vazifa | Natija |
|---|---|
| `MVP0_001–005` migratsiyalari | 11 yangi jadval + 1 view + trigger |
| `database/models.py` ga dataclass'lar | `Form`, `Attempt`, `Response`, `ItemStatistic` |
| `database/repository.py` ga repository'lar | `AttemptRepository`, `ResponseRepository`, `StatsRepository` |
| **Chiqish mezoni** | Yangi jadvallar bo'sh, eski oqim o'zgarmagan, `tests/test_exam_flow.py` o'tadi |

### M2 — Yangi API va UI (MVP-0, 2 hafta)

| Vazifa | Natija |
|---|---|
| `web/api_v2.py` (6 endpoint) | Autosave ishlaydi |
| `webapp/js/sheet.js` + `index.html` yangi ekran | Kartochkalar, autosave, refresh tiklash |
| `services/scoring.py` (snapshot scoring) | `attempts` → θ, raw, scaled |
| **Chiqish mezoni** | Sinov sessiyasi: 20 o'quvchi, 40 savol — javoblar yo'qolmaydi, natija to'g'ri |

### M3 — Question Bank va kalibrlash (MVP-1, 2–3 hafta)

| Vazifa | Natija |
|---|---|
| `MVP1_006–008` | `items`, `item_versions`, `calibration_runs`, `anchor_items` |
| `services/difficulty.py` + `services/calibration.py` | `p → b` avtomatik hisoblanadi |
| `handlers/admin_form.py` (`/new_form`) | Logit so'ralmaydi |
| `handlers/admin_stats.py` (`/item`, `/calibration`, `/freeze`) | Admin panel |
| `MVP2_010_backfill.sql` | Eski imtihonlar ko'chirildi |
| **Chiqish mezoni** | 2-sessiyadan keyin `item_parameters` avtomatik yangilandi; `tests/test_difficulty.py`, `test_calibration.py` o'tadi |

### M4 — Audit va natija versiyalash (MVP-2, 1–2 hafta)

| Vazifa | Natija |
|---|---|
| `audit_log` hamma amalga ulanishi | Har bir admin amali yoziladi |
| `result_versions` + qayta baholash oqimi | `b` o'zgarsa yangi versiya (eski qoladi) |
| `notification_outbox` + worker | Natija ishonchli yetkaziladi |
| Soft delete siyosati | `/exams` o'rniga `/forms` (soft delete) |
| **Chiqish mezoni** | Audit hisoboti: kim, qachon, nimani o'zgartirgan |

### M5 — PostgreSQL'ga o'tish (2 hafta)

| Vazifa | Natija |
|---|---|
| PG sxemalari (`core`, `stats`, `audit`, `ops`) yaratish | 02-hujjat, 5-bo'lim |
| `tools/migrate_sqlite_to_pg.py` | Ma'lumot ko'chirildi |
| `database/db.py` → `DB_URL` qo'llab-quvvatlashi | SQLite ham, PG ham ishlaydi |
| Yuklama sinovi | 2000 parallel javob |
| **Chiqish mezoni** | Satr sonlari mos, checksum mos, yuklama sinovi o'tdi |

## 4. Ma'lumot ko'chirish xaritasi (M3 backfill)

| Eski (SQLite) | Yangi | Qoida |
|---|---|---|
| `users` | `users` | `ALTER TABLE users ADD COLUMN role` (default `'student'`); adminlar `role='admin'` |
| `exams.title` | `forms.title` | 1:1 |
| `exams.test_code` | `forms.test_code` | 1:1 (unikal) |
| `exams.total_questions` | `forms.total_questions`, `form_versions.total_questions` | 1:1 |
| `exams.answer_key` | `form_versions.answer_key` | `form_versions.version_no = 1`, `status='retired'` |
| `exams.answer_key` | `form_items` satrlari | `answer_key.parse_answer_key()` → har bir pozitsiya: `position`, `correct_option`, `part` |
| `exams.start_time/end_time/result_time` | `exam_sessions` (bitta sessiya) | 1:1, `status` hisoblanadi |
| `exams.graded_at` | `exam_sessions.graded_at` | 1:1 |
| `exams.difficulty_logits` | `item_parameters` (`source='legacy_expert'`) | ⚠️ Tarixiy qiymat, `status='retired'` — **yangi tizimda ishlatilmaydi** |
| `exams.created_by` | `forms.created_by` | 1:1 |
| `exams.answer_key` | `answer_key_imports` | `source='bot_wizard'`, `raw_text = answer_key`, `status='ok'` |
| `user_answers` (har bir satr) | `attempts` (1 satr) | `status='graded'` (agar `theta` bor bo'lsa) aks holda `'submitted'` |
| `user_answers.theta/scaled_score/raw_score` | `attempts` + `scoring_snapshots` | `engine_version='legacy'`, `computed_by='system'` |
| `user_answers.submitted_at` | `attempts.submitted_at` | 1:1 |
| `user_answers.submitted_answers` | `responses` (`N` satr) | `answer_key.parse_submitted()` → har biri: `revision=1`, `is_current=1`, `source='import'` |
| `questions`, `test_results` (eski mashq rejimi) | **arxiv** | O'zgartirilmaydi (mavjud `LEGACY_MODULES` siyosati) |
| `solutions` | `solutions` | O'zgartirilmaydi (yechimlar modeli saqlanadi) |

### Backfill namunasi (SQL + Python)

```sql
-- 1) Formalar (har bir eski imtihon → forma)
INSERT INTO forms (title, test_code, total_questions, options_count, created_by, created_at)
SELECT e.title, e.test_code, e.total_questions, 4, e.created_by, e.created_at
  FROM exams e
 WHERE e.test_code NOT IN (SELECT test_code FROM forms WHERE deleted_at IS NULL);

-- 2) Form versiyalari (kalit snapshot'i)
INSERT INTO form_versions (form_id, version_no, answer_key, total_questions,
                           status, created_by, created_at)
SELECT f.form_id, 1, e.answer_key, e.total_questions, 'retired', e.created_by, e.created_at
  FROM exams e JOIN forms f ON f.test_code = e.test_code;

-- 3) Sessiyalar
INSERT INTO exam_sessions (form_id, title, start_time, end_time, result_time,
                           status, graded_at, created_by)
SELECT f.form_id, f.title, e.start_time, e.end_time, e.result_time,
       CASE WHEN e.graded_at IS NOT NULL THEN 'graded' ELSE 'closed' END,
       e.graded_at, e.created_by
  FROM exams e JOIN forms f ON f.test_code = e.test_code;

-- 4) Eski logitlarni ARXIVGA (faqat audit uchun)
INSERT INTO item_parameters (form_item_id, b_value, source, status, valid_to, created_by)
SELECT fi.form_item_id, j.value, 'legacy_expert', 'retired', :now, e.created_by
  FROM exams e
  JOIN forms f        ON f.test_code = e.test_code
  JOIN form_versions fv ON fv.form_id = f.form_id AND fv.version_no = 1
  JOIN form_items fi  ON fi.form_version_id = fv.form_version_id
  JOIN json_each(e.difficulty_logits) j ON CAST(j.key AS INTEGER) = fi.position - 1;
```

```python
# 5) Kalitni pozitsiyalarga yoyish va javoblarni item-level ko'chirish
from services import answer_key

for exam, form_version_id in old_exams():
    key = answer_key.parse_answer_key(exam.answer_key, exam.total_questions)
    for position, letter in enumerate(key, start=1):
        insert_form_item(form_version_id, position, "", letter, options_count=4)

for submission in old_submissions():
    attempt_id = insert_attempt(submission)                # user_answers → attempts
    given = answer_key.parse_submitted(submission.submitted_answers, total)
    for position, letter in enumerate(given, start=1):
        insert_response(attempt_id, form_item_id(position), position, letter,
                        source="import", revision=1, is_current=1)
```

> **Diqqat:** `difficulty_logits` **yangi tizimda ishlatilmaydi**. U
> `item_parameters` ga `source='legacy_expert'`, `status='retired'` bilan
> yoziladi — faqat "eski tizimda shunday edi" ma'lumoti sifatida (audit).
> Yangi `b` qiymatlari faqat statistika asosida hisoblanadi.

## 5. SQLite → PostgreSQL ko'chirish (M5)

### 5.1. Ko'chirish tartibi (to'xtash vaqti ~15 daqiqa)

```
0. E'lon: "Texnik xizmat 10:00–10:20" (Telegram kanalga post)
1. Zaxira: data/backup/math_bot_<sana>.db  (+ pg_dump, agar PG'da ma'lumot bo'lsa)
2. Yozishni to'xtatish: WEBAPP_READONLY=1 (yangi javob: 503 + "texnik xizmat")
3. tools/migrate_sqlite_to_pg.py --dry-run   → hisobot: qaysi jadvaldan nechta satr
4. tools/migrate_sqlite_to_pg.py             → ko'chirish (batch 5000)
5. Validatsiya (6-bo'lim)                    → satr soni + checksum
6. .env da DB_URL ni PG ga o'tkazish         → python main.py
7. Smoke test: test kodi → javob → yakunlash → natija (sinov akkaunti)
8. WEBAPP_READONLY=0 → oddiy ishlash
9. SQLite fayli faqat o'qish uchun 30 kun saqlanadi, keyin arxivga
```

### 5.2. Ko'chirish tartibi (FK ga zid emas!)

```python
COPY_ORDER = [
    # 1. Identity va lug'atlar
    "users", "subjects", "exam_programs", "topics", "tags",
    # 2. Question Bank
    "items", "item_versions", "item_tags", "item_status_history",
    # 3. Struktura va formalar
    "exam_structures", "exam_structure_sections",
    "forms", "form_versions", "form_items",
    # 4. O'tkazish va javoblar
    "exam_sessions", "attempts", "attempt_attributes", "responses", "attempt_events",
    # 5. Statistika
    "item_parameter_sets", "item_parameters", "item_statistics",
    "scoring_snapshots", "result_versions",
    "calibration_runs", "calibration_run_items", "anchor_items", "equatings",
    # 6. Audit va ops
    "audit_log", "notification_outbox", "app_settings", "staff_roles",
    "answer_key_imports", "schema_migrations",
]
```

### 5.3. Konversiya qoidalari (batafsil)

| SQLite | PostgreSQL | Diqqat |
|---|---|---|
| `TEXT` vaqt `"2026-03-12T07:00:11+00:00"` | `timestamptz` | `datetime.fromisoformat()`; `NULL` → `NULL` |
| `TEXT` JSON `"[0.0, 1.2]"` | `jsonb` | `json.loads()`; buzuq → `'[]'`/`'{}'` + ogohlantirish ro'yxati |
| `INTEGER` 0/1 | `boolean` | `bool(value)` |
| `REAL` | `numeric(8,4)` | `round(val, 4)` — aniqlik uchun |
| `INTEGER PK AUTOINCREMENT` | `bigint GENERATED ALWAYS AS IDENTITY` | **`OVERRIDING SYSTEM VALUE`** bilan INSERT (id saqlanadi) |
| `NULL` `item_version_id` (MVP-0 davri) | `NULL` | Ruxsat etilgan (`CHECK` bittasi bo'lishini talab qiladi) |
| Buzuq FK (yetim satr) | — | `rejects_<jadval>.csv` ga yoziladi, ko'chirilmaydi, admin ko'rigi |

```sql
-- IDENTITY'ni qo'lda qiymat bilan to'ldirish
INSERT INTO core.users (user_id, full_name, role, created_at)
OVERRIDING SYSTEM VALUE
VALUES (%s, %s, %s, %s)
ON CONFLICT (user_id) DO NOTHING;

-- Ko'chirishdan keyin ketma-ketlikni tiklash
SELECT setval(pg_get_serial_sequence('core.forms', 'form_id'),
              COALESCE((SELECT MAX(form_id) FROM core.forms), 0) + 1, false);
```

### 5.4. `database/db.py` o'zgarishi (ikki bazani qo'llash)

```python
# .env:  DB_URL=postgresql://app_rw:***@localhost:5432/milliy_sertifikat
#        DB_URL bo'sh bo'lsa → hozirgi SQLite yo'li (orqaga moslik)

if config.DB_URL:
    import asyncpg                     # faqat PG ishlatilganda o'rnatiladi
    # `?` → `$1, $2` konvertatsiyasi yupqa qatlamda (repository'lar o'zgarmaydi)
else:
    import aiosqlite                   # mavjud yo'l
```

> Repository'lar **o'zgarmaydi** — SQL sintaksisi `?` bilan yozilgan
> (SQLite uslubi), PG adapteri ularni `$n` ga o'giradi.

## 6. Validatsiya (chiqish mezoni)

```sql
-- 1) Satr sonlari (SQLite va PG'da bir xil bo'lishi shart)
SELECT 'users' AS t, COUNT(*) FROM users UNION ALL
SELECT 'forms', COUNT(*) FROM forms UNION ALL
SELECT 'form_items', COUNT(*) FROM form_items UNION ALL
SELECT 'exam_sessions', COUNT(*) FROM exam_sessions UNION ALL
SELECT 'attempts', COUNT(*) FROM attempts UNION ALL
SELECT 'responses', COUNT(*) FROM responses;

-- 2) Asosiy ko'rsatkichlar checksum'i (eski va yangi bazada bir xil)
SELECT COUNT(*) AS urinishlar, SUM(raw_score) AS xom_ball,
       ROUND(AVG(theta), 4) AS ort_theta
  FROM attempts WHERE deleted_at IS NULL;

-- 3) Har bir urinishda javob satrlari soni savollar soniga teng bo'lishi kerak
SELECT a.attempt_id, COUNT(r.response_id) AS javoblar, fv.total_questions
  FROM attempts a
  JOIN form_versions fv ON fv.form_version_id = a.form_version_id
  LEFT JOIN responses r ON r.attempt_id = a.attempt_id AND r.is_current = 1
 GROUP BY a.attempt_id, fv.total_questions
HAVING COUNT(r.response_id) <> fv.total_questions;
-- ↑ bo'sh natija → ko'chirish to'g'ri
```

**Smoke testlar (qo'lda, 10 daqiqa):**

| # | Test | Kutilgan |
|---|---|---|
| 1 | Eski imtihon natijasi ochiladi | θ va ball eski bilan **bir xil** |
| 2 | Yangi test kodi → javob → yakunlash | `responses` satrlari yaratildi |
| 3 | Refresh → javoblar tiklandi | Yo'qolmadi |
| 4 | `end_time` → baholash | θ hisoblandi |
| 5 | Kalibrlash (`dry_run=true`) | `p`, `b` chiqadi, xatolik yo'q |
| 6 | Audit log | Amallar yozilgan |

## 7. Orqaga qaytish (rollback)

| Bosqich | Rollback |
|---|---|
| M1–M4 (SQLite) | Yangi jadvallar **bo'sh** → `DROP TABLE` (yoki qoldirish — zarari yo'q); eski jadvallar tegilgani yo'q |
| M3 backfill | `audit_log` dagi `source='migration'` yozuvlari bo'yicha teskari o'chirish yoki zaxiradan tiklash |
| M5 (PG) | `.env` da `DB_URL` ni bo'shatish → SQLite'ga qaytish (fayl 30 kun turadi); PG'dagi yangi yozuvlar `tools/export_pg_delta.py` bilan olinadi |

**Qoida:** hech bir bosqichda mavjud jadval **o'chirilmaydi/o'zgartirilmaydi** —
faqat `ALTER TABLE ... ADD COLUMN` (orqaga qaytarish oson bo'lishi uchun).

## 8. Xatarlar va choralar

| Xatar | Ehtimol | Ta'sir | Chora |
|---|---|---|---|
| Yangi ekran davomida Mini App buziladi | O'rta | Yuqori | Yangi varag'i (`?sheet=1`) **fon** rejimida, eski oqim default |
| `1A2B3C4D` → item-level o'tishda xato | O'rta | Yuqori | `parse_submitted()` (mavjud, testlangan) + backfill validatsiyasi |
| Buzuq kalit (harf yetishmaydi) | Yuqori | O'rta | `answer_key_imports.status='partial'` + admin ogohlantirish |
| `b` noto'g'ri hisoblanib natijalar o'zgaradi | O'rta | Yuqori | Snapshot scoring + `result_versions` (eski natija tegilmaydi) + `dry_run` |
| PostgreSQL'da FK yetim satrlar | O'rta | O'rta | `rejects_*.csv` + qo'lda tozalash |
| Yuklama cho'qqisi (1000+ bir vaqtda) | Yuqori | Yuqori | `responses` partition, indekslar, connection pool, rate limit |
| `item_ref` to'ldirilmasa statistika bo'linadi | Yuqori | O'rta | `reuse_items` + `content_hash` solishtirish + `/forms` hisoboti |
| Migratsiya ikki marta ishga tushishi | O'rta | O'rta | `schema_migrations` + idempotent SQL |
| Telegram WebView eski versiyasi | O'rta | O'rta | Sof JS (build yo'q), `themeParams` fallback, `localStorage` mavjudligini tekshirish |

## 9. Migratsiya vaqt jadvali (07-hujjat roadmap bilan bog'liq)

| Hafta | Bosqich | Natija |
|---|---|---|
| 1 | M0 | Migratsiya runner, zaxira |
| 2–3 | M1 | MVP-0 jadvallari (11 ta) |
| 4–5 | M2 | `/api/v2/*` + kartochkali javoblar varag'i |
| 6–7 | M3 | Question Bank, `difficulty.py`, `/new_form` |
| 8 | M3 | Backfill (eski imtihonlar ko'chirildi) |
| 9–10 | M4 | Audit, `result_versions`, `notification_outbox` |
| 11–12 | M5 | PostgreSQL, yuklama sinovi, pilot sessiya |
