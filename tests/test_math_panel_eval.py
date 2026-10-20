"""Phase 6 regressiya: JS `evaluate` HAQIQIY bajarilishi (cscript / JScript).

Node.js bu muhitda yo'q. Shuning uchun `webapp/js/mathpanel.js` dan `evaluate`
bilan bog'liq funksiyalar **ajratib olinadi**, kichik moslashtiriladi va
`cscript //E:JScript` ostida **haqiqatan bajariladi**; natijalar Python
`math_expr.evaluate` bilan aynan solishtiriladi. Bu statik qator-qidirish EMAS.

Moslashtirish (faqat TEST tomonida; manba o'zgarmaydi):
    `const`/`let` → `var`;  `text[i]` → `text.charAt(i)`;
    shimlar: String.startsWith / String.repeat / Number.isFinite /
             Math.log10 / Math.cbrt.

Ishga tushirish:
    python tests/test_math_panel_eval.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import math_expr  # noqa: E402

PANEL_JS = ROOT / "webapp" / "js" / "mathpanel.js"

FUNCTIONS = (
    "normalizeExpression",
    "balanceParentheses",
    "acot",
    "expandBaseLogOnce",
    "expandBaseLog",
    "evaluate",
)

EXPRESSIONS = [
    # DEG
    "deg(sin(30))", "deg(cos(60))", "deg(tg(45))", "deg(ctg(45))",
    "deg(arcsin(0.5))", "deg(arccos(0.5))", "deg(arctg(1))", "deg(arcctg(1))",
    "deg(2sin(30))",
    # RAD
    "rad(sin(pi/6))", "rad(cos(pi/3))", "rad(tg(pi/4))", "rad(ctg(pi/4))",
    "rad(arcsin(0.5))", "rad(arccos(0.5))", "rad(arctg(1))", "rad(arcctg(1))",
    "deg(sin(30))+rad(sin(pi/6))",
    # wrapper'siz (legacy radian)
    "sin(pi/2)", "cos(0)", "sin(30)", "tg(pi/4)",
    # log/lg/ln + log_a(b)
    "log_2(8)", "log_3(9)", "lg(100)", "ln(1)", "log(1000)",
    # legacy umuman
    "3/7", "sqrt5", "cbrt8", "2pi", "(1+2)*3", "50%", "12,5", "|3-8|",
    "2^3^2", "-2^2", "sqrt(20)/2",
]

SHIMS = r'''
if (typeof String.prototype.startsWith !== "function") {
  String.prototype.startsWith = function (word, position) {
    var at = (position === undefined || position === null) ? 0 : position;
    return this.substr(at, word.length) === word;
  };
}
if (typeof String.prototype.repeat !== "function") {
  String.prototype.repeat = function (count) {
    var out = "";
    for (var i = 0; i < count; i += 1) { out += this; }
    return out;
  };
}
if (typeof Number.isFinite !== "function") {
  Number.isFinite = function (value) {
    return typeof value === "number" && isFinite(value);
  };
}
if (typeof Math.log10 !== "function") {
  Math.log10 = function (value) { return Math.log(value) / Math.LN10; };
}
if (typeof Math.cbrt !== "function") {
  Math.cbrt = function (value) {
    return value < 0 ? -Math.pow(-value, 1 / 3) : Math.pow(value, 1 / 3);
  };
}
'''


def extract_function(source: str, name: str) -> str:
    """`function <name>(` dan mos yopiluvchi `}` gacha (qavs hisobi bilan)."""
    start = source.index("function " + name + "(")
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError("yopilmagan funksiya: " + name)


def transpile(js: str) -> str:
    """ES6 → JScript mos: const/let → var; text[i] → text.charAt(i)."""
    js = re.sub(r"\bconst\b", "var", js)
    js = re.sub(r"\blet\b", "var", js)
    js = re.sub(r"\btext\[([^\[\]]+)\]", r"text.charAt(\1)", js)
    return js


def js_string(value: str) -> str:
    """ASCII-xavfsiz JS satr literali."""
    out = ['"']
    for char in value:
        code = ord(char)
        if 32 <= code < 127 and char not in ('"', "\\"):
            out.append(char)
        else:
            out.append("\\u%04x" % code)
    out.append('"')
    return "".join(out)


def build_program() -> str:
    """Ajratilgan JS funksiyalar + shimlar + sinov drayveri."""
    source = PANEL_JS.read_text(encoding="utf-8")
    lines = [SHIMS]
    for name in FUNCTIONS:
        lines.append(transpile(extract_function(source, name)))
    lines.append(
        'function show(name, value) { '
        'WScript.Echo(name + "=" + (value === null ? "null" : String(value))); }'
    )
    for index, expression in enumerate(EXPRESSIONS):
        lines.append('show("e%d", evaluate(%s));' % (index, js_string(expression)))
    return "\n".join(lines)


def run_js(program: str) -> dict[str, str] | None:
    """JS ni `cscript` orqali bajaradi; `{nom: qiymat}` (qiymat: "null"|son)."""
    cscript = shutil.which("cscript") or shutil.which("cscript.exe")
    if not cscript:
        return None
    ascii_source = program.encode("ascii", "replace").decode("ascii")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "eval_harness.js"
        harness.write_text(ascii_source, encoding="ascii")
        completed = subprocess.run(
            [cscript, "//nologo", "//E:JScript", str(harness)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    results: dict[str, str] = {}
    for line in (completed.stdout or "").splitlines():
        line = line.strip()
        if "=" in line:
            name, value = line.split("=", 1)
            results[name] = value
    return results


def check_js_matches_python() -> bool:
    """JS `evaluate` (cscript) natijalari Python `math_expr` bilan aynan mos."""
    results = run_js(build_program())
    if results is None:
        print("[SKIP] cscript topilmadi - JS evaluate tekshiruvi o'tkazildi")
        return False
    checked = 0
    for index, expression in enumerate(EXPRESSIONS):
        raw = results.get("e%d" % index)
        assert raw is not None, ("JS javobi yo'q", expression)
        js_value = None if raw == "null" else float(raw)
        py_value = math_expr.evaluate(expression)
        if py_value is None:
            assert js_value is None, (expression, js_value)
        else:
            assert js_value is not None, (expression, raw, py_value)
            assert abs(js_value - py_value) <= 1e-9, (expression, js_value, py_value)
        checked += 1
    print(
        "[OK] JS evaluate cscript'da BAJARILDI: %d ifoda Python bilan aynan mos"
        % checked
    )
    return True


def main() -> None:
    print("=" * 72)
    print("Phase 6: JS evaluate haqiqiy bajarilishi (cscript) - regressiya")
    print("=" * 72)
    ran = check_js_matches_python()
    print("=" * 72)
    if ran:
        print("Barcha tekshiruvlar muvaffaqiyatli o'tdi \u2705")
    else:
        print("JS tekshiruvi o'tkazildi (cscript yo'q) \u2705")
    print("=" * 72)


if __name__ == "__main__":
    main()
