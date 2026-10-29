"""Loyiha sozlamalari.

Barcha sozlamalar `.env` faylidan (yoki muhit o'zgaruvchilaridan) o'qiladi.
Kodning boshqa joylarida `os.getenv` ishlatilmaydi — hammasi shu yerda.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _get_str(name: str, default: str = "") -> str:
    """Muhit o'zgaruvchisidan matn qiymatini oladi."""
    raw = os.getenv(name)
    return default if raw is None else raw.strip()


def _get_int(name: str, default: int | None = None) -> int | None:
    """Muhit o'zgaruvchisidan butun sonni oladi (bo'sh bo'lsa — default)."""
    raw = _get_str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - faqat noto'g'ri .env uchun
        raise ValueError(f"{name} butun son bo'lishi kerak, berilgan: {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    """Muhit o'zgaruvchisidan haqiqiy sonni oladi (bo'sh bo'lsa — default)."""
    raw = _get_str(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:  # pragma: no cover - faqat noto'g'ri .env uchun
        raise ValueError(f"{name} son bo'lishi kerak, berilgan: {raw!r}") from exc


def _get_bool(name: str, default: bool = False) -> bool:
    """Muhit o'zgaruvchisidan mantiqiy qiymatni oladi.

    Rost hisoblanadigan qiymatlar: 1, true, yes, y, ha, on (katta-kichik harf farqi yo'q).
    """
    raw = _get_str(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "ha", "on"}


# ---------------------------------------------------------------------------
# Bulut (Railway) muhiti — avtomatik aniqlash
# ---------------------------------------------------------------------------
# Railway quyidagi o'zgaruvchilarni o'zi beradi (qo'lda kiritish shart emas):
#   RAILWAY_PUBLIC_DOMAIN      — ochiq HTTPS domen (sxemasiz, masalan
#                                "app-production.up.railway.app")
#   RAILWAY_VOLUME_MOUNT_PATH  — ulangan volume yo'li (masalan "/data")
#   RAILWAY_SERVICE_ID         — servis identifikatori
#   PORT                       — konteyner tinglashi kerak bo'lgan port
# Shu o'zgaruvchilardan biri mavjud bo'lsa — bulutda ishlayapmiz va quyidagi
# sozlamalar (host, port, baza yo'li, Web App manzili) avtomatik moslashadi.
RAILWAY_PUBLIC_DOMAIN: str = _get_str("RAILWAY_PUBLIC_DOMAIN")
RAILWAY_VOLUME_MOUNT_PATH: str = _get_str("RAILWAY_VOLUME_MOUNT_PATH")
HOSTING_PORT: int | None = _get_int("PORT")
IS_CLOUD: bool = bool(
    RAILWAY_PUBLIC_DOMAIN
    or RAILWAY_VOLUME_MOUNT_PATH
    or _get_str("RAILWAY_SERVICE_ID")
    or HOSTING_PORT
)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
BOT_TOKEN: str = _get_str("BOT_TOKEN")
ADMIN_ID: int | None = _get_int("ADMIN_ID")

# `.env` dagi adminlar — "egasi" hisoblanadi va bot ichidan O'CHIRILMAYDI
# (lock-out himoyasi: kimsa barcha adminlarni o'chirib qo'yolmaydi).
OWNER_ADMIN_IDS: frozenset[int] = frozenset(
    int(part)
    for part in _get_str("ADMIN_IDS").replace(" ", "").split(",")
    if part.isdigit()
) | ({ADMIN_ID} if ADMIN_ID is not None else set())

# Bot ishga tushganda bazadagi (`bot_admins`) adminlar shu yerga qo'shiladi.
# `set_db_admins()` / `add_admin()` / `remove_admin()` shu to'plamni yangilaydi.
_DB_ADMIN_IDS: frozenset[int] = frozenset()

# Amaldagi to'liq ro'yxat: egasi + bazadan qo'shilganlar.
ADMIN_IDS: frozenset[int] = OWNER_ADMIN_IDS

# Admin chat: yangi qatnashchi haqidagi xabarlar yuboriladigan guruh/kanal.
# Asosiy usul — bot ichida `/admin_chat` (bazadagi `bot_settings`); bu env
# qiymati zaxira sifatida ishlatiladi (masalan kanalni qo'lda ulash uchun).
ADMIN_CHAT_ID: int | None = _get_int("ADMIN_CHAT_ID")


def is_admin(user_id: int | None) -> bool:
    """Foydalanuvchi o'qituvchi (admin) huquqiga egami?"""
    return user_id is not None and user_id in ADMIN_IDS


def is_owner(user_id: int | None) -> bool:
    """Foydalanuvchi `.env` dagi "egasi" adminmi (o'chirilmaydi)?"""
    return user_id is not None and user_id in OWNER_ADMIN_IDS


def set_db_admins(user_ids: set[int] | frozenset[int]) -> None:
    """Bazadan o'qilgan adminlarni xotiraga yuklaydi (bot ishga tushganda)."""
    global _DB_ADMIN_IDS, ADMIN_IDS
    _DB_ADMIN_IDS = frozenset(int(uid) for uid in user_ids)
    ADMIN_IDS = OWNER_ADMIN_IDS | _DB_ADMIN_IDS


def add_admin(user_id: int) -> bool:
    """Adminlar ro'yxatiga ID qo'shadi (faqat xotirada; baza handler'da yoziladi).

    Returns:
        True — qo'shildi; False — allaqachon admin (yoki egasi).
    """
    global _DB_ADMIN_IDS, ADMIN_IDS
    if is_admin(user_id):
        return False
    _DB_ADMIN_IDS = _DB_ADMIN_IDS | {int(user_id)}
    ADMIN_IDS = OWNER_ADMIN_IDS | _DB_ADMIN_IDS
    return True


def remove_admin(user_id: int) -> bool:
    """Adminni ro'yxatdan o'chiradi.

    "Egasi" (`.env` orqali berilgan) adminni o'chirib bo'lmaydi.

    Returns:
        True — o'chirildi; False — egasi yoki ro'yxatda yo'q edi.
    """
    global _DB_ADMIN_IDS, ADMIN_IDS
    if is_owner(user_id):
        return False
    if user_id not in _DB_ADMIN_IDS:
        return False
    _DB_ADMIN_IDS = _DB_ADMIN_IDS - {int(user_id)}
    ADMIN_IDS = OWNER_ADMIN_IDS | _DB_ADMIN_IDS
    return True


def db_admin_ids() -> frozenset[int]:
    """Bot ichidan qo'shilgan adminlar (`.env` dagilarsiz)."""
    return _DB_ADMIN_IDS

# ---------------------------------------------------------------------------
# Ma'lumotlar bazasi
# ---------------------------------------------------------------------------
# Prioritet: DB_PATH (qo'lda) → volume yo'li (Railway) → loyiha ichidagi data/.
# Railway'da volume `RAILWAY_VOLUME_MOUNT_PATH=/data` bo'lsa, baza shu yerda
# saqlanadi va qayta deploy'larda imtihonlar yo'qolmaydi.
_DB_DIR: Path = (
    Path(RAILWAY_VOLUME_MOUNT_PATH) if RAILWAY_VOLUME_MOUNT_PATH else BASE_DIR / "data"
)
DB_PATH: Path = Path(_get_str("DB_PATH") or str(_DB_DIR / "math_bot.db"))

# ---------------------------------------------------------------------------
# Telegram Web App (Mini App)
# ---------------------------------------------------------------------------
# Web App ochiladigan manzil. Telegram faqat HTTPS manzilni qabul qiladi
# (masalan: https://exam.example.uz yoki dev uchun Cloudflare Tunnel/ngrok).
# Bo'sh bo'lsa — bot Web App tugmasini ko'rsatmaydi, API server esa lokal
# test uchun baribir ishlaydi.
# Prioritet: WEBAPP_URL (qo'lda) → Railway domeni → bo'sh.
# Railway'da domen generatsiya qilinsa `RAILWAY_PUBLIC_DOMAIN` avtomatik
# beriladi, shu sababli alohida o'zgaruvchi kiritish shart emas.
WEBAPP_URL: str = (
    _get_str("WEBAPP_URL")
    or (f"https://{RAILWAY_PUBLIC_DOMAIN}" if RAILWAY_PUBLIC_DOMAIN else "")
).rstrip("/")
# Mini App kesh-buster versiyasi (dizayn/JS o'zgarganda oshiriladi). Bitta joyda
# saqlanadi — menyu tugmasi, inline tugmalar va natija xabarlari shu yerdan oladi.
WEBAPP_VERSION: str = _get_str("WEBAPP_VERSION", "28") or "28"
# Bulutda konteynerdan tashqaridan ko'rinish uchun `0.0.0.0` shart;
# lokal ishlab chiqishda esa xavfsizlik uchun `127.0.0.1` qoladi.
_DEFAULT_WEBAPP_HOST: str = "0.0.0.0" if IS_CLOUD else "127.0.0.1"
WEBAPP_HOST: str = _get_str("WEBAPP_HOST", _DEFAULT_WEBAPP_HOST) or _DEFAULT_WEBAPP_HOST
# `PORT` — Railway/PaaS beradigan port (domen shu portga yo'naltiriladi),
# u bo'lmasa WEBAPP_PORT, u ham bo'lmasa 8080.
WEBAPP_PORT: int = HOSTING_PORT or _get_int("WEBAPP_PORT", 8080) or 8080
WEBAPP_DIR: Path = BASE_DIR / "webapp"
# Faqat lokal ishlab chiqish uchun: initData o'rniga X-Debug-User-Id header'i
# qabul qilinadi. Ishlab chiqarishda (production) HECH QACHON yoqilmasin!
WEBAPP_DEV_MODE: bool = _get_bool("WEBAPP_DEV_MODE", False)
# initData necha sekund "yangi" hisoblanadi (qayta yuborish hujumidan himoya).
INITDATA_MAX_AGE: int = _get_int("INITDATA_MAX_AGE", 86400) or 86400


def webapp_url(*, tab: str = "") -> str:
    """Mini App manzili: kesh-buster + ixtiyoriy bo'lim (`tab`).

    Misol: ``https://exam.example.uz/?v=21&tab=results``.
    `WEBAPP_URL` bo'sh bo'lsa — bo'sh satr (chaqiruvchi tugmani ko'rsatmaydi).
    """
    if not WEBAPP_URL:
        return ""
    url = f"{WEBAPP_URL}/?v={WEBAPP_VERSION}"
    if tab:
        url += f"&tab={tab}"
    return url

# ---------------------------------------------------------------------------
# Vaqt va fon vazifalari
# ---------------------------------------------------------------------------
# O'qituvchi vaqtni shu zonada kiritadi/ko'radi; bazada esa hamma vaqt UTC ISO.
TIMEZONE: str = _get_str("TIMEZONE", "Asia/Tashkent") or "Asia/Tashkent"
# Baholash fon vazifasi qancha sekundda bir marta bazani tekshiradi.
GRADING_INTERVAL: int = _get_int("GRADING_INTERVAL", 30) or 30
# Natija bildirishnomasi (result_time kelgach) fon vazifasi oralig'i (sekund).
# 60 sekund — o'quvchi natijani bir daqiqa ichida oladi; ortiqcha yuklama yo'q.
RESULT_NOTIFY_INTERVAL: int = _get_int("RESULT_NOTIFY_INTERVAL", 60) or 60
# Vaqtinchalik item statistikasi (p → b) fon vazifasi oralig'i (sekund).
# Baholangan testlar uchun `item_difficulty_stats` avtomatik yangilanadi.
ITEM_STATISTICS_INTERVAL: int = _get_int("ITEM_STATISTICS_INTERVAL", 30) or 30

# ---------------------------------------------------------------------------
# Sinov rejimi (vaqtinchalik)
# ---------------------------------------------------------------------------
# True bo'lsa: bot ishga tushganda `SINOV` kodli namuna test avtomatik yaratiladi
# — javob oynasini kod kiritmasdan sinash uchun. Bot tayyor bo'lgach `0` qilinadi.
DEMO_MODE: bool = _get_bool("DEMO_MODE", False)

# ---------------------------------------------------------------------------
# Imtihon parametrlari
# ---------------------------------------------------------------------------
# Test kodi kamida necha belgidan iborat bo'lishi kerak.
MIN_TEST_CODE_LENGTH: int = _get_int("MIN_TEST_CODE_LENGTH", 4) or 4
# Javoblar varag'ida ruxsat etilgan variantlar.
ANSWER_OPTIONS: tuple[str, ...] = ("A", "B", "C", "D")

# ---------------------------------------------------------------------------
# Baholash manbasi (item-level MVP)
# ---------------------------------------------------------------------------
# True bo'lsa: javoblar item-level `responses` jadvalidan o'qiladi (sessiya +
# urinish + javoblar mavjud bo'lsa). Ular topilmasa — baholash avvalgidek
# `user_answers.submitted_answers` dan o'qiladi (avtomatik fallback).
# False (standart): hamma imtihon avvalgidek `user_answers` dan baholanadi.
ITEM_LEVEL_GRADING_ENABLED: bool = _get_bool("ITEM_LEVEL_GRADING_ENABLED", False)

# ---------------------------------------------------------------------------
# Qiyinchilikni tekislash (shrinkaj / empirik Bayes) — docs/03
# ---------------------------------------------------------------------------
# True bo'lsa: baholashda har bir savolning `b` si **o'qituvchi bahosi** va
# **javob ma'lumoti** o'rtasida `N` ga qarab aralashtiriladi
# (`services/item_statistics`):
#
#     w = N / (N + K);   b = w·b_auto + (1 − w)·b_teacher
#
# Ya'ni o'quvchi kam bo'lsa — o'qituvchi qiymati, ko'p bo'lsa — ma'lumot ustun.
# False (standart): `b` faqat o'qituvchi bahosidan olinadi (avvalgi xulq).
DIFFICULTY_SHRINKAGE_ENABLED: bool = _get_bool("DIFFICULTY_SHRINKAGE_ENABLED", False)
# Shrinkaj konstantasi `K` (docs/01, docs/02: `calibration.k_shrink = 30`).
DIFFICULTY_SHRINK_K: float = _get_float("DIFFICULTY_SHRINK_K", 30.0)

# ---------------------------------------------------------------------------
# Ifodani saqlash (Phase 1 — expression preservation)
# ---------------------------------------------------------------------------
# True (standart): o'quvchi kiritgan ASL matematik ifoda (`√5+1`) `responses`
# jadvalidagi `raw_answer` ustuniga saqlanadi va `GET /api/v2/state` orqali
# tiklanadi. `normalized_answer`/`numeric_value` va baholash O'ZGARMAYDI.
# False: avvalgi xatti-harakat — faqat hisoblangan son saqlanadi.
EXPRESSION_PRESERVATION_ENABLED: bool = _get_bool(
    "EXPRESSION_PRESERVATION_ENABLED", True
)

# ---------------------------------------------------------------------------
# Sonli javoblarni taqqoslash tolerantligi (Phase 2 — matematik ekvivalentlik)
# ---------------------------------------------------------------------------
# Natural javoblar (√5, 3/7, π/2) son sifatida hisoblanadi va quyidagi
# tolerantlik bilan taqqoslanadi. Standart qiymatlar avvalgi xatti-harakatni
# saqlaydi (mutlaq 1e-6, nisbiy o'chirilgan) — mavjud imtihonlar o'zgarmaydi.
NUMERIC_ABSOLUTE_TOLERANCE: float = _get_float("NUMERIC_ABSOLUTE_TOLERANCE", 1e-6)
NUMERIC_RELATIVE_TOLERANCE: float = _get_float("NUMERIC_RELATIVE_TOLERANCE", 0.0)

# ---------------------------------------------------------------------------
# Test sozlamalari
# ---------------------------------------------------------------------------
QUESTIONS_PER_TEST: int = _get_int("QUESTIONS_PER_TEST", 10) or 10
RESULT_HISTORY_LIMIT: int = 5  # "Mening natijalarim" bo'limida ko'rsatiladigan testlar soni

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: str = (_get_str("LOG_LEVEL", "INFO") or "INFO").upper()

# ---------------------------------------------------------------------------
# Rasch modeli (1PL IRT) sozlamalari
# ---------------------------------------------------------------------------
# θ (theta) qidiruv chegarasi: MLE yechimi [-THETA_BOUND, +THETA_BOUND] ichida izlanadi.
THETA_BOUND: float = _get_float("THETA_BOUND", 3.0)
MLE_START: float = 0.0  # Newton-Raphson uchun boshlang'ich nuqta
MLE_MAX_ITER: int = 100
MLE_TOLERANCE: float = 1e-6

# θ → 0..100 "scaled score" chizig'i
SCALED_MIN: float = 0.0
SCALED_MAX: float = 100.0

# Yakuniy ball shu chegaraga QISILADI — 0 va 100 ko'rinmasligi uchun
# (ishonchlilik). Oddiy ballar TEGILMAYDI, faqat eng chet qiymatlar tekislanadi:
# mukammal (θ→+∞) → SCALED_CAP_MAX, butunlay xato → SCALED_CAP_MIN.
SCALED_CAP_MIN: float = _get_float("SCALED_CAP_MIN", 9.0)
SCALED_CAP_MAX: float = _get_float("SCALED_CAP_MAX", 91.0)


def scaled_span() -> float:
    """1 logit necha scaled-ballga teng (chiziqli o'tkazish koeffitsienti)."""
    return (SCALED_MAX - SCALED_MIN) / (2.0 * THETA_BOUND)