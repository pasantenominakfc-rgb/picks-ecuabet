"""Predicciones de Forebet, obtenidas con el actor de Apify `solidcode/forebet-scraper`
(Forebet bloquea las consultas automáticas directas). Costo aprox.: USD 0.10 por 1 000 partidos.

El actor es lento (a veces > 280 s): se ejecuta de forma ASÍNCRONA (POST /runs + sondeo cada ~10 s) con una
espera máxima configurable (`forebet_espera_max_seg`, 480 s por defecto)."""
import json
import re
import time
from datetime import timedelta

import requests

from ..config import DATOS
from ..errores import describir

BASE = "https://api.apify.com/v2"
URL_RUNS = f"{BASE}/acts/solidcode~forebet-scraper/runs"
TERMINALES = ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT")
MERCADOS = ["match1x2", "underOver25", "bothTeamsToScore", "halfTime", "doubleChance", "corners", "cards"]


def _p(x):
    return None if x is None else float(x) / 100


def a_claves(row: dict, linea_tarjetas: float = 4.5) -> dict:
    out = {}
    pares = [("1x2:1", "probabilityHome"), ("1x2:X", "probabilityDraw"), ("1x2:2", "probabilityAway"),
             ("ou:2.5:over", "probabilityOver25"), ("ou:2.5:under", "probabilityUnder25"),
             ("btts:si", "probabilityBttsYes"), ("btts:no", "probabilityBttsNo"),
             ("ht1x2:1", "probabilityHalfTimeHome"), ("ht1x2:X", "probabilityHalfTimeDraw"),
             ("ht1x2:2", "probabilityHalfTimeAway"),
             ("corners:9.5:over", "probabilityCornersOver95"), ("corners:9.5:under", "probabilityCornersUnder95"),
             (f"cards:{linea_tarjetas}:over", "probabilityCardsOver"),
             (f"cards:{linea_tarjetas}:under", "probabilityCardsUnder")]
    for k, campo in pares:
        if row.get(campo) is not None:
            out[k] = _p(row[campo])
    # normaliza grupos (Forebet redondea a enteros)
    for grupo in (("1x2:1", "1x2:X", "1x2:2"), ("ht1x2:1", "ht1x2:X", "ht1x2:2")):
        if all(g in out for g in grupo) and sum(out[g] for g in grupo) > 0:
            s = sum(out[g] for g in grupo)
            for g in grupo:
                out[g] /= s
    dc = row.get("doubleChancePrediction")
    if dc in ("1X", "12", "X2") and row.get("probabilityDoubleChance") is not None:
        out[f"dc:{dc}"] = _p(row["probabilityDoubleChance"])
    for meta, campo in (("_goles", "predictedGoalsAverage"), ("_corners", "predictedCornersAverage"),
                        ("_tarjetas", "predictedCardsAverage")):
        if row.get(campo) is not None:
            out[meta] = float(row[campo])
    return out


# ---------------------------------------------------------------- contexto (informativo) y cuotas de referencia
def _norm(k) -> str:
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def _buscar(row: dict, *nombres):
    """Primer valor no vacío entre varios nombres posibles de campo (sin distinguir mayúsculas ni separadores)."""
    mapa = {_norm(k): v for k, v in row.items()}
    for n in nombres:
        v = mapa.get(_norm(n))
        if v is not None and v != "" and v != []:
            return v
    return None


def _texto(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, dict):
        v = " ".join(str(x) for x in v.values() if isinstance(x, (str, int, float)) and not isinstance(x, bool))
    elif isinstance(v, (list, tuple)):
        v = "".join(str(x) for x in v if isinstance(x, (str, int, float)))
    elif isinstance(v, bool) or not isinstance(v, (str, int, float)):
        return None
    t = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(v))).strip()
    return t[:200] or None


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v.strip().replace(",", ".")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _entero(v) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    m = re.search(r"\d+", str(v))
    return int(m.group()) if m else None


def _cuota(v) -> float | None:
    x = _num(v)
    return round(x, 2) if x is not None and 1.01 <= x <= 200 else None


def extraer_ctx(row: dict) -> dict:
    """Contexto informativo de una fila del actor. Los nombres de campos de forma/posición/clima son SUPOSICIONES:
    se buscan varias variantes y nunca falla si faltan. La forma y la posición NO alteran probabilidades.
    Las cuotas son REFERENCIA ESTIMADA (la casa no se nombra; no son de Ecuabet): solo se exportan etiquetadas."""
    row = row if isinstance(row, dict) else {}

    def g(*n):
        return _buscar(row, *n)

    return {
        "forma": {"local": _texto(g("homeForm", "formHome", "homeTeamForm", "homeRecentForm", "homeLastResults")),
                  "visita": _texto(g("awayForm", "formAway", "awayTeamForm", "awayRecentForm", "awayLastResults"))},
        "posicion": {"local": _entero(g("homePosition", "positionHome", "homeLeaguePosition", "homeRank", "homeStanding")),
                     "visita": _entero(g("awayPosition", "positionAway", "awayLeaguePosition", "awayRank", "awayStanding"))},
        "tendencia": _texto(g("trendNote", "trend", "trendNotes")),
        "marcador_previsto": _texto(g("predictedScore", "scorePrediction", "predictedResult")),
        "goles_prom": _num(g("predictedGoalsAverage", "goalsAverage", "avgGoals")),
        "valor_pct": _num(g("valuePercent", "valuePct")),
        "clima": _texto(g("weather", "weatherForecast")),
        "cuotas_ref": {"1": _cuota(g("oddsHome")), "X": _cuota(g("oddsDraw")), "2": _cuota(g("oddsAway")),
                       "o25": _cuota(g("oddsOver25")), "u25": _cuota(g("oddsUnder25")),
                       "btts_si": _cuota(g("oddsBttsYes")), "btts_no": _cuota(g("oddsBttsNo"))}}


class Forebet:
    def __init__(self, token: str, paises: list[str] | None = None, linea_tarjetas: float = 4.5,
                 espera_max_seg: float = 480, intervalo_seg: float = 10, get=None, post=None, sleep=None, reloj=None):
        self.token, self.paises, self.linea_tarjetas = token, paises or [], linea_tarjetas
        self.espera_max_seg, self.intervalo_seg = espera_max_seg, intervalo_seg
        self._get, self._post, self._sleep, self._reloj = get, post, sleep, reloj   # inyectables (pruebas)
        self.parcial = False

    @property
    def activa(self):
        return bool(self.token)

    def _correr(self, entrada: dict) -> list[dict]:
        """Run asíncrono: POST /runs, sondeo de /actor-runs/{id} y, al terminar, /datasets/{id}/items.
        El token va SOLO en la cabecera Authorization. Si se agota la espera, aborta el run y lee UNA vez el dataset
        (resultado parcial, `self.parcial` = True). Cualquier fallo tras crear el run lo aborta (se paga por resultado)."""
        get, post = self._get or requests.get, self._post or requests.post
        sleep, reloj = self._sleep or time.sleep, self._reloj or time.monotonic
        cab = {"Authorization": f"Bearer {self.token}"}
        self.parcial = False
        r = post(URL_RUNS, headers=cab, json=entrada, timeout=60)
        r.raise_for_status()
        run_id = dataset = None
        try:
            run = r.json()["data"]
            run_id, dataset = run["id"], run.get("defaultDatasetId")
            t0 = reloj()
            while True:
                g = get(f"{BASE}/actor-runs/{run_id}", headers=cab, timeout=60)
                g.raise_for_status()
                run = g.json()["data"]
                dataset = run.get("defaultDatasetId") or dataset
                estado = run.get("status")
                if estado in TERMINALES:
                    break
                if reloj() - t0 >= self.espera_max_seg:
                    self._abortar(post, cab, run_id)
                    print(f"  ! Forebet/Apify: se agotó la espera ({self.espera_max_seg:g} s); run abortado, estado {estado}")
                    filas = self._items(get, cab, dataset)
                    self.parcial = bool(filas)
                    return filas
                sleep(self.intervalo_seg)
            if estado != "SUCCEEDED":
                print(f"  ! Forebet/Apify: el run terminó en estado {estado}")
                return []
            return self._items(get, cab, dataset)
        except Exception:
            if run_id:
                self._abortar(post, cab, run_id)   # no dejar un run vivo si falló el sondeo
            raise

    @staticmethod
    def _items(get, cab, dataset) -> list[dict]:
        if not dataset:
            return []
        d = get(f"{BASE}/datasets/{dataset}/items", headers=cab, params={"format": "json", "clean": "true"}, timeout=120)
        d.raise_for_status()
        filas = d.json()
        return filas if isinstance(filas, list) else []

    @staticmethod
    def _abortar(post, cab, run_id):
        try:
            post(f"{BASE}/actor-runs/{run_id}/abort", headers=cab, timeout=30)
        except Exception as e:  # noqa: BLE001
            print(f"  ! Forebet/Apify: no se pudo abortar el run: {describir(e)}")

    def predicciones(self, dias: int = 2) -> list[dict]:
        """Lista de {local, visita, fecha, probs, ctx} para hoy y mañana (cache 6 h; los fallos no se cachean)."""
        if not self.activa:
            return []
        from ..pipeline import hoy_ec  # import tardío: pipeline importa fuentes
        hoy = hoy_ec()
        cache = DATOS / "cache" / f"forebet_{hoy}.json"
        cache.parent.mkdir(exist_ok=True)
        filas = None
        if cache.exists() and time.time() - cache.stat().st_mtime < 6 * 3600:
            try:
                filas = json.loads(cache.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                filas = None
            if not isinstance(filas, list):      # caché corrupta o de otro formato: se ignora
                filas = None
        if filas is None:
            entrada = {"matchScope": "byDate", "predictionMarkets": MERCADOS,
                       "startDate": str(hoy), "endDate": str(hoy + timedelta(days=dias - 1)),
                       "countries": self.paises, "leagues": [], "maxResults": 0}
            try:
                filas = self._correr(entrada)
            except Exception as e:  # noqa: BLE001
                print(f"  ! Forebet/Apify: {describir(e)}")   # nunca {e}: la URL puede llevar secretos
                return []
            if not filas:
                return []
            if not self.parcial:      # un resultado parcial (espera agotada) no se cachea
                try:
                    cache.write_text(json.dumps(filas, ensure_ascii=False), encoding="utf-8")
                except OSError as e:
                    print(f"  ! Forebet: no se pudo guardar la caché: {describir(e)}")
        return [{"local": f.get("homeTeam"), "visita": f.get("awayTeam"), "fecha": f.get("kickoffDate"),
                 "liga": f.get("league"), "pais": f.get("country"),
                 "probs": a_claves(f, self.linea_tarjetas), "url": f.get("matchUrl"), "ctx": extraer_ctx(f)}
                for f in filas if isinstance(f, dict) and f.get("homeTeam") and f.get("awayTeam")]
