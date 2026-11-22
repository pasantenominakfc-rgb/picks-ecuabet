"""Pruebas del tracker (DB temporal), validación de entradas y comandos de main."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import main
from picks import config


def pick(uid="u1", clave="1x2:1", af_id=1, cuota_ecuabet=None, monto=0.0, cuota_minima=1.5,
         inicio="2026-11-20T15:00:00-05:00"):
    return {"uid": uid, "af_id": af_id, "liga": "L", "inicio": inicio, "local": "A", "visita": "B", "clave": clave,
            "nombre": "n", "p": 0.6, "p_push": 0.0, "cuota_justa": 1.6, "cuota_minima": cuota_minima,
            "cuota_ecuabet": cuota_ecuabet, "monto": monto}


def resultado(t, af_id, gl, gv):
    with t.con() as c:
        c.execute("INSERT OR REPLACE INTO resultados (af_id,gl,gv,htl,htv) VALUES (?,?,?,0,0)", (af_id, gl, gv))


def fila(t, uid="u1", clave="1x2:1"):
    with t.con() as c:
        return dict(c.execute("SELECT * FROM picks WHERE uid=? AND clave=?", (uid, clave)).fetchone())


# ------------------------------------------------------------ tarea 1: liquidar / ROI real
def test_liquidar_ganada_perdida_nula(db):
    db.agregar_picks([pick("a", "1x2:1", 1), pick("b", "1x2:2", 2), pick("c", "dnb:1", 3)])
    for u, k in (("a", "1x2:1"), ("b", "1x2:2"), ("c", "dnb:1")):
        assert db.registrar_web(u, k, 2.0, 10)
    resultado(db, 1, 2, 0)
    resultado(db, 2, 2, 0)
    resultado(db, 3, 1, 1)
    assert db.liquidar() == 3
    assert (fila(db, "a")["estado"], fila(db, "a")["ganancia"]) == ("ganada", 10.0)
    assert (fila(db, "b", "1x2:2")["estado"], fila(db, "b", "1x2:2")["ganancia"]) == ("perdida", -10.0)
    assert (fila(db, "c", "dnb:1")["estado"], fila(db, "c", "dnb:1")["ganancia"]) == ("nula", 0.0)


def test_roi_real_excluye_no_registrados(db):
    db.agregar_picks([pick("a", "1x2:1", 1, cuota_ecuabet=2.0, monto=10), pick("b", "1x2:1", 2, monto=0)])
    assert db.registrar_web("a", "1x2:1", 2.0, 10)
    resultado(db, 1, 2, 0)
    resultado(db, 2, 2, 0)
    db.liquidar()
    r = db.resumen()
    assert r["n"] == 1 and r["apostado"] == 10 and r["neto"] == 10.0
    assert fila(db, "b")["ganancia"] is None            # no se inventa ganancia real
    assert r["teorico"]["n"] == 2                        # la vista hipotética sí lo ve, rotulada aparte


def test_cuota_scrapeada_no_cuenta_como_registrada(db):
    db.agregar_picks([pick("a", "1x2:1", 1, cuota_ecuabet=2.0, monto=10)])
    resultado(db, 1, 2, 0)
    db.liquidar()
    assert db.resumen()["n"] == 0


def test_cuota_cero_o_none_es_no_registrada(db):
    db.agregar_picks([pick("a", "1x2:1", 1, cuota_ecuabet=0, monto=10)])
    resultado(db, 1, 2, 0)
    db.liquidar()
    assert db.resumen()["n"] == 0


# ------------------------------------------------------------ tarea 2: tipo
def test_registrar_conserva_tipo_y_resumen_incluye_todos(db):
    db.agregar_picks([pick("a", "1x2:1", 1)], "segura")
    db.agregar_picks([pick("b", "1x2:1", 2)], "valor")
    assert db.registrar_web("a", "1x2:1", 1.5, 20) and db.registrar_web("b", "1x2:1", 2.0, 10)
    assert fila(db, "a")["tipo"] == "segura"
    resultado(db, 1, 2, 0)
    resultado(db, 2, 2, 0)
    db.liquidar()
    r = db.resumen()
    assert r["n"] == 2 and set(r["por_tipo"]) == {"segura", "valor"}


# ------------------------------------------------------------ tarea 3: validación
@pytest.mark.parametrize("cuota,monto", [
    (float("nan"), 10), (float("inf"), 10), (1.0, 10), (1.0099, 10), (-5, 10), (0, 10), ("abc", 10), (100.01, 10),
    (2.0, 0), (2.0, -1), (2.0, float("nan")), (2.0, float("inf")), (2.0, 10001), (True, 10), (None, 10)])
def test_registrar_web_rechaza_invalidos(db, cuota, monto):
    db.agregar_picks([pick()])
    assert db.registrar_web("u1", "1x2:1", cuota, monto) is False
    f = fila(db)
    assert f["cuota_tomada"] is None and f["monto"] == 0.0


def test_registrar_web_coma_decimal(db):
    db.agregar_picks([pick()])
    assert db.registrar_web("u1", "1x2:1", "1,85", "12,5") is True
    f = fila(db)
    assert f["cuota_tomada"] == 1.85 and f["monto"] == 12.5


@pytest.mark.parametrize("uid,clave", [("a b", "1x2:1"), ("u1;DROP", "1x2:1"), ("u1", ""), ("x" * 65, "1x2:1")])
def test_uid_clave_invalidos(db, uid, clave):
    db.agregar_picks([pick()])
    assert db.registrar_web(uid, clave, 2.0, 10) is False
    assert not db.omitir_web(uid, clave)


def test_claves_reales_de_mercado_pasan_regex(db):
    from picks import mercados as M
    for k in M.todas_las_claves():
        assert db.clave_valida(k), k


def test_registrar_sobre_liquidado_rechazado(db):
    db.agregar_picks([pick()])
    assert db.registrar_web("u1", "1x2:1", 2.0, 10)
    resultado(db, 1, 2, 0)
    db.liquidar()
    antes = fila(db)
    assert db.registrar_web("u1", "1x2:1", 5.0, 99) is False
    assert fila(db) == antes
    assert db.omitir_web("u1", "1x2:1") is False and fila(db)["estado"] == "ganada"


def test_agregar_picks_idempotente(db):
    db.agregar_picks([pick()])
    db.registrar_web("u1", "1x2:1", 2.0, 10)
    db.agregar_picks([pick(cuota_ecuabet=9.9, monto=77)])
    with db.con() as c:
        assert c.execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 1
    assert fila(db)["cuota_tomada"] == 2.0


def test_omitir_web_fuera_del_resumen(db):
    db.agregar_picks([pick()])
    assert db.omitir_web("u1", "1x2:1") is True
    resultado(db, 1, 2, 0)
    db.liquidar()
    assert fila(db)["estado"] == "no_apostada" and db.resumen()["n"] == 0


# ------------------------------------------------------------ tarea 4: resultados / zona horaria
class AFFalso:
    activa = True

    def __init__(self, estado="FT", gl=2, gv=0, af_id=1):
        self.llamadas, self.estado, self.gl, self.gv, self.af_id = [], estado, gl, gv, af_id

    def _get(self, ruta, cache_horas=0, **params):
        self.llamadas.append((ruta, params))
        return {"response": [{"fixture": {"id": self.af_id, "date": "2026-11-20T15:00:00-05:00",
                                          "status": {"short": self.estado}},
                              "league": {"id": 1, "season": 2026, "name": "L", "country": "C"},
                              "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
                              "goals": {"home": self.gl, "away": self.gv},
                              "score": {"halftime": {"home": 0, "away": 0}}}]}

    @staticmethod
    def _fixture(f):
        from picks.fuentes.apifootball import APIFootball
        return APIFootball._fixture(f)

    def estadisticas(self, fid, peso):
        return None


def _con_prediccion(db, inicio):
    db.agregar_picks([pick(inicio=inicio)])
    db.registrar_web("u1", "1x2:1", 2.0, 10)
    with db.con() as c:
        c.execute("INSERT INTO predicciones VALUES ('u1',1,?, 'ensamble','1x2:1',0.6)", (inicio,))


AHORA = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def test_resultados_pasa_timezone_y_liquida(db):
    _con_prediccion(db, "2026-11-20T15:00:00-05:00")
    af = AFFalso()
    assert db.actualizar_resultados(af, {}, AHORA) == 1
    assert af.llamadas[0][1].get("timezone") == "America/Guayaquil"
    assert fila(db)["estado"] == "ganada"


def test_resultados_ventana_10_dias_y_offsets(db):
    # hace 8 días (dentro de 10) y con offset +00:00 distinto al de Ecuador
    _con_prediccion(db, "2026-11-14T20:00:00+00:00")
    af = AFFalso()
    db.actualizar_resultados(af, {}, AHORA)
    assert af.llamadas and af.llamadas[0][1]["date"] == "2026-11-14"


def test_resultados_fuera_de_ventana_no_consulta(db):
    _con_prediccion(db, "2026-11-01T20:00:00-05:00")
    af = AFFalso()
    db.actualizar_resultados(af, {}, AHORA)
    assert not af.llamadas


@pytest.mark.parametrize("estado", ["CANC", "ABD", "AWD"])
def test_partido_cancelado_marca_nula(db, estado):
    _con_prediccion(db, "2026-11-20T15:00:00-05:00")
    db.actualizar_resultados(AFFalso(estado=estado, gl=None, gv=None), {}, AHORA)
    f = fila(db)
    assert f["estado"] == "nula" and f["ganancia"] == 0.0


@pytest.mark.parametrize("estado", ["PST", "SUSP", "INT"])
def test_aplazado_reciente_sigue_pendiente_con_marca(db, estado):
    _con_prediccion(db, "2026-11-20T15:00:00-05:00")
    db.actualizar_resultados(AFFalso(estado=estado, gl=None, gv=None), {}, AHORA)
    f = fila(db)
    assert f["estado"] == "pendiente" and f["aplazado_desde"]


@pytest.mark.parametrize("estado", ["PST", "SUSP", "INT"])
def test_aplazado_7_dias_se_anula(db, estado):
    _con_prediccion(db, "2026-11-14T15:00:00-05:00")      # hace 8 días
    db.actualizar_resultados(AFFalso(estado=estado, gl=None, gv=None), {}, AHORA)
    f = fila(db)
    assert f["estado"] == "nula" and f["ganancia"] == 0.0 and f["aplazado_desde"]


def test_aplazado_se_anula_aunque_la_api_ya_no_lo_devuelva(db):
    _con_prediccion(db, "2026-11-14T15:00:00-05:00")
    with db.con() as c:
        c.execute("UPDATE picks SET aplazado_desde='2026-11-15T00:00:00+00:00'")
    af = SimpleNamespace(activa=True, _get=lambda *a, **k: {"response": []}, _fixture=AFFalso._fixture,
                         estadisticas=lambda *a: None)
    db.actualizar_resultados(af, {}, AHORA)
    assert fila(db)["estado"] == "nula"


def test_nula_por_aplazamiento_se_reabre_con_ft(db):
    _con_prediccion(db, "2026-11-14T15:00:00-05:00")
    db.actualizar_resultados(AFFalso(estado="PST", gl=None, gv=None), {}, AHORA)
    assert fila(db)["estado"] == "nula"
    db.actualizar_resultados(AFFalso(estado="FT", gl=2, gv=0), {}, AHORA)
    f = fila(db)
    assert f["estado"] == "ganada" and f["ganancia"] == 10.0


def test_cancelado_no_se_reabre_si_nunca_fue_aplazado(db):
    _con_prediccion(db, "2026-11-20T15:00:00-05:00")
    db.actualizar_resultados(AFFalso(estado="CANC", gl=None, gv=None), {}, AHORA)
    db.actualizar_resultados(AFFalso(estado="FT"), {}, AHORA)
    assert fila(db)["estado"] == "nula"


def test_ventana_14_dias_solo_para_aplazados(db):
    _con_prediccion(db, "2026-11-10T15:00:00-05:00")      # hace 12 días
    af = AFFalso()
    db.actualizar_resultados(af, {}, AHORA)
    assert not af.llamadas
    with db.con() as c:
        c.execute("UPDATE picks SET aplazado_desde='2026-11-11T00:00:00+00:00'")
    db.actualizar_resultados(af, {}, AHORA)
    assert af.llamadas and fila(db)["estado"] == "ganada"


def test_migracion_aplazado_idempotente(db):
    with db.con() as c:
        cols = [r["name"] for r in c.execute("PRAGMA table_info(picks)")]
    assert cols.count("aplazado_desde") == 1


def test_migracion_db_vieja_sin_columnas(db):
    import sqlite3
    c = sqlite3.connect(db.RUTA)
    c.execute("CREATE TABLE picks (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, tipo TEXT, uid TEXT, "
              "af_id INTEGER, liga TEXT, inicio TEXT, local TEXT, visita TEXT, clave TEXT, nombre TEXT, p REAL, "
              "p_push REAL, cuota_justa REAL, cuota_minima REAL, cuota_tomada REAL, monto REAL, "
              "estado TEXT DEFAULT 'pendiente', ganancia REAL, UNIQUE(uid, clave))")
    c.commit()
    c.close()
    for _ in range(2):
        with db.con() as c2:
            cols = {r["name"] for r in c2.execute("PRAGMA table_info(picks)")}
        assert {"registrado", "aplazado_desde"} <= cols


def test_hoy_ec_con_zona():
    from picks import tracker
    assert tracker.hoy_ec().utcoffset() == timedelta(hours=-5)


# ------------------------------------------------------------ tarea 5: main
def lote(items):
    return main.registrar_lote(items if isinstance(items, str) else json.dumps(items))


def test_lote_parcialmente_invalido_sale_1_y_registra_validos(db, capsys):
    db.agregar_picks([pick("a", "1x2:1", 1), pick("b", "1x2:1", 2)])
    items = [{"uid": "a", "clave": "1x2:1", "accion": "registrar", "cuota": "1,85", "monto": 10},
             {"uid": "zzz", "clave": "1x2:1", "accion": "registrar", "cuota": 2, "monto": 10},
             {"uid": "b", "clave": "1x2:1", "accion": "registrar", "cuota": float("nan"), "monto": 10},
             {"uid": "b", "clave": "1x2:1", "accion": "omitir"}]
    assert lote(items) == 1
    out = capsys.readouterr().out
    assert out.count("✔") == 2 and out.count("✘") == 2
    assert fila(db, "a")["cuota_tomada"] == 1.85 and fila(db, "b")["estado"] == "no_apostada"


def test_lote_todo_ok_sale_0(db):
    db.agregar_picks([pick("a", "1x2:1", 1)])
    assert lote([{"uid": "a", "clave": "1x2:1", "accion": "registrar", "cuota": 2, "monto": 5}]) == 0


def test_lote_max_50_json_malo_y_accion_desconocida(db):
    item = {"uid": "a", "clave": "1x2:1", "accion": "omitir"}
    assert lote([item] * 51) == 1
    assert lote("no es json") == 1
    assert lote([{"uid": "a", "clave": "1x2:1", "accion": "borrar"}]) == 1
    assert lote({"uid": "a"}) == 1


def test_comando_registrar_web_pick_inexistente_sale_distinto_de_0(db, monkeypatch):
    monkeypatch.setattr(main.exportar, "historial", lambda: None)
    monkeypatch.setattr(main.config, "cargar", lambda: {})
    monkeypatch.setattr("sys.argv", ["main.py", "registrar-web", "nada", "1x2:1", "2", "10"])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert e.value.code not in (0, None)


def test_comando_registrar_web_coma_ok(db, monkeypatch):
    db.agregar_picks([pick()])
    monkeypatch.setattr(main.exportar, "historial", lambda: None)
    monkeypatch.setattr(main.config, "cargar", lambda: {})
    monkeypatch.setattr("sys.argv", ["main.py", "registrar-web", "u1", "1x2:1", "1,85", "10"])
    main.main()
    assert fila(db)["cuota_tomada"] == 1.85


def test_comando_lote_lee_env_y_sale_1(db, monkeypatch):
    db.agregar_picks([pick()])
    monkeypatch.setattr(main.exportar, "historial", lambda: None)
    monkeypatch.setattr(main.config, "cargar", lambda: {})
    monkeypatch.setenv("LOTE", json.dumps([{"uid": "x", "clave": "1x2:1", "accion": "omitir"}]))
    monkeypatch.setattr("sys.argv", ["main.py", "registrar-lote"])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert e.value.code == 1


def test_hoy_sin_partidos_no_publica(db, monkeypatch, capsys):
    af = SimpleNamespace(activa=False, restantes=0)
    monkeypatch.setattr(main, "clientes", lambda cfg: (af, None, None))
    monkeypatch.setattr(main.pipeline, "analizar", lambda *a, **k: [])

    def prohibido(*a, **k):
        raise AssertionError("no debe publicar")
    for fn in ("hoy", "historial", "fuentes"):
        monkeypatch.setattr(main.exportar, fn, prohibido)
    monkeypatch.setattr(main.report, "guardar", prohibido)
    main.hoy({})
    assert "sin datos: no se publica" in capsys.readouterr().out


class _R:
    def __init__(self, ok=True, status_code=200):
        self.ok, self.status_code = ok, status_code


def _cfg(**kw):
    base = {"api_football_key": "k", "odds_api_key": "", "apify_token": "", "groq_api_key": "", "ligas": []}
    return {**base, **kw}


def _af_ok(monkeypatch, explota=False):
    class AF:
        def __init__(self, k):
            pass

        def _get(self, ruta, **kw):
            if explota:
                raise RuntimeError("boom")
            if ruta == "/status":
                return {"response": {"requests": {"current": 1, "limit_day": 100}, "subscription": {"plan": "f"}}}
            return {"response": []}
    monkeypatch.setattr(main, "APIFootball", AF)


def test_verificar_groq_invalida_falla(monkeypatch):
    _af_ok(monkeypatch)
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: _R(False, 401))
    assert main.verificar(_cfg(groq_api_key="mala")) is False


def test_verificar_odds_invalida_falla(monkeypatch):
    _af_ok(monkeypatch)

    class O:
        restantes = None

        def __init__(self, k):
            pass

        def deportes(self):
            pass
    monkeypatch.setattr(main, "OddsAPI", O)
    assert main.verificar(_cfg(odds_api_key="mala")) is False


def test_verificar_telegram_sin_chat_falla(monkeypatch):
    _af_ok(monkeypatch)
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert main.verificar(_cfg()) is False


def test_verificar_status_con_excepcion_no_traceback(monkeypatch, capsys):
    _af_ok(monkeypatch, explota=True)
    assert main.verificar(_cfg()) is False
    assert "✘" in capsys.readouterr().out


# ------------------------------------------------------------ tarea 6: config
@pytest.mark.parametrize("valor", ["abc", "nan", "inf", "-5", "0"])
def test_banca_invalida_se_ignora(monkeypatch, capsys, valor):
    monkeypatch.delenv("BANCA", raising=False)
    base = config.cargar()["banca"]
    monkeypatch.setenv("BANCA", valor)
    assert config.cargar()["banca"] == base
    assert "BANCA" in capsys.readouterr().out


def test_banca_valida(monkeypatch):
    monkeypatch.setenv("BANCA", "250.5")
    assert config.cargar()["banca"] == 250.5


# ------------------------------------------------------------ ronda 2
@pytest.mark.parametrize("uid", ["100\n", "a\n"])
def test_uid_con_salto_de_linea_rechazado(db, uid):
    db.agregar_picks([pick("100"), pick("a")])
    assert not db.clave_valida(uid)
    assert db.registrar_web(uid, "1x2:1", 2.0, 10) is False


def test_uid_entero_aceptado(db):
    db.agregar_picks([pick("100")])
    assert db.registrar_web(100, "1x2:1", 2.0, 10) is True
    assert db.clave_valida(100) and not db.clave_valida(True) and not db.clave_valida(1.5)


def test_lote_no_imprime_saltos_de_linea_de_uid(db, capsys):
    lote([{"uid": "x\nINYECTADO ✔ #9", "clave": "1x2:1", "accion": "registrar", "cuota": 2, "monto": 1}])
    out = capsys.readouterr().out
    assert "\nINYECTADO" not in out and "\\n" in out


def test_omitir_tras_registrar_limpia_registro(db):
    db.agregar_picks([pick()])
    assert lote([{"uid": "u1", "clave": "1x2:1", "accion": "registrar", "cuota": 2, "monto": 10},
                 {"uid": "u1", "clave": "1x2:1", "accion": "omitir"}]) == 0
    f = fila(db)
    assert f["estado"] == "no_apostada" and f["registrado"] == 0
    assert f["cuota_tomada"] is None and not f["monto"] and f["ganancia"] is None


def test_lote_duplicado_gana_el_ultimo(db):
    db.agregar_picks([pick()])
    lote([{"uid": "u1", "clave": "1x2:1", "accion": "registrar", "cuota": 2, "monto": 10},
          {"uid": "u1", "clave": "1x2:1", "accion": "registrar", "cuota": 3, "monto": 20}])
    f = fila(db)
    assert f["cuota_tomada"] == 3 and f["monto"] == 20


def test_comando_lote_guarda_validos_y_sale_1_aunque_falle_exportar(db, monkeypatch):
    db.agregar_picks([pick("a", "1x2:1", 1)])

    def explota():
        raise RuntimeError("fallo al exportar")
    monkeypatch.setattr(main.exportar, "historial", explota)
    monkeypatch.setattr(main.config, "cargar", lambda: {})
    monkeypatch.setenv("LOTE", json.dumps([
        {"uid": "zz", "clave": "1x2:1", "accion": "registrar", "cuota": 2, "monto": 1},
        {"uid": "a", "clave": "1x2:1", "accion": "registrar", "cuota": 2, "monto": 5}]))
    monkeypatch.setattr("sys.argv", ["main.py", "registrar-lote"])
    with pytest.raises(SystemExit) as e:
        main.main()
    assert e.value.code == 1
    assert fila(db, "a")["registrado"] == 1


def test_filas_de_picks_traen_registrado(db):
    db.agregar_picks([pick()])
    with db.con() as c:
        assert "registrado" in dict(c.execute("SELECT * FROM picks").fetchone())


def _hoy_stubs(monkeypatch, tmp_path, af, partidos):
    monkeypatch.setattr(main, "clientes", lambda cfg: (af, SimpleNamespace(restantes=0), None))
    monkeypatch.setattr(main.pipeline, "analizar", lambda *a, **k: partidos)
    monkeypatch.setattr(main.pipeline, "picks_por_dia", lambda *a, **k: {})
    for fn in ("guardar_predicciones", "agregar_picks"):
        monkeypatch.setattr(main.tracker, fn, lambda *a, **k: None)
    txt = tmp_path / "r.txt"
    txt.write_text("reporte", encoding="utf-8")
    monkeypatch.setattr(main.report, "guardar", lambda *a, **k: (tmp_path / "r.html", txt))
    monkeypatch.setattr(main.report, "texto_niveles", lambda *a, **k: "")
    monkeypatch.setattr(main.exportar, "historial", lambda: None)
    monkeypatch.setattr(main.exportar, "fuentes", lambda cfg: None)
    monkeypatch.setattr(main, "telegram", lambda m: None)


def test_hoy_pasa_estado_con_cuota_agotada(db, monkeypatch, tmp_path):
    from picks.pipeline import ResultadoAnalisis
    af = SimpleNamespace(activa=False, restantes=0, sin_cuota=True)
    partidos = ResultadoAnalisis([{"fecha": "2026-11-22"}], {"ligas_sin_datos": ["X"]})
    _hoy_stubs(monkeypatch, tmp_path, af, partidos)
    capt = {}
    monkeypatch.setattr(main.exportar, "hoy", lambda *a, **k: capt.update(k))
    main.hoy({"groq_api_key": ""})
    assert capt["estado"]["cuota_agotada"] is True and capt["estado"]["ligas_sin_datos"] == ["X"]


def test_hoy_json_trae_aviso_si_cuota_agotada(monkeypatch):
    from picks import exportar
    guardado = {}
    monkeypatch.setattr(exportar, "_guardar", lambda nombre, datos: guardado.update({nombre: datos}))
    exportar.hoy([], {}, {}, "x", estado={"cuota_agotada": True})
    assert guardado["hoy.json"]["aviso"]
