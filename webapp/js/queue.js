/* ---------------------------------------------------------------------------
   "Navbat" bo'limi: test kodini tekshirish, javoblar varag'ini to'ldirish va
   navbatdagi imtihonlar ro'yxati.
--------------------------------------------------------------------------- */
(function () {
  "use strict";

  const STATUS_CLASS = {
    upcoming: "upcoming",
    active: "active",
    closed: "closed",
    published: "published",
  };

  let selectedExam = null;
  let deadline = 0;
  let timer = null;

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

  function countAnswered() {
    const value = (byId("answer-input").value || "").toUpperCase();
    const matches = value.match(/[1-9][0-9]*\s*[ABCD]/g);
    return matches ? matches.length : 0;
  }

  function updateCountdown() {
    if (!selectedExam) {
      return;
    }
    const meta = byId("answer-meta");
    const remaining = Math.round((deadline - Date.now()) / 1000);
    const base =
      selectedExam.total_questions + " savol · belgilangan: " + countAnswered() + " ta";

    if (remaining <= 0) {
      meta.textContent = base + " · javob qabul qilish vaqti tugadi";
      byId("submit-answers").disabled = true;
      return;
    }
    meta.textContent = base + " · qolgan vaqt: " + App.formatCountdown(remaining);
  }

  function openAnswerSheet(exam) {
    selectedExam = exam;
    deadline = Date.now() + Math.max(0, exam.seconds_left) * 1000;

    byId("answer-card").classList.remove("hidden");
    byId("answer-title").textContent = exam.title;
    byId("answer-input").value = "";
    byId("submit-answers").disabled = false;

    if (timer) {
      window.clearInterval(timer);
    }
    timer = window.setInterval(updateCountdown, 1000);
    updateCountdown();
    App.setNotice("success", exam.message || "Test kodi tasdiqlandi.", true);
    byId("answer-card").scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function closeAnswerSheet() {
    selectedExam = null;
    if (timer) {
      window.clearInterval(timer);
      timer = null;
    }
    byId("answer-card").classList.add("hidden");
    byId("answer-input").value = "";
  }

  async function handleVerifyCode() {
    const code = (byId("test-code").value || "").trim().toUpperCase();
    if (code.length < 4) {
      App.setNotice("error", "Test kodi kamida 4 belgidan iborat bo'lishi kerak.", true);
      return;
    }

    API.haptic("medium");
    App.clearNotice();
    try {
      const exam = await API.post("/api/verify-code", { test_code: code });
      if (exam.submitted) {
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
        App.setNotice("error", exam.message, false);
        return;
      }
      openAnswerSheet(exam);
    } catch (error) {
      App.alert(error.message);
    }
  }

  async function handleSubmit() {
    if (!selectedExam) {
      return;
    }
    const answers = (byId("answer-input").value || "").trim();
    if (!answers) {
      App.setNotice("error", "Javoblar bo'sh — avval javoblar varag'ini to'ldiring.", true);
      return;
    }

    const button = byId("submit-answers");
    button.disabled = true;
    API.haptic("medium");
    try {
      const result = await API.post("/api/submit", {
        test_code: (byId("test-code").value || "").trim().toUpperCase(),
        answers: answers,
      });
      API.haptic("heavy");
      closeAnswerSheet();
      App.setNotice("success", result.message, false);
      await loadExams();
    } catch (error) {
      button.disabled = false;
      App.alert(error.message);
    }
  }

  window.addEventListener("DOMContentLoaded", function () {
    byId("find-exam").addEventListener("click", handleVerifyCode);
    byId("submit-answers").addEventListener("click", handleSubmit);
    byId("cancel-answers").addEventListener("click", closeAnswerSheet);
    byId("answer-input").addEventListener("input", updateCountdown);
    byId("test-code").addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        handleVerifyCode();
      }
    });
    App.onShow("queue", loadExams);
  });
})();
