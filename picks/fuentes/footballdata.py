"""Histórico de football-data.co.uk (gratis): goles, medio tiempo, córners y tarjetas."""
import io
import time

import pandas as pd
import requests

from ..config import DATOS

BASE = "https://www.football-data.co.uk"
COLS = ["fecha", "local", "visita", "gl", "gv", "htl", "htv", "cl", "cv", "tjl", "tjv"]


def _temporadas(n: int = 2) -> list[str]:
    from ..pipeline import hoy_ec  # import tardío: evita ciclo
    hoy = hoy_ec()
    ini = hoy.year if hoy.month >= 7 else hoy.year - 1
    return [f"{(ini - i) % 100:02d}{(ini - i + 1) % 100:02d}" for i in range(n)]


def _bajar(url: str, cache: str, horas: float = 12) -> str | None:
    ruta = DATOS / "cache" / cache
    ruta.parent.mkdir(exist_ok=True)
    if ruta.exists() and time.time() - ruta.stat().st_mtime < horas * 3600:
        return ruta.read_text(encoding="latin-1")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        ruta.write_bytes(r.content)
        return r.content.decode("latin-1")
    except Exception as e:  # noqa: BLE001
        print(f"  ! football-data {url}: {e}")
        return ruta.read_text(encoding="latin-1") if ruta.exists() else None


def historico(codigo: str, tipo: str = "main", peso_roja: int = 1) -> pd.DataFrame:
    marcos = []
    if tipo == "main":
        for t in _temporadas(2):
            txt = _bajar(f"{BASE}/mmz4281/{t}/{codigo}.csv", f"fd_{codigo}_{t}.csv")
            if not txt:
                continue
            d = pd.read_csv(io.StringIO(txt), on_bad_lines="skip")
            g = lambda c: d[c] if c in d else None  # noqa: E731
            marcos.append(pd.DataFrame({
                "fecha": d.get("Date"), "local": d.get("HomeTeam"), "visita": d.get("AwayTeam"),
                "gl": g("FTHG"), "gv": g("FTAG"), "htl": g("HTHG"), "htv": g("HTAG"),
                "cl": g("HC"), "cv": g("AC"),
                "tjl": (d["HY"] + peso_roja * d["HR"]) if {"HY", "HR"} <= set(d) else None,
                "tjv": (d["AY"] + peso_roja * d["AR"]) if {"AY", "AR"} <= set(d) else None}))
    else:
        txt = _bajar(f"{BASE}/new/{codigo}.csv", f"fd_{codigo}_all.csv")
        if txt:
            d = pd.read_csv(io.StringIO(txt), on_bad_lines="skip")
            marcos.append(pd.DataFrame({"fecha": d["Date"], "local": d["Home"], "visita": d["Away"],
                                        "gl": d["HG"], "gv": d["AG"]}))
    if not marcos:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(marcos, ignore_index=True).reindex(columns=COLS)
    df["fecha"] = pd.to_datetime(df["fecha"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["fecha", "local", "visita", "gl", "gv"])
    df = df[df["fecha"] >= pd.Timestamp.today() - pd.Timedelta(days=730)]
    return df.sort_values("fecha").reset_index(drop=True)


# Columnas de cuotas de football-data: Pinnacle apertura/cierre, Bet365 y la máxima del mercado
CUOTAS = {
    "ps": ("PSH", "PSD", "PSA", "P>2.5", "P<2.5"),
    "psc": ("PSCH", "PSCD", "PSCA", "PC>2.5", "PC<2.5"),
    "b365": ("B365H", "B365D", "B365A", "B365>2.5", "B365<2.5"),
    "max": ("MaxH", "MaxD", "MaxA", "Max>2.5", "Max<2.5"),
}


def historico_con_cuotas(codigo: str, temporadas: int = 3) -> pd.DataFrame:
    """Partidos con resultado y cuotas (solo ligas 'main') para el backtest."""
    marcos = []
    for t in _temporadas(temporadas):
        txt = _bajar(f"{BASE}/mmz4281/{t}/{codigo}.csv", f"fd_{codigo}_{t}.csv", horas=24 * 7)
        if not txt:
            continue
        d = pd.read_csv(io.StringIO(txt), on_bad_lines="skip")
        out = pd.DataFrame({"fecha": d.get("Date"), "local": d.get("HomeTeam"), "visita": d.get("AwayTeam"),
                            "gl": d.get("FTHG"), "gv": d.get("FTAG")})
        for pref, cols in CUOTAS.items():
            alternativas = {"MaxH": "BbMxH", "MaxD": "BbMxD", "MaxA": "BbMxA", "Max>2.5": "BbMx>2.5", "Max<2.5": "BbMx<2.5"}
            for suf, c in zip(("1", "X", "2", "o", "u"), cols):
                col = c if c in d else alternativas.get(c)
                out[f"{pref}_{suf}"] = d[col] if col in d else None
        marcos.append(out)
    if not marcos:
        return pd.DataFrame()
    df = pd.concat(marcos, ignore_index=True)
    df["fecha"] = pd.to_datetime(df["fecha"], dayfirst=True, errors="coerce")
    return df.dropna(subset=["fecha", "local", "visita", "gl", "gv"]).sort_values("fecha").reset_index(drop=True)
