"""Pruebas de la fuente ClubElo (picks/fuentes/clubelo.py). Sin internet: se inyecta un CSV falso."""
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from picks import config, exportar, pipeline, seleccion  # noqa: E402
from picks.fuentes import clubelo  # noqa: E402

CSV = """Rank,Club,Country,Level,Elo,From,To
1,Man City,ENG,1,2050.5,2026-11-01,2026-11-23
2,Real Madrid,ESP,1,2000.0,2026-11-01,2026-11-23
3,Inter,ITA,1,1950.0,2026-11-01,2026-11-23
None,Bayern,GER,1,1990.0,2026-11-01,2026-11-23
5,Atletico,ESP,1,1900.0,2026-11-01,2026-11-23
6,Paris SG,FRA,1,1940.0,2026-11-01,2026-11-23
7,Basura,ENG,1,abc,2026-11-01,2026-11-23
"""


class Resp:
    def __init__(self, texto, status=200):
        self.text, self.status_code = texto, status


def test_parsear_csv_ignora_filas_malas():
    r = clubelo.parsear_csv(CSV)
    assert r["Man City"] == pytest.approx(2050.5)
    assert r["Bayern"] == pytest.approx(1990.0)       # Rank "None" no rompe
    assert "Basura" not in r
    assert clubelo.parsear_csv("<html>502</html>") == {}
    assert clubelo.parsear_csv("") == {}


def test_buscar_elo_con_alias_y_nombres_pegados():
    r = clubelo.parsear_csv(CSV)
    assert clubelo.buscar_elo("Manchester City", r) == pytest.approx(2050.5)
    assert clubelo.buscar_elo("Man City", r) == pytest.approx(2050.5)
    assert clubelo.buscar_elo("Internazionale", r) == pytest.approx(1950.0)
    assert clubelo.buscar_elo("Inter Milan", r) == pytest.approx(1950.0)
    assert clubelo.buscar_elo("Bayern Munich", r) == pytest.approx(1990.0)
    assert clubelo.buscar_elo("Atletico Madrid", r) == pytest.approx(1900.0)
    assert clubelo.buscar_elo("Paris Saint-Germain", r) == pytest.approx(1940.0)
    assert clubelo.buscar_elo("Equipo Inexistente FC", r) is None


def test_probs_1x2_suma_uno_y_ventaja_local():
    p = clubelo.probs_desde_elo(1800, 1800)
    assert p["1x2:1"] + p["1x2:X"] + p["1x2:2"] == pytest.approx(1.0)
    assert p["1x2:1"] > p["1x2:2"]                           # ventaja de local
    assert p["1x2:X"] == pytest.approx(0.26 * math.exp(-(65 / 400) ** 2), abs=1e-6)
    fuerte = clubelo.probs_desde_elo(2100, 1700)
    assert fuerte["1x2:1"] > 0.75 and fuerte["1x2:X"] < p["1x2:X"]   # el empate decrece con |dElo|
    assert clubelo.probs_desde_elo(1800, 1800, p_empate_max=0.30)["1x2:X"] > p["1x2:X"]


def test_probs_dc_y_dnb_derivadas():
    p = clubelo.probs_desde_elo(1900, 1750)
    assert p["dc:1X"] == pytest.approx(p["1x2:1"] + p["1x2:X"])
    assert p["dc:12"] == pytest.approx(p["1x2:1"] + p["1x2:2"])
    assert p["dc:X2"] == pytest.approx(p["1x2:X"] + p["1x2:2"])
    assert p["dnb:1"] + p["dnb:2"] == pytest.approx(1.0)
    assert p["dnb:1"] == pytest.approx(p["1x2:1"] / (p["1x2:1"] + p["1x2:2"]))
    # no inventa mercados de goles/córners/tarjetas
    assert {k.split(":")[0] for k in p} == {"1x2", "dc", "dnb"}


def test_descargar_inyectando_peticion_y_cache(tmp_path):
    llamadas = []

    def get(url, **kw):
        llamadas.append(url)
        return Resp(_csv_grande(extra="1,Inter,ITA,1,1950.0,a,b\n"))
    r = clubelo.descargar(date(2026, 11, 22), cache_dir=tmp_path, get=get)
    assert r["Inter"] == pytest.approx(1950.0)
    assert llamadas == ["https://api.clubelo.com/2026-11-22"]
    assert (tmp_path / "clubelo_2026-11-22.json").exists()
    r2 = clubelo.descargar(date(2026, 11, 22), cache_dir=tmp_path, get=lambda *a, **k: pytest.fail("no debe pedir"))
    assert r2 == r                                              # caché diaria


def test_descargar_nunca_lanza(tmp_path):
    assert clubelo.descargar(date(2026, 1, 1), cache_dir=tmp_path, get=lambda *a, **k: None) == {}

    def explota(*a, **k):
        raise RuntimeError("boom")
    assert clubelo.descargar(date(2026, 1, 2), cache_dir=tmp_path, get=explota) == {}
    assert clubelo.descargar(date(2026, 1, 3), cache_dir=tmp_path, get=lambda *a, **k: Resp("<html>")) == {}


def test_elo_modelo_y_penaltyblog_son_un_solo_grupo_estadistico():
    # Decisión de negocio: elo + modelo + penaltyblog cuentan 1 EN CONJUNTO (no son independientes entre sí).
    assert seleccion.contar_fuentes({"modelo": .6, "penaltyblog": .6}) == 1
    assert seleccion.contar_fuentes({"modelo": .6, "penaltyblog": .6, "elo": .6}) == 1
    assert seleccion.contar_fuentes({"modelo": .6, "elo": .6}) == 1
    assert seleccion.contar_fuentes({"elo": .6, "ia": .6}) == 1       # la IA sigue sin contar
    assert seleccion.contar_fuentes({"elo": .6, "mercado": .6}) == 2
    assert seleccion.contar_fuentes({"modelo": .6, "elo": .6, "forebet": .6, "apifootball": .6}) == 3


def _pa_valor(detalle, p, mejor):
    return {"uid": "u1", "af_id": 1, "liga": "L", "region": "Europa", "fecha": "2026-01-01",
            "inicio": "2026-01-01T20:00:00+00:00", "local": "A", "visita": "B",
            "probs": {"1x2:1": {"p": p, "detalle": detalle, "n": len(detalle), "dispersion": 0.0, "pesos": {}}},
            "ecuabet": {}, "mejores": {"1x2:1": (mejor, "casa")}}


def test_contraejemplo_modelo_y_elo_sin_fuente_externa_no_da_valor():
    # p=0.56 en modelo y elo, sin mercado/forebet/penaltyblog, mejor cuota 1.95 (EV +9%): antes salía como Valor.
    cfg = config.cargar()
    cfg.update({"banca": 100.0, "stake_minimo": 1.0})
    valor, _ = seleccion.elegir([_pa_valor({"modelo": .56, "elo": .56}, .56, 1.95)], cfg)
    assert valor == []
    # con una fuente externa más sí pasa (el filtro no se relajó, solo se exige independencia real)
    valor, _ = seleccion.elegir([_pa_valor({"modelo": .56, "elo": .56, "forebet": .56}, .56, 1.95)], cfg)
    assert len(valor) == 1
    # y aunque min_fuentes se bajara a 1, Valor exige al menos una fuente externa
    cfg1 = dict(cfg, min_fuentes=1)
    valor, _ = seleccion.elegir([_pa_valor({"modelo": .56, "elo": .56}, .56, 1.95)], cfg1)
    assert valor == []


def test_config_trae_peso_inicial_de_elo():
    cfg = config.cargar()
    assert 0 < cfg["pesos_iniciales"]["elo"] <= 0.15


class _AF:
    activa = True
    sin_cuota = False

    def __init__(self, ini):
        self.ini = ini

    def partidos(self, fecha, ligas):
        if fecha != "2026-11-22":
            return []
        return [{"af_id": 1, "liga_id": 39, "liga": "Premier League", "pais": "England", "local": "Manchester City",
                 "visita": "Equipo Raro", "inicio": self.ini, "estado": "NS", "temporada": 2026}]

    def cuotas_liga(self, *a, **k):
        return {}

    def prediccion(self, *a, **k):
        return None

    def historico(self, *a, **k):
        import pandas as pd
        return pd.DataFrame()


def test_pipeline_agrega_fuente_elo_solo_si_ambos_equipos_se_encuentran(monkeypatch):
    from picks.fuentes import footballdata
    import pandas as pd
    monkeypatch.setattr(footballdata, "historico", lambda *a, **k: pd.DataFrame())
    ahora = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cfg = config.cargar()
    cfg["ligas"] = [cfg["ligas"][0]]
    ini = datetime(2026, 11, 22, 20, 0, tzinfo=timezone.utc).isoformat()
    ratings = clubelo.parsear_csv(CSV)
    # visita desconocida: sin fuente elo y sin error (no hay otras fuentes -> el partido se omite)
    assert pipeline.analizar(cfg, _AF(ini), None, None, ahora, elo_ratings=ratings) == []

    class AF2(_AF):
        def partidos(self, fecha, ligas):
            f = super().partidos(fecha, ligas)
            f[0]["visita"] = "Real Madrid"
            return f
    res = pipeline.analizar(cfg, AF2(ini), None, None, ahora, elo_ratings=ratings)
    assert len(res) == 1 and "elo" in res[0]["fuentes"]
    assert set(res[0]["fuentes"]["elo"]) >= {"1x2:1", "1x2:X", "1x2:2", "dc:1X", "dnb:1"}
    assert res[0]["probs"]["1x2:1"]["n"] == 1


# ------------------------------------------------------------ tabla de acuerdo (exportar)
def _partido(fuentes, probs):
    return {"uid": "1", "liga": "L", "region": "Europa", "fecha": "2026-11-22", "inicio": "2026-11-22T15:00:00-05:00",
            "local": "A", "visita": "B", "fuentes": fuentes, "probs": probs, "evaluadas": []}


def test_acuerdo_1x2_redondeado_y_dispersion():
    pa = _partido({"mercado": {"1x2:1": .5, "1x2:X": .3, "1x2:2": .2},
                   "elo": {"1x2:1": .6, "1x2:X": .25, "1x2:2": .15},
                   "ia": {"1x2:1": .9},
                   "forebet": {"ou:2.5:over": .5}},
                  {"1x2:1": {"p": .55555}, "1x2:X": {"p": .27777}, "1x2:2": {"p": .16666}})
    a = exportar.acuerdo_1x2(pa)
    assert set(a["fuentes"]) == {"mercado", "elo"}
    assert a["fuentes"]["elo"] == [0.6, 0.25, 0.15]
    assert a["consenso"] == [0.556, 0.278, 0.167]
    assert a["dispersion"] == pytest.approx(round((0.05 + 0.025 + 0.025) / 3, 3), abs=1e-3)
    assert exportar.acuerdo_1x2(_partido({"mercado": {}}, {})) is None


def test_hoy_json_incluye_acuerdo_sin_tocar_campos_existentes(tmp_path, monkeypatch):
    from picks import tracker
    monkeypatch.setattr(exportar, "WEB", tmp_path / "w")
    monkeypatch.setattr(tracker, "RUTA", tmp_path / "s.db")
    pa = _partido({"mercado": {"1x2:1": .5, "1x2:X": .3, "1x2:2": .2}, "elo": {"1x2:1": .6, "1x2:X": .25, "1x2:2": .15}},
                  {"1x2:1": {"p": .55}, "1x2:X": {"p": .27}, "1x2:2": {"p": .18}})
    exportar.hoy([pa], {}, config.cargar(), "x")
    d = json.loads((tmp_path / "w" / "hoy.json").read_text(encoding="utf-8"))["partidos"][0]
    assert "acuerdo" not in d and d["acuerdo_1x2"]["fuentes"]["mercado"] == [0.5, 0.3, 0.2]
    assert d["acuerdo_1x2"]["consenso"] == [0.55, 0.27, 0.18]
    assert set(d["fuentes"]) == {"mercado", "elo"} and "probs" in d     # campos existentes intactos


# ------------------------------------------------ revisión: homónimos, validación del CSV, NaN, alias
def _csv_grande(n=120, elo=1500.0, extra=""):
    filas = ["Rank,Club,Country,Level,Elo,From,To"]
    filas += [f"{i},Club{i},ENG,1,{elo + i},2026-11-01,2026-11-23" for i in range(n)]
    return "\n".join(filas) + "\n" + extra


def test_buscar_elo_no_empareja_por_sufijos_ambiguos():
    r = clubelo.parsear_csv(CSV + "8,Barcelona,ESP,1,1950,2026-11-01,2026-11-23\n9,Liverpool,ENG,1,1980,2026-11-01,2026-11-23\n")
    assert clubelo.buscar_elo("Barcelona", r) == pytest.approx(1950.0)
    for homonimo in ("Barcelona SC", "Atletico-MG", "Atletico MG", "Liverpool SE", "Nacional EC", "Madrid CA", "Flamengo RJ"):
        assert clubelo.buscar_elo(homonimo, r) is None, homonimo


def test_pipeline_no_calcula_elo_fuera_de_europa(monkeypatch):
    from picks.fuentes import footballdata
    import pandas as pd
    monkeypatch.setattr(footballdata, "historico", lambda *a, **k: pd.DataFrame())
    ahora = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cfg = config.cargar()
    ini = datetime(2026, 11, 22, 20, 0, tzinfo=timezone.utc).isoformat()
    ratings = clubelo.parsear_csv(CSV + "8,Barcelona,ESP,1,1950,2026-11-01,2026-11-23\n")

    class AF3(_AF):
        def partidos(self, fecha, ligas):
            f = super().partidos(fecha, ligas)
            if f:
                f[0].update(local="Barcelona", visita="Real Madrid", liga_id=13, liga="Copa Libertadores", pais="World")
            return f
    cfg["ligas"] = [{"nombre": "Copa Libertadores", "region": "Sudamérica", "af": 13}]
    # Barcelona (SC de Guayaquil en Libertadores) y Real Madrid existen en ClubElo, pero la liga no es de Europa
    assert pipeline.analizar(cfg, AF3(ini), None, None, ahora, elo_ratings=ratings) == []
    cfg["ligas"] = [{"nombre": "Copa Libertadores", "region": "Europa", "af": 13}]
    res = pipeline.analizar(cfg, AF3(ini), None, None, ahora, elo_ratings=ratings)
    assert len(res) == 1 and "elo" in res[0]["fuentes"]


def test_descargar_solo_https_sin_fallback_http_ni_cache_en_fallo(tmp_path):
    urls = []

    def get(url, **kw):
        urls.append(url)
        return None if url.startswith("https") else Resp(_csv_grande())
    assert clubelo.descargar(date(2026, 11, 22), cache_dir=tmp_path, get=get) == {}
    assert urls == ["https://api.clubelo.com/2026-11-22"]      # nunca http://
    assert not list(tmp_path.rglob("*.json")), "un fallo no se cachea"
    urls.clear()
    r = clubelo.descargar(date(2026, 11, 23), cache_dir=tmp_path, get=lambda u, **k: (urls.append(u), Resp(_csv_grande()))[1])
    assert urls == ["https://api.clubelo.com/2026-11-23"] and len(r) == 120


def test_descargar_descarta_csv_chico_o_con_elo_absurdo(tmp_path):
    assert clubelo.descargar(date(2026, 2, 1), cache_dir=tmp_path, get=lambda *a, **k: Resp(_csv_grande(n=20))) == {}
    assert clubelo.descargar(date(2026, 2, 2), cache_dir=tmp_path,
                             get=lambda *a, **k: Resp(_csv_grande(extra="999,Raro,ENG,1,2500,a,b\n"))) == {}
    assert clubelo.descargar(date(2026, 2, 3), cache_dir=tmp_path,
                             get=lambda *a, **k: Resp(_csv_grande(extra="999,Raro,ENG,1,500,a,b\n"))) == {}
    assert len(clubelo.descargar(date(2026, 2, 4), cache_dir=tmp_path, get=lambda *a, **k: Resp(_csv_grande()))) == 120


def test_probs_desde_elo_protege_nan_inf_y_limites():
    for malo in (float("nan"), float("inf"), float("-inf")):
        assert clubelo.probs_desde_elo(malo, 1800) == {}
        assert clubelo.probs_desde_elo(1800, malo) == {}
    extremo = clubelo.probs_desde_elo(2300, 800)
    assert extremo["1x2:1"] <= 0.97 + 1e-9 and extremo["1x2:X"] >= 0.12 - 1e-9
    assert extremo["1x2:1"] + extremo["1x2:X"] + extremo["1x2:2"] == pytest.approx(1.0)
    assert clubelo.probs_desde_elo(1800, 1800, p_empate_max=0.0)["1x2:X"] >= 0.12 - 1e-9


def test_alias_elo_nombres_tipicos_de_api_football():
    r = {n: 1700.0 + i for i, n in enumerate(
        ["Bilbao", "Heidenheim", "Koeln", "Hamburg", "Mainz", "Alaves", "Betis", "Verona", "Brest", "Forest", "Gladbach",
         "Leipzig", "Rayo", "Bayern", "Leverkusen"] + [f"Otro{i}" for i in range(5)])}
    esperado = {"Athletic Club": "Bilbao", "1. FC Heidenheim": "Heidenheim", "1. FC Köln": "Koeln", "Hamburger SV": "Hamburg",
                "FSV Mainz 05": "Mainz", "Deportivo Alaves": "Alaves", "Real Betis": "Betis", "Hellas Verona": "Verona",
                "Stade Brestois 29": "Brest", "Nottingham Forest": "Forest", "Borussia Monchengladbach": "Gladbach",
                "RB Leipzig": "Leipzig", "Rayo Vallecano": "Rayo", "Bayern Munich": "Bayern", "Bayer Leverkusen": "Leverkusen"}
    for api, club in esperado.items():
        assert clubelo.buscar_elo(api, r) == pytest.approx(r[club]), api
