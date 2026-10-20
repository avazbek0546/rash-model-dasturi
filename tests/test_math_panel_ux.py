"""Phase 5 regressiya testi: matematik panel UX (caret, kasr, renderer).

JS qismi HAQIQIY ishga tushiriladi: `webapp/js/mathpanel.js` ichidagi
`[PURE-BEGIN] … [PURE-END]` bloki ajratilib, sinov drayveri bilan birlashtirilib
`cscript //E:JScript` (Windows Script Host) ostida bajariladi. Node.js kerak
emas. Agar `cscript` bo'lmasa — JS tekshiruvlari o'tkazib yuboriladi (Python
tekshiruvlari baribir bajariladi).

Tekshiriladi
------------
    JS (haqiqiy bajarish):
      1. Caret insert   — token caret joyiga qo'yiladi.
      2. Caret backspace— caret CHAPIDAGI belgi o'chadi.
      3. Caret delete   — caret O'NGIDAGI belgi o'chadi.
      4. Kasr konstruktori — machine-string `(surat)/(maxraj)`.
      5. Renderer kasr  — `(3)/(7)` → m-frac/m-num/m-den.
      6. Renderer daraja— `x^2` → `x<sup>2</sup>`.
      7. Renderer ildiz — `sqrt(x)`/`√5`/`cbrt(8)`.
      8. Legacy         — `3/7`, `2sin(pi/2)` o'zgarishsiz; XSS escape.

    Simlar (statik): panel/lib/HTML/CSS ulanishi.
    Python (regressiya): `sin`/`log_a(b)` hali ishlaydi (parser tegilgan emas).

Ishga tushirish:
    python tests/test_math_panel_ux.py
"""

from __future__ import annotations

import codecs
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
QUEUE_JS = ROOT / "webapp" / "js" / "queue.js"
INDEX_HTML = ROOT / "webapp" / "index.html"
STYLE_CSS = ROOT / "webapp" / "css" / "style.css"

PURE_BEGIN = "// --- [PURE-BEGIN]"
PURE_END = "// --- [PURE-END]"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_pure(source: str) -> str:
    """`[PURE-BEGIN] … [PURE-END]` blokini ajratadi."""
    start = source.index(PURE_BEGIN)
    end = source.index(PURE_END) + len(PURE_END)
    return source[start:end]


ENC_HELPER = r'''
function enc(value) {
  var text = String(value == null ? "" : value);
  var out = "";
  for (var i = 0; i < text.length; i += 1) {
    var code = text.charCodeAt(i);
    if (code > 126 || code < 32) {
      var hex = code.toString(16);
      while (hex.length < 4) { hex = "0" + hex; }
      out += "\\u" + hex;
    } else {
      out += text.charAt(i);
    }
  }
  return out;
}
function show(name, value) { WScript.Echo(name + "=" + enc(value)); }
'''

CASES = [
    # 1. Caret insert
    ("insert_mid_text", 'insertAt("12", 1, "0").text'),
    ("insert_mid_caret", 'insertAt("12", 1, "0").caret'),
    ("insert_empty_text", 'insertAt("", 0, "sin").text'),
    ("insert_empty_caret", 'insertAt("", 0, "sin").caret'),
    ("insert_clamp_text", 'insertAt("ab", 5, "x").text'),
    ("insert_clamp_caret", 'insertAt("ab", 5, "x").caret'),
    # 2. Caret backspace
    ("bs_mid_text", 'deleteBefore("123", 2).text'),
    ("bs_mid_caret", 'deleteBefore("123", 2).caret'),
    ("bs_start_text", 'deleteBefore("123", 0).text'),
    ("bs_start_caret", 'deleteBefore("123", 0).caret'),
    # 3. Caret delete
    ("del_mid_text", 'deleteAt("123", 1).text'),
    ("del_mid_caret", 'deleteAt("123", 1).caret'),
    ("del_end_text", 'deleteAt("123", 3).text'),
    ("del_end_caret", 'deleteAt("123", 3).caret'),
    # 4. Fraction constructor
    ("frac_plain", 'buildFraction("3", "7")'),
    ("frac_trim", 'buildFraction(" x ", "y")'),
    ("frac_empty", 'buildFraction("", "")'),
    # 5. Renderer fraction
    ("render_frac", 'renderExpression("(3)/(7)")'),
    # 6. Renderer exponent
    ("render_pow", 'renderExpression("x^2")'),
    ("render_pow_group", 'renderExpression("x^(2)")'),
    # 7. Renderer root
    ("render_sqrt", 'renderExpression("sqrt(x)")'),
    ("render_sqrt_sym", 'renderExpression("\\u221A5")'),
    ("render_cbrt", 'renderExpression("cbrt(8)")'),
    # 8. Legacy / escape
    ("render_legacy_frac", 'renderExpression("3/7")'),
    ("render_legacy_sin", 'renderExpression("2sin(pi/2)")'),
    ("render_escape", 'renderExpression("<b>")'),
]


def build_harness(pure: str, cases: list[tuple[str, str]]) -> str:
    lines = [pure, "", ENC_HELPER, ""]
    for name, expression in cases:
        lines.append('show("%s", %s);' % (name, expression))
    return "\n".join(lines)


def run_js(js_source: str) -> dict[str, str] | None:
    """JS ni `cscript` orqali bajaradi; natija `{nom: qiymat}`."""
    cscript = shutil.which("cscript") or shutil.which("cscript.exe")
    if not cscript:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        # cscript faylni ANSI o'qiydi; PURE bloki matni ASCII (kodda faqat
        # `\uXXXX` escape'lar ishlatiladi) — shu sababli xavfsiz tozalaymiz.
        ascii_source = js_source.encode("ascii", "replace").decode("ascii")
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
            results[name] = codecs.decode(value, "unicode_escape")
    return results


EXPECTED = {
    # 1. Caret insert
    "insert_mid_text": "102",
    "insert_mid_caret": "2",
    "insert_empty_text": "sin",
    "insert_empty_caret": "3",
    "insert_clamp_text": "abx",
    "insert_clamp_caret": "3",
    # 2. Caret backspace
    "bs_mid_text": "13",
    "bs_mid_caret": "1",
    "bs_start_text": "123",
    "bs_start_caret": "0",
    # 3. Caret delete
    "del_mid_text": "13",
    "del_mid_caret": "1",
    "del_end_text": "123",
    "del_end_caret": "3",
    # 4. Fraction constructor
    "frac_plain": "(3)/(7)",
    "frac_trim": "(x)/(y)",
    "frac_empty": "",
    # 5. Renderer fraction
    "render_frac": (
        '<span class="m-frac"><span class="m-num">3</span>'
        '<span class="m-den">7</span></span>'
    ),
    # 6. Renderer exponent
    "render_pow": "x<sup>2</sup>",
    "render_pow_group": "x<sup>2</sup>",
    # 7. Renderer root
    "render_sqrt": "\u221A<span class=\"m-root\">x</span>",
    "render_sqrt_sym": "\u221A<span class=\"m-root\">5</span>",
    "render_cbrt": "\u221B<span class=\"m-root\">8</span>",
    # 8. Legacy / escape
    "render_legacy_frac": "3/7",
    "render_legacy_sin": "2sin(pi/2)",
    "render_escape": "&lt;b&gt;",
}


def check_js() -> bool:
    """1-8: caret, kasr va renderer JS da HAQIQIY bajariladi."""
    pure = extract_pure(read_text(PANEL_JS))
    results = run_js(build_harness(pure, CASES))
    if results is None:
        print("[SKIP] cscript topilmadi - JS tekshiruvlari o'tkazib yuborildi")
        return False
    for name, expected in EXPECTED.items():
        got = results.get(name)
        assert got == expected, (name, got, expected)
    print("[OK] JS (cscript): caret insert/backspace/delete, kasr, renderer, legacy")
    return True


def check_wiring() -> None:
    """Ulanish (statik): panel -> queue -> HTML -> CSS."""
    panel = read_text(PANEL_JS)
    queue = read_text(QUEUE_JS)
    index = read_text(INDEX_HTML)
    css = read_text(STYLE_CSS)

    assert PURE_BEGIN in panel and PURE_END in panel, "PURE blok markerlari"
    for token in (
        'action: "left"',
        'action: "right"',
        'action: "delete"',
        'action: "fraction"',
    ):
        assert token in panel, token
    for name in ("insertAt", "deleteBefore", "deleteAt", "buildFraction", "renderExpression"):
        assert (name + ": " + name) in panel, name
    for token in (
        "carets",
        "caretOf",
        "moveCaret",
        "deleteCell",
        "openFractionModal",
        "submitFractionModal",
        "renderCellHtml",
    ):
        assert token in queue, token
    for token in ('id="frac-num"', 'id="frac-den"', 'id="frac-add"', 'id="frac-cancel"'):
        assert token in index, token
    for token in (".m-frac", ".m-num", ".m-den", ".m-root", ".frac-modal"):
        assert token in css, token
    print("[OK] simlar: mathpanel.js / queue.js / index.html / style.css ulangan")


def check_python_parser() -> None:
    """Parser tegilgan emas: sin/cos/log_a(b) va legacy hali ishlaydi."""
    assert abs(math_expr.evaluate("sin(pi/2)") - 1.0) < 1e-12
    assert abs(math_expr.evaluate("cos(0)") - 1.0) < 1e-12
    assert abs(math_expr.evaluate("log_2(8)") - 3.0) < 1e-12
    assert math_expr.evaluate("3/7") == 3 / 7
    assert math_expr.equivalent("\u221a5", "(\u221a20)/2")
    print("[OK] Python parser: sin/cos/log_a(b) va legacy o'zgarmagan")


def main() -> None:
    print("=" * 72)
    print("Phase 5: matematik panel UX (caret, kasr, renderer) - regressiya")
    print("=" * 72)
    ran_js = check_js()
    check_wiring()
    check_python_parser()
    print("=" * 72)
    if ran_js:
        print("Barcha tekshiruvlar muvaffaqiyatli o'tdi \u2705")
    else:
        print("Python tekshiruvlari o'tdi (JS qismi o'tkazildi) \u2705")
    print("=" * 72)


if __name__ == "__main__":
    main()
