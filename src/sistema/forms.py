from django import forms
from django.contrib.auth.password_validation import validate_password

from sistema.models import (
    Cidade,
    CodigoIBGE,
    Empresa,
    Estado,
    Fazenda,
    Parametros,
    TipoUsuario,
    Usuario,
)


class FormularioEmSecoes(forms.ModelForm):
    secoes_campos = ()

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        if "cidade" in self.fields:
            valor_estado = (
                self.data.get("estado")
                if self.is_bound
                else self.initial.get("estado", self.instance.estado_id)
            )
            codigo_estado = getattr(valor_estado, "pk", valor_estado)
            if codigo_estado and str(codigo_estado).isdecimal():
                self.fields["cidade"].queryset = Cidade.objects.filter(
                    estado_id=codigo_estado
                )
            else:
                self.fields["cidade"].queryset = Cidade.objects.none()
            self.fields[
                "cidade"
            ].help_text = "Escolha o estado para carregar as cidades correspondentes."

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


class EmpresaForm(FormularioEmSecoes):
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
            "Selecione o estado antes de conferir a cidade e o código IBGE.",
            (
                "estado",
                "cidade",
                "codigo_ibge",
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
            "cidade",
            "codigo_ibge",
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
            "cidade": "Cidade",
            "codigo_ibge": "Código IBGE do município",
            "endereco": "Logradouro",
            "numero": "Número",
            "complemento": "Complemento",
            "bairro": "Bairro",
        }
        help_texts = {
            "codigo_ibge": "Código de sete dígitos do município.",
            "site": "Informe o endereço completo, incluindo https://.",
        }

    def clean(self):
        dados = super().clean()
        estado, cidade = dados.get("estado"), dados.get("cidade")
        if estado and cidade and cidade.estado_id != estado.pk:
            self.add_error("cidade", "Selecione uma cidade do estado informado.")
        return dados


class UsuarioForm(FormularioEmSecoes):
    secoes_campos = (
        (
            "Dados de acesso",
            "O usuário recebe uma senha temporária e deverá alterá-la ao entrar.",
            ("username", "senha", "is_active"),
        ),
        (
            "Dados do gestor",
            "Cada gestor fica associado a uma empresa/unidade.",
            ("nome_completo", "email", "empresa"),
        ),
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


class FazendaForm(FormularioEmSecoes):
    secoes_campos = (
        (
            "Identificação da fazenda",
            "Informe o responsável, documento e tipo de relação com a unidade.",
            ("empresa", "tipo_pessoa", "cpf_cnpj", "nome", "relacao"),
        ),
        (
            "Inscrições",
            "Dados fiscais opcionais do proprietário ou da propriedade.",
            ("inscricao_estadual", "inscricao_municipal"),
        ),
        (
            "Endereço da propriedade",
            "Informe a localização da fazenda e o código IBGE do município.",
            (
                "estado",
                "cidade",
                "codigo_ibge",
                "cep",
                "endereco",
                "numero",
                "complemento",
                "bairro",
            ),
        ),
        (
            "Contato",
            "Canais de contato do responsável pela propriedade.",
            ("telefone", "celular", "email", "site"),
        ),
    )

    class Meta:
        model = Fazenda
        fields = [
            "empresa",
            "tipo_pessoa",
            "cpf_cnpj",
            "nome",
            "relacao",
            "inscricao_estadual",
            "inscricao_municipal",
            "estado",
            "cidade",
            "codigo_ibge",
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
            "empresa": "Empresa/unidade",
            "tipo_pessoa": "Tipo de pessoa",
            "cpf_cnpj": "CPF/CNPJ",
            "nome": "Nome ou razão social",
            "relacao": "Relação com a unidade",
            "inscricao_estadual": "Inscrição estadual",
            "inscricao_municipal": "Inscrição municipal",
            "estado": "Estado",
            "cidade": "Cidade",
            "codigo_ibge": "Código IBGE do município",
            "endereco": "Logradouro",
            "numero": "Número",
            "complemento": "Complemento",
            "bairro": "Bairro",
        }
        help_texts = {
            "cpf_cnpj": "Informe o documento sem pontos ou traços.",
            "codigo_ibge": "Código de sete dígitos do município.",
            "site": "Informe o endereço completo, incluindo https://.",
        }

    def clean(self):
        dados = super().clean()
        estado, cidade = dados.get("estado"), dados.get("cidade")
        if estado and cidade and cidade.estado_id != estado.pk:
            self.add_error("cidade", "Selecione uma cidade do estado informado.")
        return dados


class FazendaGestorForm(FormularioEmSecoes):
    secoes_campos = (
        (
            "Identificação da fazenda",
            "Informe o responsável, documento e tipo de relação com a unidade.",
            ("tipo_pessoa", "cpf_cnpj", "nome", "relacao"),
        ),
        (
            "Inscrições",
            "Dados fiscais opcionais do proprietário ou da propriedade.",
            ("inscricao_estadual", "inscricao_municipal"),
        ),
        (
            "Endereço da propriedade",
            "Informe a localização da fazenda e o código IBGE do município.",
            (
                "estado",
                "cidade",
                "codigo_ibge",
                "cep",
                "endereco",
                "numero",
                "complemento",
                "bairro",
            ),
        ),
        (
            "Contato",
            "Canais de contato do responsável pela propriedade.",
            ("telefone", "celular", "email", "site"),
        ),
    )

    class Meta:
        model = Fazenda
        fields = [
            "tipo_pessoa",
            "cpf_cnpj",
            "nome",
            "relacao",
            "inscricao_estadual",
            "inscricao_municipal",
            "estado",
            "cidade",
            "codigo_ibge",
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
        labels = FazendaForm.Meta.labels
        help_texts = FazendaForm.Meta.help_texts

    def clean(self):
        dados = super().clean()
        estado, cidade = dados.get("estado"), dados.get("cidade")
        if estado and cidade and cidade.estado_id != estado.pk:
            self.add_error("cidade", "Selecione uma cidade do estado informado.")
        return dados


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


class EstadoForm(FormularioEmSecoes):
    secoes_campos = (
        (
            "Dados do estado",
            "Cadastre o código oficial e a sigla da UF.",
            ("codigo", "uf"),
        ),
    )

    class Meta:
        model = Estado
        fields = ["codigo", "uf"]
        labels = {"codigo": "Código do estado", "uf": "Sigla da UF"}


class CidadeForm(FormularioEmSecoes):
    secoes_campos = (
        (
            "Dados do município",
            "Informe o código de referência, estado e nome da cidade.",
            ("codigo", "estado", "cidade"),
        ),
    )

    class Meta:
        model = Cidade
        fields = ["codigo", "estado", "cidade"]
        labels = {
            "codigo": "Código da cidade",
            "estado": "Estado",
            "cidade": "Nome da cidade",
        }


class CodigoIBGEForm(FormularioEmSecoes):
    secoes_campos = (
        (
            "Identificação IBGE",
            "Referência do município conforme a tabela do documento do sistema.",
            (
                "empresa",
                "codigo_estado",
                "uf",
                "nome_uf",
                "codigo_cidade",
                "nome_cidade",
            ),
        ),
        (
            "Situação do registro",
            "Mantenha os indicadores de situação usados pela tabela.",
            ("situacao_registro", "status_registro"),
        ),
    )

    class Meta:
        model = CodigoIBGE
        fields = [
            "empresa",
            "codigo_estado",
            "uf",
            "nome_uf",
            "codigo_cidade",
            "nome_cidade",
            "situacao_registro",
            "status_registro",
        ]
        labels = {
            "empresa": "Código da empresa",
            "codigo_estado": "Código do estado",
            "uf": "Sigla da UF",
            "nome_uf": "Nome do estado",
            "codigo_cidade": "Código IBGE da cidade",
            "nome_cidade": "Nome da cidade",
            "situacao_registro": "Situação do registro",
            "status_registro": "Status do registro",
        }
