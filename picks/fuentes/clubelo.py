"""ClubElo (http://clubelo.com/API): ratings Elo públicos y gratuitos (sin clave), sobre todo de Europa.

Fuente estadística INDEPENDIENTE de los modelos de goles: el Elo sale de resultados históricos de cada club,
no de los datos de goles/córners/tarjetas de football-data. Solo opina de 1X2, doble oportunidad y DNB.

Formato (según la documentación pública; NO verificado en vivo al escribir esto): `GET http://api.clubelo.com/YYYY-MM-DD`
devuelve un CSV `Rank,Club,Country,Level,Elo,From,To` con todos los clubes en esa fecha. `Rank` puede ser "None".
Los nombres de club van sin espacios ("ManCity", "RealMadrid") o abreviados ("Man City", "Inter", "Bayern"),
por eso el emparejamiento compara los nombres normalizados y sin espacios.
Nunca lanza: si algo falla devuelve {} y el pipeline sigue sin la fuente "elo".
"""
import csv
import io
import json
import math
import re
import unicodedata
import time
from datetime import date

from .. import names
from ..config import DATOS
from ..errores import describir
from .apifootball import peticion_con_reintentos

URLS = ("https://api.clubelo.com/{fecha}",)   # solo https: si falla, sin fuente elo (y sin caché)
URL = URLS[0]                # compat
MIN_CLUBES = 100             # un CSV con menos clubes se considera roto/parcial y se descarta entero
ELO_MIN, ELO_MAX = 800.0, 2300.0   # fuera de este rango algo está mal en la fuente: se descarta entera
P_EMPATE_MIN = 0.12        # el empate nunca baja de esto (el Elo no modela bien el empate en extremos)
P_VICTORIA_MAX = 0.97      # ninguna victoria pasa de esto (el Elo extrapola mal con diferencias enormes)
# Sufijos geográficos/de club ambiguos: "Barcelona SC" (Ecuador) != "Barcelona", "Atletico-MG" != "Atletico (Madrid)".
# Un nombre que termina en uno de ellos NO se empareja con ClubElo por el resto del nombre.
SUFIJOS_AMBIGUOS = {"sc", "mg", "rj", "sp", "ec", "se", "ca"}
VENTAJA_LOCAL = 65.0       # puntos Elo de ventaja por jugar de local
P_EMPATE_MAX = 0.26        # prob. de empate entre equipos parejos (decrece con |dElo|)
_FALLOS: dict = {}         # (cache_dir, fecha) -> instante del último fallo: no insistir en la misma corrida
_ESPERA_FALLO = 900        # s

# Alias manuales: nombre normalizado y sin espacios (como lo escriben otras fuentes) -> el de ClubElo.
# Se aplica DESPUÉS de names.normalizar (que ya traduce "manchester city" -> "man city", "inter milan" -> "inter"...).
# OJO: los nombres de ClubElo del lado derecho ("koeln", "hamburg", "mainz", "verona", "brest", "betis", "alaves"...)
# son SUPOSICIONES basadas en la documentación/recuerdo del formato; el servidor devolvió 502 y no se pudieron verificar.
ALIAS_ELO = {
    "athletic": "bilbao", "1koln": "koeln", "koln": "koeln", "1heidenheim": "heidenheim", "hamburgersv": "hamburg",
    "fsvmainz05": "mainz", "mainz05": "mainz", "deportivoalaves": "alaves", "realbetis": "betis",
    "hellasverona": "verona", "stadebrestois29": "brest", "brestois": "brest", "stadebrestois": "brest",
    "bayer04leverkusen": "leverkusen", "borussiamonchengladbach": "gladbach", "1fckoln": "koeln", "rayovallecano": "rayo",
    "internazionale": "inter", "bayernmunich": "bayern", "bayernmunchen": "bayern", "athmadrid": "atletico",
    "atleticomadrid": "atletico", "athbilbao": "bilbao", "athleticclub": "bilbao", "sociedad": "sociedad",
    "nott'mforest": "forest", "nottinghamforest": "forest", "leverkusen": "leverkusen", "mgladbach": "gladbach",
    "m'gladbach": "gladbach", "einfrankfurt": "frankfurt", "parissg": "parissg", "psg": "parissg",
    "rbleipzig": "leipzig", "rasenballsportleipzig": "leipzig", "vallecano": "rayo", "espanol": "espanyol",
    "manutd": "manunited", "spurs": "tottenham", "wolverhamptonwanderers": "wolves",
}


def _compacto(nombre: str) -> str:
    return names.normalizar(nombre).replace(" ", "")


def _sufijo_ambiguo(nombre: str) -> bool:
    """True si el nombre crudo termina en un sufijo ambiguo (sc, mg, rj, sp, ec, se, ca): no se empareja."""
    t = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    toks = re.findall(r"[a-z0-9']+", t)
    return len(toks) > 1 and toks[-1] in SUFIJOS_AMBIGUOS


def parsear_csv(texto: str) -> dict[str, float]:
    """CSV de ClubElo -> {club: elo}. Ignora filas rotas (Elo no numérico) y respuestas que no son CSV."""
    out: dict[str, float] = {}
    try:
        for fila in csv.DictReader(io.StringIO(texto or "")):
            club, elo = (fila.get("Club") or "").strip(), fila.get("Elo")
            if not club or elo is None:
                continue
            try:
                v = float(elo)
            except ValueError:
                continue
            if v == v and 0 < v < 4000:
                out[club] = v
    except (csv.Error, AttributeError):
        return {}
    return out


def buscar_elo(nombre: str, ratings: dict[str, float]) -> float | None:
    """Elo del equipo `nombre` (como lo llama API-Football) o None. Solo coincidencias exactas tras normalizar
    (más alias): prefiere no tener fuente a emparejar un club equivocado. Nombres ambiguos -> None."""
    if not nombre or not ratings or _sufijo_ambiguo(nombre):
        return None
    mapa: dict[str, float | None] = {}
    for club, elo in ratings.items():
        k = _compacto(club)
        mapa[k] = None if k in mapa else elo      # dos clubes con la misma clave: ambiguo
    k = _compacto(nombre)
    for clave in (k, ALIAS_ELO.get(k)):
        if clave and mapa.get(clave) is not None:
            return mapa[clave]
    return None


def probs_desde_elo(elo_local: float, elo_visita: float, ventaja: float = VENTAJA_LOCAL,
                    p_empate_max: float = P_EMPATE_MAX) -> dict[str, float]:
    """Elo -> 1X2, doble oportunidad y DNB. p_local_sin_empate = 1/(1+10^(-d/400)) con d = dElo + ventaja local;
    p(empate) = p_empate_max * exp(-(d/400)^2); el resto se reparte según p_local_sin_empate (suma exacta 1)."""
    try:
        d = float(elo_local) + float(ventaja) - float(elo_visita)
        if not math.isfinite(d):
            return {}
        pl = 1.0 / (1.0 + 10 ** (-d / 400.0))
    except (TypeError, ValueError, OverflowError):
        return {}
    pe = max(P_EMPATE_MIN, min(max(p_empate_max, 0.0), 0.5) * math.exp(-((d / 400.0) ** 2)))
    pe = min(pe, 0.5)
    p1, p2 = (1 - pe) * pl, (1 - pe) * (1 - pl)
    # Con pe >= P_EMPATE_MIN la victoria máxima es (1 - 0.12) = 0.88 < P_VICTORIA_MAX; el tope queda como red de
    # seguridad por si se cambian las constantes: el excedente pasa al empate (la suma sigue siendo 1).
    if max(p1, p2) > P_VICTORIA_MAX:
        pe += max(p1, p2) - P_VICTORIA_MAX
        p1, p2 = ((P_VICTORIA_MAX, 1 - pe - P_VICTORIA_MAX) if p1 >= p2 else (1 - pe - P_VICTORIA_MAX, P_VICTORIA_MAX))
    return {"1x2:1": p1, "1x2:X": pe, "1x2:2": p2,
            "dc:1X": p1 + pe, "dc:12": p1 + p2, "dc:X2": pe + p2,
            "dnb:1": pl, "dnb:2": 1 - pl}


def descargar(fecha: date, cache_dir=None, get=None) -> dict[str, float]:
    """{club: elo} de `fecha`, con caché diaria en datos/cache/. Tolerante a fallos: nunca lanza (devuelve {}).
    `get`: función (url, **kw) -> respuesta con .status_code/.text o None (inyectable en pruebas)."""
    try:
        cache_dir = cache_dir or (DATOS / "cache")
        from pathlib import Path
        cache = Path(cache_dir) / f"clubelo_{fecha}.json"
        if cache.exists():
            try:
                datos = json.loads(cache.read_text(encoding="utf-8"))
                if datos:
                    return {str(k): float(v) for k, v in datos.items()}
            except (ValueError, OSError):
                pass
        clave = (str(cache_dir), str(fecha))
        if time.time() - _FALLOS.get(clave, 0) < _ESPERA_FALLO:
            return {}
        get = get or (lambda url, **kw: peticion_con_reintentos(url, reintentos=1, timeout=20, etiqueta="ClubElo", **kw))
        ratings = {}
        for plantilla in URLS:    # solo https
            r = get(plantilla.format(fecha=fecha), headers={"User-Agent": "picks-ecuabet/1.0"})
            ratings = parsear_csv(r.text) if r is not None and getattr(r, "status_code", 200) == 200 else {}
            if ratings:
                break
        if ratings and (len(ratings) < MIN_CLUBES or not all(ELO_MIN <= v <= ELO_MAX for v in ratings.values())):
            print(f"  ! ClubElo: CSV sospechoso ({len(ratings)} clubes o Elo fuera de {ELO_MIN:.0f}-{ELO_MAX:.0f}): fuente descartada")
            ratings = {}
        if not ratings:
            _FALLOS[clave] = time.time()
            return {}
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(ratings), encoding="utf-8")
        except OSError:
            pass
        return ratings
    except Exception as e:  # noqa: BLE001
        print(f"  ! ClubElo: {describir(e)}")
        return {}
