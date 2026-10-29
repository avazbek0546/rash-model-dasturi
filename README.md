# 🧮 Rasch modeli (IRT) imtihon platformasi — Telegram Web App

**O'qituvchi boshqaradigan** imtihon platformasi: testni o'qituvchi bot orqali
yaratadi (`/new_exam`), o'quvchilar javoblarini **Telegram Web App (Mini App)** da
topshiradi. Baholash **Rasch modeli (Item Response Theory, 1PL)** asosida
bajariladi — har bir savolning qiyinchiligi (`b`, logit) hisobga olinadi,
o'quvchining bilim darajasi (`θ`, logit) **maksimal ishonchlilik
(MLE / Newton-Raphson)** usulida topilib, **0–100 shkalaga** o'tkaziladi.
Natijalar faqat o'qituvchi belgilagan vaqtda e'lon qilinadi.

* Til: **Python 3.10+** (3.14 da sinovdan o'tgan)
* Kutubxonalar: **aiogram 3.x** + **aiohttp** (Web App serveri — aiogram bilan keladi)
* Baza: **SQLite** (`aiosqlite` — aiogram event loop'ini bloklamaydi)
* Frontend: sof HTML/CSS/JS (Telegram WebApp SDK + Chart.js) — build qadami yo'q
* Ilmiy kutubxona kerak emas: Rasch hisob-kitoblari sof Python `math` da
  bajariladi (numpy/scipy kerak emas)

---

## 📚 Arxitektura hujjatlari (`docs/`)

Keyingi rivojlanish **rejasi** alohida hujjatlar to'plamida yozilgan
(kod hali yozilmagan — bu arxitektura loyihasi):

| Hujjat | Mazmuni |
|---|---|
| [docs/README.md](docs/README.md) | Indeks va asosiy tamoyillar |
| [01-ARXITEKTURA](docs/01-ARXITEKTURA.md) | Komponentlar, oqimlar, xavfsizlik, texnologiya tanlovi |
| [02-DATABASE-SCHEMA](docs/02-DATABASE-SCHEMA.md) | To'liq sxema: 34 jadval (SQLite MVP + PostgreSQL), audit, soft delete |
| [03-QIYINCHILIK-ALGORITMI](docs/03-QIYINCHILIK-ALGORITMI.md) | **`p → b = ln((1−p)/p)`** avtomatik hisoblash, tekislash, shrinkaj, flag'lar |
| [04-API-VA-UI-MVP](docs/04-API-VA-UI-MVP.md) | Minimal API'lar, bot oqimi, kartochkali javoblar varag'i |
| [05-MIGRATSIYA](docs/05-MIGRATSIYA.md) | Bosqichma-bosqich ko'chirish va PostgreSQL'ga o'tish |
| [06-RASCH-KALIBRLASH](docs/06-RASCH-KALIBRLASH.md) | JMLE kalibrlash, anchor items, equating, fit statistikasi |
| [07-ROADMAP](docs/07-ROADMAP.md) | Keyingi 3 oy va keyingi 1 yil yo'l xaritasi |
| [08-PSIKOMETRIK-AUDIT](docs/08-PSIKOMETRIK-AUDIT.md) | **Senior audit**: Critical/High/Medium topilmalar, yetishmayotgan jadvallar, ideal PostgreSQL sxemasi, item lifecycle, professional roadmap |
| [09-RESPONSE-MODEL-V2](docs/09-RESPONSE-MODEL-V2.md) | **Javob saqlash modeli (yakuniy)**: 4 artefakt, uch o'qli status, autosave yo'li, immutability, testlet/LD, psixometrik majburiy maydonlar |
| [10-MVP-PRIORITET-AUDITI](docs/10-MVP-PRIORITET-AUDIT.md) | **MVP / PHASE-2 / FUTURE tasnifi**: 12 element bahosi, 5 natija ro'yxati, murakkablik byudjeti, trigger jadvali |
| [11-FINAL-MVP-DATABASE-MODEL](docs/11-FINAL-MVP-DATABASE-MODEL.md) | **Yakuniy MVP modeli (16 jadval)**: docs/02 tasnifi (M/P2/F/R), REMOVE sabablari, maydonlar lug'ati, Rasch uchun majburiy ma'lumotlar |
| [12-RAILWAY-JOYLASHTIRISH](docs/12-RAILWAY-JOYLASHTIRISH.md) | **Bulutga joylashtirish (Railway Hobby $5)**: volume, port/domen avtomatikasi, healthcheck, xatolar jadvali |

**Hujjatlardagi uchta muhim qoida:**

1. **Savollar bazaga yuklanmaydi** — faqat pozitsiya (`position`, `part`),
   javob kaliti va metadata saqlanadi.
2. **O'qituvchi `b`/logit/Rasch parametrlarini kiritmaydi** — faqat test kodi,
   javob kaliti va test metadata. Qolgan statistikani tizim hisoblaydi.
3. **Har bir savol default holatda yaratiladi** (`b = 0.0`) va test
   ishlangandan keyin qiyinchilik **avtomatik** hisoblanadi; yetarli ma'lumot
   yig'ilgach (`N ≥ 200`) modul **to'liq Rasch kalibrlash** bilan almashtiriladi.

---

## 📁 Loyiha strukturasi

```
Rash model dasturi/
│
├── main.py                  # bot + Web App server + baholash fon vazifasi (bitta jarayonda)
├── config.py                # barcha sozlamalar (.env dan o'qiladi)
├── texts.py                 # botning barcha matnlari (o'zbekcha, HTML)
├── states.py                # FSM holatlari (/new_exam ustasi uchun ExamCreateStates)
├── requirements.txt         # kerakli kutubxonalar
├── .env.example             # sozlamalar namunasi (nusxa olib .env yaratiladi)
│
├── docs/                    #  arxitektura hujjatlari (yangi tizim rejasi)
│   ├── README.md            #   hujjatlar indeksi va asosiy tamoyillar
│   ├── 01-ARXITEKTURA.md    #   komponentlar, oqimlar, xavfsizlik, stack
│   ├── 02-DATABASE-SCHEMA.md#   to'liq sxema (SQLite + PostgreSQL)
│   ├── 03-QIYINCHILIK-ALGORITMI.md  # p → b avtomatik hisoblash
│   ├── 04-API-VA-UI-MVP.md  #   MVP API'lari + Mini App javoblar varag'i
│   ├── 05-MIGRATSIYA.md     #   migratsiya va PostgreSQL'ga o'tish rejasi
│   ├── 06-RASCH-KALIBRLASH.md   # JMLE, anchor items, equating
│   └── 07-ROADMAP.md        #   3 oylik va 1 yillik yo'l xaritasi
│
├── database/                #  ma'lumotlar bazasi qatlami
│   ├── db.py                #   SQLite ulanishi + jadval sxemasi (Database)
│   ├── models.py            #   domen modellari (User, Exam, ExamSubmission, Solution, ...)
│   ├── repository.py        #   CRUD (User/Question/Result/Exam/ExamAnswer/SolutionRepository)
│   └── seed.py              #   eski "mashq rejimi" savollari (arxiv oqimi uchun)
│
├── services/                #  biznes-logika (Telegram'ga bog'liq emas)
│   ├── rasch.py             #   Rasch modeli: MLE, Newton-Raphson, 0–100 shkala, izohlar
│   ├── answer_key.py        #   "1A2B3C" kaliti va o'quvchi javoblarini tahlil qilish
│   ├── exam_service.py      #   imtihon holati, vaqt konvertatsiyasi, kiritish tekshiruvi
│   ├── grading.py           #   Rasch baholash + fon vazifasi (grading_loop)
│   ├── solutions.py         #   🔍 tahlil: tugma belgilari, sahifalash, izoh tahlili, hashtag
│   ├── webapp_auth.py       #   Telegram initData (HMAC-SHA256) tekshiruvi
│   └── test_session.py      #   eski mashq rejimi sessiyalari (arxiv)
│
├── web/                     # 🌐 Web App HTTP qatlami (aiohttp)
│   ├── server.py            #   ilova (static + marshrutlar) va serverni ishga tushirish
│   └── api.py               #   /api/* endpoint'lari (JSON)
│
├── webapp/                  # 📱 Mini App (frontend, build talab qilmaydi)
│   ├── index.html           #   4 tabli SPA (Navbat / Natijalar / Offline / Profil)
│   ├── css/style.css        #   Telegram themeParams ga moslashgan uslublar
│   └── js/                  #   api.js, queue.js, results.js, offline.js, profile.js, app.js
│
├── assets/                  # 📄 PDF hisobot resurslari
│   └── fonts/               #   DejaVu shrifti — PDF Windows/Linux'da bir xil chiqadi
│       ├── DejaVuSans.ttf   #     Unicode shrift (o', g', kirill harflari)
│       └── LICENSE-DejaVu.txt  #   shrift litsenziyasi (qayta tarqatishga ruxsat)
│
├── handlers/                # 🤖 Telegram handler'lari
│   ├── __init__.py          #   router'larni ulash (setup_routers) + LEGACY_MODULES
│   ├── access.py            #   admin (o'qituvchi) huquqini tekshirish
│   ├── start.py             #   /start, /help, inline menyu, Web App tugmasi
│   ├── webapp.py            #   /app — ilovani ochish
│   ├── admin_exam.py        #   /new_exam ustasi (8 qadam) + /cancel
│   ├── admin.py             #   /stats, /exams va imtihonlarni o'chirish
│   ├── admin_solution.py    #   /add_solution — video/rasm yechim yuklash (admin)
│   ├── analysis.py          #   🔍 Test tahlili — savollar gridi va yechimlar (o'quvchi)
│   ├── fallback.py          #   boshqa xabarlar (ENG OXIRGI router)
│   │
│   ├── test.py              #   ⚠️ ARXIV: eski chatdagi test oqimi (router'ga ulanmaydi)
│   ├── results.py           #   ⚠️ ARXIV: eski /results
│   └── about.py             #   ⚠️ ARXIV: eski /about
│
├── keyboards/
│   ├── inline.py            # Inline klaviaturalar (Web App menyusi, admin va tahlil tugmalari)
│   └── reply.py             # Eski reply menyu matnlari (moslik uchun; endi ishlatilmaydi)
│
├── middlewares/
│   └── user_sync.py         # foydalanuvchini bazaga yozib boradi
│
└── tests/                   # ✅ tekshiruv testlari (pytest kerak emas)
    ├── test_rasch.py        #   model matematikasi (10 test)
    ├── test_answer_key.py   #   kalit formatlari + Rasch kengaytmasi
    ├── test_exam_flow.py    #   sxema → repository → hayot sikli → baholash
    ├── test_solutions.py    #   🔍 Test tahlili: solutions jadvali, izoh tahlili, sahifalash
    ├── test_webapp_auth.py  #   initData imzosi va muddati
    ├── test_api.py          #   /api/* endpoint'lari (aiohttp test client)
    ├── test_flow.py         #   eski mashq rejimi + router/klaviatura tekshiruvlari
    └── test_bot_flow.py     #   botning TO'LIQ oqimi (Telegram'siz, soxta session)
```

---

## ⚙️ O'rnatish

**1. Kutubxonalarni o'rnatish**

```powershell
python -m pip install -r requirements.txt
```

**2. Sozlamalar faylini yaratish**

```powershell
copy .env.example .env
```

`.env` faylini ochib, qiymatlarni to'ldiring:

| O'zgaruvchi | Majburiy | Tavsif |
|---|---|---|
| `BOT_TOKEN` | ✅ | @BotFather dan olingan token |
| `ADMIN_ID` | ✅ | O'qituvchining Telegram ID si (`/new_exam`, `/exams`, `/stats`) |
| `ADMIN_IDS` | ➖ | Qo'shimcha adminlar (vergul bilan: `111,222`). Bot ichida `/admins` paneli orqali ham qo'shish mumkin |
| `WEBAPP_URL` | ✅* | Mini App HTTPS manzili (Railway'da domen avtomatik olinadi) |
| `WEBAPP_HOST` | ➖ | Server manzili (default: `127.0.0.1`; bulutda avtomatik `0.0.0.0`) |
| `WEBAPP_PORT` | ➖ | Server porti (default: `8080`; Railway'da `PORT` ustun turadi) |
| `WEBAPP_DEV_MODE` | ➖ | `1` — brauzerda `?debug_user_id=…` bilan sinash (prod'da `0`!) |
| `INITDATA_MAX_AGE` | ➖ | `initData` amal qilish muddati, sekund (default: `86400`) |
| `TIMEZONE` | ➖ | O'qituvchi vaqtni shu zonada kiritadi (default: `Asia/Tashkent`) |
| `GRADING_INTERVAL` | ➖ | Baholash fon vazifasi davri, sekund (default: `30`) |
| `MIN_TEST_CODE_LENGTH` | ➖ | Test kodi minimal uzunligi (default: `4`) |
| `DB_PATH` | ➖ | Baza fayli (default: `data/math_bot.db`; Railway volume'ida avtomatik `<volume>/math_bot.db`) |
| `THETA_BOUND` | ➖ | θ qidiruv chegarasi (default: `3.0` → `-3…+3` logit) |
| `LOG_LEVEL` | ➖ | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

\* `WEBAPP_URL` bo'sh bo'lsa ham server ishlaydi, lekin bot Web App tugmasini
ko'rsatmaydi (faqat API'ni lokal sinash mumkin).

**Bot tokenini olish:** Telegram'da [@BotFather](https://t.me/BotFather) →
`/newbot` → nom va username → tokenni `.env` ga yozing.
Telegram ID ingizni bilish uchun [@userinfobot](https://t.me/userinfobot) dan foydalaning.

**HTTPS manzil (Web App uchun majburiy).** Telegram Mini App'ni faqat HTTPS
sahifada ochadi. Ikki yo'l bor:

```powershell
# A) Ishlab chiqish uchun — Cloudflare Tunnel (tez va bepul)
cloudflared tunnel --url http://localhost:8080
#    chiqqan manzilni .env ga yozing:  WEBAPP_URL=https://xxxx.trycloudflare.com

# B) Doimiy domen (server/VPS) — nginx + Let's Encrypt sertifikati
#    WEBAPP_URL=https://exam.example.uz
```

> ⚠️ `WEBAPP_URL` manzili Telegram'ga aynan shu ko'rinishda yuboriladi va
> `initData` imzosi shu bot tokeni bilan tekshiriladi — domenni o'zgartirsangiz
> `.env` ni ham yangilang.

**3. Platformani ishga tushirish**

```powershell
python main.py
```

Bitta jarayonda uchta vazifa ko'tariladi:

1. **bot** (long polling) — o'qituvchi paneli va Web App tugmasi;
2. **Web App server** (`http://127.0.0.1:8080`) — Mini App va `/api/*`;
3. **baholash fon vazifasi** — muddati tugagan imtihonlarni Rasch bo'yicha baholaydi.

Birinchi ishga tushirishda `data/math_bot.db` avtomatik yaratiladi va yangi
`exams` / `user_answers` jadvallari qo'shiladi (mavjud baza buzilmaydi).
To'xtatish: `Ctrl + C`.

**4. Bulutga joylashtirish (Railway, Hobby $5/oy)**

Kod bulutga tayyor: `railway.json` (start buyrug'i, healthcheck, restart
siyosati), `.python-version` (Python 3.12) va `config.py` dagi avtomatik
aniqlash. Railway'da faqat quyidagilar qo'lda bajariladi:

1. **New Project → Deploy from GitHub repo** (`rash-model-dasturi`).
2. **Settings → Volumes → Add Volume**, mount path: `/data` (baza saqlanishi uchun).
3. **Variables**: `BOT_TOKEN`, `ADMIN_ID`, `WEBAPP_DEV_MODE=0`
   (`PORT`, `WEBAPP_HOST`, `WEBAPP_URL`, `DB_PATH` avtomatik olinadi).
4. **Settings → Networking → Generate Domain** (HTTPS domen).
5. Replicas `1`, Serverless/App Sleeping `OFF`.

To'liq yo'riqnoma, tekshirish ro'yxati va xatolar jadvali:
[docs/12-RAILWAY-JOYLASHTIRISH.md](docs/12-RAILWAY-JOYLASHTIRISH.md).

---

## 🤖 Botdan foydalanish

### O'quvchi uchun

| Komanda / tugma | Vazifasi |
|---|---|
| `/start` | Birinchi kirishda **ism va familiya** so'raladi; saqlangach **bitta inline menyu** ochiladi (pastdagi reply klaviatura ishlatilmaydi) |
| 📝 Javoblarni belgilash / `/app` | **Birinchi tugma:** Mini App'ni ochadi (Navbat, Natijalar, Offline, Profil) |
| 🔍 Test tahlili / `/tahlil` | Inline tugma: topshirilgan imtihonlarning savol-savol tahlili va video/rasm yechimlari |
| 🏡 Asosiy menyu | Inline tugma: asosiy menyuni yangilaydi (har bir bo'limdan qaytish uchun) |
| `/help` | Komandalar ro'yxati |

### O'qituvchi (admin) uchun

| Komanda | Vazifasi |
|---|---|
| `/new_exam` | Yangi imtihon yaratish ustasi (8 qadam, tugmalar bilan) |
| `/exams` | Imtihonlar ro'yxati; «🗑» tugmasi bilan o'chirish (javoblar ham o'chadi) |
| `/stats` | O'quvchilar, imtihonlar, qabul qilingan javoblar va yechimlar statistikasi |
| `/add_solution` | Video yoki rasm yechim yuklash yo'riqnomasi (quyida) |
| `/admins` | Adminlarni boshqarish: «➕ Admin qo'shish» (odamning xabarini **forward** qilish kifoya), «🗑» bilan o'chirish |
| `/cancel` | Ustani istalgan qadamda bekor qilish |

### 🔍 «Test tahlili» bo'limi (o'quvchi)

Natijasi **e'lon qilingan** va o'quvchi **javob yuborgan** imtihonlar tahlil
qilinadi. Zanjir: imtihonlar ro'yxati → savollar gridi → tanlangan savolning
yechimi.

1. **Imtihonlar ro'yxati.** Tugma matni:

   ```
   📊 RASH EXAM 12-fevral tahlili
   ```

   Sana imtihon boshlanish vaqtidan olinadi (mahalliy zona). Ortiqcha imtihonlar
   sahifalanadi: `Sahifa 1/2 (jami: 7 ta test)` + «⬅️ Oldingi», «Keyingi ➡️» va
   «🏡 Asosiy menyu» tugmalari.

2. **Savollar gridi** (bir qatorda 5 ta tugma). Har bir tugma o'quvchining shu
   savolga bergan javobini ko'rsatadi:

   | Tugma | Ma'nosi |
   |---|---|
   | `✅ 1`, `✅ 2` | to'g'ri javob berilgan savollar |
   | `❌ 3`, `❌ 8` | noto'g'ri javob berilgan (yoki javobsiz) savollar |
   | `✅ 36a`, `❌ 36b` | A/B qismli savollar (qismlar alohida tugma) |

   Klaviatura ostida doim «⬅️ Testlar ro'yxati» va «🏡 Asosiy menyu» turadi.

3. **Savol yechimi.** Savol tugmasi bosilganda bazadan shu savolning yechimi
   yuboriladi — **video yoki rasm** (`file_id`). Matnli yechim qo'llanmaydi.
   Post oxiriga hashtag qo'shiladi:

   ```
   #javob-rashtest1612-3        # 3-savol
   #javob-rashtest1612-36a      # 36-savolning «a» qismi
   ```

   Yechim yuklanmagan bo'lsa — ogohlantirish ko'rsatiladi (tugma ishlashda
   davom etadi).

### 🎬 Video va rasm yechimlarni yuklash (o'qituvchi)

Yechim faqat **video** yoki **rasm** bo'ladi — matnli yechim qo'llanmaydi
(audio, animatsiya va dumaloq video ham qabul qilinmaydi).

Eng sodda oqim — **video/rasm yuborib, izohiga kod va savol raqamini yozish**:

1. Admin botga videoni (yoki rasmni) yuboradi;
2. izoh (caption) sifatida test kodi va savol raqami yoziladi:

   ```
   rashtest1612 3      #rashtest1612-3      rashtest1612 36a
   ```

3. bot faylning Telegram `file_id` sini olib, bazadagi tegishli imtihon va savol
   raqamiga biriktiradi va shu javobni qaytaradi:

   ```
   ✅ RASHTEST1612 ning 3-savoliga video yechim muvaffaqiyatli saqlandi!
   ```

   Bir xil savolga qayta yuklansa, eski yozuv **yangilanadi** (dublikat bo'lmaydi).
   Rasm/video «fayl sifatida» yuborilsa ham qabul qilinadi (`document` turi).

**Hajm chegaralari (Telegram Bot API):** video — **50 MB** gacha (720p tavsiya
etiladi), rasm — **10 MB** gacha. Chegaradan katta fayl saqlanadi, lekin
o'qituvchi ogohlantiriladi (o'quvchida ochilmasa — 720p qilib qayta yuklash
kerak).

#### 🎬 «Yechimlar» paneli (Mini App) — qamrov va tez yuklash

Mini App'dagi **«⚙️ Test yaratish»** tabida har bir imtihon yonida
**«🎬 Yechim»** tugmasi bor. U:

* **qamrovni** ko'rsatadi — `12 / 45 (27%)` va savollar to'ri
  (`🎬 1`, `🖼 3`, `⬜ 4`): yashil = yechim bor, kulrang = yo'q;
  **«⬜ Yetishmayotganlar»** filtri bilan bo'sh savollarni tez topasiz;
* savol oynasida **holatni** ko'rsatadi (video/rasm yuklangan yoki yo'q);
* yechimni **o'chirish** (`🗑`);
* **«🎬 Video yoki 🖼 rasm yuklash»** — Telegram deep-link
  (`/start s_<kod>_<savol>`) orqali botga o'tadi: bot qaysi savolga
  yuklanishni **eslab qoladi**, shuning uchun videoni/rasmni **izohsiz**
  yuborish kifoya. Izohli oqim ham ishlashda davom etadi.

> Media fayllar (`video`/rasm) faqat **bot orqali** yuklanadi — Telegram
> `file_id` faqat fayl bot orqali o'tganda olinadi. Panel esa ko'rish va
> boshqarish uchun (qamrov, holat, o'chirish, deep-link). Matnli yechim
> butunlay olib tashlangan.

### `/new_exam` ustasi qadamlari

| # | So'raladi | Izoh |
|---|---|---|
| 1 | Imtihon nomi | masalan `Matematika — 1-bosqich` |
| 2 | Test kodi | kamida 4 belgi (harf/raqam), **unikal** bo'lishi shart |
| 3 | Savollar soni | 1–100 |
| 4 | Javoblar kaliti | `1A2B3C…` (bo'sh joy/vergul ham mumkin; savollar soniga teng bo'lishi shart) |
| 5 | Qiyinchilik logitlari | bo'sh yoki `-` → barcha savol uchun `0.0`; bitta son → hammasiga; yoki savollar sonicha qiymat |
| 6 | Boshlanish vaqti | `15.01.2026 09:00` (mahalliy vaqt) |
| 7 | Tugash vaqti | boshlanishdan keyin |
| 8 | Natija vaqti | tugashdan keyin (natijalar shu paytda oshkor bo'ladi) |

Oxirida xulosa ko'rsatiladi va **✅ Yaratish** bosilganda imtihon bazaga
yoziladi. Keyin o'qituvchi test kodini o'quvchilarga yetkazadi.

---

## 🌐 Web App (Mini App)

O'quvchi `/app` tugmasi orqali ilovani ochadi. Pastda 4 tab:

| Tab | Nima bor |
|---|---|
| **Navbat** | Test kodini kiritish, javoblar varag'i (`1A2B3C…`), faol/kutilayotgan imtihonlar ro'yxati va taymer |
| **Natijalar** | Natijalar dinamikasi (Chart.js grafigi), o'tgan imtihonlar tarixi va har biri uchun batafsil tahlil (savol-savol, `P(θ)`, SE, 95% interval) |
| **Offline imtihon** | Hududlar bo'yicha imtihonlar (statik ro'yxat — kelajak uchun tayyor joy) |
| **Profil** | Ism-familiyani tahrirlash, Telegram ID, ishlangan testlar soni, vaqt zonasi |
| **⚙️ Test yaratish** | **Faqat admin** uchun: imtihon yaratish ustasi + har bir imtihon yonida **«🎬 Yechim»** paneli (qamrov, video/rasm holati, o'chirish, botga deep-link). Uchta amal tugmasi (yechim, PDF, baholash) tor ekranda ham to'liq sig'adi |

### Javoblar qanday topshiriladi

1. O'quvchi test kodini kiritadi → server kodni tekshiradi (`POST /api/verify-code`);
2. faol oyna ichida javoblar varag'ini yuboradi (`POST /api/submit`), masalan
   `1A2B3C4D` yoki `1A 2B 3C` (ajratuvchi belgilar tashlab yuboriladi):
   * kod topilmasa → `404`; oyna hali boshlanmagan yoki tugagan → `403`;
   * takroriy yuborish → `409` (har bir imtihonga javob **bir marta** yuboriladi);
   * yetishmagan javoblar `X` (noto'g'ri) hisoblanadi;
   * muvaffaqiyatli yuborilgach **bot chatiga qisqa xabar** keladi: bitta
     sarlavha («✅ Javoblaringiz qabul qilindi») va har bir savol **alohida
     qatorda** — `1 ✅`, `2 ❌`, … (javobsiz ham ❌), «📊 Natijalar» tugmasi
     bilan. Boshqa matn yo'q: **to'g'ri javob varianti, θ va ball
     ko'rsatilmaydi** — ular `result_time` gacha yopiq (`services/feedback.py`);
3. `end_time` da qabul to'xtaydi va **θ hisoblanadi**, ammo natija `result_time`
   gacha yopiq turadi;
4. `result_time` da **natija bildirishnomasi** fon vazifasi
   (`notify.result_notification_loop`) har bir o'quvchiga bir marta boy kartani
   yuboradi: 0–100 ball, sertifikat darajasi, θ, 95% ishonch oralig'i va
   «📊 Batafsil tahlil» / «🔍 Savollar tahlili» tugmalari. Xabar
   `user_answers.notified_at` bilan belgilanadi (dublikat ketmaydi).

### API endpoint'lari

| Metod | Manzil | Vazifa |
|---|---|---|
| `GET` | `/api/health` | Server tirikligi (autentifikatsiyasiz) |
| `GET` / `POST` | `/api/me` | Profilni o'qish / ism-familiyani tahrirlash |
| `GET` | `/api/exams` | Navbat: faol/kutilayotgan/tugagan imtihonlar |
| `POST` | `/api/verify-code` | Test kodini tekshirish (`{test_code}`) |
| `POST` | `/api/submit` | Javoblarni yuborish (`{test_code, answers}`) |
| `GET` | `/api/results` | Natijalar tarixi + grafik ma'lumotlari |
| `GET` | `/api/results/{exam_id}` | Bitta imtihon bo'yicha batafsil hisobot |
| `GET` | `/api/offline` | Hududiy imtihonlar (statik) |
| `GET` | `/api/v2/me` | Profil + `is_admin` (admin panelini ko'rsatish uchun) |
| `GET` | `/api/v2/admin/exams` | Imtihonlar ro'yxati + **yechim qamrovi** (faqat admin) |
| `GET` | `/api/v2/admin/exams/{id}/solutions` | «🎬 Yechimlar» qamrovi: savollar, tur, `missing[]`, `bot_username` |
| `POST` | `/api/v2/admin/solutions/delete` | Bitta savol yechimini o'chirish |

> Yechim faqat **video yoki rasm** (`file_id`) bo'ladi va faqat **bot orqali**
> yuklanadi — `file_id` ni Telegram Bot API beradi. Matnli yechim endpoint'i
> olib tashlangan.

### Xavfsizlik

* Har bir so'rov `X-Init-Data` header'idagi Telegram `initData` bilan keladi va
  server uni **HMAC-SHA256** bilan tekshiradi
  (`secret = HMAC("WebAppData", bot_token)`) — boshqa odam nomidan so'rov
  yuborib bo'lmaydi. `auth_date` eskirgan bo'lsa (`INITDATA_MAX_AGE`) rad etiladi.
* `answer_key` va `difficulty_logits` **hech qachon** brauzerga yuborilmaydi;
  baholash to'liq serverda bajariladi. Savollar kaliti faqat `result_time` dan
  keyin hisobotda ko'rinadi.
* `WEBAPP_DEV_MODE=1` faqat lokal sinov uchun (`X-Debug-User-Id` header'i);
  ishlab chiqarishda **albatta `0`**.

---

##  Rasch modeli qanday ishlaydi

### Model

Har bir o'quvchining **bilim darajasi** `θ` (theta, logit) va har bir savolning
**qiyinchiligi** `b` (logit) bitta umumiy o'lchovda ifodalanadi:

```
P(θ) = 1 / (1 + exp(−(θ − b)))          ← to'g'ri javob berish ehtimoli
```

* `θ = b` → ehtimol aynan **50%**;
* `θ > b` → ehtimol 1 ga yaqin (savol o'quvchi uchun oson);
* `θ < b` → ehtimol 0 ga yaqin (savol qiyin).

### θ ni topish (MLE + Newton-Raphson)

`u_j ∈ {0, 1}` (to'g'ri/xato) bo'lganda:

```
ln L(θ)   = Σ [ u_j·ln P_j + (1 − u_j)·ln(1 − P_j) ]
ln L'(θ)  = Σ (u_j − P_j)                    ← gradient
ln L''(θ) = −Σ P_j(1 − P_j) = −I(θ)          ← Fisher informatsiyasi

θ_(k+1) = θ_k + [Σ (u_j − P_j)] / [Σ P_j(1 − P_j)]      ← iteratsiya
SE(θ)   = 1 / sqrt( Σ P_j(1 − P_j) )                     ← standart xato
```

Koddagi cheklovlar va nozik joylar:

* **Chekka holatlar:** barcha javob to'g'ri (yoki barchasi xato) bo'lsa MLE
  cheksizlikka intiladi — bunday holatda `θ = ±THETA_BOUND`, `SE = None` va
  `is_extreme = True` bo'ladi (o'quvchiga izoh bilan ko'rsatiladi).
* **Qadam nazorati:** log-likelihood kamayib ketmasligi uchun qadam ikki marta
  kichraytiriladi (step-halving), `θ` esa `[−THETA_BOUND, +THETA_BOUND]`
  oralig'iga siqiladi.
* **Boshlang'ich nuqta:** `θ = ln[(u + 0.5) / (n − u + 0.5)]` — xom ball
  logit'i, shu sababli odatda 5–8 iteratsiyada yaqinlashadi.

### 0–100 shkalaga o'tkazish

```
ball = 100 · (θ − (−THETA_BOUND)) / (2·THETA_BOUND)
```

ya'ni `−3 logit → 0 ball`, `0 → 50 ball`, `+3 → 100 ball`
(natija `[0, 100]` oralig'iga siqiladi). Har bir `SE` shkaladagi
"±N ball" aniqlikka o'giriladi.

### Nega bu "7/10 = 70%" dan yaxshiroq?

Rasch modelida xom ball — **bir xil savollar to'plami uchun** — `θ` uchun
*yetarli statistika*, ya'ni bir xil 10 savolda bir xil sonda to'g'ri javob
bergan ikki o'quvchi bir xil `θ` oladi. Farq **turli to'plamlarda** ko'rinadi:

| Savollar to'plami | Xom ball | θ | 0–100 ball |
|---|---|---|---|
| Oson to'plam (`b ≈ −2.5 … −0.7`) | 5 / 10 | **−1.60** | 23 |
| Qiyin to'plam (`b ≈ +0.5 … +2.3`) | 5 / 10 | **+1.40** | 73 |

Bu raqamlar `tests/test_rasch.py` dagi test bilan tasdiqlangan: bir xil "5/10"
natija savollar qiyinligiga qarab **butunlay boshqa ma'no** beradi. Qo'shimcha
ustunlik: har bir baho `SE` (aniqlik) va ishonch oralig'i bilan keladi.

> ⚠️ **Halol izoh:** bu loyihada `b` qiymatlari o'qituvchi tomonidan oldindan
> belgilangan (muallif bahosi). To'liq rasmiy IRT tahlilida `b` parametrlari
> katta guruh javoblari asosida statistik baholanadi (**calibration**) — bu
> "Keyingi qadamlar" bo'limida.

---

## 🎯 Qiyinchilik (logit) qiymatlarini tanlash

**Diqqat:** yangi platformada savollar matni bazada saqlanmaydi — o'quvchilar
javoblarni qog'oz variantdan ilovaga **javoblar varag'i** sifatida kiritadi
(`1A2B3C…`). Imtihon uchun faqat **javoblar kaliti** va **savollar
qiyinchiligi (logit)** ma'lum bo'lishi kerak.

### `b` qiymatini qanday tanlash kerak

| `b` qiymati | Ma'nosi | Taxminiy to'g'ri javob foizi |
|---|---|---|
| `−2.5 … −1.5` | juda oson | 90–95% |
| `−1.5 … −0.5` | oson | 75–90% |
| `−0.5 … +0.5` | o'rtacha (markaziy) | 40–75% |
| `+0.5 … +1.5` | qiyin | 15–40% |
| `+1.5 … +2.5` | juda qiyin | 5–15% |

`b` qiymatlari **markazlashtirilgan** bo'lishi foydali: testdagi savollar
o'quvchilarning haqiqiy darajasiga yaqin bo'lsa, `θ` aniqroq o'lchanadi
(SE kichrayadi).

### Ikkita amaliy yo'l

1. **Tez yo'l:** `/new_exam` ustarisida logitlar so'ralganda `-` (yoki bo'sh)
   yuboring — barcha savollar uchun `0.0` qabul qilinadi. Bu holda barcha
   savollar "bir xil qiyinchilikda" hisoblanadi.
2. **Aniq yo'l:** savollar qiyinchiligini oldindan baholang (oldingi yillarning
   natijalari yoki ekspert bahosi) va `-1.2, 0, 0.5, 1.4 …` ko'rinishida
   kiriting — qiymatlar soni savollar soniga teng bo'lishi kerak.

> ℹ️ Imtihondan keyin haqiqiy javoblar statistikasi asosida `b` larni qayta
> baholash (**calibration**) mumkin — bu "Keyingi qadamlar" bo'limida.

### Eski "mashq rejimi" (arxiv)

Loyihaning birinchi versiyasida botning o'zi chatda savol berardi
(`handlers/test.py`, `services/test_session.py`, `questions` / `test_results`
jadvallari, `database/seed.py` dagi 20 ta savol). Ular **arxivga o'tkazildi**:
fayllar va jadval o'chirilmagan, lekin router'ga ulanmaydi va menyuda
ko'rinmaydi (`handlers/__init__.py` dagi `LEGACY_MODULES`). Kerak bo'lsa,
`tests/test_flow.py` eski kodning ishlashini tekshirib turadi.

---

## ✅ Tekshiruv testlari

Testlar `pytest` talab qilmaydi, oddiy `python` bilan ishlaydi:

```powershell
python tests/test_rasch.py        # model matematikasi (10 test)
python tests/test_answer_key.py   # kalit formatlari + Rasch kengaytmasi
python tests/test_exam_flow.py    # sxema → repository → hayot sikli → baholash
python tests/test_solutions.py    # 🔍 Test tahlili: solutions jadvali, izoh, sahifalash
python tests/test_webapp_auth.py  # initData imzosi, muddati, buzuq holatlar
python tests/test_api.py          # /api/* (aiohttp test client, tarmoqsiz)
python tests/test_code_error_ux.py # noto'g'ri kod → aniq xato xabari (JS ulanish + API)
python tests/test_result_notify.py # qabul xabari + result_time natijasi (kalitsiz)
python tests/test_submission_feedback.py # yakunlashdan keyingi ✅/❌ (kalit/θ oshkor emas)
python tests/test_admin_api.py    # /api/v2/me + /api/v2/admin/* (yechimlar paneli)
python tests/test_flow.py         # eski mashq rejimi + router/klaviatura
python tests/test_bot_flow.py     # botning TO'LIQ oqimi (Telegram'siz)
```

**`test_rasch.py`** — model matematikasi:

* logistik funksiya xossalari (`P(b) = 0.5`, simmetriya, monotonlik);
* MLE analitik yechimi — `b = 0` bo'lgan 10 savolda `5/10` → `θ = 0`,
  `SE = 1/√2.5 = 0.6325` (qo'lda hisoblangan qiymat);
* xom ball monotonligi, yetarli statistika xossasi;
* bir xil `5/10` turli to'plamlarda → `θ = −1.60` va `θ = +1.40`;
* chekka holatlar (`0/10`, `10/10` → `θ = ±3.0`, `SE` yo'q);
* `θ → 0..100` shkala va teskari o'tkazish.

**`test_answer_key.py`** — kalit va javoblar formatlari (`1A2B3C`, `1A 2B 3C`,
`1:A, 2:B`, `ABCD`), noto'g'ri kiritishlarning rad etilishi, hamda yangi
`rasch.estimate_from_letters()` natijasining eski yo'l bilan **aynan bir xil**
bo'lishi. Shu bilan birga **mustaqil tekshiruv**: Newton-Raphson natijasi
`[−3, +3]` oralig'idagi 60 001 nuqtali to'g'ridan-to'g'ri (brute-force) qidiruv
bilan solishtiriladi:

```
[OK] Mustaqil tekshiruv: Newton-Raphson θ = +0.9035 ≈ to'r bo'yicha θ = +0.9035
```

**`test_exam_flow.py`** — vaqtinchalik SQLite faylida butun hayot sikli:
jadvallar/ustunlar, vaqt konvertatsiyasi (mahalliy ↔ UTC), `upcoming → active →
closed → published` holatlari, javob yuborish va takroriy yuborishning rad
etilishi, `end_time` dan keyin Rasch baholash (θ, SE, 0–100), `result_time`
gacha natijaning yopiq turishi, "Navbat" ro'yxati va CASCADE o'chirish.

**`test_api.py`** — HTTP qatlami `aiohttp.test_utils.TestClient` bilan: har bir
endpoint, autentifikatsiya (401 holatlari), kalitning oshkor bo'lmasligi,
`404/403/409` javoblari, natijaning `result_time` da ochilishi va statik
fayllarning berilishi.

**`test_bot_flow.py`** — **eng muhim test**: `Bot.session` soxta (tarmoqsiz)
session bilan almashtiriladi va haqiqiy `Update` obyektlari
`Dispatcher.feed_update()` orqali uzatiladi. Shunday qilib botning butun
zanjiri haqiqiy kod bo'ylab ishlaydi: `/start` (Web App tugmasi) → yordam
tugmasi → `/app`, `/help`, `/stats`, `/exams`, fallback va ruxsat nazorati →
`/new_exam` ustasining 8 qadami (xato kiritishlar bilan) → tasdiqlash va
imtihonning bazaga yozilishi → ro'yxat va o'chirish:

```
[OK] /start: Web App tugmasi (https://exam.example.uz/) + admin tugmalari
[OK] Usta: 8 qadam o'tdi, xulosa va tasdiqlash tugmalari ko'rsatildi
[OK] Imtihon bazaga yozildi: id=1, kod=MATH2026, logitlar=[0.0, 0.0, 0.0]
Jami 32 ta soxta Telegram API chaqiruvi — xatosiz ✅
```

Bu test `tg_user.user_id` ↔ `tg_user.id` kabi atribut xatolarini ham ushlaydi
(aiogram'ning `User` obyektida maydon `.id`, bizning `database.models.User` da esa
`.user_id`).

**`test_solutions.py`** — «🔍 Test tahlili» va yechimlar (tarmoqsiz):

* `solutions` jadvali (`solution_file_id`, `solution_type`, `part`) va
  `Solution`/`SolutionType` modellari — matnli yechim yo'q (`file_id` majburiy);
* admin izohini tahlil qilish: `rashtest1612 3`, `#rashtest1612-3`,
  `rashtest1612 36a`, `#javob-rashtest1612-3b` (+ noto'g'ri formatlar rad etiladi);
* repository: `upsert` dublikat yaratmaydi (qayta yuklashda yangilanadi),
  faylsiz yechimni rad etadi, A/B qismlar, o'chirish va `CASCADE`;
* tugma belgilari (`✅ 1`, `❌ 3`, `✅ 36a`, `❌ 36b`), hashtag va Inline Grid
  qatorlari (`grid_pattern`);
* sahifalash: `Sahifa 1/2 (jami: 7 ta test)` va sahifa chegaralari;
* imtihon tugmasi matni: `📊 RASH EXAM 12-fevral tahlili`;
* ro'yxatga faqat javob yuborilgan va natijasi e'lon qilingan imtihonlar tushishi.

`test_bot_flow.py` shuningdek «🔍 Test tahlili» oqimini ham tekshiradi:
inline menyu (reply klaviatura yo'q) → imtihon → savollar gridi → adminning
**video va rasm** yuklashi →
`#javob-rashtest1612-3` hashtagi bilan yuborilishi → matnli yechim va
qo'llanmaydigan media (audio) rad etilishi → sahifalash va ruxsat nazorati.

---

## ⚠️ Ma'lum cheklovlar

* **Calibration yo'q (MVP'da):** `b` lar oldindan beriladi (real javoblar statistikasi
  asosida emas). Rasmiy IRT tahlilida ular statistik baholanadi.
  → **Reja:** `docs/03-QIYINCHILIK-ALGORITMI.md` (avtomatik `p → b`) va
  `docs/06-RASCH-KALIBRLASH.md` (JMLE kalibrlash).
* **1PL (Rasch)** modeli ishlatiladi: barcha savollar bir xil diskriminatsiyaga
  (`a = 1`) ega deb hisoblanadi. 2PL/3PL modellari (taxmin parametri bilan)
  keyinchalik qo'shilishi mumkin.
* **Dichotomous (0/1) javoblar:** ko'p tanlovli savollar to'g'ri/xato sifatida
  qayd etiladi; tasodifiy taxmin ehtimoli (guessing) modellashtirilmagan.
* **Savollar matni ko'rsatilmaydi:** ilova javoblar varag'i (`1A2B3C…`) qabul
  qiladi, savol matni qog'oz variantda bo'ladi. Kelajakda savol matnini ham
  jadvalga qo'shib, Web App'da ko'rsatish mumkin.
* **Web App HTTPS talab qiladi:** Telegram Mini App'ni faqat `https://` manzilda
  ochadi (`WEBAPP_URL`). `http://localhost` Telegram ichida ishlamaydi —
  brauzerda sinash uchun `WEBAPP_DEV_MODE=1` va `?debug_user_id=…` ishlatiladi.
* **0–100 shkala chiziqli:** `θ` asosiy o'lchov (logit), 0–100 esa qulay
  ko'rinish; `θ` chegarasidan tashqaridagi qiymatlar `0` yoki `100` da siqiladi.
* **Imtihonni tahrirlash yo'q:** `/new_exam` bilan yaratilgan imtihonni faqat
  o'chirish mumkin (`/exams`); vaqtlarni o'zgartirish hozircha repository
  darajasida (`ExamRepository.update_times`).
* **Qayta baholash qo'lda:** savol kaliti yoki logitlar keyin o'zgartirilsa,
  natijalar avtomatik yangilanmaydi — `grading.grade_exam(..., regrade=True)`
  chaqirilishi kerak.
* **A/B qismli savollarning belgisi:** `user_answers.submitted_answers` har bir
  savol uchun **bitta** harf saqlaydi, shu sababli 36-savolning `a` va `b` qismlari
  bir xil ✅/❌ belgisini oladi. Qismlar bo'yicha alohida javob saqlash keyingi
  bosqich ishi (qism tugmalari va yechimlari hozir ham to'liq ishlaydi).
* **Yechimlar Telegram `file_id` bilan:** media faylning o'zi serverga
  ko'chirilmaydi — Telegram'da qoladi, bazada faqat `file_id` saqlanadi.

## 🚀 Keyingi qadamlar (g'oyalar)

1. **Calibration:** guruh javoblari yig'ilgach, `b` larni qayta baholash
   (bir o'lchovli MLE yoki `mirt`/`TAM` kabi tayyor vositalar bilan).
   → **Batafsil:** `docs/03-QIYINCHILIK-ALGORITMI.md`, `docs/06-RASCH-KALIBRLASH.md`.
2. **2PL/3PL modellar:** `a` (diskriminatsiya) va `c` (taxmin) parametrlarini
   qo'shish.
3. **Moslik (fit) statistikasi:** `Infit/Outfit MNSQ` — o'quvchi javoblarining
   modelga mosligi; savollarning mosligi (item fit).
4. **Test informatsiya funksiyasi** va `SE` ni samarali hisoblash, adaptiv
   (CAT) test — keyingi savolni o'quvchi `θ` siga moslab tanlash.
5. **O'qituvchi paneli (kengaytirish):** imtihonni tahrirlash (muddatni
   uzaytirish, kodni almashtirish), Excel/CSV eksport (user, raw, θ, scaled),
   guruh hisobotlari va eng qiyin savollar tahlili.
6. **Offline (hududiy) imtihonlar:** «Offline imtihon» bo'limini haqiqiy
   ma'lumot bilan to'ldirish (sana, joy, ro'yxatdan o'tish).
7. **Natija haqida xabarnoma:** `result_time` kelganda ishtirokchilarga bot
   orqali xabar yuborish (hozircha natija faqat ilovada ko'rinadi).
8. **Calibration (haqiqiy ma'lumot bilan):** to'plangan javoblar asosida `b`
   larni qayta baholash va tayyor imtihon shablonlarini yaratish.
9. **Reyting va monitoring:** guruh bo'yicha o'rtacha `θ` dinamikasi va
   o'qituvchi uchun jonli dashboard.

---

## 👩‍🏫 Muallif uchun eslatma

Loyihaning ilmiy yadrosi — `services/rasch.py` (mustaqil, Telegram'siz ishlay
oladi). Uni boshqa loyihalarda ham ishlatish mumkin:

```python
from services import rasch
from database.models import Question

questions = [...]                      # Question obyektlari (b qiymatlari bilan)
answers = {question.question_id: "B" for question in questions}

estimate = rasch.evaluate(questions, answers)
print(estimate.theta, estimate.scaled_score, estimate.standard_error)

# Yangi imtihon platformasi uslubi: faqat logitlar + kalit + javoblar yetarli
estimate = rasch.estimate_from_letters(
    difficulties=[0.0, 1.2, -0.5],     # b_j (logit)
    correct_letters=["A", "B", "C"],   # javoblar kaliti
    given_letters=["A", "X", "C"],     # o'quvchi javoblari ("X" — javobsiz)
)
print(estimate.theta, estimate.scaled_score, estimate.standard_error)
```

Imtihon platformasining boshqa mustaqil bo'laklari:

* `services/answer_key.py` — "1A2B3C" kalitini tahlil qilish/solishtirish;
* `services/exam_service.py` — imtihon holati va vaqt konvertatsiyasi;
* `services/grading.py` — javoblarni baholash va batafsil hisobot;
* `services/webapp_auth.py` — Telegram `initData` imzosini tekshirish.