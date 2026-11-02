from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


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
                    "primeiro_acesso",
                )
            },
        ),
    )
    add_fieldsets = (
        *UserAdmin.add_fieldsets,
        (
            "Sistema",
            {"fields": ("nome_completo", "email", "tipo_usuario", "empresa")},
        ),
    )
