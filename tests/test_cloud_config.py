"""Bulut (Railway) sozlamalari testi — `config.py` avtomatik aniqlashi.

Ishga tushirish:
    python tests/test_cloud_config.py            # pytest kerak emas
    python -m pytest tests/test_cloud_config.py  # pytest o'rnatilgan bo'lsa

Tekshiriladi:
    1. Lokal rejim (Railway o'zgaruvchilari yo'q) — eski xulq saqlanadi:
       `127.0.0.1:8080`, `data/math_bot.db`, `WEBAPP_URL` bo'sh.
    2. Railway rejimi — `PORT`, `RAILWAY_PUBLIC_DOMAIN`,
       `RAILWAY_VOLUME_MOUNT_PATH` avtomatik o'qiladi:
       `0.0.0.0:<PORT>`, `<volume>/math_bot.db`, `https://<domen>`.
    3. Qo'lda berilgan qiymatlar (WEBAPP_URL, DB_PATH, WEBAPP_HOST)
       avtomatik qiymatlardan ustun turadi.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402

# Test davomida o'zgartiriladigan o'zgaruvchilar (oxirida tiklanadi).
_MANAGED = (
    "PORT",
    "DB_PATH",
    "WEBAPP_HOST",
    "WEBAPP_PORT",
    "WEBAPP_URL",
    "RAILWAY_PUBLIC_DOMAIN",
    "RAILWAY_VOLUME_MOUNT_PATH",
    "RAILWAY_SERVICE_ID",
)

# `.env` fayli test qiymatlarini qaytarib yubormasligi uchun bo'sh qiymat
# qo'yiladi (`load_dotenv` mavjud kalitni ustidan yozmaydi).
_CLEARED = ("DB_PATH", "WEBAPP_HOST", "WEBAPP_PORT", "WEBAPP_URL")


def _apply(env: dict[str, str]) -> None:
    """Muhitni tozalaydi, `env` ni o'rnatadi va `config` ni qayta yuklaydi."""
    for name in _MANAGED:
        os.environ.pop(name, None)
    for name in _CLEARED:
        os.environ[name] = ""
    os.environ.update(env)
    importlib.reload(config)


def test_local_defaults() -> None:
    """Railway o'zgaruvchilari yo'q — lokal qiymatlar o'zgarmaydi."""
    _apply({})
    assert config.IS_CLOUD is False
    assert config.WEBAPP_HOST == "127.0.0.1"
    assert config.WEBAPP_PORT == 8080
    assert config.DB_PATH == config.BASE_DIR / "data" / "math_bot.db"
    assert config.WEBAPP_URL == ""
    print("[OK] Lokal rejim: 127.0.0.1:8080, data/math_bot.db, WEBAPP_URL bo'sh")


def test_railway_auto_config() -> None:
    """Railway o'zgaruvchilari avtomatik o'qiladi (qo'lda sozlash shart emas)."""
    _apply(
        {
            "RAILWAY_PUBLIC_DOMAIN": "rash-model.up.railway.app",
            "RAILWAY_VOLUME_MOUNT_PATH": "/data",
            "PORT": "1234",
        }
    )
    assert config.IS_CLOUD is True
    assert config.WEBAPP_HOST == "0.0.0.0"
    assert config.WEBAPP_PORT == 1234
    assert config.DB_PATH == Path("/data/math_bot.db")
    assert config.WEBAPP_URL == "https://rash-model.up.railway.app"
    assert config.WEBAPP_VERSION, "Mini App kesh-buster versiyasi bo'sh bo'lmasligi kerak"
    assert (
        config.webapp_url()
        == f"https://rash-model.up.railway.app/?v={config.WEBAPP_VERSION}"
    )
    print("[OK] Railway rejimi: 0.0.0.0:1234, /data/math_bot.db, HTTPS domen avtomatik")


def test_explicit_values_win() -> None:
    """Qo'lda kiritilgan qiymatlar avtomatik aniqlangandan ustun."""
    _apply(
        {
            "RAILWAY_PUBLIC_DOMAIN": "rash-model.up.railway.app",
            "RAILWAY_VOLUME_MOUNT_PATH": "/data",
            "PORT": "1234",
            "WEBAPP_URL": "https://exam.example.uz/",
            "DB_PATH": "/mnt/custom/db.sqlite",
            "WEBAPP_HOST": "127.0.0.1",
        }
    )
    assert config.WEBAPP_URL == "https://exam.example.uz"  # oxiridagi "/" olib tashlanadi
    assert config.DB_PATH == Path("/mnt/custom/db.sqlite")
    assert config.WEBAPP_HOST == "127.0.0.1"
    assert config.WEBAPP_PORT == 1234  # PORT — platforma kontrakti, ustun turadi
    print("[OK] Qo'lda berilgan WEBAPP_URL/DB_PATH/WEBAPP_HOST ustun turadi")


def _restore() -> None:
    """Testdan keyin muhitni va `config` ni dastlabki holatga qaytaradi."""
    for name in _MANAGED:
        os.environ.pop(name, None)
    importlib.reload(config)


def main() -> int:
    tests = [test_local_defaults, test_railway_auto_config, test_explicit_values_win]
    print("=" * 72)
    print("Bulut (Railway) sozlamalari — o'z-o'zini tekshirish testlari")
    print("=" * 72)
    try:
        for test in tests:
            test()
    finally:
        _restore()
    print("=" * 72)
    print(f"Barcha {len(tests)} ta test muvaffaqiyatli o'tdi ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
