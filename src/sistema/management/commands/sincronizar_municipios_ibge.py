from __future__ import annotations

import json
import zlib
from gzip import decompress as decompress_gzip
from http.client import HTTPException
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sistema.models import Estado, Municipio

API_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?orderBy=nome"
MINIMO_MUNICIPIOS = 5000


def _normalizar_municipios(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list) or len(payload) < MINIMO_MUNICIPIOS:
        message = "A API do IBGE não retornou a lista completa de municípios."
        raise CommandError(message)

    municipios: list[dict[str, object]] = []
    codigos: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            message = "A API do IBGE retornou um município inválido."
            raise CommandError(message)
        hierarquia = item.get("microrregiao")
        mesorregiao = (
            hierarquia.get("mesorregiao") if isinstance(hierarquia, dict) else None
        )
        uf = mesorregiao.get("UF") if isinstance(mesorregiao, dict) else None
        if not isinstance(uf, dict):
            regiao_imediata = item.get("regiao-imediata")
            regiao_intermediaria = (
                regiao_imediata.get("regiao-intermediaria")
                if isinstance(regiao_imediata, dict)
                else None
            )
            uf = (
                regiao_intermediaria.get("UF")
                if isinstance(regiao_intermediaria, dict)
                else None
            )
        if not isinstance(uf, dict):
            message = "A resposta do IBGE não contém a UF do município."
            raise CommandError(message)

        codigo = str(item.get("id", ""))
        nome = item.get("nome")
        codigo_estado = uf.get("id")
        sigla = uf.get("sigla")
        nome_estado = uf.get("nome")
        if (
            len(codigo) != 7
            or not codigo.isdecimal()
            or not isinstance(nome, str)
            or not nome
            or not isinstance(codigo_estado, int)
            or not isinstance(sigla, str)
            or len(sigla) != 2
            or not isinstance(nome_estado, str)
            or not nome_estado
        ):
            message = "A API do IBGE retornou dados inválidos de município."
            raise CommandError(message)
        if codigo in codigos:
            message = f"A API do IBGE repetiu o código municipal {codigo}."
            raise CommandError(message)
        codigos.add(codigo)
        municipios.append(
            {
                "codigo": codigo,
                "nome": nome,
                "codigo_estado": codigo_estado,
                "uf": sigla,
                "nome_estado": nome_estado,
            }
        )
    return municipios


def _buscar_municipios() -> list[dict[str, object]]:
    request = Request(API_URL, headers={"Accept": "application/json"})
    try:
        # O endereço é uma constante HTTPS da API oficial do IBGE.
        with urlopen(request, timeout=30) as resposta:  # noqa: S310
            conteudo = resposta.read()
        if conteudo.startswith(b"\x1f\x8b"):
            conteudo = decompress_gzip(conteudo)
        payload: object = json.loads(conteudo)
    except (
        URLError,
        HTTPException,
        TimeoutError,
        OSError,
        EOFError,
        zlib.error,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        message = f"Não foi possível consultar a API do IBGE: {exc}"
        raise CommandError(message) from exc
    return _normalizar_municipios(payload)


def _reconciliar_estado(codigo: int, uf: str, nome: str) -> Estado:
    """Garante o Estado com o código IBGE, migrando registros legados da mesma UF."""
    legado = Estado.objects.filter(uf=uf).exclude(codigo=codigo).first()
    if legado is not None:
        # Libera a UF (única) para criar o estado com o código oficial.
        legado.uf = f"{legado.codigo:02d}"[-2:]
        legado.save(update_fields=["uf"])
    estado, _ = Estado.objects.update_or_create(
        codigo=codigo, defaults={"uf": uf, "nome": nome}
    )
    if legado is not None:
        Municipio.objects.filter(estado=legado).update(estado=estado)
        legado.delete()
    return estado


class Command(BaseCommand):
    help = "Sincroniza estados e municípios com códigos oficiais da API do IBGE."

    def handle(self, *args: object, **options: object) -> None:
        municipios = _buscar_municipios()
        estados: dict[int, Estado] = {}
        with transaction.atomic():
            Municipio.objects.update(ativo=False)
            for municipio in municipios:
                codigo_estado = int(municipio["codigo_estado"])
                if codigo_estado not in estados:
                    estados[codigo_estado] = _reconciliar_estado(
                        codigo_estado,
                        str(municipio["uf"]),
                        str(municipio["nome_estado"]),
                    )

            for municipio in municipios:
                Municipio.objects.update_or_create(
                    codigo=str(municipio["codigo"]),
                    defaults={
                        "nome": str(municipio["nome"]),
                        "ativo": True,
                        "estado": estados[int(municipio["codigo_estado"])],
                    },
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(estados)} estados e {len(municipios)} municípios "
                "sincronizados com o IBGE."
            )
        )
