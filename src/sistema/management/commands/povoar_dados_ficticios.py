"""Apaga a base e povoa tudo de novo com dados fictícios.

Preserva os superusuários e as tabelas do IBGE (estados e municípios). Nomes,
CNPJ/CPF e documentos são inventados; a estrutura (matriz, filial, UPC com 66
fornos, talhões) e os números (ciclos, colheita, transporte, expedições,
preços) vêm das planilhas reais da UPCM-CDB, pelo importador.

Uso: manage.py povoar_dados_ficticios --confirmar
Antes de apagar, copia o banco SQLite para src/backups/.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sistema.formatacao import formatar_cnpj, formatar_cpf
from sistema.models import (
    UPC,
    AutorizacaoAmbiental,
    AutorizacaoMovimento,
    BoletimMedicao,
    BoletimTransporte,
    BoxLenha,
    CategoriaCusto,
    CentroCusto,
    CicloForno,
    Cliente,
    Colheita,
    Empresa,
    Equipamento,
    Expedicao,
    FaixaPrecoColheita,
    Fazenda,
    Fornecedor,
    FornecedorTarifa,
    Forno,
    InventarioFlorestal,
    InventarioTalhao,
    ItemBoletim,
    LancamentoCusto,
    LancamentoCustoRateio,
    Municipio,
    ParametroEmpresa,
    Parametros,
    PlanejamentoForno,
    Plantio,
    Proprietario,
    StatusBoletim,
    TabelaPrecoColheita,
    Talhao,
    TipoExecucao,
    TipoForno,
    TipoTransporte,
    TipoUsuario,
    TransporteLenha,
    Usuario,
)

SENHA_DE_TESTE = "Serra@2026"
CURVELO, BELO_HORIZONTE, SETE_LAGOAS = "3120904", "3106200", "3167202"

# Talhões (código, área ha, volume m³) com os números reais; THM na Fazenda
# Boa Vista e THL na Fazenda Lagoa Grande (nomes fictícios).
TALHOES = {
    "boa_vista": [
        ("THM-01", "28.0580", "3443.280"),
        ("THM-02", "27.7290", "3402.900"),
        ("THM-03", "23.3600", "2452.100"),
        ("THM-04", "23.6700", "2484.640"),
    ],
    "lagoa_grande": [
        ("THL-05", "44.2789", "5433.910"),
        ("THL-06", "34.8670", "4278.880"),
        ("THL-07", "31.4560", "3860.280"),
        ("THL-08", "24.1460", "2963.200"),
        ("THL-13", "66.2670", "6956.050"),
        ("THL-14", "50.4210", "5295.840"),
        ("THL-15", "36.1630", "3796.030"),
        ("THL-16", "44.8490", "4707.880"),
    ],
}
VMI_MEDICAO = Decimal("0.34")
NUMEROS_DCF = {
    "boa_vista": "2100.01.0007314/2026-04",
    "lagoa_grande": "2100.01.0008126/2026-07",
}

# Faixas de preço da colheita (VMI, derrubada, arraste, traçamento), da
# aba Valores do Boletim de Medição.
FAIXAS_ATE_5 = [
    ("0.33", "11.57", "10.25", "13.12"),
    ("0.30", "11.89", "10.57", "13.12"),
    ("0.27", "14.76", "10.57", "13.12"),
    ("0.24", "15.51", "12.08", "13.12"),
    ("0.21", "16.46", "12.08", "13.12"),
    ("0.18", "18.45", "14.09", "13.12"),
    ("0.15", "21.40", "13.01", "13.12"),
    ("0.12", "26.75", "17.80", "13.12"),
    ("0.09", "30.58", "19.21", "13.12"),
    ("0.08", "41.16", "21.14", "13.12"),
    ("0.07", "38.92", "24.16", "13.12"),
    ("0.06", "42.81", "24.87", "13.12"),
    ("0.05", "47.56", "28.18", "13.12"),
]
FAIXAS_ACIMA_5 = [
    ("0.33", "14.43", "12.06", "11.52"),
    ("0.30", "15.39", "15.58", "11.52"),
    ("0.27", "16.49", "12.52", "11.52"),
    ("0.24", "17.10", "13.01", "11.52"),
    ("0.21", "17.10", "15.88", "11.52"),
    ("0.18", "20.98", "15.58", "11.52"),
    ("0.15", "23.08", "18.15", "11.52"),
    ("0.12", "28.85", "19.67", "11.52"),
    ("0.09", "32.97", "19.21", "11.52"),
    ("0.08", "44.39", "23.27", "11.52"),
    ("0.07", "41.97", "29.50", "11.52"),
    ("0.06", "46.16", "30.04", "11.52"),
    ("0.05", "51.29", "20.39", "11.52"),
]

# Expedição diária de carvão (MDC), do Controle Geral (aba AJUSTADO).
EXPEDICOES_POR_DIA = [
    ("2026-08-25", "110.36"),
    ("2026-08-26", "108.81"),
    ("2026-08-29", "113.16"),
    ("2026-09-02", "107.87"),
    ("2026-09-03", "116.27"),
    ("2026-09-04", "229.03"),
    ("2026-09-05", "113.90"),
    ("2026-09-09", "112.35"),
    ("2026-09-16", "111.29"),
    ("2026-09-17", "113.58"),
    ("2026-09-29", "110.94"),
    ("2026-09-30", "218.50"),
    ("2026-10-01", "218.69"),
    ("2026-10-02", "106.82"),
    ("2026-10-07", "104.25"),
    ("2026-10-08", "111.99"),
    ("2026-10-09", "213.55"),
    ("2026-10-14", "107.29"),
    ("2026-10-15", "218.23"),
    ("2026-10-17", "108.47"),
    ("2026-10-18", "110.58"),
    ("2026-10-20", "102.43"),
    ("2026-10-31", "215.20"),
    ("2026-11-01", "225.49"),
]

# Ordem de exclusão: dependentes antes das tabelas de que dependem.
MODELOS_A_APAGAR = (
    BoletimTransporte,
    ItemBoletim,
    BoletimMedicao,
    FaixaPrecoColheita,
    TabelaPrecoColheita,
    LancamentoCustoRateio,
    LancamentoCusto,
    Equipamento,
    CategoriaCusto,
    CentroCusto,
    AutorizacaoMovimento,
    Expedicao,
    TransporteLenha,
    Colheita,
    PlanejamentoForno,
    CicloForno,
    BoxLenha,
    Forno,
    TipoForno,
    InventarioTalhao,
    AutorizacaoAmbiental,
    InventarioFlorestal,
    Talhao,
    UPC,
    Plantio,
    FornecedorTarifa,
    Fornecedor,
    Cliente,
    Fazenda,
    Proprietario,
    ParametroEmpresa,
    Parametros,
)


def _digito(numeros: list[int], pesos: list[int]) -> int:
    resto = sum(n * p for n, p in zip(numeros, pesos, strict=True)) % 11
    return 0 if resto < 2 else 11 - resto


def cnpj_valido(raiz: str, filial: int = 1) -> str:
    """CNPJ com dígitos verificadores válidos a partir de 8 dígitos de raiz."""
    numeros = [int(c) for c in raiz + f"{filial:04d}"]
    numeros.append(_digito(numeros, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    numeros.append(_digito(numeros, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    return formatar_cnpj("".join(map(str, numeros)))


def cpf_valido(base: str) -> str:
    numeros = [int(c) for c in base]
    numeros.append(_digito(numeros, list(range(10, 1, -1))))
    numeros.append(_digito(numeros, list(range(11, 1, -1))))
    return formatar_cpf("".join(map(str, numeros)))


class Command(BaseCommand):
    help = "Apaga a base (menos superusuários e IBGE) e povoa com dados fictícios."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Necessário: confirma que a base atual será apagada.",
        )

    def handle(self, *args: object, **opcoes: Any) -> None:  # noqa: ANN401
        if not opcoes["confirmar"]:
            mensagem = "Isto apaga a base atual. Rode de novo com --confirmar."
            raise CommandError(mensagem)
        self.autor = Usuario.objects.filter(is_superuser=True).order_by("pk").first()
        if self.autor is None:
            mensagem = "Crie um superusuário antes (createsuperuser)."
            raise CommandError(mensagem)
        if not Municipio.objects.filter(codigo=CURVELO).exists():
            mensagem = "Sincronize os municípios do IBGE antes."
            raise CommandError(mensagem)
        self._copiar_banco()
        with transaction.atomic():
            self._apagar()
            self._cadastros()
        # O importador abre a própria transação e lê as planilhas.
        call_command(
            "importar_planilhas_cdb", upc=self.upc.nome, gravar=True, stdout=self.stdout
        )
        with transaction.atomic():
            self._lancamentos()
        Session.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Base povoada com dados fictícios."))
        self.stdout.write(
            "Entre de novo. Usuários de teste (senha "
            f"{SENHA_DE_TESTE}): admin.serra, gestor.curvelo, operador.upc."
        )

    # -- apoio ---------------------------------------------------------------

    def _copiar_banco(self) -> None:
        banco = settings.DATABASES["default"]
        if "sqlite3" not in banco["ENGINE"]:
            self.stdout.write("Banco não é SQLite: faça a cópia de segurança à parte.")
            return
        origem = Path(banco["NAME"])
        pasta = origem.parent / "backups"
        pasta.mkdir(exist_ok=True)
        destino = pasta / f"db-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
        shutil.copy2(origem, destino)
        self.stdout.write(f"Cópia de segurança: {destino}")

    def _auditoria(self) -> dict[str, Usuario]:
        return {"usuario_inclusao": self.autor, "usuario_alteracao": self.autor}

    def _apagar(self) -> None:
        Colheita.objects.update(boletim=None)
        for modelo in MODELOS_A_APAGAR:
            modelo.objects.all().delete()
        Usuario.objects.filter(is_superuser=False).delete()
        Usuario.objects.filter(is_superuser=True).update(matriz=None)
        Empresa.objects.filter(matriz__isnull=False).delete()
        Empresa.objects.all().delete()
        self.stdout.write("Base apagada (superusuários e IBGE preservados).")

    # -- cadastros -----------------------------------------------------------

    def _cadastros(self) -> None:
        aud = self._auditoria()
        self.matriz = Empresa.objects.create(
            tipo="MATRIZ",
            cnpj=cnpj_valido("41287906", 1),
            razao_social="SERRA AZUL AGROFLORESTAL LTDA",
            nome_fantasia="Serra Azul Agroflorestal",
            endereco="Av. do Contorno",
            numero="4520",
            bairro="Funcionários",
            municipio_id=BELO_HORIZONTE,
            cep="30110-028",
            celular="(31) 99876-1020",
            **aud,
        )
        self.filial = Empresa.objects.create(
            tipo="FILIAL",
            matriz=self.matriz,
            descricao_filial="FILIAL 02 - CURVELO",
            cnpj=cnpj_valido("41287906", 2),
            razao_social="SERRA AZUL AGROFLORESTAL LTDA",
            nome_fantasia="Serra Azul Agroflorestal",
            endereco="Fazenda Boa Vista",
            numero="s/n",
            bairro="Zona Rural",
            municipio_id=CURVELO,
            cep="35790-000",
            celular="(38) 99712-3344",
            **aud,
        )
        empresa = self.filial
        ParametroEmpresa.objects.create(empresa=empresa, **aud)

        joaquim = Proprietario.objects.create(
            empresa=empresa,
            nome_razao_social="JOAQUIM PEREIRA LOPES",
            cpf_cnpj=cpf_valido("318452907"),
            endereco="Fazenda Boa Vista",
            bairro="Zona Rural",
            municipio_id=CURVELO,
            cep="35790-000",
            **aud,
        )
        cerrado = Proprietario.objects.create(
            empresa=empresa,
            nome_razao_social="AGROPECUÁRIA CERRADO ALTO LTDA",
            cpf_cnpj=cnpj_valido("27654193"),
            endereco="Rodovia BR-135, Km 612",
            bairro="Zona Rural",
            municipio_id=CURVELO,
            cep="35790-000",
            **aud,
        )
        fazendas = {
            "boa_vista": Fazenda.objects.create(
                empresa=empresa,
                proprietario=joaquim,
                nome="FAZENDA BOA VISTA",
                endereco="Estrada da Boa Vista, Km 8",
                localidade="Zona Rural",
                municipio_id=CURVELO,
                cep="35790-000",
                area_total_ha=Decimal("102.9240"),
                numero_matricula="48217",
                **aud,
            ),
            "lagoa_grande": Fazenda.objects.create(
                empresa=empresa,
                proprietario=cerrado,
                nome="FAZENDA LAGOA GRANDE",
                endereco="Estrada da Lagoa, Km 14",
                localidade="Zona Rural",
                municipio_id=CURVELO,
                cep="35790-000",
                area_total_ha=Decimal("342.7480"),
                numero_matricula="39105",
                **aud,
            ),
        }
        consultoria = Fornecedor.objects.create(
            empresa=empresa,
            nome_razao_social="GEOFLORA CONSULTORIA AMBIENTAL LTDA",
            cpf_cnpj=cnpj_valido("33918274"),
            fornece_servico=True,
            registro_conselho="CREA 98.214",
            municipio_id=BELO_HORIZONTE,
            telefone="(31) 3221-4410",
            **aud,
        )
        self.empreiteiro = Fornecedor.objects.create(
            empresa=empresa,
            nome_razao_social="HORIZONTE SERVIÇOS FLORESTAIS LTDA",
            cpf_cnpj=cnpj_valido("19374628"),
            fornece_servico=True,
            municipio_id=CURVELO,
            telefone="(38) 3721-5590",
            **aud,
        )
        self.transportadora = Fornecedor.objects.create(
            empresa=empresa,
            nome_razao_social="TRANSPORTES RIO DAS VELHAS LTDA",
            cpf_cnpj=cnpj_valido("28463019"),
            fornece_servico=True,
            fornece_locacao=True,
            municipio_id=CURVELO,
            telefone="(38) 3722-1180",
            **aud,
        )
        self.loja = Fornecedor.objects.create(
            empresa=empresa,
            nome_razao_social="AUTO PEÇAS CURVELO LTDA",
            cpf_cnpj=cnpj_valido("14726385"),
            fornece_produto=True,
            municipio_id=CURVELO,
            **aud,
        )
        self.cliente = Cliente.objects.create(
            empresa=empresa,
            nome_razao_social="SIDERÚRGICA VALE DO PARAOPEBA LTDA",
            cpf_cnpj=cnpj_valido("06271849"),
            inscricao_estadual="672.184.903.00-15",
            endereco="Rodovia MG-238, Km 9",
            bairro="Distrito Industrial",
            municipio_id=SETE_LAGOAS,
            cep="35702-000",
            telefone="(31) 3773-9020",
            **aud,
        )

        self.upc = UPC.objects.create(
            empresa=empresa,
            fazenda=fazendas["boa_vista"],
            nome="UPC BOA VISTA",
            responsavel_legal="MARCOS ANTÔNIO RIBEIRO",
            utm_leste=Decimal("552310.40"),
            utm_norte=Decimal("7921844.15"),
            utm_fuso="23",
            ciclo_producao_dias=24,
            regime_sabado="ALTERNADO",
            sabado_referencia=date(2026, 11, 14),
            **aud,
        )
        tipo = TipoForno.objects.create(
            empresa=empresa,
            nome="FCM",
            formato="CIRCULAR",
            nivel_mecanizacao="SEMIMECANIZADO",
            descarga_mecanizada=True,
            diametro_m=Decimal("5.50"),
            altura_total_m=Decimal("3.30"),
            altura_cilindro_m=Decimal("2.20"),
            capacidade_mdc=Decimal("18.00"),
            capacidade_lenha_mst=Decimal("42.000"),
            dias_carbonizacao_previstos=6,
            dias_resfriamento_previstos=5,
            dias_vazio_previstos=0,
            **aud,
        )
        Forno.objects.bulk_create(
            Forno(
                empresa=empresa,
                upc=self.upc,
                tipo_forno=tipo,
                numero=f"{numero:02d}",
                data_instalacao=date(2025, 3, 10),
                **aud,
            )
            for numero in range(1, 67)
        )
        for numero, descricao in (("1", "Box da entrada"), ("2", "Box dos fornos")):
            BoxLenha.objects.create(
                empresa=empresa,
                upc=self.upc,
                numero=numero,
                descricao=descricao,
                capacidade_mst=Decimal("600"),
                **aud,
            )

        for (chave, talhoes), lote in zip(
            TALHOES.items(), ("BV-01", "LG-01"), strict=True
        ):
            fazenda = fazendas[chave]
            area = sum((Decimal(a) for _, a, _ in talhoes), Decimal(0))
            volume = sum((Decimal(v) for _, _, v in talhoes), Decimal(0))
            plantio = Plantio.objects.create(
                empresa=empresa,
                fazenda=fazenda,
                idade_anos=9,
                especie="Eucalipto grandis x urophylla",
                origem="EXOTICA",
                metodo_propagacao="CLONAL",
                espacamento_entrelinha_m=Decimal("3.00"),
                espacamento_planta_m=Decimal("2.00"),
                data_plantio=date(2017, 11, 20),
                rotacao=1,
                area_ha=area,
                **aud,
            )
            inventario = InventarioFlorestal.objects.create(
                empresa=empresa,
                fornecedor=consultoria,
                fazenda=fazenda,
                plantio=plantio,
                lote=lote,
                data_inventario=date(2025, 12, 15),
                responsavel_tecnico="LUCIANA MOREIRA DIAS",
                registro_conselho="CREA 98.214",
                numero_art=f"MG2025{lote[-2:]}0417",
                area_ha=area,
                numero_talhoes=len(talhoes),
                especie="Eucalipto grandis x urophylla",
                volume_total=volume,
                numero_arvores=(volume / VMI_MEDICAO).quantize(Decimal("1")),
                dap_medio_cm=Decimal("16.40"),
                altura_media_m=Decimal("25.80"),
                usuario_inclusao=self.autor,
                usuario_alteracao=self.autor,
            )
            for codigo, area_talhao, volume_talhao in talhoes:
                talhao = Talhao.objects.create(
                    empresa=empresa,
                    fazenda=fazenda,
                    plantio=plantio,
                    identificacao=codigo,
                    area_ha=Decimal(area_talhao),
                    volume_m3=Decimal(volume_talhao),
                    inclinacao="ATE_5",
                    vmi_medicao=VMI_MEDICAO,
                    **aud,
                )
                InventarioTalhao.objects.create(
                    empresa=empresa,
                    inventario=inventario,
                    talhao=talhao,
                    area_ha=Decimal(area_talhao),
                    volume_total=Decimal(volume_talhao),
                    numero_arvores=(Decimal(volume_talhao) / VMI_MEDICAO).quantize(
                        Decimal("0.01")
                    ),
                    **aud,
                )
            autorizacao = AutorizacaoAmbiental.objects.create(
                empresa=empresa,
                tipo_documento="DCF",
                origem_floresta="EXOTICA",
                modalidade="PRODUCAO",
                numero=NUMEROS_DCF[chave],
                fazenda=fazenda,
                plantio=plantio,
                inventario=inventario,
                base_volume="INVENTARIO",
                produto="CARVAO_EXOTICA",
                unidade_volume="MDC",
                volume_declarado=(volume / Decimal("1.4")).quantize(Decimal("0.001")),
                volume_base_m3=volume,
                fator_conversao=Decimal("1.4"),
                numero_recibo_sinaflor="13" + lote[-2:] + "58204",
                data_emissao=date(2026, 3, 18),
                data_vencimento=date(2029, 3, 17),
                status="ATIVA",
                **aud,
            )
            autorizacao.upcs.set([self.upc])
        self.stdout.write("Cadastros fictícios criados.")

    # -- lançamentos complementares -----------------------------------------

    def _lancamentos(self) -> None:
        self._colheita_e_boletins()
        self._transporte()
        self._boletins_transporte()
        self._expedicoes()
        self._planejamento()
        self._custos()
        self._usuarios()

    def _colheita_e_boletins(self) -> None:
        aud = self._auditoria()
        empresa = self.filial
        # A colheita mecanizada foi feita pelo empreiteiro (terceirizada).
        Colheita.objects.filter(empresa=empresa).update(
            tipo_execucao=TipoExecucao.TERCEIRIZADA, fornecedor=self.empreiteiro
        )
        tabelas = []
        for inicio, fim, arraste in (
            (date(2026, 4, 1), date(2026, 9, 30), "10.01"),
            (date(2026, 10, 1), None, None),
        ):
            tabela = TabelaPrecoColheita.objects.create(
                empresa=empresa,
                fornecedor=self.empreiteiro,
                vigencia_inicio=inicio,
                vigencia_fim=fim,
                comprimento_tora_ate_5=Decimal("2.20"),
                comprimento_tora_acima_5=Decimal("3.50"),
                **aud,
            )
            for inclinacao, faixas in (
                ("ATE_5", FAIXAS_ATE_5),
                ("ACIMA_5", FAIXAS_ACIMA_5),
            ):
                FaixaPrecoColheita.objects.bulk_create(
                    FaixaPrecoColheita(
                        tabela=tabela,
                        inclinacao=inclinacao,
                        vmi_minimo=Decimal(vmi),
                        preco_derrubada=Decimal(derrubada),
                        preco_arraste=Decimal(arraste or preco_arraste),
                        preco_tracamento=Decimal(tracamento),
                    )
                    for vmi, derrubada, preco_arraste, tracamento in faixas
                )
            tabelas.append(tabela)
        boletins = (
            (
                date(2026, 6, 21),
                date(2026, 4, 1),
                date(2026, 6, 20),
                StatusBoletim.PAGO,
            ),
            (
                date(2026, 7, 31),
                date(2026, 6, 21),
                date(2026, 7, 31),
                StatusBoletim.PAGO,
            ),
            (
                date(2026, 10, 27),
                date(2026, 8, 1),
                date(2026, 10, 27),
                StatusBoletim.FECHADO,
            ),
        )
        for emissao, inicio, fim, status in boletins:
            boletim = BoletimMedicao.objects.create(
                empresa=empresa,
                fornecedor=self.empreiteiro,
                data_emissao=emissao,
                periodo_inicio=inicio,
                periodo_fim=fim,
                elaborado_por="Marcos Antônio Ribeiro",
                validado_por="Helena Castro Vilela",
                **aud,
            )
            boletim.gerar_itens()
            if not boletim.itens.exists():
                boletim.delete()
                continue
            boletim.status = status
            if status == StatusBoletim.PAGO:
                boletim.data_pagamento = emissao + timedelta(days=10)
            boletim.save(update_fields=["status", "data_pagamento"])
        self.stdout.write(
            f"Colheita: {len(tabelas)} tabelas de preço e "
            f"{BoletimMedicao.objects.count()} boletins de medição."
        )

    def _transporte(self) -> None:
        aud = self._auditoria()
        empresa = self.filial
        FornecedorTarifa.objects.create(
            empresa=empresa,
            fornecedor=self.transportadora,
            tipo_servico="TRANSPORTE_LENHA",
            unidade="MST",
            valor=Decimal("22.50"),
            vigencia_inicio=date(2026, 1, 1),
            **aud,
        )
        FornecedorTarifa.objects.create(
            empresa=empresa,
            fornecedor=self.transportadora,
            tipo_servico="FRETE_CARVAO",
            unidade="MDC",
            valor=Decimal("86.00"),
            vigencia_inicio=date(2026, 1, 1),
            **aud,
        )
        placas = ["RVA2C41", "QNK7J83", "PXT4B19"]
        for indice, viagem in enumerate(
            TransporteLenha.objects.filter(empresa=empresa).order_by(
                "data_transporte", "codigo"
            )
        ):
            viagem.tipo_transporte = TipoTransporte.TERCEIRIZADO
            viagem.fornecedor = self.transportadora
            viagem.placa_veiculo = placas[indice % len(placas)]
            viagem.motorista = ("Carlos Nunes", "Edson Prado", "Wagner Lima")[
                indice % 3
            ]
            viagem.numero_documento = f"MDF-{indice + 1:05d}"
            viagem.box_lenha = BoxLenha.objects.filter(upc=self.upc).order_by("numero")[
                indice % 2
            ]
            viagem.valor_mst = Decimal("22.50")
            viagem.save()
        self.stdout.write("Transporte de lenha: viagens atribuídas à transportadora.")

    def _boletins_transporte(self) -> None:
        """Fechamentos do frete de lenha da transportadora, mês a mês."""
        aud = self._auditoria()
        periodos = (
            (date(2026, 7, 31), date(2026, 5, 1), date(2026, 7, 31), "PAGO", "0", ""),
            (date(2026, 8, 31), date(2026, 8, 1), date(2026, 8, 31), "PAGO", "0", ""),
            (
                date(2026, 9, 30),
                date(2026, 9, 1),
                date(2026, 9, 30),
                "PAGO",
                "180.00",
                "Avaria na carga",
            ),
            (
                date(2026, 10, 31),
                date(2026, 10, 1),
                date(2026, 10, 31),
                "FECHADO",
                "0",
                "",
            ),
            (
                date(2026, 11, 6),
                date(2026, 11, 1),
                date(2026, 11, 30),
                "ABERTO",
                "0",
                "",
            ),
        )
        for emissao, inicio, fim, status, desconto, motivo in periodos:
            boletim = BoletimTransporte.objects.create(
                empresa=self.filial,
                fornecedor=self.transportadora,
                data_emissao=emissao,
                periodo_inicio=inicio,
                periodo_fim=fim,
                valor_desconto=Decimal(desconto),
                motivo_desconto=motivo,
                valor_adiantamento=Decimal("1500.00" if emissao.month == 8 else "0"),
                elaborado_por="Marcos Antônio Ribeiro",
                validado_por="Helena Castro Vilela",
                **aud,
            )
            boletim.gerar()
            if not boletim.viagens.exists():
                boletim.delete()
                continue
            boletim.status = status
            if status == "PAGO":
                boletim.data_pagamento = emissao + timedelta(days=5)
            boletim.save(update_fields=["status", "data_pagamento"])
        self.stdout.write(
            f"Transporte: {BoletimTransporte.objects.count()} boletins de transporte."
        )

    def _expedicoes(self) -> None:
        aud = self._auditoria()
        empresa = self.filial
        autorizacao = AutorizacaoAmbiental.objects.filter(
            empresa=empresa, fazenda__nome="FAZENDA LAGOA GRANDE"
        ).first()
        numero = 1200
        for dia, total in EXPEDICOES_POR_DIA:
            data = date.fromisoformat(dia)
            total = Decimal(total)
            cargas = 2 if total > 160 else 1
            for carga in range(cargas):
                volume = (total / cargas).quantize(Decimal("0.01"))
                numero += 1
                Expedicao.objects.create(
                    empresa=empresa,
                    autorizacao=autorizacao,
                    numero_documento=f"NF-e {numero:06d}",
                    data_expedicao=data,
                    cliente=self.cliente.nome_razao_social,
                    placa_veiculo=("RVA9H12", "QPL3M45")[carga],
                    volume_expedido=volume,
                    data_descarga=data + timedelta(days=1),
                    volume_aferido=(volume * Decimal("0.985")).quantize(
                        Decimal("0.01")
                    ),
                    **aud,
                )
        self.stdout.write(f"Expedições de carvão: {Expedicao.objects.count()} cargas.")

    def _planejamento(self) -> None:
        """Dezembro planejado: 6 fornos carregados por dia útil a partir de 01/12."""
        aud = self._auditoria()
        dia = date(2026, 12, 1)
        for posicao, forno in enumerate(
            Forno.objects.filter(upc=self.upc).order_by("numero")
        ):
            if posicao and posicao % 6 == 0:
                dia = self.upc.proximo_dia_de_trabalho(dia + timedelta(days=1))
            PlanejamentoForno.objects.create(
                empresa=self.filial,
                forno=forno,
                data_primeiro_enchimento=dia,
                mdc_previsto=Decimal("18.00"),
                **aud,
            )
        self.stdout.write("Planejamento de dezembro criado.")

    def _custos(self) -> None:
        aud = self._auditoria()
        empresa = self.filial
        centros = {
            "upc": CentroCusto.objects.create(
                empresa=empresa, nome="UPC Boa Vista", tipo="UPC", upc=self.upc, **aud
            ),
            "colheita": CentroCusto.objects.create(
                empresa=empresa, nome="Colheita", tipo="COLHEITA", **aud
            ),
            "transporte": CentroCusto.objects.create(
                empresa=empresa,
                nome="Transporte de lenha",
                tipo="TRANSPORTE_PROPRIO_LENHA",
                **aud,
            ),
            "admin": CentroCusto.objects.create(
                empresa=empresa, nome="Administrativo", tipo="ADMINISTRATIVO", **aud
            ),
        }
        categorias = {
            chave: CategoriaCusto.objects.create(
                empresa=empresa, nome=nome, grupo=grupo, tipo_custo=tipo, **aud
            )
            for chave, nome, grupo, tipo in (
                ("folha", "Folha de pagamento", "MAO_DE_OBRA", "FIXO"),
                ("diesel", "Óleo diesel", "COMBUSTIVEL", "VARIAVEL"),
                ("manutencao", "Manutenção de equipamentos", "MANUTENCAO", "VARIAVEL"),
                ("alimentacao", "Alimentação da equipe", "ALIMENTACAO", "VARIAVEL"),
                ("consultoria", "Consultoria florestal", "CONSULTORIA", "VARIAVEL"),
            )
        }
        for descricao, tipo, placa in (
            ("Carregadeira Caterpillar 924K", "CARREGADEIRA", ""),
            ("Caminhonete Hilux", "VEICULO_LEVE", "RVB1D22"),
            ("Motosserra Stihl MS 382", "MOTOSSERRA", ""),
        ):
            Equipamento.objects.create(
                empresa=empresa,
                descricao=descricao,
                tipo=tipo,
                placa=placa,
                propriedade="PROPRIO",
                centro_custo=centros["upc"],
                **aud,
            )
        mensais = (
            ("upc", "folha", "Folha da UPC", "48500.00", None),
            ("upc", "diesel", "Diesel da carregadeira", "11800.00", self.loja),
            (
                "upc",
                "manutencao",
                "Peças e manutenção dos fornos",
                "6350.00",
                self.loja,
            ),
            ("upc", "alimentacao", "Alimentação da equipe", "3240.00", None),
        )
        for mes in (8, 9, 10):
            competencia = date(2026, mes, 1)
            for centro, categoria, descricao, valor, fornecedor in mensais:
                LancamentoCusto.objects.create(
                    empresa=empresa,
                    data_lancamento=competencia + timedelta(days=27),
                    competencia=competencia,
                    centro_custo=centros[centro],
                    categoria=categorias[categoria],
                    fornecedor=fornecedor,
                    descricao=f"{descricao} - {competencia:%m/%Y}",
                    valor_total=Decimal(valor),
                    data_pagamento=competencia + timedelta(days=34),
                    **aud,
                )
            administrativo = LancamentoCusto.objects.create(
                empresa=empresa,
                data_lancamento=competencia + timedelta(days=5),
                competencia=competencia,
                centro_custo=centros["admin"],
                categoria=categorias["folha"],
                descricao=f"Escritório e gerência - {competencia:%m/%Y}",
                valor_total=Decimal("12600.00"),
                **aud,
            )
            for centro, percentual in (
                ("upc", "70"),
                ("colheita", "20"),
                ("transporte", "10"),
            ):
                LancamentoCustoRateio.objects.create(
                    empresa=empresa,
                    lancamento=administrativo,
                    centro_custo=centros[centro],
                    percentual=Decimal(percentual),
                    **aud,
                )
        LancamentoCusto.objects.create(
            empresa=empresa,
            data_lancamento=date(2025, 12, 20),
            competencia=date(2025, 12, 1),
            centro_custo=centros["colheita"],
            categoria=categorias["consultoria"],
            fornecedor=Fornecedor.objects.get(
                empresa=empresa, nome_razao_social__startswith="GEOFLORA"
            ),
            descricao="Inventário florestal pré-corte",
            valor_total=Decimal("18400.00"),
            data_pagamento=date(2026, 1, 10),
            **aud,
        )
        self.stdout.write(f"Custos: {LancamentoCusto.objects.count()} lançamentos.")

    def _usuarios(self) -> None:
        dados = (
            ("admin.serra", "Helena Castro Vilela", TipoUsuario.ADMINISTRADOR),
            ("gestor.curvelo", "Marcos Antônio Ribeiro", TipoUsuario.GESTOR),
            ("operador.upc", "José Carlos Batista", TipoUsuario.OPERADOR),
        )
        for login, nome, tipo in dados:
            usuario = Usuario(
                username=login,
                nome_completo=nome,
                email=f"{login}@serraazul.example",
                tipo_usuario=tipo,
                primeiro_acesso=False,
                matriz=self.matriz,  # a conta do cliente, para todos os perfis
            )
            usuario.set_password(SENHA_DE_TESTE)
            usuario.save()
            if tipo != TipoUsuario.ADMINISTRADOR:
                usuario.empresas.set([self.filial])
            if tipo == TipoUsuario.OPERADOR:
                usuario.upcs.set([self.upc])
        self.stdout.write("Usuários de teste criados.")
