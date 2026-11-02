from django.db import migrations

from sistema.formatacao import MASCARAS_POR_CAMPO, normalizar

MODELOS = ("Empresa", "Fazenda", "Proprietario", "Fornecedor", "Cliente")


def formatar(apps, schema_editor):
    for nome_modelo in MODELOS:
        modelo = apps.get_model("sistema", nome_modelo)
        campos = [f.name for f in modelo._meta.fields if f.name in MASCARAS_POR_CAMPO]
        for objeto in modelo.objects.all():
            alterados = []
            for campo in campos:
                try:
                    novo = normalizar(MASCARAS_POR_CAMPO[campo], getattr(objeto, campo))
                except ValueError:
                    continue
                if novo != getattr(objeto, campo):
                    setattr(objeto, campo, novo)
                    alterados.append(campo)
            if alterados:
                objeto.save(update_fields=alterados)


class Migration(migrations.Migration):
    dependencies = [("sistema", "0020_usuario_operador")]

    operations = [migrations.RunPython(formatar, migrations.RunPython.noop)]
