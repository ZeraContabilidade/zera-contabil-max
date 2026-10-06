// Botão ◐: alterna tema claro/escuro e lembra a escolha neste navegador.
document.addEventListener("click", function (evento) {
  var botao = evento.target.closest("[data-alternar-tema]");
  if (!botao) return;
  var raiz = document.documentElement;
  var atual = raiz.getAttribute("data-theme") ||
    (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  var novo = atual === "light" ? "dark" : "light";
  raiz.setAttribute("data-theme", novo);
  try { localStorage.setItem("zcm-tema", novo); } catch (erro) { /* navegador sem armazenamento */ }
});
