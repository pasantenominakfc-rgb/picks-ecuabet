"""Los logs y los JSON públicos no deben incluir el texto crudo de excepciones (pueden traer tokens en la URL)."""
import os
import sys
from datetime import datetime, timezone

import pytest
import requests

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]

from picks import config, pipeline  # noqa: E402
from picks.fuentes import forebet, ia  # noqa: E402

SECRETO = "tok_SECRETO_123"


class _ErrHTTP(requests.HTTPError):
    def __init__(self):
        super().__init__(f"403 Client Error: Forbidden for url: https://api.apify.com/x?token={SECRETO}")
        self.response = type("R", (), {"status_code": 403})()


def test_describir_error_solo_clase_y_codigo_http():
    from picks import errores
    assert errores.describir(RuntimeError(SECRETO)) == "RuntimeError"
    d = errores.describir(_ErrHTTP())
    assert "_ErrHTTP" in d and "403" in d and SECRETO not in d


def test_forebet_no_imprime_el_token(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(forebet, "DATOS", tmp_path)

    def post(*a, **k):
        raise _ErrHTTP()
    monkeypatch.setattr(requests, "post", post)
    assert forebet.Forebet(SECRETO).predicciones(1) == []
    out = capsys.readouterr().out
    assert SECRETO not in out and "_ErrHTTP" in out


def test_ia_no_imprime_texto_crudo_de_la_excepcion(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ia, "DATOS", tmp_path)

    def post(*a, **k):
        raise RuntimeError(f"Bearer {SECRETO}")
    monkeypatch.setattr(requests, "post", post)
    a = ia.AnalistaIA("k")
    assert a.analizar({"uid": "u", "clave": "1x2:1", "local": "A", "visita": "B", "inicio": "2030-01-01T00:00:00Z",
                       "nombre": "n", "p": .5}) is None
    out = capsys.readouterr().out
    assert SECRETO not in out and "RuntimeError" in out


class _AFFalla:
    activa, restantes, sin_cuota, cuota_agotada = True, 1, False, False

    def partidos(self, fecha, ligas=None):
        raise RuntimeError(f"url?apiKey={SECRETO}")

    def cuotas_liga(self, *a):
        return {}

    def prediccion(self, f):
        return None


def test_pipeline_no_imprime_ni_publica_el_mensaje_crudo(monkeypatch, capsys):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})
    cfg = config.cargar()
    ahora = datetime(2030, 6, 10, 15, 0, tzinfo=timezone.utc)
    res = pipeline.analizar(cfg, _AFFalla(), None, None, ahora, elo_ratings={})
    assert SECRETO not in capsys.readouterr().out
    assert SECRETO not in str(res.info)          # info["ligas_fallidas"] termina en hoy.json (público)
    assert res.info["ligas_fallidas"] and "RuntimeError" in res.info["ligas_fallidas"][0]["error"]


def test_pipeline_liga_que_falla_no_expone_mensaje(monkeypatch, capsys):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})

    class AF(_AFFalla):
        def partidos(self, fecha, ligas=None):
            return [{"af_id": 1, "liga_id": 39, "liga": "Premier League", "pais": "England", "local": "A", "visita": "B",
                     "inicio": "2030-06-10T20:00:00+00:00", "estado": "NS", "temporada": 2030}] if fecha == "2030-06-10" else []

        def cuotas_liga(self, *a):
            raise RuntimeError(f"apiKey={SECRETO}")

        def historico(self, *a, **k):
            import pandas as pd
            return pd.DataFrame()
    cfg = config.cargar()
    cfg["ligas"] = [cfg["ligas"][0]]
    res = pipeline.analizar(cfg, AF(), None, None, datetime(2030, 6, 10, 15, 0, tzinfo=timezone.utc), elo_ratings={})
    assert SECRETO not in capsys.readouterr().out and SECRETO not in str(res.info)
    assert "RuntimeError" in res.info["ligas_fallidas"][0]["error"]


def test_telegram_no_imprime_la_url_con_el_token(monkeypatch, capsys):
    import main
    monkeypatch.setenv("TELEGRAM_TOKEN", SECRETO)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    def post(url, **k):
        raise requests.ConnectionError(f"HTTPSConnectionPool: url: /bot{SECRETO}/sendMessage")
    monkeypatch.setattr(requests, "post", post)
    main.telegram("hola")
    assert SECRETO not in capsys.readouterr().out


def test_oddsapi_documenta_que_apikey_no_se_imprime():
    from picks.fuentes import oddsapi
    src = open(oddsapi.__file__, encoding="utf-8").read()
    assert "apiKey" in src and "NUNCA imprimir" in src
