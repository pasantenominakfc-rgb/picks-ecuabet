"""Exporta los datos que lee la web (web/data/*.json)."""
import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from . import ensamble, mercados as M, niveles, tracker
from .config import RAIZ

WEB = RAIZ / "web" / "data"
TZ = ZoneInfo("America/Guayaquil")


def _limpio(x):
    if isinstance(x, float):
        return None if math.isnan(x) or math.isinf(x) else round(x, 4)
    if isinstance(x, dict):
        return {str(k): _limpio(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_limpio(v) for v in x]
    if hasattr(x, "item"):  # numpy
        return _limpio(x.item())
    return x


def _guardar(nombre: str, datos):
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / nombre).write_text(json.dumps(_limpio(datos), ensure_ascii=False), encoding="utf-8")


CAMPOS = ["uid", "af_id", "liga", "inicio", "local", "visita", "clave", "nombre", "mercado", "p", "p_push",
          "cuota_justa", "cuota_minima", "cuota_ecuabet", "mejor_cuota", "mejor_casa", "ev", "acuerdo",
          "confianza", "n_fuentes", "dispersion", "detalle", "pesos", "monto", "confirmado", "ia",
          "cuota_est", "tipo_cuota"]


def combinada(valor: list[dict], cfg: dict) -> dict | None:
    """Combinada opcional con los picks más probables (partidos distintos)."""
    n = cfg.get("combinada_selecciones", 2)
    cands = sorted([s for s in valor if s["p"] >= cfg.get("combinada_prob_min", 0.5)], key=lambda s: -s["p"])[:n]
    if len(cands) < 2:
        return None
    p = math.prod(s["p"] for s in cands)
    cuota_min = math.prod(s["cuota_minima"] for s in cands)
    return {"selecciones": [{k: s.get(k) for k in ("local", "visita", "nombre", "p", "cuota_minima")} for s in cands],
            "p": p, "cuota_minima": cuota_min, "ev_a_cuota_minima": p * cuota_min - 1,
            "monto": max(cfg["stake_minimo"], round(cfg["banca"] * 0.005 * 4) / 4)}


def hoy(partidos, valor, alta, cfg, creditos, seguras=None, grandes=None):
    lista_partidos = []
    for pa in sorted(partidos, key=lambda x: x["inicio"]):
        sel = sorted(pa.get("evaluadas", []), key=lambda s: -(s["ev"] or -1))
        lista_partidos.append({
            "uid": pa["uid"], "liga": pa["liga"], "inicio": pa["inicio"], "local": pa["local"], "visita": pa["visita"],
            "fuentes": list(pa["fuentes"]), "xg": pa.get("xg"), "esperados": pa.get("esperados"),
            "probs": {k: v["p"] for k, v in pa["probs"].items()},
            "selecciones": [{k: s.get(k) for k in ("clave", "nombre", "mercado", "p", "cuota_justa", "cuota_minima",
                                                   "mejor_cuota", "ev", "n_fuentes", "dispersion", "detalle")}
                            for s in sel]})
    _guardar("hoy.json", {
        "generado": datetime.now(TZ).isoformat(), "creditos": creditos,
        "config": {k: cfg[k] for k in ("banca", "fraccion_kelly", "stake_max_pct", "ventaja_minima", "stake_minimo",
                                       "min_fuentes", "max_dispersion")},
        "valor": [{k: s.get(k) for k in CAMPOS} for s in valor],
        "alta": [{k: s.get(k) for k in CAMPOS} for s in alta],
        "combinada": combinada(valor, cfg), "partidos": lista_partidos,
        "seguras": [{k: s.get(k) for k in CAMPOS} for s in (seguras or [])],
        "grandes": [{**{k: c[k] for k in ("objetivo", "monto", "ganancia", "cuota", "p", "ev")},
                     "piernas": [{k: s.get(k) for k in CAMPOS} for s in c["piernas"]]} for c in (grandes or [])],
        # piernas candidatas para el armador de combinadas de la web
        "pool": [{k: s.get(k) for k in ("uid", "clave", "liga", "inicio", "local", "visita", "nombre", "mercado",
                                        "p", "cuota_est", "tipo_cuota", "eficiencia", "ia", "n_fuentes")}
                 for s in niveles._pool_combinadas(partidos, cfg)]})


def historial():
    with tracker.con() as c:
        filas = [dict(r) for r in c.execute("SELECT * FROM picks ORDER BY inicio DESC LIMIT 2000")]
    por_dia, acum = {}, 0.0
    for f in sorted([f for f in filas if f["tipo"] == "valor" and f["estado"] in ("ganada", "perdida", "nula")],
                    key=lambda f: f["inicio"]):
        acum += f["ganancia"] or 0
        por_dia[f["inicio"][:10]] = round(acum, 2)   # un punto por día (saldo al cierre)
    curva = [{"f": d, "u": u} for d, u in por_dia.items()]
    _guardar("historial.json", {"picks": filas, "resumen": tracker.resumen(), "curva": curva,
                                "generado": datetime.now(TZ).isoformat()})


def fuentes(cfg):
    calib = tracker.calibracion()
    fams = sorted({f for (_, f) in calib} | {"1x2", "ou", "btts", "corners", "cards", "dc", "ht1x2"})
    # qué fuente opina en qué mercado
    goles = {"1x2", "dc", "dnb", "ou", "btts", "tl", "tv", "ah", "ht1x2", "htou"}
    cubre = {"apifootball": {"1x2", "dc"}, "forebet": {"1x2", "ou", "btts", "ht1x2", "dc", "corners", "cards"},
             "penaltyblog": goles, "ia": set()}
    pesos = {}
    for fam in fams:
        disp = [s for s in cfg["pesos_iniciales"] if (s, fam) in calib or (not calib and fam in cubre.get(s, {fam}))]
        if not disp:
            disp = [s for s in cfg["pesos_iniciales"] if fam in cubre.get(s, {fam})]
        pesos[fam] = ensamble.pesos(fam, disp, cfg["pesos_iniciales"], calib, cfg)
    _guardar("fuentes.json", {
        "familias": {f: M.FAMILIAS.get(f, f) for f in fams},
        "calibracion": [{"fuente": s, "familia": f, **v} for (s, f), v in calib.items()],
        "pesos": pesos, "generado": datetime.now(TZ).isoformat()})


def backtest(res: dict):
    _guardar("backtest.json", {"resultado": res, "generado": datetime.now(TZ).isoformat()})
