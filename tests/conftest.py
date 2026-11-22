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
