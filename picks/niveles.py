"""Niveles de apuesta para el usuario:

- SEGURAS: simples con probabilidad alta (≥ 72%) y cuota baja (1.25–1.60; manda config.yaml).
- VALOR:   las de siempre (el sistema ve que la cuota paga más de lo que vale).
- GRANDES: combinadas armadas para ganar un objetivo ($100, $200, $500…) con un
           monto chico, eligiendo las selecciones que MÁS probabilidad conservan
           por cada punto de cuota que suman.
"""
import math

from . import mercados as M, seleccion

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
        # 'sin empate' (dnb) queda fuera de Seguras y de combinadas: su p es condicional (sin contar la
        # devolución por empate) y mezclarla con p de mercados normales sobreestima la probabilidad real.
        if M.familia(s["clave"]) == "dnb":
            continue
        cuota, tipo = cuota_estimada(s)
        out.append({**{k: partido.get(k) for k in ("uid", "af_id", "liga", "region", "fecha", "inicio", "local", "visita")},
                    **s, "cuota_est": cuota, "tipo_cuota": tipo})
    return out


def seguras(partidos: list[dict], cfg: dict) -> list[dict]:
    """Una segura por partido (la más probable). El monto es max(stake_minimo, seguras_stake_pct*banca, 2% por defecto)
    y debe respetar stake_max_pct (3%) por pick: si lo viola, la segura se OMITE (igual que seleccion.elegir).
    Tope diario propio de seguras: `seguras_exposicion_dia_pct` (6% por defecto); si el total lo excede se omiten
    las de menor probabilidad. OJO: el tope total del día (valor + seguras, exposicion_dia_pct) NO se aplica aquí:
    se deja al usuario en la app, porque las seguras y el valor se generan por separado."""
    pmin, cmin, cmax = cfg.get("seguras_prob_min", 0.72), cfg.get("seguras_cuota_min", 1.25), cfg.get("seguras_cuota_max", 1.60)
    elegidas = []
    for pa in partidos:
        c = [s for s in _candidatas(pa, cfg) if s["p"] >= pmin and cmin <= s["cuota_est"] <= cmax
             and s["dispersion"] <= cfg.get("max_dispersion", 0.08)]
        if c:
            # la más probable; a igualdad, la que mejor paga
            mejor = max(c, key=lambda s: (round(s["p"], 2), s["cuota_est"]))
            monto = max(cfg["stake_minimo"], round(cfg["banca"] * cfg.get("seguras_stake_pct", 0.02) * 4) / 4)
            if monto > cfg.get("stake_max_pct", 0.03) * cfg["banca"] + 1e-9:
                continue          # el stake mínimo/2% viola el tope por pick: no se recomienda
            mejor["monto"] = monto
            mejor["cuota_es_estimada"] = mejor["tipo_cuota"] != "ecuabet"
            # el EV solo tiene sentido contra una cuota real de Ecuabet; con la estimada sería circular
            mejor["ev"] = None if mejor["cuota_es_estimada"] else mejor["p"] * mejor["cuota_est"] - 1
            elegidas.append(mejor)
    elegidas.sort(key=lambda s: -s["p"])
    tope_dia = cfg.get("seguras_exposicion_dia_pct", 0.06) * cfg["banca"]
    usado, dentro = 0.0, []
    for s in elegidas[: cfg.get("max_seguras", 8)]:      # de mayor a menor probabilidad
        if usado + s["monto"] <= tope_dia + 1e-9:
            usado += s["monto"]
            dentro.append(s)
    return dentro


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
    ev_est = p * cuota - 1
    return {"piernas": elegidas, "cuota": cuota, "p": p, "ev": ev_est, "ev_estimado": ev_est,
            "cuota_es_estimada": any(s["tipo_cuota"] != "ecuabet" for s in elegidas)}


def grandes(partidos: list[dict], cfg: dict, monto: float | None = None, objetivos: list[float] | None = None) -> list[dict]:
    monto = monto or cfg.get("grandes_monto", 5.0)
    objetivos = objetivos or cfg.get("grandes_objetivos", [100, 200, 500])
    pool = _pool_combinadas(partidos, cfg)
    out = []
    for obj in objetivos:
        c = armar_combinada(pool, obj / monto, cfg.get("grandes_max_piernas", 8))
        if c:
            # ganancia = NETA (sin devolver el monto); pago = lo que se cobra en total
            out.append({"objetivo": obj, "monto": monto, "ganancia": round(monto * (c["cuota"] - 1), 2),
                        "pago": round(monto * c["cuota"], 2), **c})
    return out


def evaluar_combinada(c: dict, resultados: dict) -> tuple[str | None, float]:
    """(estado, cuota_efectiva). Una pierna 'nula' (devolución) sale de la combinada y la cuota se
    recalcula con las piernas restantes. 'perdida' si alguna pierde; None si falta info;
    'nula' si todas son nulas (cuota efectiva 1.0)."""
    estados, cuota = [], 1.0
    for s in c["piernas"]:
        r = resultados.get(s["uid"])
        e = M.resultado(s["clave"], r) if r else None
        if e == "perdida":
            return "perdida", 0.0
        estados.append(e)
        if e == "ganada":
            cuota *= s["cuota_est"]
    if any(e is None for e in estados):
        return None, cuota
    if all(e == "nula" for e in estados):
        return "nula", 1.0
    return "ganada", cuota


def resultado_combinada(c: dict, resultados: dict) -> str | None:
    """'ganada' | 'perdida' | 'nula' | None (falta info). Ver evaluar_combinada para la cuota efectiva."""
    return evaluar_combinada(c, resultados)[0]


def cuota_efectiva_combinada(c: dict, resultados: dict) -> float:
    """Cuota a cobrar si la combinada ganó (sin las piernas nulas); 1.0 si todas fueron nulas."""
    return evaluar_combinada(c, resultados)[1]


# ---------------------------------------------------------------- LOCAS (alto riesgo, alto pago)
_AVISO_LOCAS = False     # el aviso de banca insuficiente se imprime una sola vez por proceso


def _finito(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def locas(partidos: list[dict], cfg: dict, excluir: set | None = None, excluir_uids: set | None = None) -> list[dict]:
    """Simples de cuota alta (3 a 12 por defecto). ALTO RIESGO: se gana pocas veces; el stake es mínimo.
    Solo con cuota REAL de casas (cuota_ecuabet o mejor_cuota): sin ella no se generan (no se inventa EV con
    cuotas estimadas, ni con las de referencia de Forebet). Filtros: probabilidad >= locas_prob_min, EV >= locas_ev_min
    y el mismo consenso que Valor (fuente externa, min_fuentes, dispersión, acuerdo; IA con riesgo alto fuera).
    Se descartan valores no finitos (NaN/inf), p fuera de (0, 1) y "sin empate" (su p es condicional).
    Una por partido, máx. `locas_max_dia`, con tope de exposición diaria. `excluir` = {(uid, clave)} y `excluir_uids` =
    {uid} ya usados en otro nivel (un partido con pick de Valor/Alta/Seguras no recibe Loca).
    Banca: con el stake mínimo (`stake_minimo`) y 1.5% de exposición, banca 100 admite 1 Loca/día y 200 o más, 3."""
    global _AVISO_LOCAS
    cmin, cmax = cfg.get("locas_cuota_min", 3.0), cfg.get("locas_cuota_max", 12.0)
    pmin, evmin = cfg.get("locas_prob_min", 0.12), cfg.get("locas_ev_min", 0.10)
    banca = cfg["banca"]
    excluir = {(str(u), c) for u, c in (excluir or set())}
    excluir_uids = {str(u) for u in (excluir_uids or set())}
    elegidas = []
    for pa in partidos:
        if str(pa["uid"]) in excluir_uids:
            continue
        cands = pa.get("evaluadas") or seleccion.evaluar(pa, cfg)
        buenas = []
        for s in cands:
            if M.familia(s["clave"]) == "dnb" or (str(pa["uid"]), s["clave"]) in excluir:
                continue
            cuota = s.get("cuota_ecuabet") or s.get("mejor_cuota")
            p, disp, acuerdo, conf = s.get("p"), s.get("dispersion"), s.get("acuerdo"), s.get("confianza", 1.0)
            push = s.get("p_push") or 0.0
            if not all(_finito(x) for x in (p, cuota, disp, acuerdo, conf, push)) or not 0 < p < 1:
                continue
            ev = M.valor_esperado(p, cuota, push)
            det = s.get("detalle") or {}
            # condiciones positivas: cualquier comparación dudosa descarta
            if not (cmin <= cuota <= cmax and p >= pmin and _finito(ev) and ev >= evmin
                    and disp <= cfg.get("max_dispersion", 0.08)
                    and seleccion.contar_fuentes(det) >= cfg.get("min_fuentes", 2)
                    and seleccion.tiene_fuente_externa(det)
                    and acuerdo >= cfg.get("min_acuerdo", 0.67)
                    and (s.get("ia") or {}).get("riesgo") != "alto"):
                continue
            buenas.append((ev * conf, ev, cuota, s))
        if buenas:
            puntaje, ev, cuota, s = max(buenas, key=lambda t: t[0])
            base = {k: pa.get(k) for k in ("uid", "af_id", "liga", "region", "fecha", "inicio", "local", "visita", "xg", "esperados")}
            elegidas.append((puntaje, base | s | {"ev": ev, "cuota_calc": cuota, "confirmado": bool(s.get("cuota_ecuabet")),
                                                  "nivel": "locas"}))
    elegidas.sort(key=lambda t: -t[0])
    monto = max(cfg.get("stake_minimo", 1.0), math.floor(banca * cfg.get("locas_stake_pct", 0.005) * 4 + 1e-9) / 4)
    tope_dia = cfg.get("locas_exposicion_dia_pct", 0.015) * banca
    if elegidas and (monto > cfg.get("stake_max_pct", 0.03) * banca + 1e-9 or monto > tope_dia + 1e-9):
        if not _AVISO_LOCAS:
            _AVISO_LOCAS = True
            print("  ! Locas: con esta banca el stake mínimo supera el tope diario de Locas (o el tope por pick): "
                  "no se recomiendan Locas")
        return []
    usado, out = 0.0, []
    for _, s in elegidas[: cfg.get("locas_max_dia", 3)]:
        if usado + monto <= tope_dia + 1e-9:
            usado += monto
            out.append({**s, "monto": monto})
    return out


# ---------------------------------------------------------------- COMBINADAS candidatas (sin objetivo de cobro)
_OBJETIVOS_COMB = (3, 4, 5, 6, 8, 10, 12, 15, 25, 30, 50, 60)   # sin 20/40/100: son los de Grandes por defecto


def combinadas(partidos: list[dict], cfg: dict, grandes_dia: list[dict] | None = None) -> list[dict]:
    """Combinadas candidatas con cuota total 3-60 y p >= 0.05 (máx. 10/día), con las mismas reglas de piernas que
    Grandes (una por partido, p >= grandes_prob_min_pierna, misma dispersión). No fuerza ningún objetivo de cobro:
    `objetivo` = None. Con pocas piernas queda vacío."""
    monto = cfg.get("grandes_monto", 5.0)
    pool = _pool_combinadas(partidos, cfg)
    vistas, out = set(), []
    for g in grandes_dia or []:      # no repetir lo que ya sale como Grande
        vistas.add(frozenset((str(x["uid"]), x["clave"]) for x in g["piernas"]))
    for obj in _OBJETIVOS_COMB:
        c = armar_combinada(pool, obj, cfg.get("grandes_max_piernas", 8))
        if not c or len(c["piernas"]) < 2 or not 3.0 <= c["cuota"] <= 60.0 or c["p"] < 0.05:
            continue
        clave = frozenset((str(s["uid"]), s["clave"]) for s in c["piernas"])
        if clave in vistas:
            continue
        vistas.add(clave)
        out.append({"objetivo": None, "monto": monto, "ganancia": round(monto * (c["cuota"] - 1), 2),
                    "pago": round(monto * c["cuota"], 2), **c})
    out.sort(key=lambda c: -c["p"])
    return out[:10]

