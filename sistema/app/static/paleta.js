// Busca rápida e atalhos de teclado do ZERA CONTÁBIL MAX.
//   Ctrl+K (ou o botão “Ir para…” do trilho): abre qualquer empresa, aba ou tela digitando parte do nome
//     (“creche rev” → Revisão da Creche). Sem digitar nada, mostra as empresas abertas por último.
//   ?  → mostra todos os atalhos          /  → vai para a busca da tela
//   Na empresa: 1 a 5 → Plano, Aprendizado, Extratos, Revisão, Exportar · 0 → Cadastro
// Tudo é complemento: sem JavaScript o sistema funciona igual, pelo menu e pelos links.
(function () {
  "use strict";
  var paleta = document.getElementById("paleta");
  var ajuda = document.getElementById("atalhos-ajuda");
  if (!paleta) return;
  var campo = paleta.querySelector("input");
  var lista = paleta.querySelector("[data-resultados]");
  var dados = null, visiveis = [], escolhido = 0;

  function normalizar(texto) {
    return (texto || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }
  function digitando(alvo) {
    return alvo && (alvo.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName));
  }
  function icone(nome) {
    return '<svg class="ico" aria-hidden="true"><use href="#i-' + nome + '"></use></svg>';
  }
  function escapar(texto) {
    return String(texto).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  // ---------------------------------------------------------------- empresas abertas por último (neste navegador)
  function recentes() {
    try { return JSON.parse(localStorage.getItem("zcm-recentes") || "[]"); } catch (erro) { return []; }
  }
  var naEmpresa = location.pathname.match(/^\/empresas\/(\d+)$/);
  if (naEmpresa) {
    try {
      var lista_ = recentes().filter(function (id) { return id !== +naEmpresa[1]; });
      lista_.unshift(+naEmpresa[1]);
      localStorage.setItem("zcm-recentes", JSON.stringify(lista_.slice(0, 6)));
    } catch (erro) { /* navegador sem armazenamento */ }
  }

  // ---------------------------------------------------------------- o que pode ser aberto
  function montar(d) {
    var itens = [];
    d.empresas.forEach(function (e) {
      var base = normalizar(e.nome + " " + e.outro_nome + " " + e.detalhe);
      itens.push({ grupo: "Empresas", empresa: e.id, titulo: e.nome, sub: e.detalhe + " · " + e.proximo,
        url: "/empresas/" + e.id + "?aba=" + e.aba, icone: "empresas", busca: base, peso: 0 });
      d.abas.forEach(function (a) {
        itens.push({ grupo: "Abas", empresa: e.id, titulo: e.nome + " · " + a.nome, sub: e.detalhe,
          url: "/empresas/" + e.id + "?aba=" + a.aba, icone: a.icone, busca: base + " " + normalizar(a.nome),
          peso: 3, so_buscando: true });
      });
    });
    d.telas.forEach(function (t) {
      itens.push({ grupo: "Telas", titulo: t.nome, sub: "", url: t.url, icone: t.icone,
        busca: normalizar(t.nome + " " + t.palavras), peso: 1 });
    });
    itens.push({ grupo: "Ações", titulo: "Trocar tema claro / escuro", sub: "", acao: "tema", icone: "tema",
      busca: "tema claro escuro modo noite dia", peso: 2 });
    itens.push({ grupo: "Ações", titulo: "Ver todos os atalhos do teclado", sub: "", acao: "ajuda", icone: "teclado",
      busca: "atalhos teclado ajuda", peso: 2 });
    return itens;
  }

  function filtrar(consulta) {
    var termos = normalizar(consulta).split(/\s+/).filter(Boolean);
    if (!termos.length) {
      var ordem = recentes();
      var deRecentes = ordem.map(function (id) {
        return dados.find(function (i) { return i.empresa === id && i.grupo === "Empresas"; });
      }).filter(Boolean).map(function (i) { return Object.assign({}, i, { grupo: "Abertas por último" }); });
      var outras = dados.filter(function (i) { return i.grupo === "Empresas" && ordem.indexOf(i.empresa) < 0; });
      return deRecentes.concat(outras.slice(0, Math.max(0, 6 - deRecentes.length)),
        dados.filter(function (i) { return i.grupo === "Telas"; }));
    }
    return dados.map(function (item) {
      var pontos = item.peso * 10;
      for (var n = 0; n < termos.length; n++) {
        var onde = item.busca.indexOf(termos[n]);
        if (onde < 0) return null;
        pontos += onde === 0 || item.busca.charAt(onde - 1) === " " ? onde / 20 : 5 + onde / 10; // começo de palavra vale mais
      }
      if (item.so_buscando && termos.length < 2) pontos += 20; // a aba aparece depois da empresa, a não ser que se peça
      return { item: item, pontos: pontos };
    }).filter(Boolean).sort(function (a, b) { return a.pontos - b.pontos; })
      .slice(0, 14).map(function (r) { return r.item; });
  }

  function desenhar() {
    visiveis = filtrar(campo.value);
    escolhido = Math.min(escolhido, Math.max(0, visiveis.length - 1));
    if (!visiveis.length) {
      lista.innerHTML = '<li class="paleta-vazio">Nada com “' + escapar(campo.value) + '”. Tente outra parte do nome, o código ou o CNPJ.</li>';
      return;
    }
    var html = "", grupo = null;
    visiveis.forEach(function (item, n) {
      if (item.grupo !== grupo) { grupo = item.grupo; html += '<li class="paleta-grupo" role="presentation">' + escapar(grupo) + "</li>"; }
      html += '<li role="option" id="paleta-' + n + '" data-n="' + n + '"' + (n === escolhido ? ' aria-selected="true"' : "") + ">" +
        '<span class="paleta-ico">' + icone(item.icone) + "</span>" +
        '<span class="paleta-texto"><strong>' + escapar(item.titulo) + "</strong>" +
        (item.sub ? "<small>" + escapar(item.sub) + "</small>" : "") + "</span>" +
        '<kbd class="paleta-enter">Enter</kbd></li>';
    });
    lista.innerHTML = html;
    campo.setAttribute("aria-activedescendant", "paleta-" + escolhido);
    var atual = lista.querySelector('[aria-selected="true"]');
    if (atual) atual.scrollIntoView({ block: "nearest" });
  }

  function abrirItem(item) {
    if (!item) return;
    if (item.acao === "tema") { paleta.close(); var b = document.querySelector("[data-alternar-tema]"); if (b) b.click(); return; }
    if (item.acao === "ajuda") { paleta.close(); abrirAjuda(); return; }
    document.documentElement.classList.add("navegando");
    location.href = item.url;
  }

  function abrir() {
    if (paleta.open) return;
    campo.value = "";
    escolhido = 0;
    lista.innerHTML = '<li class="paleta-vazio">Carregando…</li>';
    paleta.showModal();
    campo.focus();
    if (dados) { desenhar(); return; }
    fetch("/atalhos", { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { dados = montar(d); desenhar(); })
      .catch(function () { lista.innerHTML = '<li class="paleta-vazio">Não consegui carregar a lista. Feche (Esc) e tente de novo.</li>'; });
  }
  function abrirAjuda() { if (ajuda && !ajuda.open) ajuda.showModal(); }

  campo.addEventListener("input", function () { escolhido = 0; if (dados) desenhar(); });
  campo.addEventListener("keydown", function (evento) {
    if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
      evento.preventDefault();
      if (!visiveis.length) return;
      escolhido = (escolhido + (evento.key === "ArrowDown" ? 1 : -1) + visiveis.length) % visiveis.length;
      desenhar();
    } else if (evento.key === "Enter") {
      evento.preventDefault();
      abrirItem(visiveis[escolhido]);
    }
  });
  lista.addEventListener("click", function (evento) {
    var linha = evento.target.closest("[data-n]");
    if (linha) abrirItem(visiveis[+linha.getAttribute("data-n")]);
  });
  lista.addEventListener("mousemove", function (evento) {
    var linha = evento.target.closest("[data-n]");
    if (linha && +linha.getAttribute("data-n") !== escolhido) { escolhido = +linha.getAttribute("data-n"); desenhar(); }
  });
  [paleta, ajuda].forEach(function (dialogo) {
    if (!dialogo) return;
    dialogo.addEventListener("click", function (evento) { if (evento.target === dialogo) dialogo.close(); }); // clique fora fecha
  });

  // ---------------------------------------------------------------- atalhos
  document.addEventListener("click", function (evento) {
    if (evento.target.closest("[data-abrir-paleta]")) abrir();
    if (evento.target.closest("[data-abrir-atalhos]")) abrirAjuda();
  });
  document.addEventListener("keydown", function (evento) {
    if ((evento.ctrlKey || evento.metaKey) && !evento.altKey && evento.key.toLowerCase() === "k") {
      evento.preventDefault();
      if (paleta.open) paleta.close(); else abrir();
      return;
    }
    if (evento.ctrlKey || evento.metaKey || evento.altKey || digitando(evento.target) || paleta.open) return;
    if (ajuda && ajuda.open) return;
    if (evento.key === "?") { evento.preventDefault(); abrirAjuda(); return; }
    if (evento.key === "/") {
      var busca = document.querySelector("input[type=search], input[name=q]");
      evento.preventDefault();
      if (busca) { busca.focus(); busca.select(); } else abrir();
      return;
    }
    if (/^[0-5]$/.test(evento.key) && document.querySelector(".jornada")) {
      var destino = evento.key === "0" ? document.querySelector(".botao-cadastro")
        : document.querySelectorAll(".progresso li > a")[+evento.key - 1];
      if (destino) { evento.preventDefault(); destino.click(); }
    }
  });
})();
