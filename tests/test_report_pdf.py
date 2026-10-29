"""PDF hisobot (`services/report_pdf.py`) testlari.

Ishga tushirish:
    python tests/test_report_pdf.py            # pytest kerak emas
    python -m pytest tests/test_report_pdf.py  # pytest o'rnatilgan bo'lsa

Tekshiriladi:
    1. Repodagi `assets/fonts/DejaVuSans.ttf` mavjud va `resolve_font()` aynan
       shu faylni qaytaradi — shu tufayli PDF Railway (Linux) konteynerida ham
       ishlaydi (ilgari faqat Windows shriftlariga tayanardi va
       «Unicode shrift topilmadi» xatosi chiqardi);
    2. `build_results_pdf()` haqiqiy PDF (`%PDF`) qaytaradi;
    3. Bo'sh ro'yxat ham yaroqli PDF beradi;
    4. Shrift umuman bo'lmasa — aniq `ReportError` (jimgina buzuq PDF emas).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from services import report_pdf  # noqa: E402

#: Repo bilan birga keladigan shrift (birinchi nomzod).
BUNDLED_FONT = config.BASE_DIR / "assets" / "fonts" / "DejaVuSans.ttf"

STUDENTS = [
    report_pdf.StudentRow(
        name="Aliyev Vali",
        theta=1.24,
        level="A",
        algebra=81.2,
        geometry=75.5,
        correct=31,
        total=45,
    ),
    report_pdf.StudentRow(
        name="Karimova Dilnoza",
        theta=-0.62,
        level="NC",
        algebra=None,
        geometry=None,
        correct=12,
        total=45,
    ),
]


def test_bundled_font_exists() -> None:
    """Shrift repoda bo'lishi shart — aks holda Railway'da PDF yasalmasdi."""
    assert BUNDLED_FONT.is_file(), f"Shrift topilmadi: {BUNDLED_FONT}"
    assert BUNDLED_FONT.stat().st_size > 100_000
    print(f"[OK] Repodagi shrift mavjud: {BUNDLED_FONT.name} ({BUNDLED_FONT.stat().st_size} bayt)")


def test_resolve_font_prefers_bundled() -> None:
    """`resolve_font()` tizim shriftidan oldin repodagi shriftni tanlaydi."""
    report_pdf.resolve_font.cache_clear()
    font = report_pdf.resolve_font()
    assert font.is_file(), font
    assert font == BUNDLED_FONT, f"Repodagi shrift o'rniga tanlandi: {font}"
    print(f"[OK] resolve_font() → {font}")


def test_build_results_pdf() -> None:
    """Hisobot haqiqiy PDF (rangli jadval + diagramma) bo'lib qaytadi."""
    data = report_pdf.build_results_pdf(
        title="Matematika — nazorat ishi",
        test_code="MATH2026",
        date_text="29-oktabr 2026",
        participants=len(STUDENTS),
        students=STUDENTS,
    )
    assert data[:4] == b"%PDF", data[:8]
    assert len(data) > 5000, len(data)
    print(f"[OK] PDF yasaldi: {len(data)} bayt (2 o'quvchi)")


def test_empty_report() -> None:
    """Natija yo'q bo'lsa ham PDF yasaladi (`Hozircha natija yo'q`)."""
    data = report_pdf.build_results_pdf(
        title="Bo'sh imtihon",
        test_code="EMPTY01",
        date_text="—",
        participants=0,
        students=[],
    )
    assert data[:4] == b"%PDF", data[:8]
    assert len(data) > 2000, len(data)
    print(f"[OK] Bo'sh hisobot ham yaroqli PDF: {len(data)} bayt")


def test_missing_font_raises() -> None:
    """Shrift umuman bo'lmasa — `ReportError` (buzuq PDF yasalmaydi)."""
    original = report_pdf.FONT_CANDIDATES
    report_pdf.FONT_CANDIDATES = (Path("Z:/definitely-missing/DejaVuSans.ttf"),)
    report_pdf.resolve_font.cache_clear()
    try:
        try:
            report_pdf.resolve_font()
        except report_pdf.ReportError as exc:
            message = str(exc)
            assert "assets/fonts/DejaVuSans.ttf" in message, message
        else:  # pragma: no cover - faqat regressiyada
            raise AssertionError("Shrift yo'q bo'lsa `ReportError` kutilgan edi")
    finally:
        report_pdf.FONT_CANDIDATES = original
        report_pdf.resolve_font.cache_clear()
    print("[OK] Shrift yo'q bo'lsa — aniq ReportError (buzuq PDF emas)")


def main() -> int:
    tests = [
        test_bundled_font_exists,
        test_resolve_font_prefers_bundled,
        test_build_results_pdf,
        test_empty_report,
        test_missing_font_raises,
    ]
    print("=" * 72)
    print("PDF hisobot (shrift + jadval) — o'z-o'zini tekshirish testlari")
    print("=" * 72)
    for test in tests:
        test()
    print("=" * 72)
    print(f"Barcha {len(tests)} ta test muvaffaqiyatli o'tdi ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
