# 11 — FINAL MVP DATABASE MODEL

> **Hujjat turi:** yakuniy ma'lumot modeli spetsifikatsiyasi (arxitektura).
> **Kod, DDL, SQL, migration yozilmagan.** Maydonlar **lug'at** ko'rinishida
> (turni **o'zbekcha** yozamiz: `matn`, `son`, `vaqt`, `mantiqiy`, `JSON`) —
> jadval yaratish buyruqlari **yo'q**.
> **Qarorlar ierarxiyasi:** `docs/10-MVP-PRIORITET-AUDIT.md` **ustun**.
> Bu hujjat `docs/02` ning MVP qismini **almashtiradi** (10 → 11 → 02).

## 0. Maqsad va qat'iy chegaralar

### 0.1. Maqsad

> `docs/02` (34 jadval) → **16 jadval**ga tushirish: bitta dasturchi
> boshqaradigan, Rasch asosidagi, Milliy Sertifikat testlarini ishonchli
> tekshiradigan model. **Yangi jadval qo'shilmaydi, yangi tizim o'ylab
> topilmaydi** — faqat **soddalashtirish** va **chiqarish**.

### 0.2. Chegaralar (qat'iy)

| Chegara | Qiymat | Holat |
|---|---|---|
| Jadvallar | **≤ 16** | 16 ✅ |
| API endpoint | **≤ 8** | 6 o'quvchi + 2 admin ✅ |
| Modul (`services/`) | **≤ 6** | 5 (`rasch`, `difficulty`, `scoring`, `answer_key`, `exam_service`) ✅ |
| Asosiy algoritm | **≤ 2** | θ (MLE) + `b` (p→b) ✅ |
| Fon vazifa (worker) | **≤ 1** | 1 (baholash + kalibrlash) ✅ |
| Yangi bog'liqlik | **≤ 1** | 0 ✅ |

### 0.3. Uchta asosiy qoida (docs/10 dan)

| Qoida | Mazmuni |
|---|---|
| **Ball qoidasi** | Element **ballni o'zgartirmasa** yoki **qonuniy hujjat** yaratmasa — MVP'ga kirmaydi |
| **Arzon-qaytarilmas qoidasi** | Ma'lumot **arzon va keyin tiklanmasa** — **bugun** yig'iladi (mantiq keyin) |
| **Trigger qoidasi** | Har kechiktirilgan elementda **o'lchanadigan shart** bo'ladi; triggersiz — ish yo'q |

---

## 1. `docs/02` dagi barcha jadvallarning tasnifi

**34 jadval + 1 view** (jami 35 obyekt). Belgilar: **M** = MVP,
**P2** = PHASE-2 (3 oy), **F** = FUTURE (1 yil), **R** = REMOVE (modeldan chiqadi).

| # | Obyekt (docs/02) | Kategoriya | Qisqa sabab |
|---|---|---|---|
| 1 | `users` | **M** | Kim javob yuboryapti + 2 arzon DIF maydoni |
| 2 | `staff_roles` | **F** | MVP: `ADMIN_IDS` konfiguratsiyasi yetarli |
| 3 | `subjects` | **R** | Fan — `items.subject_code` matn maydoni bilan qoplanadi |
| 4 | `exam_programs` | **R** | Yo'nalish/daraja — `items.program_code` matn maydoni |
| 5 | `topics` | **P2** | Mavzu tahlili (content balancing) |
| 6 | `tags` | **F** | Teg tizimi hozircha talab qilinmagan |
| 7 | `items` | **M** | Global `item_id` — kalibrlash uzluksizligining asosi |
| 8 | `item_versions` | **M** | Kalit + `item_type` + `answer_spec` (versiyalangan) |
| 9 | `item_tags` | **F** | `tags` ga bog'liq |
| 10 | `item_status_history` | **P2** | Item lifecycle audit (MVP: `items.status`) |
| 11 | `answer_key_imports` | **R** | Kalit tarixi `form_versions` + `audit_log` da bor |
| 12 | `exam_structures` | **R** | Shablon — `forms` maydonlari bilan ifodalanadi |
| 13 | `exam_structure_sections` | **R** | Bo'limlar — `form_items.section_no` |
| 14 | `forms` | **M** | Test kodi + metadata |
| 15 | `form_versions` | **M** | Kalit snapshot'i (immutable) |
| 16 | `form_items` | **M** | Pozitsiya → item_version (taqdimot) |
| 17 | `exam_sessions` | **M** | Vaqt oynasi (start/end/result) |
| 18 | `attempts` | **M** | Urinish + θ + xom ball + hisoblagichlar |
| 19 | `attempt_attributes` | **R** | Guruh ma'lumoti `users` (2 maydon) + P2 `group_snapshot` |
| 20 | `attempt_events` | **P2** | Coarse hodisa izi (MVP: `audit_log`) |
| 21 | `responses` | **M** | **Append-only qabul logi** — asosiy haqiqat |
| 22 | `item_parameter_sets` | **P2** | Snapshot `b_used` bilan qoplanadi |
| 23 | `item_parameters` | **M** | Joriy operatsion `b` (versiyalangan) |
| 24 | `item_statistics` | **M** | `p`, `b`, `SE`, `flags` tarixi (kalibrlash chiqishi) |
| 25 | `scoring_snapshots` | **M** | θ/raw/scaled + `engine_version` (audit) |
| 26 | `result_versions` | **M** | «Regrade eski natijani o'zgartirmaydi» talabi |
| 27 | `calibration_runs` | **P2** | Run tarixi (MVP: `item_statistics.computed_at`) |
| 28 | `calibration_run_items` | **R** | `item_statistics` bilan **takrorlanadi** |
| 29 | `anchor_items` | **P2** | Equating (item qayta ishlatilganda) |
| 30 | `equatings` | **P2** | Formalar orasidagi o'girish |
| 31 | `audit_log` | **M** | Majburiy audit talabi |
| 32 | `notification_outbox` | **P2** | MVP: to'g'ridan-to'g'ri yuborish |
| 33 | `app_settings` | **R** | Sozlamalar `config.py`/`.env` da |
| 34 | `schema_migrations` | **M** | Texnik (majburiy) |
| 35 | *view* `attempt_response_current` | **R** | Ortiqcha abstraksiya (indeks yetarli) |

**Yakuniy hisob:** MVP **15** (docs/02 dan) **+1** (`scoring_snapshot_items`,
`docs/09`/`docs/10` da MVP sifatida **allaqachon tasdiqlangan**) = **16**;
PHASE-2 **8**; FUTURE **3**; REMOVE **8 jadval + 1 view**.

---

## 2. REMOVE — modeldan **butunlay chiqariladigan** obyektlar

Har biri uchun: **nima qilardi → nima uchun kerak emas → nima yo'qoladi →
qayerga ko'chadi**.

| # | Obyekt | Nima qilardi | Nima uchun kerak emas | Nima yo'qoladi | Qayerga ko'chadi |
|---|---|---|---|---|---|
| R1 | `subjects` | Fanlar lug'ati (kod + nom) | 4–8 fan uchun **jadval ortiqcha**; validatsiya konfiguratsiya ro'yxati bilan bajariladi | Hech narsa (fan nomi baribir kerak) | `items.subject_code` (matn) + `forms.subject_code` |
| R2 | `exam_programs` | Fan + daraja yo'nalishlari | Daraja/yo'nalish — **bir nechta matn qiymat** | «Yo'nalish» tahlili (hozir talab emas) | `items.program_code` (matn) |
| R3 | `answer_key_imports` | Kalit kiritish/yuklash tarixi | Kalit tarixi allaqachon **ikki joyda** bor: `form_versions` (har tahrir = yangi versiya) va `audit_log` | Xom matn nusxasi (kerak emas) | `form_versions.answer_key` + `audit_log` |
| R4 | `exam_structures` | Test shabloni (bo'limlar, vaqt, qoidalar) | 45-savolli **bitta tip** test uchun shablon jadvali ortiqcha | Shablon kutubxonasi (kelajak ehtiyoji) | `forms` maydonlari (`total_questions`, `options_count`, `parts_json`) |
| R5 | `exam_structure_sections` | Shablon bo'limlari | Bo'lim — faqat **guruhlash belgisi** | Bo'lim statistikasi (hozir talab emas) | `form_items.section_no` |
| R6 | `attempt_attributes` | Urinish konteksti (hudud, til, qurilma) | Guruh ma'lumoti **shaxsga** tegishli (o'quvchi hududi), urinishga emas | Urinish-darajasidagi guruh nusxasi | `users.region_code`, `users.language_code` (MVP); P2 da `attempts.group_snapshot` |
| R7 | `calibration_run_items` | Kalibrlash run'idagi har item natijasi | **`item_statistics` bilan takrorlanadi** (u allaqachon `b_raw`/`b_final`/`b_se`/`flags` ni `computed_at` bilan saqlaydi) | Run bo'yicha birlashgan hisobot | `item_statistics` (`computed_at` + `flags`) |
| R8 | `app_settings` | Sozlamalar (kalibrlash chegaralari) | Sozlamalar **kod va `.env`** da bo'lishi kerak (versiyalanadi, test qilinadi, audit talab qilmaydi) | Sozlamani «jonli» o'zgartirish (kerak emas) | `config.py` / `.env` |
| R9 | *view* `attempt_response_current` | Joriy javoblarni «view» qilib berish | **Ortiqcha abstraksiya**: joriy holat `responses` dagi `is_current` belgisi + indeks bilan **bir xil tezlikda** olinadi | Hech narsa | `responses` (to'g'ridan-to'g'ri so'rov) |

**REMOVE ning umumiy natijasi:** −8 jadval, −1 view, **hech qanday ma'lumot
yo'qolmaydi** — hamma narsa mavjud jadvaldagi **matn maydonlari**,
`form_versions` yoki `config.py` bilan qoplanadi.

---

## 3. PHASE-2 va FUTURE (trigger bilan kechiktirilgan)

### 3.1. PHASE-2 (3 oy ichida, trigger bajarilsa)

| # | Jadval | Trigger | Foyda |
|---|---|---|---|
| P1 | `topics` | Mavzu bo'yicha content balancing talab qilinsa | Mavzuli tahlil |
| P2 | `item_status_history` | Item lifecycle (draft→active→retired) rasmiylashsa | To'liq item audit |
| P3 | `attempt_events` | Hodisalar oqimi (opened/saved/conflict) kerak bo'lsa | Xatti-harakat izi |
| P4 | `item_parameter_sets` | `b` ning bir necha versiyasini bog'lash kerak bo'lganda | Equating asosi |
| P5 | `calibration_runs` | Kalibrlash hisoboti (konvergentsiya, `max_abs_delta`) talab qilinsa | Jarayon auditi |
| P6 | `anchor_items` | Bir item **ikki formada** ishlatilganda | Shkala barqarorligi |
| P7 | `equatings` | Ikki forma natijasi **bir shkalada** kerak bo'lganda | Formalar taqqoslanadi |
| P8 | `notification_outbox` | Yuborishda xatolik > 0.5% bo'lganda | Ishonchli yetkazish |

### 3.2. FUTURE (1 yildan keyin)

| # | Jadval | Trigger |
|---|---|---|
| F1 | `staff_roles` | Adminlar soni ≥ 5, rol matritsasi kerak bo'lganda |
| F2 | `tags` | Mavzu/ko'nikma teglash talab qilinsa |
| F3 | `item_tags` | `tags` qo'shilgach |

### 3.3. Kechiktirilgan **elementlar** (jadval emas, mantiq)

| Element | Trigger | Qayerga tushadi |
|---|---|---|
| Telemetriya + `dwell_ms` | `not_reached > 10%` | P2 da yangi jadval (docs/10 §6.1) |
| Incremental hisoblagichlar | Sessiyada 5 000+ urinish | P2 |
| Sessiya statistikasi + Reliability | 3 sessiyadan keyin hisobot | P2 |
| Item fit / drift / LD | Kalibrlash ishga tushgach | P2 |
| DIF hisobotlari | 10 000+ urinish | FUTURE |
| OMR, firibgarlik, `device_hash` | Oflayn/masofaviy imtihon kengayganda | FUTURE |

---

## 4. MVP tarkibidagi 16 jadval (vazifasi, bog'lanishlari, zarurligi)

### 4.1. Identity va item

| Jadval | Vazifasi | Asosiy bog'lanishlari | Nega MVP uchun zarur |
|---|---|---|---|
| `users` | O'quvchi va admin (Telegram ID, ism), + **2 arzon DIF maydoni** (`region_code`, `language_code`) | → `attempts`, `forms.created_by`, `audit_log.actor_user_id` | Urinishni **kim** yuborayotganini bilmasak, natijani hech kimga qaytara olmaymiz; hudud/til keyin **tiklanmaydi** |
| `items` | **Global item identifikatori**: `item_ref`, `subject_code`, `program_code`, `testlet_ref`, `status` | → `item_versions` (1:N), `form_items` | Item bo'yicha statistika **faqat global ID bilan uzluksiz** yig'iladi; pozitsiya bilan bog'lansa, kalibrlash imkonsiz (audit C-1) |
| `item_versions` | Kalit + `item_type` (mcq4/mcq6/numeric/text) + `answer_spec` + `max_score`; **versiyalangan** | → `items`, `form_items`, `item_parameters` | Baholash uchun **kalit qoidasi** (moslik/tolerantlik) kerak; matn o'zgarsa — yangi versiya, statistika noldan |

### 4.2. Formalar va o'tkazish

| Jadval | Vazifasi | Asosiy bog'lanishlari | Nega MVP uchun zarur |
|---|---|---|---|
| `forms` | Test varianti: **test kodi**, nomi, fan, savollar soni, variantlar soni, qismli savollar | → `form_versions`, `exam_sessions` | Foydalanuvchi kiritadigan **test kodi** shu yerda; kodsiz testni ochib bo'lmaydi |
| `form_versions` | Kalit **snapshot'i** (immutable) — baholashda ishlatilgan kalit | → `form_items`, `attempts` | Kalit keyin tuzatilsa, **eski urinishlar buzilmasligi** kerak (audit) |
| `form_items` | Pozitsiya → item_version: `position`, `display_label` («36a»), `part`, `section_no`, `correct_option` (snapshot) | → `form_versions`, `item_versions`, `responses` | Savol QR/PDF dagi **tartib** va **belgi** bilan bog'lanadi; javob qaysi savolga tegishli ekani shu yerdan aniqlanadi |
| `exam_sessions` | Vaqt oynasi: boshlanish / tugash / natija e'loni + holat | → `forms`, `attempts`, `item_statistics` | Javob qabul qilish, avtomatik yakunlash va «natija qachon ko'rinadi» — **shu jadval** |
| `attempts` | O'quvchining bitta urinishi: holat, θ, `theta_se`, xom ball, hisoblagichlar, `last_interaction_position` | → `users`, `exam_sessions`, `form_versions`, `responses`, `scoring_snapshots`, `result_versions` | Baholash natijasi va **`not_reached`** aniqlash uchun asos; urinishsiz javob ham, natija ham yo'q |

### 4.3. Javoblar va baholash

| Jadval | Vazifasi | Asosiy bog'lanishlari | Nega MVP uchun zarur |
|---|---|---|---|
| `responses` | **Append-only qabul logi**: har o'zgarish — yangi revision; `capture_status`, `answer_kind`, variant/raw answer; `is_current` — oxirgi holat | → `attempts`, `form_items`, `item_versions` | Tizimning **yagona haqiqati**: javob yo'qolmasligi, tarix, apellyatsiya, kalibrlash uchun xom ma'lumot — hammasi shu yerdan |
| `item_parameters` | Joriy **operatsion `b`** (versiyalangan: `valid_from`/`valid_to`, `status`) | → `item_versions` | Rasch baholash uchun `b` kerak; yangi item `b = 0.0` bilan boshlanadi, keyin tizim yangilaydi |
| `item_statistics` | **Kalibrlash chiqishi**: `n_*`, `p_used`, `guessing_c`, `b_raw`/`b_final`, `b_se`, `flags`, `computed_at` | → `item_versions`, `exam_sessions` | `b` qanday hisoblanganini **isbotlaydi**; flag'lar (`key_suspect`, `too_easy`) admin ko'rigi uchun |
| `scoring_snapshots` | Urinish darajasidagi baholash snapshot'i: θ, `theta_se`, xom ball, `engine_version`, `b_checksum` | → `attempts`, `result_versions` | Natijani **takror ishlab chiqarish** (reproducibility) va audit |
| `scoring_snapshot_items` | **Item darajasidagi** muzlatilgan baholash: `key_used`, `b_used`, `theta_used`, `guessing_c`, `score_awarded`, `score_status` | → `scoring_snapshots`, `item_versions`, `form_items` | Apellyatsiya («7-savol to'g'ri edi»), regrade va kelajakdagi fit/DIF tahlilining yagona dalili (audit C-4) |
| `result_versions` | E'lon qilingan natija versiyalari: `version_no`, `visible_from`, `snapshot_id`, `reason` | → `attempts`, `scoring_snapshots` | «Regrade eski natijani **o'zgartirmaydi**» talabi — yangi versiya yaratiladi |

### 4.4. Audit va texnik

| Jadval | Vazifasi | Asosiy bog'lanishlari | Nega MVP uchun zarur |
|---|---|---|---|
| `audit_log` | Kim, qachon, nimani o'zgartirdi (`action`, `entity_type`, `before_json`, `after_json`) | → `users` (actor) | Kalit tuzatilishi, `b` yangilanishi, o'quvchi chiqarilishi — **majburiy audit talabi** |
| `schema_migrations` | Migratsiya versiyalari | — | Baza sxemasi xavfsiz rivojlanishi (texnik majburiyat) |

### 4.5. MVP modelining umumiy ko'rinishi

```
   users ──┐                                    items ──► item_versions
           │                                                 │      │
           │                                        ┌────────┘      │
           ▼                                        ▼               ▼
   exam_sessions ──► attempts ──► responses   form_items ◄── form_versions ◄── forms
                        │            │              ▲
                        │            └──────────────┘
                        ▼
                scoring_snapshots ──► scoring_snapshot_items ──► (b_used/key_used)
                        │
                        ▼
                 result_versions            item_parameters ──► item_statistics
                                                       ▲
                                                     audit_log  (hamma amallar)
```

---

## 5. Yakuniy MVP sxemasi (ro'yxat va maydonlar)

### 5.1. Jadval ro'yxati (16)

| # | Jadval | Sxema (PG) | Nima saqlaydi |
|---|---|---|---|
| 1 | `users` | `iam` | O'quvchi/admin, hudud, til |
| 2 | `items` | `item` | Global item identifikatori |
| 3 | `item_versions` | `item` | Kalit + tur + javob qoidasi (versiyalangan) |
| 4 | `item_parameters` | `scoring` | Operatsion `b` (versiyalangan) |
| 5 | `item_statistics` | `scoring` | `p`, `b`, `SE`, `flags` tarixi |
| 6 | `forms` | `delivery` | Test kodi + metadata |
| 7 | `form_versions` | `delivery` | Kalit snapshot'i |
| 8 | `form_items` | `delivery` | Pozitsiya → item_version |
| 9 | `exam_sessions` | `delivery` | Vaqt oynasi |
| 10 | `attempts` | `delivery` | Urinish + θ + xom ball |
| 11 | `responses` | `delivery` | **Append-only javob logi** |
| 12 | `scoring_snapshots` | `scoring` | Urinish snapshot'i |
| 13 | `scoring_snapshot_items` | `scoring` | Item snapshot'i (muzlatilgan) |
| 14 | `result_versions` | `scoring` | Natija versiyalari |
| 15 | `audit_log` | `audit` | Audit izi |
| 16 | `schema_migrations` | `ops` | Migratsiya versiyalari |

### 5.2. `responses` — to'liq maydonlar lug'ati

| Maydon | Tur | Majburiy | Izoh |
|---|---|---|---|
| `response_id` | son | ✅ | Har voqea uchun yagona ID |
| `attempt_id` | son | ✅ | Urinishga bog'lanish |
| `item_id` | son | ✅ | **Global identifikatsiya** |
| `item_version_id` | son | ✅ | `b` va kalit aynan shu versiyaga |
| `form_item_id` | son | ✅ | Taqdimot konteksti (pozitsiya/label) |
| `position` | son | ✅ | PDF tartibi (faqat taqdimot) |
| `display_label` | matn | ✅ | «36a» kabi **inson belgisi** |
| `part` | matn | ✅ | `''` / `'a'` / `'b'` |
| `testlet_ref` | matn | ➖ (36a–45b uchun ✅) | Umumiy matn (LD uchun, **arzon + qaytarilmas**) |
| `revision` | son | ✅ | 1 dan boshlanadi, har o'zgarishda +1 |
| `superseded_by` | son | ➖ | Keyingi revision (zanjir) |
| `is_current` | mantiqiy | ✅ | Oxirgi holat belgisi (indeks bilan) |
| `event_type` | matn | ✅ | `capture` / `clear` / `finalize` / `admin_fix` |
| `capture_status` | matn | ✅ | `answered` / `blank` / `not_reached` |
| `answer_kind` | matn | ✅ | `option` / `numeric` / `text` |
| `selected_option` | matn | ➖ | MCQ: `A`…`F` |
| `raw_answer` | matn | ➖ | O'quvchi kiritgani **aynan** (qaytarilmas) |
| `normalized_answer` | matn | ➖ | Normallashtirilgan qiymat |
| `numeric_value` | son | ➖ | Numeric javob (tolerantlik hisobi) |
| `source` | matn | ✅ | `webapp` / `bot` / `admin` / `system` |
| `client_seq` | son | ✅ | Idempotentlik (takrorlanmas: `attempt_id` + `client_seq`) |
| `recorded_at` | vaqt | ✅ | **Server vaqti** (haqiqat) |
| `created_at` | vaqt | ✅ | Partition/arxiv kaliti |

**MVP'da bu jadvalda YO'Q:** `is_correct`, `score_awarded`, `p_hat`, `b_used`
(hosilaviy → `scoring_snapshot_items` da), `prev_response_id`,
`client_clock_skew_ms`, `answer_payload`, `capture_conflicts`, `input_method`.

### 5.3. `attempts` — maydonlar lug'ati

| Maydon | Tur | Majburiy | Izoh |
|---|---|---|---|
| `attempt_id` | son | ✅ | — |
| `session_id`, `user_id`, `form_version_id` | son | ✅ | Bog'lanishlar |
| `status` | matn | ✅ | `in_progress` / `submitted` / `submitted_late` / `graded` / `invalid` |
| `submit_mode` | matn | ✅ | `manual` / `auto_timeout` / `admin` |
| `started_at`, `last_seen_at`, `submitted_at` | vaqt | ✅/➖ | Vaqtlar |
| `duration_seconds` | son | ✅ | Speededness va izoh uchun |
| `last_interaction_position` | son | ✅ | **`not_reached` ni arzon aniqlash** |
| `interaction_count` | son | ✅ | Faollik hajmi |
| `revision` | son | ✅ | Paketlar hisoblagichi (optimistik qulf) |
| `raw_score` | son | ✅ | Rasmiy xom ball (`blank` = 0 siyosati) |
| `raw_score_strict` | son | ✅ | `not_reached` = 0 variant (deyarli bepul) |
| `n_answered`, `n_omitted`, `n_not_reached` | son | ✅ | Hisoblagichlar (hisobot + `p` maxraji) |
| `theta`, `theta_se`, `scaled_score` | son | Baholashdan keyin ✅ | Baholash natijasi |
| `is_extreme_low`, `is_extreme_high` | mantiqiy | ✅ | «0/45» va «45/45» uchun siyosat |
| `engine_version` | matn | ✅ | Qaysi hisoblash |
| `deleted_at` | vaqt | ➖ | Soft delete (audit) |
| `created_at`, `updated_at` | vaqt | ✅ | — |

**MVP'da YO'Q:** `parameter_set_id`, `scoring_policy_code`, `group_snapshot`,
`person_infit_mnsq`, `log_likelihood`, `theta_method`, `level_code`,
`device_hash`, `ip_hash`, `device_json` (P2/F).

### 5.4. `scoring_snapshot_items` — maydonlar lug'ati

| Maydon | Tur | Majburiy | Izoh |
|---|---|---|---|
| `snapshot_item_id` | son | ✅ | — |
| `snapshot_id` | son | ✅ | Urinish snapshot'iga bog'lanish |
| `attempt_id`, `session_id`, `form_version_id` | son | ✅ | Tahlil uchun guruhlash |
| `form_item_id` | son | ✅ | Taqdimot konteksti |
| `item_id`, `item_version_id` | son | ✅ | Kalibrlash/drift/equating kaliti |
| `display_label`, `position` | — | ✅ | Hisobot («7-savol») |
| `testlet_ref` | matn | ➖ | LD konteksti |
| `b_used` | son | ✅ | Baholashda ishlatilgan `b` (**muzlatilgan**) |
| `b_source` | matn | ✅ | `default` / `classical` / `guessing_corrected` / `legacy_expert` |
| `theta_used` | son | ✅ | `P̂` ni qayta hisoblash imkoni |
| `guessing_c` | son | ✅ | `1/k` (mcq4: 0.25, mcq6: 0.1667, open: 0) |
| `key_used` | matn | ✅ | O'sha paytdagi kalit (option yoki qiymat) |
| `key_version_no`, `key_source` | son/matn | ✅ | Kalit tarixi |
| `answer_kind`, `raw_answer`, `normalized_answer` | — | ✅ | Apellyatsiya dalili |
| `score_awarded`, `max_score` | son | ✅ | Ball |
| `score_status` | matn | ✅ | `auto_scored` / `pending_review` / `manual_scored` |
| `match_rule` | matn | ✅ | `exact` / `tolerance` / `normalized` / `manual` |
| `capture_status` | matn | ✅ | `not_reached` ni tahlildan chiqarish |
| `engine_version` | matn | ✅ | Reproducibility |
| `scored_at`, `scored_by` | — | ✅ | Audit |

**MVP'da YO'Q:** `p_hat`, `residual`, `information` (formuladan **qayta
hisoblanadi**), `is_anchor`, `anchor_b`, `b_se_used`, `parameter_set_id`,
`validity_status` (P2).

### 5.5. Qolgan jadvallar — asosiy maydonlar

| Jadval | Asosiy maydonlar |
|---|---|
| `users` | `user_id` (Telegram ID), `full_name`, `username`, `is_admin`, `region_code`, `language_code`, `created_at`, `deleted_at` |
| `items` | `item_id`, `item_ref`, `subject_code`, `program_code`, `testlet_ref`, `status` (`active`/`flagged`/`retired`), `current_version_id`, `created_by`, `created_at`, `deleted_at` |
| `item_versions` | `item_version_id`, `item_id`, `version_no`, `item_type`, `correct_option` (`A`…`F`), `answer_spec` (JSON), `max_score`, `is_current`, `superseded_by`, `key_source`, `created_by`, `created_at`, `deleted_at` |
| `item_parameters` | `item_parameter_id`, `item_version_id`, `b_value`, `b_se`, `source`, `status` (`provisional`/`operational`/`frozen`/`retired`), `n_used`, `valid_from`, `valid_to`, `created_at` |
| `item_statistics` | `stat_id`, `item_version_id`, `session_id`, `n_presented`, `n_answered`, `n_correct`, `n_omitted`, `n_not_reached`, `p_used`, `guessing_c`, `b_raw`, `b_final`, `b_se`, `group_mean_theta`, `prior_b`, `shrinkage_weight`, `method`, `flags`, `is_current`, `computed_at`, `computed_by` |
| `forms` | `form_id`, `title`, `test_code`, `subject_code`, `total_questions`, `options_count`, `parts_json`, `current_version_id`, `created_by`, `created_at`, `updated_at`, `deleted_at` |
| `form_versions` | `form_version_id`, `form_id`, `version_no`, `answer_key`, `total_questions`, `status`, `change_reason`, `created_by`, `created_at`, `published_at` |
| `form_items` | `form_item_id`, `form_version_id`, `position`, `display_label`, `part`, `section_no`, `correct_option`, `options_count`, `item_version_id`, `points`, `created_at` |
| `exam_sessions` | `session_id`, `form_id`, `title`, `start_time`, `end_time`, `result_time`, `status`, `graded_at`, `created_by`, `created_at`, `updated_at`, `deleted_at` |
| `scoring_snapshots` | `snapshot_id`, `attempt_id`, `form_version_id`, `model`, `theta`, `theta_se`, `log_likelihood`, `raw_score`, `total_items`, `omitted_count`, `not_reached_count`, `scaled_score`, `scaled_min`, `scaled_max`, `theta_bound`, `engine_version`, `b_checksum`, `is_final`, `supersedes_id`, `computed_at`, `computed_by` |
| `result_versions` | `result_id`, `attempt_id`, `version_no`, `snapshot_id`, `visible_from`, `published_at`, `published_by`, `channel_json`, `payload_json`, `reason`, `is_active`, `created_at` |
| `audit_log` | `audit_id`, `actor_user_id`, `action`, `entity_type`, `entity_id`, `before_json`, `after_json`, `source`, `note`, `created_at` |
| `schema_migrations` | `version`, `name`, `checksum`, `applied_at`, `duration_ms` |

---

## 6. Chegaralar tekshiruvi (docs/10 talablari)

| Chegara | Talab | Natija | Holat |
|---|---|---|---|
| Jadvallar | ≤ 16 | **16** (15 + texnik) | ✅ |
| Endpoint'lar | ≤ 8 | **8** (6 o'quvchi + 2 admin) | ✅ |
| Modullar | ≤ 6 | **5** | ✅ |
| Asosiy algoritm | ≤ 2 | **2** | ✅ |
| Worker | ≤ 1 | **1** | ✅ |

### 6.1. Endpoint'lar (8)

| # | Endpoint | Turi |
|---|---|---|
| 1 | Sessiyani kod bo'yicha tekshirish | o'quvchi |
| 2 | Urinishni boshlash/tiklash (idempotent) | o'quvchi |
| 3 | Javobni saqlash (autosave, item-level) | o'quvchi |
| 4 | Holatni olish (`state`) | o'quvchi |
| 5 | Yakunlash (`submit`) | o'quvchi |
| 6 | Natijani olish | o'quvchi |
| 7 | Forma yaratish (kalit + jadval) — **bot orqali** | admin |
| 8 | Item statistikasi / kalibrlashni ishga tushirish — **bot orqali** | admin |

### 6.2. Modullar (5)

| Modul | Vazifasi |
|---|---|
| `rasch` | θ hisoblash (MLE + Newton-Raphson) — **mavjud** |
| `difficulty` | `p → b` hisoblash (Jeffreys, `c₀`, mean-mean, shrinkaj, flag'lar) |
| `scoring` | Snapshot scoring: `responses` → `scoring_snapshots` + `scoring_snapshot_items` |
| `answer_key` | Kalit tahlili, `numeric`/`text` normallashtirish — **mavjud** |
| `exam_service` | Vaqt, holat, validatsiya — **mavjud** |

### 6.3. Algoritmlar (2)

| Algoritm | Kirish | Chiqish |
|---|---|---|
| **θ (Rasch MLE)** | `b_used` (item), `u_ij` (javob) | `theta`, `theta_se`, `is_extreme` |
| **`b` (p→b)** | `n_*` hisoblagichlar, `p_used`, `guessing_c`, `θ̄` | `b_raw`, `b_final`, `b_se`, `flags` |

### 6.4. Worker (1)

| Worker | Vazifasi | Davri |
|---|---|---|
| `grading_worker` | (a) `end_time` o'tgan sessiyalarni yakunlash+baholash, (b) sessiyadan keyin `b` kalibrlash, (c) natijani e'lon qilish | 30–60 s |

---

## 7. Sakkiz jadval bo'yicha asoslash (talab: MVP'da qoladimi?)

| Jadval | MVP'da qoladimi? | Asos |
|---|---|---|
| **`items`** | ✅ **QOLADI** | «Savollar matni saqlanmaydi, faqat `item_id` + `item_version`» — bu **sizning asosiy cheklovingiz**. `items` bo'lmasa, statistika **pozitsiyaga** bog'lanadi va har formada noldan boshlanadi → kalibrlash **imkonsiz** (audit C-1) |
| **`item_versions`** | ✅ **QOLADI** | Kalit + `item_type` (mcq4/mcq6/numeric/text) + `answer_spec` shu yerda. Kalitni `form_versions` da saqlash **yetarli emas**, chunki bir item **bir necha formada** ishlatilishi mumkin va versiyalanish kerak (matn/kalit o'zgarsa — yangi versiya) |
| **`item_parameters`** | ✅ **QOLADI** | Rasch baholash uchun **joriy `b`** kerak. Yangi item `b = 0.0` (default) bilan boshlanadi; keyin `difficulty` moduli yangilaydi. `b` ni `item_statistics` dan «oxirgi qator» sifatida olish ham mumkin, lekin **alohida jadval** «amaldagi `b`» ni aniq va tez beradi (versiyalash, `valid_to`, `status`) |
| **`item_statistics`** | ✅ **QOLADI** | Bu — **avtomatik qiyinchilik hisoblashning yagona isboti**: `n_*`, `p_used`, `b_raw`/`b_final`, `SE`, `flags`, `computed_at`. `flags` (`key_suspect`, `too_easy`) **kalit xatosini** topishning MVP usuli. Bu jadval bo'lmasa, «`b` qanday chiqdi?» degan savolga javob yo'q |
| **`scoring_snapshots`** | ✅ **QOLADI** | Urinish darajasidagi **baholash fakti**: θ, `SE`, xom ball, `engine_version`, `b_checksum`. `result_versions` unga tayanadi; qayta baholashda eski natijani tiklash uchun kerak |
| **`scoring_snapshot_items`** | ✅ **QOLADI** (docs/09/10 da tasdiqlangan) | **Item darajasidagi** muzlatilgan baholash. Busiz: (a) apellyatsiya («7-savol to'g'ri edi») javobsiz qoladi, (b) regrade'da «qaysi savol o'zgargan?» aniqlanmaydi, (c) kelajakdagi fit/DIF tahlili **tiklanmaydi**. `b_used` + `key_used` + `theta_used` — **qaytarilmas** uchlik |
| **`result_versions`** | ✅ **QOLADI** | `docs/09`/`docs/10` va sizning talabingiz: «Regrade eski natijani **almashtirmaydi**, yangi **result version** yaratadi». Busiz talab **bajarilmaydi** |
| **`audit_log`** | ✅ **QOLADI** | Audit talab (soft delete, kalit tuzatish, `b` yangilash, o'quvchi chiqarish). Bitta jadval, oddiy sxema — **murakkablik qo'shmaydi** |

**Xulosa:** sakkiztasining **hammasi qoladi** — lekin `docs/02` dagi
**varianti emas**: `scoring_snapshot_items` **yangi qo'shiladi** (docs/09/10 da
tasdiqlangan), `item_parameters` va `item_statistics` dan
**`form_item_id` olib tashlanadi** (faqat `item_version_id`) — bu
**identifikatsiyani to'g'ri** qiladi va statistikani bo'linishdan saqlaydi.

---

## 8. Rasch uchun **majburiy** saqlanadigan ma'lumotlar

Bu ro'yxat **to'liq**: bundan biror narsa chiqarilsa, θ yoki `b` **xato**
hisoblanadi. Har bir qator: **nima** → **qaysi jadval** → **nega majburiy**.

### 8.1. Item darajasi (kirish ma'lumoti)

| Ma'lumot | Jadval | Nega majburiy |
|---|---|---|
| `item_id` + `item_version_id` | `items`, `item_versions` | Item statistikasi **faqat** bir xil versiya bo'yicha to'planadi |
| `item_type` (mcq4/mcq6/numeric/text) | `item_versions` | Tasodif ehtimoli `c₀ = 1/k` va baholash qoidasi shunga bog'liq |
| `answer_spec` (kalit + tolerantlik/normallashuv) | `item_versions` | Javobni **to'g'ri/noto'g'ri** ajratishning yagona manbai |
| `max_score` | `item_versions` | `u_ij = score_awarded ≥ max_score` (polytomous readiness) |
| `b_used` (baholash paytida) | `scoring_snapshot_items` | θ **aynan shu `b`** bilan hisoblangan |
| `b_value` + `status` (joriy) | `item_parameters` | Keyingi baholashlarda ishlatiladi |
| `b_raw` / `b_final` / `b_se` / `flags` | `item_statistics` | `b` qanday chiqqanini isbotlaydi |

### 8.2. Javob darajasi (`u_ij` matritsasi)

| Ma'lumot | Jadval | Nega majburiy |
|---|---|---|
| `attempt_id` + `item_version_id` | `responses` | Matritsa indekslari (o'quvchi × item) |
| `score_awarded` (yoki uning manbasi: `selected_option` / `numeric_value`) | `scoring_snapshot_items` | `u_ij` ning o'zi |
| `capture_status` | `responses` / snapshot | **`not_reached` → `missing`** (θ dan chiqariladi) |
| `is_current` + `revision` | `responses` | O'quvchining **oxirgi** javobi olinadi (eski revision emas) |
| `guessing_c` | `scoring_snapshot_items` | `p → b` da tasodif tuzatishi |

### 8.3. Urinish darajasi (θ chiqishi)

| Ma'lumot | Jadval | Nega majburiy |
|---|---|---|
| `theta`, `theta_se` | `attempts` (+ `scoring_snapshots`) | Baholash natijasi va aniqligi |
| `is_extreme_low/high` | `attempts` | «0/45» va «45/45» uchun **chekli θ yo'q** — siyosat kerak |
| `raw_score`, `n_answered`, `n_omitted`, `n_not_reached` | `attempts` | Hisobot va **`p` maxraji** |
| `theta_used` (baholash paytida) | `scoring_snapshot_items` | `P̂` va reziduallarni qayta hisoblashning yagona yo'li |

### 8.4. Reproducibility (audit uchun)

| Ma'lumot | Jadval | Nega majburiy |
|---|---|---|
| `engine_version` | `attempts`, `scoring_snapshots`, `scoring_snapshot_items` | Qaysi hisoblash bilan |
| `b_checksum` | `scoring_snapshots` | `b` to'plami bir xilmi (tez tekshiruv) |
| `key_used`, `key_version_no` | `scoring_snapshot_items` | O'sha paytdagi kalit (regrade/apellyatsiya) |
| `computed_at`, `computed_by` | `item_statistics`, `scoring_snapshots` | Kim/qachon hisobladi |

> **Qisqa nazorat ro'yxati:** `item_version_id` · `item_type` · `answer_spec` ·
> `max_score` · `score_awarded` · `b_used` · `theta` · `theta_used` ·
> `guessing_c` · `capture_status` (+`not_reached`) · `is_extreme` ·
> `engine_version`.

---

## 9. Kelajak uchun **bugundan** saqlanadigan minimal maydonlar

Bu maydonlar **arzon** (bir marta yoziladi, mantiq talab qilmaydi) va
**qaytarilmas** — shuning uchun MVP'da **saqlanadi**, lekin **ishlatilmaydi**.

### 9.1. DIF uchun (kelajakda hudud/til bo'yicha)

| Maydon | Jadval | Nega bugun |
|---|---|---|
| `region_code` | `users` | O'quvchi hududi — **kechiktirilsa tiklanmaydi** |
| `language_code` | `users` | Test/kontent tili (lotin/kirill/ru) |
| `gender`, `birth_year` (ixtiyoriy) | `users` | DIF uchun guruh o'zgaruvchilari |

**Eslatma:** DIF **hisoblash** — FUTURE (10 000+ urinish kerak), lekin bu
**2–4 maydon** bugun yozilmasa, **o'tgan davr uchun DIF hech qachon** mumkin
bo'lmaydi. Jadval qo'shilmaydi — maydonlar `users` da.

### 9.2. Anchor va equating uchun

| Maydon | Jadval | Nega bugun |
|---|---|---|
| `item_ref` | `items` | **Bir xil item ikki formada** bog'lanishining kaliti (anchor shart) |
| `version_no` + `is_current` | `item_versions` | Anchor `b` qaysi versiyaga tegishli |
| `b_source` | `item_parameters`, `scoring_snapshot_items` | `anchor` manbasini ajratish (`default`/`classical`/`anchor`) |
| `status` = `frozen` | `item_parameters` | Anchor nomzodini **keyin tiklab bo'lmaydi** (qachon qotirilgani muhim) |
| `item_version_id` (aynan) | `responses`, `item_statistics`, `item_parameters` | Equating **faqat** bir xil itemlar orasida bo'ladi |

### 9.3. Drift monitoring uchun

| Maydon | Jadval | Nega bugun |
|---|---|---|
| `session_id` + `computed_at` | `item_statistics` | Bir itemning **sessiyalar bo'ylab** tarixi |
| `n_presented`, `n_answered`, `n_correct` | `item_statistics` | Drift z-testi uchun xom sonlar (`p` ni qayta hisoblash) |
| `flags` | `item_statistics` | `drift` flag'i qaysi davrda chiqqanini bilish |
| `b_raw` va `b_final` (ikkisi) | `item_statistics` | Tuzatishlarsiz va tuzatishlar bilan solishtirish |

### 9.4. Local dependence (LD) uchun

| Maydon | Jadval | Nega bugun |
|---|---|---|
| `testlet_ref` | `items`, `responses`, `scoring_snapshot_items` | 36a–45b juftligini bog'lashning **yagona** yo'li |
| `display_label`, `part` | `form_items`, `responses` | Juftlikni inson ko'rinishida aniqlash |
| `b_used` + `score_awarded` (juftlik) | `scoring_snapshot_items` | Juftlik rezidual korrelyatsiyasi **shu ikkisidan** hisoblanadi |

### 9.5. Kelajak tayyorgarligining **to'liq ro'yxati** (jadval emas, maydon)

`users.region_code` · `users.language_code` · `items.item_ref` ·
`items.testlet_ref` · `item_versions.version_no` · `item_versions.item_type` ·
`item_versions.answer_spec` · `item_parameters.status` · `item_parameters.b_source` ·
`item_statistics.session_id` · `item_statistics.flagged` ·
`responses.testlet_ref` · `responses.raw_answer` ·
`scoring_snapshot_items.b_used` · `.key_used` · `.theta_used` · `.guessing_c`

> **Hammasi — mavjud 16 jadval ichidagi maydonlar.** Yangi jadval **yo'q**.

---

## 10. `docs/02` va `docs/04` da qilinadigan tuzatishlar (ro'yxat, DDL emas)

### 10.1. `docs/02-DATABASE-SCHEMA.md`

| # | Nima o'zgaradi | Qanday |
|---|---|---|
| 1 | §2 katalogi (34 jadval) | Har jadval yoniga **M / P2 / F / R** belgisi qo'yiladi (11-hujjat §1) |
| 2 | §3 (MVP-0) | `attempt_response_current` **view** va `responses.is_current` **partial indeks** — view olib tashlanadi (indeks qoladi) |
| 3 | §4 (MVP-1/MVP-2) | `subjects`, `exam_programs`, `exam_structures`, `exam_structure_sections`, `answer_key_imports`, `attempt_attributes`, `calibration_run_items`, `app_settings` — **chiqariladi** |
| 4 | §4 `items` | `program_id`/`topic_id` o'rniga `subject_code`, `program_code`, `testlet_ref` (matn) |
| 5 | §4 `item_versions` | `item_type`, `answer_spec`, `max_score` **qo'shiladi** (majburiy) |
| 6 | §3 `responses` | `capture_status`, `answer_kind`, `raw_answer`, `normalized_answer`, `numeric_value`, `testlet_ref`, `event_type`, `recorded_at` **qo'shiladi**; `is_correct` **olib tashlanadi**; `given_option` → `A`…`F` |
| 7 | §3 `attempts` | `last_interaction_position`, `interaction_count`, `duration_seconds`, `submit_mode`, `raw_score_strict`, `n_not_reached`, `is_extreme_*` **qo'shiladi** |
| 8 | §3 `item_parameters` / `item_statistics` | **`form_item_id` olib tashlanadi** — faqat `item_version_id` |
| 9 | §3 `scoring_snapshots` | `not_reached_count`, `engine_version` qoladi; `parameter_set_id` **P2** ga o'tadi |
| 10 | §7 «MVP uchun minimal jadvallar» | **Butunlay almashtiriladi** — 11-hujjat §5 dagi 16 jadval ro'yxati bilan |
| 11 | §8 (kalibrlash SQL so'rovlari) | `form_item_id` → `item_version_id` ga o'zgartiriladi |
| 12 | Sarlavha | «MVP tarkibi uchun `docs/11` ustun» degan **havola** qo'shiladi |

### 10.2. `docs/04-API-VA-UI-MVP.md`

| # | Nima o'zgaradi | Qanday |
|---|---|---|
| 1 | `PUT /responses` so'rovi | `position`/`part` o'rniga **`item_id` + `item_version_id`** (+ `part`) |
| 2 | Javob maydoni | MCQ: `option` (`A`…`F`); ochiq: `value` (matn); + `answer_kind` |
| 3 | `PUT` javobi | + `capture_status`, `score_status`, `revision` |
| 4 | `GET /state` | + har item uchun `capture_status` va `not_reached` ro'yxati |
| 5 | `POST /submit` | + `not_reached_count`, `raw_score_strict` |
| 6 | UI | 33–35 uchun **6 variantli** kartochka; 36–45 uchun **input** kartochkalari (36a/36b) |
| 7 | `1A2B3C4D` | **Faqat eksport** uchun (asosiy kiritish usuli emas) |

> **Muhim:** `docs/02` va `docs/04` **matnlari shu bosqichda tahrirlanmadi**
> (tahrir DDL/SQL yozishni talab qiladi, bu esa **taqiqlangan**). Tuzatishlar
> ro'yxati yuqorida — keyingi bosqichda (ruxsat berilganda) qo'llaniladi.
> Hozir **yagona manba — `docs/11`**.

---

## 11. Xulosa

### 11.1. Yakuniy holat

```
docs/02 (34 jadval)                     docs/11 (16 jadval)
────────────────────────────            ────────────────────────────
MVP-0     11  ┐                         MVP       15 + 1 texnik
MVP-1     +8  ├─► 34                    PHASE-2    8
MVP-2    +15  ┘                         FUTURE     3
                                        REMOVE     8 + 1 view
```

| Kategoriya | Soni | Nima |
|---|---|---|
| **MVP** | **16** | `users`, `items`, `item_versions`, `item_parameters`, `item_statistics`, `forms`, `form_versions`, `form_items`, `exam_sessions`, `attempts`, `responses`, `scoring_snapshots`, `scoring_snapshot_items`, `result_versions`, `audit_log`, `schema_migrations` |
| PHASE-2 | 8 | `topics`, `item_status_history`, `attempt_events`, `item_parameter_sets`, `calibration_runs`, `anchor_items`, `equatings`, `notification_outbox` |
| FUTURE | 3 | `staff_roles`, `tags`, `item_tags` |
| REMOVE | 8+1 | `subjects`, `exam_programs`, `answer_key_imports`, `exam_structures`, `exam_structure_sections`, `attempt_attributes`, `calibration_run_items`, `app_settings`, *view* `attempt_response_current` |

### 11.2. Nima **o'zgarmadi** (muhim)

| Tamoyil | Holat |
|---|---|
| Savollar matni bazaga yuklanmaydi | ✅ o'zgarmadi |
| O'qituvchi `b` kiritmaydi | ✅ o'zgarmadi |
| Har javob **item-level**, `1A2B3C4D` faqat eksport | ✅ o'zgarmadi |
| Snapshot scoring + kalit/`b` muzlatiladi | ✅ o'zgarmadi (endi **item darajasida ham**) |
| Regrade eski natijani o'zgartirmaydi | ✅ o'zgarmadi |
| Soft delete, append-only javoblar | ✅ o'zgarmadi |
| Rasch (1PL) asosiy model | ✅ o'zgarmadi |

### 11.3. Uchta asosiy natija

1. **−18 jadval** (34 → 16) va **−1 view**; **hech qanday ma'lumot
   yo'qolmaydi** — hammasi mavjud jadval maydonlari, `form_versions` yoki
   `config.py` bilan qoplanadi.
2. **Rasch uchun zarur 12 maydon** ro'yxati (8-bo'lim) va **kelajak uchun
   bugun saqlanadigan 17 maydon** ro'yxati (9-bo'lim) — **yangi jadval yo'q**.
3. **Chegaralar bajarildi:** 16 jadval · 8 endpoint · 5 modul · 2 algoritm ·
   1 worker.

### 11.4. Keyingi qadam (tavsiya)

| # | Qadam | Natija |
|---|---|---|
| 1 | `docs/02` ni shu hujjat bo'yicha qayta yozish (ruxsat berilganda) | Bitta manba, DDL bilan |
| 2 | `docs/04` ni 8 endpoint va yangi UI bilan yangilash | Mos API |
| 3 | `docs/11` ni ishlab chiqishda **tekshiruv ro'yxati** sifatida ishlatish | MVP chegarasidan chiqmaslik |
| 4 | Har 3 oyda **trigger jadvalini** ko'rib chiqish (docs/10 §10.3) | Faqat asoslangan o'sish |

### 11.5. Nazorat savoli (har yangi jadval/maydon taklifiga)

```
1. Bu ballni o'zgartiradimi?           → Yo'q → kechiktir
2. Qonuniy hujjat talabimi?            → Yo'q → kechiktir
3. Bu ma'lumot keyin tiklanadimi?      → Ha  → kechiktir
4. Trigger (metrika) bormi?            → Yo'q → kechiktir
5. 2 kundan ko'p ish talab qiladimi?   → Ha  → kechiktir
───────────────────────────────────────────────────────────
Besh savoldan biri ham «yo'q/ha» bo'lmasa — MVP'ga kiradi.
Aks holda: PHASE-2 yoki FUTURE ro'yxatiga trigger bilan yoziladi.
```
