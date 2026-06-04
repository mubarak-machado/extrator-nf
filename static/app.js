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

/* Validação inline da NPP (Fase 2): confirmar/retificar sem recarregar a página.
   Progressive enhancement — sem JS, os <form> seguem como POST normal (redirect+flash).
   O SERVIDOR continua recomputando o destaque (I-2), gravando com autor+data (I-4) e
   renderizando os fragmentos; este código só troca innerHTML e alterna flags — nunca
   faz aritmética nem formatação de valor. Erros voltam como JSON e são exibidos (I-6). */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var secao = document.querySelector('[aria-label="Grupos de impostos"]');
    if (!secao) return;

    function acharLinha(chave, tributo) {
      var trs = secao.querySelectorAll("tr[data-chave]");
      for (var i = 0; i < trs.length; i++) {
        if (trs[i].getAttribute("data-chave") === chave &&
            trs[i].getAttribute("data-tributo") === tributo) return trs[i];
      }
      return null;
    }

    function limparErro(cel) {
      var e = cel.querySelector(".erro-inline");
      if (e) e.remove();
    }

    function mostrarErro(cel, msg) {
      limparErro(cel);
      var p = document.createElement("p");
      p.className = "erro-inline";
      p.setAttribute("role", "alert");
      p.textContent = msg;
      cel.insertBefore(p, cel.firstChild);
    }

    function setVal(id, txt) {
      var el = document.getElementById(id);
      if (!el) return;
      var v = el.querySelector("[data-val]");
      if (v) v.textContent = txt;
    }

    function toggle(id, seletor, mostrar) {
      var el = document.getElementById(id);
      if (!el) return;
      var alvo = el.querySelector(seletor);
      if (alvo) alvo.hidden = !mostrar;
    }

    function atualizarLote(n) {
      var bloco = document.getElementById("bloco-confirmar-lote");
      if (!bloco) return;
      var span = bloco.querySelector("[data-n-pendentes]");
      if (span) span.textContent = n;
      bloco.hidden = (n === 0);
    }

    function realce(row) {
      row.classList.add("linha-validada");
      setTimeout(function () { row.classList.remove("linha-validada"); }, 1500);
    }

    // Recomputa o resumo do cabeçalho do grupo (chips + total) a partir do DOM já
    // atualizado, para não defasar quando o grupo está fechado. Pendência e divergência
    // são contadas no nível do tributo (uniforme entre federal/INSS/ISS), igual ao
    // servidor (_grupos_impostos).
    function atualizarCabecalhoGrupo(grupoEl, totalTxt) {
      if (!grupoEl) return;
      var det = grupoEl.closest("details.grupo-colapsavel");
      var head = det && det.querySelector(".grupo-head");
      if (!head) return;
      var nTotal = grupoEl.querySelectorAll("tr[data-chave]").length;
      var nPend = grupoEl.querySelectorAll(".cel-situacao .warn").length;
      // divergências: a marca data-diverge é persistente (não some ao validar). Uma
      // divergência é "tratada" quando a célula de situação mostra "validado" (.ok-chip).
      var divRows = grupoEl.querySelectorAll("tr[data-diverge]");
      var nDivTotal = divRows.length, nDivTratadas = 0;
      divRows.forEach(function (tr) { if (tr.querySelector(".cel-situacao .ok-chip")) nDivTratadas++; });
      function chip(seletor, mostrar, texto) {
        var c = head.querySelector(seletor);
        if (!c) return;
        c.hidden = !mostrar;
        if (mostrar && texto != null) {
          var t = c.querySelector("[data-txt]");
          if (t) t.textContent = texto;
        }
      }
      function plDiv(n, suf) { var s = n === 1 ? "" : "s"; return n + " divergência" + s + " " + suf + s; }
      var found = head.querySelector(".gh-chip.found");
      if (found) found.classList.toggle("alarme", nDivTotal > nDivTratadas);
      chip(".gh-chip.found", nDivTotal > 0, plDiv(nDivTotal, "encontrada"));
      chip(".gh-chip.treated", nDivTratadas > 0, plDiv(nDivTratadas, "tratada"));
      chip(".gh-chip.pend", nPend > 0, nPend + " a validar");
      chip(".gh-chip.ok", nTotal > 0 && nPend === 0 && nDivTotal === 0, null);
      var b = head.querySelector("[data-grupo-total-head]");
      if (b && totalTxt != null) b.textContent = totalTxt;
    }

    function aplicar(data) {
      var row = acharLinha(data.chave, data.tributo);
      if (row) {
        var celV = row.querySelector(".cel-validar");
        var celS = row.querySelector(".cel-situacao");
        if (celV) celV.innerHTML = data.cel_validar;
        if (celS) celS.innerHTML = data.cel_situacao;
        row.classList.remove("linha-diverge");  // validada deixa de pedir revisão (#2)
        realce(row);
      }
      var prog = document.getElementById("bloco-progresso");
      if (prog) prog.innerHTML = data.progresso;
      var grupo = secao.querySelector('[data-grupo="' + data.grupo_key + '"]');
      var gt = grupo ? grupo.querySelector("[data-grupo-total]") : null;
      if (gt) gt.textContent = data.grupo_total;
      atualizarCabecalhoGrupo(grupo, data.grupo_total);
      // federal é agregado por nota: troca o resumo (headline) da nota afetada e
      // realça/limpa a linha conforme a divergência destaque≠sugestão persista ou não.
      if (data.federal_resumo != null && data.federal_chave != null) {
        var fed = secao.querySelector('details[data-federal-chave="' + data.federal_chave + '"]');
        if (fed) {
          var res = fed.querySelector(".fed-resumo");
          if (res) res.innerHTML = data.federal_resumo;
          fed.classList.toggle("fed-diverge", !!data.federal_divergente);
          if (data.federal_divergente) fed.setAttribute("title", data.federal_tooltip || "");
          else fed.removeAttribute("title");
        }
      }
      setVal("dd-total-retido", data.total_retido);
      setVal("dd-liquido", data.liquido);
      toggle("dd-total-retido", "[data-parcial]", data.liquido_provisorio);
      toggle("dd-liquido", "[data-provisorio]", data.liquido_provisorio);
      atualizarLote(data.n_pendentes);
    }

    // Delegação: pega o submit de qualquer form de validação, inclusive os que entram
    // depois via innerHTML (Revalidar). A validação nativa (required) roda antes daqui.
    secao.addEventListener("submit", function (e) {
      var form = e.target;
      var cel = form.closest && form.closest(".cel-validar");
      if (!cel) return;                 // não é form de validação inline
      e.preventDefault();
      limparErro(cel);
      var botoes = form.querySelectorAll("button");
      botoes.forEach(function (b) { b.disabled = true; });
      fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch" },
        body: new FormData(form)
      }).then(function (resp) {
        return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
      }).then(function (res) {
        if (!res.ok || !res.data || !res.data.ok) {
          mostrarErro(cel, (res.data && res.data.mensagem) || "Não foi possível validar.");
          botoes.forEach(function (b) { b.disabled = false; });
          return;
        }
        aplicar(res.data);              // troca a célula (botões somem junto)
      }).catch(function () {
        form.submit();                  // sem rede: degrada para o POST normal
      });
    });
  });
})();

/* Abas da NPP (Documentos de origem / Grupos de impostos). Progressive enhancement:
   as abas são links reais para ?aba=... (funcionam sem JS, recarregando). Com JS,
   alternamos os painéis sem reload e atualizamos a URL (replaceState), sem nova entrada
   no histórico. Os dois painéis já vêm renderizados pelo servidor. */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var lista = document.getElementById("abas-npp");
    if (!lista) return;
    var abas = Array.prototype.slice.call(lista.querySelectorAll('[role="tab"]'));

    function mostrar(aba) {
      abas.forEach(function (t) {
        var ativo = (t.id === "tab-" + aba);
        t.setAttribute("aria-selected", ativo ? "true" : "false");
        var painel = document.getElementById(t.getAttribute("aria-controls"));
        if (painel) painel.hidden = !ativo;
      });
    }

    abas.forEach(function (t) {
      t.addEventListener("click", function (e) {
        e.preventDefault();
        var aba = t.id.replace("tab-", "");
        mostrar(aba);
        try { history.replaceState(null, "", t.getAttribute("href")); } catch (_) {}
      });
    });
  });
})();
