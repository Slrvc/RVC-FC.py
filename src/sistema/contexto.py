from __future__ import annotations

from typing import TYPE_CHECKING

from sistema.models import UPC, Empresa, TipoUsuario, Usuario

if TYPE_CHECKING:
    from django.http import HttpRequest

CHAVE_UPC_ATIVA = "upc_ativa_id"
CHAVE_EMPRESA_ATIVA = "empresa_ativa_id"


def usuario_eh_admin(usuario: object) -> bool:
    return isinstance(usuario, Usuario) and (
        usuario.is_superuser or usuario.tipo_usuario == TipoUsuario.ADMINISTRADOR
    )


def empresa_ativa(request: HttpRequest) -> Empresa | None:
    """Gestor: a empresa do cadastro. Administrador: a empresa escolhida no acesso."""
    usuario = request.user
    if not isinstance(usuario, Usuario):
        return None
    if not usuario_eh_admin(usuario):
        return usuario.empresa
    pk = request.session.get(CHAVE_EMPRESA_ATIVA)
    return Empresa.objects.filter(pk=pk).first() if pk else None


def definir_empresa_ativa(request: HttpRequest, empresa: Empresa) -> None:
    request.session[CHAVE_EMPRESA_ATIVA] = empresa.pk
    request.session.pop(CHAVE_UPC_ATIVA, None)


def usa_contexto_de_upc(usuario: object) -> bool:
    return (
        isinstance(usuario, Usuario)
        and not usuario.is_superuser
        and usuario.tipo_usuario != TipoUsuario.ADMINISTRADOR
        and usuario.empresa_id is not None
    )


def upc_ativa(request: HttpRequest) -> UPC | None:
    """UPC escolhida no login, sempre dentro das UPCs permitidas ao gestor."""
    usuario = request.user
    if not usa_contexto_de_upc(usuario):
        return None
    pk = request.session.get(CHAVE_UPC_ATIVA)
    if not pk:
        return None
    return usuario.upcs_permitidas().filter(pk=pk).first()


def definir_upc_ativa(request: HttpRequest, upc: UPC) -> None:
    request.session[CHAVE_UPC_ATIVA] = upc.pk


def contexto_ativo(request: HttpRequest) -> dict[str, object]:
    return {
        "upc_ativa": upc_ativa(request),
        "empresa_ativa": empresa_ativa(request),
        "usuario_admin": usuario_eh_admin(request.user),
        "usuario_operador": getattr(request.user, "tipo_usuario", None)
        == TipoUsuario.OPERADOR,
    }
