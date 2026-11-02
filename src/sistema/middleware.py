from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from sistema.contexto import (
    definir_empresa_ativa,
    definir_upc_ativa,
    empresa_ativa,
    upc_ativa,
    usa_contexto_de_upc,
    usuario_eh_admin,
)
from sistema.models import Empresa

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse
    from django.urls import ResolverMatch

RECURSOS_GLOBAIS = {"empresas", "usuarios", "parametros", "estados", "municipios-ibge"}


class ExigirTrocaSenhaMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def _exigir_empresa(
        self, request: HttpRequest, match: ResolverMatch
    ) -> HttpResponse | None:
        recurso = match.kwargs.get("recurso")
        if (
            match.app_name == "admin"
            or match.view_name == "selecionar_empresa"
            or match.view_name == "inicio"
            or recurso in RECURSOS_GLOBAIS
        ):
            return None
        if empresa_ativa(request) is not None:
            return None
        empresas = list(Empresa.objects.all()[:2])
        if not empresas:
            return None
        if len(empresas) == 1:
            definir_empresa_ativa(request, empresas[0])
            return None
        proximo = urlencode({"proximo": request.get_full_path()})
        return redirect(f"{reverse('selecionar_empresa')}?{proximo}")

    def process_view(
        self,
        request: HttpRequest,
        _view_func: Callable[..., object],
        _view_args: tuple[object, ...],
        _view_kwargs: dict[str, object],
    ) -> HttpResponse | None:
        if not request.user.is_authenticated:
            return None

        match = request.resolver_match
        if match is None or match.view_name in {
            "login",
            "logout",
            "password_change",
        }:
            return None

        if request.user.primeiro_acesso:
            return redirect("password_change")

        if usuario_eh_admin(request.user):
            return self._exigir_empresa(request, match)

        if match.view_name == "selecionar_upc" or not usa_contexto_de_upc(request.user):
            return None
        if upc_ativa(request) is not None:
            return None
        permitidas = list(request.user.upcs_permitidas()[:2])
        if not permitidas:
            return None
        if len(permitidas) == 1:
            definir_upc_ativa(request, permitidas[0])
            return None
        proximo = urlencode({"proximo": request.get_full_path()})
        return redirect(f"{reverse('selecionar_upc')}?{proximo}")
        return None
