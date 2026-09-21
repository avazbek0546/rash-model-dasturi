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
# Telegram
# ---------------------------------------------------------------------------
BOT_TOKEN: str = _get_str("BOT_TOKEN")
ADMIN_ID: int | None = _get_int("ADMIN_ID")

# Qo'shimcha administratorlar: ADMIN_IDS="111,222" (vergul bilan ajratiladi).
# ADMIN_ID ham ro'yxatga qo'shiladi. Bo'sh bo'lsa faqat ADMIN_ID admin bo'ladi.
ADMIN_IDS: frozenset[int] = frozenset(
    int(part)
    for part in _get_str("ADMIN_IDS").replace(" ", "").split(",")
    if part.isdigit()
) | ({ADMIN_ID} if ADMIN_ID is not None else set())


def is_admin(user_id: int | None) -> bool:
    """Foydalanuvchi o'qituvchi (admin) huquqiga egami?"""
    return user_id is not None and user_id in ADMIN_IDS

# ---------------------------------------------------------------------------
# Ma'lumotlar bazasi
# ---------------------------------------------------------------------------
DB_PATH: Path = Path(_get_str("DB_PATH") or str(BASE_DIR / "data" / "math_bot.db"))

# ---------------------------------------------------------------------------
# Telegram Web App (Mini App)
# ---------------------------------------------------------------------------
# Web App ochiladigan manzil. Telegram faqat HTTPS manzilni qabul qiladi
# (masalan: https://exam.example.uz yoki dev uchun Cloudflare Tunnel/ngrok).
# Bo'sh bo'lsa — bot Web App tugmasini ko'rsatmaydi, API server esa lokal
# test uchun baribir ishlaydi.
WEBAPP_URL: str = _get_str("WEBAPP_URL").rstrip("/")
WEBAPP_HOST: str = _get_str("WEBAPP_HOST", "127.0.0.1") or "127.0.0.1"
WEBAPP_PORT: int = _get_int("WEBAPP_PORT", 8080) or 8080
WEBAPP_DIR: Path = BASE_DIR / "webapp"
# Faqat lokal ishlab chiqish uchun: initData o'rniga X-Debug-User-Id header'i
# qabul qilinadi. Ishlab chiqarishda (production) HECH QACHON yoqilmasin!
WEBAPP_DEV_MODE: bool = _get_bool("WEBAPP_DEV_MODE", False)
# initData necha sekund "yangi" hisoblanadi (qayta yuborish hujumidan himoya).
INITDATA_MAX_AGE: int = _get_int("INITDATA_MAX_AGE", 86400) or 86400

# ---------------------------------------------------------------------------
# Vaqt va fon vazifalari
# ---------------------------------------------------------------------------
# O'qituvchi vaqtni shu zonada kiritadi/ko'radi; bazada esa hamma vaqt UTC ISO.
TIMEZONE: str = _get_str("TIMEZONE", "Asia/Tashkent") or "Asia/Tashkent"
# Baholash fon vazifasi qancha sekundda bir marta bazani tekshiradi.
GRADING_INTERVAL: int = _get_int("GRADING_INTERVAL", 30) or 30

# ---------------------------------------------------------------------------
# Imtihon parametrlari
# ---------------------------------------------------------------------------
# Test kodi kamida necha belgidan iborat bo'lishi kerak.
MIN_TEST_CODE_LENGTH: int = _get_int("MIN_TEST_CODE_LENGTH", 4) or 4
# Javoblar varag'ida ruxsat etilgan variantlar.
ANSWER_OPTIONS: tuple[str, ...] = ("A", "B", "C", "D")

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


def scaled_span() -> float:
    """1 logit necha scaled-ballga teng (chiziqli o'tkazish koeffitsienti)."""
    return (SCALED_MAX - SCALED_MIN) / (2.0 * THETA_BOUND)