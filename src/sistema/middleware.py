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
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse
    from django.urls import ResolverMatch

    from sistema.models import Empresa


class ExigirTrocaSenhaMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

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

        if match.view_name == "selecionar_empresa" or not self._depende_de_empresa(
            match
        ):
            return None
        empresa = empresa_ativa(request)
        if empresa is None:
            empresa = self._escolher_empresa_unica(request)
            if empresa is None:
                return self._pedir_escolha(request, "selecionar_empresa")

        if match.view_name == "selecionar_upc":
            return None
        return self._garantir_upc(request, empresa)

    def _garantir_upc(
        self, request: HttpRequest, empresa: Empresa
    ) -> HttpResponse | None:
        """Gestor e operador: com uma só UPC, entra nela; com várias, escolhe."""
        if not usa_contexto_de_upc(request.user) or upc_ativa(request) is not None:
            return None
        permitidas = list(request.user.upcs_permitidas(empresa)[:2])
        if not permitidas:
            return None
        if len(permitidas) == 1:
            definir_upc_ativa(request, permitidas[0])
            return None
        return self._pedir_escolha(request, "selecionar_upc")

    @staticmethod
    def _depende_de_empresa(match: ResolverMatch) -> bool:
        """O admin do Django e as configurações gerais não pedem empresa ativa."""
        from sistema.views import recurso_depende_de_empresa

        if match.namespace == "admin":
            return False
        recurso = match.kwargs.get("recurso")
        return recurso is None or recurso_depende_de_empresa(recurso)

    @staticmethod
    def _escolher_empresa_unica(request: HttpRequest) -> Empresa | None:
        """Com uma só empresa (ou uma só ativa), entra nela sem perguntar."""
        permitidas = request.user.empresas_permitidas()
        for opcoes in (permitidas.ativas(), permitidas):
            primeiras = list(opcoes[:2])
            if len(primeiras) == 1:
                definir_empresa_ativa(request, primeiras[0])
                return primeiras[0]
            if primeiras:
                return None
        return None

    @staticmethod
    def _pedir_escolha(request: HttpRequest, tela: str) -> HttpResponse | None:
        if not request.user.empresas_permitidas().exists():
            return None
        proximo = urlencode({"proximo": request.get_full_path()})
        return redirect(f"{reverse(tela)}?{proximo}")
