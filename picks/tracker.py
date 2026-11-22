"""Base de datos (SQLite): picks, predicciones por fuente, resultados y calibración."""
import math
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import mercados as M
from .config import DATOS

RUTA = DATOS / "sistema.db"
TZ = ZoneInfo("America/Guayaquil")
LIQUIDADOS = ("ganada", "perdida", "nula")
VENTANA_DIAS = 10                              # cuántos días atrás se piden resultados
VENTANA_APLAZADOS = 14                         # ventana ampliada SOLO para picks aplazados
DIAS_ANULAR_APLAZADO = 7                       # días desde el inicio programado para anular un aplazado
ANULADOS_API = ("CANC", "ABD", "AWD")          # sin resultado válido: se anula de inmediato
APLAZADOS_API = ("PST", "SUSP", "INT")         # puede jugarse después: se mantiene pendiente
CUOTA_MIN, CUOTA_MAX, MONTO_MAX = 1.01, 100.0, 10000.0
_RE_ID = re.compile(r"[\w.:+\-|]{1,64}")     # cubre uid (md5/af_id) y claves como "ah:-1.5:1"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS picks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, tipo TEXT, uid TEXT, af_id INTEGER, liga TEXT,
  inicio TEXT, local TEXT, visita TEXT, clave TEXT, nombre TEXT, p REAL, p_push REAL,
  cuota_justa REAL, cuota_minima REAL, cuota_tomada REAL, monto REAL, estado TEXT DEFAULT 'pendiente',
  ganancia REAL, registrado INTEGER DEFAULT 0, aplazado_desde TEXT, UNIQUE(uid, clave));
CREATE TABLE IF NOT EXISTS predicciones (
  uid TEXT, af_id INTEGER, inicio TEXT, fuente TEXT, clave TEXT, p REAL, PRIMARY KEY(uid, fuente, clave));
CREATE TABLE IF NOT EXISTS resultados (
  af_id INTEGER PRIMARY KEY, gl INTEGER, gv INTEGER, htl INTEGER, htv INTEGER, corners INTEGER, cards INTEGER);
"""


def hoy_ec() -> datetime:
    """Ahora, con zona America/Guayaquil. ÚNICA fuente de 'hoy' en este módulo."""
    return datetime.now(TZ)


def con():
    c = sqlite3.connect(RUTA)
    c.row_factory = sqlite3.Row
    c.executescript(ESQUEMA)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(picks)")}
    for col, tipo in (("registrado", "INTEGER DEFAULT 0"), ("aplazado_desde", "TEXT")):   # migración de DB vieja
        if col not in cols:
            c.execute(f"ALTER TABLE picks ADD COLUMN {col} {tipo}")
            c.commit()
    return c


# ------------------------------------------------------------------ validación
def num(x) -> float | None:
    """Número finito desde int/float/texto (acepta coma decimal). None si no es válido."""
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x.strip().replace(",", ".")) if isinstance(x, str) else float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def clave_valida(x) -> bool:
    if isinstance(x, int) and not isinstance(x, bool):
        x = str(x)
    return isinstance(x, str) and _RE_ID.fullmatch(x) is not None


def validar_apuesta(cuota, monto) -> tuple[float, float] | str:
    """(cuota, monto) normalizados, o un texto con el motivo del rechazo."""
    q, m = num(cuota), num(monto)
    if q is None or not CUOTA_MIN <= q <= CUOTA_MAX:
        return f"cuota inválida (entre {CUOTA_MIN} y {CUOTA_MAX:g})"
    if m is None or not 0 < m <= MONTO_MAX:
        return f"monto inválido (mayor que 0 y hasta {MONTO_MAX:g})"
    return q, m


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
    """Inserta picks sugeridos (idempotente). NO quedan registrados: la cuota/monto sugeridos son
    hipotéticos hasta que el usuario registre su apuesta."""
    hoy = hoy_ec().strftime("%Y-%m-%d")
    with con() as c:
        for s in picks:
            c.execute("""INSERT OR IGNORE INTO picks (fecha,tipo,uid,af_id,liga,inicio,local,visita,clave,nombre,p,
                         p_push,cuota_justa,cuota_minima,cuota_tomada,monto,registrado)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                      (hoy, tipo, s["uid"], s["af_id"], s["liga"], s["inicio"], s["local"], s["visita"], s["clave"],
                       s["nombre"], s["p"], s["p_push"], s["cuota_justa"], s["cuota_minima"],
                       s.get("cuota_ecuabet"), s.get("monto", 0.0)))


def _estado(pid: int) -> str | None:
    with con() as c:
        r = c.execute("SELECT estado FROM picks WHERE id=?", (pid,)).fetchone()
    return r["estado"] if r else None


def _registrar_id(pid: int, cuota, monto) -> str | None:
    """Registra la apuesta del usuario (conserva el tipo). None = ok; si no, el motivo del rechazo."""
    estado = _estado(pid)
    if estado is None:
        return "pick no encontrado"
    if estado in LIQUIDADOS:
        return "el pick ya está liquidado"
    if monto is None:
        with con() as c:
            monto = c.execute("SELECT monto FROM picks WHERE id=?", (pid,)).fetchone()["monto"]
    v = validar_apuesta(cuota, monto)
    if isinstance(v, str):
        return v
    with con() as c:
        c.execute("UPDATE picks SET cuota_tomada=?, monto=?, registrado=1, estado=CASE WHEN estado='no_apostada' "
                  "THEN 'pendiente' ELSE estado END WHERE id=?", (v[0], v[1], pid))
    return None


def registrar(pid: int, cuota, monto=None) -> bool:
    return _registrar_id(pid, cuota, monto) is None


def _id(uid: str, clave: str) -> int | None:
    with con() as c:
        r = c.execute("SELECT id FROM picks WHERE uid=? AND clave=?", (str(uid), clave)).fetchone()
    return r["id"] if r else None


def _id_valido(uid, clave) -> tuple[int | None, str | None]:
    if not (clave_valida(uid) and clave_valida(clave)):
        return None, "uid/clave inválidos"
    pid = _id(str(uid), str(clave))
    return (pid, None) if pid is not None else (None, "pick no encontrado")


def registrar_web_motivo(uid, clave, cuota, monto) -> str | None:
    """Desde la web: registra la apuesta hecha. None = ok; si no, el motivo del rechazo."""
    pid, err = _id_valido(uid, clave)
    return err or _registrar_id(pid, cuota, monto)


def registrar_web(uid, clave, cuota, monto) -> bool:
    return registrar_web_motivo(uid, clave, cuota, monto) is None


def omitir_web_motivo(uid, clave) -> str | None:
    pid, err = _id_valido(uid, clave)
    if err:
        return err
    if _estado(pid) in LIQUIDADOS:
        return "el pick ya está liquidado"
    omitir(pid)
    return None


def omitir_web(uid, clave) -> bool:
    return omitir_web_motivo(uid, clave) is None


def omitir(pid: int):
    with con() as c:
        c.execute("UPDATE picks SET estado='no_apostada', registrado=0, cuota_tomada=NULL, monto=0.0, "
                  "ganancia=NULL WHERE id=? AND estado NOT IN ('ganada','perdida','nula')", (pid,))


def pendientes():
    with con() as c:
        return [dict(r) for r in c.execute("SELECT * FROM picks WHERE estado='pendiente' ORDER BY inicio")]


# --------------------------------------------------------------- resultados
def _dt(txt: str) -> datetime:
    """ISO con cualquier offset -> datetime con zona (sin zona = hora de Ecuador)."""
    d = datetime.fromisoformat(txt)
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def actualizar_resultados(af, cfg: dict, ahora: datetime | None = None) -> int:
    """Baja marcadores (1 consulta por día) y córners/tarjetas (1 por partido) y liquida picks."""
    if not af or not af.activa:
        return 0
    ahora = ahora or hoy_ec()
    limite = ahora - timedelta(hours=3)
    desde, desde_aplaz = ahora - timedelta(days=VENTANA_DIAS), ahora - timedelta(days=VENTANA_APLAZADOS)
    with con() as c:
        aplazados = {r["af_id"] for r in c.execute(
            "SELECT DISTINCT af_id FROM picks WHERE aplazado_desde IS NOT NULL AND af_id IS NOT NULL")}
        cand = c.execute("""SELECT DISTINCT af_id, inicio FROM predicciones
                            WHERE af_id IS NOT NULL AND af_id NOT IN (SELECT af_id FROM resultados)""").fetchall()
        faltan = []
        for r in cand:
            try:
                ini = _dt(r["inicio"])
            except (TypeError, ValueError):
                continue
            if (desde_aplaz if r["af_id"] in aplazados else desde) < ini < limite:
                faltan.append((r["af_id"], ini.astimezone(TZ).date().isoformat()))
        fechas = sorted({d for _, d in faltan})
        ids = {i for i, _ in faltan}
        for d in fechas:
            resp = af._get("/fixtures", cache_horas=0, date=d, timezone="America/Guayaquil").get("response", [])
            for f in resp:
                fx = af._fixture(f)
                if fx["af_id"] not in ids:
                    continue
                if fx["estado"] in ("FT", "AET", "PEN") and fx["gl"] is not None:
                    c.execute("INSERT OR REPLACE INTO resultados (af_id,gl,gv,htl,htv) VALUES (?,?,?,?,?)",
                              (fx["af_id"], fx["gl"], fx["gv"], fx["htl"], fx["htv"]))
                    # nula por aplazamiento y luego se jugó: se reabre para liquidar con el resultado
                    c.execute("UPDATE picks SET estado='pendiente', ganancia=NULL "
                              "WHERE af_id=? AND estado='nula' AND aplazado_desde IS NOT NULL", (fx["af_id"],))
                elif fx["estado"] in APLAZADOS_API:    # sigue pendiente; se anula pasados DIAS_ANULAR_APLAZADO
                    c.execute("UPDATE picks SET aplazado_desde=COALESCE(aplazado_desde, ?) "
                              "WHERE af_id=? AND estado IN ('pendiente','no_apostada')",
                              (ahora.isoformat(), fx["af_id"]))
                elif fx["estado"] in ANULADOS_API:     # sin resultado válido: se anula (se devuelve el monto)
                    c.execute("UPDATE picks SET estado='nula', ganancia=CASE WHEN registrado=1 THEN 0.0 END "
                              "WHERE af_id=? AND estado IN ('pendiente','no_apostada')", (fx["af_id"],))
        # aplazados sin FT tras 7 días del inicio programado (aunque la API ya no los devuelva): nula
        for r in c.execute("""SELECT id, inicio FROM picks WHERE aplazado_desde IS NOT NULL
                              AND estado IN ('pendiente','no_apostada')
                              AND af_id NOT IN (SELECT af_id FROM resultados)""").fetchall():
            try:
                vencido = ahora - _dt(r["inicio"]) >= timedelta(days=DIAS_ANULAR_APLAZADO)
            except (TypeError, ValueError):
                continue
            if vencido:
                c.execute("UPDATE picks SET estado='nula', ganancia=CASE WHEN registrado=1 THEN 0.0 END WHERE id=?",
                          (r["id"],))
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


def _ganancia(estado: str, monto: float, cuota: float) -> float:
    return round({"ganada": monto * (cuota - 1), "perdida": -monto, "nula": 0.0}[estado], 2)


def liquidar() -> int:
    """Fija el estado de todo pick con resultado. La ganancia REAL solo se calcula para picks
    registrados por el usuario (con su cuota y monto); los demás quedan con ganancia NULL."""
    n = 0
    with con() as c:
        for p in c.execute("""SELECT p.*, r.gl, r.gv, r.htl, r.htv, r.corners, r.cards FROM picks p
                              JOIN resultados r ON r.af_id=p.af_id WHERE p.estado='pendiente'""").fetchall():
            res = M.resultado(p["clave"], _limpio(p))
            if res is None:
                continue
            real = p["registrado"] and (p["cuota_tomada"] or 0) > 1 and (p["monto"] or 0) > 0
            g = _ganancia(res, p["monto"], p["cuota_tomada"]) if real else None
            c.execute("UPDATE picks SET estado=?, ganancia=? WHERE id=?", (res, g, p["id"]))
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


def _bloque(filas: list[dict], gan, cuota, monto) -> dict:
    apostado = sum(monto(f) for f in filas)
    neto = sum(gan(f) for f in filas)
    por_mercado = defaultdict(lambda: {"n": 0, "neto": 0.0, "apostado": 0.0})
    por_tipo = defaultdict(lambda: {"n": 0, "neto": 0.0, "apostado": 0.0})
    for f in filas:
        for d, k in ((por_mercado, M.FAMILIAS[M.familia(f["clave"])]), (por_tipo, f["tipo"])):
            d[k]["n"] += 1
            d[k]["neto"] += gan(f)
            d[k]["apostado"] += monto(f)
    return {"n": len(filas), "acierto": sum(f["estado"] == "ganada" for f in filas) / len(filas),
            "apostado": apostado, "neto": neto, "roi": neto / apostado if apostado else 0,
            "ev_esperado": sum(monto(f) * M.valor_esperado(f["p"], cuota(f), f["p_push"] or 0) for f in filas),
            "por_mercado": dict(por_mercado), "por_tipo": dict(por_tipo)}


def resumen() -> dict:
    """ROI REAL: solo picks registrados por el usuario (todos los tipos, con desglose 'por_tipo').
    La clave 'teorico' es una vista HIPOTÉTICA aparte (todo pick liquidado con cuota mínima y monto
    sugeridos, o 1 si no hay): no es dinero real."""
    with con() as c:
        todas = [dict(r) for r in c.execute("SELECT * FROM picks WHERE estado IN ('ganada','perdida','nula')")]
        pend = c.execute("SELECT COUNT(*) FROM picks WHERE estado='pendiente' AND registrado=1").fetchone()[0]
        pend_sr = c.execute("SELECT COUNT(*) FROM picks WHERE estado='pendiente' AND registrado=0").fetchone()[0]
    reales = [f for f in todas if f["registrado"] and f["ganancia"] is not None]
    out = {"n": 0, "pendientes": pend, "pendientes_sin_registrar": pend_sr, "por_tipo": {}, "por_mercado": {}}
    if reales:
        out.update(_bloque(reales, lambda f: f["ganancia"], lambda f: f["cuota_tomada"], lambda f: f["monto"]))
    if todas:
        def cuota_t(f):
            return f["cuota_tomada"] if f["registrado"] and (f["cuota_tomada"] or 0) > 1 else f["cuota_minima"]

        def monto_t(f):
            return f["monto"] if (f["monto"] or 0) > 0 else 1.0
        t = _bloque(todas, lambda f: _ganancia(f["estado"], monto_t(f), cuota_t(f)), cuota_t, monto_t)
        t["nota"] = "HIPOTÉTICO, no es ROI real: incluye picks no registrados (cuota mínima y monto sugeridos, o 1)."
        out["teorico"] = t
    else:
        out["teorico"] = {"n": 0}
    return out
