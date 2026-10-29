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
from typing import Any, Iterable, Mapping, Sequence

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


def allocate_total_ball(
    total_ball: float,
    summaries: Sequence[Mapping[str, Any]],
) -> dict[str, float | None]:
    """Umumiy sertifikat balini fanlar o'rtasida taqsimlaydi.

    **Alohida θ hisoblanmaydi.** Umumiy 0–100 ball olinadi va fanlar bo'yicha
    to'g'ri javoblar ulushiga qarab bo'linadi:

        algebra_ball + geometriya_ball = umumiy_ball

    Agar birorta savolga to'g'ri javob bo'lmasa (barcha javob xato/bo'sh),
    taqsimot fanlardagi elementlar soniga mutanosib bo'ladi — shunda ham
    yig'indi umumiy ballga teng qoladi.

    `summaries` — `summarize()` natijasi: har bir fan uchun `code`, `correct`,
    `total`. Savoli yo'q fan (masalan, qisqa testda geometriya bo'lmasa)
    `None` qaytaradi; bunday fanda taqsimlanadigan ball ham yo'q.

    Qaytaradi:
        `{fan_kodi: ball}` — 0.1 aniqlikda; mavjud fanlar yig'indisi
        `round(total_ball, 1)` ga teng.
    """
    target = round(max(0.0, min(100.0, float(total_ball or 0.0))), 1)
    rows = {str(row.get("code")): row for row in summaries}

    present: dict[str, int] = {}
    correct: dict[str, int] = {}
    for code in subject_codes():
        row = rows.get(code)
        if row is None:
            continue
        total = int(row.get("total") or 0)
        if total <= 0:
            continue
        present[code] = total
        correct[code] = max(0, min(total, int(row.get("correct") or 0)))

    result: dict[str, float | None] = {code: None for code in subject_codes()}
    if not present:
        return result

    codes = [code for code in subject_codes() if code in present]
    total_items = sum(present.values())
    total_correct = sum(correct.values())
    weights = {
        code: (
            correct[code] / total_correct
            if total_correct > 0
            else present[code] / total_items
        )
        for code in codes
    }

    # Yaxlitlashda yig'indi aniq saqlanishi uchun oxirgi fanga qoldiq beriladi.
    allocated = 0.0
    for index, code in enumerate(codes):
        if index == len(codes) - 1:
            value = round(target - allocated, 1)
        else:
            value = round(target * weights[code], 1)
            allocated += value
        result[code] = max(0.0, min(100.0, value))
    return result
