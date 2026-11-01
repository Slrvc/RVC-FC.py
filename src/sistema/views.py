from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Model, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from sistema.forms import (
    CidadeForm,
    CodigoIBGEForm,
    EmpresaForm,
    EstadoForm,
    FazendaForm,
    FazendaGestorForm,
    ParametrosForm,
    UsuarioForm,
)
from sistema.models import (
    Cidade,
    CodigoIBGE,
    Empresa,
    Estado,
    Fazenda,
    Parametros,
    RegistroAuditavel,
    TipoUsuario,
    Usuario,
)

if TYPE_CHECKING:
    from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
    from django.db.models import QuerySet
    from django.http import HttpRequest, HttpResponse


RECURSOS: dict[str, dict[str, Any]] = {
    "empresas": {
        "titulo": "Empresas",
        "modelo": Empresa,
        "formulario": EmpresaForm,
        "colunas": [
            ("Código", "codigo"),
            ("CNPJ", "cnpj"),
            ("Razão social", "razao_social"),
            ("Cidade", "cidade"),
            ("UF", "estado"),
        ],
        "busca": ["cnpj", "razao_social", "nome_fantasia", "cidade__cidade"],
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
            ("Documento", "cpf_cnpj"),
            ("Relação", "get_relacao_display"),
            ("Empresa", "empresa"),
            ("Cidade", "cidade"),
        ],
        "busca": ["nome", "cpf_cnpj", "cidade__cidade", "empresa__razao_social"],
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
        "formulario": EstadoForm,
        "colunas": [("Código", "codigo"), ("UF", "uf")],
        "busca": ["uf"],
        "somente_admin": True,
    },
    "cidades": {
        "titulo": "Cidades",
        "modelo": Cidade,
        "formulario": CidadeForm,
        "colunas": [
            ("Código", "codigo"),
            ("Cidade", "cidade"),
            ("Estado", "estado"),
        ],
        "busca": ["cidade", "estado__uf"],
        "somente_admin": True,
    },
    "codigos-ibge": {
        "titulo": "Códigos IBGE",
        "modelo": CodigoIBGE,
        "formulario": CodigoIBGEForm,
        "colunas": [
            ("Código", "codigo_cidade"),
            ("Cidade", "nome_cidade"),
            ("UF", "uf"),
            ("Empresa", "empresa"),
        ],
        "busca": ["codigo_cidade", "nome_cidade", "uf", "nome_uf"],
        "somente_admin": True,
    },
}


def eh_administrador(usuario: Usuario) -> bool:
    return usuario.is_superuser or usuario.tipo_usuario == TipoUsuario.ADMINISTRADOR


def usuario_autenticado(request: HttpRequest) -> Usuario:
    usuario = request.user
    if not isinstance(usuario, Usuario):
        raise PermissionDenied
    return usuario


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
    if not administrador:
        fazendas = fazendas.filter(empresa_id=usuario.empresa_id)
    resumo = {
        "fazendas": fazendas.count(),
        "fornecedores": fazendas.filter(relacao__in=["fornecedor", "ambos"]).count(),
        "locatarios": fazendas.filter(relacao__in=["locatario", "ambos"]).count(),
        "estados": Estado.objects.count(),
        "cidades": Cidade.objects.count(),
        "codigos_ibge": CodigoIBGE.objects.count(),
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
            "empresa": usuario.empresa,
            "resumo": resumo,
            "primeira_empresa": administrador and resumo["empresas"] == 0,
        },
    )


@login_required
def cidades_por_estado(request: HttpRequest) -> JsonResponse:
    codigo_estado = request.GET.get("estado", "")
    if not codigo_estado.isdecimal():
        return JsonResponse(
            {"erro": "Informe um código de estado válido."},
            status=400,
        )
    if not Estado.objects.filter(pk=codigo_estado).exists():
        return JsonResponse({"erro": "Estado não encontrado."}, status=404)
    cidades = Cidade.objects.filter(estado_id=codigo_estado).values("codigo", "cidade")
    return JsonResponse({"cidades": list(cidades)})


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
        configuracao["modelo"] is Fazenda
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
    if configuracao["modelo"] is Usuario:
        queryset = queryset.filter(is_superuser=False)
    if configuracao["modelo"] is Fazenda and not eh_administrador(usuario):
        queryset = queryset.filter(empresa_id=usuario.empresa_id)
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
        },
    )


@login_required
def formulario_registro(
    request: HttpRequest, recurso: str, pk: int | None = None
) -> HttpResponse:
    configuracao = _configurar_recurso(request, recurso)
    queryset = _queryset_recurso(request, configuracao)
    instancia = get_object_or_404(queryset, pk=pk) if pk is not None else None
    formulario_class = configuracao["formulario"]
    usuario = usuario_autenticado(request)
    if configuracao["modelo"] is Fazenda and not eh_administrador(usuario):
        formulario_class = FazendaGestorForm
    formulario = formulario_class(request.POST or None, instance=instancia)

    if request.method == "POST" and formulario.is_valid():
        registro: Model = formulario.save(commit=False)
        if isinstance(registro, Fazenda) and not eh_administrador(usuario):
            registro.empresa = usuario.empresa
        if isinstance(registro, (Usuario, RegistroAuditavel)):
            if registro.pk is None:
                registro.usuario_inclusao = usuario
            registro.usuario_alteracao = usuario
        registro.save()
        formulario.save_m2m()
        messages.success(request, f"{configuracao['titulo']}: registro salvo.")
        return redirect("lista_registros", recurso=recurso)

    return render(
        request,
        "sistema/formulario.html",
        {
            "titulo": configuracao["titulo"],
            "formulario": formulario,
            "recurso": recurso,
            "novo": instancia is None,
        },
    )
