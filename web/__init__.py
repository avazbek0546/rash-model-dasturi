"""Web App (Mini App) HTTP qatlami.

- `api.py`    — `/api/*` endpoint'lari (JSON).
- `server.py` — `aiohttp.web` ilovasini yaratish va ishga tushirish.
"""

from web.server import create_app, start_server, stop_server

__all__ = ["create_app", "start_server", "stop_server"]
