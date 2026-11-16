# 14 — Avtomatik `b` kalibrlash (Rasch 1PL / JMLE)

## 1. Qachon ishlatiladi?

Testda yetarli javob yig'ilgach:

| N (qatnashchi) | Tavsiya |
|---|---|
| `< 200` | Kalibrlamang — mavjud bank/prior ishlating |
| `200–1000` | Ehtiyotkorlik bilan, prior/shrinkaj bilan |
| `1000–10 000` | Yaxshi |
| `> 10 000` | Barqaror; JMLE odatda 5–15 iteratsiyada yaqinlashadi |

`min_n` default **200**. Kam bo'lsa API/CLI **400/2** bilan rad etadi — jim
o'tib ketmaydi.

## 2. Algoritm

`services/calibration.py` — **JMLE** (Joint Maximum Likelihood Estimation):

1. `b` ni `p = correct/N` dan boshlang'ich baholaydi:
   `b = ln((1−p)/p)`, `p` 0/1 dan `(r+0.5)/(N+1)` bilan tekislanadi.
2. Har bir o'quvchi uchun θ ni Nyuton-Raphson bilan baholaydi (fixed `b`).
3. Har bir item uchun `b` ni Nyuton bilan yangilaydi (fixed θ):
   `Σ p_ij = r_j`.
4. `b` o'rtachasini 0 ga keltiradi (Rasch identifikatsiyasi).
5. `max|Δb| < tol` bo'lguncha takrorlaydi.
6. Har bir `b` uchun standart xato: `SE = 1 / sqrt(Σ p(1−p))`.

Chegaralar: `b ∈ [−4.6, +4.6]`, `θ ∈ [−6, +6]`. Hammasi to'g'ri/noto'g'ri
itemlar chegaraga qisiladi va `warnings` da ko'rsatiladi.

## 3. CLI

```bash
# Preview (hech narsa yozilmaydi)
python scripts/calibrate_item_bank.py --test-code m3rash25

# 10 000+ javobdan kalibrlab, examga yozish
python scripts/calibrate_item_bank.py --test-code m3rash25 --min-n 200 --apply

# Mavjud bankni prior sifatida ishlatish (kichik N uchun)
python scripts/calibrate_item_bank.py --test-code m3rash25 \
  --prior-file assets/item_banks/m3rash25.json --apply

# JSON natijani saqlash
python scripts/calibrate_item_bank.py --test-code m3rash25 --out calibration.json
```

Manba: `--source online|offline|combined` (default `combined`). `combined` —
reytingdagi kabi bog'langan/dublikat online natijalarni chiqarib tashlaydi.

## 4. Admin API

```text
POST /api/v2/admin/exams/{exam_id}/calibrate
```

Body:

```json
{
  "source": "combined",
  "min_n": 200,
  "max_iter": 100,
  "tol": 0.0001,
  "apply": false
}
```

- `apply=false` (default) — faqat preview: `b_by_label`, `se_by_label`,
  `person_count`, `item_count`, `iterations`, `converged`, `b_min/b_max`,
  `warnings`.
- `apply=true` — `exams.difficulty_logits` ga yozadi va `b_json` qaytaradi.
- `N < min_n` → `400`.

Yozgandan keyin **regrade** qiling:

```text
POST /api/v2/admin/exams/{exam_id}/regrade
```

## 5. Xavfsizlik tartibi

1. Avval **dry-run** (CLI yoki `apply=false`) — `N`, `K`, `converged`, `b`
   oralig'ini tekshiring.
2. `b` chegarada bo'lgan itemlarni ko'rib chiqing (`warnings`).
3. DB nusxasini oling (productionda).
4. `--apply` / `apply=true`.
5. Regrade qiling.
6. Natijalarni eski natijalar bilan solishtiring.

> Kalibrlash har bir javobda avtomatik ishlamaydi — bu **boshqariladigan**
> amal. Sabab: `b` ni har safar o'zgartirish natijalarni beqaror qiladi.
> Test yopilgach yoki yetarli `N` yig'ilgach bir marta ishlating.

## 6. Item bank bilan bog'lanish

Kalibrlash natijasi `exams.difficulty_logits` ga **label bo'yicha JSON obyekt**
sifatida yoziladi:

```json
{"1": -1.649, "2": -2.081, "36a": 0.135, "36b": 2.142}
```

`THETA_METHOD=auto` bo'lsa, per-item `b` borligi uchun baholash avtomatik
**EAP** rejimiga o'tadi. Keyingi kalibrlashda `--prior-file` sifatida shu bankni
berish mumkin.
