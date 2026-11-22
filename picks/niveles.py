"""Niveles de apuesta para el usuario:

- SEGURAS: simples con probabilidad alta (≥ 72%) y cuota baja (1.15–1.60).
- VALOR:   las de siempre (el sistema ve que la cuota paga más de lo que vale).
- GRANDES: combinadas armadas para ganar un objetivo ($100, $200, $500…) con un
           monto chico, eligiendo las selecciones que MÁS probabilidad conservan
           por cada punto de cuota que suman.
"""
import math

from . import mercados as M

MARGEN_ECUABET = 0.94   # si no hay cuota real: cuota estimada = justa × 0.94 (margen típico ~6%)


def cuota_estimada(s: dict) -> tuple[float, str]:
    """Cuota esperable en Ecuabet: real si la tenemos, si no estimada."""
    if s.get("cuota_ecuabet"):
        return float(s["cuota_ecuabet"]), "ecuabet"
    justa = 1 / s["p"]
    est = justa * MARGEN_ECUABET
    if s.get("mejor_cuota"):
        est = min(float(s["mejor_cuota"]) * 0.97, max(est, justa * 0.90))
    return round(max(1.01, est), 2), "estimada"


def _candidatas(partido: dict, cfg: dict) -> list[dict]:
    out = []
    for s in partido.get("evaluadas", []):
        if s["n_fuentes"] < cfg.get("niveles_min_fuentes", 1) or (s.get("ia") or {}).get("riesgo") == "alto":
            continue
        cuota, tipo = cuota_estimada(s)
        out.append({**{k: partido.get(k) for k in ("uid", "af_id", "liga", "inicio", "local", "visita")},
                    **s, "cuota_est": cuota, "tipo_cuota": tipo})
    return out


def seguras(partidos: list[dict], cfg: dict) -> list[dict]:
    pmin, cmin, cmax = cfg.get("seguras_prob_min", 0.72), cfg.get("seguras_cuota_min", 1.15), cfg.get("seguras_cuota_max", 1.60)
    elegidas = []
    for pa in partidos:
        c = [s for s in _candidatas(pa, cfg) if s["p"] >= pmin and cmin <= s["cuota_est"] <= cmax
             and s["dispersion"] <= cfg.get("max_dispersion", 0.08)]
        if c:
            # la más probable; a igualdad, la que mejor paga
            mejor = max(c, key=lambda s: (round(s["p"], 2), s["cuota_est"]))
            mejor["monto"] = max(cfg["stake_minimo"], round(cfg["banca"] * cfg.get("seguras_stake_pct", 0.02) * 4) / 4)
            mejor["ev"] = mejor["p"] * mejor["cuota_est"] - 1
            elegidas.append(mejor)
    elegidas.sort(key=lambda s: -s["p"])
    return elegidas[: cfg.get("max_seguras", 8)]


def _pool_combinadas(partidos: list[dict], cfg: dict) -> list[dict]:
    pmin = cfg.get("grandes_prob_min_pierna", 0.55)
    pool = []
    for pa in partidos:
        for s in _candidatas(pa, cfg):
            if s["p"] >= pmin and s["cuota_est"] >= 1.18 and s["dispersion"] <= cfg.get("max_dispersion", 0.08):
                # eficiencia: probabilidad que se pierde por cada unidad (log) de cuota ganada; menor = mejor
                s["eficiencia"] = -math.log(s["p"]) / math.log(s["cuota_est"])
                pool.append(s)
    return pool


def armar_combinada(pool: list[dict], objetivo_cuota: float, max_piernas: int = 8) -> dict | None:
    """Elige piernas (máx. una por partido) que lleguen a la cuota objetivo con la mayor probabilidad."""
    por_partido = {}
    for s in sorted(pool, key=lambda s: s["eficiencia"]):
        por_partido.setdefault(s["uid"], []).append(s)
    elegidas, cuota = [], 1.0
    usados = set()
    for s in sorted(pool, key=lambda s: s["eficiencia"]):
        if s["uid"] in usados:
            continue
        if cuota >= objetivo_cuota or len(elegidas) >= max_piernas:
            break
        elegidas.append(s)
        usados.add(s["uid"])
        cuota *= s["cuota_est"]
    if cuota < objetivo_cuota * 0.97 or not elegidas:
        return None
    # ajuste fino: si nos pasamos mucho, cambiar la última pierna por una de cuota menor y prob. mayor
    while len(elegidas) > 1:
        sin_ultima = cuota / elegidas[-1]["cuota_est"]
        necesaria = objetivo_cuota / sin_ultima
        alternativas = [s for s in pool if s["uid"] not in usados - {elegidas[-1]["uid"]}
                        and s["cuota_est"] >= necesaria * 0.98 and s["p"] > elegidas[-1]["p"]]
        if not alternativas:
            break
        mejor = max(alternativas, key=lambda s: s["p"])
        usados.discard(elegidas[-1]["uid"])
        elegidas[-1] = mejor
        usados.add(mejor["uid"])
        cuota = sin_ultima * mejor["cuota_est"]
        break
    p = math.prod(s["p"] for s in elegidas)
    return {"piernas": elegidas, "cuota": cuota, "p": p, "ev": p * cuota - 1}


def grandes(partidos: list[dict], cfg: dict, monto: float | None = None, objetivos: list[float] | None = None) -> list[dict]:
    monto = monto or cfg.get("grandes_monto", 5.0)
    objetivos = objetivos or cfg.get("grandes_objetivos", [100, 200, 500])
    pool = _pool_combinadas(partidos, cfg)
    out = []
    for obj in objetivos:
        c = armar_combinada(pool, obj / monto, cfg.get("grandes_max_piernas", 8))
        if c:
            out.append({"objetivo": obj, "monto": monto, "ganancia": round(monto * c["cuota"], 2), **c})
    return out


def resultado_combinada(c: dict, resultados: dict) -> str | None:
    """'ganada' si todas las piernas ganan; 'perdida' si alguna pierde; None si falta info."""
    estados = []
    for s in c["piernas"]:
        r = resultados.get(s["uid"])
        e = M.resultado(s["clave"], r) if r else None
        if e == "perdida":
            return "perdida"
        estados.append(e)
    if any(e is None for e in estados):
        return None
    return "ganada"
