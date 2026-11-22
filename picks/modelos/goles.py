"""Modelo Dixon-Coles (Poisson bivariado corregido) con decaimiento temporal.

Estima ataque/defensa de cada equipo y ventaja de localía a partir de los
resultados recientes (los partidos viejos pesan menos), y de ahí obtiene la
probabilidad de cada marcador -> 1X2, Más/Menos 2.5 y Ambos Marcan.
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

XI = 0.0019        # decaimiento por día (vida media ~ 1 año)
MAX_GOLES = 10


class DixonColes:
    def __init__(self, xi: float = XI):
        self.xi = xi
        self.equipos: list[str] = []
        self.ok = False

    # ------------------------------------------------------------------ ajuste
    def ajustar(self, df: pd.DataFrame, min_partidos: int = 60) -> "DixonColes":
        if len(df) < min_partidos:
            return self
        self.equipos = sorted(set(df["local"]) | set(df["visita"]))
        idx = {e: i for i, e in enumerate(self.equipos)}
        n = len(self.equipos)
        h = df["local"].map(idx).to_numpy()
        a = df["visita"].map(idx).to_numpy()
        x = df["gl"].to_numpy()
        y = df["gv"].to_numpy()
        dias = (df["fecha"].max() - df["fecha"]).dt.days.to_numpy()
        w = np.exp(-self.xi * dias)

        def nll(p):
            ata = np.concatenate([p[: n - 1], [-p[: n - 1].sum()]])  # suma de ataques = 0
            dfn = p[n - 1: 2 * n - 1]
            hfa, rho = p[-2], p[-1]
            lam = np.exp(ata[h] + dfn[a] + hfa)
            mu = np.exp(ata[a] + dfn[h])
            tau = np.ones_like(lam)
            m00 = (x == 0) & (y == 0)
            m01 = (x == 0) & (y == 1)
            m10 = (x == 1) & (y == 0)
            m11 = (x == 1) & (y == 1)
            tau[m00] = 1 - lam[m00] * mu[m00] * rho
            tau[m01] = 1 + lam[m01] * rho
            tau[m10] = 1 + mu[m10] * rho
            tau[m11] = 1 - rho
            tau = np.clip(tau, 1e-10, None)
            ll = (np.log(tau) + x * np.log(lam) - lam + y * np.log(mu) - mu)
            return -(w * ll).sum() + 0.01 * (p[: 2 * n - 1] ** 2).sum()  # leve regularización

        p0 = np.concatenate([np.zeros(n - 1), np.zeros(n), [0.25, -0.05]])
        limites = [(-3, 3)] * (2 * n - 1) + [(-1, 1), (-0.3, 0.3)]
        res = minimize(nll, p0, method="L-BFGS-B", bounds=limites, options={"maxiter": 500})
        p = res.x
        self.ataque = dict(zip(self.equipos, np.concatenate([p[: n - 1], [-p[: n - 1].sum()]])))
        self.defensa = dict(zip(self.equipos, p[n - 1: 2 * n - 1]))
        self.hfa, self.rho = p[-2], p[-1]
        self.ok = True
        return self

    # ------------------------------------------------------------- predicción
    def goles_esperados(self, local: str, visita: str) -> tuple[float, float]:
        lam = np.exp(self.ataque[local] + self.defensa[visita] + self.hfa)
        mu = np.exp(self.ataque[visita] + self.defensa[local])
        return float(lam), float(mu)

    def matriz(self, local: str, visita: str) -> np.ndarray:
        lam, mu = self.goles_esperados(local, visita)
        g = np.arange(MAX_GOLES + 1)
        m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
        m[0, 0] *= 1 - lam * mu * self.rho
        m[0, 1] *= 1 + lam * self.rho
        m[1, 0] *= 1 + mu * self.rho
        m[1, 1] *= 1 - self.rho
        return m / m.sum()

    def mercados(self, local: str, visita: str, ht_factor: float = 0.45) -> dict | None:
        """Probabilidades para todos los mercados de goles (claves de picks.mercados)."""
        if not self.ok or local not in self.ataque or visita not in self.ataque:
            return None
        return mercados_desde_goles(self.matriz(local, visita), *self.goles_esperados(local, visita),
                                    ht_factor=ht_factor)

    def probabilidades(self, local: str, visita: str) -> dict | None:
        if not self.ok or local not in self.ataque or visita not in self.ataque:
            return None
        m = self.matriz(local, visita)
        tot = np.add.outer(np.arange(MAX_GOLES + 1), np.arange(MAX_GOLES + 1))
        lam, mu = self.goles_esperados(local, visita)
        return {
            "1": float(np.tril(m, -1).sum()),
            "X": float(np.trace(m)),
            "2": float(np.triu(m, 1).sum()),
            "over_2.5": float(m[tot >= 3].sum()),
            "under_2.5": float(m[tot <= 2].sum()),
            "btts_si": float(m[1:, 1:].sum()),
            "xg_local": lam,
            "xg_visita": mu,
        }


def mercados_desde_goles(m: np.ndarray, lam: float, mu: float, ht_factor: float = 0.45) -> dict:
    from ..mercados import LINEAS

    g = np.arange(m.shape[0])
    gl, gv = np.meshgrid(g, g, indexing="ij")
    tot = gl + gv
    p1, px, p2 = float(m[gl > gv].sum()), float(m[gl == gv].sum()), float(m[gl < gv].sum())
    out = {"1x2:1": p1, "1x2:X": px, "1x2:2": p2,
           "dc:1X": p1 + px, "dc:12": p1 + p2, "dc:X2": px + p2,
           "dnb:1": p1 / (p1 + p2), "dnb:2": p2 / (p1 + p2),
           "btts:si": float(m[1:, 1:].sum())}
    out["btts:no"] = 1 - out["btts:si"]
    for ln in LINEAS["ou"]:
        out[f"ou:{ln}:over"] = float(m[tot > ln].sum())
        out[f"ou:{ln}:under"] = 1 - out[f"ou:{ln}:over"]
    for fam, arr in (("tl", gl), ("tv", gv)):
        for ln in LINEAS[fam]:
            out[f"{fam}:{ln}:over"] = float(m[arr > ln].sum())
            out[f"{fam}:{ln}:under"] = 1 - out[f"{fam}:{ln}:over"]
    for ln in LINEAS["ah"]:
        out[f"ah:{ln:+}:1"] = float(m[gl + ln > gv].sum())
        out[f"ah:{ln:+}:2"] = 1 - out[f"ah:{ln:+}:1"]
    # primer tiempo: Poisson independiente con ~45% de los goles esperados
    hl, hv = poisson.pmf(g, lam * ht_factor), poisson.pmf(g, mu * ht_factor)
    h = np.outer(hl, hv)
    h /= h.sum()
    out["ht1x2:1"], out["ht1x2:X"], out["ht1x2:2"] = (float(h[gl > gv].sum()), float(h[gl == gv].sum()),
                                                      float(h[gl < gv].sum()))
    for ln in LINEAS["htou"]:
        out[f"htou:{ln}:over"] = float(h[tot > ln].sum())
        out[f"htou:{ln}:under"] = 1 - out[f"htou:{ln}:over"]
    out["_xg_local"], out["_xg_visita"] = lam, mu
    return out
