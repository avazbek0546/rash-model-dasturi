"""Phase 6 regressiya: DEG/RAD burchak rejimi (`services/math_expr.py`).

`deg(...)` ichida trig burchak **gradusda**, `rad(...)` ichida **radian**;
wrapper'siz (legacy) ifoda avvalgidek radian. Rejim ifoda MATNIDA saqlanadi —
shu sababli JS va Python bir xil hisoblaydi (yashirin holat yo'q).

Ishga tushirish:
    python tests/test_degree_mode.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import math_expr  # noqa: E402

PI = math.pi


def v(expression: str) -> float | None:
    return math_expr.evaluate(expression)


def close(actual: float | None, expected: float, *, tol: float = 1e-9) -> None:
    assert actual is not None, f"None qaytardi (kutilgan {expected})"
    assert abs(actual - expected) <= tol, (actual, expected)


def check_deg() -> None:
    """DEG: sin(30)=0.5, cos(60)=0.5, tg(45)=1; teskari funksiyalar gradusda."""
    close(v("deg(sin(30))"), 0.5)
    close(v("deg(cos(60))"), 0.5)
    close(v("deg(tg(45))"), 1.0)
    close(v("deg(ctg(45))"), 1.0)
    close(v("deg(arcsin(0.5))"), 30.0)
    close(v("deg(arccos(0.5))"), 60.0)
    close(v("deg(arctg(1))"), 45.0)
    close(v("deg(arcctg(1))"), 45.0)
    close(v("deg(2sin(30))"), 1.0)
    print("[OK] DEG: sin30=0.5, cos60=0.5, tg45=1, ctg45=1, arcsin0.5=30")


def check_rad() -> None:
    """RAD: sin(pi/6)=0.5, cos(pi/3)=0.5, tg(pi/4)=1; teskari funksiyalar radian."""
    close(v("rad(sin(pi/6))"), 0.5)
    close(v("rad(cos(pi/3))"), 0.5)
    close(v("rad(tg(pi/4))"), 1.0)
    close(v("rad(ctg(pi/4))"), 1.0)
    close(v("rad(arcsin(0.5))"), PI / 6)
    close(v("rad(arccos(0.5))"), PI / 3)
    close(v("rad(arctg(1))"), PI / 4)
    close(v("rad(arcctg(1))"), PI / 4)
    close(v("rad(2sin(pi/6))"), 1.0)
    print("[OK] RAD: sin(pi/6)=0.5, cos(pi/3)=0.5, tg(pi/4)=1, arcsin0.5=pi/6")


def check_scope() -> None:
    """Rejim faqat wrapper ICHIDA; tashqarisi (legacy) radian bo'lib qoladi."""
    close(v("deg(sin(30)+sin(30))"), 1.0)
    close(v("deg(sin(30))+rad(sin(pi/6))"), 1.0)
    close(v("rad(sin(pi/6))+deg(cos(60))"), 1.0)
    close(v("sin(30)+deg(sin(30))"), math.sin(30) + 0.5)
    print("[OK] scope: rejim wrapper ichida; aralash ifoda to'g'ri")


def check_functions_still_work() -> None:
    """log_a(b), lg, ln DEG/RAD qo'shilgach ham ishlaydi."""
    close(v("log_2(8)"), 3.0)
    close(v("log_3(9)"), 2.0)
    close(v("lg(100)"), 2.0)
    close(v("ln(1)"), 0.0)
    close(v("log(1000)"), 3.0)
    close(v("deg(lg(100))"), 2.0)
    print("[OK] log_a(b), lg, ln (DEG/RAD ichida ham) ishlaydi")


def check_legacy_unchanged() -> None:
    """Wrapper'siz ifoda — avvalgidek radian (legacy buzilmagan)."""
    close(v("sin(pi/2)"), 1.0)
    close(v("cos(0)"), 1.0)
    close(v("sin(30)"), math.sin(30))
    close(v("3/7"), 3 / 7)
    close(v("sqrt5"), math.sqrt(5))
    close(v("2pi"), 2 * PI)
    close(v("50%"), 0.5)
    close(v("12,5"), 12.5)
    print("[OK] legacy: wrapper'siz ifoda radian — o'zgarmadi")


def check_determinism() -> None:
    """Bir xil matn -> bir xil natija; rejim natijaga real ta'sir qiladi."""
    assert v("deg(sin(30))") == v("deg(sin(30))")
    assert v("deg(sin(30))") != v("rad(sin(30))")
    assert v("rad(sin(30))") == v("sin(30)")
    print("[OK] determinizm: bir xil matn bir xil natija; rejim ta'sir qiladi")


def check_invalid() -> None:
    """Buzuq rejim yozuvlari -> None (jim xato emas)."""
    assert v("deg") is None
    assert v("rad") is None
    assert v("deg sin(30)") is None
    assert v("rad(deg)") is None
    print("[OK] buzuq rejim yozuvlari -> None")


def main() -> None:
    print("=" * 72)
    print("Phase 6: DEG/RAD burchak rejimi - regressiya")
    print("=" * 72)
    check_deg()
    check_rad()
    check_scope()
    check_functions_still_work()
    check_legacy_unchanged()
    check_determinism()
    check_invalid()
    print("=" * 72)
    print("Barcha tekshiruvlar muvaffaqiyatli o'tdi \u2705")
    print("=" * 72)


if __name__ == "__main__":
    main()
