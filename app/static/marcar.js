// Revisão: caixinhas para decidir várias linhas de uma vez (form="form-lote").
// "Marcar todas" liga/desliga as caixinhas visíveis; o contador mostra quantas estão marcadas.
// Sem JavaScript as caixinhas continuam funcionando, uma a uma.
function contarMarcadas() {
  var total = document.querySelectorAll('input[name="ids"][form="form-lote"]:checked').length;
  document.querySelectorAll("[data-marcadas]").forEach(function (contador) { contador.textContent = total; });
}

document.addEventListener("change", function (evento) {
  var alvo = evento.target;
  if (!alvo.matches) return;
  if (alvo.matches("[data-marcar-todas]")) {
    document.querySelectorAll('input[name="ids"][form="form-lote"]').forEach(function (caixa) {
      caixa.checked = alvo.checked;
    });
  }
  if (alvo.matches('[data-marcar-todas], input[name="ids"]')) contarMarcadas();
});

document.addEventListener("htmx:afterSwap", contarMarcadas); // a linha trocada volta desmarcada
