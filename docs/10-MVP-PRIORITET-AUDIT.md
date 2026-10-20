# 10 — MVP prioritet auditi (Response Model v2 ni soddalashtirish)

> **Hujjat turi:** arxitektura auditi va prioritetlash.
> **Kod / DDL / SQL yozilmagan.** Faqat tasnif, asoslash va chegara (trigger).
> **Audit predmeti:** `docs/09-RESPONSE-MODEL-V2.md` (va u orqali `02`, `04`, `08`).
> **Maqsad:** bitta dasturchi boshqara oladigan, Rasch asosidagi, Milliy
> Sertifikat testlarini tekshira oladigan **sodda va toza** arxitektura.

## 0. Audit mezoni (nima uchun MVP deb hisoblanadi)

Har bir element quyidagi **to'rt savolga** javob beradi:

| Savol | Ma'nosi |
|---|---|
| **1. Nima vazifa bajaradi?** | Aniq funksiya (baholash, audit, tahlil, xavfsizlik) |
| **2. MVP uchun kerakmi?** | *Yo'q* deb javob berish uchun **asos** bo'lishi shart |
| **3. Qachon kerak bo'ladi?** | Aniq **trigger** (metrika yoki voqea) |
| **4. Olib tashlansa nima yo'qoladi?** | Halol yo'qotish ro'yxati (+ «hech narsa» ham mumkin) |

### Qabul qilingan uch qoida (MVP filtri)

| Qoida | Mazmuni |
|---|---|
| **Q1. Ball qoidasi** | Element **ballni o'zgartirmasa yoki qonuniy hujjat yaratmasa** — MVP'ga kirmaydi |
| **Q2. Arzon-va-qaytarilmas qoidasi** | Ma'lumot **yig'ish arzon, lekin keyin tiklab bo'lmaydigan** bo'lsa — **yig'iladi** (tahlil kechiktiriladi) |
| **Q3. Bitta dasturchi qoidasi** | Har yangi jadval/endpoint **doimiy xizmat ko'rsatish yuki** (monitoring, zaxira, migratsiya, xato) — 1 kishi uchun bu **qimmat** |

> **Muhim:** «kelajakda kerak bo'lishi mumkin» — bu **rivojlanish sababi emas**.
> Sabab faqat: «ballni o'zgartiradi», «qonuniy talab» yoki «qaytarilmas
> ma'lumot yo'qoladi».

---

## 1. Bir qarashda: 09-hujjat hajmi vs MVP

| Ko'rsatkich | 08/09 taklif qilgan | MVP uchun zarur | Kamayish |
|---|---|---|---|
| Jadvallar (jami) | **68** | **15** (+1 texnik) | **−78%** |
| Javob modeli artefaktlari | **4** (taqdimot, log, proyeksiya, snapshot) | **2** (log, snapshot) | **−50%** |
| Status o'qlari | **3** (capture, score, validity) | **2** (capture, score) | **−33%** |
| Status kodlari | **17** | **8** | **−53%** |
| API endpoint'lar | **15** | **8** | **−47%** |
| Kalibrlash usullari | `classical` + `guessing` + `mean-mean` + `shrinkage` + `jmle` | `classical` + `shrinkage` | **−60%** |
| Psixometrik hisobotlar | 12 ta (fit, DIF, drift, LD, equating…) | **3 ta** (θ/ball, item `b`, oddiy ishonchlilik) | **−75%** |

**Xulosa:** 09-hujjat **texnik jihatdan to'g'ri**, lekin **MVP uchun 4 barobar
og'ir**. Undagi elementlarning ~**22%** MVP'ga tegishli, ~**40%** — PHASE-2,
~**38%** — FUTURE.

```
09-hujjat tarkibining MVP bo'yicha taqsimoti (taxminiy)

MVP    ███████████                     22%
PHASE-2 ████████████████████           40%
FUTURE ██████████████████████████████  38%
```

---

## 2. `docs/09` ni bo'lim-ba-bo'lim qayta baholash

| § | Bo'lim | Tasnif | Qaror / soddalashtirish |
|---|---|---|---|
| §0 | Qamrov va xulosa | **MVP** (meta) | O'zgarishsiz — audit mantig'i to'g'ri |
| §1 | **4 artefakt** (A, B, C, D) | **A → P2**, **B → MVP**, **C → P2**, **D → MVP** | MVP'da **2 artefakt**: log (B) + snapshot (D). Joriy holat = B dagi oxirgi revision (partial indeks bilan) |
| §2 | Autosave yozish yo'li | **MVP** (qisqartirilgan) | MVP: B ga yozish + `attempts.last_seen_at`/`revision`. Telemetriya va C ga yozish yo'q. Idempotentlik (`client_seq`) — MVP ✅ |
| §3 | Immutability/freeze | **MVP** (qisqartirilgan) | B — har doim immutable ✅; D — immutable ✅; *freeze* tushunchasi A va C yo'qligi uchun MVP'da kerak emas (o'rniga: `attempts.status` + `responses` ga yozishni to'xtatish) |
| §4 | 3 o'qli status tizimi | **2 o'q MVP**, `validity_status` → **P2**, `invalid_multiple` → **FUTURE** (OMR) | MVP: `capture_status` (`answered`/`blank`/`not_reached`) + `score_status` (`unscored`/`auto_scored`/`pending_review`/`manual_scored`) |
| §5 | Yagona model (MCQ + open) | **MVP** ✅ | Bu 09 ning **eng qimmatli qarori** — o'zgarishsiz qoladi |
| §6 | Testlet / local dependence | `testlet_ref` + `part` → **MVP**; LD tahlili → **P2**; `answer_chain` → **FUTURE** | MVP faqat **maydonni saqlaydi** (arzon, qaytarilmas), tahlil qilmaydi |
| §7 | Majburiy maydonlar (7.1–7.8) | **~40% MVP**, ~35% P2, ~25% FUTURE | 3-bo'limdagi maydon jadvaliga qarang |
| §8 | Qaytarib bo'lmaydigan ma'lumotlar | **MVP: 6 ta**, P2: 6 ta, FUTURE: 3 ta | Ro'yxat qisqartiriladi (Q2 qoidasi saqlanadi) |
| §9 | 12 invariant | **MVP: 8 ta**, P2: 3 ta, FUTURE: 1 ta | Masalan `I5` (freeze) → P2 |
| §10 | 02/04/08 ga ta'sir | **MVP qismi** ajratiladi | 02 va 04 ni MVP doirasida tahrirlash kifoya |
| §11 | 12 qabul mezoni | **MVP: 8 ta** | Qolgani P2 mezonlari |
| §12 | 6 ochiq qaror | **MVP: 4 ta** | `dwell_ms` chegarasi va telemetriya savoli → P2 |
| §13 | Xulosa | **MVP** (meta) | Qayta yoziladi (MVP fokusida) |

---

## 3. Maydonlar bo'yicha tasnif (09 §7 lug'atlaridan)

Belgilar: **M** = MVP, **P2** = PHASE-2 (3 oy), **F** = FUTURE (1 yildan keyin).
«O'chiriladi» = hujjatdan **butunlay olib tashlanadi** (kerak emas).

### 3.1. B — qabul logi (`responses`)

| Maydon | Tasnif | Izoh |
|---|---|---|
| `response_id`, `attempt_id`, `item_id`, `item_version_id`, `form_item_id`, `session_id`, `form_version_id` | **M** | Identifikatsiya — kalibrlashning asosi |
| `position`, `display_label`, `part` | **M** | UI/hisobot («36a»). Pozitsiya — **faqat taqdimot** |
| `testlet_ref` | **M** | Arzon + qaytarilmas metadata (36a/36b) |
| `part_index` | **P2** | LD tahlilida qulaylik |
| `revision`, `superseded_by` | **M** | Zanjir; «joriy»ni aniqlash |
| `prev_response_id` | **O'chiriladi** | `superseded_by` bilan bir xil ma'lumot (takror) |
| `event_type` | **M** (`capture`/`clear`/`finalize`) | `admin_fix` → P2, `projection_repair` → **F** |
| `capture_status` | **M** (3 qiymat) | `answered` / `blank` / `not_reached` |
| `answer_kind` | **M** | `mcq4`/`mcq6` `numeric`/`text` ni ajratish |
| `selected_option` | **M** | MCQ javobi (`A`…`F`) |
| `raw_answer` | **M** | O'quvchi kiritgani aynan — **qaytarilmas** (Q2) |
| `normalized_answer`, `numeric_value` | **M** | Baholash uchun |
| `answer_payload` | **P2** | `unit`, `fraction_form`, `tokens[]` — hozircha kerak emas |
| `capture_conflicts` | **F** | Faqat OMR/import uchun |
| `input_method` | **P2** | `tap`/`keyboard`/`import` — mode effekti tahlili |
| `source` | **M** | `webapp`/`bot`/`admin`/`system` |
| `client_seq` | **M** | Idempotentlik (tarmoq qayta urinishi) |
| `recorded_at` (server), `created_at` | **M** | Vaqt haqiqati + partition kaliti |
| `captured_at_client` | **P2** | Faqat javob vaqti tahlili uchun |
| `client_clock_skew_ms` | **O'chiriladi** | Server vaqti yetarli; skew murakkablik qo'shadi |
| `request_id` | **P2** | Ops korrelyatsiyasi |
| `ip_hash`, `device_hash` | **P2/F** | Xavfsizlik; `device_hash` → **F** (4.1 ga qarang) |
| `app_version`, `ui_variant` | **P2** | Interfeys o'zgarishi ta'siri |

### 3.2. C — joriy ko'rinish (`attempt_responses_current`)

| Artefakt | Tasnif | Izoh |
|---|---|---|
| Butun jadval | **P2** | MVP: joriy holat = B dagi oxirgi `revision` (partial indeks bilan). 2-jadval faqat yuklama **trigger**iga yetganda qo'shiladi (11-bo'lim) |

### 3.3. A — taqdimot va telemetriya (`attempt_items`)

| Maydon | Tasnif | Izoh |
|---|---|---|
| Butun jadval | **P2** | MVP o'rniga: `attempts` da **3 ta maydon** (`last_interaction_position`, `interaction_count`, `duration_seconds`) |
| `first_presented_at`, `last_presented_at` | **P2** | MVP: `last_interaction_position` bilan taxminiy aniqlanadi |
| `dwell_ms`, `total_dwell_ms` | **P2** | 4.2 ga qarang |
| `change_count` | **M (bepul)** | B dagi revision'lar sonidan hisoblanadi — qo'shimcha saqlash shart emas |
| `first_answer_at`, `final_answer_at`, `time_to_first_answer_ms` | **P2** | B dagi `recorded_at` dan keyin tiklanadi |
| `presentation_count`, `view_order_index`, `navigation_path` | **F** | Xatti-harakat tahlili |
| `focus_loss_count`, `scroll_events` | **F** | Anti-cheat |
| `was_at_end_at_timeout` | **P2** | Speededness tahlili |
| `telemetry_source` | **P2** | Import haqiqati |

### 3.4. D — baholash snapshot'i (`scoring_snapshot_items`)

| Maydon | Tasnif | Izoh |
|---|---|---|
| `snapshot_item_id`, `snapshot_id`, `attempt_id`, `session_id`, `form_version_id`, `form_item_id`, `item_id`, `item_version_id` | **M** | Psixometrik haqiqatning o'zagi |
| `display_label`, `position` | **M** | Hisobot |
| `testlet_ref` | **M** | LD uchun qaytarilmas kontekst |
| `b_used`, `b_source`, `engine_version` | **M** | **Reproducibility / regrade / apellyatsiya** |
| `theta_used` | **M** | `p_hat` ni qayta hisoblashning yagona yo'li (quyida) |
| `key_used`, `key_version_no`, `key_source` | **M** | Kalit tarixi (baholash fakti) |
| `answer_kind`, `raw_answer`, `normalized_answer` | **M** | Audit |
| `score_awarded`, `max_score`, `score_status`, `match_rule` | **M** | Ball |
| `guessing_c` | **M** | `mcq4` 0.25 / `mcq6` 0.1667 — bitta raqam, `b` ga bevosita ta'sir |
| `capture_status` | **M** | `not_reached` ni tahlildan chiqarish |
| `scored_at`, `scored_by` | **M** | Audit |
| `p_hat`, `residual`, `information` | **O'chiriladi** | **Uchtasi ham `theta_used` va `b_used` dan matematik qayta hisoblanadi** (dixotom Rasch). Saqlash — ortiqcha (3-bo'lim izohi, 8-bo'lim) |
| `b_se_used` | **P2** | Hisobot uchun |
| `is_anchor`, `anchor_b` | **P2** | Equating |
| `parameter_set_id` | **P2** | MVP: snapshot `b_used` bilan o'zi yetarli |
| `validity_status`, `validity_flags`, `exclusion_reason` | **P2** | MVP: `attempts.status='invalid'` yetarli |

> **Muhim texnik xulosa (09-hujjatga tuzatish):** `p_hat = 1/(1+e^−(θ−b))`,
> `residual = u − p_hat`, `information = p_hat·(1−p_hat)`. Uchtasi ham
> `θ`, `b`, `u` dan **qayta hisoblanadi**. Ya'ni ularni saqlash **shart emas**
> — Infit/Outfit tahlili `theta_used` + `b_used` + `score_awarded` dan
> istalgan paytda tiklanadi. Bu — 09-hujjatdagi **ortiqcha murakkablik**.

### 3.5. Urinish darajasi (`attempts`)

| Maydon | Tasnif | Izoh |
|---|---|---|
| `attempt_id`, `session_id`, `user_id`, `form_version_id`, `status`, `started_at`, `submitted_at` | **M** | Asos |
| `parameter_set_id` | **P2** | MVP: `scoring_snapshot_items.b_used` yetarli |
| `engine_version` | **M** | Qaysi hisoblash bilan |
| `engine_params` | **P2** | Konstantalar (MVP: `config.py` da muzlatilgan qiymatlar) |
| `scoring_policy_code` | **P2** | MVP: bitta siyosat (hujjatlashtirilgan) |
| `submit_mode` | **M** | `manual` / `auto_timeout` / `admin` — natija izohi uchun |
| `duration_seconds` | **M** | Speededness, `raw_score` izohi |
| `last_interaction_position`, `interaction_count` | **M** | **`not_reached` ni MVP'da arzon aniqlash** (4.3 ga qarang) |
| `raw_score` | **M** | Rasmiy ball |
| `raw_score_strict` | **M** | Solishtirish (deyarli bepul — `not_reached` soni ma'lum) |
| `n_answered`, `n_omitted`, `n_not_reached` | **M** | Hisobot va `p` maxraji (arzon counter) |
| `theta`, `theta_se`, `scaled_score` | **M** | Baholash natijasi (Rasch) |
| `theta_method` | **P2** | MVP: `mle` qat'iy |
| `log_likelihood` | **P2** | Diagnostika |
| `is_extreme_low`, `is_extreme_high` | **M** | «45/45» ga soxta ball bermaslik — **adolat** masalasi |
| `person_infit_mnsq`, `person_outfit_mnsq`, `person_fit_flag` | **P2** | Person fit tahlili |
| `max_score_total`, `score_sum` | **P2** | Polytomous readiness (hozir `max_score_total = n_omitted+…` bilan mos) |
| `level_code` | **P2** | Daraja (A/B/C) — `scales` bilan birga |
| `group_snapshot` | **P2** | MVP: 2 maydon `users` da (4.6) |
| `session_mode` | **P2** | Faqat onlayn rejim bo'lsa kerak emas |
| `device_hash`, `ip_hash` | **F/P2** | 4.1 |
| `deleted_at`, `invalidated_reason` | **M**(`deleted_at`) / **P2**(`invalidated_reason`) | Soft delete — audit talabi |

### 3.6. Agregatlar

| Artefakt | Tasnif | Izoh |
|---|---|---|
| `item_statistics` | **M** | `b` tarixi — 03-hujjat algoritmining chiqishi |
| `item_parameters` | **M** | Joriy operatsion `b` |
| `item_session_counters` | **P2** | MVP: hisoblash to'g'ridan-to'g'ri `responses` dan (pilot hajmida bir necha soniya) |
| `session_statistics` | **P2** | Reliability/θ taqsimoti — MVP hisobotida JSON sifatida «on-the-fly» |
| `item_fit_statistics` | **P2** | Infit/Outfit |
| `person_fit` | **F** | Alohida jadval shart emas (hisoblanadi) |
| `item_drift_checks` | **P2** | Drift — 3-sessiyadan keyin |
| `local_dependence_checks`, `testlet_statistics` | **P2** | LD |
| `score_conversion_tables` | **P2** | MVP: 0–100 chiziqli (config) |

### 3.7. Boshqa jadvallar va boshqa artefaktlar

| Artefakt | Tasnif | Izoh |
|---|---|---|
| `item_parameter_sets`, `item_parameter_set_items` | **P2** | MVP: `b_used` snapshot yetarli |
| `anchor_sets`, `anchor_items` | **P2** | Equating |
| `equating_links`, `equatings` | **P2** | Equating |
| `scales`, `scale_cutoffs` | **P2** | MVP: chiziqli 0–100 + config chegaralari |
| `dif_results`, `dif_stratum_counts` | **P2** | DIF |
| `scoring_reviews` | **P2** | MVP: qo'lda tuzatish → `manual_scored` + `audit_log` |
| `appeals` | **P2** | Jarayon hali yo'q (qonuniy/huquqiy tanlov) |
| `key_reviews` (4-eyes) | **P2** | MVP: bitta admin + `audit_log` |
| `item_types` | **M (config)** | 4 tur — jadval shart emas, kodda konstantalar |
| `item_sources` | **P2** | PDF havolasi/hash (link rot) |
| `item_link_suggestions` | **P2** | Item bog'lash (statistika uzluksizligi) |
| `persons_attributes` | **P2** | MVP: `users` da 2 maydon (4.6) |
| `exam_centers`, `staff_roles`, `certificates` | **F** | Markazlar, rollar matritsasi, sertifikat hujjati |
| `topics`, `tags`, `item_tags` | **P2/F** | Mavzu tahlili (P2), teglar (F) |
| `notification_outbox` | **P2** | MVP: to'g'ridan-to'g'ri yuborish + oddiy retry |
| `bot_updates` | **P2** | Telegram idempotentligi |
| `idempotency_keys` | **O'chiriladi** | `client_seq` MVP'da qoplaydi |
| `rate_limit_counters` | **P2** | Rate limit (xotirada ham mumkin) |
| `report_renders` | **F** | PDF hisobot navbati |
| `quality_checks` | **P2** | Kunlik DQ tekshiruvi |
| `schema_migrations` | **M** | Texnik (majburiy) |
| `audit_log` | **M** | Majburiy talab |
| `result_versions` | **M** | «Regrade eski natijani almashtirmaydi» talabi |
| `item_status_history` | **P2** | Item lifecycle tarixi |
| `attempt_events` | **P2** | Coarse hodisa izi |

### 3.8. API endpoint'lar

| # | Endpoint | Tasnif |
|---|---|---|
| 1 | Sessiyani kod bo'yicha tekshirish | **M** |
| 2 | Urinishni boshlash/tiklash (idempotent) | **M** |
| 3 | Javobni saqlash (autosave, item-level) | **M** |
| 4 | Holatni olish (`state`) | **M** |
| 5 | Yakunlash (`submit`) | **M** |
| 6 | Natijani olish | **M** |
| 7 | Forma yaratish (kalit + jadval) | **M** (bot orqali) |
| 8 | Admin: item statistikasi / kalibrlashni ishga tushirish | **M** (bot orqali) |
| 9 | Telemetriya yuborish | **P2** (4.2) |
| 10 | Qo'lda ko'rik navbati | **P2** |
| 11 | Kalibrlash run statistikasi (batafsil) | **P2** |
| 12 | DIF/drift hisobotlari | **P2** |
| 13 | Anchor/equating boshqaruvi | **P2** |
| 14 | Audit log so'rovi | **P2** |
| 15 | PDF hisobot | **F** |

---

## 4. Alohida baholangan 12 element

### 4.1. `device_hash`

| Savol | Javob |
|---|---|
| **1. Vazifa** | Bir qurilmani (brauzer profili) takroriy aniqlash: bir qurilmadan ko'p akkaunt, javob almashish, klaster tahlili |
| **2. MVP uchun?** | **Yo'q.** MVP'da dublikat urinish `attempts` dagi unikal (sessiya + o'quvchi) cheklovi bilan to'siladi |
| **3. Qachon** | Sessiya hajmi **5 000+** bo'lganda yoki firibgarlik shikoyati kelganda (PHASE-2 oxiri) |
| **4. Yo'qotish** | Klaster tahlilining **o'tgan davr uchun** imkoni (qaytarilmas). Ammo: qurilma hash **o'sha qurilmadan keyin ham qayta yig'ilmaydi** |

**Izoh:** MVP'da **hech narsa yo'qotilmaydi**, chunki hozir «bir qurilma — bir urinish» siyosati yo'q. Firibgarlik siyosati paydo bo'lganda qurilma hash o'sha kundan boshlab yig'ila boshlaydi. Maxfiylik nuqtai nazaridan ham bu **kechiktirish foydali**: PII saqlash majburiyati kamayadi.

### 4.2. Telemetriya (umumiy tushuncha: taqdimot/harakat logi)

| Savol | Javob |
|---|---|
| **1. Vazifa** | «Savol ekranga chiqdimi, qancha vaqt ko'rildi, qanday harakat qilindi» ni yozish |
| **2. MVP uchun?** | **Qisman emas** — MVP'da butun telemetriya jadvali kerak emas. **Faqat 2 ta maydon** (`last_interaction_position`, `duration_seconds`) `attempts` da saqlanadi |
| **3. Qachon** | `dwell_ms`/speededness tahlili kerak bo'lganda (PHASE-2, sessiya soni ≥ 3) |
| **4. Yo'qotish** | Item darajasidagi harakat tarixi (navigatsiya, ko'rish tartibi, fokus yo'qotish). **Javob vaqti taxminan** B dagi `recorded_at` zanjiridan qoladi |

**Izoh (muhim):** MVP'da **javob vaqti ma'lumoti bepul keladi** — append-only log har bir o'zgarishning **server vaqtini** yozadi. Ya'ni «7-savolga qancha vaqt sarflandi» **keyin taxminan tiklanadi** (birinchi va oxirgi revision orasidagi vaqt). Telemetriya jadvali buni **aniq** qiladi, lekin MVP uchun **taxminiy yetarli**.

### 4.3. `dwell_ms`

| Savol | Javob |
|---|---|
| **1. Vazifa** | «Savol ekranda qancha turdi» — `omitted` va `not_reached` ni ajratish, speededness, javob vaqti tahlili |
| **2. MVP uchun?** | **To'liq shaklda yo'q.** MVP'da `last_interaction_position` + `duration_seconds` bilan **taxminiy** aniqlanadi |
| **3. Qachon** | Vaqtli test **haqiqatan** speeded bo'lsa (PHASE-2, `not_reached > 10%` aniqlanganda) |
| **4. Yo'qotish** | Aniq chegara (2000 ms) bilan ajratish; «5 soniya ko'rib tashlab ketdi» va «umuman ko'rmadi» farqi |

**Izoh:** MVP'dagi arzon yechim: test tugaganda `last_interaction_position` dan **keyingi** barcha savollar **`not_reached`** deb belgilanadi (ya'ni «oxirgi ishlagan savolidan keyin hech narsaga tegmagan»). Bu **95% holatda to'g'ri** va **bitta maydon** evaziga olinadi. Aniq `dwell_ms` esa faqat «sakrab ishlash» holatlarida farq qiladi.

### 4.4. Focus tracking (ilovadan chiqib ketish)

| Savol | Javob |
|---|---|
| **1. Vazifa** | Ilova fon rejimiga o'tganini yozish — firibgarlik signali, diqqat tahlili |
| **2. MVP uchun?** | **Yo'q** |
| **3. Qachon** | Firibgarlik nazorati siyosati joriy etilganda (FUTURE) |
| **4. Yo'qotish** | Diqqat buzilishi tarixi. **Ball, kalibrlash va natijaga ta'siri yo'q** |

**Izoh:** Focus tracking **qaror qabul qilish uchun emas** — u faqat dalil (evidence) to'plash uchun. Milliy Sertifikatda test odatda **nazorat ostida** (markazda) o'tkaziladi yoki natija faqat ma'lumot uchun. Shu sababli **FUTURE**ga to'g'ri keladi.

### 4.5. Scroll tracking

| Savol | Javob |
|---|---|
| **1. Vazifa** | «Qaysi savolga qanday o'tdi» — navigatsiya tartibi, sakrab ishlash patterni |
| **2. MVP uchun?** | **Yo'q** |
| **3. Qachon** | Interfeys optimizatsiyasi va xatti-harakat tadqiqoti kerak bo'lganda (FUTURE) |
| **4. Yo'qotish** | Navigatsiya patterni. **Ball va kalibrlashga ta'siri yo'q** |

**Izoh:** Scroll ma'lumoti **qimmat** (har harakat), foydasi esa **bilvosita**. Bitta dasturchi uchun bu **sof yuk**. Kerak bo'lsa, PHASE-2 da oddiy `view_order_index` (savol qaysi tartibda ko'rildi) yetarli bo'ladi — to'liq scroll tarixi shart emas.

### 4.6. `answer_chain` (36b 36a ga bog'liq)

| Savol | Javob |
|---|---|
| **1. Vazifa** | Zanjirli savollarni belgilash: ikkinchi qism faqat birinchi qism to'g'ri bo'lganda mazmunli |
| **2. MVP uchun?** | **Yo'q.** MVP'da `testlet_ref` **saqlanadi** (arzon), lekin zanjir **mantiqi** qo'llanilmaydi |
| **3. Qachon** | Kalibrlash boshlanganda (PHASE-2) — ekspert zanjirli juftliklarni belgilagach |
| **4. Yo'qotish** | Zanjirli juftliklarning `b` i sun'iy yuqori chiqadi (LD buzilishi). **Natija to'g'ri qoladi**, faqat `b` biroz xato bo'ladi |

**Izoh:** Bu **eng xavfli «kechiktirish»**: `b(36b)` sun'iy yuqori bo'lib, `θ` hisobida ozgina xato beradi. Lekin MVP'da `b` qiymatlari **hali `0.0`** (yoki juda kam ma'lumotdan) — ya'ni **xato hali sezilarli emas**. Kalibrlash **haqiqiy** boshlanganda (PHASE-2) zanjir qoidasi kiritilishi shart. Shu sababli: **maydonni hoziroq qo'shish (arzon), mantiqni keyin**.

### 4.7. `quarantined` statusi

| Savol | Javob |
|---|---|
| **1. Vazifa** | Shubhali urinishni **hamma joydan** (kalibrlash, hisobot, natija) chiqarib turish |
| **2. MVP uchun?** | **Yo'q.** MVP'da `attempts.status = 'invalid'` + `deleted_at` **yetarli** |
| **3. Qachon** | Firibgarlik/texnik nosozlik ommaviy bo'lganda (PHASE-2) |
| **4. Yo'qotish** | «Chiqarildi, lekin o'chirilmadi» degan oraliq holat. MVP'da bu `audit_log` + `deleted_at` bilan ifodalanadi |

**Izoh:** Status o'qlarini **ko'paytirish** — eng oson «murakkablik tuzog'i». 3 ta qiymat (`valid`/`invalid`/`quarantined`) bitta qarorni 4 joyda tekshirishga olib keladi (API, kalibrlash, hisobot, bot). MVP uchun **bitta bayroq** (`attempts.status`) yetarli.

### 4.8. `projection_repair`

| Savol | Javob |
|---|---|
| **1. Vazifa** | Joriy holat (C) logdan (B) farq qilib qolsa, tuzatish izini qoldirish |
| **2. MVP uchun?** | **Yo'q** — chunki MVP'da **C jadvali yo'q** |
| **3. Qachon** | C jadvali qo'shilgandan keyin (PHASE-2) **va** qo'lda tuzatish ehtiyoji paydo bo'lganda |
| **4. Yo'qotish** | Hech narsa: MVP'da joriy holat har doim **logdan o'qiladi**, ya'ni tuzatish talab qilinmaydi |

**Izoh:** Bu — 09-hujjatdagi **eng ortiqcha** elementlardan biri. U **ikki qatlamli modelning yon mahsuloti**: ikki nusxa bo'lmasa, tuzatish ham kerak emas. MVP'da `state` so'rovi logdan o'qiydi → **manba bitta** → nomuvofiqlik **mumkin emas**.

### 4.9. OMR integratsiyasi (qog'oz javob varaqlarini skanerlash)

| Savol | Javob |
|---|---|
| **1. Vazifa** | Qog'ozda to'ldirilgan javob varaqlarini skanerdan o'qib, tizimga kiritish (hududiy/oflayn imtihon) |
| **2. MVP uchun?** | **Yo'q.** Berilgan jarayonda javoblar **faqat Web App** orqali keladi |
| **3. Qachon** | Hududiy (oflayn) imtihonlar **haqiqatan** boshlanganda (FUTURE) |
| **4. Yo'qotish** | Hech narsa — hozir bunday oqim yo'q. Kelajakda kerak bo'lsa, `source = 'omr'` qiymati va `capture_conflicts` maydoni **o'sha paytda** qo'shiladi |

**Izoh:** OMR — **butunlay boshqa loyiha** (rasm tahlili, blank dizayni, kalibrlash, operator paneli). Uni MVP'ga «ehtiyot uchun» qo'shish — bitta dasturchini cho'ktiradigan **eng katta tuzoq**. Muhim nuance: kelajakda OMR ma'lumoti Web App ma'lumotidan **boshqa sifatga** ega bo'ladi (mode) — shuning uchun `source` maydoni MVP'da borligi yaxshi (arzon kelajak tayyorgarligi).

### 4.10. Fraud detection (firibgarlikni aniqlash)

| Savol | Javob |
|---|---|
| **1. Vazifa** | Shubhali urinishlarni avtomatik belgilash (qurilma klasteri, g'ayrioddiy tez javoblar, bir xil xato patterni) |
| **2. MVP uchun?** | **Yo'q** |
| **3. Qachon** | Imtihon **masofadan** va `katta hajmda` (10 000+) o'tkazilganda (PHASE-2 → FUTURE) |
| **4. Yo'qotish** | Avtomatik signal yo'q. Ammo **asosiy himoya MVP'da bor**: bitta urinish/sessiya, kalit serverda yashirin, javoblar item darajasida, `audit_log` |

**Izoh:** Firibgarlik — **siyosat + statistika** masalasi, kod masalasi emas. MVP'da:
(a) test **kanal orqali PDF** tarqatiladi (allaqachon nazoratsiz),
(b) natija — **o'quvchi o'zini baholashi** (rasmiy sertifikat emas).
Shu sababli firibgarlik ehtimoli **past**, uni avtomatlashtirish esa **qimmat**. PHASE-2 da yetarli: «bir qurilmadan N urinish» oddiy hisobot + admin ko'rigi (murakkab model shart emas).

### 4.11. Local dependence metadata

| Savol | Javob |
|---|---|
| **1. Vazifa** | 36a/36b kabi juftliklarni bog'lash va LD (lokal bog'liqlik) ni nazorat qilish |
| **2. MVP uchun?** | **Faqat maydonlar**: `testlet_ref` + `part` (`items`/`item_versions` va `responses` da). **Tahlil yo'q** |
| **3. Qachon** | Kalibrlash haqiqiy boshlanganda (PHASE-2): `residual_corr` hisoblanadi, kerak bo'lsa juftlik kalibrlashdan chiqariladi |
| **4. Yo'qotish** | LD tahlilining **o'tgan davr** uchun imkoni — agar `testlet_ref` saqlanmasa (**qaytarilmas**) |

**Izoh — MVP uchun aniq talab:** `testlet_ref` **saqlanishi shart** (arzon, bir marta kiritiladi, keyin tiklanmaydi). Lekin LD **hisoblash**, siyosatlar (`drop_second`/`bundle_testlet`) va `local_dependence_checks` jadvali — **PHASE-2**. Ya'ni: **ma'lumot bugun, qaror keyin**.

### 4.12. Advanced audit workflows (4-eyes kalit, apellyatsiya, rollar matritsasi)

| Savol | Javob |
|---|---|
| **1. Vazifa** | Kalitni ikki kishi tekshirishi, apellyatsiya jarayoni, ko'p bosqichli tasdiqlash, rol matritsasi |
| **2. MVP uchun?** | **Juda qisqartirilgan shaklda**: bitta admin + `audit_log` (kim, qachon, nimani o'zgartirdi) |
| **3. Qachon** | `key_reviews`/4-eyes → PHASE-2 (o'qituvchilar soni ≥ 2 bo'lganda); `appeals` → PHASE-2 (rasmiy jarayon joriy etilganda); rollar matritsasi → FUTURE |
| **4. Yo'qotish** | Kalit xatosi **odam nazoratisiz** qoladi — bu **eng katta operatsion xavf** (03-hujjat: kalit xatosi = barcha natijalar buziladi) |

**Izoh va muhim ogohlantirish:** bu yerda **soddalashtirish xavfli**. 4-eyes jarayonning **texnik qismi arzon** (bitta `key_reviews` jadval + tasdiqlash tugmasi), lekin u **kalit xatosi** degan yagona halokatli xatoni kamaytiradi. Shuning uchun tavsiya:

| Element | Tavsiya |
|---|---|
| `audit_log` | **MVP** (majburiy) |
| **Kalitni matn ko'rinishida ko'rib chiqish + qayta terish (double-entry)** | **MVP** — arzon, kuchli: kalit ikki marta kiritiladi, farq bo'lsa qabul qilinmaydi (jadval kerak emas!) |
| `key_reviews` (4-eyes, ikki xil odam) | **PHASE-2** |
| `appeals` | **PHASE-2** |

---

## 5. Natija 1 — «Minimal Milliy Sertifikat MVP»

### 5.1. Maqsad (bir jumlada)

> O'quvchi PDF dan ishlaydi, kartochkalarda javob belgilaydi, Rasch bo'yicha
> θ oladi; **hech bir javob yo'qolmaydi**, **hech bir natija keyin o'zgarmaydi**,
> va tizim **kalibrlash uchun kerakli xom ma'lumotni yig'ib boradi**.

### 5.2. Jadvallar (15 + 1 texnik)

| # | Jadval | Vazifa |
|---|---|---|
| 1 | `users` | O'quvchi + **2 arzon DIF maydoni** (`region_code`, `language_code`) |
| 2 | `items` | Global `item_id`, `item_ref`, `testlet_ref` |
| 3 | `item_versions` | Kalit, `item_type`, `answer_spec`, versiya |
| 4 | `forms` | Test kodi + metadata |
| 5 | `form_versions` | Kalit snapshot'i |
| 6 | `form_items` | Pozitsiya → item_version (taqdimot) |
| 7 | `exam_sessions` | Vaqt oynasi (boshlanish/tugash/natija) |
| 8 | `attempts` | Urinish + θ + hisoblagichlar + `last_interaction_position` |
| 9 | `responses` | **Append-only qabul logi** (asosiy haqiqat) |
| 10 | `item_parameters` | Joriy operatsion `b` (versiyalangan) |
| 11 | `item_statistics` | `p`, `b`, `SE`, `flags` tarixi |
| 12 | `scoring_snapshots` | Urinish darajasidagi baholash snapshot'i |
| 13 | `scoring_snapshot_items` | **Item darajasidagi muzlatilgan baholash** |
| 14 | `result_versions` | Natija versiyalari (regrade eskisini o'zgartirmaydi) |
| 15 | `audit_log` | Kim, qachon, nimani o'zgartirdi |
| +1 | `schema_migrations` | Texnik |

### 5.3. Statuslar (8 kod, 2 o'q)

| O'q | Kodlar | Izoh |
|---|---|---|
| `capture_status` | `answered` / `blank` / `not_reached` | `blank` = `omitted` + `cleared` birlashtirilgan |
| `score_status` | `unscored` / `auto_scored` / `pending_review` / `manual_scored` | `pending_review` = qo'lda ko'rik kutilmoqda |

Hosilaviy `response_status` (API/UI uchun): `answered`, `blank`, `not_reached`,
`pending_review`, `manual_scored` — **5 ta**.

### 5.4. API (8 endpoint)

6 o'quvchi endpoint'i (tekshirish, boshlash/tiklash, javob saqlash, holat,
yakunlash, natija) + 2 admin amali (**bot orqali**: forma yaratish, item
statistikasi/kalibrlash). Telemetriya endpoint'i **yo'q**.

### 5.5. Bot komandalari (7)

`/start`, `/app`, `/new_form` (test kodi + kalit + vaqt — **`b` so'ralmaydi**),
`/forms`, `/stats`, `/item <n>`, `/calibration`.

**Kalit uchun MVP talabi (double-entry):** kalit **ikki marta** kiritiladi
(bot qayta so'raydi yoki ikki satr sifatida); farq bo'lsa **qabul qilinmaydi**.
Bu — 4-eyes jarayonining **narxi nol** bo'lgan muqobili.

### 5.6. Algoritmlar (faqat 2 ta)

| Algoritm | Tarkib | Manba |
|---|---|---|
| **Baholash (θ)** | MLE + Newton-Raphson (mavjud `rasch.py`), ekstremal holat bayrog'i | `docs/01`/`03` — tayyor |
| **Qiyinchilik (`b`)** | `p̂` (Jeffreys) → `b_raw` → `c₀ = 1/k` tuzatish → guruh o'rtachasi (mean-mean) → shrinkaj → chegara | `docs/03` — tayyor |

**MVP'da YO'Q:** JMLE, anchor items, equating, parameter sets, drift, item fit,
person fit, DIF, LD siyosatlari, 2PL/3PL.

### 5.7. UI (Web App)

| Savol turi | Interfeys |
|---|---|
| 1–32 (`mcq4`) | `1 [A][B][C][D]` kartochka |
| 33–35 (`mcq6`) | `33 [A][B][C][D][E][F]` kartochka |
| 36–45 (`numeric`) | `36a [____]` va `36b [____]` input kartochkalari |
| Umumiy | Autosave (700 ms debounce + localStorage + navbat), timer, progress, «belgilanmaganlar», refresh'dan tiklash |

### 5.8. MVP'da majburiy 6 ta sifat talabi

| # | Talab | Nega |
|---|---|---|
| 1 | Javob **hech qachon yo'qolmaydi** (refresh, tarmoq, fon rejimi) | O'quvchi ishonchi |
| 2 | **`not_reached`** `last_interaction_position` bilan aniqlanadi | θ va `b` xatosining oldini olish |
| 3 | **Kalit va `b` snapshot'i** item darajasida muzlatiladi | Apellyatsiya/regrade |
| 4 | **Ikki xom ball** (`raw_score`, `raw_score_strict`) | Shaffoflik, bahsli holat |
| 5 | **Ekstremal holat** («45/45») alohida ko'rsatiladi | Adolat |
| 6 | Eski natija **hech qachon o'zgarmaydi** (yangi `result_version`) | Audit talabi |

---

## 6. Natija 2 — «3 oy ichida qo'shiladigan narsalar» (PHASE-2)

**Shart:** faqat quyidagi **trigger**lardan biri bajarilsa qo'shiladi
(taxminiy hajm — 1 dasturchi).

### 6.1. Ishonchlilik va psixometriya

| # | Element | Trigger | Taxminiy hajm | Foyda |
|---|---|---|---|---|
| 1 | **Telemetriya jadvali** (`attempt_items`) + `dwell_ms` | `not_reached > 10%` yoki javob vaqti tahlili kerak | 3–4 kun | Speededness, aniq `omitted`/`not_reached` |
| 2 | **Incremental hisoblagichlar** (`item_session_counters`) | Sessiyada **5 000+** urinish | 2–3 kun | Kalibrlash sekundlarga tushadi |
| 3 | **Sessiya statistikasi** (`session_statistics`) + Reliability | 3 sessiyadan keyin hisobot kerak | 2 kun | `R`, `SEM`, θ taqsimoti |
| 4 | **Item fit** (`item_fit_statistics`) | Kalibrlash ishga tushgach | 2–3 kun | Buzuq savollarni topish |
| 5 | **Drift tekshiruvi** (`item_drift_checks`) | Bir item 3+ sessiyada ishlatilgach | 2 kun | Vaqt bo'yicha o'zgarish |
| 6 | **LD tekshiruvi** (`local_dependence_checks`) | Kalibrlash + `testlet_ref` to'ldirilgach | 3 kun | 36a/36b muammosini aniqlash |
| 7 | **`answer_chain` siyosati** | LD `> 0.30` chiqqach | 1–2 kun | `b` ning sun'iy o'sishini tuzatish |
| 8 | **Parameter sets + `item_parameter_set_items`** | `b` ning bir necha versiyasi paydo bo'lgach | 3 kun | Snapshot/equating asosi |
| 9 | **Anchor items + equating (mean-mean)** | Bir item ikki formada ishlatilgach | 5–7 kun | Formalar taqqoslanadi |
| 10 | **`scales` + `scale_cutoffs`** | Daraja (A/B/C) talab qilinganda | 2–3 kun | Rasmiy daraja |

### 6.2. Operatsiya va jarayon

| # | Element | Trigger | Hajm |
|---|---|---|---|
| 11 | **`notification_outbox`** | Natijani yuborishda xatolar bo'lgach | 2 kun |
| 12 | **`bot_updates`** (idempotentlik) | Takroriy `/start` hodisalari bo'lgach | 1 kun |
| 13 | **`scoring_reviews`** (qo'lda ko'rik navbati) | `pending_review` 100+ bo'lgach | 3 kun |
| 14 | **`key_reviews`** (4-eyes) | Adminlar soni ≥ 2 bo'lgach | 2 kun |
| 15 | **`appeals`** | Rasmiy apellyatsiya joriy etilganda | 4–5 kun |
| 16 | **`item_link_suggestions`** | Item statistikasi «bo'linib» ketayotgani ko'rinsa | 4–5 kun |
| 17 | **`item_sources`** (PDF havolasi/hash) | PDF posti o'chirilish holati bo'lgach | 1 kun |
| 18 | **`persons_attributes`** (to'liq DIF jadvali) | DIF tahlili rejalashtirilganda | 2 kun |
| 19 | **Proyeksiya jadvali** (`…current`) | Yozish yuklamasi **> 800 req/s** bo'lgach | 3–4 kun |
| 20 | **`quality_checks`** (kunlik DQ) | Sessiyalar soni 10+ bo'lgach | 2 kun |

### 6.3. PHASE-2 ning **yakuniy natijasi** (3 oydan keyin)

> Kalibrlash **haqiqiy** ishlaydi (`b` yangilanadi, fit/drift/LD hisoblanadi),
> natija **ishonchlilik ko'rsatkichi** va **daraja** bilan beriladi,
> formalar **equating** orqali taqqoslanadi.

---

## 7. Natija 3 — «1 yildan keyin kerak bo'lishi mumkin» (FUTURE)

| # | Element | Qachon mantiqiy | Hozir nima qilinadi |
|---|---|---|---|
| 1 | **DIF** (hudud/til bo'yicha) | 10 000+ urinish, hududiy taqsimot yetarli bo'lganda | **2 maydon yig'iladi** (`region_code`, `language_code`) |
| 2 | **Firibgarlik hisobotlari** + `device_hash` | Masofaviy imtihon kengayganda | `attempts` unikal cheklovi yetarli |
| 3 | **OMR / qog'oz integratsiyasi** | Hududiy oflayn imtihonlar boshlanganda | `source` maydoni bor (arzon tayyorgarlik) |
| 4 | **Focus / scroll tracking** | Xatti-harakat tadqiqoti kerak bo'lganda | Kerak emas |
| 5 | **`projection_repair` va 2-qatlamli model** | 100 000+ foydalanuvchi/sessiya | Trigger-based (11-bo'lim) |
| 6 | **`certificates`** (sertifikat hujjati + verifikatsiya) | Rasmiy sertifikat berish joriy etilganda | Natija varaqasi (bot/Mini App) |
| 7 | **`staff_roles`** (roller matritsasi) | Jamoa 5+ kishiga yetganda | `ADMIN_IDS` konfiguratsiya |
| 8 | **`exam_centers`, `topics`, `tags`** | Markaziy/mavzuli tahlil kerak bo'lganda | — |
| 9 | **PDF hisobot** (`report_renders`) | Ommaviy yuklab olish talab qilinganda | Yon-javob: bot xabari |
| 10 | **Exposure nazorati** | Item bank 1 000+ bo'lganda | `n_presented` allaqachon hisoblanadi |
| 11 | **2PL / 3PL** (diskriminatsiya, taxmin) | 1PL modeli mos kelmasligi aniqlanganda | `guessing_c` saqlanadi |
| 12 | **Milliy shkala hisoboti** (yillar bo'yicha) | Equating 2+ yil ishlagach | — |

> **Adaptive (CAT) test** — **qamrovdan tashqarida** (savollar PDF da, oldindan
> belgilangan). FUTURE ro'yxatiga ham kirmaydi.

---

## 8. Natija 4 — Hozirgi hujjatdagi **ortiqcha murakkablashtirilgan** qismlar

`docs/09` (va qisman `docs/08`) dan **MVP'ga tushmasligi kerak** bo'lgan
elementlar — **sababi bilan**:

| # | Element (09 da) | Nega ortiqcha | Soddalashtirish |
|---|---|---|---|
| 1 | **4 artefakt** (A, B, C, D) | MVP hajmida 2 qatlam yetarli | **2 artefakt**: log (B) + item snapshot (D) |
| 2 | **`p_hat`, `residual`, `information`** saqlash | Uchtasi `θ`, `b`, `u` dan **formula bilan** hisoblanadi | Saqlanmaydi — tahlil paytida hisoblanadi |
| 3 | **`attempt_responses_current`** jadvali | Pilot hajmida partial indeks ham bemalol ishlaydi | **P2** (trigger: >800 req/s) |
| 4 | **`projection_repair`** hodisasi | Ikki nusxa bo'lmasa — tuzatish ham kerak emas | Butunlay olib tashlanadi |
| 5 | **`validity_status`** (4 qiymat) | `attempts.status` + `deleted_at` yetarli | MVP: bitta bayroq |
| 6 | **`item_parameter_sets`** + `item_parameter_set_items` | Snapshot `b_used` bilan qoplanadi | **P2** |
| 7 | **`item_session_counters`** | 5 000 urinishgacha full-scan bir necha soniya | **P2** (trigger: 5 000+) |
| 8 | **`session_statistics`** jadvali | Hisobot uchun on-the-fly hisoblash yetarli | **P2** |
| 9 | **`testlet_statistics`** + `local_dependence_checks` | Kalibrlash boshlanmagan | **P2** |
| 10 | **`answer_payload`** (JSON) | `unit`/`fraction_form` hozircha ishlatilmaydi | **P2** |
| 11 | **`client_clock_skew_ms`** | Server vaqti yetarli | Olib tashlanadi |
| 12 | **`prev_response_id`** | `superseded_by` bilan takror | Olib tashlanadi |
| 13 | **Telemetriya tier-1/tier-2** tushunchasi | Telemetriya jadvalining o'zi MVP'da yo'q | **P2** |
| 14 | **`idempotency_keys`** jadvali | `client_seq` qoplaydi | Olib tashlanadi |
| 15 | **`attempt_events`** (alohida jadval) | MVP'da `audit_log` + `attempts` maydonlari yetarli | **P2** |
| 16 | **`scoring_policy_code`** | MVP: bitta siyosat, hujjatda yozilgan | **P2** |
| 17 | **6 ta ochiq savol** (09 §12) | Uchtasi P2 elementlariga tegishli | **4 ta** qoladi |
| 18 | **`persons_attributes`** jadvali | 2 maydon `users` da yetarli | **P2** |
| 19 | **12 qabul mezoni** | Uchtasi P2 da tekshiriladi | **8 ta** |
| 20 | **`engine_params`** (JSON) | MVP: konstantalar `config.py` da | **P2** |

**Umumiy xulosa:** `docs/09` — **yaxshi kelajak xaritasi**, lekin
**MVP spetsifikatsiyasi emas**. Uning **1, 2, 4, 11, 12, 14, 17** bandlari
**hoziroq** olib tashlanishi kerak (sabab: **matematik ortiqchalik** yoki
**takroriy maydon**).

---

## 9. Natija 5 — Hozir **implementatsiya qilinmasligi kerak** bo'lgan elementlar

### 9.1. Mutlaqo taqiqlangan (MVP doirasida)

| # | Element | Nega hozir emas |
|---|---|---|
| 1 | **OMR / skaner integratsiyasi** | Boshqa loyiha; hozir oqim yo'q |
| 2 | **Firibgarlikni avtomatik aniqlash** | Siyosat + statistika; MVP'da ehtimol past |
| 3 | **Focus / scroll / navigatsiya telemetriyasi** | Qimmat, ballga ta'siri yo'q |
| 4 | **`device_hash` va qurilma klasteri** | Maxfiylik + ehtiyoj yo'q |
| 5 | **`projection_repair` / ikki nusxali proyeksiya** | MVP'da kerak emas (manba bitta) |
| 6 | **DIF hisobotlari** | 10 000+ urinish kerak (ma'lumot hali yo'q) |
| 7 | **Equating / anchor boshqaruvi** | Item qayta ishlatilishi hali yo'q |
| 8 | **JMLE Rasch kalibrlash** | `N ≥ 200` hali to'planmagan |
| 9 | **2PL / 3PL** | 1PL yetarli |
| 10 | **Adaptiv (CAT) test** | PDF formati saqlanadi — **qamrovdan tashqarida** |
| 11 | **Sertifikat hujjati (`certificates`)** | Rasmiy jarayon yo'q |
| 12 | **Rollar matritsasi (`staff_roles`)** | `ADMIN_IDS` yetarli |
| 13 | **PDF hisobot generatori** | Bot xabari + Mini App yetarli |
| 14 | **Exposure nazorati** | Item bank kichik |
| 15 | **PostgreSQL partitioning / read-replica** | Pilot hajmida kerak emas |
| 16 | **`quality_checks` / DQ dashboard** | Sessiya soni kam |
| 17 | **`topics`, `tags`, `item_tags`** | Mavzu tahlili talab qilinmagan |
| 18 | **`exam_centers`** | Markazlar hali yo'q |

### 9.2. «Kechiktirish shart» ro'yxati (ma'lumot yig'iladi, mantiq yo'q)

| Element | Ma'lumot (bugun) | Mantiq (keyin) |
|---|---|---|
| `testlet_ref` | ✅ saqlanadi | LD tahlili — PHASE-2 |
| `region_code`, `language_code` | ✅ saqlanadi | DIF — FUTURE |
| `guessing_c` | ✅ saqlanadi | 3PL — FUTURE |
| `source = 'omr'` qiymati (kelajak) | ✅ konfiguratsiyada bor | OMR — FUTURE |
| `raw_answer` | ✅ saqlanadi | Qo'lda ko'rik — PHASE-2 |
| `b_used`, `key_used`, `theta_used` | ✅ saqlanadi | Fit/DIF/equating — PHASE-2 |

> Bu — Q2 qoidasining amalda qo'llanishi: **arzon va qaytarilmas** ma'lumot
> **hoziroq** yig'iladi, lekin **uni ishlatadigan murakkab mantiq** keyinga
> qoldiriladi. Shu bilan MVP **sodda**, kelajak esa **ochiq** qoladi.

---

## 10. Bitta dasturchi uchun **murakkablik byudjeti**

### 10.1. Qat'iy chegaralar (MVP)

| O'lchov | Chegara | Hozir reja |
|---|---|---|
| Jadvallar | **≤ 16** | 15 (+1 texnik) ✅ |
| API endpoint | **≤ 8** | 8 ✅ |
| Xizmat moduli (`services/`) | **≤ 6** | 5 (`rasch`, `difficulty`, `scoring`, `answer_key`, `exam_service`) ✅ |
| Kalibrlash algoritmi | **≤ 2** | 2 (θ, `b`) ✅ |
| Fon vazifa (worker) | **≤ 1** | 1 (baholash + kalibrlash birgalikda) ✅ |
| Hujjat/status kod | **≤ 8** | 8 ✅ |
| Yangi bog'liqlik (kutubxona) | **≤ 1** | 0 (mavjudlari yetarli) ✅ |

### 10.2. Boshqaruv qoidalari

| Qoida | Mazmuni |
|---|---|
| **B1** | Yangi jadval qo'shish uchun **javobgarlikni asoslash** kerak: «bu jadval bo'lmasa qaysi **ball** yoki **qonuniy hujjat** yo'qoladi?» |
| **B2** | Yangi jadval qo'shilsa — **bittasi P2'ga suriladi** (sof o'sish bo'lmasin) |
| **B3** | Har bir kechiktirilgan elementda **trigger** (metrika) bo'lishi shart; triggersiz kechiktirish — **tugatilmagan ish** |
| **B4** | **2 kundan** ortiq ish talab qiladigan funksiya MVP'ga **kirmaydi** (Q1 qoidasi istisno) |
| **B5** | Har **3 oyda** trigger'lar ko'rib chiqiladi; **faqat bajarilgan** trigger P2 ishini boshlaydi |
| **B6** | Optimizatsiya (proyeksiya, keshlash, partition) — **o'lchovdan keyin**, oldindan emas |
| **B7** | Har yangi maydon: «bu maydon keyin tiklanadimi?» — agar **ha** bo'lsa, kechiktiriladi |

### 10.3. Trigger jadvali (bitta ko'rinishda)

| Trigger (metrika/voqea) | Nima yoqiladi |
|---|---|
| Sessiyada **5 000+** urinish | `item_session_counters`, `session_statistics` |
| Yozish **> 800 req/s** | Proyeksiya jadvali (`…current`) |
| **`not_reached` > 10%** | Telemetriya + `dwell_ms` |
| **`pending_review` > 100** | `scoring_reviews` (ko'rik navbati) |
| **Adminlar ≥ 2** | `key_reviews` (4-eyes) |
| **Bir item 3+ sessiyada** ishlatilgan | `item_statistics` tarixidan drift, anchor nomzodlari |
| **`N ≥ 200`, `SE ≤ 0.25`** | `frozen` `b` → anchor |
| **Ikki formada bir xil item** | `anchor_items` + equating |
| **Statistika «bo'linib» ketayotgani** ko'rinsa | `item_link_suggestions` |
| **Apellyatsiya jarayoni e'lon qilinsa** | `appeals` |
| **10 000+ urinish** va hududiy ma'lumot yetarli | DIF hisobotlari |
| **Rasmiy sertifikat** talab qilinsa | `certificates` |
| **Hududiy oflayn imtihon** boshlansa | OMR oqimi |
| **Xatolik darajasi > 0.5%** (yuborishda) | `notification_outbox` |

> **Asosiy tamoyil:** *trigger bo'lmasa — ish yo'q.*

---

## 11. MVP ma'lumot modeli (yakuniy) va hujjatlarga tuzatish

### 11.1. MVP modeli — ikki artefakt

```
   ┌──────────────────────────────────────────────┐
   │ responses  (qabul logi, append-only)         │
   │  • har o'zgarish = yangi revision            │
   │  • is_current = oxirgi holat (partial indeks)│
   │  • capture_status: answered/blank/not_reached│
   └───────────────────────┬──────────────────────┘
                           │ baholashda (bir marta)
                           ▼
   ┌──────────────────────────────────────────────┐
   │ scoring_snapshot_items  (baholash haqiqati)  │
   │  • key_used · b_used · theta_used            │
   │  • score_awarded · score_status              │
   │  • guessing_c · engine_version               │
   │  • abadiy immutable                          │
   └──────────────────────────────────────────────┘
```

**Muhim:** MVP'da **joriy holat** `responses` dan o'qiladi (`is_current`),
ya'ni `attempt_responses_current` jadvali **yo'q**. Ikkinchi artefakt —
`scoring_snapshot_items` — apellyatsiya, regrade va kelajakdagi tahlil uchun
**muzlatilgan** baholash haqiqati.

### 11.2. MVP asosi allaqachon mavjud hujjatda

| Hujjat | MVP'dagi roli |
|---|---|
| **`docs/02` MVP-0** (11 jadval) | **MVP poydevori** — faqat 4 jadval qo'shiladi: `items`, `item_versions`, `scoring_snapshot_items`, `result_versions` |
| `docs/03` | Kalibrlash algoritmi — **o'zgarishsiz** ishlatiladi |
| `docs/04` | 6 o'quvchi endpoint'i + autosave — **o'zgarishsiz**, faqat `numeric/text` va `not_reached` qo'shiladi |
| `docs/07` | Roadmap — P2/F davrlariga mos keladi |
| **`docs/09`** | **PHASE-2 va FUTURE xaritasi** (MVP spetsifikatsiyasi **emas**) |
| `docs/08` | Xavflar ro'yxati — barchasi P2 trigger'lari bilan bog'lanadi |

### 11.3. Hujjatlarda qilinadigan **minimal** tuzatishlar

| Hujjat | Tuzatish |
|---|---|
| `02` | `responses` ga `capture_status`, `answer_kind`, `raw_answer`, `normalized_answer`, `testlet_ref`; `given_option` `A`…`F`; `item_versions` ga `item_type` + `answer_spec`; 4 ta yangi jadval qo'shiladi |
| `03` | «Parameter sets», «JMLE» va «anchor» bo'limlari **P2** deb belgilanadi (algoritm o'zgarmaydi) |
| `04` | `PUT` so'rovi pozitsiya emas **item identifikatori**; `numeric/text` kartochkalari; `not_reached` |
| `09` | Har bir bo'limga **MVP / P2 / F** belgisi qo'yiladi (bu hujjatning 2–4-bo'limlari bo'yicha) |
| `08` | C-4 dagi `p_hat`/`residual`/`information` «saqlanadi» → «**hisoblanadi**» ga tuzatiladi |

---

## 12. Xulosa va yakuniy hukm

### 12.1. Uchta asosiy xulosa

| # | Xulosa |
|---|---|
| **1** | `docs/02` — **MVP poydevori**. Unga faqat **4 jadval** va **5 maydon** qo'shiladi; `docs/09` esa **kelajak xaritasi** (MVP spetsifikatsiyasi emas) |
| **2** | MVP'da **2 artefakt** yetarli: **log** (nima qildi) + **item snapshot** (qanday baholandi). Ikki nusxa (proyeksiya), telemetriya, fit/DIF/equating — **keyin** |
| **3** | **Arzon va qaytarilmas** ma'lumot (testlet, hudud, til, `raw_answer`, `b_used`/`key_used`) **bugun** yig'iladi; uni **ishlatadigan mantiq** trigger bajarilganda yoziladi |

### 12.2. Soddalashtirishning **ochiq xavflari** (halol ro'yxat)

| Xavf | Ta'sir | Chora |
|---|---|---|
| **`answer_chain` mantiqi yo'q** | `b(36b)` sun'iy yuqori → `θ` da kichik xato | Kalibrlash boshlanishi bilan (PHASE-2) qoida kiritiladi; `testlet_ref` **bugun** saqlanadi |
| **4-eyes yo'q (faqat double-entry)** | Ikki kishi tekshirmasa, kalit xatosi qolishi mumkin | **Double-entry MVP'da majburiy**; adminlar 2+ bo'lishi bilan `key_reviews` |
| **Fit statistikasi yo'q** | Buzuq savol (masalan, kalit xatosi) faqat `key_suspect` bilan aniqlanadi | `key_suspect` + `too_easy` flag'lari MVP'da bor; fit → PHASE-2 |
| **Telemetriya yo'q** | `omitted`/`not_reached` **taxminiy** ajratiladi | `last_interaction_position` yondashuvi (95% to'g'ri); trigger bilan aniqlashtiriladi |
| **Reliability ko'rsatilmaydi** | Natijaning ishonchliligi o'quvchiga ko'rinmaydi | Sessiyadan keyin hisobotda **on-the-fly** hisoblanadi (jadval kerak emas) |

### 12.3. MVP «bajarildi» mezonlari (8 ta)

| # | Mezon |
|---|---|
| 1 | 45 savol (32 `mcq4` + 3 `mcq6` + 10 `numeric`) ishlaydi, kalit PDF bilan mos |
| 2 | Javob **hech qachon yo'qolmaydi** (refresh, tarmoq uzilishi, fon rejimi) |
| 3 | `not_reached` va `blank` ajratiladi; **ikki xom ball** ko'rsatiladi |
| 4 | θ (Rasch) hisoblanadi; ekstremal holat («45/45») alohida izohlanadi |
| 5 | `b` avtomatik yangilanadi (oxirgi sessiyadan keyin) va admin ko'radi |
| 6 | Kalit + `b` **item darajasida muzlatilgan**; regrade eski natijani **o'zgartirmaydi** |
| 7 | Autosave **`audit_log` ga tushmaydi**; audit faqat muhim amallarda |
| 8 | Kalit **ikki marta** kiritiladi (double-entry) va farq bo'lsa qabul qilinmaydi |

### 12.4. Yakuniy hukm

> **Maqsad — eng murakkab tizim emas, eng ishonchli sodda tizim.**
>
> 1. **`docs/02` — MVP.** 15 jadval, 8 endpoint, 2 artefakt, 2 algoritm.
> 2. **`docs/09` — PHASE-2/FUTURE xaritasi.** Undan **hoziroq** 7 element
>    olib tashlanadi (matematik ortiqchalik / takroriy maydon).
> 3. **Trigger bo'lmasa — ish yo'q.** Har kechiktirilgan elementda
>    **o'lchanadigan** shart bor (10.3-bo'lim).
> 4. **Arzon va qaytarilmas ma'lumot bugun yig'iladi** (`testlet_ref`,
>    hudud/til, `raw_answer`, `b_used`/`key_used`/`theta_used`) — bu MVP'ni
>    og'irlashtirmaydi, lekin kelajakni ochiq qoldiradi.
> 5. Natijada: **bitta dasturchi** boshqaradigan, Rasch asosidagi,
>    Milliy Sertifikat testlarini ishonchli tekshiradigan va
>    **keyingi 3–12 oyga tayyor** arxitektura.

### 12.5. Nazorat savoli (har yangi taklif uchun)

```
1. Bu ballni o'zgartiradimi?          → Yo'q → kechiktir
2. Qonuniy hujjat/huquqiy talabmi?    → Yo'q → kechiktir
3. Bu ma'lumot keyin tiklanadimi?     → Ha  → kechiktir
4. Trigger (metrika) bormi?           → Yo'q → kechiktir
5. 2 kundan ko'p ish talab qiladimi?  → Ha  → kechiktir
────────────────────────────────────────────────────────────
Besh savoldan biri ham «yo'q/ha» bo'lmasa — MVP'ga kiradi.
```

