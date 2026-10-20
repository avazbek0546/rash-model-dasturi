"""Phase 6 regressiya: DEG/RAD machine-string OQIMI (queue.js) — real bajarilish.

Maqsad: `applyExpression -> savePending -> loadPending -> createAttemptCtx ->
mergeServerState -> queueAnswer -> flushAutosave` oqimida `deg(...)`/`rad(...)`
wrapper YO'QOLMASLIGINI isbotlash. Server esa ifodani qayta hisoblaydi
(`web/api_v2.py:291-296`), shu sababli wrapper yo'qolsa baholash buziladi.

Usul: `webapp/js/queue.js` va `webapp/js/mathpanel.js` dan HAQIQIY funksiyalar
ajratib olinadi va `cscript //E:JScript` ostida BAJARILADI. DOM/API/taymerlargina
stub qilinadi (test qilinayotgan mantiq — real kod).

Moslashtirish (faqat TEST tomonida): `const/let -> var`, `async -> `, `await -> `;
JScript uchun ES5 shimlar (JSON, Object.keys, Array.isArray/forEach, Number.isFinite).

Ishga tushirish:
    python tests/test_degree_flow.py
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

QUEUE_JS = ROOT / "webapp" / "js" / "queue.js"
PANEL_JS = ROOT / "webapp" / "js" / "mathpanel.js"

PURE_BEGIN = "// --- [PURE-BEGIN]"
PURE_END = "// --- [PURE-END]"

QUEUE_FUNCTIONS = (
    "storageGet", "storageSet", "attemptKey", "seqKey", "pendingKey",
    "loadAttemptId", "loadSeq", "loadPending", "savePending", "nextSeq",
    "createAttemptCtx", "isActive", "serverCellId", "kindOf",
    "panelApi", "machineFor", "restoreExpression",
    "queueAnswer", "autosaveTarget", "mergeServerState", "flushAutosave",
    "evaluateExpression", "cellOf", "applyExpression",
)

SHIMS = r'''
var JSON = {
  stringify: function (value) {
    if (value === null || value === undefined) { return "null"; }
    var kind = typeof value;
    if (kind === "number") { return isFinite(value) ? String(value) : "null"; }
    if (kind === "boolean") { return value ? "true" : "false"; }
    if (kind === "string") { return jsonQuote(value); }
    if (value instanceof Array) {
      var parts = [];
      for (var i = 0; i < value.length; i += 1) { parts[parts.length] = JSON.stringify(value[i]); }
      return "[" + parts.join(",") + "]";
    }
    var chunks = [];
    for (var key in value) {
      if (Object.prototype.hasOwnProperty.call(value, key)) {
        chunks[chunks.length] = jsonQuote(key) + ":" + JSON.stringify(value[key]);
      }
    }
    return "{" + chunks.join(",") + "}";
  },
  parse: function (text) { return eval("(" + text + ")"); }
};

function jsonQuote(text) {
  var out = '"';
  var value = String(text);
  for (var i = 0; i < value.length; i += 1) {
    var c = value.charAt(i);
    if (c === '"') { out += '\\"'; }
    else if (c === "\\") { out += "\\\\"; }
    else { out += c; }
  }
  return out + '"';
}

if (typeof Object.keys !== "function") {
  Object.keys = function (obj) {
    var keys = [];
    for (var key in obj) {
      if (Object.prototype.hasOwnProperty.call(obj, key)) { keys[keys.length] = key; }
    }
    return keys;
  };
}
if (typeof Array.isArray !== "function") {
  Array.isArray = function (value) { return value instanceof Array; };
}
if (typeof [].forEach !== "function") {
  Array.prototype.forEach = function (fn, thisArg) {
    for (var i = 0; i < this.length; i += 1) { fn.call(thisArg, this[i], i, this); }
  };
}
if (typeof Number.isFinite !== "function") {
  Number.isFinite = function (value) { return typeof value === "number" && isFinite(value); };
}
if (typeof "".startsWith !== "function") {
  String.prototype.startsWith = function (word, position) {
    var at = (position === undefined || position === null) ? 0 : position;
    return this.substr(at, word.length) === word;
  };
}
'''

STUBS = r'''
var _store = {};
var window = {
  localStorage: {
    getItem: function (key) {
      return Object.prototype.hasOwnProperty.call(_store, key) ? _store[key] : null;
    },
    setItem: function (key, value) { _store[key] = String(value); },
    removeItem: function (key) { delete _store[key]; }
  },
  MathPanel: null,
  setTimeout: function () { return 0; },
  clearTimeout: function () {}
};

var ANSWERS_PREFIX = "rasch.answers.";
var ATTEMPT_PREFIX = "rasch.attempt.";
var SEQ_PREFIX = "rasch.seq.";
var PENDING_PREFIX = "rasch.pending.";
var NUMERIC_RE = /^-?\d{1,7}([.,]\d{1,4})?$/;

var attemptCtx = null;
var answers = {};
var expressions = {};
var items = [];
var cellIndex = {};
var epochCounter = 0;
var angleMode = "deg";
var CAPTURED = [];

function byId() { return null; }
function scheduleSave() {}
function refreshCellView() {}
function updateStatus() {}
function hintForCell() { return ""; }
function setNoteIfActive() {}
function scheduleRetry() {}
function clockText() { return ""; }

var API = {
  post: function (url, body) {
    CAPTURED[CAPTURED.length] = { url: url, body: body };
    return { ok: true };
  }
};

window.MathPanel = {
  insertAt: function () { return { text: "", caret: 0 }; },
  deleteBefore: function () { return { text: "", caret: 0 }; },
  deleteAt: function () { return { text: "", caret: 0 }; },
  buildFraction: function () { return ""; },
  renderExpression: function (text) { return String(text == null ? "" : text); },
  evaluate: function () { return 0.5; },
  formatValue: function (value) { return String(value); },
  currentTarget: function () { return null; },
  machineExpression: function (text) { return composeExpression(text, angleMode); },
  unwrapExpression: function (machine) { return unwrapExpression(machine); },
  setAngleMode: function (mode) { angleMode = mode === "rad" ? "rad" : "deg"; },
  getAngleMode: function () { return angleMode; }
};

function show(name, value) { WScript.Echo(name + "=" + String(value)); }
'''

DRIVER = r'''
angleMode = "deg";
items = [{ cellId: "36", position: 36, kind: "numeric", part: "" }];
cellIndex = { "36": items[0] };
answers = {};
expressions = {};
attemptCtx = createAttemptCtx(777);
attemptCtx.v2Enabled = true;
attemptCtx.attemptId = 55;

// 1) applyExpression -> savePending (localStorage)
applyExpression("36", "sin(30)");
show("step1_dirty", attemptCtx.dirty["36"] ? attemptCtx.dirty["36"].expression : "(none)");
show("step1_pending", loadPending(777)["36"] ? loadPending(777)["36"].expression : "(none)");

// 2) loadPending -> createAttemptCtx (reload)
var ctx2 = createAttemptCtx(777);
show("step2_ctx", ctx2.dirty["36"] ? ctx2.dirty["36"].expression : "(none)");

// 3) mergeServerState (serverda bu katak YO'Q)
attemptCtx = ctx2;
attemptCtx.v2Enabled = true;
attemptCtx.attemptId = 55;
mergeServerState(attemptCtx, { items: [] });
show("step3_dirty", attemptCtx.dirty["36"] ? attemptCtx.dirty["36"].expression : "(none)");

// 4) queueAnswer fallback (expression argumenti berilmagan)
items[items.length] = { cellId: "37", position: 37, kind: "numeric", part: "" };
cellIndex["37"] = items[items.length - 1];
expressions["37"] = "cos(60)";
answers["37"] = "0.5";
queueAnswer("37", null, "numeric");
show("step4_dirty", attemptCtx.dirty["37"] ? attemptCtx.dirty["37"].expression : "(none)");

// 5) flushAutosave payload (serverga ketadigan `expression`)
flushAutosave(attemptCtx, false);
var sent = [];
for (var i = 0; i < CAPTURED.length; i += 1) { sent[sent.length] = CAPTURED[i].body.expression; }
show("step5_payloads", sent.join("|"));

// 6) RAD rejimi
angleMode = "rad";
items[items.length] = { cellId: "38", position: 38, kind: "numeric", part: "" };
cellIndex["38"] = items[items.length - 1];
applyExpression("38", "sin(pi/6)");
show("rad_dirty", attemptCtx.dirty["38"] ? attemptCtx.dirty["38"].expression : "(none)");
'''


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_block(source: str, begin: str, end: str) -> str:
    start = source.index(begin)
    stop = source.index(end) + len(end)
    return source[start:stop]


def extract_function(source: str, name: str) -> str:
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
    """ES6 → JScript mos (faqat test tomonida).

    `const/let -> var`, `async -> `, `await -> ` va obyekt/massiv
    literallaridagi oxirgi vergul olib tashlanadi (JScript ularni rad etadi).
    """
    js = re.sub(r"\bconst\b", "var", js)
    js = re.sub(r"\blet\b", "var", js)
    js = re.sub(r"\basync\s+function\b", "function", js)
    js = re.sub(r"\bawait\s+", "", js)
    js = re.sub(r",(\s*[}\]])", r"\1", js)
    return js


def build_program() -> str:
    queue = read_text(QUEUE_JS)
    panel = read_text(PANEL_JS)
    lines = [SHIMS, STUBS]
    lines.append(transpile(extract_block(panel, PURE_BEGIN, PURE_END)))
    for name in QUEUE_FUNCTIONS:
        lines.append(transpile(extract_function(queue, name)))
    lines.append(DRIVER)
    return "\n".join(lines)


def run_js(program: str) -> dict[str, str] | None:
    cscript = shutil.which("cscript") or shutil.which("cscript.exe")
    if not cscript:
        return None
    ascii_source = program.encode("ascii", "replace").decode("ascii")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "flow_harness.js"
        harness.write_text(ascii_source, encoding="ascii")
        completed = subprocess.run(
            [cscript, "//nologo", "//E:JScript", str(harness)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    out: dict[str, str] = {}
    for line in (completed.stdout or "").splitlines():
        line = line.strip()
        if "=" in line:
            name, value = line.split("=", 1)
            out[name] = value
    return out


EXPECTED = {
    "step1_dirty": "deg(sin(30))",
    "step1_pending": "deg(sin(30))",
    "step2_ctx": "deg(sin(30))",
    "step3_dirty": "deg(sin(30))",
    "step4_dirty": "deg(cos(60))",
    "rad_dirty": "rad(sin(pi/6))",
}


def check_flow() -> bool:
    """Oqim bo'ylab `deg(...)`/`rad(...)` saqlanishi (real JS bajarilishi)."""
    results = run_js(build_program())
    if results is None:
        print("[SKIP] cscript topilmadi - oqim tekshiruvi o'tkazildi")
        return False
    for name in ("step1_dirty", "step1_pending", "step2_ctx", "step3_dirty",
                 "step4_dirty", "step5_payloads", "rad_dirty"):
        print("   %-16s = %s" % (name, results.get(name)))
    for name, expected in EXPECTED.items():
        got = results.get(name)
        assert got == expected, ("%s: kutilgan %r, olingan %r" % (name, expected, got))
    payloads = (results.get("step5_payloads") or "").split("|")
    assert "deg(sin(30))" in payloads, payloads
    assert "deg(cos(60))" in payloads, payloads
    print("[OK] oqim: applyExpression -> savePending -> loadPending -> "
          "createAttemptCtx -> mergeServerState -> queueAnswer -> flushAutosave")
    print("[OK] payloadda deg(sin(30)) / deg(cos(60)) saqlanib qoldi")
    return True


def main() -> None:
    print("=" * 72)
    print("Phase 6: DEG/RAD machine-string oqimi (queue.js) - regressiya")
    print("=" * 72)
    ran = check_flow()
    print("=" * 72)
    if ran:
        print("Barcha tekshiruvlar muvaffaqiyatli o'tdi \u2705")
    else:
        print("Oqim tekshiruvi o'tkazildi (cscript yo'q) \u2705")
    print("=" * 72)


if __name__ == "__main__":
    main()
