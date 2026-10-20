"""Phase 4 regressiya testi: matematik panel funksiyalari (trig/log).

Tekshiriladi
------------
    1. `services/math_expr.evaluate`: `sin, cos, tg, ctg, arcsin, arccos,
       arctg, arcctg, lg, ln, log` (burchak radianlarda) to'g'ri hisoblaydi.
    2. `log_a(b)` yozuvi `log(b)/log(a)` ga **xavfsiz** (muvozanatli qavs
       skani) o'giriladi — nested va ifodali argument bilan ham.
    3. Yashirin ko'paytma: `2sin(...)`, `3cos(...)`, `4ln(...)`, `5lg(...)`.
    4. Kalit parseri (`form_layout.parse_labeled_key`) yangi funksiyalarni
       qabul qiladi (u `math_expr.evaluate` dan foydalanadi).
    5. Aniqlanish sohasidan tashqari qiymatlar `None` (jim xato emas).
    6. Legacy ifodalar (yangi tokenlarsiz) **o'zgarmagan**.
    7. JS (`mathpanel.js`) va Python (`math_expr.py`) parserlari funksiya
       nomlari bo'yicha sinxron (statik parity tekshiruvi).

Ishga tushirish:
    python tests/test_math_functions.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import form_layout, math_expr  # noqa: E402

TOTAL = 45
PI = math.pi
FUNCTIONS = (
    "sin",
    "cos",
    "tg",
    "ctg",
    "arcsin",
    "arccos",
    "arctg",
    "arcctg",
    "lg",
    "ln",
    "log",
)


def value(expression: str) -> float | None:
    return math_expr.evaluate(expression)


def close(actual: float | None, expected: float, *, tol: float = 1e-9) -> None:
    assert actual is not None, f"None qaytardi (kutilgan {expected})"
    assert abs(actual - expected) <= tol, (actual, expected)


def check_single_argument() -> None:
    """1-qadam: bitta argumentli funksiyalar (radian)."""
    close(value("sin(pi/2)"), 1.0)
    close(value("sin(0)"), 0.0)
    close(value("cos(0)"), 1.0)
    close(value("cos(pi)"), -1.0)
    close(value("tg(pi/4)"), 1.0)
    close(value("ctg(pi/4)"), 1.0)
    close(value("arcsin(1)"), PI / 2)
    close(value("arccos(0)"), PI / 2)
    close(value("arctg(1)"), PI / 4)
    close(value("arcctg(1)"), PI / 4)
    close(value("lg(100)"), 2.0)
    close(value("lg(1000)"), 3.0)
    close(value("ln(1)"), 0.0)
    close(value("log(100)"), 2.0)
    # Qavssiz prefiks yozuv ham ishlaydi (sqrt kabi).
    close(value("sin0"), 0.0)
    close(value("lg100"), 2.0)
    close(value("arctg1"), PI / 4)
    print("[OK] bitta argumentli: sin cos tg ctg arcsin arccos arctg arcctg lg ln log")


def check_implicit_multiplication() -> None:
    """2-qadam: yashirin ko'paytma (2sin, 3cos, 4ln, 5lg)."""
    close(value("2sin(pi/2)"), 2.0)
    close(value("3cos(0)"), 3.0)
    close(value("4ln(1)"), 0.0)
    close(value("5lg(100)"), 10.0)
    close(value("2arctg(1)"), PI / 2)
    close(value("2pi"), 2 * PI)  # legacy
    close(value("3(4)"), 12.0)  # legacy
    print("[OK] yashirin ko'paytma: 2sin 3cos 4ln 5lg 2arctg (+ legacy 2pi, 3(4))")


def check_base_log() -> None:
    """3-qadam: log_a(b) -> log(b)/log(a) xavfsiz transformatsiya."""
    close(value("log_2(8)"), 3.0)
    close(value("log_3(9)"), 2.0)
    close(value("log_10(1000)"), 3.0)
    close(value("log_2(8)^2"), 9.0)
    close(value("2log_2(8)"), 6.0)
    close(value("log_5(25)+1"), 3.0)
    close(value("log_2(log_2(4))"), 1.0)  # nested
    close(value("log_2(8+0)"), 3.0)  # qavs ichida ifoda
    close(value("log_2(4)*log_2(8)"), 6.0)
    close(value("log_2(8"), 3.0)  # yopilmagan qavs (balance kabi)
    assert value("log_x(8)") is None  # asos raqam emas -> tegilmaydi
    print("[OK] log_a(b): log_2(8)=3, nested, ifodali argument, yopilmagan qavs")


def check_equivalence() -> None:
    """4-qadam: ekvivalentlik yangi funksiyalar bilan."""
    assert math_expr.equivalent("log_2(8)", 3)
    assert math_expr.equivalent("2sin(pi/2)", "2*sin(pi/2)")
    assert math_expr.equivalent("lg100", "2")
    assert math_expr.equivalent("ctg(pi/4)", "tg(pi/4)")
    assert not math_expr.equivalent("sin(pi/2)", "0.9")
    print("[OK] equivalent: log_2(8)==3, 2sin(pi/2)==2*sin(pi/2), ctg==tg")


def check_domain_errors() -> None:
    """5-qadam: aniqlanish sohasidan tashqari -> None."""
    for bad in (
        "lg(0)",
        "lg(-1)",
        "ln(-1)",
        "arcsin(2)",
        "arccos(2)",
        "log_2(0)",
        "ctg(0)",
        "sqrt(-1)",
    ):
        assert value(bad) is None, bad
    print("[OK] soha xatolari: lg(0), ln(-1), arcsin(2), ctg(0), sqrt(-1) -> None")


def check_key_parser() -> None:
    """6-qadam: kalit parseri yangi funksiyalarni qabul qiladi."""
    letters = "".join(
        f"{position}{('ABCD' if position <= 32 else 'ABCDEF')[(position - 1) % (4 if position <= 32 else 6)]}"
        for position in range(1, 36)
    )
    key = (
        letters
        + "|36a:log_2(8),36b:sin(pi/6),37a:lg100,37b:ctg(pi/4),38a:arctg(1)"
    )
    assert form_layout.is_labeled_key(key)
    _letters, values = form_layout.parse_labeled_key(key, TOTAL)
    close(values["36a"], 3.0)
    close(values["36b"], 0.5)
    close(values["37a"], 2.0)
    close(values["37b"], 1.0)
    close(values["38a"], PI / 4)
    print("[OK] parse_labeled_key: kalitda sin/lg/log_2/ctg/arctg o'qildi")


def check_legacy_unchanged() -> None:
    """7-qadam: legacy ifodalar o'zgarmagan."""
    close(value("\u221a5"), math.sqrt(5))
    close(value("\u221b8"), 2.0)
    close(value("3/7"), 3 / 7)
    close(value("\u03c0/2"), PI / 2)
    close(value("|3-8|"), 5.0)
    close(value("(1+2)*3"), 9.0)
    close(value("2^3"), 8.0)
    close(value("2^3^2"), 512.0)
    close(value("-2^2"), -4.0)
    close(value("12,5"), 12.5)
    close(value("50%"), 0.5)
    close(value("(\u221a20)/2"), math.sqrt(20) / 2)
    close(value("x=5"), 5.0)
    assert math_expr.equivalent("\u221a5", "(\u221a20)/2")
    assert math_expr.equivalent("3/7", "6/14")
    print("[OK] legacy: \u221a \u221b / \u03c0 |x| qavslar ^ % vergul — o'zgarmadi")


def check_parser_parity() -> None:
    """8-qadam: JS va Python parserlari funksiya nomlari bo'yicha sinxron."""
    root = Path(__file__).resolve().parent.parent
    js = (root / "webapp" / "js" / "mathpanel.js").read_text(encoding="utf-8")
    py = (root / "services" / "math_expr.py").read_text(encoding="utf-8")
    for name in FUNCTIONS:
        assert f'startsWith("{name}")' in js, f"JS da yo'q: {name}"
        assert f'_starts("{name}")' in py, f"PY da yo'q: {name}"
    assert "expandBaseLog" in js and "expandBaseLogOnce" in js
    assert "_expand_base_log" in py and "_expand_base_log_once" in py
    assert 'insert: "log_"' in js
    print("[OK] parser parity: funksiya nomlari JS va PY da sinxron")


def main() -> None:
    print("=" * 72)
    print("Phase 4: matematik panel funksiyalari (trig/log) — regressiya")
    print("=" * 72)
    check_single_argument()
    check_implicit_multiplication()
    check_base_log()
    check_equivalence()
    check_domain_errors()
    check_key_parser()
    check_legacy_unchanged()
    check_parser_parity()
    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi \u2705")
    print("=" * 72)


if __name__ == "__main__":
    main()
