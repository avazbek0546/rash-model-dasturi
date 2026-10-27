/* ---------------------------------------------------------------------------
   Mini App karkasi: pastki navigatsiya (4 tab), umumiy xabarlar, modul
   yuklash mexanizmi. Har bir bo'lim o'z yuklagichini `App.onShow` orqali
   ro'yxatdan o'tkazadi.
--------------------------------------------------------------------------- */
(function () {
  "use strict";

  const TITLES = {
    queue: ["Imtihonlar", "Rasch modeli asosida baholash"],
    results: ["Natijalar", "Baho dinamikasi va tahlil"],
    offline: ["Offline imtihon", "Hududlar bo'yicha imtihonlar"],
    profile: ["Profil", "Shaxsiy ma'lumotlar"],
    admin: ["Test yaratish", "O'qituvchi paneli"],
  };

  const listeners = { queue: [], results: [], offline: [], profile: [], admin: [] };
  let noticeTimer = null;

  function noticeBox() {
    return document.getElementById("global-notice");
  }

  function setNotice(kind, message, autoHide) {
    const box = noticeBox();
    if (!box) {
      return;
    }
    box.className = "notice " + (kind || "success");
    box.textContent = String(message);
    box.style.margin = "10px 14px 0";
    if (noticeTimer) {
      window.clearTimeout(noticeTimer);
    }
    if (autoHide) {
      noticeTimer = window.setTimeout(clearNotice, 5000);
    }
  }

  function clearNotice() {
    const box = noticeBox();
    if (!box) {
      return;
    }
    box.className = "hidden";
    box.textContent = "";
    if (noticeTimer) {
      window.clearTimeout(noticeTimer);
      noticeTimer = null;
    }
  }

  /** Admin («⚙️ Test yaratish») tugmasini ko'rsatish (`/api/v2/me` → `is_admin`). */
  function loadAdminAccess() {
    API.get("/api/v2/me")
      .then(function (data) {
        if (!data || !data.is_admin) {
          return;
        }
        const button = document.getElementById("nav-admin");
        if (button) {
          button.classList.remove("hidden");
        }
      })
      .catch(function () {
        /* admin emas yoki xato — tugma yashirin qoladi */
      });
  }

  function showTab(name) {
    if (!TITLES[name]) {
      return;
    }
    document.querySelectorAll(".tab-panel").forEach(function (panel) {
      panel.classList.toggle("active", panel.id === "tab-" + name);
    });
    document.querySelectorAll("#bottom-nav button").forEach(function (button) {
      button.classList.toggle("active", button.dataset.tab === name);
    });

    const titles = TITLES[name];
    document.getElementById("header-title").textContent = titles[0];
    document.getElementById("header-subtitle").textContent = titles[1];
    document.querySelector("main").scrollTop = 0;
    API.haptic("light");

    listeners[name].forEach(function (callback) {
      try {
        callback();
      } catch (error) {
        console.error("Bo'limni yuklashda xatolik (" + name + "):", error);
      }
    });
  }

  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatCountdown(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    const pad = function (value) {
      return String(value).padStart(2, "0");
    };
    return (hours > 0 ? pad(hours) + ":" : "") + pad(minutes) + ":" + pad(secs);
  }

  window.App = {
    /** Bo'lim ekranga chiqqanda chaqiriladigan yuklagichni ro'yxatdan o'tkazadi. */
    onShow: function (tab, callback) {
      if (listeners[tab]) {
        listeners[tab].push(callback);
      }
    },
    setNotice: setNotice,
    clearNotice: clearNotice,
    /**
     * Majburiy xabar (Telegram popup yoki brauzer `alert`).
     *
     * MUHIM: bu metod ilgari `window.App` da e'lon qilinmagan edi, holbuki
     * `queue.js`, `results.js` va `profile.js` uni chaqirardi. Natijada
     * `catch` blokidagi `TypeError: App.alert is not a function` yutilib,
     * foydalanuvchi xatoni umuman ko'rmasdi («bot ishlamayapti» taassuroti).
     */
    alert: function (message) {
      API.alert(message);
    },
    /** Tasdiqlash oynasi (`Promise<boolean>`). */
    confirm: function (message) {
      return API.confirm(message);
    },
    escape: escapeHtml,
    formatCountdown: formatCountdown,
  };

  function initialTabName() {
    // Botdagi «📊 Natijalarim» tugmasi `?tab=results` bilan ochadi.
    try {
      const requested = new URLSearchParams(window.location.search).get("tab");
      if (requested && TITLES[requested]) {
        return requested;
      }
    } catch (error) {
      /* URLSearchParams mavjud bo'lmasa — queue */
    }
    return "queue";
  }

  window.addEventListener("DOMContentLoaded", function () {
    API.ready();
    loadAdminAccess();

    document.querySelectorAll("#bottom-nav button").forEach(function (button) {
      button.addEventListener("click", function () {
        showTab(button.dataset.tab);
      });
    });

    if (!API.isTelegram) {
      const hint = /debug_user_id/.test(window.location.search)
        ? "Test rejimi (debug_user_id) yoqilgan."
        : "Ma'lumotlar yuklanmasligi mumkin — brauzerda sinash uchun manzilga ?debug_user_id=123 qo'shing.";
      setNotice(
        "error",
        "Ilova Telegram ichida ochilmagan (WEBAPP_DEV_MODE bilan ham ishlaydi). " + hint,
        false
      );
    }

    showTab(initialTabName());
  });
})();
