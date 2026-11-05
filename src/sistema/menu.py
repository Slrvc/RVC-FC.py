"""Menu lateral agrupado por categoria, filtrado pelo que cada perfil acessa."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.urls import reverse

if TYPE_CHECKING:
    from django.http import HttpRequest

GRUPOS_DO_MENU: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Cadastros",
        (
            ("proprietarios", "Proprietários"),
            ("fazendas", "Fazendas"),
            ("fornecedores", "Fornecedores"),
            ("clientes", "Clientes"),
        ),
    ),
    (
        "Florestal",
        (
            ("plantios", "Plantios"),
            ("talhoes", "Talhões"),
            ("inventarios", "Inventários"),
            ("inventarios-talhao", "Inventário por talhão"),
            ("autorizacoes", "Autorizações"),
            ("colheitas", "Colheitas"),
        ),
    ),
    (
        "Produção",
        (
            ("ciclos-forno", "Ciclos de forno"),
            ("fornos", "Fornos"),
            ("tipos-forno", "Tipos de forno"),
            ("boxes-lenha", "Box de lenha"),
            ("upcs", "UPCs"),
        ),
    ),
    (
        "Transporte e vendas",
        (
            ("transportes-lenha", "Transporte de lenha"),
            ("expedicoes", "Expedições de carvão"),
        ),
    ),
    (
        "Custos",
        (
            ("lancamentos-custo", "Lançamentos de custo"),
            ("rateios-custo", "Rateios de custo"),
            ("centros-custo", "Centros de custo"),
            ("categorias-custo", "Categorias de custo"),
            ("equipamentos", "Equipamentos"),
        ),
    ),
    (
        "Configurações",
        (
            ("empresas", "Empresas e filiais"),
            ("usuarios", "Usuários"),
            ("parametros-producao", "Parâmetros de produção"),
            ("parametros", "Parâmetros do terminal"),
            ("estados", "Estados"),
            ("municipios-ibge", "Municípios IBGE"),
        ),
    ),
)


def montar_menu(request: HttpRequest) -> list[dict[str, object]]:
    from sistema.views import usuario_pode_acessar

    usuario = request.user
    if getattr(usuario, "primeiro_acesso", True):
        return []
    match = request.resolver_match
    atual = match.kwargs.get("recurso") if match else None
    grupos = []
    for titulo, itens in GRUPOS_DO_MENU:
        links = [
            {
                "titulo": rotulo,
                "url": reverse("lista_registros", args=[recurso]),
                "ativo": recurso == atual,
            }
            for recurso, rotulo in itens
            if usuario_pode_acessar(usuario, recurso)
        ]
        if links:
            grupos.append(
                {
                    "titulo": titulo,
                    "itens": links,
                    "aberto": any(link["ativo"] for link in links),
                }
            )
    return grupos
