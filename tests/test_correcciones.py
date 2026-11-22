"""Correcciones tras la revisión: Locas robustas, acuerdo por grupo, combinadas sin duplicar Grandes, tracker,
Forebet (robustez, parcial, caché) y secretos en logs."""
import os
import sys
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]

import main  # noqa: E402
from picks import niveles, pipeline, seleccion, tracker  # noqa: E402
from picks.fuentes import footballdata, forebet  # noqa: E402
from picks.fuentes.ia import AnalistaIA  # noqa: E402
from picks.modelos import pb as modelo_pb  # noqa: E402
from test_locas_forebet import FILA, TOKEN, Red, Resp, _cfg, _fb, _pa, _s, fb_dir  # noqa: E402,F401

SECRETO = "tok_SECRETO_123"
NAN = float("nan")


# ====================================================================== LOCAS
@pytest.mark.parametrize("campo", ["p", "dispersion", "acuerdo", "confianza", "mejor_cuota"])
def test_locas_nan_no_desplaza_a_una_valida(campo):
    mala = _pa("1", [_s(**{campo: NAN})])
    buena = _pa("2", [_s()])
    out = niveles.locas([mala, buena], _cfg(locas_max_dia=1))
    assert [s["uid"] for s in out] == ["2"]


@pytest.mark.parametrize("p", [0.0, 1.0, -0.1, 1.5])
def test_locas_p_fuera_de_rango_se_descarta(p):
    assert niveles.locas([_pa("1", [_s(p=p, real=6.0, cuota_justa=1.0, cuota_minima=1.0)])], _cfg()) == []


def test_locas_excluir_normaliza_uid_a_texto():
    assert niveles.locas([_pa("1", [_s()])], _cfg(), excluir={(1, "1x2:2")}) == []


def test_locas_excluye_dnb():
    assert niveles.locas([_pa("1", [_s(clave="dnb:2")])], _cfg()) == []


def test_locas_excluye_todo_el_partido_con_otro_pick():
    pa = _pa("1", [_s(clave="1x2:2"), _s(clave="ou:2.5:over", p=0.2, real=6.0)])
    assert niveles.locas([pa], _cfg(), excluir_uids={"1"}) == []
    assert len(niveles.locas([pa], _cfg())) == 1


def test_picks_por_dia_no_da_loca_en_un_partido_que_ya_tiene_valor():
    det = {"mercado": 0.6, "modelo": 0.6, "forebet": 0.6}
    det2 = {"mercado": 0.20, "modelo": 0.19, "forebet": 0.21}
    pa = {"uid": "7", "af_id": 7, "liga": "L", "region": "Europa", "fecha": "2026-11-22",
          "inicio": "2026-11-22T20:00:00+00:00", "local": "A", "visita": "B",
          "probs": {"1x2:1": {"p": 0.6, "detalle": det, "n": 3, "dispersion": 0.01, "pesos": {}},
                    "1x2:2": {"p": 0.2, "detalle": det2, "n": 3, "dispersion": 0.01, "pesos": {}}},
          "ecuabet": {"1x2:1": 2.0}, "mejores": {"1x2:2": (6.0, "Casa")}}
    d = pipeline.picks_por_dia([pa], _cfg())["2026-11-22"]
    assert d["valor"], "debe haber Valor"
    assert d["locas"] == []


def test_locas_avisa_una_vez_si_la_banca_no_alcanza(capsys, monkeypatch):
    monkeypatch.setattr(niveles, "_AVISO_LOCAS", False, raising=False)
    cfg = _cfg(banca=50.0)      # stake mínimo 1.0 > 1.5% de 50 (0.75): ninguna Loca entra
    assert niveles.locas([_pa("1", [_s()])], cfg) == []
    assert niveles.locas([_pa("2", [_s()])], cfg) == []
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1 and "banca" in out.lower()


def test_locas_banca_100_admite_una_y_200_admiten_tres():
    partidos = [_pa(str(i), [_s(real=6.0 + i * 0.1)]) for i in range(1, 6)]
    assert len(niveles.locas(partidos, _cfg(banca=100.0))) == 1
    assert len(niveles.locas(partidos, _cfg(banca=200.0))) == 3


# ====================================================================== IA revisa Locas
def test_candidatos_ia_incluye_locas_y_piernas_de_grandes():
    loca, seg, valor = {"uid": "a", "clave": "1x2:2"}, {"uid": "b", "clave": "1x2:1"}, {"uid": "c", "clave": "1x2:1"}
    pierna = {"uid": "d", "clave": "1x2:1"}
    dias = {"2026-11-22": {"valor": [valor], "seguras": [seg], "locas": [loca], "grandes": [{"piernas": [pierna]}]},
            "2026-11-23": {"valor": [], "seguras": [], "locas": [], "grandes": []},
            "2026-11-30": {"valor": [], "seguras": [], "locas": [{"uid": "z", "clave": "x"}], "grandes": []}}
    c = pipeline.candidatos_ia(dias)
    assert {x["uid"] for x in c} == {"a", "b", "c", "d"}      # solo hoy y mañana (2 primeras fechas)


def test_ia_revisa_primero_las_locas_cuando_hay_tope():
    orden = []

    class IA(AnalistaIA):
        def analizar(self, s):
            orden.append(s["clave"])
            return None
    pa = {"uid": "1", "fuentes": {}, "probs": {"1x2:1": {"p": 0.9, "detalle": {}}, "1x2:2": {"p": 0.2, "detalle": {}}}}
    IA("k").revisar([pa], [{"uid": "1", "clave": "1x2:1", "p": 0.9},
                           {"uid": "1", "clave": "1x2:2", "p": 0.2, "nivel": "locas"}], {})
    assert orden[0] == "1x2:2"


# ====================================================================== ACUERDO por grupo estadístico
def _partido_acuerdo(detalle, ecuabet=3.0):
    return {"uid": "u", "af_id": 1, "liga": "L", "region": "Europa", "fecha": "2026-01-01",
            "inicio": "2026-01-01T20:00:00+00:00", "local": "A", "visita": "B",
            "probs": {"1x2:1": {"p": 0.4, "detalle": detalle, "n": len(detalle), "dispersion": 0.01, "pesos": {}}},
            "ecuabet": {"1x2:1": ecuabet}, "mejores": {}}


def test_acuerdo_el_grupo_estadistico_vota_una_sola_vez():
    det = {"mercado": 0.2, "modelo": 0.4, "penaltyblog": 0.4, "elo": 0.4}    # mercado en contra (0.2*3 < 1)
    s = seleccion.evaluar(_partido_acuerdo(det), _cfg())[0]
    assert s["acuerdo"] == pytest.approx(0.5) and s["acuerdo"] < _cfg()["min_acuerdo"]


def test_acuerdo_grupo_por_mayoria_de_sus_miembros():
    det = {"mercado": 0.4, "modelo": 0.4, "penaltyblog": 0.4, "elo": 0.2}    # 2 de 3 del grupo ven valor
    assert seleccion.evaluar(_partido_acuerdo(det), _cfg())[0]["acuerdo"] == pytest.approx(1.0)
    det = {"mercado": 0.4, "modelo": 0.4, "elo": 0.2}                        # 1 de 2: no es mayoría
    assert seleccion.evaluar(_partido_acuerdo(det), _cfg())[0]["acuerdo"] == pytest.approx(0.5)


# ====================================================================== COMBINADAS vs GRANDES
def test_combinadas_sin_objetivos_de_grandes():
    assert 20 not in niveles._OBJETIVOS_COMB and 40 not in niveles._OBJETIVOS_COMB and 100 not in niveles._OBJETIVOS_COMB


def _dia_con_grandes():
    cfg = _cfg(grandes_monto=5.0, grandes_objetivos=[30])
    partidos = []
    for i in range(1, 11):
        det = {"mercado": 0.8, "modelo": 0.8, "forebet": 0.8}
        partidos.append({"uid": str(i), "af_id": i, "liga": "L", "region": "Europa", "fecha": "2026-11-22",
                         "inicio": "2026-11-22T20:00:00+00:00", "local": f"A{i}", "visita": f"B{i}",
                         "probs": {"1x2:1": {"p": 0.8, "detalle": det, "n": 3, "dispersion": 0.01, "pesos": {}}},
                         "ecuabet": {"1x2:1": 1.30}, "mejores": {}})
    return partidos, cfg


def test_combinadas_no_repite_las_piernas_de_grandes():
    partidos, cfg = _dia_con_grandes()
    d = pipeline.picks_por_dia(partidos, cfg)["2026-11-22"]
    assert d["grandes"], "el escenario debe producir una Grande"
    claves = lambda c: frozenset((s["uid"], s["clave"]) for s in c["piernas"])  # noqa: E731
    gr = {claves(c) for c in d["grandes"]}
    assert all(claves(c) not in gr for c in d["combinadas"])


# ====================================================================== TRACKER
def _pk(**kw):
    base = dict(uid="U1", af_id=1, liga="L", inicio="2026-11-20T15:00:00-05:00", local="A", visita="B", clave="1x2:2",
                nombre="loca", p=0.2, p_push=0, cuota_justa=5.0, cuota_minima=5.0, cuota_ecuabet=None, monto=1.0)
    base.update(kw)
    return base


def _fila(db):
    with db.con() as c:
        return dict(c.execute("SELECT * FROM picks WHERE uid='U1' AND clave='1x2:2'").fetchone())


def test_agregar_picks_reclasifica_pendiente_no_registrado(db):
    db.agregar_picks([_pk()], "locas")
    db.agregar_picks([_pk(nombre="valor", p=0.25, cuota_ecuabet=5.5, monto=3.0)], "valor")      # 13:00: ahora es Valor
    f = _fila(db)
    assert f["tipo"] == "valor" and f["p"] == pytest.approx(0.25) and f["monto"] == pytest.approx(3.0)
    with db.con() as c:
        assert c.execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 1


def test_agregar_picks_no_toca_lo_registrado_ni_lo_omitido(db):
    db.agregar_picks([_pk()], "locas")
    assert db.registrar_web("U1", "1x2:2", 6.0, 2.0)
    db.agregar_picks([_pk(p=0.5)], "valor")
    assert _fila(db)["tipo"] == "locas" and _fila(db)["p"] == pytest.approx(0.2)
    db.omitir_web("U1", "1x2:2")
    db.agregar_picks([_pk(p=0.5)], "valor")
    assert _fila(db)["tipo"] == "locas" and _fila(db)["estado"] == "no_apostada"


# ====================================================================== FOREBET
def test_forebet_aborta_si_falla_algo_tras_crear_el_run(fb_dir):
    red = Red(["SUCCEEDED"], [FILA])

    def reloj():
        raise RuntimeError("reloj roto")
    f = forebet.Forebet(TOKEN, get=red.get, post=red.post, sleep=red.sleep, reloj=reloj)
    assert f.predicciones(1) == []
    assert any(m == "POST" and u.endswith("/actor-runs/RUN1/abort") for m, u, _ in red.llamadas)


def test_forebet_timeout_intenta_leer_resultado_parcial_una_vez(fb_dir):
    red = Red(["RUNNING"], [FILA])
    out = _fb(red, espera=60).predicciones(1)
    assert [r["local"] for r in out] == ["Arsenal"]
    assert sum("/datasets/" in u for _, u, _ in red.llamadas) == 1
    assert not list(fb_dir.rglob("forebet_*.json")), "un parcial no se cachea"


def test_forebet_cache_que_no_es_lista_se_ignora(fb_dir):
    from picks.pipeline import hoy_ec
    (fb_dir / "cache").mkdir()
    (fb_dir / "cache" / f"forebet_{hoy_ec()}.json").write_text('{"x": 1}', encoding="utf-8")
    red = Red(["SUCCEEDED"], [FILA])
    assert len(_fb(red).predicciones(1)) == 1
    assert any(m == "POST" for m, _, _ in red.llamadas)


def test_forebet_cache_utf8_con_caracteres_no_cp1252(fb_dir):
    fila = {**FILA, "homeTeam": "Łódź", "awayTeam": "Śląsk"}
    red = Red(["SUCCEEDED"], [fila])
    assert _fb(red).predicciones(1)[0]["local"] == "Łódź"
    assert _fb(Red(["SUCCEEDED"], [])).predicciones(1)[0]["visita"] == "Śląsk"      # segunda: desde la caché


def test_forebet_espera_por_defecto_sigue_en_480():
    assert forebet.Forebet("t").espera_max_seg == 480
    assert main.config.cargar()["forebet_espera_max_seg"] == 480


# ====================================================================== SEGURIDAD
def test_verificar_apify_usa_cabecera_no_params(monkeypatch):
    vistos = {}

    def get(url, **kw):
        vistos.update(url=url, **kw)
        return SimpleNamespace(ok=True, status_code=200)
    monkeypatch.setattr(main.requests, "get", get)
    assert main._apify_valido(SECRETO)[0] is True
    assert "params" not in vistos and SECRETO not in vistos["url"]
    assert vistos["headers"]["Authorization"] == f"Bearer {SECRETO}"


def test_verificar_no_imprime_texto_crudo_de_la_excepcion(monkeypatch, capsys):
    class AF:
        def __init__(self, *a):
            pass

        def _get(self, *a, **k):
            raise RuntimeError(f"url?apiKey={SECRETO}")
    monkeypatch.setattr(main, "APIFootball", AF)
    assert main.verificar({"api_football_key": "k"}) is False
    out = capsys.readouterr().out
    assert SECRETO not in out and "RuntimeError" in out


def test_registrar_lote_no_imprime_texto_crudo_si_falla_la_exportacion(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "registrar-lote"])
    monkeypatch.setenv("LOTE", "[]")
    monkeypatch.setattr(main, "registrar_lote", lambda raw: 0)

    def malo():
        raise RuntimeError(f"Bearer {SECRETO}")
    monkeypatch.setattr(main.exportar, "historial", malo)
    with pytest.raises(SystemExit):
        main.main()
    out = capsys.readouterr().out
    assert SECRETO not in out and "RuntimeError" in out


def test_footballdata_no_imprime_texto_crudo(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(footballdata, "DATOS", tmp_path)

    def get(*a, **k):
        raise RuntimeError(f"fallo {SECRETO}")
    monkeypatch.setattr(requests, "get", get)
    assert footballdata._bajar("https://x/y.csv", "y.csv") is None
    out = capsys.readouterr().out
    assert SECRETO not in out and "RuntimeError" in out


def test_penaltyblog_no_imprime_texto_crudo(monkeypatch, capsys):
    def malo(*a, **k):
        raise RuntimeError(f"fallo {SECRETO}")
    monkeypatch.setattr(modelo_pb, "pb", SimpleNamespace(models=SimpleNamespace(dixon_coles_weights=malo)))
    modelo_pb.ModeloPB().ajustar(pd.DataFrame({"fecha": range(80)}))
    out = capsys.readouterr().out
    assert SECRETO not in out and "RuntimeError" in out
