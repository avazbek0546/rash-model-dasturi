/* ---------------------------------------------------------------------------
   "Navbat" bo'limi: test kodini tekshirish, MVP kartochkalari orqali javob
   kiritish (avtomatik saqlash + yangilangandan keyin tiklash) va navbatdagi
   imtihonlar ro'yxati.

   Javob formati (server `layout` maydonidan olinadi):
     1–32   → A B C D          (yopiq)
     33–35  → A B C D E F      (yopiq)
     36–45  → ochiq, sonli javob
--------------------------------------------------------------------------- */
(function () {
  "use strict";

  const STATUS_CLASS = {
    upcoming: "upcoming",
    active: "active",
    closed: "closed",
    published: "published",
  };

  const CODE_KEY = "rasch.last_code";
  const ANSWERS_PREFIX = "rasch.answers.";
  const ATTEMPT_PREFIX = "rasch.attempt.";
  const SEQ_PREFIX = "rasch.seq.";
  const PENDING_PREFIX = "rasch.pending.";
  const NUMERIC_RE = /^-?\d{1,7}([.,]\d{1,4})?$/;
  const SAVE_DEBOUNCE = 300; // ms — belgilashdan keyin serverga saqlash kechikishi
  const RETRY_DELAY = 5000; // ms — tarmoq yo'q bo'lsa qayta urinish oralig'i

  let selectedExam = null;
  let examCode = "";
  let deadline = 0;
  let timer = null;
  let items = [];
  let answers = {};
  let saveTimer = null;
  let submitting = false;
  let activeCell = null; // tanlangan katak id ("38"; kelajakda "38b")
  let cellIndex = {}; // cellId -> { cellId, position, part, kind, options }
  let expressions = {}; // cellId -> foydalanuvchi ifodasi (ko'rsatish uchun)
  let carets = {}; // cellId -> caret pozitsiyasi (0..ifoda uzunligi)

  // --- Item-level autosave holati (`/api/v2/*`) -----------------------------
  // Barcha autosave holati urinishga bog'langan kontekstda turadi (global emas):
  // shu sababli `await` dan keyin holat almashib ketsa ham javoblar aralashmaydi.
  let attemptCtx = null; // joriy urinish konteksti (`createAttemptCtx`)
  let epochCounter = 0; // kontekstlarni ajratuvchi hisoblagich

  function byId(id) {
    return document.getElementById(id);
  }

  function renderExams(exams) {
    const box = byId("exams-list");
    box.innerHTML = "";

    if (!exams.length) {
      box.innerHTML =
        '<p class="muted">Hozircha navbatda imtihon yo\'q. O\'qituvchi imtihon ' +
        "yaratgan zahoti shu yerda ko'rinadi.</p>";
      return;
    }

    exams.forEach(function (exam) {
      const item = document.createElement("div");
      item.className = "exam-item";

      const left = document.createElement("div");
      let meta = App.escape(exam.status_title) + " · " + exam.total_questions + " savol";
      if (exam.status === "active") {
        meta += " · tugash: " + App.escape(exam.end_time_local);
      } else if (exam.status === "upcoming") {
        meta += " · boshlanish: " + App.escape(exam.start_time_local);
      } else {
        meta += " · natija: " + App.escape(exam.result_time_local);
      }
      if (exam.submitted) {
        meta += " · javobingiz yuborilgan";
      }
      left.innerHTML =
        '<div class="title">' +
        App.escape(exam.title) +
        "</div>" +
        '<div class="meta">' +
        meta +
        "</div>";

      const right = document.createElement("div");
      if (exam.published && exam.my_result) {
        right.className = "score-pill";
        right.innerHTML = Math.round(exam.my_result.scaled_score) + "<small>ball</small>";
      } else {
        right.className = "badge " + (STATUS_CLASS[exam.status] || "published");
        right.textContent = exam.status_title;
      }

      item.appendChild(left);
      item.appendChild(right);
      box.appendChild(item);
    });
  }

  async function loadExams() {
    const box = byId("exams-list");
    if (!box.querySelector(".exam-item")) {
      box.innerHTML = '<div class="spinner"></div>';
    }
    try {
      const data = await API.get("/api/exams");
      renderExams(data.exams || []);
    } catch (error) {
      box.innerHTML =
        '<p class="muted">Ro\'yxatni yuklab bo\'lmadi: ' +
        App.escape(error.message) +
        "</p>";
    }
  }

  // --- Avtomatik saqlash (localStorage, xavfsiz) ----------------------------
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
      /* xususiy rejimda ham ilova ishlashda davom etadi */
    }
  }

  function storageRemove(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (error) {
      /* e'tiborsiz */
    }
  }

  function answersKey(examId) {
    return ANSWERS_PREFIX + examId;
  }

  function attemptKey(examId) {
    return ATTEMPT_PREFIX + examId;
  }

  function seqKey(examId) {
    return SEQ_PREFIX + examId;
  }

  function pendingKey(examId) {
    return PENDING_PREFIX + examId;
  }

  function loadAttemptId(examId) {
    const value = Number(storageGet(attemptKey(examId)));
    return Number.isFinite(value) && value > 0 ? value : null;
  }

  function loadSeq(examId) {
    const value = Number(storageGet(seqKey(examId)));
    return Number.isFinite(value) && value > 0 ? value : 0;
  }

  /** Yuborilmagan javoblar `pending`da saqlanadi — refresh ham ularni yo'qotmaydi. */
  function loadPending(examId) {
    const raw = storageGet(pendingKey(examId));
    if (!raw) {
      return {};
    }
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  /** Yuborilmagan navbatni FAQAT shu urinishning kaliti ostiga yozadi. */
  function savePending(ctx) {
    if (!ctx || !ctx.examId) {
      return;
    }
    storageSet(pendingKey(ctx.examId), JSON.stringify(ctx.dirty));
  }

  /** Monoton o'suvchi `client_seq` — urinish konteksti ichida, refreshda davom etadi. */
  function nextSeq(ctx) {
    ctx.seq += 1;
    if (ctx.examId) {
      storageSet(seqKey(ctx.examId), String(ctx.seq));
    }
    return ctx.seq;
  }

  function setNote(text) {
    const note = byId("autosave-note");
    if (note) {
      note.textContent = text;
    }
  }

  function clockText() {
    const date = new Date();
    const pad = function (value) {
      return String(value).padStart(2, "0");
    };
    return pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date.getSeconds());
  }

  function kindOf(ctx, cellId) {
    const layout = (ctx && ctx.items) || items;
    for (let index = 0; index < layout.length; index += 1) {
      const item = layout[index];
      const key = item.cellId || String(item.position);
      if (key === cellId || String(item.position) === String(cellId)) {
        return item.kind === "numeric" ? "numeric" : "option";
      }
    }
    return "option";
  }

  // --- Urinish konteksti (K1 himoyasi) --------------------------------------
  /**
   * Bitta imtihon urinishi uchun autosave holatini alohida obyektga yig'amiz.
   * Sababi: `flushAutosave` `await` lardan keyin HECH QACHON global holatni
   * o'qimaydi — u o'z kontekstiga qattiq bog'langan. Shu sababli foydalanuvchi
   * flush davomida boshqa testga o'tsa ham (yangi kontekst yaratiladi), eski
   * javoblar FAQAT o'z `attempt_id` siga yoziladi.
   */
  function createAttemptCtx(examId) {
    epochCounter += 1;
    return {
      epoch: epochCounter,
      examId: examId,
      attemptId: loadAttemptId(examId),
      seq: loadSeq(examId),
      v2Enabled: false,
      blocked: false,
      finalized: false,
      busy: false,
      dirty: loadPending(examId),
      items: [],
      retryTimer: null,
    };
  }

  /** Kontekst hali ham ochiq varaqning konteksti mi (bekor qilinmagan)? */
  function isActive(ctx) {
    return Boolean(ctx) && attemptCtx === ctx && !ctx.finalized;
  }

  /** Urinish yakunlandi — navbatdagi flush hech narsa yozmasligi kerak. */
  function finalizeAttemptCtx(ctx) {
    if (!ctx) {
      return;
    }
    ctx.finalized = true;
    ctx.blocked = true;
    ctx.dirty = {};
    if (ctx.retryTimer) {
      window.clearTimeout(ctx.retryTimer);
      ctx.retryTimer = null;
    }
  }

  /** Izohni faqat ochiq varaqning konteksti yangilay oladi (eski flush emas). */
  function setNoteIfActive(ctx, text) {
    if (isActive(ctx)) {
      setNote(text);
    }
  }

  /**
   * Saqlangan javoblarni o'qiydi.
   *
   * Yangi shakl: `{ answers: {...}, expressions: {...} }`.
   * Eski shakl (orqaga moslik): `{ "36": "12.5" }` — ifoda ham shu qiymat.
   */
  function loadSavedAnswers(examId) {
    const raw = storageGet(answersKey(examId));
    const empty = { answers: {}, expressions: {} };
    if (!raw) {
      return empty;
    }
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") {
        return empty;
      }
      if (parsed.answers && typeof parsed.answers === "object") {
        return {
          answers: parsed.answers,
          expressions:
            parsed.expressions && typeof parsed.expressions === "object"
              ? parsed.expressions
              : {},
        };
      }
      return { answers: parsed, expressions: parsed };
    } catch (error) {
      return empty;
    }
  }

  function persistAnswers() {
    if (!selectedExam) {
      return;
    }
    storageSet(
      answersKey(selectedExam.exam_id),
      JSON.stringify({ answers: answers, expressions: expressions })
    );
  }

  /** Har belgilashda: avval localStorage, `SAVE_DEBOUNCE`dan keyin serverga. */
  function scheduleSave() {
    const ctx = attemptCtx; // debounce tugaganda ham AYNAN shu urinishga yozamiz
    if (saveTimer) {
      window.clearTimeout(saveTimer);
    }
    saveTimer = window.setTimeout(function () {
      saveTimer = null;
      if (!isActive(ctx)) {
        return; // varaq almashdi/yopildi — boshqa urinishga yozmaymiz
      }
      persistAnswers();
      if (ctx.v2Enabled) {
        flushAutosave(ctx, false);
      } else {
        setNote("💾 Qurilmada saqlandi " + clockText());
      }
    }, SAVE_DEBOUNCE);
  }

  /** Javob berilgan kataklar soni (serverga yuborilgan qiymatlar). */
  function countAnswered() {
    return Object.keys(answers).length;
  }

  /**
   * Javob berilgan SAVOLLAR soni (a/b qismlar bitta savol hisoblanadi).
   * Progress va tasdiq matni shu qiymatdan foydalanadi.
   */
  function answeredPositions() {
    const seen = {};
    Object.keys(answers).forEach(function (cellId) {
      const cell = cellOf(cellId);
      const position = cell ? cell.position : Number(cellId);
      if (position) {
        seen[position] = true;
      }
    });
    return Object.keys(seen).length;
  }

  /** Urinishdagi savollar soni (progress maxraji). */
  function totalPositions() {
    const seen = {};
    items.forEach(function (item) {
      seen[item.position] = true;
    });
    return Object.keys(seen).length;
  }

  /**
   * v1 `/api/submit` uchun `{kalit: qiymat}` xaritasi.
   *
   * Kalit — katak **belgisi**: oddiy savolda `"36"`, qismli savolda
   * `"36a"`/`"36b"`. Server ikkalasini ham o'qiydi
   * (`form_layout.parse_structured_answers`) va qismlarni **alohida** saqlaydi
   * (`|36a:…,36b:…`) — shu sababli `a`/`b` javoblari biri ikkinchisini bosib
   * ketmaydi.
   */
  function submitAnswers() {
    const payload = {};
    Object.keys(answers).forEach(function (cellId) {
      const cell = cellOf(cellId);
      if (!cell) {
        return;
      }
      const part = cell.part ? String(cell.part) : "";
      payload[String(cell.position) + part] = answers[cellId];
    });
    return payload;
  }

  // --- Majburiylik qoidasi (1–35 majburiy, 36–45 ixtiyoriy) -----------------
  // Qoida `form_layout` bo'limlaridan kelib chiqadi: variant savollar (kind !==
  // "numeric") — majburiy; sonli savollar (36–45) — ixtiyoriy.
  function mandatoryPositions() {
    return items
      .filter(function (item) {
        return item.kind !== "numeric";
      })
      .map(function (item) {
        return item.position;
      });
  }

  function optionalPositions() {
    return items
      .filter(function (item) {
        return item.kind === "numeric";
      })
      .map(function (item) {
        return item.position;
      });
  }

  function isBlank(value) {
    return value === undefined || value === null || value === "";
  }

  /** Javobsiz qolgan MAJBURIY savollar raqamlari. */
  function missingMandatory() {
    return mandatoryPositions().filter(function (position) {
      return isBlank(answers[position]);
    });
  }

  /** Javobsiz majburiy kartochkalarni vizual belgilaydi. */
  function markMissingMandatory() {
    const sheet = byId("answer-sheet");
    if (!sheet) {
      return;
    }
    const missing = {};
    missingMandatory().forEach(function (position) {
      missing[position] = true;
    });
    mandatoryPositions().forEach(function (position) {
      const card = sheet.querySelector('.q-card[data-position="' + position + '"]');
      if (card) {
        card.classList.toggle("invalid", Boolean(missing[position]));
      }
    });
  }

  // --- Item-level autosave (server, `/api/v2/autosave`) ---------------------
  /**
   * Javobni navbatga qo'yadi: localStorage + serverga yuborish uchun belgilaydi.
   *
   * `expression` — o'quvchi kiritgan ASL matematik ifoda (`√5+1`). U `value`
   * (hisoblangan son) bilan BIRGA saqlanadi va serverga yuboriladi — shu sababli
   * ifoda refresh/qurilma almashishdan keyin ham tiklanadi. Variant (option)
   * javoblarida ifoda yo'q — `null` yuboriladi (avvalgi xulq o'zgarmaydi).
   */
  function queueAnswer(cellId, value, kind, expression) {
    // FAQAT joriy urinish kontekstiga yozamiz (`dirty` endi global emas).
    if (attemptCtx && !attemptCtx.finalized) {
      const kindValue = kind === "numeric" ? "numeric" : "option";
      let raw = expression;
      if (raw === undefined) {
        // Burchak rejimi ifoda matnida saqlanadi (`deg(...)`/`rad(...)`) —
        // shu yerda ham muhrlanadi, aks holda server radian deb hisoblaydi.
        raw = kindValue === "numeric" ? machineFor(expressions[cellId] || "") : null;
      }
      attemptCtx.dirty[cellId] = {
        value: value === undefined ? null : value,
        kind: kindValue,
        // Ifoda faqat sonli javobda mazmunli (variant javobida — `null`).
        expression: kindValue === "numeric" && raw ? String(raw) : null,
      };
      savePending(attemptCtx);
    }
    scheduleSave();
  }

  /**
   * Autosave manzili: `position` (+ kelajakda `part`).
   *
   * Katak id bugun pozitsiyaga teng ("38"); a/b qo'shilganda `"38b"` bo'ladi
   * va `part` serverga yuboriladi (server qo'llasa — ishlaydi, qo'llamasa —
   * e'tiborsiz qoladi).
   */
  function autosaveTarget(ctx, cellId) {
    const local = cellIndex[cellId];
    if (local) {
      return { position: local.position, part: local.part || "" };
    }
    const list = (ctx && ctx.items) || items;
    for (let index = 0; index < list.length; index += 1) {
      const item = list[index];
      if ((item.cellId || String(item.position)) === cellId) {
        return { position: item.position, part: item.part || "" };
      }
    }
    const parsed = Number(cellId);
    return { position: Number.isFinite(parsed) ? parsed : 0, part: "" };
  }

  /** Server javob satridan katak id sini oladi ("38" yoki "38b"). */
  function serverCellId(row) {
    const label = row && row.label ? String(row.label) : "";
    if (label) {
      return label;
    }
    const position = Number(row && row.position);
    return position ? String(position) : "";
  }

  /**
   * Navbatdagi javoblarni serverga yuboradi (idempotent: `client_seq`).
   *
   * `ctx` — chaqiruv paytidagi urinish konteksti. Funksiya `await` lardan keyin
   * HECH QACHON global holatni (`attemptCtx`, `dirty`, `answers`) o'qimaydi:
   * shu sababli foydalanuvchi flush davomida boshqa testga o'tsa ham javoblar
   * faqat shu `ctx.attemptId` ga yoziladi (K1 bartaraf).
   */
  async function flushAutosave(ctx, keepalive) {
    if (!ctx || ctx.finalized || ctx.blocked || ctx.busy) {
      return;
    }
    if (!ctx.v2Enabled || !ctx.attemptId) {
      return;
    }
    const batch = {};
    Object.keys(ctx.dirty).forEach(function (key) {
      batch[key] = ctx.dirty[key];
    });
    const keys = Object.keys(batch);
    if (!keys.length) {
      return;
    }

    ctx.busy = true;
    let failed = false;
    try {
      for (let index = 0; index < keys.length; index += 1) {
        if (ctx.finalized) {
          break; // urinish yakunlandi (submit/tozalash) — yozishni to'xtatamiz
        }
        const cellId = keys[index];
        const entry = batch[cellId];
        if (!entry) {
          continue;
        }
        const target = autosaveTarget(ctx, cellId);
        try {
          await API.post(
            "/api/v2/autosave",
            {
              attempt_id: ctx.attemptId, // kontekstdan — globaldan emas
              position: target.position,
              part: target.part,
              value: entry.value,
              // ASL matematik ifoda (Phase 1). Server uni `raw_answer` ga
              // saqlaydi; `value`/`numeric_value` o'zgarmaydi.
              expression: entry.expression === undefined ? null : entry.expression,
              answer_kind: entry.kind || kindOf(ctx, cellId),
              client_seq: nextSeq(ctx),
            },
            keepalive ? { keepalive: true } : undefined
          );
          if (ctx.dirty[cellId] === entry) {
            delete ctx.dirty[cellId];
          }
        } catch (error) {
          const status = error ? error.status : 0;
          if (status === 409 || status === 410) {
            ctx.blocked = true;
            setNoteIfActive(
              ctx,
              "⚠️ Javobni o'zgartirish yopilgan (imtihon yakunlangan yoki vaqt tugadi)."
            );
          } else {
            failed = true;
          }
          break;
        }
      }
    } finally {
      ctx.busy = false;
      if (!ctx.finalized) {
        savePending(ctx); // navbat AYNAN shu urinishning kaliti ostiga yoziladi
      }
    }

    if (failed) {
      setNoteIfActive(ctx, "⚠️ Tarmoq yo'q — javoblar qurilmada saqlanmoqda.");
      scheduleRetry(ctx);
    } else if (!ctx.blocked && !ctx.finalized) {
      setNoteIfActive(ctx, "✓ Serverga saqlandi " + clockText());
    }
  }

  /** Qayta urinish faqat varaq ochiq turganda rejalashtiriladi (timer leak yo'q). */
  function scheduleRetry(ctx) {
    if (!isActive(ctx) || !ctx.examId) {
      return;
    }
    if (ctx.retryTimer) {
      window.clearTimeout(ctx.retryTimer);
    }
    ctx.retryTimer = window.setTimeout(function () {
      ctx.retryTimer = null;
      if (isActive(ctx)) {
        flushAutosave(ctx, false);
      }
    }, RETRY_DELAY);
  }

  /** Majburiy (debounce'siz) saqlash: `visibilitychange`/`pagehide`/`online`. */
  function flushNow(keepalive) {
    const ctx = attemptCtx;
    if (saveTimer) {
      window.clearTimeout(saveTimer);
      saveTimer = null;
    }
    persistAnswers();
    flushAutosave(ctx, Boolean(keepalive));
  }

  /**
   * Server holatini lokal javoblar bilan birlashtiradi.
   * Konfliktda **server ustun**; serverda yo'q (yuborilmagan) javoblar navbatga qo'yiladi.
   */
  function mergeServerState(ctx, payload) {
    if (!isActive(ctx)) {
      return; // varaq almashdi — yangi varaqning javoblarini o'zgartirmaymiz
    }
    const serverItems = payload && Array.isArray(payload.items) ? payload.items : [];
    const seen = {};
    serverItems.forEach(function (row) {
      const cellId = serverCellId(row);
      if (!cellId) {
        return;
      }
      seen[cellId] = true;
      delete ctx.dirty[cellId]; // server ustun — navbatdagi eski qiymat bekor qilinadi
      const value = row.value;
      const expression =
        row.expression === null || row.expression === undefined
          ? ""
          : String(row.expression);
      if (value === null || value === undefined || value === "") {
        delete answers[cellId];
        delete expressions[cellId];
      } else {
        answers[cellId] = String(value);
        // ASL ifoda serverdan tiklanadi (Phase 1). Burchak rejimi ifoda
        // ichida (`deg(...)`/`rad(...)`) — uni ajratib, ko'rinishni tozalaymiz.
        const restored = restoreExpression(expression);
        expressions[cellId] = restored.text || String(value);
      }
    });

    items.forEach(function (item) {
      const cellId = item.cellId || String(item.position);
      if (seen[cellId]) {
        return;
      }
      const value = answers[cellId];
      if (value === undefined || value === null || value === "") {
        return;
      }
      // MUHIM: shu katak uchun allaqachon muhrlangan ifoda bo'lsa (pending),
      // uni SAQLAYMIZ — u `value` bilan BIR rejimda yaratilgan. Aks holda rejim
      // almashgach ifoda yangi rejim bilan muhrlanib, `value` (eski rejimda
      // hisoblangan son) bilan ziddiyatga tushardi; server esa ifodani qayta
      // hisoblaydi (`web/api_v2.py:291-296`) -> noto'g'ri javob.
      const existing = ctx.dirty[cellId];
      const sealed =
        (existing && existing.expression) ||
        machineFor(expressions[cellId] || "") ||
        null;
      ctx.dirty[cellId] = {
        value: value,
        kind: item.kind,
        expression: item.kind === "numeric" ? sealed : null,
      };
    });

    savePending(ctx);
  }

  /**
   * Item-level urinishni boshlaydi (`/api/v2/attempt/start`) va `state`ni tiklaydi.
   * Sessiya mavjud bo'lmasa — jim ravishda localStorage (legacy) rejimida qoladi.
   *
   * Har bir `await` dan keyin kontekst hali ham ochiq varaqniki ekani tekshiriladi:
   * aks holda (foydalanuvchi boshqa testga o'tgan) bu urinish to'xtatiladi.
   */
  async function initAttempt(exam, code) {
    const ctx = attemptCtx;
    if (!exam || !code || !ctx || ctx.examId !== exam.exam_id) {
      return;
    }
    try {
      const info = await API.post("/api/v2/verify-code", { test_code: code });
      if (!isActive(ctx)) {
        return;
      }
      if (info.already_submitted) {
        setNote("Javoblaringiz allaqachon yuborilgan.");
        return;
      }
      if (!info.can_start) {
        setNote("Javob qabul qilish faol emas — javoblar qurilmada saqlanadi.");
        return;
      }
      const started = await API.post("/api/v2/attempt/start", { test_code: code });
      if (!isActive(ctx)) {
        return;
      }
      if (!started || !started.attempt_id) {
        setNote("Javoblar qurilmada saqlanadi (server urinishi mavjud emas).");
        return;
      }

      ctx.attemptId = Number(started.attempt_id);
      storageSet(attemptKey(ctx.examId), String(ctx.attemptId));
      ctx.v2Enabled = true;
      ctx.blocked = false;

      // Phase 3 Step 2: server qismli joylashuvni bersa ("36a"/"36b"), kataklar
      // shundan quriladi — a/b mustaqil yoziladi. Qism bo'lmasa — o'zgarmaydi.
      applyServerLayout(ctx, started.layout);

      const serverState = await API.get(
        "/api/v2/state?attempt_id=" + encodeURIComponent(String(ctx.attemptId))
      );
      if (!isActive(ctx)) {
        return;
      }
      mergeServerState(ctx, serverState);
      persistAnswers();
      renderSheet();
      updateStatus();
      setNote(
        serverState && serverState.answered_count
          ? "Serverdagi javoblar tiklandi (" + serverState.answered_count + " ta)."
          : "Javoblar serverga avtomatik saqlanadi."
      );
      flushAutosave(ctx, false);
    } catch (error) {
      // Item-level sessiya yo'q yoki tarmoq xatosi — legacy + localStorage rejimi.
      if (!isActive(ctx)) {
        return;
      }
      ctx.v2Enabled = false;
      ctx.attemptId = loadAttemptId(ctx.examId);
      setNote("Javoblar qurilmada saqlanadi (server autosave mavjud emas).");
    }
  }

  // --- Kartochkalar (MVP dizayni) ------------------------------------------
  /**
   * Server bo'limlarini kataklarga yoyadi.
   *
   * Hozir: bitta savol = bitta katak (36–45 → 10 katak).
   * Kelajakda server `parts` bersa (`["a","b"]`) — har bir qism uchun ALOHIDA
   * katak yaratiladi, ya'ni a/b ni qo'shish uchun bu tizim qayta yozilmaydi:
   * katak id `"38b"` bo'ladi, `position` esa `38` bo'lib qoladi.
   */
  function expandLayout(ranges) {
    const list = [];
    (ranges || []).forEach(function (range) {
      const from = Number(range.from);
      const to = Number(range.to);
      const parts = Array.isArray(range.parts) ? range.parts : [];
      for (let position = from; position <= to; position += 1) {
        if (parts.length) {
          parts.forEach(function (part) {
            list.push({
              position: position,
              part: String(part),
              cellId: String(position) + String(part),
              kind: range.kind,
              options: range.options || [],
            });
          });
        } else {
          list.push({
            position: position,
            part: "",
            cellId: String(position),
            kind: range.kind,
            options: range.options || [],
          });
        }
      }
    });
    return list;
  }

  /** Server `layout` bermasa — MVP qoidasi bo'yicha zaxira joylashuv. */
  function fallbackLayout(total) {
    const ranges = [];
    if (total >= 1) {
      ranges.push({
        from: 1,
        to: Math.min(32, total),
        kind: "option",
        options: ["A", "B", "C", "D"],
      });
    }
    if (total >= 33) {
      ranges.push({
        from: 33,
        to: Math.min(35, total),
        kind: "option",
        options: ["A", "B", "C", "D", "E", "F"],
      });
    }
    if (total >= 36) {
      ranges.push({ from: 36, to: total, kind: "numeric", options: [] });
    }
    return expandLayout(ranges);
  }

  /**
   * Server (v2) qismli joylashuvni bersa — kataklarni AYNAN undan qayta quradi.
   *
   * Phase 3 Step 2: `parts` mavjud bo'lganda ("36a"/"36b") a/b mustaqil kataklar
   * hosil bo'ladi. Qism bo'lmasa (legacy imtihonlar) — joylashuv o'zgarmaydi.
   * `renderSheet()` keyinroq (state birlashtirilgach) chaqiriladi.
   */
  function applyServerLayout(ctx, layout) {
    if (!isActive(ctx) || !Array.isArray(layout) || !layout.length) {
      return;
    }
    const hasParts = layout.some(function (range) {
      return Array.isArray(range.parts) && range.parts.length > 0;
    });
    if (!hasParts) {
      return; // legacy — mavjud joylashuv tegilmaydi
    }
    items = expandLayout(layout);
    ctx.items = items;
    cellIndex = {};
    items.forEach(function (item) {
      cellIndex[item.cellId || String(item.position)] = item;
    });
  }

  function selectOption(position, option, card) {
    const next = answers[position] === option ? null : option; // qayta bosilsa — bekor
    if (next) {
      answers[position] = next;
    } else {
      delete answers[position];
    }
    card.querySelectorAll(".q-opt").forEach(function (element) {
      const isSelected = element.dataset.value === next;
      element.classList.toggle("selected", isSelected);
      element.setAttribute("aria-pressed", isSelected ? "true" : "false");
    });
    card.classList.toggle("answered", Boolean(next));
    API.haptic("light");
    queueAnswer(position, next, "option");
    updateStatus();
  }

  /** Katak ma'lumotini qaytaradi (cellId bo'yicha; topilmasa null). */
  function cellOf(cellId) {
    return cellIndex[cellId] || null;
  }

  /** Katak uchun o'qituvchi/o'quvchi tushunadigan nom (o'zbekcha). */
  function cellLabel(cell) {
    if (cell && cell.part) {
      return cell.position + "-savol · " + cell.part + ") qismi";
    }
    return (cell ? cell.position : "") + "-savol";
  }

  /** Panel sarlavhasi ostidagi izoh: saqlanadigan qiymat yoki ogohlantirish. */
  function hintForCell(cellId) {
    const value = answers[cellId];
    if (value === undefined || value === null || value === "") {
      return expressions[cellId] ? "Ifoda to'liq emas — hisoblanmadi" : "";
    }
    return "= " + value;
  }

  /** Katak ko'rinishini yangilaydi (qiymat, aktiv holat, xato belgisi). */
  function refreshCellView(cellId) {
    const sheet = byId("answer-sheet");
    if (!sheet) {
      return;
    }
    const cell = sheet.querySelector('.q-cell[data-cell="' + cellId + '"]');
    if (!cell) {
      return;
    }
    const expression = expressions[cellId] || "";
    const saved = answers[cellId];
    const valueBox = cell.querySelector(".q-value");
    if (valueBox) {
      if (!expression) {
        valueBox.classList.add("placeholder");
        valueBox.textContent = "Javobni kiriting";
      } else {
        valueBox.classList.remove("placeholder");
        valueBox.innerHTML = renderCellHtml(cellId, expression);
      }
    }
    cell.classList.toggle("active", activeCell === cellId);
    cell.classList.toggle("answered", Boolean(saved));
    cell.classList.toggle("invalid", Boolean(expression) && !saved);
    const card = cell.closest(".q-card");
    if (card) {
      card.classList.toggle("answered", Boolean(saved));
    }
  }

  /**
   * Aktiv katakni o'rnatadi va panelni unga ulaydi.
   *
   * Talab: boshqa katakka o'tilganda oldingi katak qiymati DARHOL saqlanadi
   * (debounce kutilmaydi).
   */
  function activateCell(cellId) {
    if (activeCell === cellId) {
      return;
    }
    if (activeCell) {
      const previous = activeCell;
      flushNow(false); // oldingi katak qiymatini darhol yuboramiz
      activeCell = null;
      refreshCellView(previous);
    }
    const cell = cellOf(cellId);
    if (!cell) {
      return;
    }
    activeCell = cellId;
    refreshCellView(cellId);
    if (window.MathPanel && typeof window.MathPanel.attach === "function") {
      window.MathPanel.attach(cellId, { label: cellLabel(cell) });
      window.MathPanel.setHint(hintForCell(cellId), answers[cellId] ? "ok" : null);
    }
    const node = byId("answer-sheet").querySelector('.q-cell[data-cell="' + cellId + '"]');
    if (node) {
      node.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  /** Matematik panel API'si (caret/kasr/renderer yordamchilari). */
  function panelApi() {
    if (window.MathPanel && typeof window.MathPanel.insertAt === "function") {
      return window.MathPanel;
    }
    return null;
  }

  /** Burchak rejimi bilan machine-string (MathPanel bo'lmasa — o'zgarishsiz). */
  function machineFor(expression) {
    const api = panelApi();
    if (api && typeof api.machineExpression === "function") {
      return api.machineExpression(expression);
    }
    return expression;
  }

  /** Server machine-stringidan rejimni ajratadi va panelni moslaydi. */
  function restoreExpression(machine) {
    const api = panelApi();
    if (api && typeof api.unwrapExpression === "function") {
      const parsed = api.unwrapExpression(machine);
      if (parsed.mode && typeof api.setAngleMode === "function") {
        api.setAngleMode(parsed.mode);
      }
      return parsed;
    }
    return { text: machine, mode: null };
  }

  /** HTML escape (renderer bo'lmasa ham XSS xavfsiz). */
  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  /** Katak caret pozitsiyasi (noto'g'ri bo'lsa — oxiri). */
  function caretOf(cellId) {
    const expression = expressions[cellId] || "";
    const stored = carets[cellId];
    if (typeof stored !== "number" || stored < 0 || stored > expression.length) {
      return expression.length;
    }
    return stored;
  }

  /** Caret pozitsiyasini chegaralar ichida o'rnatadi. */
  function setCaret(cellId, index) {
    const expression = expressions[cellId] || "";
    let at = Math.round(index);
    if (!isFinite(at)) {
      at = expression.length;
    }
    carets[cellId] = Math.max(0, Math.min(at, expression.length));
  }

  /** Katak ko'rinishi: butun ifoda bir marta chiziladi, caret — absolut
   * pozitsiyada (`m-slot` katakchalari ham shu tufayli to'g'ri chiqadi). */
  function renderCellHtml(cellId, expression) {
    const api = panelApi();
    if (!api || typeof api.renderExpression !== "function") {
      return escapeHtml(expression);
    }
    const at = activeCell === cellId ? caretOf(cellId) : -1;
    return api.renderExpression(expression, at);
  }

  /** Paneldan kelgan tokenni caret joyiga qo'yadi.
   *
   * `caretBack` — kiritilgandan keyin kursorni chapga suradi. Masalan `^()`
   * kiritilganda `caretBack = 1` bo'lsa, kursor qavslar ICHIDA qoladi —
   * foydalanuvchi darajani darhol yozadi (Word'dagi katak kabi).
   */
  function insertToken(token, caretBack) {
    if (!activeCell) {
      return;
    }
    const api = panelApi();
    const expression = expressions[activeCell] || "";
    if (!api) {
      applyExpression(activeCell, expression + token);
      return;
    }
    const result = api.insertAt(expression, caretOf(activeCell), token);
    const back = Math.max(0, Math.round(Number(caretBack) || 0));
    carets[activeCell] = Math.max(0, result.caret - back);
    applyExpression(activeCell, result.text);
  }

  /**
   * `÷` — SMART KASR: caret CHAPIDAGI qism SURATGA, o'ngidagi qism MAXRAJGA
   * o'tadi va caret maxraj katagiga tushadi — foydalanuvchi darhol yozadi.
   *
   * `5` (caret oxirida)  → `(5)/()`   + caret maxraj katagida
   * `52` (caret 5 dan keyin) → `(5)/(2)` + caret maxraj katagida
   * bo'sh ifoda           → `()/( )`  + caret surat katagida
   *
   * Bo'lish = kasr, ya'ni hisoblangan qiymat o'zgarmaydi.
   */
  function smartFractionCell() {
    if (!activeCell) {
      return;
    }
    const expression = expressions[activeCell] || "";
    const at = caretOf(activeCell);
    const left = expression.slice(0, at);
    const right = expression.slice(at);
    if (!left) {
      // Surat hali bo'sh: `()/(...)` — caret SURAT katagiga tushadi.
      carets[activeCell] = 1;
      applyExpression(activeCell, "()/(" + right + ")");
      return;
    }
    // `(surat)/(maxraj)` — kursor MAXRAJ ichida:
    //   `(surat)/` dan keyin `(` (1) + maxraj matni; shu sababli
    //   `len(surat) + 4 + len(maxraj)` = maxraj matnining OXIRI.
    // Misol: `(5)/()` -> 1 + 4 + 0 = 5 (qavslar ICHIDA) ✅
    carets[activeCell] = left.length + 4 + right.length;
    applyExpression(activeCell, "(" + left + ")/(" + right + ")");
  }

  /** Caret CHAPIDAGI belgini o'chiradi (Backspace). */
  function backspaceCell() {
    if (!activeCell) {
      return;
    }
    const api = panelApi();
    const expression = expressions[activeCell] || "";
    if (!api) {
      applyExpression(activeCell, expression.slice(0, -1));
      return;
    }
    const result = api.deleteBefore(expression, caretOf(activeCell));
    carets[activeCell] = result.caret;
    applyExpression(activeCell, result.text);
  }

  /** Caret O'NGIDAGI belgini o'chiradi (Delete). */
  function deleteCell() {
    if (!activeCell) {
      return;
    }
    const api = panelApi();
    const expression = expressions[activeCell] || "";
    if (!api) {
      return;
    }
    const result = api.deleteAt(expression, caretOf(activeCell));
    carets[activeCell] = result.caret;
    applyExpression(activeCell, result.text);
  }

  /** Caret'ni chap/o'ngga suradi (`delta` -1 yoki +1). */
  function moveCaret(delta) {
    if (!activeCell) {
      return;
    }
    setCaret(activeCell, caretOf(activeCell) + delta);
    refreshCellView(activeCell);
    if (window.MathPanel && window.MathPanel.currentTarget() === activeCell) {
      window.MathPanel.setHint(hintForCell(activeCell), answers[activeCell] ? "ok" : null);
    }
  }

  /** Aktiv katakni tozalaydi. */
  function clearCell() {
    if (!activeCell) {
      return;
    }
    carets[activeCell] = 0;
    applyExpression(activeCell, "");
  }

  /** Kasr konstruktori modalini ochadi (2 slot: surat/maxraj). */
  function openFractionModal() {
    const modal = byId("frac-modal");
    if (!modal) {
      return;
    }
    const num = byId("frac-num");
    const den = byId("frac-den");
    if (num) {
      num.value = "";
    }
    if (den) {
      den.value = "";
    }
    modal.classList.remove("hidden");
    if (num) {
      try {
        num.focus();
      } catch (error) {
        /* fokus qo'yilmasa — e'tiborsiz */
      }
    }
  }

  function closeFractionModal() {
    const modal = byId("frac-modal");
    if (modal) {
      modal.classList.add("hidden");
    }
  }

  /** Slotlardan `(surat)/(maxraj)` qurib, caret joyiga qo'yadi. */
  function submitFractionModal() {
    closeFractionModal();
    if (!activeCell) {
      return;
    }
    const api = panelApi();
    if (!api || typeof api.buildFraction !== "function") {
      return;
    }
    const num = byId("frac-num");
    const den = byId("frac-den");
    const machine = api.buildFraction(num ? num.value : "", den ? den.value : "");
    if (!machine) {
      return;
    }
    const expression = expressions[activeCell] || "";
    const result = api.insertAt(expression, caretOf(activeCell), machine);
    carets[activeCell] = result.caret;
    applyExpression(activeCell, result.text);
  }

  /** Ifodani hisoblab, server formatidagi o'nlik matnni qaytaradi (yoki null). */
  function evaluateExpression(expression) {
    if (!window.MathPanel || typeof window.MathPanel.evaluate !== "function") {
      return null;
    }
    const raw = window.MathPanel.evaluate(expression);
    if (raw === null || raw === undefined) {
      return null;
    }
    return window.MathPanel.formatValue(raw);
  }

  /**
   * Ifodani qabul qiladi.
   *
   * Ko'rsatiladigan matn — `expressions[cellId]` (foydalanuvchi nima yozgan),
   * serverga yuboriladigan qiymat — `answers[cellId]` (hisoblangan o'nlik son).
   * Ifoda hisoblanmasa — javob SAQLANMAYDI (server 400 qaytarmasin).
   */
  function applyExpression(cellId, expression) {
    if (!cellOf(cellId)) {
      return;
    }
    expressions[cellId] = expression;
    // Burchak rejimi ifoda matniga "muhrlanadi" (`deg(...)`/`rad(...)`) —
    // server ham xuddi shu matnni hisoblaydi (JS/Python tafovuti yo'q).
    const machine = machineFor(expression);
    let value = machine ? evaluateExpression(machine) : null;
    if (value !== null && !NUMERIC_RE.test(value)) {
      value = null; // kutilmagan format — saqlanmaydi
    }
    if (value === null) {
      delete answers[cellId];
      // Hisoblanmagan bo'lsa ham ASL ifoda yuboriladi (ko'rik uchun) — `value` null.
      queueAnswer(cellId, null, "numeric", machine);
    } else {
      answers[cellId] = value;
      queueAnswer(cellId, value, "numeric", machine);
    }
    refreshCellView(cellId);
    if (window.MathPanel && window.MathPanel.currentTarget() === cellId) {
      window.MathPanel.setHint(hintForCell(cellId), value === null ? "error" : "ok");
    }
    updateStatus();
  }

  /** Savol qismini aniqlaydi: `"36a"` → `"a"` (qismsiz — `""`). */
  function partOf(item) {
    if (item.part) {
      return String(item.part);
    }
    const match = /^\d+([a-z])$/i.exec(String(item.cellId || ""));
    return match ? match[1].toLowerCase() : "";
  }

  /** Sonli javob katagi (native input EMAS — telefon klaviaturasi ochilmaydi). */
  function buildNumericCell(item) {
    const cellId = item.cellId || String(item.position);
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "q-cell";
    cell.dataset.cell = cellId;
    cell.setAttribute("role", "textbox");
    cell.setAttribute("aria-readonly", "true");
    cell.setAttribute("aria-label", cellLabel(item) + " — javob katagi");
    const valueBox = document.createElement("span");
    valueBox.className = "q-value placeholder";
    valueBox.textContent = "Javobni kiriting";
    cell.appendChild(valueBox);
    cell.addEventListener("click", function (event) {
      // Bo'sh KATAKCHA (`m-slot`) bosildi — caret shu katakchaga o'tadi
      // (Word'dagi tenglamalar kabi: katakchani bosib raqam yoziladi).
      const target = event.target;
      const slot = target && target.closest ? target.closest(".m-slot") : null;
      if (slot && cell.contains(slot)) {
        const off = Number(slot.getAttribute("data-off"));
        setCaret(cellId, isFinite(off) ? off : 0);
        applyExpression(cellId, expressions[cellId] || "");
        activateCell(cellId);
        return;
      }
      activateCell(cellId);
    });
    return cell;
  }

  /**
   * Bitta karta ichida savolning **qismlari**: sarlavhada raqam (`36`),
   * pastida `a)` va `b)` qatorlari (har biri alohida javob katagi).
   */
  function buildPartsCard(group) {
    const card = document.createElement("div");
    card.className = "q-card q-card-parts";
    card.dataset.position = String(group.position);

    const head = document.createElement("div");
    head.className = "q-head";
    const number = document.createElement("span");
    number.className = "q-num";
    number.textContent = String(group.position);
    const kind = document.createElement("span");
    kind.className = "q-kind";
    // Sarlavhada faqat raqam turadi — `a)`/`b)` esa pastdagi qatorlarda.
    kind.textContent = "";
    head.appendChild(number);
    head.appendChild(kind);
    card.appendChild(head);

    group.parts.forEach(function (item) {
      const row = document.createElement("div");
      row.className = "q-part";
      const label = document.createElement("span");
      label.className = "q-part-label";
      label.textContent = partOf(item) + ")";
      row.appendChild(label);
      row.appendChild(buildNumericCell(item));
      card.appendChild(row);
    });
    return card;
  }

  function buildCard(item) {
    const card = document.createElement("div");
    card.className = "q-card";
    card.dataset.position = String(item.position);

    const head = document.createElement("div");
    head.className = "q-head";
    const number = document.createElement("span");
    number.className = "q-num";
    number.textContent = String(item.position);
    const kind = document.createElement("span");
    kind.className = "q-kind";
    head.appendChild(number);
    head.appendChild(kind);
    card.appendChild(head);

    const cellId = item.cellId || String(item.position);
    const saved = answers[cellId];
    if (item.kind === "numeric") {
      kind.textContent = "Katakni bosing";
      card.appendChild(buildNumericCell(item));
    } else {
      // Variantlar soni yozuvi ("4 variant" kabi) olib tashlandi — faqat
      // A/B/C/D tugmalari ko'rsatiladi (ko'rinish; javob mantiqi o'zgarmaydi).
      const row = document.createElement("div");
      row.className = "q-options cols-" + item.options.length;
      row.setAttribute("role", "radiogroup");
      row.setAttribute("aria-label", item.position + "-savol javobi");
      item.options.forEach(function (option) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "q-opt" + (saved === option ? " selected" : "");
        button.dataset.value = option;
        button.textContent = option;
        button.setAttribute("aria-pressed", saved === option ? "true" : "false");
        button.addEventListener("click", function () {
          selectOption(item.position, option, card);
        });
        row.appendChild(button);
      });
      if (saved) {
        card.classList.add("answered");
      }
      card.appendChild(row);
    }
    return card;
  }

  function renderSheet() {
    const sheet = byId("answer-sheet");
    sheet.innerHTML = "";
    // Qismli savollar (36a/36b) — BITTA karta ichida `a)`/`b)` qatorlari bilan.
    const units = [];
    const partsByPosition = {};
    items.forEach(function (item) {
      const part = item.kind === "numeric" ? partOf(item) : "";
      if (part) {
        const key = String(item.position);
        if (!partsByPosition[key]) {
          partsByPosition[key] = { position: item.position, parts: [] };
          units.push(partsByPosition[key]);
        }
        partsByPosition[key].parts.push(item);
        return;
      }
      units.push({ item: item });
    });
    units.forEach(function (unit) {
      sheet.appendChild(unit.parts ? buildPartsCard(unit) : buildCard(unit.item));
    });
    // Tiklangan qiymatlar va aktiv katak ko'rinishini qayta chizamiz.
    items.forEach(function (item) {
      if (item.kind === "numeric") {
        refreshCellView(item.cellId || String(item.position));
      }
    });
  }

  function updateStatus() {
    const total = totalPositions();
    const done = answeredPositions();
    const percent = total ? Math.round((done * 100) / total) : 0;
    const bar = byId("answer-progress-bar");
    if (bar) {
      bar.style.width = percent + "%";
    }
    const track = byId("answer-progress-track");
    if (track) {
      track.setAttribute("aria-valuenow", String(percent));
    }

    const meta = byId("answer-meta");
    if (!meta || !selectedExam) {
      return;
    }
    const remaining = Math.round((deadline - Date.now()) / 1000);
    let text = done + "/" + total + " javob belgilandi";
    text +=
      remaining > 0 ? " · qolgan vaqt: " + App.formatCountdown(remaining) : " · vaqt tugadi";
    meta.textContent = text;

    const submit = byId("submit-answers");
    if (submit) {
      submit.disabled = submitting || remaining <= 0;
    }
    markMissingMandatory();
  }

  function openAnswerSheet(exam, code, quiet) {
    selectedExam = exam;
    examCode = code;
    submitting = false;
    // YANGI urinish konteksti. Undan oldin boshlangan (davom etayotgan) flushlar
    // o'z eski konteksti bilan ishlashda davom etadi va FAQAT o'z `attempt_id`
    // siga yozadi — global holat almashishi ularga ta'sir qilmaydi (K1 himoyasi).
    attemptCtx = createAttemptCtx(exam.exam_id);
    deadline = Date.now() + Math.max(0, exam.seconds_left) * 1000;
    items =
      exam.layout && exam.layout.length
        ? expandLayout(exam.layout)
        : fallbackLayout(exam.total_questions || 0);
    attemptCtx.items = items;

    // Katak xaritasi (autosave manzili va ko'rsatish uchun).
    cellIndex = {};
    items.forEach(function (item) {
      cellIndex[item.cellId || String(item.position)] = item;
    });

    // Sahifa yangilangan bo'lsa — javoblar localStorage'dan tiklanadi.
    const saved = loadSavedAnswers(exam.exam_id);
    answers = {};
    expressions = {};
    items.forEach(function (item) {
      const cellId = item.cellId || String(item.position);
      const value = saved.answers[cellId];
      if (value !== undefined && value !== null && value !== "") {
        answers[cellId] = String(value);
        const expression = saved.expressions[cellId];
        expressions[cellId] = expression ? String(expression) : String(value);
      }
    });
    activeCell = null;
    if (window.MathPanel && typeof window.MathPanel.detach === "function") {
      window.MathPanel.detach();
    }

    byId("answer-card").classList.remove("hidden");
    // Imtihon ochilganda pastki navigatsiya yashiriladi (focus rejimi).
    document.body.classList.add("exam-mode");
    byId("answer-title").textContent = exam.title;
    byId("autosave-note").textContent = "Javoblar avtomatik saqlanadi.";
    renderSheet();
    updateStatus();

    if (timer) {
      window.clearInterval(timer);
    }
    timer = window.setInterval(updateStatus, 1000);

    if (!quiet) {
      byId("answer-card").scrollIntoView({ behavior: "smooth", block: "start" });
    }
    const restored = countAnswered();
    App.setNotice(
      "success",
      restored
        ? "Oldingi javoblaringiz tiklandi (" + restored + " ta). Test kodi: " + examCode
        : "Test kodi tasdiqlandi. Javoblar avtomatik saqlanadi.",
      true
    );
  }

  /** Yuborilgandan keyin qurilmadagi barcha izlarni tozalaydi. */
  function clearSheetStorage(examId) {
    if (examId) {
      storageRemove(answersKey(examId));
      storageRemove(attemptKey(examId));
      storageRemove(seqKey(examId));
      storageRemove(pendingKey(examId));
    }
    storageRemove(CODE_KEY);
    if (attemptCtx && attemptCtx.examId === examId) {
      finalizeAttemptCtx(attemptCtx); // navbatdagi flush endi hech narsa yozmaydi
    }
  }

  function closeAnswerSheet(skipFlush) {
    const ctx = attemptCtx;
    if (skipFlush !== true) {
      flushNow(true); // navbatdagi javoblarni yuborishga urinamiz (kutmasdan)
    }
    selectedExam = null;
    examCode = "";
    items = [];
    answers = {};
    expressions = {};
    cellIndex = {};
    activeCell = null;
    if (window.MathPanel && typeof window.MathPanel.detach === "function") {
      window.MathPanel.detach();
    }
    // Kontekstni bo'shatamiz. Boshlangan flush o'z `ctx` referensi bilan davom
    // etadi (faqat o'z `attempt_id` siga yozadi); yuborilmagan navbat esa
    // `pending` kalitida saqlanib qoladi.
    attemptCtx = null;
    if (ctx && ctx.retryTimer) {
      window.clearTimeout(ctx.retryTimer);
      ctx.retryTimer = null;
    }
    if (timer) {
      window.clearInterval(timer);
      timer = null;
    }
    if (saveTimer) {
      window.clearTimeout(saveTimer);
      saveTimer = null;
    }
    byId("answer-card").classList.add("hidden");
    byId("answer-sheet").innerHTML = "";
    // Imtihondan chiqilganda navigatsiya yana odatdagidek ko'rinadi.
    document.body.classList.remove("exam-mode");
  }

  /** Kod maydonidagi xatoni KO'RSATADI (maydon yonida — jim qolib ketmaydi). */
  function showCodeError(message) {
    const box = byId("code-error");
    if (box) {
      box.textContent = String(message || "Kodni tekshirib qayta kiriting.");
      box.classList.remove("hidden");
    }
    const input = byId("test-code");
    if (input) {
      input.classList.add("invalid");
      input.setAttribute("aria-invalid", "true");
      try {
        input.focus();
      } catch (error) {
        /* fokus qo'yib bo'lmasa — muhim emas */
      }
    }
    API.haptic("error");
  }

  /** Kod maydonidagi xato holatini tozalaydi (yozishni boshlaganda/urinishda). */
  function clearCodeError() {
    const box = byId("code-error");
    if (box) {
      box.textContent = "";
      box.classList.add("hidden");
    }
    const input = byId("test-code");
    if (input) {
      input.classList.remove("invalid");
      input.removeAttribute("aria-invalid");
    }
  }

  /** «Kodni tekshirish» tugmasining kutish holati (takroriy bosishga qarshi). */
  function setVerifying(busy) {
    const button = byId("find-exam");
    if (!button) {
      return;
    }
    button.disabled = Boolean(busy);
    button.textContent = busy ? "Tekshirilmoqda…" : "Kodni tekshirish";
  }

  async function handleVerifyCode(codeOverride) {
    const code = (codeOverride || byId("test-code").value || "").trim().toUpperCase();
    if (!codeOverride) {
      clearCodeError();
    }
    if (code.length < 4) {
      if (!codeOverride) {
        showCodeError("Test kodi kamida 4 belgidan iborat bo'lishi kerak.");
      }
      return;
    }

    if (!codeOverride) {
      API.haptic("medium");
      App.clearNotice();
      setVerifying(true);
    }
    try {
      const exam = await API.post("/api/verify-code", { test_code: code });
      if (exam.submitted) {
        storageRemove(CODE_KEY);
        App.setNotice(
          "success",
          "Siz bu imtihonga javob yuborgansiz. Natijalar " +
            exam.result_time_local +
            " da e'lon qilinadi.",
          false
        );
        return;
      }
      if (!exam.can_submit) {
        // Kod TO'G'RI, lekin javob qabul qilish oynasi hozir ochilmagan
        // (imtihon hali boshlanmagan yoki allaqachon yopilgan). Kodni
        // O'CHIRMAYMIZ: oyna ochilganda o'quvchi qaytadan terishi kerak
        // bo'lmasin. Sahifa ochilishidagi avtomatik tekshiruvda esa jim
        // qolamiz — har ochilishda xabar chiqib bezovta qilmasin.
        if (!codeOverride) {
          App.setNotice("error", exam.message, false);
        }
        return;
      }
      byId("test-code").value = code;
      clearCodeError();
      storageSet(CODE_KEY, code);
      openAnswerSheet(exam, code, Boolean(codeOverride));
      initAttempt(exam, code);
    } catch (error) {
      const status = error && error.status ? error.status : 0;
      if (codeOverride) {
        // Sahifa ochilishida eski kod tekshiriladi. Kod umuman yo'q (404)
        // yoki formati xato (400) bo'lsa — saqlangan holatni tozalaymiz.
        // Tarmoq xatosida (status yo'q) kod SAQLANADI: aloqa tiklanishi
        // bilan u yana avtomatik tekshiriladi.
        if (status === 400 || status === 404) {
          storageRemove(CODE_KEY);
        }
        return;
      }
      // Noto'g'ri kod (yoki tarmoq xatosi) — xabar kod maydoni ostida
      // ko'rinadi. Ilgari bu yerda `App.alert` chaqirilardi, u mavjud
      // bo'lmaganligi uchun xato jim yutilib ketardi.
      showCodeError(
        error && error.message
          ? error.message
          : "Kodni tekshirishda xatolik. Internetni tekshirib, qayta urinib ko'ring."
      );
    } finally {
      if (!codeOverride) {
        setVerifying(false);
      }
    }
  }

  async function handleSubmit() {
    if (!selectedExam || submitting) {
      return;
    }
    // Majburiy savollar (1–35) to'liq bo'lishi shart; 36–45 ixtiyoriy.
    const missing = missingMandatory();
    if (missing.length) {
      markMissingMandatory();
      const shown = missing.slice(0, 12).join(", ");
      App.setNotice(
        "error",
        missing.length +
          " ta majburiy savol javobsiz: " +
          shown +
          (missing.length > 12 ? " …" : "") +
          ". 36–45 savollar ixtiyoriy.",
        false
      );
      const first = byId("answer-sheet").querySelector(
        '.q-card[data-position="' + missing[0] + '"]'
      );
      if (first) {
        first.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      return;
    }

    const done = answeredPositions();
    if (!done) {
      App.setNotice("error", "Kamida bitta savolga javob belgilang.", true);
      return;
    }

    const confirmed = await API.confirm(
      done + " ta javob yuboriladi va keyin o'zgartirib bo'lmaydi. Davom etamizmi?"
    );
    if (!confirmed) {
      return;
    }

    submitting = true;
    const button = byId("submit-answers");
    button.disabled = true;
    API.haptic("medium");
    const ctx = attemptCtx; // submit davomida kontekst almashsa ham shu urinishga yozamiz
    try {
      // 0) Ixtiyoriy (36–45) savollar javobsiz bo'lsa — `responses` ga `blank`
      //    sifatida yozamiz (baholashda "noto'g'ri" hisoblanadi).
      items
        .filter(function (item) {
          return item.kind === "numeric";
        })
        .forEach(function (item) {
          const cellId = item.cellId || String(item.position);
          if (isBlank(answers[cellId])) {
            queueAnswer(cellId, null, "numeric");
          }
        });

      // 1) Navbatdagi javoblarni MAJBURIY saqlaymiz — `responses` to'liq bo'lsin.
      await flushAutosave(ctx, false);

      // 2) Item-level urinish mavjud bo'lsa — yakunlaymiz (`attempts.status`).
      //    Xato bo'lsa ham v1 submit davom etadi (asosiy manba: `user_answers`).
      if (ctx && ctx.v2Enabled && ctx.attemptId && !ctx.blocked) {
        try {
          await API.post("/api/v2/submit", { attempt_id: ctx.attemptId });
          ctx.blocked = true;
        } catch (error) {
          const status = error ? error.status : 0;
          if (status === 409 || status === 410) {
            // Allaqachon yakunlangan yoki vaqt tugagan — bu xato emas.
            ctx.blocked = true;
          }
        }
      }

      // 3) Legacy v1 submit — baholash, natijalar va bot uchun asosiy manba.
      const result = await API.post("/api/submit", {
        test_code: examCode || (byId("test-code").value || "").trim().toUpperCase(),
        // v1 ham qism belgisini (`36a`/`36b`) taniydi — a/b javoblari saqlanadi.
        answers: submitAnswers(),
      });
      API.haptic("heavy");
      submitting = false;
      finalizeAttemptCtx(ctx); // navbatdagi flushlar endi hech narsa yozmaydi
      closeAnswerSheet(true); // persist/flush qilmaymiz — hammasi yuborildi
      clearSheetStorage(ctx ? ctx.examId : null);
      App.setNotice("success", result.message, false);
      await loadExams();
    } catch (error) {
      submitting = false;
      button.disabled = false;
      if (error && error.status === 409) {
        // Allaqachon yuborilgan — qurilmadagi nusxani tozalaymiz.
        finalizeAttemptCtx(ctx);
        closeAnswerSheet(true);
        clearSheetStorage(ctx ? ctx.examId : null);
        App.setNotice("success", error.message, false);
        await loadExams();
        return;
      }
      App.alert(error.message);
    }
  }

  window.addEventListener("DOMContentLoaded", function () {
    byId("find-exam").addEventListener("click", function () {
      handleVerifyCode();
    });
    byId("submit-answers").addEventListener("click", handleSubmit);
    byId("cancel-answers").addEventListener("click", function () {
      // Bekor qilishda navbatdagi javoblar serverga saqlanadi (yo'qolmasin).
      closeAnswerSheet(false);
    });
    byId("test-code").addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        handleVerifyCode();
      }
    });
    // O'quvchi kodni qayta yoza boshlaganda eski xato xabari yo'qoladi.
    byId("test-code").addEventListener("input", clearCodeError);
    App.onShow("queue", loadExams);

    // Matematik panel (36–45): barcha tugmalar caret joyiga yoziladi.
    if (window.MathPanel && typeof window.MathPanel.init === "function") {
      window.MathPanel.init({
        onInsert: insertToken,
        onBackspace: backspaceCell,
        onClear: clearCell,
        onLeft: function () {
          moveCaret(-1);
        },
        onRight: function () {
          moveCaret(1);
        },
        onDelete: deleteCell,
        onFraction: openFractionModal,
        onSmartFraction: smartFractionCell,
        onAngle: function () {
          // Rejim almashdi — aktiv katak qiymati qayta hisoblanadi.
          if (activeCell && cellOf(activeCell)) {
            applyExpression(activeCell, expressions[activeCell] || "");
          }
        },
        onConfirm: function () {
          // Tasdiqlash (✓): javob saqlanadi va KEYINGI qismga o'tamiz.
          const current = activeCell;
          if (!current || !cellOf(current)) {
            return;
          }
          flushNow(false);
          const order = items.map(function (item) {
            return item.cellId || String(item.position);
          });
          const next = order[order.indexOf(current) + 1];
          if (next && cellOf(next)) {
            activateCell(next);
          } else if (window.MathPanel) {
            window.MathPanel.detach();
          }
        },
        onClose: function () {
          const previous = activeCell;
          activeCell = null;
          if (previous) {
            refreshCellView(previous);
          }
          flushNow(false); // yopishdan oldin navbatni yuboramiz
        },
      });
    }

    // Kasr konstruktori (2 slot) tugmalari.
    const fracAdd = byId("frac-add");
    const fracCancel = byId("frac-cancel");
    const fracModal = byId("frac-modal");
    if (fracAdd) {
      fracAdd.addEventListener("click", submitFractionModal);
    }
    if (fracCancel) {
      fracCancel.addEventListener("click", closeFractionModal);
    }
    if (fracModal) {
      fracModal.addEventListener("click", function (event) {
        if (event.target === fracModal) {
          closeFractionModal();
        }
      });
    }

    // Oxirgi javoblar yo'qolmasligi uchun: fon/yopilish/tarmoq hodisalarida
    // darhol (debounce'siz) serverga saqlaymiz.
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") {
        flushNow(true);
      }
    });
    window.addEventListener("pagehide", function () {
      flushNow(true);
    });
    window.addEventListener("online", function () {
      flushAutosave(attemptCtx, false);
    });

    // Sahifa yangilangan bo'lsa: oxirgi test kodini tiklab, javoblarni qaytaramiz.
    const savedCode = storageGet(CODE_KEY);
    if (savedCode) {
      handleVerifyCode(savedCode);
    }
  });
})();
