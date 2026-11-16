# EAP va per-item item bank (Rasch 1PL)

Bu hujjat production Rasch 1PL modelini (JMLE+EAP) loyihaga ulash tartibini
tushuntiradi. **UI o'zgarmaydi** — faqat baholash yadrosi.

## 1. Nima o'zgardi

| Qism | Eski xulq | Yangi xulq |
|---|---|---|
| θ usuli | MLE (Newton-Raphson) | **EAP** (per-item `b` bo'lsa) |
| 55/55 natijasi | θ=+3 → **91** | θ≈2.45 → **90.86** (chekli) |
| 0/55 natijasi | θ=−3 → **9** | ≈9.7 (chekli, cap yaqinida) |
| `b` manbasi | 45 pozitsiya | **55 item** (`1..35`, `36a..45b`) |
| 36a/36b | 36-pozitsiya `b` si | **alohida** `b` |

Legacy (45 pozitsiyali) imtihonlar **o'zgarmaydi**: `auto` rejimda ular MLE
bilan baholanadi.

## 2. Item bank formati

`assets/item_banks/<test_code>.json`:

```json
{
  "test_code": "m3rash25",
  "model": "rasch_1pl",
  "theta_method": "eap",
  "prior_sd": 0.53,
  "source": "rasch_1pl_m3rash25.pdf — JMLE+EAP, N=1271",
  "b_by_label": {
    "1": -1.649,
    "35": 0.560,
    "36a": 0.135,
    "36b": 2.142,
    "45b": 3.184
  }
}
```

- `b_by_label` — 55 ta item (35 variant + 20 qism).
- `prior_sd` — EAP priorining standart chetlanishi (productionda ~0.53).
- `source` — kalibrlash manbasi (audit uchun).

Bank `exams.difficulty_logits` ga **JSON obyekt** sifatida yoziladi
(`b_by_label` ning o'zi). 55 qiymatli massiv ham qabul qilinadi
(`1..35`, `36a..45b` tartibida).

## 3. Yuklash

```bash
# dry-run (hech narsa yozilmaydi)
python scripts/load_item_bank.py --file assets/item_banks/m3rash25.json \
  --test-code m3rash25

# yozish
python scripts/load_item_bank.py --file assets/item_banks/m3rash25.json \
  --test-code m3rash25 --apply
```

Keyin imtihonni **qayta baholang** (admin panel «🔄 Baholash» yoki
`POST /api/v2/admin/exams/{id}/regrade`).

## 4. Config

| O'zgaruvchi | Default | Ma'no |
|---|---|---|
| `THETA_METHOD` | `auto` | `auto` / `eap` / `mle` |
| `EAP_PRIOR_MEAN` | `0.0` | prior o'rtachasi |
| `EAP_PRIOR_SD` | `0.53` | prior SD (testga moslanadi) |
| `EAP_GRID_MIN/MAX` | `-6/6` | integratsiya oralig'i |
| `EAP_GRID_STEP` | `0.01` | qadam |

`auto`: per-item `b` (`36a` kabi belgilar) bo'lsa EAP, aks holda MLE.

## 5. Kichik namuna (N) siyosati

- **Baholash** `b` qat'iy bo'lsa `N` ga bog'liq emas — 1 kishi ham to'g'ri
  baholanadi (CI kengroq).
- **Kalibrlash** uchun `N ≥ 100–200`; undan kam bo'lsa eski bankni saqlang
  yoki shrinkaj qiling.
- Har imtihonda `b` ni qayta kalibrlamang; yangi forma uchun anchor/equating.
- `b` ni yangilashdan oldin: `r ≥ 0.95`, `RMSD ≤ 0.30` tekshirilsin.

## 6. Validatsiya

`tests/test_eap_item_bank.py`:

```bash
python tests/test_eap_item_bank.py
```

Tekshiradi: item bank 55 ta, `36a`/`36b` alohida, EAP tanlanishi,
55/55 → ~90.86, 0/55 → ~9.7, 48/55 → 91 emas, fanlar 35/20, legacy MLE.

## 7. Test sifati dashboardi

Yangi servis: `services/test_quality.py`. Hisoblaydi:

- Cronbach α, EAP (marginal) ishonchlilik;
- item `p`, `r_pbi`, infit/outfit, `b`;
- SRMSR, M2, RMSEA, CFI/TLI (**limited-information approximation**);
- Wright xaritasi (θ va `b` gistogrammasi);
- TIF (`I(θ) = Σ P(1−P)`).

### API (faqat admin)

```text
GET /api/v2/admin/exams/{exam_id}/quality?source=combined
```

`source`: `online` | `offline` | `combined` (default). `combined` — reytingdagi
kabi: bog'langan/dublikat online natijalar chiqarib tashlanadi, offline
`included_in_ranking = 1` natijalar qo'shiladi.

Javob: `summary` (`online_participants`, `offline_participants`,
`excluded_online` bilan), `items[]`, `wright`, `tif`, `warnings`.

### CLI / mustaqil HTML

```bash
# JSON (combined)
python scripts/test_quality.py --test-code m3rash25 --json quality.json

# Faqat offline
python scripts/test_quality.py --test-code m3rash25 --source offline --html offline.html

# Mustaqil HTML dashboard (Wright + TIF bilan)
python scripts/test_quality.py --test-code m3rash25 --html quality.html
```

> M2/RMSEA/CFI/TLI — approximation; `metrics_version` javobda ko'rsatiladi.
> Aniq M2 uchun to'liq pair covariance va katta hisob kerak. SRMSR bevosita
> standartlashtirilgan residuallardan hisoblanadi.

