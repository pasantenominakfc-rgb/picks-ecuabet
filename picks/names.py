"""Empareja nombres de equipos entre fuentes (The Odds API vs football-data)."""
import difflib
import re
import unicodedata

# Alias conocidos: nombre en The Odds API -> nombre en football-data
ALIAS = {
    "manchester united": "man united",
    "manchester city": "man city",
    "newcastle united": "newcastle",
    "nottingham forest": "nott'm forest",
    "wolverhampton wanderers": "wolves",
    "tottenham hotspur": "tottenham",
    "brighton and hove albion": "brighton",
    "west ham united": "west ham",
    "leeds united": "leeds",
    "atletico madrid": "ath madrid",
    "athletic bilbao": "ath bilbao",
    "real sociedad": "sociedad",
    "rayo vallecano": "vallecano",
    "celta vigo": "celta",
    "espanyol": "espanol",
    "alaves": "alaves",
    "inter milan": "inter",
    "ac milan": "milan",
    "as roma": "roma",
    "bayern munich": "bayern munich",
    "borussia dortmund": "dortmund",
    "borussia monchengladbach": "m'gladbach",
    "bayer leverkusen": "leverkusen",
    "eintracht frankfurt": "ein frankfurt",
    "vfb stuttgart": "stuttgart",
    "fc st. pauli": "st pauli",
    "1. fc heidenheim": "heidenheim",
    "paris saint germain": "paris sg",
    "paris saint-germain": "paris sg",
    "olympique marseille": "marseille",
    "olympique lyonnais": "lyon",
    "as monaco": "monaco",
    "stade rennais": "rennes",
}

_RUIDO = re.compile(r"\b(fc|cf|sc|ac|afc|cd|ca|club|de|the|se|ec|fbpa|rj|sp|mg)\b")


def normalizar(nombre: str) -> str:
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    s = s.replace("-", " ").replace(".", " ")
    s = ALIAS.get(s.strip(), s)
    s = _RUIDO.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def similitud(a: str, b: str) -> float:
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if (na in nb or nb in na) and min(len(na), len(nb)) >= 4:
        return 0.9
    return difflib.SequenceMatcher(None, na, nb).ratio()


def emparejar_partido(local: str, visita: str, filas: list[dict]) -> dict | None:
    """Busca en `filas` (con claves 'local' y 'visita') el mismo partido."""
    mejor, puntaje = None, 0.0
    for f in filas:
        a, b = similitud(local, f["local"]), similitud(visita, f["visita"])
        if (a >= 0.6 and b >= 0.6) or (max(a, b) >= 0.9 and min(a, b) >= 0.45):
            if a + b > puntaje:
                mejor, puntaje = f, a + b
    return mejor


def emparejar(nombre: str, candidatos: list[str], corte: float = 0.72) -> str | None:
    """Devuelve el candidato de football-data que corresponde a `nombre`, o None."""
    clave = ALIAS.get(nombre.lower(), nombre)
    mapa = {normalizar(c): c for c in candidatos}
    n = normalizar(clave)
    if n in mapa:
        return mapa[n]
    # contenido (ej. "flamengo" dentro de "flamengo rj")
    for k, v in mapa.items():
        if n and (n in k or k in n) and min(len(n), len(k)) >= 4:
            return v
    match = difflib.get_close_matches(n, list(mapa), n=1, cutoff=corte)
    return mapa[match[0]] if match else None
