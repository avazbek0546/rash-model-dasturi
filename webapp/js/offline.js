/* ---------------------------------------------------------------------------
   "Offline imtihon" bo'limi: hududlar bo'yicha imtihonlar ro'yxati.

   Hozircha ma'lumot statik (`/api/offline`) — kelajakda hududiy imtihonlar
   (sana, joy, ro'yxatdan o'tish) shu bo'limga qo'shiladi.
--------------------------------------------------------------------------- */
(function () {
  "use strict";

  function byId(id) {
    return document.getElementById(id);
  }

  async function loadOffline() {
    const box = byId("offline-list");
    box.innerHTML = '<div class="spinner"></div>';
    try {
      const data = await API.get("/api/offline");
      byId("offline-note").textContent = data.note || "";

      const regions = data.regions || [];
      if (!regions.length) {
        box.innerHTML = '<p class="muted">Hozircha hududlar ro\'yxati bo\'sh.</p>';
        return;
      }
      box.innerHTML = regions
        .map(function (region) {
          return (
            '<div class="exam-item"><div><div class="title">' +
            App.escape(region.region) +
            '</div><div class="meta">' +
            App.escape(region.note || "") +
            '</div></div><span class="badge upcoming">Rejalashtirilgan</span></div>'
          );
        })
        .join("");
    } catch (error) {
      box.innerHTML = '<p class="muted">' + App.escape(error.message) + "</p>";
    }
  }

  window.addEventListener("DOMContentLoaded", function () {
    App.onShow("offline", loadOffline);
  });
})();
