# 12 — Railway'ga joylashtirish (deployment)

Bu hujjat botni **Railway.app** (Hobby, $5/oy) ga joylashtirishning to'liq
yo'riqnomasi. Kod allaqachon bulutga moslangan: qo'shimcha fayl yoki qator
yozish shart emas.

---

## 1. Nima avtomatik bajariladi

`config.py` Railway beradigan o'zgaruvchilarni o'zi o'qiydi:

| Railway o'zgaruvchisi | Avtomatik natija |
|---|---|
| `PORT` | `WEBAPP_PORT` shu portga tenglashadi |
| Railway muhiti (istalgan `RAILWAY_*`) | `WEBAPP_HOST=0.0.0.0` (konteynerdan tashqariga ochiq) |
| `RAILWAY_PUBLIC_DOMAIN` | `WEBAPP_URL=https://<domen>` — Mini App tugmasi ishlaydi |
| `RAILWAY_VOLUME_MOUNT_PATH` (masalan `/data`) | `DB_PATH=<volume>/math_bot.db` — baza deploy'lar orasida saqlanadi |

Ya'ni Railway'da **faqat 3 ta** o'zgaruvchi kiritish kifoya:
`BOT_TOKEN`, `ADMIN_ID`, `WEBAPP_DEV_MODE=0`.

`WEBAPP_HOST`, `WEBAPP_PORT`, `WEBAPP_URL`, `DB_PATH` ni qo'lda yozsangiz —
ular avtomatik qiymatlardan ustun turadi.

Qo'shimcha himoya: qayta deploy paytida eski va yangi konteyner bir necha
sekund birga ishlaydi. Telegram bu holatda `409 Conflict` qaytaradi —
`main.py` dagi `poll_with_conflict_retry()` jarayonni yiqitmaydi, 10 sekund
kutib qayta urinadi (`restartPolicyType: ON_FAILURE` bilan birga).

---

## 2. Repozitoriy tayyorligi

Railway GitHub'dan deploy qiladi. Kerakli fayllar repoda bo'lishi shart:

| Fayl | Vazifasi |
|---|---|
| `requirements.txt` | Nixpacks build (pip install) |
| `railway.json` | Start buyrug'i `python main.py`, healthcheck `/api/health`, restart siyosati, `numReplicas: 1` |
| `.python-version` | Python 3.12 (Nixpacks versiyani shu fayldan oladi) |
| `webapp/` | Mini App fayllari (index.html, js, css) |
| `data/` | **kerak emas** — serverda volume yaratiladi |

`.env` hech qachon commit qilinmaydi (`.gitignore` da) — tokenlar Railway
Variables orqali beriladi.

---

## 3. Qadamlar

### 3.1. GitHub'ga push

```powershell
git add -A
git commit -m "Railway deploy: bulut sozlamalari, healthcheck, konflikt retry"
git push origin main
```

### 3.2. Railway loyihasi

1. <https://railway.app> → **Login with GitHub**.
2. **Account Settings → Plan → Hobby ($5/oy)**.
3. **New Project → Deploy from GitHub repo** → `rash-model-dasturi`.
   Private repo bo'lsa — Railway GitHub App'ga ruxsat bering.
4. Birinchi build avtomatik boshlanadi (Nixpacks `requirements.txt` ni o'qiydi,
   start buyrug'i `railway.json` dan olinadi).

### 3.3. Volume (baza uchun — majburiy)

Service → **Settings → Volumes → Add Volume**:

* Mount path: `/data`
* Hajm: `0.5 GB` (SQLite uchun ortig'i bilan yetadi)

### 3.4. Variables

Service → **Variables → Raw Editor**:

```env
BOT_TOKEN=123456789:AA...
ADMIN_ID=123456789
WEBAPP_DEV_MODE=0
TIMEZONE=Asia/Tashkent
LOG_LEVEL=INFO
```

Majburiy bo'lmagan (standart qiymatlar qanoatlantiradi):
`ADMIN_IDS`, `INITDATA_MAX_AGE=86400`, `GRADING_INTERVAL=30`,
`RESULT_NOTIFY_INTERVAL=60`, `DEMO_MODE=0`.

> `WEBAPP_HOST`, `WEBAPP_PORT`, `WEBAPP_URL`, `DB_PATH` **yozilmaydi** —
> Railway ularni avtomatik beradi (1-bo'limga qarang).

### 3.5. Domen

Service → **Settings → Networking → Generate Domain**.
Railway portni o'zi aniqlaydi (`PORT`); agar so'ralsa — `8080`.

Domen `https://<loyiha>.up.railway.app` ko'rinishida bo'ladi va
`RAILWAY_PUBLIC_DOMAIN` orqali kodga avtomatik yetib boradi → `WEBAPP_URL`
qo'lda kiritilmaydi.

### 3.6. Sozlamalar

Service → **Settings**:

* **Replicas: 1** — 2 nusxa long polling'da `409` beradi.
* **Restart policy: On Failure** (`railway.json` da ham yozilgan).
* **Serverless / App Sleeping: OFF** — uxlab qolsa bot javob bermaydi.
* **Healthcheck Path: `/api/health`** (autentifikatsiyasiz, 200 qaytaradi).
* Memory limit: `512 MB` yetarli.

### 3.7. CLI bilan deploy (muqobil yo'l)

Agar GitHub integratsiyasi o'rniga lokal papkadan deploy qilish kerak bo'lsa
(CLI bu kompyuterga o'rnatilgan: `%LOCALAPPDATA%\Programs\railway\railway.exe`,
PATH'ga qo'shilgan — yangi terminalda `railway` ishlaydi):

```powershell
railway login          # brauzer ochiladi — Railway akkauntiga kirasiz
railway init           # loyiha nomi: rash-model-dasturi
railway up             # joriy papkadagi kodni yuklaydi va build qiladi
railway variables --set "BOT_TOKEN=..." --set "ADMIN_ID=..." --set "WEBAPP_DEV_MODE=0"
railway domain         # HTTPS domen generatsiya qiladi
```

Keyin volume va replicas sozlamalari baribir dashboard'da bajariladi
(3.3 va 3.6-bandlar).

---

## 4. Tekshirish

1. **Deploy Logs**: `Bot ishga tushdi ✅`, `Muhit: bulut`, `HTTP: 0.0.0.0:<PORT>`,
   `Ma'lumotlar bazasi tayyor: /data/math_bot.db`.
2. Brauzer: `https://<domen>/api/health` → `{"status": "ok", ...}`.
3. Brauzer: `https://<domen>/` → Mini App sahifasi.
4. Telegram: `/start` → **«Javoblar»** Web App tugmasi ko'rinadi.
5. Admin: `/new_exam` → imtihon yaratish → o'quvchi javobi → natija.
6. **Volume testi**: `Deploy → Redeploy` qiling, so'ng `/exams` — imtihonlar
   joyida turishi kerak.

---

## 5. Muammolar va yechimlar

| Belgisi | Sababi | Yechim |
|---|---|---|
| `409 Conflict ... getUpdates` | Lokal bot ham ishlayapti yoki 2 replika | Lokal `python main.py` ni to'xtating; `Replicas = 1` |
| `Telegram 401` | `BOT_TOKEN` xato | Variables ni tekshiring |
| `502 / Application failed to respond` | Domen porti `PORT` ga mos emas yoki `WEBAPP_HOST=127.0.0.1` qolgan | `WEBAPP_HOST`/`WEBAPP_PORT` ni o'chiring (avtomatik ishlaydi), domen target portini `PORT` ga tenglang |
| `503 Web App fayllari topilmadi` | `webapp/` repoga tushmagan | Push qiling (3.1) |
| Redeploy'dan keyin imtihonlar yo'q | Volume yo'q yoki `DB_PATH` volume'dan tashqarida | `/data` volume qo'shing, `DB_PATH` ni o'chiring |
| Mini App "initData invalid" | `WEBAPP_DEV_MODE=1` yoki eskirgan `initData` | `WEBAPP_DEV_MODE=0`, `INITDATA_MAX_AGE=86400` |
| Build `No start command` | `railway.json` ko'rinmagan | Fayl repoda borligini tekshiring yoki Settings → Start Command: `python main.py` |

---

## 6. Xarajat va limitlar

* Hobby tarifi: **$5/oy**, ichida $5 usage credit.
* Bitta yengil Python konteyner (~200–350 MB RAM, doimiy long polling)
  odatda **$5–7/oy** atrofida — kichik yuklamada credit yetarli.
* Bepul "trial" tarifida konteyner uxlaydi — long polling bot uchun yaroqsiz,
  shuning uchun Hobby kerak.
* SQLite + volume: bitta servis, bitta volume yetarli (SQLite tarmoqda
  ishlamaydi, shuning uchun alohida baza servisi **kerak emas**).

## 7. Botni boshqa botga almashtirish (yangi brend/manzil)

Botni yangisiga ko'chirish kerak bo'lganda (masalan «@eski_bot» → «@yangi_bot»):

1. **@BotFather → `/newbot`** → yangi nom va username (username **`bot`** bilan tugashi shart).
2. Railway → servis → **Variables** → **`BOT_TOKEN`** ni yangi tokenga almashtiring.
3. **Yangi deployment kerak bo'ladi** — Railway o'zgaruvchilarni deploymentga "muhrlab" qo'yadi,
   shuning uchun faqat restart qilish kifoya qilmaydi:
   ```powershell
   railway up --detach
   ```
4. Loglarda tasdiqlang: `Run polling for bot @yangi_bot id=...`.
5. Yangi botning nomi/tavsifini chiroyli qilish (Bot API orqali ham mumkin):
   `setMyName`, `setMyShortDescription`, `setMyDescription`.
6. Eski botga «biz ko'chdik» yozuvi qo'ying: `setMyShortDescription` + `setMyDescription`
   → `⚠️ Biz yangi manzilga ko'chdik: @yangi_bot`.
7. **Ma'lumotlar saqlanadi**: imtihonlar, o'quvchilar, natijalar va `/admins` orqali qo'shilgan
   adminlar bazada (volume ichida) qoladi. O'quvchilar yangi botga **qaytadan `/start`** bosishi kerak.

> Eslatma: `WEBAPP_URL` (Railway domeni) va `initData` tekshiruvi tokenga bog'liq — token almashsa,
> Mini App ham avtomatik yangi token bilan tekshiradi (kodda o'zgartirish kerak emas).

### «Deploys have been paused temporarily» xatosi

Bu xato **Railway tomonidagi** cheklov (kodga aloqasi yo'q). Uchraydigan sabablar:

| Sabab | Tekshirish | Yechim |
|---|---|---|
| Railway'da platforma nosozligi (outage) | <https://status.railway.com> | Kutish — nosozlik yopilgach deploy o'zi ishlaydi |
| Workspace «Limited Trial» (tekshirilmagan) | Settings → Plans | `railway.com/verify` yoki karta/Hobby |
| Kredit tugagan | `railway usage` | Hobby ($5/oy) |

Bunday holatda `railway up`, `railway redeploy`, GitHub push va manbani qayta ulash — **hammasi**
bir xil javob qaytaradi. Yagona yo'l: nosozlik yopilishini kutish yoki hisobni tasdiqlash.

---

## 8. Mahalliy bazani serverga ko'chirish (ixtiyoriy)

Lokal `data/math_bot.db` repoga tushmaydi, shuning uchun server bo'sh baza
bilan boshlanadi (`seed_questions()` faqat mashq savollarini qo'shadi).

Mavjud imtihon/o'quvchilarni ko'chirish kerak bo'lsa:

1. Lokal bazadan **nusxa** oling (botni to'xtatib): `data/math_bot.db`.
2. Faylni Railway volume'iga joylang — `railway ssh` (Hobby'da mavjud)
   orqali `/data/math_bot.db` ustiga yozish eng oddiy yo'l.
3. Deploy'dan keyin `/exams` va `/stats` bilan tekshiring.

> Bu qadam majburiy emas — yangi imtihonlarni o'qituvchi bot orqali qayta
> yaratishi mumkin.

---

## 9. Adminlarni boshqarish (deploy'dan keyin)

Bot ichida **/admins** paneli bor:

1. /admins → **«➕ Admin qo'shish»**;
2. yangi odam botga **/start** yozsin;
3. uning xabarini shu yerga **forward** qiling;
4. tasdiqlang — o'sha odam darhol admin bo'ladi;
5. o'chirish: admin yonidagi **«🗑»** → tasdiqlash.

Muhim:
* Ma'lumot **ot_admins** jadvalida saqlanadi — u /data volume ichida,
  ya'ni qayta deploy'larda yo'qolmaydi;
* .env dagi ADMIN_ID / ADMIN_IDS **egasi** hisoblanadi va panel orqali
  o'chirilmaydi (lock-out himoyasi);
* birinchi admin baribir ADMIN_ID orqali beriladi — panelga kirish uchun.

