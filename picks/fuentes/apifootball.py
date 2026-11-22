"""API-Football (api-sports.io): partidos, cuotas de muchos mercados, predicciones,
estadísticas (córners/tarjetas) y resultados. Plan gratis: 100 consultas/día."""
import json
import re
import time
from collections import deque
from datetime import date, timedelta

import pandas as pd
import requests

from ..config import DATOS

BASE = "https://v3.football.api-sports.io"


def peticion_con_reintentos(url: str, params: dict | None = None, headers: dict | None = None, sleep=time.sleep,
                            reintentos: int = 2, timeout: float = 30, etiqueta: str = "", antes=None):
    """GET tolerante a fallos: reintenta (hasta `reintentos` veces) timeouts, errores de red, 5xx y 429
    (respeta Retry-After). Devuelve la respuesta, o None si no hubo éxito (nunca lanza por HTTP/red).
    `antes`: callable sin argumentos que se invoca antes de CADA intento real (p. ej. el limitador de cupo)."""
    for intento in range(reintentos + 1):
        espera = min(2.0 * (intento + 1), 10.0)
        ultimo = intento >= reintentos
        if antes:
            antes()
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            print(f"  ! {etiqueta} red/timeout ({e.__class__.__name__})")
            if ultimo:
                return None
            sleep(espera)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            print(f"  ! {etiqueta} HTTP {r.status_code}")
            if ultimo:
                return None
            try:
                ra = r.headers.get("Retry-After")
                if ra:
                    espera = min(max(float(ra), 0.0), 65.0)
            except (TypeError, ValueError):
                pass
            sleep(espera)
            continue
        if r.status_code >= 400:   # 401/403/404...: reintentar no sirve
            print(f"  ! {etiqueta} HTTP {r.status_code}")
            return None
        return r
    return None


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


VACIO = {"response": [], "paging": {"total": 1}}


class APIFootball:
    REINTENTOS_RATE_LIMIT = 2        # veces que se espera y reintenta ante el límite por minuto
    ESPERA_RATE_LIMIT = 62.0         # segundos (la ventana del plan es de 60 s)

    def __init__(self, clave: str, reserva: int = 5, sleep=time.sleep, reloj=time.monotonic,
                 max_por_minuto: int = 10):
        """max_por_minuto: el plan gratis permite 10 peticiones/minuto (config: af_max_por_minuto)."""
        self.clave, self.reserva = clave, reserva
        self.restantes = None
        self.sleep, self.reloj, self.max_por_minuto = sleep, reloj, max_por_minuto
        self.cuota_agotada = False       # el servidor avisó que se acabó la cuota diaria
        self._marcas = deque()           # instantes de las últimas peticiones (limitador)
        # --- límites del plan GRATIS (se aprenden de los mensajes "Free plans do not have access...") ---
        self.plan_gratis = False
        self.rango_fechas = None         # (date, date): fechas permitidas para /fixtures?date=
        self.rango_temp_odds = None      # (int, int): temporadas permitidas para /odds
        self.rango_temp_fixtures = None  # (int, int): temporadas permitidas para /fixtures?season=
        self.temporadas_sin_cuotas = set()
        self.cuotas_no_disponibles = False
        self.rutas_bloqueadas = set()    # rutas con mensaje "free plans" que no se pudo parsear: no se repiten

    def configurar_plan(self, plan: str, hoy: date):
        """plan 'gratis': /fixtures solo admite [ayer, mañana]; se fija el rango sin gastar una llamada para descubrirlo.
        Reinicia lo aprendido en corridas/planes anteriores (rangos, temporadas sin cuotas, rutas bloqueadas): al
        cambiar de plan o de día esas limitaciones ya no son válidas y se vuelven a aprender si aplican."""
        self.rango_fechas = self.rango_temp_odds = self.rango_temp_fixtures = None
        self.temporadas_sin_cuotas = set()
        self.cuotas_no_disponibles = False
        self.rutas_bloqueadas = set()
        self.plan_gratis = (plan or "").strip().lower() == "gratis"
        if self.plan_gratis:
            self.rango_fechas = (hoy - timedelta(days=1), hoy + timedelta(days=1))

    def _fecha_permitida(self, fecha: str) -> bool:
        if not self.rango_fechas:
            return True
        try:
            return self.rango_fechas[0] <= date.fromisoformat(fecha) <= self.rango_fechas[1]
        except ValueError:
            return True

    @staticmethod
    def _temp_permitida(rango, temporada) -> bool:
        try:
            return rango is None or rango[0] <= int(temporada) <= rango[1]
        except (TypeError, ValueError):
            return True

    def _aprender_plan(self, ruta: str, params: dict, errores) -> bool:
        """Si el error es de plan gratis, recuerda el rango permitido (sin repetir la llamada). True si lo era."""
        txt = json.dumps(errores)
        if "free plan" not in txt.lower():
            return False
        m = re.search(r"try from (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", txt)
        if m and "date" in txt.lower():
            try:
                self.rango_fechas = (date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2)))
                return True
            except ValueError:       # fecha imposible en el mensaje: se trata como no parseable
                pass
        m = re.search(r"try from (\d{4}) to (\d{4})", txt)
        if m and "season" in txt.lower():
            rango = (int(m.group(1)), int(m.group(2)))
            if ruta == "/odds":
                self.rango_temp_odds = rango
                self.cuotas_no_disponibles = True
                if params.get("season") is not None:
                    self.temporadas_sin_cuotas.add(int(params["season"]))
            else:
                self.rango_temp_fixtures = rango
            return True
        # "Free plans" sin rango que sepamos leer: se imprime UNA vez y se corta la ruta (no gastar más llamadas)
        if ruta not in self.rutas_bloqueadas:
            print(f"  ! API-Football {ruta} (límite del plan gratis, no parseable): {errores}")
            self.rutas_bloqueadas.add(ruta)
        return True

    def resumen_plan(self) -> str | None:
        """Una sola línea legible por corrida (en vez de decenas de errores repetidos)."""
        if not self.cuotas_no_disponibles:
            return None
        temps = ", ".join(str(t) for t in sorted(self.temporadas_sin_cuotas)) or "actual"
        return (f"Plan gratis: sin cuotas de API-Football para la temporada {temps}; "
                "usa ODDS_API_KEY para cuotas")

    @property
    def activa(self) -> bool:
        return bool(self.clave) and not self.cuota_agotada and (self.restantes is None or int(self.restantes) > self.reserva)

    @property
    def sin_cuota(self) -> bool:
        """True si la cuota diaria se agotó (o quedó bajo la reserva): main/exportar lo muestran."""
        return self.cuota_agotada or (self.restantes is not None and int(self.restantes) <= self.reserva)

    def _esperar_cupo(self):
        n = int(self.max_por_minuto or 0)
        if n <= 0:
            return
        for _ in range(2):
            ahora = self.reloj()
            while self._marcas and ahora - self._marcas[0] >= 60:
                self._marcas.popleft()
            if len(self._marcas) < n:
                break
            self.sleep(max(0.0, 60 - (ahora - self._marcas[0])) + 0.1)
        self._marcas.append(self.reloj())

    def _get(self, ruta: str, cache_horas: float = 0, **params):
        """Nunca lanza por fallos HTTP/red: degrada a respuesta vacía (que NO se guarda en caché)."""
        nombre = DATOS / "cache" / ("af_" + re.sub(r"\W+", "_", ruta + json.dumps(params, sort_keys=True)) + ".json")
        nombre.parent.mkdir(exist_ok=True)
        if cache_horas and nombre.exists() and time.time() - nombre.stat().st_mtime < cache_horas * 3600:
            return json.loads(nombre.read_text())
        if not self.activa or ruta in self.rutas_bloqueadas:
            return dict(VACIO)
        for espera_rl in range(self.REINTENTOS_RATE_LIMIT + 1):
            # cada intento real (también los reintentos por 5xx/429/timeout) pasa por el limitador de cupo
            r = peticion_con_reintentos(BASE + ruta, params, {"x-apisports-key": self.clave}, self.sleep,
                                        etiqueta=f"API-Football {ruta}", antes=self._esperar_cupo)
            if r is None:
                return dict(VACIO)
            self.restantes = r.headers.get("x-ratelimit-requests-remaining", self.restantes)
            try:
                datos = r.json()
            except ValueError:
                return dict(VACIO)
            if not isinstance(datos, dict):
                return dict(VACIO)
            errores = datos.get("errors")
            if not errores:
                break
            if self._aprender_plan(ruta, params, errores):
                return dict(VACIO)               # límite del plan: se recuerda y no se repite (sin ruido en el log)
            print(f"  ! API-Football {ruta}: {errores}")
            txt = json.dumps(errores).lower()
            if "request limit" in txt or (isinstance(errores, dict) and "requests" in errores):
                self.cuota_agotada = True        # cuota DIARIA agotada
                return dict(VACIO)
            if (isinstance(errores, dict) and "ratelimit" in {str(k).lower() for k in errores})                     or "too many requests" in txt:
                # límite por MINUTO (10/min en el plan gratis): no es la cuota diaria; esperar y reintentar
                if espera_rl < self.REINTENTOS_RATE_LIMIT:
                    self.sleep(self.ESPERA_RATE_LIMIT)
                    continue
            return dict(VACIO)                   # degrada sin cachear
        else:
            return dict(VACIO)
        if cache_horas:
            nombre.write_text(json.dumps(datos))
        self.sleep(0.25)
        return datos

    # ------------------------------------------------------------- partidos
    @staticmethod
    def _fixture(f: dict) -> dict:
        score = f.get("score") or {}
        ht = score.get("halftime") or {}
        estado = f["fixture"]["status"]["short"]
        gl, gv = f["goals"]["home"], f["goals"]["away"]
        if estado in ("AET", "PEN"):
            # `goals` incluye prórroga/penales; los mercados se liquidan con los 90 minutos
            ft = score.get("fulltime") or {}
            gl, gv = ft.get("home"), ft.get("away")
        return {"af_id": f["fixture"]["id"], "liga_id": f["league"]["id"], "temporada": f["league"]["season"],
                "liga": f["league"]["name"], "pais": f["league"]["country"], "inicio": f["fixture"]["date"],
                "local": f["teams"]["home"]["name"], "visita": f["teams"]["away"]["name"],
                "estado": estado, "gl": gl, "gv": gv,
                "htl": ht.get("home"), "htv": ht.get("away")}

    def partidos(self, fecha: str, ligas: set[int] | None = None, tz: str = "America/Guayaquil") -> list[dict]:
        """Partidos de una fecha (hora de Ecuador). ligas=None devuelve todos."""
        if not self._fecha_permitida(fecha):
            return []
        d = self._get("/fixtures", cache_horas=1, date=fecha, timezone=tz)
        return [self._fixture(f) for f in d.get("response", []) if ligas is None or f["league"]["id"] in ligas]

    def historico(self, liga: int, temporada: int) -> pd.DataFrame:
        filas = []
        for t in (temporada, temporada - 1):
            if not self._temp_permitida(self.rango_temp_fixtures, t):
                continue
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
        if not self._temp_permitida(self.rango_temp_odds, temporada):
            self.temporadas_sin_cuotas.add(int(temporada))
            self.cuotas_no_disponibles = True
            return salida
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
    CENTINELAS = ("Ball Possession", "Total passes", "Shots on Goal", "Total Shots", "Fouls")

    @staticmethod
    def _entero(v) -> int:
        """None -> 0 (solo se llama con cobertura); numérico -> int; otra cosa ('N/A') -> ValueError."""
        if v is None:
            return 0
        if isinstance(v, bool):
            raise ValueError(v)
        if isinstance(v, (int, float)):
            if v != int(v):
                raise ValueError(v)
            return int(v)
        return int(str(v).strip())

    def estadisticas(self, fixture: int, peso_roja: int = 1) -> dict:
        """{'corners', 'cards'} del partido, o {} si no hay dato fiable. NUNCA lanza.
        Regla de cobertura: un equipo 'tiene cobertura' si al menos una estadística centinela (CENTINELAS)
        es no-null. Si AMBOS equipos la tienen, un null en córners/amarillas/rojas es 0 real; si alguno no
        la tiene (o falta la lista), no hay dato y no se liquida."""
        try:
            d = self._get("/fixtures/statistics", cache_horas=240, fixture=fixture)
            resp = d.get("response")
            if not isinstance(resp, list) or len(resp) != 2:
                return {}
            corners = cards = 0
            for eq in resp:
                st = {x["type"]: x["value"] for x in eq.get("statistics") or []}
                if not any(st.get(k) is not None for k in self.CENTINELAS):
                    return {}
                corners += self._entero(st.get("Corner Kicks"))
                cards += self._entero(st.get("Yellow Cards")) + peso_roja * self._entero(st.get("Red Cards"))
            return {"corners": corners, "cards": cards}
        except Exception as e:   # noqa: BLE001 - un partido malformado no debe revertir los demás resultados
            print(f"  ! estadísticas {fixture}: {e.__class__.__name__}")
            return {}
