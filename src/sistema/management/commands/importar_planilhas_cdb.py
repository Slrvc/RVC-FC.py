"""Importa o histórico real da UPCM-CDB das planilhas de controle.

Fontes (pasta Planilhas da área de trabalho):
- 02.CARBONIZAÇÃO - CDB.xlsx, aba BASE DE DADOS: ciclos dos fornos.
- 01.COLHEITA + MOVIMENTAÇÃO DE LENHA CDB.xlsx: colheita diária por etapa e
  movimentação de lenha do talhão para a UPC.
- MEDIÇÃO DE MADEIRA.xlsx, aba Controles: cubagem de cada carga, usada para
  dividir a lenha do dia em viagens (MST médio por viagem).

Sem --gravar roda uma simulação: faz tudo numa transação, mostra o resumo e
desfaz. Documentos que as planilhas não têm (número da viagem) são fictícios
e marcados na observação. Rodar de novo não duplica: o que já foi importado é
ignorado.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from sistema.models import (
    UPC,
    AutorizacaoAmbiental,
    CicloForno,
    Colheita,
    DestinoLenha,
    EtapaColheita,
    Forno,
    InventarioFlorestal,
    InventarioTalhao,
    Talhao,
    TipoExecucao,
    TransporteLenha,
    UnidadeTarifa,
    Usuario,
)

PASTA_PADRAO = Path.home() / "Área de trabalho" / "Planilhas"
MEDICAO_PADRAO = Path.home() / "Área de trabalho" / "MEDIÇÃO DE MADEIRA.xlsx"
MARCA = "Importado da planilha"
ETAPA_DA_COLUNA = {
    3: EtapaColheita.CORTE_FELLER,  # FELLER
    4: EtapaColheita.ARRASTE,  # SKIDDER
    5: EtapaColheita.TRACAMENTO,  # GARRA
    6: EtapaColheita.CORTE_MOTOSSERRA,  # MANUAL
}
MST_POR_VIAGEM_PADRAO = Decimal("67")
LINHAS_VAZIAS_PARA_PARAR = 500


class Simulacao(Exception):  # noqa: N818
    """Desfaz a transação no fim da simulação."""


def _decimal(valor: object, casas: str = "0.001") -> Decimal | None:
    if valor in (None, "") or isinstance(valor, str):
        return None
    numero = Decimal(str(valor)).quantize(Decimal(casas), rounding=ROUND_HALF_UP)
    return numero if numero > 0 else None


def _momento(valor: object) -> datetime | None:
    if not isinstance(valor, datetime):
        return None
    if timezone.is_naive(valor):
        return timezone.make_aware(valor)
    return valor


def _data(valor: object) -> date | None:
    return valor.date() if isinstance(valor, datetime) else None


def _arquivo(pasta: Path, prefixo: str) -> Path:
    encontrados = sorted(pasta.glob(f"{prefixo}*.xlsx"))
    if not encontrados:
        mensagem = f"Não encontrei {prefixo}*.xlsx em {pasta}."
        raise CommandError(mensagem)
    return encontrados[0]


class Command(BaseCommand):
    help = (
        "Importa ciclos de forno, colheita e transporte de lenha das planilhas "
        "da UPCM-CDB. Sem --gravar, só simula."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--pasta", type=Path, default=PASTA_PADRAO)
        parser.add_argument("--medicao", type=Path, default=MEDICAO_PADRAO)
        parser.add_argument("--upc", default="UPCM-CDB", help="Nome da UPC.")
        parser.add_argument(
            "--usuario", help="Login gravado como autor (padrão: superusuário)."
        )
        parser.add_argument(
            "--talhoes",
            help=(
                "Só estes talhões na colheita e no transporte, separados por "
                "vírgula (ex.: THM-01,THL-05). Padrão: todos."
            ),
        )
        parser.add_argument(
            "--gravar", action="store_true", help="Grava (sem ele, só simula)."
        )

    def handle(self, *args: object, **opcoes: Any) -> None:  # noqa: ANN401
        try:
            import openpyxl
        except ImportError as erro:
            mensagem = "Instale o openpyxl (uv sync)."
            raise CommandError(mensagem) from erro
        self.openpyxl = openpyxl
        pasta: Path = opcoes["pasta"]
        if not pasta.is_dir():
            mensagem = f"Pasta não encontrada: {pasta}"
            raise CommandError(mensagem)
        upc = UPC.objects.filter(nome=opcoes["upc"]).select_related("empresa").first()
        if upc is None:
            mensagem = f"UPC {opcoes['upc']} não cadastrada."
            raise CommandError(mensagem)
        self.upc, self.empresa = upc, upc.empresa
        self.usuario = self._usuario(opcoes.get("usuario"))
        self.avisos: list[str] = []
        self.talhoes = {
            nome.strip().upper()
            for nome in (opcoes.get("talhoes") or "").split(",")
            if nome.strip()
        }
        if self.talhoes:
            self.stdout.write(
                f"Colheita e transporte só de: {', '.join(sorted(self.talhoes))}"
            )
        gravar = opcoes["gravar"]
        self.stdout.write(
            f"{'GRAVANDO' if gravar else 'SIMULAÇÃO (nada será gravado)'} · "
            f"{self.empresa} · {upc}"
        )
        try:
            with transaction.atomic():
                self._importar_ciclos(_arquivo(pasta, "02.CARBONIZA"))
                colheita = _arquivo(pasta, "01.COLHEITA")
                self._importar_colheita(colheita)
                self._importar_transporte(colheita, opcoes["medicao"])
                self._conferir()
                if not gravar:
                    raise Simulacao  # noqa: TRY301 (desfaz a transação)
        except Simulacao:
            self.stdout.write(
                self.style.WARNING(
                    "Simulação concluída: nada foi gravado. Use --gravar."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("Importação gravada."))
        for aviso in self.avisos:
            self.stdout.write(self.style.WARNING(f"Aviso: {aviso}"))

    # -- apoio ---------------------------------------------------------------

    def _usuario(self, login: str | None) -> Usuario:
        usuarios = Usuario.objects.all()
        usuario = (
            usuarios.filter(username=login).first()
            if login
            else usuarios.filter(is_superuser=True).first()
        )
        if usuario is None:
            mensagem = "Usuário autor não encontrado (use --usuario)."
            raise CommandError(mensagem)
        return usuario

    def _auditoria(self) -> dict[str, Any]:
        return {"usuario_inclusao": self.usuario, "usuario_alteracao": self.usuario}

    def _abrir(self, caminho: Path):  # noqa: ANN202
        return self.openpyxl.load_workbook(caminho, read_only=True, data_only=True)

    def _talhao(self, fazenda: str | None, numero: object) -> Talhao | None:
        """Mumbuca n -> THM-0n; Lagoa dos Currais n -> THL-nn (5 em diante)."""
        try:
            numero = int(numero)
        except TypeError, ValueError:
            return None
        mumbuca = (fazenda or "").lower().startswith("mumbuca") or (
            fazenda is None and numero <= 4
        )
        identificacao = f"{'THM' if mumbuca else 'THL'}-{numero:02d}"
        return Talhao.objects.filter(
            empresa=self.empresa, identificacao=identificacao
        ).first()

    def _no_escopo(self, talhao: Talhao) -> bool:
        return not self.talhoes or talhao.identificacao in self.talhoes

    def _inventario(self, talhao: Talhao) -> InventarioFlorestal | None:
        por_talhao = (
            InventarioTalhao.objects.filter(talhao=talhao)
            .select_related("inventario")
            .order_by("-inventario__data_inventario")
            .first()
        )
        if por_talhao is not None:
            return por_talhao.inventario
        return (
            InventarioFlorestal.objects.filter(
                empresa=self.empresa, fazenda=talhao.fazenda
            )
            .order_by("-data_inventario")
            .first()
        )

    def _autorizacao(self, talhao: Talhao) -> AutorizacaoAmbiental | None:
        return (
            AutorizacaoAmbiental.objects.filter(
                empresa=self.empresa, fazenda=talhao.fazenda
            )
            .order_by("-data_emissao")
            .first()
        )

    # -- ciclos --------------------------------------------------------------

    def _importar_ciclos(self, caminho: Path) -> None:
        planilha = self._abrir(caminho)["BASE DE DADOS"]
        fornos = {
            forno.numero: forno
            for forno in Forno.objects.filter(upc=self.upc).select_related("tipo_forno")
        }
        linhas = []
        for linha in planilha.iter_rows(min_row=3, values_only=True):
            numero, ciclo, enchimento = linha[1], linha[2], _momento(linha[4])
            if numero is None or enchimento is None:
                continue
            linhas.append((enchimento, numero, ciclo, linha))
        criados = ignorados = 0
        sem_forno: set[object] = set()
        # Em ordem de enchimento: um forno só tem um ciclo em andamento.
        for enchimento, numero, ciclo, linha in sorted(linhas, key=lambda x: x[:2]):
            # O cadastro guarda só o número (01) ou, nos antigos, F01.
            forno = fornos.get(f"{int(numero):02d}") or fornos.get(
                f"F{int(numero):02d}"
            )
            if forno is None:
                sem_forno.add(numero)
                continue
            if CicloForno.objects.filter(forno=forno, numero_ciclo=ciclo).exists():
                ignorados += 1
                continue
            descarga = _momento(linha[11])
            mdc = _decimal(linha[14], "0.01")
            CicloForno.objects.create(
                empresa=self.empresa,
                forno=forno,
                numero_ciclo=ciclo,
                data_inicio_enchimento=enchimento,
                data_acendimento=_momento(linha[6]) or enchimento,
                data_fim_carbonizacao=_momento(linha[7]),
                data_descarga=descarga if mdc else None,
                volume_lenha_enchimento=_decimal(linha[5]) or Decimal("40.13"),
                volume_mdc=mdc if descarga else None,
                responsavel_enchimento=str(linha[3] or "")[:80],
                responsavel_descarga=str(linha[12] or "")[:80],
                tipo_execucao=TipoExecucao.PROPRIA,
                observacao=f"{MARCA} 02.CARBONIZAÇÃO",
                **self._auditoria(),
            )
            criados += 1
        if sem_forno:
            self.avisos.append(
                f"Fornos da planilha sem cadastro na UPC: {sorted(sem_forno)}"
            )
        self.stdout.write(f"Ciclos de forno: {criados} novos, {ignorados} já existiam.")

    # -- colheita ------------------------------------------------------------

    def _importar_colheita(self, caminho: Path) -> None:  # noqa: C901
        planilha = self._abrir(caminho)["COLHEITA"]
        criados = ignorados = 0
        sem_talhao: set[str] = set()
        fora_do_escopo = 0
        protegidos: set[str] = set()
        # Etapas com lançamento feito à mão não recebem a importação (não duplica).
        manuais = set(
            Colheita.objects.filter(empresa=self.empresa)
            .exclude(observacao__startswith=MARCA)
            .values_list("talhao_id", "etapa")
        )
        for linha in planilha.iter_rows(min_row=2, values_only=True):
            dia = _data(linha[0])
            if dia is None:
                continue
            talhao = self._talhao(linha[1], linha[2])
            volumes = {
                etapa: _decimal(linha[coluna])
                for coluna, etapa in ETAPA_DA_COLUNA.items()
            }
            if not any(volumes.values()):
                continue
            if talhao is None:
                sem_talhao.add(f"{linha[1]} {linha[2]}")
                continue
            if not self._no_escopo(talhao):
                fora_do_escopo += 1
                continue
            inventario = self._inventario(talhao)
            if inventario is None:
                self.avisos.append(f"{talhao} sem inventário: colheita ignorada.")
                continue
            for etapa, volume in volumes.items():
                if not volume:
                    continue
                if (talhao.pk, etapa) in manuais:
                    protegidos.add(f"{talhao.identificacao} {etapa.label}")
                    continue
                existe = Colheita.objects.filter(
                    talhao=talhao, etapa=etapa, data_inicio=dia, volume_m3=volume
                ).exists()
                if existe:
                    ignorados += 1
                    continue
                Colheita.objects.create(
                    empresa=self.empresa,
                    inventario=inventario,
                    talhao=talhao,
                    autorizacao=self._autorizacao(talhao),
                    etapa=etapa,
                    tipo_execucao=TipoExecucao.PROPRIA,
                    data_inicio=dia,
                    volume_m3=volume,
                    unidade_pagamento=UnidadeTarifa.HA,
                    observacao=f"{MARCA} 01.COLHEITA",
                    **self._auditoria(),
                )
                criados += 1
        if sem_talhao:
            self.avisos.append(
                f"Talhões da colheita sem cadastro: {sorted(sem_talhao)}"
            )
        if protegidos:
            self.avisos.append(
                "Já há lançamento manual, importação não feita: "
                f"{', '.join(sorted(protegidos))}. Exclua o manual e rode de novo "
                "para trazer o detalhe diário."
            )
        if fora_do_escopo:
            self.stdout.write(f"Colheita: {fora_do_escopo} linhas de outros talhões.")
        self.stdout.write(
            f"Colheita (lançamentos por etapa): {criados} novos, "
            f"{ignorados} já existiam."
        )

    # -- transporte de lenha -------------------------------------------------

    def _mst_por_viagem(self, caminho: Path) -> Decimal:
        if not caminho.exists():
            self.avisos.append(
                f"{caminho.name} não encontrada: "
                f"viagens de {MST_POR_VIAGEM_PADRAO} MST."
            )
            return MST_POR_VIAGEM_PADRAO
        cargas = [
            Decimal(str(linha[19]))
            for linha in self._abrir(caminho)["Controles"].iter_rows(
                min_row=3, values_only=True
            )
            if isinstance(linha[19], (int, float)) and linha[19] > 0
        ]
        if not cargas:
            return MST_POR_VIAGEM_PADRAO
        media = (sum(cargas) / len(cargas)).quantize(Decimal("0.01"))
        self.stdout.write(
            f"Cubagem: {len(cargas)} cargas, média de {media} MST por viagem."
        )
        return media

    def _importar_transporte(self, caminho: Path, medicao: Path) -> None:  # noqa: C901
        por_viagem = self._mst_por_viagem(medicao)
        planilha = self._abrir(caminho)["MOVIMENTAÇÃO"]
        por_dia: dict[tuple[date, Talhao], Decimal] = defaultdict(Decimal)
        vazias = 0
        sem_talhao: set[object] = set()
        for linha in planilha.iter_rows(min_row=3, values_only=True):
            dia, volume = _data(linha[0]), _decimal(linha[4])  # TALHÃO - UPC
            if dia is None or not volume:
                vazias += 1
                if vazias > LINHAS_VAZIAS_PARA_PARAR:
                    break
                continue
            vazias = 0
            talhao = self._talhao(None, linha[1])
            if talhao is None:
                sem_talhao.add(linha[1])
                continue
            if not self._no_escopo(talhao):
                continue
            por_dia[(dia, talhao)] += volume
        criadas = ignoradas = 0
        sequencia = TransporteLenha.objects.filter(observacao__startswith=MARCA).count()
        for (dia, talhao), volume in sorted(
            por_dia.items(), key=lambda item: (item[0][0], item[0][1].identificacao)
        ):
            if TransporteLenha.objects.filter(
                talhao=talhao, data_transporte=dia, observacao__startswith=MARCA
            ).exists():
                ignoradas += 1
                continue
            autorizacao = self._autorizacao(talhao)
            if autorizacao is None:
                self.avisos.append(f"{talhao} sem autorização: transporte ignorado.")
                continue
            viagens = max(
                1, int((volume / por_viagem).to_integral_value(ROUND_HALF_UP))
            )
            parte = (volume / viagens).quantize(Decimal("0.001"))
            for numero in range(viagens):
                sequencia += 1
                # A última viagem leva o arredondamento para fechar o dia.
                mst = volume - parte * (viagens - 1) if numero == viagens - 1 else parte
                TransporteLenha.objects.create(
                    empresa=self.empresa,
                    autorizacao=autorizacao,
                    talhao=talhao,
                    destino=DestinoLenha.UPC,
                    upc=self.upc,
                    data_transporte=dia,
                    numero_documento=f"SIM-{sequencia:05d}",
                    volume_mst=mst,
                    observacao=(
                        f"{MARCA} 01.MOVIMENTAÇÃO; documento fictício; "
                        f"viagem {numero + 1}/{viagens} do dia"
                    ),
                    **self._auditoria(),
                )
                criadas += 1
        if sem_talhao:
            self.avisos.append(
                f"Talhões da movimentação sem cadastro: {sorted(sem_talhao)}"
            )
        self.stdout.write(
            f"Transporte de lenha: {criadas} viagens novas "
            f"({len(por_dia)} dias x talhão), {ignoradas} dias já existiam."
        )

    # -- conferência ---------------------------------------------------------

    def _conferir(self) -> None:
        ciclos = CicloForno.objects.filter(forno__upc=self.upc)
        descarregados = ciclos.exclude(data_descarga__isnull=True)
        mdc = descarregados.aggregate(total=Sum("volume_mdc"))["total"] or 0
        self.stdout.write(
            f"Conferência: {ciclos.count()} ciclos, {descarregados.count()} "
            f"descarregados, {mdc} MDC produzidos."
        )
        transportado = TransporteLenha.objects.filter(upc=self.upc).aggregate(
            mst=Sum("volume_mst"), m3=Sum("volume_m3")
        )
        self.stdout.write(
            f"Conferência: lenha transportada {transportado['mst'] or 0} MST "
            f"({transportado['m3'] or 0} m³)."
        )
        totais = (
            Colheita.objects.filter(empresa=self.empresa)
            .values("talhao__identificacao", "etapa")
            .annotate(volume=Sum("volume_m3"))
            .order_by("talhao__identificacao", "etapa")
        )
        for linha in totais:
            talhao = Talhao.objects.get(
                empresa=self.empresa, identificacao=linha["talhao__identificacao"]
            )
            ifpc = Colheita.volume_do_talhao(talhao, self._inventario(talhao))
            marca = ""
            if ifpc is not None and linha["volume"] > ifpc + Decimal("0.01"):
                marca = "  ⚠ acima do inventário"
            self.stdout.write(
                f"  {linha['talhao__identificacao']} "
                f"{EtapaColheita(linha['etapa']).label}: {linha['volume']} m³ "
                f"(inventário {ifpc}){marca}"
            )
