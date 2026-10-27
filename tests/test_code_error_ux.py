"""Mini App'da test kodi xatosi UX'i — regressiya testi.

Muammo (nima uchun bu test bor)
--------------------------------
`webapp/js/queue.js` ichida noto'g'ri kod uchun `App.alert(error.message)`
chaqirilardi, lekin `window.App` da `alert` metodi **yo'q** edi. Xato `catch`
bloki ichida `TypeError` bo'lib yutilib ketardi va o'quvchi **hech narsa**
ko'rmasdi — «bot ishlamayapti» degan taassurot qolardi.

Tekshiriladi
------------
    Statik (JS/HTML/CSS ulanishi):
      1. `App.<metod>(` va `API.<metod>(` chaqiruvlarining BARCHASI
         `window.App` / `window.API` obyektlarida e'lon qilingan bo'lishi
         shart (jim yutilib ketadigan xatolarning oldini oladi).
      2. Kod tekshirish yo'li (`handleVerifyCode`) xatoni maydon yonida
         ko'rsatadi (`showCodeError`) — `App.alert` ga qaytib ketmasin.
      3. `#code-error` (HTML), `.field-error` va `input.code-input.invalid`
         (CSS) mavjud; tugmaning kutish holati (`setVerifying`) bor.

    Jonli (xotiradagi server, tarmoqqa chiqilmaydi):
      4. Noto'g'ri kod → `404` va xabarda kiritilgan kod ko'rsatiladi.
      5. Qisqa kod → `400`; to'g'ri (kichik harf + bo'sh joy) kod → `200`.
      6. `/api/submit` ham xuddi shunday aniq xabarni beradi.

Ishga tushirish:
    python tests/test_code_error_ux.py
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from database.db import Database  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import exam_service, webapp_auth  # noqa: E402
from web.server import create_app  # noqa: E402

JS_DIR = ROOT / "webapp" / "js"
APP_JS = JS_DIR / "app.js"
API_JS = JS_DIR / "api.js"
QUEUE_JS = JS_DIR / "queue.js"
INDEX_HTML = ROOT / "webapp" / "index.html"
STYLE_CSS = ROOT / "webapp" / "css" / "style.css"

#: `App.haptic(` / `API.post(` ko'rinishidagi chaqiruvlar (katta-kichik harf aniq).
CALL_RE = re.compile(r"\b(App|API)\.([A-Za-z_][A-Za-z0-9_]*)\(")

TOKEN = "123456789:AAKhatoXabariTestToken"
USER = {"id": 707_111_222, "first_name": "Nodir", "last_name": "Karimov"}
CODE = "HAXO01"


def read_text(path: Path) -> str:
    """Faylni UTF-8 da o'qiydi."""
    return path.read_text(encoding="utf-8")


def exported_members(source: str, header: str) -> set[str]:
    """`window.App = { … }` obyekt literalining kalitlarini yig'adi."""
    start = source.index(header)
    open_index = source.index("{", start)
    depth = 0
    closing = -1
    for index in range(open_index, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                closing = index
                break
    assert closing > open_index, f"Obyekt literali yopilmadi: {header}"
    return set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", source[open_index:closing]))


def check_js_wiring() -> None:
    """1–3: JS/HTML/CSS ulanishi (statik qo'riqchi)."""
    exported = {
        "App": exported_members(read_text(APP_JS), "window.App = {"),
        "API": exported_members(read_text(API_JS), "window.API = {"),
    }
    used: dict[str, set[str]] = {"App": set(), "API": set()}
    for path in sorted(JS_DIR.glob("*.js")):
        for owner, name in CALL_RE.findall(read_text(path)):
            used[owner].add(name)

    for owner, names in used.items():
        missing = sorted(names - exported[owner])
        assert not missing, (
            f"window.{owner} da e'lon qilinmagan metodlar chaqirilmoqda: {missing} "
            "(bunday xato `catch` bloki ichida jim yutilib ketadi!)"
        )
        print(f"[OK] window.{owner}: {len(names)} ta chaqiruv — barchasi e'lon qilingan")

    # 2) Kod tekshirish yo'li: xato maydon yonida ko'rsatiladi.
    queue = read_text(QUEUE_JS)
    start = queue.index("async function handleVerifyCode")
    body = queue[start : queue.index("\n  async function ", start + 10)]
    assert "showCodeError(" in body, "handleVerifyCode xatoni ko'rsatmaydi"
    assert "App.alert(" not in body, "handleVerifyCode jim yutiladigan App.alert ga qaytgan"
    assert "setVerifying(true)" in body and "finally" in body, (
        "Tugmaning kutish holati (`setVerifying`) yoki `finally` bloki yo'q"
    )
    print("[OK] handleVerifyCode: xato maydon yonida + tugma kutish holati")

    # 3) HTML/CSS ulanishi.
    html = read_text(INDEX_HTML)
    assert 'id="code-error"' in html and 'id="test-code"' in html, (
        "HTML: kod maydoni yoki xato joyi (`#code-error`) yo'q"
    )
    assert "field-error" in html, "HTML: `.field-error` klassi ishlatilmagan"
    css = read_text(STYLE_CSS)
    assert ".field-error" in css and "input.code-input.invalid" in css, (
        "CSS: xato ko'rinishi (`.field-error` / `.code-input.invalid`) yo'q"
    )
    assert 'byId("code-error")' in queue, "JS: `#code-error` elementiga murojaat yo'q"
    print("[OK] HTML/CSS: #code-error, .field-error, input.code-input.invalid joyida")


def build_init_data(user: dict, *, token: str = TOKEN) -> str:
    """Imzolangan `initData` satrini yasaydi (Telegram sxemasi bo'yicha)."""
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-code-error",
        "user": json.dumps(user, ensure_ascii=False),
    }
    payload["hash"] = webapp_auth.compute_hash(payload, token)
    return urlencode(payload)


async def make_exam(repos: Repositories) -> int:
    """Faol oyna ichida imtihon yaratadi (kod: `CODE`)."""
    now = exam_service.utc_now()
    return await repos.exams.create(
        title="Kod xatosi testi",
        test_code=CODE,
        start_time=exam_service.to_db_time(now - timedelta(minutes=5)),
        end_time=exam_service.to_db_time(now + timedelta(minutes=30)),
        result_time=exam_service.to_db_time(now + timedelta(minutes=60)),
        total_questions=3,
        answer_key="1A2B3C",
        difficulty_logits=exam_service.difficulties_to_json([0.0, 0.0, 0.0]),
        created_by=1,
    )


async def check_api(client: TestClient) -> None:
    """4–6: API xabarlari aniq va kiritilgan kodni ko'rsatadi."""
    headers = {"X-Init-Data": build_init_data(USER)}

    response = await client.post(
        "/api/verify-code", headers=headers, json={"test_code": "YOQ123"}
    )
    payload = await response.json()
    assert response.status == 404, (response.status, payload)
    message = payload["error"]
    assert "topilmadi" in message and "YOQ123" in message, message
    print(f"[OK] Noto'g'ri kod → 404: {message}")

    response = await client.post(
        "/api/verify-code", headers=headers, json={"test_code": "ab"}
    )
    payload = await response.json()
    assert response.status == 400, (response.status, payload)
    assert str(config.MIN_TEST_CODE_LENGTH) in payload["error"], payload
    print(f"[OK] Qisqa kod → 400: {payload['error']}")

    response = await client.post(
        "/api/verify-code", headers=headers, json={"test_code": f"  {CODE.lower()} "}
    )
    payload = await response.json()
    assert response.status == 200 and payload["can_submit"] is True, payload
    print(f"[OK] To'g'ri kod (bo'sh joy/kichik harf) → 200: «{payload['title']}»")

    response = await client.post(
        "/api/submit", headers=headers, json={"test_code": "YOQ999", "answers": "1A"}
    )
    payload = await response.json()
    assert response.status == 404 and "YOQ999" in payload["error"], payload
    print(f"[OK] /api/submit ham xuddi shunday: {payload['error']}")


async def main() -> None:
    """Statik va jonli tekshiruvlarni ketma-ket bajaradi."""
    print("=" * 72)
    print("Test kodi xatosi UX testi (Mini App + API)")
    print("=" * 72)

    check_js_wiring()

    config.BOT_TOKEN = TOKEN
    config.WEBAPP_DEV_MODE = False

    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_code_error_"))
    db = Database(tmp_dir / "code_error.db")
    await db.connect()
    repos = Repositories(db)
    try:
        await make_exam(repos)
        app = create_app(repos)
        async with TestClient(TestServer(app)) as client:
            await check_api(client)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Kod xatosi UX tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())

