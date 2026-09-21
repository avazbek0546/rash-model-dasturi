"""Botning TO'LIQ oqimini Telegram'siz sinaydi (soxta session bilan).

Bu test `main.py` dagi kabi Dispatcher + router + middleware zanjirini tuzadi,
so'ng haqiqiy `Update` obyektlarini `dp.feed_update()` orqali uzatadi.
`Bot.session` soxta (FakeSession) bilan almashtirilgani uchun tarmoqqa
chiqilmaydi, lekin barcha handler'lar, filter'lar, FSM, DI, klaviaturalar va
matnlar haqiqiy kod bo'ylab ishlaydi.

Bu testlar aynan quyidagi turdagi xatolarni ushlaydi:
    * noto'g'ri atribut nomlari (masalan `tg_user.user_id` — `.id` o'rniga);
    * handler ichidagi istisnolar (ularni aiogram logga yozadi, lekin
      `feed_update` xato ko'tarmaydi — shu sababli loglar ham tekshiriladi);
    * callback data / state / DI nomuvofiqliklari.

Ishga tushirish:
    python tests/test_bot_flow.py
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.methods import (  # noqa: E402
    AnswerCallbackQuery,
    EditMessageText,
    GetMe,
    SendDocument,
    SendMessage,
    SendPhoto,
    SendVideo,
)
from aiogram.types import Message, Update  # noqa: E402
from aiogram.types import User as TgUser  # noqa: E402

import config  # noqa: E402
from database.db import Database  # noqa: E402
from database.models import SolutionType, User  # noqa: E402
from database.repository import Repositories  # noqa: E402
from database.seed import seed_questions  # noqa: E402
from handlers import setup_routers  # noqa: E402
from keyboards.inline import AnalysisCallback  # noqa: E402
from keyboards.reply import ANALYSIS_BUTTON, UPLOAD_SOLUTION_BUTTON  # noqa: E402
from middlewares import UserSyncMiddleware  # noqa: E402
from services import exam_service  # noqa: E402
from services.test_session import TestSessionStore  # noqa: E402

TOKEN = "123456789:TEST_TOKEN_FOR_OFFLINE_CHECKS"
BOT_ID = 123456789
USER_ID = 555_000_333
FULL_NAME = "Aziz Karimov"
NOW = int(time.time())

USER_JSON = {
    "id": USER_ID,
    "is_bot": False,
    "first_name": "Aziz",
    "last_name": "Karimov",
    "username": "aziz",
}
BOT_JSON = {"id": BOT_ID, "is_bot": True, "first_name": "TestBot", "username": "test_bot"}

# Test sharoiti: joriy foydalanuvchi admin, Web App manzili sozlangan deb olamiz.
config.ADMIN_ID = USER_ID
config.ADMIN_IDS = frozenset({USER_ID})
config.WEBAPP_URL = "https://exam.example.uz"


class FakeSession(BaseSession):
    """Tarmoqsiz session: chaqirilgan API metodlarini yozib boradi."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[object] = []

    async def make_request(self, bot, method, timeout=None):  # type: ignore[override]
        self.calls.append(method)
        return self._result(bot, method)

    def _result(self, bot, method):
        """Metod turiga mos soxta javob qaytaradi (aiogram kutgan formatda)."""
        if isinstance(method, (SendMessage, SendVideo, SendPhoto, SendDocument)):
            return Message.model_validate(
                {
                    "message_id": len(self.calls),
                    "date": NOW,
                    "chat": {"id": method.chat_id, "type": "private"},
                    "from": BOT_JSON,
                    "text": getattr(method, "text", None)
                    or getattr(method, "caption", None)
                    or "",
                },
                context={"bot": bot},
            )
        if isinstance(method, GetMe):
            return TgUser.model_validate(BOT_JSON)
        return True  # EditMessageText, AnswerCallbackQuery, DeleteWebhook, ...

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def close(self) -> None:
        return None

    # -- yordamchilar -------------------------------------------------------
    def last(self) -> object:
        assert self.calls, "Telegram API chaqirilmadi"
        return self.calls[-1]

    def texts_of(self, kind: type) -> list[str]:
        """Berilgan turdagi chaqiruvlarning matnlarini qaytaradi."""
        return [call.text for call in self.calls if isinstance(call, kind)]

    def sent_texts(self) -> list[str]:
        return self.texts_of(SendMessage)


async def check_start_and_menu(bot, session, dp, repos) -> None:
    """`/start` → Web App tugmali menyu → foydalanuvchi bazada."""
    await dp.feed_update(bot, message_update(bot, 1, "/start"))
    last = session.last()
    assert isinstance(last, SendMessage), type(last)
    assert "Assalomu alaykum" in last.text and "Rasch" in last.text

    buttons = last.reply_markup.inline_keyboard
    # Admin uchun: Web App, «Yangi imtihon», «Imtihonlar ro'yxati», «Yordam»
    assert len(buttons) == 4, [row[0].text for row in buttons]
    web_app_button = buttons[0][0]
    assert web_app_button.web_app is not None, "Web App tugmasi yo'q"
    assert web_app_button.web_app.url == "https://exam.example.uz/", web_app_button.web_app.url

    user = await repos.users.get(USER_ID)
    assert user is not None, "middleware foydalanuvchini bazaga yozmadi"
    assert user.full_name == FULL_NAME and user.username == "aziz"
    print(
        f"[OK] /start: Web App tugmasi ({web_app_button.web_app.url}) + admin tugmalari; "
        "foydalanuvchi bazada (middleware ishladi)"
    )

    await dp.feed_update(bot, callback_update(bot, 2, "app:help"))
    assert any(isinstance(call, AnswerCallbackQuery) for call in session.calls[-2:])
    assert "Mavjud komandalar" in session.sent_texts()[-1]
    print("[OK] «ℹ️ Yordam» tugmasi yordam xabarini yubordi")


async def check_commands(bot, session, dp) -> None:
    """Komandalar, ruxsat nazorati va eskirgan tugmalar."""
    await dp.feed_update(bot, message_update(bot, 20, "/help"))
    assert "Mavjud komandalar" in session.sent_texts()[-1]
    assert "/new_exam" in session.sent_texts()[-1]

    await dp.feed_update(bot, message_update(bot, 21, "/app"))
    assert "Web App" in session.sent_texts()[-1]

    # Tanilmagan matnli xabar → yordam + menyu
    await dp.feed_update(bot, message_update(bot, 22, "salom, qalaysiz?"))
    assert "Mavjud komandalar" in session.sent_texts()[-1]

    # /stats (admin) ishlaydi
    await dp.feed_update(bot, message_update(bot, 23, "/stats"))
    stats_text = session.sent_texts()[-1]
    assert "Bot statistikasi" in stats_text and "Imtihonlar" in stats_text

    # /exams — hozircha bo'sh
    await dp.feed_update(bot, message_update(bot, 24, "/exams"))
    assert "imtihon yaratilmagan" in session.sent_texts()[-1]

    # Eskirgan tugma (hech bir handler'ga mos kelmaydi) → ogohlantirish
    await dp.feed_update(bot, callback_update(bot, 25, "ans:1:A"))
    last = session.last()
    assert isinstance(last, AnswerCallbackQuery) and "eskirgan" in last.text, last

    # Ruxsat nazorati: admin ro'yxatidan chiqarilgan foydalanuvchi
    saved = config.ADMIN_IDS
    config.ADMIN_IDS = frozenset({1})
    try:
        await dp.feed_update(bot, message_update(bot, 26, "/new_exam"))
        assert "faqat o'qituvchi" in session.sent_texts()[-1]

        # /stats ruxsatsiz foydalanuvchiga javob bermasligi kerak (eski xatti-harakat)
        before = len(session.calls)
        await dp.feed_update(bot, message_update(bot, 27, "/stats"))
        assert len(session.calls) == before, "ruxsatsiz /stats javob qaytardi"
    finally:
        config.ADMIN_IDS = saved

    print(
        "[OK] Komandalar: /help, /app, fallback, /stats, /exams; "
        "ruxsat nazorati va eskirgan tugma"
    )


async def check_new_exam_wizard(bot, session, dp, repos) -> None:
    """`/new_exam` ustasi: 8 qadam, tekshiruvlar, tasdiqlash, ro'yxat va o'chirish."""
    await dp.feed_update(bot, message_update(bot, 40, "/new_exam"))
    assert "Yangi imtihon yaratish" in session.sent_texts()[-1]

    await dp.feed_update(bot, message_update(bot, 41, "Matematika — nazorat ishi"))
    assert "Test kodini" in session.sent_texts()[-1]

    await dp.feed_update(bot, message_update(bot, 42, "math2026"))
    assert "Savollar sonini" in session.sent_texts()[-1]

    await dp.feed_update(bot, message_update(bot, 43, "3"))
    assert "Javoblar kalitini" in session.sent_texts()[-1]

    await dp.feed_update(bot, message_update(bot, 44, "1A 2B 3C"))
    assert "Qiyinchilik darajalari" in session.sent_texts()[-1]

    await dp.feed_update(bot, message_update(bot, 45, "-"))
    assert "boshlanish vaqti" in session.sent_texts()[-1]

    await dp.feed_update(bot, message_update(bot, 46, "15.01.2027 09:00"))
    assert "tugash vaqti" in session.sent_texts()[-1]

    # Xato: tugash vaqti boshlanishdan oldin
    await dp.feed_update(bot, message_update(bot, 47, "15.01.2027 08:00"))
    assert "keyin bo'lishi kerak" in session.sent_texts()[-1], repr(session.sent_texts()[-1])

    await dp.feed_update(bot, message_update(bot, 48, "15.01.2027 10:30"))
    assert "Natijalar e'lon qilinadigan vaqt" in session.sent_texts()[-1]

    await dp.feed_update(bot, message_update(bot, 49, "15.01.2027 12:00"))
    summary = session.sent_texts()[-1]
    assert "Imtihon ma'lumotlari" in summary and "MATH2026" in summary
    assert "1A2B3C" in summary and "0.0 (barcha 3 savol)" in summary, summary
    assert isinstance(session.last(), SendMessage)
    assert session.last().reply_markup is not None, "tasdiqlash tugmalari yo'q"
    print("[OK] Usta: 8 qadam o'tdi, xulosa va tasdiqlash tugmalari ko'rsatildi")

    await dp.feed_update(bot, callback_update(bot, 50, "exam:confirm:0"))
    created = session.last()
    assert isinstance(created, EditMessageText), type(created)
    assert "Imtihon yaratildi" in created.text and "MATH2026" in created.text

    exam = await repos.exams.get_by_code("MATH2026")
    assert exam is not None, "imtihon bazaga yozilmadi"
    assert exam.total_questions == 3 and exam.answer_key == "1A2B3C"
    assert exam.difficulties == [0.0, 0.0, 0.0], exam.difficulties
    assert exam.created_by == USER_ID
    expected_start = exam_service.to_db_time(exam_service.parse_local_datetime("15.01.2027 09:00"))
    assert exam.start_time == expected_start, exam.start_time
    print(
        f"[OK] Imtihon bazaga yozildi: id={exam.exam_id}, kod={exam.test_code}, "
        f"logitlar={exam.difficulties}, boshlanish={exam.start_time}"
    )

    # Band kod va to'liq bo'lmagan kalit rad etiladi
    await dp.feed_update(bot, message_update(bot, 60, "/new_exam"))
    await dp.feed_update(bot, message_update(bot, 61, "Ikkinchi imtihon"))
    await dp.feed_update(bot, message_update(bot, 62, "MATH2026"))
    assert "allaqachon ishlatilgan" in session.sent_texts()[-1]
    print("[OK] Band test kodi rad etildi")

    await dp.feed_update(bot, message_update(bot, 63, "PHYS01"))
    await dp.feed_update(bot, message_update(bot, 64, "2"))
    await dp.feed_update(bot, message_update(bot, 65, "1A"))
    assert "javob ko'rsatilmagan" in session.sent_texts()[-1]
    print("[OK] To'liq bo'lmagan kalit rad etildi")

    await dp.feed_update(bot, message_update(bot, 66, "/cancel"))
    assert "bekor qilindi" in session.sent_texts()[-1]
    assert await repos.exams.count() == 1, "bekor qilingan imtihon saqlanib qoldi"
    print("[OK] Usta /cancel bilan bekor qilindi (bazaga yozilmadi)")

    # /exams ro'yxati va o'chirish
    await dp.feed_update(bot, message_update(bot, 70, "/exams"))
    listing = session.sent_texts()[-1]
    assert "Imtihonlar ro'yxati" in listing and "MATH2026" in listing
    assert session.last().reply_markup is not None, "o'chirish tugmalari yo'q"
    print("[OK] /exams: ro'yxat va o'chirish tugmasi ko'rsatildi")

    await dp.feed_update(bot, callback_update(bot, 71, f"exam:delete:{exam.exam_id}"))
    assert await repos.exams.count() == 0, "imtihon o'chirilmadi"
    print("[OK] «🗑» tugmasi imtihonni o'chirdi (javoblar ham CASCADE)")


async def check_solution_flow(bot, session, dp, repos) -> None:
    """«🔍 Test tahlili» va video yechim yuklash oqimi (Telegram'siz)."""
    await repos.users.upsert(User(user_id=USER_ID, full_name=FULL_NAME, username="aziz"))

    now = exam_service.utc_now()
    exam_id = await repos.exams.create(
        title="RASH EXAM — 12-fevral",
        test_code="RASHTEST1612",
        start_time=exam_service.to_db_time(now - timedelta(hours=3)),
        end_time=exam_service.to_db_time(now - timedelta(hours=2)),
        result_time=exam_service.to_db_time(now - timedelta(hours=1)),
        total_questions=4,
        answer_key="1A2B3C4D",
        difficulty_logits="[]",
        created_by=USER_ID,
    )
    await repos.answers.submit(user_id=USER_ID, exam_id=exam_id, submitted_answers="1A2B3X4D")

    # 1) Reply menyu tugmasi → natijasi e'lon qilingan imtihonlar ro'yxati
    await dp.feed_update(bot, message_update(bot, 100, ANALYSIS_BUTTON))
    listing = session.last()
    assert isinstance(listing, SendMessage), type(listing)
    assert "Test tahlili" in listing.text and "Sahifa 1/1" in listing.text, listing.text
    buttons = [row[0].text for row in listing.reply_markup.inline_keyboard]
    assert buttons[0].endswith("tahlili") and buttons[0].startswith("📊 RASH EXAM"), buttons
    assert buttons[-1] == "🏡 Asosiy menyu", buttons
    print(f"[OK] «{ANALYSIS_BUTTON}»: ro'yxat tugmasi → «{buttons[0]}»")

    # 2) Imtihon tanlanadi → savollar gridi (✅/❌ belgilari bilan)
    await dp.feed_update(bot, callback_update(bot, 101, AnalysisCallback(action="exam", exam_id=exam_id).pack()))
    grid = last_edit(session)
    assert "Tanlangan testdagi savollarni tanlang" in grid.text, grid.text
    rows = grid.reply_markup.inline_keyboard
    labels = [button.text for row in rows for button in row]
    assert labels[:4] == ["✅ 1", "✅ 2", "❌ 3", "✅ 4"], labels[:4]
    assert labels[-2:] == ["⬅️ Testlar ro'yxati", "🏡 Asosiy menyu"], labels[-2:]
    assert [len(row) for row in rows] == [4, 2], [len(row) for row in rows]
    print(f"[OK] Savollar gridi qatorlarga bo'lindi: {labels}")

    # 3) Admin video yechim yuklaydi (izoh: «#rashtest1612-3»)
    await dp.feed_update(
        bot, video_update(bot, 102, caption="#rashtest1612-3", file_id="VIDEO-FILE-ID-3")
    )
    saved_text = session.sent_texts()[-1]
    assert "RASHTEST1612" in saved_text and "-savoliga" in saved_text, saved_text
    assert "video yechim muvaffaqiyatli saqlandi" in saved_text, saved_text
    saved = await repos.solutions.get(exam_id, 3)
    assert saved is not None and saved.solution_file_id == "VIDEO-FILE-ID-3"
    assert saved.type is SolutionType.VIDEO and saved.created_by == USER_ID
    print("[OK] Admin yukladi: «#rashtest1612-3» → video file_id bazada")

    # Izohdagi format noto'g'ri bo'lsa — yo'riqnoma
    await dp.feed_update(bot, video_update(bot, 103, caption="salom", file_id="VIDEO-BAD"))
    assert "Format tanilmadi" in session.sent_texts()[-1]

    # 4) «❌ 3» tugmasi → video yechim + hashtag
    await dp.feed_update(
        bot,
        callback_update(
            bot, 104, AnalysisCallback(action="question", exam_id=exam_id, question=3).pack()
        ),
    )
    videos = [call for call in session.calls if isinstance(call, SendVideo)]
    assert videos, "video yechim yuborilmadi"
    assert videos[-1].video == "VIDEO-FILE-ID-3", videos[-1].video
    assert "#javob-rashtest1612-3" in videos[-1].caption, videos[-1].caption
    assert "video yechim" in videos[-1].caption
    print("[OK] «❌ 3» tugmasi → video yuborildi, hashtag: #javob-rashtest1612-3")

    # 5) Yechimi yo'q savol → ogohlantirish
    await dp.feed_update(
        bot,
        callback_update(
            bot, 105, AnalysisCallback(action="question", exam_id=exam_id, question=1).pack()
        ),
    )
    assert "yechim hali yuklanmagan" in session.sent_texts()[-1], session.sent_texts()[-1]

    # 6) Matnli yechim: /add_solution → «✅ 1» tugmasi matn qaytaradi
    await dp.feed_update(bot, message_update(bot, 106, "/add_solution rashtest1612 1 2+2=4"))
    assert "matnli yechim muvaffaqiyatli saqlandi" in session.sent_texts()[-1]
    await dp.feed_update(
        bot,
        callback_update(
            bot, 107, AnalysisCallback(action="question", exam_id=exam_id, question=1).pack()
        ),
    )
    text_solution = session.sent_texts()[-1]
    assert "matnli yechim" in text_solution and "#javob-rashtest1612-1" in text_solution
    assert "2+2=4" in text_solution
    print("[OK] Matnli yechim: /add_solution + «#javob-rashtest1612-1» hashtagi")

    # 7) Admin reply tugmasi va huquqsiz foydalanuvchi
    await dp.feed_update(bot, message_update(bot, 108, UPLOAD_SOLUTION_BUTTON))
    assert "Video/media yechim yuklash" in session.sent_texts()[-1]

    saved_admins = config.ADMIN_IDS
    config.ADMIN_IDS = frozenset()
    try:
        await dp.feed_update(
            bot, video_update(bot, 109, caption="#rashtest1612-2", file_id="VIDEO-NOT-ADMIN")
        )
        assert "Mavjud komandalar" in session.sent_texts()[-1], session.sent_texts()[-1]
        assert await repos.solutions.get(exam_id, 2) is None, "admin bo'lmagan yuklay oldi"
    finally:
        config.ADMIN_IDS = saved_admins
    print("[OK] Ruxsat nazorati: oddiy o'quvchi video yuklay olmaydi")

    # 8) Sahifalash: 7 ta imtihon → «Sahifa 1/2 (jami: 7 ta test)»
    for index in range(6):
        extra_id = await repos.exams.create(
            title=f"RASH EXAM #{index + 2}",
            test_code=f"RASHEXTRA{index}",
            start_time=exam_service.to_db_time(now - timedelta(days=index + 1)),
            end_time=exam_service.to_db_time(now - timedelta(days=index + 1) + timedelta(hours=1)),
            result_time=exam_service.to_db_time(now - timedelta(days=index + 1) + timedelta(hours=2)),
            total_questions=2,
            answer_key="1A2B",
            difficulty_logits="[]",
        )
        await repos.answers.submit(
            user_id=USER_ID, exam_id=extra_id, submitted_answers="1A2B"
        )

    await dp.feed_update(bot, message_update(bot, 110, ANALYSIS_BUTTON))
    page_one = session.last()
    assert "Sahifa 1/2 (jami: 7 ta test)" in page_one.text, page_one.text
    assert any(row[0].text == "Keyingi ➡️" for row in page_one.reply_markup.inline_keyboard)

    await dp.feed_update(bot, callback_update(bot, 111, AnalysisCallback(action="page", page=2).pack()))
    page_two = last_edit(session)
    assert "Sahifa 2/2 (jami: 7 ta test)" in page_two.text, page_two.text
    assert any(row[0].text == "⬅️ Oldingi" for row in page_two.reply_markup.inline_keyboard)

    await dp.feed_update(bot, callback_update(bot, 112, AnalysisCallback(action="page", page=1).pack()))
    assert "Sahifa 1/2 (jami: 7 ta test)" in last_edit(session).text
    print("[OK] Sahifalash: «⬅️ Oldingi» / «Keyingi ➡️» va «Sahifa 1/2 (jami: 7 ta test)»")

    # 9) «🏡 Asosiy menyu» tugmasi asosiy menyuni qaytaradi
    await dp.feed_update(bot, callback_update(bot, 113, AnalysisCallback(action="home").pack()))
    home = session.last()
    assert isinstance(home, SendMessage) and "Web App" in home.text, home.text
    print("[OK] «🏡 Asosiy menyu» tugmasi reply + inline menyuni qaytardi")


def last_edit(session):
    """Oxirgi tahrirlangan xabar (EditMessageText) ni qaytaradi."""
    edits = [call for call in session.calls if isinstance(call, EditMessageText)]
    assert edits, "xabar tahrirlanmadi"
    return edits[-1]


async def main() -> None:
    """Dispatcher'ni `main.py` kabi tuzadi va yangilanishlarni tarmoqsiz uzatadi."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_bot_"))
    db = Database(tmp_dir / "bot_test.db")
    await db.connect()
    repos = Repositories(db)
    await seed_questions(repos.questions)

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    session = FakeSession()
    bot.session = session  # tarmoqqa chiqmaslik uchun soxta session

    dp = Dispatcher(storage=MemoryStorage())
    sessions = TestSessionStore()
    dp.workflow_data.update(repos=repos, sessions=sessions)
    dp.update.middleware(UserSyncMiddleware())
    dp.include_router(setup_routers())

    # Handler/middleware ichidagi istisnolar `feed_update` dan yuqoriga ko'tariladi
    # (aiogram ularni faqat pollingda logga yozib davom etadi), qo'shimcha ravishda
    # ERROR loglarini ham yig'ib boramiz — bu boshqa yashirin xatolarni ham tutadi.
    collector = ErrorCollector()
    logging.getLogger().addHandler(collector)
    logging.getLogger().setLevel(logging.WARNING)

    print("=" * 72)
    print("Bot oqimi testi (Telegram'siz, soxta session bilan)")
    print("=" * 72)
    try:
        await check_start_and_menu(bot, session, dp, repos)
        await check_commands(bot, session, dp)
        await check_new_exam_wizard(bot, session, dp, repos)
        await check_solution_flow(bot, session, dp, repos)
    finally:
        await bot.session.close()
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    assert not collector.records, (
        "Handler ichida istisno yuz berdi: " + collector.records[0].getMessage()
    )
    print("=" * 72)
    print(f"Jami {len(session.calls)} ta soxta Telegram API chaqiruvi — xatosiz ✅")
    print("=" * 72)


# Test bloki fayl oxirida (barcha yordamchi funksiyalar aniqlangandan keyin)


class ErrorCollector(logging.Handler):
    """Handler ichidagi istisnolarni (ERROR loglarini) yig'ib boradi."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def message_update(bot: Bot, update_id: int, text: str) -> Update:
    """Foydalanuvchi yuborgan matnli xabarni imitatsiya qiladi."""
    message: dict = {
        "message_id": update_id,
        "date": NOW,
        "chat": {"id": USER_ID, "type": "private"},
        "from": USER_JSON,
        "text": text,
    }
    if text.startswith("/"):
        # Telegram komanda xabarlariga bot_command entity qo'shadi
        message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text)}]
    return Update.model_validate({"update_id": update_id, "message": message}, context={"bot": bot})


def video_update(bot: Bot, update_id: int, *, caption: str, file_id: str) -> Update:
    """Admin yuborgan video xabarni (izohi bilan) imitatsiya qiladi."""
    message: dict = {
        "message_id": update_id,
        "date": NOW,
        "chat": {"id": USER_ID, "type": "private"},
        "from": USER_JSON,
        "caption": caption,
        "video": {
            "file_id": file_id,
            "file_unique_id": f"unique-{file_id}",
            "width": 1280,
            "height": 720,
            "duration": 120,
        },
    }
    return Update.model_validate(
        {"update_id": update_id, "message": message}, context={"bot": bot}
    )


def callback_update(bot: Bot, update_id: int, data: str) -> Update:
    """Inline tugma bosilishini imitatsiya qiladi."""
    return Update.model_validate(
        {
            "update_id": update_id,
            "callback_query": {
                "id": f"cb-{update_id}",
                "from": USER_JSON,
                "chat_instance": "1",
                "data": data,
                "message": {
                    "message_id": update_id,
                    "date": NOW,
                    "chat": {"id": USER_ID, "type": "private"},
                    "from": BOT_JSON,
                    "text": "oldingi xabar",
                },
            },
        },
        context={"bot": bot},
    )


if __name__ == "__main__":
    asyncio.run(main())