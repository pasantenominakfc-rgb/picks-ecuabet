"""Orquesta el análisis diario: fuentes -> modelos -> ensamble -> selección."""
import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from . import ensamble, mercados as M, names, seleccion, tracker
from .fuentes import footballdata
from .modelos.conteos import ModeloConteo
from .modelos.goles import DixonColes
from .modelos.pb import ModeloPB

TZ = ZoneInfo("America/Guayaquil")


def _uid(local, visita, inicio):
    return hashlib.md5(f"{local}|{visita}|{inicio[:10]}".encode()).hexdigest()[:12]


class Modelos:
    """Ajusta (una vez por liga) los modelos de goles, córners y tarjetas."""

    def __init__(self, liga: dict, af, cfg: dict, temporada: int | None):
        self.goles, self.corners, self.cards, self.equipos = None, None, None, []
        hist = pd.DataFrame()
        if liga.get("fd"):
            hist = footballdata.historico(liga["fd"], liga.get("tipo", "main"), cfg.get("peso_roja", 1))
        if len(hist) < 60 and af and af.activa and temporada:
            hist = af.historico(liga["af"], temporada)
        self.pb = None
        if len(hist) >= 60:
            self.pb = ModeloPB().ajustar(hist)
            self.goles = DixonColes().ajustar(hist)
            self.equipos = self.goles.equipos
            if "cl" in hist and hist["cl"].notna().sum() >= 80:
                self.corners = ModeloConteo().ajustar(hist, "cl", "cv")
            if "tjl" in hist and hist["tjl"].notna().sum() >= 80:
                self.cards = ModeloConteo().ajustar(hist, "tjl", "tjv")
        print(f"  modelos {liga['nombre']}: {len(hist)} partidos | goles {'ok' if self.goles and self.goles.ok else '–'}"
              f" | córners {'ok' if self.corners and self.corners.ok else '–'}"
              f" | tarjetas {'ok' if self.cards and self.cards.ok else '–'}")

    def probs(self, local: str, visita: str) -> tuple[dict | None, dict]:
        if not self.goles or not self.goles.ok:
            return None, {}
        l, v = names.emparejar(local, self.equipos), names.emparejar(visita, self.equipos)
        if not (l and v) or l == v:
            return None, {}
        out = self.goles.mercados(l, v) or {}
        esperados = {"goles": (out.get("_xg_local", 0) + out.get("_xg_visita", 0)) or None}
        for nombre, mod, fam in (("corners", self.corners, "corners"), ("tarjetas", self.cards, "cards")):
            if mod and mod.ok:
                pm = mod.prob_mas_de(l, v, M.LINEAS[fam])
                if pm:
                    esperados[nombre] = pm.pop("_media")
                    for ln, p in pm.items():
                        out[f"{fam}:{ln}:over"], out[f"{fam}:{ln}:under"] = p, 1 - p
        return out, esperados

    def probs_pb(self, local: str, visita: str) -> dict | None:
        if not self.pb or not self.pb.ok:
            return None
        l, v = names.emparejar(local, self.pb.equipos), names.emparejar(visita, self.pb.equipos)
        if not (l and v) or l == v:
            return None
        r = self.pb.mercados(l, v)
        return {k: x for k, x in r.items() if not k.startswith("_")} if r else None


def analizar(cfg: dict, af, odds, forebet, ahora: datetime | None = None) -> tuple[list, list, list]:
    ahora = ahora or datetime.now(timezone.utc)
    fin = ahora + timedelta(hours=cfg["horas_adelante"])
    fechas = sorted({(ahora + timedelta(days=d)).astimezone(TZ).strftime("%Y-%m-%d")
                     for d in range(0, cfg["horas_adelante"] // 24 + 2)})
    ligas_af = {l["af"]: l for l in cfg["ligas"] if l.get("af")}

    # 1) partidos base (API-Football)
    fixtures = []
    if af and af.activa:
        for f in fechas:
            fixtures += af.partidos(f, set(ligas_af))
    fixtures = [f for f in fixtures if f["estado"] in ("NS", "TBD")
                and ahora <= datetime.fromisoformat(f["inicio"]).astimezone(timezone.utc) <= fin]
    print(f"Partidos en ventana: {len(fixtures)}")

    # 2) fuentes externas una sola vez
    fb_filas = forebet.predicciones() if forebet and forebet.activa else []
    print(f"Forebet: {len(fb_filas)} pronósticos")
    calib = tracker.calibracion()
    prior = cfg["pesos_iniciales"]

    partidos, n_pred_af = [], 0
    for liga_id, liga in ligas_af.items():
        fx_liga = [f for f in fixtures if f["liga_id"] == liga_id]
        if not fx_liga:
            continue
        print(f"→ {liga['nombre']}: {len(fx_liga)} partidos")
        temporada = fx_liga[0]["temporada"]
        modelos = Modelos(liga, af, cfg, temporada)
        cuotas_af = {}
        for d in sorted({f["inicio"][:10] for f in fx_liga}):
            cuotas_af |= af.cuotas_liga(liga_id, temporada, d)
        eventos_odds = odds.cuotas(liga["odds_key"], cfg["horas_adelante"]) if odds and odds.activa and \
            liga.get("odds_key") else []

        for fx in fx_liga:
            casas = {k: dict(v) for k, v in cuotas_af.get(fx["af_id"], {}).items()}
            ev = names.emparejar_partido(fx["local"], fx["visita"], eventos_odds)
            if ev:
                for casa, c in ev["casas"].items():
                    casas.setdefault(casa, {}).update(c)
            fuentes = {}
            mkt = ensamble.probs_mercado(casas, cfg["casas_afiladas"], {cfg["casa_objetivo"]})
            if mkt:
                fuentes["mercado"] = mkt
            pm, esperados = modelos.probs(fx["local"], fx["visita"])
            if pm:
                fuentes["modelo"] = {k: v for k, v in pm.items() if not k.startswith("_")}
            ppb = modelos.probs_pb(fx["local"], fx["visita"])
            if ppb:
                fuentes["penaltyblog"] = ppb
            fb = names.emparejar_partido(fx["local"], fx["visita"],
                                         [r for r in fb_filas if r["fecha"] in (fx["inicio"][:10], None)] or fb_filas)
            if fb:
                fuentes["forebet"] = {k: v for k, v in fb["probs"].items() if not k.startswith("_")}
                for meta, nombre in (("_corners", "corners_fb"), ("_tarjetas", "tarjetas_fb")):
                    if meta in fb["probs"]:
                        esperados[nombre] = fb["probs"][meta]
            if af and af.activa and n_pred_af < cfg["max_predicciones_af"]:
                pa = af.prediccion(fx["af_id"])
                n_pred_af += 1
                if pa:
                    fuentes["apifootball"] = pa
            if not fuentes:
                continue
            partidos.append({
                "uid": str(fx["af_id"]), "af_id": fx["af_id"], "liga": liga["nombre"], "inicio": fx["inicio"],
                "local": fx["local"], "visita": fx["visita"], "fuentes": fuentes,
                "probs": ensamble.combinar(fuentes, prior, calib, cfg),
                "mejores": ensamble.mejores_cuotas(casas, cfg["casas_afiladas"], cfg["casa_objetivo"]),
                "ecuabet": casas.get(cfg["casa_objetivo"], {}), "n_casas": len(casas),
                "xg": (pm.get("_xg_local"), pm.get("_xg_visita")) if pm else None, "esperados": esperados})

    valor, alta = seleccion.elegir(partidos, cfg)
    return partidos, valor, alta
