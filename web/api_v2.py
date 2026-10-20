"""Item-level o'quvchi API'si (`/api/v2/*`) — attempt + autosave + natija.

Mavjud v1 API (`/api/verify-code`, `/api/submit`, `/api/results`) **tegilmagan**:
u `user_answers` jadvallari bilan ishlashda davom etadi. Bu modul esa
`docs/11` item-level jadvallaridan foydalanadi:

    exam_sessions → attempts → responses → scoring_snapshots(+items)

Endpoint'lar (hammasi `X-Init-Data` bilan autentifikatsiya qilinadi):

    POST /api/v2/verify-code        — test kodi → sessiya/forma/layout
    POST /api/v2/attempt/start      — urinishni boshlash (idempotent)
    POST /api/v2/autosave           — bitta javobni saqlash (idempotent)
    GET  /api/v2/state              — joriy javoblar (qayta ochilganda tiklash)
    POST /api/v2/submit             — urinishni yakunlash
    GET  /api/v2/result/{id}        — yakuniy snapshot'dan natija

O'qituvchi (admin) analitikasi — faqat `ADMIN_IDS` uchun:

    GET  /api/v2/admin/session/{session_id}/summary — jamlanma natijalar
    GET  /api/v2/admin/session/{session_id}/items   — savollar statistikasi

Analitika snapshot'lardan (`services.analytics`) o'qiladi — faqat yakuniy
(`is_final = 1`) snapshotlar hisobga olinadi.

Diqqat (sxema muzlatilgan — DDL yozilmaydi): `responses.capture_status` faqat
`answered`/`blank`/`not_reached` qiymatlarini qabul qiladi (`CHECK`). Shuning
uchun autosave natijasi bazada `answered`/`blank` bo'lib saqlanadi, API javobida
esa mantiqiy holat ko'rsatiladi: `capture_status = "autosave"`. Yakunlash holati
`attempts.status`/`submit_mode`/`submitted_at` da turadi va javobda
`capture_status = "submitted"` bo'lib qaytadi.

Xavfsizlik: foydalanuvchi **har doim** `initData` dan olinadi (`ensure_user`);
`attempt_id` so'rovdan kelsa ham uning egasi tekshiriladi (aks holda `403`).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from aiohttp import web

import config
from database.repository import Repositories
from services import analytics, exam_service, form_layout, math_expr
from web.api import ApiError, ensure_user, read_json, repositories

logger = logging.getLogger(__name__)

# Sessiya holatlari (vaqt bo'yicha hisoblanadi) — o'quvchiga ko'rinadigan nomlar.
STATUS_TITLES: dict[str, str] = {
    "scheduled": "Hali boshlanmagan",
    "active": "Javob qabul qilinmoqda",
    "closed": "Javob qabul qilish tugagan",
    "graded": "Baholangan",
    "published": "Natija e'lon qilingan",
    "cancelled": "Bekor qilingan",
}

# API javobidagi mantiqiy holatlar (DB'da bunday qiymat yo'q — sxema muzlatilgan).
CAPTURE_AUTOSAVE = "autosave"
CAPTURE_SUBMITTED = "submitted"


def _session_status(session: dict[str, Any], now_db: str) -> str:
    """Sessiya holatini vaqt bo'yicha aniqlaydi (saqlangan `status` ustuvor emas)."""
    if str(session.get("status") or "") == "cancelled":
        return "cancelled"
    if now_db < str(session.get("start_time") or ""):
        return "scheduled"
    if now_db < str(session.get("end_time") or ""):
        return "active"
    if session.get("graded_at"):
        return "graded"
    return "closed"


def _seconds_left(session: dict[str, Any], now_db: str) -> int:
    """`end_time` gacha qolgan sekund (manfiy bo'lsa — 0)."""
    try:
        end = exam_service.parse_db_time(str(session["end_time"]))
        now = exam_service.parse_db_time(now_db)
    except (KeyError, ValueError):
        return 0
    return max(int((end - now).total_seconds()), 0)


def _session_parts(session: dict[str, Any]) -> list[str]:
    """Sessiyadagi qismli savol belgilari (`forms.parts_json` → `["36a","36b"]`)."""
    raw = session.get("parts_json")
    if raw in (None, ""):
        return []
    if isinstance(raw, (list, tuple)):
        return [str(value) for value in raw]
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return []
    return [str(value) for value in parsed] if isinstance(parsed, list) else []


def _layout(total_questions: int, parts: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Savollar joylashuvi — ``form_layout.layout_with_parts`` (yagona manba).

    v1 (`/api/verify-code`) **aynan shu** funksiyadan foydalanadi, shu sababli
    ikkala yo'lda ham qismlar (`36a`/`36b`) bir xil ko'rinadi.
    """
    return form_layout.layout_with_parts(int(total_questions), parts)


async def _session_by_code(
    repos: Repositories, raw_code: Any
) -> tuple[str, dict[str, Any]]:
    """Test kodini tekshiradi va item-level sessiyani qaytaradi.

    Raises:
        ApiError: 400 (kod formati) yoki 404 (bunday kod bilan sessiya yo'q).
    """
    try:
        code = exam_service.validate_test_code(str(raw_code or ""))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc

    session = await repos.sessions.get_by_test_code(code)
    if session is None:
        raise ApiError(
            404,
            "Bunday test kodi topilmadi (item-level sessiya hali ochilmagan bo'lishi "
            "ham mumkin). Kodni tekshirib qayta kiriting.",
        )
    return code, session


def _require_form_version(session: dict[str, Any]) -> int:
    """Sessiyaning joriy forma versiyasi (bo'lmasa — 409).

    Raises:
        ApiError: 409.
    """
    form_version_id = session.get("form_version_id")
    if not form_version_id:
        raise ApiError(
            409,
            "Formaning joriy versiyasi topilmadi. O'qituvchi forma kalitini "
            "e'lon qilganini tekshiring.",
        )
    return int(form_version_id)


async def _attempt_form_version(
    repos: Repositories, attempt: dict[str, Any]
) -> dict[str, Any]:
    """Urinishning forma versiyasini oladi.

    `total_questions` `exam_sessions` da yo'q — u `forms`/`form_versions` da
    saqlanadi, shuning uchun savollar soni shu yerdan olinadi.

    Raises:
        ApiError: 409 — versiya topilmasa.
    """
    version = await repos.forms.get_version(int(attempt["form_version_id"]))
    if version is None:
        raise ApiError(
            409,
            "Forma versiyasi topilmadi — o'qituvchi bilan bog'lanib, "
            "imtihonni qayta e'lon qilishni so'rang.",
        )
    return version


async def _owned_attempt(
    repos: Repositories, user: dict[str, Any], raw_attempt_id: Any
) -> dict[str, Any]:
    """Urinishni oladi va uning shu foydalanuvchiga tegishli ekanini tekshiradi.

    Raises:
        ApiError: 400 (raqam emas), 404 (topilmadi), 403 (boshqa odamning urinishi).
    """
    try:
        attempt_id = int(raw_attempt_id)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "attempt_id butun son bo'lishi kerak.") from exc
    if attempt_id <= 0:
        raise ApiError(400, "attempt_id noto'g'ri.")

    attempt = await repos.attempts.get(attempt_id)
    if attempt is None or attempt.get("deleted_at"):
        raise ApiError(404, "Urinish topilmadi.")
    if int(attempt["user_id"]) != int(user["user_id"]):
        logger.warning(
            "Boshqa foydalanuvchi urinishiga murojaat: attempt_id=%s, user_id=%s",
            attempt_id,
            user["user_id"],
        )
        raise ApiError(403, "Bu urinish sizga tegishli emas.")
    return attempt


def _require_admin(user: dict[str, Any]) -> None:
    """So'rov egasi o'qituvchi (admin) ekanini tekshiradi.

    Raises:
        ApiError: 403 — `ADMIN_ID`/`ADMIN_IDS` ro'yxatida bo'lmasa.
    """
    if not config.is_admin(int(user["user_id"])):
        logger.warning("Admin bo'lmagan foydalanuvchi analitikaga murojaat qildi: %s", user)
        raise ApiError(403, "Bu bo'lim faqat o'qituvchi (admin) uchun.")


def _session_id_from_path(request: web.Request) -> int:
    """`{session_id}` yo'l parametrini tekshirib, butun songa aylantiradi.

    Raises:
        ApiError: 400 — raqam emas yoki noldan kichik bo'lsa.
    """
    raw = request.match_info.get("session_id", "")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "session_id butun son bo'lishi kerak.") from exc
    if value <= 0:
        raise ApiError(400, "session_id noto'g'ri.")
    return value


async def _analytics_or_404(coro: Any) -> Any:
    """`AnalyticsError` ni 404 JSON javobiga o'giradi (o'zbekcha izoh bilan)."""
    try:
        return await coro
    except analytics.AnalyticsError as exc:
        raise ApiError(404, str(exc)) from exc


def _answer_payload(
    position: int, value: Any, answer_kind: Any = None, expression: Any = None
) -> tuple[str, str, str | None, str | None, float | None]:
    """Kiritilgan javobni tekshirib, DB maydonlariga aylantiradi.

    Qaytaradi: ``(capture_status, answer_kind, selected_option,
    normalized_answer, numeric_value)``. `value` bo'sh yoki `null` bo'lsa —
    javob tozalanadi (`capture_status="blank"`).

    Phase 2: sonli savolda `expression` (o'quvchi kiritgan natural ifoda —
    `√5`, `3/7`, `π/2`) berilgan va hisoblanadigan bo'lsa, `normalized_answer`
    va `numeric_value` **server tomonida aniq** hisoblanadi. Ifoda bo'lmasa —
    avvalgi xatti-harakat (klient yuborgan son).

    Raises:
        ApiError: 400 — savol turiga mos bo'lmagan yoki formati buzuq qiymat.
    """
    options = form_layout.options_of(position)
    text = "" if value is None else str(value).strip()
    kind = str(answer_kind or ("option" if options else "numeric")).strip().lower()
    expression_text = "" if expression is None else str(expression).strip()

    # Phase 2: natural ifoda berilgan bo'lsa — server aniq hisoblaydi.
    if kind == "numeric" and not options and expression_text:
        evaluated = math_expr.evaluate(expression_text)
        if evaluated is not None:
            normalized = math_expr.format_number(evaluated)
            return "answered", "numeric", None, normalized, float(evaluated)

    if not text:
        return "blank", ("option" if options else "numeric"), None, None, None
    if kind == "option":
        if not options:
            raise ApiError(400, f"{position}-savol variantli emas — sonli javob yuboring.")
        letter = text.upper()
        if letter not in options:
            raise ApiError(
                400,
                f"{position}-savol uchun ruxsat etilgan javoblar: {', '.join(options)}. "
                f"Berilgan: {value!r}.",
            )
        return "answered", "option", letter, letter, None

    if kind == "numeric":
        if options:
            raise ApiError(400, f"{position}-savol sonli emas — variant (A–F) yuboring.")
        try:
            normalized = form_layout.normalize_numeric(text)
        except ValueError as exc:
            raise ApiError(
                400,
                f"Sonli javob noto'g'ri ({position}-savol): {value!r}. Masalan: 12 yoki 12.5.",
            ) from exc
        return "answered", "numeric", None, normalized, float(normalized)

    raise ApiError(400, "Javob turi faqat `option` yoki `numeric` bo'lishi mumkin.")


def _answer_of_row(row: dict[str, Any]) -> str | None:
    """`responses` satridan o'quvchi javobini oladi (javobsiz bo'lsa — `None`)."""
    if str(row.get("capture_status") or "") != "answered":
        return None
    if str(row.get("answer_kind") or "option") == "numeric":
        value = row.get("normalized_answer")
        if value in (None, ""):
            value = row.get("numeric_value")
        return None if value is None else str(value)
    option = row.get("selected_option")
    return None if option is None else str(option)


def _raw_answer_value(data: dict[str, Any]) -> str | None:
    """`responses.raw_answer` uchun qiymatni tanlaydi (Phase 1 — ifoda saqlash).

    * `EXPRESSION_PRESERVATION_ENABLED` yoqilgan va so'rovda `expression`
      berilgan bo'lsa — o'quvchi kiritgan **ASL matematik ifoda** (`√5+1`)
      saqlanadi. Baholash uchun ishlatilmaydi (u — dalil/audit maydoni).
    * Aks holda — avvalgi xatti-harakat: hisoblangan `value` saqlanadi
      (eski mijozlar bilan to'liq moslik).
    """
    if config.EXPRESSION_PRESERVATION_ENABLED:
        expression = data.get("expression")
        if expression is not None and str(expression).strip():
            return str(expression)
    value = data.get("value")
    return None if value is None else str(value)


def _expression_of_row(row: dict[str, Any]) -> str | None:
    """`responses` satridagi ASL ifodani qaytaradi (`raw_answer`).

    Faqat javob berilgan (`capture_status = "answered"`) bo'lsa qaytariladi.
    Eski yozuvlarda `raw_answer` hisoblangan son bo'lishi mumkin — u ham
    o'z holicha qaytariladi (klient ifoda o'rniga sonni ko'rsatadi), ya'ni
    orqaga moslik saqlanadi.
    """
    if str(row.get("capture_status") or "") != "answered":
        return None
    raw = row.get("raw_answer")
    return None if raw in (None, "") else str(raw)


def _status_message(session: dict[str, Any], status: str) -> str:
    """Sessiya holatiga mos o'zbekcha izoh."""
    if status == "active":
        return (
            "Javoblar "
            f"{exam_service.format_local(str(session['end_time']))} gacha qabul qilinadi."
        )
    if status == "scheduled":
        return (
            "Imtihon "
            f"{exam_service.format_local(str(session['start_time']))} da boshlanadi."
        )
    if status == "cancelled":
        return "Bu sessiya bekor qilingan."
    return "Javob qabul qilish vaqti tugagan."


# ---------------------------------------------------------------------------
# POST /api/v2/verify-code
# ---------------------------------------------------------------------------
async def verify_code(request: web.Request) -> web.Response:
    """Test kodini tekshiradi: sessiya, forma versiyasi, savollar joylashuvi."""
    user = await ensure_user(request)
    repos = repositories(request)
    data = await read_json(request)

    _code, session = await _session_by_code(repos, data.get("test_code"))
    form_version_id = _require_form_version(session)
    session_id = int(session["session_id"])
    total = int(session["total_questions"] or 0)

    now = exam_service.now_db()
    status = _session_status(session, now)
    attempt = await repos.attempts.get_for_user(session_id, user["user_id"])

    return web.json_response(
        {
            "ok": True,
            "session_id": session_id,
            "form_version_id": form_version_id,
            "total_questions": total,
            "layout": _layout(total, _session_parts(session)),
            "title": session.get("title") or session.get("form_title"),
            "status": status,
            "status_title": STATUS_TITLES.get(status, status),
            "can_start": status == "active",
            "attempt_id": None if attempt is None else int(attempt["attempt_id"]),
            "already_submitted": bool(
                attempt is not None and str(attempt.get("status")) != "in_progress"
            ),
            "end_time_local": exam_service.format_local(str(session["end_time"])),
            "result_time_local": exam_service.format_local(str(session["result_time"])),
            "seconds_left": _seconds_left(session, now),
            "message": _status_message(session, status),
        }
    )


# ---------------------------------------------------------------------------
# POST /api/v2/attempt/start
# ---------------------------------------------------------------------------
async def attempt_start(request: web.Request) -> web.Response:
    """Urinishni boshlaydi (idempotent: ikkinchi chaqiruvda o'sha `attempt_id`)."""
    user = await ensure_user(request)
    repos = repositories(request)
    data = await read_json(request)

    _code, session = await _session_by_code(repos, data.get("test_code"))
    form_version_id = _require_form_version(session)
    session_id = int(session["session_id"])
    total = int(session["total_questions"] or 0)

    now = exam_service.now_db()
    status = _session_status(session, now)
    if status == "scheduled":
        raise ApiError(409, _status_message(session, status))
    if status in {"closed", "graded", "published", "cancelled"}:
        raise ApiError(410, _status_message(session, status))

    attempt_id = await repos.attempts.get_or_create(
        session_id=session_id,
        user_id=int(user["user_id"]),
        form_version_id=form_version_id,
        started_at=now,
    )
    attempt = await repos.attempts.get(attempt_id) or {}
    rows = await repos.responses.current_by_label(attempt_id)

    return web.json_response(
        {
            "ok": True,
            "attempt_id": attempt_id,
            "session_id": session_id,
            "form_version_id": form_version_id,
            "status": attempt.get("status"),
            "started_at": attempt.get("started_at"),
            "revision": int(attempt.get("revision") or 0),
            "interaction_count": int(attempt.get("interaction_count") or 0),
            "total_questions": total,
            "layout": _layout(total, _session_parts(session)),
            "seconds_left": _seconds_left(session, now),
            "responses": {label: _answer_of_row(row) for label, row in rows.items()},
            "answered_count": sum(
                1 for row in rows.values() if _answer_of_row(row) is not None
            ),
            "message": "Urinish boshlandi. Javoblar avtomatik saqlanadi.",
        }
    )


# ---------------------------------------------------------------------------
# POST /api/v2/autosave — bitta javob (idempotent, `client_seq` bilan)
# ---------------------------------------------------------------------------
async def autosave(request: web.Request) -> web.Response:
    """Bitta savol javobini saqlaydi (`responses` ga yangi revision).

    `client_seq` berilgan va avval yozilgan bo'lsa — **yangi satr yozilmaydi**
    (tarmoq qayta urinishi idempotent) va `duplicate: true` qaytadi.

    Raises:
        ApiError: 400 (savol/qiymat), 403/404 (urinish), 409 (yakunlangan),
            410 (vaqt tugagan).
    """
    user = await ensure_user(request)
    repos = repositories(request)
    data = await read_json(request)

    attempt = await _owned_attempt(repos, user, data.get("attempt_id"))
    attempt_id = int(attempt["attempt_id"])
    session = await repos.sessions.get(int(attempt["session_id"])) or {}
    version = await _attempt_form_version(repos, attempt)
    now = exam_service.now_db()
    total = int(version.get("total_questions") or 0)

    if str(attempt.get("status")) != "in_progress":
        raise ApiError(409, "Urinish yakunlangan — javoblarni o'zgartirib bo'lmaydi.")
    if now >= str(session.get("end_time") or ""):
        raise ApiError(410, _status_message(session, "closed"))

    try:
        position = int(data.get("position"))
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "position butun son bo'lishi kerak.") from exc
    if not 1 <= position <= total:
        raise ApiError(400, f"Savol raqami 1 dan {total} gacha bo'lishi kerak.")

    # Phase 3 Step 2: javob BELGISI `(position, part)` dan aniqlanadi — 36a va
    # 36b ikki xil `form_item`. `part` yo'q bo'lsa — label = str(position).
    part = str(data.get("part") or "").strip().lower()
    try:
        label = form_layout.label_of(position, part)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc

    raw_seq = data.get("client_seq")
    client_seq: int | None = None
    if raw_seq not in (None, ""):
        try:
            client_seq = int(raw_seq)
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "client_seq butun son bo'lishi kerak.") from exc
        if client_seq <= 0:
            raise ApiError(400, "client_seq musbat son bo'lishi kerak.")

    if client_seq is not None:
        existing = await repos.responses.get_by_client_seq(attempt_id, client_seq)
        if existing is not None:
            rows = await repos.responses.current_by_label(attempt_id)
            return web.json_response(
                {
                    "ok": True,
                    "attempt_id": attempt_id,
                    "position": int(existing.get("position") or position),
                    "label": label,
                    "part": part,
                    "response_id": int(existing["response_id"]),
                    "duplicate": True,
                    "answer_kind": str(existing.get("answer_kind") or "option"),
                    "value": _answer_of_row(existing),
                    "capture_status": CAPTURE_AUTOSAVE,
                    "capture_status_db": str(existing.get("capture_status") or ""),
                    "answered_count": sum(
                        1 for row in rows.values() if _answer_of_row(row) is not None
                    ),
                    "total_questions": total,
                    "seconds_left": _seconds_left(session, now),
                    "server_time": now,
                    "message": "Bu javob avval saqlangan (takroriy so'rov).",
                }
            )

    form_items = await repos.forms.items_by_label(int(attempt["form_version_id"]))
    item = form_items.get(label)
    if item is None and not part:
        # Zaxira (juda eski yozuvlar): pozitsiya bo'yicha qidirish.
        fallback = await repos.forms.items_by_position(int(attempt["form_version_id"]))
        item = fallback.get(position)
    if item is None:
        raise ApiError(400, f"{label}-savol bu formada topilmadi.")
    if item.get("item_version_id") is None or item.get("item_id") is None:
        raise ApiError(
            409,
            "Savolda item-level bog'lanish yo'q — o'qituvchi forma kalitini "
            "yangilashi kerak.",
        )

    capture_status, answer_kind, selected, normalized, numeric = _answer_payload(
        position, data.get("value"), data.get("answer_kind"), data.get("expression")
    )

    response_id = await repos.responses.append(
        attempt_id=attempt_id,
        form_item_id=int(item["form_item_id"]),
        item_id=int(item["item_id"]),
        item_version_id=int(item["item_version_id"]),
        position=position,
        display_label=str(item["display_label"]),
        recorded_at=now,
        part=str(item.get("part") or ""),
        event_type="capture",
        capture_status=capture_status,
        answer_kind=answer_kind,
        selected_option=selected,
        raw_answer=_raw_answer_value(data),
        normalized_answer=normalized,
        numeric_value=numeric,
        source="webapp",
        client_seq=client_seq,
    )

    await repos.attempts.touch(
        attempt_id,
        now,
        revision=int(attempt.get("revision") or 0) + 1,
        interaction_count=int(attempt.get("interaction_count") or 0) + 1,
        last_interaction_position=position,
    )
    rows = await repos.responses.current_by_label(attempt_id)

    return web.json_response(
        {
            "ok": True,
            "attempt_id": attempt_id,
            "position": position,
            "label": label,
            "part": part,
            "response_id": response_id,
            "duplicate": False,
            "answer_kind": answer_kind,
            "value": normalized if answer_kind == "numeric" else selected,
            # `capture_status` — API shartnomasi (mantiqiy holat); bazada esa
            # sxema `answered`/`blank` ni saqlaydi (`CHECK` cheklovi).
            "capture_status": CAPTURE_AUTOSAVE,
            "capture_status_db": capture_status,
            "revision": int(attempt.get("revision") or 0) + 1,
            "answered_count": sum(
                1 for row in rows.values() if _answer_of_row(row) is not None
            ),
            "total_questions": total,
            "seconds_left": _seconds_left(session, now),
            "server_time": now,
            "message": "Javob saqlandi.",
        }
    )


# ---------------------------------------------------------------------------
# GET /api/v2/state — joriy javoblar (qayta ochilganda tiklash)
# ---------------------------------------------------------------------------
async def state(request: web.Request) -> web.Response:
    """Urinishning joriy javoblarini qaytaradi (Web App qayta ochilganda)."""
    user = await ensure_user(request)
    repos = repositories(request)

    attempt = await _owned_attempt(repos, user, request.query.get("attempt_id"))
    attempt_id = int(attempt["attempt_id"])
    session = await repos.sessions.get(int(attempt["session_id"])) or {}
    version = await _attempt_form_version(repos, attempt)
    now = exam_service.now_db()
    total = int(version.get("total_questions") or 0)
    rows = await repos.responses.current_by_label(attempt_id)

    items = []
    for label, row in rows.items():
        entry: dict[str, Any] = {
            "label": label,
            "position": int(row.get("position") or 0),
            "answer_kind": str(row.get("answer_kind") or "option"),
            "value": _answer_of_row(row),
            "capture_status": str(row.get("capture_status") or ""),
            "revision": int(row.get("revision") or 0),
            "recorded_at": row.get("recorded_at"),
        }
        # ASL ifoda (Phase 1): faqat yoqilgan bo'lsa va mavjud bo'lsa qo'shiladi.
        # Aks holda javob shakli avvalgidek qoladi (orqaga moslik).
        if config.EXPRESSION_PRESERVATION_ENABLED:
            expression = _expression_of_row(row)
            if expression is not None:
                entry["expression"] = expression
        items.append(entry)

    return web.json_response(
        {
            "ok": True,
            "attempt_id": attempt_id,
            "status": attempt.get("status"),
            "revision": int(attempt.get("revision") or 0),
            "interaction_count": int(attempt.get("interaction_count") or 0),
            "last_seen_at": attempt.get("last_seen_at"),
            "total_questions": total,
            "layout": _layout(total, _session_parts(session)),
            "seconds_left": _seconds_left(session, now),
            "server_time": now,
            "answered_count": sum(1 for item in items if item["value"] is not None),
            # Joriy holat: tozalangan savollar ham `null` bilan qaytadi
            # (klient "javob yo'q" ni ko'rsatadi), batafsili — `items` da.
            "responses": {item["label"]: item["value"] for item in items},
            "items": items,
        }
    )


# ---------------------------------------------------------------------------
# POST /api/v2/submit — urinishni yakunlash
# ---------------------------------------------------------------------------
async def submit(request: web.Request) -> web.Response:
    """Urinishni yakunlaydi (idempotent: takroriy chaqiruv holatni qaytaradi)."""
    user = await ensure_user(request)
    repos = repositories(request)
    data = await read_json(request)

    attempt = await _owned_attempt(repos, user, data.get("attempt_id"))
    attempt_id = int(attempt["attempt_id"])
    session = await repos.sessions.get(int(attempt["session_id"])) or {}
    version = await _attempt_form_version(repos, attempt)
    now = exam_service.now_db()
    total = int(version.get("total_questions") or 0)

    rows = await repos.responses.current_by_label(attempt_id)
    answered = sum(1 for row in rows.values() if _answer_of_row(row) is not None)

    current_status = str(attempt.get("status"))
    if current_status == "in_progress":
        late = now >= str(session.get("end_time") or "")
        status = "submitted_late" if late else "submitted"
        await repos.attempts.mark_submitted(
            attempt_id, submitted_at=now, submit_mode="manual", status=status
        )
        logger.info(
            "Urinish yakunlandi: attempt_id=%s, javoblar=%d, holat=%s",
            attempt_id,
            answered,
            status,
        )
        message = (
            "Javoblaringiz qabul qilindi (kechiktirilgan). "
            if late
            else "Javoblaringiz qabul qilindi. "
        )
        if session.get("result_time"):
            message += (
                "Natijalar "
                f"{exam_service.format_local(str(session['result_time']))} da e'lon qilinadi."
            )
    else:
        status = current_status
        message = "Urinish allaqachon yakunlangan."

    saved = await repos.attempts.get(attempt_id) or {}
    return web.json_response(
        {
            "ok": True,
            "attempt_id": attempt_id,
            "status": saved.get("status", status),
            "submit_mode": saved.get("submit_mode"),
            "submitted_at": saved.get("submitted_at"),
            # Mantiqiy holat: yakunlash `attempts` da saqlanadi (`responses`
            # jadvalida `submitted` qiymati yo'q — sxema muzlatilgan).
            "capture_status": CAPTURE_SUBMITTED,
            "answered_count": answered,
            "total_questions": total,
            "revision": int(saved.get("revision") or 0),
            "result_time_local": (
                exam_service.format_local(str(session["result_time"]))
                if session.get("result_time")
                else None
            ),
            "message": message,
        }
    )


# ---------------------------------------------------------------------------
# GET /api/v2/result/{attempt_id} — yakuniy snapshot'dan natija
# ---------------------------------------------------------------------------
async def result(request: web.Request) -> web.Response:
    """Yakuniy snapshot'dan natija: θ, 0–100 ball, xom ball, savollar tahlili.

    Natija faqat `result_time` dan keyin ochiladi (v1 qoidasi bilan bir xil).

    Raises:
        ApiError: 403/404 (urinish), 404 (snapshot yo'q), 409 (natija vaqti kelmagan).
    """
    user = await ensure_user(request)
    repos = repositories(request)

    attempt = await _owned_attempt(repos, user, request.match_info.get("attempt_id"))
    attempt_id = int(attempt["attempt_id"])
    session = await repos.sessions.get(int(attempt["session_id"])) or {}
    now = exam_service.now_db()

    if session.get("result_time") and now < str(session["result_time"]):
        raise ApiError(
            409,
            "Natijalar "
            f"{exam_service.format_local(str(session['result_time']))} da e'lon qilinadi.",
        )

    snapshot = await repos.snapshots.get_final(attempt_id)
    if snapshot is None:
        raise ApiError(
            404,
            "Natija hali tayyor emas — baholash tugagach ochiladi. "
            "Keyinroq qayta urinib ko'ring.",
        )

    rows = await repos.snapshots.list_items(int(snapshot["snapshot_id"]))
    theta = float(snapshot.get("theta") or 0.0)
    raw_se = snapshot.get("theta_se")
    scaled = float(snapshot.get("scaled_score") or 0.0)

    scaled_interval: tuple[float, float] | None = None
    if raw_se is not None:
        delta = 1.96 * float(raw_se) * config.scaled_span()
        scaled_interval = (
            round(max(config.SCALED_CAP_MIN, scaled - delta), 2),
            round(min(config.SCALED_CAP_MAX, scaled + delta), 2),
        )

    items = [
        {
            "number": int(row.get("position") or 0),
            "label": row.get("display_label"),
            "answer_kind": str(row.get("answer_kind") or "option"),
            "capture_status": str(row.get("capture_status") or ""),
            "correct_answer": row.get("key_used"),
            "given_answer": row.get("normalized_answer"),
            "score_awarded": float(row.get("score_awarded") or 0.0),
            "max_score": float(row.get("max_score") or 1.0),
            "is_correct": float(row.get("score_awarded") or 0.0)
            >= float(row.get("max_score") or 1.0),
            "match_rule": row.get("match_rule"),
            "difficulty": row.get("b_used"),
            "guessing_c": row.get("guessing_c"),
        }
        for row in rows
    ]

    return web.json_response(
        {
            "ok": True,
            "attempt_id": attempt_id,
            "form_version_id": int(snapshot["form_version_id"]),
            "model": snapshot.get("model"),
            "engine_version": snapshot.get("engine_version"),
            "theta": round(theta, 4),
            "theta_se": None if raw_se is None else round(float(raw_se), 4),
            "scaled_score": round(scaled, 2),
            "scaled_interval": scaled_interval,
            "raw_score": int(snapshot.get("raw_score") or 0),
            "total_items": int(snapshot.get("total_items") or 0),
            "omitted_count": int(snapshot.get("omitted_count") or 0),
            "not_reached_count": int(snapshot.get("not_reached_count") or 0),
            "is_extreme_low": bool(snapshot.get("is_extreme_low")),
            "is_extreme_high": bool(snapshot.get("is_extreme_high")),
            "computed_at": snapshot.get("computed_at"),
            "computed_by": snapshot.get("computed_by"),
            "b_checksum": snapshot.get("b_checksum"),
            "items": items,
        }
    )


# ---------------------------------------------------------------------------
# O'qituvchi analitikasi (faqat admin) — snapshot asosidagi panel
# ---------------------------------------------------------------------------
async def admin_session_summary(request: web.Request) -> web.Response:
    """`GET /api/v2/admin/session/{session_id}/summary` — jamlanma natijalar.

    Majburiy tekshiruvlar: initData orqali autentifikatsiya + admin huquqi.
    Faqat yakuniy (`is_final = 1`) snapshotlar hisobga olinadi.
    """
    user = await ensure_user(request)
    _require_admin(user)
    repos = repositories(request)
    session_id = _session_id_from_path(request)

    summary = await _analytics_or_404(
        analytics.build_session_summary(repos, session_id)
    )
    return web.json_response({"ok": True, **summary})


async def admin_session_items(request: web.Request) -> web.Response:
    """`GET /api/v2/admin/session/{session_id}/items` — savollar statistikasi.

    Javob: `{ok, session_id, form_id, title, total_questions, graded_count,
    participants_count, items: [...]}`. Har bir savolda `question_number`,
    `answer_type`, `attempts`, `correct_count`, `incorrect_count`,
    `omitted_count`, `p_value`.
    """
    user = await ensure_user(request)
    _require_admin(user)
    repos = repositories(request)
    session_id = _session_id_from_path(request)

    summary = await _analytics_or_404(
        analytics.build_session_summary(repos, session_id)
    )
    items = await _analytics_or_404(analytics.build_item_statistics(repos, session_id))
    return web.json_response(
        {
            "ok": True,
            "session_id": summary["session_id"],
            "form_id": summary["form_id"],
            "title": summary["title"],
            "total_questions": len(items),
            "participants_count": summary["participants_count"],
            "graded_count": summary["graded_count"],
            "items": items,
        }
    )


def setup_routes(app: web.Application) -> None:
    """`/api/v2/*` marshrutlarini ulaydi (v1 marshrutlari o'zgarmaydi)."""
    router = app.router
    router.add_post("/api/v2/verify-code", verify_code)
    router.add_post("/api/v2/attempt/start", attempt_start)
    router.add_post("/api/v2/autosave", autosave)
    router.add_get("/api/v2/state", state)
    router.add_post("/api/v2/submit", submit)
    router.add_get("/api/v2/result/{attempt_id}", result)
    # O'qituvchi (admin) analitikasi — snapshot asosida
    router.add_get("/api/v2/admin/session/{session_id}/summary", admin_session_summary)
    router.add_get("/api/v2/admin/session/{session_id}/items", admin_session_items)