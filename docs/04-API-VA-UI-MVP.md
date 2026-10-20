# 04 — MVP API'lari, bot oqimi va Mini App UI

## 1. API tamoyillari

| Tamoyil | Qoida |
|---|---|
| Bazaviy manzil | `/api/v2/*` (mavjud `/api/*` ishlab turadi — bosqichma-bosqich ko'chirish) |
| Autentifikatsiya | `X-Init-Data: <Telegram initData>` (HMAC-SHA256, mavjud `services/webapp_auth.py`); admin endpoint'larida qo'shimcha rol tekshiruvi |
| Foydalanuvchi | **Har doim** `initData` dan olinadi — so'rov tanasidan **hech qachon** |
| Javob formati | `{"ok": true, ...}` yoki `{"ok": false, "error": "…"}` (mavjud uslub) |
| Vaqt | Serverda UTC ISO, ko'rsatishda `Asia/Tashkent` (`exam_service.format_local`) |
| Idempotentlik | `PUT` amallari `client_seq` bilan; bir xil `client_seq` → `200`, yangi satr yo'q |
| Optimistik qulf | Har bir yozish `revision` qaytaradi; eski `revision` → `409` + server holati |
| Rate limit | `PUT/POST`: 30 so'rov/daqiqa/foydalanuvchi (`RATE_LIMIT_PER_MINUTE`) |
| Sir saqlash | `answer_key`, `b_value`, statistika — **o'quvchi API'sida yo'q** |
| Xatolik kodlari | `400` noto'g'ri kiritish, `401` auth yo'q, `403` ruxsat yo'q, `404` topilmadi, `409` konflikt/qulf, `410` muddat tugagan, `429` limit |

## 2. Xatolik xabarlari (o'zbekcha, `texts.py` ga qo'shiladi)

| Kod | Xabar |
|---|---|
| `400` | `Test kodi kamida 4 belgidan iborat bo'lishi kerak.` |
| `404` | `Bunday test kodi topilmadi. Kodni tekshirib qayta kiriting.` |
| `410` | `Javob qabul qilish vaqti tugagan ({{end_time}}).` |
| `409` | `Javoblaringiz boshqa qurilmada yangilangan. Sahifa avtomatik yangilanadi.` |
| `403` | `Bu imtihonda qatnashish huquqi yo'q.` |
| `429` | `Juda ko'p so'rov — biroz kutib, qayta urinib ko'ring.` |

## 3. O'quvchi API'lari (6 ta — MVP uchun yetarli)

### `POST /api/v2/sessions/verify`

Test kodini tekshiradi va ochiq sessiya haqida **kalitsiz** ma'lumot qaytaradi.

```json
// so'rov
{ "test_code": "MS-MATH-2603" }

// javob
{
  "ok": true,
  "session_id": 12,
  "form_id": 5,
  "form_version_id": 9,
  "title": "Milliy sertifikat — Matematika, 1-variant",
  "total_questions": 40,
  "parts": ["36a", "36b"],
  "options_count": 4,
  "status": "active",
  "status_title": "Javob qabul qilinmoqda",
  "can_start": true,
  "already_submitted": false,
  "attempt_id": null,
  "end_time_local": "12.03.2026 13:00",
  "result_time_local": "15.03.2026 10:00",
  "seconds_left": 3600,
  "message": "Javoblar 12.03.2026 13:00 gacha qabul qilinadi."
}
```

> ⚠️ Javobda **hech qanday** kalit, `b` yoki `item_ref` yo'q — faqat savollar
> **soni**, variantlar soni va qism belgilari.

### `POST /api/v2/attempts` — urinishni boshlash (idempotent)

```json
// so'rov
{ "test_code": "MS-MATH-2603", "device": { "ua": "…", "tz": "Asia/Tashkent" } }

// javob — savollar ro'yxati (matnsiz, faqat pozitsiyalar)
{
  "ok": true,
  "attempt_id": 771,
  "revision": 3,
  "status": "in_progress",
  "started_at": "2026-03-12T07:00:11+00:00",
  "seconds_left": 3590,
  "items": [
    { "position": 1,  "part": "",  "options": 4, "section": 1 },
    { "position": 2,  "part": "",  "options": 4, "section": 1 },
    { "position": 36, "part": "a", "options": 4, "section": 2 },
    { "position": 36, "part": "b", "options": 4, "section": 2 }
  ],
  "responses": { "1": "A", "2": "C", "36a": "B" }
}
```

Ikkinchi marta chaqirilsa **yangi urinish yaratilmaydi** — mavjudi
qaytariladi (bir o'quvchi + bir sessiya = bir urinish).

### `PUT /api/v2/attempts/{attempt_id}/responses` — autosave (asosiy endpoint)

```json
// so'rov
{
  "revision": 3,
  "items": [
    { "position": 1, "part": "", "option": "B", "client_seq": 41 },
    { "position": 7, "part": "", "option": null, "client_seq": 42 }
  ]
}

// javob
{
  "ok": true,
  "revision": 4,
  "saved": [ { "position": 1, "part": "", "option": "B" } ],
  "cleared": [ { "position": 7, "part": "" } ],
  "saved_at": "2026-03-12T07:04:52+00:00",
  "seconds_left": 3310
}
```

**Xulq-atvor qoidalari:**

| Holat | Natija |
|---|---|
| Bir xil `client_seq` qayta kelgan | `200` (idempotent takror — yangi satr yozilmaydi) |
| `revision` eski | `409` + joriy `revision` va javoblar (`state` bilan bir xil) |
| `option = null` | javob tozalanadi (`response_state = 'cleared'`, `is_correct = NULL`) |
| `option` `A/B/C/D` dan boshqa | `400` (butun paket rad etiladi — qismiy yozish yo'q) |
| `end_time` o'tgan | `410` |
| Urinish `submitted` | `409` (javob qabul qilinmaydi) |
| Paketda 0 yoki > 40 item | `400` |

### `GET /api/v2/attempts/{attempt_id}/state` — refresh / qayta ochish

```json
{
  "ok": true,
  "attempt_id": 771,
  "status": "in_progress",
  "revision": 4,
  "seconds_left": 3310,
  "answered_count": 24,
  "total_items": 40,
  "items": [ { "position": 1, "part": "", "options": 4 } ],
  "responses": { "1": "B", "2": "C", "36a": "B" }
}
```

> Bu endpoint **refresh** bo'lganda javoblar yo'qolmasligi uchun kerak:
> `localStorage` bo'sh bo'lsa ham server holati qaytariladi.

### `POST /api/v2/attempts/{attempt_id}/submit` — yakunlash

```json
// so'rov
{ "revision": 4, "confirm": true }

// javob
{
  "ok": true,
  "status": "submitted",
  "submitted_at": "2026-03-12T07:30:00+00:00",
  "answered_count": 38,
  "omitted_count": 2,
  "result_time_local": "15.03.2026 10:00",
  "message": "Javoblaringiz qabul qilindi. Natija 15.03.2026 10:00 da e'lon qilinadi."
}
```

`submit` da: paketda kelgan oxirgi o'zgarishlar yoziladi, `is_correct`
hisoblanadi, `attempts.status = 'submitted'`, `attempt_events` ga yozuv
qo'shiladi. **θ hisoblanmaydi** (faqat `end_time` dan keyin).

### `GET /api/v2/attempts/{attempt_id}/result` — natija (`result_time` dan keyin)

```json
{
  "ok": true,
  "attempt_id": 771,
  "result_version": 1,
  "title": "Milliy sertifikat — Matematika, 1-variant",
  "raw_score": 31,
  "total_items": 40,
  "theta": 0.4213,
  "standard_error": 0.3802,
  "scaled_score": 57.02,
  "scaled_interval": [49.61, 64.43],
  "ability_level": "O'rta-yuqori",
  "published_at": "2026-03-15T05:00:00+00:00",
  "items": [
    { "position": 1, "part": "", "given": "B", "correct": "B", "is_correct": true,
      "difficulty": -0.45, "difficulty_label": "oson", "probability": 0.70 }
  ]
}
```

`result_time` kelmagan bo'lsa → `403` + `Natija 15.03.2026 10:00 da e'lon
qilinadi.` (kalit ham, `b` ham oshkor bo'lmaydi).

## 4. Admin API'lari (kalibrlashni boshqarish)

Bularning barchasi **bot orqali** yoki admin Mini App orqali chaqiriladi.
Har bir amal `audit_log` ga yoziladi.

| Metod | Yo'l | Vazifasi |
|---|---|---|
| `POST` | `/api/v2/admin/forms` | Yangi forma (test kodi + kalit + metadata) — **`b` yo'q** |
| `PATCH` | `/api/v2/admin/forms/{id}` | Tahrirlash → **yangi `form_version`** (eski versiya qoladi) |
| `POST` | `/api/v2/admin/sessions` | Sessiya (vaqt oynasi) yaratish |
| `GET` | `/api/v2/admin/items/{item_version_id}/statistics` | `n`, `p`, `b`, `SE`, `flags` tarixi |
| `GET` | `/api/v2/admin/calibration/runs` | Kalibrlash tarixi |
| `POST` | `/api/v2/admin/calibration/run` | Kalibrlashni qo'lda ishga tushirish (`scope`, `method`, `dry_run`) |
| `POST` | `/api/v2/admin/items/{id}/freeze` | `b` ni qo'lda qotirish (`status='frozen'`) |
| `POST` | `/api/v2/admin/items/{id}/anchor` | Anchor item qilish (`anchor_b` bilan) |
| `POST` | `/api/v2/admin/equating/run` | Ikki parametrlar to'plamini bog'lash |
| `GET` | `/api/v2/admin/audit` | `audit_log` so'rovi (`entity_type`, `entity_id`, `from`, `to`) |
| `GET` | `/api/v2/admin/export` | CSV/JSON eksport (`raw`, `θ`, `scaled`, item statistikasi) |

**Forma yaratish so'rovi (diqqat: `difficulty` maydoni yo'q!):**

```json
{
  "title": "Milliy sertifikat — Matematika, 1-variant",
  "test_code": "MS-MATH-2603",
  "program_code": "MATH-A",
  "options_count": 4,
  "total_questions": 40,
  "parts": ["36a", "36b"],
  "answer_key": "1A2B3C4D…",
  "schedule": {
    "start": "12.03.2026 09:00",
    "end":   "12.03.2026 13:00",
    "result":"15.03.2026 10:00"
  },
  "reuse_items": true          // mavjud itemlarni item_ref bo'yicha qidirish
}
```

`reuse_items: true` bo'lsa tizim `form_items` ni mavjud `item_version` larga
bog'lashga harakat qiladi (statistika uzluksiz to'planadi); aks holda har bir
pozitsiya uchun yangi `item` + `item_version` yaratadi.

**Kalibrlashni ishga tushirish:**

```json
// so'rov
{ "scope": "form", "scope_id": 5, "method": "guessing_corrected", "dry_run": false }

// javob
{
  "ok": true,
  "run_id": 33,
  "code": "CAL-2026-03-15-01",
  "item_count": 40,
  "response_count": 4820,
  "updated": 12,
  "frozen_skipped": 3,
  "insufficient_n": 25,
  "flagged": [ { "position": 7, "flags": ["key_suspect"], "n": 118 } ],
  "max_abs_delta": 0.412,
  "convergence": "converged",
  "iterations": 3
}
```

## 5. Telegram Bot oqimi

### 5.1. O'quvchi

```
/start
  ├─ Ism familiya so'raladi (mavjud oqim) → users.upsert()
  └─ Inline: [📝 Javoblarni belgilash] → [🔍 Test tahlili] → [🏡 Asosiy menyu] → [ℹ️ Yordam]
                (birinchi tugma — WebAppButton, WEBAPP_URL)
                                    ↓
              Mini App: test kodi → javoblar varag'i → yakunlash

Natija tayyor bo'lganda (result_time):
  📊 Milliy sertifikat — Matematika, 1-variant
  To'g'ri javoblar: 31/40
  Ballar: 57.02 (0–100)
  Bilim darajasi: O'rta-yuqori (±7.4)
  [📄 Batafsil tahlil]  → Mini App "Natijalar" bo'limi
```

### 5.2. O'qituvchi (admin)

| Komanda | Vazifasi |
|---|---|
| `/new_form` | Yangi test ustasi — **6 qadam, `b` va logit SO'RALMAYDI** |
| `/forms` | Formalar ro'yxati (`/form MS-MATH-2603` — batafsil) |
| `/stats` | Umumiy statistika (o'quvchilar, sessiyalar, javoblar, `b` holati) |
| `/item 7` | 7-pozitsiya bo'yicha statistika: `n`, `p`, `b ± SE`, `flags` |
| `/hardest` | Eng qiyin 10 savol (joriy `b` bo'yicha) |
| `/calibration` | Kalibrlashni qo'lda ishga tushirish (tugmalar bilan) |
| `/freeze 7` | 7-savolning `b` sini qotirish |
| `/anchor 7 1.25` | 7-savolni anchor qilish (`b = 1.25`) |
| `/export MS-MATH-2603` | Natijalar CSV |
| `/cancel` | Ustani bekor qilish (mavjud) |

**`/new_form` ustasi (yangi, 6 qadam):**

```
1/6  Test nomi?                    → "Milliy sertifikat — Matematika, 1-variant"
2/6  Test kodi?                    → "MS-MATH-2603"
3/6  Fan/yo'nalish?                → [MATH-A] [MATH-B] [UZ-A] …  (inline tugmalar)
4/6  Savollar soni va qismlar?     → "40" / "36a,36b" (ixtiyoriy)
5/6  Javoblar kaliti?              → "1A2B3C…"  (bo'sh joy/vergul ham mumkin)
6/6  Vaqtlar?                      → "12.03.2026 09:00 - 13:00 | natija 15.03.2026 10:00"
     ──────────────────────────────────────────────
     ✅ Xulosa → [Tasdiqlash] [Bekor qilish]
     ⚠️ Hech qachon: qiyinchilik / logit / Rasch parametri so'ralmaydi
```

Tasdiqlangach bot javob beradi:

```
✅ Test yaratildi: MS-MATH-2603 (40 savol)
   • Har bir savol default qiyinchilik bilan yaratildi (b = 0.0)
   • Qiyinchilik test ishlangandan keyin avtomatik hisoblanadi
   • Javob qabul qilish: 12.03.2026 09:00 – 13:00
   • Natija: 15.03.2026 10:00
```

### 5.3. `/item 7` javobi (namuna)

```
📊 MS-MATH-2603 · 7-savol

Taqdim etilgan:              130
Javob berganlar:             118   (javobsiz: 12)
To'g'ri javob berganlar:      45   (p = 0.346)

Qiyinchilik (b):            +1.53 ± 0.49   logit
  ├ xom (c₀ = 0):           +0.63
  ├ taxmin tuzatildi:       +1.90
  ├ guruhga moslandi:       +1.75   (θ̄ = +0.15)
  ├ prior:                  +0.90
  └ shrinkaj vazni:          0.74
Holat: provisional (SE katta — ma'lumot hali yetarli emas)
Flag: yo'q

[🔒 Qotirish]  [⚓ Anchor]  [📈 Tarix]
```

`/item` formati `services` da hisoblanadi va **API'dan farq qiladi** — u
admin uchun (kalitni ham, `b` ni ham ko'rsatadi). O'quvchi API'sida bu
ma'lumot **hech qachon** ko'rinmaydi.

## 6. Mini App (Web App) — javoblar varag'i UI

### 6.1. Ekranlar

```
┌─ 1. Navbat (mavjud: index.html "tab-queue") ──────────────┐
│  [ Test kodi: MS-MATH-2603 ]  → «Kodni tekshirish»        │
│  ──────────────────────────────────────────────────────── │
│  Navbatdagi imtihonlar ro'yxati (mavjud)                  │
└───────────────────────────────────────────────────────────┘
              │ kod tasdiqlangan → yangi ekran
              ▼
┌─ 2. JAVOBLAR VARAG'I (yangi: sheet.js) ───────────────────┐
│  ◀ Milliy sertifikat — Matematika, 1-variant        ⏱ 42:13│ ← sticky header
│  ▰▰▰▰▰▰▰▰▱▱▱▱  24/40 belgilangan                          │ ← progress
│  [Savolga o'tish ▾]  [Belgilanmaganlar]                   │
│  ──────────────────────────────────────────────────────── │
│   1   [A] [B] [C] [D]        ← tanlangan variant rangda   │
│   2   [A] [B] [C] [D]                                     │
│   3   [A] [B] [C] [D]                                     │
│  …                                                        │
│  36a  [A] [B] [C] [D]        ← A/B qismli savol           │
│  36b  [A] [B] [C] [D]                                     │
│  37   [A] [B] [C] [D]                                     │
│  ──────────────────────────────────────────────────────── │
│  💾 Saqlandi 12:04:52   [Yakunlash]  [Bekor qilish]        │ ← sticky footer
└───────────────────────────────────────────────────────────┘
```

### 6.2. Kartochka tuzilishi (majburiy talab)

Har bir savol — **grid kartochka**, javoblar `1A2B3C4D` matni **emas**:

```html
<div class="q-card" data-position="1" data-part="">
  <span class="q-num">1</span>
  <div class="opts" role="radiogroup" aria-label="1-savol javobi">
    <button class="opt" data-opt="A" aria-pressed="false">A</button>
    <button class="opt" data-opt="B" aria-pressed="false">B</button>
    <button class="opt" data-opt="C" aria-pressed="false">C</button>
    <button class="opt" data-opt="D" aria-pressed="false">D</button>
  </div>
</div>
```

| Element | Talab |
|---|---|
| Savol raqami | Chap tomonda, katta va aniq (`16px`, `font-weight:600`) |
| Variantlar | 4 ta kvadrat tugma, **min 44×44 px** (barmoq uchun) |
| Tanlangan variant | Fon `var(--tg-theme-button-color)`, matn `--tg-theme-button-text-color`, `aria-pressed="true"` |
| Bosilmagan variant | `--tg-theme-secondary-bg-color`, chegara `1px` |
| Tanlash animatsiyasi | `transform: scale(0.94)` 120 ms + `HapticFeedback.impactOccurred('light')` |
| Javobni bekor qilish | Tanlangan variantni qayta bosish → tozalanadi (`option: null`) |
| A/B qismli savol | `36a` va `36b` — alohida kartochkalar, bir xil `position`, har xil `part` |
| O'ng/o'ngga | `dir="ltr"` (raqamlar), matn o'zbekcha lotin |

### 6.3. Navigatsiya va taraqqiyot

* **Sticky sarlavha:** test nomi + **qolgan vaqt** (`App.formatCountdown`) +
  progress bar (`24/40`).
* **"Savolga o'tish"**: pastdan chiqadigan grid panel (10 tadan qator) —
  har bir katak holati: belgilangan (yashil), belgilanmagan (kulrang),
  joriy (ramka). Katakni bosish → o'sha savolga scroll.
* **"Belgilanmaganlar"** tugmasi — birinchi belgilanmagan savolga o'tadi.
* **Yakunlash** bosilganda: agar belgilanmagan savollar bo'lsa —
  `Bekor qilish / Baribir yakunlash` tasdiqlash oynasi.

### 6.4. Autosave (refresh bo'lsa yo'qolmasligi)

```
[o'quvchi A ni bosdi]
  1. UI darhol yangilanadi (optimistik, kutish yo'q)
  2. localStorage:  sheet:{attempt_id}:{position}:{part} = "A"
  3. 700 ms debounce → PUT /responses  (bir paketda barcha o'zgarganlar)
  4. javob: revision yangilanadi, "💾 Saqlandi HH:MM:SS" ko'rinadi
  5. xato (409) → server `state` olinadi, UI serverga moslashtiriladi, xabar
  6. xato (tarmoq) → navbatga qo'yiladi (mavjud `js/queue.js` uslubi),
     tarmoq kelgach avtomatik qayta yuboriladi (idempotent)
```

| Hodisa | Xulq-atvor |
|---|---|
| Sahifa yangilandi (refresh) | `GET /state` → barcha javoblar tiklanadi + `localStorage` bilan solishtiriladi (server ustun) |
| Telegram'dan chiqib qayta kirdi | `POST /attempts` (idempotent) → mavjud urinish va javoblar qaytdi |
| Ilova fon rejimiga o'tdi | `visibilitychange` → darhol `PUT` (debounce kutilmaydi) |
| Sessiya vaqti tugadi | Footer'da `Javob qabul qilish vaqti tugadi`, tugmalar bloklanadi, "Yakunlash" avtomatik |
| Tarmoq yo'q | Yuqorida "⚠️ Tarmoq yo'q — javoblar qurilmada saqlanmoqda" |

### 6.5. Dizayn va texnik talablar

| Talab | Yechim |
|---|---|
| Mobil uchun zamonaviy UI | Telegram `themeParams` (`--tg-theme-*`), `viewport-fit=cover`, `safe-area-inset` |
| Yorug'/qorong'i rejim | `color-scheme: light dark` (mavjud `style.css` uslubi) |
| Kutish holati | `spinner` (mavjud), skelet yuklash (kartochkalar uchun) |
| Xabarlar | `App.setNotice("success"|"error", …)` (mavjud) |
| Haptik | `HapticFeedback.impactOccurred` — tanlashda `light`, yakunlashda `medium` |
| Kirish imkoniyati | `role="radiogroup"`, `aria-pressed`, klaviatura (`A/B/C/D` tugmalari!) |
| Offline | `js/offline.js` + navbat (mavjud infratuzilma qayta ishlatiladi) |
| Tezlik | Savollar ro'yxati bir marta olinadi; yozish faqat o'zgarganlarni yuboradi |
| Build | **yo'q** — sof HTML/CSS/JS (loyiha konvensiyasi) |

### 6.6. Mavjud frontend bilan integratsiya

`webapp/index.html` ga yangi bo'lim qo'shish emas — **yangi ekran**
(`tab-sheet`) qo'shiladi va `queue.js` dagi `answer-input` (matnli
`1A2B3C4D`) **olib tashlanadi**:

| Mavjud | Yangi |
|---|---|
| `<textarea id="answer-input">` | `<div id="sheet">` — kartochkalar |
| `handleSubmit()` — matnni yuboradi | `handleSubmit()` — `PUT /responses` + `POST /submit` |
| `countAnswered()` — regex bilan sanash | `sheet.answeredCount()` — holatdan sanash |
| `js/queue.js` ichida | yangi `js/sheet.js` (queue.js faqat ro'yxat uchun qoladi) |

Bu **o'quvchi tajribasini butunlay yaxshilaydi**: `1A2B3C4D` yozish xatolari
(`1A2B3C4D` tartibsiz, takroriy raqam, harf tushib qolishi) butunlay
yo'qoladi va **item-level javob** tabiiy ravishda yoziladi.

## 7. MVP uchun minimal API'lar (yakuniy ro'yxat)

### O'quvchi (6 endpoint) — bu **majburiy minimum**

| # | Metod | Yo'l | Vazifasi |
|---|---|---|---|
| 1 | `POST` | `/api/v2/sessions/verify` | Test kodini tekshirish |
| 2 | `POST` | `/api/v2/attempts` | Urinishni boshlash (idempotent) |
| 3 | `PUT` | `/api/v2/attempts/{id}/responses` | **Autosave** (append-only, idempotent) |
| 4 | `GET` | `/api/v2/attempts/{id}/state` | Refresh'dan keyin tiklash |
| 5 | `POST` | `/api/v2/attempts/{id}/submit` | Yakunlash |
| 6 | `GET` | `/api/v2/attempts/{id}/result` | Natija (`result_time` dan keyin) |

### Admin (9 endpoint) — MVP-1

| # | Metod | Yo'l | Vazifasi |
|---|---|---|---|
| 7 | `POST` | `/api/v2/admin/forms` | Forma + kalit + jadval (**`b` yo'q**) |
| 8 | `POST` | `/api/v2/admin/sessions` | Sessiya |
| 9 | `GET` | `/api/v2/admin/items/{id}/statistics` | Item statistikasi |
| 10 | `POST` | `/api/v2/admin/calibration/run` | Kalibrlash |
| 11 | `POST` | `/api/v2/admin/items/{id}/freeze` | `b` ni qotirish |
| 12 | `GET` | `/api/v2/admin/calibration/runs` | Kalibrlash tarixi |
| 13 | `GET` | `/api/v2/admin/audit` | Audit log |
| 14 | `GET` | `/api/v2/admin/export` | CSV eksport |
| 15 | `GET` | `/api/v2/admin/health` | Baza + worker holati |

### Marshrutlarni ulash (mavjud `setup_routes` uslubida)

```python
# web/api_v2.py
def setup_routes(app: web.Application) -> None:
    """`/api/v2/*` marshrutlarini ulaydi (mavjud `web/api.py` uslubi)."""
    router = app.router
    router.add_post("/api/v2/sessions/verify", verify_session)
    router.add_post("/api/v2/attempts", start_attempt)
    router.add_put("/api/v2/attempts/{attempt_id}/responses", save_responses)
    router.add_get("/api/v2/attempts/{attempt_id}/state", attempt_state)
    router.add_post("/api/v2/attempts/{attempt_id}/submit", submit_attempt)
    router.add_get("/api/v2/attempts/{attempt_id}/result", attempt_result)
```

```python
# web/server.py (o'zgarish)
from web import api, api_v2
api.setup_routes(app)      # mavjud /api/*  (o'chirilmaydi)
api_v2.setup_routes(app)   # yangi /api/v2/*
```

### Mavjud API'larning taqdiri

| Mavjud endpoint | Taqdiri |
|---|---|
| `/api/health` | Qoladi |
| `/api/me`, `POST /api/me` | Qoladi |
| `/api/exams` | Qoladi (ro'yxat) — `sessions` jadvalidan o'qiydi |
| `/api/verify-code` | Deprecated → `/api/v2/sessions/verify` |
| `/api/submit` (`1A2B3C4D`) | **Ishlab turadi** (qog'ozdan keyin kiritish uchun zaxira), lekin asosiy oqim emas |
| `/api/results`, `/api/results/{id}` | Qoladi (v2 `result` bilan bir xil hisobot) |
| `/api/offline` | Qoladi |

> **Muhim:** matnli `/api/submit` **o'chirilmaydi** — texnik nosozlik bo'lsa
> o'quvchi javoblarni `1A2B3C4D` ko'rinishida yuborishi mumkin (fallback).
> Bu javoblar `responses` jadvaliga `source = 'bot'`/`'import'` bilan
> item-level bo'lib yoyiladi (`answer_key.parse_submitted()` orqali) — shu
> sababli statistika yo'qolmaydi.

## 8. MVP'da ishga tushirish tartibi (foydalanuvchi nuqtai nazaridan)

```
1. O'qituvchi:  /new_form → test kodi + kalit + jadval   (b YO'Q)
2. O'quvchi:    /start → ism → [📝 Javoblarni belgilash]
3. Mini App:    test kodi → kartochkalar → autosave → Yakunlash
4. Server:      end_time → baholash (θ, SE, scaled)
5. Server:      kalibrlash sikli → har bir savol uchun p, b, SE, flags
6. result_time: natija botga + ilovaga (result_version = 1)
7. O'qituvchi:  /item 7 → b, SE, flags → kerak bo'lsa /freeze
8. Keyingi sessiya: yangi b bilan baholash (aniqroq θ)
```
