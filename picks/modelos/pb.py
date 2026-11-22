"""Modelo de goles de la librería penaltyblog (Poisson bivariado), como fuente independiente."""
import pandas as pd

from .goles import mercados_desde_goles

try:
    import penaltyblog as pb
except Exception:  # noqa: BLE001
    pb = None


class ModeloPB:
    def __init__(self, xi: float = 0.0019):
        self.xi, self.ok, self.m = xi, False, None
        self.equipos: list[str] = []

    def ajustar(self, df: pd.DataFrame, min_partidos: int = 60):
        if pb is None or len(df) < min_partidos:
            return self
        try:
            w = pb.models.dixon_coles_weights(df["fecha"], self.xi)
            self.m = pb.models.BivariatePoissonGoalModel(df["gl"].astype(int), df["gv"].astype(int),
                                                         df["local"], df["visita"], weights=w)
            self.m.fit()
            self.equipos = sorted(set(df["local"]) | set(df["visita"]))
            self.ok = True
        except Exception as e:  # noqa: BLE001
            print(f"  ! penaltyblog: {e}")
        return self

    def mercados(self, local: str, visita: str) -> dict | None:
        if not self.ok or local not in self.equipos or visita not in self.equipos:
            return None
        g = self.m.predict(local, visita, max_goals=10)
        return mercados_desde_goles(g.goal_matrix, g.home_goal_expectation, g.away_goal_expectation)
