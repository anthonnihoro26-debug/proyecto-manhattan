// asistencias/static/js/jazzmin_tabs_fix.js
document.addEventListener("DOMContentLoaded", function () {
  // Arreglo universal: tabs del admin (Jazzmin/AdminLTE) aunque falle bootstrap JS
  const links = document.querySelectorAll('a[data-toggle="tab"], a[data-bs-toggle="tab"]');

  links.forEach((a) => {
    a.addEventListener("click", function (e) {
      const target = this.getAttribute("href");
      if (!target || !target.startsWith("#")) return;

      e.preventDefault();

      // desactivar todos
      document.querySelectorAll(".nav-link").forEach((x) => x.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active", "show"));

      // activar actual
      this.classList.add("active");
      const pane = document.querySelector(target);
      if (pane) pane.classList.add("active", "show");
    });
  });
});
