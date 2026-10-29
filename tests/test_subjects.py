"""Algebra/geometriya bo'limlari — `services/subjects.py` (sof funksiyalar).

Tekshiriladi:
    1. Har bir pozitsiya (1..45) aynan bitta fanga tegishli (to'qnashuv yo'q);
    2. Chegara: 40 → algebra, 41 → geometriya;
    3. Elementlar bo'yicha: algebra **35**, geometriya **20** (jami 55;
       a/b qismlar alohida element);
    4. `summarize` to'g'ri sonlarni va tartibni qaytaradi.

Ishga tushirish:
    python tests/test_subjects.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from services import subjects  # noqa: E402


def expected_map() -> dict[int, str]:
    """Tasdiqlangan taqsimot (pozitsiya → fan)."""
    result: dict[int, str] = {}
    for position in range(1, 24):  # 1–23
        result[position] = "algebra"
    for position in range(24, 31):  # 24–30
        result[position] = "geometry"
    for position in range(31, 33):  # 31–32
        result[position] = "algebra"
    for position in range(33, 36):  # 33–35
        result[position] = "geometry"
    for position in range(36, 41):  # 36–40
        result[position] = "algebra"
    for position in range(41, 46):  # 41–45
        result[position] = "geometry"
    return result


def check_ranges() -> None:
    """Har bir pozitsiya aynan bitta fanga tegishli (to'qnashuv yo'q)."""
    expected = expected_map()
    assert len(expected) == 45, len(expected)
    for position, code in expected.items():
        got = subjects.subject_of_position(position)
        assert got == code, (position, got, code)

    # Chegara: 40 → algebra, 41 → geometriya (tasdiqlangan qaror)
    assert subjects.subject_of_position(40) == "algebra"
    assert subjects.subject_of_position(41) == "geometry"
    # Oraliqdan tashqari pozitsiyalar — fansiz
    assert subjects.subject_of_position(0) is None
    assert subjects.subject_of_position(46) is None
    # Fan tartibi (hisobotda ham shu tartib)
    assert subjects.subject_codes() == ["algebra", "geometry"]
    print(
        "[OK] Oraliqlar: 1–23,31–32,36–40 algebra / 24–30,33–35,41–45 geometriya"
    )


def check_summarize() -> None:
    """Elementlar bo'yicha jamlanma (a/b qismlar alohida)."""
    # 45 pozitsiya; 36–45 da ikkita qism (a, b) → jami 55 element
    items: list[tuple[int, bool]] = []
    for position in range(1, 46):
        parts = ("a", "b") if position >= 36 else ("",)
        for _part in parts:
            items.append((position, True))

    summary = subjects.summarize(items)
    by_code = {row["code"]: row for row in summary}
    assert by_code["algebra"]["total"] == 35, by_code
    assert by_code["geometry"]["total"] == 20, by_code
    assert by_code["algebra"]["correct"] == 35
    assert by_code["geometry"]["correct"] == 20
    assert sum(row["total"] for row in summary) == 55
    assert [row["code"] for row in summary] == ["algebra", "geometry"]
    assert by_code["algebra"]["label"] == "Algebra"
    assert by_code["geometry"]["label"] == "Geometriya"

    # 36 va 41 pozitsiyalari xato → algebra 33/35, geometriya 18/20
    mixed = [
        (position, position not in (36, 41)) for position, _is_correct in items
    ]
    by_mixed = {row["code"]: row for row in subjects.summarize(mixed)}
    assert by_mixed["algebra"] == {
        "code": "algebra",
        "label": "Algebra",
        "correct": 33,
        "total": 35,
    }, by_mixed
    assert by_mixed["geometry"] == {
        "code": "geometry",
        "label": "Geometriya",
        "correct": 18,
        "total": 20,
    }, by_mixed

    # Oraliqqa tushmagan pozitsiya e'tiborga olinmaydi
    empty = subjects.summarize([(99, True), (0, True)])
    assert all(row["total"] == 0 for row in empty), empty
    print("[OK] Jamlanma: algebra 35 element, geometriya 20 element (jami 55)")


def check_scaled_scores() -> None:
    """Fan bo'yicha Rasch ballari (0–100; foiz emas)."""
    items = []
    for position in range(1, 46):
        parts = ("a", "b") if position >= 36 else ("",)
        for _part in parts:
            items.append((position, True, 0.0))

    scores = subjects.scaled_scores(items)
    assert set(scores) == {"algebra", "geometry"}, scores
    # Hammasi to'g'ri → har bir fan uchun ham yuqori cap (91.0).
    assert abs(float(scores["algebra"]) - config.SCALED_CAP_MAX) < 1e-6, scores
    assert abs(float(scores["geometry"]) - config.SCALED_CAP_MAX) < 1e-6, scores

    mixed = [
        (position, position not in (36, 41), 0.0)
        for position, _is_correct, _difficulty in items
    ]
    mixed_scores = subjects.scaled_scores(mixed)
    for code, score in mixed_scores.items():
        assert score is not None, (code, mixed_scores)
        assert config.SCALED_CAP_MIN <= score <= config.SCALED_CAP_MAX, (
            code,
            score,
        )

    empty = subjects.scaled_scores([])
    assert empty == {"algebra": None, "geometry": None}, empty
    print("[OK] Fan ballari: Rasch bo'yicha 0–100 (foiz emas), bo'sh — None")


def main() -> None:
    print("=" * 72)
    print("Algebra / geometriya bo'limlari testi (services/subjects.py)")
    print("=" * 72)
    check_ranges()
    check_summarize()
    check_scaled_scores()
    print("=" * 72)
    print("Barcha subject tekshiruvlari muvaffaqiyatli o'tdi ✅")
    print("=" * 72)


if __name__ == "__main__":
    main()
