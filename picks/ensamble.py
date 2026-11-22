"""Combina las fuentes en una sola probabilidad por mercado, con pesos que se
ajustan solos según el error histórico de cada fuente (log-loss)."""
import math
from collections import defaultdict
from statistics import mean, median, pstdev

from . import mercados as M


# --------------------------------------------------------------- sin margen
def quitar_margen(cuotas: dict[str, float], suma: float = 1.0) -> dict[str, float]:
    imp = {k: 1 / v for k, v in cuotas.items() if v and v > 1}
    if len(imp) != len(cuotas) or not imp:
        return {}
    if suma != 1.0:  # doble oportunidad: proporcional
        s = sum(imp.values())
        return {k: v * suma / s for k, v in imp.items()}
    lo, hi = 0.5, 3.0  # método de potencia (corrige sesgo favorito/longshot)
    for _ in range(60):
        k = (lo + hi) / 2
        lo, hi = (k, hi) if sum(p ** k for p in imp.values()) > 1 else (lo, k)
    return {o: p ** k for o, p in imp.items()}


TAM_GRUPO = {"1x2": 3, "ht1x2": 3, "dc": 3}


def probs_mercado(casas: dict[str, dict[str, float]], afiladas: list[str], excluir: set[str]) -> dict:
    """Probabilidad del mercado por clave: promedio sin margen de casas afiladas,
    o mediana de todas las casas si no hay afiladas para ese mercado."""
    por_clave_af, por_clave_todas = defaultdict(list), defaultdict(list)
    for casa, cuotas in casas.items():
        if casa in excluir:
            continue
        grupos = defaultdict(dict)
        for k, o in cuotas.items():
            grupos[M.grupo(k)][k] = o
        for g, cs in grupos.items():
            if len(cs) != TAM_GRUPO.get(M.familia(g), 2):
                continue
            sm = quitar_margen(cs, M.suma_grupo(next(iter(cs))))
            for k, p in sm.items():
                por_clave_todas[k].append(p)
                if casa in afiladas:
                    por_clave_af[k].append(p)
    out = {}
    for k, lista in por_clave_todas.items():
        out[k] = mean(por_clave_af[k]) if por_clave_af.get(k) else median(lista)
    return out


def mejores_cuotas(casas: dict, afiladas: list[str], objetivo: str) -> dict[str, tuple[float, str]]:
    """Mejor cuota por clave entre casas 'blandas' (excluye afiladas y la casa objetivo)."""
    out = {}
    for casa, cuotas in casas.items():
        if casa in afiladas or casa == objetivo:
            continue
        for k, o in cuotas.items():
            if k not in out or o > out[k][0]:
                out[k] = (o, casa)
    return out


# --------------------------------------------------------------------- pesos
def pesos(fam: str, disponibles: list[str], prior: dict[str, float], calib: dict, cfg: dict) -> dict[str, float]:
    """prior x exp(-(LL - LL_min)/tau) con confianza creciente según nº de muestras."""
    n0, tau = cfg.get("calib_n0", 150), cfg.get("calib_tau", 0.01)
    st = {s: calib.get((s, fam)) for s in disponibles}
    lls = [v["ll"] for v in st.values() if v and v["n"] >= 30]
    ll_min = min(lls) if lls else None
    w = {}
    for s in disponibles:
        base = prior.get(s, 0.1)
        v = st.get(s)
        if ll_min is not None and v and v["n"] >= 30:
            conf = v["n"] / (v["n"] + n0)
            base *= math.exp(-conf * (v["ll"] - ll_min) / tau)
        w[s] = base
    tot = sum(w.values())
    if not tot:   # todos los pesos en 0: pesos uniformes en vez de un KeyError aguas abajo
        return {s: 1 / len(disponibles) for s in disponibles} if disponibles else {}
    return {s: x / tot for s, x in w.items()}


def combinar(fuentes: dict[str, dict], prior: dict, calib: dict, cfg: dict) -> dict:
    """fuentes = {nombre: {clave: p}} -> {clave: {p, detalle, n, dispersion, pesos}}"""
    claves = set().union(*[set(p) for p in fuentes.values()]) if fuentes else set()
    out = {}
    for k in claves:
        if k.startswith("_"):
            continue
        disp = {s: probs[k] for s, probs in fuentes.items() if probs.get(k) is not None}
        if not disp:
            continue
        w = pesos(M.familia(k), list(disp), prior, calib, cfg)
        p = sum(w[s] * disp[s] for s in disp)
        out[k] = {"p": min(max(p, 1e-4), 1 - 1e-4), "detalle": disp, "pesos": w, "n": len(disp),
                  "dispersion": pstdev(disp.values()) if len(disp) > 1 else 0.0}
    return out
