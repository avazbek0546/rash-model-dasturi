"""Test sifati (`services/test_quality.py`) regressiya testi.

Sintetik javob matritsasi bilan Cronbach α, item statistikasi, EAP
ishonchlilik, SRMSR/M2/RMSEA, Wright va TIF tekshiriladi.

Ishga tushirish:
    python tests/test_test_quality.py
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import test_quality  # noqa: E402

B_VALUES = [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, -0.8, 0.8, 0.2]
LABELS = [str(index) for index in range(1, len(B_VALUES) + 1)]


def make_matrix(participants: int = 120, seed: int = 42) -> tuple[list[list[float]], list[float]]:
    rng = random.Random(seed)
    matrix: list[list[float]] = []
    thetas: list[float] = []
    for _ in range(participants):
        theta = rng.gauss(0.0, 1.0)
        row = [
            1.0
            if rng.random() < 1.0 / (1.0 + math.exp(-(theta - b)))
            else 0.0
            for b in B_VALUES
        ]
        matrix.append(row)
        thetas.append(theta)
    return matrix, thetas


def test_cronbach_alpha() -> None:
    perfect = [[1, 1], [0, 0], [1, 1], [0, 0]]
    alpha = test_quality.cronbach_alpha(perfect)
    assert alpha is not None and abs(alpha - 1.0) < 1e-9, alpha
    assert test_quality.cronbach_alpha([[1], [0]]) is None
    print(f"[OK] Cronbach α: mukammal izchillik = {alpha:.3f}")


def test_residual_fit_and_tif() -> None:
    matrix, thetas = make_matrix()
    fit = test_quality.residual_fit(matrix, thetas, B_VALUES)
    assert set(fit) == {"srmr", "m2", "df", "rmsea", "cfi", "tli", "m2_p"}
    assert fit["srmr"] is not None and fit["srmr"] >= 0
    assert fit["rmsea"] is not None and fit["rmsea"] >= 0
    tif = test_quality.test_information_function(B_VALUES)
    assert len(tif["theta"]) == len(tif["information"])
    assert all(value >= 0 for value in tif["information"])
    print(
        f"[OK] Fit: SRMSR={fit['srmr']:.3f}, RMSEA={fit['rmsea']:.3f}, "
        f"CFI={fit['cfi']}, TLI={fit['tli']}; TIF nuqtalari={len(tif['theta'])}"
    )


def test_wright_map() -> None:
    matrix, thetas = make_matrix(participants=40)
    wright = test_quality.wright_map(thetas, B_VALUES)
    assert len(wright["bins"]) == 20
    assert sum(wright["person_counts"]) == len(thetas)
    assert sum(wright["item_counts"]) == len(B_VALUES)
    print(
        f"[OK] Wright: θ={sum(wright['person_counts'])}, "
        f"item={sum(wright['item_counts'])}, bin=20"
    )


def test_report() -> None:
    matrix, thetas = make_matrix()
    raws = [int(sum(row)) for row in matrix]
    ses = [0.3] * len(matrix)
    report = test_quality.build_quality_report_from_matrix(
        matrix,
        LABELS,
        B_VALUES,
        thetas=thetas,
        standard_errors=ses,
        raw_scores=raws,
        theta_method="eap",
        exam_id=1,
        title="Sintetik test",
        test_code="SYNTH01",
    )
    summary = report["summary"]
    assert summary["participants"] == 120
    assert summary["items"] == 10
    assert summary["cronbach_alpha"] is not None
    assert 0.0 <= summary["cronbach_alpha"] <= 1.0
    assert summary["eap_reliability"] is not None
    assert len(report["items"]) == 10
    for item in report["items"]:
        assert 0.0 <= item["p"] <= 1.0
        assert item["r_pbi"] is None or -1.0 <= item["r_pbi"] <= 1.0
    assert report["metrics_version"] == test_quality.METRICS_VERSION
    print(
        f"[OK] Hisobot: N={summary['participants']}, K={summary['items']}, "
        f"α={summary['cronbach_alpha']:.3f}, EAP={summary['eap_reliability']:.3f}"
    )


def test_report_without_thetas() -> None:
    matrix, _thetas = make_matrix(participants=35, seed=7)
    report = test_quality.build_quality_report_from_matrix(
        matrix, LABELS, B_VALUES, theta_method="eap"
    )
    assert report["summary"]["participants"] == 35
    assert report["summary"]["mean_raw"] is not None
    print("[OK] Hisobot thetasiz ham EAP bilan hisoblandi")


def main() -> int:
    print("=" * 72)
    print("Test sifati regressiya testi")
    print("=" * 72)
    test_cronbach_alpha()
    test_residual_fit_and_tif()
    test_wright_map()
    test_report()
    test_report_without_thetas()
    print("=" * 72)
    print("Barcha test-sifati tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
