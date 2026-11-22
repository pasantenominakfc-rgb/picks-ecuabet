"""Fixtures comunes: raíz del proyecto en sys.path y una base SQLite temporal por prueba."""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Apunta tracker.RUTA a una DB temporal (nunca toca datos/sistema.db)."""
    from picks import tracker
    monkeypatch.setattr(tracker, "RUTA", tmp_path / "sistema.db")
    return tracker


@pytest.fixture(autouse=True)
def _sin_internet_clubelo(monkeypatch, request):
    """Las pruebas nunca descargan ClubElo: por defecto no hay ratings (clubelo.descargar -> {})."""
    if request.module.__name__.endswith("test_clubelo"):   # esas pruebas ejercitan descargar() con peticiones inyectadas
        return
    try:
        from picks.fuentes import clubelo
    except ImportError:   # el módulo aún no existe
        return
    monkeypatch.setattr(clubelo, "descargar", lambda *a, **k: {})
