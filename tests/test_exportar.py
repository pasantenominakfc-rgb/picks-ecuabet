"""Pruebas de picks/exportar.py: los JSON públicos no deben filtrar banca ni dólares y deben ser JSON estricto."""
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from picks import config, exportar, tracker  # noqa: E402


def _estricto(texto: str):
    """json.loads que falla ante NaN/Infinity (JSON inválido para el navegador)."""
    def malo(c):
        raise AssertionError(f"constante no válida en JSON: {c}")
    return json.loads(texto, parse_constant=malo)


def _claves(x, acumulado=None):
    acumulado = set() if acumulado is None else acumulado
    if isinstance(x, dict):
        for k, v in x.items():
            acumulado.add(k)
            _claves(v, acumulado)
    elif isinstance(x, list):
        for v in x:
            _claves(v, acumulado)
    return acumulado


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(exportar, "WEB", tmp_path / "web_data")
    monkeypatch.setattr(tracker, "RUTA", tmp_path / "sistema.db")
    return tmp_path


def _pick(**extra):
    base = dict(uid="1", af_id=1, liga="Premier League", inicio="2026-11-22T15:00:00-05:00", local="A", visita="B",
                clave="1x2:1", nombre="Gana A", mercado="1x2", p=0.6, p_push=0, cuota_justa=1.67, cuota_minima=1.75,
                cuota_ecuabet=None, mejor_cuota=1.9, mejor_casa="X", ev=0.1, acuerdo=1.0, confianza=0.8,
                n_fuentes=3, dispersion=0.02, detalle={"mercado": 0.6}, pesos={"mercado": 1.0}, monto=3.5,
                confirmado=False, ia=None, cuota_est=1.8, tipo_cuota="estimada", cuota_es_estimada=True, region="Europa", fecha="2026-11-22")
    base.update(extra)
    return base


def _datos_hoy(p=0.6):
    pick = _pick(p=p)
    partido = {"uid": "1", "af_id": 1, "liga": "Premier League", "region": "Europa", "fecha": "2026-11-22",
               "inicio": pick["inicio"], "local": "A", "visita": "B", "fuentes": {"mercado": {}},
               "probs": {"1x2:1": {"p": p}}, "evaluadas": [pick]}
    grande = {"objetivo": 100, "monto": 5.0, "ganancia": 100.0, "cuota": 20.0, "p": 0.04, "ev": -0.2,
              "ev_estimado": -0.2, "cuota_es_estimada": True, "pago": 100.0, "piernas": [pick]}
    dias = {"2026-11-22": {"valor": [pick], "alta": [], "seguras": [pick], "grandes": [grande]}}
    return [partido], dias


def _cfg():
    return config.cargar()


def test_hoy_no_publica_banca_ni_montos(aislado):
    partidos, dias = _datos_hoy()
    exportar.hoy(partidos, dias, _cfg(), "API-Football: 90")
    datos = _estricto((aislado / "web_data" / "hoy.json").read_text(encoding="utf-8"))
    assert "banca" not in _claves(datos)
    assert "banca" not in datos["config"]
    for k in ("fraccion_kelly", "stake_max_pct", "stake_minimo", "exposicion_dia_pct", "ventaja_minima"):
        assert k in datos["config"], k
    d = datos["dias"]["2026-11-22"]
    for lista in ("valor", "alta", "seguras"):
        for s in d[lista]:
            assert "monto" not in s and "ganancia" not in s
    comb = d.get("combinada")
    assert comb is None or "monto" not in comb


def test_hoy_metadatos_y_aviso(aislado):
    partidos, dias = _datos_hoy()
    exportar.hoy(partidos, dias, _cfg(), "simulación")
    datos = _estricto((aislado / "web_data" / "hoy.json").read_text(encoding="utf-8"))
    assert datos["simulacion"] is True
    assert datos["generado"].endswith("-05:00")           # America/Guayaquil
    assert not datos.get("aviso")
    exportar.hoy(partidos, dias, _cfg(), "API-Football: 0", estado={"cuota_agotada": True, "ligas_sin_datos": ["MLS", "Serie A"]})
    datos = _estricto((aislado / "web_data" / "hoy.json").read_text(encoding="utf-8"))
    assert datos["simulacion"] is False
    assert "cuota" in datos["aviso"] and "2" in datos["aviso"]
    exportar.hoy(partidos, dias, _cfg(), "API-Football: 5", estado={})   # sin claves: no rompe
    assert not _estricto((aislado / "web_data" / "hoy.json").read_text(encoding="utf-8")).get("aviso")


def test_grandes_ganancia_neta(aislado):
    partidos, dias = _datos_hoy()
    exportar.hoy(partidos, dias, _cfg(), "x")
    g = _estricto((aislado / "web_data" / "hoy.json").read_text(encoding="utf-8"))["dias"]["2026-11-22"]["grandes"][0]
    assert g["cobro_total"] == pytest.approx(5.0 * 20.0)
    assert g["ganancia"] == pytest.approx(5.0 * 19.0)      # neta = monto*(cuota-1)


def test_hoy_sin_nan_ni_infinity(aislado):
    partidos, dias = _datos_hoy(p=float("nan"))
    dias["2026-11-22"]["valor"][0]["ev"] = float("inf")
    exportar.hoy(partidos, dias, _cfg(), "x")
    texto = (aislado / "web_data" / "hoy.json").read_text(encoding="utf-8")
    assert "NaN" not in texto and "Infinity" not in texto
    _estricto(texto)


def _sembrar(filas):
    """filas: (tipo, clave, estado, cuota, monto, ganancia, inicio[, registrado=1])."""
    with tracker.con() as c:
        for i, fila in enumerate(filas):
            tipo, clave, estado, cuota, monto, gan, ini = fila[:7]
            reg = fila[7] if len(fila) > 7 else 1
            c.execute("""INSERT INTO picks (fecha,tipo,uid,af_id,liga,inicio,local,visita,clave,nombre,p,p_push,cuota_justa,
                         cuota_minima,cuota_tomada,monto,estado,ganancia,registrado) VALUES
                         ('2026-11-01',?,?,?, 'L',?, 'A','B',?, 'n',0.6,0,1.6,1.7,?,?,?,?,?)""",
                      (tipo, str(i), i, ini, clave, cuota, monto, estado, gan, reg))


def _leer_hist(aislado):
    return _estricto((aislado / "web_data" / "historial.json").read_text(encoding="utf-8"))


def test_historial_sin_dolares_y_con_unidades(aislado):
    _sembrar([("valor", "1x2:1", "ganada", 2.0, 10.0, 10.0, "2026-11-01T15:00:00"),
              ("valor", "ou:2.5:over", "perdida", 2.0, 4.0, -4.0, "2026-11-02T15:00:00"),
              ("valor", "btts:si", "pendiente", 1.9, 5.0, None, "2026-11-03T15:00:00"),
              ("valor", "1x2:2", "ganada", None, 0.0, 0.0, "2026-11-04T15:00:00", 0),   # no registrada
              ("segura", "dc:1X", "ganada", None, 0.0, 0.0, "2026-11-05T15:00:00", 0)])
    exportar.historial()
    datos = _leer_hist(aislado)
    claves = _claves(datos)
    assert not ({"banca", "monto", "ganancia", "neto", "apostado"} & claves), claves & {"banca", "monto", "ganancia"}
    por = {f["clave"]: f for f in datos["picks"]}
    assert por["1x2:1"]["u"] == pytest.approx(1.0)
    assert por["ou:2.5:over"]["u"] == pytest.approx(-1.0)
    assert por["btts:si"]["u"] is None                     # pendiente
    assert por["1x2:2"]["u"] is None                       # no registrada: no hay unidades
    r = datos["resumen"]
    assert r["n"] == 2 and r["acierto"] == pytest.approx(0.5)
    assert r["roi"] == pytest.approx(6.0 / 14.0, abs=1e-3)           # solo apuestas registradas por el usuario
    assert r["por_tipo"]["valor"]["n"] == 2
    assert all(set(v) <= {"n", "roi"} for v in r["por_mercado"].values())
    assert datos["curva"][-1]["u"] == pytest.approx(0.0)   # +1 -1 unidades acumuladas


def test_unidades_solo_filas_registradas():
    base = {"estado": "ganada", "monto": 10.0, "ganancia": 10.0}
    assert exportar._unidades({**base, "registrado": 1}) == pytest.approx(1.0)
    assert exportar._unidades({**base, "registrado": 0}) is None      # monto/ganancia de relleno: no cuenta
    assert exportar._unidades({**base}) is None                       # sin la columna: tampoco
    assert exportar._unidades({**base, "registrado": 1, "estado": "pendiente"}) is None


def test_curva_y_kpi_cuentan_todos_los_tipos_registrados(aislado):
    _sembrar([("valor", "1x2:1", "ganada", 2.0, 10.0, 10.0, "2026-11-01T15:00:00"),
              ("segura", "dc:1X", "perdida", 1.4, 5.0, -5.0, "2026-11-02T15:00:00"),
              ("alta", "ou:2.5:over", "ganada", 1.5, 4.0, 2.0, "2026-11-03T15:00:00"),
              ("segura", "dc:X2", "ganada", 1.4, 5.0, 2.0, "2026-11-04T15:00:00", 0)])   # sin registrar: fuera
    exportar.historial()
    datos = _leer_hist(aislado)
    assert [round(p["u"], 2) for p in datos["curva"]] == [1.0, 0.0, 0.5]   # +1, -1, +0.5 (todos los tipos)
    r = datos["resumen"]
    assert r["n"] == 3
    assert r["unidades"] == pytest.approx(0.5)             # la web lo muestra en el KPI "Unidades"
    assert set(r["por_tipo"]) == {"valor", "segura", "alta"}


def test_historial_expone_registrado(aislado):
    _sembrar([("valor", "1x2:1", "ganada", 2.0, 10.0, 10.0, "2026-11-01T15:00:00", 1),
              ("valor", "1x2:2", "pendiente", None, 0.0, None, "2026-11-02T15:00:00", 0)])
    exportar.historial()
    por = {f["clave"]: f for f in _leer_hist(aislado)["picks"]}
    assert por["1x2:1"]["registrado"] == 1 and por["1x2:2"]["registrado"] == 0


def test_hoy_expone_campos_que_la_web_necesita(aislado):
    partidos, dias = _datos_hoy()
    exportar.hoy(partidos, dias, _cfg(), "x")
    d = _estricto((aislado / "web_data" / "hoy.json").read_text(encoding="utf-8"))["dias"]["2026-11-22"]
    for lista in ("seguras", "valor"):
        assert d[lista][0]["cuota_es_estimada"] is True, lista     # sin esto la web pierde el aviso de cuota estimada
    g = d["grandes"][0]
    assert g["ev_estimado"] == pytest.approx(-0.2)
    assert g["cuota_es_estimada"] is True
    assert g["cobro_total"] == pytest.approx(100.0)
    assert "monto" in g                                    # monto de la combinada sugerida (no es la banca)
    assert not ({"banca"} & _claves(d))


# ---- contrato con web/app.js: toda clave de pick/combinada/resumen que la web lee debe exportarse
WEB_JS = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
# claves que la web calcula por su cuenta o que no son del JSON (variable `s` es muy genérica en app.js)
_PROPIAS_WEB = {"monto", "_k", "_t", "classList", "querySelectorAll", "pts", "color", "name", "uid", "clave"}


def _usadas(var: str) -> set:
    import re
    return set(re.findall(rf"\b{var}\.([A-Za-z_]\w*)", WEB_JS))


def _exportado_hoy(aislado):
    partidos, dias = _datos_hoy()
    exportar.hoy(partidos, dias, _cfg(), "x")
    return _estricto((aislado / "web_data" / "hoy.json").read_text(encoding="utf-8"))["dias"]["2026-11-22"]


def test_contrato_picks_web(aislado):
    d = _exportado_hoy(aislado)
    producidas = _claves(d["seguras"]) | _claves(d["valor"])
    necesarias = {"p_push", "p", "inicio", "detalle", "pesos", "ia", "cuota_es_estimada", "cuota_ecuabet",
                  "cuota_minima", "cuota_justa", "confirmado", "mejor_cuota", "mejor_casa", "ev", "tipo_cuota",
                  "cuota_est", "liga", "mercado", "local", "visita", "nombre", "uid", "clave", "n_fuentes"}
    faltan = necesarias - producidas
    assert not faltan, f"la web usa estas claves de pick y exportar no las produce: {sorted(faltan)}"
    # deriva: toda clave `s.xxx` de app.js debe estar entre las exportadas, las del pool o las propias de la web
    pool = _claves(d["pool"]) | {"eficiencia"}
    desconocidas = _usadas("s") - producidas - pool - _PROPIAS_WEB - {"length", "ia", "riesgo", "resumen", "alertas"}
    assert not desconocidas, f"app.js lee s.{sorted(desconocidas)} y exportar no las produce"


def test_contrato_combinadas_web(aislado):
    g = _exportado_hoy(aislado)["grandes"][0]
    for k in ("cuota", "p", "ganancia", "ev_estimado", "ev", "piernas", "monto", "objetivo"):
        assert k in g, k


def test_contrato_historial_web(aislado):
    _sembrar([("valor", "1x2:1", "ganada", 2.0, 10.0, 10.0, "2026-11-01T15:00:00")])
    exportar.historial()
    H = _leer_hist(aislado)
    for k in ("resumen", "curva", "picks"):
        assert k in H
    for k in ("n", "acierto", "roi", "unidades", "por_mercado"):       # H.resumen.* que lee vRend()
        assert k in H["resumen"], k
    for k in ("estado", "tipo", "u", "nombre", "local", "visita", "inicio", "cuota_tomada", "cuota_minima", "registrado"):
        assert k in H["picks"][0], k                                     # p.* que lee la tabla de pendientes/liquidadas


def test_historial_vacio(aislado):
    exportar.historial()
    datos = _leer_hist(aislado)
    assert datos["picks"] == [] and datos["resumen"]["n"] == 0
