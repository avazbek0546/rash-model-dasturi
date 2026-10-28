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
    DeleteMessage,
    EditMessageText,
    GetMe,
    SendDocument,
    SendMessage,
    SendPhoto,
    SendVideo,
)
from aiogram.types import ReplyKeyboardRemove  # noqa: E402
from aiogram.types import Message, Update  # noqa: E402
from aiogram.types import User as TgUser  # noqa: E402

import config  # noqa: E402
from database.db import Database  # noqa: E402
from database.models import SolutionType, User  # noqa: E402
from database.repository import Repositories  # noqa: E402
from database.seed import seed_questions  # noqa: E402
from handlers import setup_routers  # noqa: E402
from keyboards.inline import AnalysisCallback, AppCallback  # noqa: E402
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
    """`/start` → ism → familiya → inline menyu (pastdagi klaviatura yo'q)."""
    await dp.feed_update(bot, message_update(bot, 1, "/start"))
    first = session.last()
    assert isinstance(first, SendMessage), type(first)
    assert "Ismingizni" in first.text, first.text
    assert first.reply_markup is None, "ro'yxatdan o'tishdan oldin menyu ko'rsatildi"

    await dp.feed_update(bot, message_update(bot, 2, "Aziz"))
    second = session.last()
    assert isinstance(second, SendMessage), type(second)
    assert "Familiyangizni" in second.text, second.text

    await dp.feed_update(bot, message_update(bot, 3, "Karimov"))
    assert any("Ro'yxatdan o'tdingiz" in text for text in session.sent_texts())

    last = session.last()
    assert isinstance(last, SendMessage), type(last)
    assert "Assalomu alaykum" in last.text and "Rasch" in last.text
    assert "Qanday ishlaydi" not in last.text, "eski yo'riqnoma matni qolgan"

    buttons = last.reply_markup.inline_keyboard
    labels = [row[0].text for row in buttons]
    # Admin uchun 7 qator: ilova → natijalar → bo'limlar → admin → yordam.
    assert len(buttons) == 7, labels
    assert labels[0] == "📝 Javoblarni belgilash", labels
    assert labels[1] == "📊 Natijalarim", labels
    assert labels[2:4] == ["🔍 Test tahlili", "🏡 Asosiy menyu"], labels
    web_app_button = buttons[0][0]
    assert web_app_button.web_app is not None, "Web App tugmasi yo'q"
    # Manzilga kesh-buster (`?v=…`) qo'shiladi — shuning uchun prefiks bo'yicha.
    assert web_app_button.web_app.url.startswith("https://exam.example.uz/"), (
        web_app_button.web_app.url
    )
    assert "tab=results" in buttons[1][0].web_app.url, buttons[1][0].web_app.url
    assert labels[4:] == [
        "📋 Imtihonlar ro'yxati",
        "🎬 Yechim yuklash",
        "ℹ️ Yordam",
    ], labels
    assert "➕ Yangi imtihon" not in labels, "«Yangi imtihon» tugmasi qaytib qo'shilgan"

    # Pastdagi (reply) klaviatura olib tashlangan: ReplyKeyboardRemove + delete.
    removals = [
        call
        for call in session.calls
        if isinstance(call, SendMessage) and isinstance(call.reply_markup, ReplyKeyboardRemove)
    ]
    assert removals, "eski reply klaviatura tozalanmadi"
    assert any(isinstance(call, DeleteMessage) for call in session.calls), (
        "tozalash xabari o'chirilmadi"
    )

    user = await repos.users.get(USER_ID)
    assert user is not None, "middleware foydalanuvchini bazaga yozmadi"
    assert user.full_name == FULL_NAME and user.username == "aziz"
    profile = await repos.profiles.get(USER_ID)
    assert profile is not None and profile.full_name == FULL_NAME
    print(
        f"[OK] /start: ism/familiya saqlandi → inline menyu ({len(buttons)} qator) "
        f"+ Web App tugmasi ({web_app_button.web_app.url}); reply klaviatura olib tashlandi"
    )

    await dp.feed_update(bot, callback_update(bot, 4, "app:help"))
    assert any(isinstance(call, AnswerCallbackQuery) for call in session.calls[-2:])
    assert "Mavjud komandalar" in session.sent_texts()[-1]
    print("[OK] «ℹ️ Yordam» tugmasi yordam xabarini yubordi")


async def check_commands(bot, session, dp) -> None:
    """Komandalar, ruxsat nazorati va eskirgan tugmalar."""
    await dp.feed_update(bot, message_update(bot, 20, "/help"))
    assert "Mavjud komandalar" in session.sent_texts()[-1]
    assert "/new_exam" in session.sent_texts()[-1]

    await dp.feed_update(bot, message_update(bot, 21, "/app"))
    app_menu = session.last()
    assert isinstance(app_menu, SendMessage) and "Assalomu alaykum" in app_menu.text
    assert any(
        button.web_app is not None
        for row in app_menu.reply_markup.inline_keyboard
        for button in row
    ), "`/app` Web App tugmasini yubormadi"

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
    # Tasodifiy bosishdan himoya: birinchi bosishda imtihon O'CHMAYDI.
    assert await repos.exams.count() == 1, "tasdiqsiz o'chirildi"
    assert "o'chirish" in session.sent_texts()[-1].lower()
    await dp.feed_update(
        bot, callback_update(bot, 72, f"exam:delete_confirm:{exam.exam_id}")
    )
    assert await repos.exams.count() == 0, "imtihon o'chirilmadi"
    print("[OK] «🗑» tugmasi tasdiqdan keyin o'chirdi (javoblar ham CASCADE)")


async def check_regrade(bot, session, dp, repos) -> None:
    """`/regrade` — kalit tuzatilgach natijalar qayta hisoblanadi."""
    now = exam_service.utc_now()
    exam_id = await repos.exams.create(
        title="Regrade testi",
        test_code="REG01",
        start_time=exam_service.to_db_time(now - timedelta(hours=3)),
        end_time=exam_service.to_db_time(now - timedelta(hours=2)),
        result_time=exam_service.to_db_time(now - timedelta(hours=1)),
        total_questions=4,
        answer_key="1A2B3C4D",
        difficulty_logits=exam_service.difficulties_to_json([0.0, 0.0, 0.0, 0.0]),
        created_by=USER_ID,
    )
    # O'quvchi: 1A 2B 3C 4A → kalit (4D) bo'yicha 4-savol xato → xom ball 3
    await repos.answers.submit(
        user_id=USER_ID, exam_id=exam_id, submitted_answers="1A2B3C4A"
    )

    # 1) Birinchi qayta baholash (hali baholanmagan) — javob hisoblanadi
    await dp.feed_update(bot, message_update(bot, 80, "/regrade REG01"))
    first = session.sent_texts()[-1]
    assert "Qayta baholash bajarildi" in first, repr(first)
    submission = await repos.answers.get(USER_ID, exam_id)
    assert submission is not None and submission.raw_score == 3, submission

    # 2) Kalit tuzatiladi (4-savol: D → A) va YANA qayta baholanadi
    await repos.db.connection.execute(
        "UPDATE exams SET answer_key = ? WHERE exam_id = ?", ("1A2B3C4A", exam_id)
    )
    await repos.db.connection.commit()
    await dp.feed_update(bot, message_update(bot, 81, "/regrade REG01"))
    assert "Qayta baholash bajarildi" in session.sent_texts()[-1]
    submission = await repos.answers.get(USER_ID, exam_id)
    assert submission is not None and submission.raw_score == 4, submission
    print("[OK] /regrade: kalit tuzatilgach natija qayta hisoblandi (3/4 → 4/4)")

    # 3) Noto'g'ri test kodi rad etiladi
    await dp.feed_update(bot, message_update(bot, 82, "/regrade YOQ01"))
    assert "topilmadi" in session.sent_texts()[-1]
    print("[OK] /regrade: noto'g'ri test kodi rad etildi")


async def check_report(bot, session, dp, repos) -> None:
    """`/report TEST_KODI` — natijalar PDF **admin chatiga** yuboriladi."""
    await dp.feed_update(bot, message_update(bot, 90, "/report REG01"))
    documents = [call for call in session.calls if isinstance(call, SendDocument)]
    assert documents, "PDF yuborilmadi"
    filename = getattr(documents[-1].document, "filename", "") or ""
    assert "REG01" in filename, (filename, documents[-1].document)
    print("[OK] /report: PDF admin chatiga yuborildi")

    await dp.feed_update(bot, message_update(bot, 91, "/report YOQ01"))
    assert "topilmadi" in session.sent_texts()[-1]
    print("[OK] /report: noto'g'ri test kodi rad etildi")


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

    # 0) Asosiy menyudagi inline «🔍 Test tahlili» → ro'yxat shu xabarda ochiladi
    await dp.feed_update(
        bot, callback_update(bot, 99, AppCallback(action="analysis").pack())
    )
    inline_list = last_edit(session)
    assert "Test tahlili" in inline_list.text, inline_list.text
    assert any(
        button.text.startswith("📊 ") and "RASHTEST1612" in button.text
        for row in inline_list.reply_markup.inline_keyboard
        for button in row
    ), [b.text for row in inline_list.reply_markup.inline_keyboard for b in row]
    print("[OK] Inline «🔍 Test tahlili»: imtihonlar ro'yxati ochildi")

    # 1) Eski reply tugmasi ham ishlashda davom etadi (moslik)
    await dp.feed_update(bot, message_update(bot, 100, ANALYSIS_BUTTON))
    listing = session.last()
    assert isinstance(listing, SendMessage), type(listing)
    assert "Test tahlili" in listing.text and "Sahifa 1/1" in listing.text, listing.text
    buttons = [row[0].text for row in listing.reply_markup.inline_keyboard]
    assert (
        buttons[0].startswith("📊 ")
        and "RASH EXAM" in buttons[0]
        and "RASHTEST1612" in buttons[0]
    ), buttons
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
    # Yechim ostida «⬅️ Savollar ro'yxati» tugmasi bo'ladi (1.1: oqimga qaytish).
    nav = [button.text for row in videos[-1].reply_markup.inline_keyboard for button in row]
    assert nav[0] == "⬅️ Savollar ro'yxati" and nav[-1] == "🏡 Asosiy menyu", nav
    print("[OK] «❌ 3» tugmasi → video yuborildi + «⬅️ Savollar ro'yxati» tugmasi")

    # 5) Yechimi yo'q savol → ogohlantirish
    await dp.feed_update(
        bot,
        callback_update(
            bot, 105, AnalysisCallback(action="question", exam_id=exam_id, question=4).pack()
        ),
    )
    assert "yechim hali yuklanmagan" in session.sent_texts()[-1], session.sent_texts()[-1]

    # 6) Rasm yechim: izoh bilan yuklash → «✅ 1» tugmasi rasm qaytaradi
    await dp.feed_update(
        bot, photo_update(bot, 106, caption="#rashtest1612-1", file_id="PHOTO-FILE-ID-1")
    )
    assert "rasm yechim muvaffaqiyatli saqlandi" in session.sent_texts()[-1]
    saved_photo = await repos.solutions.get(exam_id, 1)
    assert saved_photo is not None and saved_photo.type is SolutionType.PHOTO
    assert saved_photo.solution_file_id == "PHOTO-FILE-ID-1", saved_photo

    await dp.feed_update(
        bot,
        callback_update(
            bot, 107, AnalysisCallback(action="question", exam_id=exam_id, question=1).pack()
        ),
    )
    photos = [call for call in session.calls if isinstance(call, SendPhoto)]
    assert photos, "rasm yechim yuborilmadi"
    assert photos[-1].photo == "PHOTO-FILE-ID-1", photos[-1].photo
    assert "#javob-rashtest1612-1" in photos[-1].caption, photos[-1].caption
    assert "rasm yechim" in photos[-1].caption, photos[-1].caption
    print("[OK] Rasm yechim: izoh bilan yuklandi + hashtag bilan yuborildi")

    # 6b) Matnli yechim endi qo'llanmaydi: /add_solution faqat yo'riqnoma beradi
    before = await repos.solutions.get(exam_id, 1)
    await dp.feed_update(bot, message_update(bot, 1061, "/add_solution rashtest1612 1 2+2=4"))
    assert "Matnli yechim qo'llanmaydi" in session.sent_texts()[-1], session.sent_texts()[-1]
    after = await repos.solutions.get(exam_id, 1)
    assert after is not None and after.solution_file_id == before.solution_file_id, after
    print("[OK] Matnli yechim olib tashlandi: /add_solution faqat yo'riqnoma beradi")

    # 6c) Qo'llanmaydigan media (audio) → aniq ogohlantirish
    await dp.feed_update(
        bot, audio_update(bot, 1062, caption="#rashtest1612-2", file_id="AUDIO-FILE-2")
    )
    assert "faqat video yoki rasm" in session.sent_texts()[-1], session.sent_texts()[-1]
    assert await repos.solutions.get(exam_id, 2) is None, "audio yechim saqlandi"

    # 6d) PDF hujjat ham yechim emas (faqat rasm/video «fayl sifatida» qabul qilinadi)
    await dp.feed_update(
        bot,
        document_update(
            bot,
            1063,
            caption="#rashtest1612-4",
            file_id="PDF-FILE-4",
            mime_type="application/pdf",
            file_name="yechim.pdf",
        ),
    )
    assert "faqat video yoki rasm" in session.sent_texts()[-1], session.sent_texts()[-1]
    assert await repos.solutions.get(exam_id, 4) is None, "PDF yechim saqlandi"
    print("[OK] Qo'llanmaydigan media (audio, PDF) rad etildi")

    # 7) Admin yuklash yo'riqnomasi: inline tugma va eski reply tugmasi
    await dp.feed_update(
        bot, callback_update(bot, 1081, AppCallback(action="upload").pack())
    )
    assert "Video yoki rasm yechim yuklash" in session.sent_texts()[-1], session.sent_texts()[-1]

    await dp.feed_update(bot, message_update(bot, 108, UPLOAD_SOLUTION_BUTTON))
    assert "Video yoki rasm yechim yuklash" in session.sent_texts()[-1]
    print("[OK] «🎬 Yechim yuklash»: inline va reply tugmalari yo'riqnoma berdi")

    saved_admins = config.ADMIN_IDS
    config.ADMIN_IDS = frozenset()
    try:
        await dp.feed_update(
            bot, video_update(bot, 109, caption="#rashtest1612-2", file_id="VIDEO-NOT-ADMIN")
        )
        assert "Mavjud komandalar" in session.sent_texts()[-1], session.sent_texts()[-1]
        assert await repos.solutions.get(exam_id, 2) is None, "admin bo'lmagan yuklay oldi"

        # Soxta inline callback ham rad etiladi (tugma o'quvchiga ko'rsatilmasa ham).
        await dp.feed_update(
            bot, callback_update(bot, 1091, AppCallback(action="upload").pack())
        )
        alert = [call for call in session.calls if isinstance(call, AnswerCallbackQuery)][-1]
        assert "faqat o'qituvchi" in (alert.text or ""), alert
    finally:
        config.ADMIN_IDS = saved_admins
    print("[OK] Ruxsat nazorati: oddiy o'quvchi video yuklay olmaydi")

    # 7b) Panel deep-link'i: `/start s_<kod>_<belgi>` → IZOH YOZMASDAN yuklash
    await dp.feed_update(bot, start_deep_link_update(bot, 118, "s_RASHTEST1612_2"))
    prompt = session.sent_texts()[-1]
    assert "izoh yozish shart emas" in prompt, prompt
    assert "RASHTEST1612 · 2" in prompt, prompt

    await dp.feed_update(bot, video_update(bot, 119, caption="", file_id="VIDEO-DEEP-2"))
    deep_saved = await repos.solutions.get(exam_id, 2)
    assert deep_saved is not None and deep_saved.solution_file_id == "VIDEO-DEEP-2", deep_saved
    assert deep_saved.type is SolutionType.VIDEO, deep_saved
    print("[OK] Deep-link: «/start s_RASHTEST1612_2» → izohsiz video 2-savolga saqlandi")

    # Deep-link faqat admin uchun: oddiy o'quvchi oddiy menyuni ko'radi
    saved_admins = config.ADMIN_IDS
    config.ADMIN_IDS = frozenset()
    try:
        await dp.feed_update(bot, start_deep_link_update(bot, 120, "s_RASHTEST1612_4"))
        assert "Assalomu alaykum" in session.sent_texts()[-1], session.sent_texts()[-1]
        # Holat yoqilmagani va admin emasligi uchun media qabul qilinmaydi
        await dp.feed_update(bot, video_update(bot, 121, caption="", file_id="VIDEO-NO-TARGET"))
        assert "Mavjud komandalar" in session.sent_texts()[-1], session.sent_texts()[-1]
        assert await repos.solutions.get(exam_id, 4) is None, "admin bo'lmagan deep-link ishladi"
    finally:
        config.ADMIN_IDS = saved_admins
    print("[OK] Deep-link: admin bo'lmagan foydalanuvchida holat yoqilmaydi")

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

    # 9) «🏡 Asosiy menyu» tugmasi asosiy inline menyuni qaytaradi
    await dp.feed_update(bot, callback_update(bot, 113, AnalysisCallback(action="home").pack()))
    home = last_edit(session)
    assert "Assalomu alaykum" in home.text, home.text
    home_labels = [button.text for row in home.reply_markup.inline_keyboard for button in row]
    assert "🔍 Test tahlili" in home_labels, home_labels
    assert "🏡 Asosiy menyu" in home_labels, home_labels
    print("[OK] «🏡 Asosiy menyu» tugmasi inline menyuni qaytardi (reply klaviatura yo'q)")


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
        await check_regrade(bot, session, dp, repos)
        await check_report(bot, session, dp, repos)
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


def start_deep_link_update(bot: Bot, update_id: int, payload: str) -> Update:
    """`/start <payload>` xabarini imitatsiya qiladi (panel deep-link'i).

    Telegram'da `bot_command` entity faqat komandani qamraydi (`/start`) —
    payload undan keyin alohida keladi.
    """
    text = f"/start {payload}"
    message: dict = {
        "message_id": update_id,
        "date": NOW,
        "chat": {"id": USER_ID, "type": "private"},
        "from": USER_JSON,
        "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len("/start")}],
    }
    return Update.model_validate(
        {"update_id": update_id, "message": message}, context={"bot": bot}
    )


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
            "file_size": 5_000_000,
        },
    }
    return Update.model_validate(
        {"update_id": update_id, "message": message}, context={"bot": bot}
    )


def photo_update(bot: Bot, update_id: int, *, caption: str, file_id: str) -> Update:
    """Admin yuborgan rasm xabarni (izohi bilan) imitatsiya qiladi."""
    message: dict = {
        "message_id": update_id,
        "date": NOW,
        "chat": {"id": USER_ID, "type": "private"},
        "from": USER_JSON,
        "caption": caption,
        "photo": [
            {
                "file_id": file_id,
                "file_unique_id": f"unique-{file_id}",
                "width": 1280,
                "height": 960,
                "file_size": 250_000,
            }
        ],
    }
    return Update.model_validate(
        {"update_id": update_id, "message": message}, context={"bot": bot}
    )


def document_update(
    bot: Bot,
    update_id: int,
    *,
    caption: str,
    file_id: str,
    mime_type: str,
    file_name: str,
) -> Update:
    """Admin yuborgan hujjat xabarni imitatsiya qiladi (PDF/DOCX va h.k.)."""
    message: dict = {
        "message_id": update_id,
        "date": NOW,
        "chat": {"id": USER_ID, "type": "private"},
        "from": USER_JSON,
        "caption": caption,
        "document": {
            "file_id": file_id,
            "file_unique_id": f"unique-{file_id}",
            "file_name": file_name,
            "mime_type": mime_type,
            "file_size": 400_000,
        },
    }
    return Update.model_validate(
        {"update_id": update_id, "message": message}, context={"bot": bot}
    )


def audio_update(bot: Bot, update_id: int, *, caption: str, file_id: str) -> Update:
    """Admin yuborgan audio xabarni imitatsiya qiladi (qo'llanmaydigan media)."""
    message: dict = {
        "message_id": update_id,
        "date": NOW,
        "chat": {"id": USER_ID, "type": "private"},
        "from": USER_JSON,
        "caption": caption,
        "audio": {
            "file_id": file_id,
            "file_unique_id": f"unique-{file_id}",
            "duration": 10,
            "file_size": 100_000,
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