# 01 — Umumiy arxitektura

## 1. Maqsad va qamrov

**Maqsad.** O'zbekiston **Milliy Sertifikat** testlarini raqamli o'tkazish:
test **PDF** ko'rinishida Telegram kanalda tarqatiladi, o'quvchi savollarni
qog'ozdan ishlaydi, javoblarni **Telegram Mini App** da A/B/C/D kartochkalari
orqali belgilaydi, tizim esa har bir savolning **qiyinchiligini o'zi**
hisoblab boradi va natijalarni Rasch (1PL IRT) bo'yicha baholaydi.

### Qamrovga kiradi (IN SCOPE)

* Test kodi → sessiya → javoblar varag'i → baholash → natija → tahlil.
* **Question Bank**: item, item version, item status, item tags, statistika.
* **Item-level response storage**: har bir savolga alohida javob, append-only tarix.
* **Avtomatik qiyinchilik hisoblash**: `p → b = ln((1−p)/p)` (03-hujjat).
* **Audit**: soft delete, audit log, result versioning, immutable history.
* Rasch kalibrlash / anchor items / equating uchun **tayyor** sxema.

### Qamrovga KIRMAYDI (OUT OF SCOPE — ataylab)

| Chiqarilgan | Sabab |
|---|---|
| Listening / Speaking / Writing / Reading bo'limlari | Milliy Sertifikat formati emas |
| Adaptive (CAT) test — savolni `θ` ga moslab tanlash | Savollar PDF da, oldindan belgilangan |
| SAT/GMAT `verbal/quantitative`, CAT `sections`, essay scoring | Boshqa tizimlar |
| Savol matnini Web App'da ko'rsatish | Savollar PDF da; matn bazaga yuklanmaydi |
| O'qituvchi tomonidan `b`, `a`, logit, Rasch parametrlari kiritish | **Ta'qiqlangan** (03-hujjat) |
| 2PL/3PL, polytomous (graded response) modellari | 1PL (Rasch) yetarli; sxema kengaytirishga tayyor |

## 2. Yuqori darajadagi arxitektura

```
                    ┌──────────────────────────────────────────────┐
   PDF (kanal) ───► │  Telegram kanal (testlar tarqatiladi)        │
                    └──────────────────────────────────────────────┘
                                        │ (o'quvchi PDF ni ishlaydi)
                                        ▼
   ┌───────────────┐   initData    ┌──────────────────────┐
   │ Telegram Bot  │──────────────►│  Web App (Mini App)  │
   │  (aiogram 3)  │  WebAppButton │  HTML/CSS/JS SPA     │
   └───────┬───────┘               └──────────┬───────────┘
           │                                  │  X-Init-Data (HMAC)
           │                                  ▼
           │                       ┌──────────────────────┐
           │                       │   Web API (aiohttp)  │
           │                       │  /api/v2/*  JSON     │
           │                       └──────────┬───────────┘
           │                                  │
           │      ┌───────────────────────────┼──────────────────────────┐
           ▼      ▼                           ▼                          ▼
   ┌────────────────────┐        ┌──────────────────────┐      ┌────────────────────┐
   │  Bot service       │        │  Scoring service     │      │ Calibration worker │
   │  (form yaratish,   │        │  (snapshot scoring,  │      │ (p→b hisoblash,    │
   │   natija yuborish) │        │   Rasch MLE θ)       │      │  freeze, drift)    │
   └─────────┬──────────┘        └──────────┬───────────┘      └─────────┬──────────┘
             │                              │                            │
             └──────────────────────────────┼────────────────────────────┘
                                            ▼
                          ┌───────────────────────────────────┐
                          │  PostgreSQL  (MVP: SQLite)        │
                          │  core | stats | audit | ops       │
                          └───────────────────────────────────┘
```

### Jarayonlar (runtime process'lari)

| Jarayon | Vazifasi | Holati |
|---|---|---|
| `bot` | aiogram long polling: `/start`, form yaratish ustasi, natijalarni yuborish | mavjud (`main.py`) |
| `web` | aiohttp: Mini App statik fayllari + `/api/v2/*` | mavjud (`web/server.py`) |
| `grading_worker` | `end_time` tugagan sessiyalarni baholash (raw + θ + scaled) | mavjud (`services/grading.py`) |
| `calibration_worker` | **yangi**: statistika yig'ish + `b` ni avtomatik hisoblash | qo'shiladi (03-hujjat) |
| `outbox_worker` | natija/xabar yuborishni ishonchli yetkazish (retry) | qo'shiladi |

> MVP'da hammasi **bitta jarayonda** (asinxron vazifalar sifatida) ishlaydi —
> hozirgi `main.py` arxitekturasi saqlanadi. PostgreSQL'ga o'tgach, kerak
> bo'lsa `grading` va `calibration` alohida xizmatlarga ajratiladi.

## 3. Asosiy oqimlar

### 3.1. O'qituvchi: test yaratish (o'qituvchi `b` kiritmaydi!)

```
Admin: /new_form
  1) Test nomi                       ("Milliy sertifikat — Matematika, 1-variant")
  2) Test kodi                       ("MS-MATH-2603")   ← o'quvchi kiritadigan kod
  3) Fan / yo'nalish                 (Matematika, A-daraja)
  4) Savollar soni + A/B qismli savollar (masalan 40, 36a/36b)
  5) Javoblar kaliti                 ("1A2B3C4D…" yoki "1A 2B 3C")
  6) Boshlanish / tugash / natija vaqti
  ─────────────────────────────────────────────────────────────
  ✗ Qiyinchilik (logit) SO'RALMAYDI
  ✗ Rasch parametrlari SO'RALMAYDI
  ─────────────────────────────────────────────────────────────
  → forms + form_versions + form_items (barcha savol b=0.0, provisional)
  → exam_sessions (vaqt oynasi)
```

Kalit kiritilganda tizim avtomatik ravishda:

1. `form_items` — har bir pozitsiya uchun item slot yaratadi (`1..N`, `36a`, `36b`);
2. mavjud Question Bank'dan **item_version** ni moslashtiradi:
   * agar shu formada `item_ref` (manba belgisi) ko'rsatilgan bo'lsa — o'sha itemga bog'lanadi;
   * aks holda **yangi item** + **item_version** yaratiladi (kalit bilan);
3. har bir item uchun `item_parameters` satri yoziladi: `b_value = 0.0`,
   `b_se = NULL`, `source = 'default'`, `status = 'provisional'`.

### 3.2. O'quvchi oqimi (Telegram → Web App → javoblar)

```
/start → Ism familiya → [📝 Javoblarni belgilash] → Mini App
Mini App: test kodi → sessiya tekshiriladi → javoblar varag'i (kartochkalar)
          → har bir belgilash autosave (append-only revision)
          → "Yakunlash" → attempts.status = 'submitted'
          → natija vaqti kelgach: botga + ilovaga natija
```

Batafsil UI talablari — 04-hujjatda.

### 3.3. Javob saqlash (autosave, refresh'da yo'qolmaydi)

```
[o'quvchi A ni bosdi]
   → localStorage'ga darhol yozish (offline-first)
   → 700 ms debounce → PUT /api/v2/attempts/{id}/responses
        body: { items:[{position:1, part:"", option:"A", client_seq:41}], revision: 12 }
   → server: yangi `responses` satri (revision = 13, is_current = true),
             eskisi is_current = false (superseded_by = yangi response_id)
   → javob: { ok:true, revision:13, saved_at:… }
[tarmoq yo'q] → queue.js navbatga qo'yadi → tarmoq kelgach qayta yuboradi (idempotent)
[refresh]     → GET /api/v2/attempts/{id}/state → server revision + barcha javoblar
```

**Muhim:** `responses` jadvali **append-only**. `UPDATE`/`DELETE` yo'q.
Shu sababli javoblar tarixi (kim, qachon, nimani o'zgartirgan) to'liq saqlanadi.

### 3.4. Baholash (snapshot scoring)

```
end_time o'tdi → grading_worker:
  1) attempts (submitted) ro'yxati
  2) responses (is_current) → u_j ∈ {0,1}
  3) θ = MLE (services/rasch.py, mavjud kod) — item_parameter_set snapshot'i bo'yicha
  4) scoring_snapshots satri: { θ, SE, raw, scaled, form_version_id, parameter_set_id,
                                engine_version, computed_at }
  5) attempts.status = 'graded'
result_time keldi → result_versions satri (version_no = 1) → bot + Mini App
b qiymatlari keyin yangilansa → YANGI scoring_snapshot + result_version (v2),
                                 eski natija O'ZGARMAYDI (immutability)
```

### 3.5. Qiyinchilikni avtomatik hisoblash (asosiy yangilik)

```
[har sessiya baholangach yoki kunlik cron]
  calibration_worker:
   1) SQL agregatsiya: item_version × davr → n_presented, n_answered, c (to'g'ri)
   2) p  = c / n_presented            (javobsiz = noto'g'ri, θ hisoblash bilan bir xil)
   3) p̂ = Jeffreys tekislash: (c + 0.5) / (n + 1)      ← p = 0 yoki 1 muammosi
   4) b_raw = ln((1 − p̂) / p̂)
   5) (ixtiyoriy) taxminga tuzatish: p_c = (p̂ − 1/k)/(1 − 1/k)
   6) guruhga moslash (mean-mean): b_adj = b_raw − θ̄_guruh
   7) shrinkaj (empirik Bayes): b_new = w·b_obs + (1−w)·b_prior,  w = n/(n+K)
   8) SE(b) = 1 / sqrt(n_eff · p̂ · (1 − p̂))
   9) flag'lar: insufficient_n / key_suspect / too_easy / drift
  10) item_statistics (tarix) + item_parameters (operatsion b, versiyalangan)
```

To'liq matematika, konstantalar va chekka holatlar — **03-hujjatda**.

## 4. Ma'lumotlar modeli — yuqori daraja

```
 subjects ──┐
            ├─► exam_programs ──► exam_structures ──► exam_structure_sections
 topics ────┘        │
                     ▼
  ┌─────────────────────────── QUESTION BANK ───────────────────────────┐
  │  items ──► item_versions ──► item_tags / item_status_history        │
  │                │                                                    │
  │                ├──► item_statistics   (n, p, b, SE, flag, davr)     │
  │                ├──► item_parameters   (operatsion b, versiyalangan) │
  │                └──► anchor_items      (qotirilgan b — equating)     │
  └─────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
  forms ──► form_versions ──► form_items ──┐
   (test kodi)   (kalit snapshot)          │
                                           ▼
  exam_sessions ──► attempts ──► responses (append-only, item-level)
                       │             │
                       │             └─► attempt_response_current (VIEW)
                       ├──► attempt_events (immutable timeline)
                       ├──► scoring_snapshots ──► result_versions
                       └──► attempt_attributes (ixtiyoriy: hudud, til)

  item_parameter_sets ──► item_parameters     (snapshot scoring uchun "kalit")
  calibration_runs ──► calibration_run_items  (har bir kalibrlash tarixi)
  equatings                                   (formalar orasidagi bog'lash)
  audit_log / notification_outbox / schema_migrations
```

**Uchta "snapshot" tushunchasi** (bir-biriga aralashtirmaslik kerak):

| Snapshot | Nima qotiriladi | Nega kerak |
|---|---|---|
| `form_versions` | Javob kaliti va savollar tartibi | Kalit keyin tuzatilsa, eski urinishlar buzilmaydi |
| `item_parameter_sets` | `b` qiymatlari to'plami | `b` yangilanganda eski natija o'zgarmasligi uchun |
| `scoring_snapshots` | Hisoblash natijasi (θ, SE, raw) | Natijani takror ishlab chiqarish (reproducibility) |

## 5. Texnologiya stack

| Qatlam | MVP (hozir) | Maqsad (1 yil) | Izoh |
|---|---|---|---|
| Til | Python 3.10+ | o'zgarmaydi | `requirements.txt` minimal |
| Bot | aiogram 3.x | o'zgarmaydi | mavjud router tuzilishi |
| HTTP | aiohttp | aiohttp + gunicorn/uvicorn | aiogram bilan bir xil ekosistema |
| Baza | SQLite (`aiosqlite`) | **PostgreSQL 16** | 02-hujjatda ikkala DDL |
| Migratsiya | o'zimizning `migrations/*.sql` runner | o'sha (yoki Alembic) | yangi kutubxona qo'shmaymiz |
| Frontend | HTML/CSS/JS (build yo'q) | o'zgarmaydi | Telegram WebApp SDK + Chart.js |
| Ilmiy hisob | sof Python `math` | `numpy` (ixtiyoriy, kalibrlash uchun) | MVP'da kerak emas |
| Navbat | jadval-asosidagi `notification_outbox` | Redis/RQ yoki pg-boss | MVP'da jadval yetarli |
| Deploy | `python main.py` | systemd + nginx + PostgreSQL + TLS | VPS'da |

**Nega PostgreSQL'ga o'tish kerak bo'ladi:** bir vaqtda ko'p o'quvchi javob
yozishi (`responses` jadvali tez o'sadi: 1 mln urinish × 40 savol = 40 mln satr),
parallel kalibrlash so'rovlari, `jsonb` + partial index + partitioning.

## 6. Xavfsizlik

| Xavf | Chora |
|---|---|
| Boshqa odam nomidan so'rov | `X-Init-Data` HMAC-SHA256 tekshiruvi (`services/webapp_auth.py`, mavjud) + `auth_date` muddati |
| Kalitning oshkor bo'lishi | `answer_key` va `b` **hech qachon** API javobida qaytarilmaydi; hisoblash faqat serverda |
| Natijani muddatdan oldin bilish | θ hisoblash `end_time` dan keyin; natija `result_time` dan keyin (`result_versions.visible_from`) |
| Javobni boshqa birovga almashtirish | `attempts.user_id` serverda `initData` dan olinadi (so'rovdan emas) |
| Takroriy/parallel yozish | `client_seq` + `revision` (optimistik qulflash); eski revision → `409` |
| So'rovni ko'paytirib tashlash (flood) | Har bir foydalanuvchi uchun rate limit (PUT: 30/daq) |
| Admin amalini yashirish | `audit_log` (before/after JSON), faqat `role='admin'` |
| Ma'lumotni o'chirib yuborish | **Soft delete** (`deleted_at`), `responses`/`audit_log` da `DELETE` ta'qiqlanadi |
| SQL injection | Faqat parametrlangan so'rovlar (`?`), satr birlashtirish yo'q |
| Bazani o'g'irlash | PG'da shifrlash, kunlik `pg_dump` + 30 kun retensiya, faqat ichki tarmoq |

**Rollar (PostgreSQL):**

| Rol | Huquq |
|---|---|
| `app_rw` | `core` sxemasida SELECT/INSERT/UPDATE (soft delete), `responses`/`audit_log` da faqat INSERT/SELECT |
| `app_worker` | `stats` sxemasida yozish (statistika, kalibrlash) |
| `analyst_ro` | faqat SELECT (hisobot, eksport) |
| `migrator` | DDL (faqat migratsiya paytida) |

## 7. Unumdorlik va kuzatuv

* **Indekslar:** `responses (attempt_id, form_item_id) WHERE is_current`,
  `item_statistics (item_version_id, computed_at DESC)`,
  `attempts (session_id, status)`, `audit_log (entity_type, entity_id, created_at DESC)`.
* **Partitioning (PG):** `responses` — `RANGE (created_at)` yoki
  `LIST (session_id)` bo'yicha; `audit_log` — oylik `RANGE`.
* **Keshlash:** `form_items` + `item_parameters` snapshot'i sessiya boshida
  bir marta o'qilib, urinish davomida xotirada saqlanadi.
* **Kuzatuv:** strukturaviy log (`LOG_LEVEL`), har bir so'rovga `request_id`,
  `/api/health` (baza + worker holati), `notification_outbox` navbat uzunligi,
  `calibration_runs.convergence` monitoringi.
* **Zaxira:** SQLite — kunlik fayl nusxasi; PG — `pg_dump` + WAL arxivlash.

## 8. Muhitlar va konfiguratsiya

| Muhit | Baza | Maqsad |
|---|---|---|
| `dev` | SQLite `data/dev.db` | Lokal ishlab chiqish, `WEBAPP_DEV_MODE=1` |
| `test` | SQLite vaqtinchalik fayl | `tests/test_*.py` (mavjud uslub) |
| `staging` | PostgreSQL nusxa | Yuklama sinovi, kalibrlash mashqi |
| `prod` | PostgreSQL + TLS | Haqiqiy Milliy Sertifikat sessiyalari |

`.env` orqali boshqariladigan yangi o'zgaruvchilar (`config.py`ga qo'shiladi):

| O'zgaruvchi | Default | Ma'nosi |
|---|---|---|
| `DB_URL` | — | PostgreSQL ulanish satri (bo'sh bo'lsa SQLite) |
| `CALIBRATION_INTERVAL` | `3600` | Kalibrlash sikli, sekund |
| `CALIBRATION_MIN_N` | `30` | `b` ni yangilash uchun minimal javob soni |
| `CALIBRATION_K_SHRINK` | `30` | Shrinkaj konstantasi `K` (03-hujjat) |
| `CALIBRATION_GUESSING` | `auto` | `auto` = `1/variantlar_soni`, yoki qat'iy son |
| `CALIBRATION_SE_FREEZE` | `0.30` | `frozen` holatga o'tish chegarasi |
| `RATE_LIMIT_PER_MINUTE` | `30` | Bir foydalanuvchi uchun PUT so'rovlar chegarasi |

## 9. Modul tuzilishi (mavjud loyihaga qo'shiladigan fayllar)

Kod **hozirgi konvensiyalar** bo'yicha yoziladi: handler'lar SQL yozmaydi,
repository metodlarini chaqiradi; biznes-logika `services/` da; matnlar
`texts.py` da; testlar `tests/test_*.py` (pytest talab qilinmaydi).

```
database/
  db.py                 # + yangi jadvallar (SCHEMA_SQL) yoki migrations runner
  models.py             # + Item, ItemVersion, Form, FormVersion, FormItem,
                        #   ExamSession, Attempt, Response, ItemStatistic, ...
  repository.py         # + ItemRepository, FormRepository, SessionRepository,
                        #   AttemptRepository, ResponseRepository, StatsRepository
  migrations/           # YANGI: 001_init.sql, 002_question_bank.sql, ...
services/
  rasch.py              # mavjud — θ MLE (o'zgarmaydi)
  difficulty.py         # YANGI: p → b hisoblash, tekislash, shrinkaj, SE, flag'lar
  calibration.py        # YANGI: davr bo'yicha yig'ish, kalibrlash sikli, freeze
  scoring.py            # YANGI: snapshot scoring (attempt → θ, raw, scaled)
  answer_key.py         # mavjud — kalit tahlili (o'zgarmaydi)
  exam_service.py       # mavjud — vaqt/validatsiya
  grading.py            # mavjud — fon baholash (scoring.py dan foydalanadi)
web/
  api.py                # mavjud — /api/* (MVP davomida saqlanadi)
  api_v2.py             # YANGI: /api/v2/* (attempt, responses, autosave)
handlers/
  admin_form.py         # YANGI: /new_form ustasi (logit so'ramaydi!)
  admin_stats.py        # YANGI: /item <n>, /calibration, /freeze
webapp/js/
  sheet.js              # YANGI: javoblar varag'i (kartochkalar + autosave)
tests/
  test_difficulty.py    # YANGI: p→b matematikasi, chekka holatlar
  test_calibration.py   # YANGI: kalibrlash sikli, freeze, drift
  test_responses.py     # YANGI: append-only javoblar, revision, idempotentlik
```

## 10. Arxitektura qarorlari (ADR — qisqa jurnal)

| # | Qaror | Sabab / alternativa |
|---|---|---|
| ADR-1 | Savol matni saqlanmaydi, faqat `position` + `correct_option` | Talab: savollar PDF da. Alternativa (matnni bazaga yozish) rad etildi |
| ADR-2 | `b` ni tizim hisoblaydi, o'qituvchi kiritmaydi | Talab: «o'qituvchi b kiritmaydi» |
| ADR-3 | `responses` append-only (revision'li) | Audit talabi: immutable response history |
| ADR-4 | Test kodi `forms` da, vaqt oynasi `exam_sessions` da | Bir formani qayta-qayta ishlatish → ko'proq statistika → tezroq kalibrlash |
| ADR-5 | `b` qiymati `item_parameters` da versiyalangan (parametrlar to'plami bilan) | Snapshot scoring + equating'ga tayyorlik |
| ADR-6 | MVP: SQLite, keyin PostgreSQL (bir xil mantiqiy sxema) | Mavjud loyiha minimal bog'liqlikda; ko'chirish rejasi 05-hujjatda |
| ADR-7 | Rasch hisobi sof Python'da (`math`) | `numpy/scipy` bog'liqligini qo'shmaslik; 1PL uchun yetarli |
| ADR-8 | Javob kaliti `form_versions` snapshot'ida | Kalit tuzatilganda eski urinishlar buzilmasligi (audit) |

