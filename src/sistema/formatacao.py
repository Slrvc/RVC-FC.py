import re


def somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def formatar_cnpj(digitos: str) -> str:
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def formatar_cpf(digitos: str) -> str:
    return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"


def formatar_cep(digitos: str) -> str:
    return f"{digitos[:5]}-{digitos[5:]}"


def formatar_telefone(digitos: str) -> str:
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"


def normalizar(tipo: str, valor: str) -> str:
    """Devolve o valor formatado; levanta ValueError se o tamanho for inválido."""
    digitos = somente_digitos(valor)
    if not digitos:
        return ""
    if tipo == "cnpj" and len(digitos) == 14:
        return formatar_cnpj(digitos)
    if tipo == "cpf_cnpj" and len(digitos) == 11:
        return formatar_cpf(digitos)
    if tipo == "cpf_cnpj" and len(digitos) == 14:
        return formatar_cnpj(digitos)
    if tipo == "cep" and len(digitos) == 8:
        return formatar_cep(digitos)
    if tipo == "telefone" and len(digitos) in (10, 11):
        return formatar_telefone(digitos)
    raise ValueError(tipo)


MASCARAS_POR_CAMPO = {
    "cnpj": "cnpj",
    "cpf_cnpj": "cpf_cnpj",
    "cep": "cep",
    "telefone": "telefone",
    "celular": "telefone",
}

MENSAGENS = {
    "cnpj": "Informe um CNPJ com 14 dígitos.",
    "cpf_cnpj": "Informe um CPF (11 dígitos) ou CNPJ (14 dígitos).",
    "cep": "Informe um CEP com 8 dígitos.",
    "telefone": "Informe o telefone com DDD (10 ou 11 dígitos).",
}


# ---------------------------------------------------------------------------
# Exibição de números e datas conforme os Parâmetros do sistema.

_TOKENS_DATA = (("yyyy", "%Y"), ("yy", "%y"), ("dd", "%d"), ("mm", "%m"))
_TOKENS_HORA = (("hh", "%H"), ("mm", "%M"), ("ss", "%S"))


def _padrao_strftime(formato: str, tokens: tuple[tuple[str, str], ...]) -> str:
    resultado, posicao = "", 0
    texto = formato.lower()
    while posicao < len(texto):
        for token, codigo in tokens:
            if texto.startswith(token, posicao):
                resultado += codigo
                posicao += len(token)
                break
        else:
            resultado += formato[posicao]
            posicao += 1
    return resultado


def formatar_data(valor, parametros) -> str:
    return valor.strftime(
        _padrao_strftime(parametros.formato_data or "dd/mm/yyyy", _TOKENS_DATA)
    )


def formatar_data_hora(valor, parametros) -> str:
    hora = _padrao_strftime(parametros.formato_hora or "hh:mm", _TOKENS_HORA)
    return f"{formatar_data(valor, parametros)} {valor.strftime(hora)}"


def casas_do_campo(nome: str, parametros) -> int | None:
    """Casas decimais pelo nome do campo; None mantém as do próprio valor."""
    nome = nome.lower()
    if "valor" in nome or "custo" in nome or "preco" in nome:
        return parametros.casas_decimais_valor
    if "pct" in nome or "percent" in nome or "tolerancia" in nome:
        return parametros.casas_decimais_porcentagem
    if "fator" in nome:
        return None
    if "peso" in nome or nome.endswith("_kg"):
        return parametros.casas_decimais_peso
    if "mdc" in nome or "capacidade" in nome:
        return parametros.casas_decimais_mdc
    if "volume" in nome or "m3" in nome or "mst" in nome or "estoque" in nome:
        return parametros.casas_decimais_volume
    if "area" in nome or nome.endswith("_ha"):
        return parametros.casas_decimais_ha
    return None


def formatar_numero(valor, parametros, casas: int | None = None) -> str:
    from decimal import ROUND_HALF_UP, Decimal

    numero = Decimal(valor)
    if casas is None:
        expoente = numero.normalize().as_tuple().exponent
        casas = max(0, -expoente) if isinstance(expoente, int) else 0
    numero = numero.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    texto = f"{numero:,.{casas}f}"
    milhar = parametros.separador_milhar or ""
    decimal = parametros.separador_decimal or ","
    return texto.replace(",", "\0").replace(".", decimal).replace("\0", milhar)
