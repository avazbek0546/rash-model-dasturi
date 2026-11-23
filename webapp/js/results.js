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
   * Sertifikat bali (0–100) ko'rinishi: yuzdan birlar xonasigacha yaxlitlanadi,
   * ortiqcha nol ko'rsatilmaydi (67.1 · 50.96 · 50).
   *
   * Foydalanuvchi uchun asosiy o'lchov — sertifikat bali. θ (logit) faqat
   * ichki/texnik ko'rsatkich sifatida qoladi va bu bo'limda ko'rsatilmaydi.
   */
  function formatScore(value) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "—";
    }
    return String(Math.round(number * 100) / 100);
  }

  /** Imtihon yozuvidan sertifikat balini oladi (bo'lmasa — null). */
  function scoreOf(item) {
    if (
      !item ||
      item.scaled_score === null ||
      item.scaled_score === undefined ||
      item.scaled_score === ""
    ) {
      return null;
    }
    const value = Number(item.scaled_score);
    return Number.isFinite(value) ? value : null;
  }
  /** Fan ballari xaritasidan xavfsiz qiymat oladi (0–100 yoki null). */
  function ballOf(map, code) {
    if (!map || code === null || code === undefined) {
      return null;
    }
    const value = Number(map[code]);
    if (!Number.isFinite(value)) {
      return null;
    }
    return Math.max(0, Math.min(100, value));
  }



  // ---------------------------------------------------------------------------
  // Holat (state) va daraja (sertifikat) yordamchilari
  // ---------------------------------------------------------------------------
  const state = {
    data: null,
    filter: "all",
    heroToken: 0,
    timer: null,
    chartRange: "all",
    chartData: null,
  };

  /**
   * Sertifikat darajalari — **0–100 sertifikat bali** chegaralari bo'yicha
   * zaxira jadval (server `level` maydonini bersa, o'sha ishlatiladi).
   * Chegaralar `services/rasch.py::CERTIFICATE_LEVELS` bilan bir xil:
   * <46 → NC, 46 → C, 50 → C+, 55 → B, 60 → B+, 65 → A, 70 → A+.
   */
  const LEVELS = [
    { code: "NC", min: -Infinity, tone: "res-tone-nc" },
    { code: "C", min: 46, tone: "res-tone-c" },
    { code: "C+", min: 50, tone: "res-tone-c-plus" },
    { code: "B", min: 55, tone: "res-tone-b" },
    { code: "B+", min: 60, tone: "res-tone-b-plus" },
    { code: "A", min: 65, tone: "res-tone-a" },
    { code: "A+", min: 70, tone: "res-tone-a-plus" },
  ];

  /** Grafik nuqtalari uchun HEX ranglar (CSS `--tone` bilan bir xil). */
  const LEVEL_HEX = {
    NC: "#5f6a7a",
    C: "#c93a63",
    "C+": "#6242e8",
    B: "#9a6100",
    "B+": "#1b74ad",
    A: "#0f7f4a",
    "A+": "#0a7052",
  };

  /**
   * Chart.js plagini: sertifikat darajalari chegaralarini (46/50/55/60/65/70)
   * nuqtali chiziq va kichik yorliq bilan chizadi. Hech qanday qo'shimcha
   * kutubxonasiz — faqat canvas.
   */
  const levelBandsPlugin = {
    id: "resLevelBands",
    beforeDatasetsDraw: function (chartInstance) {
      const ctx = chartInstance.ctx;
      const area = chartInstance.chartArea;
      const yScale = chartInstance.scales ? chartInstance.scales.y : null;
      if (!ctx || !area || !yScale) {
        return;
      }
      ctx.save();
      ctx.font = "600 9px system-ui, -apple-system, Segoe UI, Roboto, sans-serif";
      ctx.textBaseline = "middle";
      LEVELS.slice(1).forEach(function (level) {
        const py = yScale.getPixelForValue(level.min);
        if (py < area.top || py > area.bottom) {
          return;
        }
        ctx.beginPath();
        ctx.setLineDash([3, 4]);
        ctx.strokeStyle = "rgba(128,128,128,0.35)";
        ctx.lineWidth = 1;
        ctx.moveTo(area.left, py);
        ctx.lineTo(area.right, py);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "rgba(128,128,128,0.7)";
        ctx.fillText(level.code, area.left + 4, py - 5);
      });
      ctx.restore();
    },
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
    const code = (item && item.level) || levelCode(scoreOf(item));
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

  /**
   * Sertifikat bali o'qi — 0..100.
   *
   * Belgilangan oraliq diagrammani imtihonlar orasida taqqoslashni oson
   * qiladi: 46 dan past — NC, 70 dan yuqori — A+ (sertifikat chegaralari).
   */
  function scoreAxis() {
    return { min: 0, max: 100 };
  }

  /**
   * Joriy daraja va keyingi daraja orasidagi masofa.
   * `progress` — joriy daraja oralig'idagi foiz (0–100), `remaining` — keyingi
   * darajagacha qolgan ball (A+ da 0).
   */
  function nextLevelInfo(score) {
    const value = Number(score);
    const safe = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
    let index = 0;
    LEVELS.forEach(function (level, position) {
      if (safe >= level.min) {
        index = position;
      }
    });
    const current = LEVELS[index];
    const next = index < LEVELS.length - 1 ? LEVELS[index + 1] : null;
    const start = current.min === -Infinity ? 0 : current.min;
    const end = next ? next.min : 100;
    const progress = next
      ? Math.max(0, Math.min(100, ((safe - start) / (end - start)) * 100))
      : 100;
    return {
      current: current,
      next: next,
      progress: progress,
      remaining: next ? Math.max(0, next.min - safe) : 0,
    };
  }

  /** 7 qadamli daraja zinapoyasi (NC … A+), joriy qadam ajratilgan. */
  function levelPath(info) {
    const currentIndex = LEVELS.indexOf(info.current);
    return (
      '<div class="res-ladder" aria-hidden="true">' +
      LEVELS.map(function (level, index) {
        const stateClass =
          index === currentIndex
            ? " is-current"
            : index < currentIndex
            ? " is-passed"
            : "";
        return '<span class="res-ladder-step' + stateClass + '">' + level.code + "</span>";
      }).join("") +
      "</div>"
    );
  }

  /**
   * "Keyingi daraja" bloki: joriy daraja ichidagi progress, qolgan ball va
   * zinapoya. `info` — `nextLevelInfo()` natijasi. Eng yuqori darajada
   * (A+) progress 100% va "qoldi" qatori o'rniga tabrik matni chiqadi.
   */
  function nextLevelBlock(info) {
    if (!info) {
      return "";
    }
    const current = info.current;
    const next = info.next;
    const percent = Math.max(0, Math.min(100, Number(info.progress) || 0));
    const head = next
      ? "Keyingi daraja: <b>" +
        next.code +
        "</b> · " +
        formatScore(info.remaining) +
        " ball qoldi"
      : "Eng yuqori daraja — <b>" + current.code + "</b>";
    return (
      '<div class="res-goal">' +
      '<div class="res-goal-head"><span>' +
      head +
      "</span><span>" +
      Math.round(percent) +
      "%</span></div>" +
      '<div class="res-goal-track"><span style="width:' +
      percent.toFixed(1) +
      '%"></span></div>' +
      levelPath(info) +
      "</div>"
    );
  }

  /**
   * Hero'dagi kichik trend chizig'i (sparkline) — oxirgi 8 natija.
   * 2 tadan kam natija bo'lsa bo'sh satr qaytadi (joy egallamaydi).
   */
  function sparklineHtml(scores) {
    const values = (scores || [])
      .map(function (value) {
        return Number(value);
      })
      .filter(function (value) {
        return Number.isFinite(value);
      })
      .slice(-8);
    if (values.length < 2) {
      return "";
    }
    const width = 120;
    const height = 26;
    const pad = 3;
    const min = Math.min.apply(null, values);
    const max = Math.max.apply(null, values);
    const span = max - min || 1;
    const step = (width - pad * 2) / (values.length - 1);
    const points = values.map(function (value, index) {
      const x = pad + step * index;
      const y = height - pad - ((value - min) / span) * (height - pad * 2);
      return x.toFixed(1) + "," + y.toFixed(1);
    });
    return (
      '<svg class="res-spark" viewBox="0 0 ' + width + " " + height + '" ' +
      'preserveAspectRatio="none" aria-hidden="true">' +
      '<polyline class="res-spark-line" points="' + points.join(" ") + '"/>' +
      "</svg>"
    );
  }


  /**
   * SVG halqa (dial) — 0–100 sertifikat bali. Progress `stroke-dashoffset`
   * orqali chiziladi; `animateHeroDial()` uni jonlantiradi.
   */
  function scoreDial(score) {
    const value = Number(score);
    const safe = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
    const radius = 50;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference * (1 - safe / 100);
    const ticks = [46, 50, 55, 60, 65, 70]
      .map(function (threshold) {
        return (
          '<line class="res-dial-tick" x1="60" y1="7" x2="60" y2="13" ' +
          'transform="rotate(' + (threshold * 3.6).toFixed(1) + ' 60 60)"/>'
        );
      })
      .join("");
    return (
      '<div class="res-dial" role="img" aria-label="Sertifikat bali ' +
      formatScore(safe) + " / 100, daraja " + App.escape(levelCode(safe)) + '">' +
      '<svg viewBox="0 0 120 120" aria-hidden="true">' +
      '<circle class="res-dial-track" cx="60" cy="60" r="' + radius + '"/>' +
      '<circle class="res-dial-progress" cx="60" cy="60" r="' + radius + '" ' +
      'stroke-dasharray="' + circumference.toFixed(2) + '" ' +
      'stroke-dashoffset="' + circumference.toFixed(2) + '" ' +
      'transform="rotate(-90 60 60)" ' +
      'data-dial-target="' + offset.toFixed(2) + '"/>' +
      ticks +
      "</svg>" +
      '<div class="res-dial-center">' +
      '<span class="res-dial-score" data-count-to="' + safe.toFixed(2) + '">0</span>' +
      '<span class="res-dial-unit">/ 100 ball</span>' +
      "</div></div>"
    );
  }

  /** Dial animatsiyasi: halqa to'lishi + ball count-up (reduced-motion hurmat). */
  function animateHeroDial() {
    const dial = document.querySelector("#tab-results .res-dial-progress");
    const counter = document.querySelector("#tab-results .res-dial-score");
    const reduced = window.matchMedia
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false;
    const targetScore = counter ? Number(counter.getAttribute("data-count-to")) : NaN;
    if (counter && Number.isFinite(targetScore)) {
      counter.textContent = reduced ? formatScore(targetScore) : "0";
    }
    if (!dial) {
      return;
    }
    const target = Number(dial.getAttribute("data-dial-target"));
    if (!Number.isFinite(target)) {
      return;
    }
    if (reduced) {
      dial.style.strokeDashoffset = target.toFixed(2);
      return;
    }
    window.requestAnimationFrame(function () {
      dial.style.strokeDashoffset = target.toFixed(2);
    });
    if (!counter || !Number.isFinite(targetScore)) {
      return;
    }
    const duration = 800;
    const start = performance.now();
    const step = function (now) {
      const ratio = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - ratio, 3);
      counter.textContent = String(Math.round(targetScore * eased * 100) / 100);
      if (ratio < 1) {
        window.requestAnimationFrame(step);
      } else {
        counter.textContent = formatScore(targetScore);
      }
    };
    window.requestAnimationFrame(step);
  }

  /** O'rtacha o'zgarish (har imtihon uchun) — "O'sish sur'ati". */
  function trendOf(scores) {
    const list = scores.filter(function (value) {
      return Number.isFinite(Number(value));
    });
    if (list.length < 2) {
      return { value: null, direction: "flat" };
    }
    let sum = 0;
    for (let index = 1; index < list.length; index += 1) {
      sum += Number(list[index]) - Number(list[index - 1]);
    }
    const average = sum / (list.length - 1);
    return {
      value: average,
      direction: average > 0.05 ? "up" : average < -0.05 ? "down" : "flat",
    };
  }

  /** Standart og'ish — natijalar barqarorligi (2 tadan kam bo'lsa null). */
  function deviation(scores) {
    const list = scores
      .map(function (value) {
        return Number(value);
      })
      .filter(function (value) {
        return Number.isFinite(value);
      });
    if (list.length < 2) {
      return null;
    }
    const mean =
      list.reduce(function (sum, value) {
        return sum + value;
      }, 0) / list.length;
    const variance =
      list.reduce(function (sum, value) {
        return sum + Math.pow(value - mean, 2);
      }, 0) / list.length;
    return Math.sqrt(variance);
  }

  /** HEX rangni shaffof rgba ga aylantiradi (gradient/to'ldirish uchun). */
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

  function renderChart(chartData) {
    const canvas = byId("results-chart");
    const fallback = byId("chart-fallback");
    const wrap = canvas ? canvas.parentElement : null;
    const sub = byId("chart-sub");
    const rangeBox = byId("chart-range");

    // Kelgan ma'lumotni saqlaymiz — oraliq tugmasi qayta so'rovsiz ishlaydi.
    state.chartData = chartData || { labels: [], score: [] };
    const fullLabels = state.chartData.labels || [];
    const fullScore = state.chartData.score || [];

    // Oraliq tanlagichi faqat 3+ natija bo'lsa mantiqiy.
    if (rangeBox) {
      rangeBox.classList.toggle("hidden", fullLabels.length < 3);
      rangeBox.querySelectorAll("[data-range]").forEach(function (button) {
        const key = button.getAttribute("data-range");
        const isActive = key === state.chartRange;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    const limit = state.chartRange === "5" ? 5 : fullLabels.length;
    const start = Math.max(0, fullLabels.length - limit);
    const labels = fullLabels.slice(start);
    const score = fullScore.slice(start);

    if (sub) {
      sub.textContent = labels.length
        ? "0–100 shkala · " +
          labels.length +
          " ta natija" +
          (state.chartRange === "5" ? " (oxirgi 5)" : "")
        : "0–100 shkala";
    }

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
              formatScore(score[index]) +
              " ball · " +
              levelCode(score[index]) +
              "</div></div>"
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

    // Sertifikat bali o'qi — 0..100 (sertifikat chegaralari ko'rinadi).
    const axis = scoreAxis();

    const theme = API.theme();
    const textColor = theme.text_color || "#10151c";
    const buttonColor = theme.button_color || "#2f7ce0";

    const pointRadii = labels.map(function (label, index) {
      return index === labels.length - 1 ? 6 : 4;
    });
    // Har bir nuqta o'z darajasi rangida — dinamika "daraja zinapoyasi"da
    // qanday siljiganini bir qarashda ko'rsatadi.
    const pointColors = score.map(function (value) {
      return LEVEL_HEX[levelCode(value)] || buttonColor;
    });

    if (chart) {
      chart.destroy();
      chart = null;
    }

    chart = new Chart(canvas.getContext("2d"), {
      type: "line",
      // Sertifikat darajalari chegaralari (46/50/55/60/65/70) chiziladi.
      plugins: [levelBandsPlugin],
      data: {
        labels: labels,
        datasets: [
          {
            label: "Sertifikat bali (0–100)",
            data: score,
            borderColor: buttonColor,
            backgroundColor: withAlpha(buttonColor, 0.12),
            borderWidth: 3,
            tension: 0.4,
            fill: true,
            spanGaps: true,
            pointRadius: pointRadii,
            pointHoverRadius: 7,
            pointBackgroundColor: pointColors,
            pointBorderColor: "#ffffff",
            pointBorderWidth: 2.5,
            pointHoverBorderColor: "#ffffff",
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
                return (
                  "Sertifikat bali: " + formatScore(value) +
                  " · daraja " + levelCode(value)
                );
              },
            },
          },
        },
        scales: {
          y: {
            min: axis.min,
            max: axis.max,
            ticks: {
              color: textColor,
              stepSize: 20,
              callback: function (value) {
                return String(Math.round(value));
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

  /**
   * Timeline oy sarlavhasi: "Sentabr 2026". Sana bo'lmasa bo'sh satr
   * qaytadi — bunda sarlavha qo'shilmaydi (timeline buzilmaydi).
   */
  function monthLabel(item) {
    const date = parseDbTime(item && item.submitted_at);
    if (!date) {
      return "";
    }
    const name = MONTHS[date.getMonth()] || "";
    return name.charAt(0).toUpperCase() + name.slice(1) + " " + date.getFullYear();
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
      previousByExam[asc[index].exam_id] = scoreOf(asc[index - 1]);
    }
    let bestScore = -Infinity;
    asc.forEach(function (item) {
      const score = scoreOf(item);
      if (score !== null && score > bestScore) {
        bestScore = score;
      }
    });

    const rows = [];
    let lastMonth = "";
    const pushRow = function (html, item) {
      const label = monthLabel(item);
      if (label && label !== lastMonth) {
        lastMonth = label;
        rows.push('<div class="res-month">' + label + "</div>");
      }
      rows.push(html);
    };

    if (state.filter !== "published") {
      pending
        .slice()
        .sort(function (a, b) {
          return pendingTime(a) - pendingTime(b);
        })
        .forEach(function (item) {
          pushRow(pendingItemHtml(item), item);
        });
    }
    if (state.filter !== "pending") {
      lastMonth = "";
      asc
        .slice()
        .reverse()
        .forEach(function (item) {
          const score = scoreOf(item);
          const isBest =
            asc.length > 1 && score !== null && Math.abs(score - bestScore) < 1e-9;
          pushRow(itemHtml(item, previousByExam[item.exam_id], isBest), item);
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
      renderInsights(data);
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
    byId("results-insights").classList.add("hidden");
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
    byId("results-insights").classList.add("hidden");
    byId("results-list-head").classList.add("hidden");
    byId("results-filters").classList.add("hidden");
    byId("results-list").classList.add("hidden");
  }

  /** Hero'dagi o'sish/kamayish chipi (oldingi imtihonga nisbatan, ball). */
  function deltaBlock(delta) {
    if (delta === null || delta === undefined || !Number.isFinite(Number(delta))) {
      return '<div class="res-delta flat">— <span>ball</span></div>';
    }
    const value = Number(delta);
    if (Math.abs(value) < 0.05) {
      return '<div class="res-delta flat">+0.0 <span>ball</span></div>';
    }
    const up = value > 0;
    return (
      '<div class="res-delta ' + (up ? "up" : "down") + '">' +
      icon(up ? "arrowUp" : "arrowDown", 14) +
      signed(value, 1) +
      ' <span>ball</span></div>'
    );
  }

  /** Hero'dagi izoh qatori — o'sish izohi (chip yonida). */
  function deltaCaption(delta) {
    if (delta === null || delta === undefined || !Number.isFinite(Number(delta))) {
      return "Taqqoslash uchun oldingi natija yo'q";
    }

    if (Math.abs(Number(delta)) < 0.05) {
      return "Oldingi natija bilan bir xil";
    }
    return "Oldingi imtihonga nisbatan";
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
    // Asosiy o'lchov — sertifikat bali (0–100). θ foydalanuvchiga ko'rsatilmaydi.
    const score = scoreOf(latest);
    const previousScore = previous ? scoreOf(previous) : null;
    const delta =
      score !== null && previousScore !== null ? score - previousScore : null;
    const level = latest.level || levelCode(score);
    const tone = toneOf(latest);
    const submitted = parseDbTime(latest.submitted_at);
    // Qismli formada savollar soni `total_items` da (masalan 55); `total_questions`
    // — pozitsiyalar soni (zaxira, eski javoblar uchun).
    const total = Number(latest.total_items || latest.total_questions) || 0;
    const raw = Number(latest.raw_score) || 0;
    const scores = asc
      .map(function (item) {
        return scoreOf(item);
      })
      .filter(function (value) {
        return value !== null;
      });
    const best = scores.length ? Math.max.apply(null, scores) : null;
    const isRecord =
      asc.length > 1 && score !== null && best !== null && Math.abs(score - best) < 1e-9;

    const info = nextLevelInfo(score);
    const correctShare = total > 0 ? Math.round((raw / total) * 100) : null;

    box.innerHTML =
      '<div class="res-hero res-hero2 ' + tone + '">' +
      '<div class="res-hero2-top">' +
      '<div class="res-hero-eyebrow">Sertifikat pasporti</div>' +
      '<div class="res-hero2-date">' + formatDate(submitted) + "</div>" +
      "</div>" +
      '<div class="res-hero-title">' + App.escape(latest.title) + "</div>" +
      '<div class="res-hero2-main">' +
      scoreDial(score) +
      '<div class="res-hero-side">' +
      '<div class="res-hero2-badges">' +
      '<span class="res-chip res-chip-lg">' + App.escape(level) + "</span>" +
      deltaBlock(delta) +
      (isRecord
        ? '<span class="res-record">' + icon("trophy", 12) + "Shaxsiy rekord</span>"
        : "") +
      "</div>" +
      '<div class="res-hero-level">' + raw + "/" + total + " to'g'ri javob" +
      (correctShare === null ? "" : " · " + correctShare + "%") +
      "</div>" +
      sparklineHtml(scores) +
      "</div></div>" +
      nextLevelBlock(info) +
      '<div id="hero-subjects-slot"></div>' +
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
    animateHeroDial();
    fillHeroDetail(latest.exam_id);
  }

  /** Hero uchun qo'shimcha: fanlar kesimi va daraja tavsiyasi. */
  function fillHeroDetail(examId) {
    const token = state.heroToken;
    API.get("/api/results/" + examId)
      .then(function (report) {
        if (token !== state.heroToken) {
          return;
        }
        const subjectsSlot = byId("hero-subjects-slot");
        const subjects = report && Array.isArray(report.subjects) ? report.subjects : [];
        const balls = (report && report.subject_balls) || {};
        if (subjectsSlot && subjects.length) {
          const rows = subjects
            .map(function (row) {
              const ball = ballOf(balls, row.code);
              if (ball === null) {
                return "";
              }
              const percent = Math.max(0, Math.min(100, ball));
              return (
                '<div class="res-subject">' +
                '<div class="res-subject-head"><span>' + App.escape(row.label) +
                "</span><b>" + formatScore(ball) + " ball</b></div>" +
                '<span class="res-subject-track"><span style="width:' +
                percent.toFixed(1) + '%"></span></span></div>'
              );
            })
            .filter(Boolean)
            .join("");
          if (rows) {
            subjectsSlot.innerHTML =
              '<div class="res-hero-subjects">' + rows + "</div>";
          }
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
      '<p class="muted">Birinchi imtihonni topshiring — sertifikat bali, ' +
      "daraja va o'sish dinamikasi shu yerda paydo bo'ladi.</p>" +
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
    const scores = [];
    published.forEach(function (item) {
      raw += Number(item.raw_score) || 0;
      total += Number(item.total_items || item.total_questions) || 0;
      const score = scoreOf(item);
      if (score !== null) {
        scores.push(score);
      }
    });
    const correct = total > 0 ? raw + "<small>/" + total + "</small>" : "—";
    const bestScore =
      summary.best_score === null || summary.best_score === undefined
        ? scores.length
          ? Math.max.apply(null, scores)
          : null
        : Number(summary.best_score);
    const averageScore =
      summary.average_score === null || summary.average_score === undefined
        ? scores.length
          ? scores.reduce(function (sum, value) {
              return sum + value;
            }, 0) / scores.length
          : null
        : Number(summary.average_score);

    const attempts = Number(summary.attempts) || published.length;
    const publishedCount = published.length;
    const correctPercent = total > 0 ? (raw / total) * 100 : null;

    box.innerHTML =
      statTile(
        "res-tone-b",
        "trophy",
        bestScore === null ? "—" : formatScore(bestScore) + "<small>ball</small>",
        "Eng yaxshi ball",
        bestScore,
        bestScore === null ? "Hali natija yo'q" : "Daraja " + levelCode(bestScore)
      ) +
      statTile(
        "res-tone-c-plus",
        "trend",
        averageScore === null
          ? "—"
          : formatScore(averageScore) + "<small>ball</small>",
        "O'rtacha ball",
        averageScore,
        averageScore === null
          ? "Hisoblash uchun ma'lumot yo'q"
          : "Barcha urinishlar bo'yicha"
      ) +
      statTile(
        "res-tone-b-plus",
        "list",
        String(attempts),
        "Urinishlar",
        attempts ? (publishedCount / attempts) * 100 : 0,
        publishedCount + " ta e'lon qilingan"
      ) +
      statTile(
        "res-tone-a",
        "target",
        correct,
        "To'g'ri javoblar",
        correctPercent,
        correctPercent === null
          ? "Jami savollar noma'lum"
          : Math.round(correctPercent) + "% aniqlik"
      );
  }

  function statTile(tone, iconName, value, label, percent, sub) {
    const safe = Number.isFinite(Number(percent))
      ? Math.max(0, Math.min(100, Number(percent)))
      : 0;
    return (
      '<div class="res-stat ' + tone + '">' +
      '<div class="res-stat-top"><span class="res-stat-icon">' +
      icon(iconName, 16) + "</span>" +
      '<span class="res-stat-bar" aria-hidden="true"><span style="width:' +
      safe.toFixed(1) + '%"></span></span></div>' +
      '<div class="res-stat-value">' + value + "</div>" +
      '<div class="res-stat-label">' + label + "</div>" +
      (sub ? '<div class="res-stat-sub">' + sub + "</div>" : "") +
      "</div>"
    );
  }

  /**
   * «Tahlil» plitkalari: o'sish sur'ati, barqarorlik, eng yaxshi natija va
   * keyingi maqsad. Ma'lumot yetarli bo'lmasa blok butunlay yashiriladi.
   */
  function renderInsights(data) {
    const box = byId("results-insights");
    if (!box) {
      return;
    }
    const published = data.published || [];
    const asc = published.slice().sort(function (a, b) {
      return timeOf(a) - timeOf(b);
    });
    const scores = asc
      .map(function (item) {
        return scoreOf(item);
      })
      .filter(function (value) {
        return value !== null;
      });

    if (!scores.length) {
      box.classList.add("hidden");
      box.innerHTML = "";
      return;
    }

    const trend = trendOf(scores);
    const spread = deviation(scores);
    const best = Math.max.apply(null, scores);
    const info = nextLevelInfo(scores[scores.length - 1]);
    const cards = [];

    if (trend.value !== null) {
      cards.push(
        insightHtml(
          trend.direction === "up"
            ? "res-tone-a"
            : trend.direction === "down"
            ? "res-tone-c"
            : "res-tone-b-plus",
          "trend",
          "O'sish sur'ati",
          signed(trend.value, 1) + "<small> ball</small>",
          "har imtihon uchun o'rtacha"
        )
      );
    }

    if (spread !== null) {
      cards.push(
        insightHtml(
          "res-tone-b-plus",
          "target",
          "Barqarorlik",
          "±" + formatScore(spread) + "<small> ball</small>",
          spread <= 6 ? "natijalar barqaror" : "natijalar o'zgaruvchan"
        )
      );
    }

    cards.push(
      insightHtml(
        "res-tone-b",
        "trophy",
        "Eng yaxshi natija",
        formatScore(best) + "<small> ball</small>",
        "daraja " + levelCode(best)
      )
    );

    cards.push(
      insightHtml(
        "res-tone-c-plus",
        "sparkle",
        "Keyingi maqsad",
        info.next
          ? info.next.code + "<small> · " + formatScore(info.remaining) + " ball</small>"
          : "A+<small> · eng yuqori</small>",
        info.next
          ? "hozirgi daraja " + info.current.code
          : "barcha darajalar ochilgan"
      )
    );

    box.innerHTML = cards.join("");
    box.classList.remove("hidden");
  }

  /** Bitta tahlil kartasi (ikonka + yorliq + qiymat + izoh). */
  function insightHtml(tone, iconName, label, value, hint) {
    return (
      '<div class="res-insight ' + tone + '">' +
      '<div class="res-insight-top"><span class="res-insight-icon">' +
      icon(iconName, 14) + "</span>" +
      '<span class="res-insight-label">' + label + "</span></div>" +
      '<span class="res-insight-value">' + value + "</span>" +
      (hint ? '<span class="res-insight-hint">' + hint + "</span>" : "") +
      "</div>"
    );
  }


  /** Bitta e'lon qilingan imtihon kartasi (timeline elementi). */
  function itemHtml(item, previousScore, isBest) {
    const tone = toneOf(item);
    const score = scoreOf(item);
    const level = item.level || levelCode(score);
    const total = Number(item.total_items || item.total_questions) || 0;
    const raw = Number(item.raw_score) || 0;
    const ratio = score === null ? 0 : Math.max(0, Math.min(100, score));
    const submitted = parseDbTime(item.submitted_at);
    const delta =
      previousScore === null ||
      previousScore === undefined ||
      score === null
        ? null
        : score - Number(previousScore);
    const metaParts = [formatDate(submitted), raw + "/" + total + " to'g'ri"];

    return (
      '<button type="button" class="res-item ' + tone + '" data-exam="' +
      item.exam_id + '" aria-label="' + App.escape(item.title) + ", " +
      formatScore(score) + " ball, daraja " + App.escape(level) +
      ' — batafsil tahlil">' +
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

  /** Oldingi natijaga nisbatan sertifikat bali o'zgarishi (kichik chip). */
  function deltaBadge(delta) {
    if (delta === null || delta === undefined || !Number.isFinite(Number(delta))) {
      return "";
    }
    const value = Number(delta);
    const cls = Math.abs(value) < 0.05 ? "flat" : value > 0 ? "up" : "down";
    const arrow =
      cls === "flat" ? "" : icon(cls === "up" ? "arrowUp" : "arrowDown", 11);
    return (
      '<span class="res-item-delta ' + cls + '">' + arrow +
      signed(value, 1) + "</span>"
    );
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
      App.escape(until ? item.result_time : "") + '">—</span></span>' +
      '<span class="res-pending-track" aria-hidden="true">' +
      '<span class="res-pending-fill" data-progress-from="' +
      App.escape(item.submitted_at || "") + '" data-progress-to="' +
      App.escape(until ? item.result_time : "") + '"></span></span></div>'
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

      // Kutilayotgan natija kartalaridagi "vaqt progressi".
      const fills = document.querySelectorAll(
        "#tab-results [data-progress-from]"
      );
      for (let index = 0; index < fills.length; index += 1) {
        const fill = fills[index];
        const from = parseDbTime(fill.getAttribute("data-progress-from"));
        const to = parseDbTime(fill.getAttribute("data-progress-to"));
        if (!from || !to) {
          fill.style.width = "0%";
          continue;
        }
        const span = to.getTime() - from.getTime();
        const ratio = span > 0 ? (Date.now() - from.getTime()) / span : 1;
        const percent = Math.max(0, Math.min(100, ratio * 100));
        fill.style.width = percent.toFixed(1) + "%";
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

        const score = scoreOf(report);
        const subjects = Array.isArray(report.subjects) ? report.subjects : [];
        const subjectBalls = report.subject_balls || {};
        const subjectRows = subjects
          .map(function (row) {
            const ball = subjectBalls[row.code];
            return (
              '<div class="profile-row"><span class="label">' +
              App.escape(row.label) +
              "</span><b>" +
              (ball === null || ball === undefined
                ? "—"
                : formatScore(ball) + " ball") +
              "</b></div>"
            );
          })
          .join("");

        root.innerHTML =
          '<div class="modal-backdrop"><div class="modal">' +
          '<div class="modal-head"><h2>' +
          App.escape(report.title) +
          '</h2><button class="close" type="button">×</button></div>' +
          '<div class="profile-row"><span class="label">Sertifikat bali</span><b>' +
          formatScore(score) +
          " ball</b></div>" +
          '<div class="profile-row"><span class="label">To\'g\'ri javoblar</span><b>' +
          report.raw_score +
          " / " +
          (report.total_items || report.total_questions) +
          "</b></div>" +
          subjectRows +
          '<div class="profile-row"><span class="label">Sertifikat darajasi</span><b>' +
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

  /** Filtr va grafik oraliq tugmalari (bir marta bog'lanadi). */
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

    // Grafik oralig'i: "Barchasi" / "Oxirgi 5" — qayta so'rovsiz qayta chiziladi.
    document.querySelectorAll("#chart-range [data-range]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (button.disabled) {
          return;
        }
        const next = button.getAttribute("data-range");
        if (next === state.chartRange) {
          return;
        }
        state.chartRange = next;
        API.haptic("light");
        if (state.chartData) {
          renderChart(state.chartData);
        }
      });
    });
  }

  window.addEventListener("DOMContentLoaded", function () {
    bindControls();
    App.onShow("results", loadResults);
  });
})();
