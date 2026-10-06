// Formulários com data-aguarde="texto": enquanto o servidor trabalha (importação, IA),
// o botão fica desligado mostrando o texto — evita clique duplo e mostra que está andando.
document.addEventListener("submit", function (evento) {
  var formulario = evento.target;
  var texto = formulario.getAttribute && formulario.getAttribute("data-aguarde");
  if (!texto) return;
  var botao = formulario.querySelector("button[type=submit], button:not([type])");
  if (!botao) return;
  botao.setAttribute("aria-busy", "true");
  botao.textContent = texto;
  setTimeout(function () { botao.disabled = true; }, 0); // depois do envio, para não cancelá-lo
});
