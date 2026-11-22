"""Descripción SEGURA de excepciones para logs y JSON públicos.

El texto de una excepción de `requests` incluye la URL completa (con `?token=`/`?apiKey=` o `/bot<TOKEN>/`):
nunca se imprime ni se publica. Solo la clase y, si es un error HTTP, el código de estado."""


def describir(e: BaseException) -> str:
    nombre = e.__class__.__name__
    codigo = getattr(getattr(e, "response", None), "status_code", None)
    return f"{nombre} HTTP {codigo}" if isinstance(codigo, int) else nombre
