"""Exporta los datos que lee la web (web/data/*.json)."""
import json
import math
import os
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
    # allow_nan=False: un NaN/Infinity escapado haría un JSON inválido para el navegador (falla ruidosa)
    (WEB / nombre).write_text(json.dumps(_limpio(datos), ensure_ascii=False, allow_nan=False), encoding="utf-8")


# Privacidad: el repositorio es público. NO se publican banca, montos ni ganancias en dólares
# (el monto sugerido lo calcula la web con la banca guardada en el teléfono).
CAMPOS = ["uid", "af_id", "liga", "inicio", "local", "visita", "clave", "nombre", "mercado", "p", "p_push",
          "cuota_justa", "cuota_minima", "cuota_ecuabet", "mejor_cuota", "mejor_casa", "ev", "acuerdo",
          "confianza", "n_fuentes", "dispersion", "detalle", "pesos", "confirmado", "ia",
          "cuota_est", "tipo_cuota", "cuota_es_estimada"]


def combinada(valor: list[dict], cfg: dict) -> dict | None:
    """Combinada opcional con los picks más probables (partidos distintos)."""
    n = cfg.get("combinada_selecciones", 2)
    cands = sorted([s for s in valor if s["p"] >= cfg.get("combinada_prob_min", 0.5)], key=lambda s: -s["p"])[:n]
    if len(cands) < 2:
        return None
    p = math.prod(s["p"] for s in cands)
    cuota_min = math.prod(s["cuota_minima"] for s in cands)
    return {"selecciones": [{k: s.get(k) for k in ("local", "visita", "nombre", "p", "cuota_minima")} for s in cands],
            "p": p, "cuota_minima": cuota_min, "ev_a_cuota_minima": p * cuota_min - 1}


def _sel(s):
    return {k: s.get(k) for k in CAMPOS + ["region", "fecha"]}


def _grande(c: dict) -> dict:
    """Combinada 'grande'. niveles.grandes() calcula ganancia = monto*cuota (cobro total, incluye lo apostado):
    se publica la ganancia NETA monto*(cuota-1) y el cobro total aparte."""
    monto, cuota = c.get("monto"), c.get("cuota")
    neta = cobro = None
    if monto is not None and cuota is not None:
        neta, cobro = round(monto * (cuota - 1), 2), round(monto * cuota, 2)
    return {"objetivo": c.get("objetivo"), "monto": monto, "ganancia": neta, "cobro_total": cobro,
            "pago": cobro, "cuota": cuota, "p": c.get("p"), "ev": c.get("ev"),
            "ev_estimado": c.get("ev_estimado"), "cuota_es_estimada": c.get("cuota_es_estimada"), "piernas": [_sel(s) for s in c["piernas"]]}


def _aviso(estado: dict | None) -> str | None:
    estado = estado or {}
    sin = estado.get("ligas_sin_datos")
    n = len(sin) if isinstance(sin, (list, tuple, set)) else sin
    if estado.get("cuota_agotada"):
        return "cuota de API agotada" + (f": {n} ligas sin datos" if n else "")
    return f"{n} ligas sin datos" if n else None


def hoy(partidos, dias: dict, cfg, creditos, estado: dict | None = None):
    """hoy.json: todos los partidos (hoy a +5 días) y los picks de cada día.
    `estado`: dict opcional del análisis (cuota_agotada, ligas_sin_datos) para mostrar un aviso."""
    lista_partidos = []
    for pa in sorted(partidos, key=lambda x: x["inicio"]):
        sel = sorted(pa.get("evaluadas", []), key=lambda s: -(s["ev"] or -1))
        lista_partidos.append({
            "uid": pa["uid"], "liga": pa["liga"], "region": pa.get("region"), "fecha": pa["fecha"],
            "inicio": pa["inicio"], "local": pa["local"], "visita": pa["visita"],
            "fuentes": list(pa["fuentes"]), "xg": pa.get("xg"), "esperados": pa.get("esperados"),
            "probs": {k: v["p"] for k, v in pa["probs"].items()},
            "selecciones": [{k: s.get(k) for k in ("clave", "nombre", "mercado", "p", "cuota_justa", "cuota_minima",
                                                   "mejor_cuota", "ev", "n_fuentes", "dispersion", "detalle")}
                            for s in sel[:12]]})
    salida_dias = {}
    for fecha, d in dias.items():
        del_dia = [p for p in partidos if p["fecha"] == fecha]
        salida_dias[fecha] = {
            "valor": [_sel(s) for s in d["valor"]], "alta": [_sel(s) for s in d["alta"]],
            "seguras": [_sel(s) for s in d["seguras"]],
            "grandes": [_grande(c) for c in d["grandes"]],
            "combinada": combinada(d["valor"], cfg),
            "pool": [{k: s.get(k) for k in ("uid", "clave", "liga", "region", "fecha", "inicio", "local", "visita",
                                            "nombre", "mercado", "p", "cuota_est", "tipo_cuota", "eficiencia", "ia",
                                            "n_fuentes")} for s in niveles._pool_combinadas(del_dia, cfg)]}
    _guardar("hoy.json", {
        "generado": datetime.now(TZ).isoformat(), "creditos": creditos,
        "simulacion": creditos == "simulación" or bool(os.environ.get("PICKS_SIMULACION")),
        "aviso": _aviso(estado),
        "config": {k: cfg.get(k) for k in ("fraccion_kelly", "stake_max_pct", "stake_minimo", "exposicion_dia_pct",
                                           "ventaja_minima", "min_fuentes", "max_dispersion", "seguras_stake_pct",
                                           "seguras_prob_min", "seguras_cuota_min", "seguras_cuota_max",
                                           "grandes_monto", "grandes_objetivos")},
        "fechas": sorted(salida_dias), "dias": salida_dias, "partidos": lista_partidos})


def _unidades(f: dict):
    """Resultado en unidades de apuesta (ganancia/monto); None si está pendiente o no se apostó.
    Solo filas con registrado==1 (igual que tracker.resumen): el monto sugerido de un pick sin registrar no cuenta."""
    if f.get("registrado") != 1 or f["estado"] not in ("ganada", "perdida", "nula") or not f.get("monto") or f.get("ganancia") is None:
        return None
    return f["ganancia"] / f["monto"]


def _roi_n(filas: list[dict]) -> dict:
    """ROI y n sobre apuestas REGISTRADAS por el usuario (monto > 0) ya liquidadas."""
    reg = [f for f in filas if _unidades(f) is not None]
    apostado = sum(f["monto"] for f in reg)
    return {"n": len(reg), "roi": (sum(f["ganancia"] for f in reg) / apostado) if apostado else None}


def resumen_publico(filas: list[dict]) -> dict:
    """Resumen sin dólares: n, acierto y ROI (fracción), por tipo y por mercado."""
    reg = [f for f in filas if _unidades(f) is not None]
    out = {**_roi_n(filas), "unidades": round(sum(_unidades(f) for f in reg), 2), "acierto": (sum(f["estado"] == "ganada" for f in reg) / len(reg)) if reg else None,
           "por_tipo": {}, "por_mercado": {}}
    for t in sorted({f["tipo"] for f in filas}):
        out["por_tipo"][t] = _roi_n([f for f in filas if f["tipo"] == t])
    for fam in sorted({M.familia(f["clave"]) for f in filas}):
        out["por_mercado"][M.FAMILIAS.get(fam, fam)] = _roi_n([f for f in filas if M.familia(f["clave"]) == fam])
    return out


def historial():
    with tracker.con() as c:
        filas = [dict(r) for r in c.execute("SELECT * FROM picks ORDER BY inicio DESC LIMIT 2000")]
    publicas = []
    for f in filas:
        pub = {k: v for k, v in f.items() if k not in ("monto", "ganancia")}
        pub["u"] = _unidades(f)
        publicas.append(pub)
    por_dia, acum = {}, 0.0
    for f in sorted([f for f in filas if _unidades(f) is not None],
                    key=lambda f: f["inicio"]):
        acum += _unidades(f)
        por_dia[f["inicio"][:10]] = round(acum, 2)   # un punto por día (saldo al cierre, en unidades)
    curva = [{"f": d, "u": u} for d, u in por_dia.items()]
    _guardar("historial.json", {"picks": publicas, "resumen": resumen_publico(filas), "curva": curva,
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
