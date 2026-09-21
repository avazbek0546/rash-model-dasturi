"""Botni va Web App serverni birga ishga tushirish nuqtasi (entry point).

Ishga tushirish:
    python main.py

Bitta jarayonda uchta vazifa ishlaydi:
    1. Telegram bot (long polling) — o'qituvchi paneli va Web App tugmasi;
    2. Web App HTTP server (`aiohttp`) — Mini App sahifasi va `/api/*`;
    3. baholash fon vazifasi — muddati tugagan imtihonlarni Rasch modeli
       bo'yicha baholab, natijalarni bazaga yozadi.

Talab: loyiha ildizida `.env` fayli bo'lishi kerak (namuna: `.env.example`),
unda @BotFather bergan `BOT_TOKEN` yozilgan bo'ladi.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonWebApp, WebAppInfo

import config
from database.db import Database
from database.repository import Repositories
from database.seed import seed_questions
from handlers import setup_routers
from middlewares import UserSyncMiddleware
from services import grading
from services.test_session import TestSessionStore
from web.server import start_server, stop_server

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Logging'ni sozlaydi.

    Windows konsoli ko'pincha cp1251 bo'ladi va o'zbekcha matnli loglarda
    UnicodeEncodeError beradi — shu sababli stdout UTF-8 ga o'tkaziladi.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(config.LOG_LEVEL)

    # aiogram har bir yangilanishni DEBUG darajasida yozadi — shovqinni kamaytiramiz
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def set_menu_button(bot: Bot) -> None:
    """Chat menyusidagi tugmani Web App'ga o'rnatadi (imkon bo'lsa).

    Bu bajarilmasa ham bot ishlayveradi — faqat menyu tugmasi ko'rinmaydi.
    """
    if not config.WEBAPP_URL:
        return
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Imtihonlar",
                web_app=WebAppInfo(url=f"{config.WEBAPP_URL}/"),
            )
        )
        logger.info("Menyu tugmasi Web App'ga o'rnatildi")
    except Exception:  # pragma: no cover - tarmoq/Telegram xatosi
        logger.exception("Menyu tugmasini o'rnatib bo'lmadi (muhim emas)")


async def main() -> None:
    """Ishga tushirish ketma-ketligi."""
    setup_logging()

    if not config.BOT_TOKEN or ":" not in config.BOT_TOKEN:
        logger.error(
            "BOT_TOKEN topilmadi yoki noto'g'ri formatda. `.env.example` dan nusxa olib "
            "`.env` fayl yarating va @BotFather bergan tokenni yozing."
        )
        raise SystemExit(1)

    if not config.ADMIN_IDS:
        logger.warning(
            "ADMIN_ID/ADMIN_IDS sozlanmagan — hech kim imtihon yarata olmaydi. "
            "`.env` faylida ADMIN_ID ni ko'rsating."
        )

    # 1) Ma'lumotlar bazasi (jadvallar avtomatik yaratiladi)
    db = Database(config.DB_PATH)
    await db.connect()
    repos = Repositories(db)

    # 2) Eski "mashq rejimi" savollari (arxivdagi oqim uchun — majburiy emas)
    added = await seed_questions(repos.questions)
    if added:
        logger.info("Boshlang'ich %d ta savol yuklandi (mashq rejimi)", added)

    # 3) Bot va dispatcher
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Handler'larga uzatiladigan obyektlar (dependency injection):
    # imzoda `repos: Repositories` yoki `sessions: TestSessionStore` yozilsa,
    # qiymat avtomatik keladi.
    sessions = TestSessionStore()
    dp.workflow_data.update(repos=repos, sessions=sessions)

    # Foydalanuvchilarni bazada saqlash uchun middleware
    dp.update.middleware(UserSyncMiddleware())

    # Router'lar: start → webapp → admin_exam → admin → fallback
    dp.include_router(setup_routers())

    # 4) Web App (Mini App) HTTP serveri — bot bilan bir event loop'da
    runner = await start_server(repos)

    # 5) Baholash fon vazifasi (muddati tugagan imtihonlarni hisoblaydi)
    grading_task = asyncio.create_task(grading.grading_loop(repos), name="grading-loop")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await set_menu_button(bot)
        logger.info(
            "Bot ishga tushdi ✅  |  imtihonlar: %d ta  |  qabul qilingan javoblar: %d ta",
            await repos.exams.count(),
            await repos.answers.count(),
        )
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        logger.error("Telegram 401: BOT_TOKEN noto'g'ri. .env faylidagi tokenni tekshiring.")
        raise SystemExit(1) from None
    finally:
        grading_task.cancel()
        await asyncio.gather(grading_task, return_exceptions=True)
        await stop_server(runner)
        await db.close()
        await bot.session.close()
        logger.info("Bot va Web App server to'xtatildi")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot to'xtatildi (Ctrl+C).")