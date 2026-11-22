"""The Odds API: cuotas de casas 'afiladas' (Pinnacle, Betfair...) para 1X2 y goles.
/events es gratis; /odds cuesta (mercados x regiones) créditos por liga."""
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.the-odds-api.com/v4"


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OddsAPI:
    def __init__(self, clave: str):
        self.clave = clave
        self.restantes = None

    @property
    def activa(self):
        return bool(self.clave)

    def _get(self, ruta, **params):
        params["apiKey"] = self.clave
        r = requests.get(API + ruta, params=params, timeout=30)
        if r.status_code in (401, 422, 429):
            print(f"  ! The Odds API {ruta}: {r.status_code}")
            return []
        r.raise_for_status()
        self.restantes = r.headers.get("x-requests-remaining", self.restantes)
        return r.json()

    def deportes(self):
        return self._get("/sports", all="true")

    def cuotas(self, liga: str, horas: int) -> list[dict]:
        """Lista de {local, visita, inicio, casas: {casa: {clave: cuota}}}."""
        if not self.activa:
            return []
        ahora = datetime.now(timezone.utc)
        rango = dict(commenceTimeFrom=_iso(ahora), commenceTimeTo=_iso(ahora + timedelta(hours=horas)))
        if not self._get(f"/sports/{liga}/events", **rango):
            return []
        salida = []
        for ev in self._get(f"/sports/{liga}/odds", regions="eu", markets="h2h,totals",
                            oddsFormat="decimal", **rango):
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
        return salida
