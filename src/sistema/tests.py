import json
from decimal import Decimal
from gzip import compress as compress_gzip
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sistema.forms import (
    AutorizacaoAmbientalGestorForm,
    ColheitaGestorForm,
    EmpresaForm,
    ExpedicaoGestorForm,
    FazendaForm,
    FazendaGestorForm,
    FornecedorForm,
    FornecedorGestorForm,
    InventarioFlorestalGestorForm,
    InventarioTalhaoGestorForm,
    ParametrosForm,
    PlantioForm,
    PlantioGestorForm,
    ProprietarioForm,
    ProprietarioGestorForm,
    TalhaoForm,
    TalhaoGestorForm,
    TransporteLenhaGestorForm,
    UPCGestorForm,
    UsuarioForm,
)
from sistema.models import (
    UPC,
    AutorizacaoAmbiental,
    CategoriaCusto,
    CentroCusto,
    Empresa,
    Equipamento,
    Estado,
    Fazenda,
    Fornecedor,
    InventarioFlorestal,
    LancamentoCusto,
    LancamentoCustoRateio,
    Municipio,
    Plantio,
    ProducaoCarvao,
    Proprietario,
    Talhao,
)
from sistema.views import RECURSOS

ADMIN_CREDENTIAL = "Admin-seguro#7291"
GESTOR_CREDENTIAL = "Gestor-seguro#7291"
INITIAL_CREDENTIAL = "Inicial-seguro#7291"
NEW_CREDENTIAL = "Nova-senha-segura#9382"


class FluxoAdministrativoTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.estado = Estado.objects.create(
            codigo=31,
            uf="MG",
            nome="Minas Gerais",
        )
        cls.municipio = Municipio.objects.create(
            codigo="3143302",
            nome="Montes Claros",
            estado=cls.estado,
        )
        cls.empresa = cls.criar_empresa("Empresa A", "00000000000191")
        cls.outra_empresa = cls.criar_empresa("Empresa B", "00000000000272")

        usuario_modelo = get_user_model()
        cls.administrador = usuario_modelo.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=ADMIN_CREDENTIAL,
            nome_completo="Administrador",
        )
        cls.administrador.primeiro_acesso = False
        cls.administrador.save(update_fields=["primeiro_acesso"])

        cls.gestor = usuario_modelo.objects.create_user(
            username="gestor",
            email="gestor@example.com",
            password=GESTOR_CREDENTIAL,
            nome_completo="Gestor da Unidade",
            empresa=cls.empresa,
            primeiro_acesso=False,
        )
        cls.proprietario_proprio = Proprietario.objects.create(
            empresa=cls.empresa,
            nome_razao_social="Proprietário da unidade",
            cpf_cnpj="12345678000199",
            municipio=cls.municipio,
        )
        cls.proprietario_alheio = Proprietario.objects.create(
            empresa=cls.outra_empresa,
            nome_razao_social="Proprietário de outra empresa",
            cpf_cnpj="12345678901",
        )
        cls.fazenda_propria = Fazenda.objects.create(
            empresa=cls.empresa,
            proprietario=cls.proprietario_proprio,
            nome="Fazenda da unidade",
            area_total_ha="10.5000",
            municipio=cls.municipio,
        )
        cls.fazenda_alheia = Fazenda.objects.create(
            empresa=cls.outra_empresa,
            proprietario=cls.proprietario_alheio,
            nome="Fazenda de outra empresa",
            area_total_ha="5.0000",
            municipio=cls.municipio,
        )

    @classmethod
    def criar_empresa(cls, nome: str, cnpj: str) -> Empresa:
        return Empresa.objects.create(
            cnpj=cnpj,
            razao_social=nome,
            endereco="Rua A",
            bairro="Centro",
            municipio=cls.municipio,
        )

    def test_usuario_novo_precisa_trocar_senha(self):
        usuario = get_user_model().objects.create_user(
            username="primeiro",
            email="primeiro@example.com",
            password=INITIAL_CREDENTIAL,
            nome_completo="Primeiro Acesso",
            empresa=self.empresa,
        )
        self.client.force_login(usuario)

        resposta = self.client.get(reverse("inicio"))

        self.assertRedirects(resposta, reverse("password_change"))

    def test_troca_de_senha_libera_acesso(self):
        usuario = get_user_model().objects.create_user(
            username="primeiro",
            email="primeiro@example.com",
            password=INITIAL_CREDENTIAL,
            nome_completo="Primeiro Acesso",
            empresa=self.empresa,
        )
        self.client.force_login(usuario)

        resposta = self.client.post(
            reverse("password_change"),
            {
                "old_password": INITIAL_CREDENTIAL,
                "new_password1": NEW_CREDENTIAL,
                "new_password2": NEW_CREDENTIAL,
            },
            follow=True,
        )

        usuario.refresh_from_db()
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(usuario.primeiro_acesso)
        self.assertTrue(usuario.check_password(NEW_CREDENTIAL))

    def test_gestor_so_lista_fazendas_da_sua_empresa(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(reverse("lista_registros", args=["fazendas"]))

        self.assertEqual(resposta.status_code, 200)
        objetos = [linha["objeto"] for linha in resposta.context["linhas"]]
        self.assertEqual(objetos, [self.fazenda_propria])

    def test_painel_do_gestor_resume_somente_sua_empresa(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(reverse("inicio"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["resumo"]["fazendas"], 1)
        self.assertEqual(resposta.context["resumo"]["proprietarios"], 1)

    def test_todas_as_telas_abrem_para_administrador_e_gestor(self):
        gestor_ids = {
            nome for nome, cfg in RECURSOS.items() if not cfg["somente_admin"]
        }
        for usuario, recursos in (
            (self.administrador, set(RECURSOS)),
            (self.gestor, gestor_ids),
        ):
            self.client.force_login(usuario)
            if usuario == self.administrador:
                self.client.post(
                    reverse("selecionar_empresa"), {"empresa": self.empresa.pk}
                )
            for recurso in sorted(recursos):
                rotas = [("lista_registros", [recurso])]
                if not RECURSOS[recurso].get("somente_leitura"):
                    rotas.append(("novo_registro", [recurso]))
                for rota, args in rotas:
                    resposta = self.client.get(reverse(rota, args=args))
                    self.assertEqual(
                        resposta.status_code, 200, f"{usuario} {rota} {recurso}"
                    )

    def test_gestor_cadastra_centro_custo_e_equipamento_na_propria_empresa(self):
        self.client.force_login(self.gestor)
        resposta = self.client.post(
            reverse("novo_registro", args=["centros-custo"]),
            {"nome": "Administração", "tipo": "ADMINISTRATIVO"},
        )
        self.assertEqual(resposta.status_code, 302)
        centro = CentroCusto.objects.get(nome="Administração")
        self.assertEqual(centro.empresa, self.empresa)

        sem_upc = self.client.post(
            reverse("novo_registro", args=["centros-custo"]),
            {"nome": "UPC X", "tipo": "UPC"},
        )
        self.assertEqual(sem_upc.status_code, 200)
        self.assertFalse(CentroCusto.objects.filter(nome="UPC X").exists())

        dados = {
            "descricao": "Caminhão 1",
            "tipo": "CAMINHAO",
            "placa": "ABC1D23",
            "propriedade": "PROPRIO",
            "centro_custo": centro.pk,
        }
        self.client.post(reverse("novo_registro", args=["equipamentos"]), dados)
        duplicado = self.client.post(
            reverse("novo_registro", args=["equipamentos"]), dados
        )
        self.assertEqual(Equipamento.objects.count(), 1)
        self.assertEqual(duplicado.status_code, 200)

    def test_lancamento_custo_e_rateio_calculam_valores_e_limitam_soma(self):
        administrativo = CentroCusto.objects.create(
            empresa=self.empresa, nome="Adm", tipo="ADMINISTRATIVO"
        )
        outro = CentroCusto.objects.create(
            empresa=self.empresa, nome="Oficina", tipo="ADMINISTRATIVO"
        )
        categoria = CategoriaCusto.objects.create(
            empresa=self.empresa, nome="Diesel", grupo="OPERACIONAL"
        )
        self.client.force_login(self.gestor)
        resposta = self.client.post(
            reverse("novo_registro", args=["lancamentos-custo"]),
            {
                "data_lancamento": "2026-03-15",
                "centro_custo": administrativo.pk,
                "categoria": categoria.pk,
                "descricao": "Diesel",
                "quantidade": "100",
                "valor_unitario": "6.5",
            },
        )
        self.assertEqual(resposta.status_code, 302, resposta.content[:0])
        lancamento = LancamentoCusto.objects.get()
        self.assertEqual(lancamento.valor_total, Decimal("650.00"))
        self.assertEqual(str(lancamento.competencia), "2026-03-01")
        self.assertEqual(lancamento.situacao_pagamento, "A pagar")

        rateio = LancamentoCustoRateio.objects.create(
            empresa=self.empresa,
            lancamento=lancamento,
            centro_custo=administrativo,
            percentual=Decimal("40"),
        )
        self.assertEqual(rateio.valor, Decimal("260.00"))
        lancamento.refresh_from_db()
        self.assertTrue(lancamento.rateado)

        dados = {
            "lancamento": lancamento.pk,
            "centro_custo": outro.pk,
            "percentual": "70",
        }
        recusado = self.client.post(
            reverse("novo_registro", args=["rateios-custo"]), dados
        )
        self.assertEqual(recusado.status_code, 200)
        dados["percentual"] = "60"
        aceito = self.client.post(
            reverse("novo_registro", args=["rateios-custo"]), dados
        )
        self.assertEqual(aceito.status_code, 302)
        self.assertEqual(lancamento.percentual_rateado, Decimal("100"))

    def test_producao_carvao_calcula_rendimento_e_alerta(self):
        upc = UPC.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            nome="U1",
            utm_leste="1",
            utm_norte="1",
            numero_fornos=1,
            volume_forno_mdc="1",
            ciclo_producao_dias=8,
        )
        producao = ProducaoCarvao.objects.create(
            empresa=self.empresa,
            upc=upc,
            data_producao="2026-01-10",
            volume_mdc=Decimal("77"),
            volume_lenha_m3=Decimal("100"),
        )
        self.assertEqual(producao.rendimento_mdc_m3, Decimal("0.7700"))
        self.assertEqual(producao.alerta_rendimento, "")
        producao.volume_mdc = Decimal("30")
        producao.save()
        self.assertEqual(producao.alerta_rendimento, "Abaixo do esperado")

        self.client.force_login(self.gestor)
        resposta = self.client.post(
            reverse("novo_registro", args=["producoes-carvao"]),
            {"upc": upc.pk, "data_producao": "2026-02-01", "volume_mdc": "10"},
        )
        self.assertEqual(resposta.status_code, 302)

    def test_administrador_escolhe_empresa_ativa_e_upc_nasce_nela(self):
        self.client.force_login(self.administrador)

        resposta = self.client.get(reverse("inicio"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Visão geral")
        self.assertContains(resposta, "Selecionar empresa")
        self.assertContains(resposta, reverse("selecionar_empresa"))

        self.client.post(reverse("selecionar_empresa"), {"empresa": self.empresa.pk})
        self.assertEqual(self.client.get(reverse("inicio")).status_code, 200)

        resposta = self.client.get(reverse("novo_registro", args=["upcs"]))
        campo = resposta.context["formulario"].fields["empresa"]
        self.assertEqual(campo.initial, self.empresa.pk)

        resposta = self.client.get(reverse("lista_registros", args=["fazendas"]))
        self.assertContains(resposta, "Fazenda da unidade")
        self.assertContains(resposta, "Fazenda de outra empresa")

    def test_menu_preserva_destino_ao_exigir_empresa_do_administrador(self):
        self.client.force_login(self.administrador)
        destino = reverse("lista_registros", args=["fazendas"])

        resposta = self.client.get(destino)
        url_selecao = resposta["Location"]
        self.assertIn("proximo=", url_selecao, url_selecao)
        self.assertRedirects(
            resposta,
            f"{reverse('selecionar_empresa')}?proximo={destino.replace('/', '%2F')}",
            fetch_redirect_response=False,
        )

        resposta = self.client.get(url_selecao)
        self.assertEqual(resposta.wsgi_request.GET.get("proximo"), destino)
        self.assertContains(resposta, f'name="proximo" value="{destino}"')
        resposta = self.client.post(
            url_selecao, {"empresa": self.empresa.pk, "proximo": destino}
        )
        self.assertRedirects(resposta, destino)
        self.assertEqual(self.client.get(destino).status_code, 200)

    def test_selecao_de_upc_preserva_destino_do_menu(self):
        dados_upc = {
            "empresa": self.empresa,
            "fazenda": self.fazenda_propria,
            "utm_leste": "1",
            "utm_norte": "1",
            "numero_fornos": 1,
            "volume_forno_mdc": "1",
            "ciclo_producao_dias": 1,
        }
        upc = UPC.objects.create(nome="UPC A", **dados_upc)
        outra_upc = UPC.objects.create(nome="UPC B", **dados_upc)
        self.gestor.upcs.add(upc, outra_upc)
        self.client.force_login(self.gestor)
        destino = reverse("lista_registros", args=["upcs"])

        resposta = self.client.get(destino)
        url_selecao = resposta["Location"]
        resposta = self.client.get(url_selecao)
        self.assertContains(resposta, "Escolha a UPC")
        self.assertContains(resposta, f'name="proximo" value="{destino}"')

        resposta = self.client.post(url_selecao, {"upc": upc.pk, "proximo": destino})
        self.assertRedirects(resposta, destino)
        self.assertEqual(self.client.get(destino).status_code, 200)

    def test_administrador_exclui_registro_e_protegido_com_vinculos(self):
        self.client.force_login(self.administrador)
        self.client.post(reverse("selecionar_empresa"), {"empresa": self.empresa.pk})

        resposta = self.client.post(
            reverse("excluir_registro", args=["fazendas", self.fazenda_propria.pk])
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertFalse(Fazenda.objects.filter(pk=self.fazenda_propria.pk).exists())

        resposta = self.client.post(
            reverse(
                "excluir_registro",
                args=["proprietarios", self.proprietario_proprio.pk],
            )
        )
        self.assertEqual(resposta.status_code, 302)

        self.client.post(
            reverse("excluir_registro", args=["empresas", self.empresa.pk])
        )
        self.assertTrue(Empresa.objects.filter(pk=self.empresa.pk).exists())

    def test_gestor_nao_exclui(self):
        self.client.force_login(self.gestor)
        resposta = self.client.post(
            reverse("excluir_registro", args=["fazendas", self.fazenda_propria.pk])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_menu_do_administrador_da_acesso_a_todos_os_cadastros(self):
        self.client.force_login(self.administrador)
        self.client.post(reverse("selecionar_empresa"), {"empresa": self.empresa.pk})

        resposta = self.client.get(reverse("inicio"))

        self.assertEqual(resposta.status_code, 200)
        for recurso in (
            "empresas",
            "usuarios",
            "parametros",
            "fazendas",
            "proprietarios",
            "fornecedores",
            "plantios",
            "talhoes",
            "estados",
            "municipios-ibge",
        ):
            with self.subTest(recurso=recurso):
                self.assertContains(
                    resposta,
                    reverse("lista_registros", args=[recurso]),
                )
        self.assertContains(resposta, reverse("password_change"))

    def test_menu_do_gestor_mostra_apenas_seus_cadastros_permitidos(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(reverse("inicio"))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(
            resposta,
            reverse("lista_registros", args=["fazendas"]),
        )
        self.assertContains(resposta, reverse("password_change"))
        for recurso in (
            "empresas",
            "usuarios",
            "parametros",
            "estados",
            "municipios-ibge",
        ):
            with self.subTest(recurso=recurso):
                self.assertNotContains(
                    resposta,
                    reverse("lista_registros", args=[recurso]),
                )

    def test_lista_de_municipios_ibge_tem_busca_e_paginacao(self):
        Municipio.objects.bulk_create(
            [
                Municipio(
                    codigo=str(1000000 + indice),
                    estado=self.estado,
                    nome=f"Município {indice}",
                )
                for indice in range(25)
            ]
        )
        self.client.force_login(self.administrador)

        resposta_lista = self.client.get(
            reverse("lista_registros", args=["municipios-ibge"])
        )
        resposta_busca = self.client.get(
            reverse("lista_registros", args=["municipios-ibge"]),
            {"q": "Montes"},
        )

        self.assertEqual(resposta_lista.context["pagina"].paginator.count, 26)
        self.assertEqual(len(resposta_lista.context["linhas"]), 25)
        self.assertTrue(resposta_lista.context["pagina"].has_next())
        self.assertEqual(resposta_busca.context["pagina"].paginator.count, 1)
        self.assertContains(resposta_lista, 'name="q"')
        self.assertNotContains(resposta_lista, "Novo cadastro")

    def test_gestor_nao_edita_fazenda_de_outra_empresa(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(
            reverse(
                "editar_registro",
                args=["fazendas", self.fazenda_alheia.pk],
            )
        )

        self.assertEqual(resposta.status_code, 404)

    def test_gestor_nao_acessa_cadastro_de_empresa(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(reverse("lista_registros", args=["empresas"]))

        self.assertEqual(resposta.status_code, 403)

    def test_django_admin_disponivel_para_superusuario(self):
        self.client.force_login(self.administrador)

        resposta = self.client.get("/admin/")

        self.assertEqual(resposta.status_code, 200)

    def test_administrador_cadastra_gestor_com_senha_inicial(self):
        self.client.force_login(self.administrador)

        resposta = self.client.post(
            reverse("novo_registro", args=["usuarios"]),
            {
                "username": "novo-gestor",
                "nome_completo": "Novo Gestor",
                "email": "novo@example.com",
                "empresa": self.empresa.pk,
                "is_active": "on",
                "senha": GESTOR_CREDENTIAL,
            },
        )

        usuario = get_user_model().objects.get(username="novo-gestor")
        self.assertRedirects(
            resposta,
            reverse("lista_registros", args=["usuarios"]),
        )
        self.assertTrue(usuario.check_password(GESTOR_CREDENTIAL))
        self.assertTrue(usuario.primeiro_acesso)
        self.assertEqual(usuario.usuario_inclusao, self.administrador)

    def test_tela_de_empresa_exibe_campos_em_secoes(self):
        self.client.force_login(self.administrador)

        resposta = self.client.get(reverse("novo_registro", args=["empresas"]))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Identificação da empresa")
        self.assertContains(resposta, "Endereço da unidade")
        self.assertContains(resposta, "Contato")
        self.assertContains(resposta, 'name="cnpj"')
        self.assertContains(resposta, 'name="municipio"')
        self.assertContains(resposta, 'name="email"')

    def test_formulario_de_edicao_mantem_municipio_historico_selecionavel(self):
        municipio_historico = Municipio.objects.create(
            codigo="3199999",
            nome="Município histórico",
            estado=self.estado,
            ativo=False,
        )
        empresa = self.empresa
        empresa.municipio = municipio_historico

        formulario = EmpresaForm(instance=empresa)

        self.assertEqual(formulario["estado"].value(), self.estado.pk)
        self.assertIn(
            municipio_historico,
            formulario.fields["municipio"].queryset,
        )

    def test_secoes_incluem_todos_os_campos_dos_formularios(self):
        for formulario_class in (
            EmpresaForm,
            UsuarioForm,
            FazendaForm,
            FazendaGestorForm,
            ProprietarioForm,
            ProprietarioGestorForm,
            FornecedorForm,
            FornecedorGestorForm,
            PlantioForm,
            PlantioGestorForm,
            TalhaoForm,
            TalhaoGestorForm,
            ParametrosForm,
        ):
            with self.subTest(formulario=formulario_class.__name__):
                formulario = formulario_class()
                campos_secionados = [
                    campo.name
                    for secao in formulario.secoes
                    for campo in secao["campos"]
                ]
                self.assertCountEqual(campos_secionados, formulario.fields)

    def test_tela_de_fazenda_do_gestor_omite_empresa(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(reverse("novo_registro", args=["fazendas"]))

        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, 'name="empresa"')
        self.assertContains(resposta, "Identificação do imóvel")
        self.assertContains(resposta, 'name="proprietario"')
        self.assertNotContains(resposta, 'name="relacao"')

    def test_proprietario_do_gestor_valida_duplicidade_e_municipio_opcional(self):
        self.client.force_login(self.gestor)
        url = reverse("novo_registro", args=["proprietarios"])
        dados = {"nome_razao_social": "Novo", "cpf_cnpj": "12345678000199"}

        resposta = self.client.post(url, dados)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Já existe um proprietário")

        dados["cpf_cnpj"] = "99999999999"
        resposta = self.client.post(url, dados)

        self.assertEqual(resposta.status_code, 302)
        novo = Proprietario.objects.get(cpf_cnpj="99999999999")
        self.assertEqual(novo.empresa, self.empresa)
        self.assertIsNone(novo.municipio)

    def test_fazenda_rejeita_proprietario_de_outra_empresa(self):
        formulario = FazendaGestorForm(
            {
                "proprietario": self.proprietario_alheio.pk,
                "nome": "Teste",
                "arrendado": "",
            },
            empresa=self.empresa,
        )

        self.assertFalse(formulario.is_valid())
        self.assertIn("proprietario", formulario.errors)

    def test_gestor_so_lista_proprietarios_da_sua_empresa(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(reverse("lista_registros", args=["proprietarios"]))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Proprietário da unidade")
        self.assertNotContains(resposta, "Proprietário de outra empresa")

    def test_fornecedor_exige_tipo_e_documento_unico_na_empresa(self):
        self.client.force_login(self.gestor)
        url = reverse("novo_registro", args=["fornecedores"])
        dados = {"nome_razao_social": "Transportes", "cpf_cnpj": "11111111000100"}

        resposta = self.client.post(url, dados)
        self.assertContains(resposta, "Marque ao menos um tipo")

        dados["fornece_servico"] = "on"
        self.assertEqual(self.client.post(url, dados).status_code, 302)
        resposta = self.client.post(url, dados)
        self.assertContains(resposta, "Já existe um registro")
        fornecedor = Fornecedor.objects.get(cpf_cnpj="11111111000100")
        self.assertEqual(fornecedor.empresa, self.empresa)
        self.assertEqual(fornecedor.tipos(), "Serviço")

    def test_plantio_exige_cadastro_ou_dispensa_e_calcula_idade(self):
        formulario = PlantioGestorForm(
            {"fazenda": self.fazenda_propria.pk, "origem": "EXOTICA", "rotacao": 1},
            empresa=self.empresa,
        )
        self.assertFalse(formulario.is_valid())
        self.assertIn("numero_cadastro", formulario.errors)

        outra = PlantioGestorForm(
            {
                "fazenda": self.fazenda_alheia.pk,
                "numero_cadastro": "PL1",
                "origem": "EXOTICA",
                "rotacao": 1,
            },
            empresa=self.empresa,
        )
        self.assertFalse(outra.is_valid())
        self.assertIn("fazenda", outra.errors)

        hoje = timezone.localdate()
        plantio = Plantio(data_plantio=hoje.replace(year=hoje.year - 9))
        self.assertEqual(plantio.idade_anos(), 9)

    def test_talhao_valida_geojson_plantio_da_fazenda_e_duplicidade(self):
        plantio = Plantio.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            numero_cadastro="PL1",
        )
        base = {
            "fazenda": self.fazenda_propria.pk,
            "plantio": plantio.pk,
            "identificacao": "T01",
            "area_ha": "2.5",
        }
        invalido = TalhaoGestorForm(
            {**base, "geometria": "{quebrado"}, empresa=self.empresa
        )
        self.assertFalse(invalido.is_valid())
        self.assertIn("geometria", invalido.errors)

        valido = TalhaoGestorForm(
            {**base, "geometria": '{"type": "Polygon"}'}, empresa=self.empresa
        )
        self.assertTrue(valido.is_valid(), valido.errors)
        talhao = valido.save(commit=False)
        talhao.empresa = self.empresa
        talhao.save()

        repetido = TalhaoGestorForm(base, empresa=self.empresa)
        self.assertFalse(repetido.is_valid())
        self.assertIn("identificacao", repetido.errors)

        outra_fazenda = Fazenda.objects.create(
            empresa=self.empresa,
            proprietario=self.proprietario_proprio,
            nome="Outra",
            area_total_ha="1",
            municipio=self.municipio,
        )
        cruzado = TalhaoGestorForm(
            {**base, "fazenda": outra_fazenda.pk}, empresa=self.empresa
        )
        self.assertFalse(cruzado.is_valid())
        self.assertIn("plantio", cruzado.errors)

    def test_upc_calcula_capacidade_e_exige_fazenda_da_empresa(self):
        dados = {
            "fazenda": self.fazenda_propria.pk,
            "nome": "UPC Mumbuca",
            "utm_leste": "574452.91",
            "utm_norte": "7897888.65",
            "utm_fuso": "23K",
            "numero_fornos": 66,
            "volume_forno_mdc": "18",
            "ciclo_producao_dias": 8,
        }
        form = UPCGestorForm(dados, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        upc = form.save(commit=False)
        upc.empresa = self.empresa
        upc.save()
        self.assertEqual(upc.volume_ciclo_mdc, 1188)
        self.assertEqual(str(upc.volume_mes_mdc), "4455.00")

        repetida = UPCGestorForm(dados, empresa=self.empresa)
        self.assertFalse(repetida.is_valid())
        self.assertIn("nome", repetida.errors)

        alheia = UPCGestorForm(
            {**dados, "nome": "Outra", "fazenda": self.fazenda_alheia.pk},
            empresa=self.empresa,
        )
        self.assertFalse(alheia.is_valid())
        self.assertIn("fazenda", alheia.errors)

    def test_inventario_calcula_derivados_e_valida_lote_talhao_e_mst(self):
        base = {
            "fazenda": self.fazenda_propria.pk,
            "lote": "Lote 1",
            "data_inventario": "2026-01-15",
            "responsavel_tecnico": "Eng. Teste",
            "registro_conselho": "CREA 1",
            "numero_art": "ART1",
            "area_ha": "50",
            "metodo_amostragem": "CASUAL_SIMPLES",
            "numero_parcelas": 7,
            "volume_total": "6000",
            "numero_arvores": "10000",
        }
        form = InventarioFlorestalGestorForm(base, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        inventario = form.save(commit=False)
        inventario.empresa = self.empresa
        inventario.save()
        self.assertEqual(inventario.volume_ha, 120)
        self.assertEqual(inventario.numero_arvores_ha, 200)
        self.assertEqual(inventario.vmi, Decimal("0.6"))
        self.assertEqual(inventario.volume_st(), Decimal("9000.00"))

        repetido = InventarioFlorestalGestorForm(base, empresa=self.empresa)
        self.assertFalse(repetido.is_valid())
        self.assertIn("lote", repetido.errors)

        talhao = Talhao.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            identificacao="T1",
            area_ha="50",
        )
        dados_talhao = {
            "inventario": inventario.pk,
            "talhao": talhao.pk,
            "area_ha": "50",
            "volume_total": "6000",
            "numero_arvores": "10000",
        }
        valido = InventarioTalhaoGestorForm(dados_talhao, empresa=self.empresa)
        self.assertTrue(valido.is_valid(), valido.errors)
        registro = valido.save(commit=False)
        registro.empresa = self.empresa
        registro.save()
        self.assertEqual(registro.volume_ha, 120)

        duplicado = InventarioTalhaoGestorForm(dados_talhao, empresa=self.empresa)
        self.assertFalse(duplicado.is_valid())
        self.assertIn("talhao", duplicado.errors)

    def test_gestor_com_upcs_vinculadas_so_ve_essas_upcs(self):
        gestor = get_user_model().objects.get(username="gestor")
        fazenda = self.fazenda_propria
        dados = {
            "fazenda": fazenda,
            "utm_leste": "1",
            "utm_norte": "1",
            "numero_fornos": 1,
            "volume_forno_mdc": "1",
            "ciclo_producao_dias": 1,
        }
        a = UPC.objects.create(empresa=self.empresa, nome="UPC A", **dados)
        b = UPC.objects.create(empresa=self.empresa, nome="UPC B", **dados)
        gestor.upcs.add(a)
        self.assertEqual(list(gestor.upcs_permitidas()), [a])
        self.client.force_login(gestor)
        resposta = self.client.get(reverse("lista_registros", args=["upcs"]))
        self.assertContains(resposta, "UPC A")
        self.assertNotContains(resposta, "UPC B")
        inventario = {
            "empresa": self.empresa,
            "fazenda": fazenda,
            "data_inventario": "2026-01-01",
            "responsavel_tecnico": "Eng",
            "registro_conselho": "CREA",
            "numero_art": "A",
            "area_ha": "1",
            "numero_parcelas": 1,
            "volume_total": "1",
            "numero_arvores": "1",
        }
        InventarioFlorestal.objects.create(lote="DA-A", upc=a, **inventario)
        InventarioFlorestal.objects.create(lote="DA-B", upc=b, **inventario)
        resposta = self.client.get(reverse("lista_registros", args=["inventarios"]))
        self.assertContains(resposta, "DA-A")
        self.assertNotContains(resposta, "DA-B")
        self.assertContains(self.client.get(reverse("inicio")), "UPC A")
        novo = self.client.get(reverse("novo_registro", args=["upcs"]))
        self.assertContains(novo, "/gestao/fazendas/novo/?proximo=")

    def test_colheita_valida_periodo_e_fazenda_do_talhao(self):
        inventario = InventarioFlorestal.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            lote="L9",
            data_inventario="2026-01-01",
            responsavel_tecnico="Eng",
            registro_conselho="CREA",
            numero_art="A9",
            area_ha="10",
            numero_parcelas=5,
            volume_total="100",
            numero_arvores="200",
        )
        talhao = Talhao.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            identificacao="T9",
            area_ha="5",
        )
        dados = {
            "inventario": inventario.pk,
            "talhao": talhao.pk,
            "area_ha": "5",
            "volume_total": "50",
            "data_inicio": "2026-03-10",
            "data_fim": "2026-03-01",
        }
        invalido = ColheitaGestorForm(dados, empresa=self.empresa)
        self.assertFalse(invalido.is_valid())
        self.assertIn("data_fim", invalido.errors)
        valido = ColheitaGestorForm(
            {**dados, "data_fim": "2026-03-20"}, empresa=self.empresa
        )
        self.assertFalse(valido.is_valid())
        valido = ColheitaGestorForm(
            {
                **dados,
                "data_fim": "2026-03-20",
                "sistema": "MECANIZADA",
                "equipamentos": ["HARVESTER", "SKIDDER"],
            },
            empresa=self.empresa,
        )
        self.assertTrue(valido.is_valid(), valido.errors)
        colheita = valido.save(commit=False)
        colheita.empresa = self.empresa
        colheita.save()
        inventario.refresh_from_db()
        self.assertEqual(colheita.volume_total, inventario.volume_total)
        errado = ColheitaGestorForm(
            {
                **dados,
                "data_fim": "2026-03-20",
                "sistema": "MANUAL",
                "equipamentos": ["HARVESTER"],
            },
            empresa=self.empresa,
        )
        self.assertFalse(errado.is_valid())
        self.assertIn("equipamentos", errado.errors)
        repetido = ColheitaGestorForm(
            {
                **dados,
                "data_fim": "2026-03-20",
                "sistema": "MANUAL",
                "equipamentos": ["MOTOSSERRA"],
            },
            empresa=self.empresa,
        )
        self.assertFalse(repetido.is_valid())
        self.assertIn("inventario", repetido.errors)

    def test_transporte_lenha_calcula_volume_e_custo(self):
        autorizacao = AutorizacaoAmbiental.objects.create(
            empresa=self.empresa,
            numero="A-2",
            modalidade="NOTA_FISCAL",
            produto="LENHA",
            unidade_volume="MST",
            volume_declarado=Decimal(1000),
            data_emissao="2026-01-01",
            status="ATIVA",
        )
        talhao = Talhao.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            identificacao="T1",
            area_ha="5",
        )
        base = {
            "autorizacao": autorizacao.pk,
            "talhao": talhao.pk,
            "data_transporte": "2026-02-01",
            "volume_mst": "30",
            "destino": "UPC",
            "tipo_transporte": "TERCEIRIZADO",
        }
        invalido = TransporteLenhaGestorForm(base, empresa=self.empresa)
        self.assertFalse(invalido.is_valid())
        for campo in ("upc", "fornecedor", "valor_mst"):
            self.assertIn(campo, invalido.errors)

        upc = UPC.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            nome="U2",
            utm_leste="1",
            utm_norte="1",
            numero_fornos=1,
            volume_forno_mdc="1",
            ciclo_producao_dias=8,
        )
        form = TransporteLenhaGestorForm(
            {**base, "upc": upc.pk, "tipo_transporte": "PROPRIO", "valor_m3": "30"},
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        transporte = form.save(commit=False)
        transporte.empresa = self.empresa
        transporte.save()
        self.assertEqual(transporte.volume_m3, Decimal("20.000"))
        self.assertEqual(transporte.valor_mst, Decimal("20.0000"))
        self.assertEqual(transporte.valor_total, Decimal("600.00"))

    def test_expedicao_baixa_saldo_em_duas_etapas(self):
        autorizacao = AutorizacaoAmbiental.objects.create(
            empresa=self.empresa,
            numero="A-1",
            modalidade="NOTA_FISCAL",
            produto="CARVAO_EXOTICA",
            unidade_volume="MDC",
            volume_declarado=Decimal(100),
            data_emissao="2026-01-01",
            status="ATIVA",
        )
        base = {
            "autorizacao": autorizacao.pk,
            "numero_documento": "NF-1",
            "data_expedicao": "2026-02-01",
            "cliente": "Siderúrgica",
        }
        excedente = ExpedicaoGestorForm(
            {**base, "volume_expedido": "101"}, empresa=self.empresa
        )
        self.assertFalse(excedente.is_valid())
        self.assertIn("volume_expedido", excedente.errors)

        form = ExpedicaoGestorForm(
            {**base, "volume_expedido": "40"}, empresa=self.empresa
        )
        self.assertTrue(form.is_valid(), form.errors)
        expedicao = form.save(commit=False)
        expedicao.empresa = self.empresa
        expedicao.save()
        self.assertEqual(expedicao.status, "EXPEDIDA")
        movimento = autorizacao.movimentos.get()
        self.assertEqual(movimento.tipo_movimento, "EXPEDICAO_CARVAO")
        self.assertEqual(movimento.volume_original, Decimal("40"))
        self.assertEqual(movimento.unidade_original, "MDC")
        self.assertEqual(movimento.volume_movimentado, Decimal("40"))
        self.assertEqual(autorizacao.saldo(), Decimal(60))

        parcial = ExpedicaoGestorForm(
            {**base, "volume_expedido": "40", "data_descarga": "2026-02-02"},
            instance=expedicao,
            empresa=self.empresa,
        )
        self.assertFalse(parcial.is_valid())
        self.assertIn("volume_aferido", parcial.errors)

        descarga = ExpedicaoGestorForm(
            {
                **base,
                "volume_expedido": "40",
                "data_descarga": "2026-02-02",
                "volume_aferido": "38.5",
            },
            instance=expedicao,
            empresa=self.empresa,
        )
        self.assertTrue(descarga.is_valid(), descarga.errors)
        descarga.save()
        expedicao.refresh_from_db()
        self.assertEqual(expedicao.status, "DESCARREGADA")
        self.assertEqual(expedicao.diferenca(), Decimal("-1.5"))
        movimento.refresh_from_db()
        self.assertEqual(movimento.volume_movimentado, Decimal("38.5"))
        self.assertEqual(autorizacao.movimentos.count(), 1)
        self.assertEqual(autorizacao.saldo(), Decimal("61.5"))

    def test_autorizacao_aplica_regras_de_modalidade_e_inventario_unico(self):
        inventario = InventarioFlorestal.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            lote="L1",
            data_inventario="2026-01-01",
            responsavel_tecnico="Eng",
            registro_conselho="CREA",
            numero_art="A1",
            area_ha="10",
            numero_parcelas=5,
            volume_total="100",
            numero_arvores="200",
        )
        base = {
            "numero": "2100.01.0004432/2026-31",
            "tipo_documento": "DCF",
            "origem_floresta": "EXOTICA",
            "modalidade": "PRODUCAO",
            "status": "PROTOCOLADA",
            "data_emissao": "2026-02-04",
            "produto": "CARVAO_EXOTICA",
            "unidade_volume": "MDC",
            "volume_declarado": "5093.05",
        }
        incompleta = AutorizacaoAmbientalGestorForm(base, empresa=self.empresa)
        self.assertFalse(incompleta.is_valid())
        for campo in ("fazenda", "base_volume", "upc"):
            self.assertIn(campo, incompleta.errors)

        upc = UPC.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            nome="U1",
            utm_leste="1",
            utm_norte="1",
            numero_fornos=1,
            volume_forno_mdc="1",
            ciclo_producao_dias=8,
        )
        completa = {
            **base,
            "fazenda": self.fazenda_propria.pk,
            "base_volume": "INVENTARIO",
            "inventario": inventario.pk,
            "upc": upc.pk,
        }
        form = AutorizacaoAmbientalGestorForm(completa, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        autorizacao = form.save(commit=False)
        autorizacao.empresa = self.empresa
        autorizacao.save()

        repetida = AutorizacaoAmbientalGestorForm(
            {**completa, "numero": "outro"}, empresa=self.empresa
        )
        self.assertFalse(repetida.is_valid())
        self.assertIn("inventario", repetida.errors)

        nota = AutorizacaoAmbientalGestorForm(
            {**base, "numero": "NF1", "modalidade": "NOTA_FISCAL"},
            empresa=self.empresa,
        )
        self.assertTrue(nota.is_valid(), nota.errors)

        mst = AutorizacaoAmbiental(unidade_volume="MST", volume_declarado=Decimal(150))
        self.assertEqual(mst.volume_em_m3(), Decimal("100.000"))

    def test_gestor_nao_ve_novos_cadastros_de_outra_empresa(self):
        Fornecedor.objects.create(
            empresa=self.outra_empresa, nome_razao_social="Alheio", cpf_cnpj="1"
        )
        Talhao.objects.create(
            empresa=self.outra_empresa,
            fazenda=self.fazenda_alheia,
            identificacao="TX",
            area_ha="1",
        )
        self.client.force_login(self.gestor)
        for recurso, texto in (("fornecedores", "Alheio"), ("talhoes", "TX")):
            with self.subTest(recurso=recurso):
                resposta = self.client.get(reverse("lista_registros", args=[recurso]))
                self.assertEqual(resposta.status_code, 200)
                self.assertNotContains(resposta, texto)

    def test_api_de_municipios_retorna_codigo_ibge_do_estado(self):
        self.client.force_login(self.gestor)
        Municipio.objects.create(
            codigo="3199999",
            nome="Município desativado",
            estado=self.estado,
            ativo=False,
        )

        resposta = self.client.get(
            reverse("municipios_por_estado"),
            {"estado": self.estado.pk},
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta.json(),
            {
                "municipios": [
                    {"codigo": self.municipio.codigo, "nome": self.municipio.nome}
                ]
            },
        )
        self.assertNotIn(
            "3199999",
            [municipio["codigo"] for municipio in resposta.json()["municipios"]],
        )

    def test_api_de_municipios_rejeita_estado_invalido(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(
            reverse("municipios_por_estado"),
            {"estado": "invalido"},
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("erro", resposta.json())

    def test_municipios_ibge_nao_podem_ser_editados_pelo_cadastro(self):
        self.client.force_login(self.administrador)

        resposta = self.client.get(reverse("novo_registro", args=["municipios-ibge"]))

        self.assertEqual(resposta.status_code, 403)


class PrimeiroCadastroTests(TestCase):
    def setUp(self):
        self.administrador = get_user_model().objects.create_superuser(
            username="admin-inicial",
            email="admin-inicial@example.com",
            password=ADMIN_CREDENTIAL,
            nome_completo="Administrador Inicial",
            primeiro_acesso=False,
        )
        self.client.force_login(self.administrador)

    def test_painel_sem_empresa_aponta_para_o_primeiro_cadastro(self):
        resposta = self.client.get(reverse("inicio"))

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context["primeira_empresa"])
        self.assertContains(resposta, "Comece cadastrando sua empresa")
        self.assertContains(
            resposta,
            reverse("novo_registro", args=["empresas"]),
        )
        self.assertNotContains(
            resposta,
            reverse("novo_registro", args=["usuarios"]),
        )

    def test_formulario_da_primeira_empresa_esta_disponivel(self):
        resposta = self.client.get(
            reverse("novo_registro", args=["empresas"]),
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'name="cnpj"')
        self.assertContains(resposta, 'name="razao_social"')


class SincronizacaoMunicipiosTests(TestCase):
    def test_sincroniza_municipios_da_api_ibge_de_forma_idempotente(self):
        payload = [
            {
                "id": 3143302,
                "nome": "Montes Claros",
                "microrregiao": {
                    "mesorregiao": {
                        "UF": {
                            "id": 31,
                            "sigla": "MG",
                            "nome": "Minas Gerais",
                        }
                    }
                },
            },
            {
                "id": 3106200,
                "nome": "Belo Horizonte",
                "microrregiao": {
                    "mesorregiao": {
                        "UF": {
                            "id": 31,
                            "sigla": "MG",
                            "nome": "Minas Gerais",
                        }
                    }
                },
            },
            {
                "id": 5101837,
                "nome": "Boa Esperança do Norte",
                "microrregiao": None,
                "regiao-imediata": {
                    "regiao-intermediaria": {
                        "UF": {
                            "id": 51,
                            "sigla": "MT",
                            "nome": "Mato Grosso",
                        }
                    }
                },
            },
        ]
        estado_antigo = Estado.objects.create(
            codigo=35,
            uf="SP",
            nome="Estado antigo",
        )
        Municipio.objects.create(
            codigo="9999999",
            nome="Município antigo",
            estado=estado_antigo,
        )
        with (
            patch(
                "sistema.management.commands.sincronizar_municipios_ibge.MINIMO_MUNICIPIOS",
                3,
            ),
            patch(
                "sistema.management.commands.sincronizar_municipios_ibge.urlopen",
                side_effect=[
                    BytesIO(compress_gzip(json.dumps(payload).encode())),
                    BytesIO(compress_gzip(json.dumps(payload).encode())),
                ],
            ),
        ):
            call_command("sincronizar_municipios_ibge")
            call_command("sincronizar_municipios_ibge")

        self.assertEqual(Municipio.objects.count(), 4)
        municipio = Municipio.objects.get(codigo="3143302")
        self.assertEqual(municipio.nome, "Montes Claros")
        self.assertEqual(municipio.estado.uf, "MG")
        self.assertEqual(Municipio.objects.filter(ativo=True).count(), 3)
        self.assertFalse(Municipio.objects.get(codigo="9999999").ativo)
        municipio_novo = Municipio.objects.get(codigo="5101837")
        self.assertEqual(municipio_novo.estado.uf, "MT")

    def test_sincronizacao_rejeita_resposta_incompleta(self):
        resposta = BytesIO(b"[]")
        with (
            patch(
                "sistema.management.commands.sincronizar_municipios_ibge.MINIMO_MUNICIPIOS",
                2,
            ),
            patch(
                "sistema.management.commands.sincronizar_municipios_ibge.urlopen",
                return_value=resposta,
            ),
            self.assertRaises(CommandError),
        ):
            call_command("sincronizar_municipios_ibge")


class SenhaLivreTests(TestCase):
    def test_troca_de_senha_aceita_senha_curta_e_numerica(self):
        usuario = get_user_model().objects.create_user(
            username="u1", password="antiga", nome_completo="U Um"
        )
        self.client.force_login(usuario)

        resposta = self.client.post(
            reverse("password_change"),
            {"old_password": "antiga", "new_password1": "1", "new_password2": "1"},
        )

        self.assertEqual(resposta.status_code, 302)
        usuario.refresh_from_db()
        self.assertTrue(usuario.check_password("1"))
