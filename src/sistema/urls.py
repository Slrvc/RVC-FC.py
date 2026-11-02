from django.contrib.auth import views as auth_views
from django.urls import path

from sistema.views import (
    LoginSistemaView,
    TrocarSenhaView,
    excluir_registro,
    formulario_registro,
    inicio,
    lista_registros,
    municipios_por_estado,
    selecionar_empresa,
    selecionar_upc,
)

urlpatterns = [
    path("", inicio, name="inicio"),
    path("empresa/", selecionar_empresa, name="selecionar_empresa"),
    path("upc/", selecionar_upc, name="selecionar_upc"),
    path("entrar/", LoginSistemaView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("senha/alterar/", TrocarSenhaView.as_view(), name="password_change"),
    path(
        "localidades/municipios/",
        municipios_por_estado,
        name="municipios_por_estado",
    ),
    path("gestao/<slug:recurso>/", lista_registros, name="lista_registros"),
    path(
        "gestao/<slug:recurso>/novo/",
        formulario_registro,
        name="novo_registro",
    ),
    path(
        "gestao/<slug:recurso>/<int:pk>/editar/",
        formulario_registro,
        name="editar_registro",
    ),
    path(
        "gestao/<slug:recurso>/<int:pk>/excluir/",
        excluir_registro,
        name="excluir_registro",
    ),
]
