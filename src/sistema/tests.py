from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from sistema.forms import (
    CidadeForm,
    CodigoIBGEForm,
    EmpresaForm,
    EstadoForm,
    FazendaForm,
    FazendaGestorForm,
    ParametrosForm,
    UsuarioForm,
)
from sistema.models import Cidade, CodigoIBGE, Empresa, Estado, Fazenda

ADMIN_CREDENTIAL = "Admin-seguro#7291"
GESTOR_CREDENTIAL = "Gestor-seguro#7291"
INITIAL_CREDENTIAL = "Inicial-seguro#7291"
NEW_CREDENTIAL = "Nova-senha-segura#9382"


class FluxoAdministrativoTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.estado = Estado.objects.create(codigo=31, uf="MG")
        cls.cidade = Cidade.objects.create(
            codigo=1,
            estado=cls.estado,
            cidade="Montes Claros",
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
        cls.fazenda_propria = Fazenda.objects.create(
            empresa=cls.empresa,
            tipo_pessoa="pj",
            cpf_cnpj="12345678000199",
            nome="Fazenda da unidade",
            relacao="fornecedor",
            endereco="Rua das Árvores",
            bairro="Centro",
            estado=cls.estado,
            cidade=cls.cidade,
            codigo_ibge="3143302",
        )
        cls.fazenda_alheia = Fazenda.objects.create(
            empresa=cls.outra_empresa,
            tipo_pessoa="pf",
            cpf_cnpj="12345678901",
            nome="Fazenda de outra empresa",
            relacao="locatario",
            endereco="Rua do Campo",
            bairro="Rural",
            estado=cls.estado,
            cidade=cls.cidade,
            codigo_ibge="3143302",
        )

    @classmethod
    def criar_empresa(cls, nome: str, cnpj: str) -> Empresa:
        return Empresa.objects.create(
            cnpj=cnpj,
            razao_social=nome,
            endereco="Rua A",
            bairro="Centro",
            estado=cls.estado,
            cidade=cls.cidade,
            codigo_ibge="3143302",
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
        self.assertEqual(resposta.context["resumo"]["fornecedores"], 1)
        self.assertEqual(resposta.context["resumo"]["locatarios"], 0)

    def test_menu_do_administrador_da_acesso_a_todos_os_cadastros(self):
        self.client.force_login(self.administrador)

        resposta = self.client.get(reverse("inicio"))

        self.assertEqual(resposta.status_code, 200)
        for recurso in (
            "empresas",
            "usuarios",
            "parametros",
            "fazendas",
            "estados",
            "cidades",
            "codigos-ibge",
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
            "cidades",
            "codigos-ibge",
        ):
            with self.subTest(recurso=recurso):
                self.assertNotContains(
                    resposta,
                    reverse("lista_registros", args=[recurso]),
                )

    def test_lista_de_cidades_tem_busca_e_paginacao(self):
        Cidade.objects.bulk_create(
            [
                Cidade(
                    codigo=1000 + indice, estado=self.estado, cidade=f"Cidade {indice}"
                )
                for indice in range(25)
            ]
        )
        self.client.force_login(self.administrador)

        resposta_lista = self.client.get(reverse("lista_registros", args=["cidades"]))
        resposta_busca = self.client.get(
            reverse("lista_registros", args=["cidades"]),
            {"q": "Montes"},
        )

        self.assertEqual(resposta_lista.context["pagina"].paginator.count, 26)
        self.assertEqual(len(resposta_lista.context["linhas"]), 25)
        self.assertTrue(resposta_lista.context["pagina"].has_next())
        self.assertEqual(resposta_busca.context["pagina"].paginator.count, 1)
        self.assertContains(resposta_lista, 'name="q"')

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
        self.assertContains(resposta, 'name="codigo_ibge"')
        self.assertContains(resposta, 'name="email"')

    def test_secoes_incluem_todos_os_campos_dos_formularios(self):
        for formulario_class in (
            EmpresaForm,
            UsuarioForm,
            FazendaForm,
            FazendaGestorForm,
            ParametrosForm,
            EstadoForm,
            CidadeForm,
            CodigoIBGEForm,
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
        self.assertContains(resposta, "Identificação da fazenda")
        self.assertContains(resposta, 'name="cpf_cnpj"')
        self.assertContains(resposta, 'name="relacao"')

    def test_api_de_cidades_retorna_apenas_cidades_do_estado(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(
            reverse("cidades_por_estado"),
            {"estado": self.estado.pk},
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta.json(),
            {"cidades": [{"codigo": self.cidade.pk, "cidade": self.cidade.cidade}]},
        )

    def test_api_de_cidades_rejeita_estado_invalido(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(
            reverse("cidades_por_estado"),
            {"estado": "invalido"},
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("erro", resposta.json())


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


class ImportacaoLocalidadesTests(TestCase):
    def test_importa_dados_do_docx_de_forma_idempotente(self):
        call_command("importar_localidades_docx")
        call_command("importar_localidades_docx")

        self.assertEqual(Estado.objects.count(), 27)
        self.assertEqual(Cidade.objects.count(), 5529)
        self.assertEqual(CodigoIBGE.objects.count(), 5564)
        self.assertTrue(Cidade.objects.filter(cidade="MONTES CLAROS").exists())


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
