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

/* Triagem da lista: abas por situação + busca + ordenação. Tudo client-side,
   sobre as linhas já renderizadas (volume de POC). Acessível: abas com
   aria-selected, ordenação reflete aria-sort. */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var tabela = document.getElementById("tabela-notas");
    if (!tabela) return;
    var tbody = tabela.querySelector("tbody");
    var linhas = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
    var abas = Array.prototype.slice.call(document.querySelectorAll(".tab"));
    var busca = document.getElementById("busca");
    var vazio = document.getElementById("vazio");
    var filtro = "todas";
    var sortKey = null, sortDir = 1;

    function contagem() {
      var c = { atencao: 0, pronta: 0, ja: 0, todas: linhas.length };
      linhas.forEach(function (tr) { var s = tr.dataset.status; if (s in c) c[s]++; });
      return c;
    }
    function atualizarContagens() {
      var c = contagem();
      abas.forEach(function (b) {
        var n = b.querySelector(".n");
        if (n) n.textContent = c[b.dataset.filtro] != null ? c[b.dataset.filtro] : 0;
      });
    }
    function aplicar() {
      var termo = (busca && busca.value || "").trim().toLowerCase();
      var visiveis = 0;
      linhas.forEach(function (tr) {
        var okStatus = filtro === "todas" || tr.dataset.status === filtro;
        var okBusca = !termo || (tr.dataset.busca || "").indexOf(termo) !== -1;
        var mostrar = okStatus && okBusca;
        tr.hidden = !mostrar;
        if (mostrar) visiveis++;
      });
      if (vazio) vazio.hidden = visiveis > 0;
    }
    function escolherAba(f) {
      filtro = f;
      abas.forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.filtro === f)); });
      aplicar();
    }
    function ordenar(key) {
      if (sortKey === key) { sortDir = -sortDir; } else { sortKey = key; sortDir = 1; }
      linhas.sort(function (a, b) {
        var va = parseFloat(a.dataset[key]) || 0, vb = parseFloat(b.dataset[key]) || 0;
        return (va - vb) * sortDir;
      });
      linhas.forEach(function (tr) { tbody.appendChild(tr); });
      tabela.querySelectorAll("th.sortable").forEach(function (th) {
        var ativa = th.dataset.sort === key;
        th.setAttribute("aria-sort", ativa ? (sortDir === 1 ? "ascending" : "descending") : "none");
        var arr = th.querySelector(".arr");
        if (arr) arr.textContent = ativa ? (sortDir === 1 ? "▲" : "▼") : "";
      });
    }

    abas.forEach(function (b) { b.addEventListener("click", function () { escolherAba(b.dataset.filtro); }); });
    tabela.querySelectorAll("th.sortable").forEach(function (th) {
      th.addEventListener("click", function () { ordenar(th.dataset.sort); });
    });
    if (busca) busca.addEventListener("input", aplicar);

    atualizarContagens();
    var c = contagem();
    escolherAba(c.atencao > 0 ? "atencao" : (c.pronta > 0 ? "pronta" : "todas"));
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
