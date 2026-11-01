from django.contrib.auth import views as auth_views
from django.urls import path

from sistema.views import (
    LoginSistemaView,
    TrocarSenhaView,
    cidades_por_estado,
    formulario_registro,
    inicio,
    lista_registros,
)

urlpatterns = [
    path("", inicio, name="inicio"),
    path("entrar/", LoginSistemaView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("senha/alterar/", TrocarSenhaView.as_view(), name="password_change"),
    path(
        "localidades/cidades/",
        cidades_por_estado,
        name="cidades_por_estado",
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
]
