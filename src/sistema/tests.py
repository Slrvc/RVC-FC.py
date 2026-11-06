import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from gzip import compress as compress_gzip
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sistema.forms import (
    AutorizacaoAmbientalGestorForm,
    CicloFornoGestorForm,
    ColheitaGestorForm,
    EmpresaForm,
    ExpedicaoGestorForm,
    FazendaForm,
    FazendaGestorForm,
    FornecedorForm,
    FornecedorGestorForm,
    FornecedorTarifaGestorForm,
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
    sequencia_de_numeros,
)
from sistema.models import (
    UPC,
    AutorizacaoAmbiental,
    BoxLenha,
    CategoriaCusto,
    CentroCusto,
    CicloForno,
    Colheita,
    Empresa,
    Equipamento,
    Estado,
    Fazenda,
    Fornecedor,
    FornecedorTarifa,
    Forno,
    InventarioFlorestal,
    LancamentoCusto,
    LancamentoCustoRateio,
    Municipio,
    ParametroEmpresa,
    Parametros,
    PlanejamentoForno,
    Plantio,
    Proprietario,
    StatusCiclo,
    Talhao,
    TipoExecucao,
    TipoForno,
    Usuario,
)
from sistema.painel import grade_do_mes
from sistema.views import RECURSOS

ADMIN_CREDENTIAL = "Admin-seguro#7291"
GESTOR_CREDENTIAL = "Gestor-seguro#7291"
INITIAL_CREDENTIAL = "Inicial-seguro#7291"
NEW_CREDENTIAL = "Nova-senha-segura#9382"


def criar_usuario(empresa: Empresa | None = None, **dados: object):
    """Cria o usuário já ligado à matriz e com acesso à empresa informada."""
    matriz_id = empresa.matriz_da_conta_id if empresa else None
    usuario = get_user_model().objects.create_user(matriz_id=matriz_id, **dados)
    if empresa is not None:
        usuario.empresas.add(empresa)
    return usuario


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

        cls.gestor = criar_usuario(
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
            cpf_cnpj="12.345.678/0001-99",
            municipio=cls.municipio,
        )
        cls.proprietario_alheio = Proprietario.objects.create(
            empresa=cls.outra_empresa,
            nome_razao_social="Proprietário de outra empresa",
            cpf_cnpj="123.456.789-01",
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
        usuario = criar_usuario(
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
        usuario = criar_usuario(
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
                self.client.post(reverse("selecionar_empresa"), {"empresa": self.empresa.pk})
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

    def _criar_upc_com_forno(self, nome: str = "U1") -> tuple[UPC, Forno]:
        upc = UPC.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            nome=nome,
            utm_leste="1",
            utm_norte="1",
            ciclo_producao_dias=8,
        )
        tipo, _ = TipoForno.objects.get_or_create(
            empresa=self.empresa,
            nome="Circular 5,5 m",
            defaults={"diametro_m": "5.50", "capacidade_mdc": "18"},
        )
        forno = Forno.objects.create(
            empresa=self.empresa, upc=upc, tipo_forno=tipo, numero="F01"
        )
        return upc, forno

    def test_forno_aparece_com_o_nome_do_tipo_e_o_numero(self):
        upc, forno = self._criar_upc_com_forno()
        tipo = TipoForno.objects.create(
            empresa=self.empresa, nome="FCM", diametro_m="5.50", capacidade_mdc="18"
        )
        retangular = TipoForno.objects.create(
            empresa=self.empresa,
            nome="FRM",
            formato="RETANGULAR",
            comprimento_m="10",
            largura_m="4",
            capacidade_mdc="110",
        )
        fcm = Forno.objects.create(
            empresa=self.empresa, upc=upc, tipo_forno=tipo, numero="01"
        )
        self.assertEqual(fcm.identificacao, "FCM 01")
        self.assertEqual(str(fcm), "U1 - FCM 01")
        self.assertEqual(fcm.formato, "Circular")
        # Número com letras (cadastro antigo) continua como está.
        self.assertEqual(forno.identificacao, "F01")
        # O mesmo número pode existir em outro tipo na mesma UPC.
        self.client.force_login(self.gestor)
        url = reverse("novo_registro", args=["fornos"])
        dados = {"upc": upc.pk, "numero": "01", "situacao": "ATIVO", "quantidade": "1"}
        self.assertEqual(
            self.client.post(url, {**dados, "tipo_forno": retangular.pk}).status_code,
            302,
        )
        repetido = self.client.post(url, {**dados, "tipo_forno": tipo.pk})
        self.assertContains(repetido, "Já existem na UPC: 01.")
        lista = self.client.get(reverse("lista_registros", args=["fornos"]))
        self.assertContains(lista, "FCM 01")
        self.assertContains(lista, "Retangular")

    def test_ciclo_forno_calcula_fatores_status_e_alerta(self):
        _, forno = self._criar_upc_com_forno()
        ciclo = CicloForno.objects.create(
            empresa=self.empresa,
            forno=forno,
            data_inicio_enchimento=datetime.fromisoformat("2026-01-01T08:00Z"),
            volume_lenha_enchimento=Decimal("40"),
        )
        self.assertEqual(ciclo.numero_ciclo, 1)
        # O enchimento já é o início da carbonização.
        self.assertEqual(ciclo.status, StatusCiclo.CARBONIZACAO)
        self.assertEqual(ciclo.data_acendimento, ciclo.data_inicio_enchimento)
        self.assertEqual(ciclo.fator_conversao, Decimal("1.5"))
        self.assertEqual(ciclo.volume_lenha_m3, Decimal("26.667"))
        self.assertEqual(ciclo.alerta_fator, "")
        self.assertEqual(
            ciclo.prevista_fim_carbonizacao,
            datetime.fromisoformat("2026-01-07T08:00Z"),
        )
        self.assertIn("carbonização passou do prazo", ciclo.alerta_prazo)

        ciclo.data_fim_carbonizacao = datetime.fromisoformat("2026-01-05T20:00Z")
        ciclo.data_descarga = datetime.fromisoformat("2026-01-09T08:00Z")
        ciclo.volume_mdc = Decimal("20")
        ciclo.save()
        ciclo.refresh_from_db()
        self.assertEqual(ciclo.status, StatusCiclo.DESCARREGADO)
        self.assertEqual(ciclo.dias_carbonizacao, Decimal("4.50"))
        self.assertEqual(ciclo.dias_resfriamento, Decimal("3.50"))
        self.assertEqual(ciclo.dias_ciclo, Decimal("8.00"))
        self.assertEqual(ciclo.fator_mst_por_mdc, Decimal("2.0000"))
        self.assertEqual(ciclo.fator_m3_por_mdc, Decimal("1.3333"))
        self.assertEqual(ciclo.alerta_fator, "")
        self.assertEqual(ciclo.alerta_prazo, "")
        self.assertIsNone(ciclo.prevista_da_etapa)

        ciclo.data_descarga = datetime.fromisoformat("2026-01-12T08:00Z")
        ciclo.save()
        self.assertIn("resfriamento passou do prazo", ciclo.alerta_prazo)

        ciclo.volume_mdc = Decimal("10")
        ciclo.save()
        self.assertEqual(ciclo.alerta_fator, "Consumo de lenha acima do ideal")

        ParametroEmpresa.objects.create(
            empresa=self.empresa,
            fator_mst_por_m3=Decimal("1.6"),
            tolerancia_fator_pct=Decimal("150"),
        )
        self.assertEqual(ciclo.alerta_fator, "")
        segundo = CicloForno.objects.create(
            empresa=self.empresa,
            forno=forno,
            data_inicio_enchimento=datetime.fromisoformat("2026-01-10T08:00Z"),
            volume_lenha_enchimento=Decimal("40"),
        )
        self.assertEqual(segundo.numero_ciclo, 2)
        self.assertEqual(segundo.fator_conversao, Decimal("1.6"))

    def test_ciclo_terceirizado_calcula_valor_do_empreiteiro(self):
        _, forno = self._criar_upc_com_forno()
        empreiteiro = Fornecedor.objects.create(
            empresa=self.empresa,
            nome_razao_social="Empreiteiro",
            cpf_cnpj="111.222.333-44",
            fornece_servico=True,
        )
        ciclo = CicloForno.objects.create(
            empresa=self.empresa,
            forno=forno,
            data_inicio_enchimento=datetime.fromisoformat("2026-01-01T08:00Z"),
            data_acendimento=datetime.fromisoformat("2026-01-01T18:00Z"),
            data_fim_carbonizacao=datetime.fromisoformat("2026-01-04T18:00Z"),
            data_descarga=datetime.fromisoformat("2026-01-08T08:00Z"),
            volume_lenha_enchimento=Decimal("40"),
            volume_mdc=Decimal("19.5"),
            tipo_execucao=TipoExecucao.TERCEIRIZADA,
            fornecedor=empreiteiro,
            valor_mdc=Decimal("12"),
        )
        self.assertEqual(ciclo.valor_producao, Decimal("234.00"))

    def test_painel_dos_fornos_mostra_estado_de_cada_dia(self):
        _, forno = self._criar_upc_com_forno()
        local = timezone.get_current_timezone()
        CicloForno.objects.create(
            empresa=self.empresa,
            forno=forno,
            data_inicio_enchimento=datetime(2026, 8, 1, 10, tzinfo=local),
            data_acendimento=datetime(2026, 8, 2, 9, tzinfo=local),
            data_fim_carbonizacao=datetime(2026, 8, 6, 10, tzinfo=local),
            data_descarga=datetime(2026, 8, 10, 10, tzinfo=local),
            volume_lenha_enchimento=Decimal("40"),
            volume_mdc=Decimal("19.1"),
        )
        self.client.force_login(self.gestor)
        resposta = self.client.get(reverse("painel_fornos"), {"mes": "2026-08"})
        self.assertEqual(resposta.status_code, 200)
        grade = resposta.context["grade"]
        estados = grade["linhas"][0]["estados"]
        self.assertEqual(estados[:11], list("LCCCCRRRRDV"))
        self.assertEqual(grade["linhas"][0]["ciclos"], 1)
        self.assertEqual(grade["total_mdc"], "19,10")
        self.assertEqual(grade["producao_dia"][9], "19,10")
        # Mês inválido cai no mês atual.
        self.assertEqual(
            self.client.get(reverse("painel_fornos"), {"mes": "x"}).status_code, 200
        )

    def test_planejamento_escalona_fornos_e_projeta_o_planejado(self):
        upc, forno = self._criar_upc_com_forno()
        for numero in ("F02", "F03"):
            Forno.objects.create(
                empresa=self.empresa, upc=upc, tipo_forno=forno.tipo_forno, numero=numero
            )
        self.client.force_login(self.gestor)
        resposta = self.client.post(
            reverse("novo_registro", args=["planejamentos-forno"]),
            {
                "forno": forno.pk,
                "data_primeiro_enchimento": "2026-08-06",
                "mdc_previsto": "20",
                "quantidade": "3",
                "fornos_por_dia": "2",
            },
        )
        self.assertEqual(resposta.status_code, 302)
        datas = dict(
            PlanejamentoForno.objects.values_list(
                "forno__numero", "data_primeiro_enchimento"
            )
        )
        self.assertEqual(
            datas,
            {
                "F01": date(2026, 8, 6),
                "F02": date(2026, 8, 6),
                "F03": date(2026, 8, 7),
            },
        )
        repetido = self.client.post(
            reverse("novo_registro", args=["planejamentos-forno"]),
            {"forno": forno.pk, "data_primeiro_enchimento": "2026-08-20"},
        )
        self.assertIn("forno", repetido.context["formulario"].errors)

        grade = self.client.get(
            reverse("painel_fornos"), {"mes": "2026-08"}
        ).context["grade"]
        linha = grade["linhas"][0]
        # 5 dias vazios, 6 carbonizando, 6 resfriando, descarga e nova carga
        # no dia seguinte (de trabalho).
        self.assertEqual(
            "".join(linha["planejados"][:25]), "VVVVVCCCCCCRRRRRRDCCCCCCR"
        )
        # Descargas em 18/08 e 31/08; o F03 (enchido em 07/08) só a de 19/08.
        self.assertEqual(linha["ciclos_pl"], 2)
        self.assertEqual(linha["mdc_pl"], "40,00")
        self.assertEqual(grade["total_ciclos_pl"], 5)
        self.assertEqual(grade["total_mdc_pl"], "100,00")
        so_pl = self.client.get(
            reverse("painel_fornos"), {"mes": "2026-08", "ver": "pl"}
        )
        self.assertNotContains(so_pl, ">RE<")

    def test_planejado_sem_planejamento_segue_o_ultimo_ciclo_real(self):
        _, forno = self._criar_upc_com_forno()
        local = timezone.get_current_timezone()
        CicloForno.objects.create(
            empresa=self.empresa,
            forno=forno,
            data_inicio_enchimento=datetime(2026, 7, 28, 8, tzinfo=local),
            volume_lenha_enchimento=Decimal("40"),
        )
        self.client.force_login(self.gestor)
        grade = self.client.get(
            reverse("painel_fornos"), {"mes": "2026-08"}
        ).context["grade"]
        # Enchido em 28/07: carboniza até 02/08 e resfria; a descarga prevista
        # (09/08) é domingo, então fica para segunda, 10/08.
        self.assertEqual(
            "".join(grade["linhas"][0]["planejados"][:10]), "CCRRRRRRRD"
        )

    def test_planejado_respeita_os_dias_de_trabalho_da_upc(self):
        upc, forno = self._criar_upc_com_forno()
        upc.regime_sabado = "ALTERNADO"
        upc.sabado_referencia = date(2026, 11, 14)
        upc.save()
        self.assertTrue(upc.dia_de_trabalho(date(2026, 11, 14)))
        self.assertFalse(upc.dia_de_trabalho(date(2026, 11, 7)))
        self.assertFalse(upc.dia_de_trabalho(date(2026, 11, 21)))
        self.assertTrue(upc.dia_de_trabalho(date(2026, 11, 28)))
        self.assertFalse(upc.dia_de_trabalho(date(2026, 11, 15)))  # domingo
        outro = Forno.objects.create(
            empresa=self.empresa, upc=upc, tipo_forno=forno.tipo_forno, numero="F02"
        )
        for alvo, inicio in ((forno, date(2026, 11, 2)), (outro, date(2026, 11, 3))):
            PlanejamentoForno.objects.create(
                empresa=self.empresa, forno=alvo, data_primeiro_enchimento=inicio
            )
        # Planejado visto antes do mês começar (independe da data de hoje).
        linhas = grade_do_mes(
            Forno.objects.filter(upc=upc),
            2026,
            11,
            Parametros.da_empresa(self.empresa),
            hoje=date(2026, 10, 31),
        )["linhas"]
        # Descarga no sábado trabalhado (14/11): domingo vazio, enche na segunda.
        self.assertEqual("".join(linhas[0]["planejados"][:16]), "VCCCCCCRRRRRRDVC")
        # Descarga prevista no domingo (15/11) fica para segunda (16/11) e o
        # forno é carregado de novo no dia seguinte, que é de trabalho.
        self.assertEqual(
            "".join(linhas[1]["planejados"][:18]), "VVCCCCCCRRRRRRRDCC"
        )

    def test_planejado_de_hoje_em_diante_parte_do_estado_real(self):
        upc, forno = self._criar_upc_com_forno()
        upc.regime_sabado = "ALTERNADO"
        upc.sabado_referencia = date(2026, 11, 14)
        upc.save()
        local = timezone.get_current_timezone()
        CicloForno.objects.create(
            empresa=self.empresa,
            forno=forno,
            data_inicio_enchimento=datetime(2026, 10, 28, 9, tzinfo=local),
            data_fim_carbonizacao=datetime(2026, 11, 2, 9, tzinfo=local),
            data_descarga=datetime(2026, 11, 6, 9, tzinfo=local),
            volume_lenha_enchimento=Decimal("40"),
            volume_mdc=Decimal("18"),
        )
        grade = grade_do_mes(
            Forno.objects.filter(pk=forno.pk),
            2026,
            11,
            Parametros.da_empresa(self.empresa),
            hoje=date(2026, 11, 6),
        )
        planejados = "".join(grade["linhas"][0]["planejados"])
        # Descarregado hoje (sexta 06/11): vazio no sábado de folga e no
        # domingo, carregado na segunda 09/11.
        self.assertEqual(planejados[5:9], "DVVC")
        # Até ontem a linha mostra o real (carbonizou até 01/11, resfriou até
        # 05/11) e o ciclo seguinte tem os 6 dias de carbonização do tipo.
        self.assertEqual(planejados[:5], "CRRRR")
        self.assertEqual(planejados[8:15], "CCCCCCR")

    def test_ritmo_compara_planejado_e_real(self):
        upc, forno = self._criar_upc_com_forno()
        local = timezone.get_current_timezone()
        CicloForno.objects.create(
            empresa=self.empresa,
            forno=forno,
            data_inicio_enchimento=datetime(2026, 7, 25, 8, tzinfo=local),
            data_fim_carbonizacao=datetime(2026, 7, 31, 8, tzinfo=local),
            data_descarga=datetime(2026, 8, 6, 8, tzinfo=local),
            volume_lenha_enchimento=Decimal("40"),
            volume_mdc=Decimal("15"),
        )
        parametros = Parametros.da_empresa(self.empresa)
        fornos = Forno.objects.filter(upc=upc)
        ritmo = grade_do_mes(fornos, 2026, 8, parametros, hoje=date(2026, 8, 10))[
            "ritmo"
        ]
        self.assertEqual(ritmo["decorridos"], 10)
        self.assertEqual(ritmo["restantes"], 21)
        self.assertEqual(ritmo["real"], "15,00")
        self.assertEqual(ritmo["ritmo_real"], "1,50")
        self.assertIsNotNone(ritmo["ritmo_necessario"])
        # Mês encerrado: o fechamento é o realizado.
        fechado = grade_do_mes(fornos, 2026, 8, parametros, hoje=date(2026, 9, 5))[
            "ritmo"
        ]
        self.assertEqual(fechado["restantes"], 0)
        self.assertEqual(fechado["previsao"], "15,00")
        self.assertIsNone(fechado["ritmo_necessario"])

    def test_desempenho_do_ciclo_compara_tempos_e_fatores(self):
        _, forno = self._criar_upc_com_forno()
        local = timezone.get_current_timezone()
        CicloForno.objects.create(
            empresa=self.empresa,
            forno=forno,
            data_inicio_enchimento=datetime(2026, 8, 1, 8, tzinfo=local),
            data_fim_carbonizacao=datetime(2026, 8, 7, 8, tzinfo=local),
            data_descarga=datetime(2026, 8, 17, 8, tzinfo=local),
            volume_lenha_enchimento=Decimal("40"),
            volume_mdc=Decimal("16"),
        )
        CicloForno.objects.create(
            empresa=self.empresa,
            forno=forno,
            data_inicio_enchimento=datetime(2026, 8, 24, 8, tzinfo=local),
            volume_lenha_enchimento=Decimal("40"),
        )
        self.client.force_login(self.gestor)
        desempenho = self.client.get(
            reverse("painel_fornos"), {"mes": "2026-08"}
        ).context["desempenho"]
        self.assertEqual(desempenho["ciclos"], 1)
        resfriamento = desempenho["etapas"][1]
        self.assertEqual(resfriamento["real"], "10,0")
        self.assertTrue(resfriamento["acima"])
        # Ciclo real 6 + 10 + 7 = 23 dias contra 6 + 6 + 2 = 14: houve perda.
        self.assertEqual(desempenho["etapas"][2]["real"], "7,0")
        self.assertEqual(desempenho["atraso_resf_pct"], 100)
        # 40 MST / 16 MDC = 2,5 contra a referência de 2,0.
        self.assertEqual(desempenho["fatores"][0]["real"], "2,50")
        self.assertTrue(desempenho["fatores"][0]["acima"])
        self.assertIsNotNone(desempenho["perda_mdc"])

    def test_consolidado_da_colheita_mostra_saldo_e_disponivel(self):
        inventario = InventarioFlorestal.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            lote="L6",
            data_inventario="2026-01-01",
            responsavel_tecnico="Eng",
            registro_conselho="CREA",
            numero_art="A6",
            area_ha="10",
            usuario_inclusao=self.gestor,
            volume_total="1000",
            numero_arvores="200",
        )
        talhao = Talhao.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            identificacao="T6",
            area_ha=Decimal("5"),
            volume_m3=Decimal("500"),
        )
        for etapa, volume in (("CORTE_FELLER", "500"), ("TRACAMENTO", "300")):
            Colheita.objects.create(
                empresa=self.empresa,
                inventario=inventario,
                talhao=talhao,
                etapa=etapa,
                data_inicio=date(2026, 5, 10),
                volume_m3=Decimal(volume),
            )
        self.client.force_login(self.gestor)
        consolidado = self.client.get(reverse("consolidado_colheita")).context[
            "consolidado"
        ]
        linha = consolidado["linhas"][0]
        self.assertEqual(linha["ifpc"], "500,000")
        self.assertEqual(linha["disponivel"], "300,000")
        self.assertEqual(linha["inicio_corte"], date(2026, 5, 10))

    def test_visao_geral_mostra_ciclo_dos_fornos_e_graficos(self):
        _, forno = self._criar_upc_com_forno()
        agora = timezone.now()
        CicloForno.objects.create(
            empresa=self.empresa,
            forno=forno,
            data_inicio_enchimento=agora - timedelta(days=10),
            volume_lenha_enchimento=Decimal("40"),
        )
        self.client.force_login(self.gestor)
        resposta = self.client.get(reverse("inicio"))
        dashboard = resposta.context["dashboard"]
        self.assertEqual(dashboard["fornos"].carbonizando, 1)
        self.assertEqual(len(dashboard["fornos"].atrasados), 1)
        # O aviso de atraso fica no painel dos fornos, não na visão geral.
        self.assertNotContains(resposta, "passou do prazo")
        self.assertContains(resposta, reverse("painel_fornos"))
        self.assertEqual(len(dashboard["graficos"]), 3)

    def test_formulario_do_ciclo_valida_etapas_e_ciclo_em_andamento(self):
        _, forno = self._criar_upc_com_forno()
        self.client.force_login(self.gestor)
        url = reverse("novo_registro", args=["ciclos-forno"])
        base = {
            "forno": forno.pk,
            "data_inicio_enchimento": "2026-03-01T08:00",
            "volume_lenha_enchimento": "40",
            "fator_conversao": "1.5",
            "tipo_execucao": "PROPRIA",
        }

        tela = self.client.get(url)
        self.assertContains(tela, "Enchimento de forno")
        self.assertNotContains(tela, 'name="data_fim_carbonizacao"')

        terceirizado = self.client.post(url, {**base, "tipo_execucao": "TERCEIRIZADA"})
        self.assertContains(terceirizado, "Obrigatório na produção terceirizada.")

        sem_lenha = self.client.post(url, {**base, "volume_lenha_enchimento": ""})
        self.assertIn(
            "volume_lenha_enchimento", sem_lenha.context["formulario"].errors
        )
        acendimento_antes = self.client.post(
            url, {**base, "data_acendimento": "2026-03-01T07:00"}
        )
        self.assertContains(acendimento_antes, "Não pode ser antes do enchimento.")

        self.assertEqual(self.client.post(url, base).status_code, 302)
        ciclo = CicloForno.objects.get()
        self.assertEqual(ciclo.status, StatusCiclo.CARBONIZACAO)
        lista = self.client.get(reverse("lista_registros", args=["ciclos-forno"]))
        self.assertEqual(lista.context["local_no_menu"], "Produção · Lançamentos")
        filtro = lista.context["filtro"]
        self.assertEqual(filtro["todos"]["total"], 1)
        self.assertEqual(
            {opcao["valor"]: opcao["total"] for opcao in filtro["opcoes"]}[
                "CARBONIZACAO"
            ],
            1,
        )
        resfriando = self.client.get(
            reverse("lista_registros", args=["ciclos-forno"]),
            {"filtro": "RESFRIAMENTO"},
        )
        self.assertEqual(resfriando.context["pagina"].paginator.count, 0)
        # Status com a marca e o texto da legenda do painel dos fornos.
        self.assertContains(
            lista,
            '<span class="estado-celula estado-C" aria-hidden="true">C</span> '
            "Carbonizando",
            html=False,
        )
        # Forno cheio some da lista do enchimento.
        em_andamento = self.client.post(url, base)
        self.assertEqual(em_andamento.status_code, 200)
        self.assertIn("forno", em_andamento.context["formulario"].errors)

        cancelar = self.client.post(
            reverse("editar_registro", args=["ciclos-forno", ciclo.pk]),
            {**base, "cancelado": "on"},
        )
        self.assertEqual(cancelar.status_code, 302)
        ciclo.refresh_from_db()
        self.assertEqual(ciclo.status, StatusCiclo.CANCELADO)
        self.assertEqual(self.client.post(url, base).status_code, 302)
        self.assertEqual(
            CicloForno.objects.order_by("numero_ciclo").last().numero_ciclo, 2
        )

    def test_etapas_do_ciclo_mostram_so_fornos_da_etapa_anterior(self):
        upc, forno = self._criar_upc_com_forno()
        outro = Forno.objects.create(
            empresa=self.empresa, upc=upc, tipo_forno=forno.tipo_forno, numero="F02"
        )
        forno.tipo_forno.capacidade_lenha_mst = Decimal("40.13")
        forno.tipo_forno.save()
        self.client.force_login(self.gestor)
        novo = reverse("novo_registro", args=["ciclos-forno"])
        fim = reverse("etapa_do_ciclo", args=["fim-carbonizacao"])
        descarga = reverse("etapa_do_ciclo", args=["descarga"])

        # A lenha do tipo é só referência: aparece na ajuda, não é preenchida.
        tela = self.client.get(novo)
        self.assertContains(tela, "Referência: Circular 5,5 m: 40,13 MST")
        self.client.post(
            novo,
            {
                "forno": forno.pk,
                "data_inicio_enchimento": "2026-03-01T08:00",
                "data_acendimento": "2026-03-01T20:00",
                "volume_lenha_enchimento": "39.8",
                "fator_conversao": "1.5",
                "tipo_execucao": "PROPRIA",
            },
        )
        ciclo = CicloForno.objects.get(forno=forno)
        self.assertEqual(ciclo.volume_lenha_enchimento, Decimal("39.8"))
        # O prazo da carbonização conta do acendimento.
        self.assertEqual(
            timezone.localtime(ciclo.prevista_fim_carbonizacao).hour, 20
        )

        enchimento = self.client.get(novo).context["formulario"]
        self.assertEqual(list(enchimento.fields["forno"].queryset), [outro])
        etapa = self.client.get(fim).context["formulario"]
        self.assertEqual(list(etapa.fields["ciclo"].queryset), [ciclo])
        self.assertEqual(
            list(self.client.get(descarga).context["formulario"].fields["ciclo"].queryset),
            [],
        )

        antes = self.client.post(
            fim, {"ciclo": ciclo.pk, "data_fim_carbonizacao": "2026-02-28T08:00"}
        )
        self.assertContains(antes, "Não pode ser antes do acendimento")
        atrasado = self.client.post(
            fim,
            {"ciclo": ciclo.pk, "data_fim_carbonizacao": "2026-03-08T08:00"},
            follow=True,
        )
        self.assertContains(atrasado, "carbonização passou do prazo")
        ciclo.refresh_from_db()
        self.assertEqual(ciclo.status, StatusCiclo.RESFRIAMENTO)
        self.assertEqual(
            list(self.client.get(fim).context["formulario"].fields["ciclo"].queryset),
            [],
        )

        sem_carvao = self.client.post(
            descarga, {"ciclo": ciclo.pk, "data_descarga": "2026-03-12T08:00"}
        )
        self.assertIn("volume_mdc", sem_carvao.context["formulario"].errors)
        self.client.post(
            descarga,
            {
                "ciclo": ciclo.pk,
                "data_descarga": "2026-03-12T08:00",
                "volume_mdc": "20",
                "responsavel_descarga": "Rafael",
            },
        )
        ciclo.refresh_from_db()
        self.assertEqual(ciclo.status, StatusCiclo.DESCARREGADO)
        self.assertEqual(ciclo.volume_mdc, Decimal("20"))
        self.assertEqual(ciclo.responsavel_descarga, "Rafael")
        # Descarregado, o forno volta a aparecer no enchimento.
        enchimento = self.client.get(novo).context["formulario"]
        self.assertEqual(set(enchimento.fields["forno"].queryset), {forno, outro})

    def test_fornos_em_lote_seguem_a_numeracao(self):
        self.assertEqual(sequencia_de_numeros("F08", 3), ["F08", "F09", "F10"])
        self.assertEqual(sequencia_de_numeros("F9", 2), ["F09", "F10"])
        with self.assertRaises(ValueError):
            sequencia_de_numeros("A", 2)

        upc, forno = self._criar_upc_com_forno()
        self.client.force_login(self.gestor)
        url = reverse("novo_registro", args=["fornos"])
        dados = {
            "upc": upc.pk,
            "tipo_forno": forno.tipo_forno_id,
            "numero": "F02",
            "quantidade": "3",
            "situacao": "ATIVO",
        }
        self.assertEqual(self.client.post(url, dados).status_code, 302)
        self.assertEqual(
            list(upc.fornos.values_list("numero", flat=True)),
            ["F01", "F02", "F03", "F04"],
        )
        self.assertEqual(upc.numero_fornos, 4)
        self.assertEqual(upc.volume_ciclo_mdc, Decimal("72"))

        repetido = self.client.post(url, {**dados, "numero": "F04", "quantidade": "2"})
        self.assertContains(repetido, "Já existem na UPC: F04.")
        self.assertEqual(upc.fornos.count(), 4)

        forno.situacao = "DESATIVADO"
        forno.save()
        self.assertEqual(upc.numero_fornos, 3)
        self.assertEqual(upc.volume_ciclo_mdc, Decimal("54"))

    def test_box_de_lenha_precisa_ser_da_upc_do_forno(self):
        _, forno = self._criar_upc_com_forno()
        outra_upc, _ = self._criar_upc_com_forno("U2")
        box_alheio = BoxLenha.objects.create(
            empresa=self.empresa, upc=outra_upc, numero="B01"
        )
        formulario = CicloFornoGestorForm(
            {
                "forno": forno.pk,
                "box_lenha": box_alheio.pk,
                "data_inicio_enchimento": "2026-03-01T08:00",
                "volume_lenha_enchimento": "40",
                "fator_conversao": "1.5",
                "tipo_execucao": "PROPRIA",
            },
            empresa=self.empresa,
        )
        self.assertFalse(formulario.is_valid())
        self.assertEqual(formulario.errors["box_lenha"], ["O box é de outra UPC."])

    def test_parametros_de_producao_sao_unicos_por_empresa(self):
        self.client.force_login(self.gestor)
        url = reverse("novo_registro", args=["parametros-producao"])
        dados = {
            "fator_mst_por_m3": "1.45",
            "fator_m3_por_mdc_ideal": "1.33",
            "fator_mst_por_mdc_ideal": "2",
            "controle_estoque_talhao": "COLHIDA",
        }
        self.assertEqual(self.client.post(url, dados).status_code, 302)
        self.assertEqual(
            ParametroEmpresa.da_empresa(self.empresa.pk).fator_mst_por_m3,
            Decimal("1.45"),
        )
        self.assertContains(self.client.post(url, dados), "já tem parâmetros")

    def test_tela_de_escolha_mostra_tipo_cidade_e_cnpj(self):
        self.outra_empresa.tipo = "FILIAL"
        self.outra_empresa.descricao_filial = "Filial 01 - Sete Lagoas"
        self.outra_empresa.save()
        self.client.force_login(self.administrador)

        resposta = self.client.get(reverse("selecionar_empresa"))

        self.assertContains(resposta, "Filial 01 - Sete Lagoas")
        self.assertContains(resposta, "Matriz")
        self.assertContains(resposta, "CNPJ 00000000000272")
        self.assertContains(resposta, "Montes Claros/MG")

    def test_formularios_herdam_empresa_ativa_sem_mostrar_seletor(self):
        self.client.force_login(self.administrador)
        self.client.post(reverse("selecionar_empresa"), {"empresa": self.empresa.pk})

        resposta = self.client.get(reverse("novo_registro", args=["upcs"]))

        self.assertNotIn("empresa", resposta.context["formulario"].fields)

        resposta = self.client.post(
            reverse("novo_registro", args=["proprietarios"]),
            {"nome_razao_social": "Proprietário cadastrado pelo admin", "cpf_cnpj": "99999999999"},
        )
        self.assertEqual(resposta.status_code, 302)
        proprietario = Proprietario.objects.get(
            nome_razao_social="Proprietário cadastrado pelo admin"
        )
        self.assertEqual(proprietario.empresa, self.empresa)

    def test_filial_exige_descricao(self):
        dados = {"tipo": "FILIAL", "descricao_filial": ""}
        form = EmpresaForm(dados)
        form.is_valid()
        self.assertIn("descricao_filial", form.errors)

    def test_administrador_escolhe_empresa_ativa_e_upc_nasce_nela(self):
        self.client.force_login(self.administrador)

        resposta = self.client.get(reverse("inicio"))
        self.assertRedirects(
            resposta,
            f"{reverse('selecionar_empresa')}?proximo={reverse('inicio')}",
            fetch_redirect_response=False,
        )

        self.client.post(reverse("selecionar_empresa"), {"empresa": self.empresa.pk})
        inicio = self.client.get(reverse("inicio"))
        self.assertEqual(inicio.status_code, 200)
        self.assertContains(inicio, "Trocar empresa")

        resposta = self.client.get(reverse("novo_registro", args=["upcs"]))
        self.assertNotIn("empresa", resposta.context["formulario"].fields)

        resposta = self.client.get(reverse("lista_registros", args=["fazendas"]))
        self.assertContains(resposta, "Fazenda da unidade")
        self.assertNotContains(resposta, "Fazenda de outra empresa")
        self.assertNotIn("Empresa", resposta.context["colunas"])

    def test_coluna_empresa_nao_aparece_na_lista_do_gestor(self):
        self.client.force_login(self.gestor)

        resposta = self.client.get(reverse("lista_registros", args=["fazendas"]))

        self.assertNotIn("Empresa", resposta.context["colunas"])
        self.assertNotContains(resposta, '<th scope="col">Empresa</th>')

    def test_admin_sem_empresa_ativa_e_redirecionado_ao_seletor(self):
        self.client.force_login(self.administrador)

        resposta = self.client.get(reverse("novo_registro", args=["fazendas"]))

        self.assertRedirects(
            resposta,
            f"{reverse('selecionar_empresa')}?proximo={reverse('novo_registro', args=['fazendas'])}",
            fetch_redirect_response=False,
        )

    def test_configuracoes_gerais_nao_pedem_empresa_ativa(self):
        self.client.force_login(self.administrador)

        for recurso in ("empresas", "usuarios", "estados", "municipios-ibge"):
            with self.subTest(recurso=recurso):
                resposta = self.client.get(reverse("lista_registros", args=[recurso]))
                self.assertEqual(resposta.status_code, 200)
        for recurso in ("upcs", "fazendas"):
            with self.subTest(recurso=recurso):
                resposta = self.client.get(reverse("lista_registros", args=[recurso]))
                self.assertEqual(resposta.status_code, 302)

    def test_selecao_de_upc_preserva_destino_do_menu(self):
        dados_upc = {
            "empresa": self.empresa,
            "fazenda": self.fazenda_propria,
            "utm_leste": "1",
            "utm_norte": "1",
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
                "tipo_usuario": "gestor",
                "nome_completo": "Novo Gestor",
                "email": "novo@example.com",
                "matriz": self.empresa.pk,
                "empresas": [self.empresa.pk],
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

    def test_administrador_da_matriz_nao_vira_superusuario(self):
        self.client.force_login(self.administrador)
        dados = {
            "username": "novo-adm",
            "tipo_usuario": "admin",
            "nome_completo": "Novo Adm",
            "email": "adm@example.com",
            "is_active": "on",
            "senha": GESTOR_CREDENTIAL,
        }

        sem_matriz = self.client.post(reverse("novo_registro", args=["usuarios"]), dados)
        self.assertContains(sem_matriz, "Selecione a matriz do usuário.")

        self.client.post(
            reverse("novo_registro", args=["usuarios"]),
            {**dados, "matriz": self.empresa.pk},
        )
        usuario = get_user_model().objects.get(username="novo-adm")
        self.assertFalse(usuario.is_superuser)
        self.assertFalse(usuario.is_staff)
        self.assertEqual(usuario.matriz, self.empresa)
        self.assertFalse(usuario.empresas.exists())

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

    def test_fazenda_cadastra_numero_de_matricula(self):
        formulario = FazendaGestorForm(
            {
                "proprietario": self.proprietario_proprio.pk,
                "nome": "Fazenda com matrícula",
                "area_total_ha": "15.2500",
                "estado": self.estado.pk,
                "municipio": self.municipio.pk,
                "numero_matricula": "12.345",
            },
            empresa=self.empresa,
        )

        self.assertTrue(formulario.is_valid(), formulario.errors)
        fazenda = formulario.save(commit=False)
        fazenda.empresa = self.empresa
        fazenda.save()

        self.assertEqual(
            Fazenda.objects.get(pk=fazenda.pk).numero_matricula, "12.345"
        )

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
        novo = Proprietario.objects.get(cpf_cnpj="999.999.999-99")
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
        fornecedor = Fornecedor.objects.get(cpf_cnpj="11.111.111/0001-00")
        self.assertEqual(fornecedor.empresa, self.empresa)
        self.assertEqual(fornecedor.tipos(), "Serviço")

    def test_plantio_nao_exige_cadastro_ou_dispensa_e_aceita_idade_informada(self):
        formulario = PlantioGestorForm(
            {
                "fazenda": self.fazenda_propria.pk,
                "origem": "EXOTICA",
                "rotacao": 1,
                "idade_anos": "9",
            },
            empresa=self.empresa,
        )
        self.assertNotIn("numero_cadastro", formulario.fields)
        self.assertNotIn("motivo_dispensa", formulario.fields)
        self.assertIn("idade_anos", formulario.fields)
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(formulario.cleaned_data["idade_anos"], 9)
        plantio = formulario.save(commit=False)
        plantio.empresa = self.empresa
        plantio.save()
        self.assertEqual(Plantio.objects.get(pk=plantio.pk).idade_anos, 9)

    def test_campos_de_area_e_idade_ficam_em_caracteristicas_e_fazenda_ocupa_largura(self):
        formulario = PlantioGestorForm(empresa=self.empresa)
        secao_caracteristicas = next(
            secao for secao in formulario.secoes if secao["titulo"] == "Características"
        )
        self.assertIn("area_ha", [campo.name for campo in secao_caracteristicas["campos"]])
        self.assertIn(
            "idade_anos", [campo.name for campo in secao_caracteristicas["campos"]]
        )

        self.client.force_login(self.gestor)
        resposta = self.client.get(reverse("novo_registro", args=["plantios"]))

        self.assertContains(resposta, 'class="field field-wide"')

        tela_talhoes = self.client.get(reverse("novo_registro", args=["talhoes"]))
        self.assertContains(
            tela_talhoes,
            f'data-plantios-url="{reverse("plantios_por_fazenda")}"',
        )
        self.assertContains(tela_talhoes, "/static/sistema/app.js?v=12")

        outra = PlantioGestorForm(
            {
                "fazenda": self.fazenda_alheia.pk,
                "origem": "EXOTICA",
                "rotacao": 1,
            },
            empresa=self.empresa,
        )
        self.assertFalse(outra.is_valid())
        self.assertIn("fazenda", outra.errors)

    def test_seletores_de_fazenda_exibem_numero_da_matricula(self):
        fazenda_com_matricula = Fazenda.objects.create(
            empresa=self.empresa,
            proprietario=self.proprietario_proprio,
            nome=self.fazenda_propria.nome,
            area_total_ha="3.0000",
            municipio=self.municipio,
            numero_matricula="12.345",
        )
        self.fazenda_propria.numero_matricula = "67.890"
        self.fazenda_propria.save(update_fields=["numero_matricula"])
        self.client.force_login(self.gestor)

        for recurso in ("plantios", "talhoes"):
            with self.subTest(recurso=recurso):
                resposta = self.client.get(reverse("novo_registro", args=[recurso]))

                self.assertEqual(resposta.status_code, 200)
                self.assertContains(resposta, "Fazenda da unidade (Matrícula 67.890)")
                self.assertContains(resposta, "Fazenda da unidade (Matrícula 12.345)")
                self.assertContains(
                    resposta, f'value="{self.fazenda_propria.pk}"'
                )
                self.assertContains(
                    resposta, f'value="{fazenda_com_matricula.pk}"'
                )

    def test_lista_de_plantios_exibe_idade_informada(self):
        Plantio.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            idade_anos=9,
        )
        self.client.force_login(self.gestor)

        resposta = self.client.get(reverse("lista_registros", args=["plantios"]))

        self.assertContains(resposta, "<td>9</td>")
        self.assertNotContains(resposta, "<bound method Plantio.idade_anos")
        self.assertNotContains(resposta, "Cadastro MG Florestas")

    def test_talhao_valida_geojson_plantio_da_fazenda_e_duplicidade(self):
        plantio = Plantio.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
        )
        plantio_outra_fazenda = Plantio.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_alheia,
        )
        base = {
            "fazenda": self.fazenda_propria.pk,
            "plantio": plantio.pk,
            "identificacao": "T01",
            "area_ha": "2.5",
            "volume_m3": "10",
        }
        formulario = TalhaoGestorForm(base, empresa=self.empresa)
        self.assertEqual(
            list(formulario.fields["plantio"].queryset), [plantio]
        )
        outro_plantio = TalhaoGestorForm(
            {**base, "plantio": plantio_outra_fazenda.pk},
            empresa=self.empresa,
        )
        self.assertFalse(outro_plantio.is_valid())
        self.assertIn("plantio", outro_plantio.errors)

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

    def test_api_de_plantios_retorna_apenas_os_da_fazenda(self):
        plantio_proprio = Plantio.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
        )
        Plantio.objects.create(
            empresa=self.outra_empresa,
            fazenda=self.fazenda_alheia,
        )
        self.client.force_login(self.gestor)

        resposta = self.client.get(
            reverse("plantios_por_fazenda"),
            {"fazenda": self.fazenda_propria.pk},
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta.json()["plantios"],
            [{"codigo": plantio_proprio.pk, "nome": str(plantio_proprio)}],
        )

        fazenda_alheia = self.client.get(
            reverse("plantios_por_fazenda"),
            {"fazenda": self.fazenda_alheia.pk},
        )
        self.assertEqual(fazenda_alheia.status_code, 404)

        invalida = self.client.get(
            reverse("plantios_por_fazenda"),
            {"fazenda": "invalida"},
        )
        self.assertEqual(invalida.status_code, 400)

    def test_upc_calcula_capacidade_e_exige_fazenda_da_empresa(self):
        dados = {
            "fazenda": self.fazenda_propria.pk,
            "nome": "UPC Mumbuca",
            "utm_leste": "574452.91",
            "utm_norte": "7897888.65",
            "utm_fuso": "23K",
            "ciclo_producao_dias": 8,
        }
        form = UPCGestorForm(dados, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        upc = form.save(commit=False)
        upc.empresa = self.empresa
        upc.save()
        self.assertEqual(upc.numero_fornos, 0)
        tipo = TipoForno.objects.create(
            empresa=self.empresa, nome="Circular", capacidade_mdc="18"
        )
        Forno.objects.bulk_create(
            Forno(empresa=self.empresa, upc=upc, tipo_forno=tipo, numero=f"F{n:02d}")
            for n in range(1, 67)
        )
        self.assertEqual(upc.numero_fornos, 66)
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
            "volume_total": "6000",
            "numero_arvores": "10000",
        }
        form = InventarioFlorestalGestorForm(base, empresa=self.empresa)
        self.assertTrue(form.fields["vmi"].disabled)
        self.assertNotIn("upc", form.fields)
        for campo in (
            "metodo_amostragem",
            "numero_parcelas",
            "area_parcela_m2",
            "equacao_volume",
            "fator_forma",
            "equacao_hipsometrica",
            "nivel_probabilidade",
            "t_student",
            "erro_padrao_media",
            "erro_amostragem_pct",
            "ic_inferior_m3",
            "ic_superior_m3",
        ):
            self.assertNotIn(campo, form.fields)
        campos_removidos = {
            "upc",
            "metodo_amostragem",
            "numero_parcelas",
            "area_parcela_m2",
            "equacao_volume",
            "fator_forma",
            "equacao_hipsometrica",
            "latitude",
            "longitude",
            "nivel_probabilidade",
            "t_student",
            "erro_padrao_media",
            "erro_amostragem_pct",
            "ic_inferior_m3",
            "ic_superior_m3",
        }
        self.assertNotIn("Amostragem", [secao["titulo"] for secao in form.secoes])
        self.assertNotIn("Estatística", [secao["titulo"] for secao in form.secoes])
        self.assertTrue(form.is_valid(), form.errors)
        inventario = form.save(commit=False)
        inventario.empresa = self.empresa
        inventario.usuario_inclusao = self.gestor
        inventario.save()
        self.assertFalse(any(hasattr(inventario, campo) for campo in campos_removidos))
        self.assertEqual(inventario.volume_ha, 120)
        self.assertEqual(inventario.numero_arvores_ha, 200)
        self.assertEqual(inventario.vmi, Decimal("0.6"))
        self.assertEqual(inventario.volume_st(), Decimal("9000.00"))
        formulario_edicao = InventarioFlorestalGestorForm(
            instance=inventario,
            empresa=self.empresa,
        )
        self.assertEqual(formulario_edicao["vmi"].value(), Decimal("0.6"))

        self.client.force_login(self.gestor)
        pagina = self.client.get(reverse("novo_registro", args=["inventarios"]))
        self.assertNotContains(pagina, 'name="upc"')
        self.assertNotContains(pagina, "Estatística")
        self.assertNotContains(pagina, "Amostragem")
        edicao = self.client.get(
            reverse("editar_registro", args=["inventarios", inventario.pk])
        )
        self.assertContains(edicao, 'name="vmi"')
        tabela = self.client.get(reverse("lista_registros", args=["inventarios"]))
        for cabecalho in (
            "Nível de probabilidade",
            "t de Student",
            "Erro-padrão da média",
            "Erro de amostragem",
            "IC inferior",
            "IC superior",
        ):
            self.assertNotContains(tabela, cabecalho)

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

        fazenda_talhoes_inventario = Fazenda.objects.create(
            empresa=self.empresa,
            proprietario=self.proprietario_proprio,
            nome="Fazenda auxiliar",
            area_total_ha="10",
            municipio=self.municipio,
        )
        talhao_calculado = Talhao.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            identificacao="T2",
            area_ha="5",
            volume_m3="250",
        )
        Talhao.objects.create(
            empresa=self.empresa,
            fazenda=fazenda_talhoes_inventario,
            identificacao="T1",
            area_ha="10",
            volume_m3="300",
        )
        formulario_com_inventario = InventarioTalhaoGestorForm(
            {"inventario": inventario.pk},
            empresa=self.empresa,
        )
        self.assertEqual(
            list(
                formulario_com_inventario.fields["talhao"].queryset.values_list(
                    "pk", flat=True
                )
            ),
            [talhao.pk, talhao_calculado.pk],
        )
        self.client.force_login(self.gestor)
        talhoes_por_inventario = self.client.get(
            reverse("talhoes_por_inventario"),
            {"inventario": inventario.pk},
        )
        self.assertEqual(talhoes_por_inventario.status_code, 200)
        dados_talhoes = {
            item["codigo"]: item
            for item in talhoes_por_inventario.json()["talhoes"]
        }
        self.assertEqual(set(dados_talhoes), {talhao.pk, talhao_calculado.pk})
        self.assertEqual(dados_talhoes[talhao_calculado.pk]["area_ha"], "5.0000")
        self.assertEqual(
            dados_talhoes[talhao_calculado.pk]["volume_total"], "250.000"
        )
        self.assertEqual(
            dados_talhoes[talhao_calculado.pk]["saldo_a_retirar_m3"], "250.000"
        )
        self.assertEqual(dados_talhoes[talhao_calculado.pk]["numero_arvores"], "1000.00")
        formulario_com_talhao = InventarioTalhaoGestorForm(
            initial={
                "inventario": inventario.pk,
                "talhao": talhao_calculado.pk,
            },
            empresa=self.empresa,
        )
        self.assertEqual(
            formulario_com_talhao["saldo_a_retirar_m3"].value(),
            Decimal("250.000"),
        )

        formulario_novo = self.client.get(
            reverse("novo_registro", args=["inventarios-talhao"])
        )
        self.assertContains(
            formulario_novo,
            f'data-talhoes-url="{reverse("talhoes_por_inventario")}"',
        )
        self.assertContains(formulario_novo, 'id="talhao-status"')
        self.assertContains(formulario_novo, 'name="saldo_a_retirar_m3"')
        self.assertContains(formulario_novo, "Saldo a retirar (m³)")

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
            "ciclo_producao_dias": 1,
        }
        outra_fazenda = Fazenda.objects.create(
            empresa=self.empresa,
            proprietario=self.proprietario_proprio,
            nome="Fazenda B",
            area_total_ha="1",
            municipio=self.municipio,
        )
        a = UPC.objects.create(empresa=self.empresa, nome="UPC A", **dados)
        b = UPC.objects.create(
            empresa=self.empresa,
            nome="UPC B",
            **{**dados, "fazenda": outra_fazenda},
        )
        gestor.upcs.add(a)
        self.assertEqual(list(gestor.upcs_permitidas()), [a])
        self.client.force_login(gestor)
        resposta = self.client.get(reverse("lista_registros", args=["upcs"]))
        self.assertContains(resposta, "UPC A")
        self.assertNotContains(resposta, "UPC B")
        autorizacao_a = AutorizacaoAmbiental.objects.create(
            empresa=self.empresa,
            numero="AUT-A",
            produto="LENHA",
            unidade_volume="MST",
            volume_declarado="10",
            data_emissao="2026-01-01",
        )
        autorizacao_a.upcs.add(a)
        autorizacao_b = AutorizacaoAmbiental.objects.create(
            empresa=self.empresa,
            numero="AUT-B",
            produto="LENHA",
            unidade_volume="MST",
            volume_declarado="10",
            data_emissao="2026-01-01",
        )
        autorizacao_b.upcs.add(b)
        autorizacoes_visiveis = self.client.get(
            reverse("lista_registros", args=["autorizacoes"])
        )
        self.assertContains(autorizacoes_visiveis, "AUT-A")
        self.assertNotContains(autorizacoes_visiveis, "AUT-B")
        inventario = {
            "empresa": self.empresa,
            "usuario_inclusao": self.gestor,
            "fazenda": fazenda,
            "data_inventario": "2026-01-01",
            "responsavel_tecnico": "Eng",
            "registro_conselho": "CREA",
            "numero_art": "A",
            "area_ha": "1",
            "volume_total": "1",
            "numero_arvores": "1",
        }
        InventarioFlorestal.objects.create(lote="DA-A", **inventario)
        InventarioFlorestal.objects.create(
            lote="DA-B",
            **{**inventario, "fazenda": outra_fazenda},
        )
        resposta = self.client.get(reverse("lista_registros", args=["inventarios"]))
        self.assertContains(resposta, "DA-A")
        self.assertNotContains(resposta, "DA-B")
        self.assertContains(self.client.get(reverse("inicio")), "UPC A")
        criado = self.client.post(
            reverse("novo_registro", args=["inventarios"]),
            {
                "fazenda": fazenda.pk,
                "lote": "DA-C",
                "data_inventario": "2026-02-01",
                "responsavel_tecnico": "Eng",
                "registro_conselho": "CREA",
                "numero_art": "C",
                "area_ha": "1",
                "volume_total": "1",
                "numero_arvores": "1",
            },
        )
        self.assertEqual(criado.status_code, 302)
        inventario_criado = InventarioFlorestal.objects.get(lote="DA-C")
        self.assertEqual(inventario_criado.fazenda_id, fazenda.pk)
        self.assertEqual(inventario_criado.usuario_inclusao_id, gestor.pk)
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
            usuario_inclusao=self.gestor,
            volume_total="100",
            numero_arvores="200",
        )
        talhao = Talhao.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            identificacao="T9",
            area_ha="5",
            volume_m3="1000",
        )
        dados = {
            "inventario": inventario.pk,
            "talhao": talhao.pk,
            "etapa": "CORTE_FELLER",
            "volume_m3": "600",
            "tipo_execucao": "PROPRIA",
            "unidade_pagamento": "HA",
            "valor_unitario": "1500",
            "data_inicio": "2026-03-10",
            "data_fim": "2026-03-01",
        }

        def salvar(formulario: ColheitaGestorForm) -> Colheita:
            self.assertTrue(formulario.is_valid(), formulario.errors)
            colheita = formulario.save(commit=False)
            colheita.empresa = self.empresa
            colheita.save()
            return colheita

        invalido = ColheitaGestorForm(dados, empresa=self.empresa)
        self.assertFalse(invalido.is_valid())
        self.assertIn("data_fim", invalido.errors)
        dados["data_fim"] = ""
        sem_empreiteiro = ColheitaGestorForm(
            {**dados, "tipo_execucao": "TERCEIRIZADA"}, empresa=self.empresa
        )
        self.assertIn("fornecedor", sem_empreiteiro.errors)

        # Lançamento do dia por volume; a área sai do rendimento (200 m³/ha).
        colheita = salvar(ColheitaGestorForm(dados, empresa=self.empresa))
        self.assertEqual(colheita.sistema, "MECANIZADA")
        self.assertEqual(colheita.rendimento_m3_ha, Decimal("200.000"))
        self.assertEqual(colheita.area_ha, Decimal("3.0000"))
        # Pago por hectare: 3 ha x R$ 1.500.
        self.assertEqual(colheita.valor_total, Decimal("4500.00"))
        self.assertEqual(colheita.volume_a_fazer(), Decimal("400"))

        # Mesma etapa: só cabe o volume que falta do inventário.
        maior = ColheitaGestorForm(dados, empresa=self.empresa)
        self.assertFalse(maior.is_valid())
        self.assertIn("400,00 m³ a fazer", maior.errors["volume_m3"][0])
        # Área informada prevalece sobre a estimada.
        resto = salvar(
            ColheitaGestorForm(
                {**dados, "volume_m3": "400", "area_ha": "1.9"},
                empresa=self.empresa,
            )
        )
        self.assertEqual(resto.area_ha, Decimal("1.9"))
        self.assertEqual(resto.valor_total, Decimal("2850.00"))

        # Outra etapa tem o próprio saldo; pagamento por m³ e por MST.
        arraste = salvar(
            ColheitaGestorForm(
                {
                    **dados,
                    "etapa": "ARRASTE",
                    "volume_m3": "1000",
                    "unidade_pagamento": "M3",
                    "valor_unitario": "3",
                },
                empresa=self.empresa,
            )
        )
        self.assertEqual(arraste.valor_total, Decimal("3000.00"))
        arraste.unidade_pagamento = "MST"
        arraste.save()
        self.assertEqual(arraste.valor_total, Decimal("4500.00"))

        # Ao editar, o volume do próprio lançamento não conta como já feito.
        edicao = ColheitaGestorForm(dados, instance=colheita, empresa=self.empresa)
        self.assertTrue(edicao.is_valid(), edicao.errors)

    def test_colheita_terceirizada_usa_tarifa_vigente_do_empreiteiro(self):
        inventario = InventarioFlorestal.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            lote="L7",
            data_inventario="2026-01-01",
            responsavel_tecnico="Eng",
            registro_conselho="CREA",
            numero_art="A7",
            area_ha="10",
            usuario_inclusao=self.gestor,
            volume_total="1000",
            numero_arvores="200",
        )
        talhao = Talhao.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            identificacao="T7",
            area_ha="10",
        )
        empreiteiro = Fornecedor.objects.create(
            empresa=self.empresa,
            nome_razao_social="Empreiteiro",
            cpf_cnpj="11111111111",
            fornece_servico=True,
        )
        for inicio, fim, valor in (
            ("2026-01-01", "2026-02-28", "10"),
            ("2026-03-01", None, "12"),
        ):
            FornecedorTarifa.objects.create(
                empresa=self.empresa,
                fornecedor=empreiteiro,
                tipo_servico="ARRASTE",
                unidade="M3",
                valor=valor,
                vigencia_inicio=inicio,
                vigencia_fim=fim,
            )
        sobreposta = FornecedorTarifaGestorForm(
            {
                "fornecedor": empreiteiro.pk,
                "tipo_servico": "ARRASTE",
                "unidade": "M3",
                "valor": "15",
                "vigencia_inicio": "2026-04-01",
            },
            empresa=self.empresa,
        )
        self.assertIn("vigencia_inicio", sobreposta.errors)

        dados = {
            "inventario": inventario.pk,
            "talhao": talhao.pk,
            "etapa": "ARRASTE",
            "volume_m3": "200",
            "tipo_execucao": "TERCEIRIZADA",
            "fornecedor": empreiteiro.pk,
            "unidade_pagamento": "HA",
            "data_inicio": "2026-02-15",
        }
        formulario = ColheitaGestorForm(dados, empresa=self.empresa)
        self.assertTrue(formulario.is_valid(), formulario.errors)
        colheita = formulario.save(commit=False)
        colheita.empresa = self.empresa
        colheita.save()
        # Tarifa de fevereiro, em m³: 2 ha x 100 m³/ha x R$ 10.
        self.assertEqual(colheita.valor_unitario, Decimal("10"))
        self.assertEqual(colheita.unidade_pagamento, "M3")
        self.assertEqual(colheita.valor_total, Decimal("2000.00"))

        self.client.force_login(self.gestor)
        resposta = self.client.get(
            reverse("tarifa_vigente"),
            {"fornecedor": empreiteiro.pk, "servico": "ARRASTE", "data": "2026-03-05"},
        )
        self.assertEqual(Decimal(resposta.json()["tarifa"]["valor"]), Decimal("12"))
        sem_tarifa = self.client.get(
            reverse("tarifa_vigente"),
            {"fornecedor": empreiteiro.pk, "servico": "CORTE_FELLER"},
        )
        self.assertIsNone(sem_tarifa.json()["tarifa"])

    def test_listas_formatam_numeros_e_datas_pelos_parametros_do_sistema(self):
        Talhao.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            identificacao="TF",
            area_ha=Decimal("1234.5678"),
            volume_m3=Decimal("98765.4321"),
        )
        self.client.force_login(self.gestor)
        lista = reverse("lista_registros", args=["talhoes"])
        resposta = self.client.get(lista)
        self.assertContains(resposta, "1.234,57")
        self.assertContains(resposta, "98.765,432")
        Parametros.objects.create(
            empresa=self.empresa,
            casas_decimais_ha=4,
            separador_milhar=" ",
            separador_decimal=".",
        )
        self.assertContains(self.client.get(lista), "1 234.5678")

    def test_parametros_partem_do_padrao_do_pais(self):
        self.assertEqual(Parametros.da_empresa(None).formato_data, "dd/mm/yyyy")
        self.assertEqual(Parametros.do_pais("US").separador_decimal, ".")
        formulario = ParametrosForm(
            {
                "empresa": self.empresa.pk,
                "pais": "US",
                "casas_decimais_ha": "2",
                "casas_decimais_volume": "3",
                "casas_decimais_mdc": "2",
                "casas_decimais_valor": "2",
                "casas_decimais_peso": "3",
                "casas_decimais_porcentagem": "2",
                "formato_data": "yyyy-mm-dd",
            }
        )
        self.assertTrue(formulario.is_valid(), formulario.errors)
        parametros = formulario.save()
        # Campos vazios vêm do país; o que foi ajustado prevalece.
        self.assertEqual(parametros.simbolo_monetario, "US$")
        self.assertEqual(parametros.separador_milhar, ",")
        self.assertEqual(parametros.formato_data, "yyyy-mm-dd")

    def test_parametros_da_filial_usam_os_da_matriz(self):
        matriz = self.criar_empresa("Matriz Teste", "11222333000181")
        filial = Empresa(razao_social="Filial Teste", tipo="FILIAL", matriz=matriz)
        self.assertEqual(Parametros.da_empresa(filial).casas_decimais_ha, 2)
        Parametros.objects.create(empresa=matriz, casas_decimais_ha=3)
        self.assertEqual(Parametros.da_empresa(filial).casas_decimais_ha, 3)

    def test_talhoes_do_inventario_informam_area_colhida_e_rendimento(self):
        inventario = InventarioFlorestal.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            lote="L8",
            data_inventario="2026-01-01",
            responsavel_tecnico="Eng",
            registro_conselho="CREA",
            numero_art="A8",
            area_ha="10",
            usuario_inclusao=self.gestor,
            volume_total="1500",
            numero_arvores="200",
        )
        talhao = Talhao.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            identificacao="T8",
            area_ha="5",
        )
        colheita = Colheita.objects.create(
            empresa=self.empresa,
            inventario=inventario,
            talhao=talhao,
            etapa="CORTE_FELLER",
            area_ha=Decimal("2"),
        )
        self.client.force_login(self.gestor)
        url = reverse("talhoes_por_inventario")
        item = self.client.get(
            url, {"inventario": inventario.pk, "etapa": "CORTE_FELLER"}
        ).json()["talhoes"][0]
        self.assertEqual(Decimal(item["area_colhida_ha"]), Decimal("2"))
        outra_etapa = self.client.get(
            url, {"inventario": inventario.pk, "etapa": "ARRASTE"}
        ).json()["talhoes"][0]
        self.assertEqual(Decimal(outra_etapa["area_colhida_ha"]), Decimal("0"))
        # Sem volume no talhão, usa o rendimento do inventário (150 m³/ha).
        self.assertEqual(Decimal(item["rendimento_m3_ha"]), Decimal("150"))
        editando = self.client.get(
            url,
            {
                "inventario": inventario.pk,
                "etapa": "CORTE_FELLER",
                "colheita": colheita.pk,
            },
        ).json()["talhoes"][0]
        self.assertEqual(Decimal(editando["area_colhida_ha"]), Decimal("0"))

    def test_transporte_lenha_calcula_volume_e_custo(self):
        talhao_novo_form = TalhaoGestorForm(empresa=self.empresa)
        self.assertIn("saldo_a_retirar_m3", talhao_novo_form.fields)
        self.assertTrue(talhao_novo_form.fields["saldo_a_retirar_m3"].disabled)
        self.assertIn(
            "transportes",
            talhao_novo_form.fields["saldo_a_retirar_m3"].help_text,
        )
        self.client.force_login(self.gestor)
        formulario_talhao = self.client.get(reverse("novo_registro", args=["talhoes"]))
        self.assertContains(formulario_talhao, "Saldo a retirar (m³)")
        self.assertContains(formulario_talhao, "volume já registrado nos transportes")

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
            volume_m3=Decimal("25"),
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
        self.assertEqual(talhao.saldo_a_retirar_m3, Decimal("5.000"))

        saldo_form = TalhaoGestorForm(instance=talhao, empresa=self.empresa)
        self.assertEqual(
            saldo_form["saldo_a_retirar_m3"].value(), Decimal("5.000")
        )
        volume_reduzido = TalhaoGestorForm(
            {
                "fazenda": self.fazenda_propria.pk,
                "identificacao": "T1",
                "area_ha": "5",
                "volume_m3": "19",
            },
            instance=talhao,
            empresa=self.empresa,
        )
        self.assertTrue(volume_reduzido.is_valid(), volume_reduzido.errors)

        excedente = TransporteLenhaGestorForm(
            {
                **base,
                "volume_mst": "9",
                "destino": "UPC",
                "upc": upc.pk,
                "tipo_transporte": "PROPRIO",
                "valor_m3": "30",
            },
            empresa=self.empresa,
        )
        self.assertTrue(excedente.is_valid(), excedente.errors)
        transporte_excedente = excedente.save(commit=False)
        transporte_excedente.empresa = self.empresa
        transporte_excedente.save()
        self.assertEqual(transporte_excedente.volume_m3, Decimal("6.000"))
        self.assertEqual(
            Talhao.objects.get(pk=talhao.pk).saldo_a_retirar_m3,
            Decimal("-1.000"),
        )

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
            usuario_inclusao=self.gestor,
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
        for campo in ("fazenda", "base_volume", "upcs"):
            self.assertIn(campo, incompleta.errors)

        upc = UPC.objects.create(
            empresa=self.empresa,
            fazenda=self.fazenda_propria,
            nome="U1",
            utm_leste="1",
            utm_norte="1",
            ciclo_producao_dias=8,
        )
        upc_outra_empresa = UPC.objects.create(
            empresa=self.outra_empresa,
            fazenda=self.fazenda_alheia,
            nome="U2",
            utm_leste="1",
            utm_norte="1",
            ciclo_producao_dias=8,
        )
        self.client.force_login(self.administrador)
        self.client.post(
            reverse("selecionar_empresa"), {"empresa": self.empresa.pk}
        )
        pagina_autorizacao = self.client.get(
            reverse("novo_registro", args=["autorizacoes"])
        )
        self.assertEqual(pagina_autorizacao.status_code, 200)
        opcoes_upc = pagina_autorizacao.context["formulario"].fields[
            "upcs"
        ].queryset
        self.assertEqual(list(opcoes_upc), [upc])
        self.assertNotIn(upc_outra_empresa, opcoes_upc)
        self.assertFalse(
            pagina_autorizacao.context["formulario"].fields["upcs"].widget.allow_multiple_selected
        )
        self.assertNotIn(
            "Colheita",
            [
                secao["titulo"]
                for secao in pagina_autorizacao.context["formulario"].secoes
            ],
        )
        for campo_removido in (
            "area_colher_ha",
            "tipo_colheita",
            "percentual_desbaste",
            "possui_subbosque",
            "volume_subbosque_m3_ha",
            "area_basal_acima_10",
        ):
            self.assertNotIn(
                campo_removido, pagina_autorizacao.context["formulario"].fields
            )

        fazenda_origem_2 = Fazenda.objects.create(
            empresa=self.empresa,
            proprietario=self.proprietario_proprio,
            nome="Fazenda de origem 2",
            area_total_ha="10",
            municipio=self.municipio,
        )
        inventario_2 = InventarioFlorestal.objects.create(
            empresa=self.empresa,
            fazenda=fazenda_origem_2,
            lote="L2",
            data_inventario="2026-01-02",
            responsavel_tecnico="Eng",
            registro_conselho="CREA",
            numero_art="A2",
            area_ha="10",
            usuario_inclusao=self.gestor,
            volume_total="100",
            numero_arvores="200",
        )
        upc_outra_fazenda = UPC.objects.create(
            empresa=self.empresa,
            fazenda=fazenda_origem_2,
            nome="U3",
            utm_leste="1",
            utm_norte="1",
            ciclo_producao_dias=8,
        )
        completa = {
            **base,
            "fazenda": self.fazenda_propria.pk,
            "base_volume": "INVENTARIO",
            "inventario": inventario.pk,
            "upcs": [upc.pk],
        }
        dados_multiplos_producao = QueryDict("", mutable=True)
        dados_multiplos_producao.update(completa)
        dados_multiplos_producao.setlist(
            "upcs", [str(upc.pk), str(upc_outra_fazenda.pk)]
        )
        formulario_multiplo_producao = AutorizacaoAmbientalGestorForm(
            dados_multiplos_producao,
            empresa=self.empresa,
        )
        self.assertFalse(formulario_multiplo_producao.is_valid())
        self.assertIn("upcs", formulario_multiplo_producao.errors)

        form = AutorizacaoAmbientalGestorForm(completa, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        autorizacao = form.save(commit=False)
        autorizacao.empresa = self.empresa
        autorizacao.save()
        form.save_m2m()

        repetida = AutorizacaoAmbientalGestorForm(
            {**completa, "numero": "outro"}, empresa=self.empresa
        )
        self.assertFalse(repetida.is_valid())
        self.assertIn("inventario", repetida.errors)

        nota = AutorizacaoAmbientalGestorForm(
            {
                **base,
                "numero": "NF1",
                "modalidade": "NOTA_FISCAL",
                "upcs": [upc.pk, upc_outra_fazenda.pk],
            },
            empresa=self.empresa,
        )
        self.assertTrue(nota.is_valid(), nota.errors)
        self.assertTrue(nota.fields["upcs"].widget.allow_multiple_selected)
        nota_autorizacao = nota.save(commit=False)
        nota_autorizacao.empresa = self.empresa
        nota_autorizacao.save()
        nota.save_m2m()
        self.assertEqual(
            set(nota_autorizacao.upcs.values_list("pk", flat=True)),
            {upc.pk, upc_outra_fazenda.pk},
        )

        segunda_fazenda_mesma_upc = AutorizacaoAmbientalGestorForm(
            {
                **completa,
                "numero": "2100.01.0004433/2026-31",
                "fazenda": fazenda_origem_2.pk,
                "inventario": inventario_2.pk,
            },
            empresa=self.empresa,
        )
        self.assertTrue(
            segunda_fazenda_mesma_upc.is_valid(),
            segunda_fazenda_mesma_upc.errors,
        )
        segunda_autorizacao = segunda_fazenda_mesma_upc.save(commit=False)
        segunda_autorizacao.empresa = self.empresa
        segunda_autorizacao.save()
        segunda_fazenda_mesma_upc.save_m2m()
        self.assertEqual(
            upc.autorizacoes.filter(modalidade="PRODUCAO").count(),
            2,
        )

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

    def test_todos_os_links_do_menu_do_gestor_abrem(self):
        self.client.force_login(self.gestor)
        pagina = self.client.get(reverse("inicio"))
        links = set(
            re.findall(r'class="nav-link[^"]*" href="([^"]+)"', pagina.content.decode())
        )
        self.assertGreater(len(links), 10)
        for link in sorted(links):
            with self.subTest(link=link):
                self.assertEqual(self.client.get(link).status_code, 200)

    def test_menu_trocado_de_empresa_atualiza_o_cabecalho(self):
        self.outra_empresa.tipo = "FILIAL"
        self.outra_empresa.descricao_filial = "Filial 02 - Alpinópolis"
        self.outra_empresa.save()
        self.client.force_login(self.administrador)
        self.client.post(reverse("selecionar_empresa"), {"empresa": self.empresa.pk})
        self.assertNotContains(self.client.get(reverse("inicio")), "Filial 02")

        self.client.post(
            reverse("selecionar_empresa"), {"empresa": self.outra_empresa.pk}
        )

        resposta = self.client.get(reverse("inicio"))
        self.assertContains(resposta, "Filial 02 - Alpinópolis")

    def test_operador_ve_e_acessa_apenas_producao(self):
        operador = criar_usuario(
            username="oper",
            password="x",
            nome_completo="Operador",
            empresa=self.empresa,
            tipo_usuario="operador",
            primeiro_acesso=False,
        )
        self.client.force_login(operador)

        pagina = self.client.get(reverse("inicio"))
        self.assertContains(pagina, reverse("lista_registros", args=["colheitas"]))
        self.assertNotContains(pagina, reverse("lista_registros", args=["fazendas"]))
        self.assertEqual(
            self.client.get(reverse("lista_registros", args=["colheitas"])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("lista_registros", args=["fazendas"])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("lista_registros", args=["ciclos-forno"])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("lista_registros", args=["fornos"])).status_code,
            403,
        )

    def test_usuario_em_primeiro_acesso_ve_aviso_em_vez_do_menu(self):
        self.gestor.primeiro_acesso = True
        self.gestor.save()
        self.client.force_login(self.gestor)

        resposta = self.client.get(reverse("password_change"))

        self.assertContains(resposta, "Defina uma nova senha")
        self.assertContains(resposta, "Salvar nova senha")

    def test_cadastro_rapido_volta_ao_formulario_com_registro_selecionado(self):
        self.client.force_login(self.administrador)
        self.client.post(reverse("selecionar_empresa"), {"empresa": self.empresa.pk})
        origem = reverse("novo_registro", args=["upcs"])
        pagina = self.client.get(origem)
        self.assertContains(pagina, "data-rascunho-link")
        self.assertContains(pagina, "campo=fazenda")

        resposta = self.client.post(
            reverse("novo_registro", args=["proprietarios"])
            + f"?proximo={origem}&campo=proprietario",
            {
                "nome_razao_social": "Novo Dono",
                "cpf_cnpj": "52998224725",
            },
        )

        novo = Proprietario.objects.get(nome_razao_social="Novo Dono")
        self.assertRedirects(
            resposta,
            f"{origem}?selecionar=proprietario%3A{novo.pk}",
            fetch_redirect_response=False,
        )

    def test_empresa_formata_cnpj_cep_e_telefone(self):
        form = EmpresaForm(
            {
                "tipo": "MATRIZ",
                "cnpj": "12345678000195",
                "razao_social": "X",
                "estado": self.estado.pk,
                "municipio": self.municipio.pk,
                "endereco": "Rua",
                "bairro": "Centro",
                "cep": "39400000",
                "telefone": "3832221111",
                "celular": "38999998888",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cnpj"], "12.345.678/0001-95")
        self.assertEqual(form.cleaned_data["cep"], "39400-000")
        self.assertEqual(form.cleaned_data["telefone"], "(38) 3222-1111")
        self.assertEqual(form.cleaned_data["celular"], "(38) 99999-8888")

    def test_cnpj_e_cep_incompletos_sao_recusados(self):
        form = EmpresaForm({"cnpj": "123", "cep": "12"})
        form.is_valid()
        self.assertIn("cnpj", form.errors)
        self.assertIn("cep", form.errors)


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


class ContasPorMatrizTests(TestCase):
    """Cada matriz é um cliente do sistema: não enxerga os dados de outra."""

    @classmethod
    def setUpTestData(cls) -> None:
        estado = Estado.objects.create(codigo=31, uf="MG", nome="Minas Gerais")
        cls.municipio = Municipio.objects.create(
            codigo="3120904", nome="Curvelo", estado=estado
        )
        cls.matriz_a = cls.criar_empresa("Cliente A", "11.111.111/0001-91")
        cls.filial_a1 = cls.criar_empresa(
            "Cliente A", "11.111.111/0002-72", matriz=cls.matriz_a, filial="Filial 01"
        )
        cls.filial_a2 = cls.criar_empresa(
            "Cliente A", "11.111.111/0003-53", matriz=cls.matriz_a, filial="Filial 02"
        )
        cls.matriz_b = cls.criar_empresa("Cliente B", "22.222.222/0001-91")
        cls.admin_a = criar_usuario(
            username="admin-a",
            password="x",
            nome_completo="Admin A",
            tipo_usuario="admin",
            primeiro_acesso=False,
        )
        cls.admin_a.matriz = cls.matriz_a
        cls.admin_a.save()
        for nome, empresa in (("Fazenda A1", cls.filial_a1), ("Fazenda B", cls.matriz_b)):
            Fazenda.objects.create(
                empresa=empresa,
                proprietario=Proprietario.objects.create(
                    empresa=empresa, nome_razao_social=f"Dono {nome}"
                ),
                nome=nome,
                area_total_ha="10",
                municipio=cls.municipio,
            )

    @classmethod
    def criar_empresa(
        cls, nome: str, cnpj: str, matriz: Empresa | None = None, filial: str = ""
    ) -> Empresa:
        return Empresa.objects.create(
            tipo="FILIAL" if matriz else "MATRIZ",
            matriz=matriz,
            descricao_filial=filial,
            cnpj=cnpj,
            razao_social=nome,
            endereco="Rua A",
            bairro="Centro",
            municipio=cls.municipio,
        )

    def criar_upc(self, empresa: Empresa, nome: str) -> UPC:
        return UPC.objects.create(
            empresa=empresa,
            fazenda=Fazenda.objects.filter(empresa=empresa).first()
            or Fazenda.objects.create(
                empresa=empresa,
                proprietario=Proprietario.objects.create(
                    empresa=empresa, nome_razao_social="Dono"
                ),
                nome=f"Fazenda {nome}",
                area_total_ha="1",
                municipio=self.municipio,
            ),
            nome=nome,
            utm_leste="1",
            utm_norte="1",
            ciclo_producao_dias=8,
        )

    def test_administrador_so_ve_a_propria_matriz(self):
        self.client.force_login(self.admin_a)

        empresas = self.client.get(reverse("lista_registros", args=["empresas"]))
        self.assertEqual(
            {linha["objeto"] for linha in empresas.context["linhas"]},
            {self.matriz_a, self.filial_a1, self.filial_a2},
        )
        outra = self.client.post(
            reverse("selecionar_empresa"), {"empresa": self.matriz_b.pk}
        )
        self.assertEqual(outra.status_code, 200)
        self.assertIn("empresa", outra.context["formulario"].errors)
        self.assertEqual(
            self.client.get(
                reverse("editar_registro", args=["empresas", self.matriz_b.pk])
            ).status_code,
            404,
        )

        self.client.post(reverse("selecionar_empresa"), {"empresa": self.filial_a1.pk})
        fazendas = self.client.get(reverse("lista_registros", args=["fazendas"]))
        self.assertContains(fazendas, "Fazenda A1")
        self.assertNotContains(fazendas, "Fazenda B")
        fazenda_b = Fazenda.objects.get(nome="Fazenda B")
        self.assertEqual(
            self.client.get(
                reverse("editar_registro", args=["fazendas", fazenda_b.pk])
            ).status_code,
            404,
        )

    def test_administrador_cadastra_filial_e_usuarios_so_da_propria_matriz(self):
        self.client.force_login(self.admin_a)
        tela = self.client.get(reverse("novo_registro", args=["empresas"]))
        self.assertNotIn("tipo", tela.context["formulario"].fields)
        self.assertNotIn("matriz", tela.context["formulario"].fields)
        resposta = self.client.post(
            reverse("novo_registro", args=["empresas"]),
            {
                "descricao_filial": "Filial 03 - Corinto",
                "cnpj": "11.111.111/0004-34",
                "razao_social": "Cliente A",
                "estado": self.municipio.estado_id,
                "municipio": self.municipio.pk,
                "endereco": "Rua B",
                "bairro": "Centro",
            },
        )
        self.assertEqual(resposta.status_code, 302)
        nova = Empresa.objects.get(cnpj="11.111.111/0004-34")
        self.assertEqual((nova.tipo, nova.matriz), ("FILIAL", self.matriz_a))

        dados = {
            "username": "gestor-a",
            "tipo_usuario": "gestor",
            "nome_completo": "Gestor A",
            "email": "g@example.com",
            "is_active": "on",
            "senha": GESTOR_CREDENTIAL,
            "empresas": [self.matriz_b.pk],
        }
        alheia = self.client.post(reverse("novo_registro", args=["usuarios"]), dados)
        self.assertIn("empresas", alheia.context["formulario"].errors)
        dados["empresas"] = [self.filial_a1.pk, self.filial_a2.pk]
        self.client.post(reverse("novo_registro", args=["usuarios"]), dados)
        gestor = Usuario.objects.get(username="gestor-a")
        self.assertEqual(gestor.matriz, self.matriz_a)
        self.assertFalse(gestor.is_superuser)

        usuarios = self.client.get(reverse("lista_registros", args=["usuarios"]))
        nomes = {linha["objeto"].username for linha in usuarios.context["linhas"]}
        self.assertEqual(nomes, {"admin-a", "gestor-a"})

    def test_gestor_com_uma_empresa_e_uma_upc_entra_direto(self):
        upc = self.criar_upc(self.filial_a1, "UPC A1")
        gestor = criar_usuario(
            username="g1",
            password="x",
            nome_completo="G1",
            empresa=self.filial_a1,
            primeiro_acesso=False,
        )
        self.client.force_login(gestor)

        self.assertEqual(self.client.get(reverse("inicio")).status_code, 200)
        self.assertEqual(
            self.client.session["empresa_ativa_id"], self.filial_a1.pk
        )
        self.assertEqual(self.client.session["upc_ativa_id"], upc.pk)
        self.assertNotContains(self.client.get(reverse("inicio")), "Trocar empresa")

    def test_gestor_com_duas_empresas_escolhe_entre_as_liberadas(self):
        gestor = criar_usuario(
            username="g2",
            password="x",
            nome_completo="G2",
            empresa=self.filial_a1,
            primeiro_acesso=False,
        )
        gestor.empresas.add(self.filial_a2)
        self.client.force_login(gestor)

        resposta = self.client.get(reverse("lista_registros", args=["fazendas"]))
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta["Location"].startswith(reverse("selecionar_empresa")))
        tela = self.client.get(reverse("selecionar_empresa"))
        self.assertEqual(
            set(tela.context["formulario"].fields["empresa"].queryset),
            {self.filial_a1, self.filial_a2},
        )

    def test_empresa_encerrada_fica_so_para_consulta(self):
        self.filial_a2.data_encerramento = "2026-06-30"
        self.filial_a2.motivo_encerramento = "Fim da floresta"
        self.filial_a2.save()
        gestor = criar_usuario(
            username="g3",
            password="x",
            nome_completo="G3",
            empresa=self.filial_a1,
            primeiro_acesso=False,
        )
        gestor.empresas.add(self.filial_a2)
        self.client.force_login(gestor)

        self.client.get(reverse("inicio"))
        self.assertEqual(self.client.session["empresa_ativa_id"], self.filial_a1.pk)

        self.client.post(reverse("selecionar_empresa"), {"empresa": self.filial_a2.pk})
        lista = self.client.get(reverse("lista_registros", args=["fazendas"]))
        self.assertContains(lista, "só para consulta")
        self.assertNotContains(lista, reverse("novo_registro", args=["fazendas"]))
        novo = self.client.get(reverse("novo_registro", args=["fazendas"]))
        self.assertRedirects(
            novo,
            reverse("lista_registros", args=["fazendas"]),
            fetch_redirect_response=False,
        )

    def test_encerramento_exige_motivo(self):
        formulario = EmpresaForm(
            {"tipo": "MATRIZ", "data_encerramento": "2026-06-30"}
        )
        formulario.is_valid()
        self.assertIn("motivo_encerramento", formulario.errors)

    def test_menu_em_secoes_e_subsecoes_conforme_o_perfil(self):
        operador = criar_usuario(
            username="op",
            password="x",
            nome_completo="Op",
            empresa=self.filial_a1,
            tipo_usuario="operador",
            primeiro_acesso=False,
        )

        def titulos(menu: list[dict]) -> set[str]:
            return {
                item["titulo"]
                for secao in menu
                for parte in secao["subsecoes"]
                for item in parte["itens"]
            }

        self.client.force_login(operador)
        menu = self.client.get(reverse("inicio")).context["menu"]
        self.assertEqual(
            [secao["titulo"] for secao in menu],
            ["Florestal", "Produção", "Transporte e vendas"],
        )
        self.assertIn("Painel dos fornos", titulos(menu))
        self.assertNotIn("Usuários", titulos(menu))
        producao = next(secao for secao in menu if secao["chave"] == "producao")
        # O operador lança e consulta, mas não mexe nos cadastros da produção.
        self.assertEqual(
            [parte["titulo"] for parte in producao["subsecoes"]],
            ["Lançamentos", "Relatórios"],
        )

        self.client.force_login(self.admin_a)
        self.client.post(reverse("selecionar_empresa"), {"empresa": self.filial_a1.pk})
        resposta = self.client.get(reverse("lista_registros", args=["fornos"]))
        menu = resposta.context["menu"]
        self.assertIn("Configurações", [secao["titulo"] for secao in menu])
        self.assertEqual([secao["titulo"] for secao in menu if secao["ativa"]], ["Produção"])
        producao = next(secao for secao in menu if secao["chave"] == "producao")
        self.assertEqual(
            [parte["titulo"] for parte in producao["subsecoes"]],
            ["Cadastros", "Lançamentos", "Relatórios"],
        )
        self.assertContains(resposta, 'href="#icone-forno"')
        self.assertContains(resposta, "data-menu-recolher")
