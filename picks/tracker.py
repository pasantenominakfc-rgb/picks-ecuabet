"""Base de datos (SQLite): picks, predicciones por fuente, resultados y calibración."""
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import mercados as M
from .config import DATOS

RUTA = DATOS / "sistema.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS picks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, tipo TEXT, uid TEXT, af_id INTEGER, liga TEXT,
  inicio TEXT, local TEXT, visita TEXT, clave TEXT, nombre TEXT, p REAL, p_push REAL,
  cuota_justa REAL, cuota_minima REAL, cuota_tomada REAL, monto REAL, estado TEXT DEFAULT 'pendiente',
  ganancia REAL, UNIQUE(uid, clave));
CREATE TABLE IF NOT EXISTS predicciones (
  uid TEXT, af_id INTEGER, inicio TEXT, fuente TEXT, clave TEXT, p REAL, PRIMARY KEY(uid, fuente, clave));
CREATE TABLE IF NOT EXISTS resultados (
  af_id INTEGER PRIMARY KEY, gl INTEGER, gv INTEGER, htl INTEGER, htv INTEGER, corners INTEGER, cards INTEGER);
"""


def con():
    c = sqlite3.connect(RUTA)
    c.row_factory = sqlite3.Row
    c.executescript(ESQUEMA)
    return c


# ------------------------------------------------------------------ guardar
def guardar_predicciones(partidos: list[dict]):
    with con() as c:
        for pa in partidos:
            for fuente, probs in pa["fuentes"].items():
                for k in M.CALIBRACION:
                    if probs.get(k) is not None:
                        c.execute("INSERT OR REPLACE INTO predicciones VALUES (?,?,?,?,?,?)",
                                  (pa["uid"], pa["af_id"], pa["inicio"], fuente, k, probs[k]))
            for k in M.CALIBRACION:
                if k in pa["probs"]:
                    c.execute("INSERT OR REPLACE INTO predicciones VALUES (?,?,?,?,?,?)",
                              (pa["uid"], pa["af_id"], pa["inicio"], "ensamble", k, pa["probs"][k]["p"]))


def agregar_picks(picks: list[dict], tipo: str = "valor"):
    hoy = datetime.now().strftime("%Y-%m-%d")
    with con() as c:
        for s in picks:
            c.execute("""INSERT OR IGNORE INTO picks (fecha,tipo,uid,af_id,liga,inicio,local,visita,clave,nombre,p,
                         p_push,cuota_justa,cuota_minima,cuota_tomada,monto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (hoy, tipo, s["uid"], s["af_id"], s["liga"], s["inicio"], s["local"], s["visita"], s["clave"],
                       s["nombre"], s["p"], s["p_push"], s["cuota_justa"], s["cuota_minima"],
                       s.get("cuota_ecuabet"), s.get("monto", 0.0)))


def registrar(pid: int, cuota: float, monto: float | None = None):
    with con() as c:
        c.execute("UPDATE picks SET cuota_tomada=? WHERE id=?", (cuota, pid))
        if monto is not None:
            c.execute("UPDATE picks SET monto=? WHERE id=?", (monto, pid))


def _id(uid: str, clave: str) -> int | None:
    with con() as c:
        r = c.execute("SELECT id FROM picks WHERE uid=? AND clave=?", (str(uid), clave)).fetchone()
    return r["id"] if r else None


def registrar_web(uid: str, clave: str, cuota: float, monto: float):
    """Desde la web: registra (o crea como 'valor' si venía de 'alta') la apuesta hecha."""
    pid = _id(uid, clave)
    if pid is None:
        return False
    with con() as c:
        c.execute("UPDATE picks SET cuota_tomada=?, monto=?, tipo='valor', estado=CASE WHEN estado='no_apostada' "
                  "THEN 'pendiente' ELSE estado END WHERE id=?", (cuota, monto, pid))
    return True


def omitir_web(uid: str, clave: str):
    pid = _id(uid, clave)
    if pid is not None:
        omitir(pid)


def omitir(pid: int):
    with con() as c:
        c.execute("UPDATE picks SET estado='no_apostada' WHERE id=?", (pid,))


def pendientes():
    with con() as c:
        return [dict(r) for r in c.execute("SELECT * FROM picks WHERE estado='pendiente' ORDER BY inicio")]


# --------------------------------------------------------------- resultados
def actualizar_resultados(af, cfg: dict, ahora: datetime | None = None) -> int:
    """Baja marcadores (1 consulta por día) y córners/tarjetas (1 por partido) y liquida picks."""
    if not af or not af.activa:
        return 0
    ahora = ahora or datetime.now(timezone.utc)
    limite = (ahora - timedelta(hours=3)).isoformat()
    with con() as c:
        faltan = c.execute("""SELECT DISTINCT af_id, substr(inicio,1,10) d FROM predicciones
                              WHERE af_id IS NOT NULL AND inicio < ? AND af_id NOT IN (SELECT af_id FROM resultados)
                              AND inicio > ?""", (limite, (ahora - timedelta(days=5)).isoformat())
                           ).fetchall()
        fechas = sorted({r["d"] for r in faltan})
        ids = {r["af_id"] for r in faltan}
        for d in fechas:
            for f in af._get("/fixtures", cache_horas=0, date=d).get("response", []):
                fx = af._fixture(f)
                if fx["af_id"] in ids and fx["estado"] in ("FT", "AET", "PEN") and fx["gl"] is not None:
                    c.execute("INSERT OR REPLACE INTO resultados (af_id,gl,gv,htl,htv) VALUES (?,?,?,?,?)",
                              (fx["af_id"], fx["gl"], fx["gv"], fx["htl"], fx["htv"]))
        # córners/tarjetas: siempre para picks de esos mercados + una muestra para calibrar
        necesitan = [r["af_id"] for r in c.execute(
            """SELECT DISTINCT r.af_id FROM resultados r JOIN picks p ON p.af_id=r.af_id
               WHERE r.corners IS NULL AND (p.clave LIKE 'corners%' OR p.clave LIKE 'cards%')""")]
        muestra = [r["af_id"] for r in c.execute(
            "SELECT af_id FROM resultados WHERE corners IS NULL ORDER BY af_id DESC LIMIT ?",
            (cfg.get("stats_calibracion_dia", 8),))]
        for fid in dict.fromkeys(necesitan + muestra):
            st = af.estadisticas(fid, cfg.get("peso_roja", 1))
            st = st or {"corners": -1, "cards": -1}   # -1 = sin estadísticas (no reintentar)
            c.execute("UPDATE resultados SET corners=?, cards=? WHERE af_id=?", (st["corners"], st["cards"], fid))
    return liquidar()


def _limpio(fila) -> dict:
    d = dict(fila)
    for k in ("corners", "cards"):
        if d.get(k) is not None and d[k] < 0:
            d[k] = None
    return d


def liquidar() -> int:
    n = 0
    with con() as c:
        for p in c.execute("""SELECT p.*, r.gl, r.gv, r.htl, r.htv, r.corners, r.cards FROM picks p
                              JOIN resultados r ON r.af_id=p.af_id WHERE p.estado='pendiente'""").fetchall():
            res = M.resultado(p["clave"], _limpio(p))
            if res is None:
                continue
            cuota = p["cuota_tomada"] or p["cuota_minima"]
            g = {"ganada": p["monto"] * (cuota - 1), "perdida": -p["monto"], "nula": 0.0}[res]
            c.execute("UPDATE picks SET estado=?, ganancia=?, cuota_tomada=? WHERE id=?",
                      (res, round(g, 2), cuota, p["id"]))
            n += 1
    return n


# --------------------------------------------------------------- calibración
def calibracion() -> dict:
    """{(fuente, familia): {n, ll, brier}} con log-loss de cada fuente."""
    acc = defaultdict(lambda: [0, 0.0, 0.0])
    with con() as c:
        filas = c.execute("""SELECT pr.fuente, pr.clave, pr.p, r.* FROM predicciones pr
                             JOIN resultados r ON r.af_id=pr.af_id""").fetchall()
    for f in filas:
        res = M.resultado(f["clave"], _limpio(f))
        if res not in ("ganada", "perdida"):
            continue
        y = 1.0 if res == "ganada" else 0.0
        p = min(max(f["p"], 0.01), 0.99)
        a = acc[(f["fuente"], M.familia(f["clave"]))]
        a[0] += 1
        a[1] += -(y * math.log(p) + (1 - y) * math.log(1 - p))
        a[2] += (p - y) ** 2
    return {k: {"n": v[0], "ll": v[1] / v[0], "brier": v[2] / v[0]} for k, v in acc.items() if v[0]}


def resumen() -> dict:
    with con() as c:
        filas = [dict(r) for r in c.execute(
            "SELECT * FROM picks WHERE tipo='valor' AND estado IN ('ganada','perdida','nula')")]
        pend = c.execute("SELECT COUNT(*) FROM picks WHERE estado='pendiente' AND tipo='valor'").fetchone()[0]
    if not filas:
        return {"n": 0, "pendientes": pend}
    apostado = sum(f["monto"] for f in filas)
    neto = sum(f["ganancia"] for f in filas)
    por_mercado = defaultdict(lambda: {"n": 0, "neto": 0.0, "apostado": 0.0})
    for f in filas:
        m = por_mercado[M.FAMILIAS[M.familia(f["clave"])]]
        m["n"] += 1
        m["neto"] += f["ganancia"]
        m["apostado"] += f["monto"]
    return {"n": len(filas), "acierto": sum(f["estado"] == "ganada" for f in filas) / len(filas),
            "apostado": apostado, "neto": neto, "roi": neto / apostado if apostado else 0,
            "ev_esperado": sum(f["monto"] * M.valor_esperado(f["p"], f["cuota_tomada"], f["p_push"] or 0)
                               for f in filas),
            "por_mercado": dict(por_mercado), "pendientes": pend}
