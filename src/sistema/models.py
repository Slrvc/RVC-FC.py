from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class Estado(models.Model):
    codigo = models.PositiveSmallIntegerField(primary_key=True)
    uf = models.CharField(max_length=2, unique=True)

    class Meta:
        ordering = ["uf"]

    def __str__(self) -> str:
        return self.uf


class Cidade(models.Model):
    codigo = models.PositiveIntegerField(primary_key=True)
    estado = models.ForeignKey(Estado, on_delete=models.PROTECT, related_name="cidades")
    cidade = models.CharField(max_length=50)

    class Meta:
        ordering = ["cidade"]
        verbose_name_plural = "cidades"
        constraints = [
            models.UniqueConstraint(
                fields=["estado", "cidade"], name="cidade_nome_por_estado"
            )
        ]

    def __str__(self) -> str:
        return f"{self.cidade}/{self.estado.uf}"


class TipoUsuario(models.TextChoices):
    ADMINISTRADOR = "admin", "Administrador do sistema"
    GESTOR = "gestor", "Gestor da unidade"


class UsuarioManager(UserManager):
    def create_superuser(
        self,
        username: str,
        email: str | None = None,
        password: str | None = None,
        **extra_fields: object,
    ):
        extra_fields.setdefault("tipo_usuario", TipoUsuario.ADMINISTRADOR)
        extra_fields.setdefault("primeiro_acesso", False)
        return super().create_superuser(
            username=username,
            email=email,
            password=password,
            **extra_fields,
        )


class Usuario(AbstractUser):
    REQUIRED_FIELDS = ["nome_completo", "email"]

    empresa = models.ForeignKey(
        "Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="usuarios",
    )
    nome_completo = models.CharField(max_length=150)
    primeiro_acesso = models.BooleanField(default=True)
    tipo_usuario = models.CharField(
        max_length=10,
        choices=TipoUsuario.choices,
        default=TipoUsuario.GESTOR,
    )
    access_count = models.PositiveIntegerField(default=0)
    atualizado_em = models.DateTimeField(auto_now=True)
    usuario_inclusao = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usuarios_incluidos",
    )
    usuario_alteracao = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usuarios_alterados",
    )

    objects = UsuarioManager()

    def __str__(self) -> str:
        return self.nome_completo or self.username


class RegistroAuditavel(models.Model):
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_modificacao = models.DateTimeField(auto_now=True)
    usuario_inclusao = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    usuario_alteracao = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    situacao_registro = models.CharField(max_length=1, default="A")
    status_registro = models.CharField(max_length=1, blank=True, default="")

    class Meta:
        abstract = True


class Empresa(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    cnpj = models.CharField("CNPJ", max_length=18, unique=True)
    razao_social = models.CharField(max_length=150)
    nome_fantasia = models.CharField(max_length=150, blank=True)
    inscricao_estadual = models.CharField(max_length=30, blank=True)
    inscricao_municipal = models.CharField(max_length=30, blank=True)
    endereco = models.CharField(max_length=150)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=100)
    estado = models.ForeignKey(
        Estado, on_delete=models.PROTECT, related_name="empresas"
    )
    cidade = models.ForeignKey(
        Cidade, on_delete=models.PROTECT, related_name="empresas"
    )
    codigo_ibge = models.CharField(max_length=7)
    cep = models.CharField(max_length=9, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    celular = models.CharField(max_length=20, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    site = models.URLField(max_length=200, blank=True)

    class Meta:
        ordering = ["razao_social"]
        verbose_name_plural = "empresas"

    def __str__(self) -> str:
        return self.nome_fantasia or self.razao_social


class CodigoIBGE(RegistroAuditavel):
    empresa = models.CharField(max_length=5, default="XXXXX")
    codigo_estado = models.PositiveSmallIntegerField()
    uf = models.CharField(max_length=2)
    nome_uf = models.CharField(max_length=50)
    codigo_cidade = models.CharField(max_length=7)
    nome_cidade = models.CharField(max_length=50)

    class Meta:
        ordering = ["uf", "nome_cidade"]
        verbose_name = "código IBGE"
        verbose_name_plural = "códigos IBGE"
        constraints = [
            models.UniqueConstraint(
                fields=["codigo_cidade", "codigo_estado", "empresa"],
                name="ibge_cidade_estado_empresa",
            )
        ]

    def __str__(self) -> str:
        return f"{self.codigo_cidade} - {self.nome_cidade}/{self.uf}"


class Idioma(models.IntegerChoices):
    PORTUGUES = 1, "Português (Brasil)"
    INGLES = 2, "Inglês (Estados Unidos)"


class Parametros(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="parametros"
    )
    idioma = models.PositiveSmallIntegerField(
        choices=Idioma.choices, default=Idioma.PORTUGUES
    )
    terminal = models.CharField(max_length=20, unique=True, default="0")
    simbolo_monetario = models.CharField(max_length=2, default="R$")
    separador_milhar = models.CharField(max_length=1, default=".")
    separador_decimal = models.CharField(max_length=1, default=",")
    separador_data = models.CharField(max_length=1, default="/")
    separador_hora = models.CharField(max_length=1, default=":")
    formato_data = models.CharField(max_length=15, default="dd/mm/yyyy")
    formato_data_extenso = models.CharField(max_length=30, blank=True)
    formato_hora = models.CharField(max_length=10, default="hh:mm")
    formato_hora_extenso = models.CharField(max_length=10, default="hh:mm:ss")
    casas_decimais_ha = models.PositiveSmallIntegerField(default=4)
    casas_decimais_mdc = models.PositiveSmallIntegerField(default=3)
    casas_decimais_valor = models.PositiveSmallIntegerField(default=2)
    casas_decimais_peso = models.PositiveSmallIntegerField(default=3)
    casas_decimais_porcentagem = models.PositiveSmallIntegerField(default=2)

    class Meta:
        ordering = ["empresa", "terminal"]
        verbose_name = "parâmetro"
        verbose_name_plural = "parâmetros"

    def __str__(self) -> str:
        return f"{self.empresa} ({self.terminal})"


class TipoPessoa(models.TextChoices):
    FISICA = "pf", "Pessoa física"
    JURIDICA = "pj", "Pessoa jurídica"


class RelacaoFazenda(models.TextChoices):
    FORNECEDOR = "fornecedor", "Fornecedor de madeira"
    LOCATARIO = "locatario", "Locatário"
    AMBOS = "ambos", "Fornecedor e locatário"


class Fazenda(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="fazendas"
    )
    tipo_pessoa = models.CharField(max_length=2, choices=TipoPessoa.choices)
    cpf_cnpj = models.CharField(max_length=18)
    nome = models.CharField(max_length=150)
    relacao = models.CharField(max_length=15, choices=RelacaoFazenda.choices)
    inscricao_estadual = models.CharField(max_length=30, blank=True)
    inscricao_municipal = models.CharField(max_length=30, blank=True)
    endereco = models.CharField(max_length=150)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=100)
    estado = models.ForeignKey(
        Estado, on_delete=models.PROTECT, related_name="fazendas"
    )
    cidade = models.ForeignKey(
        Cidade, on_delete=models.PROTECT, related_name="fazendas"
    )
    codigo_ibge = models.CharField(max_length=7)
    cep = models.CharField(max_length=9, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    celular = models.CharField(max_length=20, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    site = models.URLField(max_length=200, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "fazendas"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "cpf_cnpj"], name="fazenda_doc_por_empresa"
            )
        ]

    def __str__(self) -> str:
        return self.nome
