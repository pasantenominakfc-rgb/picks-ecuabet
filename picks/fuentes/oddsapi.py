"""The Odds API: cuotas de casas 'afiladas' (Pinnacle, Betfair...) para 1X2 y goles.
/events es gratis; /odds cuesta (mercados x regiones) créditos por liga."""
import json
import re
import time
from datetime import datetime, timedelta, timezone

from ..config import DATOS
from .apifootball import peticion_con_reintentos

API = "https://api.the-odds-api.com/v4"


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


CACHE_HORAS = 12         # una corrida repetida no vuelve a gastar créditos (2 corridas/día: la 2.ª lee de caché)
MAX_LLAMADAS_CORRIDA = 4  # 2 corridas/día x 4 llamadas x ~2 créditos x 30 días ~ 480 créditos/mes (plan gratis: 500)
RESERVA = 5              # no se llama con menos de estos créditos restantes (plan gratis: 500/mes)


def tope_corrida(cfg: dict) -> int:
    """Tope de ligas por corrida desde la config: `odds_max_llamadas_corrida`; acepta el nombre viejo
    `odds_max_llamadas_dia` (compatibilidad); por defecto 4."""
    v = cfg.get("odds_max_llamadas_corrida", cfg.get("odds_max_llamadas_dia", MAX_LLAMADAS_CORRIDA))
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return MAX_LLAMADAS_CORRIDA


class OddsAPI:
    def __init__(self, clave: str, sleep=time.sleep, max_llamadas: int = MAX_LLAMADAS_CORRIDA):
        """max_llamadas: tope de ligas consultadas (/odds) por corrida (config: odds_max_llamadas_corrida).
        Cada liga cuesta ~2 créditos (h2h + totals x 1 región): 2 corridas/día x 4 llamadas x ~2 créditos x 30 días
        ~ 480 créditos/mes."""
        self.clave = clave
        self.restantes = None
        self.sleep = sleep
        self.max_llamadas = max_llamadas
        self.llamadas = 0

    @property
    def activa(self):
        return bool(self.clave)

    def _get(self, ruta, **params):
        """Nunca lanza por fallos HTTP/red: reintenta y degrada a [] (sin caché).
        SEGURIDAD: `apiKey` viaja en la query string; NUNCA imprimir `params`, la URL ni el texto de una excepción
        de requests (incluyen la clave). Los logs solo llevan la etiqueta de la ruta y el código HTTP."""
        params["apiKey"] = self.clave
        r = peticion_con_reintentos(API + ruta, params, None, self.sleep, etiqueta=f"The Odds API {ruta}")
        if r is None:
            return []
        self.restantes = r.headers.get("x-requests-remaining", self.restantes)
        try:
            return r.json()
        except ValueError:
            return []

    def deportes(self):
        return self._get("/sports", all="true")

    def cuotas(self, liga: str, horas: int) -> list[dict]:
        """Lista de {local, visita, inicio, casas: {casa: {clave: cuota}}}."""
        if not self.activa:
            return []
        cache = DATOS / "cache" / ("odds_" + re.sub(r"\W+", "_", f"{liga}_{horas}") + ".json")
        if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_HORAS * 3600:
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        if self.llamadas >= self.max_llamadas:
            return []
        if self.restantes is not None:
            try:
                if int(float(self.restantes)) <= RESERVA:
                    return []
            except ValueError:
                pass
        ahora = datetime.now(timezone.utc)
        rango = dict(commenceTimeFrom=_iso(ahora), commenceTimeTo=_iso(ahora + timedelta(hours=horas)))
        eventos = self._get(f"/sports/{liga}/events", **rango)
        if not isinstance(eventos, list) or not eventos:
            return []
        salida = []
        evs = self._get(f"/sports/{liga}/odds", regions="eu", markets="h2h,totals",
                        oddsFormat="decimal", **rango)
        if not isinstance(evs, list):
            return []          # respuesta de error: no se cuenta como llamada ni se cachea
        self.llamadas += 1
        print(f"  The Odds API: llamada {self.llamadas}/{self.max_llamadas} ({liga}); créditos restantes: {self.restantes}")
        for ev in evs:
            casas = {}
            for b in ev.get("bookmakers", []):
                c = casas.setdefault(b["key"], {})
                for m in b.get("markets", []):
                    for o in m["outcomes"]:
                        if m["key"] == "h2h":
                            k = "1x2:1" if o["name"] == ev["home_team"] else \
                                "1x2:2" if o["name"] == ev["away_team"] else "1x2:X"
                        elif m["key"] == "totals" and float(o.get("point", 0)) % 1 == 0.5:
                            k = f"ou:{float(o['point'])}:{o['name'].lower()}"
                        else:
                            continue
                        c[k] = o["price"]
            salida.append({"local": ev["home_team"], "visita": ev["away_team"],
                           "inicio": ev["commence_time"], "casas": casas})
        if salida:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(salida), encoding="utf-8")
            except OSError:
                pass
        return salida
