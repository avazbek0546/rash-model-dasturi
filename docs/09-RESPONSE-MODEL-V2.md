# 09 — Response Model v2 Specification

> **Hujjat turi:** arxitektura spetsifikatsiyasi (yakuniy ko'rinish).
> **Kod yozilmagan. DDL yozilmagan.** Barcha jadvallar **maydonlar
> lug'ati** (data dictionary) ko'rinishida — turlar ma'lumot uchun
> ko'rsatilgan, lekin jadval yaratish buyruqlari berilmagan.
> **Tegishli hujjatlar:** `02` (§3 javoblar), `04` (§3 autosave/submit),
> `08` (C-2, C-4, M-1…M-3, §8.3).

## 0. Qamrov, o'qilgan materiallar va asosiy xulosa

### 0.1. Nima ko'rib chiqildi

| Hujjat | Tegishli joy | Hozirgi holat |
|---|---|---|
| `02-DATABASE-SCHEMA.md` §3 | `responses`: `is_current`, `superseded_by`, `given_option` (`A–D`), `response_state` = `answered/omitted/cleared`; `attempt_response_current` — VIEW | ⚠️ Bir qatlamli; `mcq6` va open javobga joy yo'q |
| `02 §5.4` | `responses` partition + partial unique indeks (`WHERE is_current`) | ⚠️ Hot-path churn (audit M-3) |
| `04-API-VA-UI-MVP.md` §3 | `PUT /responses` → `saved`/`cleared`; `option = null` → `cleared` | ⚠️ `not_reached`, open javob, `client_seq` semantikasi yo'q |
| `08-PSIKOMETRIK-AUDIT.md` | C-2 (not-reached), C-4 (item-level snapshot), M-2, M-3, §8.3 (`attempt_responses_current` — **jadval**) | ✅ Yo'nalish to'g'ri, lekin `02` bilan **ziddiyatda** |

### 0.2. Audit aniqlagan uchta tizimli kamchilik

1. **Bir qatlamli model** → `is_current` partial indeksi hot-path'da churn
   beradi va `responses` bir vaqtda ham **log**, ham **joriy holat**, ham
   **baholash** ma'lumotini saqlaydi (javobgarlik aralashmasi).
2. **`not_reached` fizik jihatdan ifodalanmaydi** — `responses` da «savol
   taqdim etildi, lekin javob yo'q» degan **yozuv umuman bo'lmaydi** (satr
   faqat javob bo'lganda paydo bo'ladi). Ya'ni `p_used = C/N` ning maxraji
   noto'g'ri (audit C-2).
3. **Status bir o'qda aralashtirilgan** — so'ralgan 6 kod (`answered`,
   `omitted`, `not_reached`, `invalid_multiple`, `auto_scored`,
   `manual_scored`) aslida **uchta mustaqil o'q**: qabul qilish, baholash,
   yaroqlilik. Ularni bitta maydonda saqlash mantiqiy ziddiyat beradi
   (masalan, «`answered` **va** `manual_scored`» bir vaqtda bo'lishi mumkin).

### 0.3. v2 ning asosiy qarori (bir jumlada)

> Javob modeli **uch mustaqil o'q** (capture / score / validity),
> **to'rt artefakt** (taqdimot, qabul logi, joriy ko'rinish, baholash
> snapshot'i) va **o'n ikkita invariant**dan iborat; bunda
> `attempt_response_current` **view emas, haqiqiy jadval** bo'ladi.

---

## 1. To'rt artefakt va ular orasidagi munosabat (1-savol)

### 1.1. Artefaktlar

| # | Artefakt | Javobgarlik | O'zgaruvchanlik |
|---|---|---|---|
| **A** | `delivery.attempt_items` | **Taqdimot haqiqati**: savol ekranga chiqdimikan, qachon, qancha vaqt | `in_progress` davomida mutable |
| **B** | `delivery.responses` | **Qabul logi**: o'quvchi *nima qildi* | **Har doim immutable** (t₀ dan) |
| **C** | `delivery.attempt_responses_current` | **Joriy ko'rinish** (B ning proyeksiyasi) | `in_progress` davomida mutable, submit'da **muzlatiladi** |
| **D** | `scoring.scoring_snapshot_items` | **Baholash haqiqati**: ishlatilgan kalit, `b`, `P̂`, ball | **Yaratilgach abadiy immutable** |

### 1.2. Munosabat diagrammasi

```
        ┌────────────────────────────────┐
        │ A) attempt_items               │  "ko'rganmi?"  (taqdimot)
        │  (attempt_id, form_item_id)    │
        └───────────────┬────────────────┘
                        │ not_reached / omitted shu yerdan aniqlanadi
                        ▼
   ┌──────────────────────────┐   proyeksiya   ┌──────────────────────────────┐
   │ B) responses             │ ─────────────► │ C) attempt_responses_current │
   │  append-only LOG (1..N)  │                │  1 satr / (attempt, item)    │
   │  har revision — yangi    │                │  last_response_id bilan      │
   └──────────────────────────┘                └──────────────┬───────────────┘
                                                              │ grading vaqtida
                                                              ▼
                                             ┌──────────────────────────────┐
                                             │ D) scoring_snapshot_items    │
                                             │  kalit + b + P̂ + ball (frozen) │
                                             └──────────────┬───────────────┘
                                                            ▼
                                     item_session_counters (incremental agregat)
                                     item_statistics / session_statistics
```

### 1.3. Munosabat qoidalari

| Qoida | Mazmuni |
|---|---|
| **R1** | **B — yagona haqiqat** «o'quvchi nima qildi» savoliga; har bir tahlil B ga qaytib tekshirilishi mumkin |
| **R2** | **C — B ning deterministik proyeksiyasi**: C dagi har satr B dagi kamida bitta voqeaga tayanadi (`last_response_id`); C.`revision` = B dagi maksimal `revision` |
| **R3** | **C hech qachon psixometrik haqiqat emas** — baholashdan keyin haqiqat **D** da; C faqat UI, tezkor hisoblash va qayta o'qish uchun |
| **R4** | **A — `not_reached` ning yagona manbai**; B da «javob yo'q» satri bo'lmagani uchun B o'zi «ko'rmadimi yoki ko'rib tashlab ketdimi» ni ajratolmaydi |
| **R5** | **D o'z-o'zini to'liq ta'minlaydi**: kalit, `b`, `P̂`, `max_score`, `engine_version` nusxalanadi; D hech qachon o'zgaruvchan jadvallarga qayta bog'lanmaydi |
| **R6** | **Kardinallik**: A — taqdim etilgan har savolga ≤ 1 satr; B — har qabul voqeasiga 1 satr (1…N); C — (attempt, item) uchun ≤ 1 satr; D — baholash matritsasidagi har savolga 1 satr |

### 1.4. Nega `view` emas — **jadval**?

| Sabab | Izoh |
|---|---|
| Yozish yo'li | `is_current` partial indeksi har saqlashda qayta yoziladi → bloat, `VACUUM` bosimi (audit M-3) |
| Javobgarlik | Log *faqat qabul*ni saqlashi kerak; view logdan hosilaviy ustunlar chiqaradi → vaqt o'tib logga ham hosilaviy maydonlar «oqib ketadi» |
| Baholash maydonlari | `score_awarded`, `match_rule`, `score_status` ni **logga yozib bo'lmaydi** (log immutable), joriy ko'rinishga esa yozish kerak |
| Tezlik | C — PK bo'yicha 45 satr (≈1 ms); view indeks + filtr talab qiladi |
| Partition | B partition'lanadi (oylik) va arxivlanadi; C partition'lanmaydi, sessiya bilan birga arxivlanadi |

> **Migratsiya eslatmasi:** `02` dagi `attempt_response_current` **view** va
> `responses.is_current` maydoni **bekor qilinadi**. `superseded_by` saqlanadi
> (revision zanjiri uchun), lekin endi «joriy»lik **C** orqali aniqlanadi.

### 1.5. Proyeksiyani tiklash (replay) qoidasi

| Qadam | Amal |
|---|---|
| 1 | B ni (attempt_id, form_item_id, revision) tartibida o'qish |
| 2 | Har bir item uchun **oxirgi** `capture_status` ni «yaroqli qabul» sifatida olish (`revision` maksimal) |
| 3 | A dan `first_presented_at`, `dwell_ms` ni olib, `not_reached`/`omitted` ni qayta aniqlash |
| 4 | C ni qayta qurish (`last_response_id`, `revision`, `capture_status`) |

> **Muhim:** C ni «jimgina» tuzatish **taqiqlanadi**. Xato proyeksiya
> aniqlansa, B ga `source='system'`, `capture_status='projection_repair'`
> voqeasi **qo'shiladi** + `audit_log` yoziladi, keyin replay bajariladi.

---

## 2. Autosave qayerga yoziladi (2-savol)

### 2.1. Yozish jadvali (write path matrix)

| # | Amal | A `attempt_items` | B `responses` | C `…current` | Boshqa | Izoh |
|---|---|---|---|---|---|---|
| 1 | Mini App ochildi | **INSERT** (tier-1) | — | — | `attempt_events` (`opened`) | Taqdimot boshlanadi |
| 2 | Savol ekranga chiqdi | **UPSERT** (tier-1: `presentation_count`) | — | — | — | `not_reached` uchun |
| 3 | Variant tanlandi (autosave) | UPSERT (tier-2) | **INSERT** (yangi revision) | **UPSERT** (`last_response_id`) | `attempts.revision+1`, `attempt_events` (`saved`) | Asosiy hot path |
| 4 | Open javob kiritildi (`36a = 12`) | UPSERT (tier-2) | INSERT | UPSERT | yuqoridagi kabi | `raw_answer` + normallashtirilgan |
| 5 | Javob tozalandi | UPSERT | INSERT (`cleared`) | UPSERT (`cleared`) | — | Yangi revision, **o'chirish emas** |
| 6 | Refresh / qayta ochish | SELECT | — | **SELECT** (manba) | — | B dan emas, C dan o'qiladi |
| 7 | Yakunlash (submit) | **final UPSERT** | **INSERT** (yakuniy holat) | **freeze** (`frozen_at`) | `attempts.status`, `attempt_events` | Muzlatish nuqtasi |
| 8 | `end_time` tugadi, o'quvchi yo'q | final UPSERT (`not_reached`) | INSERT (`source='system'`) | freeze | `status='submitted_late'` | Server tomonda |
| 9 | Baholash (grading) | — | — | SELECT | **D INSERT**, `item_session_counters` UPSERT | Psixometrik hisob |
| 10 | Qo'lda ko'rik / apellyatsiya | — | — | — | `scoring_reviews`, **yangi D satri**, yangi `result_version` | B/C **tegilmaydi** |

### 2.2. Nega aynan shunday (yozish tartibi va sabablari)

| Qoida | Sabab |
|---|---|
| **Tranzaksiya tartibi:** avval `attempts.revision` (qatorni qulflash), keyin B → C → A | Deadlock'ning oldini oladi (hamma paket bir xil tartibda qulflaydi) |
| **B ga har doim INSERT** (UPDATE yo'q) | Immutable tarix; `revision` zanjiri uzluksiz |
| **C ga har doim UPSERT** | Joriy holat bitta joyda; `last_response_id` orqali iz qoldiradi |
| **`attempts.revision` paketda 1 marta** oshadi | Har item uchun qator yangilashdan arzon (row-lock kamayadi) |
| **A ikki tier'ga bo'linadi** | Tier-1 (`first_presented_at`, `presentation_count`) **darhol** yoziladi (chunki `not_reached` shunga bog'liq); tier-2 (`dwell_ms`, `focus_losses`, `scroll_events`) — keyinroq yoki past prioritetli navbatda |
| **Telemetriya yumshatilishi mumkin** | 100k foydalanuvchida tier-2 ni har paketda yozish ortiqcha; `dwell_ms` yig'ilib, kamdan-kam yoziladi |
| **`audit_log` ga hech narsa yozilmaydi** | Autosave — foydalanuvchi harakati, audit emas (audit M-1); faqat `attempt_events` (paket boshiga 1 satr) |
| **`client_seq` takrorlanmas** ((attempt, client_seq)) | Tarmoq qayta urinishida idempotentlik; takror paket rad etiladi, javob `200` |
| **`source` maydoni** | `webapp` / `bot` / `import` / `omr` / `admin` / `system` — qaysi kanaldan kelganini bilish |

### 2.3. Idempotentlik va konflikt boshqaruvi

| Holat | Xatti-harakat |
|---|---|
| Bir xil `client_seq` qaytadan keladi | **Yangi satr yozilmaydi**; B/C tegilmagan; `200` + joriy `revision` |
| `revision` eski (boshqa qurilma oldinda) | `409` + C dagi joriy holat; klient **C ni ustun qilib** UI ni moslashtiradi |
| Ikki qurilma bir vaqtda yozadi | Oxirgi `revision` ustun; konflikt `attempt_events` ga (`conflict_resolved`) |
| `client_seq` teskari (eski paket kechikdi) | **Rad etiladi** (monotonlik); C yangilanmaydi; B ga `source='system'`, `capture_status='rejected_stale'` |
| Tarmoq uzilgach 5 paket birdan keladi | Har biri o'z `client_seq` bilan tartib bo'yicha qayta ishlanadi |
| Urinish `submitted` | `409`; `end_time` o'tgan bo'lsa `410` |

---

## 3. Yakunlashda nima immutable bo'ladi (3-savol)

### 3.1. Hayot sikli va qulflash nuqtalari

| Faza | A taqdimot | B log | C joriy | D snapshot | `attempts` / natija |
|---|---|---|---|---|---|
| `in_progress` | mutable | **immutable** | mutable | yo'q | `status` mutable |
| **submit** (`freeze`) | **frozen** | immutable | **frozen** | yo'q | `status='submitted'` |
| `end_time` + avtomatik | **frozen** | immutable | frozen | yo'q | `status='submitted_late'` |
| Baholash | frozen | immutable | frozen | **INSERT → immutable** | θ/raw/scaled yoziladi |
| Natija e'loni | frozen | immutable | frozen | immutable | `result_versions` — **immutable** |
| Qayta baholash / apellyatsiya | frozen | **immutable** | frozen | **yangi satr** (`supersedes_id`) | **yangi** `result_version` |

### 3.2. Yakunlash (submit) paytida bajariladigan qadamlar

| # | Qadam | Natija |
|---|---|---|
| 1 | `attempts` qatori qulflanadi | Ikki qurilma bir vaqtda yakunlamasin |
| 2 | Klientdagi oxirgi o'zgarishlar paketi qabul qilinadi | B ga yoziladi, C yangilanadi |
| 3 | **Finalizatsiya** — A dan «ko'rilgan/ko'rilmagan» aniqlanadi | Har savol `answered` / `cleared` / `omitted` / `not_reached` ga ajratiladi |
| 4 | C ga `frozen_at` yoziladi | Joriy holat **muzlatiladi** |
| 5 | A ga `last_presented_at`, `dwell_ms` final qiymati | Telemetriya yakunlanadi |
| 6 | `attempts.status`, `submitted_at`, `submit_mode`, `duration_seconds` | Yakunlash fakti |
| 7 | `attempt_events` (`submitted`, `auto_finalized`, `frozen`) | Hodisa izi |

> **Muhim:** `freeze` dan keyin A va C — **faqat o'qish**; B ga **hech qachon**
> yozilmaydi (u t₀ dan immutable). Immutability ham **ilova**, ham **trigger**
> darajasida ta'minlanadi (`attempts.status` ga bog'langan tekshiruv) — bu
> `08` §8.5 trigger siyosatining javob modeliga proyeksiyasi.

### 3.3. Nima **hech qachon** immutable bo'lmaydi (ataylab)

| Maydon | Sabab |
|---|---|
| `attempts.status` | `submitted → graded → invalid` kabi qonuniy o'tishlar bor |
| `attempts.theta / raw_score / scaled_score` | Faqat **tezkor ko'rsatish** uchun nusxa; haqiqat **D** va `scoring_snapshots` da |
| `attempts.deleted_at` | Soft delete (audit talabi) |
| `item_session_counters` | Incremental agregat — har yakunlashda qayta yoziladi (haqiqat B/D da) |

---

## 4. Holatlar tizimi: uchta mustaqil o'q (4-savol)

So'ralgan 6 kod bitta maydonda emas, **uchta o'qda** saqlanadi. Bu —
psixometrik jihatdan majburiy, chunki bu o'qlar **mustaqil** o'zgaradi.

### 4.1. O'q 1 — `capture_status` (o'quvchi nima qildi)

| Kod | Aniqlama | Qanday aniqlanadi | `p` maxrajiga kiradimi |
|---|---|---|---|
| `answered` | Yaroqli javob mavjud (variant tanlangan yoki open javob normallashtirilgan) | B da oxirgi revisionda `selected_option`/`normalized_value` bo'sh emas | **Ha** (`N_answered`) |
| `cleared` | O'quvchi javobni **ataylab** olib tashladi (variantni qayta bosdi) va boshqa javob bermadi | Oxirgi revision `cleared`, oldingi revisionlarda javob bor edi | Yo'q (`omitted` ga qo'shiladi) |
| `omitted` | Savol **ko'rildi**, lekin javob berilmadi (ataylab tashlab ketdi) | A da `first_presented_at` bor **va** `dwell_ms ≥ SEE_THRESHOLD` (default 2000 ms) | Yo'q (`omitted`) |
| `not_reached` | Savol **umuman ko'rilmadi** yoki ko'rishga ulgurmadi (vaqt tugadi) | A da `first_presented_at` yo'q **yoki** `dwell_ms < SEE_THRESHOLD` | **Yo'q** — `p` maxrajidan **chiqariladi** (audit C-2) |
| `not_presented` | Savol taqdim **etilmagan** (urinish boshlanmagan, texnik nosozlik) | A da satr yo'q + urinish `expired`/`invalid` | Yo'q |
| `invalid_multiple` | Bir savolga **bir nechta** belgi: OMR/skanerda ikki pufak, admin importida ziddiyatli qiymat, open javobda «12 yoki 15» | Import tahlilida `capture_conflicts` bo'sh emas | `pending_review` bo'lsa — **chiqariladi** |
| `rejected_stale` | Kechikib kelgan, monotonligi buzilgan paket | `client_seq` teskari | Yo'q (faqat iz) |
| `projection_repair` | Proyeksiyani tiklash voqeasi (system) | `source='system'` | Yo'q (faqat iz) |

**`omitted` va `not_reached` ni ajratish qoidasi (majburiy va deterministik):**

```
1. A da first_presented_at bo'lmasa           → not_presented (faza tugamagan bo'lsa) / not_reached
2. first_presented_at bor, dwell_ms < T      → not_reached   (ko'rishga ulgurmadi)
3. first_presented_at bor, dwell_ms ≥ T,
   B da hech qanday voqea yo'q               → omitted
4. oxirgi voqea 'cleared'                    → cleared  (hisobda omitted bilan bir xil)
5. oxirgi voqea 'answered' (yaroqli javob)   → answered
6. `capture_conflicts` bo'sh emas            → invalid_multiple
```

`T` (SEE_THRESHOLD) — **sozlanadigan**, lekin `dwell_ms` **saqlanadi**, shuning
uchun siyosat o'zgarsa, ajratish **qayta hisoblanadi** (ma'lumot yo'qolmaydi).

### 4.2. O'q 2 — `score_status` (baholash holati)

| Kod | Aniqlama | Kim qo'yadi | Talab qilinadigan hamroh maydonlar |
|---|---|---|---|
| `unscored` | Hali baholanmagan (qabul paytida yoki `not_reached`) | tizim (default) | — |
| `auto_scored` | Javob **mashina** tomonidan baholandi (variant mosligi / numeric tolerantlik / matn normallashuvi) | scoring engine | `score_awarded`, `max_score`, `match_rule`, `engine_version`, `scored_at` |
| `manual_scored` | Ball **inson** tomonidan qo'yildi | reviewer (admin/psixometrist) | `review_id`, `reviewer_id`, `review_reason`, `manual_scored_at` |
| `pending_review` | Avtomatik baholash **ishonchsiz** → ko'rik navbati (`invalid_multiple`, birlik/noaniq format, sinonimsiz matn) | scoring engine | `review_queue_id`, `review_reason_code`, vaqtinchalik `score_awarded` (odatda 0, `is_provisional=true`) |
| `rescored` | Ball qayta hisoblandi (regrade yoki qabul qilingan apellyatsiya) | tizim/reviewer | `superseded_by_snapshot_id`, `rescore_reason`, yangi `result_version_id` |
| `void` | Ball hisobga olinmaydi (texnik karantin) | admin | `void_reason`, `voided_by`, `voided_at` |

> **Muhim:** `auto_scored` va `manual_scored` — bu **qabul darajasi emas**.
> Bitta satr bir vaqtda `capture_status = 'answered'` **va**
> `score_status = 'manual_scored'` bo'lishi mumkin. Shu sababli ular
> ajratilishi **shart**.

### 4.3. O'q 3 — `validity_status` (tahliliy yaroqlilik)

| Kod | Aniqlama | Ta'sir |
|---|---|---|
| `valid` | Normal holat | Barcha tahlillarga kiradi |
| `suspect` | Shubhali, lekin chiqarilmagan (masalan, `dwell_ms` juda kichik, bir qurilmadan ko'p urinish) | Kiradi, lekin `validity_flags` bilan belgilanadi; **kalibrlashda vaqtincha chiqariladi** |
| `invalid` | Rasmiy natijadan ham, kalibrlashdan ham **chiqarilgan** (admin qarori) | `raw_score` qayta hisoblanadi; natija `result_version` bilan yangilanadi |
| `quarantined` | Admin qaroriga qadar **hamma joydan** chiqarilgan | Kalibrlashga ham, hisobotga ham kirmaydi |

`validity_status` **faqat admin/system** qo'yadi va har doim `audit_log` +
`attempt_events` ga yoziladi.

### 4.4. Yakuniy `response_status` — **hosilaviy** (derived) maydon

API va UI uchun qulay bo'lishi uchun bitta `response_status` **ko'rsatiladi**,
lekin u **saqlanmaydi** — quyidagi qat'iy tartib bo'yicha **hisoblanadi**:

| Tartib | Shart | `response_status` |
|---|---|---|
| 1 | `validity_status = 'quarantined'` | `quarantined` |
| 2 | `capture_status = 'not_presented'` | `not_presented` |
| 3 | `capture_status = 'not_reached'` | `not_reached` |
| 4 | `capture_status = 'invalid_multiple'` **va** `score_status = 'pending_review'` | `pending_review` |
| 5 | `score_status = 'void'` | `void` |
| 6 | `score_status = 'manual_scored'` | `manual_scored` |
| 7 | `score_status = 'auto_scored'` (yoki `rescored`) | `auto_scored` |
| 8 | `capture_status IN ('omitted','cleared')` | `omitted` |
| 9 | `capture_status = 'answered'` | `answered` |

> **6 ta so'ralgan kod shu tarzda to'liq qoplanadi**, lekin saqlash
> **3 o'qda** bo'ladi (ziddiyatsiz) — hosilaviy maydon esa faqat
> **ko'rsatish/eksport** uchun.

### 4.5. Maxrajlar va baholash siyosatlari (psixometrik yadro)

Har bir savol uchun hisoblanadigan to'plamlar:

| To'plam | Ta'rif |
|---|---|
| `N_presented` | A da satr bor (taqdim etilgan) |
| `N_reached` | `not_reached` **bo'lmagan** taqdim etilganlar |
| `N_answered` | `capture_status = 'answered'` |
| `N_omitted` | `omitted` + `cleared` |
| `N_not_reached` | `not_reached` + `not_presented` |
| `N_invalid` | `invalid_multiple` yoki `pending_review` |
| `C` | `score_awarded ≥ max_score` bo'lganlar |
| `Score_sum` | Barcha `score_awarded` yig'indisi (polytomous readiness) |

**Ikki rasmiy siyosat (ikkalasi ham saqlanadi):**

| Siyosat | `omitted`/`cleared` | `not_reached` | Qaerda ishlatiladi |
|---|---|---|---|
| **`official`** (Milliy Sertifikat uchun default) | **0** ball | **`u_ij = missing`** (θ dan chiqariladi), `p` maxrajiga kirmaydi | θ, `b`, rasmiy natija |
| **`strict`** (maxsus hisobot / apellyatsiya) | 0 | **0** ball | Zaxira hisob, sezgirlik tahlili |

Ya'ni har urinish uchun **ikki xom ball** saqlanadi: `raw_score` (official) va
`raw_score_strict`. Bu «bir xil 31/45» ikki xil ma'no berishi mumkinligini
oshkor qiladi va apellyatsiyada asos bo'ladi.

---

## 5. Yagona model yoki alohida model? (5-savol)

### 5.1. Baholash (verdict)

| Variant | Baho | Sabab |
|---|---|---|
| **A. Yagona javob modeli** (1 satr = 1 item-version-instance), turga bog'liq maydonlar bilan | ✅ **Tavsiya** | Rasch/IRT **uzun formatli matritsa** talab qiladi; kalibrlash, fit, DIF, equating — hammasi bir xil shakldagi jadvaldan ishlaydi |
| B. Alohida `mcq_responses` + `open_responses` | ❌ rad etiladi | Har kalibrlash so'rovi `UNION` talab qiladi; ikki xil ingestion yo'li; partition ikkilanadi; audit ikki joyda |
| C. Yagona model + **kengaytma jadvali** (`open_response_detail`) | ⚠️ kelajak uchun zaxira | Faqat qismiy ball (rubrika/steps) kerak bo'lganda qo'shiladi — **asosiy modelni almashtirmaydi** |

**Xulosa:** `mcq4`, `mcq6`, `numeric`, `text` — **bitta javob modeli**,
`answer_kind` diskriminatori bilan. Farqlar sxemada emas, **`item_types` va
`answer_spec` (item-version snapshot'i)** da yashaydi.

### 5.2. Nima uchun bir model yetarli

| Talab | Yagona modelda qanday qondiriladi |
|---|---|
| IRT matritsasi (o'quvchi × item) | Har (attempt, item) uchun **1 satr** — turidan qat'i nazar |
| Dichotomous `u_ij` | `score_awarded ≥ max_score` → `u = 1` (bugun barcha turlar shunday) |
| Polytomous (kelajak) | `score_awarded` + `max_score` + `category_counts` |
| `c₀` (guessing) | `item_types.guessing` → `mcq4` 0.2500, `mcq6` 0.1667, `numeric/text` 0 |
| Normalizatsiya | `answer_spec.normalize[]` — model emas, **item** xossasi |
| Qo'lda ko'rik | `numeric/text` da ko'proq uchraydi — lekin `score_status` mexanizmi **bir xil** |
| UX (kartochka vs input) | Frontend `answer_kind` bo'yicha render qiladi — modelga ta'sir qilmaydi |

### 5.3. Turga bog'liq farqlar (model ichida)

| Jihat | `mcq4` (1–32) | `mcq6` (33–35) | `numeric` (36–45) | `text` (36–45) |
|---|---|---|---|---|
| Kiritish | 4 tugma | 6 tugma | raqamli klaviatura | matn maydoni |
| Asosiy qiymat | `selected_option` | `selected_option` | `raw_answer` + `numeric_value` | `raw_answer` + `normalized_value` |
| `answer_payload` | `{kind:option}` | `{kind:option, options:6}` | `{unit, fraction_form, precision}` | `{tokens[]}` |
| `c₀` | 0.2500 | 0.1667 | 0.0000 | 0.0000 |
| Avtomatik baholash | aniq moslik | aniq moslik | tolerantlik + normallashuv | normallashuv (registr, bo'sh joy) |
| Ko'rik ehtimoli | juda past | juda past | o'rta (`birlik`, `1/2`) | yuqori (sinonim) |
| `invalid_multiple` manbai | amalda yo'q | amalda yo'q | `12 yoki 15` | `Toshkent / Uzbekistan` |

### 5.4. Kengaytma jadvali qachon kerak bo'ladi (kelajak)

| Shart | Nega asosiy model yetmaydi |
|---|---|
| Ko'p qadamli rubrika (0 / 1 / 2 ball) | Har qadam uchun alohida dalil kerak |
| O'quvchi yechim qadamlarini saqlash | Katta konteyner asosiy jadvalni og'irlashtiradi |
| OCR/OMR xom tasvirini saqlash | Binar ma'lumot asosiy modelga to'g'ri kelmaydi |
| Birlik/aniqlik bo'yicha alohida tahlil | Maxsus ustunlar to'plami |

---

## 6. Testlet (36a/36b) va local dependence metadata (6-savol)

### 6.1. Muammo

36a va 36b — **bitta matn** asosida ikki javob. Psixometrik jihatdan bu
**lokal bog'liqlik (LD)** manbai: bir qismga to'g'ri javob bergan o'quvchi
ikkinchisiga ham yuqori ehtimol bilan to'g'ri javob beradi. Bu Rasch'ning
**bir o'lchovlilik / lokal mustaqillik** shartini buzadi va:

* `b` baholari **noto'g'ri** (item «osonroq» ko'rinadi);
* `SE(b)` **sun'iy kichik** (aniqlik yolg'on oshadi);
* `Infit/Outfit` **shishadi** (MNSQ > 1.3) — savol «yaroqsiz» ko'rinadi;
* test informatsiya funksiyasi va `SEM` xato baholanadi.

### 6.2. Saqlanishi shart bo'lgan metadata

**Item darajasida (`items` / `item_versions`):**

| Maydon | Tur | Aniqlama | Misol |
|---|---|---|---|
| `testlet_ref` | matn | Testlet uchun **barqaror** identifikator (formalar orasida bir xil) | `NS2026-MATH-Q36` |
| `testlet_role` | matn | `stem` / `part` / `standalone` | `part` |
| `part_index` | son | Qism tartibi | `1` (36a) |
| `part_count` | son | Testletdagi qismlar soni | `2` |
| `shared_stem_ref` | matn | Umumiy matn havolasi (PDF belgisi) | `NS2026-MATH-Q36` |
| `dependency_type` | matn | `none` / `shared_stem` / `answer_chain` / `shared_figure` | `shared_stem` |
| `dependency_strength_expert` | matn | Ekspert bahosi: `weak` / `moderate` / `strong` | `strong` |
| `ld_calibration_policy` | matn | `flag_only` / `drop_second` / `bundle_testlet` / `exclude_from_calibration` | `flag_only` |

**Javob darajasida (A, B, C, D — denormalizatsiya):**

| Maydon | Nega javobda ham yoziladi |
|---|---|
| `testlet_ref`, `part_index` | LD tahlili B/D dan **JOINsiz** ishlashi uchun |
| `testlet_incomplete` (flag) | Qismlardan biri `not_reached` bo'lsa, juftlik tahlilga kirmasligi kerak |
| `dwell_ms`, `first_presented_at` | Juftlikda «matnni o'qishga ketgan vaqt» — LD ning qo'shimcha dalili |
| har ikki qismning `score_awarded` | Juftlik reziduallarini hisoblash |

### 6.3. LD tahlili uchun artefaktlar

| Artefakt | Asosiy maydonlar | Maqsad |
|---|---|---|
| `local_dependence_checks` | `session_id`, `testlet_ref`, `item_a`, `item_b`, `n_pairs`, `residual_corr`, `chi2`, `q3_statistic`, `flag`, `parameter_set_id`, `computed_at` | Juftlik darajasidagi LD hisoboti |
| `testlet_statistics` | `session_id`, `testlet_ref`, `n_complete_pairs`, `mean_pairwise_corr`, `mean_gain_if_first_correct`, `difficulty_gap_b`, `flag` | Testlet darajasidagi umumiy ko'rsatkich |

**Qaror chegaralari (tavsiya):**

| `residual_corr` | Xulosa | Harakat |
|---|---|---|
| `< 0.20` | LD yo'q | `ld_calibration_policy = 'flag_only'` |
| `0.20 – 0.30` | Yengil LD | Hisobotda belgilash; `SE(b)` tuzatilmaydi |
| `> 0.30` | Kuchli LD | `drop_second` (kalibrlashda 36b ni chiqarish) **yoki** `bundle_testlet` |
| `answer_chain` va `> 0.40` | Zanjirli bog'liqlik | `exclude_from_calibration` + alohida siyosat |

### 6.4. `answer_chain` uchun alohida ogohlantirish

Agar 36b **faqat 36a to'g'ri bo'lganda** mazmunli bo'lsa (zanjir):

* `p(36b)` **sun'iy past** bo'ladi (36a ni xato qilganlar 36b ni ham xato qiladi);
* `b(36b)` **sun'iy yuqori** chiqadi;
* ikkovi bir o'lchovga qo'yilsa, **o'lchov buziladi**.

Shu sababli `dependency_type = 'answer_chain'` juftliklar
**kalibrlashdan chiqariladi** va faqat **natija hisoblashda** ishtirok etadi.
Bu `answer_spec` da ham aks etadi (zanjir qoidasi: qaysi item to'g'ri bo'lishi
shart). Aks holda o'qituvchi «36b nega bunchalik qiyin?» degan savolga
noto'g'ri javob oladi.

> **Majburiy:** 36a–45b uchun `testlet_ref` **bo'sh bo'lmasligi shart** —
> u bo'lmasa LD tahlili ham, to'g'ri kalibrlash ham mumkin emas.

---

## 7. Psixometrik tahlillar uchun majburiy maydonlar (7-savol)

Quyidagi lug'atlarda **M** = majburiy (bo'sh bo'lishi mumkin emas),
**S** = shartli (holatga qarab majburiy), **X** = ixtiyoriy.
Barcha vaqtlar **server vaqti** (client vaqti alohida `*_client_at` da).

### 7.1. B — qabul logi (`responses`)

| Maydon | Tur | M | Nima uchun kerak |
|---|---|---|---|
| `response_id` | son | M | Har voqea uchun yagona identifikator (audit ildizi) |
| `attempt_id` | son | M | Urinishga bog'lash |
| `item_id` | son | M | **Global identifikatsiya** (pozitsiya emas!) |
| `item_version_id` | son | M | `b` va kalit aynan shu versiyaga bog'lanadi |
| `form_item_id` | son | M | Taqdimot konteksti |
| `session_id`, `form_version_id` | son | M | Kalibrlash davri va formani aniqlash |
| `position`, `display_label`, `part` | son/matn | M | Taqdimot snapshot'i (hisobot, «36a») |
| `testlet_ref`, `part_index` | matn/son | S | LD tahlili (36a/36b uchun majburiy) |
| `revision` | son | M | Zanjir tartibi (1..N) |
| `prev_response_id`, `superseded_by` | son | S | Revision zanjiri; «joriy»ni tiklash |
| `event_type` | matn | M | `capture` / `clear` / `finalize` / `admin_fix` / `projection_repair` |
| `capture_status` | matn | M | **O'q 1** (4-bo'lim) |
| `answer_kind` | matn | M | `option` / `numeric` / `text` (turi item'dan nusxa) |
| `selected_option` | matn | S | MCQ javobi (`A`…`F`) |
| `raw_answer` | matn | S | O'quvchi **aynan** kiritgani (`12,5`, ` 12 `) — apellyatsiya uchun hal qiluvchi |
| `normalized_answer` | matn | S | Normallashgandan keyingi qiymat |
| `numeric_value` | son | S | Numeric javobning raqamli ko'rinishi (tolerantlik hisobi) |
| `answer_payload` | JSON | S | Turga xos qo'shimcha (`unit`, `fraction_form`, `tokens[]`) |
| `capture_conflicts` | JSON | S | `invalid_multiple` dalili (qaysi variantlar/qiymatlar) |
| `input_method` | matn | S | `tap` / `keyboard` / `import` / `omr` / `admin` (mode effekti tahlili) |
| `source` | matn | M | `webapp` / `bot` / `import` / `omr` / `admin` / `system` |
| `client_seq` | son | M | Idempotentlik va tartib (webapp/import) |
| `captured_at_client` | vaqt | X | Qurilma vaqti (faqat ma'lumot uchun; tatbiq etilmaydi) |
| `recorded_at` | vaqt | M | **Server** qabul qilgan vaqt (majburiy haqiqat) |
| `client_clock_skew_ms` | son | X | Soat farqi (vaqt tahlilini tuzatish) |
| `request_id` | matn | M | So'rov bilan bog'lash (log/audit) |
| `ip_hash`, `device_hash` | matn | X | Anti-cheat, klaster tahlili (PII emas — hash) |
| `app_version`, `ui_variant` | matn | X | Interfeys o'zgarishining ta'sirini ajratish |
| `created_at` | vaqt | M | Partition kaliti (oylik) |

> **B da bo'lmasligi kerak:** `score_awarded`, `is_correct`, `match_rule`,
> `P̂`, `b`. Ular hosilaviy — D da yashaydi (invariant I4).

### 7.2. C — joriy ko'rinish (`attempt_responses_current`)

| Maydon | Tur | M | Nima uchun kerak |
|---|---|---|---|
| `attempt_id` + `form_item_id` | son | M | PK (tez o'qish) |
| `item_id`, `item_version_id` | son | M | Identifikatsiya (B bilan bir xil) |
| `last_response_id` | son | M | **B ga ishora** — izsiz satr bo'lmasligi kafolati (R2) |
| `revision` | son | M | Oxirgi revision (`= max(B.revision)`) |
| `capture_status` | matn | M | Proyeksiya natijasi |
| `answer_kind` | matn | M | UI render uchun |
| `selected_option`, `raw_answer`, `normalized_answer`, `numeric_value`, `answer_payload` | — | S | UI holatini tiklash (`GET state`) |
| `score_awarded`, `max_score` | son | S | **Vaqtinchalik** ball (UI javob berishi); haqiqat D da |
| `score_status` | matn | M | **O'q 2** (baholash holati) |
| `validity_status` | matn | M | **O'q 3** |
| `validity_flags` | JSON | S | Shubha belgilari |
| `testlet_ref`, `part_index` | matn/son | S | LD/UI guruhlash |
| `frozen_at` | vaqt | S | Submit'da muzlatilganini bildiradi (R3) |
| `updated_at` | vaqt | M | Oxirgi o'zgarish |

> **C da bo'lmasligi kerak:** `b`, `P̂`, `key_used` — bular faqat D da.

### 7.3. A — taqdimot va telemetriya (`attempt_items`)

| Maydon | Tur | M | Nima uchun kerak |
|---|---|---|---|
| `attempt_id`, `form_item_id` | son | M | PK |
| `item_id`, `item_version_id` | son | M | Identifikatsiya |
| `position`, `display_label`, `part` | — | M | PDF dagi belgi bilan solishtirish |
| `testlet_ref`, `part_index` | — | S | LD tahlili |
| `first_presented_at` | vaqt | **M** | **`not_reached` ning kaliti** (C-2) |
| `last_presented_at` | vaqt | **M** | Tugash paytida qaysi savolda edi |
| `presentation_count` | son | M | Necha marta ko'rindi (orqaga qaytish) |
| `dwell_ms` | son | **M** | Ko'rishga ketgan vaqt → `omitted`/`not_reached` ajratish |
| `total_dwell_ms` | son | M | Jami (bir necha marta ko'rilgan) |
| `focus_loss_count` | son | S | Ilovadan chiqib ketish (firibgarlik signali) |
| `scroll_events` | son | X | Xatti-harakat |
| `change_count` | son | M | Javobni necha marta o'zgartirdi (answer-changing tahlili) |
| `first_answer_at`, `final_answer_at` | vaqt | S | «Javob berishga ketgan vaqt» |
| `time_to_first_answer_ms` | son | S | Tezlik tahlili |
| `view_order_index` | son | M | Ko'rish tartibi (ketma-ket emas, sakrab ishlaganlar) |
| `navigation_path` | JSON | X | Qaysi savollardan qaysiga o'tdi |
| `was_at_end_at_timeout` | mantiqiy | S | `end_time` da shu savolda edi (speededness) |
| `telemetry_source` | matn | M | `webapp` / `import` / `system` (importda telemetriya yo'q) |

> **A bo'lmasa, quyidagilar imkonsiz:** `not_reached` ajratish, speededness
> indeksi, javob vaqti tahlili, «vaqt yetmadimi yoki bilmadimi» xulosasi
> (`08` §10 — «tiklanmaydi»).

### 7.4. D — baholash snapshot'i (`scoring_snapshot_items`)

Bu **psixometrik haqiqat**. Har bir maydon tahlilga bevosita xizmat qiladi.

| Maydon | Tur | M | Xizmat qiladigan tahlil |
|---|---|---|---|
| `snapshot_item_id` | son | M | Identifikatsiya |
| `snapshot_id` | son | M | Urinish darajasidagi snapshot (`θ`, `SE`, `raw`, `scaled`) |
| `attempt_id`, `session_id`, `form_version_id` | son | M | Davr/forma bo'yicha guruhlash |
| `form_item_id` | son | M | Formadagi pozitsiya konteksti |
| `item_id`, `item_version_id` | son | M | **Kalibrlash, drift, anchor** — hammasi shu ikkisi orqali |
| `display_label`, `position` | — | M | Hisobot («7-savol»), pozitsiya effekti tahlili |
| `testlet_ref`, `part_index` | — | S | **LD tahlili** |
| `parameter_set_id` | son | **M** | Qaysi `b` to'plami ishlatilgan (equating uchun) |
| `b_used` | son | **M** | **Infit/Outfit, person fit, `P̂`** — muzlatilgan `b` |
| `b_se_used` | son | S | Savol qiyinchiligi aniqligi (hisobot) |
| `b_source` | matn | M | `default` / `classical` / `rasch` / `anchor` |
| `is_anchor` | mantiqiy | **M** | Equating tahlili (anchor itemlar) |
| `anchor_b` | son | S | Anchor mosligini tekshirish |
| `key_used` | matn/JSON | **M** | O'sha paytdagi kalit (regrade, apellyatsiya, DIF) |
| `key_version_no`, `key_source` | son/matn | M | Kalit tarixi (4-eyes, audit) |
| `answer_kind` | matn | M | Baholash qoidasi |
| `raw_answer`, `normalized_answer` | matn | S | Apellyatsiya va ko'rik |
| `score_awarded`, `max_score` | son | **M** | `u_ij` (`score_awarded ≥ max_score`) |
| `score_status` | matn | **M** | `auto_scored` / `manual_scored` / `pending_review` |
| `match_rule` | matn | S | `exact` / `tolerance` / `normalized` / `manual` |
| `guessing_c` | son | **M** | `mcq4` 0.25 / `mcq6` 0.1667 / open 0 — **guessing tuzatishi** |
| `p_hat` | son | **M** | **Infit/Outfit** (kutilgan ehtimol) |
| `residual` | son | **M** | `u_ij − p_hat` → **Infit/Outfit, person fit** |
| `information` | son | **M** | `p_hat·(1−p_hat)` → **test informatsiya, `SEM`, `SE(θ)`** |
| `theta_used` | son | **M** | Rezidual `P̂` shu `θ` bilan hisoblangan (qayta chiqarish) |
| `engine_version` | matn | **M** | Reproducibility (`08` H-6) |
| `capture_status` | matn | M | `not_reached` ni tahlildan chiqarish |
| `validity_status`, `validity_flags` | — | M | Kalibrlashdan chiqarish (DIF/fit) |
| `exclusion_reason` | matn | S | Nega chiqarildi (`not_reached` / `pending_review` / `ld_policy`) |
| `scored_at`, `scored_by` | — | M | Audit |

> **Nega `p_hat`, `residual`, `information` saqlanadi, qayta hisoblanmaydi?**
> Chunki ular **o'sha paytdagi** `θ` va `b` bilan bog'liq. `b` keyingi
> kalibrlashda o'zgaradi, `θ` ham yangilanadi — qayta hisoblash **boshqa
> raqam** beradi. Muzlatmasak, **Infit/Outfit** tarixini tiklab bo'lmaydi.

### 7.5. Urinish darajasi (`attempts`) — Rasch, person fit, reliability

| Maydon | Tur | M | Xizmat qiladigan tahlil |
|---|---|---|---|
| `attempt_id`, `session_id`, `user_id`, `form_version_id` | son | M | Guruhlash |
| `parameter_set_id` | son | **M** | Snapshot scoring (equating) |
| `engine_version`, `engine_params` | matn/JSON | **M** | Reproducibility (konstantalar) |
| `scoring_policy_code` | matn | **M** | `official` / `strict` (4.5-bo'lim) |
| `status`, `submit_mode` | matn | M | `manual` / `auto_timeout` / `auto_expire` / `admin` |
| `started_at`, `submitted_at`, `duration_seconds` | — | **M** | Speededness, vaqt tahlili |
| `raw_score`, `raw_score_strict` | son | **M** | Ikki siyosat bo'yicha xom ball |
| `max_score_total`, `score_sum` | son | **M** | Polytomous readiness, foiz |
| `n_presented`, `n_reached`, `n_answered`, `n_omitted`, `n_not_reached`, `n_invalid` | son | **M** | Maxrajlar (4.5) — hisobot va DQ |
| `theta` | son | **M** | Ability bahosi |
| `theta_se` | son | **M** | **Reliability, separation, ishonch oralig'i** |
| `theta_method` | matn | **M** | `jmle` / `wle` / `mle` (bias farqi) |
| `log_likelihood` | son | **M** | Model mosligi, konvergensiya |
| `is_extreme_low`, `is_extreme_high` | mantiqiy | **M** | Chekli `θ` yo'qligi (hisobot siyosati) |
| `theta_lo_bound`, `theta_hi_bound` | son | S | Extremal holatda interval («≥ +3.0») |
| `person_infit_mnsq`, `person_outfit_mnsq` | son | **M** | **Person fit** |
| `person_fit_zstd` | son | S | Person fit (standartlashtirilgan) |
| `person_fit_flag` | matn | S | `normal` / `overfit` / `misfit` |
| `scaled_score`, `scaled_min`, `scaled_max` | son | M | Shkala ko'rsatish |
| `scaled_interval` | JSON | S | Ishonch oralig'i (0–100) |
| `level_code`, `level_source` | matn | S | «A/B/C» darajasi va uning manbasi (`scale_cutoffs` versiyasi) |
| `group_snapshot` | JSON | **M** | **DIF uchun** guruh o'zgaruvchilari **nusxasi** (o'sha paytdagi) |
| `session_mode` | matn | S | `online` / `center` (mode effekti, DIF) |
| `device_hash`, `ip_hash` | matn | X | Anti-cheat klasteri |
| `deleted_at`, `invalidated_reason` | — | S | Chiqarish sababi (kalibrlashda filtr) |

> **`group_snapshot` nima uchun nusxa?** O'quvchi keyinchalik hudud/maktab
> ma'lumotini o'zgartirsa yoki `persons_attributes` yangilansa, o'sha
> **sessiyadagi** guruh a'zoligi o'zgarmasligi kerak. DIF tahlili
> **o'sha paytdagi** holatga tayanishi shart.

### 7.6. Sessiya va item agregatlari

| Artefakt | Asosiy maydonlar | Xizmat qiladigan tahlil |
|---|---|---|
| `item_session_counters` | `session_id`, `form_item_id`, `item_version_id`, `n_presented`, `n_reached`, `n_answered`, `n_correct`, `n_omitted`, `n_not_reached`, `n_invalid`, `score_sum`, `category_counts`, `n_revisions`, `n_answer_changes`, `sum_dwell_ms`, `sum_time_to_first_answer_ms` | **Incremental kalibrlash** (full-scan o'rniga), `p`, exposure, answer-changing |
| `item_statistics` | `p_answered`, `p_reached`, `guessing_c`, `b_raw`, `b_adjusted`, `b_final`, `b_se`, `group_mean_theta`, `prior_b`, `shrinkage_weight`, `method`, `flags`, `scope`, `window_*`, `is_current` | Drift, anchor tanlash, DIF boshlang'ich ma'lumoti |
| `session_statistics` | `n_attempts`, `n_valid`, `n_extreme_low/high`, `theta_mean/sd/skew/kurtosis/min/max`, `theta_se_mean`, `mse`, `reliability`, `separation_index`, `item_mean_b`, `item_sd_b`, `item_se_mean`, `item_separation`, `raw_mean/sd`, `total_score_distribution`, `sem_profile`, `speededness_index`, `not_reached_rate`, `engine_params` | **Reliability**, **equating**, test informatsiya, DQ |
| `item_fit_statistics` | `item_version_id`, `session_id`, `parameter_set_id`, `n`, `infit_mnsq`, `outfit_mnsq`, `infit_zstd`, `outfit_zstd` | **Infit / Outfit** |
| `person_fit` (ixtiyoriy) | `snapshot_id`, `infit_mnsq`, `outfit_mnsq`, `zstd`, `max_residual_item` | Person fit diagnostikasi |
| `item_drift_checks` | `item_version_id`, `session_a`, `session_b`, `p_diff`, `z`, `b_diff`, `se_diff`, `flag` | **Drift monitoring** |
| `local_dependence_checks`, `testlet_statistics` | 6.3-bo'limga qarang | **LD / testlet** |

### 7.7. DIF, equating, ko'rik va apellyatsiya bog'lanishlari

| Artefakt | Asosiy maydonlar | Xizmat qiladigan tahlil |
|---|---|---|
| `dif_results` | `item_version_id`, `session_id`, `group_var` (`region`/`language`/`gender`/`school_type`), `stratum_count`, `n_ref`, `n_foc`, `mh_odds_ratio`, `mh_chi2`, `mh_p`, `ets_class` (`A`/`B`/`C`), `flag`, `parameter_set_id` | **DIF** (Mantel-Haenszel) |
| `dif_stratum_counts` (ixtiyoriy) | `item_version_id`, `group_var`, `stratum`, `n_correct`, `n_incorrect` | MH ni qayta hisoblash, audit |
| `anchor_sets`, `anchor_items` | `anchor_set_id`, `item_version_id`, `anchor_b`, `anchor_se`, `locked`, `valid_from/to`, `scale_reference` | **Equating** (o'lchovni bog'lash) |
| `item_parameter_set_items` | `parameter_set_id`, `item_version_id`, `b_value`, `b_se`, `c_value`, `a_value`, `is_anchor`, `n_used` | Har `b` ning kimligi (audit H-3) |
| `equating_links` | `from_set`, `to_set`, `anchor_count`, `slope`, `intercept`, `rmsd`, `status` | **Equating** natijasi |
| `scoring_reviews` | `attempt_id`, `form_item_id`, `item_version_id`, `raw_answer`, `auto_score`, `review_score`, `reason`, `status`, `reviewer_id`, `reviewed_at` | Qo'lda baholash izi (**`manual_scored`**) |
| `appeals` | `attempt_id`, `result_version_id`, `items_jsonb`, `status`, `decision`, `new_result_version_id` | Apellyatsiya → **yangi natija versiyasi** |
| `key_reviews` | `form_version_id`, `item_version_id`, `proposed_answer_spec`, `proposed_by`, `verified_by`, `status` | Kalit 4-eyes (audit H-8) |

### 7.8. Tahlil → maydon moslik matritsasi (nazorat jadvali)

| Tahlil | Yetarli ma'lumot qayerdan |
|---|---|
| **`p`, `b` (klassik)** | `item_session_counters` + `item_parameters` |
| **Rasch JMLE** | D (`score_awarded`, `b_used`, `p_hat`, `theta_used`) + `attempts.theta` |
| **Infit / Outfit** | **D** (`residual`, `information`, `item_version_id`) |
| **Person fit** | D (rezidual qatorlar) + `attempts.theta` |
| **Reliability / separation** | `session_statistics` (`theta_sd`, `theta_se_mean`) |
| **Equating** | `anchor_items` + `equating_links` + `session_statistics` (θ taqsimoti) |
| **DIF** | `group_snapshot` + D (`residual`, `score_awarded`) + `dif_results` |
| **Drift** | `item_statistics` (sessiyalar bo'ylab) + `item_drift_checks` |
| **Speededness** | A (`dwell_ms`, `first/last_presented_at`, `was_at_end_at_timeout`) + `session_statistics.speededness_index` |
| **Answer changing** | A (`change_count`, `first/final_answer_at`) + B (revision zanjiri) |
| **LD / testlet** | `testlet_ref` + D (juftlik reziduallari) + `local_dependence_checks` |
| **Exposure** | `item_session_counters.n_presented` + `item_exposure` |
| **Apellyatsiya** | D (`raw_answer`, `key_used`, `b_used`) + `scoring_reviews` + `appeals` |
| **Regrade auditi** | D (`engine_version`, `b_used`, `key_used`, `theta_used`) + `result_versions` |

---

## 8. Qaytarib bo'lmaydigan ma'lumotlar (8-savol)

### 8.1. **Hech qachon tiklanmaydi** — bugun yozilishi shart

| # | Ma'lumot | Qayerda | Nega tiklanmaydi |
|---|---|---|---|
| 1 | `first_presented_at`, `last_presented_at`, `dwell_ms` | A | Vaqt o'tdi — o'lchash imkoni yo'q |
| 2 | `not_reached` / `omitted` ajratilishi | A + 4.1 | Faqat 1-bandga tayanadi |
| 3 | `was_at_end_at_timeout`, `view_order_index`, `navigation_path` | A | Xatti-harakat faqat real vaqtda kuzatiladi |
| 4 | `change_count`, `first_answer_at`, `final_answer_at` | A + B | Har o'zgarish **o'sha onda** yozilishi kerak |
| 5 | `raw_answer` (kiritilgan aynan matn) | B | O'quvchi «12,5» yozganini keyin tiklab bo'lmaydi |
| 6 | `capture_conflicts` (`invalid_multiple` dalili) | B | Import tahlili bir marta bo'ladi |
| 7 | `input_method`, `device_hash`, `app_version`, `ui_variant` | A/B | Qurilma/versiya o'sha onda ma'lum |
| 8 | `client_clock_skew_ms`, `recorded_at` (server) | B | Server vaqti qayta tiklanmaydi |
| 9 | `group_snapshot` (hudud, til, jins, maktab, markaz) | `attempts` | PII o'sha paytda yig'ilishi kerak (audit C-5) |
| 10 | `b_used`, `key_used`, `p_hat`, `theta_used`, `engine_version` | D | O'sha paytdagi `b`/kalit **keyin o'zgaradi** |
| 11 | `scoring_policy_code` | `attempts` | Siyosat o'zgarsa, eski hisob qaysi siyosatda ekani yo'qoladi |
| 12 | `guessing_c` (per item, baholashda) | D | `item_types` keyin o'zgarishi mumkin |
| 13 | `submit_mode` (`manual`/`auto_timeout`/`admin`) | `attempts` | Yakunlash usuli faqat o'sha onda ma'lum |
| 14 | `scoring_reviews` izi (kim, qachon, nima uchun) | review | Inson qarori — qayta tiklanmaydi |
| 15 | `session_statistics` (θ taqsimoti, speededness) | agregat | Xom ma'lumotdan **qayta hisoblanadi**, lekin **o'sha paytdagi** `b` bilan bo'lgan versiyasi yo'qoladi |

### 8.2. **Tiklanadi** (lekin xom ma'lumot saqlansa)

| Ma'lumot | Qanday tiklanadi |
|---|---|
| Joriy javob holati (C) | B + A dan **replay** (1.5-bo'lim) |
| `p`, `b`, `SE(b)` | `item_session_counters` + `item_parameters` tarixidan qayta hisoblanadi |
| `θ` (yangi `b` bilan) | D + `item_parameters` dan **regrade** (yangi natija versiyasi) |
| Infit/Outfit (nazorat uchun) | D dan qayta yig'ish (lekin **o'sha paytdagi qiymat** D da muzlatilgan) |
| `raw_score`, `scaled_score` | Siyosat va shkala ma'lum bo'lsa qayta hisoblanadi |
| Exposure, answer-changing statistikasi | A + B dan agregatsiya |
| Apellyatsiya qarori | `appeals` + D dan |

### 8.3. **Yo'qolish xavfi bo'lgan, lekin hozir e'tibordan chetda** (3 ta)

| Xavf | Nima yo'qoladi | Chora |
|---|---|---|
| Autosave paketi rad etilsa va B ga **iz yozilmasa** | «O'quvchi nima yubordi» dalili | Har rad etish B ga `rejected_stale`/`rejected_invalid` voqeasi bilan yozilishi shart |
| Telemetriya (tier-2) umuman yozilmasa | Speededness, response time | Tier-2 ni «sampled» qilish — lekin `dwell_ms` **kamida item darajasida** yozilishi kerak |
| Import/OMR da `capture_conflicts` saqlanmasa | `invalid_multiple` sababi | Import tahlili natijasini **majburiy** saqlash |

---

## 9. Response Model v2 — invariantlar (majburiy qoidalar)

| # | Invariant | Buzilsa nima bo'ladi |
|---|---|---|
| **I1** | Har bir `score_awarded` **izlanadi**: `(response_id → item_version_id, key_version_no, b_used, engine_version)` | Apellyatsiya va regrade auditi imkonsiz |
| **I2** | **C = B ning proyeksiyasi**; C dagi har satrda `last_response_id` bor | C «haqiqat» bo'lib qoladi va audit uziladi |
| **I3** | **B ga faqat INSERT.** `UPDATE`/`DELETE` hech qachon | Tarix yo'qoladi; qayta tahlil mumkin emas |
| **I4** | **B da hosilaviy maydon yo'q** (`score_awarded`, `p_hat`, `b`) | Log va baholash aralashadi → ziddiyat |
| **I5** | Submit'dan keyin **A va C o'zgarmaydi** (`frozen_at`) | Yakunlangan natija o'zgarib ketadi |
| **I6** | **D abadiy immutable**; qayta baholash = **yangi D satri** + yangi `result_version` | Natija versiyalari chalkashadi |
| **I7** | **Pozitsiya identifikatsiya emas** — `item_id` + `item_version_id` | Statistika bo'linadi (audit C-1) |
| **I8** | **`not_reached` — `missing`**, `p` maxrajiga va θ ga kirmaydi (`official` siyosat) | θ va `b` tizimli xato (audit C-2) |
| **I9** | **Barcha vaqtlar server vaqti**; client vaqti `*_client_at` da | Deadline va response-time tahlili buziladi |
| **I10** | **PII javob jadvalida yo'q**; guruh ma'lumoti `attempts.group_snapshot` da (kodlangan) | Maxfiylik talabi buziladi |
| **I11** | **Agregatlar haqiqat emas** (`item_session_counters`, `session_statistics` — hosilaviy) | Agregat buzilsa, tahlil noto'g'ri bo'ladi |
| **I12** | Autosave **`audit_log` ga yozilmaydi**; u `attempt_events` va B da | Audit portlaydi (audit M-1) |

---

## 10. `docs/02`, `docs/04`, `docs/08` ga ta'sir (tuzatishlar ro'yxati)

### 10.1. `docs/02-DATABASE-SCHEMA.md`

| Joy | Hozir | Bo'lishi kerak (v2) |
|---|---|---|
| §3 `responses` | `is_current` belgisi + partial unique indeks | **`is_current` olib tashlanadi**; `event_type`, `capture_status`, `answer_kind`, `raw_answer`, `normalized_answer`, `numeric_value`, `answer_payload`, `capture_conflicts`, `recorded_at`, `request_id`, `testlet_ref`, `valid_from` qo'shiladi |
| §3 `responses` CHECK | `given_option IN ('A','B','C','D')` | **`A`…`F`** (mcq6) va open javobda `NULL` |
| §3 `responses` | `response_state IN ('answered','omitted','cleared')` | **Uch o'q**: `capture_status`, `score_status`, `validity_status` |
| §3 `attempt_response_current` | VIEW | **Haqiqiy jadval** (`attempt_responses_current`) + `last_response_id`, `frozen_at`, `score_status`, `validity_status` |
| §3 `responses.is_correct` | bor | **Olib tashlanadi** (hosilaviy — D da) |
| §5.4 (PG) | partial index `WHERE is_current` | Olib tashlanadi; o'rniga `attempt_items` va `attempt_responses_current` |
| §2 katalogi | 34 jadval | + `attempt_items`, `attempt_responses_current`, `scoring_snapshot_items`, `local_dependence_checks`, `testlet_statistics` |

### 10.2. `docs/04-API-VA-UI-MVP.md`

| Joy | Hozir | Bo'lishi kerak (v2) |
|---|---|---|
| `PUT /responses` so'rovi | `{position, part, option}` | `{item_id, item_version_id, answer_kind, option?/value?, client_seq, event_type}` — **pozitsiya emas, identifikator** |
| `PUT` javobi | `saved` / `cleared` | + `capture_status`, `score_status`, `revision`, `frozen` |
| `option = null` | `cleared` | `event_type='clear'`, `capture_status='cleared'` |
| Yangi `POST /responses/telemetry` | yo'q | Taqdimot/telemetriya (tier-1/tier-2) — `first_presented_at`, `dwell_ms` |
| `GET /state` | `responses: {"1":"B"}` | + `items[].capture_status`, `score_status`, `not_reached` ro'yxati, `answer_kind` |
| `POST /submit` | `answered_count`, `omitted_count` | + `not_reached_count`, `invalid_count`, `scoring_policy_code` |
| Xulq-atvor jadvali | 7 qator | + «eski `client_seq`», «`invalid_multiple`», «avtomatik finalizatsiya» |
| UI spetsifikatsiyasi | faqat MCQ kartochka | + `numeric`/`text` input kartochkalari (36a–45b), 6 variantli (`mcq6`) kartochka |
| `docs/02`, `04` | — | `1A2B3C4D` **faqat eksport** uchun (input emas) |

### 10.3. `docs/08-PSIKOMETRIK-AUDIT.md`

| Joy | Tuzatish |
|---|---|
| C-2 | «`response_state` ga `'not_reached'` qo'shish» → **uch o'qli model** bilan almashtiriladi (4-bo'lim) |
| C-4 | `scoring_snapshot_items` maydonlari to'ldiriladi: `p_hat`, `residual`, `information`, `theta_used`, `guessing_c` |
| M-2 | «ikki qatlamli model» → **to'rt artefakt** modeli (1-bo'lim) |
| M-3 | partial indeks olib tashlanadi (v2 dagi C jadval bilan hal) |
| §8.3 | `attempt_responses_current` **jadval** ekani tasdiqlanadi + `last_response_id`, `capture_status` |
| H-5 | Testlet metadata to'liq ro'yxati (6.2) + LD artefaktlari (6.3) |
| §10 jadvali | «speededness / response time — tiklanmaydi» → **A artefakti** orqali hal qilinadi |

> **Eslatma:** `docs/02` va `docs/04` **hali yangilanmagan** — bu hujjat
> (09) o'sha ikki hujjat uchun **manba** bo'lib xizmat qiladi. Kod yozilmaydi,
> shuning uchun yangilash keyingi bosqichda (`docs` tahriri) bajariladi.

---

## 11. Qabul mezonlari (Response Model v2 tayyor deb hisoblanadi, agar…)

| # | Mezon | Tekshirish usuli |
|---|---|---|
| 1 | **Har javob `item_id` + `item_version_id`** bilan yoziladi; pozitsiya faqat taqdimot | Sxema tekshiruvi + test: bir item ikki formada bir xil `item_id` |
| 2 | **`not_reached` ajratiladi** va `p` maxrajidan chiqariladi | Test: 45 dan 10 tasiga javob bermagan (ko'rmagan) o'quvchi |
| 3 | **Uch o'q** saqlanadi; hosilaviy `response_status` 9 qoida bo'yicha hisoblanadi | 6 so'ralgan kod + `quarantined`/`not_presented` holatlari |
| 4 | **`numeric` javob** `12,0` / `12.0` / ` 12 ` ni to'g'ri baholaydi; `12 yoki 15` → `pending_review` | Baholash testi |
| 5 | **`mcq6`** (`A`–`F`) qabul qilinadi, `c₀ = 0.1667` | `b` hisoblash testi |
| 6 | **B hech qachon o'zgarmaydi**; C undan qayta quriladi | Replay testi: C o'chirilib, B dan tiklanadi |
| 7 | **Submit'dan keyin freeze** — A va C ga yozib bo'lmaydi | Trigger testi |
| 8 | **D da `p_hat`, `residual`, `information`, `b_used`, `key_used`, `theta_used`** bor | Infit/Outfit tarixdan qayta tiklanadi |
| 9 | **`testlet_ref`** 36a–45b uchun majburiy; LD hisoboti ishlaydi | 36a/36b juftligi uchun `residual_corr` chiqadi |
| 10 | **Ikki xom ball**: `raw_score` (official) va `raw_score_strict` | Bir urinishda ikki qiymat farqi ko'rsatiladi |
| 11 | **Autosave `audit_log` ga tushmaydi** | 45 savolli urinishdan keyin `audit_log` bo'sh |
| 12 | **`group_snapshot`** urinishda nusxalanadi | `persons_attributes` o'zgarsa, eski hisob o'zgarmaydi |

---

## 12. Ochiq qarorlar (sizdan javob kutilayotgan 6 savol)

| # | Savol | Tavsiya etilgan javob | Nega muhim |
|---|---|---|---|
| 1 | `omitted` **0 ball** yoki `missing`? | **0 ball** (`official`), `not_reached` — `missing` | Rasch talabi + milliy hisob an'anasi |
| 2 | `SEE_THRESHOLD` (`dwell_ms`) | **2000 ms** (boshlang'ich) | `omitted`/`not_reached` chegarasi |
| 3 | `numeric` tolerantlik | **qat'iy + `0.0`**; birlik bo'lsa qo'lda ko'rik | Milliy sertifikatda «aniq javob» madaniyati |
| 4 | `text` javoblar bormi yoki faqat `numeric`? | Hozircha **`numeric`**, `text` zaxira sifatida saqlanadi | Ko'rik yuki |
| 5 | `answer_chain` (36b 36a ga bog'liqmi?) | Har bir item uchun **ekspert belgilaydi** | `b` buzilishining oldini olish |
| 6 | Telemetriya (tier-2) to'liq yoki sampled? | **To'liq** (kamida `dwell_ms` har item uchun) | Speededness va apellyatsiya |

---

## 13. Xulosa (bir sahifada)

```
                    ┌─────────────── QABUL (o'quvchi) ───────────────┐
                    │  capture_status  ·  answer_kind  ·  raw/norm.  │
                    └───────────────────────┬────────────────────────┘
                                            ▼
   B) responses (append-only, immutable)  ─►  C) attempt_responses_current (proyeksiya)
        ↑ taqdimot: A) attempt_items             │  (submit'da freeze)
        └─ not_reached / omitted / dwell          ▼
                                      D) scoring_snapshot_items (abadiy immutable)
                                                 │  key_used · b_used · p_hat · residual
                                                 ▼
                             item_session_counters → item_statistics → session_statistics
                                             → fit / drift / DIF / equating
```

**Uchta asosiy o'zgarish (audit natijasidan):**

1. **Uch o'qli status** (capture / score / validity) — 6 so'ralgan kod
   ziddiyatsiz qoplanadi; `auto_scored`/`manual_scored` endi qabul darajasi
   bilan aralashmaydi.
2. **To'rt artefakt** (taqdimot, log, joriy ko'rinish, snapshot) —
   `not_reached` fizik jihatdan ifodalanadi (audit C-2 hal), hot-path
   indeks churni yo'qoladi (M-3 hal), psixometrik haqiqat **D** da muzlatiladi
   (C-4 hal).
3. **Majburiy maydonlar** — `p_hat`, `residual`, `information`, `b_used`,
   `key_used`, `theta_used`, `guessing_c`, `dwell_ms`, `group_snapshot`,
   `testlet_ref` — **Infit/Outfit, person fit, DIF, equating, drift,
   reliability** hammasi bugungi qarorlardan kelib chiqadi.

**Eng muhim uchta jumla:**

> **1.** Javobning haqiqati — **B** (log); psixometrik haqiqat — **D**
> (snapshot); **C** — bu faqat tez ko'rsatish uchun proyeksiya.
> **2.** `not_reached` **missing** hisoblanadi; `omitted` — **0**; bu ikki
> holat **faqat taqdimot telemetriyasi** orqali ajratiladi.
> **3.** `b`, kalit, `P̂` va `θ` — **o'sha onda** muzlatilishi shart, aks
> holda Infit/Outfit va apellyatsiya **hech qachon** aniq tiklanmaydi.
