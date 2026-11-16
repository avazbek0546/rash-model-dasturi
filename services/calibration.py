"""Rasch 1PL (JMLE) avtomatik kalibrlash.

Bu modul katta qatnashchi oqimida (masalan 10 000+) item qiyinchiliklarini
**javoblardan** hisoblaydi. Natija `exams.difficulty_logits` ga label bo'yicha
JSON obyekt sifatida yoziladi — baholash `services.exam_service.b_by_key()`
orqali avtomatik EAP rejimiga o'tadi.

Asosiy g'oyalar
---------------
* **JMLE** (Joint Maximum Likelihood Estimation): θ va `b` navbatma-navbat
  baholanadi. Har bir qadamda boshqa tomon qat'iy (fixed) hisoblanadi.
* **EAP emas, tez MLE** — 10 000 × 55 matritsa uchun EAP panjarasi juda sekin;
  shu sababli θ Nyuton-Raphson bilan, `b` esa item bo'yicha Nyuton bilan
  yangilanadi. Yakuniy natija baribir `b` (logit) bo'lib qoladi.
* **Xavfsizlik chegaralari**: `min_n` (default 200), `b ∈ [-4.6, +4.6]`,
  ekstremal itemlar (hammasi to'g'ri/noto'g'ri) chegaraga qisiladi va
  ogohlantirishda ko'rsatiladi.
* **Prior/shrinkaj** (ixtiyoriy): mavjud item bankdagi `b` ni prior sifatida
  berish mumkin; `w = N / (N + K)` bilan aralashtiriladi. Katta `N` da bu
  deyarli sezilmaydi, kichik `N` da esa barqarorlik beradi.

Modul faqat hisoblaydi; yozish uchun :func:`apply_calibration` yoki
`scripts/calibrate_item_bank.py` dan foydalaning.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from database.repository import Repositories
from services import grading, scoring

logger = logging.getLogger(__name__)

#: `b` (logit) mutlaq chegarasi — `item_statistics` bilan bir xil.
B_MIN: float = -4.6
B_MAX: float = 4.6

#: θ qidiruv chegarasi (ekstremal o'quvchilar uchun).
THETA_MIN: float = -6.0
THETA_MAX: float = 6.0


class CalibrationError(ValueError):
    """Kalibrlash uchun ma'lumot yetarli emas yoki matritsa buzuq."""


@dataclass(slots=True)
class ExamMatrix:
    """Imtihon javoblaridan yig'ilgan 0/1 matritsa."""

    labels: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]
    source: str
    online_count: int
    offline_count: int
    excluded_online: int = 0


@dataclass(slots=True)
class CalibrationResult:
    """JMLE natijasi (barcha maydonlar JSON'ga tayyor)."""

    labels: tuple[str, ...]
    b_by_label: dict[str, float]
    se_by_label: dict[str, float | None]
    person_count: int
    item_count: int
    iterations: int
    converged: bool
    max_delta: float
    b_mean: float
    b_min: float
    b_max: float
    theta_mean: float
    theta_sd: float
    source: str
    online_count: int
    offline_count: int
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """API/CLI uchun lug'at ko'rinishi."""
        return {
            "labels": list(self.labels),
            "b_by_label": {key: round(float(value), 6) for key, value in self.b_by_label.items()},
            "se_by_label": {
                key: (None if value is None else round(float(value), 6))
                for key, value in self.se_by_label.items()
            },
            "person_count": self.person_count,
            "item_count": self.item_count,
            "iterations": self.iterations,
            "converged": self.converged,
            "max_delta": round(float(self.max_delta), 8),
            "b_mean": round(float(self.b_mean), 6),
            "b_min": round(float(self.b_min), 6),
            "b_max": round(float(self.b_max), 6),
            "theta_mean": round(float(self.theta_mean), 6),
            "theta_sd": round(float(self.theta_sd), 6),
            "source": self.source,
            "online_count": self.online_count,
            "offline_count": self.offline_count,
            "warnings": list(self.warnings),
        }


async def build_exam_matrix(
    repos: Repositories, exam: Any, *, source: str = "combined"
) -> ExamMatrix:
    """Imtihon javoblaridan kalibrlash matritsasini yig'adi.

    `source`: `online` | `offline` | `combined` (default). `combined` —
    reytingdagi kabi: bog'langan/dublikat online natijalar chiqarib tashlanadi,
    offline `included_in_ranking = 1` natijalar qo'shiladi.
    """
    mode = str(source or "combined").strip().lower()
    if mode not in {"online", "offline", "combined"}:
        raise CalibrationError(f"`source` noto'g'ri: {source!r} (online/offline/combined)")

    setup = await grading.prepare_scoring(repos, exam)
    context = setup.item_level_context or setup.context
    labels: list[str] | None = None
    rows: list[tuple[float, ...]] = []
    online_count = 0
    offline_count = 0
    excluded_online = 0

    if mode in {"online", "combined"}:
        for submission in await repos.answers.list_for_exam(exam.exam_id):
            if mode == "combined":
                excluded = await repos.offline_decisions.is_excluded(
                    exam.exam_id, "telegram_user", submission.user_id
                )
                if excluded:
                    excluded_online += 1
                    continue
            try:
                results = scoring.build_item_results(
                    context, str(submission.submitted_answers or "")
                )
            except Exception:
                logger.exception(
                    "Kalibrlash: online javob baholanmadi (exam_id=%s, user_id=%s)",
                    exam.exam_id,
                    submission.user_id,
                )
                continue
            if not results:
                continue
            if labels is None:
                labels = [result.question_key for result in results]
            by_label = {
                result.question_key: 1.0 if result.is_correct else 0.0
                for result in results
            }
            rows.append(tuple(by_label.get(label, 0.0) for label in labels))
            online_count += 1

    if mode in {"offline", "combined"}:
        for attempt in await repos.offline_attempts.list_for_exam(exam.exam_id):
            if mode == "combined" and not int(attempt.get("included_in_ranking") or 0):
                continue
            responses = await repos.offline_attempts.list_responses(
                int(attempt.get("offline_attempt_id") or 0)
            )
            if not responses:
                continue
            if labels is None:
                labels = [str(row.get("display_label")) for row in responses]
            by_label = {
                str(row.get("display_label")): (
                    1.0 if int(row.get("is_correct") or 0) else 0.0
                )
                for row in responses
            }
            rows.append(tuple(by_label.get(label, 0.0) for label in labels))
            offline_count += 1

    if labels is None or not rows:
        raise CalibrationError(
            f"`{mode}` manbasida kalibrlash uchun javoblar yo'q "
            "(avval javoblar yuborilishi va baholanishi kerak)."
        )
    return ExamMatrix(
        labels=tuple(labels),
        matrix=tuple(rows),
        source=mode,
        online_count=online_count,
        offline_count=offline_count,
        excluded_online=excluded_online,
    )


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _logistic(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _estimate_thetas(
    matrix: Sequence[Sequence[float]],
    b_values: Sequence[float],
    *,
    theta_min: float,
    theta_max: float,
    tol: float,
    max_iter: int = 40,
) -> list[float]:
    """Har bir o'quvchi uchun θ (MLE, Nyuton-Raphson)."""
    result: list[float] = []
    for row in matrix:
        theta = 0.0
        for _ in range(max_iter):
            gradient = 0.0
            information = 0.0
            for u, b_value in zip(row, b_values):
                p = _logistic(theta - b_value)
                gradient += u - p
                information += p * (1.0 - p)
            if information <= 1e-12:
                break
            delta = gradient / information
            theta = _clip(theta + delta, theta_min, theta_max)
            if abs(delta) < tol:
                break
        result.append(theta)
    return result



def calibrate_rasch(
    matrix: Sequence[Sequence[float]],
    labels: Sequence[str],
    *,
    min_n: int = 200,
    max_iter: int = 100,
    tol: float = 1e-4,
    b_min: float = B_MIN,
    b_max: float = B_MAX,
    theta_min: float = THETA_MIN,
    theta_max: float = THETA_MAX,
    prior_b: Mapping[str, float] | None = None,
    prior_k: float = 30.0,
) -> CalibrationResult:
    """Rasch 1PL `b` va θ ni JMLE bilan baholaydi.

    Args:
        matrix: `N × K` 0/1 matritsa (qator — o'quvchi, ustun — item).
        labels: item belgilari (`"1"`, `"36a"`, ...).
        min_n: minimal qatnashchi soni (default 200). Kam bo'lsa — xato.
        max_iter: maksimal JMLE iteratsiyasi.
        tol: `b` o'zgarishining toleransi.
        b_min/b_max: `b` chegaralari.
        theta_min/theta_max: θ chegaralari.
        prior_b: ixtiyoriy oldingi `b` (item bank) — kichik `N` uchun prior.
        prior_k: prior vazni `w = N / (N + K)`.

    Raises:
        CalibrationError: matritsa bo'sh/buzuq yoki `N < min_n` bo'lsa.
    """
    labels_list = [str(label) for label in labels]
    if not labels_list:
        raise CalibrationError("Item belgilari bo'sh.")
    if len(set(labels_list)) != len(labels_list):
        raise CalibrationError("Item belgilari takrorlanadi.")
    n = len(matrix)
    if n <= 0:
        raise CalibrationError("Matritsa bo'sh.")
    if n < int(min_n):
        raise CalibrationError(
            f"Kalibrlash uchun qatnashchilar yetarli emas: N={n}, min_n={int(min_n)}."
        )
    k = len(labels_list)
    values: list[list[float]] = []
    for row in matrix:
        if len(row) != k:
            raise CalibrationError(
                f"Matritsa ustunlari ({len(row)}) item soniga ({k}) teng emas."
            )
        values.append([1.0 if float(value) >= 0.5 else 0.0 for value in row])

    totals = [sum(row[index] for row in values) for index in range(k)]
    prior = {
        str(key): float(value)
        for key, value in (prior_b or {}).items()
        if math.isfinite(float(value))
    }

    b_values: list[float] = []
    for index, label in enumerate(labels_list):
        prior_value = prior.get(label)
        if prior_value is not None:
            b_value = _clip(prior_value, b_min, b_max)
        else:
            p = (totals[index] + 0.5) / (n + 1.0)
            b_value = _clip(math.log((1.0 - p) / p), b_min, b_max)
        b_values.append(b_value)

    converged = False
    max_delta = float("inf")
    iterations = 0
    for iteration in range(1, int(max_iter) + 1):
        iterations = iteration
        thetas = _estimate_thetas(
            values,
            b_values,
            theta_min=theta_min,
            theta_max=theta_max,
            tol=tol,
        )
        new_b: list[float] = []
        for index, label in enumerate(labels_list):
            correct = totals[index]
            b_value = b_values[index]
            if correct <= 0:
                b_value = b_max
            elif correct >= n:
                b_value = b_min
            else:
                for _ in range(30):
                    sum_p = 0.0
                    information = 0.0
                    for theta in thetas:
                        p = _logistic(theta - b_value)
                        sum_p += p
                        information += p * (1.0 - p)
                    if information <= 1e-12:
                        break
                    delta = (sum_p - correct) / information
                    b_value = _clip(b_value + delta, b_min, b_max)
                    if abs(delta) < tol:
                        break
            prior_value = prior.get(label)
            if prior_value is not None and prior_k > 0:
                weight = n / (n + float(prior_k))
                b_value = weight * b_value + (1.0 - weight) * prior_value
                b_value = _clip(b_value, b_min, b_max)
            new_b.append(b_value)

        mean_b = sum(new_b) / k
        new_b = [_clip(value - mean_b, b_min, b_max) for value in new_b]
        max_delta = max(abs(new_b[index] - b_values[index]) for index in range(k))
        b_values = new_b
        if max_delta < tol:
            converged = True
            break


    thetas = _estimate_thetas(
        values,
        b_values,
        theta_min=theta_min,
        theta_max=theta_max,
        tol=tol,
    )
    se_by_label: dict[str, float | None] = {}
    for index, label in enumerate(labels_list):
        information = 0.0
        for theta in thetas:
            p = _logistic(theta - b_values[index])
            information += p * (1.0 - p)
        se_by_label[label] = (
            None if information <= 1e-12 else 1.0 / math.sqrt(information)
        )

    mean_theta = sum(thetas) / n
    sd_theta = math.sqrt(sum((theta - mean_theta) ** 2 for theta in thetas) / n)
    mean_b = sum(b_values) / k
    extreme = [
        label
        for index, label in enumerate(labels_list)
        if totals[index] <= 0 or totals[index] >= n
    ]
    warnings: list[str] = []
    if extreme:
        warnings.append(
            f"{len(extreme)} item chegarada (hammasi to'g'ri/noto'g'ri): "
            + ", ".join(extreme[:10])
        )
    if not converged:
        warnings.append(
            f"JMLE {iterations} iteratsiyada to'liq yaqinlashmadi "
            f"(max_delta={max_delta:.6f})."
        )

    return CalibrationResult(
        labels=tuple(labels_list),
        b_by_label={
            label: float(b_values[index]) for index, label in enumerate(labels_list)
        },
        se_by_label=se_by_label,
        person_count=n,
        item_count=k,
        iterations=iterations,
        converged=converged,
        max_delta=max_delta,
        b_mean=mean_b,
        b_min=min(b_values),
        b_max=max(b_values),
        theta_mean=mean_theta,
        theta_sd=sd_theta,
        source="jmle",
        online_count=0,
        offline_count=0,
        warnings=tuple(warnings),
    )


async def apply_calibration(
    repos: Repositories, exam: Any, result: CalibrationResult
) -> str:
    """Kalibrlangan `b` ni `exams.difficulty_logits` ga yozadi.

    Baholash keyingi safar `b_by_key()` orqali per-item `b` ni o'qiydi va
    `THETA_METHOD=auto` bo'lsa avtomatik EAP rejimiga o'tadi.

    Returns:
        Bazaga yozilgan JSON satri.
    """
    payload = json.dumps(
        {
            label: round(float(value), 6)
            for label, value in result.b_by_label.items()
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    await repos.exams.update_difficulty_logits(int(exam.exam_id), payload)
    logger.info(
        "Item bank kalibrlandi: exam_id=%s, N=%s, K=%s, converged=%s",
        exam.exam_id,
        result.person_count,
        result.item_count,
        result.converged,
    )
    return payload

