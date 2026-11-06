from django.contrib.auth import views as auth_views
from django.urls import path

from sistema.views import (
    LoginSistemaView,
    TrocarSenhaView,
    consolidado_colheita,
    etapa_do_ciclo,
    excluir_registro,
    formulario_registro,
    inicio,
    lista_registros,
    municipios_por_estado,
    painel_fornos,
    plantios_por_fazenda,
    selecionar_empresa,
    selecionar_upc,
    talhoes_por_inventario,
    tarifa_vigente,
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
    path(
        "localidades/plantios/",
        plantios_por_fazenda,
        name="plantios_por_fazenda",
    ),
    path(
        "localidades/talhoes/",
        talhoes_por_inventario,
        name="talhoes_por_inventario",
    ),
    path(
        "gestao/ciclos-forno/etapa/<slug:etapa>/",
        etapa_do_ciclo,
        name="etapa_do_ciclo",
    ),
    path("painel/fornos/", painel_fornos, name="painel_fornos"),
    path(
        "painel/colheita/", consolidado_colheita, name="consolidado_colheita"
    ),
    path("localidades/tarifa/", tarifa_vigente, name="tarifa_vigente"),
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
