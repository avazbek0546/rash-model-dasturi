"""Botning barcha matnlari (o'zbek tilida, HTML formatda).

Matnlarni bitta joyda saqlash qoidasi: handler'lar ichida uzun matn yozilmaydi.
aiogram `parse_mode=HTML` bilan ishlaydi, shuning uchun <b>, <i>, <code> teglari
ishlatiladi. Foydalanuvchi ismi kabi dinamik matnlar `escape()` orqali
tozalanadi (aks holda Telegram HTML xatosi beradi).
"""

from __future__ import annotations

from html import escape
from typing import Mapping, Sequence

from database.models import SKIPPED, Exam, Participant, Question, TestResult, UserStats
from services import rasch, solutions
from services.rasch import RaschEstimate

SEP = "━━━━━━━━━━━━━━━━━━"

#: Telegram bitta xabari uchun xavfsiz chegara (haqiqiy limit — 4096 belgi).
MESSAGE_LIMIT = 4000


def _sign(value: float) -> str:
    """Musbat songa '+' qo'shadi: +0.42 / -1.10."""
    return f"{value:+.2f}"


def _short(text: str, limit: int = 42) -> str:
    """Uzun savol matnini qisqartiradi (hisobot uchun)."""
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# /start va asosiy menyu
# ---------------------------------------------------------------------------
def welcome(full_name: str, questions_per_test: int) -> str:
    """Bosh menyu matni."""
    return (
        f"👋 <b>Assalomu alaykum, {escape(full_name)}!</b>\n\n"
        "Men matematika bilimini <b>Rasch modeli</b> (Item Response Theory — IRT)\n"
        "asosida baholovchi botman.\n\n"
        f"📝 <b>Test qanday o'tadi?</b>\n"
        f"• Har bir urinishda bazadan <b>{questions_per_test} ta</b> savol tasodifiy tanlanadi;\n"
        "• savollar oson → qiyin tartibida beriladi;\n"
        "• javoblar Inline tugmalar (A, B, C, D) orqali qabul qilinadi.\n\n"
        "📊 <b>Natija nima beradi?</b>\n"
        "• nechta to'g'ri javob berganingiz (xom ball);\n"
        "• Rasch modeli bo'yicha bilim darajangiz <b>θ (theta, logit)</b>;\n"
        "• θ ning aniqligi — standart xato va 95% ishonch oralig'i.\n\n"
        "Kerakli bo'limni tanlang 👇"
    )


def help_text(is_admin: bool = False) -> str:
    """`/help` komandasi matni (rolga mos — o'quvchiga admin komandalari ko'rinmaydi)."""
    lines = [
        "🤖 <b>Mavjud komandalar</b>",
        "",
        "/start — asosiy menyu va ilova tugmasi",
        "/app — imtihon ilovasini ochish",
        "/tahlil — test tahlili va yechimlar",
        "/help — shu yordam xabari",
    ]
    if is_admin:
        lines += [
            "",
            "👨‍🏫 <b>O'qituvchi uchun</b>",
            "/new_exam — yangi imtihon yaratish",
            "/exams — imtihonlar ro'yxati (o'chirish)",
            "/stats — umumiy statistika",
            "/report TEST_KODI — natijalar PDF hisoboti",
            "/add_solution — video/rasm yechim yuklash",
            "/itemstats TEST_KODI — savollar statistikasi",
            "/participants TEST_KODI — qatnashchilar ro'yxati",
            "/admin_chat — qatnashchilar guruhini ulash",
            "/admins — adminlarni qo'shish/o'chirish",
        ]
    lines += [
        "",
        "📊 Natijalar va batafsil tahlil — <b>Mini App</b> ning "
        "«Natijalar» bo'limida.",
        "",
        "ℹ️ Javoblar faqat <b>Web App</b> orqali va belgilangan vaqt oralig'ida "
        "qabul qilinadi. Har bir imtihonga javob <b>bir marta</b> yuboriladi. "
        "Natija Rasch modeli bo'yicha θ (logit), 95% ishonch oralig'i va "
        "sertifikat darajasi ko'rinishida e'lon qilinadi.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Umumiy yordamchilar (yangi matnlar uchun)
# ---------------------------------------------------------------------------
def _safe(value: object) -> str:
    """HTML uchun xavfsiz matn — `'` va `"` o'zgartirilmaydi (o'qishga qulay)."""
    return escape(str(value), quote=False)


# ---------------------------------------------------------------------------
# Imtihon platformasi (Web App) matnlari
# ---------------------------------------------------------------------------
def webapp_welcome(full_name: str, *, webapp_ready: bool) -> str:
    """`/start` matni — qisqa, ruhlantiruvchi kirish (yo'riqnomasiz)."""
    head = (
        f"👋 <b>Assalomu alaykum, {_safe(full_name)}!</b>\n\n"
        "🎯 <b>Bilimingizni sinash va o'sish uchun to'g'ri joydasiz.</b>\n"
        "Har bir test — o'zingizni yaxshiroq tanish va keyingi safar yanada "
        "kuchli chiqish imkoniyati.\n\n"
        "📊 Natijalar <b>Rasch modeli</b> asosida adolatli baholanadi — har bir "
        "savolning qiyinchiligi hisobga olinadi, shu sababli ballingiz haqiqiy "
        "bilimingizni ko'rsatadi.\n"
        "🎬 Har bir savol uchun o'qituvchi <b>video yoki rasm yechim</b> "
        "tayyorlaydi — xatoni tushunib, uni boshqa takrorlamaysiz.\n"
        "📈 Natijalar tarixini kuzatib, o'sishingizni o'zingiz ko'rasiz.\n\n"
        "Boshlash uchun quyidagi bo'limlardan birini tanlang 👇"
    )
    if not webapp_ready:
        return head + (
            "\n\n⚠️ <b>Web App manzili hali sozlanmagan.</b>\n"
            "Administrator <code>WEBAPP_URL</code> ni <code>.env</code> faylida\n"
            "ko'rsatishi kerak (Telegram faqat HTTPS manzilni qabul qiladi)."
        )
    return head


def webapp_button_missing() -> str:
    """Web App tugmasi bosilganda manzil sozlanmagan bo'lsa."""
    return (
        "⚠️ <b>Web App manzili sozlanmagan.</b>\n\n"
        "Administrator <code>.env</code> faylida <code>WEBAPP_URL</code>\n"
        "qiymatini ko'rsatishi kerak (masalan "
        "<code>https://exam.example.uz</code>)."
    )


def ask_first_name() -> str:
    """Birinchi kirishda ism so'raladi."""
    return (
        "👋 <b>Xush kelibsiz!</b>\n\n"
        "Botdan foydalanish va test bo'limiga kirish uchun avval "
        "ro'yxatdan o'tamiz.\n\n"
        "1️⃣ <b>Ismingizni</b> kiriting (masalan: <code>Ali</code>)."
    )


def ask_last_name(first_name: str) -> str:
    """Ism qabul qilingandan keyin familiya so'raladi."""
    return (
        f"Rahmat, <b>{_safe(first_name)}</b>!\n\n"
        "2️⃣ Endi <b>Familiyangizni</b> kiriting "
        "(masalan: <code>Karimov</code>)."
    )


def invalid_name(field: str, reason: str) -> str:
    """Ism/familiya noto'g'ri kiritilganda (maydon nomi va sabab bilan)."""
    return (
        f"⚠️ <b>{_safe(field)}</b> noto'g'ri kiritildi.\n\n"
        f"{_safe(reason)}\n\n"
        "Qaytadan kiriting."
    )


def registration_completed(full_name: str) -> str:
    """Ro'yxatdan o'tish muvaffaqiyatli yakunlanganda."""
    return (
        "✅ <b>Ro'yxatdan o'tdingiz!</b>\n\n"
        f"👤 Ism-familiya: <b>{_safe(full_name)}</b>\n\n"
        "Endi test bo'limiga kirishingiz mumkin 👇"
    )


def registration_save_error() -> str:
    """Profilni bazaga saqlashda kutilmagan xatolik."""
    return (
        "⚠️ Ma'lumotni saqlashda xatolik yuz berdi.\n"
        "Iltimos, qayta urinib ko'ring."
    )


def registration_cancelled() -> str:
    """Ro'yxatdan o'tish bekor qilinganda."""
    return (
        "❌ Ro'yxatdan o'tish bekor qilindi.\n"
        "Davom etish uchun /start buyrug'ini bosing."
    )


def registration_required() -> str:
    """Ro'yxatdan o'tmagan foydalanuvchi test bo'limiga kirishga urinsa."""
    return (
        "🔐 <b>Avval ro'yxatdan o'ting.</b>\n\n"
        "Ism va familiyani kiritish uchun /start buyrug'ini bosing."
    )


def not_admin() -> str:
    """Admin bo'lmagan foydalanuvchi admin komandasini yozsa."""
    return (
        "⛔️ Bu komanda faqat o'qituvchi (admin) uchun.\n"
        "Imtihon topshirish uchun /app buyrug'ini ishlating."
    )


def new_exam_intro() -> str:
    """`/new_exam` ustasining birinchi xabari."""
    return (
        "🆕 <b>Yangi imtihon yaratish</b>\n"
        f"{SEP}\n"
        "Ketma-ket savollarga javob bering. Istalgan paytda <b>/cancel</b>\n"
        "buyrug'i bilan bekor qilishingiz mumkin.\n\n"
        "1️⃣ <b>Imtihon nomini</b> yozing (masalan: «Matematika — 1-bosqich»)."
    )


def ask_test_code(min_length: int) -> str:
    """Test kodi so'raladi."""
    return (
        f"2️⃣ <b>Test kodini</b> yozing (kamida {min_length} belgi, faqat harf va\n"
        "raqamlar). O'quvchilar shu kodni ilovada kiritadi.\n\n"
        "Masalan: <code>MATH2026</code>"
    )


def ask_total_questions() -> str:
    """Savollar soni so'raladi."""
    return "3️⃣ <b>Savollar sonini</b> yozing (butun son, masalan: <code>20</code>)."


def ask_answer_key(total_questions: int) -> str:
    """Javoblar kaliti so'raladi.

    36+ savolli (MVP formasi) imtihonda 33–35 uchun A–F va 36–45 uchun sonli
    javoblar tushuntiriladi. Kichik imtihonlarda matn avvalgidek qoladi.
    """
    if total_questions >= 36:
        return (
            "4️⃣ <b>Javoblar kalitini</b> kiriting.\n\n"
            "• <b>1–32</b> — <code>A</code>…<code>D</code>;\n"
            "• <b>33–35</b> — <code>A</code>…<code>F</code>;\n"
            "• <b>36–45</b> — sonli javob (kalit oxirida, <code>|</code> dan keyin).\n\n"
            f"Format: <code>1A2B…35F|36:12.5,37:3</code> ({total_questions} ta javob).\n"
            "Qismli (a/b) savollar ham mumkin: "
            "<code>1A2B…35F|36a:√5,36b:3/7</code>\n"
            "Eski A–D kaliti ham qabul qilinadi: <code>1A2B3C…</code>"
        )
    return (
        "4️⃣ <b>Javoblar kalitini</b> kiriting — har bir savol uchun to'g'ri variant.\n\n"
        f"Format: <code>1A2B3C…</code> ({total_questions} ta javob bo'lishi shart).\n"
        "Bo'sh joy va tinish belgilari ham qabul qilinadi:\n"
        "<code>1A 2B 3C</code> yoki <code>ABCD</code>."
    )


def ask_difficulties(total_questions: int) -> str:
    """Qiyinchilik **foizda** so'raladi (logit avtomatik hisoblanadi)."""
    return (
        "5️⃣ <b>Qiyinchilik darajalari (foizda)</b> — ixtiyoriy qadam.\n\n"
        "Har bir savolga <b>to'g'ri javob beradigan o'quvchilarning taxminiy "
        "ulushini</b> foizda yozing (sizning bahosingiz):\n\n"
        f"• Bo'sh qoldirsangiz yoki <code>-</code> yozsangiz: barcha "
        f"{total_questions} savol uchun <b>0.0</b> (ma'lumot yo'q);\n"
        "• bitta foiz yozsangiz (masalan <code>75</code>) — u hamma savolga "
        "qo'llanadi;\n"
        f"• yoki {total_questions} ta foizni vergul bilan ajratib yozing:\n"
        "<code>90, 75, 50, 25</code>\n\n"
        "⚙️ Foiz qiyinchilikka <b>avtomatik</b> o'tkaziladi "
        "(<code>b = ln((1−p)/p)</code>):\n"
        "<code>90% → -2.20 · 75% → -1.10 · 50% → 0.00 · 25% → +1.10</code>\n\n"
        "ℹ️ b katta bo'lsa savol qiyin, manfiy bo'lsa oson hisoblanadi.\n"
        "Ilg'or: logitni to'g'ridan-to'g'ri ham yozishingiz mumkin "
        "(<code>-1.1, 0, 1.1</code>), yoki foizni <code>%</code> bilan "
        "belgilang (<code>75%</code>)."
    )


def ask_start_time() -> str:
    """Javob qabul qilish boshlanishi so'raladi."""
    return (
        "6️⃣ <b>Javob qabul qilish boshlanish vaqti</b> (mahalliy vaqt).\n\n"
        "Format: <code>15.01.2026 09:00</code> yoki <code>2026-01-15 09:00</code>"
    )


def ask_end_time() -> str:
    """Javob qabul qilish tugashi so'raladi."""
    return (
        "7️⃣ <b>Javob qabul qilish tugash vaqti</b> (boshlanishdan keyin bo'lishi kerak).\n\n"
        "Masalan: <code>15.01.2026 10:30</code>"
    )


def ask_result_time() -> str:
    """Natijalar e'lon qilinishi so'raladi."""
    return (
        "8️⃣ <b>Natijalar e'lon qilinadigan vaqt</b> (javob qabul qilish tugagach).\n\n"
        "Masalan: <code>15.01.2026 14:00</code>"
    )


def exam_summary(
    *,
    title: str,
    test_code: str,
    total_questions: int,
    answer_key: str,
    difficulties: str,
    start_local: str,
    end_local: str,
    result_local: str,
) -> str:
    """Tasdiqlashdan oldingi xulosa."""
    return (
        "🧾 <b>Imtihon ma'lumotlari</b>\n"
        f"{SEP}\n"
        f"📌 Nomi: <b>{_safe(title)}</b>\n"
        f"🔑 Test kodi: <code>{_safe(test_code)}</code>\n"
        f"❓ Savollar: <b>{total_questions}</b>\n"
        f"🗝 Kalit: <code>{_safe(answer_key)}</code>\n"
        f"📈 Qiyinchilik (foiz → logit): <code>{_safe(difficulties)}</code>\n"
        f"▶️ Boshlanish: {_safe(start_local)}\n"
        f"⏹ Tugash: {_safe(end_local)}\n"
        f"📢 Natija: {_safe(result_local)}\n"
        f"{SEP}\n"
        "Tasdiqlaysizmi?"
    )


def exam_created(
    *,
    exam_id: int,
    title: str,
    test_code: str,
    total_questions: int,
    start_local: str,
    end_local: str,
    result_local: str,
) -> str:
    """Imtihon muvaffaqiyatli yaratilganda."""
    return (
        "✅ <b>Imtihon yaratildi!</b>\n"
        f"{SEP}\n"
        f"🆔 #{exam_id} · <b>{_safe(title)}</b>\n"
        f"🔑 Test kodi: <code>{_safe(test_code)}</code>\n"
        f"❓ Savollar: <b>{total_questions}</b>\n"
        f"▶️ {_safe(start_local)} → ⏹ {_safe(end_local)}\n"
        f"📢 Natijalar: {_safe(result_local)}\n"
        f"{SEP}\n"
        "🔗 <b>Test kodini o'quvchilarga yetkazing.</b> Ular /app orqali\n"
        "ilovani ochib, kodni «Navbat» bo'limida kiritadi.\n\n"
        "📋 Imtihonlar ro'yxati: /exams"
    )


def form_created(
    *,
    form_id: int,
    form_version_id: int,
    version_no: int,
    total_questions: int,
    kinds: dict[str, int],
    session_id: int | None = None,
) -> str:
    """MVP kalit bilan item-level forma yaratilganda qo'shimcha xulosa.

    Ko'rsatiladi: `form_id`, versiya raqami (`version_no`), savollar soni va
    savol turlari statistikasi (`mcq4` / `mcq6` / `numeric`) — form_builder
    `FormBuildResult.kinds` bilan bir xil tartibda.
    """
    stats = " · ".join(
        f"{name}: <b>{int(kinds.get(name, 0))}</b>"
        for name in ("mcq4", "mcq6", "numeric")
    )
    lines = [
        "🧩 <b>Item-level forma yaratildi</b>",
        SEP,
        f"🆔 Forma: <code>{int(form_id)}</code> · versiya: <b>{int(version_no)}</b> "
        f"(<code>{int(form_version_id)}</code>)",
        f"❓ Savollar: <b>{int(total_questions)}</b>",
        f"📊 Turlar: {stats}",
    ]
    if session_id is not None:
        lines.append(f"🗓 Sessiya: <code>{int(session_id)}</code> (exam_sessions)")
    return "\n".join(lines)


def form_build_error(reason: str) -> str:
    """`services.form_builder.FormBuildError` — o'qituvchiga o'zbekcha izoh.

    Matn `texts` da saqlanadi (handler ichida uzun matn yozilmaydi).
    """
    return (
        "⚠️ <b>Item-level formani yaratib bo'lmadi.</b>\n"
        f"{SEP}\n"
        f"{_safe(reason)}\n"
        f"{SEP}\n"
        "Imtihon saqlanmadi. Ma'lumotlarni tuzatib, /new_exam bilan qaytadan "
        "urinib ko'ring."
    )


def exam_list(exams: list[dict]) -> str:
    """Admin uchun imtihonlar ro'yxati.

    Har bir element: exam_id, title, test_code, total_questions, answer_key,
    status_title, start_local, end_local, result_local, submissions.
    """
    if not exams:
        return exams_empty()

    lines = ["📋 <b>Imtihonlar ro'yxati</b>", SEP]
    for item in exams:
        lines.append(
            f"🆔 #{item['exam_id']} · <b>{_safe(item['title'])}</b>\n"
            f"   <i>{_safe(item['status_title'])}</i> · "
            f"{item['submissions']} ta qatnashchi\n"
            f"   🔑 Kod: <code>{_safe(item['test_code'])}</code> · "
            f"{item['total_questions']} savol\n"
            f"   🗝 Kalit: <code>{_safe(item['answer_key'])}</code>\n"
            f"   ▶️ {_safe(item['start_local'])} → ⏹ {_safe(item['end_local'])}\n"
            f"   📢 Natija: {_safe(item['result_local'])}"
        )
    lines.append(SEP)
    lines.append("🗑 O'chirish uchun pastdagi tugmani bosing.")
    lines.append(
        "⏰ Vaqtni o'zgartirish: Mini App → «⚙️ Test yaratish» → «⏰ Vaqt»."
    )
    return "\n".join(lines)


def exams_empty() -> str:
    """Imtihonlar ro'yxati bo'sh bo'lsa."""
    return (
        "📋 <b>Imtihonlar ro'yxati</b>\n"
        f"{SEP}\n"
        "Hozircha imtihon yaratilmagan.\n\n"
        "Yangi imtihon: /new_exam"
    )


def exam_deleted(title: str) -> str:
    """Imtihon o'chirilganda."""
    return (
        f"🗑 <b>«{_safe(title)}»</b> imtihoni va unga tegishli barcha javoblar\n"
        "o'chirildi."
    )


def exam_delete_confirm(*, title: str, test_code: str, submissions: int) -> str:
    """O'chirishdan oldin tasdiqlash (tasodifiy bosishdan himoya)."""
    return (
        "⚠️ <b>Imtihonni o'chirish</b>\n"
        f"{SEP}\n"
        f"📌 {_safe(title)}\n"
        f"🔑 Kod: <code>{_safe(test_code)}</code>\n"
        f"📝 Javoblar: <b>{submissions}</b> ta\n"
        f"{SEP}\n"
        "Bu amal <b>qaytarilmaydi</b> — imtihon va unga tegishli barcha "
        "javoblar o'chadi.\n\n"
        "Davom etishni tasdiqlaysizmi?"
    )


def _submitted_text(value: str | None) -> str:
    """`user_answers.submitted_at` ni qisqa ko'rinishga keltiradi.

    Qiymat SQLite `datetime('now','localtime')` dan keladi — vaqt zonasi
    qo'shimchasiz. Shu sababli uni qayta hisoblamaymiz, faqat `T` ni bo'sh
    joyga almashtiramiz (mavjud natijalar bo'limi bilan bir xil ko'rinish).
    """
    clean = str(value or "").strip().replace("T", " ")
    return clean[:16] if clean else "—"


def _chunks(lines: list[str]) -> list[str]:
    """Qatorlarni Telegram limitidan oshmaydigan xabarlarga bo'ladi."""
    chunks: list[str] = []
    current: list[str] = []
    used = 0
    for line in lines:
        if current and used + len(line) + 1 > MESSAGE_LIMIT:
            chunks.append("\n".join(current))
            current = []
            used = 0
        current.append(line)
        used += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


# ---------------------------------------------------------------------------
# Admin chat va qatnashchilar
# ---------------------------------------------------------------------------
def admin_participant(
    *,
    title: str,
    test_code: str,
    full_name: str,
    username: str | None,
    user_id: int,
    submitted_local: str,
    count: int,
) -> str:
    """Admin chatga keladigan «yangi qatnashchi» xabari."""
    mention = _safe(full_name)
    if username:
        mention += f" (@{_safe(username)})"
    return (
        "👥 <b>Yangi qatnashchi</b>\n"
        f"{SEP}\n"
        f"📌 <b>{_safe(title)}</b>\n"
        f"🔑 Kod: <code>{_safe(test_code)}</code>\n"
        f"👤 {mention}\n"
        f"🆔 <code>{int(user_id)}</code>\n"
        f"🕒 {_safe(submitted_local)}\n"
        f"{SEP}\n"
        f"📊 Bu imtihonda jami: <b>{int(count)}</b> ta qatnashchi"
    )


def participants_chunks(
    *,
    title: str,
    test_code: str,
    participants: Sequence[Participant],
    total_questions: int = 0,
) -> list[str]:
    """`/participants TEST_KODI` — qatnashchilar ro'yxati (bo'laklarga bo'lingan).

    Har bir satr: tartib raqami, ism (@username), Telegram ID, yuborilgan
    vaqt va (baholangan bo'lsa) to'g'ri javoblar soni.
    """
    header = (
        "👥 <b>Qatnashchilar</b>\n"
        f"{SEP}\n"
        f"📌 <b>{_safe(title)}</b>\n"
        f"🔑 Kod: <code>{_safe(test_code)}</code>\n"
        f"👤 Jami: <b>{len(participants)}</b> ta"
    )
    if not participants:
        return [header + f"\n{SEP}\nHozircha hech kim javob yubormagan."]

    lines = [header, SEP]
    for index, item in enumerate(participants, start=1):
        mention = _safe(item.full_name)
        if item.username:
            mention += f" (@{_safe(item.username)})"
        details = [f"🕒 {_safe(_submitted_text(item.submitted_at))}"]
        if item.is_graded:
            details.append(f"✅ {int(item.raw_score or 0)}/{int(total_questions or 0)}")
        lines.append(
            f"{index}. {mention} · <code>{int(item.user_id)}</code>\n"
            f"   " + " · ".join(details)
        )
    lines.append(SEP)
    lines.append(f"📊 Jami: <b>{len(participants)}</b> ta qatnashchi")
    return _chunks(lines)


def participants_exams_chunks(rows: Sequence[Mapping[str, object]]) -> list[str]:
    """`/participants` (kod berilmagan) — testlar va qatnashchilar soni."""
    if not rows:
        return [
            "👥 <b>Qatnashchilar</b>\n"
            f"{SEP}\n"
            "Hozircha imtihon yaratilmagan.\n\n"
            "Yangi imtihon: /new_exam"
        ]

    lines = [
        "👥 <b>Qatnashchilar</b>",
        SEP,
        "Batafsil ro'yxat uchun: <code>/participants TEST_KODI</code>",
        SEP,
    ]
    for row in rows:
        lines.append(
            f"🔑 <code>{_safe(row.get('test_code'))}</code> · "
            f"<b>{_safe(row.get('title'))}</b> — "
            f"<b>{int(row.get('submissions') or 0)}</b> ta qatnashchi"
        )
    return _chunks(lines)


def admin_chat_instructions(current_chat_id: int | None = None) -> str:
    """`/admin_chat` (shaxsiy chat) — admin chatni sozlash yo'riqnomasi."""
    if current_chat_id is not None:
        status = f"✅ Hozirgi admin chat: <code>{int(current_chat_id)}</code>"
    else:
        status = "⚠️ Hozircha admin chat bog'lanmagan."
    return (
        "💬 <b>Admin chat</b>\n"
        f"{SEP}\n"
        f"{status}\n\n"
        "Qatnashchilar haqidagi barcha xabarlar bitta maxsus guruhda "
        "saqlanadi — u yerda kim qatnashgani va jami nechta ekanini "
        "istalgan payt ko'rasiz.\n\n"
        "Sozlash:\n"
        "1️⃣ Telegram'da <b>faqat o'zingiz</b> bo'lgan yangi guruh yarating.\n"
        "2️⃣ Botni guruhga qo'shing va <b>administrator</b> qiling "
        "(«Foydalanuvchilarni chetlatish» huquqi bilan).\n"
        "3️⃣ Guruhda <code>/admin_chat</code> buyrug'ini yuboring.\n\n"
        "Shundan keyin har bir yangi qatnashchi haqida shu guruhga avtomatik "
        "xabar keladi. Admin bo'lmagan odam guruhga qo'shilsa — bot uni "
        "darhol chiqarib yuboradi.\n\n"
        "🔕 Uzish uchun: <code>/admin_chat off</code>"
    )


def admin_chat_bound(title: str, chat_id: int) -> str:
    """Admin chat muvaffaqiyatli bog'langanda."""
    return (
        "✅ <b>Admin chat bog'landi</b>\n"
        f"{SEP}\n"
        f"💬 {_safe(title or 'Guruh')}\n"
        f"🆔 <code>{int(chat_id)}</code>\n\n"
        "Endi har bir yangi qatnashchi haqida shu chatga xabar keladi. "
        "Guruhga faqat adminlar kira oladi — bot qolganlarini chiqarib "
        "yuboradi.\n\n"
        "Ro'yxatni botda ham ko'rish: <code>/participants TEST_KODI</code>"
    )


def admin_chat_unbound() -> str:
    """Admin chat uzilganda."""
    return (
        "🔕 <b>Admin chat uzildi.</b>\n"
        "Endi yangi qatnashchilar haqidagi xabarlar guruhga yuborilmaydi.\n\n"
        "Qayta ulash: <code>/admin_chat</code>"
    )


def admin_chat_group_only() -> str:
    """`/admin_chat` guruhdan tashqarida chaqirilganda (masalan kanal)."""
    return (
        "ℹ️ Admin chatni ulash uchun buyruqni <b>guruhda</b> yuboring.\n\n"
        "Guruh yarating → botni administrator qiling → guruhda "
        "<code>/admin_chat</code> yozing."
    )


def admin_chat_group_admin_required() -> str:
    """Buyruqni yuborgan odam guruh administratori bo'lmasa."""
    return (
        "⛔ Guruhni admin chatga bog'lash uchun avval o'zingiz guruh "
        "administratori bo'lishingiz kerak."
    )


def admin_chat_restrict_warning() -> str:
    """Botda «Foydalanuvchilarni chetlatish» huquqi bo'lmasa."""
    return (
        "⚠️ <b>Diqqat:</b> botda «Foydalanuvchilarni chetlatish» huquqi yo'q.\n"
        "Guruh sozlamalari → Administratorlar → bot → "
        "<b>«Foydalanuvchilarni chetlatish»</b> ni yoqing. Aks holda begona "
        "odamlar avtomatik chiqarilmaydi (qatnashchilar xabarlari baribir "
        "keladi)."
    )


def admin_chat_bot_admin_required() -> str:
    """Bot guruh administratori bo'lmasa."""
    return (
        "⚠️ Avval botni guruh <b>administratori</b> qiling "
        "(«Foydalanuvchilarni chetlatish» huquqi bilan), keyin "
        "<code>/admin_chat</code> ni qayta yuboring."
    )


def admin_chat_kicked(full_name: str) -> str:
    """Admin chatdan admin bo'lmagan odam chiqarilganda."""
    return (
        "🚫 <b>Ruxsat yo'q</b>\n"
        f"{_safe(full_name)} adminlar ro'yxatida yo'q — guruhdan "
        "chiqarildi.\n\n"
        "Kirish faqat o'qituvchi (admin) uchun."
    )


def wizard_cancelled() -> str:
    """Usta bekor qilinganda."""
    return "❌ Imtihon yaratish bekor qilindi."


def input_error(reason: str) -> str:
    """Kiritilgan qiymat noto'g'ri bo'lganda (sabab bilan)."""
    return f"⚠️ {_safe(reason)}\n\nQaytadan kiriting yoki /cancel bilan bekor qiling."



def about() -> str:
    """Rasch modeli haqida tushuntirish."""
    return (
        "ℹ️ <b>Rasch modeli haqida</b>\n\n"
        "🧮 <b>Asosiy g'oya</b>\n"
        "Har bir o'quvchining <b>bilim darajasi θ</b> (theta, logitda) va har bir\n"
        "savolning <b>qiyinchiligi b</b> (logitda) bitta o'lchovda ifodalanadi.\n"
        "O'quvchining savolga to'g'ri javob berish ehtimoli:\n\n"
        "<code>P(θ) = 1 / (1 + e^(−(θ − b)))</code>\n\n"
        "• θ = b bo'lsa, to'g'ri javob ehtimoli aynan <b>50%</b>;\n"
        "• b katta bo'lsa (qiyin savol) — to'g'ri javob ko'proq ma'lumot beradi;\n"
        "• oson savolga xato javob berish θ ni pasaytiradi.\n\n"
        "📐 <b>Nega bu oddiy foizdan yaxshiroq?</b>\n"
        "1. <b>5/10</b> ning ma'nosi savollar qiyinligiga bog'liq: oson to'plamda\n"
        "   θ ≈ −1.6, qiyin to'plamda esa θ ≈ +1.4 bo'ladi.\n"
        "2. Har bir baho <b>standart xato (SE)</b> bilan beriladi — natija qanchalik\n"
        "   ishonchli ekanini bilasiz.\n"
        "3. Test qiyinligi o'quvchi darajasiga mos kelganda o'lchov aniqligi oshadi.\n\n"
        "⚙️ <b>Qanday hisoblanadi?</b>\n"
        "Javoblar asosida maksimal ishonchlilik (MLE) bahosi <b>Newton-Raphson</b>\n"
        "usulida topiladi:\n\n"
        "<code>θ ← θ + Σ(u − P) / Σ P(1 − P)</code>\n\n"
        "Natija asosan <b>sertifikat bali (0–100)</b> va uning <b>95% ishonch\n"
        "oralig'i</b> ko'rinishida ko'rsatiladi; qo'shimcha ravishda θ (logit),\n"
        "xom ball, sertifikat darajasi (NC … A+), algebra va geometriya ballari\n"
        "beriladi. Bu 0–100 — oddiy foiz emas: u θ dan o'tkaziladi va savollar\n"
        "qiyinchiligini hisobga oladi.\n\n"
        "⚠️ <b>Muhim izoh:</b> bu loyihada savollarning qiyinchiligi (b) o'qituvchi\n"
        "tomonidan oldindan belgilangan (muallif bahosi). To'liq rasmiy IRT\n"
        "tahlilida b parametrlari katta guruh javoblari asosida statistik\n"
        "baholanadi (calibration) — buni keyinchalik qo'shish mumkin."
    )


# ---------------------------------------------------------------------------
# Test jarayoni
# ---------------------------------------------------------------------------
def question(index: int, total: int, question: Question, progress: str, answered: int) -> str:
    """Bitta savol kartochkasi.

    Diqqat: test paytida savolning qiyinchiligi (b) ko'rsatilmaydi — bu
    o'quvchining javobiga ta'sir qilmasligi uchun (item cue bias).
    """
    options = question.options()
    options_block = "\n".join(
        f"<b>{letter})</b> {_safe(text)}" for letter, text in options.items()
    )
    topic = f"📚 {_safe(question.topic)}\n" if question.topic else ""
    return (
        f"📝 <b>Savol {index} / {total}</b>\n"
        f"{progress}  <i>({answered} ta javob berildi)</i>\n"
        f"{SEP}\n"
        f"{topic}"
        f"<b>{_safe(question.question_text)}</b>\n\n"
        f"{options_block}\n"
        f"{SEP}\n"
        "👇 To'g'ri javobni tanlang:"
    )


def skipped_notice() -> str:
    """"Bilmayman" bosilganda ko'rsatiladigan qisqa izoh."""
    return "❓ Javob «bilmayman» deb belgilandi (xom ballda 0 hisoblanadi)."


# ---------------------------------------------------------------------------
# Natija
# ---------------------------------------------------------------------------
def _extreme_note(estimate: RaschEstimate) -> str:
    """Chekka holatlar uchun izoh (MLE chegarada)."""
    if not estimate.is_extreme:
        return ""
    bound = f"{abs(estimate.theta):.1f}"
    if estimate.raw_score == estimate.total_items:
        return (
            f"⚠️ Barcha savollarga to'g'ri javob berdingiz. Bunday holatda MLE "
            f"cheksizlikka intiladi, shuning uchun θ shkala chegarasida "
            f"(+{bound} logit) qabul qilindi.\n\n"
        )
    if estimate.raw_score == 0:
        return (
            f"⚠️ Barcha savollarga xato javob berdingiz (yoki javob bermadingiz). "
            f"Bunday holatda MLE cheksizlikka intiladi, shuning uchun θ shkala "
            f"chegarasida (−{bound} logit) qabul qilindi.\n\n"
        )
    return (
        f"⚠️ Natija shkala chegarasiga yaqin (θ = {_sign(estimate.theta)} logit) — "
        f"haqiqiy daraja bundan ham yuqori/pastroq bo'lishi mumkin.\n\n"
    )


def _consistency_note(questions: list[Question], answers: dict[int, str]) -> str:
    """Javoblar izchilligini baholaydi: to'g'ri va xato savollar qiyinligi."""
    correct_b = [
        q.difficulty_b for q in questions if q.is_correct(answers.get(q.question_id))
    ]
    wrong_b = [
        q.difficulty_b for q in questions if not q.is_correct(answers.get(q.question_id))
    ]
    if not correct_b or not wrong_b:
        return ""

    avg_correct = sum(correct_b) / len(correct_b)
    avg_wrong = sum(wrong_b) / len(wrong_b)
    line = (
        f"• To'g'ri yechgan savollaringiz o'rtacha qiyinligi: "
        f"<b>{_sign(avg_correct)}</b> logit\n"
        f"• Xato qilgan savollaringiz o'rtacha qiyinligi: "
        f"<b>{_sign(avg_wrong)}</b> logit\n"
    )
    if avg_correct >= avg_wrong:
        return line + "• Natija izchil: qiyinroq savollarni osonlaridan yaxshiroq yechdingiz. ✅\n"
    return (
        line
        + "• Diqqat: xato qilgan savollaringiz to'g'ri yechganlaridan yengilroq. "
        "Bu beparvolik yoki tasodifiy taxmin belgisi bo'lishi mumkin. ⚠️\n"
    )


def result_summary(
    estimate: RaschEstimate,
    questions: list[Question],
    answers: dict[int, str],
) -> str:
    """Test yakunidagi asosiy natija va uning Rasch bo'yicha izohi."""
    skipped = sum(
        1 for q in questions if answers.get(q.question_id, SKIPPED).upper() == SKIPPED
    )
    level = rasch.ability_level(estimate.scaled_score)
    interval = estimate.theta_interval
    interval_line = (
        "• 95% ishonch oralig'i: "
        f"<b>{_sign(interval[0])} … {_sign(interval[1])}</b> logit\n"
        if interval
        else ""
    )
    se_line = (
        f"• Standart xato (SE): {estimate.standard_error:.2f} logit\n"
        if estimate.standard_error is not None
        else ""
    )
    skipped_line = f"• Bilmayman / javobsiz: {skipped} ta\n" if skipped else ""

    return (
        "📊 <b>Test yakunlandi!</b>\n"
        f"{SEP}\n"
        f"✅ To'g'ri javoblar (xom ball): <b>{estimate.raw_score} / {estimate.total_items}</b>"
        f"  ({estimate.correct_ratio * 100:.0f}%)\n"
        f"{skipped_line}"
        f"🎯 Bilim darajasi (θ): <b>{_sign(estimate.theta)} logit</b>\n"
        f"{se_line}"
        f"{interval_line}"
        f"🏅 Daraja: <b>{level}</b>\n"
        f"{SEP}\n"
        f"{_extreme_note(estimate)}"
        "🧠 <b>Bu raqamlar nimani bildiradi?</b>\n"
        f"Sizning θ = {_sign(estimate.theta)} logit. Bu shuni bildiradiki, siz "
        f"qiyinchiligi b ≈ {_sign(estimate.theta)} bo'lgan savolga <b>50%</b> "
        "ehtimol bilan to'g'ri javob berasiz. Qiyinroq savollar (b kattaroq) "
        "ehtimolini kamaytiradi, osonroq savollar — oshiradi.\n\n"
        "<b>Qanday hisoblandi?</b> Har bir javob P(θ) = 1/(1+e^(−(θ−b))) ehtimoli "
        "bilan taqqoslandi va θ maksimal ishonchlilik (MLE, Newton-Raphson) usulida "
        f"topildi (iteratsiyalar: {estimate.iterations}, yaqinlashdi: "
        f"{'ha' if estimate.converged else 'chegara holati'}).\n\n"
        "📈 <b>Javoblaringiz sifati</b>\n"
        f"{_consistency_note(questions, answers)}"
        f"{SEP}\n"
        f"💡 <b>Tavsiya:</b> {rasch.level_advice(estimate.scaled_score)}\n\n"
        "Batafsil savol-savol tahlil quyidagi xabarda 👇"
    )


def result_breakdown(
    estimate: RaschEstimate,
    questions: list[Question],
    answers: dict[int, str],
    max_length: int = 3200,
) -> list[str]:
    """Har bir savol bo'yicha tahlil. Xabar 4096 belgidan oshmasligi uchun
    natija bir nechta xabarga bo'lib qaytariladi."""
    messages: list[str] = []
    current = "📋 <b>Savollar tahlili</b>\n" + SEP + "\n"

    for index, question in enumerate(questions, start=1):
        answer = answers.get(question.question_id)
        is_correct = question.is_correct(answer)
        p_correct = rasch.probability(estimate.theta, question.difficulty_b)
        difficulty_text = rasch.difficulty_label(question.difficulty_b)

        if is_correct:
            mark = "✅"
            given = f"javobingiz: <b>{answer}</b>"
        elif answer is None or answer.upper() == SKIPPED:
            mark = "⬜️"
            given = "javobingiz: <i>bilmayman</i>"
        else:
            mark = "❌"
            given = f"javobingiz: <b>{answer}</b> · to'g'ri javob: <b>{question.correct_option}</b>"

        block = (
            f"\n{index}. {mark} <b>{_safe(_short(question.question_text))}</b>\n"
            f"   {given}\n"
            f"   b = {_sign(question.difficulty_b)} ({difficulty_text}) · "
            f"P(θ) = {p_correct * 100:.0f}%\n"
        )

        if len(current) + len(block) > max_length:
            messages.append(current)
            current = "📋 <b>Savollar tahlili (davomi)</b>\n" + SEP + "\n"
        current += block

    current += (
        f"{SEP}\n"
        "📌 <b>Belgilar:</b> b — savol qiyinchiligi (logit); "
        f"P(θ) — sizning darajangizda (θ = {_sign(estimate.theta)}) shu savolga "
        "to'g'ri javob berish ehtimoli.\n"
        "💡 Ya'ni P(θ) qanchalik kichik bo'lsa, siz shu savolni yechib "
        "kutilmagan (yaxshi) natija ko'rsatgansiz."
    )
    messages.append(current)
    return messages


# ---------------------------------------------------------------------------
# Mening natijalarim
# ---------------------------------------------------------------------------
def results_history(
    results: list[TestResult],
    stats: UserStats,
    full_name: str,
) -> str:
    """O'quvchining oxirgi natijalari va umumiy statistikasi."""
    if not results:
        return (
            f"📊 <b>Mening natijalarim</b>\n{SEP}\n"
            f"👤 {_safe(full_name)}\n\n"
            "Siz hali test topshirmagansiz.\n"
            "Boshlash uchun bosh menyudagi «📝 Testni boshlash» tugmasini bosing."
        )

    lines = [
        "📊 <b>Mening natijalarim</b>",
        SEP,
        f"👤 {_safe(full_name)}",
        f"🎯 Urinishlar soni: <b>{stats.attempts}</b>",
        "🏆 Eng yaxshi natija: <b>"
        + (
            f"θ = {_sign(stats.best_theta)} logit"
            if stats.best_theta is not None
            else "—"
        )
        + "</b>",
        f"✅ Jami to'g'ri javoblar: <b>{stats.total_correct} / {stats.total_questions}</b>"
        + (
            f" ({100 * stats.total_correct / stats.total_questions:.0f}%)"
            if stats.total_questions
            else ""
        ),
        SEP,
        "<b>Oxirgi urinishlar:</b>",
    ]

    for index, result in enumerate(results, start=1):
        theta = _sign(result.theta_score)
        date = (result.date or "")[:16]
        level = rasch.ability_level(result.final_scaled_score)
        lines.append(
            f"{index}. {date} — {result.raw_score}/{result.total_questions} · "
            f"θ = {theta} logit · <b>{level}</b>"
        )

    lines.append(SEP)
    lines.append(
        "📌 Eslatma: bir xil xom ball turli testlarda turli θ berishi mumkin — "
        "buni savollar to'plamining qiyinligi belgilaydi."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Admin statistikasi
# ---------------------------------------------------------------------------
def admin_stats(
    users: int,
    questions: int,
    attempts: int,
    average_theta: float | None,
    active_sessions: int,
    exams: int = 0,
    submissions: int = 0,
    solution_files: int = 0,
) -> str:
    """`/stats` komandasi uchun umumiy statistika (0–100 shkala ko'rsatilmaydi)."""
    average_line = (
        f"📈 O'rtacha θ (mashq rejimi): <b>{_sign(average_theta)} logit</b>"
        if average_theta is not None
        else "📈 O'rtacha θ (mashq rejimi): —"
    )
    submissions_line = (
        f"📥 Imtihonlarga yuborilgan javoblar: <b>{submissions}</b>\n" if submissions else ""
    )
    solutions_line = (
        f"🎬 Yuklangan yechimlar (video/rasm): <b>{solution_files}</b>\n"
        if solution_files
        else ""
    )
    return (
        "🛠 <b>Bot statistikasi</b>\n"
        f"{SEP}\n"
        f"👥 O'quvchilar: <b>{users}</b>\n"
        f"🗂 Imtihonlar: <b>{exams}</b>\n"
        f"{submissions_line}"
        f"{solutions_line}"
        f"❓ Bazadagi savollar (mashq rejimi): <b>{questions}</b>\n"
        f"📝 Topshirilgan testlar (mashq rejimi): <b>{attempts}</b>\n"
        f"{average_line}\n"
        f"🔄 Hozir faol testlar: <b>{active_sessions}</b>"
    )


# ---------------------------------------------------------------------------
# Adminlarni boshqarish (`/admins`)
# ---------------------------------------------------------------------------
def admin_manage_panel(*, owners: list[str], extras: list[dict]) -> str:
    """`/admins` paneli: egasi adminlar + bot ichidan qo'shilganlar.

    Args:
        owners: `.env` dan olingan (o'chirilmaydigan) adminlar — tayyor matn.
        extras: bazadagi adminlar — `{"user_id": int, "mention": str}` ro'yxati.
    """
    lines = [
        "👥 <b>Adminlar</b>",
        SEP,
        "🔒 <b>Asosiy adminlar</b> (server sozlamasidan — o'chirilmaydi):",
    ]
    if owners:
        lines += [f"• {_safe(name)}" for name in owners]
    else:
        lines.append("• —")

    lines += ["", "➕ <b>Bot ichidan qo'shilganlar</b>:"]
    if extras:
        for row in extras:
            mention = _safe(row.get("mention") or f"ID {row['user_id']}")
            lines.append(f"• {mention} — <code>{row['user_id']}</code>")
    else:
        lines.append("• hozircha yo'q")

    lines += [
        SEP,
        "Yangi admin qo'shish uchun «➕ Admin qo'shish» tugmasini bosing.",
        "O'chirish uchun admin yonidagi «🗑» tugmasini bosing.",
    ]
    return "\n".join(lines)


def admin_add_prompt() -> str:
    """«➕ Admin qo'shish» bosilganda: forward yoki ID so'raladi."""
    return (
        "➕ <b>Yangi admin qo'shish</b>\n"
        f"{SEP}\n"
        "1️⃣ Yangi admin bo'ladigan odam botga <b>/start</b> yozsin.\n"
        "2️⃣ Uning xabarini shu yerga <b>forward</b> qiling.\n\n"
        "Yoki uning ID raqamini yozib yuboring: <code>123456789</code>\n\n"
        "Bekor qilish uchun /admins deb yozing."
    )


def admin_add_unknown() -> str:
    """Forward qilingan xabarda foydalanuvchi aniqlanmadi."""
    return (
        "⚠️ Bu xabardan odamni aniqlab bo'lmadi.\n\n"
        "• Shaxsiy xabarini forward qiling (kanal yoki guruh posti emas);\n"
        "• yoki ID raqamini yozib yuboring: <code>123456789</code>"
    )


def admin_add_confirm(mention: str, user_id: int, *, already: bool = False) -> str:
    """Tasdiqlash xabari (yoki «allaqachon admin» ogohlantirishi)."""
    if already:
        return f"ℹ️ {_safe(mention)} allaqachon admin ro'yxatida."
    return (
        "❓ <b>Shu odamni admin qilaymi?</b>\n"
        f"{SEP}\n"
        f"👤 {_safe(mention)}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"{SEP}\n"
        "Tasdiqlasangiz, unga imtihon yaratish va natijalarni ko'rish huquqi "
        "beriladi."
    )


def admin_added(mention: str) -> str:
    """Admin muvaffaqiyatli qo'shildi."""
    return (
        f"✅ {_safe(mention)} admin qilib qo'shildi.\n"
        "Unga /start bosgach admin komandalari ko'rinadi."
    )


def admin_remove_confirm(mention: str, user_id: int) -> str:
    """Adminni o'chirishni tasdiqlash."""
    return (
        "❓ <b>Adminlikdan o'chiraymi?</b>\n"
        f"{SEP}\n"
        f"👤 {_safe(mention)}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"{SEP}\n"
        "O'chirilsa, u imtihon yaratolmaydi va statistikani ko'rmaydi."
    )


def admin_removed(mention: str) -> str:
    """Admin ro'yxatdan o'chirildi."""
    return f"🗑 {_safe(mention)} adminlikdan o'chirildi."


def admin_owner_protected() -> str:
    """`.env` dagi asosiy adminni o'chirishga urinish."""
    return (
        "🔒 Bu — <b>asosiy admin</b> (server sozlamasida yozilgan).\n"
        "Uni bot ichidan o'chirib bo'lmaydi."
    )


def admin_not_found() -> str:
    """O'chirilmoqchi bo'lgan admin ro'yxatda yo'q."""
    return "⚠️ Bu admin ro'yxatda topilmadi (ehtimol allaqachon o'chirilgan)."


def admin_new_notice(bot_name: str) -> str:
    """Yangi adminning o'ziga yuboriladigan xabar."""
    return (
        f"🎉 Siz <b>{_safe(bot_name)}</b> botida admin qilib qo'shildingiz.\n\n"
        "Endi sizga quyidagilar ochildi:\n"
        "• /new_exam — yangi imtihon yaratish\n"
        "• /exams — imtihonlar ro'yxati\n"
        "• /stats — statistika\n"
        "• /admins — adminlarni boshqarish\n\n"
        "Boshlash uchun /start ni bosing."
    )


# ---------------------------------------------------------------------------
# Umumiy xabarlar
# ---------------------------------------------------------------------------
def no_questions() -> str:
    """Bazada savol bo'lmasa."""
    return (
        "⚠️ Hozircha bazada savollar yo'q.\n"
        "O'qituvchi savollar qo'shgandan so'ng testni boshlash mumkin bo'ladi."
    )


def session_lost() -> str:
    """Sessiya topilmasa (masalan bot qayta ishga tushgan bo'lsa)."""
    return (
        "⚠️ Joriy test topilmadi (ehtimol bot qayta ishga tushgan).\n"
        "Iltimos, /start buyrug'i bilan menyudan yangi test boshlang."
    )


def stale_button() -> str:
    """Eskirgan tugma bosilganda."""
    return "Bu tugma eskirgan — quyidagi savolga javob bering."


# ---------------------------------------------------------------------------
# «🔍 Test tahlili» bo'limi (o'quvchi) va yechim yuklash (o'qituvchi)
# ---------------------------------------------------------------------------


def analysis_list(window: solutions.PageWindow, full_name: str) -> str:
    """Natijasi e'lon qilingan imtihonlar ro'yxati (sahifalash bilan)."""
    return (
        "🔍 <b>Test tahlili</b>\n"
        f"{SEP}\n"
        f"👤 {_safe(full_name)}\n"
        f"📚 {_safe(window.title)}\n"
        f"{SEP}\n"
        "Tahlilni ko'rish uchun imtihonni tanlang 👇"
    )


def analysis_empty(full_name: str) -> str:
    """Tahlil uchun imtihon topilmasa (javob yuborilmagan/e'lon qilinmagan)."""
    return (
        "🔍 <b>Test tahlili</b>\n"
        f"{SEP}\n"
        f"👤 {_safe(full_name)}\n\n"
        "Hozircha tahlil qilish uchun imtihon yo'q.\n\n"
        "ℹ️ Tahlil faqat siz <b>javob yuborgan</b> va <b>natijasi e'lon "
        "qilingan</b> imtihonlar uchun ochiladi.\n"
        "Natijalar e'lon qilinganini ilovaning «Natijalar» bo'limida ko'rasiz."
    )


def analysis_questions(*, label: str, title: str, correct: int, total: int) -> str:
    """Savollar gridi ustidagi sarlavha («Tanlangan testdagi savollarni tanlang»)."""
    return (
        f"{_safe(label)}\n"
        f"{SEP}\n"
        f"📌 {_safe(title)}\n"
        f"✅ To'g'ri javoblar: <b>{correct} / {total}</b>\n"
        "👇 Tugmalar: <b>✅</b> — to'g'ri javob berilgan, <b>❌</b> — noto'g'ri\n"
        f"{SEP}\n"
        "Tanlangan testdagi savollarni tanlang 👇"
    )


def analysis_no_solution(*, label: str) -> str:
    """Tanlangan savol uchun yechim hali yuklanmagan."""
    return (
        f"⚠️ <b>{_safe(label)}</b>-savol uchun yechim hali yuklanmagan.\n\n"
        "O'qituvchi video yoki rasm yechimni yuklagach, u shu yerda ko'rinadi."
    )


def solution_post(
    *,
    label: str,
    kind: str,
    hashtag: str,
    icon: str = "🎬",
) -> str:
    """O'quvchiga yuboriladigan yechim sarlavhasi (media izohi).

    Matnli yechim yo'q — post faqat sarlavha va hashtagdan iborat:
    «🎬 3 — video yechim» + «#javob-rashtest1612-3».
    """
    return f"{icon} <b>{_safe(label)}</b> — {_safe(kind)}\n{SEP}\n{hashtag}"


def solution_unavailable(*, label: str) -> str:
    """Faylli yechimni yuborib bo'lmadi (file_id eskirgan yoki fayl o'chirilgan)."""
    return (
        f"⚠️ <b>{_safe(label)}</b>-savol yechimini yuklab bo'lmadi.\n\n"
        "O'qituvchi yechimni qayta yuklashi kerak. Keyinroq yana urinib ko'ring."
    )


def solution_media_required() -> str:
    """Admin qo'llanmaydigan media (audio, animatsiya, dumaloq video) yuborsa."""
    return (
        "⚠️ <b>Yechim faqat video yoki rasm bo'lishi mumkin.</b>\n\n"
        "Videoni oddiy <b>video</b> sifatida, rasmni esa <b>surat</b> sifatida "
        "yuboring (dumaloq video, audio va animatsiya qabul qilinmaydi).\n\n"
        "Yo'riqnoma: /add_solution"
    )


def solution_size_warning(*, size_mb: float, limit_mb: int) -> str:
    """Fayl hajmi tavsiya etilgan chegaradan katta bo'lganda (saqlangan)."""
    return (
        f"ℹ️ Fayl hajmi <b>{size_mb:.1f} MB</b> — Telegram bot uchun tavsiya "
        f"etilgan chegara <b>{limit_mb} MB</b>.\n\n"
        "Yechim saqlandi. Agar o'quvchida ochilmasa — videoni <b>720p</b> qilib "
        "qayta yuklang yoki rasm ko'rinishida yuboring."
    )


def solution_admin_intro() -> str:
    """`/add_solution` yo'riqnomasi (o'qituvchi uchun)."""
    return (
        "🎬 <b>Video yoki rasm yechim yuklash</b>\n"
        f"{SEP}\n"
        "<b>1-usul (tavsiya etiladi)</b> — Mini App'dagi «🎬 Yechimlar» "
        "bo'limidan savolni tanlab, yuklash tugmasini bosing.\n\n"
        "<b>2-usul</b> — botga video yoki rasm yuboring va izohiga test kodi "
        "bilan savol raqamini yozing:\n\n"
        "<code>rashtest1612 3</code>  yoki  <code>#rashtest1612-3</code>\n"
        "A/B qismli savollar uchun: <code>rashtest1612 36a</code>\n\n"
        f"{SEP}\n"
        "⚠️ Matnli yechim qo'llanmaydi — faqat <b>video</b> yoki <b>rasm</b>.\n"
        "🎬 Video — 50 MB gacha (720p tavsiya etiladi)\n"
        "🖼 Rasm — 10 MB gacha\n"
        "🤖 Bot faylning Telegram <code>file_id</code> sini o'zi olib, "
        "bazadagi tegishli savolga biriktiradi."
    )


def solution_caption_error() -> str:
    """Izohdagi format tanilmaganda."""
    return (
        "⚠️ <b>Format tanilmadi.</b>\n\n"
        "Videoni yoki rasmni yuborib, izohiga test kodi va savol raqamini "
        "yozing:\n"
        "<code>rashtest1612 3</code> · <code>#rashtest1612-3</code> · "
        "<code>rashtest1612 36a</code>\n\n"
        "Yo'riqnoma: /add_solution"
    )


def solution_exam_not_found(test_code: str) -> str:
    """Test kodi bazada topilmasa."""
    return (
        f"⚠️ <b>{_safe(test_code)}</b> kodli imtihon topilmadi.\n\n"
        "Kodni /exams ro'yxatidan tekshirib qayta urinib ko'ring."
    )


def solution_out_of_range(*, test_code: str, number: int, total: int) -> str:
    """Savol raqami imtihon oralig'idan tashqarida bo'lsa."""
    return (
        f"⚠️ <b>{_safe(test_code)}</b> imtihonida <b>{number}</b>-savol yo'q —\n"
        f"unda jami {total} ta savol bor."
    )


def solution_saved(*, test_code: str, label: str, kind: str) -> str:
    """Yechim saqlanganda: «✅ rashtest1612 ning 3-savoliga video yechim … saqlandi!»."""
    return (
        f"✅ <b>{_safe(test_code)}</b> ning <b>{_safe(label)}</b>-savoliga "
        f"{_safe(kind)} muvaffaqiyatli saqlandi!"
    )


def solution_link_prompt(*, title: str, test_code: str, label: str) -> str:
    """Panel deep-link'i orqali botga o'tganda ko'rsatiladigan yo'riqnoma.

    Shu holatda o'qituvchi **izoh yozmaydi** — keyingi media shu savolga
    biriktiriladi (`handlers/admin_solution.py`).
    """
    return (
        "🎬 <b>Yechim yuklash</b>\n"
        f"{SEP}\n"
        f"📌 {_safe(title)}\n"
        f"🎯 Savol: <b>{_safe(test_code)} · {_safe(label)}</b>\n\n"
        "Endi shu savol uchun <b>videoni yoki rasmni</b> shu chatga yuboring — "
        "<b>izoh yozish shart emas</b>.\n\n"
        "⚠️ Matnli yechim yo'q: faqat video (50 MB gacha) yoki rasm (10 MB "
        "gacha).\n\n"
        "Bekor qilish: /cancel"
    )


# ---------------------------------------------------------------------------
# «Yakunlash» natijasi (bot xabari) — javob kalitisiz, tugmali grid bilan
# ---------------------------------------------------------------------------
def submission_accepted(
    *,
    marks: Sequence[tuple[str, bool]] | None = None,
) -> str:
    """Javob qabul qilinganini tasdiqlovchi **qisqa** xabar.

    Tarkibi ataylab minimal:

    * bitta sarlavha — «✅ Javoblaringiz qabul qilindi»;
    * (bo'lsa) savollar ro'yxati — **har bir savol alohida qatorda**:
      `1 ✅`, `2 ❌`, … (bir ustun; uzun ro'yxat ham o'qishga qulay);
    * ro'yxatdan keyin ajratgich va yakuniy sanoq — `<jami>/<to'g'ri>`,
      masalan `55/39` (55 element, 39 tasi to'g'ri).

    `marks` — `[(savol belgisi, to'g'rimi), ...]`; yakunlashdan keyin darhol
    hisoblanadi (`services.feedback`). Javobsiz savol ham ❌ bo'lib chiqadi
    (Rasch bo'yicha u 0 ball) va yakuniy sanoqda "to'g'ri emas" sifatida
    hisobga olinadi.

    Boshqa **hech qanday** matn yo'q: to'g'ri javob varianti, o'quvchi javobi,
    θ, ball, ism-familiya va vaqt ko'rsatilmaydi — kalit `result_time` gacha
    yopiq qoladi. `marks` berilmasa (kalit buzuq bo'lsa) — faqat sarlavha.
    """
    head = "✅ <b>Javoblaringiz qabul qilindi</b>"
    if not marks:
        return head

    correct = sum(1 for _label, is_correct in marks if is_correct)
    summary = f"<b>{len(marks)}/{correct}</b>"
    lines = [head, ""]
    # Sarlavha + bo'sh qator + ajratgich + yakuniy sanoq (+ "…" zaxirasi) uchun
    # joy oldindan band qilinadi — xabar Telegram limitidan oshmasligi shart.
    used = len(head) + 1 + len(SEP) + 1 + len(summary) + 4
    for label, is_correct in marks:
        line = f"{_safe(label)} {'✅' if is_correct else '❌'}"
        # Amalda 45 savol + qismlar (≈65 qator) limitga bemalol sig'adi —
        # bu faqat himoya: xabar hech qachon 4096 belgidan oshmasligi kerak.
        if used + len(line) + 1 > MESSAGE_LIMIT:
            lines.append("…")
            break
        lines.append(line)
        used += len(line) + 1
    lines.extend([SEP, summary])
    return "\n".join(lines)


def _level_emoji(level: str) -> str:
    """Daraja uchun bitta tushunarli belgi (rang o'rniga)."""
    return {
        "A+": "🏆",
        "A": "🏆",
        "B+": "🥈",
        "B": "🥈",
        "C+": "🥉",
        "C": "🥉",
    }.get(level, "📘")


def result_ready(
    *,
    title: str,
    full_name: str,
    report: Mapping[str, object],
) -> str:
    """Natija e'lon qilinganda yuboriladigan karta.

    `report` — `services.grading.build_report()` natijasi. Xabarda foydalanuvchi
    uchun zarur bo'lgan **olti ko'rsatkich** bor: sertifikat bali (95%
    ishonch oralig'i bilan), to'g'ri javoblar soni, θ (logit), sertifikat
    darajasi, algebra balli va geometriya balli. Ortiqcha texnik ko'rsatkichlar
    (SE, θ intervali, tavsiya) bu xabarga qo'shilmaydi.
    """
    level = str(report.get("ability_level") or "")
    theta = float(report.get("theta") or 0.0)
    raw = int(report.get("raw_score") or 0)
    total = int(report.get("total_questions") or 0)
    scaled = report.get("scaled_score")
    scaled_interval = report.get("scaled_interval")
    subject_balls = report.get("subject_balls") or {}

    def ball(value: object) -> str:
        """0–100 ballni bir kasr xona bilan ko'rsatadi (bo'lmasa — `—`)."""
        try:
            return f"{float(value):.1f} ball"
        except (TypeError, ValueError):
            return "—"

    score_line = f"🎯 <b>Sertifikat bali:</b> {ball(scaled)}"
    if isinstance(scaled_interval, (list, tuple)) and len(scaled_interval) == 2:
        try:
            low = float(scaled_interval[0])
            high = float(scaled_interval[1])
        except (TypeError, ValueError):
            pass
        else:
            score_line += f" (95%: {low:.1f}–{high:.1f} ball)"
    else:
        # Chekka holat (SE yo'q) — oraliq mavjud emas, lekin joyi ko'rinadi.
        score_line += " (95%: —)"

    lines = [
        "🎉 <b>Natijangiz e'lon qilindi!</b>",
        SEP,
        f"📌 {_safe(title)}",
        f"👤 {_safe(full_name)}",
        "",
        score_line,
        f"✅ <b>To'g'ri javoblar:</b> {raw} / {total}",
        f"🧮 <b>θ (logit):</b> {_sign(theta)}",
        f"{_level_emoji(level)} <b>Sertifikat darajasi:</b> {_safe(level)}",
        f"➗ <b>Algebra:</b> {ball(subject_balls.get('algebra'))}",
        f"📐 <b>Geometriya:</b> {ball(subject_balls.get('geometry'))}",
        "",
        "📊 Batafsil tahlil va yechimlar — pastdagi tugmalarda.",
    ]
    return "\n".join(lines)


def solution_locked(*, result_time: str) -> str:
    """Yechim hali ochilmagan bo'lsa — ogohlantirish (popup)."""
    return (
        "⏳ Yechimlar hali ochilmagan.\n\n"
        f"Savol yechimlarini natijalar e'lon qilinganda ({_safe(result_time)}) "
        "ko'rishingiz mumkin."
    )


