#!/usr/bin/env python3
"""Picks diarios para Ecuabet: multi-mercado y multi-fuente.

Uso:
  python main.py hoy                     analiza y genera el reporte del día
  python main.py liquidar                actualiza resultados y liquida picks
  python main.py resumen                 ROI por mercado + precisión de cada fuente
  python main.py pendientes              picks pendientes con su ID
  python main.py registrar ID CUOTA [MONTO]   anota la cuota que tomaste en Ecuabet
  python main.py omitir ID               marca un pick como no apostado
  python main.py ligas                   ids de ligas en API-Football (para config.yaml)
  python main.py backtest               prueba la estrategia en la última temporada
  python main.py verificar              revisa claves, créditos y ligas (puesta en marcha)
"""
import os
import sys

import requests

from picks import backtest, config, exportar, niveles, pipeline, report, seleccion, tracker
from picks.fuentes.apifootball import APIFootball
from picks.fuentes.forebet import Forebet
from picks.fuentes.ia import AnalistaIA
from picks.fuentes.oddsapi import OddsAPI


def telegram(msg: str):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": msg[:4000]}, timeout=20).raise_for_status()
            print("✓ Enviado a Telegram")
        except Exception as ex:  # noqa: BLE001
            print(f"! Telegram: {ex}")


def clientes(cfg):
    if not cfg["api_football_key"]:
        sys.exit("Falta API_FOOTBALL_KEY (gratis en https://dashboard.api-football.com).")
    return (APIFootball(cfg["api_football_key"]), OddsAPI(cfg["odds_api_key"]),
            Forebet(cfg["apify_token"], linea_tarjetas=cfg["forebet_linea_tarjetas"]))


def hoy(cfg):
    af, odds, fb = clientes(cfg)
    n = tracker.actualizar_resultados(af, cfg)
    if n:
        print(f"✓ {n} picks liquidados")
    partidos = pipeline.analizar(cfg, af, odds, fb)
    dias = pipeline.picks_por_dia(partidos, cfg)
    ia = AnalistaIA(cfg["groq_api_key"], cfg.get("ia_modelo", "groq/compound"), cfg.get("ia_max_consultas", 15))
    if ia.activa and dias:
        proximos = sorted(dias)[:2]            # la IA revisa hoy y mañana (las noticias cambian)
        candidatos = [x for f in proximos for x in dias[f]["valor"] + dias[f]["seguras"]
                      + [p for c in dias[f]["grandes"] for p in c["piernas"]]]
        print(f"IA (Groq): {ia.revisar(partidos, candidatos, cfg)} picks revisados")
        dias = pipeline.picks_por_dia(partidos, cfg)
    tracker.guardar_predicciones(partidos)
    for d in dias.values():
        tracker.agregar_picks(d["valor"], "valor")
        tracker.agregar_picks(d["alta"], "alta")
        tracker.agregar_picks([{**x, "cuota_ecuabet": None, "monto": 0} for x in d["seguras"]], "segura")
    res, calib = tracker.resumen(), tracker.calibracion()
    creditos = f"API-Football: {af.restantes} · Odds API: {odds.restantes}"
    hoy_f = sorted(dias)[0] if dias else None
    d0 = dias.get(hoy_f, {"valor": [], "alta": [], "seguras": [], "grandes": []})
    del_hoy = [p for p in partidos if p["fecha"] == hoy_f]
    h, t = report.guardar(d0["valor"], d0["alta"], del_hoy, cfg, res, calib, creditos)
    exportar.hoy(partidos, dias, cfg, creditos)
    exportar.historial()
    exportar.fuentes(cfg)
    msg = t.read_text(encoding="utf-8") + report.texto_niveles(d0["seguras"], d0["grandes"])
    otros = [f"{f}: {len(d['seguras'])} seguras, {len(d['valor'])} de valor" for f, d in dias.items() if f != hoy_f]
    if otros:
        msg += "\n\n📅 Próximos días (en la app):\n" + "\n".join(otros)
    if cfg.get("url_web"):
        msg += f"\n\n📱 {cfg['url_web']}"
    print("\n" + msg + f"\n\nReporte: {h}\n{creditos}")
    telegram(msg)


def verificar(cfg):
    ok = True
    print("Verificando la puesta en marcha...\n")
    if not cfg["api_football_key"]:
        print("✘ Falta API_FOOTBALL_KEY (obligatoria)")
        return False
    af = APIFootball(cfg["api_football_key"])
    st = af._get("/status")
    cuenta = (st.get("response") or {}) if isinstance(st.get("response"), dict) else {}
    if cuenta.get("requests"):
        r = cuenta["requests"]
        print(f"✔ API-Football: plan {cuenta.get('subscription', {}).get('plan')} · {r['current']}/{r['limit_day']} consultas hoy")
    else:
        print(f"✘ API-Football no respondió bien: {st.get('errors')}")
        ok = False
    ligas = {l["league"]["id"]: (l["country"]["name"], l["league"]["name"])
             for l in af._get("/leagues", cache_horas=24, current="true").get("response", [])}
    for lg in cfg["ligas"]:
        real = ligas.get(lg.get("af"))
        marca = "✔" if real else "✘"
        print(f"  {marca} {lg['nombre']:18s} id {lg.get('af')} → {real[0] + ' / ' + real[1] if real else 'NO ENCONTRADA (revisa con: python main.py ligas)'}")
        ok &= bool(real)
    if cfg["odds_api_key"]:
        o = OddsAPI(cfg["odds_api_key"])
        o.deportes()
        print(f"✔ The Odds API: {o.restantes} créditos restantes" if o.restantes else "✘ The Odds API: clave inválida")
    else:
        print("· The Odds API: sin clave (opcional)")
    if cfg["apify_token"]:
        r = requests.get("https://api.apify.com/v2/users/me", params={"token": cfg["apify_token"]}, timeout=20)
        print("✔ Apify (Forebet): token válido" if r.ok else f"✘ Apify: token inválido ({r.status_code})")
        ok &= r.ok
    else:
        print("· Apify/Forebet: sin token (opcional, recomendado)")
    if cfg["groq_api_key"]:
        r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {cfg['groq_api_key']}"}, timeout=20)
        print("✔ Groq (IA): clave válida" if r.ok else f"✘ Groq: clave inválida ({r.status_code})")
    else:
        print("· Groq (IA): sin clave (opcional, recomendado)")
    print("✔ Telegram configurado" if os.environ.get("TELEGRAM_TOKEN") else "· Telegram: sin configurar (opcional)")
    print("\n" + ("Todo listo ✅" if ok else "Hay cosas por corregir ⚠️"))
    return ok


def main():
    cfg = config.cargar()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "hoy"
    if cmd == "hoy":
        hoy(cfg)
    elif cmd == "liquidar":
        print(f"{tracker.actualizar_resultados(clientes(cfg)[0], cfg)} picks liquidados")
        exportar.historial()
        exportar.fuentes(cfg)
    elif cmd == "resumen":
        r = tracker.resumen()
        if r.get("n"):
            print(f"Apuestas {r['n']} | acierto {r['acierto']:.0%} | ROI {r['roi']:+.1%} | neto ${r['neto']:+.2f}")
            for k, v in sorted(r["por_mercado"].items()):
                print(f"  {k:24s} n={v['n']:4d}  neto ${v['neto']:+.2f}")
        else:
            print("Aún no hay picks liquidados.")
        print("\nPrecisión por fuente (Brier, más bajo = mejor):")
        for (s, fam), v in sorted(tracker.calibracion().items(), key=lambda kv: (kv[0][1], kv[1]["brier"])):
            print(f"  {fam:8s} {s:12s} brier {v['brier']:.4f}  n={v['n']}")
    elif cmd == "pendientes":
        for p in tracker.pendientes():
            print(f"[{p['id']}] {p['inicio'][:16]} {p['local']} vs {p['visita']} | {p['nombre']} | "
                  f"mín {p['cuota_minima']:.2f} | tomada {p['cuota_tomada'] or '-'} | ${p['monto']:.2f} ({p['tipo']})")
    elif cmd == "registrar":
        tracker.registrar(int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]) if len(sys.argv) > 4 else None)
        exportar.historial()
        print("✓ Registrado")
    elif cmd == "omitir":
        tracker.omitir(int(sys.argv[2]))
        exportar.historial()
        print("✓ Omitido")
    elif cmd == "registrar-web":   # usado por la página web (workflow registrar.yml)
        uid, clave, cuota, monto = sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5])
        print("✓ Registrado" if tracker.registrar_web(uid, clave, cuota, monto) else "✘ Pick no encontrado")
        exportar.historial()
    elif cmd == "omitir-web":
        tracker.omitir_web(sys.argv[2], sys.argv[3])
        exportar.historial()
        print("✓ Omitido")
    elif cmd == "backtest":
        res = backtest.correr(cfg)
        exportar.backtest(res)
        for fuente, r in res.items():
            print(f"{fuente:5s} n={r['n']} acierto {r['acierto']:.0%} ROI {r['roi']:+.1%} CLV {r['clv'] or 0:+.1%} "
                  f"racha perdedora máx {r['max_racha_perdidas']}")
    elif cmd == "verificar":
        sys.exit(0 if verificar(cfg) else 1)
    elif cmd == "ligas":
        af = clientes(cfg)[0]
        for l in af._get("/leagues", cache_horas=24, current="true").get("response", []):
            print(f"{l['league']['id']:5d}  {l['country']['name']:15s} {l['league']['name']}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
