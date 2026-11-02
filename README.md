# RVC-FC

Sistema de acesso e cadastros administrativos. O gerenciamento é feito pelas
telas do sistema; o site administrativo padrão do Django não é habilitado.

## Executar localmente

No Windows PowerShell, na raiz do repositório:

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venv-windows"
uv sync --python 3.15
uv run python src\manage.py migrate
uv run python src\manage.py sincronizar_municipios_ibge
uv run python src\manage.py createsuperuser
uv run python src\manage.py runserver
```

Abra <http://127.0.0.1:8000/entrar/> e entre com a conta criada. A lista de
municípios é obtida da API oficial do IBGE; sincronize-a novamente quando
precisar atualizar os dados.

## Interface

O painel inicial resume os cadastros conforme o perfil de acesso. As listagens
permitem buscar registros e exibem até 25 itens por página. Administradores
gerenciam empresas, usuários, parâmetros e consultam os dados de referência;
gestores veem as fazendas vinculadas à própria empresa. Os formulários são
divididos em seções de identificação, endereço, contato e configurações. Nas
empresas e fazendas, selecionar o estado carrega os municípios oficiais com o
código IBGE de sete dígitos usado na NF-e.

## Cadastros

O administrador do sistema mantém empresas, usuários/gestores e parâmetros.
Estados e municípios são sincronizados pelo comando
`sincronizar_municipios_ibge`; o cadastro de municípios é único, consultivo e
usa os códigos oficiais do IBGE. Gestores têm acesso às fazendas da própria
empresa. Após entrar, sincronize os municípios e cadastre a primeira empresa
para habilitar os cadastros dependentes.
