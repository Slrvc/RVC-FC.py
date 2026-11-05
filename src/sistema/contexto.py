from __future__ import annotations

from typing import TYPE_CHECKING

from sistema.models import UPC, Empresa, TipoUsuario, Usuario

if TYPE_CHECKING:
    from django.http import HttpRequest

CHAVE_UPC_ATIVA = "upc_ativa_id"
CHAVE_EMPRESA_ATIVA = "empresa_ativa_id"


def usuario_eh_admin(usuario: object) -> bool:
    return isinstance(usuario, Usuario) and usuario.eh_administrador


def empresa_ativa(request: HttpRequest) -> Empresa | None:
    """Empresa escolhida no acesso, sempre dentro das empresas do usuário."""
    usuario = request.user
    if not isinstance(usuario, Usuario):
        return None
    pk = request.session.get(CHAVE_EMPRESA_ATIVA)
    if not pk:
        return None
    return (
        usuario.empresas_permitidas()
        .select_related("municipio__estado")
        .filter(pk=pk)
        .first()
    )


def definir_empresa_ativa(request: HttpRequest, empresa: Empresa) -> None:
    request.session[CHAVE_EMPRESA_ATIVA] = empresa.pk
    request.session.pop(CHAVE_UPC_ATIVA, None)


def usa_contexto_de_upc(usuario: object) -> bool:
    """Gestor e operador trabalham em uma UPC; o administrador vê todas."""
    return isinstance(usuario, Usuario) and not usuario.eh_administrador


def upc_ativa(request: HttpRequest) -> UPC | None:
    """UPC escolhida no acesso, dentro das UPCs permitidas na empresa ativa."""
    usuario = request.user
    if not usa_contexto_de_upc(usuario):
        return None
    pk = request.session.get(CHAVE_UPC_ATIVA)
    empresa = empresa_ativa(request)
    if not pk or empresa is None:
        return None
    return usuario.upcs_permitidas(empresa).filter(pk=pk).first()


def definir_upc_ativa(request: HttpRequest, upc: UPC) -> None:
    request.session[CHAVE_UPC_ATIVA] = upc.pk


def contexto_ativo(request: HttpRequest) -> dict[str, object]:
    usuario = request.user
    autenticado = isinstance(usuario, Usuario)
    return {
        "upc_ativa": upc_ativa(request),
        "empresa_ativa": empresa_ativa(request),
        "usuario_admin": usuario_eh_admin(usuario),
        "usuario_superusuario": autenticado and usuario.is_superuser,
        "usuario_operador": getattr(usuario, "tipo_usuario", None)
        == TipoUsuario.OPERADOR,
        "pode_trocar_empresa": autenticado
        and usuario.empresas_permitidas()[:2].count() > 1,
        "menu": itens_do_menu(request) if autenticado else [],
    }


def itens_do_menu(request: HttpRequest) -> list[dict[str, object]]:
    from sistema.menu import montar_menu

    return montar_menu(request)
