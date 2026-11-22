"""Pruebas de liquidación de mercados, Kelly, combinadas, niveles (seguras/grandes) y selección de valor."""
import os
import sys

import pytest

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]

from picks import config, mercados as M, niveles, seleccion  # noqa: E402


# ------------------------------------------------------- tabla de verdad
def R(gl=None, gv=None, htl=None, htv=None, corners=None, cards=None):
    return {"gl": gl, "gv": gv, "htl": htl, "htv": htv, "corners": corners, "cards": cards}


TABLA = [
    # 1x2
    ("1x2:1", R(2, 1), "ganada"), ("1x2:1", R(1, 1), "perdida"), ("1x2:X", R(1, 1), "ganada"),
    ("1x2:2", R(2, 1), "perdida"), ("1x2:2", R(0, 3), "ganada"),
    # doble oportunidad
    ("dc:1X", R(1, 1), "ganada"), ("dc:12", R(1, 1), "perdida"), ("dc:12", R(2, 1), "ganada"),
    ("dc:X2", R(2, 1), "perdida"), ("dc:X2", R(1, 1), "ganada"),
    # sin empate
    ("dnb:1", R(1, 1), "nula"), ("dnb:2", R(0, 0), "nula"), ("dnb:1", R(2, 1), "ganada"),
    ("dnb:2", R(2, 1), "perdida"),
    # ambos marcan
    ("btts:si", R(1, 1), "ganada"), ("btts:si", R(1, 0), "perdida"), ("btts:no", R(1, 0), "ganada"),
    ("btts:no", R(2, 2), "perdida"),
    # goles totales (.5, enteras y cuartos)
    ("ou:2.5:over", R(2, 1), "ganada"), ("ou:2.5:under", R(2, 1), "perdida"),
    ("ou:2.5:under", R(1, 1), "ganada"),
    ("ou:2.0:over", R(1, 1), "nula"), ("ou:2.0:under", R(1, 1), "nula"),
    ("ou:2.0:over", R(2, 1), "ganada"), ("ou:2.0:under", R(1, 0), "ganada"), ("ou:2.0:under", R(2, 1), "perdida"),
    ("ou:2.25:over", R(1, 1), None), ("ou:2.75:under", R(2, 1), None),
    # goles del local / de la visita
    ("tl:1.5:over", R(2, 0), "ganada"), ("tl:1.5:under", R(2, 0), "perdida"), ("tl:1.0:over", R(1, 0), "nula"),
    ("tv:0.5:under", R(2, 0), "ganada"), ("tv:0.5:over", R(2, 0), "perdida"), ("tv:1.0:under", R(0, 1), "nula"),
    # hándicap asiático
    ("ah:-0.5:1", R(1, 0), "ganada"), ("ah:-1.5:1", R(1, 0), "perdida"), ("ah:-1.5:2", R(1, 0), "ganada"),
    ("ah:+0.5:2", R(0, 1), "ganada"), ("ah:+0.5:1", R(0, 1), "perdida"),
    ("ah:+0.0:1", R(1, 1), "nula"), ("ah:+0.0:2", R(1, 1), "nula"), ("ah:+0.0:1", R(2, 1), "ganada"),
    ("ah:-1.0:1", R(2, 1), "nula"), ("ah:-1.0:1", R(3, 1), "ganada"), ("ah:-1.0:1", R(1, 1), "perdida"),
    ("ah:-0.25:1", R(1, 1), None), ("ah:+0.75:2", R(0, 1), None),
    # primer tiempo
    ("ht1x2:X", R(2, 1, 0, 0), "ganada"), ("ht1x2:1", R(2, 1, 0, 0), "perdida"), ("ht1x2:2", R(2, 1, 0, 1), "ganada"),
    ("htou:0.5:over", R(2, 1, 1, 0), "ganada"), ("htou:0.5:under", R(2, 1, 1, 0), "perdida"),
    ("htou:1.5:under", R(2, 1, 1, 0), "ganada"),
    # córners y tarjetas
    ("corners:9.5:over", R(1, 1, corners=10), "ganada"), ("corners:9.5:under", R(1, 1, corners=10), "perdida"),
    ("corners:9.0:over", R(1, 1, corners=9), "nula"),
    ("cards:4.5:over", R(1, 1, cards=5), "ganada"), ("cards:4.5:under", R(1, 1, cards=5), "perdida"),
    ("cards:3.5:under", R(1, 1, cards=3), "ganada"),
    # datos que faltan -> no se liquida
    ("1x2:1", R(), None), ("dc:1X", R(None, 1), None), ("dnb:1", R(1, None), None), ("btts:si", R(), None),
    ("ou:2.5:over", R(), None), ("tl:1.5:over", R(None, 1), None), ("tv:0.5:over", R(1, None), None),
    ("ah:-0.5:1", R(), None), ("ht1x2:1", R(2, 1), None), ("htou:0.5:over", R(2, 1, 1, None), None),
    ("corners:9.5:over", R(1, 1), None), ("cards:4.5:over", R(1, 1), None),
]


@pytest.mark.parametrize("clave,r,esperado", TABLA)
def test_tabla_de_verdad(clave, r, esperado):
    assert M.resultado(clave, r) == esperado


def test_resultado_sin_dict_de_goles_no_revienta():
    assert M.resultado("1x2:1", {}) is None


# ----------------------------------------------------------------- Kelly
CFG_K = {"fraccion_kelly": 0.25, "stake_max_pct": 0.5}


def test_kelly_con_devolucion_reduce_la_fraccion():
    sin = seleccion.kelly(0.6, 2.0, 0.0, CFG_K)
    con = seleccion.kelly(0.6, 2.0, 0.2, CFG_K)
    assert sin == pytest.approx(0.05)          # (0.6*2-1)/1 * 0.25
    assert con == pytest.approx(0.04)          # * (1-0.2)


def test_kelly_respeta_tope_y_no_es_negativo():
    assert seleccion.kelly(0.9, 2.0, 0.0, {**CFG_K, "stake_max_pct": 0.03}) == pytest.approx(0.03)
    assert seleccion.kelly(0.3, 2.0, 0.0, CFG_K) == 0.0


def test_valor_esperado_con_push():
    assert M.valor_esperado(0.6, 2.0, 0.2) == pytest.approx(0.16)


# --------------------------------------------------- combinada con pierna nula
def _pierna(uid, clave, cuota, tipo="ecuabet"):
    return {"uid": uid, "clave": clave, "cuota_est": cuota, "tipo_cuota": tipo, "p": 0.7}


def test_pierna_nula_sale_de_la_combinada_y_recalcula_la_cuota():
    c = {"piernas": [_pierna("a", "dnb:1", 1.5), _pierna("b", "1x2:1", 2.0)], "cuota": 3.0}
    res = {"a": {"gl": 1, "gv": 1}, "b": {"gl": 2, "gv": 0}}
    assert niveles.resultado_combinada(c, res) == "ganada"
    assert niveles.cuota_efectiva_combinada(c, res) == pytest.approx(2.0)


def test_todas_las_piernas_nulas_es_nula():
    c = {"piernas": [_pierna("a", "dnb:1", 1.5), _pierna("b", "dnb:2", 1.7)], "cuota": 2.55}
    res = {"a": {"gl": 1, "gv": 1}, "b": {"gl": 0, "gv": 0}}
    assert niveles.resultado_combinada(c, res) == "nula"
    assert niveles.cuota_efectiva_combinada(c, res) == pytest.approx(1.0)


def test_pierna_perdida_gana_sobre_nula_y_falta_info_es_none():
    c = {"piernas": [_pierna("a", "dnb:1", 1.5), _pierna("b", "1x2:1", 2.0)], "cuota": 3.0}
    assert niveles.resultado_combinada(c, {"a": {"gl": 1, "gv": 1}, "b": {"gl": 0, "gv": 1}}) == "perdida"
    assert niveles.resultado_combinada(c, {"a": {"gl": 1, "gv": 1}}) is None


def test_combinada_todas_ganadas_cuota_completa():
    c = {"piernas": [_pierna("a", "1x2:1", 1.5), _pierna("b", "1x2:1", 2.0)], "cuota": 3.0}
    res = {"a": {"gl": 2, "gv": 0}, "b": {"gl": 2, "gv": 0}}
    assert niveles.resultado_combinada(c, res) == "ganada"
    assert niveles.cuota_efectiva_combinada(c, res) == pytest.approx(3.0)


# ------------------------------------------------------------- niveles
def _sel(clave, p, cuota_ecuabet=None, mejor=None, n=3, disp=0.01):
    return {"clave": clave, "nombre": clave, "mercado": M.FAMILIAS[M.familia(clave)], "p": p,
            "cuota_ecuabet": cuota_ecuabet, "mejor_cuota": mejor, "n_fuentes": n, "dispersion": disp, "ia": None}


def _partido(uid, sels):
    return {"uid": uid, "af_id": 1, "liga": "L", "region": "Europa", "fecha": "2026-01-01",
            "inicio": "2026-01-01T20:00:00+00:00", "local": "A" + uid, "visita": "B" + uid, "evaluadas": sels}


CFG_N = {"banca": 100.0, "stake_minimo": 1.0}


def test_seguras_excluye_dnb():
    pa = _partido("1", [_sel("dnb:1", 0.90, 1.40), _sel("1x2:1", 0.80, 1.30)])
    out = niveles.seguras([pa], CFG_N)
    assert [s["clave"] for s in out] == ["1x2:1"]


def test_pool_de_combinadas_excluye_dnb():
    pa = _partido("1", [_sel("dnb:1", 0.90, 1.40), _sel("1x2:1", 0.80, 1.30)])
    assert {s["clave"] for s in niveles._pool_combinadas([pa], CFG_N)} == {"1x2:1"}


def test_segura_marca_cuota_estimada_y_ev_solo_con_cuota_real():
    real = niveles.seguras([_partido("1", [_sel("1x2:1", 0.80, 1.40)])], CFG_N)[0]
    assert real["cuota_es_estimada"] is False
    assert real["ev"] == pytest.approx(0.80 * 1.40 - 1)
    est = niveles.seguras([_partido("2", [_sel("1x2:1", 0.72)])], CFG_N)[0]   # sin cuota de Ecuabet
    assert est["cuota_es_estimada"] is True
    assert est["ev"] is None


def test_combinada_una_pierna_por_partido_y_ganancia_neta():
    partidos = [_partido(str(i), [_sel("1x2:1", 0.80, 1.30), _sel("ou:1.5:over", 0.78, 1.35),
                                  _sel("dc:1X", 0.85, 1.25)]) for i in range(8)]
    cfg = {**CFG_N, "grandes_monto": 5.0, "grandes_objetivos": [30]}
    g = niveles.grandes(partidos, cfg)
    assert g, "debería armarse una combinada"
    c = g[0]
    uids = [s["uid"] for s in c["piernas"]]
    assert len(uids) == len(set(uids))
    assert c["ganancia"] == pytest.approx(round(5.0 * (c["cuota"] - 1), 2))     # neta, no el pago bruto
    assert c["pago"] == pytest.approx(round(5.0 * c["cuota"], 2))
    assert c["cuota_es_estimada"] is False
    assert c["ev_estimado"] == pytest.approx(c["p"] * c["cuota"] - 1)


def test_combinada_con_cuota_estimada_se_marca():
    partidos = [_partido(str(i), [_sel("1x2:1", 0.72)]) for i in range(8)]
    g = niveles.grandes(partidos, {**CFG_N, "grandes_monto": 5.0, "grandes_objetivos": [20]})
    assert g and g[0]["cuota_es_estimada"] is True


# ---------------------------------------------------- selección de valor
def _cfg(**kw):
    cfg = config.cargar()
    cfg.update({"banca": 100.0, "stake_minimo": 1.0})
    cfg.update(kw)
    return cfg


def _partido_valor(detalle=None, p=0.6, cuota=2.0):
    detalle = detalle or {"modelo": 0.6, "mercado": 0.62, "forebet": 0.58}
    return {"uid": "u1", "af_id": 1, "liga": "L", "region": "Europa", "fecha": "2026-01-01",
            "inicio": "2026-01-01T20:00:00+00:00", "local": "A", "visita": "B",
            "probs": {"1x2:1": {"p": p, "detalle": detalle, "n": len(detalle), "dispersion": 0.01, "pesos": {}}},
            "ecuabet": {"1x2:1": cuota}, "mejores": {}}


def test_seleccion_normal_banca_100_no_cambia():
    valor, _ = seleccion.elegir([_partido_valor()], _cfg())
    assert len(valor) == 1 and valor[0]["monto"] == pytest.approx(3.0)


def test_stake_minimo_no_viola_el_tope_por_pick():
    # banca 20 -> tope por pick 0.6 < stake mínimo 1: no se recomienda
    valor, _ = seleccion.elegir([_partido_valor()], _cfg(banca=20.0))
    assert valor == []


def test_stake_minimo_no_viola_la_exposicion_diaria():
    valor, _ = seleccion.elegir([_partido_valor()], _cfg(exposicion_dia_pct=0.005))
    assert valor == []


def test_ev_cero_no_se_apuesta():
    pa = _partido_valor({"modelo": 0.5, "mercado": 0.5}, p=0.5, cuota=2.0)
    valor, _ = seleccion.elegir([pa], _cfg(ventaja_minima=0.0, min_acuerdo=0.0))
    assert valor == []


def test_la_ia_no_cuenta_como_fuente_para_el_consenso():
    pa = _partido_valor({"mercado": 0.6, "ia": 0.6})            # 1 fuente real + IA
    valor, _ = seleccion.elegir([pa], _cfg(min_fuentes=2))
    assert valor == []


def test_modelo_y_penaltyblog_cuentan_como_una_sola_fuente():
    assert seleccion.contar_fuentes({"modelo": 0.6, "penaltyblog": 0.6, "ia": 0.6}) == 1
    assert seleccion.contar_fuentes({"modelo": 0.6, "penaltyblog": 0.6, "forebet": 0.6}) == 2
    pa = _partido_valor({"modelo": 0.6, "penaltyblog": 0.6, "ia": 0.6})
    valor, _ = seleccion.elegir([pa], _cfg(min_fuentes=2))
    assert valor == []
    pa = _partido_valor({"modelo": 0.6, "penaltyblog": 0.6, "mercado": 0.6})
    valor, _ = seleccion.elegir([pa], _cfg(min_fuentes=2))
    assert len(valor) == 1


# ------------------------------------- seguras: tope por pick y exposición diaria
def _seg(uid, p, cuota=1.40):
    return _partido(uid, [_sel("1x2:1", p, cuota)])


@pytest.mark.parametrize("banca", [20.0, 30.0])
def test_segura_omitida_si_el_stake_minimo_viola_el_tope_por_pick(banca):
    # banca 20: max(1, 0.4)=1 > 3%*20=0.6; banca 30: 1 > 0.9
    assert niveles.seguras([_seg("1", 0.80)], {"banca": banca, "stake_minimo": 1.0}) == []


def test_segura_banca_100_no_cambia_el_2_por_ciento():
    out = niveles.seguras([_seg("1", 0.80)], {"banca": 100.0, "stake_minimo": 1.0})
    assert [s["monto"] for s in out] == [2.0]


def test_segura_respeta_stake_max_pct_configurado():
    cfg = {"banca": 100.0, "stake_minimo": 1.0, "stake_max_pct": 0.015}    # tope 1.5 < 2% = 2.0
    assert niveles.seguras([_seg("1", 0.80)], cfg) == []


def test_seguras_exposicion_diaria_omite_las_de_menor_probabilidad():
    ps = [0.74, 0.90, 0.80, 0.76, 0.85]
    partidos = [_seg(str(i), p) for i, p in enumerate(ps)]
    out = niveles.seguras(partidos, {"banca": 100.0, "stake_minimo": 1.0})     # tope diario 6% = 6.0
    assert [s["p"] for s in out] == [0.90, 0.85, 0.80]
    assert sum(s["monto"] for s in out) <= 6.0 + 1e-9


def test_seguras_exposicion_diaria_configurable():
    partidos = [_seg(str(i), 0.80 + i / 100) for i in range(5)]
    cfg = {"banca": 100.0, "stake_minimo": 1.0, "seguras_exposicion_dia_pct": 0.04}
    out = niveles.seguras(partidos, cfg)
    assert len(out) == 2 and sum(s["monto"] for s in out) <= 4.0 + 1e-9


# ------------------------- valor: el redondeo nunca rompe el tope diario
def _varios_valor(n):
    out = []
    for i in range(n):
        pa = _partido_valor()
        pa["uid"] = f"u{i}"
        pa["local"] = f"A{i}"
        out.append(pa)
    return out


@pytest.mark.parametrize("banca", [10.0, 20.0, 100.0, 1000.0])
def test_valor_total_del_dia_nunca_supera_la_exposicion(banca):
    cfg = _cfg(banca=banca)
    valor, _ = seleccion.elegir(_varios_valor(6), cfg)
    tot = sum(s["monto"] for s in valor)
    assert tot <= cfg["exposicion_dia_pct"] * banca + 1e-9
    for s in valor:
        assert s["monto"] <= cfg["stake_max_pct"] * banca + 1e-9
        assert s["monto"] >= cfg["stake_minimo"] - 1e-9
        assert (s["monto"] * 4) == pytest.approx(round(s["monto"] * 4))        # múltiplos de 0.25


def test_valor_banca_100_seis_picks_no_pasa_de_10():
    valor, _ = seleccion.elegir(_varios_valor(6), _cfg(banca=100.0))
    assert len(valor) == 6 and sum(s["monto"] for s in valor) <= 10.0 + 1e-9    # antes: 6 x 1.75 = 10.50


def test_valor_banca_1000_no_pasa_de_100():
    valor, _ = seleccion.elegir(_varios_valor(6), _cfg(banca=1000.0))
    assert len(valor) == 6 and sum(s["monto"] for s in valor) <= 100.0 + 1e-9   # antes: 100.50


# ------------------------------------------- ultimos30: pagos y JSON sin dólares
def _cargar_ultimos30():
    import importlib.util
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ultimos30.py")
    spec = importlib.util.spec_from_file_location("ultimos30_t", ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_ultimos30_se_importa_sin_ejecutar_la_simulacion():
    assert hasattr(_cargar_ultimos30(), "armar_salida")


def test_ultimos30_pagar():
    u = _cargar_ultimos30()
    assert u.pagar("ganada", 2.0, 1.5) == pytest.approx(1.0)
    assert u.pagar("perdida", 2.0, 1.5) == -2.0
    assert u.pagar("nula", 2.0, 1.5) == 0
    assert u.pagar(None, 2.0, 1.5) is None


def test_ultimos30_combinada_usa_cuota_efectiva_y_nula():
    u = _cargar_ultimos30()
    c = {"objetivo": 20, "monto": 5.0, "cuota": 3.0, "p": 0.3,
         "piernas": [{**_pierna("a", "dnb:1", 1.5), "nombre": "x", "local": "A", "visita": "B"},
                     {**_pierna("b", "1x2:1", 2.0), "nombre": "y", "local": "C", "visita": "D"}]}
    res = {"a": R(1, 1), "b": R(2, 0)}                        # a nula, b ganada: cuota efectiva 2.0
    f = u.fila_combinada("2026-01-01", c, res)
    assert f["resultado"] == "ganada" and f["ganancia"] == pytest.approx(5.0) and f["cuota"] == 2.0
    res = {"a": R(1, 1), "b": R(1, 1)}                        # a nula, b perdida
    assert u.fila_combinada("d", c, res)["ganancia"] == -5.0
    c2 = {**c, "piernas": [c["piernas"][0]]}
    assert u.fila_combinada("d", c2, {"a": R(1, 1)})["ganancia"] == 0       # todas nulas: paga 0
    assert u.fila_combinada("d", c, {"a": R(1, 1)}) is None          # falta info: no liquidable


def test_ultimos30_salida_sin_dolares():
    u = _cargar_ultimos30()
    reg = {"valor": [{"dia": "d", "resultado": "ganada", "p": 0.6, "ganancia": 3.0, "monto": 3.0},
                     {"dia": "d", "resultado": "perdida", "p": 0.6, "ganancia": -1.0, "monto": 1.0}],
           "seguras": [], "grandes": []}
    sal = u.armar_salida(reg, 10, 0.5, "periodo")
    txt = repr(sal)
    for k in ("'monto'", "'ganancia'", "'neto'", "'apostado'"):
        assert k not in txt
    r = sal["resumen"]["valor"]
    assert r["n"] == 2 and r["ganadas"] == 1 and r["acierto"] == 0.5
    assert r["u"] == pytest.approx(0.0)
    assert r["roi"] == pytest.approx((3.0 - 1.0) / 4.0)   # ponderado por monto (interno)
    assert sal["valor"][0]["u"] == 1.0 and "monto" not in sal["valor"][0]
    assert sal["resumen"]["seguras"] == {"n": 0}
