"""Modelo para córners y tarjetas.

Cada equipo tiene una tasa de 'generar' y de 'conceder' (córners) o de 'recibir'
y 'provocar' (tarjetas), con ventaja de localía y decaimiento temporal. El total
del partido se modela con una binomial negativa, porque estos conteos varían más
que una Poisson (sobredispersión).
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import nbinom, poisson


class ModeloConteo:
    def __init__(self, xi: float = 0.0025):
        self.xi = xi
        self.ok = False

    def ajustar(self, df: pd.DataFrame, col_l: str, col_v: str, min_partidos: int = 80):
        df = df.dropna(subset=[col_l, col_v])
        if len(df) < min_partidos:
            return self
        self.equipos = sorted(set(df["local"]) | set(df["visita"]))
        idx = {e: i for i, e in enumerate(self.equipos)}
        n = len(self.equipos)
        h, a = df["local"].map(idx).to_numpy(), df["visita"].map(idx).to_numpy()
        x, y = df[col_l].to_numpy(float), df[col_v].to_numpy(float)
        w = np.exp(-self.xi * (df["fecha"].max() - df["fecha"]).dt.days.to_numpy())

        def nll(p):
            gen, con = p[:n], p[n:2 * n]
            c, hfa = p[-2], p[-1]
            lam = np.exp(c + hfa + gen[h] + con[a])
            mu = np.exp(c + gen[a] + con[h])
            ll = x * np.log(lam) - lam + y * np.log(mu) - mu
            return -(w * ll).sum() + 0.5 * (p[:2 * n] ** 2).sum()  # regularización (encoge a la media)

        p0 = np.concatenate([np.zeros(2 * n), [np.log(max((x.mean() + y.mean()) / 2, 0.5)), 0.05]])
        p = minimize(nll, p0, method="L-BFGS-B").x
        self.gen, self.con = dict(zip(self.equipos, p[:n])), dict(zip(self.equipos, p[n:2 * n]))
        self.c, self.hfa = p[-2], p[-1]
        # sobredispersión del total
        lam = np.exp(self.c + self.hfa + p[:n][h] + p[n:2 * n][a])
        mu = np.exp(self.c + p[:n][a] + p[n:2 * n][h])
        m, t = lam + mu, x + y
        self.phi = float(max(1.0, np.average((t - m) ** 2 / m, weights=w)))
        self.ok = True
        return self

    def esperado(self, local: str, visita: str) -> tuple[float, float] | None:
        if not self.ok or local not in self.gen or visita not in self.gen:
            return None
        lam = float(np.exp(self.c + self.hfa + self.gen[local] + self.con[visita]))
        mu = float(np.exp(self.c + self.gen[visita] + self.con[local]))
        return lam, mu

    def prob_mas_de(self, local: str, visita: str, lineas: list[float]) -> dict | None:
        e = self.esperado(local, visita)
        if not e:
            return None
        m = sum(e)
        if self.phi <= 1.01:
            cdf = lambda k: poisson.cdf(k, m)  # noqa: E731
        else:  # NB con media m y varianza phi*m
            pr = 1 / self.phi
            r = m * pr / (1 - pr)
            cdf = lambda k: nbinom.cdf(k, r, pr)  # noqa: E731
        return {ln: float(1 - cdf(np.floor(ln))) for ln in lineas} | {"_media": m}
