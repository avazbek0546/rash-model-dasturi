"""Web App uchun JSON API (`/api/*`).

Xavfsizlik qoidalari
--------------------
* Har bir so'rov `X-Init-Data` header'idagi Telegram `initData` bilan
  tekshiriladi (`services.webapp_auth`) — boshqa odam nomidan so'rov yuborib
  bo'lmaydi.
* `answer_key` va `difficulty_logits` **hech qachon** javobda qaytarilmaydi;
  natija tafsilotlari esa faqat `result_time` kelgandan keyin beriladi.
* Baholash to'liq serverda (Rasch modeli) bajariladi.

Endpoint'lar
------------
    GET  /api/health            — server tirikligi (autentifikatsiyasiz)
    GET  /api/me                — profil + ishlangan testlar soni
    POST /api/me                — ism-familiyani tahrirlash
    GET  /api/exams             — navbat: faol/kutilayotgan/tugagan imtihonlar
    POST /api/submit            — {test_code, answers} ni qabul qilish
    GET  /api/results           — natijalar tarixi + grafik ma'lumotlari
    GET  /api/results/{exam_id} — bitta imtihon bo'yicha batafsil hisobot
    GET  /api/offline           — hududlar bo'yicha imtihonlar (statik)
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

import config
from database.models import SKIPPED, ExamStatus, User
from database.repository import AlreadySubmittedError, Repositories
from services import answer_key, exam_service, grading, webapp_auth

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """API javobida ko'rsatiladigan xatolik (status + o'zbekcha izoh)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# Hududlar bo'yicha (offline) imtihonlar — statik ro'yxat, kelajakda bazadan
# yoki alohida fayldan yuklanishi mumkin (hozircha "tayyor joy").
OFFLINE_REGIONS: list[dict[str, Any]] = [
    {"region": "Toshkent shahri", "status": "planned", "note": "Tez kunda"},
    {"region": "Toshkent viloyati", "status": "planned", "note": "Tez kunda"},
    {"region": "Samarqand", "status": "planned", "note": "Tez kunda"},
    {"region": "Buxoro", "status": "planned", "note": "Tez kunda"},
    {"region": "Farg'ona", "status": "planned", "note": "Tez kunda"},
    {"region": "Namangan", "status": "planned", "note": "Tez kunda"},
    {"region": "Andijon", "status": "planned", "note": "Tez kunda"},
    {"region": "Qashqadaryo", "status": "planned", "note": "Tez kunda"},
    {"region": "Surxondaryo", "status": "planned", "note": "Tez kunda"},
    {"region": "Xorazm", "status": "planned", "note": "Tez kunda"},
    {"region": "Navoiy", "status": "planned", "note": "Tez kunda"},
    {"region": "Jizzax", "status": "planned", "note": "Tez kunda"},
    {"region": "Sirdaryo", "status": "planned", "note": "Tez kunda"},
    {"region": "Qoraqalpog'iston", "status": "planned", "note": "Tez kunda"},
]


# ---------------------------------------------------------------------------
# Umumiy yordamchilar
# ---------------------------------------------------------------------------
def error_response(status: int, message: str) -> web.Response:
    """Standart xatolik javobi (frontend `error` maydonini o'qiydi)."""
    return web.json_response({"ok": False, "error": message}, status=status)


def repositories(request: web.Request) -> Repositories:
    """Ilovaga biriktirilgan repository konteynerini qaytaradi."""
    return request.app["repos"]


async def read_json(request: web.Request) -> dict[str, Any]:
    """So'rov tanasini JSON sifatida o'qiydi (bo'sh/buzuq bo'lsa — xatolik)."""
    if not request.can_read_body:
        return {}
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError(400, "So'rov tanasi JSON formatida emas.") from exc
    if not isinstance(data, dict):
        raise ApiError(400, "So'rov tanasi JSON obyekt bo'lishi kerak.")
    return data


def _init_data(request: web.Request) -> str | None:
    """`initData` ni header'dan oladi (X-Init-Data yoki Authorization: tma ...)."""
    direct = request.headers.get("X-Init-Data")
    if direct:
        return direct.strip()
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("tma "):
        return authorization[4:].strip()
    return None


def current_user(request: web.Request) -> dict[str, Any]:
    """So'rov egasini Telegram `initData` bo'yicha aniqlaydi.

    Raises:
        webapp_auth.WebAppAuthError: autentifikatsiya muvaffaqiyatsiz bo'lsa.
    """
    debug_header = request.headers.get("X-Debug-User-Id", "")
    debug_user_id = int(debug_header) if debug_header.isdigit() else None
    return webapp_auth.identify_user(_init_data(request), debug_user_id=debug_user_id)


async def ensure_user(request: web.Request) -> dict[str, Any]:
    """Foydalanuvchini aniqlab, `users` jadvalini sinxronlaydi."""
    user = current_user(request)
    repos = repositories(request)
    if await repos.users.get(user["user_id"]) is None:
        await repos.users.upsert(
            User(
                user_id=user["user_id"],
                full_name=user["full_name"],
                username=user["username"],
            )
        )
    return user


@web.middleware
async def error_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """Kutilgan xatoliklarni bir xil JSON ko'rinishiga o'giradi."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except webapp_auth.WebAppAuthError as exc:
        logger.info("API 401: %s", exc)
        return error_response(401, f"Autentifikatsiya xatosi: {exc}")
    except AlreadySubmittedError:
        return error_response(409, "Siz bu imtihonga allaqachon javob yuborgansiz.")
    except answer_key.AnswerKeyError as exc:
        return error_response(400, f"Javoblar formati noto'g'ri: {exc}")
    except ApiError as exc:
        return error_response(exc.status, exc.message)
    except Exception:
        logger.exception("API'da kutilmagan xatolik: %s %s", request.method, request.path)
        return error_response(500, "Serverda kutilmagan xatolik yuz berdi.")


# ---------------------------------------------------------------------------
# GET /api/health — autentifikatsiyasiz (monitoring uchun)
# ---------------------------------------------------------------------------
async def health(request: web.Request) -> web.Response:
    """Server tirikligini va vaqtni qaytaradi."""
    return web.json_response(
        {"ok": True, "time": exam_service.now_db(), "time_local": exam_service.format_local(exam_service.utc_now())}
    )


# ---------------------------------------------------------------------------
# /api/me — profil
# ---------------------------------------------------------------------------
async def get_me(request: web.Request) -> web.Response:
    """Foydalanuvchi profili: ism, Telegram ID, ishlangan testlar soni."""
    user = await ensure_user(request)
    repos = repositories(request)
    saved = await repos.users.get(user["user_id"])
    return web.json_response(
        {
            "ok": True,
            "user_id": user["user_id"],
            "full_name": (saved.full_name if saved and saved.full_name else user["full_name"]),
            "username": user["username"],
            "tests_done": await repos.answers.count_for_user(user["user_id"]),
            "dev_mode": config.WEBAPP_DEV_MODE,
            "timezone": config.TIMEZONE,
            "now_local": exam_service.format_local(exam_service.utc_now()),
        }
    )


async def update_me(request: web.Request) -> web.Response:
    """Ism-familiyani tahrirlaydi (`users` jadvali yangilanadi)."""
    user = await ensure_user(request)
    data = await read_json(request)
    full_name = " ".join(str(data.get("full_name", "")).split())
    if not 3 <= len(full_name) <= 120:
        raise ApiError(400, "Ism-familiya 3–120 belgidan iborat bo'lishi kerak.")

    await repositories(request).users.update_full_name(user["user_id"], full_name)
    logger.info("Profil yangilandi: user_id=%s, full_name=%r", user["user_id"], full_name)
    return web.json_response({"ok": True, "full_name": full_name})


# ---------------------------------------------------------------------------
# GET /api/exams — "Navbat" bo'limi
# ---------------------------------------------------------------------------
async def _exam_payload(request: web.Request, exam: Any, user_id: int, now: str) -> dict[str, Any]:
    """Bitta imtihon haqidagi ma'lumot (kalit va logitlar ko'rsatilmaydi)."""
    repos = repositories(request)
    status = exam_service.status_of(exam, now)
    submission = await repos.answers.get(user_id, exam.exam_id)
    average = exam_service.average_difficulty(exam)

    payload: dict[str, Any] = {
        "exam_id": exam.exam_id,
        "title": exam.title,
        "status": status.value,
        "status_title": exam_service.status_title(status),
        "total_questions": exam.total_questions,
        "average_difficulty": round(average, 3) if average is not None else None,
        "start_time_local": exam_service.format_local(exam.start_time),
        "end_time_local": exam_service.format_local(exam.end_time),
        "result_time_local": exam_service.format_local(exam.result_time),
        "seconds_left": exam_service.seconds_left(exam, now),
        "submitted": submission is not None,
        "can_submit": status is ExamStatus.ACTIVE and submission is None,
        "published": status is ExamStatus.PUBLISHED,
    }

    if submission is not None and submission.is_graded and status is ExamStatus.PUBLISHED:
        payload["my_result"] = {
            "theta": submission.theta,
            "scaled_score": submission.scaled_score,
            "raw_score": submission.raw_score,
        }
    return payload


async def list_exams(request: web.Request) -> web.Response:
    """Natijasi hali e'lon qilinmagan imtihonlar ro'yxati + o'quvchi holati."""
    user = await ensure_user(request)
    repos = repositories(request)
    now = exam_service.now_db()
    exams = await repos.exams.list_relevant(now)
    items = [await _exam_payload(request, exam, user["user_id"], now) for exam in exams]
    return web.json_response(
        {
            "ok": True,
            "now": now,
            "now_local": exam_service.format_local(now),
            "exams": items,
        }
    )


# ---------------------------------------------------------------------------
# POST /api/submit — javoblarni qabul qilish
# ---------------------------------------------------------------------------
async def submit_answers(request: web.Request) -> web.Response:
    """Test kodi va javoblar varag'ini qabul qiladi (faqat faol oynada)."""
    user = await ensure_user(request)
    repos = repositories(request)
    data = await read_json(request)

    code = str(data.get("test_code", ""))
    try:
        code = exam_service.validate_test_code(code)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    raw_answers = str(data.get("answers", ""))

    exam = await repos.exams.get_by_code(code)
    if exam is None:
        raise ApiError(404, "Bunday test kodi topilmadi. Kodni tekshirib qayta kiriting.")

    allowed, reason = exam_service.can_submit(exam)
    if not allowed:
        raise ApiError(403, reason)

    if await repos.answers.get(user["user_id"], exam.exam_id) is not None:
        raise ApiError(409, "Siz bu imtihonga allaqachon javob yuborgansiz.")

    letters = answer_key.parse_submitted(raw_answers, exam.total_questions)
    answered = sum(1 for letter in letters if letter != SKIPPED)
    if answered == 0:
        raise ApiError(400, "Javoblar bo'sh — kamida bitta savolga variant belgilang.")

    # Javoblar kanonik ko'rinishda saqlanadi ("1A2B3X4D") — keyin bir xilda tahlil qilinadi.
    canonical = answer_key.format_compact(letters)
    submission_id = await repos.answers.submit(
        user_id=user["user_id"], exam_id=exam.exam_id, submitted_answers=canonical
    )
    logger.info(
        "Javob qabul qilindi: user_id=%s, exam_id=%s, belgilangan=%d/%d",
        user["user_id"],
        exam.exam_id,
        answered,
        exam.total_questions,
    )
    return web.json_response(
        {
            "ok": True,
            "submission_id": submission_id,
            "exam_id": exam.exam_id,
            "title": exam.title,
            "answered": answered,
            "total_questions": exam.total_questions,
            "result_time_local": exam_service.format_local(exam.result_time),
            "message": (
                f"Javoblaringiz qabul qilindi ({answered}/{exam.total_questions}). "
                f"Natijalar {exam_service.format_local(exam.result_time)} da e'lon qilinadi."
            ),
        }
    )


# ---------------------------------------------------------------------------
# GET /api/results — "Natijalar" bo'limi
# ---------------------------------------------------------------------------
async def list_results(request: web.Request) -> web.Response:
    """O'quvchining javoblari: e'lon qilinganlari va natijasi kutilayotganlari."""
    user = await ensure_user(request)
    repos = repositories(request)
    now = exam_service.now_db()
    submissions = await repos.answers.list_for_user(user["user_id"])

    published: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for submission in submissions:
        is_published = submission.result_time is not None and submission.result_time <= now
        entry: dict[str, Any] = {
            "exam_id": submission.exam_id,
            "title": submission.exam_title or f"Imtihon #{submission.exam_id}",
            "total_questions": submission.total_questions or 0,
            "submitted_at": (submission.submitted_at or "")[:16],
            "published": is_published,
            "result_time_local": (
                exam_service.format_local(submission.result_time)
                if submission.result_time
                else None
            ),
        }
        if is_published and submission.is_graded:
            entry.update(
                {
                    "theta": submission.theta,
                    "scaled_score": submission.scaled_score,
                    "raw_score": submission.raw_score,
                }
            )
            published.append(entry)
        else:
            pending.append(entry)

    chart_source = sorted(published, key=lambda item: item["submitted_at"])
    average = (
        sum(item["scaled_score"] for item in published) / len(published) if published else None
    )
    return web.json_response(
        {
            "ok": True,
            "published": published,
            "pending": pending,
            "chart": {
                "labels": [item["title"] for item in chart_source],
                "theta": [item["theta"] for item in chart_source],
                "scaled": [item["scaled_score"] for item in chart_source],
            },
            "summary": {
                "attempts": len(submissions),
                "published": len(published),
                "best_scaled": max((item["scaled_score"] for item in published), default=None),
                "average_scaled": round(average, 1) if average is not None else None,
            },
        }
    )


async def result_detail(request: web.Request) -> web.Response:
    """Bitta imtihon bo'yicha batafsil hisobot (faqat e'lon qilingandan keyin)."""
    user = await ensure_user(request)
    repos = repositories(request)
    try:
        exam_id = int(request.match_info["exam_id"])
    except (KeyError, ValueError) as exc:
        raise ApiError(400, "exam_id butun son bo'lishi kerak.") from exc

    exam = await repos.exams.get(exam_id)
    if exam is None:
        raise ApiError(404, "Bunday imtihon topilmadi.")

    exam = await grading.ensure_graded(repos, exam)  # fon vazifasi zaxirasi
    if not exam_service.results_published(exam):
        raise ApiError(
            403,
            "Natijalar hali e'lon qilinmagan. E'lon vaqti: "
            f"{exam_service.format_local(exam.result_time)}",
        )

    submission = await repos.answers.get(user["user_id"], exam_id)
    if submission is None:
        raise ApiError(404, "Siz bu imtihonda qatnashmagansiz.")
    if not submission.is_graded:
        await grading.grade_exam(repos, exam)
        submission = await repos.answers.get(user["user_id"], exam_id)
    if submission is None:  # pragma: no cover - nazariy jihatdan bo'lmaydi
        raise ApiError(404, "Siz bu imtihonda qatnashmagansiz.")

    report = grading.build_report(exam, submission)
    report["ok"] = True
    return web.json_response(report)


async def list_offline(request: web.Request) -> web.Response:
    """Hududlar bo'yicha (offline) imtihonlar ro'yxati — statik, tayyor joy."""
    return web.json_response(
        {
            "ok": True,
            "regions": OFFLINE_REGIONS,
            "note": (
                "Hududiy (offline) imtihonlar keyingi bosqichda qo'shiladi. "
                "Hozircha ro'yxat ma'lumot uchun ko'rsatiladi."
            ),
        }
    )


async def verify_code(request: web.Request) -> web.Response:
    """Test kodini tekshiradi va imtihon haqida qisqa ma'lumot qaytaradi.

    Bu endpoint javob yubormaydi — o'quvchi kodni tasdiqlab, keyin javoblar
    varag'ini to'ldirishi uchun kerak. Kalit va logitlar berilmaydi.
    """
    user = await ensure_user(request)
    repos = repositories(request)
    data = await read_json(request)

    try:
        code = exam_service.validate_test_code(str(data.get("test_code", "")))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc

    exam = await repos.exams.get_by_code(code)
    if exam is None:
        raise ApiError(404, "Bunday test kodi topilmadi. Kodni tekshirib qayta kiriting.")

    now = exam_service.now_db()
    status = exam_service.status_of(exam, now)
    submission = await repos.answers.get(user["user_id"], exam.exam_id)
    allowed, reason = exam_service.can_submit(exam, now)

    return web.json_response(
        {
            "ok": True,
            "exam_id": exam.exam_id,
            "title": exam.title,
            "total_questions": exam.total_questions,
            "status": status.value,
            "status_title": exam_service.status_title(status),
            "can_submit": allowed and submission is None,
            "submitted": submission is not None,
            "end_time_local": exam_service.format_local(exam.end_time),
            "result_time_local": exam_service.format_local(exam.result_time),
            "seconds_left": exam_service.seconds_left(exam, now),
            "message": (
                reason
                if not allowed
                else (
                    f"Javoblar {exam_service.format_local(exam.end_time)} gacha qabul qilinadi."
                )
            ),
        }
    )


def setup_routes(app: web.Application) -> None:
    """Barcha API marshrutlarini ilovaga ulaydi."""
    router = app.router
    router.add_get("/api/health", health)
    router.add_get("/api/me", get_me)
    router.add_post("/api/me", update_me)
    router.add_get("/api/exams", list_exams)
    router.add_post("/api/submit", submit_answers)
    router.add_post("/api/verify-code", verify_code)
    router.add_get("/api/results", list_results)
    router.add_get("/api/results/{exam_id}", result_detail)
    router.add_get("/api/offline", list_offline)
