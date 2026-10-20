"""Phase 6 regressiya: `=` (tenglik) + DEG/RAD wrapper (D2) — real bajarilish.

Muammo: `composeExpression` HAR QANDAY bo'sh bo'lmagan matnni `deg(...)`/`rad(...)`
ga o'raydi; `normalize` esa oxirgi `=` dan keyingisini oladi (`math_expr.py:49-52`,
`mathpanel.js:normalizeExpression`). Natijada `=5` -> `deg(=5)` -> `"5)"` ->
`evaluate = None` (avval `5` edi).

Test HAQIQIY bajariladi: `webapp/js/mathpanel.js` dan `composeExpression` va
`evaluate` (+ bog'liq funksiyalar) ajratilib, `cscript //E:JScript` ostida
ishga tushiriladi va Python `math_expr.evaluate` bilan solishtiriladi.

Ishga tushirish:
    python tests/test_equals_mode.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import math_expr  # noqa: E402
import test_math_panel_eval as ev  # noqa: E402

DRIVER = r'''
function show(name, value) {
  WScript.Echo(name + "=" + (value === null || value === undefined ? "null" : String(value)));
}
show("compose_deg_eq5", composeExpression("=5", "deg"));
show("eval_deg_eq5", evaluate(composeExpression("=5", "deg")));
show("compose_rad_eq5", composeExpression("=5", "rad"));
show("eval_rad_eq5", evaluate(composeExpression("=5", "rad")));
show("compose_deg_eq10", composeExpression("=10", "deg"));
show("eval_deg_eq10", evaluate(composeExpression("=10", "deg")));
show("compose_rad_eq10", composeExpression("=10", "rad"));
show("eval_rad_eq10", evaluate(composeExpression("=10", "rad")));
show("compose_deg_x_eq5", composeExpression("x=5", "deg"));
show("eval_deg_x_eq5", evaluate(composeExpression("x=5", "deg")));
show("compose_rad_x_eq5", composeExpression("x=5", "rad"));
show("eval_rad_x_eq5", evaluate(composeExpression("x=5", "rad")));
show("compose_deg_sin30", composeExpression("sin(30)", "deg"));
show("eval_deg_sin30", evaluate(composeExpression("sin(30)", "deg")));
show("compose_deg_cos60", composeExpression("cos(60)", "deg"));
show("eval_deg_cos60", evaluate(composeExpression("cos(60)", "deg")));
show("compose_rad_sin_pi6", composeExpression("sin(pi/6)", "rad"));
show("eval_rad_sin_pi6", evaluate(composeExpression("sin(pi/6)", "rad")));
show("bare_eq5", evaluate("=5"));
show("bare_x_eq5", evaluate("x=5"));
show("bare_sin30", evaluate("sin(30)"));
show("bare_cos60", evaluate("cos(60)"));
show("compose_deg_plain5", composeExpression("5", "deg"));
'''

EXPECTED_MACHINE = {
    "deg_eq5": "deg(5)",
    "rad_eq5": "rad(5)",
    "deg_eq10": "deg(10)",
    "rad_eq10": "rad(10)",
    "deg_x_eq5": "deg(5)",
    "rad_x_eq5": "rad(5)",
    "deg_sin30": "deg(sin(30))",
    "deg_cos60": "deg(cos(60))",
    "rad_sin_pi6": "rad(sin(pi/6))",
}

EXPECTED_VALUE = {
    "deg_eq5": 5.0,
    "rad_eq5": 5.0,
    "deg_eq10": 10.0,
    "rad_eq10": 10.0,
    "deg_x_eq5": 5.0,
    "rad_x_eq5": 5.0,
    "deg_sin30": 0.5,
    "deg_cos60": 0.5,
    "rad_sin_pi6": 0.5,
}


def build_program() -> str:
    panel = ev.PANEL_JS.read_text(encoding="utf-8")
    parts = [ev.SHIMS]
    parts.append(ev.transpile(ev.extract_function(panel, "composeExpression")))
    for name in ev.FUNCTIONS:
        parts.append(ev.transpile(ev.extract_function(panel, name)))
    parts.append(DRIVER)
    return "\n".join(parts)


def js_float(raw: str | None) -> float | None:
    if raw is None or raw == "null":
        return None
    return float(raw)


def close(actual: float | None, expected: float, label: str) -> None:
    assert actual is not None, "%s: None (kutilgan %r)" % (label, expected)
    assert abs(actual - expected) <= 1e-9, (label, actual, expected)


def check_equals_mode() -> bool:
    """`=` + DEG/RAD: wrapper ham, `=` semantikasi ham ishlashi (JS + Python)."""
    results = ev.run_js(build_program())
    if results is None:
        print("[SKIP] cscript topilmadi - tekshiruv o'tkazildi")
        return False

    print("   case              machine             JS     PY")
    for key, machine in EXPECTED_MACHINE.items():
        compose = results.get("compose_" + key)
        assert compose == machine, (
            "%s: compose kutilgan %r, olingan %r" % (key, machine, compose)
        )
        js_value = js_float(results.get("eval_" + key))
        py_value = math_expr.evaluate(machine)
        close(js_value, EXPECTED_VALUE[key], key + " JS")
        close(py_value, EXPECTED_VALUE[key], key + " PY")
        print("   %-16s %-18s %-6s %s" % (key, machine, js_value, py_value))

    # `=` wrapper'siz (legacy) — avvalgidek ishlaydi.
    close(js_float(results.get("bare_eq5")), 5.0, "bare =5 JS")
    close(js_float(results.get("bare_x_eq5")), 5.0, "bare x=5 JS")
    close(math_expr.evaluate("=5"), 5.0, "bare =5 PY")
    close(math_expr.evaluate("x=5"), 5.0, "bare x=5 PY")
    assert results.get("compose_deg_plain5") == "deg(5)"

    # Trigonometriya DEG/RAD da ishlashda davom etadi.
    close(js_float(results.get("bare_sin30")), math_expr.evaluate("sin(30)"), "bare sin30")
    close(js_float(results.get("bare_cos60")), math_expr.evaluate("cos(60)"), "bare cos60")

    print("[OK] `=` DEG/RAD da: =5 -> 5, =10 -> 10 (JS va Python aynan)")
    print("[OK] sin(30)/cos(60) DEG da 0.5; wrapper'siz radian o'zgarmagan")
    print("[OK] composeExpression JS va Python machine-string bilan mos")
    return True


def main() -> None:
    print("=" * 72)
    print("Phase 6: `=` + DEG/RAD regression (D2) - regressiya")
    print("=" * 72)
    ran = check_equals_mode()
    print("=" * 72)
    if ran:
        print("Barcha tekshiruvlar muvaffaqiyatli o'tdi \u2705")
    else:
        print("Tekshiruv o'tkazildi (cscript yo'q) \u2705")
    print("=" * 72)


if __name__ == "__main__":
    main()
