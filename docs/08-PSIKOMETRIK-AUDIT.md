# 08 — Psixometrik va arxitektura auditi (senior review)

> **Audit predmeti:** `docs/01–07` hujjatlaridagi ma'lumot modeli, oqimlar va
> sxema — Milliy Sertifikat testlari uchun (45 savol: 1–32 `mcq4`,
> 33–35 `mcq6`, 36–45 `numeric/text`, A/B qismli).
> **Auditor roli:** software architect + psychometrician (Rasch) + DB architect.
> **Chiqarish:** kod yozilmadi — faqat topilmalar, model o'zgarishlari va roadmap.

## 0. Audit qamrovi va baholash mezoni

| Tekshirilgan | Holat |
|---|---|
| Item identifikatsiyasi (global `item_id` + version) | ⚠️ qisman — `items`/`item_versions` bor, lekin javoblar `form_item_id` orqali |
| Item turlari (`mcq4`, `mcq6`, `numeric`, `text`) | ❌ yo'q |
| Ochiq javob spetsifikatsiyasi (normalizatsiya, tolerantlik) | ❌ yo'q |
| Item-level javoblar + append-only tarix | ✅ bor |
| Snapshot scoring | ⚠️ qisman — item darajasida muzlatilmagan |
| Regrade → yangi result version | ✅ bor |
| Soft delete / immutability | ✅ bor |
| Anchor items / equating / calibration runs jadvali | ✅ bor |
| Fit (Infit/Outfit), DIF, Reliability uchun ma'lumot | ❌ asosiy maydonlar yo'q |
| Not-reached vs omitted ajratilishi | ❌ yo'q (kritik) |
| 10K–100K yuklamaga tayyorlik | ⚠️ bir nechta to'siq |

**Prioritet shkalasi:** `Critical` — kalibrlash yoki ishonchlilikni **butunlay
buzadi** (bugun tuzatilmasa, keyin tiklab bo'lmaydi); `High` — sifatni sezilarli
pasaytiradi yoki 6 oy ichida qimmat refaktoring talab qiladi; `Medium` — ish
jarayoni/operatsiya samaradorligi.

## 1. Ijroiya xulosasi (verdict)

Arxitektura **asosli va kengaytiriladigan**, lekin hozirgi model
**«qog'oz javoblar varag'i»** tipidagi testni modellashtiradi. Yangi talab
(`mcq4/mcq6/numeric/text` + `item_id/version` identifikatsiyasi + ochiq javoblar)
**to'rt** joyda uzilish beradi:

1. **Item turi va javob spetsifikatsiyasi yo'q** → `numeric` javoblarni
   baholab bo'lmaydi, `mcq6` da tasodif ehtimoli xato hisoblanadi.
2. **Javoblar `form_item_id` orqali bog'langan** (item_version_id nullable) →
   «savollar hech qachon pozitsiya orqali identifikatsiya qilinmaydi» talabi
   **hali bajarilmagan**; kalibrlash uzluksizligi xavf ostida.
3. **«Taqdim etilgan, lekin javob berilmagan»** (not-reached) holati yo'q →
   45 savolli vaqtli testda **speededness** tufayli θ va `b` **tizimli xato**
   bo'ladi.
4. **Sessiya darajasidagi psixometrik ko'rsatkichlar saqlanmaydi** →
   Reliability, equating, drift va DIF **keyin tiklab bo'lmaydi**.

### Eng xavfli 7 topilma (bir qatorda)

| # | Topilma | Prioritet |
|---|---|---|
| 1 | Item statistikasi uzluksizligi: yangi formada yangi `item` yaratilsa, `N≥200` **hech qachon** to'planmaydi → Rasch kalibrlash ishlamaydi | **Critical** |
| 2 | Not-reached ≠ omitted: taqdim etish logi (`attempt_items`) yo'q | **Critical** |
| 3 | `item_type` + `answer_spec` yo'q → numeric/text baholanmaydi, `c₀` xato | **Critical** |
| 4 | `scoring_snapshot_items` yo'q → `b` muzlatilgan bo'lsa ham, **item darajasida** muzlatilmagan; Infit/Outfit/regrade aniq qayta chiqarilmaydi | **Critical** |
| 5 | DIF guruh o'zgaruvchilari (hudud, til, jins, yosh, maktab) **bugun** yig'ilmasa, hech qachon tiklanmaydi | **Critical** |
| 6 | Incremental item statistika yo'q → har kalibrlashda millionlab satr skanerlanadi (100k foydalanuvchida ishlamaydi) | **Critical** |
| 7 | «Kalitni 4 ko'z bilan tekshirish» oqimi yo'q (`key_review`) → kalit xatolari (psixometrikada 1-xatar manbai) | **High** |

## 2. Critical topilmalar

### C-1. Item statistikasining uzluksizligi (kalibrlashning 1-sharti)

**Muammo.** `docs/02 §4` da `items` jadvali `UNIQUE (program_id, item_ref, part)`
bilan yaratilgan, lekin `/new_form` ish oqimi (04 §4) `reuse_items` ni **ixtiyoriy**
qoldirgan. Amalda har yangi PDF/formada o'qituvchi yangi kalit kiritadi → har bir
pozitsiya uchun **yangi `item`** yaratiladi.

**Psixometrik ta'sir.** `b` va `SE(b)` **`item_version`** ga bog'lanadi
(02 §4, 03 §3). Agar har sessiyada yangi `item_version` paydo bo'lsa:

* `N` hech qachon `min_n = 30` dan oshmaydi → `b` **doim `0.0`** da qoladi;
* Rasch kalibrlash uchun **hech qachon** `N ≥ 200` yig'ilmaydi → `frozen` (anchor)
  itemlar umuman shakllanmaydi → **equating imkonsiz**;
* drift tahlili (bir itemning vaqt bo'yicha o'zgarishi) **mantiqan yo'qoladi** —
  har item faqat bir marta ishlatilgan bo'ladi.

**Talab (majburiy):**

| # | O'zgarish |
|---|---|
| 1 | `item_ref` **majburiy** maydon (kalit yuklashda ham: `36a=12`, `37b=19` yonida `item_ref` ustuni) |
| 2 | `POST /admin/forms` da `reuse_items` **default `true`** (o'chirilishi mumkin, lekin ogohlantirish bilan) |
| 3 | Yangi jadval: `item_link_suggestions` (yangi pozitsiya ↔ mavjud `item_version` takliflari) |
| 4 | Admin ekrani: «item bog'lash» — `form_item` → mavjud `item_id`, `linked_by`, `link_reason`, `audit_log` |
| 5 | Hisobot: «Formada bog'lanmagan itemlar: 45/45» → kalibrlash **ogohlantirish bilan** ishlaydi |

**Prioritet: Critical.** Bu — kalibrlashning bo'lish-shart-sharti
(*conditio sine qua non*). Boshqa hamma narsa ikkinchi darajali.

---

### C-2. Not-reached ≠ omitted (speededness xatosi)

**Muammo.** `docs/02` da `responses.response_state` faqat
`('answered','omitted','cleared')` (02 §3, satr 209). `docs/03 §3.2` da esa
**`p_used = C/N`** (javobsiz = noto'g'ri) deb qat'iy belgilangan.

**Psixometrik ta'sir.** 45 savol + vaqt chegarasi bo'lgan testda **vaqt yetmay
qolgan** savollar (not-reached) va **ataylab tashlab ketilgan** savollar
(omitted) butunlay boshqa ma'no beradi:

| Holat | To'g'ri qayta ishlash | Hozirgi model |
|---|---|---|
| Omitted (o'quvchi ko'rdi, javob bermadi) | `u_ij = 0` yoki missing — siyosat tanlanadi | `0` ✅ |
| **Not-reached** (vaqt yetmadi, ko'rmadi ham) | **`u_ij = missing`** — θ hisoblashdan **chiqariladi** | **`0`** ❌ → θ **pastga tortiladi** |

Oqibat: tez ishlaydigan o'quvchi «aqlli», sekin ishlaydigan o'quvchi sun'iy
«past» chiqadi; `p_used = C/N` esa **savol qiyinligini sun'iy oshiradi**
(`b` ↑), chunki oxirgi savollarda hech kim javob bermagan bo'ladi →
`p → 0` → `b → +4.0` → **barcha oxirgi savollar «juda qiyin» deb belgilanadi**.

Toki bu tuzatilmasa, **kalibrlash natijalari tizimli ravishda buziladi**.

**Talab:**

| # | O'zgarish |
|---|---|
| 1 | Yangi jadval `attempt_items` (taqdim etish logi) — pastda 7-bo'lim |
| 2 | `responses.response_state` ga `'not_reached'` (va `'not_presented'`) qo'shish |
| 3 | `p` ning ikki varianti: `p_answered = C/A` va `p_reached = C/N_reached`; `p_used` segmentga qarab |
| 4 | θ hisoblashda `not_reached` → **`u_ij = missing`** (`rasch.py` ga «presented» massivi qo'shiladi) |
| 5 | `session_statistics` ga **speededness indeksi** (`not_reached / N`, oxirgi 5 savol `p` o'rtachasi) |
| 6 | `end_time` da server tomonda **avtomatik yakunlash** — `not_reached` aniq belgilanadi |

**Prioritet: Critical.**

---

### C-3. `item_type` va javob spetsifikatsiyasi yo'q

**Muammo.** `item_versions.correct_option` faqat `('A','B','C','D')`
CHECK bilan (02 §4, satr 438). `options_count INTEGER DEFAULT 4` bor, lekin:

* **`mcq6`** (33–35 savollar, `A–F`) — `correct_option` CHECK **rad etadi**;
* **`numeric` / `text`** (36–45: `36a = 12`, `36b = 45`) — **umuman joy yo'q**.

**Psixometrik ta'sir.**

| Item turi | Kerak | Yo'q bo'lsa |
|---|---|---|
| `mcq4` | `c₀ = 1/4 = 0.25` | ✅ to'g'ri |
| `mcq6` | `c₀ = 1/6 = 0.1667` | `c₀` **xato** → `b` tizimli xato |
| `numeric` | normalizatsiya + tolerantlik | javobni **baholab bo'lmaydi** |
| `text` | normalizatsiya (registr, bo'sh joy) | javobni **baholab bo'lmaydi** |

`docs/03 §3.5` dagi «`p̂ ≤ c₀` → `key_suspect`» qoidasi `numeric/text` da
**noto'g'ri ishlaydi** (ochiq javobda tasodif yo'q → `c₀ = 0` bo'lishi kerak).

**Talab:**

```
item_types (lug'at):
  code          title        has_options  options  guessing  answer_rule      score_rule
  mcq4          A–D variant  true         4        0.25      option_match     dichotomous
  mcq6          A–F variant  true         6        0.1667    option_match     dichotomous
  numeric       Sonli javob  false        0        0.00      numeric_match    dichotomous
  text          Qisqa matn   false        0        0.00      normalized_text  dichotomous

item_versions ga qo'shiladi:
  item_type     TEXT NOT NULL REFERENCES item_types (code)
  answer_spec   JSONB NOT NULL            -- javobning MASHINA o'qiydigan ta'rifi
  max_score     NUMERIC(4,2) NOT NULL DEFAULT 1.0     -- polytomous readiness
```

`answer_spec` ning kanonik shakllari:

```json
// mcq4 / mcq6
{ "kind": "option", "correct": "C", "options_count": 6 }

// numeric  (36a = 12)
{ "kind": "numeric", "accepted": [12], "tolerance": 0.0,
  "normalize": ["trim","strip_spaces","decimal_comma_to_dot","unicode_minus"],
  "allow_fraction": true, "unit": null, "min": null, "max": null }

// text     ("Toshkent")
{ "kind": "text", "accepted": ["toshkent"],
  "normalize": ["trim","lower","collapse_spaces","fold_case"],
  "max_length": 40 }
```

**`responses` ga qo'shiladi:**

```
raw_answer        TEXT          -- o'quvchi kiritgani aynan ("12,5" / " 12 ")
normalized_answer TEXT          -- normallashtirilgan ("12.5")
answer_kind       TEXT          -- 'option' | 'numeric' | 'text'
score_awarded     NUMERIC(4,2)  -- 0.0 / 1.0 (kelajakda 0.5, 2.0 …)
max_score         NUMERIC(4,2)
match_rule        TEXT          -- 'exact' | 'tolerance' | 'manual'
given_option      TEXT          -- faqat mcq uchun (mavjud, ochiq javobda NULL)
```

**Prioritet: Critical** (`numeric/text`), **High** (`mcq6` `c₀`).

---

### C-4. Item darajasida muzlatilgan scoring snapshot yo'q

**Muammo.** `docs/02 §3` da `scoring_snapshots` bor, lekin u faqat
**urinish darajasida** yozilgan: `θ`, `SE`, `raw_score`, `b_checksum`.
`b_checksum` — **hash**, ya'ni qiymatlarning o'zi emas.

**Psixometrik ta'sir.** Quyidagilarni **aniq** qayta chiqarib bo'lmaydi:

1. **Infit/Outfit**: `z_ij = (u_ij − P̂(θ_i, b_j)) / √(P̂(1−P̂))` ni hisoblash
   uchun **har bir item uchun ishlatilgan `b_j` va `P̂`** kerak. Hashdan
   tiklab bo'lmaydi; `b` esa kalibrlashdan keyin **o'zgargan** bo'ladi.
2. **Regrade auditi**: «o'sha kuni natija nega shunday chiqdi?» degan savolga
   **item darajasida** javob berib bo'lmaydi.
3. **Qayta baholashda solishtirish**: eski va yangi `θ` farqini **qaysi item**
   keltirib chiqarganini aniqlab bo'lmaydi.
4. **Appellyatsiya**: «7-savol mening javobim to'g'ri edi» — o'sha paytda
   ishlatilgan kalit va `b` ni ko'rsatish kerak.

**Talab — yangi jadval `scoring_snapshot_items`:**

```
snapshot_item_id  bigint PK
snapshot_id       bigint FK → scoring_snapshots (ON DELETE RESTRICT)
form_item_id      bigint FK → form_items
item_id           bigint FK → items            -- global identifikatsiya
item_version_id   bigint FK → item_versions    -- muzlatilgan versiya
display_label     text                         -- "36a"
position          integer                      -- taqdimot tartibi (snapshot)
is_anchor         boolean                      -- shu baholashda anchor edi?
key_used          text                         -- ishlatilgan kalit (option / accepted / NULL)
key_version_no    integer                      -- item_version.version_no
b_used            numeric(8,4)                 -- ishlatilgan qiyinchilik (logit)
b_source          text                         -- 'default'|'classical'|'rasch'|'anchor'
parameter_set_id  bigint FK → item_parameter_sets
answer_kind       text
raw_answer        text
normalized_answer text
score_awarded     numeric(4,2)
max_score         numeric(4,2)
is_correct        boolean
p_hat             numeric(6,4)                 -- P̂(θ_i, b_j) shu baholashda
residual          numeric(8,4)                 -- u_ij − P̂  (Infit/Outfit uchun xom)
information       numeric(8,4)                 -- P̂(1−P̂)  (I(X), SE uchun)
UNIQUE (snapshot_id, form_item_id)
```

Bu jadval bilan **istalgan paytda** Infit/Outfit, item-level tahlil, apellyatsiya
javobi va regrade solishtiruvi **bir xil aniqlikda** qayta hisoblanadi.

**Prioritet: Critical.**

---

### C-5. DIF uchun guruh o'zgaruvchilari bugun yig'ilmasa — tiklab bo'lmaydi

**Muammo.** `docs/02 §4` da `attempt_attributes` (`region`, `language`, `device`)
bor, lekin u **ixtiyoriy** va **urinish** darajasida. DIF tahlili uchun
**shaxs (person) darajasidagi** guruh o'zgaruvchilari kerak — ularni
**retrospektiv tiklab bo'lmaydi**.

**Psixometrik ta'sir.** DIF (Differential Item Functioning) — «bir xil
qobiliyatli, ammo turli guruhdagi o'quvchilar bu savolga har xil javob
beradimi?» degan savol. Milliy Sertifikat uchun bu **majburiy** tekshiruv:
hudud, til (lotin/kirill, o'zbek/rus/qoraqalpoq), shahar/qishloq, maktab turi
bo'yicha savol **kamsitmasligi** kerak. Lekin:

* guruh o'zgaruvchisi yozilmagan bo'lsa → **DIF umuman hisoblanmaydi**;
* keyin to'plash uchun yangi sessiya kerak → **o'tgan yillar tiklanmaydi**.

**Talab:**

```
persons_attributes (yoki attempt_attributes, lekin STRUKTURALANGAN):
   region_code      TEXT      -- 'TAS','SAM','BUX' (14 hudud)
   district_code    TEXT
   language_code    TEXT      -- 'uz-latn','uz-cyrl','ru','kaa'
   gender           TEXT      -- 'm','f' | NULL (ixtiyoriy)
   birth_year       INTEGER
   school_code      TEXT
   teacher_ref      TEXT      -- o'qituvchi (klaster effekti uchun)
   center_id        BIGINT    -- imtihon markazi
   session_mode     TEXT      -- 'online' | 'center'

exam_centers:  center_id, region_code, title, address, is_active
```

> ⚠️ **Maxfiylik:** bu **PII**. Shuning uchun: (a) yig'ishda **rozilik**;
> (b) analytics uchun **kodlash** (to'liq manzil emas); (c) saqlash muddati
> siyosati; (d) `analyst_ro` faqat agregat ko'radi.

**Prioritet: Critical** — vaqt o'tishi bilan qimmatlashadi; bugun yig'ilmasa
**hech qachon** tiklanmaydi.

---

### C-6. Sessiya darajasidagi psixometrik ko'rsatkichlar saqlanmaydi

**Muammo.** `item_statistics` — **item** darajasida, `scoring_snapshots` —
**o'quvchi** darajasida. **Sessiya (administratsiya)** darajasida hech narsa
saqlanmaydi.

**Psixometrik ta'sir.** Quyidagilar **hisoblanmaydi**:

| Ko'rsatkich | Formula / tarkib | Nega kerak |
|---|---|---|
| **Reliability** | `R = (SD_θ² − MSE) / SD_θ²`, `MSE = mean(SE²)` | Baholash qanchalik ishonchli? Mezon: `R ≥ 0.80` |
| **Person separation** | `G = SD_true / avg(SE)` | Test nechta daraja ajratadi |
| **Item separation** | `SD_b / avg(SE_b)` | Savollar to'plami qamrovi |
| **SEM profili** | `SEM(θ)` turli nuqtalarda | Cut-score yaqinidagi aniqlik |
| **θ taqsimoti** | `mean, sd, skew, min, max, N` | Equating uchun sampling distribution |
| **Ekstremal holatlar** | `n(0/45)`, `n(45/45)` | Ularga θ **yo'q** — alohida ko'rsatiladi |
| **Xom ball taqsimoti** | har ball chastotasi | Xom ball → θ konversiya jadvali |
| **Speededness** | `not_reached %`, oxirgi 5 savol `p` | Vaqt yetarlimi? |

**Talab — yangi jadval `session_statistics`:**

```
session_id, parameter_set_id, engine_version,
n_attempts, n_valid, n_extreme_low, n_extreme_high, n_incomplete,
theta_mean, theta_sd, theta_min, theta_max,
theta_se_mean, mse, reliability, separation_index,
item_mean_b, item_sd_b, item_se_mean, item_separation,
raw_mean, raw_sd, raw_min, raw_max,
total_score_distribution JSONB,     -- {"31": 214, "32": 987, ...}
sem_profile JSONB,                  -- {"-2.0": 0.61, "-1.0": 0.45, ...}
speededness_index NUMERIC(6,4),
speededness_flags JSONB,
engine_params JSONB, computed_at
```

Har sessiyadan keyin **avtomatik** hisoblanadi (kalibrlash sikli ichida).

**Prioritet: Critical** (Reliability — milliy hisobot uchun majburiy;
equating uchun taqsimot kerak).

---

### C-7. Incremental statistika yo'q (10K–100K'da ishlamaydi)

**Muammo.** `docs/02 §8` va `docs/03 §4.2` da kalibrlash **har safar
`responses` jadvali bo'ylab `GROUP BY`** qiladi.

**Yuklama hisobi (100 000 foydalanuvchi × 45 savol):**

| Ko'rsatkich | Qiymat |
|---|---|
| Javob satrlari (revision'lar bilan) | **4.5M – 9M** |
| Kalibrlash so'rovi skaneri | 4.5M satr × 3 jadval JOIN ≈ **30–60 s** |
| Sessiyalar soni (yilda) | 50–100 |
| To'plangan skaner hajmi | ~**5 mlrd satr-o'qish/yil** |

Bunday yondashuv **kunlik kalibrlashda** ishlamaydi, **real-time** (sessiya
yopilgach darhol) esa umuman mumkin emas.

**Talab — incremental hisoblagichlar:**

```
item_session_counters (UPSERT, yakunlash paytida yangilanadi):
   session_id, form_item_id, item_version_id,
   n_presented, n_reached, n_answered, n_correct, n_omitted, n_not_reached,
   n_revisions, sum_time_spent_ms, n_answer_changes,
   score_sum,               -- polytomous readiness
   category_counts JSONB,    -- {"0": 412, "1": 987, "2": 33}
   updated_at
   UNIQUE (session_id, form_item_id)
```

* Kalibrlash endi **4.5M emas, 45 satr** o'qiydi;
* `item_statistics` (tarix) faqat **kunlik konsolidatsiyada** to'ldiriladi;
* `responses` **audit va re-analysis** uchun to'liq saqlanadi, lekin **issiq
  yo'lda** ishlatilmaydi.

**Prioritet: Critical** (arxitektura o'zgarishi; keyin qo'shish qimmat).

---

### C-8. Ochiq javoblarni qo'lda ko'rikdan o'tkazish va apellyatsiya oqimi yo'q

**Muammo.** `numeric`/`text` javoblar (36–45, ya'ni 10 savol = **22% test**)
avtomatik baholanadi. Amalda esa:

* `36a` kaliti `12`; o'quvchi `12,0`, `12.0`, `  12  `, `1 2`, `12 sm` yozadi;
* o'quvchi ko'chirishda xato qiladi (PDF da `6` ni `8` deb o'qish);
* o'quvchi «javob to'g'ri edi, tizim qabul qilmadi» deb **apellyatsiya** beradi.

Hozirgi modelda **apellyatsiya jadvali, qo'lda ko'rik navbati va qaror izi
yo'q**.

**Talab:**

```
scoring_reviews:      -- qo'lda ko'rik navbati
   review_id, attempt_id, form_item_id, item_version_id,
   raw_answer, normalized_answer, auto_score, review_score,
   reason ('tolerance'|'parsing'|'key_dispute'|'appeal'),
   status ('pending'|'accepted'|'rejected'|'escalated'),
   reviewer_id, reviewed_at, note

appeals:              -- rasmiy apellyatsiya
   appeal_id, attempt_id, user_id, result_version_id,
   submitted_at, deadline_at, reason, items_jsonb,
   status ('pending'|'in_review'|'accepted'|'rejected'),
   decision, decided_by, decided_at, new_result_version_id

key_reviews:          -- kalitni 4 ko'z bilan tekshirish (H-8 bilan bog'liq)
   key_review_id, form_version_id, item_version_id, proposed_key,
   proposed_by, verified_by, status, note, created_at
```

**Prioritet: Critical** — apellyatsiya **huquqiy** talab; qo'lda ko'rik
bo'lmasa `numeric/text` savollarda adolatsizlik real holatga aylanadi.

---

## 3. High prioritetli topilmalar

| # | Topilma | Ta'sir | Talab |
|---|---|---|---|
| **H-1** | **Polytomous readiness yo'q**: `points` bor, lekin javobda `score_awarded`/`max_score` yo'q | Kelajakda qismiy ball (PCM/GPCM) **imkonsiz** | `score_awarded`, `max_score`, `category_counts JSONB`, `item_statistics.category_counts` |
| **H-2** | **Fit statistikasi saqlanmaydi** | Infit/Outfit faqat `scoring_snapshot_items` bilan qayta hisoblanadi (C-4) yoki umuman yo'q | `item_fit_statistics` (item_version, session, infit, outfit, zstd), `person_fit` (snapshot_id, infit, outfit) |
| **H-3** | **Item ↔ parameter set bog'lanishi yo'q** (faqat `b_checksum`) | Qaysi item qaysi sessiyada anchor edi — aniqlanmaydi | `item_parameter_set_items` (`parameter_set_id`, `item_version_id`, `b_value`, `is_anchor`, `anchor_b`) |
| **H-4** | **Exposure nazorati yo'q** | Savol «charchashi» va xavfsizlik nazorati yo'q | `item_exposure` (`item_version_id`, `session_id`, `n_presented`) yoki `item_session_counters.n_presented` + `exposure_cap` |
| **H-5** | **Testlet / lokal bog'liqlik (LD) maydoni yo'q** | 36a va 36b bir savol matnidan → **LD buzilishi**; Rasch taxmini buziladi | `item_versions.testlet_ref` (+ `item_versions.shared_stem_ref`), LD tekshiruv hisoboti (`residual_correlations`) |
| **H-6** | **Engine parametrlari muzlatilmaydi** | `engine_version='1.0'` bor, lekin konstanta (`K`, `c₀`, `θ_bound`, WLE/JMLE) yo'q | `scoring_snapshots.engine_params JSONB`; `scoring_engine_versions` jadvali |
| **H-7** | **Ekstremal o'quvchilar siyosati yo'q** | «45/45» o'quvchiga `θ=+3` berish — **noto'g'ri** (haqiqiy θ cheksiz) | `attempts.is_extreme`, `theta_lo_bound/theta_hi_bound`, hisobotda «≥ +3.0 (aniq emas)» |
| **H-8** | **Kalitni tekshirish oqimi (4-eyes) yo'q** | Kalit xatosi = barcha natijalar buziladi | `key_reviews` + `key_revision_impact` (qaysi urinishlar ta'sirlangan) |
| **H-9** | **Telegram update idempotentligi yo'q** | Bir `update_id` ikki marta qayta ishlansa — dubl javob/dupl `attempt` | `bot_updates(update_id PK, processed_at)` + `attempts` unique (bor) |
| **H-10** | **Xabar yuborish masshtabi** | 100k natijani bitta bot bilan yuborish ≈ **55 daqiqa** (30 msg/s limit) | `notification_outbox` sharding + prioritet + **pull** (Mini App) yondashuvi |
| **H-11** | **PDF manba link rot** | Kanal posti o'chirilsa item manbasi yo'qoladi | `item_sources` (`item_ref`, `channel_message_id`, `file_id`, `pdf_sha256`, `stored_path`) — matn **saqlanmaydi**, faqat havola/hash |
| **H-12** | **PDF hisobot pipeline yo'q** | 100k PDF ≈ 30–80 CPU-soat | `report_renders` navbati + on-demand generatsiya + keshlash |

## 4. Medium prioritetli topilmalar

| # | Topilma | Nega muhim | Talab |
|---|---|---|---|
| **M-1** | **`audit_log` ga autosave yozilishi** xavfi | 100k × 20 paket = **2M audit satr/sessiya** → jadval portlaydi va asl auditni ko'mib tashlaydi | Audit faqat: admin amallari, kalit/`b` o'zgarishi, submit, soft delete, regrade. **Autosave → `attempt_events`** (coarse) |
| **M-2** | **Javob revision'larining cheksiz o'sishi** | 45 savol × o'rtacha 2–3 revision = **9M satr/sessiya** | Ikki qatlamli model: (a) `responses` — append-only log (audit), (b) `attempt_responses_current` — haqiqiy jadval (UPSERT, tez o'qish). Eski revision'lar arxiv partition'ga |
| **M-3** | **Partial unique index churn** (`WHERE is_current`) | Har saqlashda indeks yangilanadi → bloat, VACUUM muammosi | `is_current` ni **joriy holat jadvaliga** ko'chirish (M-2) → partial indeks kerak bo'lmaydi |
| **M-4** | **`form_items.display_label` yo'q** | PDF da raqamlash doim 1..45 bo'lmasligi mumkin (bo'limlar, 36a/36b) | `display_label TEXT` («36a», «III-12») + `section_no`; UI **faqat label** ko'rsatadi |
| **M-5** | **Subject bo'yicha markazlashtirish noaniq** | Turli fanlar `b` lari aralashsa, o'lchov buziladi | Kalibrlash **`program_id` ichida** markazlashtiriladi; `item_parameter_sets` ham fan bo'yicha |
| **M-6** | **Vaqt manbasi noaniq** | Client soati noto'g'ri → javob vaqti (`time_spent`) xato | Deadline — **server vaqti**; client vaqti faqat `answered_at` (skew bilan), `attempt_items` da server vaqti ham |
| **M-7** | **`raw_score` → `θ` konversiya jadvali yo'q** | Milliy sertifikatda ball → daraja jadvali **yil bo'yicha qotirilishi** kerak | `score_conversion_tables` (`parameter_set_id`, `raw_score`, `theta`, `scaled`, `sem`) — har sessiyadan keyin |
| **M-8** | **Cut-score / daraja ta'riflari yo'q** | «A daraja» nima — qaysi `θ` dan boshlanadi? | `scales`, `scale_cutoffs` (versiyalangan, yil bilan), `scale_reference_session` |
| **M-9** | **Sertifikat jadvali yo'q** | Milliy sertifikat **hujjat** beradi (seriya, daraja, amal muddati) | `certificates` (`serial`, `attempt_id`, `level`, `issued_at`, `valid_to`, `verify_hash`, `revoked_at`) |
| **M-10** | **Idempotentlik kalitlari registri yo'q** | Tarmoq qayta urinishida dubl amal | `idempotency_keys` (`key`, `endpoint`, `request_hash`, `response_json`, `created_at`) |
| **M-11** | **Qurilma fingerprint / anti-cheat yo'q** | Bir qurilmadan ko'p akkaunt, javob almashish | `attempts.device_hash`, `device_clusters` (bir xil qurilma → bir sessiyada N urinish hisoboti) |
| **M-12** | **Monitoring / DQ dashboard yo'q** | Kalibrlash sifati va ma'lumot bo'shliqlari ko'rinmaydi | `ops.quality_checks` (kunlik: yetim javob, 0-javobli item, `p` ekstremal, `not_reached` o'sishi) |

---

## 5. Rasch kalibrlashga to'sqinlik qiluvchi 12 nuqta (checklist)

«Kelajakda kalibrlash qo'shamiz» degan reja **bugungi qarorlarga** bog'liq.
Har bir punkt — **bugun tuzatilmasa, keyin ma'lumot yo'qoladi**:

| # | To'siq | Yechim | Prioritet |
|---|---|---|---|
| 1 | Javob `form_item_id` orqali bog'langan, `item_version_id` NULL bo'lishi mumkin | `responses.item_id` + `item_version_id` **NOT NULL** qilish (MVP-1 dan keyin) | Critical |
| 2 | Item statistikasi uzluksizligi yo'q (C-1) | `item_ref` majburiy + `item_link_suggestions` | Critical |
| 3 | `not_reached` ajratilmagan (C-2) | `attempt_items` + `response_state` kengaytmasi | Critical |
| 4 | `item_type`/`c₀` per item emas (C-3) | `item_types` + `item_versions.item_type` | Critical |
| 5 | Item darajasida `b`/`P̂` muzlatilmaydi (C-4) | `scoring_snapshot_items` | Critical |
| 6 | DIF guruh o'zgaruvchilari yo'q (C-5) | `persons_attributes` + `exam_centers` | Critical |
| 7 | Sessiya statistikasi yo'q (C-6) | `session_statistics` | Critical |
| 8 | Incremental hisoblagich yo'q (C-7) | `item_session_counters` | Critical |
| 9 | Lokal bog'liqlik (36a/36b) uchun maydon yo'q (H-5) | `testlet_ref` + LD tekshiruvi | High |
| 10 | Anchor eksplitsit bog'lanmagan (H-3) | `item_parameter_set_items` + `anchor_sets` | High |
| 11 | Fit statistikasi saqlanmaydi (H-2) | `item_fit_statistics` + `person_fit` | High |
| 12 | O'lchov identifikatsiyasi (markazlash) hujjatlashtirilmagan | `item_parameter_sets.scale_center` (`item_mean_zero` / `anchor_locked`), fan ichida | High |

**Qo'shimcha psixometrik ogohlantirishlar:**

| Ogohlantirish | Izoh |
|---|---|
| **1PL + tasodif** | `mcq4` da `c₀ = 0.25`, `mcq6` da `0.167`. 1PL modelida `c = 0` bo'ladi → past qobiliyatli o'quvchilarning `θ` i **pastga tortiladi**. Bugun bu klassik tuzatish bilan qoplanadi; **kelajakda 3PL** (yoki 1PL+c qat'iy) zarur. Sxema `c_value`, `a_value` ni **hozir** qabul qilsin. |
| **JMLE person bias** | Qisqa testlarda JMLE `θ` i **yuqoriga** bias beradi (`WLE` yaxshiroq). `engine_params.method = 'jmle' | 'wle'` qilib saqlash kerak. |
| **Ekstremal holatlar** | `0/45` va `45/45` o'quvchilarga **chekli θ yo'q**. Ularni `+3.0` deb ko'rsatish — **noto'g'ri**; «≥ +3.0 (aniq emas)» deb ko'rsatish va sertifikat qarorida alohida siyosat. |
| **Speededness** | `not_reached > 10%` bo'lsa, test **speeded** hisoblanadi va Rasch taxminlari buziladi → test vaqtini oshirish yoki savol sonini kamaytirish (psixometrik tavsiya). |
| **LD / testlet** | 36a–45b juftliklari bir matndan → rezidual korrelyatsiyalar `> 0.20–0.30` bo'lsa LD buzilgan; testlet modeli kerak bo'ladi. |
| **Fan bo'yicha alohida o'lchov** | Matematika va Ona tili `b`/`θ` lari **birlashtirilmaydi** — har fan o'z shkalasi. |

## 6. 10K–100K foydalanuvchi: yuklama tahlili va yechimlar

### 6.1. Hajm va tezlik hisoblari (45 savol, 1 sessiya)

| Ko'rsatkich | 10 000 | 100 000 |
|---|---|---|
| `attempts` satrlari | 10k | 100k |
| `attempt_items` (taqdimot) | 450k | **4.5M** |
| `responses` (revision'lar bilan 2×) | 900k | **9M** |
| `attempt_responses_current` (UPSERT) | 450k | **4.5M** |
| Avtosave paketlari (debounce ~15–25/urinish) | 150–250k | **1.5–2.5M** |
| Cho'qqi (oxirgi 30 daqiqada 70%) | ~100–150 req/s | **~1000–1500 req/s** |
| Har paketda yozuv (batch 5 item) | ~1M yozuv | **~10M yozuv** |
| DB hajmi (1 sessiya) | ~1.5–2 GB | **~15–20 GB** |
| Yillik (50–100 sessiya) | — | **~1–1.5 TB** |

### 6.2. Muammoli joylar va yechimlar

| # | Muammo | Nima bo'ladi | Yechim |
|---|---|---|---|
| 1 | **Avtosave yozuv ko'paytmasi** | Har javob: (a) `INSERT` (revision), (b) `UPDATE` eski `is_current=false`, (c) `UPDATE attempts.revision` → **3 yozuv**. 1000 req/s da 3000+ yozuv/s + indeks bloat | **Ikki qatlam:** `attempt_responses_current` (UPSERT, 1 yozuv) + `responses` append-only (1 yozuv, partition). `attempts.revision` = counter (bir qatorda) |
| 2 | **Partial indeks** (`WHERE is_current`) | Bloat, VACUUM bosim | (1) dagi modeldan keyin kerak emas |
| 3 | **Statistika full-scan** | Kalibrlash 30–60 s, kunlik 100 sessiyada imkonsiz | `item_session_counters` (C-7) — **45 satr/sessiya** |
| 4 | **Thundering herd**: hamma `end_time` da yakunlaydi | 100k submit + grading bir vaqtda → DB qulflanadi | (a) server tomonda `end_time` da **batch auto-finalize** (navbat bilan), (b) grading **navbat** (`grading_queue`) va qismlarga bo'lib, (c) natija hisoblash **kechiktirilgan** (sessiya yopilgach bosqichma-bosqich) |
| 5 | **Telegram push limiti** | 30 xabar/s → 100k ≈ **55 daqiqa**; yana per-chat limit | (a) `notification_outbox` **prioritet + throttling**; (b) **pull** — Mini App'da «Natijani olish» tugmasi; (c) bir nechta bot/shards; (d) birinchi navbatda faqat `result_time` da «Natija tayyor» (matnsiz) |
| 6 | **PDF hisobot CPU** | 100k × 1–3 s = **30–80 CPU-soat** | On-demand + navbat + keshlash (`report_renders`), 8 worker bilan 4–10 soatda |
| 7 | **Bir jarayonli monolit** (`main.py`) | Bot + API + worker bir jarayonda: bittasi qulasa hammasi to'xtaydi | `bot` / `api` / `grading` / `calibration` / `notifier` **alohida xizmatlar** (PG bo'lgandan keyin), systemd/supervisor |
| 8 | **SQLite** | 1000 yozuv/s da **WAL qulfi** va `database is locked` | PostgreSQL (M5) majburiy; `PgBouncer`; `statement_timeout` |
| 9 | **Web App statik fayllar** | Har ochilishda serverdan | CDN/cache, `ETag`, `Cache-Control: immutable` (build hash) |
| 10 | **`initData` HMAC har so'rovda** | Arzon (μs), lekin Python'da 1500 req/s da sezilarli | 60 s TTL cache (`user_id` → validated), `auth_date` bo'yicha |
| 11 | **Audit portlashi** (M-1) | 2M satr/sessiya | Autosave audit qilinmaydi |
| 12 | **`responses` partition'siz** | 9M satr/sessiya, `VACUUM`/`REINDEX` imkonsiz | `PARTITION BY RANGE (created_at)` oylik + `BRIN` |
| 13 | **Connection pool** | 1500 req/s × turli ish → pool tugaydi | PgBouncer `transaction` rejimi, har worker uchun kichik pool |
| 14 | **Backup** | 1.5 TB `pg_dump` = soatlar | `pg_basebackup` + WAL arxivlash (PITR), replika |
| 15 | **Analytics so'rovlari prodni bloklaydi** | Katta hisobotlar | `read-replica` (physical) + `analyst_ro` faqat replikada |

### 6.3. Capacity reja (tavsiya)

| Bosqich | Foydalanuvchi/sessiya | Tavsiya |
|---|---|---|
| Pilot | 300 | 1 VPS (2 vCPU/4 GB) + PG |
| Kichik milliy | 5 000 | 4 vCPU/8 GB, PgBouncer, 4 aiohttp worker |
| O'rta | 20 000 | 8 vCPU/16 GB + read-replica, partition, notifier alohida |
| Katta | 100 000 | 16 vCPU/32 GB, 3+ xizmat instansiyasi, 2 replika, PgBouncer, CDN |

### 6.4. Bir sessiyaning vaqt byudjeti (100k)

| Bosqich | Vaqt | Izoh |
|---|---|---|
| Javob qabul qilish | 60–180 daq | Cho'qqi 1000–1500 req/s |
| Auto-finalize (server) | 5–10 daq | Navbat bilan `end_time` + kichik kechikish |
| Baholash (θ) | 10–20 daq | 100k × MLE ≈ 100k × 30 ms = 50 daqiqa CPU → 8 worker bilan ~7 daq |
| Kalibrlash + statistika | 5–15 daq | Incremental (45 × sessiya) |
| Natija e'lon + xabar | 30–60 daq | Telegram limiti |

## 7. Yetishmayotgan jadvallar (to'liq katalog)

**P** = prioritet (C = Critical, H = High, M = Medium).
**Tiklanadi?** — bugun saqlanmasa, keyin tiklab bo'ladimi (❌ = yo'q).

### 7.1. Item modeli (C-1, C-3, H-5)

| Jadval | P | Asosiy ustunlar | Nega |
|---|---|---|---|
| `item_types` | C | `code` (mcq4/mcq6/numeric/text), `options_count`, `guessing`, `answer_rule`, `score_rule` | Tur bo'yicha `c₀` va baholash qoidasi |
| `item_sources` | H | `item_ref`, `channel_message_id`, `file_id`, `pdf_sha256`, `stored_path`, `page_no` | PDF — tashqi manba, lekin **havola** saqlanishi shart (link rot) |
| `item_link_suggestions` | C | `form_item_id`, `candidate_item_version_id`, `score`, `reason`, `status` | Item uzluksizligi (C-1) |
| `*_answer` maydonlari | C | `responses.raw_answer`, `normalized_answer`, `score_awarded`, `max_score` | Ochiq javoblar |

### 7.2. Taqdim etish va javoblar (C-2, M-2)

| Jadval | P | Asosiy ustunlar | Tiklanadi? | Nega |
|---|---|---|---|---|
| `attempt_items` | C | `attempt_id`, `form_item_id`, `item_version_id`, `display_label`, `position`, `first_presented_at`, `last_presented_at`, `time_spent_ms`, `focus_losses`, `change_count` | ❌ | **not_reached**, javob vaqti, o'zgartirish tahlili |
| `attempt_responses_current` | C | `attempt_id`, `form_item_id`, `given_option`, `raw_answer`, `normalized_answer`, `score_awarded`, `revision`, `updated_at` | ✅ | Issiq yo'l (UPSERT), partial indeks o'rniga |
| `item_events` | M | `attempt_id`, `item_version_id`, `event` (focus/blur/scroll/paste), `at` | ❌ | Xatti-harakat tahlili, firibgarlik signallari |

### 7.3. Snapshot va baholash (C-4, H-6, H-7)

| Jadval | P | Asosiy ustunlar | Nega |
|---|---|---|---|
| `scoring_snapshot_items` | C | C-4 bo'limida to'liq berilgan | Infit/Outfit, regrade audit, apellyatsiya |
| `scoring_engine_versions` | H | `engine_version`, `algorithm`, `constants JSONB`, `code_commit` | Qaysi konstanta bilan hisoblangani |
| `grading_queue` | H | `attempt_id`, `status`, `priority`, `attempts`, `last_error` | 100k da baholashni navbatga qo'yish |
| `score_conversion_tables` | M | `parameter_set_id`, `raw_score`, `theta`, `scaled`, `sem` | Xom ball → θ → shkala jadvali |

### 7.4. Statistika va psixometrika (C-6, C-7, H-1…H-4)

| Jadval | P | Asosiy ustunlar | Nega |
|---|---|---|---|
| `item_session_counters` | C | C-7 bo'limida to'liq berilgan | Incremental statistika |
| `session_statistics` | C | C-6 bo'limida to'liq berilgan | Reliability, separation, θ taqsimoti, speededness |
| `item_parameter_set_items` | H | `parameter_set_id`, `item_version_id`, `b_value`, `b_se`, `is_anchor`, `anchor_b`, `c_value`, `a_value` | Anchor eksplitsitligi, equating, 3PL readiness |
| `item_fit_statistics` | H | `item_version_id`, `session_id`, `parameter_set_id`, `infit_mnsq`, `outfit_mnsq`, `infit_zstd`, `n` | Item fit monitoring |
| `person_fit` | M | `snapshot_id`, `infit_mnsq`, `outfit_mnsq`, `zstd`, `flag` | Qoidabuzar javoblar |
| `item_drift_checks` | H | `item_version_id`, `session_a`, `session_b`, `p_diff`, `z`, `b_diff`, `flag` | Drift monitoring |
| `local_dependence_checks` | H | `session_id`, `item_a`, `item_b`, `residual_corr`, `flag` | Testlet/LD (36a–36b) |
| `equating_links` | H | `from_set`, `to_set`, `anchor_count`, `slope`, `intercept`, `rmsd` | Formalar bog'lanishi |
| `anchor_sets` | H | `anchor_set_id`, `program_id`, `scale_reference`, `valid_from`, `valid_to` | Anchor to'plami versiyalari |
| `item_exposure` | M | `item_version_id`, `session_id`, `n_presented`, `exposure_rate` | Exposure nazorati |

### 7.5. Shaxs, DIF, markaz (C-5)

| Jadval | P | Asosiy ustunlar | Tiklanadi? | Nega |
|---|---|---|---|---|
| `persons_attributes` | C | `user_id`, `region_code`, `district_code`, `language_code`, `gender`, `birth_year`, `school_code`, `teacher_ref`, `consent_at` | ❌ | DIF |
| `exam_centers` | H | `center_id`, `region_code`, `title`, `address`, `is_active` | ⚠️ qisman | Markaz bo'yicha tahlil |
| `dif_results` | H | `item_version_id`, `session_id`, `group_var`, `mh_stat`, `mh_p`, `ets_class`, `flag` | ✅ | DIF hisoboti |

### 7.6. Kalit, ko'rik, apellyatsiya (C-8, H-8)

| Jadval | P | Asosiy ustunlar | Nega |
|---|---|---|---|
| `key_reviews` | H | `form_version_id`, `item_version_id`, `proposed_answer_spec`, `proposed_by`, `verified_by`, `status` | 4-eyes, kalit xatosi oldini olish |
| `key_revision_impact` | H | `item_version_id`, `old_key`, `new_key`, `affected_attempts`, `regrade_run_id` | Kalit tuzatilganda ta'sir tahlili |
| `scoring_reviews` | C | C-8 bo'limida to'liq berilgan | `numeric/text` qo'lda ko'riki |
| `appeals` | C | C-8 bo'limida to'liq berilgan | Rasmiy apellyatsiya |

### 7.7. Shkala, sertifikat, hisobot (M-7…M-9, H-12)

| Jadval | P | Asosiy ustunlar | Nega |
|---|---|---|---|
| `scales` | H | `scale_id`, `program_id`, `code`, `valid_from`, `valid_to`, `reference_parameter_set_id` | Milliy shkala versiyalari |
| `scale_cutoffs` | H | `scale_id`, `level` (A/B/C), `theta_min`, `raw_min`, `scaled_min`, `sem_at_cut` | Daraja chegaralari + aniqlik |
| `certificates` | H | `serial`, `attempt_id`, `user_id`, `scale_id`, `level`, `issued_at`, `valid_to`, `verify_hash`, `revoked_at` | Milliy sertifikat hujjati |
| `report_renders` | M | `render_id`, `attempt_id`, `template_code`, `status`, `file_path`, `bytes` | PDF hisobot navbati + kesh |

### 7.8. Operatsiya, xavfsizlik, sifat (M-1, M-10…M-12, H-9, H-10)

| Jadval | P | Asosiy ustunlar | Nega |
|---|---|---|---|
| `bot_updates` | H | `update_id` PK, `processed_at`, `status` | Telegram idempotentligi |
| `idempotency_keys` | M | `key`, `endpoint`, `request_hash`, `response_json`, `expires_at` | Qayta urinish himoyasi |
| `rate_limit_counters` | M | `scope`, `key`, `window_start`, `count` | Rate limit (Redis bo'lmasa) |
| `device_clusters` | M | `device_hash`, `user_ids`, `attempt_count`, `flag` | Anti-cheat |
| `quality_checks` | M | `check_code`, `session_id`, `value`, `threshold`, `flag`, `at` | Kunlik DQ monitoringi |
| `notification_delivery` | M | `outbox_id`, `channel`, `status`, `error`, `delivered_at` | Yetkazish auditi |

**Jami:** mavjud **34** + yangi **34** = **68 jadval** (professional daraja).

## 8. Ideal PostgreSQL sxemasi (target model)

### 8.1. Sxemalar (6 ta)

```sql
CREATE SCHEMA iam;       -- users, staff_roles, persons_attributes, exam_centers
CREATE SCHEMA item;      -- item_types, items, item_versions, item_tags, item_sources,
                         --   item_link_suggestions, key_reviews, item_status_history
CREATE SCHEMA delivery;  -- forms, form_versions, form_items, exam_sessions, attempts,
                         --   attempt_items, responses, attempt_responses_current,
                         --   attempt_events, bot_updates
CREATE SCHEMA scoring;   -- item_parameter_sets, item_parameter_set_items, item_parameters,
                         --   item_session_counters, item_statistics, session_statistics,
                         --   scoring_snapshots, scoring_snapshot_items, result_versions,
                         --   item_fit_statistics, calibration_runs, anchor_items, equatings
CREATE SCHEMA audit;     -- audit_log, key_revision_impact, scoring_reviews, appeals
CREATE SCHEMA ops;       -- notification_outbox, report_renders, idempotency_keys,
                         --   app_settings, schema_migrations, quality_checks
```

| Sxema | Kim yozadi | Xususiyat |
|---|---|---|
| `iam` | `app_rw` | PII → alohida rol; `analyst_ro` faqat agregat ko'radi |
| `item` | `item_admin` | Kalit **faqat** shu yerda; `app_rw` `answer_spec`/`correct_option` ni **o'qimaydi** |
| `delivery` | `app_rw` (INSERT/UPDATE) | Hot path, partition'li |
| `scoring` | `app_worker` (yozadi), `app_rw` (faqat SELECT) | Worker-only yozuv |
| `audit` | `app_rw` (faqat INSERT) | `UPDATE/DELETE` — `REVOKE` + trigger |
| `ops` | `app_rw`, `app_worker`, `notifier` | Navbatlar |

### 8.2. Konvensiyalar (majburiy)

| Qoida | Qiymat |
|---|---|
| PK | `bigint GENERATED ALWAYS AS IDENTITY` (o'zgarmas) |
| Vaqt | `timestamptz` — **server** vaqti; client vaqti faqat `*_client_at` da |
| `b`, `θ`, `SE` | `numeric(8,4)`; `p` → `numeric(6,4)`; ball → `numeric(6,2)` (hech qachon `float`) |
| JSON | `jsonb` + `CHECK (jsonb_typeof(col) = 'object')` |
| Statuslar | `text` + `CHECK` yoki lug'at jadvali (`item_types`) |
| Soft delete | `deleted_at timestamptz` + partial unique (`WHERE deleted_at IS NULL`) |
| Immutability | `responses`, `scoring_snapshot_items`, `audit_log`, `item_statistics` — trigger bilan qulflangan |
| Naming | jadval ko'plik; FK `<birlik>_id`; indeks `ix_*`; unique `ux_*` |
| Evolyutsiya | Faqat `ADD COLUMN ... DEFAULT`; ishlab chiqarishda `DROP COLUMN` **yo'q** |

### 8.3. Hot path modeli (M-2, M-3 — eng muhim o'zgarish)

```
Yozish (autosave paketi, bitta tranzaksiya):
  1. UPSERT delivery.attempt_responses_current (attempt_id, form_item_id)   → 1 yozuv
  2. INSERT delivery.responses (append-only, partition)                     → 1 yozuv
  3. UPDATE delivery.attempts SET revision = revision + 1, last_seen_at = now()

O'qish (state, submit):
  → attempt_responses_current (45 satr, PK bo'yicha) ≈ 1 ms
  → responses — faqat audit / eksport / qayta tahlil uchun
```

| Nega | Natija |
|---|---|
| Partial indeks kerak emas | `WHERE is_current` indeks churni **yo'qoladi** |
| `UPDATE` atigi 1 ta | Yozuv hajmi **3× → 2×** kamayadi |
| Joriy holat bitta joyda | `GET state` tez, `JOIN`siz |

```sql
CREATE TABLE delivery.attempt_responses_current (
    attempt_id        bigint NOT NULL,
    form_item_id      bigint NOT NULL,
    item_id           bigint NOT NULL,
    item_version_id   bigint NOT NULL,
    answer_kind       text NOT NULL,
    given_option      char(1),
    raw_answer        text,
    normalized_answer text,
    score_awarded     numeric(4,2),
    max_score         numeric(4,2) NOT NULL DEFAULT 1.0,
    response_state    text NOT NULL DEFAULT 'answered'
                      CHECK (response_state IN ('answered','omitted','not_reached',
                                                'not_presented','cleared')),
    revision          integer NOT NULL DEFAULT 1,
    client_seq        bigint,
    updated_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (attempt_id, form_item_id)
);
```

### 8.4. Partitioning strategiyasi

| Jadval | Usul | Kalit | Izoh |
|---|---|---|---|
| `delivery.responses` | `RANGE (created_at)` | **oylik** | Eski oylar `DETACH` → arxiv (`pg_dump --table`) |
| `delivery.attempt_items` | `RANGE (created_at)` | oylik | Sessiya bo'yicha analitika uchun indeks |
| `delivery.attempt_responses_current` | partition **kerak emas** | — | Sessiya tugagach `attempts` bilan arxivlanadi |
| `audit.audit_log` | `RANGE (created_at)` | oylik | 5 yil retensiya |
| `scoring.item_statistics`, `session_statistics` | kerak emas | — | Kichik (item × davr) |
| `responses` indekslari | `BRIN (created_at)` + `btree (attempt_id)` + `btree (item_version_id, created_at)` | — | Append-only uchun BRIN arzon |

**Partition'li jadvalda FK ishlamaydi** → integrallik: (a) ilova yozuv paytida
tekshiradi; (b) haftalik `ops.quality_checks` «yetim satr» ni izlaydi;
(c) `NOT NULL` + `CHECK` majburiy.

### 8.5. Immutability va audit (trigger'lar)

```sql
-- responses — faqat INSERT
CREATE TRIGGER trg_responses_append_only
    BEFORE UPDATE OR DELETE ON delivery.responses
    FOR EACH ROW EXECUTE FUNCTION audit.forbid_mutation();

-- scoring_snapshot_items — muzlatilgan
CREATE TRIGGER trg_snapshot_items_immutable
    BEFORE UPDATE OR DELETE ON scoring.scoring_snapshot_items
    FOR EACH ROW EXECUTE FUNCTION audit.forbid_mutation();

-- audit_log — faqat INSERT
REVOKE UPDATE, DELETE ON audit.audit_log FROM app_rw, app_worker;
```

> `attempt_responses_current` — **o'zgaruvchan** (UPSERT), lekin har bir
> o'zgarish `responses` (append-only) da **iz qoldiradi** → tarix to'liq.

### 8.6. RLS va kolonna darajasidagi himoya

```sql
ALTER TABLE delivery.attempts ENABLE ROW LEVEL SECURITY;
CREATE POLICY attempts_self ON delivery.attempts
    FOR SELECT USING (user_id = current_setting('app.user_id', true)::bigint);

-- Kalit o'quvchi sessiyasida ko'rinmasin
REVOKE SELECT (answer_spec) ON item.item_versions FROM app_rw;
GRANT  SELECT (answer_spec) ON item.item_versions TO item_admin;
```

### 8.7. Indekslar (majburiy minimal to'plam)

```sql
CREATE INDEX ix_form_items_version ON delivery.form_items (form_version_id, position);
CREATE UNIQUE INDEX ux_form_items_label ON delivery.form_items (form_version_id, display_label);
CREATE UNIQUE INDEX ux_attempts_session_user ON delivery.attempts (session_id, user_id)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_responses_item ON delivery.responses (item_version_id, created_at)
    WHERE response_state = 'answered';
CREATE INDEX ix_item_stats_item ON scoring.item_statistics (item_version_id, computed_at DESC);
CREATE INDEX ix_counters_session ON scoring.item_session_counters (session_id);
CREATE INDEX ix_outbox_pending ON ops.notification_outbox (status, priority, created_at);
CREATE INDEX ix_audit_entity ON audit.audit_log (entity_type, entity_id, created_at DESC);
```

### 8.8. Hosilaviy maydonlar va ko'rinishlar

```sql
ALTER TABLE scoring.scoring_snapshot_items
    ADD COLUMN is_correct boolean
    GENERATED ALWAYS AS (score_awarded >= max_score) STORED;

CREATE MATERIALIZED VIEW scoring.mv_item_last_stats AS
SELECT DISTINCT ON (item_version_id) *
  FROM scoring.item_statistics
 ORDER BY item_version_id, computed_at DESC;
```

### 8.9. Tranzaksiya va izolyatsiya qoidalari

| Amal | Izolyatsiya | Izoh |
|---|---|---|
| Autosave (UPSERT) | `READ COMMITTED` | Optimistik qulf (`revision`) — `FOR UPDATE` kerak emas |
| Submit | `READ COMMITTED` + `attempts` qatorida `FOR UPDATE` | Bir vaqtda ikki qurilma submit qilmasin |
| Baholash (attempt) | `READ COMMITTED` | Snapshot yozish |
| Kalibrlash | `REPEATABLE READ` | Bir davr ustida izchil o'qish |
| Regrade / equating | `SERIALIZABLE` | Natija versiyalari buzilmasligi |

**Qoida:** uzoq tranzaksiyalar taqiqlanadi — `statement_timeout = 5s`
(kalibrlash uchun alohida `30s`).

---

## 9. Item lifecycle (professional)

### 9.1. Holatlar mashinasi

```
   [draft] ──kalit kiritildi──► [key_pending] ──2-ko'z tasdiq──► [verified]
        ▲                             │                              │
        │                     rad etildi (xato)                      │
        └─────────────────────────────┘                              ▼
                                                                [active]
                                                    b = 0.0, provisional
                                                                    │
                                          birinchi sessiyada ishlatildi
                                                                    ▼
                                                             [calibrating]
                                              N < 30 → b yangilanmaydi
                                                                    │
                                                   N ≥ 110, SE ≤ 0.30
                                                                    ▼
                                                             [operational]
                                                                    │
                                                   N ≥ 200, SE ≤ 0.25
                                                                    ▼
                                                               [frozen] ──► anchor
                       fit yomon / drift / exposure haddan tashqari │
                                          ┌─────────────────────────┘
                                          ▼
                                     [flagged] ──ko'rik──► [draft] (yangi version)
                                          │
                        iste'moldan chiqarildi ──► [retired] ──► [archived]
```

### 9.2. O'tish qoidalari (kim, qachon, nima yoziladi)

| O'tish | Kim | Shart | Yoziladi |
|---|---|---|---|
| `draft → key_pending` | creator | `answer_spec` to'liq, `item_ref` mavjud | `key_reviews`, `item_status_history` |
| `key_pending → verified` | **ikkinchi** admin | `verified_by ≠ proposed_by` (4-eyes) | `key_reviews.status='verified'` |
| `key_pending → draft` | ikkinchi admin | Mos kelmasa | `key_reviews.status='rejected'` |
| `verified → active` | tizim | `form_version` publish qilinganda | `item_status_history` |
| `active → calibrating` | tizim | ≥ 1 sessiyada ishlatilgan | `item_statistics` |
| `calibrating → operational` | tizim | `N ≥ 110`, `SE ≤ 0.30` | `item_parameters` yangi satr |
| `operational → frozen` | tizim | `N ≥ 200`, `SE ≤ 0.25` | `anchor_sets` nomzodi |
| `→ flagged` | tizim | `key_suspect` / `anchor_mismatch` / fit `> 1.5` / drift `z > 3` | `quality_checks` + admin xabari |
| `flagged → draft` | admin | Kalit tuzatiladi → **yangi `item_version`** | `key_revision_impact` + regrade |
| `→ retired` | admin | Savol eskirgan / exposure yuqori | `item_status_history` |
| `→ archived` | tizim | 3 yil ishlatilmagan | arxiv partition |

### 9.3. Versioning qoidalari (qat'iy)

| O'zgarish | Natija |
|---|---|
| **Savol matni** (PDF da) o'zgardi | **Yangi `item`** (yoki yangi `item_version`) — `stem_hash` o'zgaradi |
| **Kalit** o'zgardi (`A → B`) | **Yangi `item_version`** (`version_no + 1`) + `key_revision_impact` + regrade |
| **`answer_spec`** o'zgardi (tolerantlik, `accepted[]`) | Yangi `item_version` |
| **`b`** o'zgardi (statistika) | `item_version` **o'zgarmaydi** — `item_parameters` yangi satr |
| `item_ref` bir xil va matn bir xil | **Bir xil item** — statistika davom etadi ✅ |
| `testlet_ref` (36a/36b) | Bir xil `testlet_ref` — bir matn, **ikki alohida item** |

> ⚠️ **Eng muhim qoida:** `b` **`item_version`** ga bog'langan. Matn o'zgargan
> bo'lsa, eski `b` **yaroqsiz** — statistika noldan boshlanadi. Shu sababli
> «matn o'zgarishi» va «kalit o'zgarishi»ni **Item Version** darajasida
> ajratish hayotiy zarur.

---

## 10. Bugundan saqlanishi shart bo'lgan ma'lumotlar

**Ko'rsatkich → kerakli minimal ma'lumot → qayerda → bugun bormi?**

| Ko'rsatkich | Kerakli minimal ma'lumot | Qayerda saqlanadi | Bugun bor? |
|---|---|---|---|
| **Difficulty `b`** | `item_version_id`, `n_presented`, `n_reached`, `n_correct`, `session_id`, `θ̄` | `item_session_counters` → `item_statistics` | ⚠️ qisman |
| **Infit / Outfit** | har bir javob uchun `b_used`, `P̂(θ)`, `u_ij` | `scoring_snapshot_items` | ❌ |
| **Person fit** | `snapshot_id`, reziduallar yig'indisi | `person_fit` | ❌ |
| **Reliability / separation** | `θ_i`, `SE_i`, sessiya `id` | `session_statistics` | ❌ |
| **DIF** | `region_code`, `language_code`, `gender`, `school_code`, `center_id` + `θ` | `persons_attributes` | ❌ **tiklanmaydi** |
| **Equating** | anchor itemlar (bir xil `item_version_id` ikki sessiyada), `b`, `SE`, `θ` taqsimoti | `anchor_sets`, `item_parameter_set_items`, `session_statistics` | ⚠️ qisman |
| **Drift** | bir `item_version` uchun sessiyalar bo'ylab `p`, `b`, `SE`, sana | `item_statistics`, `item_drift_checks` | ⚠️ qisman |
| **Speededness** | `presented_at`, `time_spent_ms`, `not_reached` | `attempt_items` | ❌ **tiklanmaydi** |
| **Response time** | item ochilgan/yopilgan vaqtlar | `attempt_items` | ❌ **tiklanmaydi** |
| **Answer changes** | har bir revision va vaqti | `responses` + `attempt_items.change_count` | ✅ / ⚠️ |
| **LD / testlet** | `testlet_ref`, rezidual korrelyatsiya | `item_versions`, `local_dependence_checks` | ❌ |
| **Exposure** | `item_version_id` × `session_id` × `n_presented` | `item_session_counters` | ⚠️ qisman |
| **Scale / cut-scores** | `θ` chegaralari, `raw → θ` jadvali, yil | `scales`, `scale_cutoffs`, `score_conversion_tables` | ❌ |
| **Reproducibility** | `engine_version`, konstantalar, `b`, kalit, `P̂` | `scoring_engine_versions`, `scoring_snapshot_items` | ⚠️ qisman |
| **Appellyatsiya / ko'rik** | javob, qaror, iz | `appeals`, `scoring_reviews` | ❌ |

> **Xulosa:** 15 ko'rsatkichdan **6 tasi butunlay yo'q**; ulardan **4 tasi
> (DIF, speededness, response time, LD)** — **hech qachon tiklanmaydi**.
> Bu auditning eng muhim amaliy xulosasi.

---

## 11. Prioritetlar matritsasi (nima qilish kerak)

### Critical (1–2 oy ichida, kalibrlashdan **oldin**)

| # | Harakat | Taxminiy hajm | Bog'liq topilma |
|---|---|---|---|
| 1 | `item_types` + `item_versions.item_type/answer_spec/max_score` | 2–3 kun | C-3 |
| 2 | `responses` ga `raw_answer`, `normalized_answer`, `score_awarded`, `max_score`, `item_id` | 2 kun | C-3 |
| 3 | `attempt_items` (taqdim etish logi) + `not_reached` | 3–4 kun | C-2 |
| 4 | `scoring_snapshot_items` (item darajasida muzlatish) | 3 kun | C-4 |
| 5 | `item_session_counters` (incremental statistika) | 3 kun | C-7 |
| 6 | `session_statistics` (+ Reliability) | 2 kun | C-6 |
| 7 | `persons_attributes` + `exam_centers` (ro'yxatdan o'tishda yig'ish) | 4–5 kun | C-5 |
| 8 | `item_ref` majburiy + `item_link_suggestions` + bog'lash ekrani | 5–7 kun | C-1 |
| 9 | `scoring_reviews` + `appeals` (qo'lda ko'rik va apellyatsiya) | 5–6 kun | C-8 |
| 10 | `attempt_responses_current` (hot path UPSERT) | 3–4 kun | M-2, M-3 |

**Jami: ~5–6 hafta** (1 backend developer). Bularsiz kalibrlash **soxta
aniqlik** beradi yoki umuman yig'ilmaydi.

### High (2–4 oy)

| # | Harakat | Topilma |
|---|---|---|
| 11 | `key_reviews` (4-eyes) + `key_revision_impact` | H-8 |
| 12 | `item_parameter_set_items` + `anchor_sets` | H-3, H-12 |
| 13 | `item_fit_statistics` + `person_fit` | H-2 |
| 14 | `grading_queue` + xizmatlarni ajratish | H-10, M-1 |
| 15 | `scales` + `scale_cutoffs` + `score_conversion_tables` | M-7, M-8 |
| 16 | `certificates` (seriya, daraja, muddat) | M-9 |
| 17 | `report_renders` (PDF navbati) | H-12 |
| 18 | `bot_updates` + `idempotency_keys` | H-9, M-10 |
| 19 | `item_drift_checks` + `local_dependence_checks` | H-5 |
| 20 | `item_sources` (PDF havolasi/hash) | H-11 |

### Medium (4–12 oy)

| # | Harakat | Topilma |
|---|---|---|
| 21 | `item_events`, `device_clusters` (anti-cheat) | M-11 |
| 22 | `quality_checks` + DQ dashboard | M-12 |
| 23 | `rate_limit_counters`, `notification_delivery` | M-10 |
| 24 | `dif_results` (Mantel-Haenszel) | H-2, C-5 |
| 25 | `item_exposure` + exposure siyosati | H-4 |
| 26 | 3PL readiness (`a_value`, `c_value`) | H-1 (ogohlantirish) |

---

## 12. Milliy Sertifikat uchun professional daraja roadmapi

### Phase 0 — «Model tuzatish» (0–2 oy)

**Maqsad:** kalibrlash uchun ma'lumot yo'qolmasligi.

| Ish | Chiqish mezoni |
|---|---|
| 10 ta Critical harakat (§11) | Sxema + API yangilandi, migratsiya o'tdi |
| `not_reached` oqimi | Test: 45 savoldan 10 tasini ko'rmagan o'quvchi `not_reached` oladi |
| `numeric/text` baholash | `12,0` = `12.0` = `12` → to'g'ri; `12 sm` → `scoring_reviews` navbati |
| Item bog'lash (C-1) | Bir item ikki formada → **bitta** `item_id` |
| DIF o'zgaruvchilari | `persons_attributes` to'ldirilgan urinishlar ≥ 95% |

**Nazorat:** psixometrik mutaxassis sxemaga sign-off beradi.

### Phase 1 — «Ishonchli o'lchov» (2–4 oy)

| Ish | Chiqish mezoni |
|---|---|
| `session_statistics` + Reliability | Har sessiya uchun `R`, `G`, `SEM` hisobotda |
| Item fit | `item_fit_statistics` (infit/outfit) har sessiyadan keyin |
| Drift + LD monitoring | `item_drift_checks`, `local_dependence_checks` |
| Speededness nazorati | `not_reached ≤ 10%` yoki test vaqti qayta ko'riladi |
| `scales` + `scale_cutoffs` | «A/B/C» darajalari `θ` da, `sem_at_cut` hisoblangan |
| 4-eyes kalit | Har forma kaliti **ikki** kishi tomonidan tasdiqlangan |

**Nazorat:** 3 sessiyada `R ≥ 0.80`, `not_reached ≤ 10%`, item fit 95% qabul
oralig'ida.

### Phase 2 — «Rasch kalibrlash va equating» (4–7 oy)

| Ish | Chiqish mezoni |
|---|---|
| JMLE moduli (`method='rasch_jmle'`) | Klassik va JMLE `b` korrelyatsiyasi `r ≥ 0.95`, RMSD ≤ 0.30 |
| `anchor_sets` + `anchor_items` | Har formada ≥ 20% anchor |
| `equating_links` | Ikki forma natijasi **bir shkalada** taqqoslanadi |
| `item_parameter_set_items` | Har `b` qaysi itemga tegishli — aniq |
| O'lchov identifikatsiyasi | Fan bo'yicha markazlash / anchor — hujjatlashtirilgan |
| `frozen` itemlar | ≥ 100 ta `frozen`, barqaror item banki |

**Nazorat:** equating natijasi mustaqil psixometrik tekshiruvdan o'tadi.

### Phase 3 — «Milliy shkala va huquqiy tayyorlik» (7–12 oy)

| Ish | Chiqish mezoni |
|---|---|
| Yillik equating, shkala barqarorligi | Yillar bo'yicha ball taqqoslanadi |
| DIF (Mantel-Haenszel) | Har sessiya uchun DIF hisoboti (`ets_class`) |
| `certificates` + verifikatsiya | Seriya, `verify_hash`, revocation |
| Apellyatsiya jarayoni | `deadline_at`, qaror izi, `new_result_version` |
| Exposure va bank salomatligi | Har item `exposure ≤ cap`, `retired` oqimi |
| Xavfsizlik auditi | Pen-test, RLS, PITR mashqi (`RTO ≤ 1 soat`) |
| Metodologik hujjat | O'zbek/rus: model, kalibrlash, shkala, cut-score, DIF |
| Mustaqil audit | Tashqi psixometrist sign-off |

### Phase 4 — «Doimiy yaxshilash» (12+ oy)

| Ish | Izoh |
|---|---|
| 2PL/3PL baholash | `a`, `c` parametrlari (sxema tayyor) — model solishtirish |
| Bank boyitish | Mavzu qamrovi, item generation pipeline |
| CAT / adaptive | **Qamrovdan tashqarida** (PDF formati saqlanadi) |
| Hududiy/markaz rejimi | `session_mode = 'center'`, proctoring siyosati |
| Yillik hisobot | Milliy tendensiyalar (`θ` taqsimoti, drift, DIF) |

---

## 13. Sizdan zarur bo'lgan qarorlar (open questions)

Bu savollarga javob **sxemaga bevosita ta'sir qiladi** — 01–07 hujjatlarni
yangilashdan oldin aniqlashtirish kerak:

| # | Savol | Variantlar | Ta'sir |
|---|---|---|---|
| 1 | **36–45 ochiq javoblar bir yoki ikki ballmi?** | (a) har `a`/`b` = 1 ball (dichotomous) — **tavsiya**; (b) qismiy ball | `score_awarded`, PCM/GPCM readiness |
| 2 | **`numeric` javoblarda tolerantlik?** | (a) qat'iy teng; (b) `±0.01`; (c) `±1%` | `answer_spec.tolerance` |
| 3 | **Apellyatsiya muddati va jarayoni?** | 15 / 30 kun, kim ko'radi | `appeals`, xodim oqimi |
| 4 | **Sertifikatni tizim beradimi?** | generatsiya qilinadimi yoki faqat natija | `certificates` (M-9) |
| 5 | **DIF o'zgaruvchilari majburiymi?** | `region` majburiy, `gender` ixtiyoriy | Ro'yxatdan o'tish formasi |
| 6 | **Test vaqti chegarasi bormi?** | Yo'q bo'lsa speededness kamayadi (lekin `not_reached` baribir kerak) | `attempt_items` prioriteti |
| 7 | **Bir forma qayta ishlatiladimi?** | **Ha** tavsiya etiladi (kalibrlash uchun) | C-1, anchor |
| 8 | **Fan/yo'nalishlar soni va turlari?** | 5–15 fan, darajalar A/B/C | `scales`, `programs` |
| 9 | **Hududiy (offline) imtihonlarda OMR/skaner bormi?** | Ha/yo'q | `import` oqimi, `source='scan'` |
| 10 | **PII saqlash muddati?** | 3 / 5 / 10 yil | Retensiya siyosati, arxiv partition |

---

## 14. Oltin qoidalar (xulosa)

1. **Item identifikatsiyasi pozitsiya emas** — global `item_id` + `version`.
   Pozitsiya faqat **taqdimot** ma'lumoti (`display_label`).
2. **Har bir javob item darajasida**, append-only; `1A2B3C4D` faqat eksport uchun.
3. **Kalit va `b` muzlatiladi** (`scoring_snapshot_items`), natija
   **versiyalanadi**, regrade eskisini **o'zgartirmaydi**.
4. **O'qituvchi hech qachon `b` kiritmaydi** — yangi item `b = 0.0`,
   keyin tizim hisoblaydi.
5. **`b` — `item_version` ga bog'langan**: matn o'zgarsa, statistika noldan.
6. **Not-reached ≠ omitted** — 45 savolli vaqtli testda **taqdimot logi**
   bilan ajratilishi shart.
7. **Item turi (`mcq4`/`mcq6`/`numeric`/`text`) va `answer_spec`** —
   baholash va `c₀` ning birdan-bir manbai.
8. **Sessiya ko'rsatkichlari** (Reliability, separation, θ SD, SEM)
   saqlanmasa, equating va milliy shkala qurilmaydi.
9. **DIF o'zgaruvchilari va javob vaqtlari** — bir marta o'tkazib yuborilsa,
   **orqaga qaytmaydi**.
10. **Incremental hisoblash** — `responses` hech qachon issiq yo'lda
    skanerlanmaydi.
11. **`audit_log` — admin uchun; `attempt_events`/`responses` — o'quvchi uchun.**
12. **Professional daraja = 68 jadval + 5 qatlamli oqim + psixometrist imzosi.**
    Taxminiy vaqt: **12 oy** (1–2 developer + 0.5 psixometrist).

### Yakuniy hukm

> Arxitektura **to'g'ri poydevorda** (item-level javoblar, snapshot scoring,
> append-only tarix, anchor/equating uchun jadvallar). Lekin u **«A/B/C/D
> varag'i»** uslubidagi testni modellashtiradi. Milliy Sertifikatning haqiqiy
> strukturasi (`mcq4 + mcq6 + numeric + text`, 45 savol, 10 tasi ochiq javob)
> **10 ta Critical** va **12 ta High** o'zgarishni talab qiladi.
>
> Eng xavfli uchta narsa:
> **(1)** item statistikasi uzluksizligi (C-1 — kalibrlashning bo'lish
> shart-sharti);
> **(2)** not-reached / speededness (C-2 — θ va `b` ni tizimli buzadi);
> **(3)** DIF, javob vaqti va LD kabi **qaytarib bo'lmaydigan** ma'lumotlarning
> yo'qligi (C-5, H-5).
>
> Shu uchtasi bugun hal qilinsa, keyingi 12 oyda to'liq professional
> psixometrik o'lchov tizimi qurish mumkin.

### Keyingi hujjatlar (taklif)

| Yangi hujjat | Mazmuni |
|---|---|
| `09-ITEM-MODEL.md` | `item_type`, `answer_spec`, `numeric/text` normalizatsiya qoidalari, misollar |
| `10-STATISTIKA-PIPELINE.md` | `item_session_counters` → `item_statistics` → `session_statistics` → fit → DIF oqimi |
| `11-SHKALA-VA-SERTIFIKAT.md` | `scales`, cut-scores, `raw→θ` jadvali, sertifikat va verifikatsiya |
| `12-HODIM-OQIMLARI.md` | Kalit 4-eyes, ko'rik, apellyatsiya, item bog'lash jarayonlari |

