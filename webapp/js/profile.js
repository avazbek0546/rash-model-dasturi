/* ---------------------------------------------------------------------------
   "Profil" bo'limi: ism-familiyani tahrirlash, Telegram ID va statistika.
--------------------------------------------------------------------------- */
(function () {
  "use strict";

  function byId(id) {
    return document.getElementById(id);
  }

  async function loadProfile() {
    try {
      const me = await API.get("/api/me");
      byId("profile-name").value = me.full_name || "";
      byId("profile-id").textContent = me.user_id;
      byId("profile-tests").textContent = me.tests_done;
      byId("profile-tz").textContent = me.timezone + " · " + me.now_local;
    } catch (error) {
      App.setNotice("error", error.message, false);
    }
  }

  async function saveProfile() {
    const fullName = (byId("profile-name").value || "").trim();
    if (fullName.length < 3) {
      App.setNotice("error", "Ism-familiya kamida 3 belgidan iborat bo'lishi kerak.", true);
      return;
    }
    try {
      const result = await API.post("/api/me", { full_name: fullName });
      API.haptic("medium");
      byId("profile-name").value = result.full_name;
      App.setNotice("success", "Profil saqlandi.", true);
    } catch (error) {
      App.alert(error.message);
    }
  }

  window.addEventListener("DOMContentLoaded", function () {
    byId("save-profile").addEventListener("click", saveProfile);
    App.onShow("profile", loadProfile);
  });
})();
