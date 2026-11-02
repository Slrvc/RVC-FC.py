import json
from decimal import Decimal
from typing import TYPE_CHECKING

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q, Sum

from sistema.models import (
    EQUIPAMENTOS_POR_SISTEMA,
    UPC,
    AutorizacaoAmbiental,
    BaseVolume,
    CategoriaCusto,
    CentroCusto,
    Cliente,
    Colheita,
    DestinoLenha,
    Empresa,
    Equipamento,
    EquipamentoColheita,
    Estado,
    Expedicao,
    Fazenda,
    Fornecedor,
    InventarioFlorestal,
    InventarioTalhao,
    LancamentoCusto,
    LancamentoCustoRateio,
    Modalidade,
    Municipio,
    OrigemAutorizacao,
    Parametros,
    Plantio,
    ProducaoCarvao,
    ProdutoAutorizado,
    Proprietario,
    StatusAutorizacao,
    Talhao,
    TipoColheita,
    TipoTransporte,
    TipoUsuario,
    TransporteLenha,
    Usuario,
)

if TYPE_CHECKING:
    from datetime import date


class ContextoEmpresaForm(forms.Form):
    empresa = forms.ModelChoiceField(
        queryset=Empresa.objects.all(), label="Empresa", empty_label=None
    )


class ContextoUPCForm(forms.Form):
    upc = forms.ModelChoiceField(queryset=UPC.objects.none(), label="UPC")

    def __init__(self, *args, upcs, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["upc"].queryset = upcs
        self.fields["upc"].empty_label = None


class FormularioEmSecoes(forms.ModelForm):
    secoes_campos = ()

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)

    @property
    def secoes(self):
        incluidos = set()
        secoes = []
        for titulo, descricao, nomes_campos in self.secoes_campos:
            campos = [self[nome] for nome in nomes_campos if nome in self.fields]
            incluidos.update(campo.name for campo in campos)
            if campos:
                secoes.append(
                    {"titulo": titulo, "descricao": descricao, "campos": campos}
                )

        restantes = [campo for campo in self if campo.name not in incluidos]
        if restantes:
            secoes.append(
                {
                    "titulo": "Outras informações",
                    "descricao": "",
                    "campos": restantes,
                }
            )
        return secoes


class FormularioComMunicipio(FormularioEmSecoes):
    estado = forms.ModelChoiceField(
        queryset=Estado.objects.order_by("uf"),
        label="Estado",
    )

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["estado"].required = self.fields["municipio"].required
        if self.instance.pk and self.instance.municipio_id:
            self.initial.setdefault("estado", self.instance.municipio.estado_id)

        valor_estado = (
            self.data.get("estado") if self.is_bound else self.initial.get("estado")
        )
        codigo_estado = getattr(valor_estado, "pk", valor_estado)
        if codigo_estado and str(codigo_estado).isdecimal():
            municipios = Municipio.objects.filter(estado_id=codigo_estado)
            if self.instance.pk and self.instance.municipio_id:
                municipios = municipios.filter(
                    Q(ativo=True) | Q(pk=self.instance.municipio_id)
                )
            else:
                municipios = municipios.filter(ativo=True)
            self.fields["municipio"].queryset = municipios
        else:
            self.fields["municipio"].queryset = Municipio.objects.none()
        self.fields[
            "municipio"
        ].help_text = (
            "Selecione o estado para carregar os municípios e seus códigos IBGE."
        )
        ordem = list(self.fields)
        ordem.remove("estado")
        ordem.insert(ordem.index("municipio"), "estado")
        self.order_fields(ordem)

    def clean(self):
        dados = super().clean()
        estado, municipio = dados.get("estado"), dados.get("municipio")
        if estado and municipio and municipio.estado_id != estado.pk:
            self.add_error("municipio", "Selecione um município do estado informado.")
        return dados


class EmpresaForm(FormularioComMunicipio):
    secoes_campos = (
        (
            "Identificação da empresa",
            "Informe os dados fiscais e os nomes usados pela unidade.",
            (
                "cnpj",
                "razao_social",
                "nome_fantasia",
                "inscricao_estadual",
                "inscricao_municipal",
            ),
        ),
        (
            "Endereço da unidade",
            "Selecione o estado para escolher um município oficial do IBGE.",
            (
                "estado",
                "municipio",
                "cep",
                "endereco",
                "numero",
                "complemento",
                "bairro",
            ),
        ),
        (
            "Contato",
            "Canais de contato da empresa.",
            ("telefone", "celular", "email", "site"),
        ),
    )

    class Meta:
        model = Empresa
        fields = [
            "cnpj",
            "razao_social",
            "nome_fantasia",
            "inscricao_estadual",
            "inscricao_municipal",
            "estado",
            "municipio",
            "cep",
            "endereco",
            "numero",
            "complemento",
            "bairro",
            "telefone",
            "celular",
            "email",
            "site",
        ]
        labels = {
            "razao_social": "Razão social",
            "nome_fantasia": "Nome fantasia",
            "inscricao_estadual": "Inscrição estadual",
            "inscricao_municipal": "Inscrição municipal",
            "estado": "Estado",
            "municipio": "Município (código IBGE)",
            "endereco": "Logradouro",
            "numero": "Número",
            "complemento": "Complemento",
            "bairro": "Bairro",
        }
        help_texts = {
            "site": "Informe o endereço completo, incluindo https://.",
        }


class UsuarioForm(FormularioEmSecoes):
    secoes_campos = (
        (
            "Dados de acesso",
            "O usuário recebe uma senha temporária e deverá alterá-la ao entrar.",
            ("username", "senha", "is_active"),
        ),
        (
            "Dados do gestor",
            (
                "Cada gestor fica associado a uma empresa/unidade. "
                "Escolha as UPCs que ele acessa; sem seleção, acessa todas da empresa."
            ),
            ("nome_completo", "email", "empresa", "upcs"),
        ),
    )

    upcs = forms.ModelMultipleChoiceField(
        label="UPCs com acesso",
        queryset=UPC.objects.select_related("empresa"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    senha = forms.CharField(
        label="Senha inicial",
        widget=forms.PasswordInput,
        strip=False,
        required=False,
        help_text=(
            "Obrigatória ao criar o usuário. Será solicitada troca no primeiro acesso."
        ),
    )

    class Meta:
        model = Usuario
        fields = [
            "username",
            "nome_completo",
            "email",
            "empresa",
            "upcs",
            "is_active",
        ]
        labels = {
            "username": "Usuário de acesso",
            "nome_completo": "Nome completo",
            "empresa": "Empresa/unidade",
            "is_active": "Ativo no sistema",
        }
        help_texts = {
            "username": "Identificador usado para entrar no sistema.",
            "is_active": "Desative para bloquear o acesso sem excluir o cadastro.",
        }

    def clean_senha(self):
        senha = self.cleaned_data.get("senha")
        if self.instance.pk is None and not senha:
            message = "Informe uma senha inicial para o usuário."
            raise forms.ValidationError(message)
        if senha:
            validate_password(senha, self.instance)
        return senha

    def clean_empresa(self):
        empresa = self.cleaned_data.get("empresa")
        if empresa is None:
            message = "Selecione a empresa do gestor."
            raise forms.ValidationError(message)
        return empresa

    def clean(self):
        dados = super().clean()
        empresa = dados.get("empresa")
        upcs = dados.get("upcs")
        if empresa and upcs and any(u.empresa_id != empresa.pk for u in upcs):
            self.add_error("upcs", "Selecione apenas UPCs da empresa do gestor.")
        return dados

    def save(self, commit=True):  # noqa: FBT002
        usuario = super().save(commit=False)
        senha = self.cleaned_data.get("senha")
        if senha:
            usuario.set_password(senha)
            usuario.primeiro_acesso = True
        usuario.tipo_usuario = TipoUsuario.GESTOR
        if commit:
            usuario.save()
            self.save_m2m()
        return usuario


class FazendaForm(FormularioComMunicipio):
    secoes_campos = (
        (
            "Identificação do imóvel",
            "Informe a unidade, o proprietário e o nome do imóvel rural.",
            ("empresa", "proprietario", "nome", "area_total_ha", "arrendado"),
        ),
        (
            "Endereço da propriedade",
            "Selecione o estado e o município oficial do IBGE.",
            (
                "estado",
                "municipio",
                "cep",
                "endereco",
                "localidade",
                "referencia_local",
            ),
        ),
        (
            "Regularização",
            "Informe o CAR ou, na falta dele, o documento de propriedade ou posse.",
            (
                "numero_car",
                "tipo_documento_posse",
                "numero_documento_posse",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = Fazenda
        fields = [
            "empresa",
            "proprietario",
            "nome",
            "area_total_ha",
            "arrendado",
            "estado",
            "municipio",
            "cep",
            "endereco",
            "localidade",
            "referencia_local",
            "numero_car",
            "tipo_documento_posse",
            "numero_documento_posse",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "nome": "Nome do imóvel",
            "area_total_ha": "Área total (ha)",
            "arrendado": "Imóvel arrendado",
            "estado": "Estado",
            "municipio": "Município (código IBGE)",
            "endereco": "Endereço",
            "referencia_local": "Como chegar",
            "tipo_documento_posse": "Tipo do documento de posse",
            "numero_documento_posse": "Número do documento de posse",
            "observacao": "Observação",
        }

    def __init__(self, *args, empresa=None, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.empresa_fixa = empresa
        if empresa is not None:
            self.fields["proprietario"].queryset = Proprietario.objects.filter(
                empresa=empresa
            )

    def clean(self):
        dados = super().clean()
        empresa = self.empresa_fixa or dados.get("empresa")
        proprietario = dados.get("proprietario")
        if empresa and proprietario and proprietario.empresa_id != empresa.pk:
            self.add_error(
                "proprietario", "Selecione um proprietário da mesma empresa."
            )
        return dados


class FazendaGestorForm(FazendaForm):
    class Meta(FazendaForm.Meta):
        fields = [campo for campo in FazendaForm.Meta.fields if campo != "empresa"]


class ProprietarioForm(FormularioComMunicipio):
    secoes_campos = (
        (
            "Identificação do proprietário",
            "Informe o proprietário ou possuidor do imóvel rural.",
            ("empresa", "nome_razao_social", "cpf_cnpj"),
        ),
        (
            "Endereço",
            "O estado e o município são opcionais.",
            ("estado", "municipio", "cep", "endereco", "bairro"),
        ),
        (
            "Contato",
            "Canais de contato do proprietário.",
            ("telefone", "email", "observacao"),
        ),
    )

    class Meta:
        model = Proprietario
        fields = [
            "empresa",
            "nome_razao_social",
            "cpf_cnpj",
            "estado",
            "municipio",
            "cep",
            "endereco",
            "bairro",
            "telefone",
            "email",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "nome_razao_social": "Nome ou razão social",
            "estado": "Estado",
            "municipio": "Município (código IBGE)",
            "endereco": "Endereço",
            "observacao": "Observação",
        }
        help_texts = {"cpf_cnpj": "Informe o documento sem pontos ou traços."}

    def __init__(self, *args, empresa=None, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.empresa_fixa = empresa

    def clean(self):
        dados = super().clean()
        documento = dados.get("cpf_cnpj")
        if self.empresa_fixa and documento:
            duplicado = Proprietario.objects.filter(
                empresa=self.empresa_fixa, cpf_cnpj=documento
            ).exclude(pk=self.instance.pk)
            if duplicado.exists():
                self.add_error(
                    "cpf_cnpj", "Já existe um proprietário com este documento."
                )
        return dados


class ProprietarioGestorForm(ProprietarioForm):
    class Meta(ProprietarioForm.Meta):
        fields = [campo for campo in ProprietarioForm.Meta.fields if campo != "empresa"]


class FormularioDaEmpresa:
    """Restringe relacionamentos e unicidades à empresa do gestor."""

    campos_da_empresa: tuple[str, ...] = ()
    campos_unicos: tuple[str, ...] = ()

    def __init__(self, *args, empresa=None, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.empresa_fixa = empresa
        if empresa is not None:
            for nome in self.campos_da_empresa:
                campo = self.fields[nome]
                campo.queryset = campo.queryset.filter(empresa=empresa)

    def clean(self):
        dados = super().clean()
        empresa = self.empresa_fixa or dados.get("empresa")
        if not empresa:
            return dados
        for nome in self.campos_da_empresa:
            relacionado = dados.get(nome)
            if relacionado and relacionado.empresa_id != empresa.pk:
                self.add_error(nome, "Selecione um registro da mesma empresa.")
        for nome in self.campos_unicos:
            valor = dados.get(nome)
            if not valor:
                continue
            repetido = (
                self._meta.model.objects.filter(empresa=empresa, **{nome: valor})
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if repetido:
                self.add_error(nome, "Já existe um registro com este valor.")
        return dados


class FornecedorForm(FormularioDaEmpresa, FormularioComMunicipio):
    campos_unicos = ("cpf_cnpj",)
    secoes_campos = (
        (
            "Identificação do fornecedor",
            "Quem presta serviço, vende produto ou loca equipamento.",
            ("empresa", "nome_razao_social", "cpf_cnpj", "registro_conselho"),
        ),
        (
            "O que fornece",
            "Marque todas as opções que se aplicam.",
            ("fornece_servico", "fornece_produto", "fornece_locacao"),
        ),
        (
            "Endereço",
            "O estado e o município são opcionais.",
            ("estado", "municipio", "cep", "endereco", "bairro"),
        ),
        (
            "Contato",
            "Canais de contato do fornecedor.",
            ("telefone", "email", "observacao"),
        ),
    )

    class Meta:
        model = Fornecedor
        fields = [
            "empresa",
            "nome_razao_social",
            "cpf_cnpj",
            "registro_conselho",
            "fornece_servico",
            "fornece_produto",
            "fornece_locacao",
            "estado",
            "municipio",
            "cep",
            "endereco",
            "bairro",
            "telefone",
            "email",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "nome_razao_social": "Nome ou razão social",
            "registro_conselho": "Registro no conselho (CREA/CFTA)",
            "fornece_servico": "Presta serviço",
            "fornece_produto": "Vende produto",
            "fornece_locacao": "Loca equipamento ou veículo",
            "estado": "Estado",
            "municipio": "Município (código IBGE)",
            "endereco": "Endereço",
            "observacao": "Observação",
        }
        help_texts = {
            "cpf_cnpj": "Informe o documento sem pontos ou traços.",
            "registro_conselho": "Para responsável técnico de inventário.",
        }

    def clean(self):
        dados = super().clean()
        tipos = ("fornece_servico", "fornece_produto", "fornece_locacao")
        if not any(dados.get(tipo) for tipo in tipos):
            self.add_error(None, "Marque ao menos um tipo de fornecimento.")
        return dados


class FornecedorGestorForm(FornecedorForm):
    class Meta(FornecedorForm.Meta):
        fields = [campo for campo in FornecedorForm.Meta.fields if campo != "empresa"]


class PlantioForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fazenda",)
    campos_unicos = ("numero_cadastro",)
    secoes_campos = (
        (
            "Cadastro do plantio",
            "Número no MG Florestas ou o motivo da dispensa.",
            (
                "empresa",
                "fazenda",
                "numero_cadastro",
                "motivo_dispensa",
                "area_ha",
            ),
        ),
        (
            "Características",
            "Espécie, origem e espaçamento do plantio.",
            (
                "especie",
                "origem",
                "metodo_propagacao",
                "espacamento_entrelinha_m",
                "espacamento_planta_m",
            ),
        ),
        (
            "Ciclo",
            "A idade é calculada a partir do plantio ou do último corte.",
            ("data_plantio", "data_ultimo_corte", "rotacao", "observacao"),
        ),
    )

    class Meta:
        model = Plantio
        fields = [
            "empresa",
            "fazenda",
            "numero_cadastro",
            "motivo_dispensa",
            "area_ha",
            "especie",
            "origem",
            "metodo_propagacao",
            "espacamento_entrelinha_m",
            "espacamento_planta_m",
            "data_plantio",
            "data_ultimo_corte",
            "rotacao",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "numero_cadastro": "Cadastro MG Florestas",
            "motivo_dispensa": "Motivo da dispensa",
            "area_ha": "Área (ha)",
            "especie": "Espécie",
            "metodo_propagacao": "Método de propagação",
            "espacamento_entrelinha_m": "Espaçamento entre linhas (m)",
            "espacamento_planta_m": "Espaçamento entre plantas (m)",
            "data_plantio": "Data do plantio",
            "data_ultimo_corte": "Data do último corte",
            "rotacao": "Rotação",
            "observacao": "Observação",
        }
        widgets = {
            "data_plantio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_ultimo_corte": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
        }

    def clean(self):
        dados = super().clean()
        if not dados.get("numero_cadastro") and not dados.get("motivo_dispensa"):
            self.add_error(
                "numero_cadastro",
                "Informe o número do cadastro ou o motivo da dispensa.",
            )
        plantio, corte = dados.get("data_plantio"), dados.get("data_ultimo_corte")
        if plantio and corte and corte < plantio:
            self.add_error(
                "data_ultimo_corte", "O corte não pode ser anterior ao plantio."
            )
        return dados


class PlantioGestorForm(PlantioForm):
    class Meta(PlantioForm.Meta):
        fields = [campo for campo in PlantioForm.Meta.fields if campo != "empresa"]


class TalhaoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fazenda", "plantio")
    secoes_campos = (
        (
            "Identificação do talhão",
            "Use o mesmo código da planilha de talhões do DCF.",
            ("empresa", "fazenda", "plantio", "identificacao", "area_ha"),
        ),
        (
            "Localização",
            "Ponto central em graus decimais e polígono do shapefile.",
            ("latitude", "longitude", "geometria", "observacao"),
        ),
    )

    class Meta:
        model = Talhao
        fields = [
            "empresa",
            "fazenda",
            "plantio",
            "identificacao",
            "area_ha",
            "latitude",
            "longitude",
            "geometria",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "identificacao": "Identificação",
            "area_ha": "Área (ha)",
            "geometria": "Geometria (GeoJSON)",
            "observacao": "Observação",
        }
        widgets = {"geometria": forms.Textarea(attrs={"rows": 4})}

    def clean_geometria(self) -> str:
        texto = self.cleaned_data["geometria"].strip()
        if texto:
            try:
                json.loads(texto)
            except ValueError:
                msg = "Informe um GeoJSON válido."
                raise forms.ValidationError(msg) from None
        return texto

    def clean(self):
        dados = super().clean()
        fazenda, plantio = dados.get("fazenda"), dados.get("plantio")
        if fazenda and plantio and plantio.fazenda_id != fazenda.pk:
            self.add_error("plantio", "O plantio pertence a outra fazenda.")
        fazenda, identificacao = dados.get("fazenda"), dados.get("identificacao")
        if fazenda and identificacao:
            repetido = (
                Talhao.objects.filter(fazenda=fazenda, identificacao=identificacao)
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if repetido:
                self.add_error(
                    "identificacao", "Já existe um talhão com esta identificação."
                )
        return dados


class TalhaoGestorForm(TalhaoForm):
    class Meta(TalhaoForm.Meta):
        fields = [campo for campo in TalhaoForm.Meta.fields if campo != "empresa"]


class UPCForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fazenda",)
    campos_unicos = ("nome",)
    secoes_campos = (
        (
            "Identificação da UPC",
            "Unidade de Produção de Carvão (DCF itens 6 e 7).",
            ("empresa", "fazenda", "nome", "responsavel_legal", "observacao"),
        ),
        (
            "Localização (UTM SIRGAS 2000)",
            "Coordenadas como constam no DCF, item 7.1.",
            ("utm_leste", "utm_norte", "utm_fuso"),
        ),
        (
            "Fornos e capacidade",
            "O volume por ciclo e por mês é calculado automaticamente.",
            (
                "numero_fornos",
                "tipo_forno",
                "diametro_forno_m",
                "altura_total_forno_m",
                "altura_cilindro_m",
                "volume_forno_mdc",
                "ciclo_producao_dias",
            ),
        ),
    )

    class Meta:
        model = UPC
        fields = [
            "empresa",
            "fazenda",
            "nome",
            "responsavel_legal",
            "observacao",
            "utm_leste",
            "utm_norte",
            "utm_fuso",
            "numero_fornos",
            "tipo_forno",
            "diametro_forno_m",
            "altura_total_forno_m",
            "altura_cilindro_m",
            "volume_forno_mdc",
            "ciclo_producao_dias",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "responsavel_legal": "Responsável legal",
            "observacao": "Observação",
            "utm_leste": "UTM leste (X)",
            "utm_norte": "UTM norte (Y)",
            "utm_fuso": "Fuso UTM",
            "numero_fornos": "Número de fornos",
            "tipo_forno": "Tipo de forno",
            "diametro_forno_m": "Diâmetro (m)",
            "altura_total_forno_m": "Altura total (m)",
            "altura_cilindro_m": "Altura do cilindro (m)",
            "volume_forno_mdc": "Volume por forno (MDC)",
            "ciclo_producao_dias": "Ciclo de produção (dias)",
        }


class UPCGestorForm(UPCForm):
    class Meta(UPCForm.Meta):
        fields = [campo for campo in UPCForm.Meta.fields if campo != "empresa"]


class InventarioFlorestalForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fornecedor", "fazenda", "plantio", "upc")
    secoes_campos = (
        (
            "Identificação do inventário",
            "Um registro por lote. Cada autorização usa um inventário.",
            (
                "empresa",
                "upc",
                "fazenda",
                "plantio",
                "lote",
                "data_inventario",
                "area_ha",
                "numero_talhoes",
                "especie",
            ),
        ),
        (
            "Responsável técnico",
            "DCF itens 5.1 a 5.3.",
            ("fornecedor", "responsavel_tecnico", "registro_conselho", "numero_art"),
        ),
        (
            "Amostragem",
            "Método, intensidade e equações usadas.",
            (
                "metodo_amostragem",
                "numero_parcelas",
                "area_parcela_m2",
                "equacao_volume",
                "fator_forma",
                "equacao_hipsometrica",
                "latitude",
                "longitude",
            ),
        ),
        (
            "Resultado",
            "Volume por hectare, árvores por hectare e VMI são calculados.",
            (
                "volume_total",
                "numero_arvores",
                "dap_medio_cm",
                "altura_media_m",
            ),
        ),
        (
            "Estatística",
            "Parâmetros exigidos no DCF, item 5.",
            (
                "nivel_probabilidade",
                "t_student",
                "erro_padrao_media",
                "erro_amostragem_pct",
                "ic_inferior_m3",
                "ic_superior_m3",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = InventarioFlorestal
        fields = [
            "empresa",
            "upc",
            "fazenda",
            "plantio",
            "lote",
            "data_inventario",
            "area_ha",
            "numero_talhoes",
            "especie",
            "fornecedor",
            "responsavel_tecnico",
            "registro_conselho",
            "numero_art",
            "metodo_amostragem",
            "numero_parcelas",
            "area_parcela_m2",
            "equacao_volume",
            "fator_forma",
            "equacao_hipsometrica",
            "latitude",
            "longitude",
            "volume_total",
            "numero_arvores",
            "dap_medio_cm",
            "altura_media_m",
            "nivel_probabilidade",
            "t_student",
            "erro_padrao_media",
            "erro_amostragem_pct",
            "ic_inferior_m3",
            "ic_superior_m3",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "upc": "UPC",
            "data_inventario": "Data do inventário",
            "area_ha": "Área do lote (ha)",
            "numero_talhoes": "Número de talhões",
            "especie": "Espécie",
            "fornecedor": "Executado por (fornecedor)",
            "responsavel_tecnico": "Responsável técnico",
            "registro_conselho": "Registro no conselho",
            "numero_art": "Número da ART",
            "metodo_amostragem": "Método de amostragem",
            "numero_parcelas": "Número de parcelas",
            "area_parcela_m2": "Área da parcela (m²)",
            "equacao_volume": "Equação de volume",
            "fator_forma": "Fator de forma",
            "equacao_hipsometrica": "Equação hipsométrica",
            "volume_total": "Volume total (m³)",
            "numero_arvores": "Número de árvores",
            "dap_medio_cm": "DAP médio (cm)",
            "altura_media_m": "Altura média (m)",
            "nivel_probabilidade": "Nível de probabilidade (%)",
            "t_student": "t de Student",
            "erro_padrao_media": "Erro-padrão da média",
            "erro_amostragem_pct": "Erro de amostragem (%)",
            "ic_inferior_m3": "IC inferior (m³)",
            "ic_superior_m3": "IC superior (m³)",
            "observacao": "Observação",
        }
        widgets = {"data_inventario": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        dados = super().clean()
        empresa = self.empresa_fixa or dados.get("empresa")
        fazenda, lote = dados.get("fazenda"), dados.get("lote")
        plantio = dados.get("plantio")
        if fazenda and plantio and plantio.fazenda_id != fazenda.pk:
            self.add_error("plantio", "O plantio pertence a outra fazenda.")
        if empresa and fazenda and lote:
            repetido = (
                InventarioFlorestal.objects.filter(
                    empresa=empresa, fazenda=fazenda, lote=lote
                )
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if repetido:
                self.add_error("lote", "Já existe um inventário deste lote.")
        return dados


class InventarioFlorestalGestorForm(InventarioFlorestalForm):
    class Meta(InventarioFlorestalForm.Meta):
        fields = [
            campo for campo in InventarioFlorestalForm.Meta.fields if campo != "empresa"
        ]


class InventarioTalhaoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("inventario", "talhao")
    secoes_campos = (
        (
            "Talhão no inventário",
            "Volume e árvores do talhão neste inventário.",
            (
                "empresa",
                "inventario",
                "talhao",
                "area_ha",
                "volume_total",
                "numero_arvores",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = InventarioTalhao
        fields = [
            "empresa",
            "inventario",
            "talhao",
            "area_ha",
            "volume_total",
            "numero_arvores",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "inventario": "Inventário",
            "talhao": "Talhão",
            "area_ha": "Área (ha)",
            "volume_total": "Volume total (m³)",
            "numero_arvores": "Número de árvores",
            "observacao": "Observação",
        }

    def clean(self):
        dados = super().clean()
        inventario, talhao = dados.get("inventario"), dados.get("talhao")
        if inventario and talhao:
            if talhao.fazenda_id != inventario.fazenda_id:
                self.add_error("talhao", "O talhão pertence a outra fazenda.")
            repetido = (
                InventarioTalhao.objects.filter(inventario=inventario, talhao=talhao)
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if repetido:
                self.add_error("talhao", "Este talhão já está neste inventário.")
        return dados


class InventarioTalhaoGestorForm(InventarioTalhaoForm):
    class Meta(InventarioTalhaoForm.Meta):
        fields = [
            campo for campo in InventarioTalhaoForm.Meta.fields if campo != "empresa"
        ]


class AutorizacaoAmbientalForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fazenda", "upc", "plantio", "inventario")
    campos_unicos = ("numero",)
    secoes_campos = (
        (
            "Documento",
            "O número é o do processo SEI e identifica o saldo.",
            (
                "empresa",
                "numero",
                "tipo_documento",
                "origem_floresta",
                "modalidade",
                "status",
                "data_emissao",
                "data_vencimento",
                "numero_recibo_sinaflor",
            ),
        ),
        (
            "Vínculos",
            "Em nota fiscal, fazenda, UPC, plantio e inventário ficam vazios.",
            ("fazenda", "plantio", "inventario", "upc"),
        ),
        (
            "Volume autorizado",
            "Uma autorização usa um inventário (lote).",
            (
                "produto",
                "base_volume",
                "unidade_volume",
                "volume_declarado",
                "volume_base_m3",
                "fator_conversao",
            ),
        ),
        (
            "Colheita",
            "DCF itens 4.2 e 4.10 a 4.13.",
            (
                "area_colher_ha",
                "tipo_colheita",
                "percentual_desbaste",
                "possui_subbosque",
                "volume_subbosque_m3_ha",
                "area_basal_acima_10",
            ),
        ),
        (
            "Taxas",
            "Número e valor dos DAEs; informe o motivo se houver isenção.",
            (
                "numero_dae_expediente",
                "valor_taxa_expediente",
                "numero_dae_florestal",
                "valor_taxa_florestal",
                "motivo_isencao",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = AutorizacaoAmbiental
        fields = [
            "empresa",
            "numero",
            "tipo_documento",
            "origem_floresta",
            "modalidade",
            "status",
            "data_emissao",
            "data_vencimento",
            "numero_recibo_sinaflor",
            "fazenda",
            "plantio",
            "inventario",
            "upc",
            "produto",
            "base_volume",
            "unidade_volume",
            "volume_declarado",
            "volume_base_m3",
            "fator_conversao",
            "area_colher_ha",
            "tipo_colheita",
            "percentual_desbaste",
            "possui_subbosque",
            "volume_subbosque_m3_ha",
            "area_basal_acima_10",
            "numero_dae_expediente",
            "valor_taxa_expediente",
            "numero_dae_florestal",
            "valor_taxa_florestal",
            "motivo_isencao",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "numero": "Número (processo SEI)",
            "tipo_documento": "Tipo de documento",
            "origem_floresta": "Origem da floresta",
            "data_emissao": "Data de emissão",
            "data_vencimento": "Data de vencimento",
            "numero_recibo_sinaflor": "Recibo SINAFLOR",
            "inventario": "Inventário",
            "upc": "UPC",
            "base_volume": "Base do volume",
            "unidade_volume": "Unidade do volume",
            "volume_declarado": "Volume declarado",
            "volume_base_m3": "Volume base (m³)",
            "fator_conversao": "Fator de conversão",
            "area_colher_ha": "Área a colher (ha)",
            "tipo_colheita": "Tipo de colheita",
            "percentual_desbaste": "Percentual de desbaste (%)",
            "possui_subbosque": "Possui sub-bosque nativo",
            "volume_subbosque_m3_ha": "Volume do sub-bosque (m³/ha)",
            "area_basal_acima_10": "Área basal acima de 10 m²/ha",
            "numero_dae_expediente": "DAE da taxa de expediente",
            "valor_taxa_expediente": "Valor da taxa de expediente",
            "numero_dae_florestal": "DAE da taxa florestal",
            "valor_taxa_florestal": "Valor da taxa florestal",
            "motivo_isencao": "Motivo da isenção",
            "observacao": "Observação",
        }
        widgets = {
            "data_emissao": forms.DateInput(attrs={"type": "date"}),
            "data_vencimento": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        dados = super().clean()
        if dados.get("modalidade") == Modalidade.NOTA_FISCAL:
            for nome in ("fazenda", "upc", "plantio", "inventario"):
                dados[nome] = None
            dados["base_volume"] = ""
        else:
            self._validar_producao(dados)
        emissao, vencimento = dados.get("data_emissao"), dados.get("data_vencimento")
        if emissao and vencimento and vencimento < emissao:
            self.add_error("data_vencimento", "O vencimento é anterior à emissão.")
        if dados.get(
            "origem_floresta"
        ) == OrigemAutorizacao.NATIVA_PLANTADA and not dados.get(
            "numero_recibo_sinaflor"
        ):
            self.add_error("numero_recibo_sinaflor", "Informe o recibo SINAFLOR.")
        if dados.get("tipo_colheita") == TipoColheita.DESBASTE and not dados.get(
            "percentual_desbaste"
        ):
            self.add_error("percentual_desbaste", "Informe o percentual do desbaste.")
        if (
            dados.get("possui_subbosque")
            and dados.get("volume_subbosque_m3_ha") is None
        ):
            self.add_error("volume_subbosque_m3_ha", "Informe o volume do sub-bosque.")
        return dados

    def _validar_producao(self, dados: dict) -> None:
        fazenda, inventario = dados.get("fazenda"), dados.get("inventario")
        if not fazenda:
            self.add_error("fazenda", "Obrigatório em produção.")
        if not dados.get("base_volume"):
            self.add_error("base_volume", "Obrigatório em produção.")
        if dados.get("produto") in {
            ProdutoAutorizado.CARVAO_EXOTICA,
            ProdutoAutorizado.CARVAO_NATIVO,
        } and not dados.get("upc"):
            self.add_error("upc", "Obrigatória quando o produto é carvão.")
        if dados.get("base_volume") == BaseVolume.INVENTARIO and not inventario:
            self.add_error("inventario", "Informe o inventário que embasa o volume.")
        if fazenda:
            for nome in ("inventario", "plantio", "upc"):
                registro = dados.get(nome)
                if registro and registro.fazenda_id != fazenda.pk:
                    self.add_error(nome, "Pertence a outra fazenda.")


class AutorizacaoAmbientalGestorForm(AutorizacaoAmbientalForm):
    class Meta(AutorizacaoAmbientalForm.Meta):
        fields = [
            campo
            for campo in AutorizacaoAmbientalForm.Meta.fields
            if campo != "empresa"
        ]


class ExpedicaoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("autorizacao",)
    campos_unicos = ("numero_documento",)
    secoes_campos = (
        (
            "Expedição",
            "Primeira etapa: a saída baixa o volume expedido do saldo.",
            (
                "empresa",
                "autorizacao",
                "numero_documento",
                "data_expedicao",
                "cliente",
                "placa_veiculo",
                "volume_expedido",
            ),
        ),
        (
            "Descarga no cliente",
            "Segunda etapa: o volume aferido substitui o expedido na baixa.",
            ("data_descarga", "volume_aferido", "observacao"),
        ),
    )

    class Meta:
        model = Expedicao
        fields = [
            "empresa",
            "autorizacao",
            "numero_documento",
            "data_expedicao",
            "cliente",
            "placa_veiculo",
            "volume_expedido",
            "data_descarga",
            "volume_aferido",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "autorizacao": "Autorização",
            "numero_documento": "Documento de expedição",
            "data_expedicao": "Data da expedição",
            "placa_veiculo": "Placa do veículo",
            "volume_expedido": "Volume expedido",
            "data_descarga": "Data da descarga",
            "volume_aferido": "Volume aferido no cliente",
            "observacao": "Observação",
        }
        widgets = {
            "data_expedicao": forms.DateInput(attrs={"type": "date"}),
            "data_descarga": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        dados = super().clean()
        autorizacao = dados.get("autorizacao")
        expedicao = dados.get("data_expedicao")
        if autorizacao:
            self._validar_autorizacao(dados, autorizacao, expedicao)
        descarga, aferido = dados.get("data_descarga"), dados.get("volume_aferido")
        if (descarga is None) != (aferido is None):
            self.add_error(
                "volume_aferido" if aferido is None else "data_descarga",
                "Informe a data e o volume aferido da descarga juntos.",
            )
        if descarga and expedicao and descarga < expedicao:
            self.add_error("data_descarga", "A descarga é anterior à expedição.")
        return dados

    def _validar_autorizacao(
        self, dados: dict, autorizacao: AutorizacaoAmbiental, expedicao: date | None
    ) -> None:
        if not self.instance.pk and autorizacao.status != StatusAutorizacao.ATIVA:
            self.add_error("autorizacao", "A autorização não está ativa.")
        if expedicao and expedicao < autorizacao.data_emissao:
            self.add_error("data_expedicao", "Anterior à emissão da autorização.")
        if (
            expedicao
            and autorizacao.data_vencimento
            and expedicao > autorizacao.data_vencimento
        ):
            self.add_error("data_expedicao", "Posterior ao vencimento da autorização.")
        volume = dados.get("volume_expedido")
        if volume is None:
            return
        saldo = autorizacao.saldo()
        if self.instance.pk and self.instance.autorizacao_id == autorizacao.pk:
            saldo += self.instance.volume_baixa()
        if dados.get("volume_aferido") is None and volume > saldo:
            self.add_error("volume_expedido", f"Maior que o saldo ({saldo}).")


class ExpedicaoGestorForm(ExpedicaoForm):
    class Meta(ExpedicaoForm.Meta):
        fields = [campo for campo in ExpedicaoForm.Meta.fields if campo != "empresa"]


class TransporteLenhaForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("autorizacao", "talhao", "upc", "fornecedor")
    secoes_campos = (
        (
            "Carga",
            "Cada registro é uma viagem retirada do talhão.",
            (
                "empresa",
                "autorizacao",
                "talhao",
                "data_transporte",
                "volume_mst",
                "numero_documento",
            ),
        ),
        (
            "Destino",
            "UPC própria ou venda a terceiros.",
            ("destino", "upc", "comprador"),
        ),
        (
            "Transporte",
            "Terceirizado exige o transportador.",
            ("tipo_transporte", "fornecedor", "placa_veiculo", "motorista"),
        ),
        (
            "Custo",
            "Informe o valor por MST ou por m³; o outro é calculado.",
            ("valor_mst", "valor_m3", "observacao"),
        ),
    )

    class Meta:
        model = TransporteLenha
        fields = [
            "empresa",
            "autorizacao",
            "talhao",
            "data_transporte",
            "volume_mst",
            "numero_documento",
            "destino",
            "upc",
            "comprador",
            "tipo_transporte",
            "fornecedor",
            "placa_veiculo",
            "motorista",
            "valor_mst",
            "valor_m3",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "autorizacao": "Autorização",
            "talhao": "Talhão de origem",
            "data_transporte": "Data da viagem",
            "volume_mst": "Volume (MST)",
            "numero_documento": "Nota, guia ou ticket",
            "upc": "UPC de destino",
            "tipo_transporte": "Tipo de transporte",
            "fornecedor": "Transportador",
            "placa_veiculo": "Placa do veículo",
            "valor_mst": "Valor por MST",
            "valor_m3": "Valor por m³",
            "observacao": "Observação",
        }
        widgets = {"data_transporte": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        dados = super().clean()
        if dados.get("destino") == DestinoLenha.UPC:
            if not dados.get("upc"):
                self.add_error("upc", "Informe a UPC de destino.")
            dados["comprador"] = ""
        elif dados.get("destino") == DestinoLenha.VENDA:
            if not dados.get("comprador"):
                self.add_error("comprador", "Informe o comprador.")
            dados["upc"] = None
        if dados.get("tipo_transporte") == TipoTransporte.TERCEIRIZADO:
            if not dados.get("fornecedor"):
                self.add_error("fornecedor", "Obrigatório em transporte terceirizado.")
        else:
            dados["fornecedor"] = None
        if dados.get("valor_mst") is None and dados.get("valor_m3") is None:
            self.add_error("valor_mst", "Informe o valor por MST ou por m³.")
        autorizacao, talhao = dados.get("autorizacao"), dados.get("talhao")
        if (
            autorizacao
            and talhao
            and autorizacao.fazenda_id
            and autorizacao.fazenda_id != talhao.fazenda_id
        ):
            self.add_error("talhao", "O talhão é de outra fazenda da autorização.")
        return dados


class TransporteLenhaGestorForm(TransporteLenhaForm):
    class Meta(TransporteLenhaForm.Meta):
        fields = [
            campo for campo in TransporteLenhaForm.Meta.fields if campo != "empresa"
        ]


class ColheitaForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("inventario", "autorizacao", "talhao")
    campos_unicos = ("inventario",)
    equipamentos = forms.MultipleChoiceField(
        label="Equipamentos",
        choices=EquipamentoColheita.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    secoes_campos = (
        (
            "Origem",
            "Inventário do lote colhido (uma colheita por inventário).",
            ("empresa", "inventario", "autorizacao", "talhao"),
        ),
        (
            "Sistema de colheita",
            (
                "Mecanizada: harvester/feller, skidder e garra traçadora. "
                "Manual: motosserra e baldeio manual."
            ),
            ("sistema", "equipamentos"),
        ),
        (
            "Colheita",
            "Período e área colhida. O volume colhido é o do inventário.",
            ("data_inicio", "data_fim", "area_ha"),
        ),
        (
            "Localização",
            "Coordenadas em graus decimais.",
            ("latitude", "longitude", "observacao"),
        ),
    )

    class Meta:
        model = Colheita
        fields = [
            "empresa",
            "inventario",
            "sistema",
            "equipamentos",
            "autorizacao",
            "talhao",
            "data_inicio",
            "data_fim",
            "area_ha",
            "latitude",
            "longitude",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "inventario": "Inventário",
            "autorizacao": "Autorização",
            "talhao": "Talhão",
            "data_inicio": "Início da colheita",
            "data_fim": "Fim da colheita",
            "area_ha": "Área colhida (ha)",
            "observacao": "Observação",
        }
        widgets = {
            "data_inicio": forms.DateInput(attrs={"type": "date"}),
            "data_fim": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("data_inicio"), dados.get("data_fim")
        if inicio and fim and fim < inicio:
            self.add_error("data_fim", "O fim é anterior ao início.")
        sistema = dados.get("sistema")
        permitidos = {item.value for item in EQUIPAMENTOS_POR_SISTEMA.get(sistema, ())}
        if any(item not in permitidos for item in dados.get("equipamentos", [])):
            self.add_error(
                "equipamentos", "Há equipamentos que não pertencem ao sistema."
            )
        inventario = dados.get("inventario")
        if inventario:
            talhao = dados.get("talhao")
            if talhao and talhao.fazenda_id != inventario.fazenda_id:
                self.add_error("talhao", "O talhão é de outra fazenda.")
            autorizacao = dados.get("autorizacao")
            if (
                autorizacao
                and autorizacao.fazenda_id
                and autorizacao.fazenda_id != inventario.fazenda_id
            ):
                self.add_error("autorizacao", "A autorização é de outra fazenda.")
        return dados


class ColheitaGestorForm(ColheitaForm):
    class Meta(ColheitaForm.Meta):
        fields = [campo for campo in ColheitaForm.Meta.fields if campo != "empresa"]


class ParametrosForm(FormularioEmSecoes):
    secoes_campos = (
        (
            "Unidade e idioma",
            "Identifique a empresa e o terminal que usará estas preferências.",
            ("empresa", "terminal", "idioma", "simbolo_monetario"),
        ),
        (
            "Formatos de data e hora",
            "Defina como datas e horários serão exibidos.",
            (
                "separador_data",
                "formato_data",
                "formato_data_extenso",
                "separador_hora",
                "formato_hora",
                "formato_hora_extenso",
            ),
        ),
        (
            "Números e precisão",
            "Configure os separadores e as casas decimais utilizadas.",
            (
                "separador_milhar",
                "separador_decimal",
                "casas_decimais_ha",
                "casas_decimais_mdc",
                "casas_decimais_valor",
                "casas_decimais_peso",
                "casas_decimais_porcentagem",
            ),
        ),
    )

    class Meta:
        model = Parametros
        fields = [
            "empresa",
            "terminal",
            "idioma",
            "simbolo_monetario",
            "separador_milhar",
            "separador_decimal",
            "separador_data",
            "separador_hora",
            "formato_data",
            "formato_data_extenso",
            "formato_hora",
            "formato_hora_extenso",
            "casas_decimais_ha",
            "casas_decimais_mdc",
            "casas_decimais_valor",
            "casas_decimais_peso",
            "casas_decimais_porcentagem",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "terminal": "Terminal",
            "idioma": "Idioma",
            "simbolo_monetario": "Símbolo monetário",
            "separador_milhar": "Separador de milhar",
            "separador_decimal": "Separador decimal",
            "separador_data": "Separador de data",
            "separador_hora": "Separador de hora",
            "formato_data": "Formato de data",
            "formato_data_extenso": "Formato de data por extenso",
            "formato_hora": "Formato de hora",
            "formato_hora_extenso": "Formato de hora por extenso",
            "casas_decimais_ha": "Casas decimais de hectares",
            "casas_decimais_mdc": "Casas decimais de MDC",
            "casas_decimais_valor": "Casas decimais de valores",
            "casas_decimais_peso": "Casas decimais de peso",
            "casas_decimais_porcentagem": "Casas decimais de porcentagem",
        }


class CentroCustoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("upc",)
    campos_unicos = ("nome",)
    secoes_campos = (
        (
            "Centro de custo",
            "Onde o custo é gasto.",
            ("empresa", "nome", "tipo", "upc", "observacao"),
        ),
    )

    class Meta:
        model = CentroCusto
        fields = ["empresa", "nome", "tipo", "upc", "observacao"]
        labels = {"empresa": "Empresa/unidade", "observacao": "Observação"}
        help_texts = {"upc": "Informe quando o tipo for UPC."}

    def clean(self):
        dados = super().clean()
        if dados.get("tipo") == "UPC" and not dados.get("upc"):
            self.add_error("upc", "Informe a UPC deste centro de custo.")
        return dados


class CentroCustoGestorForm(CentroCustoForm):
    class Meta(CentroCustoForm.Meta):
        fields = [campo for campo in CentroCustoForm.Meta.fields if campo != "empresa"]


class CategoriaCustoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("categoria_pai",)
    campos_unicos = ("nome",)
    secoes_campos = (
        (
            "Categoria de custo",
            "O grupo fecha a conta na apuração do custo por MDC.",
            (
                "empresa",
                "nome",
                "grupo",
                "tipo_custo",
                "categoria_pai",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = CategoriaCusto
        fields = [
            "empresa",
            "nome",
            "grupo",
            "tipo_custo",
            "categoria_pai",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "tipo_custo": "Tipo de custo",
            "categoria_pai": "Categoria superior",
            "observacao": "Observação",
        }

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            campo = self.fields["categoria_pai"]
            campo.queryset = campo.queryset.exclude(pk=self.instance.pk)


class CategoriaCustoGestorForm(CategoriaCustoForm):
    class Meta(CategoriaCustoForm.Meta):
        fields = [
            campo for campo in CategoriaCustoForm.Meta.fields if campo != "empresa"
        ]


class EquipamentoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("centro_custo",)
    campos_unicos = ("placa",)
    secoes_campos = (
        (
            "Identificação do equipamento",
            "Caminhões, tratores, máquinas e veículos.",
            (
                "empresa",
                "descricao",
                "tipo",
                "placa",
                "propriedade",
                "centro_custo",
                "observacao",
            ),
        ),
        (
            "Capacidade e consumo",
            "Referências para as viagens e para conferir os abastecimentos.",
            ("capacidade_mst", "capacidade_mdc", "consumo_medio_km_l"),
        ),
    )

    class Meta:
        model = Equipamento
        fields = [
            "empresa",
            "descricao",
            "tipo",
            "placa",
            "propriedade",
            "centro_custo",
            "capacidade_mst",
            "capacidade_mdc",
            "consumo_medio_km_l",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "descricao": "Descrição",
            "propriedade": "Propriedade",
            "centro_custo": "Centro de custo padrão",
            "observacao": "Observação",
        }


class EquipamentoGestorForm(EquipamentoForm):
    class Meta(EquipamentoForm.Meta):
        fields = [campo for campo in EquipamentoForm.Meta.fields if campo != "empresa"]


class ClienteForm(FormularioDaEmpresa, FormularioComMunicipio):
    campos_unicos = ("cpf_cnpj",)
    secoes_campos = (
        (
            "Identificação do cliente",
            "Usina ou comprador do carvão e da lenha.",
            ("empresa", "nome_razao_social", "cpf_cnpj", "inscricao_estadual"),
        ),
        (
            "Endereço",
            "Local de descarga. O estado e o município são opcionais.",
            ("estado", "municipio", "cep", "endereco", "bairro"),
        ),
        (
            "Contato",
            "Canais de contato do cliente.",
            ("telefone", "email", "observacao"),
        ),
    )

    class Meta:
        model = Cliente
        fields = [
            "empresa",
            "nome_razao_social",
            "cpf_cnpj",
            "inscricao_estadual",
            "estado",
            "municipio",
            "cep",
            "endereco",
            "bairro",
            "telefone",
            "email",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "nome_razao_social": "Nome ou razão social",
            "inscricao_estadual": "Inscrição estadual",
            "estado": "Estado",
            "municipio": "Município (código IBGE)",
            "endereco": "Endereço",
            "observacao": "Observação",
        }
        help_texts = {"cpf_cnpj": "Informe o documento sem pontos ou traços."}


class ClienteGestorForm(ClienteForm):
    class Meta(ClienteForm.Meta):
        fields = [campo for campo in ClienteForm.Meta.fields if campo != "empresa"]


class ProducaoCarvaoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("upc", "autorizacao")
    secoes_campos = (
        (
            "Produção",
            "Carvão produzido na UPC (descarga dos fornos ou fim do ciclo).",
            (
                "empresa",
                "upc",
                "autorizacao",
                "data_producao",
                "numero_fornos",
                "observacao",
            ),
        ),
        (
            "Volumes",
            "O rendimento é calculado (referência do DCF: 0,77 MDC por m³).",
            ("volume_mdc", "volume_lenha_m3"),
        ),
    )

    class Meta:
        model = ProducaoCarvao
        fields = [
            "empresa",
            "upc",
            "autorizacao",
            "data_producao",
            "numero_fornos",
            "volume_mdc",
            "volume_lenha_m3",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "upc": "UPC",
            "autorizacao": "Autorização da lenha",
            "data_producao": "Data da produção",
            "numero_fornos": "Fornos descarregados",
            "observacao": "Observação",
        }
        widgets = {"data_producao": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        dados = super().clean()
        autorizacao, upc = dados.get("autorizacao"), dados.get("upc")
        if autorizacao and upc and autorizacao.upc_id != upc.pk:
            self.add_error("autorizacao", "A autorização é de outra UPC.")
        for campo in ("volume_mdc", "volume_lenha_m3"):
            valor = dados.get(campo)
            if valor is not None and valor <= 0:
                self.add_error(campo, "Informe um volume maior que zero.")
        return dados


class ProducaoCarvaoGestorForm(ProducaoCarvaoForm):
    class Meta(ProducaoCarvaoForm.Meta):
        fields = [
            campo for campo in ProducaoCarvaoForm.Meta.fields if campo != "empresa"
        ]


class LancamentoCustoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("centro_custo", "categoria", "fornecedor", "equipamento")
    secoes_campos = (
        (
            "Lançamento",
            "Um lançamento por gasto. Transporte terceirizado e frete do carvão "
            "não entram aqui.",
            (
                "empresa",
                "data_lancamento",
                "competencia",
                "centro_custo",
                "categoria",
                "descricao",
            ),
        ),
        (
            "Origem do gasto",
            "Quem recebeu e qual equipamento gerou o custo.",
            ("fornecedor", "equipamento", "numero_documento"),
        ),
        (
            "Valores",
            "O total é calculado quando quantidade e valor unitário são informados.",
            ("quantidade", "unidade", "valor_unitario", "valor_total"),
        ),
        (
            "Pagamento",
            "Sem data de pagamento, o lançamento fica a pagar (só caixa).",
            ("data_pagamento", "observacao"),
        ),
    )

    class Meta:
        model = LancamentoCusto
        fields = [
            "empresa",
            "data_lancamento",
            "competencia",
            "centro_custo",
            "categoria",
            "descricao",
            "fornecedor",
            "equipamento",
            "numero_documento",
            "quantidade",
            "unidade",
            "valor_unitario",
            "valor_total",
            "data_pagamento",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "data_lancamento": "Data do gasto",
            "competencia": "Competência (mês)",
            "centro_custo": "Centro de custo",
            "descricao": "Descrição",
            "numero_documento": "Nº do documento (NF/recibo)",
            "valor_unitario": "Valor unitário",
            "valor_total": "Valor total",
            "data_pagamento": "Data do pagamento",
            "observacao": "Observação",
        }
        widgets = {
            "data_lancamento": forms.DateInput(attrs={"type": "date"}),
            "competencia": forms.DateInput(attrs={"type": "date"}),
            "data_pagamento": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["competencia"].required = False
        self.fields["valor_total"].required = False
        self.fields["competencia"].help_text = (
            "Se vazio, usa o mês da data do gasto."
        )

    def clean(self):
        dados = super().clean()
        if not dados.get("competencia") and dados.get("data_lancamento"):
            dados["competencia"] = dados["data_lancamento"].replace(day=1)
        quantidade, unitario = dados.get("quantidade"), dados.get("valor_unitario")
        if quantidade is not None and unitario is not None:
            dados["valor_total"] = (quantidade * unitario).quantize(Decimal("0.01"))
        if dados.get("valor_total") is None:
            self.add_error("valor_total", "Informe o valor total.")
        elif dados["valor_total"] <= 0:
            self.add_error("valor_total", "Informe um valor maior que zero.")
        return dados

    def _post_clean(self) -> None:
        # O valor e a competência calculados precisam chegar ao modelo.
        for campo in ("competencia", "valor_total"):
            if campo in self.cleaned_data:
                setattr(self.instance, campo, self.cleaned_data[campo])
        super()._post_clean()


class LancamentoCustoGestorForm(LancamentoCustoForm):
    class Meta(LancamentoCustoForm.Meta):
        fields = [
            campo for campo in LancamentoCustoForm.Meta.fields if campo != "empresa"
        ]


class LancamentoCustoRateioForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("lancamento", "centro_custo")
    secoes_campos = (
        (
            "Rateio",
            "Divide um custo comum entre centros. A soma dos percentuais é 100.",
            ("empresa", "lancamento", "centro_custo", "percentual"),
        ),
    )

    class Meta:
        model = LancamentoCustoRateio
        fields = ["empresa", "lancamento", "centro_custo", "percentual"]
        labels = {
            "empresa": "Empresa/unidade",
            "lancamento": "Lançamento",
            "centro_custo": "Centro que recebe a parte",
            "percentual": "Percentual (%)",
        }

    def clean(self):
        dados = super().clean()
        lancamento = dados.get("lancamento")
        percentual = dados.get("percentual")
        if percentual is not None and not 0 < percentual <= 100:
            self.add_error("percentual", "Informe um percentual entre 0 e 100.")
        elif lancamento and percentual is not None:
            outros = lancamento.rateios.exclude(pk=self.instance.pk).aggregate(
                soma=Sum("percentual")
            )["soma"] or Decimal(0)
            if outros + percentual > 100:
                self.add_error(
                    "percentual",
                    f"A soma passaria de 100% (já rateado: {outros}%).",
                )
        centro = dados.get("centro_custo")
        if (
            lancamento
            and centro
            and lancamento.rateios.exclude(pk=self.instance.pk)
            .filter(centro_custo=centro)
            .exists()
        ):
            self.add_error("centro_custo", "Este centro já recebe parte do lançamento.")
        return dados


class LancamentoCustoRateioGestorForm(LancamentoCustoRateioForm):
    class Meta(LancamentoCustoRateioForm.Meta):
        fields = [
            campo
            for campo in LancamentoCustoRateioForm.Meta.fields
            if campo != "empresa"
        ]
