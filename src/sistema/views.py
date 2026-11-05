from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Model, ProtectedError, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme, urlencode

from sistema.contexto import (
    definir_empresa_ativa,
    definir_upc_ativa,
    empresa_ativa,
    upc_ativa,
    usa_contexto_de_upc,
)
from sistema.forms import (
    AutorizacaoAmbientalForm,
    AutorizacaoAmbientalGestorForm,
    BoxLenhaForm,
    BoxLenhaGestorForm,
    CategoriaCustoForm,
    CategoriaCustoGestorForm,
    CentroCustoForm,
    CentroCustoGestorForm,
    CicloFornoForm,
    CicloFornoGestorForm,
    ClienteForm,
    ClienteGestorForm,
    ColheitaForm,
    ColheitaGestorForm,
    ContextoEmpresaForm,
    ContextoUPCForm,
    EmpresaForm,
    EquipamentoForm,
    EquipamentoGestorForm,
    ExpedicaoForm,
    ExpedicaoGestorForm,
    FazendaForm,
    FazendaGestorForm,
    FornecedorForm,
    FornecedorGestorForm,
    FornoForm,
    FornoGestorForm,
    InventarioFlorestalForm,
    InventarioFlorestalGestorForm,
    InventarioTalhaoForm,
    InventarioTalhaoGestorForm,
    LancamentoCustoForm,
    LancamentoCustoGestorForm,
    LancamentoCustoRateioForm,
    LancamentoCustoRateioGestorForm,
    ParametroEmpresaForm,
    ParametroEmpresaGestorForm,
    ParametrosForm,
    PlantioForm,
    PlantioGestorForm,
    ProprietarioForm,
    ProprietarioGestorForm,
    TalhaoForm,
    TalhaoGestorForm,
    TipoFornoForm,
    TipoFornoGestorForm,
    TransporteLenhaForm,
    TransporteLenhaGestorForm,
    UPCForm,
    UPCGestorForm,
    UsuarioForm,
)
from sistema.models import (
    UPC,
    AutorizacaoAmbiental,
    BoxLenha,
    CategoriaCusto,
    CentroCusto,
    CicloForno,
    Cliente,
    Colheita,
    Empresa,
    Equipamento,
    Estado,
    Expedicao,
    Fazenda,
    Fornecedor,
    Forno,
    InventarioFlorestal,
    InventarioTalhao,
    LancamentoCusto,
    LancamentoCustoRateio,
    Municipio,
    ParametroEmpresa,
    Parametros,
    Plantio,
    Proprietario,
    RegistroAuditavel,
    Talhao,
    TipoForno,
    TipoUsuario,
    TransporteLenha,
    Usuario,
)

if TYPE_CHECKING:
    from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
    from django.db.models import QuerySet
    from django.forms import ModelForm
    from django.http import HttpRequest, HttpResponse

MODELOS_POR_EMPRESA = (
    Fazenda,
    Proprietario,
    Fornecedor,
    Plantio,
    Talhao,
    UPC,
    InventarioFlorestal,
    InventarioTalhao,
    AutorizacaoAmbiental,
    Expedicao,
    TransporteLenha,
    Colheita,
    CentroCusto,
    CategoriaCusto,
    Equipamento,
    Cliente,
    ParametroEmpresa,
    TipoForno,
    Forno,
    BoxLenha,
    CicloForno,
    LancamentoCusto,
    LancamentoCustoRateio,
)
FORMULARIOS_DO_GESTOR = {
    LancamentoCusto: LancamentoCustoGestorForm,
    LancamentoCustoRateio: LancamentoCustoRateioGestorForm,
    ParametroEmpresa: ParametroEmpresaGestorForm,
    TipoForno: TipoFornoGestorForm,
    Forno: FornoGestorForm,
    BoxLenha: BoxLenhaGestorForm,
    CicloForno: CicloFornoGestorForm,
    CentroCusto: CentroCustoGestorForm,
    CategoriaCusto: CategoriaCustoGestorForm,
    Equipamento: EquipamentoGestorForm,
    Cliente: ClienteGestorForm,
    Colheita: ColheitaGestorForm,
    TransporteLenha: TransporteLenhaGestorForm,
    Expedicao: ExpedicaoGestorForm,
    AutorizacaoAmbiental: AutorizacaoAmbientalGestorForm,
    InventarioFlorestal: InventarioFlorestalGestorForm,
    InventarioTalhao: InventarioTalhaoGestorForm,
    Fazenda: FazendaGestorForm,
    Proprietario: ProprietarioGestorForm,
    Fornecedor: FornecedorGestorForm,
    Plantio: PlantioGestorForm,
    Talhao: TalhaoGestorForm,
    UPC: UPCGestorForm,
}
ATALHOS_DE_CADASTRO = {
    "empresa": "empresas",
    "fazenda": "fazendas",
    "proprietario": "proprietarios",
    "fornecedor": "fornecedores",
    "plantio": "plantios",
    "talhao": "talhoes",
    "upc": "upcs",
    "inventario": "inventarios",
    "autorizacao": "autorizacoes",
    "colheita": "colheitas",
    "expedicao": "expedicoes",
    "centro_custo": "centros-custo",
    "lancamento": "lancamentos-custo",
    "categoria_pai": "categorias-custo",
    "tipo_forno": "tipos-forno",
    "forno": "fornos",
    "box_lenha": "boxes-lenha",
}
FILTROS_POR_UPC = {
    InventarioFlorestal: lambda upcs: Q(fazenda__upcs__in=upcs),
    InventarioTalhao: lambda upcs: Q(inventario__fazenda__upcs__in=upcs),
    AutorizacaoAmbiental: lambda upcs: Q(upcs__in=upcs),
    Expedicao: lambda upcs: Q(autorizacao__upcs__in=upcs),
    TransporteLenha: lambda upcs: Q(upc__in=upcs) | Q(autorizacao__upcs__in=upcs),
    Colheita: lambda upcs: Q(inventario__fazenda__upcs__in=upcs),
    Forno: lambda upcs: Q(upc__in=upcs),
    BoxLenha: lambda upcs: Q(upc__in=upcs),
    CicloForno: lambda upcs: Q(forno__upc__in=upcs),
}


RECURSOS: dict[str, dict[str, Any]] = {
    "lancamentos-custo": {
        "titulo": "Lançamentos de custo",
        "modelo": LancamentoCusto,
        "formulario": LancamentoCustoForm,
        "colunas": [
            ("Data", "data_lancamento"),
            ("Competência", "competencia"),
            ("Descrição", "descricao"),
            ("Centro", "centro_custo"),
            ("Categoria", "categoria"),
            ("Valor", "valor_total"),
            ("Pagamento", "situacao_pagamento"),
            ("Rateado (%)", "percentual_rateado"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "descricao",
            "numero_documento",
            "centro_custo__nome",
            "categoria__nome",
            "fornecedor__nome_razao_social",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "rateios-custo": {
        "titulo": "Rateios de custo",
        "modelo": LancamentoCustoRateio,
        "formulario": LancamentoCustoRateioForm,
        "colunas": [
            ("Lançamento", "lancamento"),
            ("Centro", "centro_custo"),
            ("Percentual (%)", "percentual"),
            ("Valor", "valor"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "lancamento__descricao",
            "centro_custo__nome",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "parametros-producao": {
        "titulo": "Parâmetros de produção",
        "modelo": ParametroEmpresa,
        "formulario": ParametroEmpresaForm,
        "colunas": [
            ("MST por m³", "fator_mst_por_m3"),
            ("m³ por MDC (ideal)", "fator_m3_por_mdc_ideal"),
            ("MST por MDC (ideal)", "fator_mst_por_mdc_ideal"),
            ("Tolerância (%)", "tolerancia_efetiva_pct"),
            ("Estoque no talhão", "get_controle_estoque_talhao_display"),
            ("Empresa", "empresa"),
        ],
        "busca": ["empresa__razao_social"],
        "somente_admin": False,
    },
    "tipos-forno": {
        "titulo": "Tipos de forno",
        "modelo": TipoForno,
        "formulario": TipoFornoForm,
        "colunas": [
            ("Nome", "nome"),
            ("Formato", "get_formato_display"),
            ("Mecanização", "get_nivel_mecanizacao_display"),
            ("MDC por ciclo", "capacidade_mdc"),
            ("Empresa", "empresa"),
        ],
        "busca": ["nome", "empresa__razao_social"],
        "somente_admin": False,
    },
    "fornos": {
        "titulo": "Fornos",
        "modelo": Forno,
        "formulario": FornoForm,
        "colunas": [
            ("UPC", "upc"),
            ("Forno", "numero"),
            ("Tipo", "tipo_forno"),
            ("MDC por ciclo", "capacidade_efetiva_mdc"),
            ("Situação", "get_situacao_display"),
            ("Empresa", "empresa"),
        ],
        "busca": ["numero", "upc__nome", "tipo_forno__nome", "empresa__razao_social"],
        "somente_admin": False,
    },
    "boxes-lenha": {
        "titulo": "Box de lenha",
        "modelo": BoxLenha,
        "formulario": BoxLenhaForm,
        "colunas": [
            ("UPC", "upc"),
            ("Box", "numero"),
            ("Descrição", "descricao"),
            ("Capacidade (MST)", "capacidade_mst"),
            ("Estoque estimado (MST)", "estoque_mst"),
            ("Situação", "get_situacao_display"),
            ("Empresa", "empresa"),
        ],
        "busca": ["numero", "descricao", "upc__nome", "empresa__razao_social"],
        "somente_admin": False,
    },
    "ciclos-forno": {
        "titulo": "Ciclos de forno",
        "modelo": CicloForno,
        "formulario": CicloFornoForm,
        "colunas": [
            ("Forno", "forno"),
            ("Ciclo", "numero_ciclo"),
            ("Status", "get_status_display"),
            ("Enchimento", "data_inicio_enchimento"),
            ("Descarga", "data_descarga"),
            ("Lenha (MST)", "volume_lenha_enchimento"),
            ("Carvão (MDC)", "volume_mdc"),
            ("MST/MDC", "fator_mst_por_mdc"),
            ("Alerta", "alerta_fator"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "forno__numero",
            "forno__upc__nome",
            "fornecedor__nome_razao_social",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "centros-custo": {
        "titulo": "Centros de custo",
        "modelo": CentroCusto,
        "formulario": CentroCustoForm,
        "colunas": [
            ("Nome", "nome"),
            ("Tipo", "get_tipo_display"),
            ("UPC", "upc"),
            ("Empresa", "empresa"),
        ],
        "busca": ["nome", "upc__nome", "empresa__razao_social"],
        "somente_admin": False,
    },
    "categorias-custo": {
        "titulo": "Categorias de custo",
        "modelo": CategoriaCusto,
        "formulario": CategoriaCustoForm,
        "colunas": [
            ("Nome", "nome"),
            ("Grupo", "get_grupo_display"),
            ("Tipo", "get_tipo_custo_display"),
            ("Categoria superior", "categoria_pai"),
            ("Empresa", "empresa"),
        ],
        "busca": ["nome", "categoria_pai__nome", "empresa__razao_social"],
        "somente_admin": False,
    },
    "equipamentos": {
        "titulo": "Equipamentos",
        "modelo": Equipamento,
        "formulario": EquipamentoForm,
        "colunas": [
            ("Descrição", "descricao"),
            ("Tipo", "get_tipo_display"),
            ("Placa", "placa"),
            ("Propriedade", "get_propriedade_display"),
            ("Centro de custo", "centro_custo"),
            ("Empresa", "empresa"),
        ],
        "busca": ["descricao", "placa", "empresa__razao_social"],
        "somente_admin": False,
    },
    "clientes": {
        "titulo": "Clientes",
        "modelo": Cliente,
        "formulario": ClienteForm,
        "colunas": [
            ("Nome", "nome_razao_social"),
            ("Documento", "cpf_cnpj"),
            ("Município", "municipio"),
            ("Empresa", "empresa"),
        ],
        "busca": ["nome_razao_social", "cpf_cnpj", "empresa__razao_social"],
        "somente_admin": False,
    },
    "empresas": {
        "titulo": "Empresas",
        "modelo": Empresa,
        "formulario": EmpresaForm,
        "colunas": [
            ("Código", "codigo"),
            ("CNPJ", "cnpj"),
            ("Razão social", "razao_social"),
            ("Tipo", "tipo_exibicao"),
            ("Município", "municipio"),
        ],
        "busca": [
            "descricao_filial",
            "cnpj",
            "razao_social",
            "nome_fantasia",
            "municipio__nome",
            "municipio__codigo",
        ],
        "somente_admin": True,
    },
    "usuarios": {
        "titulo": "Usuários",
        "modelo": Usuario,
        "formulario": UsuarioForm,
        "colunas": [
            ("Usuário", "username"),
            ("Nome", "nome_completo"),
            ("Empresa", "empresa"),
            ("E-mail", "email"),
            ("Ativo", "is_active"),
        ],
        "busca": ["username", "nome_completo", "email", "empresa__razao_social"],
        "somente_admin": True,
    },
    "fazendas": {
        "titulo": "Fazendas",
        "modelo": Fazenda,
        "formulario": FazendaForm,
        "colunas": [
            ("Nome", "nome"),
            ("Proprietário", "proprietario"),
            ("Área (ha)", "area_total_ha"),
            ("Empresa", "empresa"),
            ("Município", "municipio"),
        ],
        "busca": [
            "nome",
            "proprietario__nome_razao_social",
            "numero_car",
            "municipio__nome",
            "municipio__codigo",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "proprietarios": {
        "titulo": "Proprietários",
        "modelo": Proprietario,
        "formulario": ProprietarioForm,
        "colunas": [
            ("Nome", "nome_razao_social"),
            ("Documento", "cpf_cnpj"),
            ("Empresa", "empresa"),
            ("Município", "municipio"),
        ],
        "busca": ["nome_razao_social", "cpf_cnpj", "empresa__razao_social"],
        "somente_admin": False,
    },
    "fornecedores": {
        "titulo": "Fornecedores",
        "modelo": Fornecedor,
        "formulario": FornecedorForm,
        "colunas": [
            ("Nome", "nome_razao_social"),
            ("Documento", "cpf_cnpj"),
            ("Fornece", "tipos"),
            ("Empresa", "empresa"),
            ("Município", "municipio"),
        ],
        "busca": [
            "nome_razao_social",
            "cpf_cnpj",
            "registro_conselho",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "plantios": {
        "titulo": "Plantios",
        "modelo": Plantio,
        "formulario": PlantioForm,
        "colunas": [
            ("Fazenda", "fazenda"),
            ("Espécie", "especie"),
            ("Área (ha)", "area_ha"),
            ("Idade (anos)", "idade_anos"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "especie",
            "fazenda__nome",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "talhoes": {
        "titulo": "Talhões",
        "modelo": Talhao,
        "formulario": TalhaoForm,
        "colunas": [
            ("Talhão", "identificacao"),
            ("Fazenda", "fazenda"),
            ("Plantio", "plantio"),
            ("Área (ha)", "area_ha"),
            ("Volume (m³)", "volume_m3"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "identificacao",
            "fazenda__nome",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "upcs": {
        "titulo": "UPCs",
        "modelo": UPC,
        "formulario": UPCForm,
        "colunas": [
            ("UPC", "nome"),
            ("Fazenda", "fazenda"),
            ("Fornos", "numero_fornos"),
            ("Volume/mês (MDC)", "volume_mes_mdc"),
            ("Empresa", "empresa"),
        ],
        "busca": ["nome", "fazenda__nome", "empresa__razao_social"],
        "somente_admin": False,
    },
    "inventarios": {
        "titulo": "Inventários",
        "modelo": InventarioFlorestal,
        "formulario": InventarioFlorestalForm,
        "colunas": [
            ("Fazenda", "fazenda"),
            ("Lote", "lote"),
            ("Data", "data_inventario"),
            ("Área (ha)", "area_ha"),
            ("Volume (m³)", "volume_total"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "lote",
            "fazenda__nome",
            "numero_art",
            "responsavel_tecnico",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "inventarios-talhao": {
        "titulo": "Inventário por talhão",
        "modelo": InventarioTalhao,
        "formulario": InventarioTalhaoForm,
        "colunas": [
            ("Inventário", "inventario"),
            ("Talhão", "talhao"),
            ("Área (ha)", "area_ha"),
            ("Volume (m³)", "volume_total"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "inventario__lote",
            "inventario__fazenda__nome",
            "talhao__identificacao",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "autorizacoes": {
        "titulo": "Autorizações",
        "modelo": AutorizacaoAmbiental,
        "formulario": AutorizacaoAmbientalForm,
        "colunas": [
            ("Número", "numero"),
            ("UPC(s)", "lista_upcs"),
            ("Tipo", "tipo_documento"),
            ("Produto", "produto"),
            ("Volume", "volume_declarado"),
            ("Vencimento", "data_vencimento"),
            ("Saldo", "saldo"),
            ("Status", "status"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "numero",
            "fazenda__nome",
            "upcs__nome",
            "numero_dae_expediente",
            "numero_dae_florestal",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "colheitas": {
        "titulo": "Colheitas",
        "modelo": Colheita,
        "formulario": ColheitaForm,
        "colunas": [
            ("Início", "data_inicio"),
            ("Fim", "data_fim"),
            ("Inventário", "inventario"),
            ("Sistema", "get_sistema_display"),
            ("Equipamentos", "lista_equipamentos"),
            ("Talhão", "talhao"),
            ("Área (ha)", "area_ha"),
            ("Estoque em campo (m³)", "estoque_em_campo"),
            ("Volume do inventário (m³)", "volume_inventario"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "inventario__lote",
            "inventario__fazenda__nome",
            "talhao__identificacao",
            "autorizacao__numero",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "transportes-lenha": {
        "titulo": "Transporte de lenha",
        "modelo": TransporteLenha,
        "formulario": TransporteLenhaForm,
        "colunas": [
            ("Data", "data_transporte"),
            ("Talhão", "talhao"),
            ("Destino", "destino"),
            ("Volume (MST)", "volume_mst"),
            ("Volume (m³)", "volume_m3"),
            ("Custo (R$)", "valor_total"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "numero_documento",
            "placa_veiculo",
            "motorista",
            "talhao__identificacao",
            "autorizacao__numero",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "expedicoes": {
        "titulo": "Expedições de carvão",
        "modelo": Expedicao,
        "formulario": ExpedicaoForm,
        "colunas": [
            ("Documento", "numero_documento"),
            ("Autorização", "autorizacao"),
            ("Data", "data_expedicao"),
            ("Cliente", "cliente"),
            ("Expedido", "volume_expedido"),
            ("Aferido", "volume_aferido"),
            ("Status", "status"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "numero_documento",
            "autorizacao__numero",
            "cliente",
            "placa_veiculo",
            "empresa__razao_social",
        ],
        "somente_admin": False,
    },
    "parametros": {
        "titulo": "Parâmetros",
        "modelo": Parametros,
        "formulario": ParametrosForm,
        "colunas": [
            ("Empresa", "empresa"),
            ("Terminal", "terminal"),
            ("Idioma", "get_idioma_display"),
            ("Moeda", "simbolo_monetario"),
        ],
        "busca": ["empresa__razao_social", "terminal"],
        "somente_admin": True,
    },
    "estados": {
        "titulo": "Estados",
        "modelo": Estado,
        "formulario": None,
        "colunas": [("Código", "codigo"), ("UF", "uf")],
        "busca": ["uf"],
        "somente_admin": True,
        "somente_leitura": True,
    },
    "municipios-ibge": {
        "titulo": "Municípios IBGE",
        "modelo": Municipio,
        "formulario": None,
        "colunas": [
            ("Código IBGE", "codigo"),
            ("Município", "nome"),
            ("UF", "estado"),
        ],
        "busca": ["codigo", "nome", "estado__uf"],
        "somente_admin": True,
        "somente_leitura": True,
    },
}


def eh_administrador(usuario: Usuario) -> bool:
    return usuario.eh_administrador


def usuarios_visiveis(usuario: Usuario) -> QuerySet[Usuario]:
    """Superusuário vê todos; o administrador, só os usuários da sua matriz."""
    if usuario.is_superuser:
        return Usuario.objects.all()
    if usuario.matriz_id is None:
        return Usuario.objects.none()
    return Usuario.objects.filter(matriz_id=usuario.matriz_id, is_superuser=False)


def usuario_autenticado(request: HttpRequest) -> Usuario:
    usuario = request.user
    if not isinstance(usuario, Usuario):
        raise PermissionDenied
    return usuario


def restringir_por_upc(
    queryset: QuerySet[Model], request: HttpRequest
) -> QuerySet[Model]:
    """Limita o gestor à UPC ativa (ou às UPCs vinculadas, se não houver ativa)."""
    usuario = usuario_autenticado(request)
    filtro = FILTROS_POR_UPC.get(queryset.model)
    if filtro is None or eh_administrador(usuario):
        return queryset
    ativa = upc_ativa(request)
    if ativa is not None:
        return queryset.filter(filtro(UPC.objects.filter(pk=ativa.pk)))
    if usuario.upcs.exists():
        return queryset.filter(filtro(usuario.upcs.all()))
    return queryset


def upcs_visiveis(request: HttpRequest) -> QuerySet[UPC]:
    ativa = upc_ativa(request)
    if ativa is not None:
        return UPC.objects.filter(pk=ativa.pk)
    empresa = empresa_ativa(request)
    if empresa is None:
        return UPC.objects.none()
    return usuario_autenticado(request).upcs_permitidas(empresa)


@login_required
def selecionar_empresa(request: HttpRequest) -> HttpResponse:
    formulario = ContextoEmpresaForm(
        request.POST or None,
        empresas=usuario_autenticado(request).empresas_permitidas(),
        initial={"empresa": empresa_ativa(request)},
    )
    if request.method == "POST" and formulario.is_valid():
        definir_empresa_ativa(request, formulario.cleaned_data["empresa"])
        return redirect(_proximo_seguro(request) or "inicio")
    return render(
        request,
        "sistema/selecionar_empresa.html",
        {"formulario": formulario, "proximo": request.GET.get("proximo", "")},
    )


@login_required
def selecionar_upc(request: HttpRequest) -> HttpResponse:
    usuario = usuario_autenticado(request)
    if not usa_contexto_de_upc(usuario):
        return redirect("inicio")
    empresa = empresa_ativa(request)
    if empresa is None:
        return redirect("selecionar_empresa")
    formulario = ContextoUPCForm(
        request.POST or None,
        upcs=usuario.upcs_permitidas(empresa),
        initial={"upc": upc_ativa(request)},
    )
    if request.method == "POST" and formulario.is_valid():
        definir_upc_ativa(request, formulario.cleaned_data["upc"])
        return redirect(_proximo_seguro(request) or "inicio")
    return render(
        request,
        "sistema/selecionar_upc.html",
        {
            "formulario": formulario,
            "empresa": empresa,
            "proximo": request.GET.get("proximo", ""),
        },
    )


class LoginSistemaView(LoginView):
    template_name = "sistema/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form: AuthenticationForm) -> HttpResponse:
        usuario = form.get_user()
        if not isinstance(usuario, Usuario):
            raise PermissionDenied
        usuario.access_count += 1
        usuario.save(update_fields=["access_count"])
        return super().form_valid(form)


class TrocarSenhaView(PasswordChangeView):
    template_name = "sistema/trocar_senha.html"
    success_url = reverse_lazy("inicio")

    def form_valid(self, form: PasswordChangeForm) -> HttpResponse:
        resposta = super().form_valid(form)
        usuario = usuario_autenticado(self.request)
        usuario.primeiro_acesso = False
        usuario.save(update_fields=["primeiro_acesso"])
        return resposta


RESUMO_DA_EMPRESA = {
    "fazendas": Fazenda,
    "proprietarios": Proprietario,
    "fornecedores": Fornecedor,
    "plantios": Plantio,
    "talhoes": Talhao,
    "inventarios": InventarioFlorestal,
    "autorizacoes": AutorizacaoAmbiental,
    "expedicoes": Expedicao,
    "transportes": TransporteLenha,
    "colheitas": Colheita,
}


@login_required
def inicio(request: HttpRequest) -> HttpResponse:
    usuario = usuario_autenticado(request)
    administrador = eh_administrador(usuario)
    empresa = empresa_ativa(request)
    resumo: dict[str, int] = {}
    for chave, modelo in RESUMO_DA_EMPRESA.items():
        registros = modelo.objects.none()
        if empresa is not None:
            registros = restringir_por_upc(
                modelo.objects.filter(empresa_id=empresa.pk), request
            )
        resumo[chave] = registros.distinct().count()
    resumo["upcs"] = upcs_visiveis(request).count()
    resumo["estados"] = Estado.objects.count()
    resumo["municipios_ibge"] = Municipio.objects.filter(ativo=True).count()
    if administrador:
        empresas = usuario.empresas_permitidas()
        resumo.update(
            {
                "empresas": empresas.count(),
                "usuarios": usuarios_visiveis(usuario).filter(is_active=True).count(),
                "parametros": Parametros.objects.filter(empresa__in=empresas).count(),
            }
        )
    return render(
        request,
        "sistema/inicio.html",
        {
            "administrador": administrador,
            "empresa": empresa,
            "resumo": resumo,
            "primeira_empresa": administrador and resumo["empresas"] == 0,
        },
    )


@login_required
def municipios_por_estado(request: HttpRequest) -> JsonResponse:
    codigo_estado = request.GET.get("estado", "")
    if not codigo_estado.isdecimal():
        return JsonResponse(
            {"erro": "Informe um código de estado válido."},
            status=400,
        )
    if not Estado.objects.filter(pk=codigo_estado).exists():
        return JsonResponse({"erro": "Estado não encontrado."}, status=404)
    municipios = Municipio.objects.filter(estado_id=codigo_estado, ativo=True).values(
        "codigo", "nome"
    )
    return JsonResponse({"municipios": list(municipios)})


@login_required
def plantios_por_fazenda(request: HttpRequest) -> JsonResponse:
    configuracao = _configurar_recurso(request, "fazendas")
    codigo_fazenda = request.GET.get("fazenda", "")
    if not codigo_fazenda.isdecimal():
        return JsonResponse(
            {"erro": "Informe o código de uma fazenda válida."},
            status=400,
        )
    fazenda = get_object_or_404(
        _queryset_recurso(request, configuracao), pk=codigo_fazenda
    )
    plantios = Plantio.objects.filter(
        fazenda=fazenda,
        empresa_id=fazenda.empresa_id,
    ).order_by("codigo")
    return JsonResponse(
        {
            "plantios": [
                {"codigo": plantio.pk, "nome": str(plantio)}
                for plantio in plantios
            ]
        }
    )


@login_required
def talhoes_por_inventario(request: HttpRequest) -> JsonResponse:
    configuracao = _configurar_recurso(request, "inventarios")
    codigo_inventario = request.GET.get("inventario", "")
    if not codigo_inventario.isdecimal():
        return JsonResponse(
            {"erro": "Informe o código de um inventário válido."},
            status=400,
        )
    inventario = get_object_or_404(
        _queryset_recurso(request, configuracao), pk=codigo_inventario
    )
    talhoes = Talhao.objects.filter(
        empresa_id=inventario.empresa_id,
        fazenda_id=inventario.fazenda_id,
    ).order_by("identificacao")
    arvores_por_hectare = inventario.numero_arvores_ha
    if arvores_por_hectare is None and inventario.area_ha:
        arvores_por_hectare = inventario.numero_arvores / inventario.area_ha
    return JsonResponse(
        {
            "talhoes": [
                {
                    "codigo": talhao.pk,
                    "identificacao": talhao.identificacao,
                    "area_ha": str(talhao.area_ha),
                    "volume_total": (
                        str(talhao.volume_m3) if talhao.volume_m3 is not None else ""
                    ),
                    "saldo_a_retirar_m3": (
                        str(talhao.saldo_a_retirar_m3)
                        if talhao.saldo_a_retirar_m3 is not None
                        else ""
                    ),
                    "numero_arvores": (
                        str(
                            (arvores_por_hectare * talhao.area_ha).quantize(
                                Decimal("0.01")
                            )
                        )
                        if arvores_por_hectare is not None
                        else ""
                    ),
                }
                for talhao in talhoes
            ]
        }
    )


RECURSOS_DO_OPERADOR = {
    "colheitas",
    "expedicoes",
    "transportes-lenha",
    "ciclos-forno",
    "inventarios",
    "inventarios-talhao",
}


def recurso_depende_de_empresa(recurso: str) -> bool:
    configuracao = RECURSOS.get(recurso)
    return configuracao is None or configuracao["modelo"] in MODELOS_POR_EMPRESA


def usuario_pode_acessar(usuario: object, recurso: str) -> bool:
    """Regra única para o menu, os atalhos e o acesso às telas."""
    configuracao = RECURSOS.get(recurso)
    if configuracao is None or not isinstance(usuario, Usuario):
        return False
    if eh_administrador(usuario):
        return True
    return not configuracao["somente_admin"] and _perfil_acessa(usuario, recurso)


def _perfil_acessa(usuario: Usuario, recurso: str) -> bool:
    if usuario.tipo_usuario == TipoUsuario.GESTOR:
        return True
    return (
        usuario.tipo_usuario == TipoUsuario.OPERADOR and recurso in RECURSOS_DO_OPERADOR
    )


def _configurar_recurso(request: HttpRequest, recurso: str) -> dict[str, Any]:
    usuario = usuario_autenticado(request)
    configuracao = RECURSOS.get(recurso)
    if configuracao is None:
        raise Http404
    if not usuario_pode_acessar(usuario, recurso):
        raise PermissionDenied
    return configuracao


def _valor_de_exibicao(valor: object) -> str:
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    return str(valor) if valor not in (None, "") else "—"


def _queryset_recurso(
    request: HttpRequest, configuracao: dict[str, Any]
) -> QuerySet[Model]:
    usuario = usuario_autenticado(request)
    modelo = configuracao["modelo"]
    queryset = modelo.objects.all()
    if modelo is Municipio:
        queryset = queryset.filter(ativo=True)
    elif modelo is Empresa:
        queryset = usuario.empresas_permitidas()
    elif modelo is Usuario:
        queryset = usuarios_visiveis(usuario)
    elif modelo is Parametros:
        queryset = queryset.filter(empresa__in=usuario.empresas_permitidas())
    elif modelo in MODELOS_POR_EMPRESA:
        empresa = empresa_ativa(request)
        if empresa is None:
            return queryset.none()
        queryset = restringir_por_upc(queryset.filter(empresa_id=empresa.pk), request)
        if modelo is UPC:
            queryset = queryset.filter(pk__in=upcs_visiveis(request))
    return queryset


def _somente_consulta(request: HttpRequest, configuracao: dict[str, Any]) -> bool:
    """Empresa encerrada: os dados dela ficam só para consulta."""
    if configuracao.get("somente_leitura"):
        return True
    empresa = empresa_ativa(request)
    return (
        configuracao["modelo"] in MODELOS_POR_EMPRESA
        and empresa is not None
        and empresa.encerrada
    )


def _recusar_empresa_encerrada(request: HttpRequest, recurso: str) -> HttpResponse:
    empresa = empresa_ativa(request)
    messages.error(
        request,
        f"{empresa} está encerrada: os registros ficam disponíveis só para consulta.",
    )
    return redirect("lista_registros", recurso=recurso)


@login_required
def lista_registros(request: HttpRequest, recurso: str) -> HttpResponse:
    configuracao = _configurar_recurso(request, recurso)
    objetos = _queryset_recurso(request, configuracao)
    termo = request.GET.get("q", "").strip()
    if termo:
        filtros = Q()
        for campo in configuracao["busca"]:
            filtros |= Q(**{f"{campo}__icontains": termo})
        objetos = objetos.filter(filtros)
    objetos = objetos.distinct()
    if not objetos.ordered:
        objetos = objetos.order_by("pk")
    pagina = Paginator(objetos, 25).get_page(request.GET.get("page"))
    # Os dados são sempre da empresa ativa: a coluna "Empresa" seria repetida.
    colunas = [coluna for coluna in configuracao["colunas"] if coluna[1] != "empresa"]
    linhas = [
        {
            "objeto": objeto,
            "valores": [
                _valor_de_exibicao(
                    valor() if callable(valor := getattr(objeto, campo)) else valor
                )
                for _, campo in colunas
            ],
        }
        for objeto in pagina.object_list
    ]
    return render(
        request,
        "sistema/lista.html",
        {
            "titulo": configuracao["titulo"],
            "recurso": recurso,
            "colunas": [rotulo for rotulo, _ in colunas],
            "linhas": linhas,
            "pagina": pagina,
            "termo": termo,
            "somente_leitura": _somente_consulta(request, configuracao),
            "consulta_de_encerrada": _somente_consulta(request, configuracao)
            and not configuracao.get("somente_leitura"),
        },
    )


@login_required
def excluir_registro(request: HttpRequest, recurso: str, pk: int) -> HttpResponse:
    configuracao = _configurar_recurso(request, recurso)
    usuario = usuario_autenticado(request)
    if configuracao.get("somente_leitura") or not eh_administrador(usuario):
        raise PermissionDenied
    if _somente_consulta(request, configuracao):
        return _recusar_empresa_encerrada(request, recurso)
    objeto = get_object_or_404(_queryset_recurso(request, configuracao), pk=pk)
    lista = reverse("lista_registros", args=[recurso])
    if objeto == usuario:
        messages.error(request, "Você não pode excluir o próprio usuário.")
        return redirect(lista)
    if request.method == "POST":
        try:
            objeto.delete()
        except ProtectedError:
            messages.error(
                request,
                "Não é possível excluir: há registros vinculados a este item.",
            )
        else:
            messages.success(request, f"{configuracao['titulo']}: registro excluído.")
        return redirect(lista)
    return render(
        request,
        "sistema/confirmar_exclusao.html",
        {"titulo": configuracao["titulo"], "objeto": objeto, "recurso": recurso},
    )


def _proximo_seguro(request: HttpRequest) -> str | None:
    destino = request.POST.get("proximo") or request.GET.get("proximo", "")
    permitido = url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}
    )
    return destino if destino and permitido else None


UPC_DO_CONTEXTO = (InventarioFlorestal, AutorizacaoAmbiental, Forno, BoxLenha)


def _limitar_fornos_e_boxes(formulario: ModelForm, request: HttpRequest) -> None:
    """Fornos e boxes só das UPCs que o usuário enxerga."""
    upcs = upcs_visiveis(request)
    for nome in ("forno", "box_lenha"):
        campo = formulario.fields.get(nome)
        if campo is not None:
            campo.queryset = campo.queryset.filter(upc__in=upcs)


def _limitar_upcs(
    formulario: ModelForm,
    request: HttpRequest,
    modelo: type[Model],
    empresa_fixa: Empresa | None,
) -> None:
    campo = formulario.fields.get("upcs") or formulario.fields.get("upc")
    if campo is None or not empresa_fixa:
        return
    usuario = usuario_autenticado(request)
    if eh_administrador(usuario):
        campo.queryset = UPC.objects.filter(empresa=empresa_fixa)
    else:
        campo.queryset = usuario.upcs_permitidas(empresa_fixa)
    ativa = upc_ativa(request)
    if ativa is not None and modelo in UPC_DO_CONTEXTO:
        if modelo is AutorizacaoAmbiental:
            campo.initial = [ativa.pk]
            formulario.initial["upcs"] = [ativa.pk]
            return
        # O cadastro sempre pertence à UPC escolhida no acesso.
        campo.queryset = UPC.objects.filter(pk=ativa.pk)
        campo.initial = ativa.pk
        campo.disabled = True
        campo.required = False
        formulario.initial["upc"] = ativa.pk


def _adicionar_atalhos(
    request: HttpRequest, formulario: ModelForm, recurso: str, usuario: Usuario
) -> None:
    retorno = urlencode({"proximo": _caminho_sem_selecao(request)})
    for nome_campo, destino in ATALHOS_DE_CADASTRO.items():
        campo = formulario.fields.get(nome_campo)
        if campo is None or destino == recurso:
            continue
        if not usuario_pode_acessar(usuario, destino):
            continue
        campo.atalho_url = (
            f"{reverse('novo_registro', args=[destino])}?{retorno}"
            f"&{urlencode({'campo': nome_campo})}"
        )


def _caminho_sem_selecao(request: HttpRequest) -> str:
    consulta = request.GET.copy()
    consulta.pop("selecionar", None)
    texto = consulta.urlencode()
    return f"{request.path}?{texto}" if texto else request.path


def _destino_com_selecao(proximo: str, campo: str, pk: object) -> str:
    partes = urlsplit(proximo)
    consulta = [
        (k, v) for k, v in parse_qsl(partes.query) if k != "selecionar"
    ] + [("selecionar", f"{campo}:{pk}")]
    return urlunsplit(partes._replace(query=urlencode(consulta)))


def _salvar_registro(formulario: ModelForm, registro: Model, usuario: Usuario) -> None:
    """Grava o registro, os vínculos e o que o formulário criar junto (ex.: lote)."""
    if isinstance(registro, (Usuario, RegistroAuditavel)):
        if registro.pk is None:
            registro.usuario_inclusao = usuario
        registro.usuario_alteracao = usuario
    with transaction.atomic():
        registro.save()
        formulario.save_m2m()
        salvar_extras = getattr(formulario, "salvar_extras", None)
        if salvar_extras is not None:
            salvar_extras(registro)


@login_required
def formulario_registro(
    request: HttpRequest, recurso: str, pk: int | None = None
) -> HttpResponse:
    configuracao = _configurar_recurso(request, recurso)
    if configuracao.get("somente_leitura"):
        raise PermissionDenied
    if _somente_consulta(request, configuracao):
        return _recusar_empresa_encerrada(request, recurso)
    usuario = usuario_autenticado(request)
    empresa_do_contexto = empresa_ativa(request)
    modelo = configuracao["modelo"]
    if modelo in MODELOS_POR_EMPRESA and empresa_do_contexto is None:
        proximo = urlencode({"proximo": request.get_full_path()})
        return redirect(f"{reverse('selecionar_empresa')}?{proximo}")
    queryset = _queryset_recurso(request, configuracao)
    instancia = get_object_or_404(queryset, pk=pk) if pk is not None else None
    formulario_class = configuracao["formulario"]
    empresa_fixa = None
    if modelo in MODELOS_POR_EMPRESA:
        empresa_fixa = (
            getattr(instancia, "empresa", None)
            if instancia is not None
            else empresa_do_contexto
        )
    if empresa_fixa is not None and modelo in FORMULARIOS_DO_GESTOR:
        formulario_class = FORMULARIOS_DO_GESTOR[configuracao["modelo"]]
    argumentos: dict[str, Any] = {"empresa": empresa_fixa} if empresa_fixa else {}
    if getattr(formulario_class, "recebe_usuario", False):
        argumentos["usuario"] = usuario
    formulario = formulario_class(
        request.POST or None, instance=instancia, **argumentos
    )
    _limitar_upcs(formulario, request, configuracao["modelo"], empresa_fixa)
    _limitar_fornos_e_boxes(formulario, request)
    proximo = _proximo_seguro(request)
    _adicionar_atalhos(request, formulario, recurso, usuario)

    if request.method == "POST" and formulario.is_valid():
        registro: Model = formulario.save(commit=False)
        if empresa_fixa:
            registro.empresa = empresa_fixa
        _salvar_registro(formulario, registro, usuario)
        messages.success(request, f"{configuracao['titulo']}: registro salvo.")
        campo_origem = request.GET.get("campo", "")
        if proximo and campo_origem:
            proximo = _destino_com_selecao(proximo, campo_origem, registro.pk)
        return redirect(proximo or reverse("lista_registros", args=[recurso]))

    return render(
        request,
        "sistema/formulario.html",
        {
            "titulo": configuracao["titulo"],
            "formulario": formulario,
            "recurso": recurso,
            "novo": instancia is None,
            "pk": pk,
            "pode_excluir": eh_administrador(usuario),
        },
    )
