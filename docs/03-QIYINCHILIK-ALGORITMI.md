# 03 — Qiyinchilikni avtomatik hisoblash algoritmi

> Bu hujjat «O'qituvchi `b` kiritmaydi — tizim o'zi hisoblaydi» talabining
> to'liq texnik yechimidir. Bu yerda klassik `p → b` usuli, uning zaif
> joylari va ularni tuzatish usullari, keyinchalik Rasch kalibrlashga
> o'tish nuqtasi ko'rsatilgan.

## 1. Asosiy g'oya va belgilar

| Belgi | Ma'nosi |
|---|---|
| `k` | Savoldagi variantlar soni (Milliy Sertifikatda odatda `k = 4`) |
| `c₀ = 1/k` | Tasodifan to'g'ri javob topish ehtimoli (`k=4` → `0.25`) |
| `N` | `n_presented` — savol **taqdim etilgan** urinishlar soni |
| `A` | `n_answered` — javob **belgilangan** urinishlar (bo'sh/javobsiz emas) |
| `C` | `n_correct` — **to'g'ri** javob berilgan urinishlar |
| `p` | To'g'ri javob berganlar ulushi (*item facility*) |
| `p̂` | Tekislangan (silliqlangan) `p` |
| `b` | Savol qiyinchiligi, **logit** (Rasch shkalasi) |
| `θ` | O'quvchi bilim darajasi, **logit** (mavjud `services/rasch.py` hisoblaydi) |
| `θ̄` | Guruhning o'rtacha `θ` si (mean-mean moslash uchun) |
| `SE(b)` | `b` ning standart xatosi (aniqlik o'lchovi) |

**Asosiy formula** (barcha keyingi bosqichlarning o'zagi):

```
p = C / N                 (to'g'ri javob berganlar ulushi)
b = ln( (1 − p) / p )     (qiyinchilik, logit)
```

Bu formula **aks** taqqoslama: `p = 0.5 → b = 0`, `p → 1 → b → −∞` (oson),
`p → 0 → b → +∞` (qiyin). Aynan shu shkalada `services/rasch.py` θ ni
hisoblaydi, ya'ni `b` va `θ` **bitta o'lchovda** bo'ladi.

Rasch modelida `b` ning ma'nosi aniq:

```
P(to'g'ri javob | θ = b) = 1 / (1 + exp(−(θ − b))) = 0.5
```

Ya'ni **`b` — savolga qodir o'quvchilarning yarmi to'g'ri javob beradigan
daraja**. `p` esa o'lchangan guruhdagi ulush; guruh kuchli bo'lsa `p` katta
bo'ladi. Shu sababli `p → b` o'girish **guruhga bog'liq** — buni tuzatish
3.6-bo'limda ko'rsatilgan.

### `p` va `b` moslik jadvali (`k = 4`)

| `p` (to'g'ri javob ulushi) | `b` (logit) | Ma'nosi |
|---|---|---|
| 0.95 | `−2.94` | juda oson (deyarli hamma to'g'ri) |
| 0.90 | `−2.20` | juda oson |
| 0.80 | `−1.39` | oson |
| 0.70 | `−0.85` | o'rtachadan oson |
| 0.50 | `0.00` | markaziy savol |
| 0.40 | `+0.41` | o'rtachadan qiyin |
| 0.25 | `+1.10` | qiyin (tasodif darajasi!) |
| 0.15 | `+1.73` | juda qiyin |
| 0.05 | `+2.94` | juda qiyin (yoki kalit xatosi) |

## 2. Hisoblash zanjiri (to'liq)

```
┌─ 1. AGREGATSIYA ────────────────────────────────────────────────┐
│  responses (is_current) JOIN form_items JOIN attempts           │
│  faqat: status IN (submitted, submitted_late, graded)           │
│         attempts.deleted_at IS NULL                             │
│  → har bir form_item uchun: N, A, C                             │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─ 2. FILTR ──────────────────────────────────────────────────────┐
│  N < min_n (30)  → statistika yoziladi, b YANGILANMAYDI         │
│  N ≥ min_n       → davom etiladi                                │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─ 3. p HISOBLASH VA TEKISLASH ───────────────────────────────────┐
│  p_raw = C / A           (faqat javob berganlar)                │
│  p_used = C / N          (javobsiz = NOTO'G'RI) ← asosiy         │
│  p̂ = (C + 0.5) / (N + 1)  ← Jeffreys tekislash                   │
│  p̂ = clamp(p̂, p_min, 1 − p_min)                                 │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─ 4. XOM LOGIT ──────────────────────────────────────────────────┐
│  b_raw = ln((1 − p̂) / p̂)                                        │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─ 5. TAXMINGA TUZATISH (ixtiyoriy, default: yoqilgan) ───────────┐
│  p_c = (p̂ − c₀) / (1 − c₀),   c₀ = 1/k                          │
│  agar p_c ≤ p_min → p_c = p_min (flag: key_suspect)             │
│  b_guess = ln((1 − p_c) / p_c)                                  │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─ 6. GURUHGA MOSLASH (mean-mean) ────────────────────────────────┐
│  b_adj = b_guess − θ̄_guruh                                      │
│  (θ̄ guruhning o'rtacha darajasi; iterativ 2–3 marta)             │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─ 7. SHRINKAJ (empirik Bayes) ───────────────────────────────────┐
│  w = n_eff / (n_eff + K),  K = calibration.k_shrink (30)        │
│  b_final = w · b_adj + (1 − w) · b_prior                        │
│  b_prior = itemning oldingi b_final'i (yoki 0.0)                │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─ 8. ANIQLIK VA CHEGARA ─────────────────────────────────────────┐
│  SE(b) = 1 / sqrt(n_eff · p̂ · (1 − p̂))                          │
│  b_final = clamp(b_final, −b_bound, +b_bound)   (b_bound = 4.0) │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─ 9. FLAG'LAR (sifat nazorati) ──────────────────────────────────┐
│  insufficient_n | key_suspect | too_easy | drift | extreme      │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─ 10. YOZISH ────────────────────────────────────────────────────┐
│  item_statistics  (yangi satr, append-only)                     │
│  item_parameters  (eski satr valid_to = now, yangi satr)        │
│  audit_log        (action='calibration.item_b', before/after)   │
└─────────────────────────────────────────────────────────────────┘
```

## 3. Har bir qadamning asosi (nega aynan shunday?)

### 3.1. Agregatsiya — qaysi javoblar hisobga olinadi

| Holat | Hisobga olinadimi | Sabab |
|---|---|---|
| `attempts.status = 'in_progress'` | ❌ | Hali tugatmagan — javoblar to'liq emas |
| `attempts.status = 'expired'` | ❌ | Uzilgan sessiya (tarmoq/texnik nosozlik) |
| `attempts.status IN ('submitted','submitted_late','graded')` | ✅ | To'liq va yakunlangan urinish |
| `attempts.deleted_at IS NOT NULL` | ❌ | Soft delete qilingan |
| `responses.is_current = 0` | ❌ | Eski revision (o'quvchi keyin o'zgartirgan) |
| `responses.source = 'admin'` | ❌ (default) | Admin tuzatishi statistikaga tushmasligi kerak |
| `given_option = NULL` (`cleared`) | ✅ `N` ga, `A` ga ❌ | Savol taqdim etilgan, javob yo'q |

> **`source = 'import'`** (migratsiya paytida yozilgan javoblar) statistikaga
> **kiradi** — aks holda eski imtihonlarning ma'lumoti yo'qoladi. Bu
> `item_statistics` da `method='imported'` bilan ajratiladi.

### 3.2. `p` ni tanlash: `C/N` yoki `C/A`?

Ikkalasi ham saqlanadi, lekin **asosiy qiymat — `p_used = C/N`** (javobsiz =
noto'g'ri). Sabablari:

1. `services/rasch.py` da javobsiz savol `u_j = 0` deb olinadi — demak θ
   hisoblash bilan bir xil mezon ishlatilishi kerak (aks holda `b` va `θ`
   boshqa-boshqa tarozida bo'lib qoladi);
2. Milliy Sertifikatda **javob bermaslik ham natija**: vaqt yetmadi, bilmadi;
3. `p_used = C/N` **pastga qarab xolis emas**, lekin barqaror va tushunarli.

`C/A` esa alohida ustunda saqlanadi (`p_raw`) — "belgilaganlar orasida
to'g'ri javob ulushi" sifatida tahlilda foydali (masalan, "o'quvchilar
bu savolni belgilashga ulgurmadi" muammosini ko'rsatadi).

```
d = N − A  (javobsiz qoldirilganlar soni)
agar d / N > 0.30  →  flag: "omission_high"  (vaqt yetmayapti yoki savol tushunarsiz)
```

### 3.3. Tekislash (Jeffreys) — `p = 0` va `p = 1` muammosi

Agar savolga hech kim to'g'ri javob bermasa (`C = 0`), formula `ln(∞)` beradi.
Shuning uchun **Jeffreys (1946) tekislashi** qo'llaniladi:

```
p̂ = (C + 0.5) / (N + 1)
```

Bu — binomial ehtimol uchun Jeffreys prior `Beta(0.5, 0.5)` ning posterior
o'rtachasi. Xossalari:

| Holat | `p̂` | `b_raw` | Natija |
|---|---|---|---|
| `C = 0`, `N = 30` | 0.0161 | `+4.11` | yumshoq chegara (∞ emas) |
| `C = 0`, `N = 200` | 0.00249 | `+5.99` | juda qiyin (lekin chekli) |
| `C = 30`, `N = 30` | 0.984 | `−4.11` | juda oson |
| `C = 15`, `N = 30` | 0.50 | `0.00` | markaziy |

Keyin qat'iy chegara qo'llaniladi:

```
p_min = 0.005  →  |b_raw| ≤ ln(0.995 / 0.005) = 5.29
p̂ = clamp(p̂, 0.005, 0.995)
b_final = clamp(b_final, −4.0, +4.0)     # b_bound = 4.0
```

`b_bound = 4.0` ataylab tanlangan: `θ` ham `[−3, +3]` da qidiriladi
(`config.THETA_BOUND`), ya'ni `|b| = 4` savol o'sha o'lchov chegarasidan
tashqarida ekanini bildiradi (practikada "hamma to'g'ri" / "hech kim to'g'ri
emas" savol). Bunday savollar **informativ emas** deb flag'lanadi.

### 3.4. Xom logit `b_raw = ln((1 − p̂)/p̂)`

Bu yerda `b` — `p̂` ning logit funksiyasining **manfiy** qiymati. Tekshirish
uchun ekvivalent shakl: `p̂ = 1 / (1 + e^{b})`, ya'ni `θ = 0` bo'lgan o'quvchi
uchun Rasch modeli aynan shu `p̂` ni beradi:

```
P(0) = 1 / (1 + exp(−(0 − b))) = 1 / (1 + e^{b}) = p̂   ✅
```

Demak **`b_raw` — "bu savolni o'rtacha (θ=0) o'quvchi qanday yechadi"**
ma'nosini beradi. Bu aynan bizga kerak bo'lgan shkalaga o'girish.

### 3.5. Taxminga tuzatish (guessing) — nega kerak

4 variantli savolda o'quvchi **hech narsa bilmasa ham** 25% to'g'ri javob
oladi. `p = 0.30` ko'rsatkich aslida "hech narsa bilmaydigan guruh" bo'lishi
mumkin. Tuzatish formulasi (standard *correction for guessing*):

```
p_c = (p̂ − c₀) / (1 − c₀)          c₀ = 1/k
b_guess = ln((1 − p_c) / p_c)
```

| `p̂` | `b_raw` | `p_c` (`c₀=0.25`) | `b_guess` | Izoh |
|---|---|---|---|---|
| 0.75 | `−1.10` | 0.667 | `−0.69` | savol aslida osonroq |
| 0.50 | `0.00` | 0.333 | `+0.69` | markazdan qiyinroq |
| 0.40 | `+0.41` | 0.200 | `+1.39` | qiyin |
| 0.30 | `+0.85` | 0.067 | `+2.64` | juda qiyin |
| 0.25 | `+1.10` | 0.000 → `p_min` | `+4.0` (chegarada) | **tasodif darajasi** |
| 0.20 | `+1.39` | manfiy → `p_min` | `+4.0` | 🚩 kalit xatosi gumoni |

**Muhim tanlov.** Rasch (1PL) modeli nazariy jihatdan `c₀ = 0` ni nazarda
tutadi; 3PL modeli esa `c ≠ 0` bo'ladi. Shuning uchun ikkita qiymat
saqlanadi:

* `item_statistics.b_raw` — sof `p → b` (Rasch'ga tayyor, `c₀ = 0`),
* `item_statistics.b_final` — tuzatilgan qiymat (`method = 'guessing_corrected'`).

Milliy Sertifikat uchun **default: `c₀ = 1/k`** (tuzatilgan variant), chunki
test butunlay 4 variantli va real guruhlar aralash. Sozlama:
`app_settings.calibration.guessing = "auto" | 0.0 … 0.33`.

> ⚠️ `p̂ ≤ c₀` holati **matematik signal**: o'quvchilar tasodifdan ham yomon
> yechdi. Bu odatda (a) kalitda xato, (b) savol tushunarsiz, (yoki) savol
> butunlay boshqa mavzudan. Shuning uchun `key_suspect` flag'i qo'yiladi va
> admin ko'rigiga chiqariladi (auto-fix **qilinmaydi**).

### 3.6. Guruhga moslash (mean-mean linking)

`p` o'lchangan guruhning kuchiga bog'liq: kuchli guruhda `p` katta → `b`
sun'iy ravishda kichik chiqadi. Buni tuzatish — klassik **mean-mean**
usuli:

```
b_adj = b_raw_or_guess − θ̄_guruh
```

Bu yerda `θ̄_guruh` — shu davrda ushbu savolni yechgan o'quvchilarning
o'rtacha `θ` si (`scoring_snapshots` dan). Mantiq: agar guruh o'rtachadan
`+0.5` logit kuchli bo'lsa, `b` ni `0.5` ga **kamaytirish** kerak (savol
aslida o'sha qadar qiyin emas).

**Iterativ sxema** (`θ` va `b` bir-biriga bog'liq, shuning uchun bir necha qadam):

| Bosqich | Amal |
|---|---|
| 0 | `b⁰` = joriy `item_parameters` (yoki `0.0`) |
| 1 | `b⁰` bilan θ hisoblanadi → `θ̄₁` |
| 2 | `b¹ = b_raw − θ̄₁`, keyin yana θ → `θ̄₂` |
| 3 | `b² = b_raw − θ̄₂`; `abs(θ̄₂ − θ̄₃) < 1e-4` bo'lsa to'xtatiladi |

Amalda 2–3 iteratsiya yetarli (`services/rasch.py` dagi MLE ham 5–8
iteratsiyada yaqinlashadi). Iteratsiya soni `calibration_runs.iterations`
ga yoziladi.

> **Nega bu "haqiqiy Rasch" emas?** Chunki `b_raw` har bir savolning
> javoblaridan **alohida** hisoblanadi va `θ` ning `b` ga bog'liqligi
> faqat guruh o'rtachasi orqali qoplanadi. To'liq yechim — JMLE, ya'ni
> `b` va `θ` birgalikda baholanadi (06-hujjat). Mean-mean — JMLE'ning
> birinchi darajali yaqinlashuvi va **anchor items paydo bo'lguncha**
> yetarli.

### 3.7. Shrinkaj (empirik Bayes) — kichik namunani yumshatish

`N = 12` bo'lganda `p = 0.5` hisoblanib `b = 0.0` chiqishi tasodif bo'lishi
mumkin. Yechim: **posterior o'rtacha** (normal prior bilan).

```
prior:      b ~ N(b_prior, σ₀²)          σ₀ = 0.7  →  σ₀² = 0.49
likelihood: b̂ (kuzatilgan), Var(b̂) ≈ 1 / (N · p̂ · (1 − p̂))
posterior:  b_final = w · b̂ + (1 − w) · b_prior

aniq shakl:  w = (1/Var) / (1/Var + 1/σ₀²)
amaliy shakl: w = clamp( N/(N+K) · 4·p̂·(1−p̂), 0, 1 ),   K = 30
```

| `N` | `p̂` | `w` (`K=30`) | Effekt |
|---|---|---|---|
| 10 | 0.50 | 0.25 | kuzatuvga 25% ishonch — `b` prior tomon tortiladi |
| 30 | 0.50 | 0.50 | yarim yo'l |
| 100 | 0.50 | 0.77 | kuzatuv ustun |
| 500 | 0.50 | 0.94 | amalda sof kuzatuv |
| 100 | 0.90 | 0.28 | chekka holat (oson savol) — ehtiyotkorlik |

**`b_prior` tanlash tartibi** (birinchi mavjud bo'lgani olinadi):

1. itemning **oldingi** `item_parameters.b_value` (random-walk prior —
   savol qiyinchiligi keskin sakramaydi);
2. item `topic_id` bo'yicha shu mavzudagi itemlarning o'rtacha `b` si;
3. `program_id` bo'yicha o'rtacha;
4. `0.0` (yangi item uchun default — «Test yaratilganda barcha savollar
   default holatda yaratiladi» talabi).

### 3.8. Standart xato `SE(b)`

Delta-usul bilan `p̂` ning dispersiyasidan:

```
Var(p̂) ≈ p̂ · (1 − p̂) / (N + 1)        # Jeffreys posterior dispersiyasi
db/dp  = −1 / (p̂ · (1 − p̂))
SE(b)  = |db/dp| · sqrt(Var(p̂)) = 1 / sqrt((N + 1) · p̂ · (1 − p̂))
```

Tuzatilgan (guessing) variant uchun `p_c` orqali:

```
SE(b_guess) = SE(p̂) / ((1 − c₀) · p_c · (1 − p_c))
```

**Talqin:** `SE ≤ 0.30` → `b` ±0.6 logit aniqlikda (qabul qilinadi);
`SE > 0.50` → savol qiyinchiligi hali "suzuvchi" (faqat prognoz).

| `N` | `p̂` | `SE(b)` | Holat |
|---|---|---|---|
| 30 | 0.50 | **0.36** | chegarada — faqat `provisional` |
| 30 | 0.90 | **0.61** | ishonchsiz (chekka holat) |
| 100 | 0.50 | **0.20** | yaxshi |
| 100 | 0.25 | **0.23** | yaxshi |
| 200 | 0.50 | **0.14** | `frozen` uchun yetarli |
| 400 | 0.50 | **0.10** | juda aniq (milliy daraja) |

Ya'ni `SE ≤ 0.30` chegarasiga yetish uchun `p̂ ≈ 0.5` bo'lganda taxminan
**`N ≥ 110`** javob kerak — shu sababli `min_n = 30` «yangilash mumkin»,
`se_freeze = 0.30` esa «qotirish mumkin» mezoni hisoblanadi.

### 3.9. Chekka holatlar (to'liq ro'yxat)
| Holat | Shart | Harakat |
|---|---|---|
| Namuna kam | `N < 30` | `b` **yangilanmaydi**; `item_statistics` yoziladi, `flags=['insufficient_n']` |
| Hech kim to'g'ri emas | `C = 0` | `flags=['key_suspect','extreme','too_hard']`; **`b` yangilanmaydi** (kalit xatosi gumoni) |
| Hamma to'g'ri | `C = N` | `b_final = −4.0`, `flags=['extreme','too_easy']` (informativ emas) |
| `p̂ ≤ c₀` | `p̂ ≤ 0.25` (`k=4`) | `flags=['key_suspect']`; **`b` YANGILANMAYDI** (eski qiymat qoladi) + admin bildirishnomasi |
| Javobsiz ko'p | `(N−A)/N > 0.30` | `flags=['omission_high']` |
| `b` keskin sakradi | `abs(b_new − b_old) > 1.5` va `N < 200` | shrinkajni kuchaytirish (`K × 2`), `flags=['unstable']` |
| Drift | ikki davr `abs(z) > 3` | `flags=['drift']`, admin ko'rigi (kalit o'zgarganmi?) |
| Ankerga zid | `abs(b_new − anchor_b) > 1.0` | `flags=['anchor_mismatch']`, `b` **o'zgartirilmaydi** |
| Aniqlik yetarli | `N ≥ 200` va `SE ≤ 0.25` | `status = 'frozen'` (qotiriladi) |

### 3.10. Holatlar mashinasi (status transitions)

```
             N < 30                 30 ≤ N < 110             N ≥ 110, SE ≤ 0.30
 [provisional] ───► (o'zgarmaydi) ──────► [operational] ─────────► [operational]
      │                                        │
      │   N ≥ 200 va SE ≤ 0.25                 │   N ≥ 200 va SE ≤ 0.25
      └────────────────────────────────────────┴──────────► [frozen]
                                                               │
                                        admin qo'lda ochsa ─────┘
                                                   ▼
                                             [operational]
```

| Status | Ma'nosi | Scoring'da |
|---|---|---|
| `provisional` | `b` hali ishonchsiz (default `0.0` yoki kam ma'lumot) | ishlatiladi |
| `operational` | `b` statistik asosda (kamida 110 javob) | ishlatiladi |
| `frozen` | `b` qotirilgan (≥ 200 javob, `SE ≤ 0.25`) | **anchor sifatida** ishlatiladi |
| `retired` | savol iste'moldan chiqarilgan | ishlatilmaydi |

### 3.11. Yozish tartibi (atomar tranzaksiya)

```sql
BEGIN;
  -- 1. Eski operatsion b ni yopish (tarix saqlanadi)
  UPDATE item_parameters SET valid_to = :now
   WHERE form_item_id = :fi AND valid_to IS NULL;

  -- 2. Yangi satr (versiyalangan operatsion b)
  INSERT INTO item_parameters
      (form_item_id, item_version_id, parameter_set_id, b_value, b_se, source,
       status, n_used, valid_from, calibration_run_id)
  VALUES (:fi, :iv, :ps, :b_final, :se, 'guessing_corrected',
          :status, :n_used, :now, :run_id);

  -- 3. Statistika tarixi (append-only): eski belgi olib tashlanadi
  UPDATE item_statistics SET is_current = 0 WHERE form_item_id = :fi AND is_current = 1;
  INSERT INTO item_statistics (form_item_id, ..., b_final, b_se, flags, is_current, ...)
  VALUES (:fi, ..., :b_final, :se, :flags_json, 1, ...);

  -- 4. Audit
  INSERT INTO audit_log (action, entity_type, entity_id, before_json, after_json, source)
  VALUES ('calibration.item_b', 'item_parameter', :fi, :before, :after, 'system');
COMMIT;
```

**Qoida:** birorta javob yoki natija **hech qachon** o'zgartirilmaydi.
Faqat `b` versiyalanadi — va yangi versiya **keyingi** urinishlarga ta'sir
qiladi (eski `scoring_snapshots` o'z parametrlari bilan qoladi).

### 3.12. Kalibrlash qachon ishga tushadi

| Trigger | Vaqt | Ko'lam (`scope`) |
|---|---|---|
| Sessiya baholandi (`status = 'graded'`) | avtomatik, `grade_exam` oxirida | `session` |
| Kunlik fon vazifasi | har kuni 03:00 (mahalliy) | `form` + `program` |
| Admin buyrug'i (`/calibration`) | qo'lda | istalgan |
| `N` chegarasi kesib o'tilganda (`30`, `110`, `200`) | avtomatik | `form` |
| Yangi `anchor_items` kiritilganda | qo'lda | `global` |

**Ko'lam (scope) tanlash qoidasi:** eng kichik ko'lamdan boshlanadi
(`session`), ma'lumot yetmasa kattalashtiriladi:

```
scope = 'session'   → agar N ≥ min_n
scope = 'form'      → shu formaning barcha sessiyalari
scope = 'program'   → yo'nalish bo'yicha (boshqa formalardagi bir xil itemlar)
scope = 'global'    → butun baza (anchor items bilan bog'lash)
```

MVP'da `item_statistics.scope = 'session'` va `'form'` yetarli; keyinchalik
`program` va `global` (equating bilan) qo'shiladi.

## 4. Algoritmning psevdo-kodi (modul dizayni)

### 4.1. `services/difficulty.py` — bitta savol uchun

```
FUNKSIYA hisobla_item_qiyinchilik(
    n_presented, n_answered, n_correct, options_count,
    group_mean_theta, prior_b, is_anchor, anchor_b, sozlamalar
) -> ItemDifficultyResult:

    # --- 1. Namuna yetarlimi? ---
    agar n_presented < sozlamalar.min_n:
        QAYTAR Natija(b_final=none, flags=["insufficient_n"],
                      n_used=n_presented, status="provisional")

    # --- 2. p va tekislash (Jeffreys) ---
    p_answered = n_correct / n_answered            # faqat belgilaganlar
    p_hat      = (n_correct + 0.5) / (n_presented + 1)
    p_hat      = clamp(p_hat, p_min, 1 - p_min)    # p_min = 0.005

    # --- 3. Xom logit ---
    b_raw = ln((1 - p_hat) / p_hat)

    # --- 4. Taxminga tuzatish ---
    c0 = sozlamalar.guessing                   # "auto" → 1 / options_count
    p_c = (p_hat - c0) / (1 - c0)
    flags = []
    agar p_c <= p_min:
        # p tasodif darajasidan ham past → kalitga zid ma'lumot
        flags.qosh("key_suspect")
        agar n_correct == 0: flags.qosh("extreme"); flags.qosh("too_hard")
        QAYTAR Natija(b_raw=b_raw, b_final=none, flags=flags,   # b YANGILANMAYDI
                      se=se_b(...), n_used=n_presented, status="provisional")
    b_guess = ln((1 - p_c) / p_c)

    # --- 5. Guruhga moslash (mean-mean) ---
    b_adj = b_guess - group_mean_theta

    # --- 6. Shrinkaj (empirik Bayes) ---
    ext = (n_correct == n_presented)           # C=0 holati yuqorida qaytdi
    agar ext:
        w = 1.0                                # chekka holatda ishonch to'liq
        flags.qosh("extreme")
        flags.qosh("too_easy")
    boshqa:
        w = clamp( n_presented/(n_presented + K) * 4*p_hat*(1 - p_hat), 0, 1 )
    b_final = w * b_adj + (1 - w) * prior_b

    # --- 7. Chegara va SE ---
    b_final = clamp(b_final, -b_bound, +b_bound)
    se      = se_b(p_c, n_presented, c0)

    # --- 8. Anker bilan solishtirish (agar mavjud bo'lsa) ---
    agar is_anchor va |b_final - anchor_b| > 1.0:
        flags.qosh("anchor_mismatch")
        b_final = anchor_b                     # ankerni ustun qo'yamiz
        se      = anchor_se

    # --- 9. Holat (status) ---
    status = "provisional"
    agar n_presented >= 110 va se <= se_freeze:      status = "operational"
    agar n_presented >= 200 va se <= se_freeze*0.83: status = "frozen"

    QAYTAR Natija(b_raw, b_guess, b_adj, b_final, se, w, flags,
                  n_used=n_presented, p_used=p_hat, status)
```

### 4.2. `services/calibration.py` — davr bo'yicha sikl

```
FUNKSIYA kalibrlash_sikli(scope, scope_id, method, quruq_ishlash=False):

    run_id = calibration_runs.yozish(scope, scope_id, method, status="running")

    # A) Agregatsiya (bitta SQL — 02-hujjat, 8-bo'lim)
    satrlar = db.ol(
        "SELECT fi.form_item_id, COUNT(*) n_presented, "
        "       SUM(...) n_answered, SUM(...) n_correct "
        "  FROM responses r JOIN form_items fi ... WHERE ... GROUP BY fi.form_item_id"
    )

    # B) Guruhning o'rtacha θ si (iterativ)
    theta_bar = scoring_snapshots.orta_theta(scope, scope_id)

    UCHUN iteratsiya ichida 1..max_iter (odatda 3):
        yangi_b = {}
        UCHUN s IN satrlar:
            res = hisobla_item_qiyinchilik(..., group_mean_theta=theta_bar,
                                           prior_b=joriy_b(s.form_item_id))
            yangi_b[s.form_item_id] = res
        agar quruq_ishlash: davom

        # θ larni yangi b bilan qayta hisoblash (mavjud rasch.estimate_theta)
        theta_bar = qayta_hisobla_theta_va_ortacha(yangi_b)
        agar |theta_bar - oldingi| < 1e-4: tanaffus

    # C) Yozish (bitta tranzaksiyada — 3.11 ga qarang)
    UCHUN s IN satrlar:
        item_statistics.yozish(res)                     # append-only
        agar res.status == "insufficient_n": davom      # b yangilanmaydi
        item_parameters.yangi_versiya(res)              # eski satr valid_to = now
        audit_log.yozish("calibration.item_b", ...)

    # D) Yakuniy hisobot
    calibration_runs.yangilash(status="finished", iterations=n,
                              convergence="converged",
                              item_count=len(satrlar),
                              max_abs_delta=max(|b_new - b_old|))
    agar birorta flag "key_suspect" bo'lsa:
        notification_outbox.qo'shish(kind="item_flagged", user_id=admin)

    QAYTAR run_id
```

## 5. Qo'lda hisoblangan misollar (test uchun etalon)

Quyidagi qiymatlar `tests/test_difficulty.py` da **etalon (expected)** sifatida
ishlatiladi. `K = 30`, `p_min = 0.005`, `b_bound = 4.0`, `c₀ = 1/k`.

### Misol A — oddiy holat: `N=100`, `C=75`, `k=4`, `θ̄=+0.10`, `prior=0`

| Qadam | Hisoblash | Natija |
|---|---|---|
| `p_answered` | `75/100` | `0.7500` |
| `p̂` | `(75+0.5)/(100+1)` | `0.74753` |
| `b_raw` | `ln(0.25247/0.74753)` | **`−1.0858`** |
| `p_c` | `(0.74753−0.25)/0.75` | `0.66337` |
| `b_guess` | `ln(0.33663/0.66337)` | **`−0.6784`** |
| `b_adj` | `−0.6784 − 0.10` | `−0.7784` |
| `w` | `(100/130)·4·0.74753·0.25247` | `0.5808` |
| `b_final` | `0.5808·(−0.7784) + 0.4192·0` | **`−0.4521`** |
| `SE(b)` | `0.04323/(0.75·0.66337·0.33663)` | **`0.2581`** |
| `status` / `flags` | `N=100 < 110` | `provisional`, `[]` |

**Talqin:** savol oson (`b ≈ −0.45`), lekin `b` hali `prior = 0` tomon
tortilgan; keyingi sessiyalarda `prior` shu `−0.45` bo'ladi va `w` o'sishi
bilan `b → −0.68` ga yaqinlashadi.

### Misol B — chekka holat: `N=40`, `C=0` (hech kim to'g'ri emas), `k=4`

| Qadam | Hisoblash | Natija |
|---|---|---|
| `p̂` | `0.5/41` | `0.012195` |
| `b_raw` | `ln(0.987805/0.012195)` | **`+4.3944`** |
| `p_c` | `(0.012195−0.25)/0.75 < 0` | → `p_min` 🚩 |
| `b_guess` | `ln(0.995/0.005)` | `+5.2930` (chegaradan tashqari) |
| `b_final` | 🚩 `key_suspect` → **`None`** | **yangilanmaydi** |
| `SE(b)` | `0.01714/(0.012195·0.987805)` | **`1.4230`** |
| `flags` | — | `extreme`, `too_hard`, `key_suspect` |

**Talqin:** o'quvchilar tasodifan (25%) ham to'g'ri javob topmadi → ma'lumot
kalitga **zid**. Shu sababli tizim `b` ni **o'zgartirmaydi** (eski `0.0`
qoladi) va adminga «kalitni tekshiring» bildirishnomasi yuboriladi.
`SE = 1.42` — hisob natijasi juda ishonchsiz ekanini ko'rsatadi.

### Misol C — katta namuna: `N=200`, `C=140`, `k=4`, `θ̄=0`

| Qadam | Hisoblash | Natija |
|---|---|---|
| `p̂` | `140.5/201` | `0.69901` |
| `b_raw` | `ln(0.30099/0.69901)` | `−0.8425` |
| `p_c` | `(0.69901−0.25)/0.75` | `0.59867` |
| `b_guess` | `ln(0.40133/0.59867)` | **`−0.4000`** |
| `w` | `(200/230)·4·0.69901·0.30099` | `0.7319` |
| `b_final` | `0.7319·(−0.4000) + 0.2681·0` | **`−0.2928`** |
| `SE(b)` | `0.03235/(0.75·0.59867·0.40133)` | **`0.1796`** |
| `status` | `N=200`, `SE ≤ 0.25` | **`frozen`** ✅ |

**Talqin:** yetarli ma'lumot yig'ildi — savol `frozen` holatga o'tdi va endi
**anchor item** sifatida ishlatilishi mumkin (boshqa formalarni bog'lash uchun).

### Misol D — shrinkaj priorning ta'siri: `N=60`, `C=39`, `prior=+1.0`

| Qadam | Hisoblash | Natija |
|---|---|---|
| `p̂` | `39.5/61` | `0.64754` |
| `b_guess` | `ln((1−0.53006)/0.53006)` | `−0.1204` |
| `w` | `(60/90)·4·0.64754·0.35246` | `0.6086` |
| `b_final` | `0.6086·(−0.1204) + 0.3914·(+1.0)` | **`+0.3181`** |
| `SE(b)` | `0.06117/0.18682` | **`0.3274`** |
| `flags` / `status` | `SE > 0.30` | `[]`, `provisional` |

**Talqin:** kuzatuv `b ≈ −0.12` desa ham, eski `b = +1.0` prior kuchli:
natija `+0.32`. Bu **ataylab** — kam namunada keskin sakrashdan himoya.
Ikkinchi, uchinchi kalibrlashdan keyin prior kuzatuvga moslashib, farq
yo'qoladi (teskarisi ham to'g'ri: savol rostdan o'zgargan bo'lsa, 2–3
sikl ichida yangi qiymat o'rnashadi).

### Shrinkajning tuzoq jihati (halol izoh)

* Prior **kuzatuvga qarab** siljiydi → `b` qiymatlar "yopishqoq" bo'ladi;
* Savol matni (PDF da) **o'zgarmagan holda** qiyinchiligi o'zgarishi mumkin
  (dastur o'zgardi, o'qituvchi tayyorladi) → drift flag'i shu sababli zarur;
* `b` **mutlaq** kattalik emas, **nisbiy** (shu guruh, shu davr uchun).
  Mutlaq milliy shkala faqat **anchor items + equating** bilan olinadi.

## 6. Validatsiya testlari (`tests/test_difficulty.py`, `tests/test_calibration.py`)

Testlar mavjud loyiha uslubida yoziladi: `pytest` **talab qilinmaydi**,
`python tests/test_difficulty.py` bilan ishlaydi, `sys.path` ga loyiha ildizi
qo'shiladi (`tests/test_rasch.py` dagi kabi).

### 6.1. `test_difficulty.py` — matematika (12 test)

| # | Test | Kirish | Kutilgan natija |
|---|---|---|---|
| 1 | Markaziy holat | `N=30, C=15` | `p̂ = 0.5`, `b_raw = 0.0` (aniq) |
| 2 | Simmetriya | `C=0` va `C=N` (`N=30`) | `b_raw = +4.1109` va `−4.1109` |
| 3 | Monotonlik | `C` 5→25 | `b_raw` qat'iy kamayadi |
| 4 | Jeffreys ishlashi | `C=0, N=30` | xatolik yo'q, `b` chekli, `4.1109` |
| 5 | `p = 1` chegarasi | `C=N=30` | `p̂ = 0.98387`, `b_raw = −4.1109` |
| 6 | `SE` (delta-usul) | `N=100, C=50` | `SE ≈ 0.1990` (tol. `1e-6`) |
| 7 | `SE` tekislash bilan | `N=30, C=15` | `SE ≈ 0.3592` |
| 8 | Guessing tuzatish | `N=100, C=75, k=4` | `b_guess = −0.6784` (tol. `1e-4`) |
| 9 | `key_suspect` | `N=100, C=20, k=4` | `flags` da `key_suspect`, `b_final = None` |
| 10 | Mean-mean | `θ̄ = +0.5` | `b_adj = b_guess − 0.5` |
| 11 | Shrinkaj | `N=60, prior=+1.0, C=39` | `b_final = +0.3181`, `w = 0.6086` |
| 12 | Namuna kam | `N=12` | `status = insufficient_n`, `b_final = None` |

Qo'shimcha testlar:

| # | Test | Kutilgan natija |
|---|---|---|
| 13 | Etalon misollar A–D (5-bo'lim) | Jadvaldagi qiymatlar `1e-3` aniqlikda |
| 14 | `p_used` `C/N` ekani | `N=100, A=80, C=60` → `p_used = 0.6`, `p_raw = 0.75` |
| 15 | Chegara | `b_final` hech qachon `±4.0` dan katta emas |
| 16 | Anker | `anchor_b=+1.0`, hisob `+2.5` → `anchor_mismatch`, `b_final = +1.0` |
| 17 | `omission_high` | `(N−A)/N = 0.4` → flag |
| 18 | Shrinkaj konstantasi | `N=10` → `w = 0.25`, `N=500` → `w = 0.94` (`p̂=0.5`) |
| 19 | Determinizm | Bir xil kirish → har doim bir xil `b` (tasodifiylik yo'q) |
| 20 | `k` ga bog'liqlik | `k=4` va `k=5` farqi (`c₀ = 1/k`) to'g'ri hisoblanishi |

### 6.2. `test_calibration.py` — sikl (8 test)

| # | Test | Tekshiriladi |
|---|---|---|
| 1 | To'liq sikl | Vaqtinchalik SQLite: form + sessiya + 50 `attempts` + javoblar → kalibrlash → `item_parameters` yangilandi, `item_statistics` satri bor, `audit_log` yozuvi bor |
| 2 | `N < min_n` | 5 javob → `item_parameters` **o'zgarmadi**, statistika yozildi |
| 3 | Prior davomiyligi | 2-sikl prior sifatida 1-sikl `b` ini oladi (`w` oshadi) |
| 4 | `frozen` | `N=200`, `SE ≤ 0.25` → `status = 'frozen'` |
| 5 | Frozen himoyasi | `frozen` item yangi kalibrlashda **o'zgarmaydi** (`status='frozen'`), run ichida `anchor` deb belgilanadi |
| 6 | Drift | Ikki sessiya, `p` farqi katta → `flags` da `drift` |
| 7 | Snapshot scoring | `b` yangilangach **eski** `scoring_snapshots` o'zgarmadi; yangi urinish yangi `parameter_set` ishlatadi |
| 8 | Soft delete | `deleted_at` qo'yilgan urinish statistikaga **kirmaydi** |

### 6.3. `test_responses.py` — javoblar (7 test)

| # | Test | Tekshiriladi |
|---|---|---|
| 1 | Append-only | 2 marta saqlash → 2 satr, bittasi `is_current=1` |
| 2 | `superseded_by` | Eski satr yangi `response_id` ga ishora qiladi |
| 3 | Idempotentlik | Bir xil `client_seq` qayta kelsa → yangi satr **qo'shilmaydi**, `200` javob |
| 4 | Revision konflikti | Eski `revision` bilan yozish → `409` |
| 5 | Refresh | `GET state` → barcha joriy javoblar qaytadi |
| 6 | Javobni tozalash | `option = null` → `response_state = 'cleared'`, `is_correct = NULL` |
| 7 | Immutability | `UPDATE responses SET is_current = 1 WHERE ...` → `RAISE(ABORT)` |

### 6.4. Ishlatish

```powershell
python tests/test_difficulty.py      # p→b matematikasi + etalon misollar
python tests/test_calibration.py     # kalibrlash sikli, freeze, drift
python tests/test_responses.py       # append-only javoblar, revision, idempotentlik
python tests/test_rasch.py           # mavjud θ testlari (o'zgarmaydi)
```

## 7. Sozlamalar va ularning ta'siri (sezgirlik)

| Sozlama | Default | Nima uchun shunday | Noto'g'ri tanlansa |
|---|---|---|---|
| `calibration.min_n` | `30` | `N < 30` da `p` ning 95% ishonch oralig'i `±0.18` — juda keng | Kichik (10) → `b` sakraydi; katta (200) → yangi savollar `b = 0` da qoladi |
| `calibration.k_shrink` (`K`) | `30` | `N = 30` da `w = 0.5` — "yarim ishonch" mantiqiy boshlanish | Kichik (5) → shovqin; katta (200) → yangi ma'lumot deyarli hisobga olinmaydi |
| `calibration.guessing` | `"auto"` (`1/k`) | 4 variantli test uchun `c₀ = 0.25` real | `0.0` → savollar osonroq ko'rinadi (Rasch 1PL bilan mos, lekin haqiqatga yaqin emas) |
| `calibration.se_freeze` | `0.30` | `±0.59` logit aniqlik — amaliyotda qabul qilinadi | Kichik (0.15) → `frozen` deyarli bo'lmaydi; katta (0.6) → ishonchsiz `b` qotib qoladi |
| `calibration.b_bound` | `4.0` | `θ ∈ [−3, +3]` dan tashqaridagi savol informativ emas | Kichik (2.5) → haqiqiy qiyin savollar siqilib qoladi |
| `calibration.drift_z` | `3.0` | `α = 0.003` — soxta signal kam | Kichik (2.0) → ko'p soxta ogohlantirish |
| `calibration.key_suspect_p` | `0.20` | Tasodif ehtimolidan past (`0.25`) | Katta (0.30) → ko'p savol "shubhali" bo'lib qoladi |
| `scoring.theta_bound` | `3.0` | Mavjud `config.THETA_BOUND` bilan bir xil | O'zgartirilsa, 0–100 shkala koeffitsiyenti ham o'zgaradi |

## 8. Cheklovlar (halol ro'yxat)

1. **`b` guruhga bog'liq.** `p → b` faqat guruh o'rtachasi (`θ̄`) orqali
   tuzatiladi. Guruh **tanlab olingan** bo'lsa (masalan, faqat kuchli
   o'quvchilar tayyorlov kursidan) — `b` xato bo'ladi.
2. **Rasch (1PL) emas.** Har bir savol alohida baholanadi; savol va o'quvchi
   parametrlari birgalikda emas. `b` va `θ` mos kelmasligi mumkin
   (**fit** statistikasi yo'q).
3. **Guessing tuzatishi bor, lekin modelda `c ≠ 0` emas.** Ya'ni 3PL
   haqiqiy emas; bu **klassik tuzatish**, taxminiy.
4. **Shrinkaj "yopishqoq"lik** beradi (5-bo'lim, Misol D).
5. **Drift** aniqlanadi, lekin **sababi** aniqlanmaydi (kalit o'zgarganmi,
   dastur o'zgarganmi, o'quvchilar tayyorlanganmi).
6. **`b` mutlaq emas** — formalar orasida taqqoslash faqat **anchor items**
   va **equating** bilan to'g'ri bo'ladi (06-hujjat).
7. **Savol matni bazada yo'q** → `content_hash`/`item_ref` to'g'ri
   kiritilmasa, bir xil savol ikki marta "yangi item" bo'lib qolishi mumkin
   (statistika bo'linadi). Bu — admin intizomi masalasi, texnik yechim:
   yuklashda `item_ref` majburiy va dublikat tekshiruvi.

## 9. Rasch kalibrlashga o'tish mezoni

Klassik modul **almashtiriladi** (o'chirilmaydi — zaxira bo'lib qoladi),
quyidagi shartlar bajarilganda:

| Mezon | Chegara | Nega |
|---|---|---|
| Item bo'yicha javoblar | `N ≥ 200` | `SE(b) ≤ 0.15` |
| Kamida nechta sessiya | ≥ 3 xil sessiya | Guruh effekti yo'qoladi |
| Anchor items qamrovi | Formaning ≥ 20% savoli `frozen` | Shkala bog'lash uchun |
| `frozen` itemlar soni | ≥ 30 ta | Barqaror o'q (scale) |
| Anchor birlashuvi | `abs(RMSD) ≤ 0.30` logit | Anchor itemlar mosligi |
| Fit statistikasi | `infit/outfit MNSQ ∈ [0.7, 1.3]` | Model mosligi |

**O'tish tartibi (xavfsiz, orqaga qaytariladigan):**

```
1. `frozen` itemlarning b lari → anchor_items jadvaliga ko'chiriladi
   (source = 'prior_calibration', locked = TRUE)
2. yangi `calibration_runs` (method = 'rasch_jmle') ishga tushiriladi:
   - anchor itemlar b si QOTIRILGAN
   - boshqa itemlar θ bilan birgalikda baholanadi (06-hujjat)
3. yangi `item_parameter_sets` yaratiladi (status = 'draft')
4. solishtirish: klassik b vs JMLE b (korrelyatsiya, RMSD, fit)
   - agar `r ≥ 0.95` va `RMSD ≤ 0.3` → parameter set 'active' qilinadi
   - aks holda → eski to'plam qoladi, sabab `calibration_runs.notes` ga yoziladi
5. `equatings` orqali eski natijalarni yangi shkalaga o'girish (agar kerak bo'lsa)
6. eski `scoring_snapshots` O'ZGARMAYDI (audit talabi)
```

**Muhim:** o'tish paytida ham `p → b` moduli **zaxira** sifatida qoladi —
yangi formadagi (`anchor` bo'lmagan) savollar uchun ishlatiladi. Ya'ni
tizim "aralash" rejimda ishlay oladi: `frozen` itemlar — Rasch b, yangi
itemlar — klassik b (Rasch shkalasiga mean-mean bilan bog'langan).

## 10. Qisqa xulosa

```
O'quvchi 40 savolga javob berdi
   → responses 40 satr (append-only)
   → sessiya yopildi, baholandi
   → kalibrlash sikli: har bir savol uchun N, A, C
   → p̂ = (C + 0.5) / (N + 1)
   → b_raw = ln((1 − p̂) / p̂)              ← user talab qilgan formula
   → guessing + mean-mean + shrinkaj       ← ishonchlilik uchun
   → item_parameters.b_value (versiyalangan)
   → keyingi baholash shu yangi b bilan
   → N ≥ 200 bo'lgach → anchor → Rasch JMLE
```
