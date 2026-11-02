import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def criar_proprietarios(apps, schema_editor) -> None:
    Fazenda = apps.get_model("sistema", "Fazenda")
    Proprietario = apps.get_model("sistema", "Proprietario")
    for fazenda in Fazenda.objects.order_by("pk"):
        proprietario, _ = Proprietario.objects.get_or_create(
            empresa_id=fazenda.empresa_id,
            cpf_cnpj=fazenda.cpf_cnpj,
            defaults={
                "nome_razao_social": fazenda.nome,
                "endereco": fazenda.endereco,
                "bairro": fazenda.bairro[:60],
                "municipio_id": fazenda.municipio_id,
                "cep": fazenda.cep,
                "telefone": fazenda.telefone,
                "email": fazenda.email[:100],
                "usuario_inclusao_id": fazenda.usuario_inclusao_id,
                "usuario_alteracao_id": fazenda.usuario_alteracao_id,
            },
        )
        fazenda.proprietario_id = proprietario.pk
        fazenda.save(update_fields=["proprietario"])


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sistema", "0003_localidades_obrigatorias"),
    ]

    operations = [
        migrations.CreateModel(
            name="Proprietario",
            fields=[
                ("data_criacao", models.DateTimeField(auto_now_add=True)),
                ("data_modificacao", models.DateTimeField(auto_now=True)),
                ("situacao_registro", models.CharField(default="A", max_length=1)),
                (
                    "status_registro",
                    models.CharField(blank=True, default="", max_length=1),
                ),
                ("codigo", models.BigAutoField(primary_key=True, serialize=False)),
                ("nome_razao_social", models.CharField(max_length=150)),
                ("cpf_cnpj", models.CharField(max_length=18, verbose_name="CPF/CNPJ")),
                ("endereco", models.CharField(blank=True, max_length=150)),
                ("bairro", models.CharField(blank=True, max_length=60)),
                ("cep", models.CharField(blank=True, max_length=9)),
                ("telefone", models.CharField(blank=True, max_length=20)),
                ("email", models.EmailField(blank=True, max_length=100)),
                ("observacao", models.CharField(blank=True, max_length=255)),
                (
                    "empresa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="proprietarios",
                        to="sistema.empresa",
                    ),
                ),
                (
                    "municipio",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="proprietarios",
                        to="sistema.municipio",
                    ),
                ),
                (
                    "usuario_alteracao",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "usuario_inclusao",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "proprietários",
                "ordering": ["nome_razao_social"],
            },
        ),
        migrations.AddConstraint(
            model_name="proprietario",
            constraint=models.UniqueConstraint(
                fields=("empresa", "cpf_cnpj"), name="proprietario_doc_por_empresa"
            ),
        ),
        migrations.AddField(
            model_name="fazenda",
            name="proprietario",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="fazendas",
                to="sistema.proprietario",
            ),
        ),
        migrations.AddField(
            model_name="fazenda",
            name="localidade",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="fazenda",
            name="referencia_local",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="fazenda",
            name="area_total_ha",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=12),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="fazenda",
            name="arrendado",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="fazenda",
            name="numero_car",
            field=models.CharField(
                blank=True, max_length=60, verbose_name="Número do CAR"
            ),
        ),
        migrations.AddField(
            model_name="fazenda",
            name="tipo_documento_posse",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="fazenda",
            name="numero_documento_posse",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="fazenda",
            name="observacao",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(criar_proprietarios, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="fazenda",
            name="fazenda_doc_por_empresa",
        ),
        *[
            migrations.RemoveField(model_name="fazenda", name=nome)
            for nome in (
                "tipo_pessoa",
                "cpf_cnpj",
                "relacao",
                "inscricao_estadual",
                "inscricao_municipal",
                "numero",
                "complemento",
                "bairro",
                "telefone",
                "celular",
                "email",
                "site",
            )
        ],
        migrations.AlterField(
            model_name="fazenda",
            name="endereco",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AlterField(
            model_name="fazenda",
            name="proprietario",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="fazendas",
                to="sistema.proprietario",
            ),
        ),
    ]
