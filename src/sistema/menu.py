"""Menu lateral em seções recolhíveis, com subseções e ícones.

Cada seção (Florestal, Produção...) separa Cadastros, Lançamentos e
Relatórios. Só aparecem as telas que o perfil do usuário acessa.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.urls import reverse

if TYPE_CHECKING:
    from django.http import HttpRequest

# Item: (chave, rótulo, ícone). Chave com "@" é uma tela que não é lista de
# cadastro; o acesso a ela segue o recurso indicado em TELAS_DO_MENU.
Item = tuple[str, str, str]
Subsecao = tuple[str, tuple[Item, ...]]
SECOES_DO_MENU: tuple[tuple[str, str, str, tuple[Subsecao, ...]], ...] = (
    (
        "florestal",
        "Florestal",
        "arvore",
        (
            (
                "Cadastros",
                (
                    ("proprietarios", "Proprietários", "pessoa"),
                    ("fazendas", "Fazendas", "fazenda"),
                    ("plantios", "Plantios", "broto"),
                    ("talhoes", "Talhões", "mapa"),
                ),
            ),
            (
                "Lançamentos",
                (
                    ("inventarios", "Inventários", "prancheta"),
                    ("inventarios-talhao", "Inventário por talhão", "linhas"),
                    ("autorizacoes", "Autorizações", "escudo"),
                    ("colheitas", "Colheitas", "machado"),
                ),
            ),
            (
                "Relatórios",
                (("@consolidado_colheita", "Consolidado da colheita", "tabela"),),
            ),
        ),
    ),
    (
        "producao",
        "Produção",
        "chama",
        (
            (
                "Cadastros",
                (
                    ("upcs", "UPCs", "fabrica"),
                    ("tipos-forno", "Tipos de forno", "camadas"),
                    ("fornos", "Fornos", "forno"),
                    ("boxes-lenha", "Box de lenha", "toras"),
                ),
            ),
            (
                "Lançamentos",
                (
                    ("ciclos-forno", "Ciclos de forno", "ciclo"),
                    ("planejamentos-forno", "Planejamento dos fornos", "calendario"),
                ),
            ),
            (
                "Relatórios",
                (("@painel_fornos", "Painel dos fornos", "grafico"),),
            ),
        ),
    ),
    (
        "transporte",
        "Transporte e vendas",
        "caminhao",
        (
            (
                "Cadastros",
                (
                    ("clientes", "Clientes", "loja"),
                    ("fornecedores", "Fornecedores", "caixa"),
                    ("tarifas-fornecedor", "Tarifas de fornecedor", "etiqueta"),
                ),
            ),
            (
                "Lançamentos",
                (
                    ("transportes-lenha", "Transporte de lenha", "caminhao"),
                    ("expedicoes", "Expedições de carvão", "enviar"),
                ),
            ),
        ),
    ),
    (
        "custos",
        "Custos",
        "moeda",
        (
            (
                "Cadastros",
                (
                    ("centros-custo", "Centros de custo", "alvo"),
                    ("categorias-custo", "Categorias de custo", "categorias"),
                    ("equipamentos", "Equipamentos", "chave-inglesa"),
                ),
            ),
            (
                "Lançamentos",
                (
                    ("lancamentos-custo", "Lançamentos de custo", "moeda"),
                    ("rateios-custo", "Rateios de custo", "percentual"),
                ),
            ),
        ),
    ),
    (
        "configuracoes",
        "Configurações",
        "engrenagem",
        (
            (
                "Acesso",
                (
                    ("empresas", "Empresas e filiais", "predio"),
                    ("usuarios", "Usuários", "pessoas"),
                ),
            ),
            (
                "Parâmetros",
                (
                    ("parametros-producao", "Parâmetros de produção", "medidor"),
                    ("parametros", "Parâmetros do sistema", "ajustes"),
                ),
            ),
            (
                "Tabelas",
                (
                    ("estados", "Estados", "pino"),
                    ("municipios-ibge", "Municípios IBGE", "cerquilha"),
                ),
            ),
        ),
    ),
)
TELAS_DO_MENU = {
    "@painel_fornos": "ciclos-forno",
    "@consolidado_colheita": "colheitas",
}


def _item(chave: str, rotulo: str, icone: str, usuario, atual, nome_url) -> dict | None:
    from sistema.views import usuario_pode_acessar

    if chave in TELAS_DO_MENU:
        if not usuario_pode_acessar(usuario, TELAS_DO_MENU[chave]):
            return None
        url, ativo = reverse(chave[1:]), nome_url == chave[1:]
    else:
        if not usuario_pode_acessar(usuario, chave):
            return None
        url, ativo = reverse("lista_registros", args=[chave]), chave == atual
    return {"titulo": rotulo, "url": url, "ativo": ativo, "icone": icone}


def montar_menu(request: HttpRequest) -> list[dict[str, object]]:
    usuario = request.user
    if getattr(usuario, "primeiro_acesso", True):
        return []
    match = request.resolver_match
    atual = match.kwargs.get("recurso") if match else None
    nome_url = match.url_name if match else None
    secoes = []
    for chave, titulo, icone, subsecoes in SECOES_DO_MENU:
        partes = []
        for subtitulo, itens in subsecoes:
            links = [
                link
                for item in itens
                if (link := _item(*item, usuario, atual, nome_url)) is not None
            ]
            if links:
                partes.append({"titulo": subtitulo, "itens": links})
        if partes:
            secoes.append(
                {
                    "chave": chave,
                    "titulo": titulo,
                    "icone": icone,
                    "subsecoes": partes,
                    "ativa": any(
                        link["ativo"] for parte in partes for link in parte["itens"]
                    ),
                }
            )
    return secoes


def local_no_menu(chave: str) -> str:
    """Seção e subseção do menu onde a tela fica (ex.: Produção · Lançamentos)."""
    for _, titulo, _, subsecoes in SECOES_DO_MENU:
        for subtitulo, itens in subsecoes:
            if any(item[0] == chave for item in itens):
                return f"{titulo} · {subtitulo}"
    return ""
