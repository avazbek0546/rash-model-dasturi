# 07 — Yo'l xaritasi (3 oy va 1 yil)

## Umumiy tamoyil

Har bir bosqich **mustaqil foyda** beradi va oldingisini buzmaydi:

```
1-oy:  PDF → Web App javoblari (item-level, autosave)      ← foydalanuvchi ko'radi
2-oy:  Avtomatik qiyinchilik hisoblash + admin statistikasi ← ilmiy qiymat
3-oy:  PostgreSQL + pilot + audit to'liq                    ← ishonch va masshtab
4–12-oy: Rasch kalibrlash, equating, DIF, milliy daraja     ← aniqlik va rasmiylik
```

## 1. Keyingi 3 oy (12 hafta)

### Sprint 1–2 (1–3 hafta) — Poydevor (M0 + M1)

| Ish | Natija |
|---|---|
| `database/migrations/` + `migrate.py` runner | `schema_migrations` ishlaydi |
| MVP-0 jadvallari (11 ta) + view + trigger | `responses` append-only himoyalangan |
| `models.py` / `repository.py` kengaytmasi | `AttemptRepository`, `ResponseRepository` |
| `audit_log` infratuzilmasi | Eski amallar ham yozila boshlaydi |
| **Deliverable** | Baza yangi sxemaga o'tdi, eski oqim ishlab turibdi |
| **KPI** | `python main.py` xatosiz; mavjud 8 ta test o'tadi |

### Sprint 3–4 (4–6 hafta) — Yangi javoblar varag'i (M2)

| Ish | Natija |
|---|---|
| `web/api_v2.py` (6 endpoint) | Autosave, idempotentlik, `409` boshqaruvi |
| `webapp/js/sheet.js` + `index.html` (`tab-sheet`) | Kartochkali UI (A/B/C/D), progress, timer |
| `localStorage` + navbat + `visibilitychange` | Refresh/uzilishda javob yo'qolmaydi |
| `services/scoring.py` (snapshot scoring) | `attempts` → θ, raw, scaled, `b_checksum` |
| **Deliverable** | O'quvchi `1A2B3C4D` yozmasdan javob belgilaydi |
| **KPI** | Javob yo'qolish hodisasi **0**; 40 savolga belgilash `< 3 daqiqa` |

### Sprint 5–6 (7–9 hafta) — Question Bank va avtomatik qiyinchilik (M3)

| Ish | Natija |
|---|---|
| `items`, `item_versions`, `item_parameter_sets` | Item versiyalash ishlaydi |
| `services/difficulty.py` (`p → b`, tekislash, shrinkaj) | `test_difficulty.py` (20 test) yashil |
| `services/calibration.py` + fon vazifasi | Kalibrlash avtomatik ishga tushadi |
| `handlers/admin_form.py` (`/new_form` — logitsiz) | O'qituvchi `b` kiritmaydi ✅ |
| `handlers/admin_stats.py` (`/item`, `/hardest`, `/calibration`) | Admin statistikani ko'radi |
| **Deliverable** | 2-sessiyadan keyin `b` qiymatlari **o'zi** yangilanadi |
| **KPI** | `item_parameters` yangilanishi avtomatik; `flags` hisoboti admin ko'rigi |

### Sprint 7 (10-hafta) — Backfill va audit (M3 + M4)

| Ish | Natija |
|---|---|
| `MVP2_010_backfill.sql` + `answer_key.parse_*` | Eski imtihonlar yangi sxemada |
| `result_versions` + qayta baholash oqimi | Yangi `b` → yangi natija versiyasi |
| `notification_outbox` + worker | Natija ishonchli yetkaziladi |
| **Deliverable** | Migratsiya validatsiyasi: `SUM(raw_score)` va `AVG(theta)` mos |
| **KPI** | Eski natijalar **o'zgarmagan** (audit talabi) |

### Sprint 8 (11-hafta) — PostgreSQL va yuklama (M5)

| Ish | Natija |
|---|---|
| PG sxemalari + `tools/migrate_sqlite_to_pg.py` | Ko'chirish va validatsiya |
| `DB_URL` qo'llab-quvvatlashi (`asyncpg` adapteri) | Ikki baza rejimi |
| `responses` partition + indekslar + pool | Yuklamaga tayyorlik |
| Yuklama sinovi: 500 → 2000 parallel javob | `p95` javob vaqti `< 400 ms` |
| **Deliverable** | Milliy sessiyaga texnik tayyorlik |
| **KPI** | 500 o'quvchi × 40 savol, xatolik `0%` |

### Sprint 9 (12-hafta) — Pilot va qabul

| Ish | Natija |
|---|---|
| Pilot sessiya (1 hudud, 1 fan, 100–300 o'quvchi) | Real ma'lumot |
| Kalibrlash natijalari hisoboti | `b`, `SE`, `flags` tahlili |
| Xatolar tahlili + tuzatish (retrospektiv) | Barqaror versiya |
| Hujjatlar: admin qo'llanma (o'zbekcha) | O'qituvchi o'rgatish |
| **KPI** | Pilotdan keyin: `b` yangilangan itemlar ≥ 80%, `key_suspect` sabablari aniqlangan |

### 3 oylik natija (acceptance criteria)

| # | Mezon | O'lchov |
|---|---|---|
| 1 | O'quvchi javoblari item-level | `responses` jadvali to'liq |
| 2 | Autosave uzilishsiz | Yo'qolgan javob = 0 |
| 3 | `b` avtomatik hisoblanadi | `item_parameters` tarixi mavjud |
| 4 | O'qituvchi `b`/logit kiritmaydi | `/new_form` da bunday qadam yo'q |
| 5 | Audit to'liq | `audit_log` da har bir admin amali |
| 6 | Yuklama | 500 o'quvchi, xatolik 0% |
| 7 | Natijalar o'zgarmasligi | Eski `scoring_snapshots` o'zgarmagan |

## 2. Keyingi 1 yil (4 chorak)

### Q1 (1–3 oy) — MVP + pilot

| Maqsad | Deliverable | Metrika |
|---|---|---|
| Item-level javoblar va autosave | `/api/v2/*`, `sheet.js` | Yo'qolgan javob 0 |
| Avtomatik `p → b` | `difficulty.py`, kalibrlash fon vazifasi | `b` yangilangan item ≥ 80% |
| Audit va snapshot scoring | `audit_log`, `scoring_snapshots`, `result_versions` | Har bir amal izlanadi |
| PostgreSQL | PG sxemalari + ko'chirish | Yuklama 500 o'quvchi |
| Pilot | 1–3 hudud, 300–1000 o'quvchi | Xatolik 0%, `p95 < 400 ms` |

### Q2 (4–6 oy) — Masshtab va admin tajribasi

| Maqsad | Deliverable | Metrika |
|---|---|---|
| Question Bank to'liq | `topics`, `tags`, `item_tags`, `item_status_history` | 5000+ item |
| Formalar kutubxonasi | `reuse_items`, `content_hash` moslashtirish | Item qayta ishlatish ≥ 60% |
| Admin panel (Mini App) | Statistik dashboard, `/hardest`, grafiklar (Chart.js) | O'qituvchi o'zi tahlil qiladi |
| Eksport/hisobot | CSV/JSON, hudud bo'yicha hisobot | Haftalik hisobot avtomatik |
| Sifat nazorati | `key_suspect`, `omission_high`, `drift` ishlanmalari | Flag'lar 100% ko'rib chiqiladi |
| **Metrika** | 3 hudud, 10 000+ urinish, PG'da barqaror | Uptime ≥ 99% |

### Q3 (7–9 oy) — Rasch kalibrlash va equating

| Maqsad | Deliverable | Metrika |
|---|---|---|
| JMLE moduli | `method='rasch_jmle'` | `±0.2` logit aniqlik (validatsiya) |
| Anchor items | `anchor_items` (locked), tanlash avtomatikasi | Har formada ≥ 20% anchor |
| Equating | `equatings` (mean-mean + anchor) | Formalar orasida taqqoslanadi |
| Fit statistikasi | `infit/outfit MNSQ`, `flagged` oqimi | Fit hisoboti har sessiyadan keyin |
| Yangi `item_parameter_sets` | Klassik → Rasch o'tish | Eski natijalar o'zgarmagan |
| **Metrika** | Klassik va JMLE `r ≥ 0.95`, RMSD ≤ 0.3 | Milliy shkala barqaror |

### Q4 (10–12 oy) — Milliy daraja

| Maqsad | Deliverable | Metrika |
|---|---|---|
| DIF va drift tahlili | Mantel-Haenszel hisobotlari (hudud/til) | Shubhali itemlar qayta ko'riladi |
| Exposure nazorati | Savol "charchashi" monitoringi | Item umri ≥ 5 sessiya |
| Band score / milliy shkala | `equatings` asosida yagona shkala | Yillar bo'yicha taqqoslash mumkin |
| Masshtab | PG partitioning, replikatsiya, monitoring | 20 000+ urinish/sessiya |
| Xavfsizlik auditi | Penetratsiya testi, RLS, backup/DR mashqi | Tiklash vaqti `RTO ≤ 1 soat` |
| Rasmiylashtirish | Hujjatlar (metodologiya), sertifikat shabloni | Rasmiy foydalanishga tayyor |
| **Metrika** | 5+ hudud, 50 000+ urinish, uptime ≥ 99.5% | Yillik hisobot |

## 3. Yillik KPI jadvali

| Ko'rsatkich | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| Urinishlar (jami) | 1 000 | 10 000 | 30 000 | 60 000+ |
| Yonib turgan itemlar | 200 | 2 000 | 5 000 | 10 000 |
| `frozen` (anchor) itemlar | 0 | 30 | 150 | 400+ |
| Kalibrlash usuli | klassik | klassik | klassik + JMLE | JMLE + equating |
| Uptime | 98% | 99% | 99.3% | 99.5% |
| Javob yo'qolishi | 0 | 0 | 0 | 0 |
| `p95` javob vaqti | 400 ms | 350 ms | 300 ms | 250 ms |

## 4. Jamoa va resurslar (minimal)

| Rol | Q1 | Q2–Q4 | Vazifa |
|---|---|---|---|
| Backend (Python/aiogram/aiohttp) | 1 | 1–2 | Bot, API, servislar, kalibrlash |
| Frontend (HTML/CSS/JS, Mini App) | 0.5 | 1 | Javoblar varag'i, admin panel |
| DB/DevOps | 0.5 | 1 | Migratsiya, PostgreSQL, monitoring, zaxira |
| Testolog / psixometrik mutaxassis | 0.2 | 0.5 | Anchor tanlash, kalibrlash nazorati, DIF |
| Kontent (fan mutaxassislari) | 0.5 | 1 | Kalitlar, `item_ref`, mavzular |

**Infratuzilma:** Q1 — 1 VPS (2 vCPU/4 GB) + PostgreSQL; Q2 — 4 vCPU/8 GB;
Q3–Q4 — ajratilgan PG (replikatsiya) + monitoring (Grafana/Prometheus).

## 5. Risklar (yil bo'yicha)

| Risklar | Chorasi |
|---|---|
| Pilotda javob yo'qolishi (Telegram WebView) | `localStorage` + navbat + `state` tiklash; `visibilitychange` da darhol saqlash |
| Kalit xatolari ko'p (`key_suspect`) | Kalitni ikki kishi tekshirishi (4-eyes), `answer_key_imports` audit |
| Anchor itemlar mos kelmasligi | RMSD monitoringi, `anchor_mismatch` → anchor ro'yxatini yangilash |
| O'quvchilar tayyorlanishi (drift) | Har yili yangi formalar + drift hisoboti |
| PG yuklamasi | Partition, indekslar, pool, read-replica |
| Xavfsizlik (soxta javob) | initData HMAC, rate limit, `revision`, RLS, audit |

## 6. Ataylab QILINMAYDIGAN ishlar (qamrovni saqlash)

| Ish | Nega yo'q |
|---|---|
| Listening/Speaking/Writing bo'limlari | Milliy sertifikat formati emas |
| Adaptive (CAT) test | Savollar PDF da, oldin belgilangan |
| SAT/GMAT `verbal/quantitative` bo'limlari | Boshqa tizim |
| Savol matnini bazaga yuklab, ilovada ko'rsatish | Talab: savollar PDF da |
| 2PL/3PL (diskriminatsiya, taxmin) modellari | 1PL yetarli; sxema kengaytirishga tayyor |
| O'qituvchi tomonidan `b`/logit kiritish | **Ta'qiqlangan** |
| Real-time proctoring, kamera | Hozircha talab emas; `attempt_attributes` tayyor |

## 7. Yakuniy maqsad holati (12 oydan keyin)

```
PDF (kanal) → Mini App javoblari (item-level, autosave)
   → responses (append-only, audit)
   → avtomatik kalibrlash (p→b, keyin JMLE + anchor)
   → item_parameters (versiyalangan, anchor bilan bog'langan)
   → θ (Rasch) → 0–100 shkala (milliy shkala, yillar bo'yicha taqqoslanadi)
   → natija (result_versions) → bot + Mini App
   → milliy hisobotlar (hudud, fan, mavzu, trend)
```

Ya'ni: **kichik MVP → barqaror platforma → milliy o'lchov tizimi.**
