"""Telegram Web App (`initData`) ma'lumotlarini tekshirish.

Har bir Web App so'rovi Telegram tomonidan imzolangan `initData` satri bilan
keladi. Uni quyidagi rasmiy sxema bo'yicha tekshiramiz:

    secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    hash       = HMAC_SHA256(key=secret_key,  msg=data_check_string)

`data_check_string` — `hash` dan tashqari barcha maydonlarning "kalit=qiymat"
ko'rinishidagi, kalit bo'yicha alifbo tartibida saralangan va "\n" bilan
ulangan matni.

Bu tekshiruvsiz istalgan odam API'ga boshqa odamning `user_id` sini yozib,
uning nomidan javob yuborishi mumkin bo'lardi — shu sababli tekshiruv
majburiy (faqat `config.WEBAPP_DEV_MODE` yoqilganda chetlab o'tiladi).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import parse_qsl

import config

logger = logging.getLogger(__name__)


class WebAppAuthError(ValueError):
    """`initData` yaroqsiz: imzo noto'g'ri, muddati o'tgan yoki ma'lumot yo'q."""


def secret_key(bot_token: str) -> bytes:
    """Telegram spetsifikatsiyasi bo'yicha `secret_key` ni hisoblaydi."""
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()


def data_check_string(fields: dict[str, str]) -> str:
    """`hash` dan tashqari maydonlardan tekshiruv satrini quradi."""
    return "\n".join(f"{key}={fields[key]}" for key in sorted(fields))


def compute_hash(fields: dict[str, str], bot_token: str) -> str:
    """Berilgan maydonlar uchun kutilgan `hash` ni hisoblaydi (testlar uchun ham)."""
    payload = data_check_string(fields).encode("utf-8")
    return hmac.new(secret_key(bot_token), payload, hashlib.sha256).hexdigest()


def validate_init_data(
    init_data: str,
    bot_token: str | None = None,
    *,
    max_age: int | None = None,
) -> dict[str, Any]:
    """`initData` satrini tekshiradi va ichidagi ma'lumotlarni qaytaradi.

    Args:
        init_data: Telegram Web App bergan xom `initData` satri.
        bot_token: bot tokeni (bo'sh bo'lsa — `config.BOT_TOKEN`).
        max_age: `auth_date` dan keyin o'tishi mumkin bo'lgan maksimal sekund
            (bo'sh bo'lsa — `config.INITDATA_MAX_AGE`; 0 — tekshirilmaydi).

    Qaytaradi:
        {"user": {...}, "auth_date": int, "query_id": str | None, "hash": str}

    Raises:
        WebAppAuthError: imzo mos kelmasa, muddat o'tgan bo'lsa yoki
            foydalanuvchi ma'lumoti bo'lmasa.
    """
    token = bot_token if bot_token is not None else config.BOT_TOKEN
    if not token:
        raise WebAppAuthError("BOT_TOKEN sozlanmagan — initData ni tekshirib bo'lmaydi.")
    if not init_data:
        raise WebAppAuthError("initData bo'sh.")

    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = fields.pop("hash", "")
    if not received_hash:
        raise WebAppAuthError("initData ichida 'hash' maydoni yo'q.")

    expected_hash = compute_hash(fields, token)
    if not hmac.compare_digest(expected_hash, received_hash):
        raise WebAppAuthError("initData imzosi (hash) mos kelmadi.")

    age_limit = config.INITDATA_MAX_AGE if max_age is None else max_age
    raw_auth_date = fields.get("auth_date", "")
    try:
        auth_date = int(raw_auth_date)
    except (TypeError, ValueError) as exc:
        raise WebAppAuthError("initData ichida 'auth_date' yo'q yoki son emas.") from exc

    if age_limit and (time.time() - auth_date) > age_limit:
        raise WebAppAuthError(
            "initData muddati o'tgan — Web App ilovasini qayta oching."
        )

    user_raw = fields.get("user")
    if not user_raw:
        raise WebAppAuthError("initData ichida 'user' maydoni yo'q.")
    try:
        user = json.loads(user_raw)
    except ValueError as exc:
        raise WebAppAuthError("'user' maydoni JSON formatida emas.") from exc
    if not isinstance(user, dict) or "id" not in user:
        raise WebAppAuthError("'user' ma'lumotida 'id' maydoni yo'q.")

    return {
        "user": user,
        "auth_date": auth_date,
        "query_id": fields.get("query_id"),
        "hash": received_hash,
    }


def normalized_user(payload: dict[str, Any]) -> dict[str, Any]:
    """`validate_init_data` natijasidan bazaga yoziladigan foydalanuvchini oladi."""
    user = payload["user"]
    full_name = " ".join(
        part for part in (user.get("first_name"), user.get("last_name")) if part
    ).strip()
    if not full_name:
        full_name = user.get("username") or "Noma'lum"
    return {
        "user_id": int(user["id"]),
        "full_name": full_name,
        "username": user.get("username"),
    }


def identify_user(
    init_data: str | None,
    *,
    debug_user_id: int | None = None,
) -> dict[str, Any]:
    """So'rovdan foydalanuvchini aniqlaydi (dev rejimini hisobga oladi).

    Args:
        init_data: `X-Init-Data` header'i (yoki Authorization: tma ...).
        debug_user_id: `WEBAPP_DEV_MODE=1` bo'lgandagina ishlatiladigan ID
            (lokal brauzerda sinash uchun).

    Raises:
        WebAppAuthError: autentifikatsiya qilib bo'lmasa.
    """
    if config.WEBAPP_DEV_MODE and debug_user_id:
        logger.warning("DEV REJIM: initData o'rniga debug user_id ishlatiladi (%s)", debug_user_id)
        return {
            "user_id": int(debug_user_id),
            "full_name": f"Test foydalanuvchi {debug_user_id}",
            "username": None,
        }
    return normalized_user(validate_init_data(init_data or ""))
