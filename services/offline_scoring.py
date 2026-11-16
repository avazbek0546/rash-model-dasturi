"""Offline mock natijalarini mavjud Rasch 1PL modeli bilan baholash.

Bu modul `services.rasch.py` ni qayta yozmaydi: online baholash bilan **aynan
bir xil** `rasch.estimate_theta()` ishlatiladi. Farq faqat javob manbasida:
online — kanonik matn, offline — 55 ta 0/1 bayroq.
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from typing import Any, Sequence

import config
from database.models import Exam
from database.repository import Repositories
from services import form_layout, rasch, scoring, subjects

logger = logging.getLogger(__name__)

OFFLINE_MODEL = "rasch_1pl"


class OfflineReadinessError(ValueError):
    """Imtihon 55 itemli offline importga tayyor emas."""


@dataclass(frozen=True, slots=True)
class OfflineReadiness:
    """55-item tayyorgarlik natijasi."""

    ready: bool
    reason: str
    exam_id: int
    form_version_id: int | None
    form_version: dict[str, Any] | None
    items: tuple[dict[str, Any], ...]
    labels: tuple[str, ...]
    key_fingerprint: str
    labels_order_hash: str
    b_checksum: str
    b_source: str
    engine_version: str
    scored_items: int


@dataclass(frozen=True, slots=True)
class OfflineScore:
    """Bitta offline o'quvchining Rasch natijasi."""

    theta: float
    theta_se: float | None
    scaled_score: float
    raw_score: int
    total_items: int
    level: str
    is_extreme: bool
    log_likelihood: float
    converged: bool
    engine_version: str
    b_checksum: str
    b_source: str
    key_fingerprint: str
    subject_summaries: tuple[dict[str, Any], ...]
    subject_balls: dict[str, float | None]
    responses: tuple[dict[str, Any], ...]


def key_fingerprint(key_text: str) -> str:
    """Javoblar kalitining barqaror SHA-256 fingerprinti."""
    return hashlib.sha256(str(key_text or "").encode("utf-8")).hexdigest()


def labels_order_hash(labels: Sequence[str]) -> str:
    """55 ustun tartibining SHA-256 hash'i."""
    return hashlib.sha256("\n".join(str(label) for label in labels).encode("utf-8")).hexdigest()


def expected_labels(total_questions: int) -> list[str]:
    """45 pozitsiya → 55 item belgisi: `1..35`, `36a`, `36b`, ... `45b`."""
    labels: list[str] = []
    for position in range(1, int(total_questions) + 1):
        parts = form_layout.parts_of(position)
        if parts == ("",):
            labels.append(str(position))
        else:
            labels.extend(form_layout.label_of(position, part) for part in parts)
    return labels


def keys_are_equivalent(
    exam_key: str, version_key: str, total_questions: int
) -> bool:
    """`exams.answer_key` va `form_versions.answer_key` bir xil kalitmi?

    Online item-level baholash forma kalitini, offline import ham forma
    kalitini ishlatadi. Lekin imtihon yozuvidagi eski kalit bilan forma
    kaliti jimgina farq qilsa, ikki yo'l boshqa javoblarni to'g'ri deb
    hisoblashi mumkin. Shu sababli readiness bosqichida ikkala kalitning
    harflari va sonli qiymatlari **matematik ekvivalentlik** bilan
    solishtiriladi (`√5 ≡ (√20)/2`, `3/7 ≡ 6/14`).
    """
    exam_letters, exam_numeric = form_layout.parse_labeled_key(
        exam_key, total_questions
    )
    version_letters, version_numeric = form_layout.parse_labeled_key(
        version_key, total_questions
    )
    if [str(letter).upper() for letter in exam_letters] != [
        str(letter).upper() for letter in version_letters
    ]:
        return False
    if set(exam_numeric) != set(version_numeric):
        return False
    return all(
        math.isclose(
            float(exam_numeric[label]),
            float(version_numeric[label]),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        for label in exam_numeric
    )


async def check_readiness(repos: Repositories, exam: Exam) -> OfflineReadiness:
    """Imtihon 55 itemli, labeled kalitli va bir xil `b` bilan tayyormi?"""
    if config.DIFFICULTY_SHRINKAGE_ENABLED:
        return _not_ready(
            exam,
            "`DIFFICULTY_SHRINKAGE_ENABLED` yoqilgan: `b` qatnashchilar "
            "tarkibiga qarab o'zgaradi. Offline import uchun avval uni o'chiring.",
        )
    session = await repos.sessions.get_by_test_code(exam.test_code)
    if session is None:
        return _not_ready(exam, "exam_sessions topilmadi — forma/sessiya yaratilmagan.")
    form_version_id = int(session.get("form_version_id") or 0) or None
    if form_version_id is None:
        return _not_ready(exam, "Sessiyada form_version_id yo'q.")
    version = await repos.forms.get_version(form_version_id)
    if version is None:
        return _not_ready(exam, "Forma versiyasi topilmadi.")
    if int(version.get("total_questions") or 0) != int(exam.total_questions):
        return _not_ready(
            exam,
            "Forma versiyasidagi savollar soni imtihondagi bilan mos emas.",
            form_version_id=form_version_id,
            version=version,
        )
    items = await repos.forms.list_items(form_version_id)
    labels = tuple(str(row.get("display_label") or "") for row in items)
    expected = tuple(expected_labels(exam.total_questions))

    if len(items) != 55:
        return _not_ready(
            exam,
            f"Formada {len(items)} ta item bor; offline mock uchun 55 ta kerak.",
            form_version_id=form_version_id, version=version, items=items, labels=labels,
        )
    if labels != expected:
        return _not_ready(
            exam,
            "Forma itemlari kutilgan 55 belgi tartibiga mos emas "
            "(1–35, 36a, 36b, …, 45b).",
            form_version_id=form_version_id, version=version, items=items, labels=labels,
        )
    missing_item_versions = [
        label for label, item in zip(labels, items)
        if not int(item.get("item_version_id") or 0)
    ]
    if missing_item_versions:
        return _not_ready(
            exam,
            "Formada item-level bog'lanish yo'q: "
            + ", ".join(missing_item_versions[:5])
            + ("…" if len(missing_item_versions) > 5 else "")
            + ". Imtihonni item-level forma bilan qayta yarating.",
            form_version_id=form_version_id, version=version, items=items, labels=labels,
        )

    exam_key = str(exam.answer_key or "")
    version_key = str(version.get("answer_key") or "")
    if not form_layout.is_labeled_key(exam_key) or not form_layout.is_labeled_key(version_key):
        return _not_ready(
            exam,
            "Javoblar kaliti labeled emas. `36a`/`36b` qismlari alohida "
            "ko'rsatilgan kalit kerak (masalan `...|36a:√5,36b:3/7`).",
            form_version_id=form_version_id, version=version, items=items, labels=labels,
        )

    try:
        exam_outcomes = form_layout.score_items(exam_key, exam_key, exam.total_questions)
        version_outcomes = form_layout.score_items(
            version_key, version_key, exam.total_questions
        )
    except Exception as exc:
        return _not_ready(
            exam, f"Kalitni tekshirib bo'lmadi: {exc}",
            form_version_id=form_version_id, version=version, items=items, labels=labels,
        )

    if len(exam_outcomes) != 55 or len(version_outcomes) != 55:
        return _not_ready(
            exam,
            "Kalit 55 ta itemni qamramaydi "
            f"(exam={len(exam_outcomes)}, form={len(version_outcomes)}). "
            "Barcha 20 qism (36a…45b) kalitda bo'lishi shart.",
            form_version_id=form_version_id, version=version, items=items, labels=labels,
        )
    try:
        same_key = keys_are_equivalent(
            exam_key, version_key, exam.total_questions
        )
    except Exception as exc:
        return _not_ready(
            exam,
            f"Kalitlarni solishtirib bo'lmadi: {exc}",
            form_version_id=form_version_id, version=version, items=items, labels=labels,
        )
    if not same_key:
        return _not_ready(
            exam,
            "`exams.answer_key` va `form_versions.answer_key` bir xil emas. "
            "Online va offline natijalar adolatli bo'lishi uchun kalitlarni "
            "moslashtiring (yoki imtihonni qayta yarating).",
            form_version_id=form_version_id, version=version, items=items, labels=labels,
        )

    context = scoring.ScoringContext.from_exam(exam)
    if context.total_questions <= 0 or len(context.b_by_key) < context.total_questions:
        return _not_ready(
            exam, "`b` parametrlari to'liq emas.",
            form_version_id=form_version_id, version=version, items=items, labels=labels,
        )
    try:
        for item in items:
            context.difficulty_of(
                str(item.get("display_label") or ""), int(item.get("position") or 0)
            )
    except Exception as exc:
        return _not_ready(
            exam, f"`b` xaritasida item topilmadi: {exc}",
            form_version_id=form_version_id, version=version, items=items, labels=labels,
        )

    return OfflineReadiness(
        ready=True,
        reason="55 item, labeled kalit va `b` tayyor.",
        exam_id=exam.exam_id,
        form_version_id=form_version_id,
        form_version=version,
        items=tuple(items),
        labels=labels,
        key_fingerprint=key_fingerprint(version_key),
        labels_order_hash=labels_order_hash(labels),
        b_checksum=scoring.b_checksum(context),
        b_source=str(context.b_source),
        engine_version=str(scoring.SCORING_ENGINE_VERSION),
        scored_items=len(exam_outcomes),
    )


def _not_ready(
    exam: Exam,
    reason: str,
    *,
    form_version_id: int | None = None,
    version: dict[str, Any] | None = None,
    items: Sequence[dict[str, Any]] = (),
    labels: Sequence[str] = (),
) -> OfflineReadiness:
    context = scoring.ScoringContext.from_exam(exam)
    return OfflineReadiness(
        ready=False,
        reason=reason,
        exam_id=exam.exam_id,
        form_version_id=form_version_id,
        form_version=version,
        items=tuple(items),
        labels=tuple(labels),
        key_fingerprint="",
        labels_order_hash="",
        b_checksum=scoring.b_checksum(context),
        b_source=str(context.b_source),
        engine_version=str(scoring.SCORING_ENGINE_VERSION),
        scored_items=0,
    )


def score_offline(
    exam: Exam,
    readiness: OfflineReadiness,
    flags: Sequence[int],
) -> OfflineScore:
    """55 ta 0/1 bayroqni mavjud Rasch modeli bilan baholaydi (MLE/EAP)."""
    if not readiness.ready:
        raise OfflineReadinessError(readiness.reason)
    if len(flags) != len(readiness.items):
        raise OfflineReadinessError(
            f"Javoblar soni {len(flags)}; kutilgan {len(readiness.items)}."
        )

    context = scoring.ScoringContext.from_exam(exam)
    responses: list[rasch.ItemResponse] = []
    rows: list[dict[str, Any]] = []
    for index, (item, flag) in enumerate(zip(readiness.items, flags), start=1):
        label = str(item.get("display_label") or "")
        position = int(item.get("position") or 0)
        b_value = context.difficulty_of(label, position)
        is_correct = bool(int(flag))
        responses.append(
            rasch.ItemResponse(
                question_id=index,
                difficulty=float(b_value),
                is_correct=is_correct,
                skipped=False,
            )
        )
        rows.append(
            {
                "form_item_id": int(item.get("form_item_id") or 0),
                "item_version_id": int(item.get("item_version_id") or 0),
                "position": position,
                "display_label": label,
                "is_correct": is_correct,
                "b_used": float(b_value),
            }
        )

    estimate = (
        rasch.estimate_theta_eap(responses)
        if context.theta_method == "eap"
        else rasch.estimate_theta(responses)
    )
    summaries = subjects.summarize(
        (int(item.get("position") or 0), bool(int(flag)))
        for item, flag in zip(readiness.items, flags)
    )
    subject_balls = subjects.allocate_total_ball(estimate.scaled_score, summaries)

    return OfflineScore(
        theta=float(estimate.theta),
        theta_se=estimate.standard_error,
        scaled_score=float(estimate.scaled_score),
        raw_score=int(estimate.raw_score),
        total_items=int(estimate.total_items),
        level=rasch.ability_level(float(estimate.scaled_score)),
        is_extreme=bool(estimate.is_extreme),
        log_likelihood=float(estimate.log_likelihood),
        converged=bool(estimate.converged),
        engine_version=str(scoring.SCORING_ENGINE_VERSION),
        b_checksum=scoring.b_checksum(context),
        b_source=str(context.b_source),
        key_fingerprint=readiness.key_fingerprint,
        subject_summaries=tuple(summaries),
        subject_balls=dict(subject_balls),
        responses=tuple(rows),
    )
