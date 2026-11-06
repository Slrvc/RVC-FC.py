from django.db import migrations, models
from django.db.models import F


def para_dias_vazio(apps, schema_editor):
    """Dias da descarga ao novo enchimento -> dias vazio entre eles (um a menos)."""
    TipoForno = apps.get_model("sistema", "TipoForno")
    TipoForno.objects.filter(dias_vazio_previstos__gt=0).update(
        dias_vazio_previstos=F("dias_vazio_previstos") - 1
    )


def para_intervalo(apps, schema_editor):
    TipoForno = apps.get_model("sistema", "TipoForno")
    TipoForno.objects.update(dias_vazio_previstos=F("dias_vazio_previstos") + 1)


class Migration(migrations.Migration):
    dependencies = [
        ('sistema', '0037_colheita_diaria_por_volume'),
    ]

    operations = [
        migrations.RenameField(
            model_name="tipoforno",
            old_name="dias_intervalo_previstos",
            new_name="dias_vazio_previstos",
        ),
        migrations.AlterField(
            model_name="tipoforno",
            name="dias_vazio_previstos",
            field=models.PositiveSmallIntegerField(
                default=1, verbose_name="Dias vazio entre ciclos"
            ),
        ),
        migrations.RunPython(para_dias_vazio, para_intervalo),
    ]
