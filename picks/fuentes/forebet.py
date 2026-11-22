"""Predicciones de Forebet, obtenidas con el actor de Apify `solidcode/forebet-scraper`
(Forebet bloquea las consultas automáticas directas). Costo aprox.: USD 0.10 por 1 000 partidos."""
import json
import time
from datetime import date, timedelta

import requests

from ..config import DATOS

URL = "https://api.apify.com/v2/acts/solidcode~forebet-scraper/run-sync-get-dataset-items"
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


class Forebet:
    def __init__(self, token: str, paises: list[str] | None = None, linea_tarjetas: float = 4.5):
        self.token, self.paises, self.linea_tarjetas = token, paises or [], linea_tarjetas

    @property
    def activa(self):
        return bool(self.token)

    def predicciones(self, dias: int = 2) -> list[dict]:
        """Lista de {local, visita, fecha, probs} para hoy y mañana (cache 6 h)."""
        if not self.activa:
            return []
        cache = DATOS / "cache" / f"forebet_{date.today()}.json"
        cache.parent.mkdir(exist_ok=True)
        if cache.exists() and time.time() - cache.stat().st_mtime < 6 * 3600:
            filas = json.loads(cache.read_text())
        else:
            entrada = {"matchScope": "byDate", "predictionMarkets": MERCADOS,
                       "startDate": str(date.today()), "endDate": str(date.today() + timedelta(days=dias - 1)),
                       "countries": self.paises, "leagues": [], "maxResults": 0}
            try:
                r = requests.post(URL, params={"token": self.token, "timeout": 280}, json=entrada, timeout=300)
                r.raise_for_status()
                filas = r.json()
                cache.write_text(json.dumps(filas))
            except Exception as e:  # noqa: BLE001
                print(f"  ! Forebet/Apify: {e}")
                return []
        return [{"local": f.get("homeTeam"), "visita": f.get("awayTeam"), "fecha": f.get("kickoffDate"),
                 "liga": f.get("league"), "pais": f.get("country"),
                 "probs": a_claves(f, self.linea_tarjetas), "url": f.get("matchUrl")}
                for f in filas if f.get("homeTeam") and f.get("awayTeam")]
