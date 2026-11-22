"""Simulación sin internet de 25 días: fuentes falsas con el formato real de las APIs.
Verifica parseo, ensamble, selección, liquidación de todos los mercados y que los pesos
se ajusten castigando a la fuente más ruidosa (API-Football simulada con mucho ruido).

AISLAMIENTO: todo se escribe en un directorio temporal (base, caché, reportes y web/data). Las rutas se
reemplazan con monkeypatch desde este script (config.DATOS, tracker.RUTA, report.REPORTES, exportar.WEB y
cualquier otro módulo de picks que importó DATOS), sin tocar el código del proyecto. Un archivo centinela
en el datos/ real comprueba al final que la simulación no lo borró."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import poisson

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["PICKS_SIMULACION"] = "1"

# centinela en el datos/ REAL (si el script lo tocara, desaparecería)
DATOS_REAL = RAIZ / "datos"
DATOS_REAL.mkdir(exist_ok=True)
CENTINELA = DATOS_REAL / f".centinela_simulacion_{os.getpid()}"   # único por proceso (pruebas en paralelo)
CENTINELA.write_text("no borrar: lo comprueba tests/simulacion.py", encoding="utf-8")
_db_real = DATOS_REAL / "sistema.db"
_db_real_antes = (_db_real.stat().st_mtime_ns, _db_real.stat().st_size) if _db_real.exists() else None

from picks import config, pipeline, report, tracker  # noqa: E402
from picks.fuentes import footballdata  # noqa: E402
from picks.fuentes.apifootball import APIFootball  # noqa: E402
from picks.fuentes.forebet import Forebet, a_claves  # noqa: E402
from picks.fuentes.oddsapi import OddsAPI  # noqa: E402
from picks.modelos.goles import mercados_desde_goles  # noqa: E402

# --- aislamiento: directorio temporal --------------------------------------------
TMP = Path(tempfile.mkdtemp(prefix="picks_sim_"))
_datos_original = config.DATOS
for sub in ("datos/cache", "reportes", "web_data"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
config.DATOS, config.REPORTES = TMP / "datos", TMP / "reportes"
for _m in list(sys.modules.values()):                # módulos que hicieron `from .config import DATOS`
    if getattr(_m, "__name__", "").startswith("picks"):
        if getattr(_m, "DATOS", None) == _datos_original:
            _m.DATOS = TMP / "datos"
        if getattr(_m, "REPORTES", None) == RAIZ / "reportes":
            _m.REPORTES = TMP / "reportes"
tracker.RUTA = TMP / "datos" / "sistema.db"
report.REPORTES = TMP / "reportes"
WEB_REAL = RAIZ / "web" / "data"
_web_antes = {f: f.stat().st_mtime_ns for f in WEB_REAL.glob("*.json")} if WEB_REAL.exists() else {}
print("Directorio temporal de la simulación:", TMP)

rng = np.random.default_rng(11)
EQ = ["Arsenal", "Chelsea", "Liverpool", "Manchester City", "Manchester United", "Tottenham", "Newcastle",
      "Brighton", "Aston Villa", "West Ham", "Everton", "Fulham", "Brentford", "Wolves", "Crystal Palace", "Bournemouth"]
FD = {"Manchester City": "Man City", "Manchester United": "Man United"}  # nombres distintos en football-data
T = {e: dict(at=rng.normal(0, .3), de=rng.normal(0, .25), cg=rng.normal(0, .15), cc=rng.normal(0, .12),
             tg=rng.normal(0, .15), tp=rng.normal(0, .12)) for e in EQ}


def tasas(h, a):
    lam, mu = np.exp(.15 + T[h]["at"] + T[a]["de"] + .25), np.exp(.15 + T[a]["at"] + T[h]["de"])
    cl, cv = np.exp(1.65 + T[h]["cg"] + T[a]["cc"] + .1), np.exp(1.65 + T[a]["cg"] + T[h]["cc"])
    tl, tv = np.exp(.75 + T[h]["tg"] + T[a]["tp"]), np.exp(.75 + T[a]["tg"] + T[h]["tp"] + .08)
    return lam, mu, cl, cv, tl, tv


def jugar(h, a):
    lam, mu, cl, cv, tl, tv = tasas(h, a)
    htl, htv = rng.poisson(lam * .45), rng.poisson(mu * .45)
    return dict(gl=htl + rng.poisson(lam * .55), gv=htv + rng.poisson(mu * .55), htl=htl, htv=htv,
                cl=rng.negative_binomial(8, 8 / (8 + cl)), cv=rng.negative_binomial(8, 8 / (8 + cv)),
                tjl=rng.poisson(tl), tjv=rng.poisson(tv))


def verdad(h, a):
    lam, mu, cl, cv, tl, tv = tasas(h, a)
    g = np.arange(11)
    out = mercados_desde_goles(np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu)), lam, mu)
    for ln in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5):
        out[f"corners:{ln}:over"] = 1 - poisson.cdf(int(ln), cl + cv)
    for ln in (2.5, 3.5, 4.5, 5.5, 6.5):
        out[f"cards:{ln}:over"] = 1 - poisson.cdf(int(ln), tl + tv)
    return out


# --- histórico para los modelos propios -------------------------------------
filas, d0 = [], pd.Timestamp.today() - pd.Timedelta(days=650)
for _ in range(3):
    for h in EQ:
        for a in EQ:
            if h != a:
                filas.append({"fecha": d0 + pd.Timedelta(days=int(rng.integers(0, 640))),
                              "local": FD.get(h, h), "visita": FD.get(a, a), **jugar(h, a)})
HIST = pd.DataFrame(filas).sort_values("fecha").reset_index(drop=True)
footballdata.historico = lambda *a, **k: HIST.copy()


# --- API-Football falsa (respuestas con el formato real) ----------------------
def cuota(p, margen, ruido):
    return round(max(1.01, 1 / (p * (1 + margen) * np.exp(rng.normal(0, ruido)))), 2)


class FakeAF(APIFootball):
    def __init__(self):
        super().__init__("fake")
        self.por_fecha, self.res, self.fx = {}, {}, {}

    def nuevo_dia(self, ahora):
        fecha = ahora.astimezone(pipeline.TZ).strftime("%Y-%m-%d")
        orden = rng.permutation(EQ)
        for i in range(8):
            fid = int(rng.integers(1e6, 9e6))
            h, a = orden[2 * i], orden[2 * i + 1]
            horas = 2 + i if i < 5 else 2 + 24 * (i - 4)     # 5 hoy y 3 en los próximos días
            ini = (ahora + timedelta(hours=horas)).astimezone(pipeline.TZ).isoformat()
            self.fx[fid] = dict(h=h, a=a, ini=ini, fecha=ini[:10], estado="NS")
            self.por_fecha.setdefault(ini[:10], []).append(fid)

    def raw(self, fid):
        f = self.fx[fid]
        r = self.res.get(fid, {})
        return {"fixture": {"id": fid, "date": f["ini"], "status": {"short": f["estado"]}},
                "league": {"id": 39, "name": "Premier League", "country": "England", "season": 2026},
                "teams": {"home": {"name": f["h"]}, "away": {"name": f["a"]}},
                "goals": {"home": r.get("gl"), "away": r.get("gv")},
                "score": {"halftime": {"home": r.get("htl"), "away": r.get("htv")}}}

    def _get(self, ruta, cache_horas=0, **p):
        if ruta == "/fixtures":
            return {"response": [self.raw(f) for f in self.por_fecha.get(p["date"], [])]}
        if ruta == "/odds":
            resp = []
            for fid in self.por_fecha.get(p["date"], []):
                f = self.fx[fid]
                v = verdad(f["h"], f["a"])
                casas = []
                for nombre, mg, rd in (("Pinnacle", .025, .015), ("Bet365", .06, .05), ("1xBet", .05, .06),
                                       ("Betano", .065, .06)):
                    q = lambda k: str(cuota(v[k], mg, rd))  # noqa: E731
                    bets = [{"name": "Match Winner", "values": [{"value": "Home", "odd": q("1x2:1")},
                             {"value": "Draw", "odd": q("1x2:X")}, {"value": "Away", "odd": q("1x2:2")}]},
                            {"name": "Goals Over/Under", "values": [
                                {"value": f"{s} {ln}", "odd": str(cuota(v[f'ou:{ln}:over'] if s == 'Over' else 1 - v[f'ou:{ln}:over'], mg, rd))}
                                for ln in (1.5, 2.5, 3.5) for s in ("Over", "Under")]},
                            {"name": "Both Teams Score", "values": [{"value": "Yes", "odd": q("btts:si")},
                                                                    {"value": "No", "odd": q("btts:no")}]},
                            {"name": "Double Chance", "values": [{"value": "Home/Draw", "odd": q("dc:1X")},
                             {"value": "Home/Away", "odd": q("dc:12")}, {"value": "Draw/Away", "odd": q("dc:X2")}]},
                            {"name": "Asian Handicap", "values": [{"value": "Home -0.5", "odd": q("ah:-0.5:1")},
                                                                  {"value": "Away +0.5", "odd": q("ah:-0.5:2")}]}]
                    if nombre != "Pinnacle":  # córners/tarjetas solo en casas blandas
                        bets += [{"name": "Corners Over Under", "values": [
                                    {"value": f"Over {ln}", "odd": str(cuota(v[f'corners:{ln}:over'], mg, rd * 1.5))}
                                    for ln in (8.5, 9.5, 10.5)] + [
                                    {"value": f"Under {ln}", "odd": str(cuota(1 - v[f'corners:{ln}:over'], mg, rd * 1.5))}
                                    for ln in (8.5, 9.5, 10.5)]},
                                 {"name": "Cards Over/Under", "values": [
                                    {"value": f"{s} 4.5", "odd": str(cuota(v['cards:4.5:over'] if s == 'Over' else 1 - v['cards:4.5:over'], mg, rd * 1.5))}
                                    for s in ("Over", "Under")]}]
                    casas.append({"name": nombre, "bets": bets})
                resp.append({"fixture": {"id": fid}, "bookmakers": casas})
            return {"response": resp, "paging": {"total": 1}}
        if ruta == "/predictions":
            f = self.fx[p["fixture"]]
            v = verdad(f["h"], f["a"])
            q = np.array([v["1x2:1"], v["1x2:X"], v["1x2:2"]]) * np.exp(rng.normal(0, .35, 3))  # muy ruidosa
            q = (q / q.sum() * 100).round()
            return {"response": [{"predictions": {"percent": {"home": f"{q[0]:.0f}%", "draw": f"{q[1]:.0f}%",
                                                              "away": f"{q[2]:.0f}%"}}}]}
        if ruta == "/fixtures/statistics":
            r = self.res.get(p["fixture"])
            if not r:
                return {"response": []}
            return {"response": [{"statistics": [{"type": "Corner Kicks", "value": r["cl"]},
                                                 {"type": "Yellow Cards", "value": r["tjl"]}, {"type": "Red Cards", "value": None}]},
                                 {"statistics": [{"type": "Corner Kicks", "value": r["cv"]},
                                                 {"type": "Yellow Cards", "value": r["tjv"]}, {"type": "Red Cards", "value": 0}]}]}
        return {"response": []}

    def terminar(self, hasta=None):
        for fid, f in self.fx.items():
            if f["estado"] == "NS" and (hasta is None or datetime.fromisoformat(f["ini"]) < hasta):
                self.res[fid] = jugar(f["h"], f["a"])
                f["estado"] = "FT"


class FakeForebet(Forebet):
    def __init__(self, af):
        super().__init__("fake")
        self.af = af

    def predicciones(self, dias=2):
        out = []
        for fid, f in self.af.fx.items():
            if f["estado"] != "NS":
                continue
            v = verdad(f["h"], f["a"])
            n = lambda p: int(np.clip(round(100 * p * np.exp(rng.normal(0, .08))), 1, 99))  # noqa: E731
            ph, pdw = n(v["1x2:1"]), n(v["1x2:X"])
            row = {"homeTeam": f["h"].replace("Manchester", "Man."), "awayTeam": f["a"], "kickoffDate": f["ini"][:10],
                   "probabilityHome": ph, "probabilityDraw": pdw, "probabilityAway": max(1, 100 - ph - pdw),
                   "probabilityOver25": n(v["ou:2.5:over"]), "probabilityBttsYes": n(v["btts:si"]),
                   "probabilityCornersOver95": n(v["corners:9.5:over"]), "probabilityCardsOver": n(v["cards:4.5:over"]),
                   "predictedCornersAverage": 10.1, "predictedCardsAverage": 4.4}
            row["probabilityUnder25"], row["probabilityBttsNo"] = 100 - row["probabilityOver25"], 100 - row["probabilityBttsYes"]
            row["probabilityCornersUnder95"], row["probabilityCardsUnder"] = 100 - row["probabilityCornersOver95"], 100 - row["probabilityCardsOver"]
            out.append({"local": row["homeTeam"], "visita": row["awayTeam"], "fecha": row["kickoffDate"],
                        "probs": a_claves(row, 4.5)})
        return out


# --- 25 días -------------------------------------------------------------------
cfg = config.cargar()
cfg["ligas"] = [cfg["ligas"][0]]
af, fb, odds = FakeAF(), None, OddsAPI("")
fb = FakeForebet(af)
# ClubElo falso: Elo según la fuerza real (ataque - defensa) con ruido, para ejercitar la fuente "elo" sin internet
ELO_FALSO = {e: 1500 + 600 * (T[e]["at"] - T[e]["de"]) + rng.normal(0, 40) for e in EQ}
import contextlib, io  # noqa: E401
inicio_sim = datetime.now(timezone.utc)
for dia in range(25):
    ahora = inicio_sim + timedelta(days=dia)
    af.nuevo_dia(ahora)
    with contextlib.redirect_stdout(io.StringIO() if dia else sys.stdout):
        partidos = pipeline.analizar(cfg, af, odds, fb, ahora, elo_ratings=ELO_FALSO)
        dias = pipeline.picks_por_dia(partidos, cfg)
        valor = [x for d in dias.values() for x in d["valor"]]
        alta = [x for d in dias.values() for x in d["alta"]]
    tracker.guardar_predicciones(partidos)
    tracker.agregar_picks(valor, "valor")
    tracker.agregar_picks(alta, "alta")
    if dia == 24:
        break
    af.terminar(ahora + timedelta(hours=20))
    tracker.actualizar_resultados(af, cfg, ahora + timedelta(days=1))

res, calib = tracker.resumen(), tracker.calibracion()
h, t = report.guardar(valor, alta, partidos, cfg, res, calib, "simulación")
print(t.read_text())
print("\nFuentes del último partido:", {k: len(v) for k, v in partidos[0]["fuentes"].items()})
print("Mercados distintos analizados:", len({k for p in partidos for k in p["probs"]}))
print("\nPrecisión (Brier) por fuente y mercado:")
for (s, fam), v in sorted(calib.items(), key=lambda kv: (kv[0][1], kv[1]["brier"])):
    print(f"  {fam:8s} {s:12s} {v['brier']:.4f} n={v['n']}")
k = next(k for k in partidos[0]["probs"] if k == "1x2:1")
print("\nPesos 1X2 tras calibrar:", {s: round(w, 2) for s, w in partidos[0]["probs"][k]["pesos"].items()})
print("Resumen:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in res.items() if k != "por_mercado"})
print("Por mercado:", res.get("por_mercado"))
print("HTML:", h)

# --- exportar para la web + backtest sintético --------------------------------
from picks import backtest, exportar  # noqa: E402

exportar.WEB = TMP / "web_data"

from picks import niveles, seleccion  # noqa: E402
from picks.fuentes.ia import AnalistaIA  # noqa: E402


class FakeIA(AnalistaIA):
    def analizar(self, s):
        r = ["bajo", "medio", "alto"][int(rng.integers(0, 3))]
        return {"probabilidad": float(np.clip(s["p"] + rng.normal(0, .05), .02, .98)), "riesgo": r,
                "alertas": ["Baja confirmada del delantero titular"] if r != "bajo" else [],
                "resumen": "Sin novedades relevantes; el local llega con el plantel completo." if r == "bajo"
                else "Rotaciones probables por partido de copa a mitad de semana."}


dias = pipeline.picks_por_dia(partidos, cfg)
ia = FakeIA("fake")
cand = [x for d in dias.values() for x in d["valor"] + d["seguras"] + [p for c in d["grandes"] for p in c["piernas"]]]
print("IA revisó:", ia.revisar(partidos, cand, cfg))
dias = pipeline.picks_por_dia(partidos, cfg)
for f, d in dias.items():
    print(f, "valor", len(d["valor"]), "seguras", len(d["seguras"]), "grandes", len(d["grandes"]))
exportar.hoy(partidos, dias, cfg, "simulación")
exportar.historial()
exportar.fuentes(cfg)

filas = []
d0 = pd.Timestamp.today() - pd.Timedelta(days=1000)
for k in range(5):
    for h in EQ:
        for a in EQ:
            if h == a:
                continue
            v = verdad(h, a)
            r = jugar(h, a)
            fila = {"fecha": d0 + pd.Timedelta(days=int(rng.integers(0, 995))), "local": FD.get(h, h),
                    "visita": FD.get(a, a), "gl": r["gl"], "gv": r["gv"]}
            ps = {"1": v["1x2:1"], "X": v["1x2:X"], "2": v["1x2:2"], "o": v["ou:2.5:over"], "u": v["ou:2.5:under"]}
            for suf, p in ps.items():
                fila[f"ps_{suf}"] = cuota(p, .025, .03)
                fila[f"psc_{suf}"] = cuota(p, .02, .015)
                fila[f"b365_{suf}"] = cuota(p, .055, .05)
                fila[f"max_{suf}"] = max(cuota(p, .03, .05) for _ in range(6))
            filas.append(fila)
dfb = pd.DataFrame(filas).sort_values("fecha").reset_index(drop=True)
res_bt = backtest.resumir(backtest.liga("E0", "Premier League", cfg, dfb)["apuestas"])
exportar.backtest(res_bt)
for f, r in res_bt.items():
    print(f"BACKTEST {f}: n={r['n']} acierto {r['acierto']:.0%} ROI {r['roi']:+.1%} CLV {r['clv']:+.1%} racha {r['max_racha_perdidas']}")


# --- aserciones reales ----------------------------------------------------------------
def _sin_nan(texto):
    def malo(c):
        raise AssertionError(f"JSON con {c}")
    return json.loads(texto, parse_constant=malo)


with tracker.con() as _c:
    n_picks = _c.execute("SELECT COUNT(*) FROM picks").fetchone()[0]
assert n_picks > 0, "la simulación no generó ningún pick"

pesos_1x2 = partidos[0]["probs"]["1x2:1"]["pesos"]
assert pesos_1x2["apifootball"] < pesos_1x2["mercado"], f"apifootball debía pesar menos que mercado: {pesos_1x2}"

if res.get("n"):
    assert -0.5 <= res["roi"] <= 0.5, f"ROI fuera de rango: {res['roi']}"
else:
    print("AVISO: sin apuestas registradas con cuota tomada; no se evalúa el ROI real.")

jsons = sorted((TMP / "web_data").glob("*.json"))
assert {j.name for j in jsons} >= {"hoy.json", "historial.json", "fuentes.json", "backtest.json"}, jsons
for j in jsons:
    texto = j.read_text(encoding="utf-8")
    datos = _sin_nan(texto)
    assert '"banca"' not in texto, f"{j.name} publica la banca"
    if j.name == "historial.json":
        assert '"monto"' not in texto and '"ganancia"' not in texto, "historial.json publica dólares"
assert _sin_nan((TMP / "web_data" / "hoy.json").read_text(encoding="utf-8"))["simulacion"] is True

# el proyecto real quedó intacto
assert CENTINELA.exists(), "la simulación borró datos/ del proyecto"
CENTINELA.unlink()
if _db_real_antes:
    assert (_db_real.stat().st_mtime_ns, _db_real.stat().st_size) == _db_real_antes, "la simulación modificó la base real"
assert {f: f.stat().st_mtime_ns for f in WEB_REAL.glob("*.json")} == _web_antes, "la simulación escribió en web/data real"
print(f"\nOK simulación: {n_picks} picks, pesos 1X2 {({k: round(v, 2) for k, v in pesos_1x2.items()})}, "
      f"{len(jsons)} JSON válidos, datos/ real intacto.")
