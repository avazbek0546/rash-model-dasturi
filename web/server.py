"""Web App HTTP serveri (`aiohttp.web`).

Ilova uchta vazifani bajaradi:
    1. `webapp/` papkasidagi Mini App fayllarini beradi (`/`, `/static/*`);
    2. `/api/*` JSON endpoint'larini xizmat qiladi (`web/api.py`);
    3. barcha xatoliklarni JSON ko'rinishida qaytaradi.

Serverni `main.py` bot bilan bitta `asyncio` event loop'ida ishga tushiradi:

    runner = await start_server(repos)
    ...
    await stop_server(runner)
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

import config
from database.repository import Repositories
from web import api, api_admin, api_v2

logger = logging.getLogger(__name__)


def create_app(repos: Repositories, *, bot: Any = None) -> web.Application:
    """`aiohttp.web` ilovasini yaratadi (static + API marshrutlari bilan).

    `bot` — ixtiyoriy Telegram bot: berilsa, «Yakunlash»dan keyin o'quvchiga
    natija xabari bot chatiga yuboriladi (`web/api.py`). Testlarda `None`.
    """
    app = web.Application(middlewares=[api.error_middleware])
    app["repos"] = repos
    app["bot"] = bot

    # --- API marshrutlari ---------------------------------------------------
    api.setup_routes(app)      # v1 (o'zgarmagan: /api/verify-code, /api/submit, ...)
    api_v2.setup_routes(app)   # item-level o'quvchi oqimi (/api/v2/*)
    api_admin.setup_routes(app)  # admin paneli (/api/v2/me, /api/v2/admin/*)

    # --- Mini App fayllari --------------------------------------------------
    async def index(request: web.Request) -> web.StreamResponse:
        """Mini App'ning asosiy sahifasi."""
        index_file = config.WEBAPP_DIR / "index.html"
        if not index_file.exists():
            return api.error_response(
                503,
                "Web App fayllari topilmadi (webapp/index.html yo'q). "
                "Loyiha to'liq nusxalanganini tekshiring.",
            )
        # `no-cache` — Telegram WebView Mini App ni qattiq keshlaydi; shu sarlavha
        # tufayli yangilangan sahifa har ochilganda qaytadan olinadi.
        return web.FileResponse(
            index_file,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    app.router.add_get("/", index)
    app.router.add_get("/index.html", index)
    if config.WEBAPP_DIR.exists():
        app.router.add_static("/static/", config.WEBAPP_DIR, name="static")
    else:  # pragma: no cover - fayllar o'chirilgan holat
        logger.warning("Web App papkasi topilmadi: %s", config.WEBAPP_DIR)

    return app


async def start_server(
    repos: Repositories,
    *,
    bot: Any = None,
    host: str | None = None,
    port: int | None = None,
) -> web.AppRunner:
    """Serverni ishga tushiradi va `AppRunner` ni qaytaradi (to'xtatish uchun)."""
    app = create_app(repos, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()

    address = host or config.WEBAPP_HOST
    listen_port = port or config.WEBAPP_PORT
    site = web.TCPSite(runner, address, listen_port)
    await site.start()

    logger.info("Web App server ishga tushdi: http://%s:%d", address, listen_port)
    if config.WEBAPP_URL:
        logger.info("Web App manzili (Telegram uchun): %s", config.WEBAPP_URL)
    else:
        logger.warning(
            "WEBAPP_URL sozlanmagan — bot Web App tugmasini ko'rsatmaydi. "
            "Dev uchun Cloudflare Tunnel/ngrok manzilini .env ga yozing."
        )
    return runner


async def stop_server(runner: web.AppRunner) -> None:
    """Serverni to'xtatadi va resurslarni bo'shatadi."""
    await runner.cleanup()
    logger.info("Web App server to'xtatildi")
