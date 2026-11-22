"""Backtest 'walk-forward': prueba la estrategia en la última temporada sin mirar el futuro.

Para cada semana se reajusta el modelo solo con partidos anteriores, se combinan
modelo + mercado (Pinnacle de apertura, sin margen) y se 'apuesta' 1 unidad donde
la estrategia habría encontrado valor. Se mide contra dos tipos de cuota:
  - b365: una casa blanda típica (lo más parecido a Ecuabet)
  - max:  la mejor cuota del mercado (optimista: no siempre estará en Ecuabet)
CLV = cuánto mejor fue la cuota tomada frente a la de cierre de Pinnacle (sin margen).
Un CLV positivo sostenido es la mejor señal de que la ventaja es real.
"""
import numpy as np
import pandas as pd

from .ensamble import quitar_margen
from .fuentes import footballdata
from .modelos.goles import DixonColes

SEL = [("1x2:1", "1"), ("1x2:X", "X"), ("1x2:2", "2"), ("ou:2.5:over", "o"), ("ou:2.5:under", "u")]


def _sin_margen(fila, pref):
    out = {}
    for grupo in (("1", "X", "2"), ("o", "u")):
        cs = {g: fila.get(f"{pref}_{g}") for g in grupo}
        if all(pd.notna(v) and v > 1 for v in cs.values()):
            out |= quitar_margen(cs)
    return out


def liga(codigo: str, nombre: str, cfg: dict, df: pd.DataFrame | None = None) -> dict:
    df = footballdata.historico_con_cuotas(codigo) if df is None else df
    if len(df) < 500:
        return {}
    inicio_test = df["fecha"].max() - pd.Timedelta(days=330)
    pw = cfg["pesos_iniciales"]
    w_mod = pw["modelo"] / (pw["modelo"] + pw["mercado"])
    apuestas = []
    semanas = pd.date_range(inicio_test, df["fecha"].max() + pd.Timedelta(days=7), freq="7D")
    for a, b in zip(semanas[:-1], semanas[1:]):
        test = df[(df["fecha"] >= a) & (df["fecha"] < b)]
        if test.empty:
            continue
        train = df[(df["fecha"] < a) & (df["fecha"] >= a - pd.Timedelta(days=730))]
        m = DixonColes().ajustar(train)
        if not m.ok:
            continue
        for _, f in test.iterrows():
            fila = f.to_dict()
            pmod = m.probabilidades(f["local"], f["visita"])
            mkt, cierre = _sin_margen(fila, "ps"), _sin_margen(fila, "psc")
            if not pmod or not mkt:
                continue
            pm = {"1x2:1": pmod["1"], "1x2:X": pmod["X"], "1x2:2": pmod["2"],
                  "ou:2.5:over": pmod["over_2.5"], "ou:2.5:under": pmod["under_2.5"]}
            for fuente in ("b365", "max"):
                mejor = None
                for clave, suf in SEL:
                    if suf not in mkt or pd.isna(fila.get(f"{fuente}_{suf}")):
                        continue
                    p = (1 - w_mod) * mkt[suf] + w_mod * pm[clave]
                    o = float(fila[f"{fuente}_{suf}"])
                    ev = p * o - 1
                    acuerdo = (mkt[suf] * o > 1) + (pm[clave] * o > 1)
                    if not (cfg["cuota_min"] <= 1 / p <= cfg["cuota_max"]) or ev < cfg["ventaja_minima"] or acuerdo < 2:
                        continue
                    if mejor is None or ev > mejor["ev"]:
                        gl, gv = f["gl"], f["gv"]
                        gana = {"1": gl > gv, "X": gl == gv, "2": gl < gv, "o": gl + gv > 2.5, "u": gl + gv < 2.5}[suf]
                        mejor = {"fecha": f["fecha"], "liga": nombre, "fuente": fuente, "clave": clave, "p": p,
                                 "cuota": o, "ev": ev, "gana": gana, "ganancia": (o - 1) if gana else -1.0,
                                 "clv": (o * cierre[suf] - 1) if suf in cierre else np.nan}
                if mejor:
                    apuestas.append(mejor)
    return {"apuestas": apuestas}


def resumir(apuestas: list[dict]) -> dict:
    if not apuestas:
        return {}
    df = pd.DataFrame(apuestas).sort_values("fecha")
    out = {}
    for fuente, g in df.groupby("fuente"):
        g = g.copy()
        g["acum"] = g["ganancia"].cumsum()
        semanal = g.set_index("fecha")["ganancia"].resample("W").sum().cumsum()
        out[fuente] = {
            "n": int(len(g)), "acierto": float(g["gana"].mean()), "roi": float(g["ganancia"].mean()),
            "unidades": float(g["ganancia"].sum()), "cuota_media": float(g["cuota"].mean()),
            "clv": float(g["clv"].mean()) if g["clv"].notna().any() else None,
            "clv_positivo": float((g["clv"] > 0).mean()) if g["clv"].notna().any() else None,
            "max_racha_perdidas": int(max((len(list(x)) for k, x in __import__("itertools").groupby(g["gana"]) if not k), default=0)),
            "max_caida": float((g["acum"].cummax() - g["acum"]).max()),
            "curva": [{"f": d.strftime("%Y-%m-%d"), "u": round(float(v), 2)} for d, v in semanal.items()],
            "por_liga": {k: {"n": int(len(x)), "roi": float(x["ganancia"].mean())} for k, x in g.groupby("liga")},
            "por_mercado": {k: {"n": int(len(x)), "roi": float(x["ganancia"].mean())}
                            for k, x in g.groupby(g["clave"].str.split(":").str[0])},
        }
    return out


def correr(cfg: dict) -> dict:
    todas = []
    for lg in cfg["ligas"]:
        if lg.get("fd") and lg.get("tipo", "main") == "main":
            print(f"→ backtest {lg['nombre']}")
            todas += liga(lg["fd"], lg["nombre"], cfg).get("apuestas", [])
    return resumir(todas)
