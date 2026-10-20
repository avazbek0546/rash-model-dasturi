/* ---------------------------------------------------------------------------
   Matematik javob paneli (36–45 savollar uchun).

   BITTA GLOBAL panel: qaysi katak "active" bo'lsa, panelning barcha tugmalari
   aynan o'sha katakka yoziladi. Har bir savol ostida alohida mini-panel YO'Q.

   Ifoda quvuri
       tugma  →  ifoda matni (foydalanuvchi ko'radi)
              →  hisoblash (xavfsiz parser)
              →  o'nli son (baholash uchun) + ASL IFODA (dalil uchun)

   Sabab: baholash faqat `-?\d{1,7}([.,]\d{1,4})?` son formatini biladi
   (`services/form_layout.py`), shuning uchun son baribir hisoblanadi.
   LEKIN Phase 1 dan boshlab ASL ifoda ham saqlanadi: `queue.js` uni
   `expression` sifatida serverga yuboradi va `raw_answer` ustuniga tushadi —
   backend, Rasch, scoring, grading va analytics logikasi O'ZGARMAYDI.

   Xavfsizlik: `eval()` ISHLATILMAYDI — oq ro'yxatli normalizatsiya + rekursiv
   tushish parseri (faqat kerakli amallar).
--------------------------------------------------------------------------- */
(function () {
  "use strict";

  const MODE_KEY = "rasch.panel.mode";
  const ANGLE_KEY = "rasch.panel.angle";

  // Burchak rejimi: DEG (standart) / RAD. Ifoda matniga "muhrlanadi"
  // (`deg(...)` / `rad(...)`) — shu sababli JS va Python bir xil hisoblaydi.
  let angleMode = "deg";

  // Server qabul qiladigan son formati (form_layout._NUMERIC_RE bilan bir xil).
  const NUMBER_RE = /^-?\d{1,7}([.,]\d{1,4})?$/;

  // --- Tugmalar registri ----------------------------------------------------
  // `insert` — ifodaga qo'shiladigan matn; `action` — maxsus amal.
  // Kengaytirish nuqtasi: kelajakda kasr/ildiz/daraja konstruktorlari shu
  // registrga yangi yozuv sifatida qo'shiladi (panel qayta yozilmaydi).
  const ARROW = "\u232B"; // ⌫

  const LAYOUT_BASIC = [
    ["7", "8", "9", { label: ARROW, action: "backspace", cls: "key-fn" }],
    // `÷` — SMART KASR: terilgan qism SURATGA o'tadi, caret MAXRAJGA tushadi
    // (foydalanuvchi darhol maxrajni yozadi). Bo'lish = kasr — qiymat o'zgarmaydi,
    // faqat kiritish tez va qulay bo'ladi.
    ["4", "5", "6", { label: "\u00F7", action: "smartfraction", cls: "key-op" }],
    ["1", "2", "3", { label: "\u00D7", insert: "*", cls: "key-op" }],
    [",", "0", ".", { label: "\u2212", insert: "-", cls: "key-op" }],
    [
      "(",
      ")",
      { label: "=", insert: "=", cls: "key-op" },
      { label: "+", insert: "+", cls: "key-op" },
    ],
    [
      { label: "\u2190", action: "left", cls: "key-fn" },
      { label: "\u2192", action: "right", cls: "key-fn" },
      { label: "\u2326", action: "delete", cls: "key-fn" },
      { label: "a/b", action: "fraction", cls: "key-fn" },
    ],
  ];

  // «Funksiya» rejimi — FAQAT matematik belgilar (raqamlar «Asosiy»da).
  // Guruhlar: ildiz/daraja · sonlar · trigonometriya · logarifm · tahrir.
  const LAYOUT_MATH_V2 = [
    [
      // √ — kvadrat ildiz (kursor radikand ichida turadi).
      { label: "\u221A", insert: "\u221A()", caretBack: 1, cls: "key-fn" },
      // ⁿ√ — n-DARAJALI ILDIZ: daraja o'rnida bo'sh KATAKCHA ochiladi va
      // kursor shu katakcha ichiga tushadi — foydalanuvchi o'zi darajani
      // yozadi (3, 5, 6, n…) — Word'dagi tenglamalar kabi.
      { label: "\u207F\u221A", insert: "\u221A[]()", caretBack: 3, cls: "key-fn" },
      // xⁿ — daraja o'rnida bo'sh KATAKCHA (kursor ichida).
      { label: "x\u207F", insert: "^()", caretBack: 1, cls: "key-fn" },
      { label: "x\u207B\u00B9", insert: "^(-1)", cls: "key-fn" }, // x⁻¹
    ],
    [
      { label: "\u03C0", insert: "\u03C0", cls: "key-fn" }, // π
      { label: "e", insert: "e", cls: "key-fn" },
      { label: "|x|", insert: "|", cls: "key-fn" },
      { label: "\u2044", action: "fraction", cls: "key-fn" }, // kasr: surat/maxraj
    ],
    [
      { label: "sin", insert: "sin", cls: "key-fn" },
      { label: "cos", insert: "cos", cls: "key-fn" },
      { label: "tg", insert: "tg", cls: "key-fn" },
      { label: "ctg", insert: "ctg", cls: "key-fn" },
    ],
    [
      { label: "ln", insert: "ln", cls: "key-fn" },
      { label: "lg", insert: "lg", cls: "key-fn" },
      // `logₐ` — asos va argument katakchalari darhol ochiladi, kursor ASOS
      // KATAKCHASIGA tushadi (avval asos, keyin argument) — n-darajali ildiz
      // bilan bir xil mantiq (`√[]()`).
      { label: "log\u2090", insert: "log_()", caretBack: 2, cls: "key-fn" },
      { label: "\u2044", action: "fraction", cls: "key-fn" }, // kasr: surat/maxraj
    ],
    [
      { label: "(", insert: "(", cls: "key-fn" },
      { label: ")", insert: ")", cls: "key-fn" },
      { label: "\u2190", action: "left", cls: "key-fn" },
      { label: "\u2192", action: "right", cls: "key-fn" },
    ],
    [
      { label: ARROW, action: "backspace", cls: "key-fn" },
      { label: "\u2326", action: "delete", cls: "key-fn" },
      { label: "C", action: "clear", cls: "key-fn" },
      { label: "\u2713", action: "confirm", cls: "key-ok" },
    ],
  ];

  const LAYOUT_MATH = [
    ["7", "8", "9", { label: ARROW, action: "backspace", cls: "key-fn" }],
    ["4", "5", "6", { label: "\u00F7", insert: "/", cls: "key-op" }],
    ["1", "2", "3", { label: "\u00D7", insert: "*", cls: "key-op" }],
    ["0", ".", ",", { label: "\u2212", insert: "-", cls: "key-op" }],
    [
      "(",
      ")",
      { label: "+", insert: "+", cls: "key-op" },
      { label: "=", insert: "=", cls: "key-op" },
    ],
    [
      { label: "\u221A", insert: "\u221A", cls: "key-fn" },
      { label: "\u221B", insert: "\u221B", cls: "key-fn" },
      { label: "x\u00B2", insert: "^2", cls: "key-fn" },
      { label: "x\u00B3", insert: "^3", cls: "key-fn" },
    ],
    [
      { label: "x\u207F", insert: "^", cls: "key-fn" },
      { label: "a/b", action: "fraction", cls: "key-fn" },
      { label: "|x|", insert: "|", cls: "key-fn" },
      { label: "\u03C0", insert: "\u03C0", cls: "key-fn" },
    ],
    [
      { label: "sin", insert: "sin", cls: "key-fn" },
      { label: "cos", insert: "cos", cls: "key-fn" },
      { label: "tg", insert: "tg", cls: "key-fn" },
      { label: "ctg", insert: "ctg", cls: "key-fn" },
    ],
    [
      { label: "arcsin", insert: "arcsin", cls: "key-fn" },
      { label: "arccos", insert: "arccos", cls: "key-fn" },
      { label: "arctg", insert: "arctg", cls: "key-fn" },
      { label: "arcctg", insert: "arcctg", cls: "key-fn" },
    ],
    [
      { label: "lg", insert: "lg", cls: "key-fn" },
      { label: "ln", insert: "ln", cls: "key-fn" },
      { label: "log\u2090", insert: "log_", cls: "key-fn" },
    ],
    [
      { label: "%", insert: "%", cls: "key-fn" },
      { label: "C", action: "clear", cls: "key-fn" },
    ],
    [
      { label: "\u2190", action: "left", cls: "key-fn" },
      { label: "\u2192", action: "right", cls: "key-fn" },
      { label: "\u2326", action: "delete", cls: "key-fn" },
    ],
  ];

  let mode = "basic";
  let activeId = null;
  let handlers = {
    onInsert: null, onBackspace: null, onClear: null, onClose: null,
    onLeft: null, onRight: null, onDelete: null, onFraction: null,
    onSmartFraction: null,
    onAngle: null,
  };
  let panel = null;
  let keysBox = null;
  let targetBox = null;
  let hintBox = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function storageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      /* localStorage yopiq bo'lsa — e'tiborsiz */
    }
  }

  function haptic() {
    if (window.API && typeof window.API.haptic === "function") {
      window.API.haptic("light");
    }
  }

  function normalizeKey(key) {
    if (typeof key === "string") {
      return { label: key, insert: key };
    }
    return key;
  }

  // --- [PURE-BEGIN] Caret tahriri, kasr konstruktori va renderer -----------
  // Bu blok ES3-sinovli: `tests/test_math_panel_ux.py` uni ajratib olib,
  // `cscript //E:JScript` ostida HAQIQIY ishga tushiradi (Node.js kerak emas).
  // Shu sababli: `const`/`let`, o'q funksiyasi, shablon satri va ES5 massiv
  // metodlari ISHLATILMAYDI. Render faqat UI uchun — machine-string O'ZGARMAYDI.

  function mdTrim(text) {
    return String(text == null ? "" : text).replace(/^\s+|\s+$/g, "");
  }

  function mdIsDigit(ch) {
    return ch >= "0" && ch <= "9";
  }

  function mdStarts(text, index, word) {
    return text.substr(index, word.length) === word;
  }

  function mdEscape(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  /** `insertAt(text, caret, token)` -> { text, caret } (token caret joyiga). */
  function insertAt(text, caret, token) {
    var source = String(text == null ? "" : text);
    var at = typeof caret === "number" ? Math.round(caret) : source.length;
    if (at < 0) {
      at = 0;
    }
    if (at > source.length) {
      at = source.length;
    }
    var piece = String(token == null ? "" : token);
    return {
      text: source.substring(0, at) + piece + source.substring(at),
      caret: at + piece.length
    };
  }

  /** `deleteBefore(text, caret)` -> { text, caret } (Backspace — chapdagi). */
  function deleteBefore(text, caret) {
    var source = String(text == null ? "" : text);
    var at = typeof caret === "number" ? Math.round(caret) : source.length;
    if (at < 0) {
      at = 0;
    }
    if (at > source.length) {
      at = source.length;
    }
    if (at === 0) {
      return { text: source, caret: 0 };
    }
    return {
      text: source.substring(0, at - 1) + source.substring(at),
      caret: at - 1
    };
  }

  /** `deleteAt(text, caret)` -> { text, caret } (Delete — o'ngdagi). */
  function deleteAt(text, caret) {
    var source = String(text == null ? "" : text);
    var at = typeof caret === "number" ? Math.round(caret) : source.length;
    if (at < 0) {
      at = 0;
    }
    if (at > source.length) {
      at = source.length;
    }
    if (at >= source.length) {
      return { text: source, caret: source.length };
    }
    return {
      text: source.substring(0, at) + source.substring(at + 1),
      caret: at
    };
  }

  /** Kasr konstruktori: machine-string `(surat)/(maxraj)`. */
  function buildFraction(numerator, denominator) {
    var num = mdTrim(numerator);
    var den = mdTrim(denominator);
    if (!num && !den) {
      return "";
    }
    return "(" + num + ")/(" + den + ")";
  }

  /** `(` ... `)` — mos yopiluvchi qavs indeksi (topilmasa -1). */
  function mdMatchParen(text, open) {
    var depth = 0;
    var index;
    for (index = open; index < text.length; index += 1) {
      var ch = text.charAt(index);
      if (ch === "(") {
        depth += 1;
      } else if (ch === ")") {
        depth -= 1;
        if (depth === 0) {
          return index;
        }
      }
    }
    return -1;
  }

  /** Caret belgisi (faqat UI). */
  var CARET_HTML = '<span class="q-caret">|</span>';

  /** Bo'sh KATAKCHA (Word'dagi kabi): bosilganda caret ichiga tushadi. */
  function mdSlot(base, caret, extraCls) {
    var on = caret === base ? " m-slot-on" : "";
    var bar = caret === base ? CARET_HTML : "";
    return (
      '<span class="m-slot' + extraCls + on + '" data-off="' + base + '">' + bar + "</span>"
    );
  }

  /** Ildiz ostidagi operand: qavs ichi ochiladi, BO'SH bo'lsa — katakcha. */
  function mdRadicand(text, index, base, caret) {
    if (text.charAt(index) === "(") {
      var close = mdMatchParen(text, index);
      if (close >= 0) {
        var inner = text.substring(index + 1, close);
        if (!inner) {
          return { html: mdSlot(base + index + 1, caret), next: close + 1 };
        }
        return { html: mdRenderRange(inner, base + index + 1, caret), next: close + 1 };
      }
    }
    return mdRenderAtom(text, index, base, caret);
  }

  /** Daraja ko'rsatkichi: qavs ichi ochiladi, BO'SH bo'lsa — katakcha. */
  function mdExponent(text, index, base, caret) {
    if (text.charAt(index) === "(") {
      var close = mdMatchParen(text, index);
      if (close >= 0) {
        var inner = text.substring(index + 1, close);
        if (!inner) {
          return { html: mdSlot(base + index + 1, caret), next: close + 1 };
        }
        return { html: mdRenderRange(inner, base + index + 1, caret), next: close + 1 };
      }
    }
    return mdRenderAtom(text, index, base, caret);
  }

  /**
   * ILDIZ: `√(x)` — kvadrat ildiz, `√[n](x)` — n-darajali ildiz.
   * `√[](x)` da daraja o'rnida bo'sh KATAKCHA chiziladi — foydalanuvchi
   * uni bosib ixtiyoriy darajani (3, 5, 6, n…) yozadi (Word'dagi kabi).
   */
  function mdRoot(text, index, base, caret, head) {
    var at = index + (head || 1);
    var degree = null;
    var degreeStart = -1;
    if (text.charAt(at) === "[") {
      var closeB = text.indexOf("]", at + 1);
      if (closeB >= 0) {
        degree = text.substring(at + 1, closeB);
        degreeStart = at + 1;
        at = closeB + 1;
      }
    }
    var rad = mdRadicand(text, at, base, caret);
    var indexHtml = "";
    if (degreeStart >= 0 && !degree) {
      indexHtml = mdSlot(base + degreeStart, caret, "m-slot-idx");
    } else if (degreeStart >= 0) {
      indexHtml = mdRenderRange(degree, base + degreeStart, caret);
    }
    return {
      html:
        '<span class="m-root-wrap"><span class="m-index">' +
        indexHtml +
        "</span>\u221A" +
        '<span class="m-root">' +
        rad.html +
        "</span></span>",
      next: rad.next
    };
  }

  /** Bitta atomni HTML ga aylantiradi: { html, next } (caret belgisi bilan). */
  function mdRenderAtom(text, index, base, caret) {
    var ch = text.charAt(index);
    var mark = function (position) {
      return position === caret ? CARET_HTML : "";
    };
    if (ch === "(") {
      var close = mdMatchParen(text, index);
      if (close < 0) {
        return { html: mdEscape(ch), next: index + 1 };
      }
      if (text.charAt(close + 1) === "/" && text.charAt(close + 2) === "(") {
        var denClose = mdMatchParen(text, close + 2);
        if (denClose >= 0) {
          var numRaw = text.substring(index + 1, close);
          var denRaw = text.substring(close + 3, denClose);
          return {
            html:
              '<span class="m-frac"><span class="m-num">' +
              (numRaw
                ? mdRenderRange(numRaw, base + index + 1, caret)
                : mdSlot(base + index + 1, caret)) +
              '</span><span class="m-den">' +
              (denRaw
                ? mdRenderRange(denRaw, base + close + 3, caret)
                : mdSlot(base + close + 3, caret)) +
              "</span></span>",
            next: denClose + 1
          };
        }
      }
      return {
        html:
          "(" + mdRenderRange(text.substring(index + 1, close), base + index + 1, caret) + ")",
        next: close + 1
      };
    }
    // `√(x)` / `√[n](x)` — daraja KATAKCHASI bilan.
    if (ch === "\u221A" || mdStarts(text, index, "sqrt")) {
      return mdRoot(text, index, base, caret, ch === "\u221A" ? 1 : 4);
    }
    // Legacy: `∛x` / `cbrt(x)` — 3-darajali ildiz (moslik uchun saqlanadi).
    if (ch === "\u221B" || mdStarts(text, index, "cbrt")) {
      var cbrtHead = ch === "\u221B" ? 1 : 4;
      var rad3 = mdRadicand(text, index + cbrtHead, base, caret);
      return {
        html:
          '<span class="m-root-wrap"><span class="m-index">3</span>\u221A' +
          '<span class="m-root">' +
          rad3.html +
          "</span></span>",
        next: rad3.next
      };
    }
    if (ch === "|") {
      var bar = text.indexOf("|", index + 1);
      if (bar < 0) {
        return { html: mdEscape(ch), next: index + 1 };
      }
      return {
        html:
          "|" + mdRenderRange(text.substring(index + 1, bar), base + index + 1, caret) + "|",
        next: bar + 1
      };
    }
    if (mdIsDigit(ch) || ch === ".") {
      var end = index;
      while (end < text.length && (mdIsDigit(text.charAt(end)) || text.charAt(end) === ".")) {
        end += 1;
      }
      var digits = "";
      for (var k = index; k < end; k += 1) {
        digits += mdEscape(text.charAt(k));
        if (k < end - 1) {
          digits += mark(base + k + 1);
        }
      }
      return { html: digits, next: end };
    }
    // Logarifm: `log_2(8)` → `log` + KICHIK asos + argument (Word kabi).
    // Bo'sh asos/argument — bosiladigan KATAKCHA (foydalanuvchi qayerga
    // yozishini KO'RADI). Sintaksis o'zgarmaydi (`log_2(8)`) — server ham,
    // lokal hisoblash ham uni allaqachon qo'llab-quvvatlaydi.
    if (mdStarts(text, index, "log_")) {
      var after = index + 4;
      var baseEnd = after;
      while (baseEnd < text.length && mdIsDigit(text.charAt(baseEnd))) {
        baseEnd += 1;
      }
      var baseHtml =
        baseEnd > after
          ? mdRenderRange(text.substring(after, baseEnd), base + after, caret)
          : mdSlot(base + after, caret, "m-slot-log");
      // Kursor token ICHIDA, lekin katakchaga tushmagan bo'lsa — `log` dan
      // keyin ko'rsatamiz (aks holda kursor KO'RINMAY qolardi).
      var innerCaret = caret > index && caret < base + after ? CARET_HTML : "";
      var logHtml =
        "log" + innerCaret + '<sub class="m-logbase">' + baseHtml + "</sub>";
      if (text.charAt(baseEnd) === "(") {
        var argClose = mdMatchParen(text, baseEnd);
        if (argClose >= 0) {
          var argRaw = text.substring(baseEnd + 1, argClose);
          if (!argRaw) {
            return {
              html: logHtml + mdSlot(base + baseEnd + 1, caret),
              next: argClose + 1
            };
          }
          return {
            html:
              logHtml +
              "(" + mdRenderRange(argRaw, base + baseEnd + 1, caret) + ")",
            next: argClose + 1
          };
        }
      }
      return { html: logHtml, next: baseEnd };
    }
    var word = /^[A-Za-z]+/.exec(text.substring(index));
    if (word) {
      return { html: mdEscape(word[0]), next: index + word[0].length };
    }
    return { html: mdEscape(ch), next: index + 1 };
  }

  /** Ketma-ketlikni chizadi: daraja `<sup>`, caret `|`. */
  function mdRenderRange(text, base, caret) {
    var out = "";
    var index = 0;
    var b = typeof base === "number" ? base : 0;
    var at = typeof caret === "number" ? caret : -1;
    var mark = function (position) {
      return position === at ? CARET_HTML : "";
    };
    out += mark(b);
    while (index < text.length) {
      var atom = mdRenderAtom(text, index, b, at);
      index = atom.next;
      out += atom.html;
      if (text.charAt(index) === "^") {
        out += mark(b + index);
        index += 1;
        out += mark(b + index);
        var power = mdExponent(text, index, b, at);
        index = power.next;
        out += "<sup>" + power.html + "</sup>";
      } else {
        out += mark(b + index);
      }
    }
    return out;
  }

  /**
   * Faqat UI: ifodani HTML ko'rinishida chizadi (machine-string tegilmaydi).
   * `caret` — absolut caret indeksi (shu joyga `|` qo'yiladi); berilmasa — yo'q.
   * Katakchalar (`m-slot`) `data-off` bilan caret manzilini saqlaydi.
   */
  function renderExpression(text, caret) {
    return mdRenderRange(
      String(text == null ? "" : text),
      0,
      typeof caret === "number" ? caret : -1
    );
  }
  /** Burchak rejimini ifoda matniga "muhrlaydi" (machine-string). */
  function composeExpression(text, mode) {
    var body = String(text == null ? "" : text);
    // `normalize` oxirgi `=` dan keyingisini oladi (masalan `x=5` -> `5`).
    // Shu sababli `=` AVVAL qirqiladi: aks holda u wrapper ichida qolib
    // `deg(=5)` -> `"5)"` -> `evaluate = None` bo'lardi (D2 regressiyasi).
    var equalAt = body.lastIndexOf("=");
    if (equalAt >= 0) {
      body = body.slice(equalAt + 1);
    }
    if (!body) {
      return "";
    }
    return (mode === "rad" ? "rad(" : "deg(") + body + ")";
  }

  /** Machine-stringdan rejimni ajratadi: { text, mode } (mode null — legacy). */
  function unwrapExpression(machine) {
    var body = String(machine == null ? "" : machine);
    var names = ["deg", "rad"];
    for (var i = 0; i < names.length; i += 1) {
      var name = names[i];
      if (body.length > name.length + 2 && body.substr(0, name.length + 1) === name + "(") {
        var close = mdMatchParen(body, name.length);
        if (close === body.length - 1) {
          return { text: body.substring(name.length + 1, close), mode: name };
        }
      }
    }
    return { text: body, mode: null };
  }
  // --- [PURE-END] ----------------------------------------------------------

  function renderKeys() {
    if (!keysBox) {
      return;
    }
    const layout = mode === "math" ? LAYOUT_MATH_V2 : LAYOUT_BASIC;
    keysBox.innerHTML = "";
    layout.forEach(function (row) {
      const rowBox = document.createElement("div");
      rowBox.className = "math-row";
      row.forEach(function (rawKey) {
        const key = normalizeKey(rawKey);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "math-key" + (key.cls ? " " + key.cls : "");
        button.textContent = key.label;
        button.setAttribute("aria-label", key.label);
        button.addEventListener("click", function (event) {
          event.preventDefault();
          haptic();
          // Admin «Qulay kiritish» maydoni ulangan bo'lsa — panel shu
          // `<input>` ga yozadi (foydalanuvchi paneli bilan bir xil ishlaydi).
          if (applyKeyToInput(key)) {
            return;
          }
          if (key.action === "backspace") {
            if (handlers.onBackspace) {
              handlers.onBackspace();
            }
            return;
          }
          if (key.action === "clear") {
            if (handlers.onClear) {
              handlers.onClear();
            }
            return;
          }
          if (key.action === "left" || key.action === "right" || key.action === "delete") {
            if (key.action === "left" && handlers.onLeft) {
              handlers.onLeft();
            } else if (key.action === "right" && handlers.onRight) {
              handlers.onRight();
            } else if (key.action === "delete" && handlers.onDelete) {
              handlers.onDelete();
            }
            return;
          }
          if (key.action === "confirm") {
            if (handlers.onConfirm) {
              handlers.onConfirm();
            }
            return;
          }
          if (key.action === "fraction") {
            if (handlers.onFraction) {
              handlers.onFraction();
            }
            return;
          }
          // `÷` — terilgan qismni suratga o'tkazib, kursorni maxrajga tushiradi.
          if (key.action === "smartfraction") {
            if (handlers.onSmartFraction) {
              handlers.onSmartFraction();
            }
            return;
          }
          if (key.insert && handlers.onInsert) {
            handlers.onInsert(key.insert, key.caretBack || 0);
          }
        });
        rowBox.appendChild(button);
      });
      keysBox.appendChild(rowBox);
    });
  }

  function updateModeButtons() {
    const basic = byId("math-mode-basic");
    const math = byId("math-mode-math");
    if (basic) {
      basic.classList.toggle("active", mode !== "math");
    }
    if (math) {
      math.classList.toggle("active", mode === "math");
    }
  }

  /** Rejimni almashtiradi ("basic" | "math") va tanlovni eslab qoladi. */
  function setMode(next) {
    mode = next === "math" ? "math" : "basic";
    storageSet(MODE_KEY, mode);
    renderKeys();
    updateModeButtons();
  }

  /* -------------------------------------------------------------------------
     ADMIN REJIMI: panel oddiy `<input>` ga ham yozadi (test yaratish bo'limi,
     36–45 javob maydonlari). Foydalanuvchi oqimida esa katakka yozadi
     (`handlers` orqali) — bu rejim faqat maydon fokusda bo'lganda yoqiladi.
  ------------------------------------------------------------------------- */
  let boundInput = null;

  /** Panelni `<input>` ga ulaydi (null berilsa — uzadi). */
  function bindInput(node) {
    boundInput = node || null;
  }

  function caretToInput(index) {
    if (!boundInput) {
      return;
    }
    try {
      boundInput.setSelectionRange(index, index);
    } catch (error) {
      /* ba'zi brauzerlarda ruxsat yo'q — e'tiborsiz */
    }
  }

  /** Ulangan maydonga matnni yozadi, kursorni qo'yadi va UI ni yangilaydi. */
  function writeInput(text, caret) {
    if (!boundInput) {
      return;
    }
    boundInput.value = text;
    caretToInput(caret);
    boundInput.dispatchEvent(new Event("input", { bubbles: true }));
    updateInputHint();
  }

  /** `÷` (smart kasr) — ulangan maydonda ham xuddi shunday ishlaydi. */
  function smartFractionInInput() {
    if (!boundInput) {
      return;
    }
    const value = String(boundInput.value || "");
    const at =
      typeof boundInput.selectionStart === "number"
        ? boundInput.selectionStart
        : value.length;
    const left = value.slice(0, at);
    const right = value.slice(at);
    if (!left) {
      writeInput("()/(" + right + ")", 1);
      return;
    }
    writeInput("(" + left + ")/(" + right + ")", left.length + 4 + right.length);
  }

  /** Ulangan maydon uchun natija ko'rsatkichi (faqat UI). */
  function updateInputHint() {
    if (!boundInput) {
      return;
    }
    const raw = String(boundInput.value || "").trim();
    if (!raw) {
      setHint("", null);
      return;
    }
    let value = null;
    try {
      value = evaluate(raw);
    } catch (error) {
      value = null;
    }
    if (value === null || value === undefined || !isFinite(value)) {
      setHint("Hozircha hisoblanmayapti — ifodani tugating", "error");
      return;
    }
    setHint("= " + formatValue(value), "ok");
  }

  /**
   * Panel tugmasini ulangan `<input>` ichida bajaradi.
   *
   * @returns {boolean} `true` — tugma shu yerda bajarildi (handlers chaqirilmaydi).
   */
  function applyKeyToInput(key) {
    if (!boundInput) {
      return false;
    }
    const value = String(boundInput.value || "");
    const start =
      typeof boundInput.selectionStart === "number"
        ? boundInput.selectionStart
        : value.length;
    const end =
      typeof boundInput.selectionEnd === "number" &&
      boundInput.selectionEnd >= start
        ? boundInput.selectionEnd
        : start;

    if (key.action === "backspace") {
      writeInput(
        start > 0 ? value.slice(0, start - 1) + value.slice(start) : value,
        Math.max(0, start - 1)
      );
      return true;
    }
    if (key.action === "delete") {
      writeInput(
        end < value.length
          ? value.slice(0, start) + value.slice(end + 1)
          : value,
        start
      );
      return true;
    }
    if (key.action === "left") {
      caretToInput(Math.max(0, start - 1));
      return true;
    }
    if (key.action === "right") {
      caretToInput(Math.min(value.length, end + 1));
      return true;
    }
    if (key.action === "clear") {
      writeInput("", 0);
      return true;
    }
    if (key.action === "smartfraction") {
      smartFractionInInput();
      return true;
    }
    if (key.action === "fraction") {
      // Maydonda modal ochilmaydi — bo'sh kasr ochiladi (`÷` — asosiy usul).
      writeInput(value.slice(0, start) + "()/()" + value.slice(end), start + 1);
      return true;
    }
    if (key.action === "confirm") {
      // Tayyor — maydonni yopamiz (klaviatura yig'iladi).
      try {
        boundInput.blur();
      } catch (error) {
        /* e'tiborsiz */
      }
      return true;
    }
    if (key.insert) {
      const back = Math.max(0, Math.round(Number(key.caretBack) || 0));
      writeInput(
        value.slice(0, start) + key.insert + value.slice(end),
        start + key.insert.length - back
      );
      return true;
    }
    return false;
  }

  /**
   * Panelni katakka ulaydi va ko'rsatadi.
   *
   * @param {string} cellId — katak identifikatori ("38", kelajakda "38b").
   * @param {{label?: string}} options — sarlavhada ko'rinadigan matn.
   */
  function attach(cellId, options) {
    activeId = cellId;
    const opts = options || {};
    if (targetBox) {
      targetBox.textContent = opts.label || cellId;
    }
    setHint("", null);
    if (panel) {
      panel.classList.remove("hidden");
    }
    document.body.classList.add("panel-open");
  }

  /** Panelni yopadi va aktiv katakni bo'shatadi. */
  function detach() {
    activeId = null;
    if (panel) {
      panel.classList.add("hidden");
    }
    document.body.classList.remove("panel-open");
    setHint("", null);
  }

  /**
   * Panel sarlavhasi ostidagi izoh — foydalanuvchi nima saqlanishini ko'radi.
   *
   * @param {string} text — o'zbekcha izoh (masalan "= 3.2361").
   * @param {string|null} kind — "ok" | "error" | null.
   */
  function setHint(text, kind) {
    if (!hintBox) {
      return;
    }
    hintBox.textContent = text || "";
    hintBox.className = "math-hint" + (kind ? " " + kind : "");
  }

  function currentTarget() {
    return activeId;
  }

  /** Joriy burchak rejimi ("deg" | "rad"). */
  function getAngleMode() {
    return angleMode;
  }

  /** Burchak rejimini o'rnatadi, saqlaydi va tugmani yangilaydi. */
  function setAngleMode(mode) {
    angleMode = mode === "rad" ? "rad" : "deg";
    storageSet(ANGLE_KEY, angleMode);
    updateAngleButton();
    if (handlers.onAngle) {
      handlers.onAngle(angleMode);
    }
  }

  /** DEG ↔ RAD almashtirish. */
  function toggleAngleMode() {
    setAngleMode(angleMode === "deg" ? "rad" : "deg");
  }

  /** Joriy rejim bilan machine-string quradi (server shu matnni oladi).
   * `√[n](x)` server uchun `(x)^(1/(n))` ga aylantiriladi — grading ishlaydi.
   */
  function machineExpression(text) {
    return composeExpression(expandRootDegrees(text), angleMode);
  }

  function updateAngleButton() {
    const button = byId("math-angle");
    if (button) {
      button.textContent = angleMode === "deg" ? "DEG" : "RAD";
    }
  }

  /** Komponentni ishga tushiradi (bir marta chaqiriladi). */
  function init(options) {
    handlers = Object.assign(
      {
        onInsert: null, onBackspace: null, onClear: null, onClose: null,
        onLeft: null, onRight: null, onDelete: null, onFraction: null,
        onAngle: null, onConfirm: null,
      },
      options || {}
    );
    panel = byId("math-panel");
    if (panel) {
      // Admin rejimida panel tugmasini bosganda `<input>` fokusdan
      // chiqmasligi kerak (aks holda maydon "blur" bo'lib panel yopiladi).
      panel.addEventListener("mousedown", function (event) {
        if (boundInput && event.target !== boundInput) {
          event.preventDefault();
        }
      });
    }
    keysBox = byId("math-keys");
    targetBox = byId("math-target");
    hintBox = byId("math-hint");

    const saved = storageGet(MODE_KEY);
    mode = saved === "math" ? "math" : "basic";
    const savedAngle = storageGet(ANGLE_KEY);
    angleMode = savedAngle === "rad" ? "rad" : "deg";
    renderKeys();
    updateModeButtons();
    updateAngleButton();

    const basicBtn = byId("math-mode-basic");
    const mathBtn = byId("math-mode-math");
    const closeBtn = byId("math-close");
    if (basicBtn) {
      basicBtn.addEventListener("click", function () {
        setMode("basic");
      });
    }
    if (mathBtn) {
      mathBtn.addEventListener("click", function () {
        setMode("math");
      });
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        detach();
        if (handlers.onClose) {
          handlers.onClose();
        }
      });
    }
    const angleBtn = byId("math-angle");
    if (angleBtn) {
      angleBtn.addEventListener("click", function () {
        toggleAngleMode();
      });
    }
  }

  window.MathPanel = {
    init: init,
    attach: attach,
    detach: detach,
    setMode: setMode,
    setHint: setHint,
    currentTarget: currentTarget,
    /* Hisoblash yordamchilari (queue.js ishlatadi). */
    evaluate: evaluate,
    formatValue: formatValue,
    /* Caret tahriri / kasr konstruktori / renderer (faqat UI; queue.js). */
    insertAt: insertAt,
    deleteBefore: deleteBefore,
    deleteAt: deleteAt,
    buildFraction: buildFraction,
    renderExpression: renderExpression,
    // Admin rejimi (test yaratish): panel oddiy `<input>` ga yozadi.
    bindInput: bindInput,
    unbindInput: bindInput,
    /* Ifodani normallashtirish — transport/kelajak uchun. Xulq o'zgarmaydi. */
    normalizeExpression: normalizeExpression,
    /* Burchak rejimi (DEG/RAD) — ifoda matnida saqlanadi. */
    getAngleMode: getAngleMode,
    setAngleMode: setAngleMode,
    toggleAngleMode: toggleAngleMode,
    machineExpression: machineExpression,
    unwrapExpression: unwrapExpression,
  };

  // --- Ifodani hisoblash ----------------------------------------------------
  /**
   * Matematik ifodani hisoblashga tayyorlaydi.
   *
   * "x=5" → "5" (oxirgi `=` dan keyingi qism), `π` → `pi`, `√` → `sqrt`,
   * `∛` → `cbrt`, `%` → `/100`, `×` → `*`, `÷` → `/`, `,` → `.`.
   */
  /**
   * `√[n](x)` → `(x)^(1/(n))` — BAHOLASH uchun (UI matni o'zgarmaydi).
   * `√[](x)` / `√(x)` — kvadrat ildiz. Shu tufayli foydalanuvchi
   * katakchaga ixtiyoriy daraja (3, 5, 6, n…) yozishi mumkin.
   */
  function expandRootDegrees(text) {
    return String(text == null ? "" : text).replace(
      /\u221A\[([^\[\]()]*)\]\(([^()]*)\)/g,
      function (all, degree, body) {
        var d = mdTrim(degree);
        if (!d || d === "2") {
          return "\u221A(" + body + ")";
        }
        return "(" + body + ")^(1/(" + d + "))";
      }
    );
  }

  function normalizeExpression(text) {
    text = expandRootDegrees(text);
    let value = String(text || "");
    const equalAt = value.lastIndexOf("=");
    if (equalAt >= 0) {
      value = value.slice(equalAt + 1);
    }
    return expandBaseLog(
      value
        .replace(/[\u2212\u2013\u2014]/g, "-")
        .replace(/[\u00D7\u00B7]/g, "*")
        .replace(/\u00F7/g, "/")
        .replace(/,/g, ".")
        .replace(/\u03C0/g, "pi")
        .replace(/\u221A/g, "sqrt")
        .replace(/\u221B/g, "cbrt")
        .replace(/%/g, "/100")
        .replace(/\s+/g, "")
    );
  }

  /** Yopilmagan qavslarni avtomatik yopadi (`√(5` → `√(5)`). */
  function balanceParentheses(text) {
    let open = 0;
    for (let index = 0; index < text.length; index += 1) {
      if (text[index] === "(") {
        open += 1;
      } else if (text[index] === ")") {
        open -= 1;
      }
    }
    if (open <= 0) {
      return text;
    }
    return text + ")".repeat(open);
  }

  /** `arcctg` (kotangens arkk) — qiymat oralig'i (0, π). */
  function acot(value) {
    return Math.PI / 2 - Math.atan(value);
  }

  /**
   * Bir o'tishda `log_<asos>(<argument>)` ni `log(arg)/log(asos)` ga aylantiradi.
   *
   * Asos — faqat butun son (raqamlar); argument — qavs ichida. Mos yopiluvchi
   * qavs bo'lmasa — oxirigacha argument deb olinadi (`balanceParentheses` bilan
   * bir xil). Asos raqam bo'lmasa yoki `(` bo'lmasa — matn tegilmaydi.
   */
  function expandBaseLogOnce(text) {
    let out = "";
    let index = 0;
    while (index < text.length) {
      if (text.startsWith("log_", index)) {
        let baseEnd = index + 4;
        while (baseEnd < text.length && text[baseEnd] >= "0" && text[baseEnd] <= "9") {
          baseEnd += 1;
        }
        if (baseEnd > index + 4 && baseEnd < text.length && text[baseEnd] === "(") {
          let depth = 0;
          let close = baseEnd;
          while (close < text.length) {
            if (text[close] === "(") {
              depth += 1;
            } else if (text[close] === ")") {
              depth -= 1;
              if (depth === 0) {
                break;
              }
            }
            close += 1;
          }
          const base = text.slice(index + 4, baseEnd);
          if (close < text.length) {
            out += "(log(" + text.slice(baseEnd + 1, close) + ")/log(" + base + "))";
            index = close + 1;
          } else {
            out += "(log(" + text.slice(baseEnd + 1) + ")/log(" + base + "))";
            index = text.length;
          }
          continue;
        }
      }
      out += text[index];
      index += 1;
    }
    return out;
  }

  /**
   * `log_a(b)` → `log(b)/log(a)` (barqaror holatga qadar takrorlanadi).
   *
   * Nested yozuv (`log_2(log_2(4))`) keyingi o'tishda almashtiriladi; o'zgarish
   * bo'lmasa tsikl to'xtaydi (`log(` endi `log_` bilan boshlanmaydi).
   */
  function expandBaseLog(text) {
    let result = text;
    for (let pass = 0; pass < 1000; pass += 1) {
      const expanded = expandBaseLogOnce(result);
      if (expanded === result) {
        return result;
      }
      result = expanded;
    }
    return result;
  }

  /**
   * Ifodani hisoblaydi (xavfsiz rekursiv tushish parseri; `eval` YO'Q).
   *
   * Qo'llab-quvvatlanadi: `+ - * / ^`, qavslar, `|x|`, `sqrt()`, `cbrt()`,
   * `pi`, yashirin ko'paytma (`2π`, `3(4)`, `2sin(30)`) hamda maktab
   * funksiyalari: `sin cos tg ctg arcsin arccos arctg arcctg lg ln log`.
   * Burchak rejimi: `deg(...)` ichida gradus, `rad(...)` ichida radian
   * (wrapper'siz — legacy radian); `log_a(b)` → `log(b)/log(a)`.
   *
   * @returns {number|null} son yoki `null` (hisoblab bo'lmasa).
   */
  function evaluate(expression) {
    const text = balanceParentheses(normalizeExpression(expression));
    if (!text) {
      return null;
    }
    let index = 0;
    let deg = false; // `deg(...)` ichida true; standart — radian

    function peek() {
      return text[index] || "";
    }

    function startsWith(word) {
      return text.slice(index, index + word.length) === word;
    }

    function isDigitAt(position) {
      const ch = text[position] || "";
      return ch >= "0" && ch <= "9";
    }

    function toRad(value) {
      return deg ? value * (Math.PI / 180) : value;
    }

    function fromRad(value) {
      return deg ? value * (180 / Math.PI) : value;
    }

    function parseScoped(degrees) {
      const saved = deg;
      deg = degrees;
      let value;
      try {
        value = parseExpression();
      } finally {
        deg = saved;
      }
      if (peek() !== ")") {
        throw new Error("qavs yopilmagan");
      }
      index += 1;
      return value;
    }

    function parseExpression() {
      let value = parseTerm();
      for (;;) {
        const ch = peek();
        if (ch === "+") {
          index += 1;
          value += parseTerm();
        } else if (ch === "-") {
          index += 1;
          value -= parseTerm();
        } else {
          break;
        }
      }
      return value;
    }

    function parseTerm() {
      let value = parseUnary();
      for (;;) {
        const ch = peek();
        if (ch === "*") {
          index += 1;
          value *= parseUnary();
        } else if (ch === "/") {
          index += 1;
          const divisor = parseUnary();
          if (divisor === 0) {
            throw new Error("nolga bo'lish");
          }
          value /= divisor;
        } else if (
          ch === "(" ||
          startsWith("pi") ||
          startsWith("sqrt") ||
          startsWith("cbrt") ||
          startsWith("sin") ||
          startsWith("cos") ||
          startsWith("tg") ||
          startsWith("ctg") ||
          startsWith("arcsin") ||
          startsWith("arccos") ||
          startsWith("arctg") ||
          startsWith("arcctg") ||
          startsWith("lg") ||
          startsWith("ln") ||
          startsWith("log") ||
          startsWith("deg") ||
          startsWith("rad") ||
          isDigitAt(index) ||
          ch === "."
        ) {
          value *= parseUnary(); // yashirin ko'paytma: 2π, 3(4), 2sqrt(9)
        } else {
          break;
        }
      }
      return value;
    }

    function parseUnary() {
      const ch = peek();
      if (ch === "-") {
        index += 1;
        return -parseUnary();
      }
      if (ch === "+") {
        index += 1;
        return parseUnary();
      }
      if (startsWith("sqrt")) {
        index += 4;
        return Math.sqrt(parseUnary());
      }
      if (startsWith("cbrt")) {
        index += 4;
        return Math.cbrt(parseUnary());
      }
      if (startsWith("deg")) {
        index += 3;
        if (peek() !== "(") {
          throw new Error("deg(...) uchun qavs kerak");
        }
        index += 1;
        return parseScoped(true);
      }
      if (startsWith("rad")) {
        index += 3;
        if (peek() !== "(") {
          throw new Error("rad(...) uchun qavs kerak");
        }
        index += 1;
        return parseScoped(false);
      }
      if (startsWith("arcsin")) {
        index += 6;
        return fromRad(Math.asin(parseUnary()));
      }
      if (startsWith("arccos")) {
        index += 6;
        return fromRad(Math.acos(parseUnary()));
      }
      if (startsWith("arctg")) {
        index += 5;
        return fromRad(Math.atan(parseUnary()));
      }
      if (startsWith("arcctg")) {
        index += 6;
        return fromRad(acot(parseUnary()));
      }
      if (startsWith("sin")) {
        index += 3;
        return Math.sin(toRad(parseUnary()));
      }
      if (startsWith("cos")) {
        index += 3;
        return Math.cos(toRad(parseUnary()));
      }
      if (startsWith("tg")) {
        index += 2;
        return Math.tan(toRad(parseUnary()));
      }
      if (startsWith("ctg")) {
        index += 3;
        return 1 / Math.tan(toRad(parseUnary()));
      }
      if (startsWith("lg")) {
        index += 2;
        return Math.log10(parseUnary());
      }
      if (startsWith("ln")) {
        index += 2;
        return Math.log(parseUnary());
      }
      if (startsWith("log")) {
        index += 3;
        return Math.log10(parseUnary());
      }
      return parsePower();
    }

    function parsePower() {
      const base = parsePrimary();
      if (peek() === "^") {
        index += 1;
        return Math.pow(base, parseUnary()); // o'ngga assotsiativ
      }
      return base;
    }

    function parsePrimary() {
      const ch = peek();
      if (ch === "(") {
        index += 1;
        const value = parseExpression();
        if (peek() !== ")") {
          throw new Error("qavs yopilmagan");
        }
        index += 1;
        return value;
      }
      if (ch === "|") {
        index += 1;
        const value = Math.abs(parseExpression());
        if (peek() !== "|") {
          throw new Error("| yopilmagan");
        }
        index += 1;
        return value;
      }
      if (startsWith("pi")) {
        index += 2;
        return Math.PI;
      }
      if (isDigitAt(index) || ch === ".") {
        const start = index;
        while (index < text.length && /[0-9.]/.test(text[index])) {
          index += 1;
        }
        const value = Number(text.slice(start, index));
        if (!Number.isFinite(value)) {
          throw new Error("son noto'g'ri");
        }
        return value;
      }
      throw new Error("kutilmagan belgi");
    }

    try {
      const value = parseExpression();
      if (index !== text.length) {
        return null; // hisoblanmagan qoldiq bor
      }
      return Number.isFinite(value) ? value : null;
    } catch (error) {
      return null;
    }
  }

  /**
   * Hisoblangan sonni server qabul qiladigan matnga aylantiradi.
   *
   * 4 kasr xonaga yumaloqlanadi (`\d{1,4}` cheklovi), ortiqcha nollar olib
   * tashlanadi; |qiymat| ≥ 10^7 bo'lsa qabul qilinmaydi.
   *
   * @returns {string|null} masalan "3.2361" · "8" · "-0.5"
   */
  function formatValue(value) {
    if (!Number.isFinite(value)) {
      return null;
    }
    const rounded = Math.round(value * 10000) / 10000;
    if (Math.abs(rounded) >= 1e7) {
      return null;
    }
    let text = rounded.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
    if (text === "-0" || text === "") {
      text = "0";
    }
    return NUMBER_RE.test(text) ? text : null;
  }


})();
