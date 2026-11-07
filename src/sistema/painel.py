"""Dados do dashboard da visão geral e do painel diário dos fornos."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Q, Sum
from django.utils import timezone

from sistema.formatacao import formatar_numero
from sistema.models import (
    STATUS_CICLO_ATIVO,
    UPC,
    CicloForno,
    Colheita,
    EtapaColheita,
    Expedicao,
    Forno,
    InventarioFlorestal,
    PlanejamentoForno,
    SituacaoForno,
    StatusCiclo,
    TransporteLenha,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet

    from sistema.models import Parametros

# Estados do forno no dia, na ordem do ciclo (mesmas letras da planilha).
ESTADOS_DO_DIA = (
    ("V", "Vazio"),
    ("L", "Enchido, aguardando acendimento"),
    ("C", "Carbonizando"),
    ("R", "Resfriando"),
    ("D", "Descarga"),
    ("M", "Manutenção"),
)
DIAS_DOS_GRAFICOS = 30


def _dia(valor) -> date | None:
    return timezone.localdate(valor) if valor else None


# ---------------------------------------------------------------------------
# Situação atual dos fornos


@dataclass
class SituacaoFornos:
    total: int = 0
    vazios: int = 0
    carbonizando: int = 0
    resfriando: int = 0
    manutencao: int = 0
    atrasados: list[CicloForno] = field(default_factory=list)

    @property
    def partes(self) -> list[dict]:
        """Blocos da barra segmentada (só os que têm fornos)."""
        partes = [
            ("V", "Vazios", self.vazios),
            ("C", "Carbonizando", self.carbonizando),
            ("R", "Resfriando", self.resfriando),
            ("M", "Em manutenção", self.manutencao),
        ]
        return [
            {
                "codigo": codigo,
                "rotulo": rotulo,
                "quantidade": quantidade,
                "percentual": round(quantidade * 100 / self.total, 1),
            }
            for codigo, rotulo, quantidade in partes
            if quantidade and self.total
        ]


def situacao_dos_fornos(fornos: QuerySet[Forno]) -> SituacaoFornos:
    fornos = fornos.exclude(situacao=SituacaoForno.DESATIVADO)
    situacao = SituacaoFornos(total=fornos.count())
    ativos = (
        CicloForno.objects.filter(forno__in=fornos, status__in=STATUS_CICLO_ATIVO)
        .select_related("forno__upc", "forno__tipo_forno")
        .order_by("forno__upc__nome", "forno__numero")
    )
    ocupados = set()
    for ciclo in ativos:
        ocupados.add(ciclo.forno_id)
        if ciclo.status == StatusCiclo.RESFRIAMENTO:
            situacao.resfriando += 1
        else:
            situacao.carbonizando += 1
        if ciclo.alerta_prazo:
            situacao.atrasados.append(ciclo)
    livres = fornos.exclude(pk__in=ocupados)
    situacao.manutencao = livres.filter(situacao=SituacaoForno.EM_MANUTENCAO).count()
    situacao.vazios = livres.count() - situacao.manutencao
    return situacao


# ---------------------------------------------------------------------------
# Indicadores do mês e séries diárias


def _soma(queryset: QuerySet, campo: str) -> Decimal:
    return queryset.aggregate(total=Sum(campo))["total"] or Decimal(0)


def indicadores_do_mes(
    empresa_id: int, fornos: QuerySet[Forno], inicio: date, fim: date
) -> dict[str, Decimal | None]:
    descargas = CicloForno.objects.filter(
        forno__in=fornos,
        status=StatusCiclo.DESCARREGADO,
        data_descarga__date__range=(inicio, fim),
    )
    producao = _soma(descargas, "volume_mdc")
    lenha_dos_descarregados = _soma(descargas, "volume_lenha_enchimento")
    enchimentos = CicloForno.objects.filter(
        forno__in=fornos, data_inicio_enchimento__date__range=(inicio, fim)
    ).exclude(status=StatusCiclo.CANCELADO)
    return {
        "producao_mdc": producao,
        "lenha_enfornada_mst": _soma(enchimentos, "volume_lenha_enchimento"),
        "fator_mst_mdc": (lenha_dos_descarregados / producao) if producao else None,
        "expedido": _soma(
            Expedicao.objects.filter(
                empresa_id=empresa_id, data_expedicao__range=(inicio, fim)
            ),
            "volume_expedido",
        ),
        "lenha_transportada_mst": _soma(
            TransporteLenha.objects.filter(
                empresa_id=empresa_id, data_transporte__range=(inicio, fim)
            ),
            "volume_mst",
        ),
        "colheita_corte_ha": _soma(
            _colheitas_do_periodo(empresa_id, inicio, fim).filter(
                etapa__in=(EtapaColheita.CORTE_FELLER, EtapaColheita.CORTE_MOTOSSERRA)
            ),
            "area_ha",
        ),
    }


def _colheitas_do_periodo(empresa_id: int, inicio: date, fim: date) -> QuerySet:
    """Lançamentos cuja data (fim, ou início se não houver) cai no período."""
    return Colheita.objects.filter(empresa_id=empresa_id).filter(
        Q(data_fim__range=(inicio, fim))
        | Q(data_fim__isnull=True, data_inicio__range=(inicio, fim))
    )


@dataclass
class Grafico:
    titulo: str
    unidade: str
    colunas: list[dict]
    total: str
    vazio: bool


def _grafico_diario(
    titulo: str,
    unidade: str,
    valores: dict[date, Decimal],
    inicio: date,
    parametros: Parametros,
    casas: int,
) -> Grafico:
    dias = [inicio + timedelta(days=n) for n in range(DIAS_DOS_GRAFICOS)]
    maior = max((valores.get(dia, Decimal(0)) for dia in dias), default=Decimal(0))
    colunas = []
    for dia in dias:
        valor = valores.get(dia, Decimal(0))
        texto = formatar_numero(valor, parametros, casas)
        colunas.append(
            {
                "dia": dia,
                "rotulo_dia": dia.strftime("%d/%m"),
                "valor": texto,
                "altura": float(valor / maior * 100) if maior else 0,
                "descricao": f"{dia:%d/%m}: {texto} {unidade}",
                "marcar_dia": dia.day == 1 or dia == dias[0] or dia.weekday() == 0,
            }
        )
    total = sum(valores.get(dia, Decimal(0)) for dia in dias)
    return Grafico(
        titulo=titulo,
        unidade=unidade,
        colunas=colunas,
        total=formatar_numero(total, parametros, casas),
        vazio=not maior,
    )


def _por_dia(pares: Iterable[tuple[object, Decimal | None]]) -> dict[date, Decimal]:
    totais: dict[date, Decimal] = {}
    for momento, valor in pares:
        dia = _dia(momento) if isinstance(momento, datetime) else momento
        if dia is not None and valor:
            totais[dia] = totais.get(dia, Decimal(0)) + valor
    return totais


def graficos_dos_ultimos_dias(
    empresa_id: int, fornos: QuerySet[Forno], hoje: date, parametros: Parametros
) -> list[Grafico]:
    inicio = hoje - timedelta(days=DIAS_DOS_GRAFICOS - 1)
    producao = _por_dia(
        CicloForno.objects.filter(
            forno__in=fornos,
            status=StatusCiclo.DESCARREGADO,
            data_descarga__date__gte=inicio,
        ).values_list("data_descarga", "volume_mdc")
    )
    transporte = _por_dia(
        TransporteLenha.objects.filter(
            empresa_id=empresa_id, data_transporte__gte=inicio
        ).values_list("data_transporte", "volume_mst")
    )
    expedicao = _por_dia(
        Expedicao.objects.filter(
            empresa_id=empresa_id, data_expedicao__gte=inicio
        ).values_list("data_expedicao", "volume_expedido")
    )
    mdc, volume = parametros.casas_decimais_mdc, parametros.casas_decimais_volume
    return [
        _grafico_diario("Produção de carvão", "MDC", producao, inicio, parametros, mdc),
        _grafico_diario(
            "Transporte de lenha", "MST", transporte, inicio, parametros, volume
        ),
        _grafico_diario(
            "Expedição de carvão", "MDC", expedicao, inicio, parametros, mdc
        ),
    ]


def colheita_por_etapa(
    empresa_id: int, inicio: date, fim: date, parametros: Parametros
) -> list[dict]:
    """Área lançada no mês por etapa, da maior para a menor."""
    totais = {
        linha["etapa"]: linha["area"]
        for linha in _colheitas_do_periodo(empresa_id, inicio, fim)
        .values("etapa")
        .annotate(area=Sum("area_ha"))
    }
    maior = max(totais.values(), default=Decimal(0))
    return [
        {
            "rotulo": EtapaColheita(etapa).label,
            "valor": formatar_numero(area, parametros, parametros.casas_decimais_ha),
            "largura": float(area / maior * 100) if maior else 0,
        }
        for etapa, area in sorted(totais.items(), key=lambda item: -item[1])
    ]


# ---------------------------------------------------------------------------
# Painel diário dos fornos (grade do mês)


def estado_no_dia(ciclos: list[CicloForno], forno: Forno, dia: date, hoje: date) -> str:
    if dia > hoje:
        return ""
    for ciclo in ciclos:
        enchimento = _dia(ciclo.data_inicio_enchimento)
        acendimento = _dia(ciclo.data_acendimento) or enchimento
        fim = _dia(ciclo.data_fim_carbonizacao)
        descarga = _dia(ciclo.data_descarga)
        if descarga == dia:
            return "D"
        if enchimento <= dia < acendimento:
            return "L"
        em_carbonizacao = acendimento <= dia and (fim is None or dia < fim)
        if em_carbonizacao and (descarga is None or dia < descarga):
            return "C"
        if fim is not None and fim <= dia and (descarga is None or dia < descarga):
            return "R"
    if dia == hoje and forno.situacao == SituacaoForno.EM_MANUTENCAO:
        return "M"
    return "V"


def _projetar(
    estados: list[str],
    producao: list[Decimal],
    inicio_mes: date,
    enchimento: date,
    tipo,
    mdc: Decimal,
    upc: UPC,
    ate: date | None = None,
) -> None:
    """Preenche os ciclos previstos a partir de um enchimento, até o fim do mês.

    Carbonização a partir do enchimento, resfriamento, descarga e, depois dos
    dias vazio, um novo enchimento (como na linha PL da planilha de ciclo).
    Enchimento e descarga só em dia de trabalho da UPC: sem trabalho, o forno
    continua resfriando (descarga) ou fica vazio (enchimento) até o próximo.
    """
    ultimo = inicio_mes + timedelta(days=len(estados) - 1)
    limite = min(ultimo, ate) if ate else ultimo
    carbonizacao = max(tipo.dias_carbonizacao_previstos, 1)
    resfriamento = tipo.dias_resfriamento_previstos
    # Novo enchimento no dia seguinte aos dias vazio depois da descarga.
    intervalo = tipo.dias_vazio_previstos + 1
    enchimento = upc.proximo_dia_de_trabalho(enchimento)
    while enchimento <= limite:
        descarga = upc.proximo_dia_de_trabalho(
            enchimento + timedelta(days=carbonizacao + resfriamento)
        )
        dia = enchimento
        while dia <= min(descarga, limite):
            if dia >= inicio_mes:
                indice = (dia - inicio_mes).days
                if dia == descarga:
                    estados[indice] = "D"
                    producao[indice] += mdc
                elif dia < enchimento + timedelta(days=carbonizacao):
                    estados[indice] = "C"
                else:
                    estados[indice] = "R"
            dia += timedelta(days=1)
        enchimento = upc.proximo_dia_de_trabalho(
            descarga + timedelta(days=intervalo)
        )


def _projetar_do_ciclo(
    estados: list[str],
    producao: list[Decimal],
    inicio_mes: date,
    ciclo: CicloForno,
    forno: Forno,
    mdc: Decimal,
    minimo: date,
    conhecido_ate: date,
    ate: date | None = None,
) -> None:
    """Continua a partir de um ciclo real, usando o que já aconteceu nele.

    Datas reais até ``conhecido_ate`` valem; o que ainda não aconteceu é
    previsto pelos prazos e não fica antes de ``minimo`` (o forno atrasado
    descarrega no próximo dia de trabalho possível).
    """
    tipo, upc = forno.tipo_forno, forno.upc
    corte = conhecido_ate

    def real(valor) -> date | None:
        dia = _dia(valor)
        return dia if dia is not None and dia <= corte else None

    enchimento = _dia(ciclo.data_acendimento) or _dia(ciclo.data_inicio_enchimento)
    fim = real(ciclo.data_fim_carbonizacao) or max(
        enchimento + timedelta(days=max(tipo.dias_carbonizacao_previstos, 1)),
        minimo,
    )
    descarga = real(ciclo.data_descarga) or upc.proximo_dia_de_trabalho(
        max(fim + timedelta(days=tipo.dias_resfriamento_previstos), minimo)
    )
    ultimo = inicio_mes + timedelta(days=len(estados) - 1)
    limite = min(ultimo, ate) if ate else ultimo
    dia = max(enchimento, inicio_mes)
    while dia <= min(descarga, limite):
        indice = (dia - inicio_mes).days
        if dia == descarga:
            estados[indice] = "D"
            producao[indice] += mdc
        else:
            estados[indice] = "C" if dia < fim else "R"
        dia += timedelta(days=1)
    # O próximo enchimento ainda não lançado não pode cair num dia que passou.
    seguinte = max(
        descarga + timedelta(days=tipo.dias_vazio_previstos + 1), minimo
    )
    _projetar(estados, producao, inicio_mes, seguinte, tipo, mdc, upc, ate)


def planejado_do_forno(
    forno: Forno,
    plano: PlanejamentoForno | None,
    ultimo_real: CicloForno | None,
    inicio_mes: date,
    dias: int,
    atual: CicloForno | None = None,
    hoje: date | None = None,
) -> tuple[list[str], list[Decimal]]:
    """Linha PL do forno no mês.

    Até ontem: o planejado no início do mês (planejamento do mês ou, sem ele,
    a continuação do último ciclo real). De hoje em diante: refeito a partir
    do estado real do forno (``atual``), para mostrar o que vem pela frente.
    """
    if ultimo_real is None and plano is None and atual is None:
        return [""] * dias, [Decimal(0)] * dias
    mdc = plano.mdc_por_ciclo if plano else forno.capacidade_efetiva_mdc

    def montar(
        base: CicloForno | None, minimo: date, conhecido_ate: date
    ) -> tuple[list, list]:
        estados = ["V"] * dias
        producao = [Decimal(0)] * dias
        usa_plano = plano is not None and plano.data_primeiro_enchimento >= minimo
        ate = plano.data_primeiro_enchimento - timedelta(days=1) if usa_plano else None
        if base is not None:
            _projetar_do_ciclo(
                estados,
                producao,
                inicio_mes,
                base,
                forno,
                mdc,
                minimo,
                conhecido_ate,
                ate,
            )
        if usa_plano or (plano is not None and base is None):
            _projetar(
                estados,
                producao,
                inicio_mes,
                plano.data_primeiro_enchimento,
                forno.tipo_forno,
                mdc,
                forno.upc,
            )
        return estados, producao

    # No início do mês só se sabia o que aconteceu até o mês anterior.
    estados, producao = montar(
        ultimo_real, inicio_mes, inicio_mes - timedelta(days=1)
    )
    fim_mes = inicio_mes + timedelta(days=dias - 1)
    if atual is not None and hoje is not None and inicio_mes < hoje <= fim_mes:
        # Hoje já se sabe o que foi lançado hoje; o resto pode acontecer hoje.
        novos, nova_producao = montar(atual, hoje, hoje)
        corte = (hoje - inicio_mes).days
        estados[corte:] = novos[corte:]
        producao[corte:] = nova_producao[corte:]
    return estados, producao


def grade_do_mes(  # noqa: C901
    fornos: QuerySet[Forno],
    ano: int,
    mes: int,
    parametros: Parametros,
    hoje: date | None = None,
) -> dict:
    hoje = hoje or timezone.localdate()
    ultimo = calendar.monthrange(ano, mes)[1]
    inicio, fim = date(ano, mes, 1), date(ano, mes, ultimo)
    dias = [inicio + timedelta(days=n) for n in range(ultimo)]
    fornos = list(
        fornos.exclude(situacao=SituacaoForno.DESATIVADO)
        .select_related("upc", "tipo_forno")
        .order_by("upc__nome", "numero")
    )
    # Um objeto por UPC para todos os fornos dela.
    upcs: dict[int, UPC] = {}
    for forno in fornos:
        forno.upc = upcs.setdefault(forno.upc_id, forno.upc)
    ciclos_por_forno: dict[int, list[CicloForno]] = {forno.pk: [] for forno in fornos}
    ciclos = (
        CicloForno.objects.filter(
            forno__in=fornos, data_inicio_enchimento__date__lte=fim
        )
        .exclude(status=StatusCiclo.CANCELADO)
        .filter(Q(data_descarga__isnull=True) | Q(data_descarga__date__gte=inicio))
        .order_by("data_inicio_enchimento")
    )
    for ciclo in ciclos:
        ciclos_por_forno[ciclo.forno_id].append(ciclo)
    planos = {
        plano.forno_id: plano
        for plano in PlanejamentoForno.objects.filter(forno__in=fornos, mes=inicio)
    }
    # Base do PL sem planejamento: o último ciclo real enchido antes do mês.
    ultimos_reais: dict[int, CicloForno] = {}
    for ciclo in (
        CicloForno.objects.filter(
            forno__in=fornos, data_inicio_enchimento__date__lt=inicio
        )
        .exclude(status=StatusCiclo.CANCELADO)
        .order_by("data_inicio_enchimento")
    ):
        ultimos_reais[ciclo.forno_id] = ciclo
    # Estado real de hoje: o último ciclo enchido até hoje.
    atuais: dict[int, CicloForno] = {}
    for ciclo in (
        CicloForno.objects.filter(
            forno__in=fornos, data_inicio_enchimento__date__lte=hoje
        )
        .exclude(status=StatusCiclo.CANCELADO)
        .order_by("data_inicio_enchimento")
    ):
        atuais[ciclo.forno_id] = ciclo
    producao_pl = [Decimal(0)] * ultimo
    # Plano feito no início do mês (sem o que aconteceu depois), para comparar.
    producao_plano = [Decimal(0)] * ultimo
    ciclos_plano = 0
    contagem_pl = {codigo: [0] * ultimo for codigo, _ in ESTADOS_DO_DIA}

    contagem = {codigo: [0] * ultimo for codigo, _ in ESTADOS_DO_DIA}
    producao_dia = [Decimal(0)] * ultimo
    linhas = []
    upc_anterior = None
    for forno in fornos:
        ciclos_do_forno = ciclos_por_forno[forno.pk]
        estados = [estado_no_dia(ciclos_do_forno, forno, dia, hoje) for dia in dias]
        for indice, estado in enumerate(estados):
            if estado:
                contagem[estado][indice] += 1
        descarregados = [
            ciclo
            for ciclo in ciclos_do_forno
            if ciclo.data_descarga and inicio <= _dia(ciclo.data_descarga) <= fim
        ]
        for ciclo in descarregados:
            producao_dia[_dia(ciclo.data_descarga).day - 1] += ciclo.volume_mdc or 0
        mdc = sum(
            (ciclo.volume_mdc or Decimal(0) for ciclo in descarregados), Decimal(0)
        )
        planejados, producao_forno = planejado_do_forno(
            forno,
            planos.get(forno.pk),
            ultimos_reais.get(forno.pk),
            inicio,
            ultimo,
            atual=atuais.get(forno.pk),
            hoje=hoje,
        )
        plano_inicial, producao_inicial = planejado_do_forno(
            forno, planos.get(forno.pk), ultimos_reais.get(forno.pk), inicio, ultimo
        )
        ciclos_plano += plano_inicial.count("D")
        for indice, valor in enumerate(producao_inicial):
            producao_plano[indice] += valor
        if inicio < hoje <= fim:
            # Mês corrente: o que já passou é o realizado e, de hoje em diante,
            # a previsão. A linha fica contínua (sem emendar o plano antigo).
            passado = (hoje - inicio).days
            planejados[:passado] = estados[:passado]
            producao_forno[:passado] = [Decimal(0)] * passado
            for ciclo in descarregados:
                indice = (_dia(ciclo.data_descarga) - inicio).days
                if indice < passado:
                    producao_forno[indice] += ciclo.volume_mdc or 0
        for indice, estado in enumerate(planejados):
            if estado:
                contagem_pl[estado][indice] += 1
            producao_pl[indice] += producao_forno[indice]
        casas = parametros.casas_decimais_mdc
        linhas.append(
            {
                "forno": forno,
                "nova_upc": forno.upc_id != upc_anterior,
                "estados": estados,
                "planejados": planejados,
                "planejado": forno.pk in planos,
                "ciclos": len(descarregados),
                "mdc": formatar_numero(mdc, parametros, casas),
                "_mdc_real": mdc,
                "ciclos_pl": planejados.count("D"),
                "mdc_pl": formatar_numero(sum(producao_forno), parametros, casas),
            }
        )
        upc_anterior = forno.upc_id
    total_mdc = sum(producao_dia, Decimal(0))
    casas = parametros.casas_decimais_mdc
    return {
        "dias": [
            {"data": dia, "numero": dia.day, "semana": "dstqqss"[dia.isoweekday() % 7]}
            for dia in dias
        ],
        "linhas": linhas,
        "contagem": [
            {"codigo": codigo, "rotulo": rotulo, "por_dia": contagem[codigo]}
            for codigo, rotulo in ESTADOS_DO_DIA
        ],
        "producao_dia": [
            formatar_numero(valor, parametros, casas) if valor else ""
            for valor in producao_dia
        ],
        "varias_upcs": len(upcs) > 1,
        "total_ciclos": sum(linha["ciclos"] for linha in linhas),
        "total_mdc": formatar_numero(total_mdc, parametros, casas),
        "contagem_pl": [
            {"codigo": codigo, "rotulo": rotulo, "por_dia": contagem_pl[codigo]}
            for codigo, rotulo in ESTADOS_DO_DIA
        ],
        "producao_dia_pl": [
            formatar_numero(valor, parametros, casas) if valor else ""
            for valor in producao_pl
        ],
        "total_ciclos_pl": sum(linha["ciclos_pl"] for linha in linhas),
        "total_mdc_pl": formatar_numero(sum(producao_pl), parametros, casas),
        "total_mdc_pl_valor": sum(producao_pl),
        "ritmo": _ritmo_de_producao(
            producao_plano, ciclos_plano, linhas, producao_pl, inicio, hoje, parametros
        ),
        "inicio": inicio,
        "anterior": (inicio - timedelta(days=1)).strftime("%Y-%m"),
        "proximo": (fim + timedelta(days=1)).strftime("%Y-%m"),
    }


def _ritmo_de_producao(
    producao_plano: list[Decimal],
    ciclos_plano: int,
    linhas: list[dict],
    producao_previsao: list[Decimal],
    inicio: date,
    hoje: date,
    parametros: Parametros,
) -> dict:
    """Planejado (início do mês) x real até hoje, e o ritmo em MDC por dia."""
    dias_mes = len(producao_plano)
    # Dias já trabalhados no mês, contando hoje (0 se o mês ainda não começou).
    decorridos = max(0, min((hoje - inicio).days + 1, dias_mes))
    restantes = dias_mes - decorridos
    plano_mes = sum(producao_plano, Decimal(0))
    plano_ate_hoje = sum(producao_plano[:decorridos], Decimal(0))
    real = sum((linha["_mdc_real"] for linha in linhas), Decimal(0))
    ciclos_real = sum(linha["ciclos"] for linha in linhas)
    # Mês encerrado: não há o que prever, o fechamento é o realizado.
    previsao = real if restantes == 0 else sum(producao_previsao, Decimal(0))
    casas = parametros.casas_decimais_mdc

    def mdc(valor: Decimal | None) -> str:
        return "—" if valor is None else formatar_numero(valor, parametros, casas)

    def por_dia(total: Decimal, dias: int) -> Decimal | None:
        return total / dias if dias else None

    necessario = (
        max(plano_mes - real, Decimal(0)) / restantes if restantes else None
    )
    ritmo_real = por_dia(real, decorridos)
    atingido = round(real * 100 / plano_ate_hoje) if plano_ate_hoje else None
    return {
        "dias_mes": dias_mes,
        "decorridos": decorridos,
        "restantes": restantes,
        "plano_mes": mdc(plano_mes),
        "plano_ciclos": ciclos_plano,
        "plano_ate_hoje": mdc(plano_ate_hoje),
        "real": mdc(real),
        "real_ciclos": ciclos_real,
        "previsao": mdc(previsao),
        "previsao_abaixo": previsao < plano_mes,
        "ritmo_plano": mdc(por_dia(plano_mes, dias_mes)),
        "ritmo_real": mdc(ritmo_real),
        "ritmo_necessario": mdc(necessario) if restantes else None,
        "ritmo_abaixo": (
            ritmo_real is not None
            and necessario is not None
            and ritmo_real < necessario
        ),
        "atingido_pct": atingido,
    }


# ---------------------------------------------------------------------------
# Consolidado da colheita por talhão (como a aba CONSOLIDADO COLHEITA)

ETAPAS_FINAIS = (EtapaColheita.TRACAMENTO, EtapaColheita.EMBANDEIRAMENTO)
ETAPAS_DE_CORTE = (EtapaColheita.CORTE_FELLER, EtapaColheita.CORTE_MOTOSSERRA)


def consolidado_da_colheita(
    talhoes: QuerySet, hoje: date, parametros: Parametros
) -> dict:
    casas = parametros.casas_decimais_volume

    def fmt(valor: Decimal | None) -> str:
        return "—" if valor is None else formatar_numero(valor, parametros, casas)

    talhoes = talhoes.select_related("fazenda").order_by(
        "fazenda__nome", "identificacao"
    )
    feitos: dict[int, dict[str, Decimal]] = {}
    inicios: dict[int, date] = {}
    inventarios: dict[int, InventarioFlorestal] = {}
    for linha in (
        Colheita.objects.filter(talhao__in=talhoes)
        .values("talhao_id", "etapa")
        .annotate(volume=Sum("volume_m3"))
    ):
        feitos.setdefault(linha["talhao_id"], {})[linha["etapa"]] = linha[
            "volume"
        ] or Decimal(0)
    for colheita in Colheita.objects.filter(
        talhao__in=talhoes, etapa__in=ETAPAS_DE_CORTE
    ).order_by("data_inicio"):
        if colheita.data_inicio:
            inicios.setdefault(colheita.talhao_id, colheita.data_inicio)
    for colheita in Colheita.objects.filter(talhao__in=talhoes).select_related(
        "inventario"
    ):
        inventarios.setdefault(colheita.talhao_id, colheita.inventario)
    transportado = dict(
        TransporteLenha.objects.filter(talhao__in=talhoes)
        .values_list("talhao_id")
        .annotate(total=Sum("volume_m3"))
    )
    etapas = list(EtapaColheita)
    usadas = [
        etapa for etapa in etapas if any(etapa in f for f in feitos.values())
    ] or etapas[:3]
    linhas = []
    for talhao in talhoes:
        feito = feitos.get(talhao.pk, {})
        ifpc = Colheita.volume_do_talhao(talhao, inventarios.get(talhao.pk))
        if not feito and not transportado.get(talhao.pk) and ifpc is None:
            continue
        levado = transportado.get(talhao.pk) or Decimal(0)
        final = sum(
            (feito.get(etapa, Decimal(0)) for etapa in ETAPAS_FINAIS), Decimal(0)
        )
        disponivel = final - levado
        inicio = inicios.get(talhao.pk)
        linhas.append(
            {
                "talhao": talhao,
                "ifpc": fmt(ifpc),
                "etapas": [
                    {
                        "feito": fmt(feito.get(etapa, Decimal(0))),
                        "saldo": fmt(
                            None
                            if ifpc is None
                            else ifpc - feito.get(etapa, Decimal(0))
                        ),
                    }
                    for etapa in usadas
                ],
                "transportado": fmt(levado),
                "disponivel": fmt(disponivel),
                "negativo": disponivel < 0,
                "inicio_corte": inicio,
                "dias_secagem": (hoje - inicio).days if inicio else None,
            }
        )
    return {"etapas": [etapa.label for etapa in usadas], "linhas": linhas}


# ---------------------------------------------------------------------------
# Desempenho do ciclo: tempos reais x prazos e efeito na produção


def _media(valores: list[float]) -> float | None:
    return sum(valores) / len(valores) if valores else None


def desempenho_do_ciclo(
    fornos: QuerySet[Forno],
    inicio: date,
    fim: date,
    referencias,
    parametros: Parametros,
) -> dict | None:
    """Ciclos descarregados no período: tempos, atrasos, fator e MDC perdido."""
    ciclos = list(
        CicloForno.objects.filter(
            forno__in=fornos,
            status=StatusCiclo.DESCARREGADO,
            data_descarga__date__range=(inicio, fim),
        ).select_related("forno__tipo_forno")
    )
    if not ciclos:
        return None
    proximos: dict[int, list] = {}
    for ciclo in (
        CicloForno.objects.filter(
            forno__in=fornos, data_inicio_enchimento__date__gte=inicio
        )
        .exclude(status=StatusCiclo.CANCELADO)
        .values_list("forno_id", "data_inicio_enchimento")
    ):
        proximos.setdefault(ciclo[0], []).append(ciclo[1])

    def dias(de, ate) -> float:
        return (ate - de).total_seconds() / 86400

    carbonizacao, resfriamento, intervalo = [], [], []
    previsto_carb, previsto_resf, previsto_int = [], [], []
    atraso_carb = atraso_resf = 0
    for ciclo in ciclos:
        tipo = ciclo.forno.tipo_forno
        inicio_carb = ciclo.data_acendimento or ciclo.data_inicio_enchimento
        carb = dias(inicio_carb, ciclo.data_fim_carbonizacao)
        resf = dias(ciclo.data_fim_carbonizacao, ciclo.data_descarga)
        carbonizacao.append(carb)
        resfriamento.append(resf)
        previsto_carb.append(tipo.dias_carbonizacao_previstos)
        previsto_resf.append(tipo.dias_resfriamento_previstos)
        previsto_int.append(tipo.dias_vazio_previstos + 1)
        atraso_carb += carb > tipo.dias_carbonizacao_previstos
        atraso_resf += resf > tipo.dias_resfriamento_previstos
        seguinte = min(
            (
                data
                for data in proximos.get(ciclo.forno_id, [])
                if data > ciclo.data_descarga
            ),
            default=None,
        )
        if seguinte is not None:
            intervalo.append(dias(ciclo.data_descarga, seguinte))

    real = {
        "carb": _media(carbonizacao),
        "resf": _media(resfriamento),
        "int": _media(intervalo),
    }
    previsto = {
        "carb": _media(previsto_carb),
        "resf": _media(previsto_resf),
        "int": _media(previsto_int),
    }
    ciclo_previsto = sum(previsto.values())
    ciclo_real = real["carb"] + real["resf"] + (real["int"] or previsto["int"])
    total = len(ciclos)
    mdc = sum((c.volume_mdc or Decimal(0) for c in ciclos), Decimal(0))
    lenha_mst = sum((c.volume_lenha_enchimento for c in ciclos), Decimal(0))
    lenha_m3 = sum((c.volume_lenha_m3 for c in ciclos), Decimal(0))
    mdc_medio = mdc / total
    # Capacidade do período com o ciclo previsto e com o ciclo real.
    fornos_ativos = fornos.exclude(situacao=SituacaoForno.DESATIVADO).count()
    dias_periodo = (fim - inicio).days + 1
    perda = None
    if ciclo_real > ciclo_previsto > 0:
        ciclos_perdidos = (
            fornos_ativos * dias_periodo * (1 / ciclo_previsto - 1 / ciclo_real)
        )
        perda = Decimal(str(ciclos_perdidos)) * mdc_medio

    def fmt_dias(valor: float | None) -> str:
        return (
            "—"
            if valor is None
            else formatar_numero(Decimal(str(valor)), parametros, 1)
        )

    def fator(valor: Decimal) -> str:
        return formatar_numero(valor, parametros, 2)

    etapas = []
    for chave, rotulo in (
        ("carb", "Carbonização"),
        ("resf", "Resfriamento"),
        ("int", "Descarga → novo enchimento"),
    ):
        diferenca = None if real[chave] is None else real[chave] - previsto[chave]
        etapas.append(
            {
                "rotulo": rotulo,
                "real": fmt_dias(real[chave]),
                "previsto": fmt_dias(previsto[chave]),
                "diferenca": fmt_dias(diferenca),
                "acima": diferenca is not None and diferenca > 0.25,
            }
        )
    mst_mdc, m3_mdc = lenha_mst / mdc, lenha_m3 / mdc
    return {
        "ciclos": total,
        "etapas": etapas,
        "ciclo_real": fmt_dias(ciclo_real),
        "ciclo_previsto": fmt_dias(ciclo_previsto),
        "atraso_carb_pct": round(atraso_carb * 100 / total),
        "atraso_resf_pct": round(atraso_resf * 100 / total),
        "mdc_medio": formatar_numero(
            mdc_medio, parametros, parametros.casas_decimais_mdc
        ),
        "perda_mdc": (
            formatar_numero(perda, parametros, parametros.casas_decimais_mdc)
            if perda
            else None
        ),
        "fatores": [
            {
                "rotulo": "MST por MDC",
                "real": fator(mst_mdc),
                "referencia": fator(referencias.fator_mst_por_mdc_ideal),
                "acima": mst_mdc > referencias.fator_mst_por_mdc_ideal,
            },
            {
                "rotulo": "m³ por MDC",
                "real": fator(m3_mdc),
                "referencia": fator(referencias.fator_m3_por_mdc_ideal),
                "acima": m3_mdc > referencias.fator_m3_por_mdc_ideal,
            },
        ],
        "fator_mst_m3": fator(referencias.fator_mst_por_m3),
    }
