"""Rasch JMLE avtomatik kalibrlash testlari.

Ishga tushirish:
    python tests/test_calibration.py
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import calibration  # noqa: E402


def logistic(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _correlation(xs: list[float], ys: list[float]) -> float:
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    return cov / math.sqrt(vx * vy)


def check_synthetic_recovery() -> None:
    """N=1200, 12 item: JMLE haqiqiy `b` ni tiklaydi."""
    rng = random.Random(42)
    true_b = [
        -2.0,
        -1.5,
        -1.0,
        -0.5,
        0.0,
        0.5,
        1.0,
        1.5,
        2.0,
        -0.25,
        0.25,
        0.75,
    ]
    labels = [str(index + 1) for index in range(len(true_b))]
    matrix: list[list[float]] = []
    for _ in range(1200):
        theta = rng.gauss(0.0, 1.0)
        matrix.append(
            [
                1.0 if rng.random() < logistic(theta - b_value) else 0.0
                for b_value in true_b
            ]
        )

    result = calibration.calibrate_rasch(
        matrix, labels, min_n=200, max_iter=100, tol=1e-5
    )
    assert result.converged, result.warnings
    assert result.person_count == 1200 and result.item_count == len(true_b)
    estimated = [result.b_by_label[label] for label in labels]
    corr = _correlation(true_b, estimated)
    rmse = math.sqrt(
        sum((true - est) ** 2 for true, est in zip(true_b, estimated)) / len(true_b)
    )
    assert corr > 0.95, corr
    assert rmse < 0.45, rmse
    assert abs(result.b_mean) < 0.05, result.b_mean
    assert all(value is not None for value in result.se_by_label.values())
    print(
        f"[OK] JMLE: N={result.person_count}, K={result.item_count}, "
        f"corr={corr:.4f}, RMSE={rmse:.4f}, iter={result.iterations}"
    )


def check_min_n() -> None:
    """N < min_n — aniq xato (jim hisoblamaydi)."""
    matrix = [[1.0, 0.0] for _ in range(10)]
    try:
        calibration.calibrate_rasch(matrix, ["1", "2"], min_n=100)
    except calibration.CalibrationError as exc:
        assert "min_n" in str(exc), exc
        print("[OK] min_n: N=10, min_n=100 → CalibrationError")
        return
    raise AssertionError("CalibrationError kutilgan edi")


def check_extreme_items() -> None:
    """Hammasi to'g'ri/noto'g'ri itemlar chegaraga qisiladi va ogohlantiradi."""
    matrix = [[1.0, 0.0] for _ in range(300)]
    result = calibration.calibrate_rasch(matrix, ["1", "2"], min_n=1, max_iter=20)
    assert result.warnings and "chegarada" in result.warnings[0], result.warnings
    assert all(
        calibration.B_MIN <= value <= calibration.B_MAX
        for value in result.b_by_label.values()
    )
    payload = result.to_dict()
    assert payload["person_count"] == 300 and payload["item_count"] == 2
    assert "b_by_label" in payload and "se_by_label" in payload
    print("[OK] Ekstremal itemlar: b chegarada, warning bor, to_dict ishlaydi")


def main() -> None:
    print("=" * 72)
    print("Rasch JMLE avtomatik kalibrlash testi")
    print("=" * 72)
    check_synthetic_recovery()
    check_min_n()
    check_extreme_items()
    print("=" * 72)
    print("Barcha kalibrlash tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    main()
