"""Simulación con DATOS REALES de los últimos 30 días (23/10 – 21/11/2026).

Para cada día, el sistema solo usa información anterior a ese día:
  - modelos (goles, córners, tarjetas) entrenados con la temporada pasada + lo jugado hasta el día anterior
  - mercado: cuotas de Betfair Exchange (casa 'afilada') sin margen
  - cuota de apuesta: Bet365 como aproximación a Ecuabet (1X2 y +/-2.5); el resto, cuota estimada (justa × 0.94)
Luego compara con el resultado real y calcula ganancias.

Uso: python tests/ultimos30.py CARPETA_DATOS
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from picks import config, ensamble, mercados as M, niveles, seleccion  # noqa: E402
from picks.modelos.conteos import ModeloConteo  # noqa: E402
from picks.modelos.goles import DixonColes  # noqa: E402
from picks.modelos.pb import ModeloPB  # noqa: E402

DATOS = Path(sys.argv[1]) if len(sys.argv) > 1 else None   # sin carpeta: descarga de football-data
LIGAS = {"E0": ("Premier League", "premier-league"), "SP1": ("LaLiga", "la-liga"), "I1": ("Serie A", "serie-a"),
         "D1": ("Bundesliga", "bundesliga"), "F1": ("Ligue 1", "ligue-1")}
FIN = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
INICIO = FIN - pd.Timedelta(days=29)


def _fd(codigo, temporada):
    import io

    import requests
    r = requests.get(f"https://www.football-data.co.uk/mmz4281/{temporada}/{codigo}.csv", timeout=30,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.content.decode("latin-1")), on_bad_lines="skip")


def cargar(codigo, slug):
    if DATOS:
        prev = pd.read_csv(DATOS / f"{slug}_2526.csv")
        cur = pd.read_csv(DATOS / f"{codigo}_2627.csv")
    else:
        ini = FIN.year if FIN.month >= 7 else FIN.year - 1
        t = lambda a: f"{a % 100:02d}{(a + 1) % 100:02d}"  # noqa: E731
        prev, cur = _fd(codigo, t(ini - 1)), _fd(codigo, t(ini))
    for d in (prev, cur):
        d["fecha"] = pd.to_datetime(d["Date"], dayfirst=not str(d["Date"].iloc[0])[:4].isdigit(), errors="coerce")
    df = pd.concat([prev, cur], ignore_index=True)
    out = pd.DataFrame({"fecha": df["fecha"], "local": df["HomeTeam"], "visita": df["AwayTeam"],
                        "gl": df["FTHG"], "gv": df["FTAG"], "htl": df["HTHG"], "htv": df["HTAG"],
                        "cl": df["HC"], "cv": df["AC"], "tjl": df["HY"] + df["HR"], "tjv": df["AY"] + df["AR"]})
    for c in ("B365H", "B365D", "B365A", "BFEH", "BFED", "BFEA", "B365>2.5", "B365<2.5", "BFE>2.5", "BFE<2.5"):
        out[c] = df[c] if c in df else None
    return out.dropna(subset=["gl", "gv"]).sort_values("fecha").reset_index(drop=True)


def casas(f):
    def g(c):
        v = f.get(c)
        return float(v) if pd.notna(v) else None
    out = {}
    for casa, pre in (("betfair_ex_eu", "BFE"), ("bet365", "B365")):
        c = {"1x2:1": g(pre + "H"), "1x2:X": g(pre + "D"), "1x2:2": g(pre + "A"),
             "ou:2.5:over": g(pre + ">2.5"), "ou:2.5:under": g(pre + "<2.5")}
        out[casa] = {k: v for k, v in c.items() if v}
    return out


cfg = config.cargar()
cfg |= {"casa_objetivo": "bet365", "niveles_min_fuentes": 1, "min_fuentes": 1}
prior = cfg["pesos_iniciales"]

registro = {"valor": [], "seguras": [], "grandes": []}
por_dia = defaultdict(lambda: {"partidos": 0})
todos_partidos = []

for codigo, (nombre, slug) in LIGAS.items():
    df = cargar(codigo, slug)
    prueba = df[(df["fecha"] >= INICIO) & (df["fecha"] <= FIN)]
    print(f"→ {nombre}: {len(prueba)} partidos de prueba")
    for dia, grupo in prueba.groupby("fecha"):
        train = df[(df["fecha"] < dia) & (df["fecha"] >= dia - pd.Timedelta(days=730))]
        dc = DixonColes().ajustar(train)
        mc = ModeloConteo().ajustar(train, "cl", "cv")
        mt = ModeloConteo().ajustar(train, "tjl", "tjv")
        mpb = ModeloPB().ajustar(train)
        for _, f in grupo.iterrows():
            f = f.to_dict()
            uid = f"{codigo}-{dia:%Y%m%d}-{f['local']}"
            cs = casas(f)
            fuentes = {}
            mkt = ensamble.probs_mercado(cs, cfg["casas_afiladas"], {"bet365"})
            if mkt:
                fuentes["mercado"] = mkt
            pm = dc.mercados(f["local"], f["visita"]) if dc.ok else None
            esperados = {}
            if pm:
                for fam, mod, nm in (("corners", mc, "corners"), ("cards", mt, "tarjetas")):
                    if mod.ok:
                        r = mod.prob_mas_de(f["local"], f["visita"], M.LINEAS[fam])
                        if r:
                            esperados[nm] = r.pop("_media")
                            for ln, p in r.items():
                                pm[f"{fam}:{ln}:over"], pm[f"{fam}:{ln}:under"] = p, 1 - p
                fuentes["modelo"] = {k: v for k, v in pm.items() if not k.startswith("_")}
            if mpb.ok:
                r = mpb.mercados(f["local"], f["visita"])
                if r:
                    fuentes["penaltyblog"] = {k: v for k, v in r.items() if not k.startswith("_")}
            if not fuentes:
                continue
            pa = {"uid": uid, "af_id": None, "liga": nombre, "inicio": f"{dia:%Y-%m-%d}T15:00:00+00:00",
                  "local": f["local"], "visita": f["visita"], "fuentes": fuentes,
                  "probs": ensamble.combinar(fuentes, prior, {}, cfg),
                  "mejores": ensamble.mejores_cuotas(cs, cfg["casas_afiladas"], "bet365"),
                  "ecuabet": cs.get("bet365", {}), "xg": (pm["_xg_local"], pm["_xg_visita"]) if pm else None,
                  "esperados": esperados,
                  "real": {"gl": int(f["gl"]), "gv": int(f["gv"]), "htl": f["htl"], "htv": f["htv"],
                           "corners": int(f["cl"] + f["cv"]), "cards": int(f["tjl"] + f["tjv"])},
                  "dia": f"{dia:%Y-%m-%d}"}
            todos_partidos.append(pa)

# --- selección día por día (todas las ligas juntas, como la app) ----------------
res = {p["uid"]: p["real"] for p in todos_partidos}
dias = sorted({p["dia"] for p in todos_partidos})
for d in dias:
    pd_dia = [p for p in todos_partidos if p["dia"] == d]
    valor, _ = seleccion.elegir(pd_dia, cfg)
    for s in valor:
        r = M.resultado(s["clave"], res[s["uid"]])
        cuota = s["cuota_ecuabet"] or s["cuota_minima"]
        gan = {"ganada": s["monto"] * (cuota - 1), "perdida": -s["monto"], "nula": 0}[r]
        registro["valor"].append({"dia": d, "partido": f"{s['local']} vs {s['visita']}", "liga": s["liga"],
                                  "pick": s["nombre"], "p": s["p"], "cuota": cuota, "monto": s["monto"],
                                  "resultado": r, "ganancia": round(gan, 2), "marcador": f"{res[s['uid']]['gl']}-{res[s['uid']]['gv']}"})
    for s in niveles.seguras(pd_dia, cfg):
        r = M.resultado(s["clave"], res[s["uid"]])
        gan = {"ganada": s["monto"] * (s["cuota_est"] - 1), "perdida": -s["monto"], "nula": 0}[r]
        registro["seguras"].append({"dia": d, "partido": f"{s['local']} vs {s['visita']}", "liga": s["liga"],
                                    "pick": s["nombre"], "p": s["p"], "cuota": s["cuota_est"], "tipo_cuota": s["tipo_cuota"],
                                    "monto": s["monto"], "resultado": r, "ganancia": round(gan, 2),
                                    "marcador": f"{res[s['uid']]['gl']}-{res[s['uid']]['gv']}"})
    for c in niveles.grandes(pd_dia, cfg):
        r = niveles.resultado_combinada(c, res)
        piernas = [{"partido": f"{s['local']} vs {s['visita']}", "pick": s["nombre"], "p": s["p"], "cuota": s["cuota_est"],
                    "acierto": M.resultado(s["clave"], res[s["uid"]]) == "ganada"} for s in c["piernas"]]
        registro["grandes"].append({"dia": d, "objetivo": c["objetivo"], "monto": c["monto"], "cuota": round(c["cuota"], 2),
                                    "p": c["p"], "piernas": piernas, "resultado": r,
                                    "ganancia": round(c["monto"] * (c["cuota"] - 1) if r == "ganada" else -c["monto"], 2),
                                    "aciertos": sum(x["acierto"] for x in piernas)})


def resumen(lista):
    if not lista:
        return {"n": 0}
    n = len(lista)
    g = sum(1 for x in lista if x["resultado"] == "ganada")
    ap = sum(x["monto"] for x in lista)
    neto = sum(x["ganancia"] for x in lista)
    return {"n": n, "ganadas": g, "acierto": g / n, "apostado": round(ap, 2), "neto": round(neto, 2),
            "roi": neto / ap if ap else 0, "prob_media": sum(x["p"] for x in lista) / n}


# precisión simple de "el favorito según el sistema"
acierto_1x2 = []
for p in todos_partidos:
    pr = {k: p["probs"][k]["p"] for k in ("1x2:1", "1x2:X", "1x2:2") if k in p["probs"]}
    if len(pr) == 3:
        fav = max(pr, key=pr.get)
        acierto_1x2.append(M.resultado(fav, p["real"]) == "ganada")

salida = {"periodo": f"{INICIO:%d/%m/%Y} – {FIN:%d/%m/%Y}", "partidos": len(todos_partidos),
          "acierto_favorito_1x2": sum(acierto_1x2) / len(acierto_1x2),
          "resumen": {k: resumen(v) for k, v in registro.items()}, **registro}
(RAIZ / "web" / "data").mkdir(parents=True, exist_ok=True)
(RAIZ / "web" / "data" / "simulacion30.json").write_text(json.dumps(salida, ensure_ascii=False, default=float), encoding="utf-8")

print(f"\nPartidos analizados: {salida['partidos']} | el favorito del sistema acertó el 1X2 en {salida['acierto_favorito_1x2']:.0%}")
for k, r in salida["resumen"].items():
    if r["n"]:
        print(f"{k.upper():8s} n={r['n']:3d} ganadas={r['ganadas']:3d} ({r['acierto']:.0%}, prob. media {r['prob_media']:.0%}) "
              f"apostado ${r['apostado']:.2f} neto ${r['neto']:+.2f} ROI {r['roi']:+.1%}")
print("\nCombinadas:")
for c in registro["grandes"]:
    print(f"  {c['dia']} objetivo ${c['objetivo']} cuota {c['cuota']} prob {c['p']:.1%} → {c['resultado']} "
          f"({c['aciertos']}/{len(c['piernas'])} piernas)")
