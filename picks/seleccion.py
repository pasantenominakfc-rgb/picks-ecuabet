"""Elige las apuestas del día: valor esperado + consenso entre fuentes + Kelly."""
from . import mercados as M


def kelly(p: float, cuota: float, p_push: float, cfg: dict) -> float:
    b = cuota - 1
    if b <= 0:
        return 0.0
    f = (p * cuota - 1) / b  # con devolución (sin empate) el riesgo efectivo se reduce en (1 - p_push)
    f *= (1 - p_push)
    return max(0.0, min(f * cfg["fraccion_kelly"], cfg["stake_max_pct"]))


def evaluar(partido: dict, cfg: dict) -> list[dict]:
    """Todas las selecciones candidatas de un partido con sus métricas."""
    activos = set(cfg["mercados_activos"])
    out = []
    probs_1x2 = {k: v["p"] for k, v in partido["probs"].items() if k.startswith("1x2:")}
    for k, info in partido["probs"].items():
        if M.familia(k) not in activos:
            continue
        p = info["p"]
        p_push = M.prob_empuje(k, probs_1x2)
        justa = 1 / p
        minima = (1 + cfg["ventaja_minima"] / (1 - p_push)) / p   # cuota con EV >= ventaja mínima
        ecuabet = partido["ecuabet"].get(k)
        mejor, casa = partido["mejores"].get(k, (None, None))
        ref = ecuabet or mejor
        ev = M.valor_esperado(p, ref, p_push) if ref else None
        acuerdo = (sum(1 for ps in info["detalle"].values() if ps * ref > 1) / info["n"]) if ref else None
        conf = min(1.0, info["n"] / 3) * max(0.0, 1 - info["dispersion"] / (2 * cfg["max_dispersion"]))
        out.append({"clave": k, "nombre": M.nombre(k, partido["local"], partido["visita"]),
                    "mercado": M.FAMILIAS[M.familia(k)], "p": p, "p_push": p_push,
                    "cuota_justa": justa, "cuota_minima": minima, "cuota_ecuabet": ecuabet,
                    "mejor_cuota": mejor, "mejor_casa": casa, "cuota_ref": ref, "ev": ev,
                    "acuerdo": acuerdo, "confianza": conf, "n_fuentes": info["n"],
                    "dispersion": info["dispersion"], "detalle": info["detalle"], "pesos": info["pesos"],
                    "ia": (partido.get("ia") or {}).get(k)})
    return out


def _pasa_basico(s: dict, cfg: dict) -> bool:
    return (cfg["cuota_min"] <= s["cuota_justa"] <= cfg["cuota_max"]
            and s["n_fuentes"] >= cfg["min_fuentes"] and s["dispersion"] <= cfg["max_dispersion"])


def elegir(partidos: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """Devuelve (picks_de_valor, picks_alta_probabilidad)."""
    valor, alta = [], []
    for pa in partidos:
        cands = evaluar(pa, cfg)
        pa["evaluadas"] = cands
        base = {k: pa[k] for k in ("uid", "liga", "inicio", "local", "visita", "af_id", "xg", "esperados")}
        v = [s for s in cands if _pasa_basico(s, cfg) and s["ev"] is not None and (s["ia"] or {}).get("riesgo") != "alto"
             and s["ev"] >= cfg["ventaja_minima"] and s["acuerdo"] >= cfg["min_acuerdo"]]
        if v:
            mejor = max(v, key=lambda s: s["ev"] * s["confianza"])
            valor.append(base | mejor | {"confirmado": mejor["cuota_ecuabet"] is not None})
        # alta probabilidad: casi todas las fuentes coinciden (útil para tarjetas/córners en Ecuabet)
        a = [s for s in cands if s["p"] >= cfg["alta_prob_min"] and s["n_fuentes"] >= cfg["min_fuentes"]
             and s["dispersion"] <= cfg["max_dispersion"] / 2 and s["cuota_justa"] >= cfg["alta_cuota_justa_min"]]
        if a:
            alta.append(base | max(a, key=lambda s: s["p"] * s["confianza"]))

    valor.sort(key=lambda s: s["ev"] * s["confianza"], reverse=True)
    valor = valor[: cfg["max_picks_dia"]]
    banca = cfg["banca"]
    for s in valor:
        cuota = s["cuota_ecuabet"] or s["cuota_minima"]   # monto calculado a la cuota mínima (conservador)
        s["cuota_calc"] = cuota
        s["fraccion"] = kelly(s["p"], cuota, s["p_push"], cfg)
    tot = sum(s["fraccion"] for s in valor)
    escala = min(1.0, cfg["exposicion_dia_pct"] / tot) if tot else 1.0
    for s in valor:
        m = round(s["fraccion"] * escala * banca * 4) / 4
        s["monto"] = max(m, cfg["stake_minimo"]) if m > 0 else 0.0
        s["ganancia_esperada"] = s["monto"] * M.valor_esperado(s["p"], s["cuota_calc"], s["p_push"])
    alta.sort(key=lambda s: s["p"], reverse=True)
    return [s for s in valor if s["monto"] > 0], alta[: cfg["max_alta_prob"]]
