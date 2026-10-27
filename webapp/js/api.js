/* ---------------------------------------------------------------------------
   API qatlami: Telegram initData, fetch, xatoliklarni ko'rsatish.
   Barcha so'rovlar `X-Init-Data` header'i bilan yuboriladi — server tomonida
   HMAC imzo tekshiriladi (services/webapp_auth.py).
--------------------------------------------------------------------------- */
(function () {
  "use strict";

  const tg =
    window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const params = new URLSearchParams(window.location.search);
  // Lokal sinov uchun: ?debug_user_id=123 (server WEBAPP_DEV_MODE=1 bo'lishi kerak)
  const debugUserId = params.get("debug_user_id");

  function buildHeaders() {
    const headers = { "Content-Type": "application/json" };
    if (tg && tg.initData) {
      headers["X-Init-Data"] = tg.initData;
    }
    if (debugUserId) {
      headers["X-Debug-User-Id"] = debugUserId;
    }
    return headers;
  }

  async function request(path, options) {
    const opts = options || {};
    let response;
    try {
      response = await fetch(path, {
        method: opts.method || "GET",
        headers: buildHeaders(),
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        // `keepalive` — sahifa yopilayotganda ham so'rov uzatilishini ta'minlaydi
        // (Telegram WebView `pagehide`/`visibilitychange` holatlari uchun).
        keepalive: opts.keepalive === true,
      });
    } catch (error) {
      // Server/tunnel ishlamayapti yoki internet yo'q: `fetch` faqat
      // "Failed to fetch" beradi. Foydalanuvchiga o'zbekcha, aniq xabar
      // ko'rsatamiz — ilgari bu holat butunlay jim qolardi.
      const failure = new Error(
        "Serverga ulanib bo'lmadi. Internet aloqasini tekshirib, qayta urinib ko'ring."
      );
      failure.status = 0;
      failure.network = true;
      throw failure;
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }

    if (!response.ok) {
      let message = payload && payload.error ? String(payload.error) : "";
      if (!message) {
        // Teskari proksi/tunnel xatolari (502/503/504) — tushunarli izoh.
        message =
          response.status >= 500
            ? "Server vaqtincha ishlamayapti (HTTP " +
              response.status +
              "). Birozdan keyin qayta urinib ko'ring."
            : "Server xatosi (" + response.status + ")";
      }
      const failure = new Error(message);
      failure.status = response.status;
      throw failure;
    }
    return payload;
  }

  window.API = {
    tg: tg,
    /** Ilova haqiqiy Telegram ichida ochilganmi? */
    isTelegram: Boolean(tg && tg.initData),
    get: function (path) {
      return request(path);
    },
    /**
     * POST so'rovi. `options.keepalive = true` bo'lsa — sahifa yopilishida ham
     * so'rov uzatiladi (Telegram WebView `pagehide` holati uchun).
     */
    post: function (path, body, options) {
      const opts = options || {};
      return request(path, {
        method: "POST",
        body: body,
        keepalive: opts.keepalive === true,
      });
    },
    /**
     * Haptic javob — faqat Telegram ichida ishlaydi.
     *
     * `style`:
     *   * `"error"` / `"success"` / `"warning"` → `notificationOccurred`
     *     (xato yoki natija haqidagi xabarnoma tebranishi);
     *   * qolganlari (`light`, `medium`, `heavy`, `rigid`, `soft`) →
     *     `impactOccurred` (oddiy tebranish).
     */
    haptic: function (style) {
      try {
        if (!tg || !tg.HapticFeedback) {
          return;
        }
        const preset = style || "light";
        const isNotification =
          preset === "error" || preset === "success" || preset === "warning";
        if (isNotification) {
          if (typeof tg.HapticFeedback.notificationOccurred === "function") {
            tg.HapticFeedback.notificationOccurred(preset);
          }
          return;
        }
        tg.HapticFeedback.impactOccurred(preset);
      } catch (error) {
        /* e'tiborsiz */
      }
    },
    /** Foydalanuvchiga xabar (Telegram popup yoki brauzer alert). */
    alert: function (message) {
      try {
        if (tg && typeof tg.showAlert === "function") {
          tg.showAlert(String(message));
          return;
        }
      } catch (error) {
        /* e'tiborsiz */
      }
      window.alert(String(message));
    },
    /** Tasdiqlash oynasi (Telegram popup yoki brauzer confirm). */
    confirm: function (message) {
      return new Promise(function (resolve) {
        try {
          if (tg && typeof tg.showConfirm === "function") {
            tg.showConfirm(String(message), function (ok) {
              resolve(Boolean(ok));
            });
            return;
          }
        } catch (error) {
          /* e'tiborsiz */
        }
        resolve(window.confirm(String(message)));
      });
    },
    /** Ilovani ishga tayyorlash (ranglar, balandlik, sarlavha). */
    ready: function () {
      if (!tg) {
        return;
      }
      try {
        tg.ready();
        tg.expand();
        if (typeof tg.setHeaderColor === "function" && tg.themeParams) {
          tg.setHeaderColor(tg.themeParams.bg_color || "#ffffff");
        }
      } catch (error) {
        /* e'tiborsiz */
      }
    },
    theme: function () {
      return (tg && tg.themeParams) || {};
    },
  };
})();
