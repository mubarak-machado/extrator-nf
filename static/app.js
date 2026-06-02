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

/* Menus expansíveis (<details class="dropdown">): fecham ao clicar fora ou com Esc,
   e só um fica aberto por vez. Disclosure nativo — sem JS ainda abrem no clique e são
   acessíveis por teclado. */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var menus = Array.prototype.slice.call(document.querySelectorAll("details.dropdown"));
    if (!menus.length) return;
    menus.forEach(function (d) {
      d.addEventListener("toggle", function () {
        if (d.open) menus.forEach(function (o) { if (o !== d) o.removeAttribute("open"); });
      });
    });
    document.addEventListener("click", function (e) {
      menus.forEach(function (d) {
        if (d.open && !d.contains(e.target)) d.removeAttribute("open");
      });
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      menus.forEach(function (d) {
        if (d.open) { d.removeAttribute("open"); var s = d.querySelector("summary"); if (s) s.focus(); }
      });
    });
  });
})();

/* Modal de feedback do sistema: abre sozinha quando há mensagem (flash) e fecha
   no botão, no Esc (nativo do <dialog>) ou clicando fora. */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var m = document.getElementById("modal-msg");
    if (!m) return;
    if (typeof m.showModal === "function") { m.showModal(); }
    else { m.setAttribute("open", ""); }            // fallback navegadores antigos
    m.querySelectorAll("[data-fechar-modal]").forEach(function (b) {
      b.addEventListener("click", function () { m.close(); });
    });
    m.addEventListener("click", function (e) {       // clique no backdrop fecha
      if (e.target === m) m.close();
    });
  });
})();

/* Marcação de material: o campo de valor só faz sentido quando "Sim". Mostra/
   oculta conforme o rádio (degrada bem: sem JS, o campo fica visível). */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var campo = document.getElementById("campo-valor-material");
    var radios = document.querySelectorAll("[data-mostra-material]");
    if (!campo || !radios.length) return;
    function sync() {
      var sim = document.querySelector('input[name="material"]:checked');
      campo.hidden = !(sim && sim.value === "sim");
    }
    radios.forEach(function (r) { r.addEventListener("change", sync); });
    sync();
  });
})();

/* Campos condicionais (form de contrato): elementos com data-mostra-se="nome"
   (checkbox) ou data-mostra-se="nome=valor" (radio/select) só aparecem quando a
   condição é satisfeita. Degrada bem: sem JS, ficam visíveis. */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-mostra-se]").forEach(function (el) {
      var cond = el.dataset.mostraSe;
      var eq = cond.indexOf("=");
      var name = eq >= 0 ? cond.slice(0, eq) : cond;
      var want = eq >= 0 ? cond.slice(eq + 1) : null;
      var inputs = document.querySelectorAll('[name="' + name + '"]');
      function sync() {
        var on;
        if (want === null) {                       // checkbox
          var cb = document.querySelector('[name="' + name + '"]');
          on = !!(cb && cb.checked);
        } else {                                   // radio ou select
          var sel = document.querySelector('select[name="' + name + '"]');
          var val = sel ? sel.value
                        : (document.querySelector('[name="' + name + '"]:checked') || {}).value;
          on = val === want;
        }
        el.hidden = !on;
      }
      inputs.forEach(function (i) { i.addEventListener("change", sync); });
      sync();
    });
  });
})();

/* Seletor de pasta (webkitdirectory): botão aciona o input oculto e mostra a
   pasta escolhida e a contagem de XML, antes de enviar. */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-abrir-seletor]").forEach(function (botao) {
      var input = document.getElementById(botao.dataset.abrirSeletor);
      if (!input) return;
      botao.addEventListener("click", function () { input.click(); });
      var info = document.querySelector('[data-info-seletor="' + input.id + '"]');
      input.addEventListener("change", function () {
        var arquivos = Array.prototype.slice.call(input.files || []);
        var xmls = arquivos.filter(function (f) { return /\.xml$/i.test(f.name); });
        if (!info) return;
        if (!arquivos.length) { info.textContent = "Nenhuma pasta selecionada"; return; }
        var rel = arquivos[0].webkitRelativePath || "";
        var pasta = rel ? rel.split("/")[0] : "pasta";
        info.textContent = pasta + " · " + xmls.length + " XML";
      });
    });
  });
})();
