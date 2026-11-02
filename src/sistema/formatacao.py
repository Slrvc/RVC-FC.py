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
