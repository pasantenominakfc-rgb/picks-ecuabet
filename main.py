#!/usr/bin/env python3
"""Picks diarios para Ecuabet: multi-mercado y multi-fuente.

Uso:
  python main.py hoy                     analiza y genera el reporte del día
  python main.py liquidar                actualiza resultados y liquida picks
  python main.py resumen                 ROI por mercado + precisión de cada fuente
  python main.py pendientes              picks pendientes con su ID
  python main.py registrar ID CUOTA [MONTO]   anota la cuota que tomaste en Ecuabet
  python main.py omitir ID               marca un pick como no apostado
  python main.py registrar-lote          registra/omite varios picks (JSON en la variable de entorno LOTE)
  python main.py ligas                   ids de ligas en API-Football (para config.yaml)
  python main.py backtest               prueba la estrategia en la última temporada
  python main.py verificar              revisa claves, créditos y ligas (puesta en marcha)
"""
import json
import os
import sys

import requests

from picks.errores import describir
from picks import backtest, config, exportar, niveles, pipeline, report, seleccion, tracker
from picks.fuentes.apifootball import APIFootball
from picks.fuentes.forebet import Forebet
from picks.fuentes.ia import AnalistaIA
from picks.fuentes.oddsapi import OddsAPI, tope_corrida


def telegram(msg: str):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": msg[:4000]}, timeout=20).raise_for_status()
            print("✓ Enviado a Telegram")
        except Exception as ex:  # noqa: BLE001
            print(f"! Telegram: {describir(ex)}")   # nunca {ex}: la URL lleva el token del bot


def clientes(cfg):
    if not cfg["api_football_key"]:
        sys.exit("Falta API_FOOTBALL_KEY (gratis en https://dashboard.api-football.com).")
    return (APIFootball(cfg["api_football_key"]), OddsAPI(cfg["odds_api_key"], max_llamadas=tope_corrida(cfg)),
            Forebet(cfg["apify_token"], linea_tarjetas=cfg["forebet_linea_tarjetas"],
                    espera_max_seg=cfg.get("forebet_espera_max_seg", 480)))


def hoy(cfg):
    af, odds, fb = clientes(cfg)
    n = tracker.actualizar_resultados(af, cfg)
    if n:
        print(f"✓ {n} picks liquidados")
    partidos = pipeline.analizar(cfg, af, odds, fb)
    if not partidos:
        print("⚠ sin datos: no se publica (¿cuota de API agotada o fallo de las fuentes?). "
              "Se conserva lo ya publicado en web/data.")
        return
    dias = pipeline.picks_por_dia(partidos, cfg)
    ia = AnalistaIA(cfg["groq_api_key"], cfg.get("ia_modelo", "groq/compound"), cfg.get("ia_max_consultas", 15))
    if ia.activa and dias:
        candidatos = pipeline.candidatos_ia(dias)   # la IA revisa hoy y mañana (las noticias cambian), con las Locas
        print(f"IA (Groq): {ia.revisar(partidos, candidatos, cfg)} picks revisados")
        dias = pipeline.picks_por_dia(partidos, cfg)
    tracker.guardar_predicciones(partidos)
    for d in dias.values():
        tracker.agregar_picks(d["valor"], "valor")
        tracker.agregar_picks(d["alta"], "alta")
        tracker.agregar_picks(d.get("locas", []), "locas")
        tracker.agregar_picks([{**x, "cuota_ecuabet": None, "monto": 0} for x in d["seguras"]], "segura")
    res, calib = tracker.resumen(), tracker.calibracion()
    creditos = f"API-Football: {af.restantes} · Odds API: {odds.restantes}"
    hoy_f = sorted(dias)[0] if dias else None
    d0 = dias.get(hoy_f, {"valor": [], "alta": [], "seguras": [], "grandes": []})
    del_hoy = [p for p in partidos if p["fecha"] == hoy_f]
    h, t = report.guardar(d0["valor"], d0["alta"], del_hoy, cfg, res, calib, creditos)
    info = getattr(partidos, "info", None) or {}
    estado = {**info, "cuota_agotada": bool(info.get("cuota_agotada") or getattr(af, "sin_cuota", False)),
              "ia": bool(ia.activa)}
    exportar.hoy(partidos, dias, cfg, creditos, estado=estado)
    exportar.historial()
    exportar.fuentes(cfg)
    msg = t.read_text(encoding="utf-8") + report.texto_niveles(d0["seguras"], d0["grandes"], d0.get("locas"))
    otros = [f"{f}: {len(d['seguras'])} seguras, {len(d['valor'])} de valor" for f, d in dias.items() if f != hoy_f]
    if otros:
        msg += "\n\n📅 Próximos días (en la app):\n" + "\n".join(otros)
    if cfg.get("url_web"):
        msg += f"\n\n📱 {cfg['url_web']}"
    print("\n" + msg + f"\n\nReporte: {h}\n{creditos}")
    telegram(msg)


def _http(url, **kw):
    """GET que nunca lanza: devuelve (ok, detalle)."""
    try:
        r = requests.get(url, timeout=20, **kw)
        return r.ok, r.status_code
    except requests.RequestException as ex:
        return False, type(ex).__name__


def _apify_valido(token: str):
    """Comprueba el token de Apify; va en la cabecera Authorization (nunca en la URL)."""
    return _http("https://api.apify.com/v2/users/me", headers={"Authorization": f"Bearer {token}"})


def verificar(cfg):
    ok = True
    print("Verificando la puesta en marcha...\n")
    if not cfg["api_football_key"]:
        print("✘ Falta API_FOOTBALL_KEY (obligatoria)")
        return False
    af = APIFootball(cfg["api_football_key"])
    try:
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
    except Exception as ex:  # noqa: BLE001
        print(f"✘ API-Football falló: {describir(ex)}")
        return False
    for lg in cfg["ligas"]:
        real = ligas.get(lg.get("af"))
        marca = "✔" if real else "✘"
        print(f"  {marca} {lg['nombre']:18s} id {lg.get('af')} → {real[0] + ' / ' + real[1] if real else 'NO ENCONTRADA (revisa con: python main.py ligas)'}")
        ok &= bool(real)
    if cfg["odds_api_key"]:
        try:
            o = OddsAPI(cfg["odds_api_key"])
            o.deportes()
            bien = bool(o.restantes)
        except Exception:  # noqa: BLE001
            bien = False
        print(f"✔ The Odds API: {o.restantes} créditos restantes" if bien else "✘ The Odds API: clave inválida")
        ok &= bien
    else:
        print("· The Odds API: sin clave (opcional)")
    if cfg["apify_token"]:
        bien, det = _apify_valido(cfg["apify_token"])
        print("✔ Apify (Forebet): token válido" if bien else f"✘ Apify: token inválido ({det})")
        ok &= bien
    else:
        print("· Apify/Forebet: sin token (opcional, recomendado)")
    if cfg["groq_api_key"]:
        bien, det = _http("https://api.groq.com/openai/v1/models",
                          headers={"Authorization": f"Bearer {cfg['groq_api_key']}"})
        print("✔ Groq (IA): clave válida" if bien else f"✘ Groq: clave inválida ({det})")
        ok &= bien
    else:
        print("· Groq (IA): sin clave (opcional, recomendado)")
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and not chat:
        print("✘ Telegram: hay TELEGRAM_TOKEN pero falta TELEGRAM_CHAT_ID")
        ok = False
    elif token:
        bien, det = _http(f"https://api.telegram.org/bot{token}/getChat", params={"chat_id": chat})
        print("✔ Telegram configurado (token y chat válidos)" if bien else f"✘ Telegram: token o chat inválido ({det})")
        ok &= bien
    else:
        print("· Telegram: sin configurar (opcional)")
    print("\n" + ("Todo listo ✅" if ok else "Hay cosas por corregir ⚠️"))
    return bool(ok)


MAX_LOTE = 50


def _s(x, n: int) -> str:
    """Texto seguro para logs: ascii() escapa saltos de línea y caracteres de control (sin inyección)."""
    return ascii(str(x)[:n])


def registrar_lote(raw: str) -> int:
    """Procesa un lote JSON [{uid, clave, accion: registrar|omitir, cuota, monto}]. Devuelve el código de
    salida: 0 solo si TODOS los ítems se aplicaron. No exporta (lo hace el comando)."""
    try:
        items = json.loads(raw or "")
    except ValueError:
        print("✘ LOTE no es un JSON válido")
        return 1
    if not isinstance(items, list) or not items:
        print("✘ LOTE debe ser una lista no vacía")
        return 1
    if len(items) > MAX_LOTE:
        print(f"✘ LOTE tiene {len(items)} ítems (máximo {MAX_LOTE}); no se procesó nada")
        return 1
    fallos = 0
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            print(f"✘ #{i}: ítem no es un objeto")
            fallos += 1
            continue
        uid, clave, accion = it.get("uid"), it.get("clave"), it.get("accion")
        if accion == "registrar":
            motivo = tracker.registrar_web_motivo(uid, clave, it.get("cuota"), it.get("monto"))
        elif accion == "omitir":
            motivo = tracker.omitir_web_motivo(uid, clave)
        else:
            motivo = f"acción desconocida ({_s(accion, 20)})"
        etiqueta = f"#{i} {_s(accion, 20)} {_s(uid, 20)} {_s(clave, 30)}"
        if motivo:
            fallos += 1
            print(f"✘ {etiqueta}: {motivo}")
        else:
            print(f"✔ {etiqueta}")
    print(f"{len(items) - fallos}/{len(items)} aplicados" + (f" · {fallos} con error" if fallos else ""))
    return 1 if fallos else 0


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
            print(f"Aún no hay apuestas registradas y liquidadas (sin registrar: {r.get('pendientes_sin_registrar', 0)} pendientes).")
        t = r.get("teorico") or {}
        if t.get("n"):
            print(f"[HIPOTÉTICO, no es ROI real] {t['n']} picks | ROI {t['roi']:+.1%} | neto ${t['neto']:+.2f}")
        print("\nPrecisión por fuente (Brier, más bajo = mejor):")
        for (s, fam), v in sorted(tracker.calibracion().items(), key=lambda kv: (kv[0][1], kv[1]["brier"])):
            print(f"  {fam:8s} {s:12s} brier {v['brier']:.4f}  n={v['n']}")
    elif cmd == "pendientes":
        for p in tracker.pendientes():
            print(f"[{p['id']}] {p['inicio'][:16]} {p['local']} vs {p['visita']} | {p['nombre']} | "
                  f"mín {p['cuota_minima']:.2f} | tomada {p['cuota_tomada'] or '-'} | ${p['monto']:.2f} ({p['tipo']})")
    elif cmd == "registrar":
        try:
            pid, cuota = int(sys.argv[2]), sys.argv[3]
            monto = sys.argv[4] if len(sys.argv) > 4 else None
        except (IndexError, ValueError):
            sys.exit("Uso: python main.py registrar ID CUOTA [MONTO]")
        if not tracker.registrar(pid, cuota, monto):
            sys.exit("✘ No se registró (pick inexistente, ya liquidado o cuota/monto inválidos)")
        exportar.historial()
        print("✓ Registrado")
    elif cmd == "omitir":
        tracker.omitir(int(sys.argv[2]))
        exportar.historial()
        print("✓ Omitido")
    elif cmd == "registrar-web":   # usado por la página web (workflow registrar.yml)
        if len(sys.argv) < 6:
            sys.exit("Uso: python main.py registrar-web UID CLAVE CUOTA MONTO")
        motivo = tracker.registrar_web_motivo(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
        if motivo:
            sys.exit(f"✘ No registrado: {motivo}")
        exportar.historial()
        print("✓ Registrado")
    elif cmd == "omitir-web":
        if len(sys.argv) < 4:
            sys.exit("Uso: python main.py omitir-web UID CLAVE")
        motivo = tracker.omitir_web_motivo(sys.argv[2], sys.argv[3])
        if motivo:
            sys.exit(f"✘ No omitido: {motivo}")
        exportar.historial()
        print("✓ Omitido")
    elif cmd == "registrar-lote":   # el JSON viaja en la variable de entorno LOTE, no en argv
        codigo = registrar_lote(os.environ.get("LOTE", ""))   # ya guardó en la DB todo ítem válido
        try:
            exportar.historial()
        except Exception as ex:  # noqa: BLE001 - un fallo al exportar no debe ocultar el código del lote
            print(f"! historial no exportado: {describir(ex)}")
            codigo = codigo or 1
        sys.exit(codigo)
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
