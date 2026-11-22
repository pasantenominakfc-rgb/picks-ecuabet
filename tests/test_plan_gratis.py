"""Plan gratis de API-Football y presupuesto de The Odds API (sin internet: respuestas falsas inyectadas)."""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]

from picks import exportar, pipeline, tracker  # noqa: E402
from picks.fuentes import apifootball, oddsapi  # noqa: E402
from picks.fuentes.apifootball import APIFootball  # noqa: E402
from picks.fuentes.oddsapi import OddsAPI  # noqa: E402

MSG_TEMP = "Free plans do not have access to this season, try from 2022 to 2024."
MSG_FECHA = "Free plans do not have access to this date, try from 2026-11-21 to 2026-11-23."


class Resp:
    def __init__(self, datos, headers=None, status=200):
        self._d, self.headers, self.status_code = datos, headers or {}, status

    def json(self):
        return self._d


class Red:
    """requests.get falso: registra (ruta, params) y responde con `manejador(ruta, params)`."""

    def __init__(self, monkeypatch, manejador):
        self.llamadas, self.manejador = [], manejador
        monkeypatch.setattr(requests, "get", self.get)

    def get(self, url, params=None, headers=None, timeout=None):
        ruta = "/" + url.split("//", 1)[1].split("/", 1)[1]
        if "/v4/" in ruta:
            ruta = ruta.split("/v4", 1)[1]
        self.llamadas.append((ruta, dict(params or {})))
        return self.manejador(ruta, dict(params or {}))

    def n(self, ruta):
        return sum(1 for r, _ in self.llamadas if r == ruta)


@pytest.fixture
def af_aislado(monkeypatch, tmp_path):
    monkeypatch.setattr(apifootball, "DATOS", tmp_path)
    return lambda **k: APIFootball("k", sleep=lambda s: None, max_por_minuto=0, **k)


# ------------------------------------------------------------- 1a) /odds
def test_odds_aprende_el_rango_de_temporadas_y_no_repite(monkeypatch, af_aislado):
    red = Red(monkeypatch, lambda r, p: Resp({"errors": {"plan": MSG_TEMP}, "response": [], "paging": {"total": 1}}))
    af = af_aislado()
    assert af.cuotas_liga(39, 2026, "2026-11-22") == {}
    assert af.cuotas_liga(140, 2026, "2026-11-22") == {}
    assert af.cuotas_liga(135, 2026, "2026-11-23") == {}
    assert red.n("/odds") == 1
    assert af.cuotas_no_disponibles is True


def test_odds_temporada_dentro_del_rango_si_se_pide(monkeypatch, af_aislado):
    red = Red(monkeypatch, lambda r, p: Resp({"errors": {"plan": MSG_TEMP}, "response": [], "paging": {"total": 1}}))
    af = af_aislado()
    af.cuotas_liga(39, 2026, "2026-11-22")
    af.cuotas_liga(39, 2024, "2024-05-01")      # 2024 sí está permitida: se intenta
    assert red.n("/odds") == 2


# ----------------------------------------------------------- 1b) /fixtures
def test_fixtures_aprende_el_rango_de_fechas(monkeypatch, af_aislado):
    red = Red(monkeypatch, lambda r, p: Resp({"errors": {"plan": MSG_FECHA}, "response": []}))
    af = af_aislado()
    af.partidos("2026-11-27")
    for f in ("2026-11-25", "2026-11-26", "2026-11-20", "2026-12-01"):
        assert af.partidos(f) == []
    assert red.n("/fixtures") == 1
    af.partidos("2026-11-22")                      # dentro del rango: sí se pide
    assert red.n("/fixtures") == 2


def test_plan_gratis_limita_fechas_a_ayer_y_manana(monkeypatch, af_aislado):
    red = Red(monkeypatch, lambda r, p: Resp({"errors": [], "response": []}))
    af = af_aislado()
    af.configurar_plan("gratis", date(2026, 11, 22))
    for f in ("2026-11-20", "2026-11-24", "2026-11-27"):
        af.partidos(f)
    assert red.n("/fixtures") == 0
    for f in ("2026-11-21", "2026-11-22", "2026-11-23"):
        af.partidos(f)
    assert red.n("/fixtures") == 3


def test_plan_pro_no_limita_fechas(monkeypatch, af_aislado):
    red = Red(monkeypatch, lambda r, p: Resp({"errors": [], "response": []}))
    af = af_aislado()
    af.configurar_plan("pro", date(2026, 11, 22))
    af.partidos("2026-11-27")
    assert red.n("/fixtures") == 1


def test_historico_no_repite_temporada_bloqueada(monkeypatch, af_aislado):
    msg = "Free plans do not have access to this season, try from 2021 to 2023."
    red = Red(monkeypatch, lambda r, p: Resp({"errors": {"plan": msg}, "response": []}))
    af = af_aislado()
    af.historico(242, 2026)
    af.historico(253, 2026)
    assert red.n("/fixtures") == 1          # 2026 se pide una vez y se recuerda; 2025 también (otra temporada)


# ------------------------------------------------- 1c) resumen + info del pipeline
def _fixture_json(fid, liga, inicio):
    return {"fixture": {"id": fid, "date": inicio, "status": {"short": "NS"}},
            "league": {"id": liga, "season": 2030, "name": f"Liga {liga}", "country": "England"},
            "teams": {"home": {"name": f"L{liga}"}, "away": {"name": f"V{liga}"}},
            "goals": {"home": None, "away": None}, "score": {"halftime": {}}}


class ModelosFalsos:
    def __init__(self, *a):
        pass

    def probs(self, l, v):
        return None, {}

    def probs_pb(self, l, v):
        return None


def _cfg(**kw):
    base = {"dias_adelante": 1, "af_plan": "gratis", "af_max_por_minuto": 0,
            "ligas": [{"nombre": "Liga 1", "af": 1, "region": "Europa"}, {"nombre": "Liga 2", "af": 2, "region": "Europa"}],
            "casas_afiladas": [], "casa_objetivo": "ecuabet", "pesos_iniciales": {"apifootball": 1.0},
            "max_predicciones_af": 0, "mercados_activos": ["1x2"]}
    return base | kw


AHORA = datetime(2030, 6, 10, 15, 0, tzinfo=timezone.utc)


def _inicio():
    return (AHORA + timedelta(hours=2)).astimezone(pipeline.TZ).isoformat()


def test_pipeline_plan_gratis_un_solo_resumen_y_bandera(monkeypatch, af_aislado, capsys):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})
    monkeypatch.setattr(pipeline, "Modelos", ModelosFalsos)
    hoy = AHORA.astimezone(pipeline.TZ).date().isoformat()

    def manejador(ruta, p):
        if ruta == "/fixtures":
            return Resp({"errors": [], "response": [_fixture_json(100 + i, i, _inicio()) for i in (1, 2)]
                         if p["date"] == hoy else []})
        if ruta == "/odds":
            return Resp({"errors": {"plan": MSG_TEMP}, "response": [], "paging": {"total": 1}})
        return Resp({"errors": [], "response": []})
    red = Red(monkeypatch, manejador)
    af = af_aislado()
    res = pipeline.analizar(_cfg(), af, None, None, AHORA)
    out = capsys.readouterr().out
    assert res.info["cuotas_af_no_disponibles"] is True
    assert red.n("/odds") == 1
    assert out.count("Plan gratis: sin cuotas de API-Football para la temporada 2030") == 1
    assert "ODDS_API_KEY" in out
    assert out.count("Free plans do not have access") == 0       # no se repiten decenas de líneas


def test_pipeline_plan_gratis_no_pide_fechas_fuera_de_rango(monkeypatch, af_aislado):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})
    monkeypatch.setattr(pipeline, "Modelos", ModelosFalsos)
    red = Red(monkeypatch, lambda r, p: Resp({"errors": [], "response": []}))
    pipeline.analizar(_cfg(dias_adelante=5), af_aislado(), None, None, AHORA)
    fechas = {p["date"] for r, p in red.llamadas if r == "/fixtures"}
    assert fechas <= {"2030-06-09", "2030-06-10", "2030-06-11"}
    assert len(red.llamadas) <= 3


# ---------------------------------------------------------- 2) fuentes_estado
@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(exportar, "WEB", tmp_path / "web_data")
    monkeypatch.setattr(tracker, "RUTA", tmp_path / "sistema.db")
    return tmp_path


def _hoy_json(aislado, estado, cfg_extra=None):
    from tests.test_exportar import _cfg as cfg_base, _datos_hoy  # noqa: PLC0415
    partidos, dias = _datos_hoy()
    exportar.hoy(partidos, dias, cfg_base() | (cfg_extra or {}), "x", estado=estado)
    return json.loads((aislado / "web_data" / "hoy.json").read_text(encoding="utf-8"))


def test_hoy_json_fuentes_estado_sin_cuotas(aislado):
    d = _hoy_json(aislado, {"cuotas_casas": False, "forebet": False, "ia": True, "cuotas_af_no_disponibles": True,
                            "dias_max": 1}, {"af_plan": "gratis"})
    fe = d["fuentes_estado"]
    assert fe["cuotas_casas"] is False and fe["forebet"] is False and fe["ia"] is True
    assert fe["plan_af"] == "gratis" and fe["dias_max"] == 1
    assert "Sin cuotas de casas" in fe["mensaje"] and "ODDS_API_KEY" in fe["mensaje"]


def test_hoy_json_fuentes_estado_con_cuotas_y_sin_secretos(aislado):
    d = _hoy_json(aislado, {"cuotas_casas": True, "forebet": True, "ia": False},
                  {"af_plan": "pro", "dias_adelante": 5, "odds_api_key": "SECRETO123"})
    fe = d["fuentes_estado"]
    assert fe["cuotas_casas"] is True and fe["plan_af"] == "pro" and fe["dias_max"] == 5
    assert "ODDS_API_KEY" not in fe["mensaje"]
    assert "SECRETO123" not in json.dumps(d)
    assert all(isinstance(v, (bool, int, str)) for v in fe.values())


def test_hoy_json_fuentes_estado_sin_estado_no_rompe(aislado):
    assert "fuentes_estado" in _hoy_json(aislado, None)


# ------------------------------------------------------- 3) presupuesto Odds API
def _red_odds(monkeypatch, restantes="480"):
    def manejador(ruta, p):
        h = {"x-requests-remaining": restantes}
        if ruta.endswith("/events"):
            return Resp([{"id": "e"}], h)
        return Resp([{"home_team": "A", "away_team": "B", "commence_time": "2030-06-10T20:00:00Z",
                      "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                          {"name": "A", "price": 2.0}, {"name": "B", "price": 3.0}, {"name": "Draw", "price": 3.2}]}]}]}], h)
    return Red(monkeypatch, manejador)


def test_odds_tope_por_defecto_4_ligas(monkeypatch, tmp_path):
    monkeypatch.setattr(oddsapi, "DATOS", tmp_path)
    red = _red_odds(monkeypatch)
    o = OddsAPI("k", sleep=lambda s: None)
    for i in range(12):
        o.cuotas(f"soccer_x{i}", 48)
    assert sum(1 for r, _ in red.llamadas if r.endswith("/odds")) == 4


def test_odds_tope_configurable(monkeypatch, tmp_path):
    monkeypatch.setattr(oddsapi, "DATOS", tmp_path)
    red = _red_odds(monkeypatch)
    o = OddsAPI("k", sleep=lambda s: None, max_llamadas=2)
    res = [o.cuotas(f"soccer_x{i}", 48) for i in range(5)]
    assert sum(1 for r, _ in red.llamadas if r.endswith("/odds")) == 2
    assert res[0] and res[1] and res[2] == [] and o.llamadas == 2


def test_odds_cache_3_horas_no_gasta_llamadas(monkeypatch, tmp_path):
    monkeypatch.setattr(oddsapi, "DATOS", tmp_path)
    red = _red_odds(monkeypatch)
    a = OddsAPI("k", sleep=lambda s: None).cuotas("soccer_epl", 48)
    n = len(red.llamadas)
    b = OddsAPI("k", sleep=lambda s: None).cuotas("soccer_epl", 48)     # otra corrida: lee de caché
    assert len(red.llamadas) == n and a == b and a
    for f in (tmp_path / "cache").glob("odds_*.json"):
        os.utime(f, (1, 1))                                               # caché de hace décadas
    OddsAPI("k", sleep=lambda s: None).cuotas("soccer_epl", 48)
    assert len(red.llamadas) > n


def test_odds_registra_creditos_restantes(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(oddsapi, "DATOS", tmp_path)
    _red_odds(monkeypatch, "123")
    o = OddsAPI("k", sleep=lambda s: None)
    o.cuotas("soccer_epl", 48)
    assert o.restantes == "123"
    assert "123" in capsys.readouterr().out


def test_odds_sin_clave_no_hace_nada(monkeypatch, tmp_path):
    monkeypatch.setattr(oddsapi, "DATOS", tmp_path)
    red = _red_odds(monkeypatch)
    o = OddsAPI("")
    assert o.cuotas("soccer_epl", 48) == [] and red.llamadas == []


class OddsContador:
    activa = True

    def __init__(self):
        self.pedidas = []

    def cuotas(self, key, horas):
        self.pedidas.append(key)
        return []


class AFBase:
    activa, restantes, sin_cuota, cuota_agotada = True, 1, False, False

    def cuotas_liga(self, *a):
        return {}

    def prediccion(self, f):
        return {"1x2:1": .5, "1x2:X": .3, "1x2:2": .2}


def _fx(lid, ini, pais="X"):
    return {"af_id": lid, "liga_id": lid, "temporada": 2030, "liga": f"L{lid}", "pais": pais, "inicio": ini,
            "local": f"L{lid}", "visita": f"V{lid}", "estado": "NS", "gl": None, "gv": None, "htl": None, "htv": None}


def test_pipeline_prioriza_ligas_para_odds_y_respeta_tope(monkeypatch):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})
    monkeypatch.setattr(pipeline, "Modelos", ModelosFalsos)
    ini_hoy = _inicio()
    ini_manana = (AHORA + timedelta(days=1, hours=2)).astimezone(pipeline.TZ).isoformat()

    class AF(AFBase):
        def partidos(self, fecha, ligas=None):
            # solo la liga 3 (última de la lista) juega hoy; las demás mañana
            return [_fx(l, ini_hoy if l == 3 else ini_manana) for l in (1, 2, 3)
                    if fecha == (ini_hoy if l == 3 else ini_manana)[:10]]

    cfg = _cfg(odds_max_llamadas_dia=2, max_predicciones_af=9,
               ligas=[{"nombre": f"L{i}", "af": i, "region": "Europa", "odds_key": f"k{i}"} for i in (1, 2, 3)])
    odds = OddsContador()
    pipeline.analizar(cfg, AF(), odds, None, AHORA)
    assert odds.pedidas == ["k3", "k1"]          # hoy primero, luego el orden de cfg["ligas"]


# --------------------------------------------------- 4) tope de ligas analizadas
class AFMuchas(AFBase):
    def __init__(self, n, ini):
        self.n, self.ini = n, ini

    def partidos(self, fecha, ligas=None):
        return [_fx(i, self.ini, "England") for i in range(1, self.n + 1)] if fecha == self.ini[:10] else []


def test_tope_max_ligas_analizadas_por_defecto_en_gratis(monkeypatch):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})
    monkeypatch.setattr(pipeline, "Modelos", ModelosFalsos)
    cfg = _cfg(incluir_todas_las_ligas=True, regiones_todas=["Europa"], max_predicciones_af=999,
               ligas=[{"nombre": "Principal", "af": 50, "region": "Europa"}])
    res = pipeline.analizar(cfg, AFMuchas(60, _inicio()), None, None, AHORA)
    assert len({p["liga"] for p in res}) == 25
    assert res.info["ligas_omitidas_por_tope"] == 35
    cfg["max_ligas_analizadas"] = 10
    assert len({p["liga"] for p in pipeline.analizar(cfg, AFMuchas(60, _inicio()), None, None, AHORA)}) == 10


def test_tope_ligas_da_prioridad_a_la_lista_de_cfg(monkeypatch):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})
    monkeypatch.setattr(pipeline, "Modelos", ModelosFalsos)
    cfg = _cfg(incluir_todas_las_ligas=True, regiones_todas=["Europa"], max_ligas_analizadas=3, max_predicciones_af=999,
               ligas=[{"nombre": "Principal", "af": 50, "region": "Europa"}, {"nombre": "Otra", "af": 59, "region": "Europa"}])
    res = pipeline.analizar(cfg, AFMuchas(60, _inicio()), None, None, AHORA)
    assert {p["liga"] for p in res} >= {"Principal", "Otra"}      # las de la lista primero
    assert len({p["liga"] for p in res}) == 3


def test_perfil_pro_no_aplica_tope_por_defecto(monkeypatch):
    monkeypatch.setattr(pipeline.tracker, "calibracion", lambda: {})
    monkeypatch.setattr(pipeline, "Modelos", ModelosFalsos)
    cfg = _cfg(af_plan="pro", incluir_todas_las_ligas=True, regiones_todas=["Europa"], max_predicciones_af=999)
    res = pipeline.analizar(cfg, AFMuchas(40, _inicio()), None, None, AHORA)
    assert len({p["liga"] for p in res}) == 40


def test_filtros_de_apuesta_intactos_en_config():
    from picks import config
    cfg = config.cargar()
    assert cfg["min_fuentes"] == 2 and cfg["ventaja_minima"] == 0.04 and cfg["max_dispersion"] == 0.08
    assert cfg["seguras_prob_min"] == 0.72
    assert cfg["dias_adelante"] == 1 and cfg["odds_max_llamadas_corrida"] == 8 and cfg["max_ligas_analizadas"] == 25


# ------------------------------------------ revisión: presupuesto Odds API (12 h, 4 por corrida, nombre nuevo)
def test_odds_cache_12_horas_y_tope_por_defecto_4():
    assert oddsapi.CACHE_HORAS == 12
    assert OddsAPI("k").max_llamadas == 4


def test_odds_tope_acepta_nombre_nuevo_y_el_viejo():
    assert oddsapi.tope_corrida({"odds_max_llamadas_corrida": 3}) == 3
    assert oddsapi.tope_corrida({"odds_max_llamadas_dia": 6}) == 6          # compatibilidad
    assert oddsapi.tope_corrida({"odds_max_llamadas_corrida": 3, "odds_max_llamadas_dia": 6}) == 3
    assert oddsapi.tope_corrida({}) == 4


def test_odds_respuesta_de_error_no_lista_no_cuenta_llamada(monkeypatch, tmp_path):
    monkeypatch.setattr(oddsapi, "DATOS", tmp_path)
    Red(monkeypatch, lambda ruta, p: Resp({"message": "Invalid key"}, {"x-requests-remaining": "400"}))
    o = OddsAPI("k", sleep=lambda s: None)
    assert o.cuotas("soccer_epl", 48) == [] and o.llamadas == 0


def test_odds_solo_cuenta_llamada_si_odds_devuelve_lista(monkeypatch, tmp_path):
    monkeypatch.setattr(oddsapi, "DATOS", tmp_path)

    def manejador(ruta, p):
        if ruta.endswith("/events"):
            return Resp([{"id": "e"}], {})
        return Resp({"message": "quota"}, {})
    Red(monkeypatch, manejador)
    o = OddsAPI("k", sleep=lambda s: None)
    assert o.cuotas("soccer_epl", 48) == [] and o.llamadas == 0


# ------------------------------------- revisión: mensaje "free plans" sin rango parseable, reinicio del estado
MSG_RARO = "Free plans can not use this endpoint. Upgrade your subscription."


def test_mensaje_free_plans_no_parseable_se_imprime_una_vez_y_corta_la_ruta(monkeypatch, af_aislado, capsys):
    red = Red(monkeypatch, lambda r, p: Resp({"errors": {"plan": MSG_RARO}, "response": [], "paging": {"total": 1}}))
    af = af_aislado()
    for d in ("2026-11-22", "2026-11-23", "2026-11-21"):
        assert af.partidos(d) == []
    assert red.n("/fixtures") == 1                                   # no se repiten llamadas a esa ruta
    assert capsys.readouterr().out.count(MSG_RARO) == 1               # y el mensaje sale una sola vez
    af.cuotas_liga(39, 2026, "2026-11-22")
    assert red.n("/odds") == 1                                       # otra ruta distinta sí se intenta


def test_fecha_invalida_en_el_mensaje_no_lanza(monkeypatch, af_aislado):
    msg = "Free plans do not have access to this date, try from 2026-13-45 to 2026-99-99."
    Red(monkeypatch, lambda r, p: Resp({"errors": {"plan": msg}, "response": []}))
    af = af_aislado()
    assert af.partidos("2026-11-22") == []            # antes: ValueError de date.fromisoformat
    assert af.rango_fechas is None


def test_configurar_plan_reinicia_lo_aprendido(monkeypatch, af_aislado):
    Red(monkeypatch, lambda r, p: Resp({"errors": {"plan": MSG_TEMP}, "response": [], "paging": {"total": 1}}))
    af = af_aislado()
    af.cuotas_liga(39, 2026, "2026-11-22")
    assert af.cuotas_no_disponibles and af.temporadas_sin_cuotas and af.rango_temp_odds
    af.configurar_plan("pro", date(2026, 11, 23))
    assert not af.cuotas_no_disponibles and not af.temporadas_sin_cuotas
    assert af.rango_temp_odds is None and af.rango_temp_fixtures is None and af.rango_fechas is None
