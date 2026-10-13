// Formulários com data-arrastar: soltar arquivos na zona (ou em qualquer lugar da página) já envia.
document.addEventListener("DOMContentLoaded", function () {
  var formulario = document.querySelector("form[data-arrastar]");
  if (!formulario) return;
  var entrada = formulario.querySelector("input[type=file]");
  var zona = formulario.querySelector(".zona-arquivos") || formulario;

  function marcar(ligado) { zona.classList.toggle("arrastando", ligado); }

  ["dragenter", "dragover"].forEach(function (nome) {
    document.addEventListener(nome, function (evento) {
      if (!evento.dataTransfer || Array.prototype.indexOf.call(evento.dataTransfer.types, "Files") < 0) return;
      evento.preventDefault();
      marcar(true);
    });
  });
  document.addEventListener("dragleave", function (evento) {
    if (!evento.relatedTarget) marcar(false);
  });
  document.addEventListener("drop", function (evento) {
    if (!evento.dataTransfer || !evento.dataTransfer.files.length) return;
    evento.preventDefault();
    marcar(false);
    entrada.files = evento.dataTransfer.files;
    formulario.requestSubmit();
  });
  entrada.addEventListener("change", function () {
    if (entrada.files.length) formulario.requestSubmit();
  });
});
// Formulários com data-enviar-ao-escolher: escolher o arquivo já envia (sem o botão nativo “Escolher arquivo”).
document.addEventListener("change", function (evento) {
  var campo = evento.target;
  if (!campo.matches || !campo.matches("input[type=file]") || !campo.files.length) return;
  var formulario = campo.form;
  if (!formulario || !formulario.hasAttribute("data-enviar-ao-escolher")) return;
  var rotulo = campo.closest("label");
  if (rotulo) rotulo.classList.add("enviando");
  document.documentElement.classList.add("navegando");
  formulario.requestSubmit();
});
