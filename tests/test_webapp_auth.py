"""Telegram Web App `initData` tekshiruvi testlari (`services/webapp_auth.py`).

Tekshiriladi:
    1. to'g'ri imzolangan `initData` qabul qilinishi va foydalanuvchi
       ma'lumotlarining to'g'ri o'qilishi;
    2. o'zgartirilgan ma'lumot, boshqa token imzosi va muddati o'tgan
       `initData` rad etilishi;
    3. bo'sh/buzuq kiritishlar va token sozlanmagan holat.

Ishga tushirish:
    python tests/test_webapp_auth.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import webapp_auth  # noqa: E402

TOKEN = "123456789:AATestTokenForUnitChecks"
USER = {
    "id": 42_000_111,
    "first_name": "Zilola",
    "last_name": "Karimova",
    "username": "zilola",
}


def build(fields: dict, token: str = TOKEN) -> str:
    """Imzolangan `initData` satrini yasaydi (Telegram bilan bir xil sxema)."""
    payload = {key: str(value) for key, value in fields.items()}
    payload["hash"] = webapp_auth.compute_hash(payload, token)
    return urlencode(payload)


def expect_error(init_data: str, title: str) -> None:
    """Berilgan `initData` rad etilishini tekshiradi."""
    try:
        webapp_auth.validate_init_data(init_data, TOKEN)
    except webapp_auth.WebAppAuthError as exc:
        print(f"[OK] Rad etildi ({title}): {exc}")
    else:  # pragma: no cover
        raise AssertionError(f"{title}: WebAppAuthError kutilgan edi")


def main() -> None:
    """Testlarni ketma-ket ishga tushiradi."""
    print("=" * 72)
    print("Web App initData tekshiruvi testlari (tarmoqsiz)")
    print("=" * 72)

    now = int(time.time())
    base = {"auth_date": now, "query_id": "AAF123", "user": json.dumps(USER, ensure_ascii=False)}

    payload = webapp_auth.validate_init_data(build(base), TOKEN)
    user = webapp_auth.normalized_user(payload)
    assert user["user_id"] == USER["id"]
    assert user["full_name"] == "Zilola Karimova"
    assert user["username"] == "zilola"
    print(f"[OK] To'g'ri imzo qabul qilindi: {user}")

    solo = {"auth_date": now, "user": json.dumps({"id": 5, "first_name": "Aziz"})}
    solo_user = webapp_auth.normalized_user(webapp_auth.validate_init_data(build(solo), TOKEN))
    assert solo_user["full_name"] == "Aziz" and solo_user["username"] is None
    print("[OK] Faqat first_name bo'lsa ham to'g'ri ism-familiya qurildi")

    expect_error(build(base).replace("zilola", "boshqa"), "foydalanuvchi almashtirilgan")
    expect_error(build(base, "999:WRONG_TOKEN"), "boshqa token bilan imzolangan")

    old = {"auth_date": now - 90_000, "user": json.dumps(USER)}
    expect_error(build(old), "muddati o'tgan")
    assert (
        webapp_auth.validate_init_data(build(old), TOKEN, max_age=0)["auth_date"]
        == old["auth_date"]
    )
    print("[OK] max_age=0 bo'lsa muddat tekshirilmaydi")

    expect_error("", "bo'sh satr")
    expect_error("auth_date=1&user=%7B%7D", "hash yo'q")
    expect_error("hash=abc&auth_date=1", "user yo'q")

    try:
        webapp_auth.validate_init_data(build(base), "")
    except webapp_auth.WebAppAuthError as exc:
        print(f"[OK] Token berilmasa xato: {exc}")
    else:  # pragma: no cover
        raise AssertionError("WebAppAuthError kutilgan edi")

    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    main()
