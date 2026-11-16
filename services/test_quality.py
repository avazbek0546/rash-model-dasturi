"""Test sifati (Rasch 1PL) — Cronbach α, item fit, SRMSR/RMSEA, Wright, TIF.

Bu modul **baholashni o'zgartirmaydi**: u mavjud javoblar matritsasi va
`b` qiymatlaridan test sifatini hisoblaydi. Hisobot admin panel/CLI uchun.

Muhim: M2/RMSEA/CFI/TLI — **limited-information approximation**. Aniq M2
uchun to'liq pair covariance matritsasi va katta hisob kerak; bu modul
amaliy dashboard uchun yetarli yaqinlashuvni beradi (SRMSR esa bevosita
pair residuallardan hisoblanadi). Natijalar `metrics_version` bilan
belgilanadi.
"""

from __future__ import annotations

import logging
import math
import statistics
from typing import Any, Sequence

from services import exam_service, form_layout, grading, rasch, scoring

logger = logging.getLogger(__name__)

METRICS_VERSION = "1.0-approx"
MIN_RELIABLE_N = 30
MIN_ITEMS = 3


class TestQualityError(ValueError):
    """Test sifatini hisoblash uchun ma'lumot yetarli emas."""


def _fmean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _pvar(values: Sequence[float]) -> float:
    return statistics.pvariance(values) if len(values) > 1 else 0.0


def _safe_round(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def _pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Pearson korrelyatsiyasi (dispersiya 0 bo'lsa — `None`)."""
    if len(x) != len(y) or len(x) < 2:
        return None
    mx, my = _fmean(x), _fmean(y)
    vx = sum((value - mx) ** 2 for value in x)
    vy = sum((value - my) ** 2 for value in y)
    if vx <= 0 or vy <= 0:
        return None
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    return cov / math.sqrt(vx * vy)


def _chi2_sf(value: float, df: int) -> float | None:
    """Chi-kvadrat yuqori quyruq ehtimoli (Wilson–Hilferty yaqinlashuvi)."""
    if df <= 0 or value <= 0:
        return None
    z = ((value / df) ** (1.0 / 3.0) - (1.0 - 2.0 / (9.0 * df))) / math.sqrt(
        2.0 / (9.0 * df)
    )
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def cronbach_alpha(matrix: Sequence[Sequence[float]]) -> float | None:
    """Cronbach α — ichki izchillik.

    `matrix` — `N × K` (o'quvchi × item), qiymatlar 0/1. `K < 2` yoki umumiy
    dispersiya 0 bo'lsa — `None`.
    """
    if not matrix:
        return None
    k = len(matrix[0])
    if k < 2:
        return None
    n = len(matrix)
    item_vars = [_pvar([row[index] for row in matrix]) for index in range(k)]
    total = [sum(row) for row in matrix]
    total_var = _pvar(total)
    if total_var <= 0:
        return None
    alpha = (k / (k - 1)) * (1.0 - sum(item_vars) / total_var)
    return max(0.0, min(1.0, alpha))


def _probabilities(theta: float, b_values: Sequence[float]) -> list[float]:
    return [rasch.probability(theta, b) for b in b_values]


def _infit_outfit(
    matrix: Sequence[Sequence[float]],
    thetas: Sequence[float],
    b_values: Sequence[float],
) -> tuple[list[float | None], list[float | None]]:
    """Item infit/outfit MNSQ (Rasch standartlashtirilgan residuallar)."""
    k = len(b_values)
    n = len(matrix)
    infit: list[float | None] = []
    outfit: list[float | None] = []
    for index in range(k):
        z2: list[float] = []
        weights: list[float] = []
        for person in range(n):
            p = rasch.probability(thetas[person], b_values[index])
            variance = p * (1.0 - p)
            if variance <= 0:
                continue
            residual = (matrix[person][index] - p) / math.sqrt(variance)
            z2.append(residual * residual)
            weights.append(variance)
        outfit.append(_fmean(z2) if z2 else None)
        total_weight = sum(weights)
        infit.append(
            (sum(value * weight for value, weight in zip(z2, weights, strict=True))
             / total_weight)
            if total_weight > 0
            else None
        )
    return infit, outfit


def item_statistics(
    matrix: Sequence[Sequence[float]],
    thetas: Sequence[float],
    b_values: Sequence[float],
    labels: Sequence[str],
) -> list[dict[str, Any]]:
    """Har bir item uchun `p`, `r_pbi`, infit/outfit, `b`."""
    n = len(matrix)
    k = len(b_values)
    totals = [sum(row) for row in matrix]
    infit, outfit = _infit_outfit(matrix, thetas, b_values)
    rows: list[dict[str, Any]] = []
    for index in range(k):
        item = [row[index] for row in matrix]
        rest = [totals[person] - item[person] for person in range(n)]
        position = 0
        try:
            position, _part = form_layout.split_label(str(labels[index]))
        except ValueError:
            position = index + 1
        rows.append(
            {
                "label": str(labels[index]),
                "position": int(position),
                "b": _safe_round(b_values[index]),
                "p": _safe_round(_fmean(item)),
                "r_pbi": _safe_round(_pearson(item, rest)),
                "infit": _safe_round(infit[index]),
                "outfit": _safe_round(outfit[index]),
            }
        )
    return rows


def residual_fit(
    matrix: Sequence[Sequence[float]],
    thetas: Sequence[float],
    b_values: Sequence[float],
) -> dict[str, float | int | None]:
    """Limited-information fit: SRMSR, M2, RMSEA, CFI, TLI.

    Har bir item juftligi uchun kuzatilgan va Rasch bo'yicha kutilgan
    kovariatsiya solishtiriladi. M2/RMSEA/CFI/TLI — **approximation**
    (`metrics_version` ga qarang); SRMSR bevosita standartlashtirilgan
    residuallardan hisoblanadi.
    """
    n = len(matrix)
    k = len(b_values)
    if n < 2 or k < 3:
        return {
            "srmr": None,
            "m2": None,
            "df": None,
            "rmsea": None,
            "cfi": None,
            "tli": None,
            "m2_p": None,
        }

    probabilities = [
        [rasch.probability(theta, b) for b in b_values] for theta in thetas
    ]
    observed_means = [_fmean([row[index] for row in matrix]) for index in range(k)]
    expected_means = [
        _fmean([probabilities[person][index] for person in range(n)])
        for index in range(k)
    ]
    variances: list[float] = []
    for index in range(k):
        probs = [probabilities[person][index] for person in range(n)]
        variances.append(
            _pvar(probs)
            + _fmean([p * (1.0 - p) for p in probs])
        )

    residuals: list[float] = []
    null_residuals: list[float] = []
    for first in range(k):
        for second in range(first + 1, k):
            denom = math.sqrt(variances[first] * variances[second])
            if denom <= 0:
                continue
            observed_cov = _fmean(
                [
                    (matrix[person][first] - observed_means[first])
                    * (matrix[person][second] - observed_means[second])
                    for person in range(n)
                ]
            )
            expected_cov = _fmean(
                [
                    (probabilities[person][first] - expected_means[first])
                    * (probabilities[person][second] - expected_means[second])
                    for person in range(n)
                ]
            )
            residuals.append((observed_cov - expected_cov) / denom)
            null_residuals.append(observed_cov / denom)

    if not residuals:
        return {
            "srmr": None,
            "m2": None,
            "df": None,
            "rmsea": None,
            "cfi": None,
            "tli": None,
            "m2_p": None,
        }

    pairs = len(residuals)
    srmr = math.sqrt(_fmean([value * value for value in residuals]))
    m2 = n * sum(value * value for value in residuals)
    df = max(pairs - k, 1)
    rmsea = math.sqrt(max((m2 - df) / (df * n), 0.0))

    m2_null = n * sum(value * value for value in null_residuals)
    df_null = max(pairs, 1)
    cfi: float | None = None
    tli: float | None = None
    null_gap = max(m2_null - df_null, 0.0)
    model_gap = max(m2 - df, 0.0)
    if null_gap > 0:
        cfi = max(0.0, min(1.0, 1.0 - model_gap / null_gap))
        tli_denom = null_gap / df_null - 1.0
        if abs(tli_denom) > 1e-12:
            tli = max(
                0.0,
                min(1.0, (null_gap / df_null - model_gap / df) / tli_denom),
            )
    return {
        "srmr": _safe_round(srmr),
        "m2": _safe_round(m2, 2),
        "df": int(df),
        "rmsea": _safe_round(rmsea),
        "cfi": _safe_round(cfi),
        "tli": _safe_round(tli),
        "m2_p": _safe_round(_chi2_sf(m2, df)),
    }


def eap_reliability(
    thetas: Sequence[float], standard_errors: Sequence[float | None]
) -> float | None:
    """Marginal (EAP) ishonchlilik: `1 − mean(SE²)/var(θ)`."""
    if len(thetas) < 2:
        return None
    variance = _pvar(thetas)
    if variance <= 0:
        return None
    errors = [float(value) ** 2 for value in standard_errors if value is not None]
    if not errors:
        return None
    return max(0.0, min(1.0, 1.0 - _fmean(errors) / variance))


def wright_map(
    thetas: Sequence[float], b_values: Sequence[float], *, bins: int = 20
) -> dict[str, Any]:
    """Wright xaritasi: θ va `b` taqsimoti (logit bo'yicha gistogramma)."""
    values = [float(value) for value in thetas] + [float(value) for value in b_values]
    if not values:
        return {"min": -4.0, "max": 4.0, "bins": [], "person_counts": [], "item_counts": []}
    low = min(min(values), -4.0)
    high = max(max(values), 4.0)
    if high <= low:
        high = low + 1.0
    width = (high - low) / max(int(bins), 1)
    person_counts = [0] * bins
    item_counts = [0] * bins
    centers = [low + width * (index + 0.5) for index in range(bins)]
    for theta in thetas:
        index = min(bins - 1, max(0, int((float(theta) - low) / width)))
        person_counts[index] += 1
    for b in b_values:
        index = min(bins - 1, max(0, int((float(b) - low) / width)))
        item_counts[index] += 1
    return {
        "min": round(low, 3),
        "max": round(high, 3),
        "bins": [round(value, 3) for value in centers],
        "person_counts": person_counts,
        "item_counts": item_counts,
    }


def test_information_function(
    b_values: Sequence[float], *, low: float = -4.0, high: float = 4.0, step: float = 0.25
) -> dict[str, list[float]]:
    """TIF: `I(θ) = Σ P_j(θ)(1 − P_j(θ))`."""
    if high <= low or step <= 0:
        raise ValueError("TIF panjarasi noto'g'ri")
    points = int(round((high - low) / step)) + 1
    grid = [low + step * index for index in range(points)]
    information = [
        sum(
            rasch.probability(theta, b) * (1.0 - rasch.probability(theta, b))
            for b in b_values
        )
        for theta in grid
    ]
    return {
        "theta": [round(value, 3) for value in grid],
        "information": [round(value, 4) for value in information],
    }


def build_quality_report_from_matrix(
    matrix: Sequence[Sequence[float]],
    labels: Sequence[str],
    b_values: Sequence[float],
    *,
    thetas: Sequence[float] | None = None,
    standard_errors: Sequence[float | None] | None = None,
    raw_scores: Sequence[int] | None = None,
    theta_method: str = "eap",
    exam_id: int | None = None,
    title: str = "",
    test_code: str = "",
    source: str = "online",
) -> dict[str, Any]:
    """Matritsadan to'liq sifat hisobotini quradi (sof funksiya)."""
    rows = [list(row) for row in matrix]
    labels = [str(label) for label in labels]
    b_values = [float(value) for value in b_values]
    if not rows:
        raise TestQualityError("Javoblar matritsasi bo'sh.")
    if len(labels) != len(b_values):
        raise TestQualityError("`labels` va `b_values` uzunligi mos emas.")
    for row in rows:
        if len(row) != len(labels):
            raise TestQualityError("Matritsa qatorlari item soniga mos emas.")
    k = len(labels)
    n = len(rows)

    if thetas is None:
        theta_values: list[float] = []
        se_values: list[float | None] = []
        raw_values: list[int] = []
        for row in rows:
            responses = [
                rasch.ItemResponse(
                    question_id=index + 1,
                    difficulty=b_values[index],
                    is_correct=bool(row[index]),
                    skipped=False,
                )
                for index in range(k)
            ]
            estimate = (
                rasch.estimate_theta_eap(responses)
                if str(theta_method).lower() == "eap"
                else rasch.estimate_theta(responses)
            )
            theta_values.append(float(estimate.theta))
            se_values.append(estimate.standard_error)
            raw_values.append(int(estimate.raw_score))
    else:
        theta_values = [float(value) for value in thetas]
        se_values = list(standard_errors or [None] * n)
        raw_values = (
            [int(value) for value in raw_scores]
            if raw_scores is not None
            else [int(sum(row)) for row in rows]
        )

    if len(theta_values) != n:
        raise TestQualityError("`thetas` uzunligi qatorlar soniga mos emas.")

    items = item_statistics(rows, theta_values, b_values, labels)
    alpha = cronbach_alpha(rows)
    reliability = eap_reliability(theta_values, se_values)
    fit = residual_fit(rows, theta_values, b_values)
    r_pbi_values = [
        float(item["r_pbi"]) for item in items if item["r_pbi"] is not None
    ]
    warnings: list[str] = []
    if n < MIN_RELIABLE_N:
        warnings.append(
            f"N={n} < {MIN_RELIABLE_N}: ishonchlilik/fit ko'rsatkichlari beqaror."
        )
    if k < MIN_ITEMS:
        warnings.append(f"Itemlar soni {k} < {MIN_ITEMS}: fit hisoblanmaydi.")
    if alpha is None:
        warnings.append("Cronbach α hisoblanmadi (dispersiya 0 yoki item < 2).")
    if fit["m2"] is not None:
        warnings.append(
            "M2/RMSEA/CFI/TLI — limited-information approximation; "
            "SRMSR bevosita residuallardan."
        )

    return {
        "ok": True,
        "metrics_version": METRICS_VERSION,
        "source": source,
        "exam_id": exam_id,
        "title": title,
        "test_code": test_code,
        "theta_method": str(theta_method).lower(),
        "summary": {
            "participants": n,
            "items": k,
            "mean_raw": _safe_round(_fmean([float(value) for value in raw_values]), 2),
            "sd_raw": _safe_round(
                math.sqrt(_pvar([float(value) for value in raw_values])), 2
            ),
            "min_raw": min(raw_values),
            "max_raw": max(raw_values),
            "cronbach_alpha": _safe_round(alpha),
            "eap_reliability": _safe_round(reliability),
            "mean_r_pbi": _safe_round(_fmean(r_pbi_values)) if r_pbi_values else None,
            "srmr": fit["srmr"],
            "m2": fit["m2"],
            "df": fit["df"],
            "m2_p": fit["m2_p"],
            "rmsea": fit["rmsea"],
            "cfi": fit["cfi"],
            "tli": fit["tli"],
        },
        "items": items,
        "wright": wright_map(theta_values, b_values),
        "tif": test_information_function(b_values),
        "warnings": warnings,
    }


async def build_exam_quality(repos, exam, *, source: str = "combined") -> dict[str, Any]:
    """Imtihonning test sifati hisoboti.

    Args:
        source: `"online"` — faqat online javoblar; `"offline"` — faqat offline
            (qog'oz) natijalar; `"combined"` — ikkalasi (reytingdagi kabi:
            bog'langan/dublikat online natijalar chiqarib tashlanadi).
    """
    mode = str(source or "combined").strip().lower()
    if mode not in {"online", "offline", "combined"}:
        raise TestQualityError(
            f"`source` noto'g'ri: {source!r} (online/offline/combined)"
        )

    setup = await grading.prepare_scoring(repos, exam)
    context = setup.item_level_context or setup.context
    labels: list[str] | None = None
    b_values: list[float] | None = None
    theta_method = context.theta_method
    matrix: list[list[float]] = []
    thetas: list[float] = []
    standard_errors: list[float | None] = []
    raw_scores: list[int] = []
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
                answers, active = await grading.resolve_grading_answers(
                    repos, exam, submission
                )
                results = scoring.build_item_results(active, answers)
                if not results:
                    continue
                estimate = scoring.estimate_theta(results, active)
            except Exception:
                logger.exception(
                    "Test sifati: online javob baholanmadi (exam_id=%s, user_id=%s)",
                    exam.exam_id,
                    submission.user_id,
                )
                continue

            if labels is None:
                labels = [result.question_key for result in results]
                b_values = [float(result.difficulty) for result in results]
                theta_method = active.theta_method
            by_label = {result.question_key: result.is_correct for result in results}
            matrix.append(
                [1.0 if by_label.get(label, False) else 0.0 for label in labels]
            )
            thetas.append(float(estimate.theta))
            standard_errors.append(estimate.standard_error)
            raw_scores.append(int(estimate.raw_score))
            online_count += 1

    if mode in {"offline", "combined"}:
        for attempt in await repos.offline_attempts.list_for_exam(exam.exam_id):
            if mode == "combined" and not int(attempt.get("included_in_ranking") or 0):
                continue
            attempt_id = int(attempt.get("offline_attempt_id") or 0)
            responses = await repos.offline_attempts.list_responses(attempt_id)
            if not responses:
                continue
            if labels is None:
                labels = [str(row.get("display_label")) for row in responses]
                b_values = [float(row.get("b_used") or 0.0) for row in responses]
            by_label = {
                str(row.get("display_label")): bool(int(row.get("is_correct") or 0))
                for row in responses
            }
            matrix.append(
                [1.0 if by_label.get(label, False) else 0.0 for label in labels]
            )
            thetas.append(float(attempt.get("theta") or 0.0))
            standard_errors.append(
                None if attempt.get("theta_se") is None else float(attempt["theta_se"])
            )
            raw_scores.append(int(attempt.get("raw_score") or 0))
            offline_count += 1

    if not matrix or labels is None or b_values is None:
        raise TestQualityError(
            f"`{mode}` manbasida baholanadigan javoblar yo'q "
            "(avval javoblar yuborilishi va baholanishi kerak)."
        )

    report = build_quality_report_from_matrix(
        matrix,
        labels,
        b_values,
        thetas=thetas,
        standard_errors=standard_errors,
        raw_scores=raw_scores,
        theta_method=theta_method,
        exam_id=int(exam.exam_id),
        title=str(exam.title),
        test_code=str(exam.test_code),
        source=mode,
    )
    report["summary"]["online_participants"] = online_count
    report["summary"]["offline_participants"] = offline_count
    report["summary"]["excluded_online"] = excluded_online
    return report


