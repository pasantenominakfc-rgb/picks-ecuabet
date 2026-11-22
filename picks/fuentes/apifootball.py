"""API-Football (api-sports.io): partidos, cuotas de muchos mercados, predicciones,
estadísticas (córners/tarjetas) y resultados. Plan gratis: 100 consultas/día."""
import json
import re
import time

import pandas as pd
import requests

from ..config import DATOS

BASE = "https://v3.football.api-sports.io"


def _linea(txt: str) -> float | None:
    m = re.search(r"([+-]?\d+(?:\.\d+)?)", txt)
    return float(m.group(1)) if m else None


def _media(ln: float | None) -> bool:
    return ln is not None and abs(ln * 2 % 2 - 1) < 1e-9  # solo líneas .5 (sin devolución)


def clave_apuesta(bet: str, valor: str) -> str | None:
    """Traduce (nombre de apuesta, valor) de API-Football a una clave de picks.mercados."""
    b, v = bet.strip().lower(), str(valor).strip()
    vl = v.lower()
    if b == "match winner":
        return {"home": "1x2:1", "draw": "1x2:X", "away": "1x2:2"}.get(vl)
    if b == "double chance":
        return {"home/draw": "dc:1X", "home/away": "dc:12", "draw/away": "dc:X2"}.get(vl)
    if b == "home/away":
        return {"home": "dnb:1", "away": "dnb:2"}.get(vl)
    if b == "both teams score":
        return {"yes": "btts:si", "no": "btts:no"}.get(vl)
    if b == "first half winner":
        return {"home": "ht1x2:1", "draw": "ht1x2:X", "away": "ht1x2:2"}.get(vl)
    fam = {"goals over/under": "ou", "goals over/under first half": "htou", "total - home": "tl",
           "total - away": "tv", "corners over under": "corners", "cards over/under": "cards"}.get(b)
    if fam:
        ln = _linea(v)
        if not _media(ln) or not vl.startswith(("over", "under")):
            return None
        return f"{fam}:{ln}:{'over' if vl.startswith('over') else 'under'}"
    if b == "asian handicap":
        ln = _linea(v)
        if not _media(ln):
            return None
        if vl.startswith("home"):
            return f"ah:{ln:+}:1"
        if vl.startswith("away"):
            return f"ah:{-ln:+}:2"
    return None


class APIFootball:
    def __init__(self, clave: str, reserva: int = 5):
        self.clave, self.reserva = clave, reserva
        self.restantes = None

    @property
    def activa(self) -> bool:
        return bool(self.clave) and (self.restantes is None or int(self.restantes) > self.reserva)

    def _get(self, ruta: str, cache_horas: float = 0, **params):
        nombre = DATOS / "cache" / ("af_" + re.sub(r"\W+", "_", ruta + json.dumps(params, sort_keys=True)) + ".json")
        nombre.parent.mkdir(exist_ok=True)
        if cache_horas and nombre.exists() and time.time() - nombre.stat().st_mtime < cache_horas * 3600:
            return json.loads(nombre.read_text())
        if not self.activa:
            return {"response": [], "paging": {"total": 1}}
        r = requests.get(BASE + ruta, params=params, headers={"x-apisports-key": self.clave}, timeout=30)
        r.raise_for_status()
        self.restantes = r.headers.get("x-ratelimit-requests-remaining", self.restantes)
        datos = r.json()
        if datos.get("errors"):
            print(f"  ! API-Football {ruta}: {datos['errors']}")
        if cache_horas:
            nombre.write_text(json.dumps(datos))
        time.sleep(0.25)
        return datos

    # ------------------------------------------------------------- partidos
    @staticmethod
    def _fixture(f: dict) -> dict:
        ht = (f.get("score") or {}).get("halftime") or {}
        return {"af_id": f["fixture"]["id"], "liga_id": f["league"]["id"], "temporada": f["league"]["season"],
                "liga": f["league"]["name"], "pais": f["league"]["country"], "inicio": f["fixture"]["date"],
                "local": f["teams"]["home"]["name"], "visita": f["teams"]["away"]["name"],
                "estado": f["fixture"]["status"]["short"], "gl": f["goals"]["home"], "gv": f["goals"]["away"],
                "htl": ht.get("home"), "htv": ht.get("away")}

    def partidos(self, fecha: str, ligas: set[int], tz: str = "America/Guayaquil") -> list[dict]:
        d = self._get("/fixtures", cache_horas=1, date=fecha, timezone=tz)
        return [self._fixture(f) for f in d.get("response", []) if f["league"]["id"] in ligas]

    def historico(self, liga: int, temporada: int) -> pd.DataFrame:
        filas = []
        for t in (temporada, temporada - 1):
            d = self._get("/fixtures", cache_horas=20, league=liga, season=t, status="FT")
            filas += [self._fixture(f) for f in d.get("response", [])]
        if not filas:
            return pd.DataFrame()
        df = pd.DataFrame(filas)
        df["fecha"] = pd.to_datetime(df["inicio"], utc=True).dt.tz_localize(None)
        return df.dropna(subset=["gl", "gv"]).sort_values("fecha").reset_index(drop=True)

    # ---------------------------------------------------------------- cuotas
    def cuotas_liga(self, liga: int, temporada: int, fecha: str, tz: str = "America/Guayaquil") -> dict[int, dict[str, dict[str, float]]]:
        """{fixture_id: {casa: {clave: cuota}}} para todos los partidos de esa liga y fecha."""
        salida, pagina, total = {}, 1, 1
        while pagina <= total:
            d = self._get("/odds", cache_horas=2, league=liga, season=temporada, date=fecha, page=pagina, timezone=tz)
            total = d.get("paging", {}).get("total", 1)
            for item in d.get("response", []):
                fid = item["fixture"]["id"]
                for casa in item.get("bookmakers", []):
                    nombre_casa = re.sub(r"\W+", "", casa["name"].lower())
                    c = salida.setdefault(fid, {}).setdefault(nombre_casa, {})
                    for bet in casa.get("bets", []):
                        for v in bet.get("values", []):
                            k = clave_apuesta(bet["name"], v["value"])
                            if k:
                                try:
                                    c[k] = float(v["odd"])
                                except (TypeError, ValueError):
                                    pass
            pagina += 1
        return salida

    # ----------------------------------------------------------- predicción
    def prediccion(self, fixture: int) -> dict | None:
        d = self._get("/predictions", cache_horas=6, fixture=fixture)
        if not d.get("response"):
            return None
        pc = d["response"][0]["predictions"].get("percent") or {}
        try:
            p = {k: float(str(pc[s]).strip("%")) / 100 for k, s in
                 (("1x2:1", "home"), ("1x2:X", "draw"), ("1x2:2", "away"))}
        except (KeyError, ValueError):
            return None
        s = sum(p.values())
        if s <= 0:
            return None
        p = {k: v / s for k, v in p.items()}
        p |= {"dc:1X": p["1x2:1"] + p["1x2:X"], "dc:X2": p["1x2:X"] + p["1x2:2"],
              "dc:12": p["1x2:1"] + p["1x2:2"]}
        return p

    # ---------------------------------------------------------- resultados
    def estadisticas(self, fixture: int, peso_roja: int = 1) -> dict:
        d = self._get("/fixtures/statistics", cache_horas=240, fixture=fixture)
        corners = cards = 0
        ok = False
        for eq in d.get("response", []):
            st = {s["type"]: s["value"] or 0 for s in eq.get("statistics", [])}
            if "Corner Kicks" in st:
                ok = True
                corners += int(st.get("Corner Kicks") or 0)
                cards += int(st.get("Yellow Cards") or 0) + peso_roja * int(st.get("Red Cards") or 0)
        return {"corners": corners, "cards": cards} if ok else {}
