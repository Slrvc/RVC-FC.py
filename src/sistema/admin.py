from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    UPC,
    AutorizacaoAmbiental,
    AutorizacaoMovimento,
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
    Talhao,
    TransporteLenha,
    Usuario,
)

for modelo in (
    Colheita,
    Empresa,
    Parametros,
    Estado,
    Municipio,
    Proprietario,
    Fazenda,
    Fornecedor,
    Plantio,
    Talhao,
    UPC,
    InventarioFlorestal,
    InventarioTalhao,
    AutorizacaoAmbiental,
    AutorizacaoMovimento,
    Expedicao,
    TransporteLenha,
    CentroCusto,
    CategoriaCusto,
    Equipamento,
    Cliente,
    ProducaoCarvao,
    LancamentoCusto,
    LancamentoCustoRateio,
):
    admin.site.register(modelo)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "nome_completo", "email", "tipo_usuario", "is_active")
    list_filter = ("tipo_usuario", "is_active", "is_superuser")
    fieldsets = (
        *UserAdmin.fieldsets,
        (
            "Sistema",
            {
                "fields": (
                    "nome_completo",
                    "tipo_usuario",
                    "empresa",
                    "upcs",
                    "primeiro_acesso",
                )
            },
        ),
    )
    filter_horizontal = (*UserAdmin.filter_horizontal, "upcs")
    add_fieldsets = (
        *UserAdmin.add_fieldsets,
        (
            "Sistema",
            {"fields": ("nome_completo", "email", "tipo_usuario", "empresa")},
        ),
    )
