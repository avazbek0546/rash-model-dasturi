# 06 — Rasch kalibrlashga o'tish (JMLE, anchor items, equating)

> Bu hujjat **kelajakka tayyorlik** rejasi: `p → b` (03-hujjat) moduli
> o'rnini bosadigan to'liq 1PL (Rasch) kalibrlash. Sxema (02-hujjat) va
> `services/rasch.py` (mavjud θ hisoblash) allaqachon shunga tayyor.

## 1. Nima o'zgaradi? (klassik vs Rasch)

| Jihat | Klassik (`p → b`, MVP) | Rasch JMLE |
|---|---|---|
| `b` manbasi | Bitta savolning `p` idan alohida | Barcha savollar **birgalikda**, θ bilan bog'langan |
| Guruh effekti | Mean-mean bilan tuzatiladi (taxminiy) | Tabiiy qoplanadi (joint estimation) |
| O'lchov birligi | `b` va `θ` taxminan mos | Qat'iy mos (bitta logit o'qi) |
| Savol mosligi | Tekshirilmaydi | `infit/outfit MNSQ` bilan tekshiriladi |
| Yetishmagan javob | Noto'g'ri deb olinadi | Model bo'yicha to'g'ri ishlanadi |
| Aniqlik | `SE(b)` taxminiy | `SE(b) = 1/√ΣP(1−P)` — to'g'ri |
| Formalar taqqoslash | Mumkin emas | **Anchor + equating** bilan mumkin |

## 2. Model (1PL / dichotomous Rasch)

```
P(u_ij = 1 | θ_i, b_j) = 1 / (1 + exp(−(θ_i − b_j)))
```

`i` — o'quvchi, `j` — savol, `u_ij ∈ {0,1}` (javobsiz → tashqi/`NA`).

**Log-likelihood:**

```
ln L = Σ_i Σ_j [ u_ij · ln P_ij + (1 − u_ij) · ln(1 − P_ij) ]
```

**Shaxsiy (θ) yangilash** — mavjud `services/rasch.py` dagi Newton-Raphson
bilan **aynan bir xil** (kod qayta ishlatiladi):

```
θ_i ← θ_i + Σ_j (u_ij − P_ij) / Σ_j P_ij(1 − P_ij)
SE(θ_i) = 1 / sqrt( Σ_j P_ij(1 − P_ij) )
```

**Savol (b) yangilash** — xuddi shu mantiq, faqat indekslar almashadi:

```
b_j ← b_j + Σ_i (P_ij − u_ij) / Σ_i P_ij(1 − P_ij)
SE(b_j) = 1 / sqrt( Σ_i P_ij(1 − P_ij) )
```

**Nega ishora shunday?** Agar model kuzatuvdan ko'p to'g'ri javob kutilsa
(`ΣP > Σu`), demak savol aslida qiyinroq → `b` **oshiradi**. Bu klassik
`p → b` natijasi bilan bir xil yo'nalishda (qiyin savol → katta `b`).

## 3. JMLE algoritmi (Joint Maximum Likelihood)

```
KIRISH:  javoblar matritsasi X (i × j), u_ij ∈ {0, 1, NA}
         anchor_items: {(j, b_j_fixed)}  (bo'sh bo'lishi mumkin)
         max_cycles = 100, tol = 1e-4

0. Initsializatsiya:
   b_j⁰ = hozirgi operatsion b (klassik moduldan!) yoki 0.0
   θ_i⁰ = ln[(u_i + 0.5) / (n_i − u_i + 0.5)]        # xom ball logit'i
   (mavjud `rasch.py` MLE_START uslubi)

1. HAR BIR SIKLNING BOSQICHIDA:
   a) θ yangilash (extreme o'quvchilar CHIQARILADI: u_i = 0 yoki u_i = n_i):
        θ_i ← θ_i + Σ_j (u_ij − P_ij) / Σ_j P_ij(1 − P_ij)
        (step-halving: log-likelihood kamaysa qadam ikki marta kichraytiriladi —
         mavjud `rasch.estimate_theta` mantig'i)
   b) b yangilash (anchor itemlar QOTIRILGAN — yangilanmaydi):
        b_j ← b_j + Σ_i (P_ij − u_ij) / Σ_i P_ij(1 − P_ij)

2. IDENTIFIABILITET (o'lchovni aniqlash) — ikki yo'ldan biri:
   (i)  item markazlash:  b_j ← b_j − mean(b_j)            # Σb = 0
   (ii) anchor mahkamlash: mean(b_anchor) = anchor_b_mean
        (bu holda θ shkalasi oldingi kalibrlash bilan BIR XIL bo'ladi)

3. TO'XTASH SHARTI:
   max_j |b_j^(k) − b_j^(k−1)| < tol     yoki     k = max_cycles

4. NATIJA:
   b_j, SE(b_j), θ_i, SE(θ_i), ln L, sikllar soni, konvergentsiya
   → `calibration_runs` (convergence, iterations, max_abs_delta, log_likelihood)
   → `calibration_run_items` (har bir item: b_before, b_after, b_se, delta)
   → yangi `item_parameter_sets` (method = 'rasch_jmle')
```

**Muhim nozik joylar:**

| Nuqta | To'g'ri yondashuv |
|---|---|
| `u_i = 0` yoki `u_i = n_i` (chekka o'quvchi) | θ baholanmaydi (informatsiya yo'q), **lekin javoblari item kalibrlashda ishlatiladi** |
| Yetishmagan javob (`NA`) | `Σ` da hisobga olinmaydi (klassik modulda esa noto'g'ri deb olinadi) |
| Itemda `Σu = 0` yoki `Σu = n` | `b` aniqlanmaydi (`±∞`) → anchor yoki klassik qiymatdan foydalaniladi, `status='flagged'` |
| O'lchov identifikatsiyasi | Faqat **bittasi**: yoki item markazlash, yoki anchor |
| Sikllar soni | Odatiy 10–25; 100 dan oshsa → `convergence = 'max_iter'` |
| Hisoblash narxi | `40 savol × 5000 o'quvchi` = 200k `P` hisobi/sikl ≈ bir necha sekund |

## 4. Anchor items (o'lchovni bog'lash)

**Anchor item** — `b` si **qotirilgan** savol. Kalibrlashda u o'zgarmaydi va
butun yangi formaning shkalasini eski shkalaga bog'laydi.

| Jihat | Qoida |
|---|---|
| Manbasi | `status='frozen'` bo'lgan itemlar (`N ≥ 200`, `SE ≤ 0.25`) — 03-hujjat |
| Minimal son | Har bir formada **kamida 5–10 ta** yoki savollarning **≥ 20%** |
| Joylashuvi | Formada **tarqoq** (boshida, o'rtasida, oxirida) |
| `b` qamrovi | Oson (`−2…−1`), o'rta (`−0.5…+0.5`), qiyin (`+1…+2`) — butun oraliqni qoplashi kerak |
| Saqlash | `anchor_items` jadvali (`anchor_b`, `anchor_se`, `locked=TRUE`, `valid_from/to`) |
| Tekshiruv | Har kalibrlashdan keyin: `abs(b_new − anchor_b) ≤ 1.0` logit |
| Buzilganda | `flags=['anchor_mismatch']`, `calibration_runs.notes` ga sabab, admin ko'rigi |

**Anchor tanlash tartibi:**

```
1. item_statistics dan `is_current = 1 AND status = 'frozen'` itemlarni olish
2. har biri uchun: N, SE, b, topic_id, exposure
3. saralash: kichik SE → barqaror exposure → `b` qamrovi xilma-xil
4. 5–10 tani tanlash → anchor_items ga yozish (locked = TRUE)
5. `frozen` itemlar hech qachon qayta baholanmaydi (himoya)
```

## 5. Equating (formalar orasidagi o'girish)

Ikki kalibrlash natijasini bitta o'qqa keltirish. Sxema `equatings`
jadvali bilan tayyor.

### 5.1. Mean-mean (MVP + anchor)

```
d = mean(b_anchor_yangi) − mean(b_anchor_eski)     # ikki to'plamdagi anchor farqi
b_yangi = b_xom − d                                # hamma itemlarga bitta siljish
θ_yangi = θ_xom − d                                # θ ham shu siljishga mos
equatings: constant_slope = 1.0, constant_intercept = −d
```

### 5.2. Haebara / Stocking-Lord (to'liq, keyingi bosqich)

Chiziqli o'girish: `θ_new = A · θ_old + B`, bu yerda `A`, `B` test
informatsiya funksiyalarini moslashtirib topiladi:

```
minimize  ∫ [ I_new(A·θ + B) − I_old(θ) ]² dθ
```

Rasch modelida `a = 1` bo'lgani uchun amalda `A = 1.0` — ya'ni equating
**sof siljish** bo'ladi. Bu **to'g'ri va standart** yondashuv.

### 5.3. O'girishni qo'llash

```
1. yangi `item_parameter_sets` yaratiladi (barcha b yangi shkalada)
2. `equatings` satri yoziladi (from → to, constant_intercept)
3. yangi urinishlar yangi to'plam bilan baholanadi
4. ESKI `scoring_snapshots` O'ZGARMAYDI
5. kerak bo'lsa `result_versions` ga yangi versiya:
   "shkala yangilandi — ballar qayta hisoblandi" izohi bilan
```

## 6. Fit statistikasi (model mosligi)

`item_statistics` ga qo'shimcha ustunlar (MVP-2 da):

```
J_ij     = P_ij · (1 − P_ij)                   # dispersiya (Rasch)
z_ij     = (u_ij − P_ij) / sqrt(J_ij)          # standart rezidual
Outfit_j = (1/n_j) · Σ_i z_ij²                 # MNSQ (outfit)
Infit_j  = Σ_i z_ij²·J_ij / Σ_i J_ij           # MNSQ (infit, vaznli)
```

| Ko'rsatkich | Qabul | Shubhali | Izoh |
|---|---|---|---|
| Outfit MNSQ | 0.7 – 1.3 | < 0.7 yoki > 1.3 | Kutilmagan javoblar (oz sonli o'quvchi) |
| Infit MNSQ | 0.7 – 1.3 | < 0.7 yoki > 1.3 | O'quvchi darajasiga mos kelmagan javoblar |
| Person fit | 0.5 – 1.5 | tashqarida | "Tasodifiy" yoki "qoidabuzar" javob bergan o'quvchi |

**Choralar:**

| Topilma | Harakat |
|---|---|
| Item fit yomon (`MNSQ > 1.5`) | Savol `status='flagged'`, admin ko'rigi, kalit tekshiruvi |
| Item fit juda past (`MNSQ < 0.6`) | Informativi kam → `retired` ga nomzod |
| Person fit yomon | Natija **bekor qilinmaydi**, lekin `attempts.status='invalid'` ko'rib chiqiladi |

## 7. Drift va DIF (keyingi bosqich)

| Tur | Savol | Usul |
|---|---|---|
| **Drift** (vaqt bo'yicha) | Savol yillar o'tib osonlashdi/qiyinlashdi? | Ikki davr `b` farqi (z-test) — MVP'da ham bor (03-hujjat) |
| **DIF** (guruh bo'yicha) | Hudud/til bo'yicha savol boshqacha ishlaydimi? | Mantel-Haenszel (oddiy) yoki Rasch DIF |
| Manba | `attempt_attributes` (`region`, `language`) | Sxema tayyor (02-hujjat) |

```
Mantel-Haenszel (DIF) — qisqacha:
  o'quvchilarni θ bo'yicha qatlamlarga bo'lish (masalan, 10 ta qatlam)
  har qatlamda 2×2 jadval:  [guruh × to'g'ri/noto'g'ri]
  MH statistikasi hisoblanadi → |MH| > 1.5 va p < 0.05 → DIF gumoni
```

> ⚠️ DIF tahlili **milliy sertifikat** uchun muhim: hudud/til bo'yicha farq
> aniqlansa, savol qayta ko'riladi. Bu bosqich **MVP-2 dan keyin**
> (3–4-chorak) rejalashtiriladi.

## 8. Amalga oshirish bosqichlari

| Bosqich | Nima qilinadi | Bog'liqlik |
|---|---|---|
| **P1** | `services/calibration.py` ga `method='rasch_jmle'` shoxi; anchor hurmat qilinadi | 03-hujjat moduli |
| **P2** | `calibration_runs`, `calibration_run_items` to'liq yozish, `convergence` monitoringi | 02-hujjat jadvallari |
| **P3** | Fit statistikasi (`infit/outfit`) va `flagged` itemlar oqimi | P1 |
| **P4** | Klassik va JMLE natijalarini solishtirish hisoboti (`/calibration compare`) | P1 |
| **P5** | Equating (`mean_mean` + anchor) va yangi `item_parameter_sets` | `anchor_items` |
| **P6** | DIF/drift hisobotlari, exposure nazorati | `attempt_attributes` |

## 9. Validatsiya (Rasch moduli to'g'ri ishlashini qanday bilamiz?)

| # | Test | Kutilgan |
|---|---|---|
| 1 | Sun'iy ma'lumot: ma'lum `b` lar bo'yicha javoblar generatsiya qilinadi | JMLE `b` lari haqiqiy qiymatlarga `±0.2` logit ichida qaytadi |
| 2 | Konvergensiya: 2 xil boshlang'ich nuqta | Bir xil natija (`max abs Δb < 1e-3`) |
| 3 | Anchor: `b` qotirilgan item | Kalibrlashdan keyin o'zgarmagan |
| 4 | Chekka o'quvchilar | θ baholanmagan, lekin item kalibrlashda ishtirok etgan (`n_used` da ko'rinadi) |
| 5 | Mavjud `rasch.py` bilan moslik | Bir xil `b` lar berilganda θ **aynan** bir xil (mavjud `test_rasch.py` ga tayanish) |
| 6 | `SE(b)` kamayishi | `N` ikki barobar → `SE` `√2` marta kamayadi |
| 7 | Taqqoslash (ixtiyoriy) | `mirt` / `jamovi` bilan solishtirish (`±0.05` logit) |

## 10. Hisoblash resursi

| Ko'lam | Amal soni (sikl boshiga) | Sof Python | `numpy` bilan |
|---|---|---|---|
| 40 savol × 200 o'quvchi | 8 000 `P` hisobi | ~0.05 s | — |
| 40 savol × 2 000 o'quvchi | 80 000 | ~0.5 s | ~0.02 s |
| 40 savol × 20 000 o'quvchi | 800 000 | ~5 s | ~0.2 s |

20–25 sikl bilan: **2 daqiqadan kam** (sof Python, 20k o'quvchi). Ya'ni
milliy daraja uchun ham `numpy` **majburiy emas**; faqat juda katta
ko'lamda (100k+) qo'shiladi.

## 11. Xulosa: to'liq zanjir

```
MVP (hozir)                     →  Kalibrlash (keyingi bosqich)
─────────────────────────────────────────────────────────────────────
p = C/N                         →  JMLE: θ va b birgalikda
b = ln((1−p)/p)                 →  P_ij = 1/(1+e^−(θ_i−b_j))
mean-mean (θ̄)                   →  Identifikatsiya: anchor / markazlash
shrinkaj (prior)                →  (kerak emas — JMLE barqaror)
SE ≈ 1/√(N·p(1−p))              →  SE(b) = 1/√ΣP(1−P)
drift (z-test)                  →  drift + DIF (Mantel-Haenszel)
anchor: status='frozen'         →  anchor_items (locked)
—                               →  equating (mean-mean / Haebara)
—                               →  fit: infit/outfit MNSQ
```

**Eng muhim xulosa:** 03-hujjatdagi modul **tashlanmaydi** — u yangi
formalar, yangi savollar va anchor bo'lmagan holatlar uchun **zaxira**
bo'lib qoladi. Tizim ikki rejimni **bir vaqtda** qo'llab-quvvatlaydi va
bu `item_parameter_sets` + `scoring_snapshots` tufayli **hech qanday
natijani buzmaydi**.
