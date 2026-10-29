"""O'qituvchi (admin) Web App API'si — «⚙️ Test yaratish» paneli.

Mini App ichidagi admin bo'limi uchun endpoint'lar::

    GET  /api/v2/me                         — foydalanuvchi + `is_admin`
    GET  /api/v2/admin/exams                — imtihonlar ro'yxati
    POST /api/v2/admin/exams                — yangi test yaratish
    POST /api/v2/admin/exams/{id}/schedule  — vaqtlarni o'zgartirish
    GET  /api/v2/admin/exams/{id}/participants — qatnashchilar ro'yxati
    POST /api/v2/admin/exams/{id}/regrade   — qayta baholash
    POST /api/v2/admin/exams/{id}/report-send — PDF ni adminga chatda yuborish
    GET  /api/v2/admin/exams/{id}/solutions — «🎬 Yechimlar» qamrovi
    POST /api/v2/admin/solutions/delete     — bitta yechimni o'chirish

    Yechim faqat **video yoki rasm** (`file_id`) ko'rinishida bo'ladi; matnli
    yechim qo'llanmaydi. Fayl Mini App'dan emas, **bot orqali** yuklanadi
    (deep-link) — `file_id` ni faqat Telegram Bot API bera oladi.

**Xavfsizlik:** har bir admin endpoint'i **server tomonda** `config.is_admin`
tekshiradi (:func:`ensure_admin`). Frontend'da tugmani yashirish yetarli emas —
endpoint'ni to'g'ridan-to'g'ri chaqirish ham rad etilishi shart.

Yaratish mantig'i `services.exam_admin` da (bot ustasi bilan **bir xil**) — bu
modul faqat HTTP qatlami.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from html import escape as html_escape
from typing import Any

from aiogram.types import BufferedInputFile
from aiohttp import web

import config
from database.models import normalize_part
from services import exam_admin, exam_service, grading, report_data, report_pdf
from services import solutions as solutions_service
from web.api import ApiError, ensure_user, get_bot, read_json, repositories

logger = logging.getLogger(__name__)

#: Ro'yxatda ko'rsatiladigan imtihonlar chegarasi.
MAX_EXAMS: int = 30

#: PDF havolasi qancha sekund amal qiladi (10 daqiqa).
REPORT_TTL_SECONDS: int = 600


async def ensure_admin(request: web.Request) -> dict[str, Any]:
    """Foydalanuvchi admin ekanini tekshiradi (aks holda `403`)."""
    user = await ensure_user(request)
    if not config.is_admin(user["user_id"]):
        raise ApiError(403, "Bu bo'lim faqat o'qituvchi (admin) uchun.")
    return user


def exam_payload(exam: Any, *, now_db: str, submissions: int) -> dict[str, Any]:
    """Imtihonni ro'yxat/panel uchun JSON ko'rinishiga keltiradi."""
    status = exam_service.status_of(exam, now_db)
    return {
        "exam_id": exam.exam_id,
        "title": exam.title,
        "test_code": exam.test_code,
        "total_questions": exam.total_questions,
        "status": status.value,
        "status_title": exam_service.status_title(status),
        "start_local": exam_service.format_local(exam.start_time),
        "end_local": exam_service.format_local(exam.end_time),
        "result_local": exam_service.format_local(exam.result_time),
        # `datetime-local` input'lari uchun tayyor qiymatlar (tahrirlash formasi).
        "start_input": exam_service.format_local(exam.start_time, "%Y-%m-%dT%H:%M"),
        "end_input": exam_service.format_local(exam.end_time, "%Y-%m-%dT%H:%M"),
        "result_input": exam_service.format_local(exam.result_time, "%Y-%m-%dT%H:%M"),
        "submissions": int(submissions),
    }


async def me(request: web.Request) -> web.Response:
    """Foydalanuvchi haqida qisqa ma'lumot (admin tugmasini ko'rsatish uchun)."""
    user = await ensure_user(request)
    return web.json_response(
        {
            "ok": True,
            "user_id": user["user_id"],
            "full_name": user.get("full_name"),
            "is_admin": config.is_admin(user["user_id"]),
        }
    )


async def list_exams(request: web.Request) -> web.Response:
    """Imtihonlar ro'yxati (faqat admin)."""
    await ensure_admin(request)
    repos = repositories(request)
    exams = await repos.exams.list_all(limit=MAX_EXAMS)
    now = exam_service.now_db()
    rows: list[dict[str, Any]] = []
    for exam in exams:
        payload = exam_payload(
            exam,
            now_db=now,
            submissions=await repos.answers.count_for_exam(exam.exam_id),
        )
        try:
            items, missing = await _coverage_items(repos, exam)
            payload["solutions_total"] = len(items)
            payload["solutions_covered"] = len(items) - len(missing)
        except Exception:  # bitta buzuq imtihon ro'yxatni to'xtatmasin
            logger.exception(
                "Yechim qamrovini hisoblab bo'lmadi: exam_id=%s", exam.exam_id
            )
        rows.append(payload)
    return web.json_response({"ok": True, "exams": rows})


def _parse_db_time(body: dict[str, Any], field: str) -> str:
    """Mahalliy vaqtni bazaga yoziladigan (UTC ISO) qiymatga o'giradi."""
    raw = str(body.get(field) or "").strip()
    if not raw:
        raise ApiError(
            400, "Boshlanish, tugash va natija vaqtlari to'ldirilishi shart."
        )
    try:
        return exam_service.to_db_time(exam_service.parse_local_datetime(raw))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc


async def create_exam(request: web.Request) -> web.Response:
    """«Test yaratish» formasi: yangi imtihon + forma + sessiya (faqat admin)."""
    user = await ensure_admin(request)
    repos = repositories(request)
    body = await read_json(request)

    start_db = _parse_db_time(body, "start_time")
    end_db = _parse_db_time(body, "end_time")
    result_db = _parse_db_time(body, "result_time")
    try:
        exam_service.validate_schedule(
            exam_service.parse_db_time(start_db),
            exam_service.parse_db_time(end_db),
            exam_service.parse_db_time(result_db),
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        total = int(body.get("total_questions") or 0)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "Savollar soni butun son bo'lishi kerak.") from exc

    try:
        created = await exam_admin.create_exam(
            repos,
            title=str(body.get("title") or ""),
            test_code=str(body.get("test_code") or ""),
            total_questions=total,
            answer_key=str(body.get("answer_key") or ""),
            difficulty=body.get("difficulty"),
            start_time=start_db,
            end_time=end_db,
            result_time=result_db,
            created_by=int(user["user_id"]),
        )
    except exam_admin.ExamAdminError as exc:
        raise ApiError(400, str(exc)) from exc

    return web.json_response(
        {
            "ok": True,
            "exam_id": created.exam_id,
            "test_code": created.test_code,
            "form_id": created.form_id,
            "session_id": created.session_id,
            "kinds": created.kinds,
        }
    )


def _exam_id(request: web.Request) -> int:
    """Marshrutdan `exam_id` ni o'qiydi (noto'g'ri bo'lsa — 400)."""
    try:
        return int(request.match_info["exam_id"])
    except (KeyError, ValueError) as exc:
        raise ApiError(400, "Imtihon ID si noto'g'ri.") from exc


async def update_schedule(request: web.Request) -> web.Response:
    """Yaratilgan imtihonning boshlanish/tugash/natija vaqtlarini o'zgartiradi.

    Vaqtlar `exams` va `exam_sessions` jadvallarida **birga** yangilanadi —
    botdagi ro'yxat, v1 va item-level (`/api/v2/*`) oqimlari bir xil oynani
    ko'rishi uchun. Tugash vaqti kelajakka surilsa, imtihon qayta ochiladi
    va fon baholash yangi javoblarni ham hisoblaydi.
    """
    await ensure_admin(request)
    repos = repositories(request)
    exam_id = _exam_id(request)
    body = await read_json(request)

    start_db = _parse_db_time(body, "start_time")
    end_db = _parse_db_time(body, "end_time")
    result_db = _parse_db_time(body, "result_time")

    try:
        await exam_admin.update_exam_times(
            repos,
            exam_id=exam_id,
            start_time=start_db,
            end_time=end_db,
            result_time=result_db,
        )
    except exam_admin.ExamAdminError as exc:
        raise ApiError(400, str(exc)) from exc

    exam = await repos.exams.get(exam_id)
    if exam is None:  # pragma: no cover - update muvaffaqiyatli bo'lsa bo'lmaydi
        raise ApiError(404, "Imtihon topilmadi.")
    return web.json_response(
        {
            "ok": True,
            "exam": exam_payload(
                exam,
                now_db=exam_service.now_db(),
                submissions=await repos.answers.count_for_exam(exam.exam_id),
            ),
        }
    )


def _submitted_text(value: str | None) -> str:
    """`submitted_at` ni ro'yxat uchun qisqa ko'rinishga keltiradi."""
    clean = str(value or "").strip().replace("T", " ")
    return clean[:16] if clean else "—"


async def exam_participants(request: web.Request) -> web.Response:
    """Imtihonda qatnashganlar ro'yxati va soni (faqat admin).

    Har bir yozuv: Telegram ID, ism (`@username` bilan), yuborilgan vaqt va
    baholangan bo'lsa — to'g'ri javoblar soni. Baholar `result_time` dan
    qat'i nazar ko'rsatiladi: bu ma'lumot faqat o'qituvchi uchun.
    """
    await ensure_admin(request)
    repos = repositories(request)
    exam_id = _exam_id(request)
    exam = await repos.exams.get(exam_id)
    if exam is None:
        raise ApiError(404, "Imtihon topilmadi.")

    participants = await repos.answers.list_participants(exam.exam_id)
    return web.json_response(
        {
            "ok": True,
            "exam_id": exam.exam_id,
            "title": exam.title,
            "test_code": exam.test_code,
            "count": len(participants),
            "total_questions": exam.total_questions,
            "participants": [
                {
                    "user_id": item.user_id,
                    "full_name": item.full_name,
                    "username": item.username,
                    "submitted_at": item.submitted_at,
                    "submitted_at_short": _submitted_text(item.submitted_at),
                    "graded": item.is_graded,
                    "raw_score": item.raw_score if item.is_graded else None,
                    "theta": item.theta if item.is_graded else None,
                }
                for item in participants
            ],
        }
    )


async def regrade_exam(request: web.Request) -> web.Response:
    """Imtihonni qayta baholash (faqat admin)."""
    await ensure_admin(request)
    repos = repositories(request)
    try:
        exam_id = int(request.match_info["exam_id"])
    except (KeyError, ValueError) as exc:
        raise ApiError(400, "Imtihon ID si noto'g'ri.") from exc

    exam = await repos.exams.get(exam_id)
    if exam is None:
        raise ApiError(404, "Imtihon topilmadi.")
    try:
        graded = await grading.grade_exam(repos, exam, regrade=True)
    except Exception as exc:
        logger.exception("Qayta baholashda xatolik: exam_id=%s", exam_id)
        raise ApiError(
            400, "Qayta baholashda xatolik. Kalit va 'b' ni tekshiring."
        ) from exc

    return web.json_response({"ok": True, "graded": graded})


# ---------------------------------------------------------------------------
# PDF hisobot: stateless HMAC token (vaqtinchalik, saqlanmaydi)
# ---------------------------------------------------------------------------
def _token_secret() -> bytes:
    """Token uchun maxfiy kalit (`BOT_TOKEN` allaqachon maxfiy)."""
    return (config.BOT_TOKEN or "rasch-report-secret").encode("utf-8")


def make_report_token(exam_id: int, *, now: int | None = None) -> str:
    """`exam_id.timestamp.signature` ko'rinishidagi token yasaydi."""
    stamp = int(time.time() if now is None else now)
    payload = f"{int(exam_id)}.{stamp}"
    signature = hmac.new(
        _token_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]
    return f"{payload}.{signature}"


def parse_report_token(token: str) -> int | None:
    """Tokenni tekshiradi va `exam_id` ni qaytaradi (yaroqsiz → `None`)."""
    parts = str(token or "").split(".")
    if len(parts) != 3:
        return None
    exam_raw, stamp_raw, signature = parts
    payload = f"{exam_raw}.{stamp_raw}"
    expected = hmac.new(
        _token_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        exam_id, stamp = int(exam_raw), int(stamp_raw)
    except ValueError:
        return None
    if (time.time() - stamp) > REPORT_TTL_SECONDS:
        return None
    return exam_id


def _forwarded_first(request: web.Request, header: str) -> str:
    """Proksi sarlavhasidan birinchi qiymatni oladi (`a, b` → `a`)."""
    raw = request.headers.get(header, "")
    return raw.split(",")[0].strip()


def public_base_url(request: web.Request) -> str:
    """Mini App ochilgan **ommaviy** manzilni (`https://domen`) aniqlaydi.

    `request.url.origin()` faqat soket sxemasini ko'radi: Railway, Cloudflare
    Tunnel, ngrok kabi proksilar ortida u doim `http://...` bo'ladi, holbuki
    foydalanuvchi sahifasi `https://...` da ochilgan. Bunday manzilni `fetch`
    qilishda brauzer «aralash kontent» (mixed content) deb bloklaydi — PDF
    o'rniga «Failed to fetch» xatosi chiqadi. Tartib:

        1. proksi sarlavhalari (`X-Forwarded-Proto` / `X-Forwarded-Host`);
        2. `WEBAPP_URL` sxemasi (ommaviy manzil HTTPS bo'lsa — HTTPS);
        3. so'rovning o'z sxemasi (lokal ishlab chiqishda `http`).
    """
    proto = _forwarded_first(request, "X-Forwarded-Proto").lower()
    host = _forwarded_first(request, "X-Forwarded-Host") or _forwarded_first(
        request, "Host"
    )
    if not host:
        return str(request.url.origin()).rstrip("/")
    if proto not in {"http", "https"}:
        proto = request.url.scheme
        if proto == "http" and config.WEBAPP_URL.startswith("https://"):
            proto = "https"
    return f"{proto}://{host}"


async def report_link(request: web.Request) -> web.Response:
    """PDF uchun vaqtinchalik havola yasaydi (faqat admin).

    `url` — to'liq (ommaviy) manzil, `path` — shu serverdagi yo'l. Mini App
    PDF ni har doim `path` bo'yicha **o'z origin'ida** yuklaydi: proksi ortida
    `url` `http://...` bo'lib qolsa ham brauzer aralash kontentni bloklamaydi.
    """
    await ensure_admin(request)
    repos = repositories(request)
    try:
        exam_id = int(request.match_info["exam_id"])
    except (KeyError, ValueError) as exc:
        raise ApiError(400, "Imtihon ID si noto'g'ri.") from exc
    if await repos.exams.get(exam_id) is None:
        raise ApiError(404, "Imtihon topilmadi.")
    token = make_report_token(exam_id)
    path = f"/api/v2/report/{token}"
    return web.json_response(
        {
            "ok": True,
            "url": f"{public_base_url(request)}{path}",
            "path": path,
            "ttl": REPORT_TTL_SECONDS,
        },
        # Havola bir martalik va shaxsiy — proksi/brauzer keshlmasin.
        headers={"Cache-Control": "no-store"},
    )


async def report_pdf_view(request: web.Request) -> web.Response:
    """Tokenni tekshirib, o'quvchilar natijalari PDF ini qaytaradi."""
    repos = repositories(request)
    exam_id = parse_report_token(request.match_info.get("token", ""))
    if exam_id is None:
        raise ApiError(403, "Havola yaroqsiz yoki muddati o'tgan — qaytadan oling.")
    exam = await repos.exams.get(exam_id)
    if exam is None:
        raise ApiError(404, "Imtihon topilmadi.")
    try:
        report = await report_data.build_exam_report(repos, exam)
        data = report_pdf.build_results_pdf(
            title=report.title,
            test_code=report.test_code,
            date_text=report.date_text,
            participants=report.participants,
            students=report.students,
        )
    except report_pdf.ReportError as exc:
        raise ApiError(500, str(exc)) from exc

    filename = f"natijalar-{exam.test_code}.pdf"
    return web.Response(
        body=data,
        content_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            # Hisobotda o'quvchilarning shaxsiy natijalari bor — keshlanmasin.
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def report_send(request: web.Request) -> web.Response:
    """PDF hisobotni adminga Telegram chatda yuboradi.

    Mini App'dagi «📄 PDF» tugmasi shu endpoint'ni chaqiradi: fayl brauzer
    yuklamasi sifatida emas, **bot orqali** adminga shaxsiy chatda keladi.
    Shu tufayli PDF Telegram'da saqlanadi — WebView yuklamasi iOS'da
    saqlanmay, Android'da ko'rinmas papkaga tushib qolmaydi.
    """
    user = await ensure_admin(request)
    repos = repositories(request)
    bot = get_bot(request)
    if bot is None:
        raise ApiError(503, "Bot ishlamayapti — PDF ni chatga yuborib bo'lmaydi.")
    try:
        exam_id = int(request.match_info["exam_id"])
    except (KeyError, ValueError) as exc:
        raise ApiError(400, "Imtihon ID si noto'g'ri.") from exc
    exam = await repos.exams.get(exam_id)
    if exam is None:
        raise ApiError(404, "Imtihon topilmadi.")

    try:
        report = await report_data.build_exam_report(repos, exam)
        data = report_pdf.build_results_pdf(
            title=report.title,
            test_code=report.test_code,
            date_text=report.date_text,
            participants=report.participants,
            students=report.students,
        )
    except report_pdf.ReportError as exc:
        raise ApiError(500, str(exc)) from exc
    except Exception as exc:
        logger.exception("PDF hisobot yasalmadi: exam_id=%s", exam_id)
        raise ApiError(
            500, "Hisobotni yasashda xatolik yuz berdi. Keyinroq qayta urinib ko'ring."
        ) from exc

    filename = f"natijalar-{exam.test_code}.pdf"
    try:
        await bot.send_document(
            chat_id=int(user["user_id"]),
            document=BufferedInputFile(data, filename=filename),
            caption=(
                f"📄 «{html_escape(str(exam.title))}» — natijalar\n"
                f"O'quvchilar: <b>{report.participants}</b> ta"
            ),
        )
    except Exception as exc:
        logger.exception(
            "PDF hisobotni chatga yuborib bo'lmadi: exam_id=%s, admin=%s",
            exam_id,
            user["user_id"],
        )
        raise ApiError(
            502,
            "PDF ni chatga yuborib bo'lmadi. Bot bilan chatni ochib /start "
            "bosganingizni tekshirib, qayta urinib ko'ring.",
        ) from exc

    logger.info(
        "PDF hisobot chatga yuborildi: exam_id=%s, kod=%s, o'quvchilar=%d, admin=%s",
        exam_id,
        exam.test_code,
        report.participants,
        user["user_id"],
    )
    return web.json_response(
        {
            "ok": True,
            "sent": True,
            "participants": report.participants,
            "filename": filename,
        }
    )


# ---------------------------------------------------------------------------
# «🎬 Yechimlar» bo'limi (admin): qamrov (video/rasm) va o'chirish
# ---------------------------------------------------------------------------
async def _bot_username(request: web.Request) -> str | None:
    """Botning `@username` i (deep-link uchun) — bir marta olib **keshlanadi**."""
    bot = get_bot(request)
    if bot is None:
        return None
    cached = request.app.get("bot_username")
    if cached:
        return str(cached)
    try:
        me = await bot.get_me()
    except Exception:  # tarmoq/Telegram xatosi — deep-link ko'rsatilmaydi
        logger.info("Bot username olinmadi (deep-link ko'rsatilmaydi)", exc_info=True)
        return None
    username = getattr(me, "username", None)
    if not username:
        return None
    request.app["bot_username"] = str(username)
    return str(username)


def _parse_solution_target(body: dict[str, Any]) -> tuple[int, int, str]:
    """So'rovdan `(exam_id, question, part)` ni o'qiydi va tekshiradi."""
    try:
        exam_id = int(body.get("exam_id") or 0)
        number = int(body.get("question") or 0)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "Imtihon ID si va savol raqami butun son bo'lishi kerak.") from exc
    if exam_id <= 0 or number <= 0:
        raise ApiError(400, "Imtihon ID si va savol raqami ko'rsatilishi shart.")
    try:
        part = normalize_part(str(body.get("part") or ""))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    return exam_id, number, part


async def _coverage_items(
    repos: Repositories, exam: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    """Imtihonning kutiladigan savollari va qamrov holati: `(items, missing)`.

    Kutiladigan savollar imtihonning **o'z tuzilmasidan** olinadi
    (`solutions.build_question_units(exam, None)`) — 1…N va 36a/36b qismlari.
    Shu bilan qaysi savolda yechim **bor**, qaysinisida **yo'q** aniqlanadi.
    """
    units = solutions_service.build_question_units(exam, None)
    existing = await repos.solutions.list_for_exam(exam.exam_id)
    by_key = {
        (int(solution.question_number), normalize_part(solution.part)): solution
        for solution in existing
    }

    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for unit in units:
        solution = by_key.get((unit.number, unit.part))
        # Qamrov faqat faylli yechim (video/rasm) bo'yicha hisoblanadi: bazada
        # qolgan eski matnli yozuvlar yechim hisoblanmaydi.
        covered = solution is not None and solution.is_file
        label = f"{unit.number}{unit.part}"
        items.append(
            {
                "number": unit.number,
                "part": unit.part,
                "label": label,
                "covered": covered,
                "type": str(solution.solution_type) if covered else None,
                "type_title": solution.type.title if covered else None,
                "is_file": covered,
                "updated_at": solution.updated_at if covered else None,
            }
        )
        if not covered:
            missing.append(label)
    return items, missing


async def exam_solutions(request: web.Request) -> web.Response:
    """Imtihon bo'yicha yechimlar **qamrovi** (faqat admin)."""
    await ensure_admin(request)
    repos = repositories(request)
    try:
        exam_id = int(request.match_info["exam_id"])
    except (KeyError, ValueError) as exc:
        raise ApiError(400, "Imtihon ID si noto'g'ri.") from exc
    exam = await repos.exams.get(exam_id)
    if exam is None:
        raise ApiError(404, "Imtihon topilmadi.")

    items, missing = await _coverage_items(repos, exam)
    return web.json_response(
        {
            "ok": True,
            "exam_id": exam.exam_id,
            "title": exam.title,
            "test_code": exam.test_code,
            "total": len(items),
            "covered": len(items) - len(missing),
            "missing": missing,
            "bot_username": await _bot_username(request),
            "items": items,
        }
    )


async def delete_solution(request: web.Request) -> web.Response:
    """Bitta savol (yoki qism) yechimini o'chiradi (faqat admin)."""
    await ensure_admin(request)
    repos = repositories(request)
    body = await read_json(request)
    exam_id, number, part = _parse_solution_target(body)
    exam = await repos.exams.get(exam_id)
    if exam is None:
        raise ApiError(404, "Imtihon topilmadi.")
    await repos.solutions.delete(exam_id, number, part)
    logger.info(
        "Yechim o'chirildi: exam_id=%s, savol=%s%s", exam_id, number, part
    )
    return web.json_response({"ok": True})


def setup_routes(app: web.Application) -> None:
    """`/api/v2/me`, `/api/v2/admin/*` va PDF havolasi marshrutlarini ulaydi."""
    router = app.router
    router.add_get("/api/v2/me", me)
    router.add_get("/api/v2/admin/exams", list_exams)
    router.add_post("/api/v2/admin/exams", create_exam)
    # Yaratilgan test vaqtini tahrirlash va qatnashchilarni ko'rish.
    router.add_post("/api/v2/admin/exams/{exam_id}/schedule", update_schedule)
    router.add_get("/api/v2/admin/exams/{exam_id}/participants", exam_participants)
    router.add_post("/api/v2/admin/exams/{exam_id}/regrade", regrade_exam)
    router.add_post("/api/v2/admin/exams/{exam_id}/report-link", report_link)
    # Mini App «📄 PDF» tugmasi: fayl brauzerga emas, adminga chatga yuboriladi.
    router.add_post("/api/v2/admin/exams/{exam_id}/report-send", report_send)
    # «🎬 Yechimlar» bo'limi (admin). Fayl (video/rasm) faqat bot orqali
    # yuklanadi — `file_id` ni Telegram Bot API beradi.
    router.add_get("/api/v2/admin/exams/{exam_id}/solutions", exam_solutions)
    router.add_post("/api/v2/admin/solutions/delete", delete_solution)
    router.add_get("/api/v2/report/{token}", report_pdf_view)
