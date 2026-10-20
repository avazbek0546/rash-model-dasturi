# 📚 Arxitektura hujjatlari — Milliy Sertifikat test platformasi

Bu papkadagi hujjatlar **O'zbekiston Milliy Sertifikat** testlarini
`PDF → Telegram Bot → Web App javoblari → avtomatik qiyinchilik hisoblash →
(keyinchalik) Rasch kalibrlash` zanjiri bo'yicha ishlaydigan tizim
arxitekturasini belgilaydi.

> **Muhim:** bu tizim **IELTS / SAT / GMAT / CAT emas**. Hech qanday
> listening/speaking, adaptive multi-stage, verbal/quantitative bo'lim
> mantiqlari qo'shilmaydi. Faqat Milliy Sertifikat testi formati:
> savollar **PDF** da tarqatiladi, o'quvchi javoblarni **A/B/C/D** variant
> kartochkalari orqali Web App'da belgilaydi.

## Asosiy tamoyillar

1. **Savollar bazaga yuklanmaydi.** Bazada savol matni yo'q — faqat
   *savol pozitsiyasi* (`position`, `part`), *javob kaliti* (`A/B/C/D`) va
   *metadata* (fan, yo'nalish, struktura, manba havolasi).
2. **O'qituvchi `b` (logit) kiritmaydi.** U faqat **test kodi**, **javob
   kaliti** va **test metadata**sini kiritadi. Qolgan parametrlarni tizim
   o'quvchilar javoblari asosida o'zi hisoblaydi.
3. **Har bir savol default holatda yaratiladi.** Yangi savol
   (`item_version`) `b = 0.0`, `status = provisional` bilan boshlanadi.
4. **Hamma javob append-only.** Har bir o'zgarish yangi `revision` satri
   bo'lib yoziladi — javoblar tarixi hech qachon o'chirilmaydi/o'zgartirilmaydi.
5. **Snapshot scoring.** Har bir natija qaysi `form_version` va qaysi
   `item_parameter_set` bilan hisoblanganini saqlaydi — keyin `b` yangilansa
   ham eski natija qayta yozilmaydi, yangi **result version** yaratiladi.
6. **Rasch'ga tayyor.** Sxema `anchor_items`, `calibration_runs`,
   `equatings` jadvallarini birinchi kundan o'z ichiga oladi, shuning uchun
   klassik `p → b` usulidan to'liq `JMLE Rasch calibration`ga o'tish
   **ma'lumot yo'qotmasdan** amalga oshiriladi.

## Hujjatlar ro'yxati

| № | Hujjat | Mazmuni |
|---|---|---|
| 01 | [ARXITEKTURA](01-ARXITEKTURA.md) | Umumiy arxitektura, komponentlar, oqimlar, xavfsizlik, stack |
| 02 | [DATABASE SCHEMA](02-DATABASE-SCHEMA.md) | To'liq sxema: SQLite (MVP) va PostgreSQL DDL, audit, soft delete, indekslar |
| 03 | [QIYINCHILIK ALGORITMI](03-QIYINCHILIK-ALGORITMI.md) | `p = c/n` → `b = ln((1−p)/p)` avtomatik hisoblash, tekislash, guruhga moslash, freeze |
| 04 | [API VA UI (MVP)](04-API-VA-UI-MVP.md) | Minimal API'lar, bot komandalari, Mini App javoblar varag'i UI |
| 05 | [MIGRATSIYA](05-MIGRATSIYA.md) | SQLite → yangi sxema → PostgreSQL ko'chirish rejasi va skript ketma-ketligi |
| 06 | [RASCH KALIBRLASH](06-RASCH-KALIBRLASH.md) | JMLE kalibrlash, anchor items, equating, drift — integratsiya rejasi |
| 07 | [ROADMAP](07-ROADMAP.md) | Keyingi 3 oy va keyingi 1 yil yo'l xaritasi |
| 08 | [PSIKOMETRIK AUDIT](08-PSIKOMETRIK-AUDIT.md) | **Senior audit**: Critical/High/Medium topilmalar, 34 yetishmayotgan jadval, ideal PostgreSQL sxemasi, item lifecycle, professional roadmap |
| 09 | [RESPONSE MODEL v2](09-RESPONSE-MODEL-V2.md) | **Javob saqlash modeli (yakuniy)**: 4 artefakt, uch o'qli status, autosave yo'li, immutability, testlet/LD, psixometrik majburiy maydonlar, qaytarib bo'lmaydigan ma'lumotlar |
| 10 | [MVP PRIORITET AUDITI](10-MVP-PRIORITET-AUDIT.md) | **MVP / PHASE-2 / FUTURE tasnifi**: 12 element bahosi, 5 natija ro'yxati, murakkablik byudjeti, trigger jadvali |
| 11 | [FINAL MVP DATABASE MODEL](11-FINAL-MVP-DATABASE-MODEL.md) | **Yakuniy MVP modeli (16 jadval)**: docs/02 tasnifi (M/P2/F/R), README sabablari, maydonlar lug'ati, Rasch uchun majburiy ma'lumotlar |

## Hozirgi loyihaga aloqasi

Hujjatlar mavjud kod bazasi bilan **mos** yozilgan:

| Hujjatdagi tushuncha | Mavjud koddagi joy |
|---|---|
| θ hisoblash (MLE) | `services/rasch.py` — `estimate_theta()`, `estimate_from_letters()` |
| Javob kaliti tahlili | `services/answer_key.py` — `parse_answer_key()`, `parse_submitted()` |
| Test kodi / jadval | `services/exam_service.py`, `exams` jadvali |
| Baholash fon vazifasi | `services/grading.py` — `grade_pending()`, `grading_loop()` |
| Mini App / API | `webapp/`, `web/api.py` |
| Bot oqimi | `handlers/`, `middlewares/user_sync.py` |

Ya'ni mavjud tizim **Rasch baholash** qismida tayyor; yangi hujjatlar unga
**Question Bank**, **item-level javoblar**, **avtomatik kalibrlash** va
**audit** qatlamlarini qo'shadi.

## Tezkor xulosa (bir jumlada)

> O'qituvchi test kodi + kalit + metadata kiritadi → o'quvchi PDF dan
> ishlab, Mini App'da kartochkalar orqali javoblarni belgilaydi → tizim har
> bir savol bo'yicha `p` (to'g'ri javob ulushi) ni yig'adi va
> `b = ln((1−p)/p)` formula bilan qiyinchilikni **o'zi** hisoblaydi →
> yetarli ma'lumot yig'ilgach shu modul to'liq Rasch kalibrlash bilan
> almashtiriladi.
