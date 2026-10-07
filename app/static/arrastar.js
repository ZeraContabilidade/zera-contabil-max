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
