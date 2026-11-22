"""Pruebas de: Forebet asíncrono (Apify) + contexto/cuotas de referencia, nivel Locas y combinadas exportadas."""
import json
import os
import sys

import pytest

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]

from picks import config, exportar, mercados as M, niveles, pipeline, tracker  # noqa: E402
from picks.fuentes import forebet  # noqa: E402

TOKEN = "tok_SECRETO_XYZ"


# ====================================================================== Forebet asíncrono
class Resp:
    def __init__(self, datos, status=200):
        self._d, self.status_code = datos, status

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            e = RuntimeError("HTTP")
            e.response = self
            raise e


class Red:
    """Apify falso: estados sucesivos del run y filas del dataset. Reloj falso que avanza con sleep()."""

    def __init__(self, estados, filas=None):
        self.estados, self.filas = list(estados), filas or []
        self.llamadas, self.t = [], 0.0

    def reloj(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def post(self, url, **kw):
        self.llamadas.append(("POST", url, kw))
        if url.endswith("/abort"):
            return Resp({"data": {"status": "ABORTING"}})
        return Resp({"data": {"id": "RUN1", "defaultDatasetId": "DS1", "status": "READY"}}, 201)

    def get(self, url, **kw):
        self.llamadas.append(("GET", url, kw))
        if "/datasets/" in url:
            return Resp(self.filas)
        est = self.estados.pop(0) if len(self.estados) > 1 else self.estados[0]
        return Resp({"data": {"id": "RUN1", "defaultDatasetId": "DS1", "status": est}})


@pytest.fixture
def fb_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(forebet, "DATOS", tmp_path)
    return tmp_path


def _fb(red, **kw):
    return forebet.Forebet(TOKEN, espera_max_seg=kw.pop("espera", 480), get=red.get, post=red.post,
                           sleep=red.sleep, reloj=red.reloj, **kw)


FILA = {"homeTeam": "Arsenal", "awayTeam": "Chelsea", "kickoffDate": "2026-11-22", "league": "EPL", "country": "Inglaterra",
        "probabilityHome": 50, "probabilityDraw": 25, "probabilityAway": 25, "oddsHome": 1.9, "oddsDraw": 3.5,
        "oddsAway": 4.2, "homeForm": "WWDLW", "awayPosition": 7, "trendNote": "Racha\nlocal", "valuePercent": 6.5}


def test_forebet_sondea_hasta_succeeded_y_lee_dataset(fb_dir):
    red = Red(["RUNNING", "RUNNING", "SUCCEEDED"], [FILA])
    out = _fb(red).predicciones(2)
    assert [r["local"] for r in out] == ["Arsenal"]
    metodos = [(m, u.split("/v2/")[1]) for m, u, _ in red.llamadas]
    assert metodos[0] == ("POST", "acts/solidcode~forebet-scraper/runs")
    assert [u for m, u in metodos if u.startswith("actor-runs/RUN1")] == ["actor-runs/RUN1"] * 3
    assert metodos[-1] == ("GET", "datasets/DS1/items")
    assert red.t == 20          # dos esperas de 10 s entre tres sondeos


def test_forebet_token_en_cabecera_nunca_en_la_url(fb_dir):
    red = Red(["SUCCEEDED"], [FILA])
    _fb(red).predicciones(1)
    for _, url, kw in red.llamadas:
        assert TOKEN not in url and "token" not in url.lower()
        assert "token" not in {k.lower() for k in (kw.get("params") or {})}
        assert kw["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_forebet_timeout_aborta_el_run_y_devuelve_vacio(fb_dir, capsys):
    red = Red(["RUNNING"], [])
    out = _fb(red, espera=60).predicciones(1)
    assert out == []
    assert any(m == "POST" and u.endswith("/actor-runs/RUN1/abort") for m, u, _ in red.llamadas)
    assert TOKEN not in capsys.readouterr().out
    assert not list(fb_dir.rglob("forebet_*.json")), "un fallo no se cachea"


@pytest.mark.parametrize("estado", ["FAILED", "ABORTED", "TIMED-OUT"])
def test_forebet_estados_terminales_malos_devuelven_vacio(fb_dir, estado, capsys):
    red = Red(["RUNNING", estado], [FILA])
    assert _fb(red).predicciones(1) == []
    assert estado in capsys.readouterr().out
    assert not any("/datasets/" in u for _, u, _ in red.llamadas)


def test_forebet_cache_6h_no_repite_la_corrida(fb_dir):
    red = Red(["SUCCEEDED"], [FILA])
    f = _fb(red)
    f.predicciones(1)
    n = len(red.llamadas)
    assert len(f.predicciones(1)) == 1
    assert len(red.llamadas) == n


# ====================================================================== contexto y cuotas de referencia
def test_ctx_estructura_completa_y_defensiva_sin_campos():
    ctx = forebet.extraer_ctx({"homeTeam": "A", "awayTeam": "B"})
    assert ctx == {"forma": {"local": None, "visita": None}, "posicion": {"local": None, "visita": None},
                   "tendencia": None, "marcador_previsto": None, "goles_prom": None, "valor_pct": None, "clima": None,
                   "cuotas_ref": {k: None for k in ("1", "X", "2", "o25", "u25", "btts_si", "btts_no")}}


def test_ctx_extrae_variantes_recorta_y_filtra_cuotas():
    fila = {**FILA, "formHome": "ignorada", "positionHome": "3rd", "predictedScore": "2-1",
            "predictedGoalsAverage": "2.7", "weather": {"temp": "12C", "desc": "lluvia"},
            "oddsOver25": 0.5, "oddsUnder25": 999, "oddsBttsYes": "1,8", "trendNote": "x" * 500 + "\nfin"}
    c = forebet.extraer_ctx(fila)
    assert c["forma"] == {"local": "WWDLW", "visita": None}
    assert c["posicion"] == {"local": 3, "visita": 7}
    assert c["marcador_previsto"] == "2-1" and c["goles_prom"] == pytest.approx(2.7)
    assert c["valor_pct"] == pytest.approx(6.5)
    assert c["clima"] == "12C lluvia"
    assert len(c["tendencia"]) == 200 and "\n" not in c["tendencia"]
    assert c["cuotas_ref"]["1"] == 1.9 and c["cuotas_ref"]["2"] == 4.2
    assert c["cuotas_ref"]["o25"] is None and c["cuotas_ref"]["u25"] is None      # fuera de 1.01–200
    assert c["cuotas_ref"]["btts_si"] == pytest.approx(1.8)


def test_predicciones_agrega_ctx_sin_tocar_probs(fb_dir):
    out = _fb(Red(["SUCCEEDED"], [FILA])).predicciones(1)
    assert out[0]["ctx"]["cuotas_ref"]["1"] == 1.9
    assert set(out[0]["probs"]) == {"1x2:1", "1x2:X", "1x2:2"}        # las cuotas no entran a probs/mercado
    assert not any("odds" in k or k == "mercado" for k in out[0]["probs"])


# ====================================================================== Locas
def _s(clave="1x2:2", p=0.20, real=6.0, ecua=None, ev_det=None, **kw):
    s = {"clave": clave, "nombre": clave, "mercado": "1X2", "p": p, "p_push": 0.0, "cuota_ecuabet": ecua,
         "mejor_cuota": real, "mejor_casa": "X", "n_fuentes": 3, "dispersion": 0.02, "acuerdo": 1.0, "confianza": 0.8,
         "detalle": ev_det or {"mercado": p, "modelo": p - 0.01, "forebet": p + 0.01}, "pesos": {}, "ia": None,
         "cuota_justa": 1 / p if p else 1.0, "cuota_minima": 1 / p if p else 1.0, "ev": None}
    s.update(kw)
    return s


def _pa(uid, sels, fecha="2026-11-22"):
    return {"uid": uid, "af_id": int(uid) if uid.isdigit() else 1, "liga": "L", "region": "Europa", "fecha": fecha,
            "inicio": f"{fecha}T20:00:00+00:00", "local": "A" + uid, "visita": "B" + uid, "evaluadas": sels}


def _cfg(**kw):
    cfg = config.cargar()
    cfg.update({"banca": 1000.0, "stake_minimo": 1.0})
    cfg.update(kw)
    return cfg


def test_locas_sin_cuota_real_no_genera_nada():
    sin_cuota = _s(real=None)           # plan gratis: solo cuota estimada
    assert niveles.locas([_pa("1", [sin_cuota])], _cfg()) == []


def test_locas_con_cuota_real_y_filtros_cumplidos():
    out = niveles.locas([_pa("1", [_s()])], _cfg())
    assert len(out) == 1
    s = out[0]
    assert s["nivel"] == "locas" and s["clave"] == "1x2:2"
    assert s["ev"] == pytest.approx(0.20 * 6.0 - 1)
    assert s["monto"] == pytest.approx(5.0)                  # 0.5% de 1000
    assert s["confirmado"] is False


@pytest.mark.parametrize("cambio", [
    dict(real=2.9),                                            # cuota < 3
    dict(real=12.5, p=0.2),                                    # cuota > 12
    dict(p=0.11, real=11.0),                                   # p < 0.12 (EV 0.21 pero p baja)
    dict(p=0.2, real=5.4),                                     # EV 0.08 < 0.10
    dict(dispersion=0.09),                                     # dispersión > max
    dict(n_fuentes=1, detalle={"mercado": 0.2}),               # < min_fuentes
    dict(detalle={"modelo": 0.2, "elo": 0.2, "penaltyblog": 0.2}),   # sin fuente externa
    dict(ia={"riesgo": "alto"}),
])
def test_locas_filtros_conservadores_rechazan(cambio):
    assert niveles.locas([_pa("1", [_s(**cambio)])], _cfg()) == []


def test_locas_nunca_mas_de_max_dia_y_respeta_exposicion():
    partidos = [_pa(str(i), [_s(real=6.0 + i * 0.1)]) for i in range(1, 8)]
    assert len(niveles.locas(partidos, _cfg())) == 3
    assert len(niveles.locas(partidos, _cfg(locas_max_dia=2))) == 2
    # exposición 1.5% de 1000 = 15 -> con 5.0 por pick caben 3; con tope 0.01 caben 2
    assert len(niveles.locas(partidos, _cfg(locas_max_dia=5, locas_exposicion_dia_pct=0.01))) == 2


def test_locas_no_repite_pick_ya_elegido_en_valor():
    pa = _pa("1", [_s()])
    assert niveles.locas([pa], _cfg(), excluir={("1", "1x2:2")}) == []


def test_picks_por_dia_incluye_locas_y_combinadas():
    d = pipeline.picks_por_dia([], _cfg())
    assert d == {}
    pa = {**_pa("1", []), "probs": {}, "ecuabet": {}, "mejores": {}}
    dias = pipeline.picks_por_dia([pa], _cfg())
    assert dias["2026-11-22"]["locas"] == [] and dias["2026-11-22"]["combinadas"] == []


def test_picks_por_dia_genera_un_pick_locas_real():
    detalle = {"mercado": 0.20, "modelo": 0.19, "forebet": 0.21}
    pa = {"uid": "7", "af_id": 7, "liga": "L", "region": "Europa", "fecha": "2026-11-22",
          "inicio": "2026-11-22T20:00:00+00:00", "local": "A", "visita": "B",
          "probs": {"1x2:2": {"p": 0.20, "detalle": detalle, "n": 3, "dispersion": 0.01, "pesos": {}}},
          "ecuabet": {}, "mejores": {"1x2:2": (6.0, "Casa")}}
    dias = pipeline.picks_por_dia([pa], _cfg())
    assert [s["clave"] for s in dias["2026-11-22"]["locas"]] == ["1x2:2"]


def test_exportar_locas_mismos_campos_que_valor_mas_nivel(tmp_path, monkeypatch):
    monkeypatch.setattr(exportar, "WEB", tmp_path / "w")
    s = niveles.locas([_pa("1", [_s()])], _cfg())
    dias = {"2026-11-22": {"valor": s, "alta": [], "seguras": [], "grandes": [], "locas": s, "combinadas": []}}
    partido = {**_pa("1", [_s()]), "fuentes": {"mercado": {}}, "probs": {"1x2:2": {"p": 0.2}}}
    exportar.hoy([partido], dias, _cfg(), "x")
    d = json.loads((tmp_path / "w" / "hoy.json").read_text(encoding="utf-8"))["dias"]["2026-11-22"]
    assert set(d["locas"][0]) == set(d["valor"][0]) | {"nivel", "stake"} and d["locas"][0]["nivel"] == "locas"
    assert "monto" not in d["locas"][0] and d["locas"][0]["stake"] == 0.005


# ---- tracker: tipo locas
def _pick_db(**kw):
    base = dict(uid="L1", af_id=1, liga="L", inicio="2026-11-20T15:00:00-05:00", local="A", visita="B",
                clave="1x2:2", nombre="Gana B", p=0.2, p_push=0, cuota_justa=5.0, cuota_minima=5.0,
                cuota_ecuabet=None, monto=5.0)
    base.update(kw)
    return base


def test_tracker_locas_registro_liquidacion_y_roi_separado(db):
    db.agregar_picks([_pick_db()], "locas")
    db.agregar_picks([_pick_db(uid="V1", clave="1x2:1", p=0.6, cuota_justa=1.7, cuota_minima=1.8)], "valor")
    assert db.registrar_web("L1", "1x2:2", 6.0, 5.0) and db.registrar_web("V1", "1x2:1", 2.0, 10)
    with db.con() as c:
        c.execute("INSERT INTO resultados (af_id, gl, gv) VALUES (1, 0, 1)")
        c.execute("UPDATE picks SET af_id=1")
    assert db.liquidar() == 2
    r = db.resumen()
    assert r["por_tipo"]["locas"]["n"] == 1
    assert r["por_tipo"]["locas"]["neto"] == pytest.approx(5.0 * 5.0)       # ganada: 5 * (6-1)
    assert r["por_tipo"]["valor"]["neto"] == pytest.approx(-10.0)
    pub = exportar.resumen_publico([dict(f) for f in db.con().execute("SELECT * FROM picks")])
    assert pub["por_tipo"]["locas"]["roi"] == pytest.approx(5.0)


# ====================================================================== Combinadas exportadas
def _legs(n=8):
    return [_pa(str(i), [_s(clave="1x2:1", p=0.80, real=1.40, ecua=1.40), ]) for i in range(1, n + 1)]


def test_combinadas_cuota_3_a_60_p_minima_y_tope():
    partidos = [_pa(str(i), [_s(clave="1x2:1", p=0.80, ecua=1.30, real=1.30),
                             _s(clave="ou:1.5:over", p=0.78, ecua=1.35, real=1.35)]) for i in range(1, 13)]
    out = niveles.combinadas(partidos, _cfg(grandes_monto=5.0))
    assert 1 <= len(out) <= 10
    for c in out:
        assert 3.0 <= c["cuota"] <= 60.0 and c["p"] >= 0.05 and c["objetivo"] is None
        uids = [s["uid"] for s in c["piernas"]]
        assert len(uids) == len(set(uids)) >= 2
    assert len({tuple(sorted((s["uid"], s["clave"]) for s in c["piernas"])) for c in out}) == len(out)


def test_combinadas_sin_piernas_suficientes_vacio():
    assert niveles.combinadas([_pa("1", [_s(clave="1x2:1", p=0.8, ecua=1.3, real=1.3)])], _cfg()) == []


def test_exportar_combinadas_y_forebet_ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(exportar, "WEB", tmp_path / "w")
    partidos = [_pa(str(i), [_s(clave="1x2:1", p=0.80, ecua=1.30, real=1.30)]) for i in range(1, 9)]
    comb = niveles.combinadas(partidos, _cfg(grandes_monto=5.0))
    assert comb
    ctx = forebet.extraer_ctx(FILA)
    for p in partidos:
        p.update({"fuentes": {"mercado": {}}, "probs": {"1x2:1": {"p": 0.8}}})
    partidos[0]["forebet_ctx"] = ctx
    exportar.hoy(partidos, {"2026-11-22": {"valor": [], "alta": [], "seguras": [], "grandes": [], "locas": [],
                                           "combinadas": comb}}, _cfg(), "x")
    h = json.loads((tmp_path / "w" / "hoy.json").read_text(encoding="utf-8"))
    c = h["dias"]["2026-11-22"]["combinadas"][0]
    assert c["objetivo"] is None and {"cuota", "p", "ev", "piernas", "cobro_total", "ganancia"} <= set(c)
    assert h["partidos"][0]["forebet_ctx"]["cuotas_ref"]["1"] == 1.9
    assert h["partidos"][1]["forebet_ctx"] is None


def test_pipeline_guarda_forebet_ctx_en_el_partido_emparejado():
    assert pipeline.contexto_forebet({"local": "Arsenal", "visita": "Chelsea"}, None) is None
    fb = {"ctx": {"x": 1}}
    assert pipeline.contexto_forebet({"local": "A"}, fb) == {"x": 1}
