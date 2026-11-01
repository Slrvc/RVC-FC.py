from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sistema.models import Cidade, CodigoIBGE, Estado

if TYPE_CHECKING:
    from pathlib import Path

NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _valores_sql(statement: str) -> list[list[str]]:
    _, separator, content = statement.partition("VALUES")
    if not separator:
        message = "O documento contém um INSERT sem a cláusula VALUES."
        raise CommandError(message)

    registros: list[list[str]] = []
    index = 0
    while index < len(content):
        if content[index] != "(":
            index += 1
            continue

        index += 1
        campos: list[str] = []
        campo: list[str] = []
        quoted = False
        while index < len(content):
            char = content[index]
            if char == "\\" and quoted and index + 1 < len(content):
                campo.append(content[index + 1])
                index += 2
                continue
            if char == "'":
                if quoted and index + 1 < len(content) and content[index + 1] == "'":
                    campo.append("'")
                    index += 2
                    continue
                quoted = not quoted
            elif not quoted and char == ",":
                campos.append("".join(campo).strip())
                campo.clear()
            elif not quoted and char == ")":
                campos.append("".join(campo).strip())
                registros.append(campos)
                index += 1
                break
            else:
                campo.append(char)
            index += 1
        else:
            message = "O documento contém uma linha SQL incompleta."
            raise CommandError(message)
    return registros


def _ler_tabelas(documento: Path) -> dict[str, list[list[str]]]:
    try:
        with ZipFile(documento) as arquivo:
            conteudo = arquivo.read("word/document.xml")
        if b"<!DOCTYPE" in conteudo.upper() or b"<!ENTITY" in conteudo.upper():
            message = "O DOCX não pode conter declarações XML de entidades."
            raise CommandError(message)
        # Rejeitar DTDs e entidades antes de analisar o XML do DOCX.
        xml = ET.fromstring(conteudo)  # noqa: S314
    except (BadZipFile, ET.ParseError, KeyError) as exc:
        message = f"Não foi possível ler o DOCX: {documento}"
        raise CommandError(message) from exc

    textos = [
        "".join(no.text or "" for no in paragrafo.findall(".//w:t", NAMESPACE))
        for paragrafo in xml.findall(".//w:p", NAMESPACE)
    ]
    tabelas: dict[str, list[list[str]]] = {}
    for nome, quantidade_campos in (
        ("estados", 2),
        ("cidades", 3),
        ("codigo_ibge", 12),
    ):
        insercoes = [
            texto for texto in textos if texto.startswith(f"INSERT INTO `{nome}`")
        ]
        if not insercoes:
            message = f"O DOCX não contém dados da tabela {nome}."
            raise CommandError(message)
        linhas = [linha for insercao in insercoes for linha in _valores_sql(insercao)]
        if any(len(linha) != quantidade_campos for linha in linhas):
            message = f"Há registros inválidos na tabela {nome} do DOCX."
            raise CommandError(message)
        tabelas[nome] = linhas
    return tabelas


class Command(BaseCommand):
    help = "Importa estados, cidades e códigos IBGE descritos no DOCX do projeto."

    def handle(self, *args: object, **options: object) -> None:
        documento = settings.BASE_DIR.parent / "Tabeslas siatema.docx"
        if not documento.is_file():
            message = f"Documento não encontrado: {documento}"
            raise CommandError(message)
        tabelas = _ler_tabelas(documento)

        with transaction.atomic():
            estados_antes = Estado.objects.count()
            cidades_antes = Cidade.objects.count()
            codigos_antes = CodigoIBGE.objects.count()
            Estado.objects.bulk_create(
                [
                    Estado(codigo=int(codigo), uf=uf)
                    for codigo, uf in tabelas["estados"]
                ],
                ignore_conflicts=True,
                batch_size=1000,
            )
            Cidade.objects.bulk_create(
                [
                    Cidade(
                        codigo=int(codigo),
                        estado_id=int(estado),
                        cidade=nome,
                    )
                    for codigo, estado, nome in tabelas["cidades"]
                ],
                ignore_conflicts=True,
                batch_size=1000,
            )
            CodigoIBGE.objects.bulk_create(
                [
                    CodigoIBGE(
                        empresa=empresa,
                        codigo_estado=int(codigo_estado),
                        uf=uf,
                        nome_uf=nome_uf,
                        codigo_cidade=codigo_cidade,
                        nome_cidade=nome_cidade,
                        situacao_registro=situacao,
                        status_registro=status,
                    )
                    for (
                        empresa,
                        codigo_estado,
                        uf,
                        nome_uf,
                        codigo_cidade,
                        nome_cidade,
                        _data_inclusao,
                        _data_alteracao,
                        _usuario_inclusao,
                        _usuario_alteracao,
                        situacao,
                        status,
                    ) in tabelas["codigo_ibge"]
                ],
                ignore_conflicts=True,
                batch_size=1000,
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Localidades importadas: "
                f"{Estado.objects.count() - estados_antes} estados, "
                f"{Cidade.objects.count() - cidades_antes} cidades e "
                f"{CodigoIBGE.objects.count() - codigos_antes} códigos IBGE."
            )
        )
