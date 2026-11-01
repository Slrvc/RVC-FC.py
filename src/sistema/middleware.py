from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import redirect

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse


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

        return None
