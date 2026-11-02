from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
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
    CategoriaCustoForm,
    CategoriaCustoGestorForm,
    CentroCustoForm,
    CentroCustoGestorForm,
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
    InventarioFlorestalForm,
    InventarioFlorestalGestorForm,
    InventarioTalhaoForm,
    InventarioTalhaoGestorForm,
    LancamentoCustoForm,
    LancamentoCustoGestorForm,
    LancamentoCustoRateioForm,
    LancamentoCustoRateioGestorForm,
    ParametrosForm,
    PlantioForm,
    PlantioGestorForm,
    ProducaoCarvaoForm,
    ProducaoCarvaoGestorForm,
    ProprietarioForm,
    ProprietarioGestorForm,
    TalhaoForm,
    TalhaoGestorForm,
    TransporteLenhaForm,
    TransporteLenhaGestorForm,
    UPCForm,
    UPCGestorForm,
    UsuarioForm,
)
from sistema.models import (
    UPC,
    AutorizacaoAmbiental,
    CategoriaCusto,
    CentroCusto,
    Cliente,
    Colheita,
    Empresa,
    Equipamento,
    Estado,
    Expedicao,
    Fazenda,
    Fornecedor,
    InventarioFlorestal,
    InventarioTalhao,
    LancamentoCusto,
    LancamentoCustoRateio,
    Municipio,
    Parametros,
    Plantio,
    ProducaoCarvao,
    Proprietario,
    RegistroAuditavel,
    Talhao,
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
    ProducaoCarvao,
    LancamentoCusto,
    LancamentoCustoRateio,
)
FORMULARIOS_DO_GESTOR = {
    LancamentoCusto: LancamentoCustoGestorForm,
    LancamentoCustoRateio: LancamentoCustoRateioGestorForm,
    ProducaoCarvao: ProducaoCarvaoGestorForm,
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
}
FILTROS_POR_UPC = {
    InventarioFlorestal: lambda upcs: Q(upc__in=upcs),
    InventarioTalhao: lambda upcs: Q(inventario__upc__in=upcs),
    AutorizacaoAmbiental: lambda upcs: Q(upc__in=upcs),
    Expedicao: lambda upcs: Q(autorizacao__upc__in=upcs),
    TransporteLenha: lambda upcs: Q(upc__in=upcs) | Q(autorizacao__upc__in=upcs),
    Colheita: lambda upcs: Q(inventario__upc__in=upcs),
    ProducaoCarvao: lambda upcs: Q(upc__in=upcs),
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
    "producoes-carvao": {
        "titulo": "Produção de carvão",
        "modelo": ProducaoCarvao,
        "formulario": ProducaoCarvaoForm,
        "colunas": [
            ("Data", "data_producao"),
            ("UPC", "upc"),
            ("MDC", "volume_mdc"),
            ("Lenha (m³)", "volume_lenha_m3"),
            ("Rendimento", "rendimento_mdc_m3"),
            ("Alerta", "alerta_rendimento"),
            ("Empresa", "empresa"),
        ],
        "busca": ["upc__nome", "autorizacao__numero", "empresa__razao_social"],
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
            ("Município", "municipio"),
        ],
        "busca": [
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
            ("Cadastro", "numero_cadastro"),
            ("Fazenda", "fazenda"),
            ("Espécie", "especie"),
            ("Área (ha)", "area_ha"),
            ("Idade (anos)", "idade_anos"),
            ("Empresa", "empresa"),
        ],
        "busca": [
            "numero_cadastro",
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
            ("Empresa", "empresa"),
        ],
        "busca": [
            "identificacao",
            "fazenda__nome",
            "plantio__numero_cadastro",
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
    return usuario.is_superuser or usuario.tipo_usuario == TipoUsuario.ADMINISTRADOR


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
    usuario = usuario_autenticado(request)
    if eh_administrador(usuario):
        empresa = empresa_ativa(request)
        return UPC.objects.filter(empresa=empresa) if empresa else UPC.objects.all()
    return usuario.upcs_permitidas()


@login_required
def selecionar_empresa(request: HttpRequest) -> HttpResponse:
    if not eh_administrador(usuario_autenticado(request)):
        return redirect("inicio")
    formulario = ContextoEmpresaForm(
        request.POST or None, initial={"empresa": empresa_ativa(request)}
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
    formulario = ContextoUPCForm(
        request.POST or None,
        upcs=usuario.upcs_permitidas(),
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
            "empresa": usuario.empresa,
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


@login_required
def inicio(request: HttpRequest) -> HttpResponse:
    usuario = usuario_autenticado(request)
    administrador = eh_administrador(usuario)
    fazendas = Fazenda.objects.all()
    proprietarios = Proprietario.objects.all()
    fornecedores = Fornecedor.objects.all()
    plantios = Plantio.objects.all()
    talhoes = Talhao.objects.all()
    upcs = UPC.objects.all()
    inventarios = InventarioFlorestal.objects.all()
    autorizacoes = AutorizacaoAmbiental.objects.all()
    expedicoes = Expedicao.objects.all()
    transportes = TransporteLenha.objects.all()
    colheitas = Colheita.objects.all()
    empresa = empresa_ativa(request)
    if empresa is not None:
        empresa_id = empresa.pk
        colheitas = restringir_por_upc(colheitas.filter(empresa_id=empresa_id), request)
        transportes = restringir_por_upc(
            transportes.filter(empresa_id=empresa_id), request
        )
        expedicoes = restringir_por_upc(
            expedicoes.filter(empresa_id=empresa_id), request
        )
        autorizacoes = restringir_por_upc(
            autorizacoes.filter(empresa_id=empresa_id), request
        )
        inventarios = restringir_por_upc(
            inventarios.filter(empresa_id=empresa_id), request
        )
        upcs = upcs_visiveis(request)
        fazendas = fazendas.filter(empresa_id=empresa_id)
        proprietarios = proprietarios.filter(empresa_id=empresa_id)
        fornecedores = fornecedores.filter(empresa_id=empresa_id)
        plantios = plantios.filter(empresa_id=empresa_id)
        talhoes = talhoes.filter(empresa_id=empresa_id)
    resumo = {
        "fazendas": fazendas.count(),
        "proprietarios": proprietarios.count(),
        "fornecedores": fornecedores.count(),
        "plantios": plantios.count(),
        "talhoes": talhoes.count(),
        "upcs": upcs.count(),
        "inventarios": inventarios.count(),
        "autorizacoes": autorizacoes.count(),
        "expedicoes": expedicoes.count(),
        "transportes": transportes.count(),
        "colheitas": colheitas.count(),
        "estados": Estado.objects.count(),
        "municipios_ibge": Municipio.objects.filter(ativo=True).count(),
    }
    if administrador:
        resumo.update(
            {
                "empresas": Empresa.objects.count(),
                "usuarios": Usuario.objects.filter(
                    is_active=True, is_superuser=False
                ).count(),
                "parametros": Parametros.objects.count(),
            }
        )
    return render(
        request,
        "sistema/inicio.html",
        {
            "administrador": administrador,
            "empresa": empresa_ativa(request),
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


def _configurar_recurso(request: HttpRequest, recurso: str) -> dict[str, Any]:
    usuario = usuario_autenticado(request)
    configuracao = RECURSOS.get(recurso)
    if configuracao is None:
        raise Http404
    if configuracao["somente_admin"] and not eh_administrador(usuario):
        raise PermissionDenied
    if not configuracao["somente_admin"] and not (
        eh_administrador(usuario) or usuario.tipo_usuario == TipoUsuario.GESTOR
    ):
        raise PermissionDenied
    if (
        configuracao["modelo"] in MODELOS_POR_EMPRESA
        and not eh_administrador(usuario)
        and usuario.empresa_id is None
    ):
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
    queryset = configuracao["modelo"].objects.all()
    if configuracao["modelo"] is Municipio:
        queryset = queryset.filter(ativo=True)
    if configuracao["modelo"] is Usuario:
        queryset = queryset.filter(is_superuser=False)
    empresa = empresa_ativa(request)
    if (
        configuracao["modelo"] in MODELOS_POR_EMPRESA
        and empresa is not None
        and not eh_administrador(usuario)
    ):
        queryset = queryset.filter(empresa_id=empresa.pk)
        queryset = restringir_por_upc(queryset, request)
    if configuracao["modelo"] is UPC and not eh_administrador(usuario):
        queryset = queryset.filter(pk__in=upcs_visiveis(request))
    return queryset


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
    colunas = configuracao["colunas"]
    linhas = [
        {
            "objeto": objeto,
            "valores": [
                _valor_de_exibicao(
                    getattr(objeto, campo)()
                    if campo.startswith("get_")
                    else getattr(objeto, campo)
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
            "somente_leitura": configuracao.get("somente_leitura", False),
        },
    )


@login_required
def excluir_registro(request: HttpRequest, recurso: str, pk: int) -> HttpResponse:
    configuracao = _configurar_recurso(request, recurso)
    usuario = usuario_autenticado(request)
    if configuracao.get("somente_leitura") or not eh_administrador(usuario):
        raise PermissionDenied
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


UPC_DO_CONTEXTO = (InventarioFlorestal, AutorizacaoAmbiental, ProducaoCarvao)


def _limitar_upcs(
    formulario: ModelForm,
    request: HttpRequest,
    modelo: type[Model],
    empresa_fixa: Empresa | None,
) -> None:
    campo = formulario.fields.get("upc")
    if campo is None or not empresa_fixa:
        return
    campo.queryset = usuario_autenticado(request).upcs_permitidas()
    ativa = upc_ativa(request)
    if ativa is not None and modelo in UPC_DO_CONTEXTO:
        # O cadastro sempre pertence à UPC escolhida no acesso.
        campo.queryset = UPC.objects.filter(pk=ativa.pk)
        campo.initial = ativa.pk
        campo.disabled = True
        campo.required = False
        formulario.initial["upc"] = ativa.pk


def _adicionar_atalhos(
    request: HttpRequest, formulario: ModelForm, recurso: str, usuario: Usuario
) -> None:
    retorno = urlencode({"proximo": request.get_full_path()})
    for nome_campo, destino in ATALHOS_DE_CADASTRO.items():
        campo = formulario.fields.get(nome_campo)
        restrito = RECURSOS[destino].get("somente_admin")
        if campo is None or destino == recurso:
            continue
        if restrito and not eh_administrador(usuario):
            continue
        campo.atalho_url = f"{reverse('novo_registro', args=[destino])}?{retorno}"


@login_required
def formulario_registro(
    request: HttpRequest, recurso: str, pk: int | None = None
) -> HttpResponse:
    configuracao = _configurar_recurso(request, recurso)
    if configuracao.get("somente_leitura"):
        raise PermissionDenied
    queryset = _queryset_recurso(request, configuracao)
    instancia = get_object_or_404(queryset, pk=pk) if pk is not None else None
    formulario_class = configuracao["formulario"]
    usuario = usuario_autenticado(request)
    empresa_fixa = None
    empresa_do_contexto = empresa_ativa(request)
    if (
        configuracao["modelo"] in MODELOS_POR_EMPRESA
        and empresa_do_contexto
        and not eh_administrador(usuario)
    ):
        formulario_class = FORMULARIOS_DO_GESTOR[configuracao["modelo"]]
        empresa_fixa = empresa_do_contexto
    argumentos = {"empresa": empresa_fixa} if empresa_fixa else {}
    formulario = formulario_class(
        request.POST or None, instance=instancia, **argumentos
    )
    if (
        eh_administrador(usuario)
        and empresa_do_contexto
        and instancia is None
        and "empresa" in formulario.fields
    ):
        formulario.fields["empresa"].initial = empresa_do_contexto.pk
    _limitar_upcs(formulario, request, configuracao["modelo"], empresa_fixa)
    proximo = _proximo_seguro(request)
    _adicionar_atalhos(request, formulario, recurso, usuario)

    if request.method == "POST" and formulario.is_valid():
        registro: Model = formulario.save(commit=False)
        if empresa_fixa:
            registro.empresa = empresa_fixa
        if isinstance(registro, (Usuario, RegistroAuditavel)):
            if registro.pk is None:
                registro.usuario_inclusao = usuario
            registro.usuario_alteracao = usuario
        registro.save()
        formulario.save_m2m()
        messages.success(request, f"{configuracao['titulo']}: registro salvo.")
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
