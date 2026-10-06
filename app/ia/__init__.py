"""Inteligência artificial (API da Anthropic), isolada do resto do sistema.

Quem usa a IA monta um `PedidoIA` e chama `app.ia.servico.chamar_ia`; nunca fala com o SDK direto.
Nos testes, o `ClienteFalso` responde no lugar da API (sem internet e sem custo).
"""
