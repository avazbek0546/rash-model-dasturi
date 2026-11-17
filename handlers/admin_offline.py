"""Admin uchun Offline Mock Import buyruqlari.

Faqat admin. Excel fayl faqat `OfflineImportStates.waiting_file` holatida
qabul qilinadi — boshqa handlerlar (masalan, video/rasm yechimlar) bilan
to'qnashmaydi. Himoya ikki qatlamda: `handlers/__init__.py` da bu router
`admin_solution` dan **oldin** ulanadi va `admin_solution` handlerlari
`OfflineImportStates.waiting_file` holatini `~StateFilter` bilan chetlab o'tadi.
"""

from __future__ import annotations

import io
import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import config
from database.repository import Repositories
from handlers.access import is_admin, log_denied
from keyboards.inline import (
    AppCallback,
    OfflineAdminCallback,
    offline_batch_delete_confirm_kb,
    offline_batches_kb,
    offline_cancel_kb,
    offline_exams_kb,
    offline_link_kb,
    offline_menu_kb,
    offline_preview_kb,
    offline_unlink_kb,
)
from services import offline_import, offline_report, offline_scoring, offline_template, report_pdf
from states import OfflineImportStates

logger = logging.getLogger(__name__)

router = Router(name="admin_offline")


def _guard(message: Message) -> bool:
    if message.from_user is None:
        return False
    if not is_admin(message.from_user.id):
        log_denied("offline", message.from_user.id, message.from_user.full_name)
        return False
    return True


def _enabled(message: Message) -> bool:
    if not config.OFFLINE_IMPORT_ENABLED:
        return False
    return True


def _arg(message: Message, index: int = 1) -> str:
    parts = (message.text or "").split()
    return parts[index].strip() if len(parts) > index else ""


async def _exam(repos: Repositories, code: str):
    return await repos.exams.get_by_code(code) if code else None


def _readiness_text(readiness: offline_scoring.OfflineReadiness) -> str:
    lines = [
        "🔎 <b>Offline mock tayyorgarligi</b>",
        f"Imtihon: <b>#{readiness.exam_id}</b>",
        f"Forma versiyasi: <code>{readiness.form_version_id or '—'}</code>",
        f"Itemlar: <b>{len(readiness.items)}</b> ta",
        f"Kalit bilan baholanadigan itemlar: <b>{readiness.scored_items}</b> ta",
        f"`b` manbasi: <code>{escape(readiness.b_source)}</code>",
        "",
    ]
    if readiness.ready:
        lines.append("✅ <b>Tayyor.</b> Shablon va import ishlaydi.")
    else:
        lines.append(f"❌ <b>Tayyor emas:</b> {escape(readiness.reason)}")
    return "\n".join(lines)


async def _send_readiness(message: Message, repos: Repositories, exam) -> bool:
    readiness = await offline_scoring.check_readiness(repos, exam)
    await message.answer(_readiness_text(readiness), reply_markup=offline_menu_kb(exam.exam_id))
    return readiness.ready


@router.callback_query(AppCallback.filter(F.action == "offline"))
async def offline_menu_callback(
    call: CallbackQuery, repos: Repositories
) -> None:
    """«📥 Offline mock» tugmasi — admin imtihonni tanlaydi."""
    if not _call_guard(call):
        await call.answer("Faqat admin uchun.", show_alert=True)
        return
    if not config.OFFLINE_IMPORT_ENABLED:
        await call.answer("Offline import o'chirilgan.", show_alert=True)
        return
    await call.answer()
    if call.message is None:
        return
    exams = await repos.exams.list_all(limit=10)
    if not exams:
        await call.message.answer(
            "📥 <b>Offline mock</b>\n\nHozircha imtihon yaratilmagan. "
            "Avval <code>/new_exam</code> orqali imtihon yarating."
        )
        return
    text = (
        "📥 <b>Offline mock</b>\n\n"
        "Excel bilan ishlash uchun imtihonni tanlang. "
        "Ichida shablon, import, tarix, PDF va online bilan bog‘lash bor."
    )
    markup = offline_exams_kb(exams)
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except Exception:
        await call.message.answer(text, reply_markup=markup)


@router.message(Command("offline"))
async def cmd_offline(message: Message, repos: Repositories) -> None:
    """`/offline KOD` — offline amallar menyusi."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    code = _arg(message)
    if not code:
        await message.answer(
            "Ishlatish: <code>/offline TEST_KODI</code>\n"
            "Masalan: <code>/offline MOCK2026</code>"
        )
        return
    exam = await _exam(repos, code)
    if exam is None:
        await message.answer(f"«{escape(code)}» test kodi topilmadi.")
        return
    await _send_readiness(message, repos, exam)


@router.message(Command("offline_check"))
async def cmd_offline_check(message: Message, repos: Repositories) -> None:
    """55 item / labeled kalit / `b` tayyorgarligini tekshiradi."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    code = _arg(message)
    exam = await _exam(repos, code)
    if exam is None:
        await message.answer("Test kodi topilmadi. Ishlatish: <code>/offline_check KOD</code>")
        return
    await _send_readiness(message, repos, exam)


async def _send_template(message: Message, repos: Repositories, exam) -> None:
    readiness = await offline_scoring.check_readiness(repos, exam)
    if not readiness.ready:
        await message.answer(
            "❌ Shablon yaratib bo'lmaydi.\n\n" + _readiness_text(readiness)
        )
        return
    try:
        data = offline_template.build_template(exam, readiness)
    except Exception as exc:
        logger.exception("Offline shablon yasalmadi: exam_id=%s", exam.exam_id)
        await message.answer(f"⚠️ Shablon yasalmadi: {escape(str(exc))}")
        return
    await message.answer_document(
        BufferedInputFile(data, filename=offline_template.template_filename(exam)),
        caption=(
            f"📥 «{escape(str(exam.title))}» uchun offline shablon\n"
            f"55 ta topshiriq · kod: <code>{escape(str(exam.test_code))}</code>"
        ),
    )


@router.message(Command("offline_template"))
async def cmd_offline_template(message: Message, repos: Repositories) -> None:
    """`/offline_template KOD` — Excel shablonni yuboradi."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    code = _arg(message)
    exam = await _exam(repos, code)
    if exam is None:
        await message.answer("Test kodi topilmadi. Ishlatish: <code>/offline_template KOD</code>")
        return
    await _send_template(message, repos, exam)


@router.message(Command("offline_import"))
async def cmd_offline_import(
    message: Message, state: FSMContext, repos: Repositories
) -> None:
    """`.xlsx` fayl yuklashni boshlaydi."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    code = _arg(message)
    exam = await _exam(repos, code)
    if exam is None:
        await message.answer("Test kodi topilmadi. Ishlatish: <code>/offline_import KOD</code>")
        return
    readiness = await offline_scoring.check_readiness(repos, exam)
    if not readiness.ready:
        await message.answer("❌ Import bloklandi.\n\n" + _readiness_text(readiness))
        return
    await state.set_state(OfflineImportStates.waiting_file)
    await state.update_data(offline_exam_id=exam.exam_id)
    await message.answer(
        f"📤 «{escape(str(exam.title))}» uchun Excel faylni yuboring.\n\n"
        "Faqat bot bergan `.xlsx` shablon. Fayl avval tekshiriladi, "
        "tasdiqlaganingizdan keyingina bazaga yoziladi."
    )


async def _preview_text(preview: offline_import.BatchPreview) -> str:
    batch = preview.batch
    rows = preview.rows
    lines = [
        "📋 <b>Excel tekshirildi</b>",
        f"Partiya: <b>#{batch.get('batch_no')}</b> (ID {batch.get('batch_id')})",
        f"Qatorlar: <b>{len(rows)}</b> ta",
        f"Xatolar: <b>{preview.error_count}</b> · ogohlantirish: <b>{preview.warning_count}</b>",
        "",
    ]
    for row in rows[:5]:
        status = "✅" if row.get("row_status") == "valid" else "⚠️"
        lines.append(
            f"{status} <code>{escape(str(row.get('student_code')))}</code> — "
            f"{escape(str(row.get('full_name')))} ({escape(str(row.get('class_label')))})"
        )
    if len(rows) > 5:
        lines.append(f"… yana {len(rows) - 5} ta qator")
    if preview.issues:
        lines.append("")
        lines.append("<b>Birinchi xatolar:</b>")
        for issue in preview.issues[:8]:
            row_no = issue.get("row_no")
            prefix = f"{row_no}-qator: " if row_no else ""
            lines.append(f"• {escape(prefix + str(issue.get('message')))}")
        if len(preview.issues) > 8:
            lines.append(f"… yana {len(preview.issues) - 8} ta xato")
    lines.append("")
    if preview.can_commit:
        lines.append("✅ Tasdiqlasangiz, natijalar bazaga yoziladi.")
    else:
        lines.append("❌ Xatolarni tuzatib, faylni qayta yuklang. Hech narsa yozilmadi.")
    return "\n".join(lines)


@router.message(OfflineImportStates.waiting_file, F.document)
async def upload_offline_file(
    message: Message, state: FSMContext, repos: Repositories
) -> None:
    """Faylni qabul qiladi, tekshiradi va preview ko'rsatadi."""
    if not _guard(message):
        return
    if not _enabled(message):
        await state.clear()
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    document = message.document
    if document is None:
        return
    name = str(document.file_name or "")
    if not name.lower().endswith(".xlsx"):
        await message.answer("Faqat `.xlsx` fayl qabul qilinadi.")
        return
    if int(document.file_size or 0) > config.OFFLINE_IMPORT_MAX_MB * 1024 * 1024:
        await message.answer(
            f"Fayl hajmi {config.OFFLINE_IMPORT_MAX_MB} MB dan oshmasligi kerak."
        )
        return
    data_state = await state.get_data()
    exam = await repos.exams.get(int(data_state.get("offline_exam_id") or 0))
    await state.clear()
    if exam is None:
        await message.answer("Imtihon topilmadi. Qaytadan `/offline_import KOD` yuboring.")
        return
    readiness = await offline_scoring.check_readiness(repos, exam)
    if not readiness.ready:
        await message.answer("❌ Import bloklandi.\n\n" + _readiness_text(readiness))
        return
    buffer = io.BytesIO()
    try:
        await message.bot.download(document, destination=buffer)
        data = buffer.getvalue()
    except Exception:
        logger.exception("Offline faylni yuklab bo'lmadi")
        await message.answer("⚠️ Faylni yuklab bo'lmadi. Qayta urinib ko'ring.")
        return
    try:
        preview = await offline_import.stage_batch(
            repos=repos,
            exam=exam,
            readiness=readiness,
            data=data,
            filename=name,
            admin_id=message.from_user.id if message.from_user else 0,
        )
    except offline_import.OfflineImportError as exc:
        await message.answer(f"❌ {escape(str(exc))}")
        return
    except Exception:
        logger.exception("Offline faylni tahlil qilishda xatolik")
        await message.answer("⚠️ Faylni tekshirishda texnik xatolik yuz berdi.")
        return
    markup = (
        offline_preview_kb(int(preview.batch["batch_id"]))
        if preview.can_commit
        else offline_cancel_kb(int(preview.batch["batch_id"]))
    )
    await message.answer(await _preview_text(preview), reply_markup=markup)


@router.message(OfflineImportStates.waiting_file)
async def upload_offline_wrong(message: Message) -> None:
    """Holatda matn yoki boshqa fayl kelsa."""
    await message.answer("Iltimos, `.xlsx` faylni yuboring yoki `/cancel` bilan bekor qiling.")


async def _send_batches(message: Message, repos: Repositories, exam) -> None:
    batches = await repos.offline_batches.list_batches(exam.exam_id)
    if not batches:
        await message.answer("Hozircha offline import partiyasi yo'q.")
        return
    lines = [f"📚 <b>«{escape(str(exam.title))}» — import tarixi</b>", ""]
    for batch in batches:
        lines.append(
            f"#{batch.get('batch_no')} · ID <code>{batch.get('batch_id')}</code> · "
            f"<b>{escape(str(batch.get('status')))}</b>\n"
            f"   qatorlar: {batch.get('rows_valid')}/{batch.get('rows_total')} · "
            f"fayl: {escape(str(batch.get('file_name')))}"
        )
    lines.append("")
    lines.append("Bekor qilish (tarix qoladi): <code>/offline_void BATCH_ID</code>")
    lines.append(
        "Butunlay o'chirish: pastdagi 🗑 tugmasi yoki "
        "<code>/offline_delete BATCH_ID</code>"
    )
    await message.answer(
        "\n".join(lines), reply_markup=offline_batches_kb(batches, exam.exam_id)
    )


@router.message(Command("offline_batches"))
async def cmd_offline_batches(message: Message, repos: Repositories) -> None:
    """`/offline_batches KOD` — import tarixi."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    exam = await _exam(repos, _arg(message))
    if exam is None:
        await message.answer("Test kodi topilmadi. Ishlatish: <code>/offline_batches KOD</code>")
        return
    await _send_batches(message, repos, exam)


@router.message(Command("offline_void"))
async def cmd_offline_void(message: Message, repos: Repositories) -> None:
    """`/offline_void BATCH_ID` — partiyani bekor qiladi."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    raw = _arg(message)
    try:
        batch_id = int(raw)
    except ValueError:
        await message.answer("Ishlatish: <code>/offline_void BATCH_ID</code>")
        return
    try:
        stats = await offline_import.void_batch(
            repos, batch_id, message.from_user.id if message.from_user else 0, "admin"
        )
    except offline_import.OfflineImportError as exc:
        await message.answer(f"❌ {escape(str(exc))}")
        return
    await message.answer(
        f"✅ Partiya #{batch_id} bekor qilindi. "
        f"Attemptlar: {stats.get('attempts', 0)}. "
        "Online natijalar (agar bog'langan bo'lsa) reytingga qaytdi."
    )


def _delete_confirm_text(batch) -> str:
    """Partiyani butunlay o'chirishdan oldingi tasdiq matni."""
    return (
        f"🗑 <b>Partiya #{batch.get('batch_no')} butunlay o'chirilsinmi?</b>\n\n"
        f"Fayl: <code>{escape(str(batch.get('file_name') or ''))}</code>\n"
        f"Holat: <b>{escape(str(batch.get('status')))}</b> · "
        f"qatorlar: {batch.get('rows_valid')}/{batch.get('rows_total')}\n\n"
        "Qatorlar, offline natijalar, bog'lanishlar va reyting qarorlari "
        "bazadan o'chadi; bog'langan online natijalar reytingga qaytadi.\n"
        "Bu amalni qaytarib bo'lmaydi."
    )


@router.message(Command("offline_delete"))
async def cmd_offline_delete(message: Message, repos: Repositories) -> None:
    """`/offline_delete BATCH_ID` — partiyani butunlay o'chirishni tasdiqlatadi."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    try:
        batch_id = int(_arg(message))
    except ValueError:
        await message.answer(
            "Ishlatish: <code>/offline_delete BATCH_ID</code>\n\n"
            "Partiya ID sini «📚 Import tarixi»dan oling."
        )
        return
    batch = await repos.offline_batches.get_batch(batch_id)
    if batch is None:
        await message.answer("Bunday partiya topilmadi.")
        return
    await message.answer(
        _delete_confirm_text(batch),
        reply_markup=offline_batch_delete_confirm_kb(
            batch_id, int(batch["exam_id"])
        ),
    )


async def _send_reports(message: Message, repos: Repositories, exam) -> None:
    try:
        combined = await offline_report.build_combined_report(repos, exam)
        data = report_pdf.build_combined_results_pdf(
            meta=combined.meta, students=list(combined.students)
        )
        await message.answer_document(
            BufferedInputFile(
                data, filename=f"umumiy-reyting-{exam.test_code}.pdf"
            ),
            caption=(
                f"📄 «{escape(str(exam.title))}» — umumiy reyting\n"
                f"Oflayn: {combined.offline_count} · Onlayn: {combined.online_count} · "
                f"Chiqarilgan: {combined.excluded_count}"
            ),
        )
    except Exception as exc:
        logger.exception("Umumiy offline PDF yasalmadi: exam_id=%s", exam.exam_id)
        await message.answer(f"⚠️ Umumiy PDF yasalmadi: {escape(str(exc))}")

    try:
        offline = await offline_report.build_offline_report(repos, exam)
        data = report_pdf.build_offline_results_pdf(
            meta=offline.meta, students=list(offline.students)
        )
        await message.answer_document(
            BufferedInputFile(
                data, filename=f"offline-reyting-{exam.test_code}.pdf"
            ),
            caption=(
                f"📄 «{escape(str(exam.title))}» — faqat offline\n"
                f"Qatnashchilar: {offline.participants}"
            ),
        )
    except Exception as exc:
        logger.exception("Offline PDF yasalmadi: exam_id=%s", exam.exam_id)
        await message.answer(f"⚠️ Offline PDF yasalmadi: {escape(str(exc))}")


@router.message(Command("offline_report"))
async def cmd_offline_report(message: Message, repos: Repositories) -> None:
    """`/offline_report KOD` — umumiy va offline PDF yuboradi."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    exam = await _exam(repos, _arg(message))
    if exam is None:
        await message.answer("Test kodi topilmadi. Ishlatish: <code>/offline_report KOD</code>")
        return
    await _send_reports(message, repos, exam)


async def _send_links(message: Message, repos: Repositories, exam) -> None:
    participants = await repos.offline_participants.list_for_exam(exam.exam_id)
    if not participants:
        await message.answer("Hozircha offline ishtirokchi yo'q.")
        return
    suggested = [
        p for p in participants
        if p.get("match_status") == "suggested" and p.get("matched_user_id")
    ]
    confirmed = [p for p in participants if p.get("match_status") == "confirmed"]
    conflict = [p for p in participants if p.get("match_status") == "conflict"]
    unmatched = [
        p for p in participants
        if p.get("match_status") in {"unmatched", "rejected"}
    ]
    await message.answer(
        f"🔗 <b>«{escape(str(exam.title))}» — bog'lash</b>\n"
        f"Taklif qilingan: {len(suggested)} · tasdiqlangan: {len(confirmed)} · "
        f"konflikt: {len(conflict)} · jami: {len(participants)}"
    )
    for participant in suggested[:8]:
        await message.answer(
            f"<code>{escape(str(participant.get('student_code')))}</code> — "
            f"{escape(str(participant.get('full_name')))} "
            f"({escape(str(participant.get('class_label')))}) → "
            f"user <code>{participant.get('matched_user_id')}</code>",
            reply_markup=offline_link_kb(
                int(participant["participant_id"]),
                int(participant["matched_user_id"]),
                exam.exam_id,
            ),
        )
    for participant in confirmed[:8]:
        await message.answer(
            f"✅ <code>{escape(str(participant.get('student_code')))}</code> — "
            f"{escape(str(participant.get('full_name')))} → "
            f"user <code>{participant.get('matched_user_id')}</code>",
            reply_markup=offline_unlink_kb(
                int(participant["participant_id"]), exam.exam_id
            ),
        )
    if conflict:
        await message.answer(
            "⚠️ Konfliktlar (bir nechta nomzod):\n"
            + "\n".join(
                f"• participant <code>{p['participant_id']}</code> — "
                f"{escape(str(p.get('full_name')))}"
                for p in conflict[:10]
            )
            + "\n\nQo'lda bog'lash: <code>/offline_link_user PARTICIPANT_ID USER_ID</code>"
        )
    if unmatched:
        await message.answer(
            "❓ Telegram bilan bog'lanmagan offline ishtirokchilar:\n"
            + "\n".join(
                f"• <code>{p['participant_id']}</code> — "
                f"{escape(str(p.get('student_code')))} · "
                f"{escape(str(p.get('full_name')))}"
                for p in unmatched[:15]
            )
            + (
                "\n\nBu o'quvchilar botda ro'yxatdan o'tmagan bo'lishi mumkin — "
                "bu normal. Online natijasi bilan birlashtirish kerak bo'lsa, "
                "qo'lda bog'lang: <code>/offline_link_user PARTICIPANT_ID USER_ID</code>"
            )
        )
    if not suggested and not confirmed:
        await message.answer(
            "Taklif yo'q. Qo'lda bog'lash: "
            "<code>/offline_link_user PARTICIPANT_ID USER_ID</code>"
        )


@router.message(Command("offline_links"))
async def cmd_offline_links(message: Message, repos: Repositories) -> None:
    """`/offline_links KOD` — nomzodlar va tasdiqlangan bog'lanishlar."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    exam = await _exam(repos, _arg(message))
    if exam is None:
        await message.answer("Test kodi topilmadi. Ishlatish: <code>/offline_links KOD</code>")
        return
    await _send_links(message, repos, exam)


@router.message(Command("offline_link_user"))
async def cmd_offline_link_user(message: Message, repos: Repositories) -> None:
    """`/offline_link_user PARTICIPANT_ID USER_ID` — qo'lda tasdiqlash."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Ishlatish: <code>/offline_link_user PARTICIPANT_ID USER_ID</code>"
        )
        return
    try:
        participant_id, user_id = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("ID lar butun son bo'lishi kerak.")
        return
    try:
        await offline_import.link_participant(
            repos,
            participant_id=participant_id,
            user_id=user_id,
            admin_id=message.from_user.id if message.from_user else 0,
            method="manual",
        )
    except offline_import.OfflineImportError as exc:
        await message.answer(f"❌ {escape(str(exc))}")
        return
    await message.answer(
        "✅ Bog'landi. Agar bu foydalanuvchida online natija bo'lsa, "
        "u reytingdan chiqarildi."
    )


@router.message(Command("offline_unlink"))
async def cmd_offline_unlink(message: Message, repos: Repositories) -> None:
    """`/offline_unlink PARTICIPANT_ID` — bog'lanishni bekor qiladi."""
    if not _guard(message):
        return
    if not _enabled(message):
        await message.answer("Offline import hozircha o'chirilgan.")
        return
    try:
        participant_id = int(_arg(message))
    except ValueError:
        await message.answer("Ishlatish: <code>/offline_unlink PARTICIPANT_ID</code>")
        return
    try:
        await offline_import.unlink_participant(
            repos,
            participant_id=participant_id,
            admin_id=message.from_user.id if message.from_user else 0,
        )
    except offline_import.OfflineImportError as exc:
        await message.answer(f"❌ {escape(str(exc))}")
        return
    await message.answer("✅ Bog'lanish bekor qilindi.")


def _call_guard(call: CallbackQuery) -> bool:
    if not is_admin(call.from_user.id):
        log_denied("offline:callback", call.from_user.id, call.from_user.full_name)
        return False
    return True


@router.callback_query(OfflineAdminCallback.filter())
async def offline_callback(
    call: CallbackQuery,
    callback_data: OfflineAdminCallback,
    state: FSMContext,
    repos: Repositories,
) -> None:
    """Offline menyu va preview tugmalari."""
    if not _call_guard(call):
        await call.answer("Faqat admin uchun.", show_alert=True)
        return
    if not config.OFFLINE_IMPORT_ENABLED:
        await call.answer("Offline import o'chirilgan.", show_alert=True)
        return
    action = callback_data.action
    message = call.message
    admin_id = call.from_user.id

    if action in {"panel", "template", "import", "batches", "report", "links"}:
        exam = await repos.exams.get(int(callback_data.exam_id))
        if exam is None:
            await call.answer("Imtihon topilmadi.", show_alert=True)
            return
        await call.answer()
        if message is None:
            return
        if action == "panel":
            await _send_readiness(message, repos, exam)
        elif action == "template":
            await _send_template(message, repos, exam)
        elif action == "import":
            readiness = await offline_scoring.check_readiness(repos, exam)
            if not readiness.ready:
                await message.answer("❌ Import bloklandi.\n\n" + _readiness_text(readiness))
                return
            await state.set_state(OfflineImportStates.waiting_file)
            await state.update_data(offline_exam_id=exam.exam_id)
            await message.answer(
                f"📤 «{escape(str(exam.title))}» uchun `.xlsx` faylni yuboring."
            )
        elif action == "batches":
            await _send_batches(message, repos, exam)
        elif action == "report":
            await _send_reports(message, repos, exam)
        else:
            await _send_links(message, repos, exam)
        return

    if action == "batch_delete":
        batch = await repos.offline_batches.get_batch(int(callback_data.batch_id))
        if batch is None:
            await call.answer("Partiya topilmadi.", show_alert=True)
            return
        await call.answer()
        if message is not None:
            await message.answer(
                _delete_confirm_text(batch),
                reply_markup=offline_batch_delete_confirm_kb(
                    int(batch["batch_id"]), int(batch["exam_id"])
                ),
            )
        return

    if action == "batch_delete_confirm":
        await call.answer("O'chirilmoqda…")
        try:
            stats = await offline_import.delete_batch(
                repos, int(callback_data.batch_id), admin_id
            )
        except offline_import.OfflineImportError as exc:
            await call.answer(str(exc)[:190], show_alert=True)
            return
        except Exception:
            logger.exception(
                "Offline delete xatosi: batch_id=%s", callback_data.batch_id
            )
            await call.answer("Texnik xatolik. Qayta urinib ko'ring.", show_alert=True)
            return
        if message is not None:
            await message.edit_text(
                "🗑 <b>Partiya butunlay o'chirildi</b>\n"
                f"Qatorlar: <b>{stats.get('rows', 0)}</b> · "
                f"offline natijalar: <b>{stats.get('attempts', 0)}</b> · "
                f"ishtirokchilar: <b>{stats.get('participants', 0)}</b>\n"
                "Reyting qayta hisoblandi: bog'langan online natijalar qaytdi."
            )
        exam = (
            await repos.exams.get(int(callback_data.exam_id))
            if callback_data.exam_id
            else None
        )
        if exam is not None and message is not None:
            await _send_readiness(message, repos, exam)
        return

    if action == "confirm":
        await call.answer("Tasdiqlanmoqda…")
        try:
            result = await offline_import.commit_batch(
                repos, int(callback_data.batch_id), admin_id
            )
        except offline_import.OfflineImportError as exc:
            await call.answer(str(exc)[:190], show_alert=True)
            return
        except Exception:
            logger.exception("Offline commit xatosi: batch_id=%s", callback_data.batch_id)
            await call.answer("Texnik xatolik. Qayta urinib ko'ring.", show_alert=True)
            return
        if message is not None:
            await message.edit_text(
                "✅ <b>Import yakunlandi</b>\n"
                f"Qatnashchilar: <b>{result.participants}</b> "
                f"(yangi {result.created}, yangilangan {result.updated})\n"
                f"Oflayn natijalar: <b>{result.offline_count}</b>\n"
                f"Reytingdan chiqarilgan online: <b>{result.online_excluded}</b>"
            )
            try:
                exam = await repos.exams.get(int(callback_data.exam_id)) if callback_data.exam_id else None
                if exam is None:
                    batch = await repos.offline_batches.get_batch(int(callback_data.batch_id))
                    exam = await repos.exams.get(int(batch["exam_id"])) if batch else None
                if exam is not None:
                    # Excel alohida hisoblanmasin: darhol umumiy (offline+online)
                    # reyting yuboriladi.
                    report = await offline_report.build_combined_report(repos, exam)
                    data = report_pdf.build_combined_results_pdf(
                        meta=report.meta, students=list(report.students)
                    )
                    await message.answer_document(
                        BufferedInputFile(
                            data, filename=f"umumiy-reyting-{exam.test_code}.pdf"
                        ),
                        caption=(
                            f"📄 Umumiy reyting — {report.participants} ta qatnashchi\n"
                            f"Oflayn: {report.offline_count} · "
                            f"Onlayn: {report.online_count} · "
                            f"Chiqarilgan: {report.excluded_count}"
                        ),
                    )
            except Exception:
                logger.exception("Umumiy PDF commitdan keyin yasalmadi")
        return

    if action == "cancel":
        await call.answer()
        try:
            await offline_import.void_batch(repos, int(callback_data.batch_id), admin_id)
        except Exception:
            logger.exception("Offline bekor qilish xatosi")
        if message is not None:
            await message.edit_text("❌ Import bekor qilindi. Bazaga hech narsa yozilmadi.")
        return

    if action == "link_confirm":
        await call.answer()
        try:
            await offline_import.link_participant(
                repos,
                participant_id=int(callback_data.participant_id),
                user_id=int(callback_data.user_id),
                admin_id=admin_id,
                method="manual",
            )
        except offline_import.OfflineImportError as exc:
            if message is not None:
                await message.answer(f"❌ {escape(str(exc))}")
            return
        if message is not None:
            await message.edit_text("✅ Bog'lanish tasdiqlandi.")
        return

    if action == "unlink":
        await call.answer()
        try:
            await offline_import.unlink_participant(
                repos,
                participant_id=int(callback_data.participant_id),
                admin_id=admin_id,
            )
        except offline_import.OfflineImportError as exc:
            if message is not None:
                await message.answer(f"❌ {escape(str(exc))}")
            return
        if message is not None:
            await message.edit_text("🔓 Bog'lanish bekor qilindi.")
        return

    await call.answer()
