/* Preferências de exibição: tema e escala de fonte, persistidas em localStorage.
   Aplicadas cedo (head) para evitar "flash" de tema. */
(function () {
  var root = document.documentElement;

  // ----- tema: auto | light | dark -----
  var tema = localStorage.getItem("nf_tema") || "auto";
  root.setAttribute("data-theme", tema);

  // ----- escala de fonte: 100 | 112 | 125 | 140 (%) -----
  var fs = localStorage.getItem("nf_fs") || "100";
  root.style.setProperty("--fs", fs + "%");

  function syncBotoes() {
    document.querySelectorAll("[data-set-theme]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.setTheme === root.getAttribute("data-theme")));
    });
    document.querySelectorAll("[data-set-fs]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.setFs === (localStorage.getItem("nf_fs") || "100")));
    });
  }

  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-set-theme]");
    if (t) {
      root.setAttribute("data-theme", t.dataset.setTheme);
      localStorage.setItem("nf_tema", t.dataset.setTheme);
      syncBotoes();
      return;
    }
    var f = e.target.closest("[data-set-fs]");
    if (f) {
      root.style.setProperty("--fs", f.dataset.setFs + "%");
      localStorage.setItem("nf_fs", f.dataset.setFs);
      syncBotoes();
    }
  });

  document.addEventListener("DOMContentLoaded", syncBotoes);
})();
