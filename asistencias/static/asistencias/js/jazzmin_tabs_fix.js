// asistencias/static/asistencias/js/jazzmin_tabs_fix.js
document.addEventListener("DOMContentLoaded", function () {
  // Busca SOLO pestañas del formulario (evita romper menú, logout, etc.)
  const navTabs = document.querySelectorAll(".nav-tabs");

  navTabs.forEach((tabs) => {
    const tabLinks = tabs.querySelectorAll('a[data-toggle="tab"], a[data-bs-toggle="tab"], a.nav-link');

    tabLinks.forEach((a) => {
      a.addEventListener("click", function (e) {
        const target = this.getAttribute("href");
        if (!target || !target.startsWith("#")) return;

        const pane = document.querySelector(target);
        if (!pane) return; // si no existe, no hacemos nada

        e.preventDefault();

        // ✅ desactivar SOLO dentro de este grupo de tabs (no toda la página)
        tabs.querySelectorAll(".nav-link").forEach((x) => x.classList.remove("active"));

        // el contenedor de panes suele estar cerca
        const root = tabs.closest(".card, .content, .container-fluid, form, body");
        const tabContent = (root && root.querySelector(".tab-content")) || document.querySelector(".tab-content");
        if (tabContent) {
          tabContent.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active", "show"));
        } else {
          // fallback
          document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active", "show"));
        }

        // ✅ activar actual
        this.classList.add("active");
        pane.classList.add("active", "show");

        // ✅ actualizar hash (para que el link quede bien)
        try {
          history.replaceState(null, "", target);
        } catch (_) {}
      });
    });
  });

  // ✅ si entras con URL que ya trae #algo, activa esa pestaña al cargar
  if (window.location.hash) {
    const h = window.location.hash;
    const link =
      document.querySelector(`.nav-tabs a[href="${CSS.escape(h)}"]`) ||
      document.querySelector(`.nav-tabs a[href="${h}"]`);
    if (link) link.click();
  }
});
