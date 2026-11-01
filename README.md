# RVC-FC

Sistema de acesso e cadastros administrativos baseado no documento
`Tabeslas siatema.docx`. O gerenciamento é feito pelas telas do sistema; o
site administrativo padrão do Django não é habilitado.

## Executar localmente

Na raiz do repositório, com o ambiente virtual do projeto ativo:

```bash
PYTHONPATH=src DJANGO_SETTINGS_MODULE=core.settings python -m django migrate
PYTHONPATH=src DJANGO_SETTINGS_MODULE=core.settings python -m django importar_localidades_docx
PYTHONPATH=src DJANGO_SETTINGS_MODULE=core.settings python -m django createsuperuser
PYTHONPATH=src DJANGO_SETTINGS_MODULE=core.settings python -m django runserver
```

Abra <http://127.0.0.1:8000/entrar/> e entre com a conta criada. A senha do
primeiro acesso deve ser trocada antes de usar o sistema.

## Interface

O painel inicial resume os cadastros conforme o perfil de acesso. As listagens
permitem buscar registros e exibem até 25 itens por página. Administradores
gerenciam empresas, usuários, parâmetros e dados de referência; gestores veem
os dados de fazendas vinculados à própria empresa. Os formulários são divididos
em seções de identificação, endereço, contato e configurações. Nas empresas e
fazendas, a lista de cidades acompanha o estado selecionado.

## Cadastros

O administrador do sistema mantém empresas, usuários/gestores, parâmetros,
estados, cidades e códigos IBGE. Gestores têm acesso às fazendas da própria
empresa. Estados, cidades e códigos IBGE são importados do DOCX pelo comando
`importar_localidades_docx`, que pode ser executado novamente sem duplicar
registros. O documento fornece as tabelas de referência, mas não dados reais de
empresas ou fazendas; após entrar, cadastre a primeira empresa pelo atalho do
painel para habilitar os cadastros dependentes.
