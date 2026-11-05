from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def preencher_usuario_inclusao(apps, schema_editor):
    InventarioFlorestal = apps.get_model("sistema", "InventarioFlorestal")
    Usuario = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    banco = schema_editor.connection.alias
    usuario_padrao_id = (
        Usuario.objects.using(banco).order_by("pk").values_list("pk", flat=True).first()
    )

    for inventario in (
        InventarioFlorestal.objects.using(banco)
        .filter(usuario_inclusao__isnull=True)
        .iterator()
    ):
        usuario_id = inventario.usuario_alteracao_id or usuario_padrao_id
        if usuario_id is None:
            msg = (
                "Não é possível exigir o usuário no inventário: "
                "não há usuários cadastrados para preencher registros antigos."
            )
            raise RuntimeError(msg)
        InventarioFlorestal.objects.using(banco).filter(pk=inventario.pk).update(
            usuario_inclusao_id=usuario_id
        )


class Migration(migrations.Migration):

    dependencies = [
        ("sistema", "0027_remove_inventarioflorestal_area_parcela_m2_and_more"),
    ]

    operations = [
        migrations.RunPython(
            preencher_usuario_inclusao,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="inventarioflorestal",
            name="usuario_inclusao",
            field=models.ForeignKey(
                db_column="codigo_usuario",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="inventarios_incluidos",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
