// Revisão pelo teclado: J/K (ou ↓/↑) andam entre as linhas, Enter (ou E) vai para a conta, A aprova, I ignora,
// X marca a caixinha. Depois de cada decisão o foco passa sozinho para a linha seguinte; Esc sai do campo.
// Com o mouse, clicar numa linha também a escolhe. Sem JavaScript a grade funciona igual, clique a clique.
(function () {
  "use strict";
  var tabela = document.querySelector(".tabela-revisao");
  if (!tabela) return;
  var calmo = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var focoId = null;

  function linhas() { return Array.prototype.slice.call(tabela.querySelectorAll("tr.linha-revisao:not(.saindo)")); }
  function atual() { return focoId ? document.getElementById(focoId) : null; }
  function digitando(alvo) { return alvo && (alvo.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName)); }
  function janelaAberta() { return !!document.querySelector("dialog[open]"); }

  function focar(linha, rolar) {
    var antes = atual();
    if (antes) antes.classList.remove("linha-foco");
    focoId = linha ? linha.id : null;
    if (!linha) return;
    linha.classList.add("linha-foco");
    if (rolar) linha.scrollIntoView({ block: "nearest", behavior: calmo ? "auto" : "smooth" });
  }
  function vizinha(linha, passo) {
    var todas = linhas();
    var i = todas.indexOf(linha);
    if (i < 0) return todas[0] || null;
    return todas[Math.max(0, Math.min(todas.length - 1, i + passo))];
  }
  function seguinte(linha) { // a próxima linha ainda por decidir (senão, simplesmente a próxima)
    var todas = linhas(), i = todas.indexOf(linha);
    for (var n = i + 1; n < todas.length; n++) if (todas[n].getAttribute("data-status") === "PENDENTE") return todas[n];
    return todas[i + 1] || linha;
  }
  function recusar(linha) { // a ação não existe nesta linha (ex.: aprovar sem conta sugerida)
    linha.classList.remove("nao-pode");
    void linha.offsetWidth;
    linha.classList.add("nao-pode");
  }
  function decidir(acao) {
    var linha = atual();
    if (!linha) return;
    var botao = linha.querySelector('button[name="acao"][value="' + acao + '"]');
    if (!botao) { recusar(linha); return; }
    var proxima = seguinte(linha);
    botao.click();
    focar(proxima, true);
  }
  function irParaConta() {
    var linha = atual();
    var campo = linha && linha.querySelector('input[name="conta"]');
    if (campo) { campo.focus(); campo.select(); }
  }

  // começa na primeira linha que precisa de decisão (sem tirar o cursor de onde estiver)
  focar(tabela.querySelector('tr.linha-revisao[data-status="PENDENTE"]') || linhas()[0], false);

  tabela.addEventListener("click", function (evento) {
    var linha = evento.target.closest("tr.linha-revisao");
    if (linha && linha.id !== focoId) focar(linha, false);
  });
  tabela.addEventListener("focusin", function (evento) {
    var linha = evento.target.closest("tr.linha-revisao");
    if (linha && linha.id !== focoId) focar(linha, false);
  });
  // Enter no campo da conta grava (Salvar): o foco segue para a próxima linha
  tabela.addEventListener("submit", function (evento) {
    var linha = evento.target.closest("tr.linha-revisao");
    if (linha && evento.target.classList.contains("form-revisao") && linha.id === focoId) focar(seguinte(linha), true);
  }, true);
  // a linha voltou com erro (ex.: conta que não existe): volta para ela, no campo da conta
  document.addEventListener("htmx:afterSettle", function (evento) {
    var alvo = evento.detail.target;
    var linha = alvo && alvo.id ? document.getElementById(alvo.id) : null;
    if (linha && linha.querySelector(".erro-linha")) { focar(linha, true); irParaConta(); }
    else if (linha && linha.id === focoId) linha.classList.add("linha-foco");
  });

  document.addEventListener("keydown", function (evento) {
    if (evento.ctrlKey || evento.metaKey || evento.altKey || janelaAberta()) return;
    if (digitando(evento.target)) {
      if (evento.key === "Escape" && evento.target.closest("tr.linha-revisao")) { evento.target.blur(); }
      return;
    }
    var tecla = evento.key.toLowerCase();
    if ((tecla === "enter" || tecla === " ") && /^(A|BUTTON|SUMMARY)$/.test(evento.target.tagName)) return; // botão/link em foco: Enter é dele
    var acoes = { j: 1, arrowdown: 1, k: -1, arrowup: -1 };
    if (tecla in acoes) { evento.preventDefault(); focar(vizinha(atual(), acoes[tecla]), true); }
    else if (tecla === "enter" || tecla === "e") { if (atual()) { evento.preventDefault(); irParaConta(); } }
    else if (tecla === "a") { evento.preventDefault(); decidir("aprovar"); }
    else if (tecla === "i") { evento.preventDefault(); decidir("ignorar"); }
    else if (tecla === "x" || tecla === " ") {
      var caixa = atual() && atual().querySelector('input[name="ids"]');
      if (caixa) { evento.preventDefault(); caixa.click(); }
    }
  });
})();
