"""Carga de configuración."""
import math
import os
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"
REPORTES = RAIZ / "reportes"


def cargar(ruta: str | Path | None = None) -> dict:
    ruta = Path(ruta) if ruta else RAIZ / "config.yaml"
    with open(ruta, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for var in ("API_FOOTBALL_KEY", "ODDS_API_KEY", "APIFY_TOKEN", "GROQ_API_KEY"):
        cfg[var.lower()] = os.environ.get(var, cfg.get(var.lower(), "")) or ""
    banca = (os.environ.get("BANCA") or "").strip()
    if banca:
        try:
            v = float(banca.replace(",", "."))
            if not math.isfinite(v) or v <= 0:
                raise ValueError
            cfg["banca"] = v
        except ValueError:
            print(f"! BANCA='{banca}' no es un número válido mayor que 0: se ignora y se usa banca={cfg.get('banca')} de config.yaml")
    DATOS.mkdir(exist_ok=True)
    (DATOS / "cache").mkdir(exist_ok=True)
    REPORTES.mkdir(exist_ok=True)
    return cfg
