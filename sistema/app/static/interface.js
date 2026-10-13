// Interface do ZERA CONTÁBIL MAX: avisos que somem sozinhos, menu do celular, números que contam,
// confete dourado nas conquistas (Revisão zerada, lanctos.txt gerado) e o placar da Revisão ao vivo.
// Tudo é enfeite: sem JavaScript as telas continuam funcionando.
(function () {
  "use strict";
  var calmo = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------------------------------------------------------- avisos (toasts)
  function fecharToast(toast) {
    if (!toast || toast.classList.contains("saindo")) return;
    toast.classList.add("saindo");
    setTimeout(function () { toast.remove(); }, 320);
  }
  function prepararToasts() {
    document.querySelectorAll("[data-toast]").forEach(function (toast, i) {
      var tipo = toast.getAttribute("data-toast");
      toast.style.setProperty("--atraso", i * 90 + "ms");
      if (tipo === "festa") celebrar();
      if (tipo === "ok" || tipo === "festa") setTimeout(function () { fecharToast(toast); }, 7000 + i * 600);
    });
  }
  document.addEventListener("click", function (evento) {
    var botao = evento.target.closest("[data-fechar-toast]");
    if (botao) fecharToast(botao.closest(".toast"));
  });

  // ---------------------------------------------------------------- menu do celular
  document.addEventListener("click", function (evento) {
    if (evento.target.closest("[data-abrir-menu]")) document.body.classList.add("menu-aberto");
    else if (evento.target.closest("[data-fechar-menu]")) document.body.classList.remove("menu-aberto");
  });
  document.addEventListener("keydown", function (evento) {
    if (evento.key === "Escape") document.body.classList.remove("menu-aberto");
  });

  // ---------------------------------------------------------------- números que contam até o valor
  function contar(elemento) {
    var texto = elemento.textContent.trim();
    var alvo = parseInt(texto.replace(/\./g, ""), 10);
    if (isNaN(alvo) || alvo <= 0 || calmo) return;
    var sufixo = texto.replace(/^[\d.]+/, "");
    var inicio = null, duracao = Math.min(900, 300 + alvo * 12);
    function passo(agora) {
      if (inicio === null) inicio = agora;
      var t = Math.min(1, (agora - inicio) / duracao);
      var valor = Math.round(alvo * (1 - Math.pow(1 - t, 3)));
      elemento.textContent = valor.toLocaleString("pt-BR") + sufixo;
      if (t < 1) requestAnimationFrame(passo);
    }
    requestAnimationFrame(passo);
  }

  // ---------------------------------------------------------------- confete dourado
  var CORES = ["#EED6A0", "#C9A662", "#A8843F", "#F3F0E8", "#E6CB8D", "#3FB27F"];
  function celebrar() {
    if (calmo) return;
    var tela = document.createElement("canvas");
    tela.className = "confete";
    tela.width = window.innerWidth;
    tela.height = window.innerHeight;
    document.body.appendChild(tela);
    var ctx = tela.getContext("2d");
    var pedacos = [];
    for (var i = 0; i < 150; i++) {
      var deEsquerda = i % 2 === 0;
      pedacos.push({
        x: deEsquerda ? -10 : tela.width + 10,
        y: tela.height * (0.55 + Math.random() * 0.35),
        vx: (deEsquerda ? 1 : -1) * (5 + Math.random() * 9),
        vy: -(11 + Math.random() * 9),
        giro: Math.random() * Math.PI, vgiro: (Math.random() - 0.5) * 0.35,
        tam: 5 + Math.random() * 7, cor: CORES[i % CORES.length], lingote: Math.random() < 0.45,
      });
    }
    var inicio = performance.now();
    function quadro(agora) {
      var passou = agora - inicio;
      ctx.clearRect(0, 0, tela.width, tela.height);
      pedacos.forEach(function (p) {
        p.vy += 0.32; p.vx *= 0.99; p.x += p.vx; p.y += p.vy; p.giro += p.vgiro;
        ctx.save();
        ctx.globalAlpha = Math.max(0, 1 - passou / 2600);
        ctx.translate(p.x, p.y); ctx.rotate(p.giro); ctx.fillStyle = p.cor;
        if (p.lingote) { // lingote de ouro em miniatura (trapézio), nada redondo
          var l = p.tam;
          ctx.beginPath();
          ctx.moveTo(-l * 0.5, l * 0.25); ctx.lineTo(l * 0.5, l * 0.25);
          ctx.lineTo(l * 0.32, -l * 0.25); ctx.lineTo(-l * 0.32, -l * 0.25);
          ctx.closePath(); ctx.fill();
        } else ctx.fillRect(-p.tam / 2, -p.tam / 4, p.tam, p.tam / 2);
        ctx.restore();
      });
      if (passou < 2600) requestAnimationFrame(quadro); else tela.remove();
    }
    requestAnimationFrame(quadro);
  }
  window.celebrar = celebrar;

  function celebrarUmaVez(chave) {
    try {
      if (sessionStorage.getItem("zcm-festa:" + chave)) return;
      sessionStorage.setItem("zcm-festa:" + chave, "1");
    } catch (erro) { /* sem armazenamento: celebra mesmo assim */ }
    celebrar();
  }

  // ---------------------------------------------------------------- placar da Revisão ao vivo
  // Cada linha decidida na hora (HTMX) desconta do “faltam”; no filtro “Precisa de atenção” ela sai da lista.
  function placar() { return document.querySelector("[data-placar]"); }
  function atualizarPlacar(delta) {
    var p = placar();
    if (!p) return;
    var total = parseInt(p.getAttribute("data-total"), 10) || 0;
    var restam = Math.max(0, (parseInt(p.getAttribute("data-restam"), 10) || 0) + delta);
    p.setAttribute("data-restam", restam);
    var prontas = total - restam;
    p.querySelectorAll("[data-restam-texto]").forEach(function (e) { e.textContent = restam.toLocaleString("pt-BR"); });
    p.querySelectorAll("[data-prontas-texto]").forEach(function (e) { e.textContent = prontas.toLocaleString("pt-BR"); });
    var barra = p.querySelector("[data-barra]");
    if (barra) barra.style.width = (total ? Math.round(100 * prontas / total) : 0) + "%";
    var fim = document.querySelector("[data-tudo-pronto]");
    if (restam === 0 && total > 0) {
      if (fim) fim.hidden = false;
      celebrarUmaVez(p.getAttribute("data-chave") || "revisao");
    } else if (fim) fim.hidden = true;
  }
  document.addEventListener("htmx:beforeSwap", function (evento) {
    var alvo = evento.detail.target;
    if (alvo && alvo.matches && alvo.matches("tr.linha-revisao")) evento.detail.xhr.zcmAntes = alvo.getAttribute("data-status");
  });
  document.addEventListener("htmx:afterSettle", function (evento) {
    var xhr = evento.detail.xhr, alvo = evento.detail.target;
    if (!xhr || !xhr.zcmAntes || !alvo || !alvo.id) return;
    var linha = document.getElementById(alvo.id);
    if (!linha) return;
    var antes = xhr.zcmAntes === "PENDENTE", agora = linha.getAttribute("data-status") === "PENDENTE";
    if (antes && !agora) {
      linha.classList.add("acabou-de-resolver");
      atualizarPlacar(-1);
      var p = placar();
      if (p && p.getAttribute("data-filtro") === "atencao") {
        setTimeout(function () { linha.classList.add("saindo"); }, 900);
        setTimeout(function () { linha.remove(); }, 1500);
      }
    } else if (!antes && agora) {
      atualizarPlacar(1);
    }
  });

  // ---------------------------------------------------------------- fio de ouro: a próxima tela está a caminho
  var ARQUIVO = /\.(txt|xlsx|xls|csv|ofx|pdf|dump|zip)$/i; // baixar arquivo não troca de tela
  var desligar = null;
  function navegando(ligado) {
    document.documentElement.classList.toggle("navegando", ligado);
    clearTimeout(desligar);
    if (ligado) desligar = setTimeout(function () { navegando(false); }, 20000); // nunca fica preso
  }
  document.addEventListener("click", function (evento) {
    if (evento.defaultPrevented || evento.button !== 0 || evento.ctrlKey || evento.metaKey || evento.shiftKey) return;
    var link = evento.target.closest("a[href]");
    if (!link || link.target || link.hasAttribute("download") || link.hasAttribute("hx-get")) return;
    var destino = new URL(link.href, location.href);
    if (destino.origin !== location.origin || ARQUIVO.test(destino.pathname)) return;
    if (destino.pathname === location.pathname && destino.search === location.search && destino.hash) return;
    navegando(true);
  });
  document.addEventListener("submit", function (evento) {
    var formulario = evento.target;
    if (!evento.defaultPrevented && !formulario.hasAttribute("hx-post") && !formulario.hasAttribute("hx-get")) navegando(true);
  });
  document.addEventListener("htmx:beforeRequest", function () { navegando(true); });
  document.addEventListener("htmx:afterRequest", function () { navegando(false); });
  window.addEventListener("pageshow", function () { navegando(false); }); // voltou pelo “Voltar” do navegador

  // ---------------------------------------------------------------- ao abrir a tela
  function iniciar() {
    prepararToasts();
    document.querySelectorAll("[data-contar]").forEach(contar);
    document.querySelectorAll("[data-celebrar]").forEach(function (e) { celebrarUmaVez(e.getAttribute("data-celebrar")); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
