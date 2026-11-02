from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models, transaction
from django.utils import timezone

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
    ADMINISTRADOR = "admin", "Administrador do sistema"
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

    empresa = models.ForeignKey(
        "Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="usuarios",
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

    def upcs_permitidas(self):
        # Sem UPCs vinculadas, o gestor atende todas as UPCs da empresa.
        if self.empresa_id is None:
            return UPC.objects.none()
        permitidas = UPC.objects.filter(empresa_id=self.empresa_id)
        if self.pk and self.upcs.exists():
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


class Empresa(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    tipo = models.CharField(
        max_length=6, choices=TipoEmpresa.choices, default=TipoEmpresa.MATRIZ
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

    class Meta:
        ordering = ["razao_social"]
        verbose_name_plural = "empresas"

    def __str__(self) -> str:
        return self.nome_fantasia or self.razao_social

    @property
    def tipo_exibicao(self) -> str:
        if self.tipo == TipoEmpresa.FILIAL and self.descricao_filial:
            return self.descricao_filial
        return self.get_tipo_display()

    @property
    def identificacao(self) -> str:
        local = f"{self.municipio.nome}/{self.municipio.estado.uf}"
        return f"{self} · {self.tipo_exibicao} · {local} · CNPJ {self.cnpj}"


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


class Proprietario(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="proprietarios"
    )
    nome_razao_social = models.CharField(max_length=150)
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=18)
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
    numero_car = models.CharField("Número do CAR", max_length=60, blank=True)
    tipo_documento_posse = models.CharField(max_length=30, blank=True)
    numero_documento_posse = models.CharField(max_length=50, blank=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "fazendas"

    def __str__(self) -> str:
        return self.nome


class Fornecedor(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="fornecedores"
    )
    nome_razao_social = models.CharField(max_length=150)
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=18)
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
    numero_cadastro = models.CharField(
        "Cadastro MG Florestas", max_length=30, blank=True
    )
    motivo_dispensa = models.CharField(max_length=100, blank=True)
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
        ordering = ["fazenda__nome", "numero_cadastro"]
        verbose_name_plural = "plantios"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero_cadastro"],
                condition=~models.Q(numero_cadastro=""),
                name="plantio_cadastro_por_empresa",
            )
        ]

    def __str__(self) -> str:
        return self.numero_cadastro or f"Plantio {self.codigo} - {self.fazenda}"

    def idade_anos(self) -> int | None:
        base = self.data_ultimo_corte or self.data_plantio
        if base is None:
            return None
        hoje = timezone.localdate()
        return hoje.year - base.year - ((hoje.month, hoje.day) < (base.month, base.day))


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


class UPC(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="upcs")
    fazenda = models.ForeignKey(Fazenda, on_delete=models.PROTECT, related_name="upcs")
    nome = models.CharField(max_length=100)
    responsavel_legal = models.CharField(max_length=100, blank=True)
    utm_leste = models.DecimalField(max_digits=12, decimal_places=2)
    utm_norte = models.DecimalField(max_digits=12, decimal_places=2)
    utm_fuso = models.CharField(max_length=4, blank=True)
    numero_fornos = models.PositiveIntegerField()
    tipo_forno = models.CharField(max_length=60, blank=True)
    diametro_forno_m = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    altura_total_forno_m = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    altura_cilindro_m = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    volume_forno_mdc = models.DecimalField(max_digits=10, decimal_places=2)
    ciclo_producao_dias = models.PositiveIntegerField()
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

    @property
    def volume_ciclo_mdc(self) -> Decimal:
        return self.numero_fornos * self.volume_forno_mdc

    @property
    def volume_mes_mdc(self) -> Decimal:
        if not self.ciclo_producao_dias:
            return Decimal(0)
        return (self.volume_ciclo_mdc * 30 / self.ciclo_producao_dias).quantize(
            Decimal("0.01")
        )


class MetodoAmostragem(models.TextChoices):
    CASUAL_SIMPLES = "CASUAL_SIMPLES", "Casual simples"
    ESTRATIFICADA = "ESTRATIFICADA", "Estratificada"
    SISTEMATICA = "SISTEMATICA", "Sistemática"
    CENSO = "CENSO", "Censo"


def _dividir(numerador: Decimal | None, denominador: Decimal | None) -> Decimal | None:
    if numerador is None or not denominador:
        return None
    return Decimal(numerador) / Decimal(denominador)


class InventarioFlorestal(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="inventarios"
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
    upc = models.ForeignKey(
        "UPC",
        on_delete=models.PROTECT,
        related_name="inventarios",
        null=True,
        blank=True,
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
    metodo_amostragem = models.CharField(
        max_length=30,
        choices=MetodoAmostragem.choices,
        default=MetodoAmostragem.CASUAL_SIMPLES,
    )
    numero_parcelas = models.PositiveIntegerField()
    area_parcela_m2 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    equacao_volume = models.CharField(max_length=200, blank=True)
    fator_forma = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )
    equacao_hipsometrica = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
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
    nivel_probabilidade = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    t_student = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    erro_padrao_media = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    erro_amostragem_pct = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    ic_inferior_m3 = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    ic_superior_m3 = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True
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


class TipoColheita(models.TextChoices):
    CORTE_RASO_SEM_DESTOCA = "CORTE_RASO_SEM_DESTOCA", "Corte raso sem destoca"
    CORTE_RASO_COM_DESTOCA = "CORTE_RASO_COM_DESTOCA", "Corte raso com destoca"
    DESTOCA = "DESTOCA", "Destoca"
    CORTE_SELETIVO = "CORTE_SELETIVO", "Corte seletivo"
    DESBASTE = "DESBASTE", "Desbaste"


class SistemaColheita(models.TextChoices):
    MECANIZADA = "MECANIZADA", "Mecanizada"
    MANUAL = "MANUAL", "Manual"


class EquipamentoColheita(models.TextChoices):
    HARVESTER = "HARVESTER", "Harvester"
    FELLER = "FELLER", "Feller"
    SKIDDER = "SKIDDER", "Skidder"
    GARRA_TRACADORA = "GARRA_TRACADORA", "Garra traçadora"
    MOTOSSERRA = "MOTOSSERRA", "Motosserra"
    BALDEIO_MANUAL = "BALDEIO_MANUAL", "Baldeio manual"


EQUIPAMENTOS_POR_SISTEMA = {
    SistemaColheita.MECANIZADA: (
        EquipamentoColheita.HARVESTER,
        EquipamentoColheita.FELLER,
        EquipamentoColheita.SKIDDER,
        EquipamentoColheita.GARRA_TRACADORA,
    ),
    SistemaColheita.MANUAL: (
        EquipamentoColheita.MOTOSSERRA,
        EquipamentoColheita.BALDEIO_MANUAL,
    ),
}


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
    upc = models.ForeignKey(
        UPC,
        on_delete=models.PROTECT,
        related_name="autorizacoes",
        null=True,
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
    area_colher_ha = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    tipo_colheita = models.CharField(
        max_length=25, choices=TipoColheita.choices, blank=True
    )
    percentual_desbaste = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    numero_recibo_sinaflor = models.CharField(max_length=30, blank=True)
    possui_subbosque = models.BooleanField(default=False)
    volume_subbosque_m3_ha = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    area_basal_acima_10 = models.BooleanField(default=False)
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
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_transporte", "-codigo"]
        verbose_name = "transporte de lenha"
        verbose_name_plural = "transportes de lenha"

    def __str__(self) -> str:
        return f"{self.data_transporte:%d/%m/%Y} - {self.talhao}"

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
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


class Colheita(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="colheitas"
    )
    inventario = models.ForeignKey(
        InventarioFlorestal, on_delete=models.PROTECT, related_name="colheitas"
    )
    sistema = models.CharField(
        max_length=12,
        choices=SistemaColheita.choices,
        default=SistemaColheita.MECANIZADA,
    )
    equipamentos = models.JSONField(default=list, blank=True)
    autorizacao = models.ForeignKey(
        AutorizacaoAmbiental,
        on_delete=models.PROTECT,
        related_name="colheitas",
        null=True,
        blank=True,
    )
    talhao = models.ForeignKey(
        Talhao,
        on_delete=models.PROTECT,
        related_name="colheitas",
        null=True,
        blank=True,
    )
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    area_ha = models.DecimalField(max_digits=12, decimal_places=4)
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    volume_total = models.DecimalField(
        max_digits=14, decimal_places=3, editable=False, default=0
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_inicio", "-codigo"]
        verbose_name = "colheita"
        verbose_name_plural = "colheitas"
        constraints = [
            models.UniqueConstraint(
                fields=["inventario"], name="colheita_unica_por_inventario"
            )
        ]

    def __str__(self) -> str:
        return f"{self.inventario} - {self.talhao or 'sem talhão'}"

    def lista_equipamentos(self) -> str:
        return ", ".join(EquipamentoColheita(item).label for item in self.equipamentos)

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        # O volume colhido é o volume do inventário, que não é alterado.
        self.volume_total = self.inventario.volume_total
        super().save(*args, **kwargs)

    def volume_inventario(self) -> Decimal:
        return self.inventario.volume_total

    def estoque_em_campo(self) -> Decimal:
        # Informativo: não altera o volume do inventário nem baixa autorização.
        return self.volume_total


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


RENDIMENTO_REFERENCIA_MDC_M3 = Decimal("0.77")


class ProducaoCarvao(RegistroAuditavel):
    codigo = models.BigAutoField(primary_key=True)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="producoes_carvao"
    )
    upc = models.ForeignKey(
        UPC, on_delete=models.PROTECT, related_name="producoes_carvao"
    )
    autorizacao = models.ForeignKey(
        AutorizacaoAmbiental,
        on_delete=models.PROTECT,
        related_name="producoes_carvao",
        null=True,
        blank=True,
    )
    data_producao = models.DateField()
    numero_fornos = models.PositiveIntegerField(null=True, blank=True)
    volume_mdc = models.DecimalField(
        "Carvão produzido (MDC)", max_digits=12, decimal_places=2
    )
    volume_lenha_m3 = models.DecimalField(
        "Lenha consumida (m³)",
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
    )
    rendimento_mdc_m3 = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True, editable=False
    )
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data_producao", "-codigo"]
        verbose_name = "produção de carvão"
        verbose_name_plural = "produções de carvão"

    def __str__(self) -> str:
        return f"{self.upc} - {self.data_producao:%d/%m/%Y} - {self.volume_mdc} MDC"

    @property
    def alerta_rendimento(self) -> str:
        if self.rendimento_mdc_m3 is None:
            return ""
        referencia = RENDIMENTO_REFERENCIA_MDC_M3
        if self.rendimento_mdc_m3 < referencia * Decimal("0.7"):
            return "Abaixo do esperado"
        if self.rendimento_mdc_m3 > referencia * Decimal("1.3"):
            return "Acima do esperado"
        return ""

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        rendimento = _dividir(self.volume_mdc, self.volume_lenha_m3)
        self.rendimento_mdc_m3 = (
            rendimento.quantize(Decimal("0.0001")) if rendimento is not None else None
        )
        super().save(*args, **kwargs)


class TipoMovimentoAutorizacao(models.TextChoices):
    TRANSPORTE = "TRANSPORTE", "Transporte de lenha"
    VENDA = "VENDA", "Venda de lenha"
    PRODUCAO_CARVAO = "PRODUCAO_CARVAO", "Produção de carvão"
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
    producao = models.ForeignKey(
        ProducaoCarvao,
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
