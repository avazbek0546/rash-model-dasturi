# Standart `p → b` qiyinchilik xaritasi va kalibrlash

Bu hujjat ikki narsani ajratib tushuntiradi:

1. **Standart `p → b` xaritasi** — admin p foizlarni har safar kiritmasligi
   uchun `services/default_difficulty.py` da saqlanadigan 55 itemli xarita;
2. **Kalibrlash** — admin panelidagi «📐 Kalibrlash» tugmasi nima qiladi va
   u standart xaritadan qanday farq qiladi.

---

## 1. Standart `p → b` xaritasi

### Manba

Rasmdagi 55 item bo'yicha `p` (to'g'ri javob berganlar foizi) qiymatlari
`services/default_difficulty.py` dagi `DEFAULT_PERCENT_BY_LABEL` da
saqlanadi:

- `1`..`35` — yopiq savollar;
- `36a`, `36b`, ..., `45a`, `45b` — ochiq savollarning A/B qismlari.

### Formula

Har bir item uchun:

```text
p = percent / 100
b = ln((1 - p) / p)
```

`p` `[0.01, 0.99]` oralig'iga, `b` esa `[-4.6, +4.6]` oralig'iga siqiladi
(`p = 0` yoki `p = 100` da ham chekli qiymat qoladi). Bu
`services/item_statistics.py` dagi klassik `p → b` modeli bilan bir xil.

Misol:

| p | b |
|---|---|
| 90% | −2.197 |
| 70% | −0.847 |
| 50% | 0.000 |
| 30% | +0.847 |
| 4% | +3.178 |

### Qayerda ishlatiladi

- **Yangi imtihon yaratilganda** (`/new_exam` ustasi yoki Mini App
  «⚙️ Test yaratish»): qiyinchilik berilmasa, `exams.difficulty_logits`
  maydoniga 55 itemli JSON obyekt yoziladi. Admin p kiritmaydi.
- **Qayta baholash (regrade)**: agar imtihonda **aniq per-item `b`**
  bo'lmasa (eski 45 pozitsiyali massiv yoki bo'sh), regrade avval standart
  xaritani yozadi, keyin barcha javoblarni qayta baholaydi. Shu sababli
  mavjud imtihonlarda ham natija o'zgaradi. Aniq per-item `b` (JMLE bank)
  bo'lsa — u tegilmaydi.
- **Mavjud imtihonlar uchun**: `scripts/apply_default_difficulty.py`
  skripti bilan qo'llanadi (dry-run/`--apply`).
- **Zaxira**: `exams.difficulty_logits` umuman bo'sh bo'lsa,
  `services.exam_service.b_by_key()` standart xaritani qaytaradi.

### Baholash qanday ishlaydi

1. `exams.difficulty_logits` o'qiladi.
2. Agar u 55 itemli obyekt yoki 55 qiymatli massiv bo'lsa — har bir item
   o'z `b` sini oladi; `THETA_METHOD=auto` **EAP** ni tanlaydi.
3. 36–45 qismlari (`36a`, `36b`, ...) **alohida** item bo'lib baholanadi —
   jami 55 item.
4. `θ` 0–100 shkalaga o'tkaziladi va sertifikat darajasi aniqlanadi:
   `<46 → NC`, `46 → C`, `50 → C+`, `55 → B`, `60 → B+`, `65 → A`,
   `70 → A+`.

Eslatma: standart xarita bilan `24/55` ≈ **51 ball (C+)**, JMLE bank bilan
`24/55` = **44.66 (NC)**. Farq `b` shkalasida — standart xarita siz kiritgan
p foizlardan hisoblanadi, JMLE bank esa javoblar matritsasidan birgalikda
baholangan.

---

## 2. Kalibrlash («📐 Kalibrlash») nima qiladi?

Admin panelidagi har bir imtihon qatorida «📐 Kalibrlash» tugmasi bor. U
`POST /api/v2/admin/exams/{exam_id}/calibrate` endpointini chaqiradi:

1. **Matritsa yig'ish** — imtihon javoblaridan `o'quvchi × item` matritsasi
   quriladi (`online`, `offline` yoki `combined` manbadan).
2. **JMLE** (Joint Maximum Likelihood Estimation) — `b` (item qiyinchiligi)
   va `θ` (o'quvchi darajasi) **birgalikda**, Nyuton-Rafson iteratsiyalari
   bilan baholanadi.
3. **Preview** — `N` (o'quvchilar), `K` (itemlar), iteratsiyalar soni,
   yaqinlashish (`converged`), `b` oralig'i va ogohlantirishlar ko'rsatiladi.
4. **Apply** — tasdiqlansa, yangi `b` qiymatlari `exams.difficulty_logits`
   ga yoziladi va imtihon **qayta baholanadi** (regrade).

### Kalibrlash shartlari

- Standart `min_n = 200`: `N < 200` bo'lsa endpoint `400` qaytaradi.
  Kichik guruhda JMLE beqaror bo'ladi.
- `b` ni tez-tez qayta kalibrlamang: yangi forma uchun anchor/equating
  ishlatiladi.
- `b` yangilangach natijalar o'zgaradi — bu **yangi natija versiyasi**
  hisoblanadi (eski snapshot saqlanib qoladi).

### Standart xarita va kalibrlash farqi

| | Standart `p → b` | JMLE kalibrlash |
|---|---|---|
| Manba | Rasmdagi p foizlar | Haqiqiy javoblar matritsasi |
| Formula | `b = ln((1-p)/p)` | `b` va `θ` birgalikda optimallashtiriladi |
| `N` talabi | Yo'q (qo'lda kiritilgan) | `N ≥ 200` |
| Qachon ishlatiladi | Yangi test, ma'lumot kam | Ko'p javob to'plangach, aniqroq baho |
| `24/55` natijasi | ≈ 51 (C+) | ≈ 44.66 (NC) |

Ikkalasi bir vaqtda ishlatilmaydi: agar imtihonga JMLE bank yozilgan bo'lsa,
u standart xaritadan **ustun** turadi; standart xarita faqat aniq per-item
`b` bo'lmaganda ishlaydi.

---

## 3. Tekshirish

- Natija kartasidagi maxraj: `24/55` — 55 itemli oqim ishlayapti;
  `24/45` — eski 45 pozitsiyali oqim.
- `exams.difficulty_logits`:
  - `{"1": ..., "36a": ...}` — 55 itemli xarita;
  - `[...45 ta son...]` — eski pozitsiya massivi.
- `item_difficulty_stats` (dashboard) — **faqat hisobot**; baholashga
  ta'sir qilmaydi.
- `item_parameters.b_value` — hozircha baholashda ishlatilmaydi.

---

## 4. Qayta baholashdan keyin

- Web App’dagi natija darhol yangilanadi.
- Telegram natija xabari avval yuborilgan bo'lsa (`user_answers.notified_at`
  to'ldirilgan), bot **yangi xabar yubormaydi** — eski xabar eski qiymatni
  ko'rsatishi mumkin.
- Natija hali e'lon qilinmagan bo'lsa, regrade’ni `result_time` dan oldin
  qiling — keyin yangi natija yuboriladi.
