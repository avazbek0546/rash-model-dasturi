/* ---------------------------------------------------------------------------
   «⚙️ Test yaratish» — faqat o'qituvchi (admin) uchun Mini App paneli.
   Ishonch: tugma `/api/v2/me` orqali ko'rsatiladi, LEKIN barcha so'rovlar
   serverda alohida tekshiriladi (403) — frontend yashirishi xavfsizlik emas.
--------------------------------------------------------------------------- */
(function () {
  "use strict";

  const FIELDS = [
    "admin-title",
    "admin-code",
    "admin-total",
    "admin-key",
    "admin-difficulty",
    "admin-start",
    "admin-end",
    "admin-result",
  ];

  function el(id) {
    return document.getElementById(id);
  }

  function value(id) {
    const node = el(id);
    return node ? String(node.value || "").trim() : "";
  }

  function clearForm() {
    FIELDS.forEach(function (id) {
      const node = el(id);
      if (node) {
        node.value = "";
      }
    });
  }

  function renderExams(rows) {
    const root = el("admin-exams");
    if (!root) {
      return;
    }
    if (!rows.length) {
      root.innerHTML = '<p class="muted">Hozircha imtihon yaratilmagan.</p>';
      return;
    }
    root.innerHTML = rows
      .map(function (row) {
        const total = Number(row.solutions_total || 0);
        const covered = Number(row.solutions_covered || 0);
        const percent = total ? Math.round((covered * 100) / total) : 0;
        const coverage =
          total > 0
            ? '<div class="meta">🎬 Yechimlar: <b>' +
              covered +
              " / " +
              total +
              "</b> (" +
              percent +
              "%)</div>"
            : "";
        return (
          '<div class="admin-card">' +
          '<div class="head"><span class="name">' +
          App.escape(row.title) +
          '</span><span class="badge ' +
          App.escape(row.status) +
          '">' +
          App.escape(row.status_title) +
          "</span></div>" +
          '<div class="meta">Kod: <b>' +
          App.escape(row.test_code) +
          "</b> · " +
          row.total_questions +
          " savol · " +
          row.submissions +
          " javob</div>" +
          coverage +
          '<div class="actions">' +
          '<button type="button" class="solutions" data-exam="' +
          row.exam_id +
          '" title="Video/rasm yechimlar">🎬 Yechim</button>' +
          '<button type="button" class="report" data-exam="' +
          row.exam_id +
          '" title="PDF hisobot">📄 PDF</button>' +
          '<button type="button" class="ghost regrade" data-exam="' +
          row.exam_id +
          '" title="Qayta baholash">🔄 Baholash</button>' +
          "</div></div>"
        );
      })
      .join("");
    root.querySelectorAll(".report").forEach(function (button) {
      button.addEventListener("click", function () {
        report(Number(button.dataset.exam));
      });
    });
    root.querySelectorAll(".regrade").forEach(function (button) {
      button.addEventListener("click", function () {
        regrade(Number(button.dataset.exam));
      });
    });
    root.querySelectorAll(".solutions").forEach(function (button) {
      button.addEventListener("click", function () {
        openSolutions(Number(button.dataset.exam));
      });
    });
  }

  function loadExams() {
    const root = el("admin-exams");
    if (root) {
      root.innerHTML = '<div class="spinner"></div>';
    }
    API.get("/api/v2/admin/exams")
      .then(function (data) {
        renderExams((data && data.exams) || []);
      })
      .catch(function (error) {
        if (root) {
          root.innerHTML =
            '<p class="muted">' + App.escape(error.message) + "</p>";
        }
      });
  }

  async function create() {
    // Grid → kanonik matn (agar foydalanuvchi griddan kiritgan bo'lsa).
    syncKeyText();
    const body = {
      title: value("admin-title"),
      test_code: value("admin-code"),
      total_questions: Number(value("admin-total") || 0),
      answer_key: value("admin-key"),
      difficulty: value("admin-difficulty"),
      start_time: value("admin-start"),
      end_time: value("admin-end"),
      result_time: value("admin-result"),
    };
    const button = el("admin-create");
    if (button) {
      button.disabled = true;
    }
    try {
      const result = await API.post("/api/v2/admin/exams", body);
      App.setNotice(
        "success",
        "✅ Test yaratildi: " + result.test_code + " (kodni o'quvchilarga bering)",
        false
      );
      clearForm();
      loadExams();
    } catch (error) {
      App.setNotice("error", error.message, false);
    } finally {
      if (button) {
        button.disabled = false;
      }
    }
  }

  /**
   * Blob'ni fayl sifatida yuklab oladi (Telegram WebView'da ham ishlaydi).
   *
   * Nega `openLink` emas? Havolani to'g'ridan-to'g'ri ochishda server xato
   * qaytarsa (`{"ok": false, "error": ...}`) foydalanuvchi brauzerda xom JSON
   * ko'rib qolardi. Endi fayl avval `fetch` bilan olinadi: xato bo'lsa —
   * tushunarli popup, muvaffaqiyat bo'lsa — yuklab olish.
   */
  function downloadBlob(blob, filename) {
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename || "natijalar.pdf";
    anchor.rel = "noopener";
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    // WebView faylni ulgurguncha URL'ni darhol bo'shatmaymiz.
    window.setTimeout(function () {
      URL.revokeObjectURL(objectUrl);
    }, 60000);
  }

  /** `Content-Disposition` sarlavhasidan fayl nomini oladi. */
  function filenameOf(response, fallback) {
    try {
      const header = response.headers.get("Content-Disposition") || "";
      const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
      if (match && match[1]) {
        return decodeURIComponent(match[1]);
      }
    } catch (error) {
      /* sarlavha o'qilmasa — zaxira nom ishlatiladi */
    }
    return fallback || "natijalar.pdf";
  }

  /**
   * «📄 PDF» — o'quvchilar natijalari hisobotini yuklab oladi.
   *
   * Ikki qadam: (1) vaqtinchalik havola olinadi; (2) fayl `fetch` bilan
   * yuklanadi. Shu tufayli server xatosi (masalan, shrift topilmasa) xom JSON
   * ko'rinishida ochilib qolmaydi — foydalanuvchiga aniq xabar chiqadi.
   */
  async function report(examId) {
    const button = document.querySelector('.report[data-exam="' + examId + '"]');
    if (button) {
      button.disabled = true;
    }
    try {
      const link = await API.post(
        "/api/v2/admin/exams/" + examId + "/report-link",
        {}
      );
      const url = link && link.url;
      if (!url) {
        throw new Error("PDF havolasi olinmadi. Qayta urinib ko'ring.");
      }

      const response = await fetch(url);
      if (!response.ok) {
        let message = "";
        try {
          const payload = await response.json();
          message = payload && payload.error ? String(payload.error) : "";
        } catch (error) {
          message = "";
        }
        throw new Error(message || "PDF yasalmadi (HTTP " + response.status + ").");
      }

      const blob = await response.blob();
      if (!blob || blob.size === 0) {
        throw new Error("PDF bo'sh keldi. Qayta urinib ko'ring.");
      }
      downloadBlob(blob, filenameOf(response, "natijalar-" + examId + ".pdf"));
      App.setNotice("success", "📄 PDF yuklab olindi.", true);
    } catch (error) {
      const message = error && error.message ? error.message : "PDF yuklab bo'lmadi.";
      App.setNotice("error", message, false);
      App.alert(message);
    } finally {
      if (button) {
        button.disabled = false;
      }
    }
  }

  async function regrade(examId) {
    const ok = await API.confirm(
      "Bu imtihon qayta baholanadi (kalit yoki qiyinchilik tuzatilgach). Davom etamizmi?"
    );
    if (!ok) {
      return;
    }
    try {
      const result = await API.post(
        "/api/v2/admin/exams/" + examId + "/regrade",
        {}
      );
      App.setNotice("success", "🔄 Qayta baholandi: " + result.graded + " javob", true);
      loadExams();
    } catch (error) {
      App.setNotice("error", error.message, false);
    }
  }

  /* -------------------------------------------------------------------------
     «Qulay kiritish» (Grid) — javoblar kaliti bir bosishda kiritiladi.

     Bu FAQAT ko'rinish: oxirida xuddi shu **kanonik matn** hosil bo'ladi
     (`1A2B…35F|36a:12.5,36b:3`) va maydonga yoziladi — server, baholash va
     baza **o'zgarmaydi** (orqaga moslik saqlanadi).

     36–45 uchun **doim** `a)` va `b)` ikkita maydon (qism kafolati). Bo'sh
     qolgan qism kalitga yozilmaydi va baholashda doim "noto'g'ri" hisoblanadi
     — bu haqda pastda ogohlantirish chiqadi.
  ------------------------------------------------------------------------- */
  const LETTERS_4 = ["A", "B", "C", "D"];
  const LETTERS_6 = ["A", "B", "C", "D", "E", "F"];

  const keyState = { letters: {}, nums: {} };

  function totalQuestions() {
    const raw = Number(value("admin-total") || 0);
    if (!raw || raw < 1) {
      return 45;
    }
    return Math.min(Math.max(Math.round(raw), 1), 200);
  }

  function optionsFor(position) {
    if (position <= 32) {
      return LETTERS_4;
    }
    if (position <= 35) {
      return LETTERS_6;
    }
    return [];
  }

  function partLabels(position) {
    return position >= 36 ? ["a", "b"] : [""];
  }

  function keyCounts() {
    const total = totalQuestions();
    const counts = {
      lettersDone: 0,
      lettersTotal: 0,
      partsDone: 0,
      partsTotal: 0,
    };
    for (let position = 1; position <= total; position += 1) {
      if (optionsFor(position).length) {
        counts.lettersTotal += 1;
        if (keyState.letters[position]) {
          counts.lettersDone += 1;
        }
        continue;
      }
      partLabels(position).forEach(function (part) {
        counts.partsTotal += 1;
        if (String(keyState.nums[position + part] || "").trim()) {
          counts.partsDone += 1;
        }
      });
    }
    return counts;
  }

  /** Kanonik matnni quradi va maydonga yozadi (`|36a:12.5,36b:3`). */
  function syncKeyText() {
    const total = totalQuestions();
    const compact = [];
    const numeric = [];
    for (let position = 1; position <= total; position += 1) {
      if (optionsFor(position).length) {
        const letter = keyState.letters[position];
        if (letter) {
          compact.push(position + letter);
        }
        continue;
      }
      partLabels(position).forEach(function (part) {
        const raw = String(keyState.nums[position + part] || "").trim();
        if (raw) {
          numeric.push(position + part + ":" + raw);
        }
      });
    }
    const text =
      compact.join("") + (numeric.length ? "|" + numeric.join(",") : "");
    const area = el("admin-key");
    if (area) {
      area.value = text;
    }
    refreshKeyStatus();
  }

  function refreshKeyStatus() {
    const counts = keyCounts();
    const node = el("key-count");
    if (node) {
      const full =
        counts.lettersTotal > 0 &&
        counts.lettersDone === counts.lettersTotal &&
        counts.partsDone === counts.partsTotal;
      node.textContent =
        "Variantlar " +
        counts.lettersDone +
        "/" +
        counts.lettersTotal +
        " · Sonli " +
        counts.partsDone +
        "/" +
        counts.partsTotal;
      node.className = "key-count" + (full ? " ok" : " warn");
    }
    const warn = el("key-warn");
    if (warn) {
      const empty = [];
      const total = totalQuestions();
      for (let position = 1; position <= total; position += 1) {
        if (optionsFor(position).length) {
          continue;
        }
        partLabels(position).forEach(function (part) {
          if (!String(keyState.nums[position + part] || "").trim()) {
            empty.push(position + part);
          }
        });
      }
      warn.textContent = empty.length
        ? "⚠️ Bo'sh: " + empty.join(", ") + " — bu javoblar noto'g'ri hisoblanadi."
        : "";
    }
  }

  /** Matn (`1A2B…|36a:12.5`) → tahrirlanadigan holat (nusxa ko'chirish uchun). */
  function parseKeyText(raw) {
    keyState.letters = {};
    keyState.nums = {};
    const text = String(raw || "").trim();
    if (!text) {
      return;
    }
    const chunks = text.split("|");
    const head = chunks[0] || "";
    const letterRe = /(\d{1,7})([A-Fa-f])/g;
    let match = letterRe.exec(head);
    while (match !== null) {
      keyState.letters[Number(match[1])] = match[2].toUpperCase();
      match = letterRe.exec(head);
    }
    chunks
      .slice(1)
      .join("|")
      .split(",")
      .forEach(function (piece) {
        const item = piece.trim();
        const sep = item.indexOf(":");
        if (!item || sep < 0) {
          return;
        }
        const found = /^(\d{1,7})([a-bA-B]?)$/.exec(item.slice(0, sep).trim());
        if (!found) {
          return;
        }
        const position = Number(found[1]);
        if (optionsFor(position).length) {
          return;
        }
        // Belgilanmagan (`36:12.5`) — `a` qismiga tushadi
        // (`form_builder` bilan bir xil qoida).
        const part = (found[2] || "a").toLowerCase();
        keyState.nums[position + part] = item.slice(sep + 1).trim();
      });
  }

  function markPartInput(input, raw) {
    const filled = String(raw || "").trim().length > 0;
    input.classList.toggle("filled", filled);
    input.classList.toggle("empty", !filled);
  }

  /** 36–45 maydonlari uchun MATEMATIK PANEL (foydalanuvchilardagi bilan bir xil). */
  function bindMathPanel(input, label) {
    if (!window.MathPanel || typeof window.MathPanel.bindInput !== "function") {
      return;
    }
    input.addEventListener("focus", function () {
      window.MathPanel.bindInput(input);
      if (typeof window.MathPanel.attach === "function") {
        window.MathPanel.attach("admin-" + label, { label: label + ") javobi" });
      }
    });
    input.addEventListener("blur", function () {
      window.MathPanel.unbindInput(null);
      if (typeof window.MathPanel.detach === "function") {
        window.MathPanel.detach();
      }
    });
  }

  /** Bitta savol kartasi: 1–35 → harflar; 36–45 → `a)`/`b)` maydonlari. */
  function buildKeyCard(position) {
    const card = document.createElement("div");
    card.className = "key-card";
    const number = document.createElement("span");
    number.className = "key-num";
    number.textContent = String(position);
    card.appendChild(number);

    const options = optionsFor(position);
    if (options.length) {
      const letters = document.createElement("div");
      letters.className = "key-letters";
      options.forEach(function (letter) {
        const button = document.createElement("button");
        button.type = "button";
        button.className =
          "key-letter" + (keyState.letters[position] === letter ? " active" : "");
        button.textContent = letter;
        button.addEventListener("click", function () {
          // Xuddi shu harfni qayta bosish — javobni o'chiradi (toggle).
          keyState.letters[position] =
            keyState.letters[position] === letter ? "" : letter;
          renderKeyGrid();
          syncKeyText();
        });
        letters.appendChild(button);
      });
      card.appendChild(letters);
      return card;
    }

    const parts = document.createElement("div");
    parts.className = "key-parts";
    partLabels(position).forEach(function (part) {
      const label = document.createElement("span");
      label.className = "key-part-label";
      label.textContent = part + ")";
      parts.appendChild(label);
      const input = document.createElement("input");
      input.type = "text";
      // TELEFON KLAVIATURASI OCHILMAYDI: javob faqat MATEMATIK PANEL orqali
      // kiritiladi (`readonly` + `inputmode="none"` — ishonchli usul).
      input.readOnly = true;
      input.inputMode = "none";
      input.autocomplete = "off";
      input.spellcheck = false;
      input.className = "key-part-input";
      input.placeholder = part;
      input.value = keyState.nums[position + part] || "";
      markPartInput(input, input.value);
      input.addEventListener("input", function () {
        keyState.nums[position + part] = input.value.trim();
        markPartInput(input, input.value);
        syncKeyText();
      });
      // Maydonni MATEMATIK PANELGA ulaydi (√, kasr, daraja, log…).
      bindMathPanel(input, position + part);
      parts.appendChild(input);
    });
    card.appendChild(parts);
    return card;
  }

  /** BARCHA savollar bitta ro'yxatda: 1–35 (harflar) + 36–45 (`a`/`b`). */
  function renderKeyGrid() {
    const box = el("key-grid");
    if (!box) {
      return;
    }
    const total = totalQuestions();
    box.innerHTML = "";
    const optionCount = Math.min(total, 35);
    for (let position = 1; position <= optionCount; position += 1) {
      box.appendChild(buildKeyCard(position));
    }
    for (let position = 36; position <= total; position += 1) {
      box.appendChild(buildKeyCard(position));
    }
    refreshKeyStatus();
  }

  function clearKeyGrid() {
    keyState.letters = {};
    keyState.nums = {};
    renderKeyGrid();
    syncKeyText();
  }

  /** Grid bilan maydonni bog'laydi (matn yozilsa — grid qayta o'qiladi). */
  function initKeyGrid() {
    const area = el("admin-key");
    if (area) {
      area.addEventListener("input", function () {
        parseKeyText(area.value);
        renderKeyGrid();
      });
      parseKeyText(area.value);
    }
    const total = el("admin-total");
    if (total) {
      total.addEventListener("input", function () {
        renderKeyGrid();
        syncKeyText();
      });
    }
    renderKeyGrid();
  }

  /* -------------------------------------------------------------------------
     «🎬 Yechimlar» — qamrov to'ri, video/rasm yuklash, o'chirish.

     Fayllar (video/rasm) FAQAT bot orqali yuklanadi — Telegram `file_id` ni
     faqat Bot API bera oladi, brauzer emas. Matnli yechim qo'llanmaydi.
     Serverda barchasi `ensure_admin` bilan himoyalangan.
  ------------------------------------------------------------------------- */
  const SOL_ICONS = {
    video: "🎬",
    photo: "🖼",
    document: "📄",
    animation: "🎞",
    audio: "🔊",
  };
  let solExam = null;

  function openSolutions(examId) {
    const root = el("sol-panel");
    if (root) {
      root.innerHTML = '<div class="spinner"></div>';
    }
    API.get("/api/v2/admin/exams/" + examId + "/solutions")
      .then(function (data) {
        solExam = data;
        renderSolutions("all");
      })
      .catch(function (error) {
        if (root) {
          root.innerHTML = '<p class="muted">' + App.escape(error.message) + "</p>";
        }
      });
  }

  function renderSolutions(mode) {
    const root = el("sol-panel");
    if (!root || !solExam) {
      return;
    }
    const all = solExam.items || [];
    const items = all.filter(function (item) {
      return mode === "missing" ? !item.covered : true;
    });
    const total = Number(solExam.total || 0);
    const covered = Number(solExam.covered || 0);
    const percent = total ? Math.round((covered * 100) / total) : 0;
    const chips = items
      .map(function (item) {
        const icon = item.covered ? SOL_ICONS[item.type] || "📎" : "⬜";
        return (
          '<button type="button" class="sol-chip' +
          (item.covered ? " ok" : "") +
          '" data-label="' +
          App.escape(item.label) +
          '">' +
          icon +
          " " +
          App.escape(item.label) +
          "</button>"
        );
      })
      .join("");
    root.innerHTML =
      '<div class="sol-head"><b>' +
      App.escape(solExam.title) +
      "</b> · " +
      App.escape(solExam.test_code) +
      "</div>" +
      '<div class="profile-row"><span class="label">Qamrov</span><b>' +
      covered +
      " / " +
      total +
      " (" +
      percent +
      "%)</b></div>" +
      '<div class="progress-track"><div class="progress-bar" style="width:' +
      percent +
      '%"></div></div>' +
      '<div class="sol-filter">' +
      '<button type="button" class="sol-tab' +
      (mode === "all" ? " active" : "") +
      '" data-mode="all">Hammasi</button>' +
      '<button type="button" class="sol-tab' +
      (mode === "missing" ? " active" : "") +
      '" data-mode="missing">⬜ Yetishmayotganlar (' +
      (total - covered) +
      ")</button></div>" +
      '<div class="sol-grid">' +
      (chips || '<p class="muted">Hammasi qoplangan 🎉</p>') +
      "</div>" +
      '<div id="sol-detail" class="sol-detail hidden"></div>';

    root.querySelectorAll(".sol-tab").forEach(function (button) {
      button.addEventListener("click", function () {
        renderSolutions(button.dataset.mode);
      });
    });
    root.querySelectorAll(".sol-chip").forEach(function (button) {
      button.addEventListener("click", function () {
        const found = all.filter(function (entry) {
          return entry.label === button.dataset.label;
        })[0];
        if (found) {
          showSolutionDetail(found);
        }
      });
    });
  }

  /** Detal oynasidagi holat qatori: video/rasm bor-yo'qligi. */
  function solutionStatus(item) {
    if (!item.covered) {
      return '<div class="sol-status missing">⬜ Yechim hali yuklanmagan</div>';
    }
    const icon = SOL_ICONS[item.type] || "📎";
    const title = item.type_title || "yechim";
    return (
      '<div class="sol-status ok">' +
      icon +
      " <b>" +
      App.escape(title) +
      "</b> yuklangan — o'quvchilar tahlilda ko'radi.</div>"
    );
  }

  function showSolutionDetail(item) {
    const box = el("sol-detail");
    if (!box || !solExam) {
      return;
    }
    const upload = solExam.bot_username
      ? '<button type="button" class="sol-upload">🎬 Video yoki 🖼 rasm yuklash</button>' +
        '<p class="muted sol-hint">Tugma botni ochadi — videoni yoki rasmni ' +
        "izohsiz yuboring. Video 50 MB gacha, rasm 10 MB gacha. " +
        "Yuklagach ro'yxatni yangilash uchun «🎬 Yechim»ni qayta bosing.</p>"
      : '<p class="muted sol-hint">Bot manzili aniqlanmadi — sahifani ' +
        "yangilab, qayta urinib ko'ring.</p>";
    box.classList.remove("hidden");
    box.innerHTML =
      "<h3>Savol " +
      App.escape(item.label) +
      "</h3>" +
      solutionStatus(item) +
      upload +
      (item.covered
        ? '<div class="btn-row"><button type="button" class="ghost sol-delete">🗑 Yechimni o\'chirish</button></div>'
        : "") +
      '<div class="btn-row"><button type="button" class="ghost sol-close">Yopish</button></div>';

    const bind = function (selector, handler) {
      const node = box.querySelector(selector);
      if (node) {
        node.addEventListener("click", handler);
      }
    };
    bind(".sol-close", function () {
      box.classList.add("hidden");
    });
    bind(".sol-delete", function () {
      deleteSolution(item);
    });
    bind(".sol-upload", function () {
      openBotUpload(item);
    });
  }

  async function deleteSolution(item) {
    const ok = await API.confirm(
      "«" + item.label + "» savolining yechimi o'chiriladi. Davom etamizmi?"
    );
    if (!ok) {
      return;
    }
    try {
      await API.post("/api/v2/admin/solutions/delete", {
        exam_id: solExam.exam_id,
        question: item.number,
        part: item.part,
      });
      App.setNotice("success", "🗑 O'chirildi: " + item.label, true);
      openSolutions(solExam.exam_id);
    } catch (error) {
      App.setNotice("error", error.message, false);
    }
  }

  /** Botga deep-link: `/start s_<kod>_<belgi>` → bot izohsiz qabul qiladi. */
  function openBotUpload(item) {
    if (!solExam || !solExam.bot_username) {
      return;
    }
    const url =
      "https://t.me/" +
      solExam.bot_username +
      "?start=s_" +
      encodeURIComponent(solExam.test_code) +
      "_" +
      encodeURIComponent(item.label);
    try {
      if (API.tg && typeof API.tg.openTelegramLink === "function") {
        API.tg.openTelegramLink(url);
        return;
      }
      if (API.tg && typeof API.tg.openLink === "function") {
        API.tg.openLink(url);
        return;
      }
    } catch (error) {
      /* pastdagi window.open ishlatiladi */
    }
    window.open(url, "_blank");
  }

  window.addEventListener("DOMContentLoaded", function () {
    App.onShow("admin", loadExams);
    initKeyGrid();

    const createButton = el("admin-create");
    if (createButton) {
      createButton.addEventListener("click", create);
    }
    const resetButton = el("admin-reset");
    if (resetButton) {
      resetButton.addEventListener("click", function () {
        clearForm();
        clearKeyGrid();
      });
    }
  });
})();
