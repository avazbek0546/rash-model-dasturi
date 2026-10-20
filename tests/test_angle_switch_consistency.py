"""Phase 6 regressiya: burchak rejimi almashganda javob izchilligi.

Muammo (risk): javob bir rejimda yozilib, keyin rejim almashsa, `value` (eski
rejimda hisoblangan son) va `expression` (yangi rejim bilan muhrlangan matn)
ajralib qolishi mumkin — server esa **ifodani** qayta hisoblaydi
(`web/api_v2.py:291-296`).

Invariant: `evaluate(entry.expression) == entry.value` HAR QADAMDA.

Test HAQIQIY bajariladi: `webapp/js/queue.js` va `webapp/js/mathpanel.js` dan
real funksiyalar ajratilib `cscript //E:JScript` ostida ishga tushiriladi
(HAQIQIY `evaluate`/`formatValue`); DOM/API/taymerlargina stub.

Ishga tushirish:
    python tests/test_angle_switch_consistency.py
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
import test_degree_flow as flow  # noqa: E402
import test_math_panel_eval as ev  # noqa: E402

QUEUE_FUNCTIONS = tuple(flow.QUEUE_FUNCTIONS) + (
    "answersKey",
    "loadSavedAnswers",
    "persistAnswers",
)

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
var NUMBER_RE = /^-?\d{1,7}([.,]\d{1,4})?$/;

var attemptCtx = null;
var answers = {};
var expressions = {};
var items = [];
var cellIndex = {};
var epochCounter = 0;
var angleMode = "deg";
var CAPTURED = [];
var activeCell = null;
var selectedExam = null;

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
  evaluate: function (text) { return evaluate(text); },
  formatValue: function (value) { return formatValue(value); },
  currentTarget: function () { return null; },
  machineExpression: function (text) { return composeExpression(text, angleMode); },
  unwrapExpression: function (machine) { return unwrapExpression(machine); },
  setAngleMode: function (mode) { angleMode = mode === "rad" ? "rad" : "deg"; },
  getAngleMode: function () { return angleMode; }
};

function show(name, value) { WScript.Echo(name + "=" + String(value)); }
'''

DRIVER = r'''
function resetAll(mode) {
  _store = {};
  answers = {};
  expressions = {};
  CAPTURED = [];
  activeCell = null;
  angleMode = mode;
  items = [
    { cellId: "36", position: 36, kind: "numeric", part: "" },
    { cellId: "37", position: 37, kind: "numeric", part: "" }
  ];
  cellIndex = {};
  for (var i = 0; i < items.length; i += 1) { cellIndex[items[i].cellId] = items[i]; }
  selectedExam = { exam_id: 777 };
  attemptCtx = createAttemptCtx(777);
  attemptCtx.v2Enabled = true;
  attemptCtx.attemptId = 55;
}

// queue.js:1575-1580 (`onAngle`) bilan bir xil 3 satr.
function switchMode(mode) {
  angleMode = mode;
  if (activeCell && cellOf(activeCell)) {
    applyExpression(activeCell, expressions[activeCell] || "");
  }
}

// queue.js:1301-1312 (`openAnswerSheet` tiklash) emulyatsiyasi.
function emulateReload(examId) {
  var saved = loadSavedAnswers(examId);
  answers = {};
  expressions = {};
  for (var i = 0; i < items.length; i += 1) {
    var cellId = items[i].cellId;
    var value = saved.answers[cellId];
    if (value !== undefined && value !== null && value !== "") {
      answers[cellId] = String(value);
      var expression = saved.expressions[cellId];
      expressions[cellId] = expression ? String(expression) : String(value);
    }
  }
  activeCell = null;
  var ctx = createAttemptCtx(examId);
  attemptCtx = ctx;
  ctx.v2Enabled = true;
  ctx.attemptId = 55;
  return ctx;
}

function pair(entry) {
  if (!entry) { return "(none)"; }
  return String(entry.expression) + "@" + String(entry.value);
}

function payloadPairs() {
  var out = [];
  for (var i = 0; i < CAPTURED.length; i += 1) {
    out[out.length] = String(CAPTURED[i].body.expression) + "@" + String(CAPTURED[i].body.value);
  }
  return out.join(",");
}

// CASE A: DEG -> yoz -> RAD (katak aktiv) -> hech narsa yozilmaydi
resetAll("deg");
activeCell = "36";
applyExpression("36", "sin(30)");
show("A_before", pair(attemptCtx.dirty["36"]));
switchMode("rad");
show("A_after", pair(attemptCtx.dirty["36"]));
flushAutosave(attemptCtx, false);
show("A_payload", payloadPairs());

// CASE B: DEG -> yoz -> katakdan chiq -> RAD -> qayta tanlash
resetAll("deg");
activeCell = "36";
applyExpression("36", "sin(30)");
activeCell = null;
switchMode("rad");
show("B_after_switch", pair(attemptCtx.dirty["36"]));
activeCell = "36";
show("B_after_reactivate", pair(attemptCtx.dirty["36"]));
flushAutosave(attemptCtx, false);
show("B_payload", payloadPairs());

// CASE C: DEG -> yoz -> RAD -> reload -> merge
resetAll("deg");
activeCell = "36";
applyExpression("36", "sin(30)");
persistAnswers();
activeCell = null;
switchMode("rad");
var ctxC = emulateReload(777);
mergeServerState(ctxC, { items: [] });
show("C_merged", pair(ctxC.dirty["36"]));
flushAutosave(ctxC, false);
show("C_payload", payloadPairs());

// CASE C2: RAD -> yoz -> DEG -> reload -> merge
resetAll("rad");
activeCell = "36";
applyExpression("36", "sin(pi/6)");
persistAnswers();
activeCell = null;
switchMode("deg");
var ctxC2 = emulateReload(777);
mergeServerState(ctxC2, { items: [] });
show("C2_merged", pair(ctxC2.dirty["36"]));
flushAutosave(ctxC2, false);
show("C2_payload", payloadPairs());

// CASE D: ikki katak (DEG) -> RAD -> autosave
resetAll("deg");
activeCell = "36";
applyExpression("36", "sin(30)");
activeCell = "37";
applyExpression("37", "cos(60)");
activeCell = null;
switchMode("rad");
flushAutosave(attemptCtx, false);
show("D_payload", payloadPairs());
'''


def build_program() -> str:
    panel = flow.PANEL_JS.read_text(encoding="utf-8")
    queue = flow.QUEUE_JS.read_text(encoding="utf-8")
    parts = [ev.SHIMS, flow.SHIMS, STUBS]
    parts.append(ev.transpile(flow.extract_block(panel, flow.PURE_BEGIN, flow.PURE_END)))
    for name in ev.FUNCTIONS:
        parts.append(ev.transpile(flow.extract_function(panel, name)))
    parts.append(ev.transpile(flow.extract_function(panel, "formatValue")))
    for name in QUEUE_FUNCTIONS:
        parts.append(flow.transpile(flow.extract_function(queue, name)))
    parts.append(DRIVER)
    return "\n".join(parts)


WATCHED = (
    "A_before", "A_after", "A_payload",
    "B_after_switch", "B_after_reactivate", "B_payload",
    "C_merged", "C_payload",
    "C2_merged", "C2_payload",
    "D_payload",
)


def parse_pairs(raw: str | None) -> list[tuple[str, str]]:
    if raw is None or raw == "" or raw == "(none)":
        return []
    pairs: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        if "@" not in chunk:
            continue
        expression, value = chunk.split("@", 1)
        pairs.append((expression, value))
    return pairs


def check_consistency() -> bool:
    """Har qadamda `evaluate(expression) == value` invariantini tekshiradi."""
    results = flow.run_js(build_program())
    if results is None:
        print("[SKIP] cscript topilmadi - tekshiruv o'tkazildi")
        return False

    for name in WATCHED:
        print("   %-20s = %s" % (name, results.get(name)))

    problems: list[tuple[str, str, str, object]] = []
    for name in WATCHED:
        for expression, value in parse_pairs(results.get(name)):
            if not expression or expression == "null":
                continue
            if not value or value == "null":
                continue
            evaluated = math_expr.evaluate(expression)
            if evaluated is None:
                problems.append((name, expression, value, "hisoblanmadi"))
                continue
            # `value` `formatValue` bilan 4 kasrga yumaloqlanadi — shu sababli
            # taqqoslash ham shu aniqlikda (matematik nomuvofiqlik ~0.5 kabi
            # katta farq bilan ajralib turadi).
            if abs(evaluated - float(value)) > 5e-5:
                problems.append((name, expression, value, evaluated))

    assert results.get("A_before") == "deg(sin(30))@0.5", results.get("A_before")
    assert results.get("D_payload") == "deg(sin(30))@0.5,deg(cos(60))@0.5", results.get("D_payload")

    if problems:
        for name, expression, value, evaluated in problems:
            print("   [!] %s: expression=%r, value=%r, evaluate(expression)=%r"
                  % (name, expression, value, evaluated))
        raise AssertionError("BUG BOR: expression/value nomuvofiq (%d ta)" % len(problems))

    print("[OK] BUG YO'Q: har qadamda evaluate(expression) == value")
    print("[OK] DEG->RAD, RAD->DEG, reload, merge, autosave: izchil")
    return True


def main() -> None:
    print("=" * 72)
    print("Phase 6: burchak rejimi almashganda javob izchilligi - regressiya")
    print("=" * 72)
    ran = check_consistency()
    print("=" * 72)
    if ran:
        print("Barcha tekshiruvlar muvaffaqiyatli o'tdi \u2705")
    else:
        print("Tekshiruv o'tkazildi (cscript yo'q) \u2705")
    print("=" * 72)


if __name__ == "__main__":
    main()
