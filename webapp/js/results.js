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

  /**
   * Ball ko'rinishi: har doim 1 kasr xona (20.4 · 67.8 · 50.0).
   * Ball hech qachon butun songa yaxlitlanmaydi — o'quvchi aniq natijasini
   * ko'rishi kerak.
   */
  function formatScore(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(1) : "—";
  }

  // ---------------------------------------------------------------------------
  // Holat (state) va daraja (sertifikat) yordamchilari
  // ---------------------------------------------------------------------------
  const state = {
    data: null,
    filter: "all",
    metric: "scaled",
    heroToken: 0,
    timer: null,
  };

  /**
   * Sertifikat darajalari — `services/rasch.py::CERTIFICATE_LEVELS` bilan bir xil
   * chegaralar (server `level` maydonini bersa, o'sha ishlatiladi; bu — zaxira).
   */
  const LEVELS = [
    { code: "NC", min: 0, tone: "res-tone-nc" },
    { code: "C", min: 46, tone: "res-tone-c" },
    { code: "C+", min: 50, tone: "res-tone-c-plus" },
    { code: "B", min: 55, tone: "res-tone-b" },
    { code: "B+", min: 60, tone: "res-tone-b-plus" },
    { code: "A", min: 65, tone: "res-tone-a" },
    { code: "A+", min: 70, tone: "res-tone-a-plus" },
  ];

  // Grafik nuqtalari uchun ranglar (CSS "ton"lari bilan mos).
  const LEVEL_COLORS = {
    NC: "#8b93a3",
    C: "#e0507a",
    "C+": "#7c5cff",
    B: "#d98c0b",
    "B+": "#2f9be0",
    A: "#1e9e62",
    "A+": "#0f9d76",
  };

  const MONTHS = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
  ];

  /** Inline SVG ikonkalar (emoji emas — uslub va rang bir xil bo'lsin). */
  function icon(name, size) {
    const pixels = size || 16;
    const paths = {
      trophy:
        '<path d="M8 4h8v5a4 4 0 0 1-8 0V4Z"/>' +
        '<path d="M8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4"/>' +
        '<path d="M12 13v4M9 21h6M10 17h4"/>',
      trend: '<path d="M3 17l6-6 4 4 7-7"/><path d="M14 8h6v6"/>',
      list: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
      target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
      arrowUp: '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
      arrowDown: '<path d="M12 5v14"/><path d="M18 13l-6 6-6-6"/>',
      clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
      chevron: '<path d="M9 6l6 6-6 6"/>',
      sparkle:
        '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/>' +
        '<path d="M18.5 16.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7.7-2Z"/>',
      chart:
        '<path d="M4 19V5"/><path d="M4 19h16"/>' +
        '<path d="M8 15l3-4 3 2 4-6"/>',
    };
    return (
      '<svg width="' + pixels + '" height="' + pixels + '" viewBox="0 0 24 24" ' +
      'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round" aria-hidden="true">' + (paths[name] || "") + "</svg>"
    );
  }

  function levelCode(score) {
    const value = Number(score);
    if (!Number.isFinite(value)) {
      return "NC";
    }
    let code = "NC";
    LEVELS.forEach(function (level) {
      if (value >= level.min) {
        code = level.code;
      }
    });
    return code;
  }

  function toneOf(item) {
    const code = (item && item.level) || levelCode(item && item.scaled_score);
    for (let index = 0; index < LEVELS.length; index += 1) {
      if (LEVELS[index].code === code) {
        return LEVELS[index].tone;
      }
    }
    return "res-tone-nc";
  }

  /** "DB vaqti" (UTC ISO, ba'zan soniyasiz kesilgan) → `Date`. */
  function parseDbTime(value) {
    if (!value) {
      return null;
    }
    let text = String(value).trim();
    if (!text) {
      return null;
    }
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text)) {
      text += ":00Z";
    } else if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(text)) {
      text += "Z";
    }
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function timeOf(item) {
    const date = parseDbTime(item && item.submitted_at);
    return date ? date.getTime() : 0;
  }

  function formatDate(date) {
    if (!date) {
      return "—";
    }
    return date.getDate() + "-" + MONTHS[date.getMonth()] + " " + date.getFullYear();
  }

  function formatRemaining(milliseconds) {
    const total = Math.max(0, Math.floor(milliseconds / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    if (hours >= 24) {
      return Math.floor(hours / 24) + " kun " + (hours % 24) + " soat";
    }
    if (hours > 0) {
      return hours + " soat " + minutes + " daq.";
    }
    if (minutes > 0) {
      return minutes + " daq. " + String(seconds).padStart(2, "0") + " son.";
    }
    return seconds + " son.";
  }

  function signed(value, digits) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "—";
    }
    return (number >= 0 ? "+" : "") + number.toFixed(digits);
  }

  // Y o'qi uchun "yumaloq" qadamlar (faqat masshtab; dizayn o'zgarmaydi).
  const AXIS_STEPS = [1, 2, 5, 10, 20, 25, 50, 100];

  /**
   * Grafikning Y o'qi chegarasi va qadamini hisoblaydi.
   *
   * Past chegara har doim 0 (ball shkalasi 0–100), yuqori chegara esa eng katta
   * natijaga moslashadi — shunda o'sish dinamikasi vizual aniq ko'rinadi:
   *   35.7 → 0, 10, 20, 30, 40
   *   67.3 → 0, 20, 40, 60, 80
   *   91.4 → 0, 25, 50, 75, 100
   */
  function scoreAxis(values) {
    const numbers = (values || [])
      .map(function (value) {
        return Number(value);
      })
      .filter(function (value) {
        return Number.isFinite(value);
      });
    const top = numbers.length ? Math.max.apply(null, numbers) : 0;
    if (!(top > 0)) {
      return { max: 10, step: 2 };
    }

    // ~4 bo'linma hosil qiladigan eng kichik "yumaloq" qadam.
    const target = top / 4;
    let step = AXIS_STEPS[AXIS_STEPS.length - 1];
    for (let index = 0; index < AXIS_STEPS.length; index += 1) {
      if (AXIS_STEPS[index] >= target) {
        step = AXIS_STEPS[index];
        break;
      }
    }

    return { max: Math.min(100, Math.ceil(top / step) * step), step: step };
  }

  // Daraja zonalari — diagramma fonidagi rangli polosalar (A+ yashil … NC kulrang).
  const LEVEL_ZONES = [
    { min: 0, max: 46, color: "rgba(120,120,120,0.10)" },
    { min: 46, max: 50, color: "rgba(248,187,208,0.20)" },
    { min: 50, max: 55, color: "rgba(197,202,233,0.22)" },
    { min: 55, max: 60, color: "rgba(255,224,178,0.22)" },
    { min: 60, max: 65, color: "rgba(255,249,196,0.30)" },
    { min: 65, max: 70, color: "rgba(187,222,251,0.24)" },
    { min: 70, max: 1000, color: "rgba(200,230,201,0.26)" },
  ];

  const levelZonesPlugin = {
    id: "levelZones",
    beforeDatasetsDraw: function (instance) {
      const y = instance.scales.y;
      const area = instance.chartArea;
      if (!y || !area) {
        return;
      }
      const ctx = instance.ctx;
      ctx.save();
      LEVEL_ZONES.forEach(function (zone) {
        // Zona faqat grafik maydonchasi ichida bo'yaladi (tashqariga chiqmaydi).
        const top = Math.max(area.top, y.getPixelForValue(zone.max));
        const bottom = Math.min(area.bottom, y.getPixelForValue(zone.min));
        if (bottom <= top) {
          return;
        }
        ctx.fillStyle = zone.color;
        ctx.fillRect(area.left, top, area.right - area.left, bottom - top);
      });
      ctx.restore();
    },
  };

  /** Daraja zonalari faqat 0–100 ball shkalasida ma'noga ega (θ da yo'q). */
  function makeZonePlugin(metric) {
    return {
      id: "levelZones",
      beforeDatasetsDraw: function (instance) {
        if (metric !== "scaled") {
          return;
        }
        levelZonesPlugin.beforeDatasetsDraw(instance);
      },
    };
  }

  /** θ (logit) o'qi uchun yumshoq chegaralar. */
  function thetaAxis(values) {
    const numbers = (values || [])
      .map(function (value) {
        return Number(value);
      })
      .filter(function (value) {
        return Number.isFinite(value);
      });
    if (!numbers.length) {
      return { min: -3, max: 3 };
    }
    let low = Math.min.apply(null, numbers);
    let high = Math.max.apply(null, numbers);
    if (high - low < 1) {
      const middle = (low + high) / 2;
      low = middle - 0.5;
      high = middle + 0.5;
    }
    const padding = (high - low) * 0.18;
    return {
      min: Math.floor((low - padding) * 10) / 10,
      max: Math.ceil((high + padding) * 10) / 10,
    };
  }

  /** HEX rangni shaffof rgba ga aylantiradi (gradient uchun). */
  function withAlpha(color, alpha) {
    const match = /^#([0-9a-f]{6})$/i.exec(String(color || "").trim());
    if (!match) {
      return "rgba(47,124,224," + alpha + ")";
    }
    const value = parseInt(match[1], 16);
    return (
      "rgba(" + ((value >> 16) & 255) + "," + ((value >> 8) & 255) + "," +
      (value & 255) + "," + alpha + ")"
    );
  }

  /** Zamonaviy gradient to'ldirish (yuqoridan rang → pastga shaffof). */
  function gradientFill(color) {
    return function (context) {
      const area = context.chart.chartArea;
      if (!area) {
        return withAlpha(color, 0.12);
      }
      const gradient = context.chart.ctx.createLinearGradient(
        0,
        area.top,
        0,
        area.bottom
      );
      gradient.addColorStop(0, withAlpha(color, 0.34));
      gradient.addColorStop(1, withAlpha(color, 0.02));
      return gradient;
    };
  }

  function renderChart(chartData) {
    const canvas = byId("results-chart");
    const fallback = byId("chart-fallback");
    const wrap = canvas ? canvas.parentElement : null;
    const labels = (chartData && chartData.labels) || [];
    const metric = state.metric === "theta" ? "theta" : "scaled";
    const scaled = (chartData && chartData.scaled) || [];
    const theta = (chartData && chartData.theta) || [];
    const series = metric === "theta" ? theta : scaled;

    renderScaleLegend();

    if (!labels.length) {
      if (chart) {
        chart.destroy();
        chart = null;
      }
      if (wrap) {
        wrap.classList.add("hidden");
      }
      canvas.classList.add("hidden");
      fallback.classList.remove("hidden");
      fallback.innerHTML =
        '<p class="muted">Grafik birinchi e\'lon qilingan natijadan keyin ' +
        "shu yerda paydo bo'ladi.</p>";
      return;
    }

    if (typeof Chart === "undefined") {
      if (chart) {
        chart.destroy();
        chart = null;
      }
      if (wrap) {
        wrap.classList.add("hidden");
      }
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
              formatScore(scaled[index]) +
              " ball</div></div>"
            );
          })
          .join("");
      return;
    }

    canvas.classList.remove("hidden");
    fallback.classList.add("hidden");
    if (wrap) {
      wrap.classList.remove("hidden");
    }

    // Ball: 0 dan maksimalgacha; θ: qiymatlar atrofida yumshoq chegara.
    const axis = metric === "theta" ? thetaAxis(theta) : scoreAxis(scaled);

    const theme = API.theme();
    const textColor = theme.text_color || "#10151c";
    const buttonColor = theme.button_color || "#2f7ce0";

    // Nuqta rangi = o'sha natijaning sertifikat darajasi (θ da — brend rangi).
    const pointBackgrounds = labels.map(function (label, index) {
      if (metric === "theta") {
        return "#ffffff";
      }
      return LEVEL_COLORS[levelCode(scaled[index])] || buttonColor;
    });
    const pointRadii = labels.map(function (label, index) {
      return index === labels.length - 1 ? 6 : 4;
    });

    if (chart) {
      chart.destroy();
      chart = null;
    }
    chart = new Chart(canvas.getContext("2d"), {
      type: "line",
      plugins: [makeZonePlugin(metric)],
      data: {
        labels: labels,
        datasets: [
          {
            label: metric === "theta" ? "θ (logit)" : "0–100 ball",
            data: series,
            borderColor: buttonColor,
            backgroundColor:
              metric === "theta"
                ? withAlpha(buttonColor, 0.12)
                : gradientFill(buttonColor),
            borderWidth: 3,
            tension: 0.4,
            fill: true,
            spanGaps: true,
            pointRadius: pointRadii,
            pointHoverRadius: 7,
            pointBackgroundColor:
              metric === "scaled" ? pointBackgrounds : "#ffffff",
            pointBorderColor: metric === "scaled" ? "#ffffff" : buttonColor,
            pointBorderWidth: 2.5,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 600 },
        interaction: { intersect: false, mode: "index" },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(15,23,42,0.92)",
            padding: 10,
            cornerRadius: 10,
            displayColors: false,
            callbacks: {
              title: function (items) {
                return labels[items[0].dataIndex];
              },
              label: function (item) {
                const value = Number(item.parsed.y);
                if (!Number.isFinite(value)) {
                  return "—";
                }
                if (metric === "theta") {
                  return "θ " + signed(value, 2) + " logit";
                }
                return formatScore(value) + " ball · daraja " + levelCode(value);
              },
            },
          },
        },
        scales: {
          y: {
            min: metric === "theta" ? axis.min : 0,
            max: axis.max,
            ticks: {
              color: textColor,
              stepSize: metric === "theta" ? undefined : axis.step,
              callback:
                metric === "theta"
                  ? function (value) {
                      return signed(value, 1);
                    }
                  : function (value) {
                      return Number(value).toFixed(0);
                    },
            },
            grid: { color: "rgba(128,128,128,0.18)" },
            border: { display: false },
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
            border: { display: false },
          },
        },
      },
    });
  }

  function renderList(data) {
    const box = byId("results-list");
    if (!box) {
      return;
    }
    const published = data.published || [];
    const pending = data.pending || [];

    if (!published.length && !pending.length) {
      box.classList.add("hidden");
      box.innerHTML = "";
      renderFilters(data);
      return;
    }

    // Filtr tanlangan bo'lim bo'sh bo'lib qolsa — "Barchasi"ga qaytamiz.
    if (state.filter === "published" && !published.length) {
      state.filter = "all";
    }
    if (state.filter === "pending" && !pending.length) {
      state.filter = "all";
    }

    const asc = published.slice().sort(function (a, b) {
      return timeOf(a) - timeOf(b);
    });
    const previousByExam = {};
    for (let index = 1; index < asc.length; index += 1) {
      previousByExam[asc[index].exam_id] = Number(asc[index - 1].scaled_score);
    }
    let bestScore = -Infinity;
    asc.forEach(function (item) {
      const score = Number(item.scaled_score);
      if (score > bestScore) {
        bestScore = score;
      }
    });

    const rows = [];
    if (state.filter !== "published") {
      pending
        .slice()
        .sort(function (a, b) {
          return pendingTime(a) - pendingTime(b);
        })
        .forEach(function (item) {
          rows.push(pendingItemHtml(item));
        });
    }
    if (state.filter !== "pending") {
      asc
        .slice()
        .reverse()
        .forEach(function (item) {
          const score = Number(item.scaled_score);
          const isBest = asc.length > 1 && Math.abs(score - bestScore) < 1e-9;
          rows.push(itemHtml(item, previousByExam[item.exam_id], isBest));
        });
    }

    box.classList.remove("hidden");
    box.innerHTML = rows.length
      ? '<div class="res-timeline">' + rows.join("") + "</div>"
      : '<div class="res-empty-list">Bu bo\'limda yozuv yo\'q.</div>';

    const countBox = byId("results-count");
    if (countBox) {
      countBox.textContent = pending.length
        ? published.length + " ta natija · " + pending.length + " kutilmoqda"
        : published.length + " ta natija";
    }

    box.querySelectorAll("[data-exam]").forEach(function (element) {
      element.addEventListener("click", function () {
        openDetail(Number(element.getAttribute("data-exam")));
      });
    });

    renderFilters(data);
    startCountdowns();
  }

  /** Kutilayotgan natijalarni saralash vaqti (eng yaqin e'lon birinchi). */
  function pendingTime(item) {
    const until = parseDbTime(item && item.result_time);
    if (until) {
      return until.getTime();
    }
    const submitted = parseDbTime(item && item.submitted_at);
    return submitted ? submitted.getTime() : 0;
  }

  /** Filtr tugmalari: sanoq + faol holat (bo'sh bo'lim o'chiriladi). */
  function renderFilters(data) {
    const box = byId("results-filters");
    if (!box) {
      return;
    }
    const published = (data.published || []).length;
    const pending = (data.pending || []).length;
    const counts = {
      all: published + pending,
      published: published,
      pending: pending,
    };
    const labels = {
      all: "Barchasi",
      published: "E'lon qilingan",
      pending: "Kutilmoqda",
    };

    if (!counts.all) {
      box.classList.add("hidden");
      return;
    }
    box.classList.remove("hidden");

    box.querySelectorAll("[data-filter]").forEach(function (button) {
      const key = button.getAttribute("data-filter");
      const isActive = key === state.filter;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-selected", isActive ? "true" : "false");
      button.disabled = counts[key] === 0;
      button.innerHTML =
        labels[key] + ' <span class="res-filter-count">' + counts[key] + "</span>";
    });
  }

  async function loadResults() {
    // Birinchi yuklashda skelet; keyingi ochishlarda eski ma'lumot ko'rinib
    // turadi (fon rejimida yangilanadi) — "miltillash" bo'lmaydi.
    if (!state.data) {
      showSkeleton();
    }
    try {
      const data = await API.get("/api/results");
      state.data = data;
      renderHero(data);
      renderStats(data);
      renderList(data);
      renderChart(data.chart || {});
      renderSectionState(data);
    } catch (error) {
      if (!state.data) {
        showError(error.message);
      } else {
        App.setNotice("error", error.message, true);
      }
    }
  }

  /** Umumiy ko'rinish: ma'lumot yo'q bo'lsa ortiqcha bloklar yashiriladi. */
  function renderSectionState(data) {
    const published = (data.published || []).length;
    const pending = (data.pending || []).length;
    byId("results-stats").classList.toggle("hidden", !published);
    byId("results-chart-card").classList.toggle("hidden", !published);
    byId("results-list-head").classList.toggle("hidden", !published && !pending);
  }

  /** Birinchi yuklanish: spinner o'rniga skelet kartalar. */
  function showSkeleton() {
    const hero = byId("results-hero");
    if (hero) {
      hero.innerHTML = '<div class="res-skeleton res-skeleton-hero"></div>';
    }
    const stats = byId("results-stats");
    if (stats) {
      stats.classList.remove("hidden");
      stats.innerHTML =
        '<div class="res-skeleton res-skeleton-tile"></div>' +
        '<div class="res-skeleton res-skeleton-tile"></div>' +
        '<div class="res-skeleton res-skeleton-tile"></div>' +
        '<div class="res-skeleton res-skeleton-tile"></div>';
    }
    byId("results-chart-card").classList.add("hidden");
    byId("results-list-head").classList.add("hidden");
    byId("results-filters").classList.add("hidden");
    const list = byId("results-list");
    if (list) {
      list.classList.remove("hidden");
      list.innerHTML =
        '<div class="res-skeleton res-skeleton-row"></div>' +
        '<div class="res-skeleton res-skeleton-row"></div>';
    }
  }

  /** Xatolik holati (eski ma'lumot bo'lmasa — qayta urinish tugmasi bilan). */
  function showError(message) {
    const hero = byId("results-hero");
    if (hero) {
      hero.innerHTML =
        '<div class="res-error"><p>' + App.escape(message) + "</p>" +
        '<button type="button" id="res-retry">Qayta urinish</button></div>';
      const retry = byId("res-retry");
      if (retry) {
        retry.addEventListener("click", loadResults);
      }
    }
    byId("results-stats").classList.add("hidden");
    byId("results-chart-card").classList.add("hidden");
    byId("results-list-head").classList.add("hidden");
    byId("results-filters").classList.add("hidden");
    byId("results-list").classList.add("hidden");
  }

  /** 0–100 shkaladagi ball halqasi (SVG; tashqi kutubxona kerak emas). */
  function ringHtml(score, tone) {
    const circumference = 2 * Math.PI * 46;
    const value = Math.max(0, Math.min(100, Number(score) || 0));
    const offset = circumference * (1 - value / 100);
    return (
      '<div class="res-ring ' + tone + '">' +
      '<svg viewBox="0 0 110 110" aria-hidden="true">' +
      '<circle class="res-ring-track" cx="55" cy="55" r="46"></circle>' +
      '<circle class="res-ring-progress" cx="55" cy="55" r="46" ' +
      'stroke-dasharray="' + circumference.toFixed(2) + '" ' +
      'stroke-dashoffset="' + offset.toFixed(2) + '"></circle>' +
      "</svg>" +
      '<div class="res-ring-text">' +
      '<span class="res-ring-score">' + formatScore(score) + "</span>" +
      '<span class="res-ring-unit">ball</span>' +
      "</div></div>"
    );
  }

  /** Hero ichidagi o'sish/kamayish bloki (oldingi imtihonga nisbatan). */
  function deltaBlock(delta) {
    if (delta === null || delta === undefined || !Number.isFinite(Number(delta))) {
      return (
        '<div class="res-delta flat">— <span>ball</span></div>' +
        '<div class="res-hero-level">Taqqoslash uchun oldingi natija yo\'q</div>'
      );
    }
    const value = Number(delta);
    if (Math.abs(value) < 0.05) {
      return (
        '<div class="res-delta flat">0.0 <span>ball</span></div>' +
        '<div class="res-hero-level">Oldingi natija bilan bir xil</div>'
      );
    }
    const up = value > 0;
    return (
      '<div class="res-delta ' + (up ? "up" : "down") + '">' +
      icon(up ? "arrowUp" : "arrowDown", 14) +
      (up ? "+" : "-") + formatScore(Math.abs(value)) +
      ' <span>ball</span></div>' +
      '<div class="res-hero-level">Oldingi imtihonga nisbatan</div>'
    );
  }

  /** 95% ishonch oralig'i: trek + oraliq + ball nuqtasi. */
  function intervalHtml(low, high, score) {
    const left = Math.max(0, Math.min(100, Number(low)));
    const right = Math.max(0, Math.min(100, Number(high)));
    const width = Math.max(0, right - left);
    const dot = Math.max(0, Math.min(100, Number(score)));
    return (
      '<div class="res-interval">' +
      '<div class="res-interval-head"><span>95% ishonch oralig\'i</span>' +
      "<b>" + formatScore(low) + " – " + formatScore(high) + "</b></div>" +
      '<div class="res-interval-track">' +
      '<span class="res-interval-range" style="left:' + left.toFixed(1) +
      "%;width:" + width.toFixed(1) + '%"></span>' +
      '<span class="res-interval-dot" style="left:' + dot.toFixed(1) + '%"></span>' +
      "</div></div>"
    );
  }

  /** Bosh karta: eng so'nggi natija (yoki kutilayotgan natija / bo'sh holat). */
  function renderHero(data) {
    const box = byId("results-hero");
    if (!box) {
      return;
    }
    const published = data.published || [];
    const pending = data.pending || [];
    state.heroToken += 1; // eski "batafsil" javobi endi kerak emas

    if (!published.length) {
      if (pending.length) {
        box.innerHTML = pendingHeroHtml(pending);
        startCountdowns();
      } else {
        box.innerHTML = emptyHeroHtml();
        const cta = byId("res-go-queue");
        if (cta) {
          cta.addEventListener("click", function () {
            const button = document.querySelector(
              '#bottom-nav button[data-tab="queue"]'
            );
            if (button) {
              button.click();
            }
          });
        }
      }
      return;
    }

    const asc = published.slice().sort(function (a, b) {
      return timeOf(a) - timeOf(b);
    });
    const latest = asc[asc.length - 1];
    const previous = asc.length > 1 ? asc[asc.length - 2] : null;
    const score = Number(latest.scaled_score);
    const delta = previous ? score - Number(previous.scaled_score) : null;
    const level = latest.level || levelCode(score);
    const tone = toneOf(latest);
    const submitted = parseDbTime(latest.submitted_at);
    const total = Number(latest.total_questions) || 0;
    const raw = Number(latest.raw_score) || 0;
    const best = Math.max.apply(
      null,
      asc.map(function (item) {
        return Number(item.scaled_score);
      })
    );
    const isRecord = asc.length > 1 && Math.abs(score - best) < 1e-9;

    box.innerHTML =
      '<div class="res-hero ' + tone + '">' +
      '<div class="res-hero-top"><div>' +
      '<div class="res-hero-eyebrow">So\'nggi natija</div>' +
      '<div class="res-hero-title">' + App.escape(latest.title) + "</div>" +
      '<div class="res-hero-meta">' + formatDate(submitted) + " · " +
      raw + "/" + total + " to'g'ri javob</div>" +
      "</div>" +
      '<span class="res-chip">' + App.escape(level) + "</span>" +
      "</div>" +
      '<div class="res-hero-main">' + ringHtml(score, tone) +
      '<div class="res-hero-side">' + deltaBlock(delta) +
      '<div class="res-hero-level">Daraja: <b>' + App.escape(level) + "</b></div>" +
      (isRecord
        ? '<span class="res-record">' + icon("trophy", 12) + "Shaxsiy rekord</span>"
        : "") +
      "</div></div>" +
      '<div id="hero-interval-slot"></div>' +
      '<div id="hero-advice-slot"></div>' +
      '<button type="button" class="res-hero-cta" data-exam="' + latest.exam_id + '">' +
      icon("chart", 15) + "Batafsil tahlil" + icon("chevron", 15) +
      "</button></div>";

    const cta = box.querySelector("[data-exam]");
    if (cta) {
      cta.addEventListener("click", function () {
        openDetail(Number(cta.getAttribute("data-exam")));
      });
    }
    fillHeroDetail(latest.exam_id);
  }

  /** Hero uchun qo'shimcha aniqlik: 95% interval va daraja tavsiyasi. */
  function fillHeroDetail(examId) {
    const token = state.heroToken;
    API.get("/api/results/" + examId)
      .then(function (report) {
        if (token !== state.heroToken) {
          return;
        }
        const intervalSlot = byId("hero-interval-slot");
        if (intervalSlot && report && Array.isArray(report.scaled_interval)) {
          intervalSlot.innerHTML = intervalHtml(
            report.scaled_interval[0],
            report.scaled_interval[1],
            report.scaled_score
          );
        }
        const adviceSlot = byId("hero-advice-slot");
        if (adviceSlot && report && report.advice) {
          adviceSlot.innerHTML =
            '<div class="res-hero-advice">' + icon("sparkle", 16) +
            "<span>" + App.escape(report.advice) + "</span></div>";
        }
      })
      .catch(function () {
        /* qo'shimcha ma'lumot — olinmasa hero baribir to'liq ishlaydi */
      });
  }

  /** Faqat kutilayotgan natija bo'lsa — hero o'rnida countdown kartasi. */
  function pendingHeroHtml(pending) {
    const sorted = pending.slice().sort(function (a, b) {
      return pendingTime(a) - pendingTime(b);
    });
    const item = sorted[0];
    const until = parseDbTime(item.result_time);
    return (
      '<div class="res-hero res-hero-pending res-tone-b">' +
      '<div class="res-hero-top"><div>' +
      '<div class="res-hero-eyebrow">Natija kutilmoqda</div>' +
      '<div class="res-hero-title">' + App.escape(item.title) + "</div>" +
      '<div class="res-hero-meta">E\'lon vaqti: ' +
      App.escape(item.result_time_local || "—") + "</div></div>" +
      '<span class="res-chip">' + icon("clock", 12) + "Kutilmoqda</span></div>" +
      '<div class="res-pending-hero">' +
      '<span class="res-pending-hero-label">E\'lon qilinishiga</span>' +
      '<span class="res-countdown" data-countdown="' +
      App.escape(until ? item.result_time : "") + '">—</span>' +
      '<span class="res-pending-hero-time">Javoblaringiz saqlandi — ' +
      "natija avtomatik hisoblanadi.</span></div></div>"
    );
  }

  /** Hali birorta imtihon topshirilmagan bo'lsa — illyustratsiya + CTA. */
  function emptyHeroHtml() {
    return (
      '<div class="res-empty">' +
      '<svg class="res-empty-art" viewBox="0 0 96 96" fill="none" aria-hidden="true">' +
      '<rect x="6" y="12" width="84" height="72" rx="16" fill="currentColor" opacity="0.1"/>' +
      '<path d="M20 66V54M33 66V42M46 66V58M59 66V36M72 66V28" ' +
      'stroke="currentColor" stroke-width="6" stroke-linecap="round" opacity="0.5"/>' +
      '<path d="M18 44l14-10 13 10 15-16 12 6" stroke="currentColor" ' +
      'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<circle cx="72" cy="28" r="4" fill="currentColor"/>' +
      "</svg>" +
      "<h2>Hali natijalar yo'q</h2>" +
      '<p class="muted">Birinchi imtihonni topshiring — ball, sertifikat darajasi ' +
      "va o'sish dinamikasi shu yerda paydo bo'ladi.</p>" +
      '<button type="button" class="res-empty-cta" id="res-go-queue">' +
      "Navbatga o'tish</button>" +
      "</div>"
    );
  }

  /** To'rt ko'rsatkich plitkasi (eng yaxshi, o'rtacha, urinishlar, to'g'ri). */
  function renderStats(data) {
    const box = byId("results-stats");
    if (!box) {
      return;
    }
    const summary = data.summary || {};
    const published = data.published || [];
    let raw = 0;
    let total = 0;
    published.forEach(function (item) {
      raw += Number(item.raw_score) || 0;
      total += Number(item.total_questions) || 0;
    });
    const correct = total > 0 ? raw + "<small>/" + total + "</small>" : "—";

    box.innerHTML =
      statTile(
        "res-tone-b",
        "trophy",
        summary.best_scaled === null || summary.best_scaled === undefined
          ? "—"
          : formatScore(summary.best_scaled),
        "Eng yaxshi ball"
      ) +
      statTile(
        "res-tone-c-plus",
        "trend",
        summary.average_scaled === null || summary.average_scaled === undefined
          ? "—"
          : formatScore(summary.average_scaled),
        "O'rtacha ball"
      ) +
      statTile("res-tone-b-plus", "list", String(summary.attempts || 0), "Urinishlar") +
      statTile("res-tone-a", "target", correct, "To'g'ri javoblar");
  }

  function statTile(tone, iconName, value, label) {
    return (
      '<div class="res-stat ' + tone + '">' +
      '<div class="res-stat-top"><span class="res-stat-icon">' +
      icon(iconName, 16) + "</span></div>" +
      '<div class="res-stat-value">' + value + "</div>" +
      '<div class="res-stat-label">' + label + "</div></div>"
    );
  }

  /** Grafik ustidagi daraja chegaralari (joriy daraja — rangli chip). */
  function renderScaleLegend() {
    const box = byId("chart-zones");
    if (!box) {
      return;
    }
    const metric = state.metric === "theta" ? "theta" : "scaled";
    box.classList.toggle("hidden", metric !== "scaled");
    if (metric !== "scaled") {
      return;
    }

    let current = "";
    const published = (state.data && state.data.published) || [];
    if (published.length) {
      const latest = published
        .slice()
        .sort(function (a, b) {
          return timeOf(a) - timeOf(b);
        })
        .pop();
      current = latest.level || levelCode(latest.scaled_score);
    }

    box.innerHTML = LEVELS.map(function (level) {
      const isCurrent = level.code === current;
      const threshold = level.code === "NC" ? "&lt;46" : "≥" + level.min;
      return (
        '<span class="res-zone ' + level.tone +
        (isCurrent ? " is-current" : "") + '">' +
        '<i class="res-zone-dot"></i>' + App.escape(level.code) +
        " <b>" + threshold + "</b></span>"
      );
    }).join("");
  }

  /** Bitta e'lon qilingan imtihon kartasi (timeline elementi). */
  function itemHtml(item, previousScore, isBest) {
    const tone = toneOf(item);
    const score = Number(item.scaled_score);
    const level = item.level || levelCode(score);
    const total = Number(item.total_questions) || 0;
    const raw = Number(item.raw_score) || 0;
    const ratio = total ? Math.max(0, Math.min(100, (raw / total) * 100)) : 0;
    const submitted = parseDbTime(item.submitted_at);
    const theta = Number(item.theta);
    const delta =
      previousScore === null || previousScore === undefined
        ? null
        : score - Number(previousScore);
    const metaParts = [formatDate(submitted), raw + "/" + total + " to'g'ri"];
    if (
      item.theta !== null &&
      item.theta !== undefined &&
      Number.isFinite(theta)
    ) {
      metaParts.push("θ " + signed(theta, 2));
    }

    return (
      '<button type="button" class="res-item ' + tone + '" data-exam="' +
      item.exam_id + '" aria-label="' + App.escape(item.title) + ", " +
      formatScore(score) + ' ball — batafsil tahlil">' +
      '<span class="res-item-dot" aria-hidden="true"></span>' +
      '<span class="res-item-top">' +
      '<span class="res-item-title">' + App.escape(item.title) + "</span>" +
      '<span class="res-item-score">' + formatScore(score) +
      "<small>ball</small></span></span>" +
      '<span class="res-item-meta">' + App.escape(metaParts.join(" · ")) + "</span>" +
      '<span class="res-item-foot">' +
      '<span class="res-mini" aria-hidden="true"><span style="width:' +
      ratio.toFixed(1) + '%"></span></span>' +
      '<span class="res-chip">' + App.escape(level) + "</span>" +
      (isBest
        ? '<span class="res-record">' + icon("trophy", 12) + "Rekord</span>"
        : "") +
      deltaBadge(delta) +
      '<span class="res-chevron" aria-hidden="true">' + icon("chevron", 16) +
      "</span></span></button>"
    );
  }

  /** Oldingi natijaga nisbatan o'zgarish (kichik chip). */
  function deltaBadge(delta) {
    if (delta === null || delta === undefined || !Number.isFinite(Number(delta))) {
      return "";
    }
    const value = Number(delta);
    const cls = Math.abs(value) < 0.05 ? "flat" : value > 0 ? "up" : "down";
    const arrow =
      cls === "flat" ? "" : icon(cls === "up" ? "arrowUp" : "arrowDown", 11);
    const text =
      (value > 0 ? "+" : value < 0 ? "-" : "") + formatScore(Math.abs(value));
    return '<span class="res-item-delta ' + cls + '">' + arrow + text + "</span>";
  }

  /** Kutilayotgan natija kartasi (jonli countdown bilan). */
  function pendingItemHtml(item) {
    const submitted = parseDbTime(item.submitted_at);
    const until = parseDbTime(item.result_time);
    return (
      '<div class="res-item pending res-tone-b">' +
      '<span class="res-item-dot" aria-hidden="true"></span>' +
      '<span class="res-item-top">' +
      '<span class="res-item-title">' + App.escape(item.title) + "</span>" +
      '<span class="res-pending-badge">' + icon("clock", 12) +
      "Kutilmoqda</span></span>" +
      '<span class="res-item-meta">Yuborilgan: ' + formatDate(submitted) +
      " · e'lon vaqti: " + App.escape(item.result_time_local || "—") + "</span>" +
      '<span class="res-pending-line"><span>E\'lon qilinishiga</span>' +
      '<span class="res-countdown" data-countdown="' +
      App.escape(until ? item.result_time : "") + '">—</span></span></div>'
    );
  }

  /** Natija vaqtigacha bo'lgan jonli countdown (har soniyada yangilanadi). */
  function startCountdowns() {
    if (state.timer) {
      window.clearInterval(state.timer);
      state.timer = null;
    }
    const nodes = document.querySelectorAll("#tab-results [data-countdown]");
    if (!nodes.length) {
      return;
    }

    const tick = function () {
      const list = document.querySelectorAll("#tab-results [data-countdown]");
      for (let index = 0; index < list.length; index += 1) {
        const node = list[index];
        const until = parseDbTime(node.getAttribute("data-countdown"));
        if (!until) {
          node.textContent = "—";
          continue;
        }
        const left = until.getTime() - Date.now();
        if (left <= 0) {
          node.textContent = "Natija tayyorlanmoqda…";
          node.classList.add("is-ready");
        } else {
          node.textContent = formatRemaining(left);
          node.classList.remove("is-ready");
        }
      }
    };

    tick();
    state.timer = window.setInterval(tick, 1000);
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
              // Qismli savol (`36a`/`36b`) belgisi — server `label` bersa shu
              // ko'rsatiladi; legacy yozuvlarda `label` yo'q, pozitsiya chiqadi.
              (item.label || item.number) +
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
            formatScore(report.scaled_interval[0]) +
            " – " +
            formatScore(report.scaled_interval[1]) +
            " ball</b></div>"
          : "";

        const subjects = Array.isArray(report.subjects) ? report.subjects : [];
        const subjectRows = subjects
          .map(function (row) {
            return (
              '<div class="profile-row"><span class="label">' +
              App.escape(row.label) +
              "</span><b>" +
              row.correct +
              " / " +
              row.total +
              "</b></div>"
            );
          })
          .join("");

        root.innerHTML =
          '<div class="modal-backdrop"><div class="modal">' +
          '<div class="modal-head"><h2>' +
          App.escape(report.title) +
          '</h2><button class="close" type="button">×</button></div>' +
          '<div class="profile-row"><span class="label">Natija</span><b>' +
          formatScore(report.scaled_score) +
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
          subjectRows +
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

  /** Filtr va metrika tugmalari (bir marta bog'lanadi). */
  function bindControls() {
    document.querySelectorAll("#results-filters [data-filter]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (button.disabled) {
          return;
        }
        state.filter = button.getAttribute("data-filter");
        API.haptic("light");
        if (state.data) {
          renderList(state.data);
        }
      });
    });

    document.querySelectorAll("#chart-metrics [data-metric]").forEach(function (button) {
      button.addEventListener("click", function () {
        const metric = button.getAttribute("data-metric");
        if (metric === state.metric) {
          return;
        }
        state.metric = metric === "theta" ? "theta" : "scaled";
        document
          .querySelectorAll("#chart-metrics [data-metric]")
          .forEach(function (other) {
            const isActive = other === button;
            other.classList.toggle("active", isActive);
            other.setAttribute("aria-selected", isActive ? "true" : "false");
          });
        const subtitle = byId("chart-sub");
        if (subtitle) {
          subtitle.textContent =
            state.metric === "theta"
              ? "Bilim darajasi θ, logit shkalasi"
              : "0–100 ball shkalasi";
        }
        API.haptic("light");
        if (state.data) {
          renderChart(state.data.chart || {});
        }
      });
    });
  }

  window.addEventListener("DOMContentLoaded", function () {
    bindControls();
    App.onShow("results", loadResults);
  });
})();
