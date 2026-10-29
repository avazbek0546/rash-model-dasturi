"""Algebra / geometriya bo'limlari (milliy sertifikat strukturasi).

Har bir savol **pozitsiyasi** (raqami) bitta fanga tegishli. Oraliqlar pastdagi
:data:`SUBJECT_RANGES` da — test strukturasi o'zgarsa, faqat shu yerni
yangilash kifoya.

Diqqat: 36–45 pozitsiyalar ``a``/``b`` qismlarga bo'lingan — har bir qism
**alohida element** (masalan ``36a``, ``36b``) va ikkisi ham o'sha pozitsiya
faniga kiradi.

45 pozitsiyali to'liq test uchun elementlar bo'yicha::

    Algebra    : 1–23 (23) + 31–32 (2) + 36–40 (5 × 2 = 10) = 35 element
    Geometriya : 24–30 (7)  + 33–35 (3) + 41–45 (5 × 2 = 10) = 20 element
    Jami       : 55 element

Oraliqlar **to'qnashmasligi** shart — har bir pozitsiya aynan bitta fanga
tegishli (:func:`subject_of_position`).
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from services import rasch

logger = logging.getLogger(__name__)

#: Fan kodlari.
SUBJECT_ALGEBRA: str = "algebra"
SUBJECT_GEOMETRY: str = "geometry"

#: Ko'rsatish uchun nomlar.
SUBJECT_LABELS: dict[str, str] = {
    SUBJECT_ALGEBRA: "Algebra",
    SUBJECT_GEOMETRY: "Geometriya",
}

#: ``(fan, boshlanish, tugash)`` — INKLYUZIV oraliqlar (savol pozitsiyasi).
#: Tartib muhim va oraliqlar to'qnashmasligi kerak.
#: Tasdiqlangan taqsimot: 40 → algebra, 41 → geometriya.
SUBJECT_RANGES: tuple[tuple[str, int, int], ...] = (
    (SUBJECT_ALGEBRA, 1, 23),
    (SUBJECT_GEOMETRY, 24, 30),
    (SUBJECT_ALGEBRA, 31, 32),
    (SUBJECT_GEOMETRY, 33, 35),
    (SUBJECT_ALGEBRA, 36, 40),
    (SUBJECT_GEOMETRY, 41, 45),
)


def subject_codes() -> list[str]:
    """Oraliqlarda uchraydigan fanlar (birinchi uchrash tartibida, takrorsiz)."""
    codes: list[str] = []
    for code, _start, _end in SUBJECT_RANGES:
        if code not in codes:
            codes.append(code)
    return codes


def subject_of_position(position: int) -> str | None:
    """Pozitsiya (savol raqami) qaysi fanga tegishli (topilmasa — ``None``)."""
    value = int(position)
    for code, start, end in SUBJECT_RANGES:
        if start <= value <= end:
            return code
    return None


def summarize(items: Iterable[tuple[int, bool]]) -> list[dict[str, Any]]:
    """``(pozitsiya, to'g'rimi)`` juftliklaridan fan bo'yicha jamlanma.

    Har bir fan uchun ``{"code", "label", "correct", "total"}`` qaytariladi
    (tartib — :func:`subject_codes`). Oraliqqa tushmagan pozitsiyalar
    e'tiborga olinmaydi; bir pozitsiyaning ``a``/``b`` qismlari **alohida**
    element bo'lib sanaladi.
    """
    codes = subject_codes()
    counts: dict[str, dict[str, int]] = {
        code: {"correct": 0, "total": 0} for code in codes
    }
    for position, is_correct in items:
        code = subject_of_position(position)
        if code is None:
            continue
        counts[code]["total"] += 1
        if is_correct:
            counts[code]["correct"] += 1
    return [
        {
            "code": code,
            "label": SUBJECT_LABELS.get(code, code),
            "correct": counts[code]["correct"],
            "total": counts[code]["total"],
        }
        for code in codes
    ]


def scaled_scores(
    items: Iterable[tuple[int, bool, float]],
) -> dict[str, float | None]:
    """Har bir fan uchun **Rasch bo'yicha 0–100 ball** (umumiy ball bilan bir shkala).

    `items` — `(pozitsiya, to'g'rimi, qiyinchilik)` uchliklari. Har bir fan
    bo'yicha alohida θ baholanadi va `rasch.theta_to_scaled()` orqali 0–100
    shkalaga o'tkaziladi. Kichik bo'limda θ beqarorroq bo'lishi mumkin — shu
    sababli hisoblanmasa `None` qaytariladi.

    Bu **foiz emas**: fan ichidagi savollarning qiyinchiligi ham hisobga
    olinadi. Shuning uchun Algebra/Geometriya ballari sertifikat bali bilan
    bir xil shkalada bo'ladi va ularni taqqoslash mumkin.
    """
    groups: dict[str, list[rasch.ItemResponse]] = {}
    for position, is_correct, difficulty in items:
        code = subject_of_position(int(position))
        if code is None:
            continue
        groups.setdefault(code, []).append(
            rasch.ItemResponse(
                question_id=int(position),
                difficulty=float(difficulty),
                is_correct=bool(is_correct),
            )
        )

    scores: dict[str, float | None] = {}
    for code in subject_codes():
        responses = groups.get(code) or []
        if not responses:
            scores[code] = None
            continue
        try:
            scores[code] = round(
                rasch.estimate_theta(responses).scaled_score, 1
            )
        except Exception:  # pragma: no cover - kutilmagan matematik holat
            logger.exception("Fan bo'yicha ball hisoblanmadi: %s", code)
            scores[code] = None
    return scores
