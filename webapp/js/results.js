/* ---------------------------------------------------------------------------
   "Natijalar" bo'limi: dinamika grafigi (Chart.js), topshirilgan imtihonlar
   tarixi va bitta imtihon bo'yicha batafsil tahlil (modal oyna).
--------------------------------------------------------------------------- */
(function () {
  "use strict";

  let chart = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function shorten(text, limit) {
    const clean = String(text || "");
    return clean.length <= limit ? clean : clean.slice(0, limit - 1) + "…";
  }

  function renderChart(chartData) {
    const canvas = byId("results-chart");
    const fallback = byId("chart-fallback");
    const labels = (chartData && chartData.labels) || [];
    const scaled = (chartData && chartData.scaled) || [];

    if (!labels.length) {
      canvas.classList.add("hidden");
      fallback.classList.remove("hidden");
      fallback.innerHTML =
        '<p class="muted">Hali e\'lon qilingan natija yo\'q — birinchi imtihon ' +
        "natijasi chiqqach grafik shu yerda paydo bo'ladi.</p>";
      return;
    }

    if (typeof Chart === "undefined") {
      canvas.classList.add("hidden");
      fallback.classList.remove("hidden");
      fallback.innerHTML =
        '<p class="muted">Grafik kutubxonasi yuklanmadi. Natijalar ro\'yxati:</p>' +
        labels
          .map(function (label, index) {
            return (
              '<div class="exam-item"><div><div class="title">' +
              App.escape(label) +
              "</div></div><div>" +
              Math.round(scaled[index]) +
              " ball</div></div>"
            );
          })
          .join("");
      return;
    }

    canvas.classList.remove("hidden");
    fallback.classList.add("hidden");

    const theme = API.theme();
    const textColor = theme.text_color || "#10151c";
    const buttonColor = theme.button_color || "#2f7ce0";

    if (chart) {
      chart.destroy();
    }
    chart = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "0–100 ball",
            data: scaled,
            borderColor: buttonColor,
            backgroundColor: "rgba(47,124,224,0.18)",
            borderWidth: 2,
            tension: 0.3,
            fill: true,
            pointRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function (items) {
                return labels[items[0].dataIndex];
              },
            },
          },
        },
        scales: {
          y: {
            min: 0,
            max: 100,
            ticks: { color: textColor, stepSize: 25 },
            grid: { color: "rgba(128,128,128,0.18)" },
          },
          x: {
            ticks: {
              color: textColor,
              maxRotation: 0,
              autoSkip: true,
              callback: function (value) {
                return shorten(this.getLabelForValue(value), 9);
              },
            },
            grid: { display: false },
          },
        },
      },
    });
  }

  function renderList(data) {
    const box = byId("results-list");
    const published = data.published || [];
    const pending = data.pending || [];
    const summary = data.summary || {};

    let summaryText =
      "Topshirilgan: " + (summary.attempts || 0) + " · e'lon qilingan: " + (summary.published || 0);
    if (summary.best_scaled !== null && summary.best_scaled !== undefined) {
      summaryText += " · eng yaxshi ball: " + summary.best_scaled;
    }
    if (summary.average_scaled !== null && summary.average_scaled !== undefined) {
      summaryText += " · o'rtacha: " + summary.average_scaled;
    }
    byId("summary-line").textContent = summaryText;

    if (!published.length && !pending.length) {
      box.innerHTML =
        '<p class="muted">Siz hali imtihon topshirmagansiz. «Navbat» bo\'limida ' +
        "test kodini kiritib boshlang.</p>";
      return;
    }

    const rows = [];

    pending.forEach(function (item) {
      rows.push(
        '<div class="exam-item"><div><div class="title">' +
          App.escape(item.title) +
          "</div>" +
          '<div class="meta">Yuborilgan: ' +
          App.escape(item.submitted_at) +
          " · natija: " +
          App.escape(item.result_time_local || "—") +
          "</div></div>" +
          '<span class="badge closed">Kutilmoqda</span></div>'
      );
    });

    published.forEach(function (item) {
      const theta = Number(item.theta);
      rows.push(
        '<div class="exam-item" data-exam="' +
          item.exam_id +
          '"><div><div class="title">' +
          App.escape(item.title) +
          "</div>" +
          '<div class="meta">' +
          App.escape(item.submitted_at) +
          " · " +
          item.raw_score +
          "/" +
          item.total_questions +
          " · θ = " +
          (theta >= 0 ? "+" : "") +
          theta.toFixed(2) +
          "</div></div>" +
          '<div class="score-pill">' +
          Math.round(item.scaled_score) +
          "<small>ball</small></div></div>"
      );
    });

    box.innerHTML = rows.join("");
    box.querySelectorAll("[data-exam]").forEach(function (element) {
      element.addEventListener("click", function () {
        openDetail(Number(element.dataset.exam));
      });
    });
  }

  async function loadResults() {
    const box = byId("results-list");
    box.innerHTML = '<div class="spinner"></div>';
    try {
      const data = await API.get("/api/results");
      renderChart(data.chart || {});
      renderList(data);
    } catch (error) {
      box.innerHTML = '<p class="muted">' + App.escape(error.message) + "</p>";
    }
  }

  function closeModal() {
    byId("modal-root").innerHTML = "";
  }

  function attachModalHandlers(root) {
    const backdrop = root.querySelector(".modal-backdrop");
    if (backdrop) {
      backdrop.addEventListener("click", function (event) {
        if (event.target.classList.contains("modal-backdrop")) {
          closeModal();
        }
      });
    }
    const closeButton = root.querySelector(".close");
    if (closeButton) {
      closeButton.addEventListener("click", closeModal);
    }
  }

  function openDetail(examId) {
    const root = byId("modal-root");
    root.innerHTML =
      '<div class="modal-backdrop"><div class="modal"><div class="spinner"></div></div></div>';
    attachModalHandlers(root);

    API.get("/api/results/" + examId)
      .then(function (report) {
        const items = (report.items || [])
          .map(function (item) {
            return (
              '<div class="item-cell ' +
              (item.is_correct ? "ok" : "bad") +
              '"><b>' +
              App.escape(item.given_answer || "—") +
              "</b><small>" +
              item.number +
              " · " +
              App.escape(item.correct_answer) +
              "</small></div>"
            );
          })
          .join("");

        const theta = Number(report.theta);
        const se =
          report.standard_error === null
            ? "chekka holat"
            : Number(report.standard_error).toFixed(3);
        const interval = report.scaled_interval
          ? '<div class="profile-row"><span class="label">95% ishonch oralig\'i</span><b>' +
            report.scaled_interval[0] +
            " – " +
            report.scaled_interval[1] +
            " ball</b></div>"
          : "";

        root.innerHTML =
          '<div class="modal-backdrop"><div class="modal">' +
          '<div class="modal-head"><h2>' +
          App.escape(report.title) +
          '</h2><button class="close" type="button">×</button></div>' +
          '<div class="profile-row"><span class="label">Natija</span><b>' +
          Math.round(report.scaled_score) +
          " ball</b></div>" +
          '<div class="profile-row"><span class="label">Bilim darajasi (θ)</span><b>' +
          (theta >= 0 ? "+" : "") +
          theta.toFixed(3) +
          " logit</b></div>" +
          '<div class="profile-row"><span class="label">To\'g\'ri javoblar</span><b>' +
          report.raw_score +
          " / " +
          report.total_questions +
          "</b></div>" +
          '<div class="profile-row"><span class="label">Standart xato (SE)</span><b>' +
          se +
          "</b></div>" +
          interval +
          '<div class="profile-row"><span class="label">Daraja</span><b>' +
          App.escape(report.ability_level) +
          "</b></div>" +
          '<p class="muted">' +
          App.escape(report.advice) +
          "</p>" +
          '<h2 style="font-size:15px">Savollar tahlili</h2>' +
          '<p class="muted">Katta harf — sizning javobingiz, kichigi — to\'g\'ri javob.</p>' +
          '<div class="item-grid">' +
          items +
          "</div></div></div>";

        attachModalHandlers(root);
      })
      .catch(function (error) {
        closeModal();
        App.alert(error.message);
      });
  }

  window.addEventListener("DOMContentLoaded", function () {
    App.onShow("results", loadResults);
  });
})();
