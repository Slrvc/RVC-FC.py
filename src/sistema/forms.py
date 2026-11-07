import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import TYPE_CHECKING

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q, Sum
from django.utils import timezone

from sistema.formatacao import MASCARAS_POR_CAMPO, MENSAGENS, normalizar
from sistema.models import (
    ETAPAS_DO_BOLETIM,
    ETAPAS_POR_SISTEMA,
    PADROES_POR_PAIS,
    STATUS_CICLO_ATIVO,
    UNIDADES_DA_COLHEITA,
    UPC,
    AutorizacaoAmbiental,
    BaseVolume,
    BoletimMedicao,
    BoletimTransporte,
    BoxLenha,
    CategoriaCusto,
    CentroCusto,
    CicloForno,
    Cliente,
    Colheita,
    DestinoLenha,
    Empresa,
    Equipamento,
    Estado,
    EtapaColheita,
    Expedicao,
    FaixaPrecoColheita,
    Fazenda,
    FormatoForno,
    Fornecedor,
    FornecedorTarifa,
    Forno,
    Inclinacao,
    InventarioFlorestal,
    InventarioTalhao,
    LancamentoCusto,
    LancamentoCustoRateio,
    Modalidade,
    Municipio,
    NivelMecanizacao,
    OrigemAutorizacao,
    ParametroEmpresa,
    Parametros,
    PlanejamentoForno,
    Plantio,
    ProdutoAutorizado,
    Proprietario,
    RegimeSabado,
    SituacaoForno,
    StatusAutorizacao,
    StatusBoletim,
    StatusCiclo,
    TabelaPrecoColheita,
    Talhao,
    TipoEmpresa,
    TipoExecucao,
    TipoForno,
    TipoTransporte,
    TipoUsuario,
    TransporteLenha,
    Usuario,
)

ENTRADA_DATA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def _numero(valor: Decimal, casas: int = 2) -> str:
    """Número no formato brasileiro, para mensagens."""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


class UPCsAutorizacaoField(forms.ModelMultipleChoiceField):
    def clean(self, value):
        if not isinstance(value, (list, tuple)):
            value = [value] if value else []
        return super().clean(value)


class UPCsSelectWidget(forms.Select):
    def value_from_datadict(self, data, files, name):
        getlist = getattr(data, "getlist", None)
        if getlist is not None:
            values = getlist(name)
            return values or None
        return super().value_from_datadict(data, files, name)


class ContextoEmpresaForm(forms.Form):
    empresa = forms.ModelChoiceField(
        queryset=Empresa.objects.none(),
        label="Empresa",
        empty_label=None,
    )

    def __init__(self, *args, empresas, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        campo = self.fields["empresa"]
        # Ativas primeiro; as encerradas ficam no fim, só para consulta.
        campo.queryset = empresas.select_related("municipio__estado").order_by(
            "data_encerramento", "razao_social", "cnpj"
        )
        campo.label_from_instance = lambda e: e.identificacao


class ContextoUPCForm(forms.Form):
    upc = forms.ModelChoiceField(queryset=UPC.objects.none(), label="UPC")

    def __init__(self, *args, upcs, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["upc"].queryset = upcs
        self.fields["upc"].empty_label = None


OPCAO_VAZIA = "Selecione"


def _traduzir_opcao_vazia(formulario: forms.BaseForm) -> None:
    """A opção vazia dos selects vem em inglês no Django 6; usa o português."""
    for campo in formulario.fields.values():
        if isinstance(campo, forms.ModelChoiceField):
            if campo.empty_label is not None:
                campo.empty_label = OPCAO_VAZIA
        elif isinstance(campo, forms.ChoiceField) and not isinstance(
            campo, forms.MultipleChoiceField
        ):
            opcoes = list(campo.choices)
            if opcoes and opcoes[0][0] in ("", None):
                campo.choices = [("", OPCAO_VAZIA), *opcoes[1:]]


class FormularioEmSecoes(forms.ModelForm):
    secoes_campos = ()

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        _traduzir_opcao_vazia(self)
        for nome, tipo in MASCARAS_POR_CAMPO.items():
            if nome in self.fields:
                self.fields[nome].widget.attrs["data-mask"] = tipo
                self.fields[nome].widget.attrs["inputmode"] = "numeric"
        for campo in self.fields.values():
            if (
                isinstance(campo, forms.ModelChoiceField)
                and campo.queryset.model is Empresa
            ):
                campo.queryset = campo.queryset.select_related("municipio__estado")
                campo.label_from_instance = lambda e: e.identificacao
            elif (
                isinstance(campo, forms.ModelChoiceField)
                and campo.queryset.model is Fazenda
            ):
                campo.label_from_instance = lambda fazenda: (
                    f"{fazenda.nome} (Matrícula {fazenda.numero_matricula})"
                    if fazenda.numero_matricula
                    else fazenda.nome
                )

    def clean(self):
        dados = super().clean()
        for nome, tipo in MASCARAS_POR_CAMPO.items():
            if nome not in self.fields or nome in self.errors:
                continue
            try:
                dados[nome] = normalizar(tipo, dados.get(nome, ""))
            except ValueError:
                self.add_error(nome, MENSAGENS[tipo])
        return dados

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
    recebe_usuario = True
    secoes_campos = (
        (
            "Identificação da empresa",
            "A matriz é a conta do cliente; cada filial pertence a uma matriz.",
            (
                "tipo",
                "matriz",
                "descricao_filial",
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
        (
            "Encerramento",
            "Floresta finda ou unidade fechada: os dados ficam só para consulta.",
            ("data_encerramento", "motivo_encerramento"),
        ),
    )

    class Meta:
        model = Empresa
        fields = [
            "tipo",
            "matriz",
            "descricao_filial",
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
            "data_encerramento",
            "motivo_encerramento",
        ]
        widgets = {"data_encerramento": ENTRADA_DATA}
        labels = {
            "tipo": "Tipo da unidade",
            "matriz": "Matriz",
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

    def __init__(self, *args, usuario=None, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self.fields["matriz"].label_from_instance = lambda e: e.identificacao
        self.fields["matriz"].queryset = Empresa.objects.filter(
            tipo=TipoEmpresa.MATRIZ
        ).exclude(pk=self.instance.pk)
        if usuario is not None and not usuario.is_superuser:
            # O administrador da matriz só cadastra filiais da própria conta.
            del self.fields["tipo"]
            del self.fields["matriz"]

    @property
    def _restrito_a_conta(self) -> bool:
        return "tipo" not in self.fields

    def clean(self):
        dados = super().clean()
        if self._restrito_a_conta:
            if self.instance.pk:
                tipo = self.instance.tipo
            else:
                tipo = TipoEmpresa.FILIAL
                self.instance.tipo = tipo
                self.instance.matriz_id = self.usuario.matriz_id
        else:
            tipo = dados.get("tipo")
            self._validar_matriz(dados, tipo)
        if tipo == TipoEmpresa.FILIAL:
            if not dados.get("descricao_filial"):
                self.add_error(
                    "descricao_filial",
                    "Descreva a filial. Ex.: Filial 01 - Sete Lagoas.",
                )
        else:
            dados["descricao_filial"] = ""
        if dados.get("data_encerramento") is None:
            dados["motivo_encerramento"] = ""
        elif not dados.get("motivo_encerramento"):
            self.add_error("motivo_encerramento", "Informe o motivo do encerramento.")
        return dados

    def _validar_matriz(self, dados: dict, tipo: str | None) -> None:
        if tipo == TipoEmpresa.FILIAL:
            if not dados.get("matriz"):
                self.add_error("matriz", "Selecione a matriz da filial.")
            if self.instance.pk and self.instance.filiais.exists():
                self.add_error("tipo", "A matriz tem filiais e não pode virar filial.")
        else:
            dados["matriz"] = None


class UPCsPorEmpresaWidget(forms.SelectMultiple):
    def create_option(self, *args, **kwargs):  # noqa: ANN002, ANN003
        opcao = super().create_option(*args, **kwargs)
        value = args[1] if len(args) > 1 else kwargs["value"]
        instancia = getattr(value, "instance", None)
        if instancia is not None:
            opcao["attrs"]["data-empresa"] = instancia.empresa_id
        return opcao


class UsuarioForm(FormularioEmSecoes):
    recebe_usuario = True
    secoes_campos = (
        (
            "Dados de acesso",
            "O usuário recebe uma senha temporária e deverá alterá-la ao entrar.",
            ("username", "senha", "tipo_usuario", "is_active"),
        ),
        (
            "Dados do usuário",
            (
                "O administrador acessa a matriz e todas as filiais dela. Gestores "
                "e operadores acessam só as empresas liberadas abaixo."
            ),
            ("nome_completo", "email", "matriz"),
        ),
        (
            "Acesso do gestor e do operador",
            (
                "Marque as empresas e as UPCs (segure Ctrl para marcar várias); "
                "sem UPC marcada, acessa todas as UPCs das empresas liberadas."
            ),
            ("empresas", "upcs"),
        ),
    )

    tipo_usuario = forms.ChoiceField(
        label="Tipo de usuário",
        choices=TipoUsuario.choices,
        initial=TipoUsuario.GESTOR,
    )

    upcs = forms.ModelMultipleChoiceField(
        label="UPCs com acesso",
        queryset=UPC.objects.select_related("empresa"),
        required=False,
        widget=UPCsPorEmpresaWidget,
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
            "tipo_usuario",
            "nome_completo",
            "email",
            "matriz",
            "empresas",
            "upcs",
            "is_active",
        ]
        labels = {
            "username": "Usuário de acesso",
            "nome_completo": "Nome completo",
            "matriz": "Matriz (conta do cliente)",
            "empresas": "Empresas com acesso",
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

    def __init__(self, *args, usuario=None, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        matriz = self.fields["matriz"]
        matriz.queryset = Empresa.objects.filter(tipo=TipoEmpresa.MATRIZ)
        matriz.label_from_instance = lambda e: e.identificacao
        self.fields["empresas"].label_from_instance = lambda e: e.identificacao
        if usuario is not None and not usuario.is_superuser:
            # O administrador da matriz cadastra usuários só da própria conta.
            del self.fields["matriz"]
            conta = Empresa.objects.da_conta(usuario.matriz_id)
            self.fields["empresas"].queryset = conta
            self.fields["upcs"].queryset = UPC.objects.filter(
                empresa__in=conta
            ).select_related("empresa")

    def clean(self):
        dados = super().clean()
        if "matriz" in self.fields:
            matriz = dados.get("matriz")
        else:
            matriz = self.usuario.matriz if self.usuario else None
            self.instance.matriz = matriz
        if matriz is None and not self.instance.is_superuser:
            self.add_error(
                "matriz" if "matriz" in self.fields else None,
                "Selecione a matriz do usuário.",
            )
        if dados.get("tipo_usuario") == TipoUsuario.ADMINISTRADOR:
            dados["empresas"] = Empresa.objects.none()
            dados["upcs"] = UPC.objects.none()
            return dados
        empresas = dados.get("empresas") or []
        if not empresas:
            self.add_error("empresas", "Marque pelo menos uma empresa.")
        if matriz and any(e.matriz_da_conta_id != matriz.pk for e in empresas):
            self.add_error("empresas", "Marque apenas empresas da matriz do usuário.")
        codigos = {empresa.pk for empresa in empresas}
        upcs = dados.get("upcs") or []
        if any(upc.empresa_id not in codigos for upc in upcs):
            self.add_error("upcs", "Marque apenas UPCs das empresas liberadas.")
        return dados

    def save(self, commit=True):  # noqa: FBT002
        usuario = super().save(commit=False)
        senha = self.cleaned_data.get("senha")
        if senha:
            usuario.set_password(senha)
            usuario.primeiro_acesso = True
        # O perfil de administrador vale só dentro da matriz; o superusuário
        # (dono do sistema) é criado pelo comando createsuperuser.
        usuario.is_staff = usuario.is_superuser
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
            "Informe a matrícula, o CAR ou o documento de propriedade ou posse.",
            (
                "numero_matricula",
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
            "numero_matricula",
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
            "numero_matricula": "Número da matrícula",
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
            ("empresa", "nome_razao_social", "cpf_cnpj", "inscricao_estadual"),
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
            (
                "empresa",
                "nome_razao_social",
                "cpf_cnpj",
                "inscricao_estadual",
                "registro_conselho",
            ),
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
            "inscricao_estadual",
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
            "inscricao_estadual": "Inscrição estadual",
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


class FornecedorTarifaForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fornecedor",)
    secoes_campos = (
        (
            "Tarifa",
            (
                "Valor combinado com o fornecedor para um serviço. O mesmo "
                "fornecedor pode ter tarifas de vários serviços."
            ),
            ("empresa", "fornecedor", "tipo_servico", "unidade", "valor"),
        ),
        (
            "Vigência",
            "Fim em branco: em vigor. O lançamento usa a tarifa vigente na data.",
            ("vigencia_inicio", "vigencia_fim", "observacao"),
        ),
    )

    class Meta:
        model = FornecedorTarifa
        fields = [
            "empresa",
            "fornecedor",
            "tipo_servico",
            "unidade",
            "valor",
            "vigencia_inicio",
            "vigencia_fim",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "tipo_servico": "Serviço",
            "valor": "Valor por unidade (R$)",
            "vigencia_inicio": "Vigente a partir de",
            "vigencia_fim": "Vigente até",
            "observacao": "Observação",
        }
        widgets = {"vigencia_inicio": ENTRADA_DATA, "vigencia_fim": ENTRADA_DATA}

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["fornecedor"].queryset = self.fields[
            "fornecedor"
        ].queryset.filter(fornece_servico=True)

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("vigencia_inicio"), dados.get("vigencia_fim")
        if inicio and fim and fim < inicio:
            self.add_error("vigencia_fim", "O fim é anterior ao início.")
        valor = dados.get("valor")
        if valor is not None and valor <= 0:
            self.add_error("valor", "Informe um valor maior que zero.")
        fornecedor, servico = dados.get("fornecedor"), dados.get("tipo_servico")
        if fornecedor and servico and inicio and not self.errors:
            outras = FornecedorTarifa.objects.filter(
                fornecedor=fornecedor, tipo_servico=servico
            ).exclude(pk=self.instance.pk)
            fim_efetivo = fim or date.max
            for outra in outras:
                fim_outra = outra.vigencia_fim or date.max
                if outra.vigencia_inicio <= fim_efetivo and inicio <= fim_outra:
                    self.add_error(
                        "vigencia_inicio",
                        "Já há uma tarifa deste serviço nesse período. "
                        "Encerre a anterior (vigente até) antes.",
                    )
                    break
        return dados


class FornecedorTarifaGestorForm(FornecedorTarifaForm):
    class Meta(FornecedorTarifaForm.Meta):
        fields = [c for c in FornecedorTarifaForm.Meta.fields if c != "empresa"]


class PlantioForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fazenda",)
    secoes_campos = (
        (
            "Identificação",
            "Fazenda do plantio.",
            (
                "empresa",
                "fazenda",
            ),
        ),
        (
            "Características",
            "Área, idade, espécie, origem e espaçamento do plantio.",
            (
                "area_ha",
                "idade_anos",
                "especie",
                "origem",
                "metodo_propagacao",
                "espacamento_entrelinha_m",
                "espacamento_planta_m",
            ),
        ),
        (
            "Ciclo",
            "Informe as datas do plantio e do último corte, quando conhecidas.",
            ("data_plantio", "data_ultimo_corte", "rotacao", "observacao"),
        ),
    )

    class Meta:
        model = Plantio
        fields = [
            "empresa",
            "fazenda",
            "area_ha",
            "idade_anos",
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
            "idade_anos": "Idade (anos)",
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
            "data_plantio": ENTRADA_DATA,
            "data_ultimo_corte": ENTRADA_DATA,
        }

    def clean(self):
        dados = super().clean()
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
    volume_m3 = forms.DecimalField(
        label="Volume total (m³)",
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0"),
    )
    saldo_a_retirar_m3 = forms.DecimalField(
        label="Saldo a retirar (m³)",
        max_digits=12,
        decimal_places=3,
        required=False,
        disabled=True,
        help_text=(
            "Calculado pelo volume total menos o volume já registrado nos transportes."
        ),
    )
    secoes_campos = (
        (
            "Identificação do talhão",
            "Use o mesmo código da planilha de talhões do DCF.",
            (
                "empresa",
                "fazenda",
                "plantio",
                "identificacao",
                "area_ha",
                "volume_m3",
                "saldo_a_retirar_m3",
            ),
        ),
        (
            "Medição da colheita",
            (
                "A inclinação escolhe a tabela de preço do boletim de medição. "
                "VMI em branco: o do inventário."
            ),
            ("inclinacao", "vmi_medicao"),
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
            "volume_m3",
            "inclinacao",
            "vmi_medicao",
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

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["inclinacao"].required = False
        valor_fazenda = (
            self.data.get("fazenda")
            if self.is_bound
            else self.initial.get("fazenda")
        )
        codigo_fazenda = getattr(valor_fazenda, "pk", valor_fazenda)
        if codigo_fazenda and str(codigo_fazenda).isdecimal():
            self.fields["plantio"].queryset = self.fields["plantio"].queryset.filter(
                fazenda_id=codigo_fazenda
            )
        else:
            self.fields["plantio"].queryset = Plantio.objects.none()
        volume_retirado = self.instance.volume_retirado_m3
        saldo = self.instance.saldo_a_retirar_m3
        self.fields["volume_m3"].widget.attrs["data-volume-retirado"] = str(
            volume_retirado
        )
        self.initial["saldo_a_retirar_m3"] = saldo

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
        if not dados.get("inclinacao"):
            dados["inclinacao"] = Inclinacao.ATE_5
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
            "Produção declarada",
            "O número de fornos e o volume por ciclo e por mês vêm do cadastro.",
            ("ciclo_producao_dias",),
        ),
        (
            "Dias de trabalho",
            (
                "Enchimento e descarga só nos dias de trabalho; carbonização e "
                "resfriamento seguem nos outros. Usado no planejamento (PL)."
            ),
            ("regime_sabado", "sabado_referencia", "trabalha_domingo"),
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
            "ciclo_producao_dias",
            "regime_sabado",
            "sabado_referencia",
            "trabalha_domingo",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "responsavel_legal": "Responsável legal",
            "observacao": "Observação",
            "utm_leste": "UTM leste (X)",
            "utm_norte": "UTM norte (Y)",
            "utm_fuso": "Fuso UTM",
            "ciclo_producao_dias": "Ciclo de produção (dias)",
        }
        help_texts = {
            "sabado_referencia": "Um sábado de trabalho; a partir dele alterna.",
        }
        widgets = {"sabado_referencia": ENTRADA_DATA}

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["regime_sabado"].required = False

    def clean(self):
        dados = super().clean()
        if not dados.get("regime_sabado"):
            dados["regime_sabado"] = RegimeSabado.TODOS
        referencia = dados.get("sabado_referencia")
        if dados.get("regime_sabado") == RegimeSabado.ALTERNADO:
            if referencia is None:
                self.add_error(
                    "sabado_referencia", "Informe um sábado trabalhado de referência."
                )
            elif referencia.weekday() != 5:
                self.add_error("sabado_referencia", "Esta data não é um sábado.")
        else:
            dados["sabado_referencia"] = None
        return dados


class UPCGestorForm(UPCForm):
    class Meta(UPCForm.Meta):
        fields = [campo for campo in UPCForm.Meta.fields if campo != "empresa"]


class InventarioFlorestalForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fornecedor", "fazenda", "plantio")
    secoes_campos = (
        (
            "Identificação do inventário",
            "Um registro por lote. Cada autorização usa um inventário.",
            (
                "empresa",
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
            "Resultado",
            "Volume por hectare, árvores por hectare e VMI são calculados.",
            (
                "volume_total",
                "numero_arvores",
                "dap_medio_cm",
                "altura_media_m",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = InventarioFlorestal
        fields = [
            "empresa",
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
            "volume_total",
            "numero_arvores",
            "dap_medio_cm",
            "altura_media_m",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "data_inventario": "Data do inventário",
            "area_ha": "Área do lote (ha)",
            "numero_talhoes": "Número de talhões",
            "especie": "Espécie",
            "fornecedor": "Executado por (fornecedor)",
            "responsavel_tecnico": "Responsável técnico",
            "registro_conselho": "Registro no conselho",
            "numero_art": "Número da ART",
            "volume_total": "Volume total (m³)",
            "numero_arvores": "Número de árvores",
            "dap_medio_cm": "DAP médio (cm)",
            "altura_media_m": "Altura média (m)",
            "observacao": "Observação",
        }
        widgets = {"data_inventario": ENTRADA_DATA}

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["vmi"] = forms.DecimalField(
            label="VMI",
            max_digits=10,
            decimal_places=4,
            required=False,
            disabled=True,
        )
        self.initial["vmi"] = self.instance.vmi

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
    saldo_a_retirar_m3 = forms.DecimalField(
        label="Saldo a retirar (m³)",
        max_digits=12,
        decimal_places=3,
        required=False,
        disabled=True,
        help_text="Saldo do talhão após descontar os transportes registrados.",
    )
    secoes_campos = (
        (
            "Talhão no inventário",
            "Volume, saldo disponível e árvores do talhão neste inventário.",
            (
                "empresa",
                "inventario",
                "talhao",
                "area_ha",
                "volume_total",
                "saldo_a_retirar_m3",
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
        help_texts = {
            "numero_arvores": (
                "Estimado pela densidade de árvores do inventário e a área do talhão."
            ),
        }

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        valor_inventario = (
            self.data.get("inventario")
            if self.is_bound
            else self.initial.get("inventario", self.instance.inventario_id)
        )
        codigo_inventario = getattr(valor_inventario, "pk", valor_inventario)
        inventario = None
        if codigo_inventario and str(codigo_inventario).isdecimal():
            inventario = self.fields["inventario"].queryset.filter(
                pk=codigo_inventario
            ).first()
        if inventario is None:
            self.fields["talhao"].queryset = Talhao.objects.none()
        else:
            self.fields["talhao"].queryset = self.fields["talhao"].queryset.filter(
                fazenda_id=inventario.fazenda_id
            )
        valor_talhao = (
            self.data.get("talhao")
            if self.is_bound
            else self.initial.get("talhao", self.instance.talhao_id)
        )
        codigo_talhao = getattr(valor_talhao, "pk", valor_talhao)
        talhao = None
        if codigo_talhao and str(codigo_talhao).isdecimal():
            talhao = self.fields["talhao"].queryset.filter(
                pk=codigo_talhao
            ).first()
        self.initial["saldo_a_retirar_m3"] = (
            talhao.saldo_a_retirar_m3 if talhao is not None else None
        )

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
    upcs = UPCsAutorizacaoField(
        queryset=UPC.objects.all(),
        required=False,
        label="UPC(s)",
        help_text="Produção permite uma UPC; nota fiscal pode vincular várias.",
    )
    campos_da_empresa = ("fazenda", "plantio", "inventario")
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
            "A autorização pode vincular uma ou mais UPCs.",
            ("fazenda", "plantio", "inventario", "upcs"),
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
            "upcs",
            "produto",
            "base_volume",
            "unidade_volume",
            "volume_declarado",
            "volume_base_m3",
            "fator_conversao",
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
            "upcs": "UPC(s)",
            "base_volume": "Base do volume",
            "unidade_volume": "Unidade do volume",
            "volume_declarado": "Volume declarado",
            "volume_base_m3": "Volume base (m³)",
            "fator_conversao": "Fator de conversão",
            "numero_dae_expediente": "DAE da taxa de expediente",
            "valor_taxa_expediente": "Valor da taxa de expediente",
            "numero_dae_florestal": "DAE da taxa florestal",
            "valor_taxa_florestal": "Valor da taxa florestal",
            "motivo_isencao": "Motivo da isenção",
            "observacao": "Observação",
        }
        widgets = {
            "data_emissao": ENTRADA_DATA,
            "data_vencimento": ENTRADA_DATA,
        }

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        empresa = self.empresa_fixa or getattr(self.instance, "empresa", None)
        if empresa is not None:
            self.fields["upcs"].queryset = UPC.objects.filter(empresa=empresa)
        modalidade = (
            self.data.get("modalidade")
            if self.is_bound
            else self.initial.get("modalidade", self.instance.modalidade)
        )
        if modalidade != Modalidade.NOTA_FISCAL:
            self.fields["upcs"].widget = UPCsSelectWidget()

    def clean(self):
        dados = super().clean()
        if dados.get("modalidade") == Modalidade.NOTA_FISCAL:
            for nome in ("fazenda", "plantio", "inventario"):
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
        return dados

    def _validar_producao(self, dados: dict) -> None:
        fazenda, inventario = dados.get("fazenda"), dados.get("inventario")
        if not fazenda:
            self.add_error("fazenda", "Obrigatório em produção.")
        if not dados.get("base_volume"):
            self.add_error("base_volume", "Obrigatório em produção.")
        upcs = dados.get("upcs")
        if (
            dados.get("modalidade") == Modalidade.PRODUCAO
            and upcs is not None
            and len(upcs) > 1
        ):
            self.add_error(
                "upcs",
                "Uma autorização de produção permite apenas uma UPC.",
            )
        if dados.get("produto") in {
            ProdutoAutorizado.CARVAO_EXOTICA,
            ProdutoAutorizado.CARVAO_NATIVO,
        } and not upcs:
            self.add_error("upcs", "Obrigatória quando o produto é carvão.")
        if dados.get("base_volume") == BaseVolume.INVENTARIO and not inventario:
            self.add_error("inventario", "Informe o inventário que embasa o volume.")
        if fazenda:
            for nome in ("inventario", "plantio"):
                registro = dados.get(nome)
                if registro and registro.fazenda_id != fazenda.pk:
                    self.add_error(nome, "Pertence a outra fazenda.")
        empresa = self.empresa_fixa or dados.get("empresa")
        if empresa and upcs and any(upc.empresa_id != empresa.pk for upc in upcs):
            self.add_error("upcs", "Selecione apenas UPCs da mesma empresa.")


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
            "data_expedicao": ENTRADA_DATA,
            "data_descarga": ENTRADA_DATA,
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


def _recusar_viagem_de_boletim_fechado(viagem: TransporteLenha) -> None:
    """Viagem de boletim de transporte fechado ou pago não muda mais."""
    boletim = viagem.boletim if viagem.pk else None
    if boletim is None or boletim.editavel:
        return
    situacao = boletim.get_status_display().lower()
    mensagem = (
        f"Esta viagem está no boletim de transporte de "
        f"{boletim.data_emissao:%d/%m/%Y}, já {situacao}."
    )
    raise forms.ValidationError(mensagem)


class TransporteLenhaForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("autorizacao", "talhao", "upc", "box_lenha", "fornecedor")
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
            "UPC própria ou venda a terceiros. O box é opcional.",
            ("destino", "upc", "box_lenha", "comprador"),
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
            "box_lenha",
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
            "box_lenha": "Box da praça",
            "tipo_transporte": "Tipo de transporte",
            "fornecedor": "Transportador",
            "placa_veiculo": "Placa do veículo",
            "valor_mst": "Valor por MST",
            "valor_m3": "Valor por m³",
            "observacao": "Observação",
        }
        widgets = {"data_transporte": ENTRADA_DATA}

    def clean(self):
        dados = super().clean()
        _recusar_viagem_de_boletim_fechado(self.instance)
        if dados.get("destino") == DestinoLenha.UPC:
            if not dados.get("upc"):
                self.add_error("upc", "Informe a UPC de destino.")
            box, upc = dados.get("box_lenha"), dados.get("upc")
            if box and upc and box.upc_id != upc.pk:
                self.add_error("box_lenha", "O box é de outra UPC.")
            dados["comprador"] = ""
        elif dados.get("destino") == DestinoLenha.VENDA:
            if not dados.get("comprador"):
                self.add_error("comprador", "Informe o comprador.")
            dados["upc"] = None
            dados["box_lenha"] = None
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


def _rotulos_das_etapas():  # noqa: ANN202
    """Etapas agrupadas por sistema no select: Mecanizada / Manual."""
    return [
        (sistema.label, [(etapa.value, etapa.label) for etapa in etapas])
        for sistema, etapas in ETAPAS_POR_SISTEMA.items()
    ]


class ColheitaForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("inventario", "autorizacao", "talhao", "fornecedor")
    secoes_campos = (
        (
            "Talhão e etapa",
            (
                "Cada etapa é um serviço pago à parte. O lançamento é diário, "
                "por volume, até completar o volume inventariado do talhão."
            ),
            ("empresa", "inventario", "talhao", "etapa", "autorizacao"),
        ),
        (
            "Produção do dia",
            "Volume feito na etapa. A área é a base do pagamento por hectare.",
            ("data_inicio", "data_fim", "volume_m3", "area_ha"),
        ),
        (
            "Execução e pagamento",
            (
                "O valor vem da tarifa vigente do empreiteiro para esta etapa; "
                "pode ser alterado no lançamento."
            ),
            ("tipo_execucao", "fornecedor", "unidade_pagamento", "valor_unitario"),
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
            "talhao",
            "etapa",
            "autorizacao",
            "data_inicio",
            "data_fim",
            "area_ha",
            "volume_m3",
            "tipo_execucao",
            "fornecedor",
            "unidade_pagamento",
            "valor_unitario",
            "latitude",
            "longitude",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "inventario": "Inventário",
            "autorizacao": "Autorização",
            "talhao": "Talhão",
            "etapa": "Etapa",
            "tipo_execucao": "Execução",
            "fornecedor": "Empreiteiro",
            "data_inicio": "Data",
            "data_fim": "Até (se mais de um dia)",
            "area_ha": "Área (ha)",
            "volume_m3": "Volume (m³)",
            "unidade_pagamento": "Pago por",
            "valor_unitario": "Valor unitário (R$)",
            "observacao": "Observação",
        }
        help_texts = {
            "area_ha": "Em branco: volume ÷ rendimento do talhão (m³/ha).",
            "valor_unitario": "Em branco: a tarifa vigente do empreiteiro.",
        }
        widgets = {
            "data_inicio": ENTRADA_DATA,
            "data_fim": ENTRADA_DATA,
        }

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["fornecedor"].queryset = self.fields[
            "fornecedor"
        ].queryset.filter(fornece_servico=True)
        self.fields["talhao"].required = True
        self.fields["volume_m3"].required = True
        self.fields["data_inicio"].required = True
        self.fields["etapa"].choices = _rotulos_das_etapas()

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("data_inicio"), dados.get("data_fim")
        if inicio and fim and fim < inicio:
            self.add_error("data_fim", "O fim é anterior ao início.")
        for campo in ("area_ha", "volume_m3", "valor_unitario"):
            valor = dados.get(campo)
            if valor is not None and valor <= 0:
                self.add_error(campo, "Informe um valor maior que zero.")
        inventario = dados.get("inventario")
        talhao = dados.get("talhao")
        if inventario:
            if talhao and talhao.fazenda_id != inventario.fazenda_id:
                self.add_error("talhao", "O talhão é de outra fazenda.")
            autorizacao = dados.get("autorizacao")
            if (
                autorizacao
                and autorizacao.fazenda_id
                and autorizacao.fazenda_id != inventario.fazenda_id
            ):
                self.add_error("autorizacao", "A autorização é de outra fazenda.")
        if dados.get("tipo_execucao") == TipoExecucao.TERCEIRIZADA:
            if not dados.get("fornecedor"):
                self.add_error("fornecedor", "Obrigatório na colheita terceirizada.")
            else:
                self._aplicar_tarifa(dados)
        else:
            dados["fornecedor"] = None
        self._validar_area(dados, talhao)
        return dados

    def _aplicar_tarifa(self, dados: dict) -> None:
        if dados.get("valor_unitario") is not None:
            return
        data = dados.get("data_inicio") or timezone.localdate()
        tarifa = FornecedorTarifa.vigente(
            dados["fornecedor"].pk, dados.get("etapa"), data
        )
        if tarifa is None:
            return
        if tarifa.unidade not in {u.value for u in UNIDADES_DA_COLHEITA}:
            return
        dados["valor_unitario"] = tarifa.valor
        dados["unidade_pagamento"] = tarifa.unidade

    def _validar_area(self, dados: dict, talhao: Talhao | None) -> None:
        volume, etapa = dados.get("volume_m3"), dados.get("etapa")
        if not (talhao and volume and etapa) or "volume_m3" in self.errors:
            return
        total = Colheita.volume_do_talhao(talhao, dados.get("inventario"))
        if total is None:
            return
        saldo = total - Colheita.volume_ja_feito(
            talhao.pk, etapa, exceto=self.instance.pk
        )
        # Arredonda ao centésimo: a planilha fecha o talhão com sobras de 0,003 m³.
        if volume.quantize(Decimal("0.01")) > saldo.quantize(Decimal("0.01")):
            self.add_error(
                "volume_m3",
                f"Nesta etapa o talhão tem {_numero(saldo)} m³ a fazer "
                f"(inventário {_numero(total)} m³).",
            )


class ColheitaGestorForm(ColheitaForm):
    class Meta(ColheitaForm.Meta):
        fields = [campo for campo in ColheitaForm.Meta.fields if campo != "empresa"]


class ParametrosForm(FormularioEmSecoes):
    recebe_usuario = True

    def __init__(self, *args, usuario=None, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        if usuario is not None:
            campo = self.fields["empresa"]
            campo.queryset = usuario.empresas_permitidas()
        self.fields["pais"].widget.attrs["data-padroes-pais"] = json.dumps(
            {pais.value: padroes for pais, padroes in PADROES_POR_PAIS.items()}
        )
        for nome in self.CAMPOS_DO_PAIS:
            self.fields[nome].required = False

    CAMPOS_DO_PAIS = (
        "idioma",
        "simbolo_monetario",
        "separador_milhar",
        "separador_decimal",
        "formato_data",
        "formato_hora",
        "formato_hora_extenso",
    )

    secoes_campos = (
        (
            "País e idioma",
            (
                "Sem parâmetros vale o padrão do Brasil. Ao escolher o país, os "
                "formatos são preenchidos com o padrão dele e podem ser ajustados. "
                "As filiais sem parâmetros próprios usam os da matriz."
            ),
            ("empresa", "pais", "idioma", "simbolo_monetario"),
        ),
        (
            "Formatos de data e hora",
            "Ex.: dd/mm/yyyy e hh:mm. Usados nas listas e no painel.",
            (
                "formato_data",
                "formato_data_extenso",
                "formato_hora",
                "formato_hora_extenso",
            ),
        ),
        (
            "Números e precisão",
            "Separadores e casas decimais mostradas nas listas e no painel.",
            (
                "separador_milhar",
                "separador_decimal",
                "casas_decimais_ha",
                "casas_decimais_volume",
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
            "pais",
            "idioma",
            "simbolo_monetario",
            "separador_milhar",
            "separador_decimal",
            "formato_data",
            "formato_data_extenso",
            "formato_hora",
            "formato_hora_extenso",
            "casas_decimais_ha",
            "casas_decimais_volume",
            "casas_decimais_mdc",
            "casas_decimais_valor",
            "casas_decimais_peso",
            "casas_decimais_porcentagem",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "idioma": "Idioma",
            "simbolo_monetario": "Símbolo monetário",
            "separador_milhar": "Separador de milhar",
            "separador_decimal": "Separador decimal",
            "formato_data": "Formato de data",
            "formato_data_extenso": "Formato de data por extenso",
            "formato_hora": "Formato de hora",
            "formato_hora_extenso": "Formato de hora com segundos",
            "casas_decimais_ha": "Casas decimais de área (ha)",
            "casas_decimais_volume": "Casas decimais de volume (m³ e MST)",
            "casas_decimais_mdc": "Casas decimais de carvão (MDC)",
            "casas_decimais_valor": "Casas decimais de valores (R$)",
            "casas_decimais_peso": "Casas decimais de peso",
            "casas_decimais_porcentagem": "Casas decimais de porcentagem",
        }

    def clean(self):
        dados = super().clean()
        padroes = PADROES_POR_PAIS.get(dados.get("pais"), {})
        for nome in self.CAMPOS_DO_PAIS:
            # O separador de milhar pode ser um espaço: só o vazio volta ao padrão.
            if dados.get(nome) in (None, "") and nome in padroes:
                dados[nome] = padroes[nome]
        for campo in (c for c in self.fields if c.startswith("casas_decimais")):
            valor = dados.get(campo)
            if valor is not None and valor > 6:
                self.add_error(campo, "Use no máximo 6 casas decimais.")
        if dados.get("separador_milhar") == dados.get("separador_decimal"):
            self.add_error("separador_decimal", "Use separadores diferentes.")
        return dados


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


def _sem_empresa(campos: list[str]) -> list[str]:
    return [campo for campo in campos if campo != "empresa"]


class ParametroEmpresaForm(FormularioEmSecoes):
    secoes_campos = (
        (
            "Conversão da lenha",
            "Toda lenha é medida em MST; o sistema converte para m³ com este fator.",
            ("empresa", "fator_mst_por_m3"),
        ),
        (
            "Rendimento ideal",
            (
                "Referência para o alerta de cada ciclo de forno. Sem tolerância "
                "informada, o sistema alerta a partir de 30% de diferença."
            ),
            (
                "fator_m3_por_mdc_ideal",
                "fator_mst_por_mdc_ideal",
                "tolerancia_fator_pct",
            ),
        ),
        (
            "Estoque no talhão",
            "Define qual posição do talhão gera alerta.",
            ("controle_estoque_talhao", "observacao"),
        ),
    )

    class Meta:
        model = ParametroEmpresa
        fields = [
            "empresa",
            "fator_mst_por_m3",
            "fator_m3_por_mdc_ideal",
            "fator_mst_por_mdc_ideal",
            "tolerancia_fator_pct",
            "controle_estoque_talhao",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "fator_mst_por_m3": "MST por m³",
            "fator_m3_por_mdc_ideal": "m³ de lenha por MDC (ideal)",
            "fator_mst_por_mdc_ideal": "MST de lenha por MDC (ideal)",
            "tolerancia_fator_pct": "Tolerância do alerta (%)",
            "controle_estoque_talhao": "Controle do estoque no talhão",
            "observacao": "Observação",
        }

    def __init__(self, *args, empresa=None, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.empresa_fixa = empresa

    def clean(self):
        dados = super().clean()
        for campo in (
            "fator_mst_por_m3",
            "fator_m3_por_mdc_ideal",
            "fator_mst_por_mdc_ideal",
        ):
            valor = dados.get(campo)
            if valor is not None and valor <= 0:
                self.add_error(campo, "Informe um fator maior que zero.")
        tolerancia = dados.get("tolerancia_fator_pct")
        if tolerancia is not None and not 0 <= tolerancia <= 100:
            self.add_error("tolerancia_fator_pct", "Informe entre 0 e 100%.")
        if self.empresa_fixa is not None:
            repetido = (
                ParametroEmpresa.objects.filter(empresa=self.empresa_fixa)
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if repetido:
                self.add_error(
                    None,
                    "Esta empresa já tem parâmetros de produção. Edite o "
                    "registro existente.",
                )
        return dados


class ParametroEmpresaGestorForm(ParametroEmpresaForm):
    class Meta(ParametroEmpresaForm.Meta):
        fields = _sem_empresa(ParametroEmpresaForm.Meta.fields)


class TipoFornoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_unicos = ("nome",)
    secoes_campos = (
        (
            "Modelo",
            "DCF itens 7.3 e 7.5.",
            ("empresa", "nome", "formato", "capacidade_mdc", "capacidade_lenha_mst"),
        ),
        (
            "Tempo do ciclo",
            (
                "Prazos usados para avisar ATENÇÃO quando o forno passa do tempo "
                "previsto e para projetar o planejado (PL) do painel."
            ),
            (
                "dias_carbonizacao_previstos",
                "dias_resfriamento_previstos",
                "dias_vazio_previstos",
            ),
        ),
        (
            "Mecanização",
            "Semimecanizado: só o enchimento ou só a descarga é mecanizado.",
            ("nivel_mecanizacao", "enchimento_mecanizado", "descarga_mecanizada"),
        ),
        (
            "Dimensões (DCF 7.4)",
            "Circular: diâmetro. Retangular: comprimento e largura.",
            (
                "diametro_m",
                "comprimento_m",
                "largura_m",
                "altura_total_m",
                "altura_cilindro_m",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = TipoForno
        fields = [
            "empresa",
            "nome",
            "formato",
            "capacidade_mdc",
            "capacidade_lenha_mst",
            "dias_carbonizacao_previstos",
            "dias_resfriamento_previstos",
            "dias_vazio_previstos",
            "nivel_mecanizacao",
            "enchimento_mecanizado",
            "descarga_mecanizada",
            "diametro_m",
            "comprimento_m",
            "largura_m",
            "altura_total_m",
            "altura_cilindro_m",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "capacidade_mdc": "Produção por ciclo (MDC)",
            "capacidade_lenha_mst": "Lenha por enchimento (MST)",
            "nivel_mecanizacao": "Nível de mecanização",
            "diametro_m": "Diâmetro (m)",
            "comprimento_m": "Comprimento (m)",
            "largura_m": "Largura (m)",
            "altura_total_m": "Altura total (m)",
            "altura_cilindro_m": "Altura do cilindro (m)",
            "observacao": "Observação",
        }

    def clean(self):
        dados = super().clean()
        if dados.get("formato") == FormatoForno.CIRCULAR:
            if not dados.get("diametro_m"):
                self.add_error("diametro_m", "Informe o diâmetro do forno circular.")
            dados["comprimento_m"] = dados["largura_m"] = None
        elif dados.get("formato") == FormatoForno.RETANGULAR:
            for campo in ("comprimento_m", "largura_m"):
                if not dados.get(campo):
                    self.add_error(campo, "Obrigatório no forno retangular.")
            dados["diametro_m"] = None
        nivel = dados.get("nivel_mecanizacao")
        if nivel == NivelMecanizacao.MANUAL:
            dados["enchimento_mecanizado"] = dados["descarga_mecanizada"] = False
        elif nivel == NivelMecanizacao.MECANIZADO:
            dados["enchimento_mecanizado"] = dados["descarga_mecanizada"] = True
        elif nivel == NivelMecanizacao.SEMIMECANIZADO and (
            dados.get("enchimento_mecanizado") == dados.get("descarga_mecanizada")
        ):
            self.add_error(
                "nivel_mecanizacao",
                "No semimecanizado, só o enchimento ou só a descarga é mecanizado.",
            )
        capacidade = dados.get("capacidade_mdc")
        if capacidade is not None and capacidade <= 0:
            self.add_error("capacidade_mdc", "Informe uma capacidade maior que zero.")
        return dados


class TipoFornoGestorForm(TipoFornoForm):
    class Meta(TipoFornoForm.Meta):
        fields = _sem_empresa(TipoFornoForm.Meta.fields)


LIMITE_FORNOS_EM_LOTE = 500


def sequencia_de_numeros(primeiro: str, quantidade: int) -> list[str]:
    """F01 e 3 viram F01, F02 e F03, mantendo o prefixo e os zeros."""
    inicio = len(primeiro.rstrip("0123456789"))
    prefixo, digitos = primeiro[:inicio], primeiro[inicio:]
    if not digitos:
        raise ValueError
    base = int(digitos)
    largura = max(len(digitos), len(str(base + quantidade - 1)))
    return [f"{prefixo}{base + i:0{largura}d}" for i in range(quantidade)]


class FornoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("upc", "tipo_forno")
    quantidade = forms.IntegerField(
        label="Quantidade de fornos",
        min_value=1,
        max_value=LIMITE_FORNOS_EM_LOTE,
        initial=1,
        required=False,
        help_text="Para criar vários de uma vez: informe o primeiro número "
        "(ex.: 01) e a quantidade.",
    )
    secoes_campos = (
        (
            "Forno",
            "Cada forno é cadastrado com seu número na UPC.",
            ("empresa", "upc", "tipo_forno", "numero", "quantidade", "situacao"),
        ),
        (
            "Detalhes",
            "Capacidade só se for diferente da do tipo de forno.",
            ("data_instalacao", "capacidade_mdc", "observacao"),
        ),
    )

    class Meta:
        model = Forno
        fields = [
            "empresa",
            "upc",
            "tipo_forno",
            "numero",
            "situacao",
            "data_instalacao",
            "capacidade_mdc",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "upc": "UPC",
            "tipo_forno": "Tipo de forno",
            "numero": "Número do forno",
            "situacao": "Situação",
            "data_instalacao": "Data de instalação",
            "capacidade_mdc": "Capacidade própria (MDC)",
            "observacao": "Observação",
        }
        widgets = {"data_instalacao": ENTRADA_DATA}

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.numeros_extras: list[str] = []
        self.fields["numero"].help_text = (
            "Só o número (ex.: 01). O forno aparece com o nome do tipo: FCM 01."
        )
        self.fields["tipo_forno"].label_from_instance = (
            lambda tipo: f"{tipo.nome} · {tipo.get_formato_display()}"
        )
        if self.instance.pk:
            del self.fields["quantidade"]

    def clean(self):
        dados = super().clean()
        upc, numero = dados.get("upc"), dados.get("numero")
        quantidade = dados.get("quantidade") or 1
        if not upc or not numero:
            return dados
        numeros = [numero]
        if quantidade > 1:
            try:
                numeros = sequencia_de_numeros(numero, quantidade)
            except ValueError:
                self.add_error(
                    "numero", "Para criar em lote, o número deve terminar em dígitos."
                )
                return dados
        existentes = list(
            Forno.objects.filter(
                upc=upc, tipo_forno=dados.get("tipo_forno"), numero__in=numeros
            )
            .exclude(pk=self.instance.pk)
            .values_list("numero", flat=True)
        )
        if existentes:
            self.add_error(
                "numero", f"Já existem na UPC: {', '.join(sorted(existentes))}."
            )
        self.numeros_extras = numeros[1:]
        return dados

    def salvar_extras(self, registro: Forno) -> None:
        Forno.objects.bulk_create(
            Forno(
                empresa_id=registro.empresa_id,
                upc_id=registro.upc_id,
                tipo_forno_id=registro.tipo_forno_id,
                numero=numero,
                situacao=registro.situacao,
                data_instalacao=registro.data_instalacao,
                capacidade_mdc=registro.capacidade_mdc,
                observacao=registro.observacao,
                usuario_inclusao=registro.usuario_inclusao,
                usuario_alteracao=registro.usuario_alteracao,
            )
            for numero in self.numeros_extras
        )


class FornoGestorForm(FornoForm):
    class Meta(FornoForm.Meta):
        fields = _sem_empresa(FornoForm.Meta.fields)


class BoxLenhaForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("upc",)
    secoes_campos = (
        (
            "Box",
            "Box da praça de carbonização onde a lenha do baldeio é depositada.",
            (
                "empresa",
                "upc",
                "numero",
                "descricao",
                "capacidade_mst",
                "situacao",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = BoxLenha
        fields = [
            "empresa",
            "upc",
            "numero",
            "descricao",
            "capacidade_mst",
            "situacao",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "upc": "UPC",
            "numero": "Número do box",
            "descricao": "Descrição ou localização",
            "capacidade_mst": "Capacidade (MST)",
            "situacao": "Situação",
            "observacao": "Observação",
        }

    def clean(self):
        dados = super().clean()
        upc, numero = dados.get("upc"), dados.get("numero")
        if (
            upc
            and numero
            and BoxLenha.objects.filter(upc=upc, numero=numero)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            self.add_error("numero", "Já existe um box com este número na UPC.")
        return dados


class BoxLenhaGestorForm(BoxLenhaForm):
    class Meta(BoxLenhaForm.Meta):
        fields = _sem_empresa(BoxLenhaForm.Meta.fields)


ENTRADA_DATA_HORA = forms.DateTimeInput(
    attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
)
ETAPAS_DO_CICLO = (
    ("data_inicio_enchimento", "enchimento"),
    ("data_fim_carbonizacao", "fim da carbonização"),
    ("data_descarga", "descarga"),
)
CAMPOS_DEPOIS_DO_ENCHIMENTO = (
    "data_fim_carbonizacao",
    "data_descarga",
    "volume_mdc",
    "responsavel_descarga",
)


def fornos_vazios(fornos):
    """Fornos ativos sem ciclo em andamento: os que podem ser enchidos."""
    return fornos.filter(situacao=SituacaoForno.ATIVO).exclude(
        ciclos__status__in=STATUS_CICLO_ATIVO
    )


class CicloFornoForm(FormularioDaEmpresa, FormularioEmSecoes):
    """Enchimento (novo ciclo) ou correção de um ciclo já lançado."""

    campos_da_empresa = ("forno", "box_lenha", "fornecedor")
    cancelado = forms.BooleanField(label="Ciclo cancelado", required=False)
    secoes_campos = (
        (
            "Forno e etapas",
            (
                "Em geral o forno é aceso ao terminar o enchimento; informe o "
                "acendimento só quando for em outro horário. As etapas seguintes "
                "são lançadas em Fim da carbonização e Descarga."
            ),
            (
                "empresa",
                "forno",
                "numero_ciclo",
                "data_inicio_enchimento",
                "data_acendimento",
                "data_fim_carbonizacao",
                "data_descarga",
                "cancelado",
            ),
        ),
        (
            "Lenha e carvão",
            "Lenha em MST; o m³ e os fatores de conversão são calculados.",
            (
                "box_lenha",
                "volume_lenha_enchimento",
                "fator_conversao",
                "volume_mdc",
            ),
        ),
        (
            "Execução",
            "Terceirizada: o empreiteiro recebe por MDC produzido.",
            ("tipo_execucao", "fornecedor", "valor_mdc"),
        ),
        (
            "Fatores do rendimento",
            "Ajudam a explicar a variação do fator de conversão.",
            (
                "condicao_tempo",
                "dias_secagem_lenha",
                "responsavel_enchimento",
                "responsavel_descarga",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = CicloForno
        fields = [
            "empresa",
            "forno",
            "numero_ciclo",
            "data_inicio_enchimento",
            "data_acendimento",
            "data_fim_carbonizacao",
            "data_descarga",
            "box_lenha",
            "volume_lenha_enchimento",
            "fator_conversao",
            "volume_mdc",
            "tipo_execucao",
            "fornecedor",
            "valor_mdc",
            "condicao_tempo",
            "dias_secagem_lenha",
            "responsavel_enchimento",
            "responsavel_descarga",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "numero_ciclo": "Número do ciclo",
            "data_inicio_enchimento": "Enchimento",
            "data_acendimento": "Acendimento (ignição)",
            "data_fim_carbonizacao": "Fim da carbonização",
            "data_descarga": "Descarga",
            "box_lenha": "Box de origem da lenha",
            "fator_conversao": "Fator (MST por m³)",
            "tipo_execucao": "Execução",
            "fornecedor": "Empreiteiro",
            "valor_mdc": "Valor por MDC",
            "condicao_tempo": "Condição do tempo",
            "dias_secagem_lenha": "Dias de secagem da lenha",
            "responsavel_enchimento": "Responsável pelo enchimento",
            "responsavel_descarga": "Responsável pela descarga",
            "observacao": "Observação",
        }
        help_texts = {
            "numero_ciclo": "Em branco: o próximo número do forno.",
            "data_acendimento": "Em branco: a mesma data e hora do enchimento.",
            "volume_mdc": "Medido na descarga do forno.",
            "valor_mdc": "Em branco: a tarifa de carbonização do empreiteiro.",
        }
        widgets = {
            **{nome: ENTRADA_DATA_HORA for nome, _ in ETAPAS_DO_CICLO},
            "data_acendimento": ENTRADA_DATA_HORA,
        }

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["fornecedor"].queryset = self.fields[
            "fornecedor"
        ].queryset.filter(fornece_servico=True)
        self.fields["cancelado"].initial = (
            self.instance.status == StatusCiclo.CANCELADO
        )
        self.fields["fator_conversao"].required = True
        if self.instance.pk:
            return
        # Novo ciclo = enchimento: só fornos vazios e só os campos desta etapa.
        for nome in (*CAMPOS_DEPOIS_DO_ENCHIMENTO, "cancelado"):
            del self.fields[nome]
        self.fields["forno"].queryset = fornos_vazios(self.fields["forno"].queryset)
        self.fields["forno"].help_text = "Só aparecem os fornos vazios."
        self.fields["data_inicio_enchimento"].initial = _agora_local()
        parametro = ParametroEmpresa.da_empresa(
            self.empresa_fixa.pk if self.empresa_fixa else None
        )
        self.fields["fator_conversao"].initial = parametro.fator_mst_por_m3
        referencias = [
            f"{tipo.nome}: {_numero(tipo.capacidade_lenha_mst)} MST"
            for tipo in TipoForno.objects.filter(
                fornos__in=self.fields["forno"].queryset,
                capacidade_lenha_mst__isnull=False,
            ).distinct()
        ]
        self.fields["volume_lenha_enchimento"].help_text = (
            "Medida em cada enchimento."
            + (f" Referência: {'; '.join(referencias)}." if referencias else "")
        )

    def clean(self):
        dados = super().clean()
        forno = dados.get("forno")
        self._validar_datas(dados)
        acendimento = dados.get("data_acendimento")
        enchimento = dados.get("data_inicio_enchimento")
        if acendimento and enchimento and acendimento < enchimento:
            self.add_error("data_acendimento", "Não pode ser antes do enchimento.")
        fim = dados.get("data_fim_carbonizacao")
        if acendimento and fim and fim < acendimento:
            self.add_error(
                "data_fim_carbonizacao", "Não pode ser antes do acendimento."
            )
        self._validar_volumes(dados)
        box = dados.get("box_lenha")
        if box and forno and box.upc_id != forno.upc_id:
            self.add_error("box_lenha", "O box é de outra UPC.")
        if dados.get("tipo_execucao") == TipoExecucao.TERCEIRIZADA:
            if not dados.get("fornecedor"):
                self.add_error("fornecedor", "Obrigatório na produção terceirizada.")
        else:
            dados["fornecedor"] = None
            dados["valor_mdc"] = None
        self.instance.status = (
            StatusCiclo.CANCELADO
            if dados.get("cancelado")
            else StatusCiclo.ENCHIMENTO
        )
        if not dados.get("numero_ciclo") and self.instance.pk and (
            forno is None or forno.pk == self.instance.forno_id
        ):
            dados["numero_ciclo"] = self.instance.numero_ciclo
        if forno:
            self._validar_forno(dados, forno)
        return dados

    def _validar_datas(self, dados: dict) -> None:
        """Cada etapa exige a anterior e não pode ser antes dela."""
        for (nome_anterior, rotulo_anterior), (nome, _) in pairwise(ETAPAS_DO_CICLO):
            if nome not in self.fields:
                continue
            valor, valor_anterior = dados.get(nome), dados.get(nome_anterior)
            if valor is None or nome_anterior in self.errors:
                continue
            if valor_anterior is None:
                self.add_error(nome, f"Preencha o {rotulo_anterior} primeiro.")
            elif valor < valor_anterior:
                self.add_error(nome, f"Não pode ser antes do {rotulo_anterior}.")

    def _validar_volumes(self, dados: dict) -> None:
        for campo in ("volume_lenha_enchimento", "fator_conversao", "volume_mdc"):
            valor = dados.get(campo)
            if valor is not None and valor <= 0:
                self.add_error(campo, "Informe um valor maior que zero.")
        if "data_descarga" not in self.fields:
            return
        if dados.get("data_descarga") and dados.get("volume_mdc") is None:
            self.add_error("volume_mdc", "Informe o carvão medido na descarga.")
        if dados.get("volume_mdc") is not None and not dados.get("data_descarga"):
            self.add_error("data_descarga", "Informe a data da descarga do carvão.")

    def _validar_forno(self, dados: dict, forno: Forno) -> None:
        mudou_forno = self.instance.forno_id != forno.pk
        if mudou_forno and forno.situacao == SituacaoForno.DESATIVADO:
            self.add_error("forno", "O forno está desativado.")
        outros = CicloForno.objects.filter(forno=forno).exclude(pk=self.instance.pk)
        numero = dados.get("numero_ciclo")
        if numero and outros.filter(numero_ciclo=numero).exists():
            self.add_error("numero_ciclo", "O forno já tem um ciclo com este número.")
        self.instance.data_inicio_enchimento = dados.get("data_inicio_enchimento")
        self.instance.data_acendimento = dados.get(
            "data_acendimento"
        ) or dados.get("data_inicio_enchimento")
        self.instance.data_descarga = dados.get("data_descarga")
        self.instance.data_fim_carbonizacao = dados.get("data_fim_carbonizacao")
        ativo = self.instance.status_pelas_datas() in STATUS_CICLO_ATIVO
        if ativo and outros.filter(status__in=STATUS_CICLO_ATIVO).exists():
            self.add_error(
                "forno", "Este forno já tem um ciclo em andamento. Descarregue-o antes."
            )


class CicloFornoGestorForm(CicloFornoForm):
    class Meta(CicloFornoForm.Meta):
        fields = _sem_empresa(CicloFornoForm.Meta.fields)


def _agora_local():  # noqa: ANN202
    return timezone.localtime().replace(second=0, microsecond=0)


def _data_hora(valor) -> str:
    return timezone.localtime(valor).strftime("%d/%m %H:%M") if valor else "—"


class CicloEtapaForm(forms.Form):
    """Lança uma etapa num forno que está na etapa anterior.

    Subclasses definem o status de origem, o campo de data da etapa, a data da
    etapa anterior (para validação) e os demais campos gravados no ciclo.
    """

    status_origem: str = ""
    campo_data: str = ""
    campo_data_anterior: str = ""
    rotulo_anterior: str = ""
    campos_extras: tuple[str, ...] = ()
    titulo = ""
    descricao = ""
    secoes = FormularioEmSecoes.secoes

    ciclo = forms.ModelChoiceField(label="Forno", queryset=CicloForno.objects.none())

    def __init__(self, *args, ciclos, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        campo = self.fields["ciclo"]
        campo.queryset = (
            ciclos.filter(status=self.status_origem)
            .select_related("forno__upc", "forno__tipo_forno")
            .order_by("forno__upc__nome", "forno__numero")
        )
        campo.label_from_instance = self.rotulo_do_ciclo
        campo.empty_label = "Selecione o forno"
        if not campo.queryset.exists():
            campo.empty_label = "Nenhum forno nesta etapa"
        self.fields[self.campo_data].initial = _agora_local()

    @property
    def secoes_campos(self):
        return ((self.titulo, self.descricao, tuple(self.fields)),)

    def rotulo_do_ciclo(self, ciclo: CicloForno) -> str:
        anterior = _data_hora(getattr(ciclo, self.campo_data_anterior))
        prevista = _data_hora(ciclo.prevista_da_etapa)
        atraso = " · ATENÇÃO, passou do prazo" if ciclo.alerta_prazo else ""
        return (
            f"{ciclo.forno} · ciclo {ciclo.numero_ciclo} · "
            f"{self.rotulo_anterior} {anterior} · previsto {prevista}{atraso}"
        )

    def clean(self):
        dados = super().clean()
        ciclo, data = dados.get("ciclo"), dados.get(self.campo_data)
        if ciclo and data:
            anterior = getattr(ciclo, self.campo_data_anterior)
            if anterior and data < anterior:
                self.add_error(
                    self.campo_data,
                    f"Não pode ser antes do {self.rotulo_anterior} "
                    f"({_data_hora(anterior)}).",
                )
            if data > timezone.now() + timedelta(hours=1):
                self.add_error(self.campo_data, "A data está no futuro.")
        return dados

    def aplicar(self) -> CicloForno:
        ciclo = self.cleaned_data["ciclo"]
        for nome in (self.campo_data, *self.campos_extras):
            setattr(ciclo, nome, self.cleaned_data[nome])
        return ciclo


class FimCarbonizacaoForm(CicloEtapaForm):
    status_origem = StatusCiclo.CARBONIZACAO
    campo_data = "data_fim_carbonizacao"
    campo_data_anterior = "data_acendimento"
    rotulo_anterior = "acendimento"
    titulo = "Fim da carbonização"
    descricao = (
        "Só aparecem os fornos carbonizando. Depois desta etapa o forno entra "
        "em resfriamento."
    )

    data_fim_carbonizacao = forms.DateTimeField(
        label="Fim da carbonização", widget=ENTRADA_DATA_HORA
    )


class DescargaForm(CicloEtapaForm):
    status_origem = StatusCiclo.RESFRIAMENTO
    campo_data = "data_descarga"
    campo_data_anterior = "data_fim_carbonizacao"
    rotulo_anterior = "fim da carbonização"
    campos_extras = ("volume_mdc", "responsavel_descarga")
    titulo = "Descarga"
    descricao = (
        "Só aparecem os fornos em resfriamento. Na descarga o forno fica vazio "
        "e pode ser enchido de novo."
    )

    data_descarga = forms.DateTimeField(label="Descarga", widget=ENTRADA_DATA_HORA)
    volume_mdc = forms.DecimalField(
        label="Carvão produzido (MDC)",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    responsavel_descarga = forms.CharField(
        label="Responsável pela descarga", max_length=80, required=False
    )


ETAPAS_DE_LANCAMENTO = {
    "fim-carbonizacao": FimCarbonizacaoForm,
    "descarga": DescargaForm,
}


def _ler_faixas(texto: str) -> list[tuple[Decimal, Decimal, Decimal, Decimal]]:
    """Linhas coladas do Excel: VMI, derrubada, arraste, traçamento (e o resto).

    Aceita tabulação, ponto e vírgula ou espaços entre as colunas e vírgula
    decimal. Linhas sem números (títulos) são ignoradas.
    """
    faixas = []
    for numero_linha, linha in enumerate(texto.splitlines(), start=1):
        partes = [
            parte.strip().lstrip("><=≥ ").replace("R$", "").strip()
            for parte in re.split(r"[\t;]+|\s{2,}|\s(?=[>\d])", linha.strip())
        ]
        numeros = []
        for parte in partes:
            if not parte:
                continue
            valor = parte.replace(".", "").replace(",", ".") if "," in parte else parte
            try:
                numeros.append(Decimal(valor))
            except InvalidOperation:
                continue
        if not numeros:
            continue
        if len(numeros) < 4:
            mensagem = (
                f"Linha {numero_linha}: informe VMI, derrubada, arraste e traçamento."
            )
            raise forms.ValidationError(mensagem)
        faixas.append(tuple(numeros[:4]))
    return faixas


def _faixas_em_texto(tabela: TabelaPrecoColheita, inclinacao: str) -> str:
    return "\n".join(
        "\t".join(
            str(valor).replace(".", ",")
            for valor in (
                faixa.vmi_minimo.normalize(),
                faixa.preco_derrubada.normalize(),
                faixa.preco_arraste.normalize(),
                faixa.preco_tracamento.normalize(),
            )
        )
        for faixa in tabela.faixas.filter(inclinacao=inclinacao)
    )


class TabelaPrecoColheitaForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fornecedor",)
    faixas_ate_5 = forms.CharField(
        label="Faixas com inclinação até 5%",
        widget=forms.Textarea(attrs={"rows": 9, "class": "texto-tabela"}),
        help_text=(
            "Cole do Excel uma linha por faixa: VMI, derrubada, arraste, "
            "traçamento (R$/m³). Ex.: 0,33  11,57  10,25  13,12"
        ),
    )
    faixas_acima_5 = forms.CharField(
        label="Faixas com inclinação acima de 5%",
        widget=forms.Textarea(attrs={"rows": 9, "class": "texto-tabela"}),
        required=False,
    )
    secoes_campos = (
        (
            "Empreiteiro e vigência",
            "O boletim usa a tabela vigente na data de emissão.",
            ("empresa", "fornecedor", "vigencia_inicio", "vigencia_fim", "observacao"),
        ),
        (
            "Faixas de VMI (R$ por m³)",
            (
                "O talhão usa a faixa de maior VMI que não passa do VMI dele "
                "(VMI 0,34 usa a faixa 0,33)."
            ),
            (
                "faixas_ate_5",
                "comprimento_tora_ate_5",
                "faixas_acima_5",
                "comprimento_tora_acima_5",
            ),
        ),
    )

    class Meta:
        model = TabelaPrecoColheita
        fields = [
            "empresa",
            "fornecedor",
            "vigencia_inicio",
            "vigencia_fim",
            "comprimento_tora_ate_5",
            "comprimento_tora_acima_5",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "fornecedor": "Empreiteiro",
            "vigencia_inicio": "Vigente a partir de",
            "vigencia_fim": "Vigente até",
            "observacao": "Observação",
        }
        widgets = {"vigencia_inicio": ENTRADA_DATA, "vigencia_fim": ENTRADA_DATA}

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["fornecedor"].queryset = self.fields[
            "fornecedor"
        ].queryset.filter(fornece_servico=True)
        if self.instance.pk:
            self.fields["faixas_ate_5"].initial = _faixas_em_texto(
                self.instance, Inclinacao.ATE_5
            )
            self.fields["faixas_acima_5"].initial = _faixas_em_texto(
                self.instance, Inclinacao.ACIMA_5
            )
        self.faixas: dict[str, list] = {}

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("vigencia_inicio"), dados.get("vigencia_fim")
        if inicio and fim and fim < inicio:
            self.add_error("vigencia_fim", "O fim é anterior ao início.")
        for campo, inclinacao in (
            ("faixas_ate_5", Inclinacao.ATE_5),
            ("faixas_acima_5", Inclinacao.ACIMA_5),
        ):
            try:
                faixas = _ler_faixas(dados.get(campo) or "")
            except forms.ValidationError as erro:
                self.add_error(campo, erro)
                continue
            vmis = [faixa[0] for faixa in faixas]
            if len(set(vmis)) != len(vmis):
                self.add_error(campo, "Há VMI repetido nas faixas.")
            self.faixas[inclinacao] = faixas
        if not self.faixas.get(Inclinacao.ATE_5) and "faixas_ate_5" not in self.errors:
            self.add_error("faixas_ate_5", "Informe ao menos uma faixa.")
        return dados

    def salvar_extras(self, registro: TabelaPrecoColheita) -> None:
        registro.faixas.all().delete()
        FaixaPrecoColheita.objects.bulk_create(
            FaixaPrecoColheita(
                tabela=registro,
                inclinacao=inclinacao,
                vmi_minimo=vmi,
                preco_derrubada=derrubada,
                preco_arraste=arraste,
                preco_tracamento=tracamento,
            )
            for inclinacao, faixas in self.faixas.items()
            for vmi, derrubada, arraste, tracamento in faixas
        )


class TabelaPrecoColheitaGestorForm(TabelaPrecoColheitaForm):
    class Meta(TabelaPrecoColheitaForm.Meta):
        fields = _sem_empresa(TabelaPrecoColheitaForm.Meta.fields)


class BoletimMedicaoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fornecedor",)
    secoes_campos = (
        (
            "Boletim",
            (
                "Entram os lançamentos de colheita do empreiteiro no período que "
                "ainda não estão em outro boletim (derrubada, arraste e traçamento)."
            ),
            ("empresa", "fornecedor", "data_emissao", "periodo_inicio", "periodo_fim"),
        ),
        (
            "Assinaturas e situação",
            "Fechado, o boletim não muda mais; cancelado, os lançamentos voltam.",
            (
                "elaborado_por",
                "validado_por",
                "status",
                "data_pagamento",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = BoletimMedicao
        fields = [
            "empresa",
            "fornecedor",
            "data_emissao",
            "periodo_inicio",
            "periodo_fim",
            "elaborado_por",
            "validado_por",
            "status",
            "data_pagamento",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "fornecedor": "Empreiteiro",
            "periodo_inicio": "Lançamentos de",
            "periodo_fim": "Lançamentos até",
            "elaborado_por": "Elaborado por",
            "validado_por": "Validado por",
            "data_pagamento": "Data do pagamento",
            "observacao": "Observação",
        }
        widgets = {
            "data_emissao": ENTRADA_DATA,
            "periodo_inicio": ENTRADA_DATA,
            "periodo_fim": ENTRADA_DATA,
            "data_pagamento": ENTRADA_DATA,
        }

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["fornecedor"].queryset = self.fields[
            "fornecedor"
        ].queryset.filter(fornece_servico=True)
        if not self.instance.pk:
            del self.fields["status"]
            del self.fields["data_pagamento"]
            self.fields["data_emissao"].initial = timezone.localdate()
        else:
            for nome in ("fornecedor", "periodo_inicio", "periodo_fim"):
                self.fields[nome].disabled = True

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("periodo_inicio"), dados.get("periodo_fim")
        if inicio and fim and fim < inicio:
            self.add_error("periodo_fim", "O fim é anterior ao início.")
        fornecedor, emissao = dados.get("fornecedor"), dados.get("data_emissao")
        if self.instance.pk or not (fornecedor and emissao and inicio and fim):
            if dados.get("status") == StatusBoletim.PAGO and not dados.get(
                "data_pagamento"
            ):
                self.add_error("data_pagamento", "Informe a data do pagamento.")
            return dados
        if TabelaPrecoColheita.vigente(fornecedor.pk, emissao) is None:
            self.add_error(
                "fornecedor",
                "Cadastre a tabela de preço deste empreiteiro vigente na emissão.",
            )
        existe = Colheita.objects.filter(
            fornecedor=fornecedor,
            boletim__isnull=True,
            etapa__in=[etapa for etapa, _, _ in ETAPAS_DO_BOLETIM],
            data_inicio__range=(inicio, fim),
        ).exists()
        if not existe:
            self.add_error(
                "periodo_fim",
                "Não há lançamentos de colheita deste empreiteiro no período "
                "fora de outro boletim.",
            )
        return dados

    def salvar_extras(self, registro: BoletimMedicao) -> None:
        if not registro.itens.exists() and registro.status == StatusBoletim.ABERTO:
            registro.gerar_itens()
        if registro.status == StatusBoletim.CANCELADO:
            registro.liberar_lancamentos()


class BoletimMedicaoGestorForm(BoletimMedicaoForm):
    class Meta(BoletimMedicaoForm.Meta):
        fields = _sem_empresa(BoletimMedicaoForm.Meta.fields)


class BoletimTransporteForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("fornecedor",)
    secoes_campos = (
        (
            "Boletim",
            (
                "Entram as viagens terceirizadas da transportadora no período que "
                "ainda não estão em outro boletim. Sem valor na viagem, vale a "
                "tarifa de transporte de lenha vigente na data."
            ),
            ("empresa", "fornecedor", "data_emissao", "periodo_inicio", "periodo_fim"),
        ),
        (
            "Descontos e adiantamento",
            "Líquido a pagar = valor das viagens - desconto - adiantamento.",
            ("valor_desconto", "motivo_desconto", "valor_adiantamento"),
        ),
        (
            "Assinaturas e situação",
            "Fechado, o boletim e as viagens dele não mudam mais.",
            (
                "elaborado_por",
                "validado_por",
                "status",
                "data_pagamento",
                "observacao",
            ),
        ),
    )

    class Meta:
        model = BoletimTransporte
        fields = [
            "empresa",
            "fornecedor",
            "data_emissao",
            "periodo_inicio",
            "periodo_fim",
            "valor_desconto",
            "motivo_desconto",
            "valor_adiantamento",
            "elaborado_por",
            "validado_por",
            "status",
            "data_pagamento",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "fornecedor": "Transportadora",
            "periodo_inicio": "Viagens de",
            "periodo_fim": "Viagens até",
            "motivo_desconto": "Motivo do desconto",
            "elaborado_por": "Elaborado por",
            "validado_por": "Validado por",
            "data_pagamento": "Data do pagamento",
            "observacao": "Observação",
        }
        help_texts = {"motivo_desconto": "Quebra, avaria, multa..."}
        widgets = {
            "data_emissao": ENTRADA_DATA,
            "periodo_inicio": ENTRADA_DATA,
            "periodo_fim": ENTRADA_DATA,
            "data_pagamento": ENTRADA_DATA,
        }

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["fornecedor"].queryset = self.fields[
            "fornecedor"
        ].queryset.filter(fornece_servico=True)
        if not self.instance.pk:
            del self.fields["status"]
            del self.fields["data_pagamento"]
            self.fields["data_emissao"].initial = timezone.localdate()
        else:
            for nome in ("fornecedor", "periodo_inicio", "periodo_fim"):
                self.fields[nome].disabled = True

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("periodo_inicio"), dados.get("periodo_fim")
        if inicio and fim and fim < inicio:
            self.add_error("periodo_fim", "O fim é anterior ao início.")
        for campo in ("valor_desconto", "valor_adiantamento"):
            valor = dados.get(campo)
            if valor is not None and valor < 0:
                self.add_error(campo, "Informe um valor positivo.")
        if dados.get("valor_desconto") and not dados.get("motivo_desconto"):
            self.add_error("motivo_desconto", "Informe o motivo do desconto.")
        if dados.get("status") == StatusBoletim.PAGO and not dados.get(
            "data_pagamento"
        ):
            self.add_error("data_pagamento", "Informe a data do pagamento.")
        fornecedor = dados.get("fornecedor")
        if not self.instance.pk and fornecedor and inicio and fim:
            existe = TransporteLenha.objects.filter(
                fornecedor=fornecedor,
                tipo_transporte=TipoTransporte.TERCEIRIZADO,
                boletim__isnull=True,
                data_transporte__range=(inicio, fim),
            ).exists()
            if not existe:
                self.add_error(
                    "periodo_fim",
                    "Não há viagens terceirizadas desta transportadora no período "
                    "fora de outro boletim.",
                )
        return dados

    def salvar_extras(self, registro: BoletimTransporte) -> None:
        if registro.status == StatusBoletim.CANCELADO:
            registro.liberar_viagens()
        elif not registro.viagens.exists() and registro.status == StatusBoletim.ABERTO:
            registro.gerar()
        registro.recalcular()


class BoletimTransporteGestorForm(BoletimTransporteForm):
    class Meta(BoletimTransporteForm.Meta):
        fields = _sem_empresa(BoletimTransporteForm.Meta.fields)


class PlanejamentoFornoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("forno",)
    quantidade = forms.IntegerField(
        label="Planejar também os próximos fornos",
        min_value=1,
        max_value=LIMITE_FORNOS_EM_LOTE,
        initial=1,
        required=False,
        help_text="Quantos fornos da UPC, a partir deste, em ordem de número.",
    )
    fornos_por_dia = forms.IntegerField(
        label="Fornos enchidos por dia",
        min_value=1,
        initial=1,
        required=False,
        help_text="Escalona o primeiro enchimento: a cada N fornos, um dia depois.",
    )
    secoes_campos = (
        (
            "Forno e mês",
            (
                "O mês é o do primeiro enchimento previsto. Daí em diante os "
                "ciclos são projetados pelos prazos do tipo de forno."
            ),
            ("empresa", "forno", "data_primeiro_enchimento", "mdc_previsto"),
        ),
        (
            "Vários fornos de uma vez",
            "Os planejamentos que já existirem no mês são substituídos.",
            ("quantidade", "fornos_por_dia", "observacao"),
        ),
    )

    class Meta:
        model = PlanejamentoForno
        fields = [
            "empresa",
            "forno",
            "data_primeiro_enchimento",
            "mdc_previsto",
            "observacao",
        ]
        labels = {
            "empresa": "Empresa/unidade",
            "observacao": "Observação",
        }
        help_texts = {
            "mdc_previsto": "Em branco: a capacidade do forno (ou do tipo).",
        }
        widgets = {"data_primeiro_enchimento": ENTRADA_DATA}

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.fields["forno"].queryset = self.fields["forno"].queryset.exclude(
            situacao=SituacaoForno.DESATIVADO
        )
        self.planos_extras: list[tuple[Forno, date]] = []
        if self.instance.pk:
            del self.fields["quantidade"]
            del self.fields["fornos_por_dia"]

    def clean(self):
        dados = super().clean()
        forno, data = dados.get("forno"), dados.get("data_primeiro_enchimento")
        if not forno or not data:
            return dados
        repetido = (
            PlanejamentoForno.objects.filter(forno=forno, mes=data.replace(day=1))
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if repetido and not self.instance.pk:
            self.add_error("forno", "Este forno já tem planejamento no mês. Edite-o.")
        quantidade = dados.get("quantidade") or 1
        por_dia = dados.get("fornos_por_dia") or 1
        seguintes = list(
            self.fields["forno"]
            .queryset.filter(upc_id=forno.upc_id)
            .order_by("numero")
            .filter(tipo_forno_id=forno.tipo_forno_id, numero__gt=forno.numero)[
                : quantidade - 1
            ]
        )
        self.planos_extras = [
            (outro, data + timedelta(days=(posicao // por_dia)))
            for posicao, outro in enumerate(seguintes, start=1)
        ]
        return dados

    def salvar_extras(self, registro: PlanejamentoForno) -> None:
        for forno, data in self.planos_extras:
            PlanejamentoForno.objects.update_or_create(
                forno=forno,
                mes=data.replace(day=1),
                defaults={
                    "empresa_id": registro.empresa_id,
                    "data_primeiro_enchimento": data,
                    "mdc_previsto": registro.mdc_previsto,
                    "observacao": registro.observacao,
                    "usuario_inclusao": registro.usuario_inclusao,
                    "usuario_alteracao": registro.usuario_alteracao,
                },
            )


class PlanejamentoFornoGestorForm(PlanejamentoFornoForm):
    class Meta(PlanejamentoFornoForm.Meta):
        fields = _sem_empresa(PlanejamentoFornoForm.Meta.fields)


class LancamentoCustoForm(FormularioDaEmpresa, FormularioEmSecoes):
    campos_da_empresa = ("centro_custo", "categoria", "fornecedor", "equipamento")
    secoes_campos = (
        (
            "Lançamento",
            (
                "Um lançamento por gasto. Transporte terceirizado e frete do carvão "
                "não entram aqui."
            ),
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
            "data_lancamento": ENTRADA_DATA,
            "competencia": ENTRADA_DATA,
            "data_pagamento": ENTRADA_DATA,
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
