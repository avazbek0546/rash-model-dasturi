"""To'liq oqim testi: baza → savollar → javoblar → Rasch bahosi → hisobot.

Telegram tokeni talab qilinmaydi: tarmoqqa chiqilmaydi. Tekshiriladi:
    1. jadval yaratilishi va savollarning yuklanishi (seed idempotentligi);
    2. test sessiyasi: javoblar qabul qilinishi, xom ball, o'tkazib yuborilganlar;
    3. Rasch bahosi (θ, SE, 0–100 ball) va natijani bazaga yozish/o'qish;
    4. barcha xabar matnlari: HTML teglar muvozanati va 4096 belgi chegarasi;
    5. handler'lar: import, DI parametrlari va callback data factory'lari.

Ishga tushirish:
    python tests/test_flow.py
"""

from __future__ import annotations

import asyncio
import inspect
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
import texts  # noqa: E402
from database.db import Database  # noqa: E402
from database.models import SKIPPED, TestResult, User, UserStats  # noqa: E402
from database.repository import Repositories  # noqa: E402
from database.seed import SEED_QUESTIONS, seed_questions  # noqa: E402
from services.test_session import TestSessionStore  # noqa: E402

USER_ID = 555_000_111


def check_html(name: str, body: str) -> None:
    """Xabar matnining HTML teglari muvozanatini va uzunligini tekshiradi."""
    for tag in ("b", "i", "code"):
        opened = body.count(f"<{tag}>")
        closed = body.count(f"</{tag}>")
        assert opened == closed, f"{name}: <{tag}> ochilgan {opened}, yopilgan {closed}"
    assert len(body) <= 4096, f"{name}: xabar juda uzun ({len(body)} belgi)"


async def check_database(repos: Repositories) -> list:
    """Baza, seed va savollar tanlovini tekshiradi."""
    added = await seed_questions(repos.questions)
    assert added == len(SEED_QUESTIONS), f"seed: {added} ta savol qo'shildi"
    assert await seed_questions(repos.questions) == 0, "seed ikkinchi marta qo'shildi"
    print(f"[OK] Baza: {await repos.questions.count()} ta savol yuklandi (seed idempotent)")

    await repos.users.upsert(User(user_id=USER_ID, full_name="Aziz Karimov", username="aziz"))
    assert await repos.users.count() == 1
    user = await repos.users.get(USER_ID)
    assert user is not None and user.full_name == "Aziz Karimov"
    print("[OK] Foydalanuvchi bazaga yozildi va o'qildi")

    questions = await repos.questions.pick_random(config.QUESTIONS_PER_TEST)
    assert len(questions) == config.QUESTIONS_PER_TEST, len(questions)
    difficulties = [q.difficulty_b for q in questions]
    assert difficulties == sorted(difficulties), "savollar oson → qiyin tartibda emas"
    assert len({q.question_id for q in questions}) == len(questions), "takroriy savol"
    print(
        f"[OK] Savollar tanlandi: {len(questions)} ta, "
        f"b = {difficulties[0]:+.2f} … {difficulties[-1]:+.2f} (oson → qiyin)"
    )
    return questions


async def check_session(repos: Repositories, questions: list) -> None:
    """Test sessiyasi va Rasch bahosini tekshiradi."""
    store = TestSessionStore()
    session = store.start(USER_ID, questions)

    # Ssenariy: 7 to'g'ri, 1 bilmayman, 2 xato
    plan = ["correct"] * 7 + ["skipped", "wrong", "wrong"]
    while not session.is_finished:
        question = session.current_question
        assert question is not None
        kind = plan[session.answered_count]
        if kind == "correct":
            answer = question.correct_option
        elif kind == "skipped":
            answer = SKIPPED
        else:
            answer = next(
                letter for letter in ("A", "B", "C", "D") if letter != question.correct_option
            )
        assert session.register_answer(question.question_id, answer) is True

    assert session.correct_count == 7, session.correct_count
    assert session.skipped_count == 1, session.skipped_count
    assert store.is_active(USER_ID) is False

    estimate = session.evaluate()
    assert estimate.raw_score == 7 and estimate.total_items == len(questions)
    assert -config.THETA_BOUND <= estimate.theta <= config.THETA_BOUND
    assert 0.0 <= estimate.scaled_score <= 100.0
    assert estimate.standard_error is not None and estimate.standard_error > 0
    assert not estimate.is_extreme, "7/10 uchun chegara holati bo'lmasligi kerak"
    print(
        f"[OK] Rasch bahosi: 7/{len(questions)} → θ = {estimate.theta:+.3f} logit, "
        f"ball = {estimate.scaled_score:.0f}/100, SE = {estimate.standard_error:.2f}"
    )

    saved_id = await repos.results.add(
        TestResult(
            user_id=USER_ID,
            raw_score=estimate.raw_score,
            total_questions=estimate.total_items,
            theta_score=estimate.theta,
            final_scaled_score=estimate.scaled_score,
        )
    )
    assert saved_id > 0
    rows = await repos.results.last_for_user(USER_ID, config.RESULT_HISTORY_LIMIT)
    assert len(rows) == 1
    assert abs(rows[0].theta_score - round(estimate.theta, 4)) < 1e-9
    stats = await repos.results.stats_for_user(USER_ID)
    assert stats.attempts == 1 and stats.best_scaled is not None
    assert await repos.results.count() == 1
    average = await repos.results.average_scaled()
    assert average is not None and abs(average - round(estimate.scaled_score, 2)) < 1e-9
    print("[OK] Natija bazaga yozildi, statistika to'g'ri o'qildi")

    # --- Hisobot matnlari -------------------------------------------------
    welcome = texts.welcome("Aziz Karimov", config.QUESTIONS_PER_TEST)
    check_html("welcome", welcome)
    escaped = texts.welcome("<b>hacker</b>", config.QUESTIONS_PER_TEST)
    assert "&lt;b&gt;hacker&lt;/b&gt;" in escaped, "ism HTML-escape qilinmagan"

    check_html("help", texts.help_text())
    assert "/new_exam" not in texts.help_text(), "o'quvchiga admin komandalari ko'rinyapti"
    assert "/new_exam" in texts.help_text(is_admin=True), "admin yordamida komandalar yo'q"
    check_html("about", texts.about())
    check_html("question", texts.question(1, 10, questions[0], session.progress_bar(), 0))
    check_html("summary", texts.result_summary(estimate, questions, session.answers))

    chunks = texts.result_breakdown(estimate, questions, session.answers)
    assert chunks, "savol-savol tahlil bo'sh"
    for index, chunk in enumerate(chunks, start=1):
        check_html(f"breakdown#{index}", chunk)
    assert "P(θ)" in chunks[0]

    check_html("history", texts.results_history(rows, stats, "Aziz Karimov"))
    check_html("history empty", texts.results_history([], UserStats(), "Aziz"))
    check_html("admin", texts.admin_stats(1, 20, 1, 55.0, 0))
    check_html("no_questions", texts.no_questions())
    print(
        f"[OK] Barcha matnlar yaroqli: HTML muvozanatli, tahlil {len(chunks)} ta "
        f"xabarga bo'lindi (uzunligi {len(chunks[0])} belgi)"
    )


async def check_mle_against_grid(repos: Repositories) -> None:
    """Mustaqil tekshiruv: MLE natijasini to'g'ridan-to'g'ri (brute-force) qidiruv bilan solishtiradi."""
    from services import rasch

    questions = await repos.questions.all()  # qiyinchilik bo'yicha o'sish tartibida
    assert len(questions) >= 15, len(questions)

    # Deterministik javob namunasi: 7 ta eng oson savolga to'g'ri, 1 ta bilmayman,
    # qolganlariga xato javob.
    answers: dict[int, str] = {}
    for index, question in enumerate(questions):
        if index < 7:
            answers[question.question_id] = question.correct_option
        elif index == 7:
            answers[question.question_id] = SKIPPED
        else:
            answers[question.question_id] = next(
                letter for letter in ("A", "B", "C", "D") if letter != question.correct_option
            )

    responses = rasch.build_responses(questions, answers)
    estimate = rasch.estimate_theta(responses)

    # Brute-force: [-3, +3] oralig'ida log-likelihood eng katta bo'lgan nuqta
    steps = 60_001
    low, high = -config.THETA_BOUND, config.THETA_BOUND
    best_theta = low
    best_ll = rasch.log_likelihood(low, responses)
    for step in range(1, steps):
        theta = low + (high - low) * step / (steps - 1)
        value = rasch.log_likelihood(theta, responses)
        if value > best_ll:
            best_theta, best_ll = theta, value

    assert not estimate.is_extreme
    assert abs(best_theta - estimate.theta) < 0.001, (best_theta, estimate.theta)
    assert abs(rasch.gradient(estimate.theta, responses)) < 1e-4
    assert estimate.log_likelihood >= best_ll - 1e-6, "MLE global maksimum emas"
    print(
        f"[OK] Mustaqil tekshiruv ({len(questions)} ta haqiqiy savol): "
        f"Newton-Raphson θ = {estimate.theta:+.4f} ≈ brute-force θ = {best_theta:+.4f}"
    )


def check_handlers(questions: list) -> None:
    """Router'lar, handler DI parametrlari va yangi klaviaturalar."""
    from aiogram import Router

    from handlers import LEGACY_MODULES, setup_routers
    from keyboards.inline import (
        AppCallback,
        ExamAdminCallback,
        exam_confirm_kb,
        webapp_kb,
    )

    def walk(router: Router) -> list[Router]:
        """Router daraxtini rekursiv aylanib chiqadi."""
        found = [router]
        for child in router.sub_routers:
            found.extend(walk(child))
        return found

    root = setup_routers()
    routers = walk(root)
    assert len(routers) >= 6, f"router'lar soni: {len(routers)} (root + 5 ta modul)"

    # Arxivlangan modullar router'ga ULANMAGAN bo'lishi kerak (yangi platforma
    # mantiqi ularning o'rnini egalladi).
    registered = {item.name for item in routers}
    assert set(LEGACY_MODULES) == {"test", "results", "about"}, LEGACY_MODULES
    assert not (set(LEGACY_MODULES) & registered), f"arxiv modullar ulangan: {registered}"

    message_handlers = sum(len(item.observers["message"].handlers) for item in routers)
    callback_handlers = sum(len(item.observers["callback_query"].handlers) for item in routers)
    assert message_handlers >= 6, f"message handler'lari: {message_handlers}"
    assert callback_handlers >= 6, f"callback handler'lari: {callback_handlers}"

    # Handler imzolaridagi DI parametrlari faqat ruxsat etilgan nomlardan iborat
    # bo'lishi kerak (masalan `repos` o'rniga `repositories` yozilsa — xatolik).
    allowed = {
        "message",
        "call",
        "callback_data",
        "state",
        "repos",
        "sessions",
        "bot",
        "dispatcher",
        "event_from_user",
        "event_context",
        "raw_state",
        "fsm_storage",
    }
    checked = 0
    for item in routers:
        for observer in item.observers.values():
            for handler in observer.handlers:
                params = set(inspect.signature(handler.callback).parameters)
                unknown = params - allowed
                assert not unknown, f"{handler.callback.__name__}: noma'lum DI {unknown}"
                checked += 1
    assert checked == message_handlers + callback_handlers, (checked, message_handlers)
    print(
        f"[OK] Handler'lar: {len(routers)} ta router, {message_handlers} ta message + "
        f"{callback_handlers} ta callback; {checked} ta imzo DI nomlari to'g'ri"
    )

    # Callback data factory'lari (prefix va maydonlar mos kelishi)
    assert AppCallback.unpack("app:help").action == "help"
    deleted = ExamAdminCallback.unpack("exam:delete:12")
    assert deleted.action == "delete" and deleted.exam_id == 12
    assert ExamAdminCallback(action="confirm").pack() == "exam:confirm:0"

    # Klaviaturalar: asosiy inline menyu (admin va oddiy o'quvchi uchun farq qiladi).
    # Pastdagi reply klaviatura yo'q — bo'limlar inline menyuga ko'chirilgan.
    admin_markup = webapp_kb(is_admin=True)
    admin_rows = [row[0].text for row in admin_markup.inline_keyboard]
    assert len(admin_markup.inline_keyboard) == 7, admin_rows
    assert admin_rows[0].startswith("📝 Javoblarni belgilash"), admin_rows
    assert admin_rows[1] == "📊 Natijalarim", admin_rows
    assert admin_rows[2:4] == ["🔍 Test tahlili", "🏡 Asosiy menyu"], admin_rows
    assert admin_rows[-1] == "ℹ️ Yordam", admin_rows
    assert all("Yangi imtihon" not in label for label in admin_rows), admin_rows

    user_markup = webapp_kb(is_admin=False)
    user_rows = [row[0].text for row in user_markup.inline_keyboard]
    assert len(user_markup.inline_keyboard) == 5, user_rows
    assert user_rows[0].startswith("📝 Javoblarni belgilash"), user_rows
    assert user_rows[1] == "📊 Natijalarim", user_rows
    assert user_rows[2:4] == ["🔍 Test tahlili", "🏡 Asosiy menyu"], user_rows
    assert user_rows[-1] == "ℹ️ Yordam", user_rows
    assert all("Yechim yuklash" not in label for label in user_rows), user_rows

    confirm = exam_confirm_kb()
    assert len(confirm.inline_keyboard[0]) == 2
    assert "Yaratish" in confirm.inline_keyboard[0][0].text
    assert "Bekor" in confirm.inline_keyboard[0][1].text
    print("[OK] Klaviaturalar: Web App menyusi (admin/o'quvchi) va tasdiqlash tugmalari")


async def check_middleware(repos: Repositories) -> None:
    """`UserSyncMiddleware` ni haqiqiy aiogram `User` obyekti bilan sinaydi.

    Bu tekshiruv `tg_user.user_id` ↔ `tg_user.id` kabi atribut xatolarini
    ushlab qoladi (Telegram `User` da maydon `.id`, bizning modelda `.user_id`).
    """
    from aiogram.types import User as TgUser

    from middlewares import UserSyncMiddleware

    tg_user = TgUser(
        id=777_000_222,
        is_bot=False,
        first_name="Dilnoza",
        last_name="Rustamova",
        username="dilnoza",
    )
    middleware = UserSyncMiddleware()
    calls: list[dict] = []

    async def fake_handler(event, data):  # middleware zanjirining oxiri
        calls.append(data)
        return "ok"

    # 1) Birinchi yangilanish: foydalanuvchi bazaga yozilishi kerak
    result = await middleware(fake_handler, None, {"event_from_user": tg_user, "repos": repos})
    assert result == "ok" and len(calls) == 1

    saved = await repos.users.get(777_000_222)
    assert saved is not None, "middleware foydalanuvchini bazaga yozmadi"
    assert saved.full_name == "Dilnoza Rustamova", saved.full_name
    assert saved.username == "dilnoza"

    # 2) Ism o'zgarmagan — kesh ishlaydi (qayta yozilmaydi)
    await middleware(fake_handler, None, {"event_from_user": tg_user, "repos": repos})
    assert len(middleware._known) == 1, middleware._known  # noqa: SLF001

    # 3) Ism o'zgargan — baza yangilanadi
    renamed = TgUser(
        id=777_000_222,
        is_bot=False,
        first_name="Dilnoza",
        last_name="R.",
        username="dilnoza_new",
    )
    await middleware(fake_handler, None, {"event_from_user": renamed, "repos": repos})
    updated = await repos.users.get(777_000_222)
    assert updated is not None and updated.full_name == "Dilnoza R."
    assert updated.username == "dilnoza_new"

    # 4) Botning o'zi va repos bo'lmagan holat — xatolik bermasligi kerak
    bot_user = TgUser(id=999, is_bot=True, first_name="Bot")
    await middleware(fake_handler, None, {"event_from_user": bot_user, "repos": repos})
    await middleware(fake_handler, None, {"event_from_user": None, "repos": repos})
    assert len(calls) == 5, len(calls)
    print("[OK] Middleware: User.id to'g'ri o'qildi, ism/username yangilandi, kesh ishlaydi")


async def main() -> None:
    """Testlarni ketma-ket ishga tushiradi."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="rasch_flow_"))
    db = Database(tmp_dir / "math_bot_test.db")
    await db.connect()
    repos = Repositories(db)

    print("=" * 72)
    print("To'liq oqim testi (Telegram tokeni talab qilinmaydi)")
    print("=" * 72)
    try:
        questions = await check_database(repos)
        await check_session(repos, questions)
        await check_mle_against_grid(repos)
        await check_middleware(repos)
        check_handlers(questions)
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())