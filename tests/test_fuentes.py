"""Pruebas de fuentes: API-Football (_fixture, estadísticas, reintentos, limitador), The Odds API,
bucle por liga del pipeline, ensamble con pesos 0 y zona horaria."""
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]

from picks import ensamble, pipeline  # noqa: E402
from picks.fuentes import apifootball, footballdata, oddsapi  # noqa: E402
from picks.fuentes.apifootball import APIFootball  # noqa: E402
from picks.fuentes.oddsapi import OddsAPI  # noqa: E402


# ------------------------------------------------------------ _fixture
def _fx(estado, goals, fulltime, halftime=(1, 0)):
    return {"fixture": {"id": 1, "date": "2026-01-01T20:00:00-05:00", "status": {"short": estado}},
            "league": {"id": 9, "season": 2025, "name": "L", "country": "C"},
            "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
            "goals": {"home": goals[0], "away": goals[1]},
            "score": {"halftime": {"home": halftime[0], "away": halftime[1]},
                      "fulltime": {"home": fulltime[0], "away": fulltime[1]},
                      "extratime": {"home": 1, "away": 0}, "penalty": {"home": None, "away": None}}}


def test_fixture_ft_usa_goals():
    f = APIFootball._fixture(_fx("FT", (2, 1), (2, 1)))
    assert (f["gl"], f["gv"], f["htl"], f["htv"]) == (2, 1, 1, 0)


def test_fixture_aet_usa_los_90_minutos():
    f = APIFootball._fixture(_fx("AET", (3, 2), (2, 2)))
    assert (f["gl"], f["gv"]) == (2, 2)
    assert (f["htl"], f["htv"]) == (1, 0)


def test_fixture_pen_usa_los_90_minutos():
    f = APIFootball._fixture(_fx("PEN", (6, 5), (1, 1)))
    assert (f["gl"], f["gv"]) == (1, 1)


# ------------------------------------------------------- estadísticas
def _eq(c, y, r, centinelas=True):
    """Estadísticas de un equipo. centinelas=True: trae 'Total Shots' (el equipo 'tiene cobertura')."""
    st = [{"type": "Corner Kicks", "value": c}, {"type": "Yellow Cards", "value": y},
          {"type": "Red Cards", "value": r}]
    st.append({"type": "Total Shots", "value": 9 if centinelas else None})
    st.append({"type": "Ball Possession", "value": "55%" if centinelas else None})
    return {"statistics": st}


def _stats(corners_l, corners_v, yel=(2, 1), red=(0, 1)):
    return {"response": [_eq(corners_l, yel[0], red[0]), _eq(corners_v, yel[1], red[1])]}


def _af_con(datos):
    af = APIFootball("k")
    af._get = lambda *a, **k: datos
    return af


def test_estadisticas_completas_con_peso_roja():
    assert _af_con(_stats(5, 4)).estadisticas(1, peso_roja=1) == {"corners": 9, "cards": 4}
    assert _af_con(_stats(5, 4)).estadisticas(1, peso_roja=2) == {"corners": 9, "cards": 5}


def test_estadisticas_con_cobertura_corners_null_cuenta_como_cero():
    assert _af_con(_stats(5, None)).estadisticas(1) == {"corners": 5, "cards": 4}


def test_estadisticas_con_cobertura_tarjetas_null_cuentan_como_cero():
    assert _af_con(_stats(5, 4, yel=(2, None), red=(None, None))).estadisticas(1) == {"corners": 9, "cards": 2}
    assert _af_con(_stats(3, 4, yel=(None, None), red=(None, None))).estadisticas(1) == {"corners": 7, "cards": 0}


def test_estadisticas_roja_null_si_cuenta_como_cero():
    assert _af_con(_stats(5, 4, red=(None, None))).estadisticas(1) == {"corners": 9, "cards": 3}


def test_estadisticas_equipo_sin_ninguna_centinela_es_sin_dato():
    d = {"response": [_eq(5, 2, 0), _eq(None, None, None, centinelas=False)]}
    assert _af_con(d).estadisticas(1) == {}
    d = {"response": [_eq(None, None, None, centinelas=False), _eq(None, None, None, centinelas=False)]}
    assert _af_con(d).estadisticas(1) == {}


def test_estadisticas_lista_faltante_o_incompleta_es_sin_dato():
    assert _af_con({"response": []}).estadisticas(1) == {}
    assert _af_con({}).estadisticas(1) == {}
    assert _af_con({"response": [_eq(5, 2, 0)]}).estadisticas(1) == {}      # un solo equipo


def test_estadisticas_centinela_no_numerica_cuenta_como_cobertura():
    eq = {"statistics": [{"type": "Ball Possession", "value": "45%"}, {"type": "Corner Kicks", "value": None},
                         {"type": "Yellow Cards", "value": None}]}
    assert _af_con({"response": [eq, eq]}).estadisticas(1) == {"corners": 0, "cards": 0}


def test_estadisticas_valor_no_numerico_es_sin_dato_y_no_lanza():
    assert _af_con(_stats("N/A", 4)).estadisticas(1) == {}
    assert _af_con(_stats(5, 4, yel=("x", 1))).estadisticas(1) == {}
    assert _af_con(_stats(5, 4, red=(0, "?"))).estadisticas(1) == {}


def test_estadisticas_nunca_lanza_con_datos_malformados():
    assert _af_con({"response": [None, 3]}).estadisticas(1) == {}
    assert _af_con({"response": [{"statistics": [None]}, {"statistics": []}]}).estadisticas(1) == {}
    assert _af_con({"response": "basura"}).estadisticas(1) == {}


# ------------------------------------------------- HTTP: reintentos y degradación
class Resp:
    def __init__(self, status=200, datos=None, headers=None):
        self.status_code, self._d, self.headers = status, datos if datos is not None else {"response": [1]}, headers or {}

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def _parchear(monkeypatch, secuencia):
    """requests.get devuelve/lanza los elementos de la secuencia en orden (el último se repite)."""
    llamadas = []

    def get(*a, **k):
        llamadas.append(1)
        x = secuencia[min(len(llamadas) - 1, len(secuencia) - 1)]
        if isinstance(x, Exception):
            raise x
        return x
    monkeypatch.setattr(requests, "get", get)
    return llamadas


@pytest.fixture
def af(tmp_path, monkeypatch):
    monkeypatch.setattr(apifootball, "DATOS", tmp_path)
    esperas = []
    a = APIFootball("k", sleep=esperas.append)
    a.esperas = esperas
    return a


def test_get_reintenta_500_y_se_recupera(af, monkeypatch):
    n = _parchear(monkeypatch, [Resp(500), Resp(500), Resp(200, {"response": [7]})])
    assert af._get("/x")["response"] == [7]
    assert len(n) == 3


def test_get_tres_500_degrada_a_vacio_sin_lanzar(af, monkeypatch):
    n = _parchear(monkeypatch, [Resp(500)])
    assert af._get("/x")["response"] == []
    assert len(n) == 3


def test_get_429_respeta_retry_after(af, monkeypatch):
    _parchear(monkeypatch, [Resp(429, headers={"Retry-After": "3"}), Resp(200, {"response": [1]})])
    assert af._get("/x")["response"] == [1]
    assert 3.0 in af.esperas


def test_get_timeout_degrada_a_vacio(af, monkeypatch):
    n = _parchear(monkeypatch, [requests.Timeout("t")])
    assert af._get("/x")["response"] == []
    assert len(n) == 3


def test_get_error_4xx_no_reintenta(af, monkeypatch):
    n = _parchear(monkeypatch, [Resp(403)])
    assert af._get("/x")["response"] == []
    assert len(n) == 1


def test_get_no_cachea_respuestas_con_errores(af, monkeypatch, tmp_path):
    _parchear(monkeypatch, [Resp(200, {"errors": {"token": "mala"}, "response": []})])
    af._get("/x", cache_horas=1, a=1)
    assert list((tmp_path / "cache").glob("*.json")) == []


def test_get_cachea_respuesta_buena(af, monkeypatch, tmp_path):
    _parchear(monkeypatch, [Resp(200, {"errors": [], "response": [1]})])
    af._get("/x", cache_horas=1, a=1)
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1


def test_get_cuota_diaria_agotada_se_marca_y_no_lanza(af, monkeypatch):
    n = _parchear(monkeypatch, [Resp(200, {"errors": {"requests": "You have reached the request limit for the day"},
                                           "response": []})])
    assert af._get("/x")["response"] == []
    assert af.cuota_agotada is True and af.activa is False
    af._get("/y")
    assert len(n) == 1          # ya no consulta más


def test_limitador_espera_al_superar_el_maximo_por_minuto(tmp_path, monkeypatch):
    monkeypatch.setattr(apifootball, "DATOS", tmp_path)
    t = [0.0]
    esperas = []

    def dormir(s):
        esperas.append(s)
        t[0] += s
    a = APIFootball("k", sleep=dormir, reloj=lambda: t[0], max_por_minuto=3)
    _parchear(monkeypatch, [Resp(200, {"response": [1]})])
    for i in range(3):
        a._get("/x", i=i)
    assert not any(e >= 30 for e in esperas)
    a._get("/x", i=99)
    assert any(e >= 30 for e in esperas)


def test_cada_reintento_real_pasa_por_el_limitador(tmp_path, monkeypatch):
    monkeypatch.setattr(apifootball, "DATOS", tmp_path)
    t = [0.0]
    a = APIFootball("k", sleep=lambda s: t.__setitem__(0, t[0] + s), reloj=lambda: t[0], max_por_minuto=3)
    n = _parchear(monkeypatch, [Resp(500)])
    a._get("/x")
    assert len(n) == 3 and len(a._marcas) == 3      # 3 intentos reales = 3 marcas


def test_reintentos_esperan_si_el_limitador_esta_lleno(tmp_path, monkeypatch):
    monkeypatch.setattr(apifootball, "DATOS", tmp_path)
    t = [0.0]
    esperas = []

    def dormir(s):
        esperas.append(s)
        t[0] += s
    a = APIFootball("k", sleep=dormir, reloj=lambda: t[0], max_por_minuto=2)
    _parchear(monkeypatch, [Resp(500)])
    a._get("/x")                                    # intento 3 supera 2/min: debe esperar ~60 s
    assert any(e >= 30 for e in esperas)


RATE = {"errors": {"rateLimit": "Too many requests. Your rate limit is 10 requests per minute."}, "response": []}


def test_rate_limit_por_minuto_espera_y_reintenta(af, monkeypatch):
    n = _parchear(monkeypatch, [Resp(200, RATE), Resp(200, {"errors": [], "response": [5]})])
    assert af._get("/x")["response"] == [5]
    assert len(n) == 2
    assert af.cuota_agotada is False and af.activa is True
    assert any(e >= 30 for e in af.esperas)


def test_rate_limit_por_texto_too_many_requests(af, monkeypatch):
    n = _parchear(monkeypatch, [Resp(200, {"errors": {"message": "Too many requests"}, "response": []}),
                                Resp(200, {"errors": [], "response": [6]})])
    assert af._get("/x")["response"] == [6]
    assert len(n) == 2 and af.cuota_agotada is False


def test_rate_limit_persistente_degrada_sin_cachear_ni_agotar_cuota(af, monkeypatch, tmp_path):
    n = _parchear(monkeypatch, [Resp(200, RATE)])
    assert af._get("/x", cache_horas=1, a=1)["response"] == []
    assert len(n) == 3
    assert af.cuota_agotada is False and af.activa is True
    assert list((tmp_path / "cache").glob("*.json")) == []


def test_rate_limit_junto_a_requests_diario_si_agota_la_cuota(af, monkeypatch):
    _parchear(monkeypatch, [Resp(200, {"errors": {"requests": "You have reached the request limit for the day"},
                                       "response": []})])
    af._get("/x")
    assert af.cuota_agotada is True


# ------------------------------------------------------------ The Odds API
@pytest.fixture
def odds():
    esperas = []
    o = OddsAPI("k", sleep=esperas.append)
    o.esperas = esperas
    return o


def test_odds_get_500_reintenta_y_degrada(odds, monkeypatch):
    n = _parchear(monkeypatch, [Resp(500)])
    assert odds._get("/sports") == []
    assert len(n) == 3


def test_odds_get_timeout_degrada(odds, monkeypatch):
    _parchear(monkeypatch, [requests.ConnectionError("x")])
    assert odds._get("/sports") == []


def test_odds_get_429_con_retry_after_y_recuperacion(odds, monkeypatch):
    _parchear(monkeypatch, [Resp(429, headers={"Retry-After": "2"}), Resp(200, [{"a": 1}])])
    assert odds._get("/sports") == [{"a": 1}]
    assert 2.0 in odds.esperas


def test_odds_get_ok(odds, monkeypatch):
    _parchear(monkeypatch, [Resp(200, [{"a": 1}], headers={"x-requests-remaining": "400"})])
    assert odds._get("/sports") == [{"a": 1}]
    assert odds.restantes == "400"


# ------------------------------------------------- bucle por liga en el pipeline
class AFFalsa:
    activa = True
    restantes = 50
    cuota_agotada = False
    max_por_minuto = 10

    def __init__(self, ini):
        self.ini = ini

    def partidos(self, fecha, ligas=None):
        out = []
        for lid, nombre in ((1, "Liga 1"), (2, "Liga 2")):
            out.append({"af_id": lid * 100, "liga_id": lid, "temporada": 2025, "liga": nombre, "pais": "X",
                        "inicio": self.ini, "local": f"L{lid}", "visita": f"V{lid}", "estado": "NS",
                        "gl": None, "gv": None, "htl": None, "htv": None})
        return out if fecha == self.ini[:10] else []

    def cuotas_liga(self, liga, temporada, fecha):
        return {}

    def prediccion(self, fixture):
        return {"1x2:1": 0.5, "1x2:X": 0.3, "1x2:2": 0.2}


def _cfg():
    return {"dias_adelante": 0, "ligas": [{"nombre": "Liga 1", "af": 1, "region": "Europa"},
                                          {"nombre": "Liga 2", "af": 2, "region": "Europa"}],
            "casas_afiladas": [], "casa_objetivo": "ecuabet", "pesos_iniciales": {"apifootball": 1.0},
            "max_predicciones_af": 40, "mercados_activos": ["1x2"]}


def test_bucle_por_liga_continua_tras_una_excepcion(monkeypatch):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})
    ahora = datetime.now(timezone.utc)
    ini = (ahora + timedelta(hours=1)).astimezone(pipeline.TZ).isoformat()

    class ModelosFalsos:
        def __init__(self, liga, af, cfg, temporada):
            if liga["af"] == 1:
                raise RuntimeError("falla al construir modelos")

        def probs(self, l, v):
            return None, {}

        def probs_pb(self, l, v):
            return None

    monkeypatch.setattr(pipeline, "Modelos", ModelosFalsos)
    # la hora de inicio debe caer dentro del día local de "ahora": se usa ahora + 1 h en hora local
    res = pipeline.analizar(_cfg(), AFFalsa(ini), None, None, ahora)
    ligas = {p["liga"] for p in res}
    assert ligas == {"Liga 2"}
    assert res.info["ligas_fallidas"][0]["liga"] == "Liga 1"
    assert "Liga 1" in res.info["ligas_sin_datos"]


def test_pipeline_marca_cuota_agotada(monkeypatch):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})
    ahora = datetime.now(timezone.utc)
    ini = (ahora + timedelta(hours=1)).astimezone(pipeline.TZ).isoformat()
    af = AFFalsa(ini)
    af.cuota_agotada = True

    class ModelosFalsos:
        def __init__(self, *a):
            pass

        def probs(self, l, v):
            return None, {}

        def probs_pb(self, l, v):
            return None

    monkeypatch.setattr(pipeline, "Modelos", ModelosFalsos)
    res = pipeline.analizar(_cfg(), af, None, None, ahora)
    assert res.info["cuota_agotada"] is True


def test_pipeline_aplica_af_max_por_minuto_de_la_config(monkeypatch):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})
    af = AFFalsa("2026-01-01T00:00:00+00:00")
    cfg = _cfg() | {"af_max_por_minuto": 30}
    pipeline.analizar(cfg, af, None, None, datetime.now(timezone.utc))
    assert af.max_por_minuto == 30


# ----------------------------------------------------------------- ensamble
def test_ensamble_con_pesos_cero_usa_pesos_uniformes():
    fuentes = {"a": {"x": 0.4}, "b": {"x": 0.6}}
    try:
        out = ensamble.combinar(fuentes, {"a": 0.0, "b": 0.0}, {}, {})
    except KeyError:
        pytest.fail("KeyError con todos los pesos en 0")
    assert out["x"]["p"] == pytest.approx(0.5)
    assert out["x"]["pesos"] == {"a": pytest.approx(0.5), "b": pytest.approx(0.5)}


# -------------------------------------------------------------- zona horaria
def test_hoy_ec_usa_America_Guayaquil():
    # 03:00 UTC del 2 de enero = 22:00 del 1 de enero en Ecuador (UTC-5)
    assert pipeline.hoy_ec(datetime(2026, 1, 2, 3, 0, tzinfo=timezone.utc)) == date(2026, 1, 1)


def test_footballdata_usa_hoy_ec(monkeypatch):
    monkeypatch.setattr(pipeline, "hoy_ec", lambda *a: date(2026, 3, 1), raising=False)
    assert footballdata._temporadas(2) == ["2526", "2425"]
