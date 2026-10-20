"""Teacher Analytics — sessiya natijalari paneli (snapshot asosida).

O'qituvchi imtihon tugagach **item-level** natijalarni ko'radi. Barcha
ma'lumot muzlatilgan baholash haqiqatidan o'qiladi:

    repos.sessions  → sessiya (forma, vaqt oynasi)
    repos.attempts  → qatnashchilar va yakunlangan urinishlar
    repos.snapshots → YAKUNIY (`is_final = 1`) snapshotlar va savol natijalari
    repos.forms     → savollar ro'yxati (turi, joriy versiya)

Regrade zanjirida faqat **eng yangi yakuniy** snapshot hisobga olinadi
(`scoring_snapshots.is_final`); avvalgilari `is_final = 0` bo'lib qoladi.
Shu sababli "faqat final snapshotlar" qoidasi `repos.snapshots.get_final()`
orqali ta'minlanadi.

Cheklovlar
----------
* `services/rasch.py` ga **tegilmaydi** — θ va ball allaqachon snapshotda
  muzlatilgan, bu modul faqat o'qiydi;
* hech qanday migratsiya/DDL yo'q (sxema muzlatilgan);
* legacy `exams`/`user_answers` oqimi o'zgarmaydi.

`p_value` — savol qiyinligining klassik bahosi (facility):

    p_value = correct_count / attempts

bu yerda `attempts` — savolni **ko'rgan** (ya'ni `not_reached` bo'lmagan)
yakuniy snapshotlar soni; `omitted_count` — ko'rgan, lekin javob bermaganlar
(`capture_status = 'blank'`). `not_reached` savollar tahlildan chiqariladi
(docs/11 §`responses.capture_status`) va faqat ma'lumot uchun sanaladi.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from database.repository import Repositories
from services import form_layout

logger = logging.getLogger(__name__)

#: `attempts.status` — javob topshirilgan hisoblanadigan holatlar.
SUBMITTED_STATUSES: frozenset[str] = frozenset(
    {"submitted", "submitted_late", "graded"}
)

#: Snapshot'dagi javob holatlari (`scoring_snapshot_items.capture_status`).
CAPTURE_ANSWERED: str = "answered"
CAPTURE_OMITTED: str = "blank"
CAPTURE_NOT_REACHED: str = "not_reached"

#: Savol turlari (`item_versions.item_type`).
TYPE_MCQ4: str = "mcq4"
TYPE_MCQ6: str = "mcq6"
TYPE_NUMERIC: str = "numeric"
TYPE_TEXT: str = "text"


class AnalyticsError(ValueError):
    """Analitika so'rovidagi xatolik (foydalanuvchiga ko'rsatiladigan izoh)."""


def _average(values: Sequence[float], digits: int) -> float | None:
    """O'rtacha qiymat (bo'sh ro'yxatda — `None`)."""
    if not values:
        return None
    return round(sum(float(value) for value in values) / len(values), digits)


def _is_submitted(attempt: dict[str, Any]) -> bool:
    """Urinish javob topshirilgan holatdami?"""
    if attempt.get("submitted_at"):
        return True
    return str(attempt.get("status") or "") in SUBMITTED_STATUSES


def _answer_type(form_item: dict[str, Any] | None, answer_kind: str | None) -> str:
    """Savol turini aniqlaydi (`mcq4` / `mcq6` / `numeric` / `text`).

    Ustuvorlik: `form_items.options_count` (forma ta'rifi), so'ng snapshot'dagi
    `answer_kind` (javob turi). Variantli savolda 4 tadan ko'p variant bo'lsa —
    `mcq6`.
    """
    options = int((form_item or {}).get("options_count") or 0)
    if options >= 6:
        return TYPE_MCQ6
    if options >= 2:
        return TYPE_MCQ4
    if str(answer_kind or "") == "option":
        return TYPE_MCQ4
    if str(answer_kind or "") == "text":
        return TYPE_TEXT
    return TYPE_NUMERIC


def _item_label(row: Mapping[str, Any]) -> str:
    """`form_items` satridan savol belgisi: `"36"` yoki `"36a"` (qism bilan).

    Snapshot'dagi `display_label` bilan bir xil qoida (`form_layout.label_of`),
    shu sababli statistika qatorlari snapshot belgilariga to'g'ri bog'lanadi.
    """
    position = int(row.get("position") or 0)
    part = str(row.get("part") or "").strip().lower()
    if not part:
        return str(position)
    try:
        return form_layout.label_of(position, part)
    except ValueError:  # sxemada bo'lmagan qism — xom ko'rinishda qoldiramiz
        return f"{position}{part}"


def _new_bucket() -> dict[str, Any]:
    """Bo'sh hisoblagich to'plami (savol statistikasi uchun)."""
    return {
        "attempts": 0,
        "correct": 0,
        "incorrect": 0,
        "omitted": 0,
        "not_reached": 0,
        "answer_kind": None,
    }


def _count_row(bucket: dict[str, Any], row: Mapping[str, Any]) -> None:
    """Snapshot satrini hisoblagichga qo'shadi (`not_reached` tahlildan chiqadi)."""
    if bucket["answer_kind"] is None:
        bucket["answer_kind"] = row.get("answer_kind")

    capture = str(row.get("capture_status") or "")
    max_score = float(row.get("max_score") or 0.0)
    score = float(row.get("score_awarded") or 0.0)
    is_correct = max_score > 0.0 and score >= max_score

    if capture == CAPTURE_NOT_REACHED:
        bucket["not_reached"] += 1
        return

    bucket["attempts"] += 1
    if is_correct:
        bucket["correct"] += 1
    elif capture == CAPTURE_OMITTED:
        bucket["omitted"] += 1
    else:
        bucket["incorrect"] += 1


async def _get_session(repos: Repositories, session_id: int) -> dict[str, Any]:
    """Sessiya satrini oladi.

    Raises:
        AnalyticsError: raqam noto'g'ri yoki sessiya topilmasa.
    """
    try:
        value = int(session_id)
    except (TypeError, ValueError) as exc:
        raise AnalyticsError("Sessiya raqami butun son bo'lishi kerak.") from exc
    if value <= 0:
        raise AnalyticsError("Sessiya raqami noto'g'ri.")
    session = await repos.sessions.get(value)
    if session is None:
        raise AnalyticsError(f"Sessiya topilmadi: {value}.")
    return session


async def _final_snapshots(
    repos: Repositories, attempts: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Har bir urinish uchun **yakuniy** snapshot (`is_final = 1`) ro'yxati.

    Regrade bo'lgan urinishda `repos.snapshots.get_final()` eng yangi yakuniy
    versiyani qaytaradi — eski snapshotlar hisobga olinmaydi.
    """
    snapshots: list[dict[str, Any]] = []
    for attempt in attempts:
        snapshot = await repos.snapshots.get_final(int(attempt["attempt_id"]))
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


async def _form_meta(
    repos: Repositories, session: dict[str, Any]
) -> tuple[int | None, int, dict[str, dict[str, Any]]]:
    """Sessiya formasining joriy versiyasi va savollari.

    Qaytaradi:
        ``(form_version_id, total_questions, {label: form_item})`` — belgi
        qismli savolda `"36a"`, qismsiz savolda `"36"`. Forma/versiya topilmasa —
        ``(None, 0, {})``.
    """
    form_id = session.get("form_id")
    if form_id is None:
        return None, 0, {}
    version_id = await repos.forms.current_version_id(int(form_id))
    if version_id is None:
        return None, 0, {}
    version = await repos.forms.get_version(int(version_id))
    rows = await repos.forms.list_items(int(version_id))
    total = int((version or {}).get("total_questions") or len(rows))
    return int(version_id), total, {_item_label(row): row for row in rows}


async def build_session_summary(
    repos: Repositories, session_id: int
) -> dict[str, Any]:
    """Sessiya bo'yicha jamlanma natijalar (snapshot'lardan).

    Faqat **yakuniy** (`is_final = 1`) snapshotlar hisobga olinadi; regrade
    qilingan urinishda eng yangi yakuniy versiya olinadi.

    Qaytaradi (kalit qiymatlar):
        * ``participants_count`` — urinish boshlaganlar (o'chirilmagan);
        * ``submitted_count`` — javob topshirganlar;
        * ``graded_count`` — yakuniy snapshot'i borlar (baholanganlar);
        * ``average_theta`` / ``average_scaled_score`` / ``average_raw_score``;
        * ``min_scaled_score`` / ``max_scaled_score``.

    Baholangan urinish bo'lmasa o'rtachalar/min-max `None` bo'ladi.
    """
    session = await _get_session(repos, session_id)
    attempts = await repos.attempts.list_for_session(int(session_id))
    snapshots = await _final_snapshots(repos, attempts)

    thetas = [float(s["theta"]) for s in snapshots if s.get("theta") is not None]
    scaled = [
        float(s["scaled_score"])
        for s in snapshots
        if s.get("scaled_score") is not None
    ]
    raws = [int(s.get("raw_score") or 0) for s in snapshots]

    summary = {
        "session_id": int(session_id),
        "form_id": None if session.get("form_id") is None else int(session["form_id"]),
        "title": session.get("title"),
        "start_time": session.get("start_time"),
        "end_time": session.get("end_time"),
        "result_time": session.get("result_time"),
        "participants_count": len(attempts),
        "submitted_count": sum(1 for attempt in attempts if _is_submitted(attempt)),
        "graded_count": len(snapshots),
        "average_theta": _average(thetas, 4),
        "average_scaled_score": _average(scaled, 2),
        "average_raw_score": _average(raws, 2),
        "min_scaled_score": round(min(scaled), 2) if scaled else None,
        "max_scaled_score": round(max(scaled), 2) if scaled else None,
    }
    logger.debug(
        "Sessiya jamlanmasi: session_id=%s, qatnashchilar=%d, baholangan=%d",
        session_id,
        summary["participants_count"],
        summary["graded_count"],
    )
    return summary


async def build_item_statistics(
    repos: Repositories, session_id: int
) -> list[dict[str, Any]]:
    """Har bir savol bo'yicha statistika (faqat yakuniy snapshotlardan).

    Har bir savol uchun qaytariladi:

        ``question_number`` — pozitsiya (1..N);
        ``answer_type``     — `mcq4` / `mcq6` / `numeric` / `text`;
        ``attempts``        — savolni ko'rganlar (`not_reached` hisobga olinmaydi);
        ``correct_count``   — to'g'ri javob berganlar (`score_awarded >= max_score`);
        ``incorrect_count`` — ko'rgan, lekin noto'g'ri javob berganlar;
        ``omitted_count``   — ko'rgan, lekin javob bermaganlar (`blank`);
        ``not_reached_count`` — savolga yetib bormaganlar (tahlildan chiqarilgan);
        ``p_value``         — ``correct_count / attempts`` (attempts = 0 bo'lsa `None`).

    Savollar ro'yxati `repos.forms.list_items()` dan olinadi — shu sababli
    baholanmagan (snapshot'i yo'q) savollar ham `attempts = 0` bilan qaytadi.
    """
    session = await _get_session(repos, session_id)
    attempts = await repos.attempts.list_for_session(int(session_id))
    snapshots = await _final_snapshots(repos, attempts)
    _version_id, _total, form_items = await _form_meta(repos, session)

    # Qismsiz savollar: position bo'yicha (avvalgi xulq).
    plain_items: dict[int, dict[str, Any]] = {}
    # Qismli savollar (`36a`, `36b`): belgi bo'yicha — har biri alohida item.
    part_items: dict[str, dict[str, Any]] = {}
    for label, item in form_items.items():
        position = int(item.get("position") or 0)
        if label == str(position):
            plain_items[position] = item
        else:
            part_items[label] = item

    # position → hisoblagichlar (qismsiz savollar)
    buckets: dict[int, dict[str, Any]] = {}
    # belgi → hisoblagichlar (qismli savollar) va ularning pozitsiyasi
    part_buckets: dict[str, dict[str, Any]] = {}
    part_positions: dict[str, int] = {}

    def _bucket(position: int) -> dict[str, Any]:
        return buckets.setdefault(position, _new_bucket())

    for snapshot in snapshots:
        rows = await repos.snapshots.list_items(int(snapshot["snapshot_id"]))
        for row in rows:
            position = int(row.get("position") or 0)
            label = str(row.get("display_label") or "").strip() or str(position)
            if label == str(position):
                _count_row(_bucket(position), row)
            else:
                part_positions.setdefault(label, position)
                _count_row(part_buckets.setdefault(label, _new_bucket()), row)

    positions = sorted(set(plain_items) | set(buckets))
    statistics: list[dict[str, Any]] = []
    for position in positions:
        bucket = buckets.get(position) or _new_bucket()
        attempts_count = int(bucket["attempts"])
        correct = int(bucket["correct"])
        statistics.append(
            {
                "question_number": position,
                "answer_type": _answer_type(
                    plain_items.get(position), bucket["answer_kind"]
                ),
                "attempts": attempts_count,
                "correct_count": correct,
                "incorrect_count": int(bucket["incorrect"]),
                "omitted_count": int(bucket["omitted"]),
                "not_reached_count": int(bucket["not_reached"]),
                "p_value": (
                    round(correct / attempts_count, 4) if attempts_count else None
                ),
            }
        )

    # Qismli savollar — alohida yozuvlar (`label` maydoni bilan).
    for label in sorted(set(part_items) | set(part_buckets)):
        item = part_items.get(label)
        bucket = part_buckets.get(label) or _new_bucket()
        position = int((item or {}).get("position") or part_positions.get(label) or 0)
        attempts_count = int(bucket["attempts"])
        correct = int(bucket["correct"])
        statistics.append(
            {
                "question_number": position,
                "label": label,
                "answer_type": _answer_type(item, bucket["answer_kind"]),
                "attempts": attempts_count,
                "correct_count": correct,
                "incorrect_count": int(bucket["incorrect"]),
                "omitted_count": int(bucket["omitted"]),
                "not_reached_count": int(bucket["not_reached"]),
                "p_value": (
                    round(correct / attempts_count, 4) if attempts_count else None
                ),
            }
        )

    logger.debug(
        "Savol statistikasi: session_id=%s, savollar=%d, qismlar=%d, baholangan=%d",
        session_id,
        len(positions),
        len(part_items) or len(part_buckets),
        len(snapshots),
    )
    return statistics