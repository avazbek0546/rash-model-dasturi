"""Botning barcha matnlari (o'zbek tilida, HTML formatda).

Matnlarni bitta joyda saqlash qoidasi: handler'lar ichida uzun matn yozilmaydi.
aiogram `parse_mode=HTML` bilan ishlaydi, shuning uchun <b>, <i>, <code> teglari
ishlatiladi. Foydalanuvchi ismi kabi dinamik matnlar `escape()` orqali
tozalanadi (aks holda Telegram HTML xatosi beradi).
"""

from __future__ import annotations

from html import escape

from database.models import SKIPPED, Exam, Question, TestResult, UserStats
from services import rasch, solutions
from services.rasch import RaschEstimate

SEP = "━━━━━━━━━━━━━━━━━━"


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
        "• 0–100 shkaladagi ball va uning aniqligi (ishonch oralig'i).\n\n"
        "Kerakli bo'limni tanlang 👇"
    )


def help_text() -> str:
    """`/help` komandasi matni."""
    return (
        "🤖 <b>Mavjud komandalar</b>\n\n"
        "/start — asosiy menyu va Web App tugmasi\n"
        "/app — imtihon ilovasini ochish\n"
        "/help — shu yordam xabari\n\n"
        "👨‍🏫 <b>O'qituvchi uchun</b>\n"
        "/new_exam — yangi imtihon yaratish (usta yordamida)\n"
        "/exams — imtihonlar ro'yxati (o'chirish mumkin)\n"
        "/stats — umumiy statistika\n\n"
        "ℹ️ Javoblar faqat <b>Web App</b> orqali va faqat belgilangan vaqt\n"
        "oralig'ida qabul qilinadi. Har bir imtihonga javob <b>bir marta</b>\n"
        "yuboriladi — natija Rasch modeli bo'yicha θ va 0–100 ball ko'rinishida\n"
        "e'lon qilinadi."
    )


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
    """`/start` matni (yangi imtihon platformasi)."""
    head = (
        f"👋 <b>Assalomu alaykum, {_safe(full_name)}!</b>\n\n"
        "Bu <b>Rasch modeli (IRT)</b> asosida ishlaydigan imtihon platformasi.\n"
        "Imtihonni o'qituvchi yaratadi, javoblar esa Telegram <b>Web App</b>\n"
        "(Mini App) orqali topshiriladi.\n"
    )
    if not webapp_ready:
        return head + (
            "\n⚠️ <b>Web App manzili hali sozlanmagan.</b>\n"
            "Administrator <code>WEBAPP_URL</code> ni <code>.env</code> faylida\n"
            "ko'rsatishi kerak (Telegram faqat HTTPS manzilni qabul qiladi)."
        )
    return head + (
        "\n<b>Qanday ishlaydi?</b>\n"
        "1️⃣ O'qituvchi <b>test kodini</b> beradi;\n"
        "2️⃣ ilovadagi «Navbat» bo'limida kodni kiritib, javoblar varag'ini\n"
        "   (masalan <code>1A2B3C</code>) yuborasiz;\n"
        "3️⃣ natijalar e'lon qilingan vaqtda <b>θ (logit)</b> va\n"
        "   <b>0–100 ball</b> ko'rinishida chiqadi.\n\n"
        "Ilovani ochish uchun quyidagi tugmani bosing 👇"
    )


def webapp_button_missing() -> str:
    """Web App tugmasi bosilganda manzil sozlanmagan bo'lsa."""
    return (
        "⚠️ <b>Web App manzili sozlanmagan.</b>\n\n"
        "Administrator <code>.env</code> faylida <code>WEBAPP_URL</code>\n"
        "qiymatini ko'rsatishi kerak (masalan "
        "<code>https://exam.example.uz</code>)."
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
    """Javoblar kaliti so'raladi."""
    return (
        "4️⃣ <b>Javoblar kalitini</b> kiriting — har bir savol uchun to'g'ri variant.\n\n"
        f"Format: <code>1A2B3C…</code> ({total_questions} ta javob bo'lishi shart).\n"
        "Bo'sh joy va tinish belgilari ham qabul qilinadi:\n"
        "<code>1A 2B 3C</code> yoki <code>ABCD</code>."
    )


def ask_difficulties(total_questions: int) -> str:
    """Qiyinchilik logitlari so'raladi."""
    return (
        "5️⃣ <b>Qiyinchilik darajalari (logit)</b> — ixtiyoriy qadam.\n\n"
        f"• Bo'sh qoldirsangiz yoki <code>-</code> yozsangiz: barcha "
        f"{total_questions} savol uchun <b>0.0</b>;\n"
        "• bitta son yozsangiz (masalan <code>0.5</code>) — u hamma savolga "
        "qo'llanadi;\n"
        f"• yoki {total_questions} ta sonni vergul bilan ajratib yozing:\n"
        "<code>-1.2, 0, 0.5, 1.4</code>\n\n"
        "ℹ️ b katta bo'lsa savol qiyin, manfiy bo'lsa oson hisoblanadi."
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
        f"📈 Logitlar: <code>{_safe(difficulties)}</code>\n"
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
            f"{item['submissions']} ta javob\n"
            f"   🔑 Kod: <code>{_safe(item['test_code'])}</code> · "
            f"{item['total_questions']} savol\n"
            f"   🗝 Kalit: <code>{_safe(item['answer_key'])}</code>\n"
            f"   ▶️ {_safe(item['start_local'])} → ⏹ {_safe(item['end_local'])}\n"
            f"   📢 Natija: {_safe(item['result_local'])}"
        )
    lines.append(SEP)
    lines.append("🗑 O'chirish uchun pastdagi tugmani bosing.")
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
        "So'ng θ 0–100 shkalaga chiziqli o'tkaziladi:\n"
        "<code>−3 logit → 0 ball,  0 → 50 ball,  +3 → 100 ball</code>\n\n"
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
    accuracy = (
        f"±{estimate.scaled_error:.1f} ball"
        if estimate.scaled_error is not None
        else "aniqlanmagan (chegara holati)"
    )
    interval = estimate.scaled_interval
    interval_line = (
        f"• 95% ishonch oralig'i: <b>{interval[0]:.0f} – {interval[1]:.0f}</b> ball\n"
        if interval
        else ""
    )
    se_line = (
        f"• Standart xato (SE): {estimate.standard_error:.2f} logit  →  {accuracy}\n"
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
        f"🏅 0–100 shkalada: <b>{estimate.scaled_score:.0f} ball</b> — {level}\n"
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
        f"🏆 Eng yaxshi ball: <b>{stats.best_scaled:.0f}</b>"
        + (f" (θ = {_sign(stats.best_theta)})" if stats.best_theta is not None else ""),
        f"📈 O'rtacha ball: <b>{stats.average_scaled:.1f}</b>"
        if stats.average_scaled is not None
        else "📈 O'rtacha ball: —",
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
        lines.append(
            f"{index}. {date} — {result.raw_score}/{result.total_questions} · "
            f"θ = {theta} · <b>{result.final_scaled_score:.0f} ball</b>"
        )

    lines.append(SEP)
    lines.append(
        "📌 Eslatma: bir xil xom ball turli testlarda turli ballga olib kelishi "
        "mumkin — buni savollar to'plamining qiyinligi belgilaydi."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Admin statistikasi
# ---------------------------------------------------------------------------
def admin_stats(
    users: int,
    questions: int,
    attempts: int,
    average_scaled: float | None,
    active_sessions: int,
    exams: int = 0,
    submissions: int = 0,
    solution_files: int = 0,
) -> str:
    """`/stats` komandasi uchun umumiy statistika."""
    average_line = (
        f"📈 O'rtacha scaled ball (mashq rejimi): <b>{average_scaled:.1f}</b>"
        if average_scaled is not None
        else "📈 O'rtacha scaled ball (mashq rejimi): —"
    )
    submissions_line = (
        f"📥 Imtihonlarga yuborilgan javoblar: <b>{submissions}</b>\n" if submissions else ""
    )
    solutions_line = (
        f"🎬 Yuklangan video yechimlar: <b>{solution_files}</b>\n" if solution_files else ""
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
MEDIA_CAPTION_LIMIT = 900  # media izohi 1024 belgidan oshmasligi kerak
TEXT_MESSAGE_LIMIT = 3600  # oddiy xabar 4096 belgidan oshmasligi kerak


def _truncate(text: str, limit: int) -> str:
    """Matnni `limit` belgiga qisqartiradi (oxiriga «…» qo'shiladi)."""
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def reply_menu_hint() -> str:
    """Pastdagi (reply) menyu ko'rsatilganda yuboriladigan qisqa izoh."""
    return (
        "🧭 <b>Bo'limlar menyusi</b>\n"
        f"{SEP}\n"
        "Pastdagi tugmalar orqali kerakli bo'limni tanlang:\n"
        "🔍 <b>Test tahlili</b> — topshirgan imtihoningiz savollarini "
        "video yechimlari bilan ko'rish."
    )


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
        "O'qituvchi video yechimni yuklagach, u shu yerda ko'rinadi."
    )


def solution_post(
    *,
    label: str,
    kind: str,
    solution_text: str,
    hashtag: str,
    limit: int = MEDIA_CAPTION_LIMIT,
) -> str:
    """Foydalanuvchiga yuboriladigan yechim posti (media izohi yoki matn).

    Post oxiriga doim hashtag qo'shiladi: «#javob-rashtest1612-3».
    """
    lines = [f"📝 <b>{_safe(label)}</b> — {_safe(kind)}", SEP]
    body = _truncate(solution_text, limit)
    if body:
        lines.append(_safe(body))
        lines.append(SEP)
    lines.append(hashtag)
    return "\n".join(lines)


def solution_admin_intro() -> str:
    """`/add_solution` yo'riqnomasi (o'qituvchi uchun)."""
    return (
        "🎬 <b>Video/media yechim yuklash</b>\n"
        f"{SEP}\n"
        "<b>1-usul (tavsiya etiladi)</b> — botga video (rasm yoki hujjat)\n"
        "yuboring va izohiga test kodi bilan savol raqamini yozing:\n\n"
        "<code>rashtest1612 3</code>  yoki  <code>#rashtest1612-3</code>\n"
        "A/B qismli savollar uchun: <code>rashtest1612 36a</code>\n\n"
        "<b>2-usul (matnli tahlil)</b>:\n"
        "<code>/add_solution rashtest1612 3 yechim matni…</code>\n"
        f"{SEP}\n"
        "🤖 Bot faylning Telegram <code>file_id</code> sini o'zi olib,\n"
        "bazadagi tegishli savolga biriktiradi."
    )


def solution_caption_error() -> str:
    """Izohdagi format tanilmaganda."""
    return (
        "⚠️ <b>Format tanilmadi.</b>\n\n"
        "Izohga test kodi va savol raqamini yozing:\n"
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


def solution_text_required() -> str:
    """Matnli yechim uchun matn kiritilmaganda."""
    return (
        "⚠️ Matnli yechim uchun matn ham yozing.\n\n"
        "Masalan:\n"
        "<code>/add_solution rashtest1612 3 2x+5=13 → x=4</code>"
    )


