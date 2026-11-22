"""Arma la vista previa con partidos reales: Forebet (leído hoy) + modelos propios + penaltyblog."""
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
sys.path.insert(0, "/home/claude/apuestas")
from picks import config, ensamble, exportar, mercados as M, names, pipeline
from picks.fuentes.forebet import a_claves
from picks.modelos.goles import DixonColes
from picks.modelos.pb import ModeloPB
from picks.modelos.conteos import ModeloConteo

TZ = ZoneInfo("America/Guayaquil")
D = "/home/claude/datos_reales"
FD = {"Premier League": ("E0", "premier-league"), "LaLiga": ("SP1", "la-liga"), "Serie A": ("I1", "serie-a")}
cfg = config.cargar()
cfg |= {"min_fuentes": 1, "niveles_min_fuentes": 1}
modelos = {}
for liga, (c, slug) in FD.items():
    prev = pd.read_csv(f"{D}/{slug}_2526.csv"); prev["fecha"] = pd.to_datetime(prev["Date"])
    cur = pd.read_csv(f"{D}/{c}_2627.csv"); cur["fecha"] = pd.to_datetime(cur["Date"], dayfirst=True)
    df = pd.concat([prev, cur])
    df = pd.DataFrame({"fecha": df.fecha, "local": df.HomeTeam, "visita": df.AwayTeam, "gl": df.FTHG, "gv": df.FTAG,
                       "cl": df.HC, "cv": df.AC, "tjl": df.HY + df.HR, "tjv": df.AY + df.AR}).dropna(subset=["gl"])
    modelos[liga] = (DixonColes().ajustar(df), ModeloPB().ajustar(df), ModeloConteo().ajustar(df, "cl", "cv"),
                     ModeloConteo().ajustar(df, "tjl", "tjv"))

partidos = []
for i, line in enumerate(open("/home/claude/demo_real/forebet_hoy.txt", encoding="utf-8")):
    liga, h, a, ini, p1x2, avg, odds, ou, bt, co, coavg, ca, caavg = line.strip().split(";")
    dt = datetime.fromisoformat(ini).replace(tzinfo=timezone.utc).astimezone(TZ)
    sp = lambda x: [float(v) for v in x.split("/")] if x else []  # noqa: E731
    P, O, B, C, T = sp(p1x2), sp(ou), sp(bt), sp(co), sp(ca)
    row = {"probabilityHome": P[0], "probabilityDraw": P[1], "probabilityAway": P[2], "predictedGoalsAverage": float(avg)}
    if O: row |= {"probabilityUnder25": O[0], "probabilityOver25": O[1]}
    if B: row |= {"probabilityBttsNo": B[0], "probabilityBttsYes": B[1]}
    if C: row |= {"probabilityCornersUnder95": C[0], "probabilityCornersOver95": C[1], "predictedCornersAverage": float(coavg)}
    if T: row |= {"probabilityCardsUnder": T[0], "probabilityCardsOver": T[1], "predictedCardsAverage": float(caavg)}
    fb = a_claves(row, 4.5)
    fuentes = {"forebet": {k: v for k, v in fb.items() if not k.startswith("_")}}
    o = sp(odds)
    casas = {"promedio_casas": {"1x2:1": o[0], "1x2:X": o[1], "1x2:2": o[2]}} if len(o) == 3 and min(o) > 1 else {}
    mkt = ensamble.probs_mercado(casas, cfg["casas_afiladas"], {"ecuabet"})
    if mkt: fuentes["mercado"] = mkt
    esperados = {"corners_fb": fb.get("_corners"), "tarjetas_fb": fb.get("_tarjetas")}
    xg = None
    if liga in modelos:
        dc, pb, mc, mt = modelos[liga]
        lh, la = names.emparejar(h, dc.equipos), names.emparejar(a, dc.equipos)
        if lh and la:
            m = dc.mercados(lh, la)
            xg = (m["_xg_local"], m["_xg_visita"])
            for fam, mod, nm in (("corners", mc, "corners"), ("cards", mt, "tarjetas")):
                r = mod.prob_mas_de(lh, la, M.LINEAS[fam]); esperados[nm] = r.pop("_media")
                for ln, p in r.items(): m[f"{fam}:{ln}:over"], m[f"{fam}:{ln}:under"] = p, 1 - p
            fuentes["modelo"] = {k: v for k, v in m.items() if not k.startswith("_")}
            r2 = pb.mercados(lh, la)
            if r2: fuentes["penaltyblog"] = {k: v for k, v in r2.items() if not k.startswith("_")}
        else:
            print("sin modelo:", h, a, lh, la)
    region = "Europa"
    partidos.append({"uid": f"fb{i}", "af_id": None, "liga": liga, "region": region, "inicio": dt.isoformat(),
                     "fecha": dt.date().isoformat(), "local": h, "visita": a, "fuentes": fuentes,
                     "probs": ensamble.combinar(fuentes, cfg["pesos_iniciales"], {}, cfg),
                     "mejores": ensamble.mejores_cuotas(casas, cfg["casas_afiladas"], "ecuabet"), "ecuabet": {},
                     "xg": xg, "esperados": esperados})
dias = pipeline.picks_por_dia(partidos, cfg)
for f, d in dias.items():
    print(f, "partidos", sum(p["fecha"] == f for p in partidos), "valor", len(d["valor"]), "seguras", len(d["seguras"]),
          "grandes", [(c["objetivo"], round(c["cuota"], 1), f"{c['p']:.1%}") for c in d["grandes"]])
exportar.hoy(partidos, dias, cfg, "Vista previa: Forebet + modelos")
for f, d in dias.items():
    print("\n==", f)
    for s in d["seguras"]: print(f"  SEGURA {s['local']} vs {s['visita']}: {s['nombre']} {s['p']:.0%} justa {s['cuota_justa']:.2f}")
    for s in d["valor"]: print(f"  VALOR  {s['local']} vs {s['visita']}: {s['nombre']} {s['p']:.0%} min {s['cuota_minima']:.2f} ref {s['mejor_cuota']}")
