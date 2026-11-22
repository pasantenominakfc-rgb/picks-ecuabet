"""Carga de configuración."""
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
    if os.environ.get("BANCA"):
        cfg["banca"] = float(os.environ["BANCA"])
    DATOS.mkdir(exist_ok=True)
    (DATOS / "cache").mkdir(exist_ok=True)
    REPORTES.mkdir(exist_ok=True)
    return cfg
