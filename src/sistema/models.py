from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models, transaction
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.html import format_html

FATOR_MST_POR_M3 = Decimal("1.5")


class Estado(models.Model):
    codigo = models.PositiveSmallIntegerField(primary_key=True)
    uf = models.CharField(max_length=2, unique=True)
    nome = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["uf"]

    def __str__(self) -> str:
        return self.uf


class Municipio(models.Model):
    codigo = models.CharField(max_length=7, primary_key=True)
    nome = models.CharField(max_length=100)
    ativo = models.BooleanField(default=True)
    estado = models.ForeignKey(
        Estado, on_delete=models.PROTECT, related_name="municipios"
    )

    class Meta:
        ordering = ["nome", "estado__uf"]
        verbose_name = "município"
        verbose_name_plural = "municípios"

    def __str__(self) -> str:
        return f"{self.nome}/{self.estado.uf} ({self.codigo})"


class TipoUsuario(models.TextChoices):
    ADMINISTRADOR = "admin", "Administrador da matriz"
    GESTOR = "gestor", "Gestor da unidade"
    OPERADOR = "operador", "Operador (lançamentos de produção)"


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

    matriz = models.ForeignKey(
        "Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="usuarios_da_matriz",
        limit_choices_to={"tipo": "MATRIZ"},
    )
    empresas = models.ManyToManyField(
        "Empresa", blank=True, related_name="usuarios_com_acesso"
    )
    nome_completo = models.CharField(max_length=150)
    upcs = models.ManyToManyField("UPC", blank=True, related_name="gestores")
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

    @property
    def eh_administrador(self) -> bool:
        return self.is_superuser or self.tipo_usuario == TipoUsuario.ADMINISTRADOR

    def empresas_permitidas(self) -> models.QuerySet[Empresa]:
        """Superusuário: todas. Administrador: a matriz e as filiais dela.
        Gestor e operador: as empresas liberadas pelo administrador."""
        if self.is_superuser:
            return Empresa.objects.all()
        if self.matriz_id is None:
            return Empresa.objects.none()
        da_conta = Empresa.objects.da_conta(self.matriz_id)
        if self.tipo_usuario == TipoUsuario.ADMINISTRADOR:
            return da_conta
        if not self.pk:
            return Empresa.objects.none()
        return da_conta.filter(usuarios_com_acesso=self)

    def upcs_permitidas(self, empresa: Empresa | None = None) -> models.QuerySet[UPC]:
        """UPCs das empresas permitidas (ou só da empresa informada).
        Sem UPCs vinculadas, o gestor atende todas as UPCs dessas empresas."""
        permitidas = UPC.objects.filter(empresa__in=self.empresas_permitidas())
        if empresa is not None:
            permitidas = permitidas.filter(empresa=empresa)
        if not self.eh_administrador and self.pk and self.upcs.exists():
            return permitidas.filter(gestores=self)
        return permitidas


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


class TipoEmpresa(models.TextChoices):
    MATRIZ = "MATRIZ", "Matriz"
    FILIAL = "FILIAL", "Filial"


class EmpresaQuerySet(models.QuerySet):
    def da_conta(self, matriz_id: int) -> EmpresaQuerySet:
        """A matriz e as filiais dela: tudo o que um cliente do sistema enxerga."""
        return self.filter(models.Q(pk=matriz_id) | models.Q(matriz_id=matriz_id))

    def ativas(self) -> EmpresaQuerySet:
        return self.filter(data_encerramento__isnull=True)


class Empresa(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    tipo = models.CharField(
        max_length=6, choices=TipoEmpresa.choices, default=TipoEmpresa.MATRIZ
    )
    matriz = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="filiais",
        limit_choices_to={"tipo": TipoEmpresa.MATRIZ},
    )
    descricao_filial = models.CharField(
        "Descrição da filial",
        max_length=100,
        blank=True,
        help_text="Ex.: Filial 01 - Sete Lagoas.",
    )
    cnpj = models.CharField("CNPJ", max_length=18, unique=True)
    razao_social = models.CharField(max_length=150)
    nome_fantasia = models.CharField(max_length=150, blank=True)
    inscricao_estadual = models.CharField(max_length=30, blank=True)
    inscricao_municipal = models.CharField(max_length=30, blank=True)
    endereco = models.CharField(max_length=150)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=100)
    municipio = models.ForeignKey(
        Municipio, on_delete=models.PROTECT, related_name="empresas"
    )
    cep = models.CharField(max_length=9, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    celular = models.CharField(max_length=20, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    site = models.URLField(max_length=200, blank=True)
    data_encerramento = models.DateField(
        "Data de encerramento",
        null=True,
        blank=True,
        help_text="Empresa encerrada fica disponível só para consulta.",
    )
    motivo_encerramento = models.CharField(
        "Motivo do encerramento", max_length=255, blank=True
    )

    objects = EmpresaQuerySet.as_manager()

    class Meta:
        ordering = ["razao_social", "cnpj"]
        verbose_name_plural = "empresas"

    def __str__(self) -> str:
        return self.nome_fantasia or self.razao_social

    @property
    def encerrada(self) -> bool:
        return self.data_encerramento is not None

    @property
    def situacao_exibicao(self) -> str:
        if self.encerrada:
            return f"Encerrada em {self.data_encerramento:%d/%m/%Y}"
        return "Ativa"

    @property
    def matriz_da_conta_id(self) -> int:
        """A matriz que é dona desta empresa (a própria, se for matriz)."""
        return self.matriz_id or self.pk

    @property
    def tipo_exibicao(self) -> str:
        if self.tipo == TipoEmpresa.FILIAL and self.descricao_filial:
            return self.descricao_filial
        return self.get_tipo_display()

    @property
    def identificacao(self) -> str:
        local = f"{self.municipio.nome}/{self.municipio.estado.uf}"
        texto = f"{self} · {self.tipo_exibicao} · {local} · CNPJ {self.cnpj}"
        return f"{texto} · encerrada" if self.encerrada else texto


class Idioma(models.IntegerChoices):
    PORTUGUES = 1, "Português (Brasil)"
    INGLES = 2, "Inglês (Estados Unidos)"


class Pais(models.TextChoices):
    BRASIL = "BR", "Brasil"
    PORTUGAL = "PT", "Portugal"
    ESTADOS_UNIDOS = "US", "Estados Unidos"


# Formatos de cada país; os parâmetros partem deles e podem ser ajustados.
PADROES_POR_PAIS = {
    Pais.BRASIL: {
        "idioma": 1,
        "simbolo_monetario": "R$",
        "separador_milhar": ".",
        "separador_decimal": ",",
        "formato_data": "dd/mm/yyyy",
        "formato_hora": "hh:mm",
        "formato_hora_extenso": "hh:mm:ss",
    },
    Pais.PORTUGAL: {
        "idioma": 1,
        "simbolo_monetario": "€",
        "separador_milhar": " ",
        "separador_decimal": ",",
        "formato_data": "dd/mm/yyyy",
        "formato_hora": "hh:mm",
        "formato_hora_extenso": "hh:mm:ss",
    },
    Pais.ESTADOS_UNIDOS: {
        "idioma": 2,
        "simbolo_monetario": "US$",
        "separador_milhar": ",",
        "separador_decimal": ".",
        "formato_data": "mm/dd/yyyy",
        "formato_hora": "hh:mm",
        "formato_hora_extenso": "hh:mm:ss",
    },
}


class Parametros(RegistroAuditavel):
    """Parâmetros do sistema: formatação de números, datas e valores.

    Sem registro vale o padrão do Brasil. Com registro, parte do padrão do país
    escolhido e cada formato pode ser ajustado. A filial sem registro usa o da
    matriz.
    """

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.OneToOneField(
        Empresa, on_delete=models.CASCADE, related_name="parametros"
    )
    pais = models.CharField(
        "País", max_length=2, choices=Pais.choices, default=Pais.BRASIL
    )
    idioma = models.PositiveSmallIntegerField(
        choices=Idioma.choices, default=Idioma.PORTUGUES
    )
    simbolo_monetario = models.CharField(max_length=3, default="R$")
    separador_milhar = models.CharField(max_length=1, default=".")
    separador_decimal = models.CharField(max_length=1, default=",")
    separador_data = models.CharField(max_length=1, default="/")
    separador_hora = models.CharField(max_length=1, default=":")
    formato_data = models.CharField(max_length=15, default="dd/mm/yyyy")
    formato_data_extenso = models.CharField(max_length=30, blank=True)
    formato_hora = models.CharField(max_length=10, default="hh:mm")
    formato_hora_extenso = models.CharField(max_length=10, default="hh:mm:ss")
    casas_decimais_ha = models.PositiveSmallIntegerField(default=2)
    casas_decimais_volume = models.PositiveSmallIntegerField(default=3)
    casas_decimais_mdc = models.PositiveSmallIntegerField(default=2)
    casas_decimais_valor = models.PositiveSmallIntegerField(default=2)
    casas_decimais_peso = models.PositiveSmallIntegerField(default=3)
    casas_decimais_porcentagem = models.PositiveSmallIntegerField(default=2)

    class Meta:
        ordering = ["empresa"]
        verbose_name = "parâmetro do sistema"
        verbose_name_plural = "parâmetros do sistema"

    def __str__(self) -> str:
        return f"Parâmetros do sistema - {self.empresa}"

    @classmethod
    def da_empresa(cls, empresa: Empresa | None) -> Parametros:
        """Os da empresa, senão os da matriz, senão os padrões."""
        if empresa is not None:
            for codigo in (empresa.pk, empresa.matriz_id):
                if codigo is None:
                    continue
                encontrado = cls.objects.filter(empresa_id=codigo).first()
                if encontrado is not None:
                    return encontrado
        return cls.do_pais(Pais.BRASIL)

    @classmethod
    def do_pais(cls, pais: str) -> Parametros:
        """Parâmetros (não gravados) com os formatos padrão do país."""
        return cls(pais=pais, **PADROES_POR_PAIS[Pais(pais)])


class ControleEstoqueTalhao(models.TextChoices):
    EM_PE = "EM_PE", "Madeira em pé (inventário até a colheita)"
    COLHIDA = "COLHIDA", "Lenha colhida (colheita até o baldeio)"


TOLERANCIA_FATOR_PADRAO_PCT = Decimal("30")


class ParametroEmpresa(RegistroAuditavel):
    """Fatores de conversão e regras de estoque, uma linha por empresa."""

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.OneToOneField(
        Empresa, on_delete=models.CASCADE, related_name="parametro_empresa"
    )
    controle_estoque_talhao = models.CharField(
        max_length=10,
        choices=ControleEstoqueTalhao.choices,
        default=ControleEstoqueTalhao.COLHIDA,
    )
    fator_mst_por_m3 = models.DecimalField(
        max_digits=6, decimal_places=3, default=FATOR_MST_POR_M3
    )
    fator_m3_por_mdc_ideal = models.DecimalField(
        max_digits=6, decimal_places=3, default=Decimal("1.33")
    )
    fator_mst_por_mdc_ideal = models.DecimalField(
        max_digits=6, decimal_places=3, default=Decimal("2.0")
    )
    tolerancia_fator_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["empresa"]
        verbose_name = "parâmetro de produção"
        verbose_name_plural = "parâmetros de produção"

    def __str__(self) -> str:
        return f"Parâmetros de produção - {self.empresa}"

    @classmethod
    def da_empresa(cls, empresa_id: int | None) -> ParametroEmpresa:
        """Parâmetros gravados da empresa ou, se não houver, os valores padrão."""
        if empresa_id is not None:
            parametro = cls.objects.filter(empresa_id=empresa_id).first()
            if parametro is not None:
                return parametro
        return cls(empresa_id=empresa_id)

    @property
    def tolerancia_efetiva_pct(self) -> Decimal:
        if self.tolerancia_fator_pct is None:
            return TOLERANCIA_FATOR_PADRAO_PCT
        return self.tolerancia_fator_pct


class Proprietario(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="proprietarios"
    )
    nome_razao_social = models.CharField(max_length=150)
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=18)
    inscricao_estadual = models.CharField(
        "Inscrição estadual", max_length=20, blank=True
    )
    endereco = models.CharField(max_length=150, blank=True)
    bairro = models.CharField(max_length=60, blank=True)
    municipio = models.ForeignKey(
        Municipio,
        on_delete=models.PROTECT,
        related_name="proprietarios",
        null=True,
        blank=True,
    )
    cep = models.CharField(max_length=9, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(max_length=100, blank=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nome_razao_social"]
        verbose_name_plural = "proprietários"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "cpf_cnpj"], name="proprietario_doc_por_empresa"
            )
        ]

    def __str__(self) -> str:
        return self.nome_razao_social


class Fazenda(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="fazendas"
    )
    proprietario = models.ForeignKey(
        Proprietario, on_delete=models.PROTECT, related_name="fazendas"
    )
    nome = models.CharField(max_length=150)
    endereco = models.CharField(max_length=150, blank=True)
    localidade = models.CharField(max_length=100, blank=True)
    municipio = models.ForeignKey(
        Municipio, on_delete=models.PROTECT, related_name="fazendas"
    )
    cep = models.CharField(max_length=9, blank=True)
    referencia_local = models.CharField(max_length=255, blank=True)
    area_total_ha = models.DecimalField(max_digits=12, decimal_places=4)
    arrendado = models.BooleanField(default=False)
    numero_matricula = models.CharField(
        "Número da matrícula", max_length=50, blank=True
    )
    numero_car = models.CharField("Número do CAR", max_length=60, blank=True)
    tipo_documento_posse = models.CharField(max_length=30, blank=True)
    numero_documento_posse = models.CharField(max_length=50, blank=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "fazendas"

    def __str__(self) -> str:
        return self.nome

    @property
    def nome_curto(self) -> str:
        """Sem "Fazenda" e com as preposições minúsculas: Lagoa dos Currais."""
        nome = self.nome.strip()
        if nome.upper().startswith("FAZENDA "):
            nome = nome[8:]
        palavras = [
            palavra.lower()
            if palavra.lower() in {"da", "das", "de", "do", "dos", "e"} and indice
            else palavra.capitalize()
            for indice, palavra in enumerate(nome.split())
        ]
        return " ".join(palavras)


class SistemaColheita(models.TextChoices):
    MECANIZADA = "MECANIZADA", "Mecanizada"
    MANUAL = "MANUAL", "Manual"


class EtapaColheita(models.TextChoices):
    CORTE_FELLER = "CORTE_FELLER", "Corte/derrubada (feller)"
    ARRASTE = "ARRASTE", "Arraste (skidder)"
    TRACAMENTO = "TRACAMENTO", "Traçamento (garra traçadora)"
    CORTE_MOTOSSERRA = "CORTE_MOTOSSERRA", "Corte (motosserra)"
    EMBANDEIRAMENTO = "EMBANDEIRAMENTO", "Embandeiramento"


ETAPAS_POR_SISTEMA = {
    SistemaColheita.MECANIZADA: (
        EtapaColheita.CORTE_FELLER,
        EtapaColheita.ARRASTE,
        EtapaColheita.TRACAMENTO,
    ),
    SistemaColheita.MANUAL: (
        EtapaColheita.CORTE_MOTOSSERRA,
        EtapaColheita.EMBANDEIRAMENTO,
    ),
}
SISTEMA_DA_ETAPA = {
    etapa: sistema for sistema, etapas in ETAPAS_POR_SISTEMA.items() for etapa in etapas
}


class TipoServico(models.TextChoices):
    """Serviços que um fornecedor presta; as etapas da colheita vêm primeiro."""

    CORTE_FELLER = EtapaColheita.CORTE_FELLER.value, EtapaColheita.CORTE_FELLER.label
    ARRASTE = EtapaColheita.ARRASTE.value, EtapaColheita.ARRASTE.label
    TRACAMENTO = EtapaColheita.TRACAMENTO.value, EtapaColheita.TRACAMENTO.label
    CORTE_MOTOSSERRA = (
        EtapaColheita.CORTE_MOTOSSERRA.value,
        EtapaColheita.CORTE_MOTOSSERRA.label,
    )
    EMBANDEIRAMENTO = (
        EtapaColheita.EMBANDEIRAMENTO.value,
        EtapaColheita.EMBANDEIRAMENTO.label,
    )
    TRANSPORTE_LENHA = "TRANSPORTE_LENHA", "Transporte de lenha"
    CARBONIZACAO = "CARBONIZACAO", "Carbonização (produção de carvão)"
    FRETE_CARVAO = "FRETE_CARVAO", "Expedição (frete de carvão)"
    OUTRO = "OUTRO", "Outro"


class UnidadeTarifa(models.TextChoices):
    M3 = "M3", "m³"
    MST = "MST", "MST"
    HA = "HA", "Hectare"
    MDC = "MDC", "MDC"
    TONELADA = "TONELADA", "Tonelada"
    VIAGEM = "VIAGEM", "Viagem"
    KM = "KM", "Km"


UNIDADES_DA_COLHEITA = (UnidadeTarifa.M3, UnidadeTarifa.MST, UnidadeTarifa.HA)


class Fornecedor(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="fornecedores"
    )
    nome_razao_social = models.CharField(max_length=150)
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=18)
    inscricao_estadual = models.CharField(
        "Inscrição estadual", max_length=20, blank=True
    )
    endereco = models.CharField(max_length=150, blank=True)
    bairro = models.CharField(max_length=60, blank=True)
    municipio = models.ForeignKey(
        Municipio,
        on_delete=models.PROTECT,
        related_name="fornecedores",
        null=True,
        blank=True,
    )
    cep = models.CharField(max_length=9, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(max_length=100, blank=True)
    fornece_servico = models.BooleanField(default=False)
    fornece_produto = models.BooleanField(default=False)
    fornece_locacao = models.BooleanField(default=False)
    registro_conselho = models.CharField(max_length=30, blank=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nome_razao_social"]
        verbose_name_plural = "fornecedores"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "cpf_cnpj"], name="fornecedor_doc_por_empresa"
            )
        ]

    def __str__(self) -> str:
        return self.nome_razao_social

    def tipos(self) -> str:
        nomes = [
            nome
            for ativo, nome in (
                (self.fornece_servico, "Serviço"),
                (self.fornece_produto, "Produto"),
                (self.fornece_locacao, "Locação"),
            )
            if ativo
        ]
        return ", ".join(nomes) or "-"


class FornecedorTarifa(RegistroAuditavel):
    """Valor combinado com o fornecedor por serviço e unidade, com vigência."""

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="tarifas_fornecedor"
    )
    fornecedor = models.ForeignKey(
        Fornecedor, on_delete=models.CASCADE, related_name="tarifas"
    )
    tipo_servico = models.CharField(max_length=20, choices=TipoServico.choices)
    unidade = models.CharField(max_length=10, choices=UnidadeTarifa.choices)
    valor = models.DecimalField(max_digits=12, decimal_places=4)
    vigencia_inicio = models.DateField()
    vigencia_fim = models.DateField(null=True, blank=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["fornecedor__nome_razao_social", "tipo_servico", "-vigencia_inicio"]
        verbose_name = "tarifa de fornecedor"
        verbose_name_plural = "tarifas de fornecedor"

    def __str__(self) -> str:
        return (
            f"{self.fornecedor} - {self.get_tipo_servico_display()} "
            f"({self.get_unidade_display()})"
        )

    @classmethod
    def vigente(
        cls, fornecedor_id: int | None, tipo_servico: str, data
    ) -> FornecedorTarifa | None:
        if not fornecedor_id or not tipo_servico or data is None:
            return None
        return (
            cls.objects.filter(
                fornecedor_id=fornecedor_id,
                tipo_servico=tipo_servico,
                vigencia_inicio__lte=data,
            )
            .filter(
                models.Q(vigencia_fim__isnull=True) | models.Q(vigencia_fim__gte=data)
            )
            .order_by("-vigencia_inicio")
            .first()
        )


class OrigemFloresta(models.TextChoices):
    EXOTICA = "EXOTICA", "Exótica"
    NATIVA = "NATIVA", "Nativa"


class MetodoPropagacao(models.TextChoices):
    CLONAL = "CLONAL", "Clonal"
    SEMINAL = "SEMINAL", "Seminal"


class Rotacao(models.IntegerChoices):
    PRIMEIRA = 1, "1º corte"
    SEGUNDA = 2, "2º corte"
    TERCEIRA = 3, "3º corte ou mais"


class Plantio(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="plantios"
    )
    fazenda = models.ForeignKey(
        Fazenda, on_delete=models.PROTECT, related_name="plantios"
    )
    idade_anos = models.PositiveSmallIntegerField(
        "Idade (anos)", null=True, blank=True
    )
    especie = models.CharField(max_length=60, blank=True)
    origem = models.CharField(
        max_length=10, choices=OrigemFloresta.choices, default=OrigemFloresta.EXOTICA
    )
    metodo_propagacao = models.CharField(
        max_length=10, choices=MetodoPropagacao.choices, blank=True
    )
    espacamento_entrelinha_m = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    espacamento_planta_m = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    data_plantio = models.DateField(null=True, blank=True)
    data_ultimo_corte = models.DateField(null=True, blank=True)
    rotacao = models.PositiveSmallIntegerField(
        choices=Rotacao.choices, default=Rotacao.PRIMEIRA
    )
    area_ha = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["fazenda__nome", "codigo"]
        verbose_name_plural = "plantios"

    def __str__(self) -> str:
        return f"Plantio {self.codigo} - {self.fazenda}"


class Inclinacao(models.TextChoices):
    ATE_5 = "ATE_5", "Até 5%"
    ACIMA_5 = "ACIMA_5", "Acima de 5%"


class Talhao(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="talhoes"
    )
    fazenda = models.ForeignKey(
        Fazenda, on_delete=models.PROTECT, related_name="talhoes"
    )
    plantio = models.ForeignKey(
        Plantio,
        on_delete=models.PROTECT,
        related_name="talhoes",
        null=True,
        blank=True,
    )
    identificacao = models.CharField(max_length=30)
    area_ha = models.DecimalField(max_digits=12, decimal_places=4)
    volume_m3 = models.DecimalField(
        "Volume total (m³)", max_digits=12, decimal_places=3, null=True, blank=True
    )
    inclinacao = models.CharField(
        "Inclinação do terreno",
        max_length=10,
        choices=Inclinacao.choices,
        default=Inclinacao.ATE_5,
    )
    vmi_medicao = models.DecimalField(
        "VMI para medição (m³/árvore)",
        max_digits=8,
        decimal_places=4,
        null=True,
        blank=True,
    )
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    geometria = models.TextField(blank=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["fazenda__nome", "identificacao"]
        verbose_name_plural = "talhões"
        constraints = [
            models.UniqueConstraint(
                fields=["fazenda", "identificacao"], name="talhao_identificacao_fazenda"
            )
        ]

    def __str__(self) -> str:
        return f"{self.fazenda} - {self.identificacao}"

    @property
    def volume_retirado_m3(self) -> Decimal:
        if not self.pk:
            return Decimal("0.000")
        retirado = self.transportes_lenha.aggregate(
            total=models.Sum("volume_m3")
        )["total"]
        return retirado or Decimal("0.000")

    @property
    def saldo_a_retirar_m3(self) -> Decimal | None:
        if self.volume_m3 is None:
            return None
        return self.volume_m3 - self.volume_retirado_m3


class RegimeSabado(models.TextChoices):
    TODOS = "TODOS", "Trabalha todo sábado"
    ALTERNADO = "ALTERNADO", "Um sábado sim, outro não"
    NENHUM = "NENHUM", "Não trabalha aos sábados"


class UPC(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="upcs")
    fazenda = models.ForeignKey(Fazenda, on_delete=models.PROTECT, related_name="upcs")
    nome = models.CharField(max_length=100)
    responsavel_legal = models.CharField(max_length=100, blank=True)
    utm_leste = models.DecimalField(max_digits=12, decimal_places=2)
    utm_norte = models.DecimalField(max_digits=12, decimal_places=2)
    utm_fuso = models.CharField(max_length=4, blank=True)
    ciclo_producao_dias = models.PositiveIntegerField()
    regime_sabado = models.CharField(
        "Sábados",
        max_length=10,
        choices=RegimeSabado.choices,
        default=RegimeSabado.TODOS,
    )
    sabado_referencia = models.DateField(
        "Sábado trabalhado de referência", null=True, blank=True
    )
    trabalha_domingo = models.BooleanField("Trabalha aos domingos", default=False)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "UPC"
        verbose_name_plural = "UPCs"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"], name="upc_nome_por_empresa"
            )
        ]

    def __str__(self) -> str:
        return self.nome

    def dia_de_trabalho(self, dia: date) -> bool:
        """Enchimento e descarga só acontecem nos dias de trabalho da UPC."""
        semana = dia.weekday()
        if semana == 6:
            return self.trabalha_domingo
        if semana != 5:
            return True
        if self.regime_sabado == RegimeSabado.NENHUM:
            return False
        if self.regime_sabado == RegimeSabado.ALTERNADO and self.sabado_referencia:
            return (dia - self.sabado_referencia).days % 14 == 0
        return True

    def proximo_dia_de_trabalho(self, dia: date) -> date:
        for _ in range(60):
            if self.dia_de_trabalho(dia):
                return dia
            dia += timedelta(days=1)
        return dia

    def _fornos_em_uso(self) -> models.QuerySet[Forno]:
        if not self.pk:
            return Forno.objects.none()
        return self.fornos.exclude(situacao=SituacaoForno.DESATIVADO)

    @property
    def numero_fornos(self) -> int:
        """DCF 7.2: fornos que não estão desativados."""
        return self._fornos_em_uso().count()

    @property
    def volume_ciclo_mdc(self) -> Decimal:
        """DCF 7.7: soma da capacidade dos fornos em uso."""
        total = self._fornos_em_uso().aggregate(
            total=models.Sum(
                Coalesce("capacidade_mdc", "tipo_forno__capacidade_mdc")
            )
        )["total"]
        return total or Decimal(0)

    @property
    def volume_mes_mdc(self) -> Decimal:
        if not self.ciclo_producao_dias:
            return Decimal(0)
        return (self.volume_ciclo_mdc * 30 / self.ciclo_producao_dias).quantize(
            Decimal("0.01")
        )


class FormatoForno(models.TextChoices):
    CIRCULAR = "CIRCULAR", "Circular"
    RETANGULAR = "RETANGULAR", "Retangular"


class NivelMecanizacao(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    SEMIMECANIZADO = "SEMIMECANIZADO", "Semimecanizado"
    MECANIZADO = "MECANIZADO", "Mecanizado"


DIAS_CARBONIZACAO_PADRAO = 6
DIAS_RESFRIAMENTO_PADRAO = 6
DIAS_VAZIO_PADRAO = 0


class TipoForno(RegistroAuditavel):
    """Modelo de forno (DCF 7.3 a 7.5)."""

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="tipos_forno"
    )
    nome = models.CharField(max_length=60)
    formato = models.CharField(
        max_length=12, choices=FormatoForno.choices, default=FormatoForno.CIRCULAR
    )
    nivel_mecanizacao = models.CharField(
        max_length=15,
        choices=NivelMecanizacao.choices,
        default=NivelMecanizacao.MANUAL,
    )
    enchimento_mecanizado = models.BooleanField(default=False)
    descarga_mecanizada = models.BooleanField(default=False)
    diametro_m = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    comprimento_m = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    largura_m = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    altura_total_m = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    altura_cilindro_m = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    capacidade_mdc = models.DecimalField(max_digits=10, decimal_places=2)
    capacidade_lenha_mst = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    dias_carbonizacao_previstos = models.PositiveSmallIntegerField(
        "Carbonização prevista (dias)", default=DIAS_CARBONIZACAO_PADRAO
    )
    dias_resfriamento_previstos = models.PositiveSmallIntegerField(
        "Resfriamento previsto (dias)", default=DIAS_RESFRIAMENTO_PADRAO
    )
    dias_vazio_previstos = models.PositiveSmallIntegerField(
        "Dias vazio mínimos entre ciclos",
        default=DIAS_VAZIO_PADRAO,
        help_text=(
            "0: carrega no próximo dia de trabalho depois da descarga. Domingos "
            "e sábados de folga já deixam o forno vazio."
        ),
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "tipo de forno"
        verbose_name_plural = "tipos de forno"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"], name="tipo_forno_nome_por_empresa"
            )
        ]

    def __str__(self) -> str:
        return self.nome


class SituacaoForno(models.TextChoices):
    ATIVO = "ATIVO", "Ativo"
    EM_MANUTENCAO = "EM_MANUTENCAO", "Em manutenção"
    DESATIVADO = "DESATIVADO", "Desativado"


class Forno(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="fornos"
    )
    upc = models.ForeignKey(UPC, on_delete=models.PROTECT, related_name="fornos")
    tipo_forno = models.ForeignKey(
        TipoForno, on_delete=models.PROTECT, related_name="fornos"
    )
    numero = models.CharField(max_length=20)
    data_instalacao = models.DateField(null=True, blank=True)
    capacidade_mdc = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    situacao = models.CharField(
        max_length=15, choices=SituacaoForno.choices, default=SituacaoForno.ATIVO
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["upc__nome", "numero"]
        verbose_name_plural = "fornos"
        constraints = [
            models.UniqueConstraint(
                fields=["upc", "tipo_forno", "numero"],
                name="forno_numero_por_upc_e_tipo",
            )
        ]

    def __str__(self) -> str:
        return f"{self.upc} - {self.identificacao}"

    @property
    def identificacao(self) -> str:
        """Nome do tipo + número (ex.: FCM 01); número com letras fica como está."""
        if self.numero.isdigit() and self.tipo_forno_id:
            return f"{self.tipo_forno.nome} {self.numero}"
        return self.numero

    @property
    def formato(self) -> str:
        return self.tipo_forno.get_formato_display()

    @property
    def capacidade_efetiva_mdc(self) -> Decimal:
        if self.capacidade_mdc is not None:
            return self.capacidade_mdc
        return self.tipo_forno.capacidade_mdc


class SituacaoBox(models.TextChoices):
    ATIVO = "ATIVO", "Ativo"
    INATIVO = "INATIVO", "Inativo"


class BoxLenha(RegistroAuditavel):
    """Box da praça de carbonização onde a lenha do baldeio é depositada."""

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="boxes_lenha"
    )
    upc = models.ForeignKey(UPC, on_delete=models.PROTECT, related_name="boxes_lenha")
    numero = models.CharField(max_length=20)
    descricao = models.CharField(max_length=100, blank=True)
    capacidade_mst = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    situacao = models.CharField(
        max_length=10, choices=SituacaoBox.choices, default=SituacaoBox.ATIVO
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["upc__nome", "numero"]
        verbose_name = "box de lenha"
        verbose_name_plural = "boxes de lenha"
        constraints = [
            models.UniqueConstraint(fields=["upc", "numero"], name="box_numero_por_upc")
        ]

    def __str__(self) -> str:
        return f"{self.upc} - Box {self.numero}"

    @property
    def estoque_mst(self) -> Decimal:
        """Aproximação: lenha entregue no box menos a enchida a partir dele."""
        if not self.pk:
            return Decimal(0)
        entregue = self.transportes_lenha.aggregate(total=models.Sum("volume_mst"))[
            "total"
        ] or Decimal(0)
        enchida = self.ciclos_forno.exclude(
            status=StatusCiclo.CANCELADO
        ).aggregate(total=models.Sum("volume_lenha_enchimento"))["total"] or Decimal(0)
        return entregue - enchida


def _dividir(numerador: Decimal | None, denominador: Decimal | None) -> Decimal | None:
    if numerador is None or not denominador:
        return None
    return Decimal(numerador) / Decimal(denominador)


class InventarioFlorestal(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="inventarios"
    )
    usuario_inclusao = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventarios_incluidos",
        db_column="codigo_usuario",
    )
    fornecedor = models.ForeignKey(
        Fornecedor,
        on_delete=models.PROTECT,
        related_name="inventarios",
        null=True,
        blank=True,
    )
    fazenda = models.ForeignKey(
        Fazenda, on_delete=models.PROTECT, related_name="inventarios"
    )
    plantio = models.ForeignKey(
        Plantio,
        on_delete=models.PROTECT,
        related_name="inventarios",
        null=True,
        blank=True,
    )
    lote = models.CharField(max_length=50)
    data_inventario = models.DateField()
    responsavel_tecnico = models.CharField(max_length=100)
    registro_conselho = models.CharField(max_length=30)
    numero_art = models.CharField(max_length=30)
    area_ha = models.DecimalField(max_digits=12, decimal_places=4)
    numero_talhoes = models.PositiveIntegerField(null=True, blank=True)
    especie = models.CharField(max_length=60, blank=True)
    volume_total = models.DecimalField(max_digits=14, decimal_places=3)
    numero_arvores = models.DecimalField(max_digits=14, decimal_places=2)
    volume_ha = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, editable=False
    )
    numero_arvores_ha = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, editable=False
    )
    vmi = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, editable=False
    )
    dap_medio_cm = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    altura_media_m = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_inventario", "lote"]
        verbose_name = "inventário florestal"
        verbose_name_plural = "inventários florestais"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "fazenda", "lote"], name="inventario_lote_unico"
            )
        ]

    def __str__(self) -> str:
        return f"{self.fazenda} - {self.lote}"

    def volume_st(self) -> Decimal:
        return (self.volume_total * FATOR_MST_POR_M3).quantize(Decimal("0.01"))

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.volume_ha = _dividir(self.volume_total, self.area_ha)
        self.numero_arvores_ha = _dividir(self.numero_arvores, self.area_ha)
        self.vmi = _dividir(self.volume_total, self.numero_arvores)
        super().save(*args, **kwargs)


class OrigemAutorizacao(models.TextChoices):
    EXOTICA = "EXOTICA", "Exótica"
    NATIVA_PLANTADA = "NATIVA_PLANTADA", "Nativa plantada"
    NATIVA = "NATIVA", "Nativa"


class TipoDocumento(models.TextChoices):
    DCF = "DCF", "DCF (floresta plantada)"
    DAIA = "DAIA", "DAIA (floresta nativa)"


class Modalidade(models.TextChoices):
    PRODUCAO = "PRODUCAO", "Produção"
    NOTA_FISCAL = "NOTA_FISCAL", "Nota fiscal"


class BaseVolume(models.TextChoices):
    INVENTARIO = "INVENTARIO", "Inventário"
    IFMG = "IFMG", "Inventário Florestal de Minas Gerais"


class ProdutoAutorizado(models.TextChoices):
    CARVAO_EXOTICA = "CARVAO_EXOTICA", "Carvão de exótica"
    CARVAO_NATIVO = "CARVAO_NATIVO", "Carvão de nativo"
    LENHA = "LENHA", "Lenha"
    MADEIRA = "MADEIRA", "Madeira"


class UnidadeVolume(models.TextChoices):
    MDC = "MDC", "MDC"
    MST = "MST", "MST"
    M3 = "M3", "m³"


class StatusAutorizacao(models.TextChoices):
    PROTOCOLADA = "PROTOCOLADA", "Protocolada"
    ATIVA = "ATIVA", "Ativa"
    VENCIDA = "VENCIDA", "Vencida"
    ESGOTADA = "ESGOTADA", "Esgotada"
    CANCELADA = "CANCELADA", "Cancelada"


class AutorizacaoAmbiental(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="autorizacoes"
    )
    tipo_documento = models.CharField(
        max_length=10, choices=TipoDocumento.choices, default=TipoDocumento.DCF
    )
    origem_floresta = models.CharField(
        max_length=20,
        choices=OrigemAutorizacao.choices,
        default=OrigemAutorizacao.EXOTICA,
    )
    modalidade = models.CharField(
        max_length=15, choices=Modalidade.choices, default=Modalidade.PRODUCAO
    )
    numero = models.CharField(max_length=30)
    fazenda = models.ForeignKey(
        Fazenda,
        on_delete=models.PROTECT,
        related_name="autorizacoes",
        null=True,
        blank=True,
    )
    upcs = models.ManyToManyField(
        UPC,
        related_name="autorizacoes",
        blank=True,
    )
    plantio = models.ForeignKey(
        Plantio,
        on_delete=models.PROTECT,
        related_name="autorizacoes",
        null=True,
        blank=True,
    )
    inventario = models.OneToOneField(
        InventarioFlorestal,
        on_delete=models.PROTECT,
        related_name="autorizacao",
        null=True,
        blank=True,
    )
    base_volume = models.CharField(
        max_length=10, choices=BaseVolume.choices, blank=True
    )
    produto = models.CharField(max_length=20, choices=ProdutoAutorizado.choices)
    unidade_volume = models.CharField(
        max_length=3, choices=UnidadeVolume.choices, default=UnidadeVolume.MDC
    )
    volume_declarado = models.DecimalField(max_digits=14, decimal_places=3)
    volume_base_m3 = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    fator_conversao = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    numero_recibo_sinaflor = models.CharField(max_length=30, blank=True)
    data_emissao = models.DateField()
    data_vencimento = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=12,
        choices=StatusAutorizacao.choices,
        default=StatusAutorizacao.PROTOCOLADA,
    )
    numero_dae_expediente = models.CharField(max_length=20, blank=True)
    valor_taxa_expediente = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    numero_dae_florestal = models.CharField(max_length=20, blank=True)
    valor_taxa_florestal = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    motivo_isencao = models.CharField(max_length=100, blank=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_emissao", "numero"]
        verbose_name = "autorização ambiental"
        verbose_name_plural = "autorizações ambientais"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"], name="autorizacao_numero_por_empresa"
            )
        ]

    def __str__(self) -> str:
        return self.numero

    def lista_upcs(self) -> str:
        return ", ".join(str(upc) for upc in self.upcs.all())

    def volume_em_m3(self) -> Decimal | None:
        if self.unidade_volume == UnidadeVolume.M3:
            return self.volume_declarado
        if self.unidade_volume == UnidadeVolume.MST:
            return (self.volume_declarado / FATOR_MST_POR_M3).quantize(Decimal("0.001"))
        return self.volume_base_m3

    def volume_baixado(self) -> Decimal:
        """Volume já baixado: o aferido na descarga ou, antes dela, o expedido."""
        return self.movimentos.aggregate(total=models.Sum("volume_movimentado"))[
            "total"
        ] or Decimal(0)

    def saldo(self) -> Decimal:
        return self.volume_declarado - self.volume_baixado()


class StatusExpedicao(models.TextChoices):
    EXPEDIDA = "EXPEDIDA", "Em trânsito"
    DESCARREGADA = "DESCARREGADA", "Descarregada"


class Expedicao(RegistroAuditavel):
    """Saída de carvão que baixa o saldo da autorização em duas etapas."""

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="expedicoes"
    )
    autorizacao = models.ForeignKey(
        AutorizacaoAmbiental, on_delete=models.PROTECT, related_name="expedicoes"
    )
    numero_documento = models.CharField(max_length=44)
    data_expedicao = models.DateField()
    cliente = models.CharField(max_length=120)
    placa_veiculo = models.CharField(max_length=10, blank=True)
    volume_expedido = models.DecimalField(max_digits=14, decimal_places=3)
    data_descarga = models.DateField(null=True, blank=True)
    volume_aferido = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    status = models.CharField(
        max_length=12,
        choices=StatusExpedicao.choices,
        default=StatusExpedicao.EXPEDIDA,
        editable=False,
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_expedicao", "numero_documento"]
        verbose_name = "expedição de carvão"
        verbose_name_plural = "expedições de carvão"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero_documento"],
                name="expedicao_documento_por_empresa",
            )
        ]

    def __str__(self) -> str:
        return self.numero_documento

    def volume_baixa(self) -> Decimal:
        if self.volume_aferido is None:
            return self.volume_expedido
        return self.volume_aferido

    def diferenca(self) -> Decimal | None:
        if self.volume_aferido is None:
            return None
        return self.volume_aferido - self.volume_expedido

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.status = (
            StatusExpedicao.EXPEDIDA
            if self.volume_aferido is None
            else StatusExpedicao.DESCARREGADA
        )
        with transaction.atomic():
            super().save(*args, **kwargs)
            AutorizacaoMovimento.objects.update_or_create(
                expedicao=self,
                defaults={
                    "empresa": self.empresa,
                    "autorizacao": self.autorizacao,
                    "tipo_movimento": TipoMovimentoAutorizacao.EXPEDICAO_CARVAO,
                    "data_movimento": self.data_expedicao,
                    "volume_original": self.volume_expedido,
                    "unidade_original": self.autorizacao.unidade_volume,
                    "volume_movimentado": self.volume_baixa(),
                    "usuario_inclusao": self.usuario_inclusao,
                    "usuario_alteracao": self.usuario_alteracao,
                },
            )


class TipoTransporte(models.TextChoices):
    PROPRIO = "PROPRIO", "Próprio"
    TERCEIRIZADO = "TERCEIRIZADO", "Terceirizado"


class DestinoLenha(models.TextChoices):
    UPC = "UPC", "Abastecimento de UPC"
    VENDA = "VENDA", "Venda a terceiros"


class TransporteLenha(RegistroAuditavel):
    """Uma viagem de lenha do talhão até a UPC ou o comprador."""

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="transportes_lenha"
    )
    autorizacao = models.ForeignKey(
        AutorizacaoAmbiental,
        on_delete=models.PROTECT,
        related_name="transportes_lenha",
    )
    talhao = models.ForeignKey(
        Talhao, on_delete=models.PROTECT, related_name="transportes_lenha"
    )
    destino = models.CharField(max_length=5, choices=DestinoLenha.choices)
    upc = models.ForeignKey(
        UPC,
        on_delete=models.PROTECT,
        related_name="transportes_lenha",
        null=True,
        blank=True,
    )
    box_lenha = models.ForeignKey(
        BoxLenha,
        on_delete=models.PROTECT,
        related_name="transportes_lenha",
        null=True,
        blank=True,
    )
    comprador = models.CharField(max_length=120, blank=True)
    tipo_transporte = models.CharField(
        max_length=15, choices=TipoTransporte.choices, default=TipoTransporte.PROPRIO
    )
    fornecedor = models.ForeignKey(
        Fornecedor,
        on_delete=models.PROTECT,
        related_name="transportes_lenha",
        null=True,
        blank=True,
    )
    data_transporte = models.DateField()
    placa_veiculo = models.CharField(max_length=10, blank=True)
    motorista = models.CharField(max_length=80, blank=True)
    numero_documento = models.CharField(max_length=30, blank=True)
    volume_mst = models.DecimalField(max_digits=12, decimal_places=3)
    fator_conversao = models.DecimalField(
        max_digits=6, decimal_places=3, default=FATOR_MST_POR_M3, editable=False
    )
    volume_m3 = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, editable=False
    )
    valor_mst = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    valor_m3 = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    valor_total = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, editable=False
    )
    boletim = models.ForeignKey(
        "BoletimTransporte",
        on_delete=models.SET_NULL,
        related_name="viagens",
        null=True,
        blank=True,
        editable=False,
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_transporte", "-codigo"]
        verbose_name = "transporte de lenha"
        verbose_name_plural = "transportes de lenha"

    def __str__(self) -> str:
        return f"{self.data_transporte:%d/%m/%Y} - {self.talhao}"

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        if self._state.adding:
            self.fator_conversao = ParametroEmpresa.da_empresa(
                self.empresa_id
            ).fator_mst_por_m3
        fator = self.fator_conversao
        self.volume_m3 = (self.volume_mst / fator).quantize(Decimal("0.001"))
        if self.valor_mst is not None:
            self.valor_m3 = (self.valor_mst * fator).quantize(Decimal("0.0001"))
        elif self.valor_m3 is not None:
            self.valor_mst = (self.valor_m3 / fator).quantize(Decimal("0.0001"))
        if self.valor_mst is not None:
            self.valor_total = (self.volume_mst * self.valor_mst).quantize(
                Decimal("0.01")
            )
        super().save(*args, **kwargs)


class StatusCiclo(models.TextChoices):
    ENCHIMENTO = "ENCHIMENTO", "Enchimento"
    CARBONIZACAO = "CARBONIZACAO", "Carbonização"
    RESFRIAMENTO = "RESFRIAMENTO", "Resfriamento"
    DESCARREGADO = "DESCARREGADO", "Descarregado"
    CANCELADO = "CANCELADO", "Cancelado"


# Mesmas letras e textos da legenda do painel dos fornos.
LEGENDA_DO_STATUS = {
    StatusCiclo.ENCHIMENTO: ("L", "Enchido, aguardando acendimento"),
    StatusCiclo.CARBONIZACAO: ("C", "Carbonizando"),
    StatusCiclo.RESFRIAMENTO: ("R", "Resfriando"),
    StatusCiclo.DESCARREGADO: ("D", "Descarga"),
}

STATUS_CICLO_ATIVO = (
    StatusCiclo.ENCHIMENTO,
    StatusCiclo.CARBONIZACAO,
    StatusCiclo.RESFRIAMENTO,
)


class CondicaoTempo(models.TextChoices):
    SECO = "SECO", "Seco"
    CHUVOSO = "CHUVOSO", "Chuvoso"
    MISTO = "MISTO", "Misto"


class TipoExecucao(models.TextChoices):
    PROPRIA = "PROPRIA", "Própria"
    TERCEIRIZADA = "TERCEIRIZADA", "Terceirizada (empreiteiro)"


def _dias_entre(inicio, fim) -> Decimal | None:
    if inicio is None or fim is None:
        return None
    return (Decimal((fim - inicio).total_seconds()) / 86400).quantize(Decimal("0.01"))


class CicloForno(RegistroAuditavel):
    """Um ciclo de um forno: enchimento, carbonização, resfriamento e descarga."""

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="ciclos_forno"
    )
    forno = models.ForeignKey(Forno, on_delete=models.PROTECT, related_name="ciclos")
    numero_ciclo = models.PositiveIntegerField(blank=True)
    status = models.CharField(
        max_length=15, choices=StatusCiclo.choices, default=StatusCiclo.ENCHIMENTO
    )
    data_inicio_enchimento = models.DateTimeField()
    data_acendimento = models.DateTimeField(null=True, blank=True)
    data_fim_carbonizacao = models.DateTimeField(null=True, blank=True)
    data_descarga = models.DateTimeField(null=True, blank=True)
    dias_carbonizacao = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, editable=False
    )
    dias_resfriamento = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, editable=False
    )
    dias_ciclo = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, editable=False
    )
    box_lenha = models.ForeignKey(
        BoxLenha,
        on_delete=models.PROTECT,
        related_name="ciclos_forno",
        null=True,
        blank=True,
    )
    volume_lenha_enchimento = models.DecimalField(
        "Lenha no enchimento (MST)", max_digits=12, decimal_places=3
    )
    fator_conversao = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    volume_lenha_m3 = models.DecimalField(
        "Lenha no enchimento (m³)", max_digits=12, decimal_places=3, editable=False
    )
    volume_mdc = models.DecimalField(
        "Carvão produzido (MDC)", max_digits=12, decimal_places=2, null=True, blank=True
    )
    fator_m3_por_mdc = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, editable=False
    )
    fator_mst_por_mdc = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, editable=False
    )
    condicao_tempo = models.CharField(
        max_length=20, choices=CondicaoTempo.choices, blank=True
    )
    dias_secagem_lenha = models.PositiveIntegerField(null=True, blank=True)
    responsavel_enchimento = models.CharField(max_length=80, blank=True)
    responsavel_descarga = models.CharField(max_length=80, blank=True)
    tipo_execucao = models.CharField(
        max_length=15, choices=TipoExecucao.choices, default=TipoExecucao.PROPRIA
    )
    fornecedor = models.ForeignKey(
        Fornecedor,
        on_delete=models.PROTECT,
        related_name="ciclos_forno",
        null=True,
        blank=True,
    )
    valor_mdc = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    valor_producao = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, editable=False
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_inicio_enchimento", "-codigo"]
        verbose_name = "ciclo de forno"
        verbose_name_plural = "ciclos de forno"
        constraints = [
            models.UniqueConstraint(
                fields=["forno", "numero_ciclo"], name="ciclo_numero_por_forno"
            ),
            models.UniqueConstraint(
                fields=["forno"],
                condition=models.Q(status__in=STATUS_CICLO_ATIVO),
                name="um_ciclo_ativo_por_forno",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.forno} - ciclo {self.numero_ciclo}"

    def status_pelas_datas(self) -> str:
        if self.status == StatusCiclo.CANCELADO:
            return StatusCiclo.CANCELADO
        if self.data_descarga:
            return StatusCiclo.DESCARREGADO
        if self.data_fim_carbonizacao:
            return StatusCiclo.RESFRIAMENTO
        if self.data_acendimento:
            return StatusCiclo.CARBONIZACAO
        return StatusCiclo.ENCHIMENTO

    @property
    def prevista_fim_carbonizacao(self):
        dias = self.forno.tipo_forno.dias_carbonizacao_previstos
        inicio = self.data_acendimento or self.data_inicio_enchimento
        return inicio + timedelta(days=dias)

    @property
    def prevista_descarga(self):
        if self.data_fim_carbonizacao is None:
            return None
        dias = self.forno.tipo_forno.dias_resfriamento_previstos
        return self.data_fim_carbonizacao + timedelta(days=dias)

    @property
    def prevista_da_etapa(self):
        """Quando a etapa atual deve terminar (vazio se o ciclo terminou)."""
        if self.status == StatusCiclo.CARBONIZACAO:
            return self.prevista_fim_carbonizacao
        if self.status == StatusCiclo.RESFRIAMENTO:
            return self.prevista_descarga
        return None

    @property
    def alerta_prazo(self) -> str:
        """ATENÇÃO quando uma etapa passou (ou está passando) do prazo do tipo."""
        agora = timezone.now()
        etapas = (
            (
                self.prevista_fim_carbonizacao,
                self.data_fim_carbonizacao,
                "Carbonização",
            ),
            (self.prevista_descarga, self.data_descarga, "Resfriamento"),
        )
        for prevista, realizada, nome in etapas:
            if prevista is None or self.status == StatusCiclo.CANCELADO:
                continue
            if (realizada or agora) > prevista:
                return f"ATENÇÃO: {nome.lower()} passou do prazo"
        return ""

    @property
    def status_legenda(self) -> str:
        """Status com a marca e o texto da legenda do painel dos fornos."""
        codigo, texto = LEGENDA_DO_STATUS.get(
            self.status, ("", self.get_status_display())
        )
        if not codigo:
            return texto
        return format_html(
            '<span class="estado-celula estado-{}" aria-hidden="true">{}</span> {}',
            codigo,
            codigo,
            texto,
        )

    @property
    def prazo_curto(self) -> str:
        """Alerta de prazo resumido, para a coluna da lista."""
        alerta = self.alerta_prazo
        if not alerta:
            return ""
        texto = (
            "Resfriamento atrasado"
            if "resfriamento" in alerta
            else "Carbonização atrasada"
        )
        return format_html('<span class="prazo-atrasado">⚠ {}</span>', texto)

    def proximo_numero_ciclo(self) -> int:
        ultimo = CicloForno.objects.filter(forno_id=self.forno_id).aggregate(
            maior=models.Max("numero_ciclo")
        )["maior"]
        return (ultimo or 0) + 1

    @property
    def alerta_fator(self) -> str:
        """Compara o MST por MDC do ciclo com o ideal da empresa."""
        if self.fator_mst_por_mdc is None:
            return ""
        parametro = ParametroEmpresa.da_empresa(self.empresa_id)
        ideal = parametro.fator_mst_por_mdc_ideal
        if not ideal:
            return ""
        desvio_pct = (self.fator_mst_por_mdc - ideal) / ideal * 100
        if desvio_pct > parametro.tolerancia_efetiva_pct:
            return "Consumo de lenha acima do ideal"
        if desvio_pct < -parametro.tolerancia_efetiva_pct:
            return "Consumo de lenha abaixo do ideal"
        return ""

    @property
    def forno_curto(self) -> str:
        return self.forno.identificacao

    @property
    def alerta_fator_curto(self) -> str:
        """Alerta de consumo de lenha em etiqueta, para a coluna da lista."""
        alerta = self.alerta_fator
        if not alerta:
            return ""
        texto = "Lenha acima do ideal" if "acima" in alerta else "Lenha abaixo do ideal"
        return format_html('<span class="alerta-fator">⚠ {}</span>', texto)

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        if not self.numero_ciclo:
            self.numero_ciclo = self.proximo_numero_ciclo()
        if self.fator_conversao is None:
            self.fator_conversao = ParametroEmpresa.da_empresa(
                self.empresa_id
            ).fator_mst_por_m3
        # Em geral o forno é aceso ao terminar o enchimento; em branco, é a mesma
        # data e hora.
        if self.data_acendimento is None:
            self.data_acendimento = self.data_inicio_enchimento
        if (
            self.tipo_execucao == TipoExecucao.TERCEIRIZADA
            and self.valor_mdc is None
        ):
            tarifa = FornecedorTarifa.vigente(
                self.fornecedor_id,
                TipoServico.CARBONIZACAO,
                timezone.localdate(self.data_inicio_enchimento),
            )
            if tarifa is not None and tarifa.unidade == UnidadeTarifa.MDC:
                self.valor_mdc = tarifa.valor
        self.status = self.status_pelas_datas()
        self.dias_carbonizacao = _dias_entre(
            self.data_acendimento, self.data_fim_carbonizacao
        )
        self.dias_resfriamento = _dias_entre(
            self.data_fim_carbonizacao, self.data_descarga
        )
        self.dias_ciclo = _dias_entre(self.data_inicio_enchimento, self.data_descarga)
        self.volume_lenha_m3 = (
            self.volume_lenha_enchimento / self.fator_conversao
        ).quantize(Decimal("0.001"))
        if self.volume_mdc:
            self.fator_m3_por_mdc = (
                self.volume_lenha_enchimento / self.fator_conversao / self.volume_mdc
            ).quantize(Decimal("0.0001"))
            self.fator_mst_por_mdc = (
                self.volume_lenha_enchimento / self.volume_mdc
            ).quantize(Decimal("0.0001"))
        else:
            self.fator_m3_por_mdc = self.fator_mst_por_mdc = None
        self.valor_producao = None
        if (
            self.tipo_execucao == TipoExecucao.TERCEIRIZADA
            and self.volume_mdc is not None
            and self.valor_mdc is not None
        ):
            self.valor_producao = (self.volume_mdc * self.valor_mdc).quantize(
                Decimal("0.01")
            )
        super().save(*args, **kwargs)


class PlanejamentoForno(RegistroAuditavel):
    """Planejado (PL) de um forno no mês.

    Guarda o primeiro enchimento previsto no mês; a partir dele os ciclos são
    projetados pelos prazos do tipo do forno (carbonização, resfriamento e
    dias vazio até o novo enchimento).
    """

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="planejamentos_forno"
    )
    forno = models.ForeignKey(
        Forno, on_delete=models.CASCADE, related_name="planejamentos"
    )
    mes = models.DateField("Mês", editable=False)
    data_primeiro_enchimento = models.DateField("Primeiro enchimento previsto")
    mdc_previsto = models.DecimalField(
        "MDC previsto por ciclo",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-mes", "forno__upc__nome", "forno__numero"]
        verbose_name = "planejamento de forno"
        verbose_name_plural = "planejamentos de forno"
        constraints = [
            models.UniqueConstraint(
                fields=["forno", "mes"], name="planejamento_forno_por_mes"
            )
        ]

    def __str__(self) -> str:
        return f"{self.forno} - {self.mes:%m/%Y}"

    @property
    def mdc_por_ciclo(self) -> Decimal:
        return self.mdc_previsto or self.forno.capacidade_efetiva_mdc

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.mes = self.data_primeiro_enchimento.replace(day=1)
        super().save(*args, **kwargs)


class Colheita(RegistroAuditavel):
    """Lançamento diário de uma etapa da colheita num talhão.

    O lançamento do dia é o volume (m³) feito na etapa; o pagamento costuma ser
    por área, estimada por volume ÷ rendimento (m³/ha) quando não informada.
    Por etapa, a soma dos volumes não passa do volume inventariado do talhão.
    """

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="colheitas"
    )
    inventario = models.ForeignKey(
        InventarioFlorestal, on_delete=models.PROTECT, related_name="colheitas"
    )
    talhao = models.ForeignKey(
        Talhao, on_delete=models.PROTECT, related_name="colheitas"
    )
    autorizacao = models.ForeignKey(
        AutorizacaoAmbiental,
        on_delete=models.PROTECT,
        related_name="colheitas",
        null=True,
        blank=True,
    )
    etapa = models.CharField(
        max_length=20,
        choices=EtapaColheita.choices,
        default=EtapaColheita.CORTE_FELLER,
    )
    sistema = models.CharField(
        max_length=12,
        choices=SistemaColheita.choices,
        default=SistemaColheita.MECANIZADA,
        editable=False,
    )
    tipo_execucao = models.CharField(
        max_length=15, choices=TipoExecucao.choices, default=TipoExecucao.TERCEIRIZADA
    )
    fornecedor = models.ForeignKey(
        Fornecedor,
        on_delete=models.PROTECT,
        related_name="colheitas",
        null=True,
        blank=True,
    )
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    area_ha = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    rendimento_m3_ha = models.DecimalField(
        "Rendimento (m³/ha)",
        max_digits=12,
        decimal_places=3,
        null=True,
        editable=False,
    )
    volume_m3 = models.DecimalField(
        "Volume colhido (m³)",
        max_digits=14,
        decimal_places=3,
        null=True,
        blank=True,
    )
    unidade_pagamento = models.CharField(
        max_length=10,
        choices=[(u.value, u.label) for u in UNIDADES_DA_COLHEITA],
        default=UnidadeTarifa.HA,
    )
    valor_unitario = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    valor_total = models.DecimalField(
        "Valor a pagar", max_digits=14, decimal_places=2, null=True, editable=False
    )
    boletim = models.ForeignKey(
        "BoletimMedicao",
        on_delete=models.SET_NULL,
        related_name="lancamentos",
        null=True,
        blank=True,
        editable=False,
    )
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_inicio", "-codigo"]
        verbose_name = "colheita"
        verbose_name_plural = "colheitas"

    def __str__(self) -> str:
        return f"{self.talhao} - {self.get_etapa_display()}"

    @staticmethod
    def rendimento_do_talhao(
        talhao: Talhao, inventario: InventarioFlorestal | None = None
    ) -> Decimal | None:
        """m³/ha: inventário do talhão, senão volume do talhão, senão inventário."""
        if inventario is not None:
            por_talhao = (
                InventarioTalhao.objects.filter(inventario=inventario, talhao=talhao)
                .values_list("volume_ha", flat=True)
                .first()
            )
            if por_talhao:
                return por_talhao
        if talhao.volume_m3 is not None and talhao.area_ha:
            return (talhao.volume_m3 / talhao.area_ha).quantize(Decimal("0.001"))
        if inventario is not None and inventario.volume_ha:
            return inventario.volume_ha
        return None

    @staticmethod
    def volume_do_talhao(
        talhao: Talhao, inventario: InventarioFlorestal | None = None
    ) -> Decimal | None:
        """Volume inventariado (IFPC): do inventário do talhão, senão do talhão."""
        if inventario is not None:
            volume = (
                InventarioTalhao.objects.filter(inventario=inventario, talhao=talhao)
                .values_list("volume_total", flat=True)
                .first()
            )
            if volume:
                return volume
        if talhao.volume_m3 is not None:
            return talhao.volume_m3
        rendimento = Colheita.rendimento_do_talhao(talhao, inventario)
        return (rendimento * talhao.area_ha) if rendimento else None

    @staticmethod
    def volume_ja_feito(
        talhao_id: int, etapa: str, exceto: int | None = None
    ) -> Decimal:
        """Volume do talhão já lançado nesta etapa."""
        colheitas = Colheita.objects.filter(talhao_id=talhao_id, etapa=etapa)
        if exceto is not None:
            colheitas = colheitas.exclude(pk=exceto)
        total = colheitas.aggregate(total=models.Sum("volume_m3"))["total"]
        return (total or Decimal(0)).quantize(Decimal("0.001"))

    def volume_a_fazer(self) -> Decimal | None:
        """Saldo do talhão nesta etapa, em m³, depois de todos os lançamentos."""
        total = self.volume_do_talhao(self.talhao, self.inventario)
        if total is None:
            return None
        return total - self.volume_ja_feito(self.talhao_id, self.etapa)

    @staticmethod
    def area_ja_colhida(
        talhao_id: int, etapa: str, exceto: int | None = None
    ) -> Decimal:
        """Área do talhão já lançada nesta etapa."""
        colheitas = Colheita.objects.filter(talhao_id=talhao_id, etapa=etapa)
        if exceto is not None:
            colheitas = colheitas.exclude(pk=exceto)
        total = colheitas.aggregate(total=models.Sum("area_ha"))["total"]
        return (total or Decimal(0)).quantize(Decimal("0.0001"))


    def quantidade_paga(self) -> Decimal | None:
        if self.unidade_pagamento == UnidadeTarifa.HA:
            return self.area_ha
        if self.volume_m3 is None:
            return None
        if self.volume_m3 is None:
            return None
        if self.unidade_pagamento == UnidadeTarifa.MST:
            fator = ParametroEmpresa.da_empresa(self.empresa_id).fator_mst_por_m3
            return self.volume_m3 * fator
        return self.volume_m3

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.sistema = SISTEMA_DA_ETAPA[EtapaColheita(self.etapa)]
        if self.tipo_execucao == TipoExecucao.PROPRIA:
            self.fornecedor = None
        self.rendimento_m3_ha = self.rendimento_do_talhao(self.talhao, self.inventario)
        rendimento = self.rendimento_m3_ha
        if self.volume_m3 is None and self.area_ha is not None and rendimento:
            self.volume_m3 = (self.area_ha * rendimento).quantize(Decimal("0.001"))
        if self.area_ha is None and self.volume_m3 is not None and rendimento:
            self.area_ha = (self.volume_m3 / rendimento).quantize(Decimal("0.0001"))
        quantidade = self.quantidade_paga()
        self.valor_total = None
        if quantidade is not None and self.valor_unitario is not None:
            self.valor_total = (quantidade * self.valor_unitario).quantize(
                Decimal("0.01")
            )
        super().save(*args, **kwargs)


class InventarioTalhao(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="inventarios_talhao"
    )
    inventario = models.ForeignKey(
        InventarioFlorestal, on_delete=models.PROTECT, related_name="talhoes"
    )
    talhao = models.ForeignKey(
        Talhao, on_delete=models.PROTECT, related_name="inventarios"
    )
    area_ha = models.DecimalField(max_digits=12, decimal_places=4)
    volume_total = models.DecimalField(max_digits=14, decimal_places=3)
    numero_arvores = models.DecimalField(max_digits=14, decimal_places=2)
    volume_ha = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, editable=False
    )
    vmi = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, editable=False
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["inventario", "talhao__identificacao"]
        verbose_name = "inventário por talhão"
        verbose_name_plural = "inventários por talhão"
        constraints = [
            models.UniqueConstraint(
                fields=["inventario", "talhao"], name="inventario_talhao_unico"
            )
        ]

    def __str__(self) -> str:
        return f"{self.inventario} - {self.talhao.identificacao}"

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.volume_ha = _dividir(self.volume_total, self.area_ha)
        self.vmi = _dividir(self.volume_total, self.numero_arvores)
        super().save(*args, **kwargs)




# Etapas que o boletim de medição paga e a coluna de preço de cada uma.
ETAPAS_DO_BOLETIM = (
    (EtapaColheita.CORTE_FELLER, "derrubada", "Derrubada"),
    (EtapaColheita.ARRASTE, "arraste", "Arraste"),
    (EtapaColheita.TRACAMENTO, "tracamento", "Traçamento"),
)


class TabelaPrecoColheita(RegistroAuditavel):
    """Preços da colheita de um empreiteiro, por faixa de VMI e inclinação."""

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="tabelas_preco_colheita"
    )
    fornecedor = models.ForeignKey(
        Fornecedor, on_delete=models.PROTECT, related_name="tabelas_preco_colheita"
    )
    vigencia_inicio = models.DateField()
    vigencia_fim = models.DateField(null=True, blank=True)
    comprimento_tora_ate_5 = models.DecimalField(
        "Tora traçada até 5% (m)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    comprimento_tora_acima_5 = models.DecimalField(
        "Tora traçada acima de 5% (m)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["fornecedor__nome_razao_social", "-vigencia_inicio"]
        verbose_name = "tabela de preço da colheita"
        verbose_name_plural = "tabelas de preço da colheita"

    def __str__(self) -> str:
        return f"{self.fornecedor} - desde {self.vigencia_inicio:%d/%m/%Y}"

    @classmethod
    def vigente(cls, fornecedor_id: int, data) -> TabelaPrecoColheita | None:
        return (
            cls.objects.filter(fornecedor_id=fornecedor_id, vigencia_inicio__lte=data)
            .filter(
                models.Q(vigencia_fim__isnull=True) | models.Q(vigencia_fim__gte=data)
            )
            .order_by("-vigencia_inicio")
            .first()
        )

    def faixa(self, inclinacao: str, vmi: Decimal | None) -> FaixaPrecoColheita | None:
        """A faixa de maior VMI mínimo que não passa do VMI do talhão."""
        if vmi is None:
            return None
        return (
            self.faixas.filter(inclinacao=inclinacao, vmi_minimo__lte=vmi)
            .order_by("-vmi_minimo")
            .first()
        )

    def comprimento_tora(self, inclinacao: str) -> Decimal | None:
        if inclinacao == Inclinacao.ACIMA_5:
            return self.comprimento_tora_acima_5
        return self.comprimento_tora_ate_5

    def quantidade_faixas(self) -> int:
        return self.faixas.count()


class FaixaPrecoColheita(models.Model):
    """Uma linha da tabela: a partir de um VMI, o R$/m³ de cada etapa."""

    codigo = models.BigAutoField(primary_key=True)
    tabela = models.ForeignKey(
        TabelaPrecoColheita, on_delete=models.CASCADE, related_name="faixas"
    )
    inclinacao = models.CharField(max_length=10, choices=Inclinacao.choices)
    vmi_minimo = models.DecimalField(max_digits=8, decimal_places=4)
    preco_derrubada = models.DecimalField(max_digits=10, decimal_places=4)
    preco_arraste = models.DecimalField(max_digits=10, decimal_places=4)
    preco_tracamento = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        ordering = ["inclinacao", "-vmi_minimo"]
        constraints = [
            models.UniqueConstraint(
                fields=["tabela", "inclinacao", "vmi_minimo"],
                name="faixa_preco_colheita_unica",
            )
        ]

    def preco(self, chave: str) -> Decimal:
        return getattr(self, f"preco_{chave}")


class StatusBoletim(models.TextChoices):
    ABERTO = "ABERTO", "Aberto"
    FECHADO = "FECHADO", "Fechado"
    PAGO = "PAGO", "Pago"
    CANCELADO = "CANCELADO", "Cancelado"


class BoletimMedicao(RegistroAuditavel):
    """Fechamento da colheita de um empreiteiro (Boletim de Medição)."""

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="boletins_medicao"
    )
    fornecedor = models.ForeignKey(
        Fornecedor, on_delete=models.PROTECT, related_name="boletins_medicao"
    )
    data_emissao = models.DateField("Emissão")
    periodo_inicio = models.DateField("Lançamentos de")
    periodo_fim = models.DateField("até")
    tabela = models.ForeignKey(
        TabelaPrecoColheita,
        on_delete=models.PROTECT,
        related_name="boletins",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=10, choices=StatusBoletim.choices, default=StatusBoletim.ABERTO
    )
    elaborado_por = models.CharField(max_length=100, blank=True)
    validado_por = models.CharField(max_length=100, blank=True)
    data_pagamento = models.DateField(null=True, blank=True)
    valor_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, editable=False
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_emissao", "-codigo"]
        verbose_name = "boletim de medição"
        verbose_name_plural = "boletins de medição"

    def __str__(self) -> str:
        return f"{self.fornecedor} - {self.data_emissao:%d/%m/%Y}"

    @property
    def editavel(self) -> bool:
        return self.status == StatusBoletim.ABERTO

    def fazendas(self) -> str:
        fazendas = {
            item.talhao.fazenda.pk: item.talhao.fazenda.nome_curto
            for item in self.itens.select_related("talhao__fazenda")
        }
        return " / ".join(sorted(fazendas.values()))

    def gerar_itens(self) -> None:
        """Agrupa por talhão e etapa os lançamentos do período ainda sem boletim."""
        self.tabela = TabelaPrecoColheita.vigente(self.fornecedor_id, self.data_emissao)
        etapas = [etapa for etapa, _, _ in ETAPAS_DO_BOLETIM]
        colheitas = Colheita.objects.filter(
            empresa_id=self.empresa_id,
            fornecedor_id=self.fornecedor_id,
            boletim__isnull=True,
            etapa__in=etapas,
            data_inicio__range=(self.periodo_inicio, self.periodo_fim),
        ).select_related("talhao", "inventario")
        grupos: dict[tuple[int, str], list[Colheita]] = {}
        for colheita in colheitas:
            grupos.setdefault((colheita.talhao_id, colheita.etapa), []).append(colheita)
        for (_, etapa), lancamentos in grupos.items():
            primeiro = lancamentos[0]
            item = ItemBoletim(
                boletim=self,
                talhao=primeiro.talhao,
                etapa=etapa,
                inclinacao=primeiro.talhao.inclinacao,
                vmi=primeiro.talhao.vmi_medicao or _vmi_do_inventario(primeiro),
                volume_inventario_ha=Colheita.rendimento_do_talhao(
                    primeiro.talhao, primeiro.inventario
                ),
                area_ha=sum((c.area_ha or Decimal(0) for c in lancamentos), Decimal(0)),
            )
            item.save()
            Colheita.objects.filter(pk__in=[c.pk for c in lancamentos]).update(
                boletim=self
            )
        self.recalcular()

    def recalcular(self) -> None:
        for item in self.itens.all():
            item.save()
        total = self.itens.aggregate(total=models.Sum("valor"))["total"]
        self.valor_total = total or Decimal(0)
        BoletimMedicao.objects.filter(pk=self.pk).update(
            tabela=self.tabela, valor_total=self.valor_total
        )

    def liberar_lancamentos(self) -> None:
        Colheita.objects.filter(boletim=self).update(boletim=None)


def _vmi_do_inventario(colheita: Colheita) -> Decimal | None:
    por_talhao = (
        InventarioTalhao.objects.filter(
            inventario=colheita.inventario, talhao=colheita.talhao
        )
        .values_list("vmi", flat=True)
        .first()
    )
    return por_talhao or colheita.inventario.vmi


class ItemBoletim(models.Model):
    """Linha do boletim: um talhão numa etapa."""

    codigo = models.BigAutoField(primary_key=True)
    boletim = models.ForeignKey(
        BoletimMedicao, on_delete=models.CASCADE, related_name="itens"
    )
    talhao = models.ForeignKey(Talhao, on_delete=models.PROTECT, related_name="+")
    etapa = models.CharField(max_length=20, choices=EtapaColheita.choices)
    inclinacao = models.CharField(max_length=10, choices=Inclinacao.choices)
    vmi = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    volume_inventario_ha = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    area_ha = models.DecimalField(max_digits=12, decimal_places=4)
    volume_m3 = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    preco_m3 = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["talhao__fazenda__nome", "talhao__identificacao", "etapa"]

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        # Valor com o volume sem arredondar, como a planilha (Excel).
        volume = (
            self.area_ha * self.volume_inventario_ha
            if self.volume_inventario_ha
            else Decimal(0)
        )
        self.volume_m3 = volume.quantize(Decimal("0.001"))
        tabela = self.boletim.tabela
        chave = {etapa: coluna for etapa, coluna, _ in ETAPAS_DO_BOLETIM}.get(
            self.etapa
        )
        faixa = tabela.faixa(self.inclinacao, self.vmi) if tabela and chave else None
        self.preco_m3 = faixa.preco(chave) if faixa else None
        self.valor = (
            (volume * self.preco_m3).quantize(Decimal("0.01"))
            if self.preco_m3 is not None
            else Decimal(0)
        )
        super().save(*args, **kwargs)

class TipoCentroCusto(models.TextChoices):
    UPC = "UPC", "UPC"
    COLHEITA = "COLHEITA", "Colheita"
    TRANSPORTE_PROPRIO_LENHA = "TRANSPORTE_PROPRIO_LENHA", "Transporte próprio (lenha)"
    TRANSPORTE_PROPRIO_CARVAO = (
        "TRANSPORTE_PROPRIO_CARVAO",
        "Transporte próprio (carvão)",
    )
    ADMINISTRATIVO = "ADMINISTRATIVO", "Administrativo"
    OUTRO = "OUTRO", "Outro"


class CentroCusto(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="centros_custo"
    )
    nome = models.CharField(max_length=80)
    tipo = models.CharField(max_length=30, choices=TipoCentroCusto)
    upc = models.ForeignKey(
        UPC,
        on_delete=models.PROTECT,
        related_name="centros_custo",
        null=True,
        blank=True,
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "centro de custo"
        verbose_name_plural = "centros de custo"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"], name="centro_custo_nome_por_empresa"
            )
        ]

    def __str__(self) -> str:
        return self.nome


class GrupoCusto(models.TextChoices):
    LENHA = "LENHA", "Lenha"
    MAO_DE_OBRA = "MAO_DE_OBRA", "Mão de obra"
    ALIMENTACAO = "ALIMENTACAO", "Alimentação"
    COMBUSTIVEL = "COMBUSTIVEL", "Combustível"
    PECAS = "PECAS", "Peças"
    MANUTENCAO = "MANUTENCAO", "Manutenção"
    CONSULTORIA = "CONSULTORIA", "Consultoria"
    FRETE_CARVAO = "FRETE_CARVAO", "Frete do carvão"
    ADMINISTRATIVO = "ADMINISTRATIVO", "Administrativo"
    OUTROS = "OUTROS", "Outros"


class TipoCusto(models.TextChoices):
    FIXO = "FIXO", "Fixo"
    VARIAVEL = "VARIAVEL", "Variável"


class CategoriaCusto(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="categorias_custo"
    )
    nome = models.CharField(max_length=80)
    grupo = models.CharField(max_length=20, choices=GrupoCusto)
    tipo_custo = models.CharField(
        max_length=10, choices=TipoCusto, blank=True, default=""
    )
    categoria_pai = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="subcategorias",
        null=True,
        blank=True,
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["grupo", "nome"]
        verbose_name = "categoria de custo"
        verbose_name_plural = "categorias de custo"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"], name="categoria_custo_nome_por_empresa"
            )
        ]

    def __str__(self) -> str:
        return self.nome


class TipoEquipamento(models.TextChoices):
    CAMINHAO = "CAMINHAO", "Caminhão"
    TRATOR = "TRATOR", "Trator"
    CARREGADEIRA = "CARREGADEIRA", "Carregadeira"
    MOTOSSERRA = "MOTOSSERRA", "Motosserra"
    VEICULO_LEVE = "VEICULO_LEVE", "Veículo leve"
    OUTRO = "OUTRO", "Outro"


class PropriedadeEquipamento(models.TextChoices):
    PROPRIO = "PROPRIO", "Próprio"
    ALUGADO = "ALUGADO", "Alugado"


class Equipamento(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="equipamentos"
    )
    descricao = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TipoEquipamento)
    placa = models.CharField(max_length=10, blank=True)
    propriedade = models.CharField(max_length=10, choices=PropriedadeEquipamento)
    centro_custo = models.ForeignKey(
        CentroCusto,
        on_delete=models.PROTECT,
        related_name="equipamentos",
        null=True,
        blank=True,
    )
    capacidade_mst = models.DecimalField(
        "Capacidade (MST)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    capacidade_mdc = models.DecimalField(
        "Capacidade (MDC)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    consumo_medio_km_l = models.DecimalField(
        "Consumo médio (km/l)", max_digits=6, decimal_places=2, null=True, blank=True
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["descricao"]
        verbose_name_plural = "equipamentos"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "placa"],
                condition=~models.Q(placa=""),
                name="equipamento_placa_por_empresa",
            )
        ]

    def __str__(self) -> str:
        return self.descricao


class Cliente(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="clientes"
    )
    nome_razao_social = models.CharField(max_length=150)
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=18)
    inscricao_estadual = models.CharField(max_length=20, blank=True)
    endereco = models.CharField(max_length=150, blank=True)
    bairro = models.CharField(max_length=60, blank=True)
    municipio = models.ForeignKey(
        Municipio,
        on_delete=models.PROTECT,
        related_name="clientes",
        null=True,
        blank=True,
    )
    cep = models.CharField(max_length=9, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(max_length=100, blank=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nome_razao_social"]
        verbose_name_plural = "clientes"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "cpf_cnpj"], name="cliente_doc_por_empresa"
            )
        ]

    def __str__(self) -> str:
        return self.nome_razao_social


class TipoMovimentoAutorizacao(models.TextChoices):
    TRANSPORTE = "TRANSPORTE", "Transporte de lenha"
    VENDA = "VENDA", "Venda de lenha"
    EXPEDICAO_CARVAO = "EXPEDICAO_CARVAO", "Expedição de carvão"
    AJUSTE = "AJUSTE", "Ajuste"
    ESTORNO = "ESTORNO", "Estorno"


class AutorizacaoMovimento(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="movimentos_autorizacao"
    )
    autorizacao = models.ForeignKey(
        AutorizacaoAmbiental,
        on_delete=models.PROTECT,
        related_name="movimentos",
    )
    tipo_movimento = models.CharField(
        max_length=20, choices=TipoMovimentoAutorizacao.choices
    )
    data_movimento = models.DateField()
    transporte = models.ForeignKey(
        TransporteLenha,
        on_delete=models.PROTECT,
        related_name="movimentos_autorizacao",
        null=True,
        blank=True,
    )
    expedicao = models.OneToOneField(
        Expedicao,
        on_delete=models.CASCADE,
        related_name="movimento_autorizacao",
        null=True,
        blank=True,
    )
    volume_original = models.DecimalField(max_digits=14, decimal_places=3)
    unidade_original = models.CharField(max_length=3, choices=UnidadeVolume.choices)
    fator_conversao = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    volume_movimentado = models.DecimalField(max_digits=14, decimal_places=3)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_movimento", "-codigo"]
        verbose_name = "movimento de autorização"
        verbose_name_plural = "movimentos de autorização"

    def __str__(self) -> str:
        return f"{self.autorizacao} - {self.get_tipo_movimento_display()}"


class LancamentoCusto(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="lancamentos_custo"
    )
    data_lancamento = models.DateField()
    competencia = models.DateField(
        help_text="Primeiro dia do mês a que o custo pertence."
    )
    centro_custo = models.ForeignKey(
        CentroCusto, on_delete=models.PROTECT, related_name="lancamentos"
    )
    categoria = models.ForeignKey(
        CategoriaCusto, on_delete=models.PROTECT, related_name="lancamentos"
    )
    fornecedor = models.ForeignKey(
        Fornecedor,
        on_delete=models.PROTECT,
        related_name="lancamentos_custo",
        null=True,
        blank=True,
    )
    equipamento = models.ForeignKey(
        Equipamento,
        on_delete=models.PROTECT,
        related_name="lancamentos",
        null=True,
        blank=True,
    )
    descricao = models.CharField(max_length=150)
    quantidade = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    unidade = models.CharField(max_length=10, blank=True)
    valor_unitario = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)
    numero_documento = models.CharField(max_length=30, blank=True)
    data_pagamento = models.DateField(null=True, blank=True)
    rateado = models.BooleanField(default=False)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_lancamento", "-codigo"]
        verbose_name = "lançamento de custo"
        verbose_name_plural = "lançamentos de custo"

    def __str__(self) -> str:
        return f"{self.descricao} - {self.valor_total}"

    @property
    def situacao_pagamento(self) -> str:
        return "Pago" if self.data_pagamento else "A pagar"

    @property
    def percentual_rateado(self) -> Decimal:
        total = self.rateios.aggregate(soma=models.Sum("percentual"))["soma"]
        return total or Decimal(0)

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.competencia = self.competencia.replace(day=1)
        super().save(*args, **kwargs)
        for rateio in self.rateios.all():
            rateio.save()


class LancamentoCustoRateio(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="rateios_custo"
    )
    lancamento = models.ForeignKey(
        LancamentoCusto, on_delete=models.PROTECT, related_name="rateios"
    )
    centro_custo = models.ForeignKey(
        CentroCusto, on_delete=models.PROTECT, related_name="rateios"
    )
    percentual = models.DecimalField(max_digits=7, decimal_places=4)
    valor = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False, default=Decimal(0)
    )

    class Meta:
        ordering = ["lancamento", "centro_custo"]
        verbose_name = "rateio de custo"
        verbose_name_plural = "rateios de custo"
        constraints = [
            models.UniqueConstraint(
                fields=["lancamento", "centro_custo"],
                name="rateio_centro_por_lancamento",
            )
        ]

    def __str__(self) -> str:
        return f"{self.lancamento} - {self.centro_custo} ({self.percentual}%)"

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.valor = (
            self.lancamento.valor_total * self.percentual / Decimal(100)
        ).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
        if not self.lancamento.rateado:
            self.lancamento.rateado = True
            self.lancamento.save(update_fields=["rateado"])


class BoletimTransporte(RegistroAuditavel):
    """Fechamento do frete de lenha de uma transportadora, por período."""

    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="boletins_transporte"
    )
    fornecedor = models.ForeignKey(
        Fornecedor, on_delete=models.PROTECT, related_name="boletins_transporte"
    )
    data_emissao = models.DateField("Emissão")
    periodo_inicio = models.DateField("Viagens de")
    periodo_fim = models.DateField("até")
    status = models.CharField(
        max_length=10, choices=StatusBoletim.choices, default=StatusBoletim.ABERTO
    )
    valor_desconto = models.DecimalField(
        "Desconto (R$)", max_digits=12, decimal_places=2, default=0
    )
    motivo_desconto = models.CharField(max_length=100, blank=True)
    valor_adiantamento = models.DecimalField(
        "Adiantamento já pago (R$)", max_digits=12, decimal_places=2, default=0
    )
    elaborado_por = models.CharField(max_length=100, blank=True)
    validado_por = models.CharField(max_length=100, blank=True)
    data_pagamento = models.DateField(null=True, blank=True)
    total_viagens = models.PositiveIntegerField(default=0, editable=False)
    total_mst = models.DecimalField(
        max_digits=14, decimal_places=3, default=0, editable=False
    )
    valor_bruto = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, editable=False
    )
    valor_liquido = models.DecimalField(
        "Líquido a pagar", max_digits=14, decimal_places=2, default=0, editable=False
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_emissao", "-codigo"]
        verbose_name = "boletim de transporte"
        verbose_name_plural = "boletins de transporte"

    def __str__(self) -> str:
        return f"{self.fornecedor} - {self.data_emissao:%d/%m/%Y}"

    @property
    def editavel(self) -> bool:
        return self.status == StatusBoletim.ABERTO

    def viagens_disponiveis(self) -> models.QuerySet[TransporteLenha]:
        return TransporteLenha.objects.filter(
            empresa_id=self.empresa_id,
            fornecedor_id=self.fornecedor_id,
            tipo_transporte=TipoTransporte.TERCEIRIZADO,
            boletim__isnull=True,
            data_transporte__range=(self.periodo_inicio, self.periodo_fim),
        )

    def gerar(self) -> None:
        """Traz as viagens do período; sem valor, usa a tarifa vigente."""
        for viagem in self.viagens_disponiveis():
            if viagem.valor_mst is None and viagem.valor_m3 is None:
                tarifa = FornecedorTarifa.vigente(
                    self.fornecedor_id,
                    TipoServico.TRANSPORTE_LENHA,
                    viagem.data_transporte,
                )
                if tarifa is not None and tarifa.unidade == UnidadeTarifa.MST:
                    viagem.valor_mst = tarifa.valor
                elif tarifa is not None and tarifa.unidade == UnidadeTarifa.M3:
                    viagem.valor_m3 = tarifa.valor
            viagem.boletim = self
            viagem.save()
        self.recalcular()

    def recalcular(self) -> None:
        soma = self.viagens.aggregate(
            quantidade=models.Count("pk"),
            mst=models.Sum("volume_mst"),
            valor=models.Sum("valor_total"),
        )
        self.total_viagens = soma["quantidade"] or 0
        self.total_mst = soma["mst"] or Decimal(0)
        self.valor_bruto = soma["valor"] or Decimal(0)
        self.valor_liquido = (
            self.valor_bruto - self.valor_desconto - self.valor_adiantamento
        )
        BoletimTransporte.objects.filter(pk=self.pk).update(
            total_viagens=self.total_viagens,
            total_mst=self.total_mst,
            valor_bruto=self.valor_bruto,
            valor_liquido=self.valor_liquido,
        )

    def liberar_viagens(self) -> None:
        TransporteLenha.objects.filter(boletim=self).update(boletim=None)

    def viagens_sem_valor(self) -> int:
        return self.viagens.filter(valor_total__isnull=True).count()
