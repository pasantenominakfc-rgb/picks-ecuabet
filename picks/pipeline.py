"""Orquesta el análisis diario: fuentes -> modelos -> ensamble -> selección."""
import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from .errores import describir
from . import ensamble, mercados as M, names, niveles, regiones, seleccion, tracker
from .fuentes import clubelo, footballdata, oddsapi
from .modelos.conteos import ModeloConteo
from .modelos.goles import DixonColes
from .modelos.pb import ModeloPB

TZ = ZoneInfo("America/Guayaquil")


def hoy_ec(ahora: datetime | None = None):
    """Fecha de hoy en Ecuador (America/Guayaquil). Única fuente de 'hoy' del proyecto:
    el runner de GitHub Actions está en UTC y date.today() daría el día equivocado de noche."""
    return (ahora or datetime.now(timezone.utc)).astimezone(TZ).date()


class ResultadoAnalisis(list):
    """Lista de partidos analizados (compatible con el uso anterior) + `info` con avisos para main/exportar:
    cuota_agotada (bool), ligas_sin_datos (list[str]), ligas_fallidas (list[{liga, error}])."""

    def __init__(self, partidos=(), info=None):
        super().__init__(partidos)
        self.info = info or {}


def _uid(local, visita, inicio):
    return hashlib.md5(f"{local}|{visita}|{inicio[:10]}".encode()).hexdigest()[:12]


class Modelos:
    """Ajusta (una vez por liga) los modelos de goles, córners y tarjetas."""

    def __init__(self, liga: dict, af, cfg: dict, temporada: int | None):
        self.goles, self.corners, self.cards, self.equipos = None, None, None, []
        hist = pd.DataFrame()
        if liga.get("fd"):
            hist = footballdata.historico(liga["fd"], liga.get("tipo", "main"), cfg.get("peso_roja", 1))
        if len(hist) < 60 and af and af.activa and temporada and liga.get("historico", True):
            hist = af.historico(liga["af"], temporada)
        self.pb = None
        if len(hist) >= 60:
            self.pb = ModeloPB().ajustar(hist)
            self.goles = DixonColes().ajustar(hist)
            self.equipos = self.goles.equipos
            if "cl" in hist and hist["cl"].notna().sum() >= 80:
                self.corners = ModeloConteo().ajustar(hist, "cl", "cv")
            if "tjl" in hist and hist["tjl"].notna().sum() >= 80:
                self.cards = ModeloConteo().ajustar(hist, "tjl", "tjv")
        print(f"  modelos {liga['nombre']}: {len(hist)} partidos | goles {'ok' if self.goles and self.goles.ok else '–'}"
              f" | córners {'ok' if self.corners and self.corners.ok else '–'}"
              f" | tarjetas {'ok' if self.cards and self.cards.ok else '–'}")

    def probs(self, local: str, visita: str) -> tuple[dict | None, dict]:
        if not self.goles or not self.goles.ok:
            return None, {}
        l, v = names.emparejar(local, self.equipos), names.emparejar(visita, self.equipos)
        if not (l and v) or l == v:
            return None, {}
        out = self.goles.mercados(l, v) or {}
        esperados = {"goles": (out.get("_xg_local", 0) + out.get("_xg_visita", 0)) or None}
        for nombre, mod, fam in (("corners", self.corners, "corners"), ("tarjetas", self.cards, "cards")):
            if mod and mod.ok:
                pm = mod.prob_mas_de(l, v, M.LINEAS[fam])
                if pm:
                    esperados[nombre] = pm.pop("_media")
                    for ln, p in pm.items():
                        out[f"{fam}:{ln}:over"], out[f"{fam}:{ln}:under"] = p, 1 - p
        return out, esperados

    def probs_pb(self, local: str, visita: str) -> dict | None:
        if not self.pb or not self.pb.ok:
            return None
        l, v = names.emparejar(local, self.pb.equipos), names.emparejar(visita, self.pb.equipos)
        if not (l and v) or l == v:
            return None
        r = self.pb.mercados(l, v)
        return {k: x for k, x in r.items() if not k.startswith("_")} if r else None


def contexto_forebet(pa: dict, fb: dict | None) -> dict | None:
    """Contexto informativo (forma, posición, cuotas de REFERENCIA) de la fila de Forebet emparejada; None si no hay.
    No entra a probabilidades, a 'mercado' ni al conteo de fuentes."""
    return (fb or {}).get("ctx") or None


def analizar(cfg: dict, af, odds, forebet, ahora: datetime | None = None,
             elo_ratings: dict | None = None) -> ResultadoAnalisis:
    """Analiza todos los partidos desde ahora hasta el final del día hoy + dias_adelante.
    Devuelve una lista de partidos con el atributo `.info` (ver ResultadoAnalisis). Una liga que falla
    se registra y se salta; nunca aborta todo el análisis."""
    ahora = ahora or datetime.now(timezone.utc)
    info = {"cuota_agotada": False, "ligas_sin_datos": [], "ligas_fallidas": [], "cuotas_af_no_disponibles": False,
            "cuotas_casas": False, "forebet": False, "ligas_omitidas_por_tope": 0}
    if af is not None and hasattr(af, "max_por_minuto"):   # plan gratis de API-Football: 10 peticiones/minuto
        af.max_por_minuto = cfg.get("af_max_por_minuto", 10)
    dias = cfg.get("dias_adelante", 5)
    hoy_local = ahora.astimezone(TZ).date()
    gratis = str(cfg.get("af_plan", "")).strip().lower() == "gratis"
    if gratis:   # el plan gratis solo sirve /fixtures para [ayer, mañana]: más días gastan llamadas inútiles
        dias = min(dias, 1)
    if af is not None and hasattr(af, "configurar_plan"):
        af.configurar_plan(cfg.get("af_plan", "pro"), hoy_local)
    fechas = [(hoy_local + timedelta(days=d)).isoformat() for d in range(dias + 1)]
    info["plan_af"] = "gratis" if gratis else "pro"
    info["dias_max"] = dias
    fin = datetime.combine(hoy_local + timedelta(days=dias + 1), datetime.min.time(), TZ).astimezone(timezone.utc)
    ligas_af = {l["af"]: l for l in cfg["ligas"] if l.get("af")}
    todas = cfg.get("incluir_todas_las_ligas", False)
    regiones_ok = set(cfg.get("regiones_todas", []))

    # 1) partidos base (API-Football)
    fixtures = []
    if af and af.activa:
        for f in fechas:
            try:
                fixtures += af.partidos(f, None if todas else set(ligas_af))
            except Exception as e:  # noqa: BLE001
                print(f"  ! partidos del {f}: {describir(e)}")
                info["ligas_fallidas"].append({"liga": f"(fixtures {f})", "error": describir(e)})
    fixtures = [f for f in fixtures if f["estado"] in ("NS", "TBD")
                and ahora <= datetime.fromisoformat(f["inicio"]).astimezone(timezone.utc) < fin]
    if todas:  # ligas que no están en la lista: se agregan si son de las regiones elegidas
        for f in fixtures:
            if f["liga_id"] not in ligas_af:
                reg = regiones.region(f.get("pais"), f.get("liga", ""))
                if reg in regiones_ok:
                    ligas_af[f["liga_id"]] = {"nombre": f"{f['liga']} ({f['pais']})", "region": reg, "af": f["liga_id"],
                                              "historico": cfg.get("historico_ligas_extra", False)}
        fixtures = [f for f in fixtures if f["liga_id"] in ligas_af]
    print(f"Partidos del {fechas[0]} al {fechas[-1]}: {len(fixtures)} en {len({f['liga_id'] for f in fixtures})} ligas")

    # 2) fuentes externas una sola vez
    fb_filas = forebet.predicciones(dias + 1) if forebet and forebet.activa else []
    info["forebet"] = bool(fb_filas)
    print(f"Forebet: {len(fb_filas)} pronósticos")
    # ClubElo: ratings de hoy (una descarga por día, tolerante a fallos). `elo_ratings` permite inyectarlos (pruebas).
    if elo_ratings is None:
        elo_ratings = clubelo.descargar(hoy_local) if cfg.get("elo_activo", True) else {}
    info["elo"] = bool(elo_ratings)
    print(f"ClubElo: {len(elo_ratings)} clubes")
    calib = tracker.calibracion()
    prior = cfg["pesos_iniciales"]

    # ligas a analizar: solo con partidos; primero las de la lista de cfg (orden de cfg["ligas"]), luego el resto, con tope
    por_liga = {}
    for f in fixtures:
        por_liga.setdefault(f["liga_id"], []).append(f)
    ids_cfg = [l["af"] for l in cfg["ligas"] if l.get("af")]
    orden = [i for i in ids_cfg if i in por_liga] + [i for i in ligas_af if i not in ids_cfg and i in por_liga]
    tope = cfg.get("max_ligas_analizadas", 25 if gratis else None)
    if tope is not None and len(orden) > int(tope):
        info["ligas_omitidas_por_tope"] = len(orden) - int(tope)
        print(f"Tope max_ligas_analizadas={tope}: se omiten {len(orden) - int(tope)} ligas menores")
        orden = orden[:int(tope)]
    # presupuesto de The Odds API: las ligas con partidos hoy primero (estable: conserva el orden de cfg)
    orden.sort(key=lambda i: not any(f["inicio"][:10] == fechas[0] for f in por_liga[i]))
    max_odds = oddsapi.tope_corrida(cfg)
    con_odds = [i for i in orden if ligas_af[i].get("odds_key")][:max_odds]

    partidos, n_pred_af = [], 0
    for liga_id in orden:
        liga, fx_liga = ligas_af[liga_id], por_liga[liga_id]
        print(f"→ {liga['nombre']}: {len(fx_liga)} partidos")
        antes = len(partidos)
        try:
            temporada = fx_liga[0]["temporada"]
            modelos = Modelos(liga, af, cfg, temporada)
            cuotas_af = {}
            for d in sorted({f["inicio"][:10] for f in fx_liga}):
                cuotas_af |= af.cuotas_liga(liga_id, temporada, d)
            eventos_odds = odds.cuotas(liga["odds_key"], 24 * (dias + 1)) if odds and odds.activa and \
                liga_id in con_odds else []

            for fx in fx_liga:
                casas = {k: dict(v) for k, v in cuotas_af.get(fx["af_id"], {}).items()}
                ev = names.emparejar_partido(fx["local"], fx["visita"], eventos_odds)
                if ev:
                    for casa, c in ev["casas"].items():
                        casas.setdefault(casa, {}).update(c)
                fuentes = {}
                mkt = ensamble.probs_mercado(casas, cfg["casas_afiladas"], {cfg["casa_objetivo"]})
                if mkt:
                    fuentes["mercado"] = mkt
                    info["cuotas_casas"] = True
                pm, esperados = modelos.probs(fx["local"], fx["visita"])
                if pm:
                    fuentes["modelo"] = {k: v for k, v in pm.items() if not k.startswith("_")}
                ppb = modelos.probs_pb(fx["local"], fx["visita"])
                if ppb:
                    fuentes["penaltyblog"] = ppb
                fb = names.emparejar_partido(fx["local"], fx["visita"],
                                             [r for r in fb_filas if r["fecha"] in (fx["inicio"][:10], None)] or fb_filas)
                if fb:
                    fuentes["forebet"] = {k: v for k, v in fb["probs"].items() if not k.startswith("_")}
                    for meta, nombre in (("_corners", "corners_fb"), ("_tarjetas", "tarjetas_fb")):
                        if meta in fb["probs"]:
                            esperados[nombre] = fb["probs"][meta]
                # ClubElo solo cubre bien clubes europeos: fuera de Europa hay homónimos (Barcelona SC, Atletico-MG, Liverpool de Uruguay)
                if elo_ratings and liga.get("region") == "Europa":   # solo si se encuentran AMBOS equipos
                    el, ev_ = clubelo.buscar_elo(fx["local"], elo_ratings), clubelo.buscar_elo(fx["visita"], elo_ratings)
                    if el is not None and ev_ is not None:
                        fuentes["elo"] = clubelo.probs_desde_elo(el, ev_, cfg.get("elo_ventaja_local", clubelo.VENTAJA_LOCAL),
                                                                 cfg.get("elo_p_empate_max", clubelo.P_EMPATE_MAX))
                if af and af.activa and n_pred_af < cfg["max_predicciones_af"]:
                    pa = af.prediccion(fx["af_id"])
                    n_pred_af += 1
                    if pa:
                        fuentes["apifootball"] = pa
                if not fuentes:
                    continue
                partidos.append({
                    "uid": str(fx["af_id"]), "af_id": fx["af_id"], "liga": liga["nombre"],
                    "region": liga.get("region") or regiones.region(fx.get("pais"), fx.get("liga", "")),
                    "inicio": fx["inicio"], "fecha": fx["inicio"][:10],
                    "local": fx["local"], "visita": fx["visita"], "fuentes": fuentes,
                    "forebet_ctx": contexto_forebet(fx, fb),
                    "probs": ensamble.combinar(fuentes, prior, calib, cfg),
                    "mejores": ensamble.mejores_cuotas(casas, cfg["casas_afiladas"], cfg["casa_objetivo"]),
                    "ecuabet": casas.get(cfg["casa_objetivo"], {}), "n_casas": len(casas),
                    "xg": (pm.get("_xg_local"), pm.get("_xg_visita")) if pm else None, "esperados": esperados})
        except Exception as e:  # noqa: BLE001   (una liga mala no tumba las demás)
            print(f"  ! liga {liga['nombre']} falló: {describir(e)}")
            info["ligas_fallidas"].append({"liga": liga["nombre"], "error": describir(e)})
        if len(partidos) == antes:
            info["ligas_sin_datos"].append(liga["nombre"])

    info["cuotas_af_no_disponibles"] = bool(getattr(af, "cuotas_no_disponibles", False))
    resumen = getattr(af, "resumen_plan", None)
    if callable(resumen):
        txt = resumen()
        if txt:
            print(f"  ! {txt}")
    info["cuota_agotada"] = bool(getattr(af, "sin_cuota", False) or getattr(af, "cuota_agotada", False))
    if info["cuota_agotada"]:
        print("  ! Cuota diaria de API-Football agotada: resultados parciales")
    return ResultadoAnalisis(partidos, info)


def picks_por_dia(partidos: list[dict], cfg: dict) -> dict:
    """{fecha: {valor, alta, seguras, grandes, locas, combinadas}} calculado día por día."""
    out = {}
    for fecha in sorted({p["fecha"] for p in partidos}):
        del_dia = [p for p in partidos if p["fecha"] == fecha]
        valor, alta = seleccion.elegir(del_dia, cfg)
        seg, grandes = niveles.seguras(del_dia, cfg), niveles.grandes(del_dia, cfg)
        ya = {str(x["uid"]) for x in valor + alta + seg}      # un partido con pick de otro nivel no recibe Loca
        out[fecha] = {"valor": valor, "alta": alta, "seguras": seg, "grandes": grandes,
                      "locas": niveles.locas(del_dia, cfg, excluir_uids=ya),
                      "combinadas": niveles.combinadas(del_dia, cfg, grandes)}
    return out



def candidatos_ia(dias: dict, n_dias: int = 2) -> list[dict]:
    """Picks que la IA revisa: Valor, Seguras, Locas y piernas de Grandes de los primeros `n_dias` días."""
    return [x for f in sorted(dias)[:n_dias]
            for x in dias[f]["valor"] + dias[f]["seguras"] + dias[f].get("locas", [])
            + [p for c in dias[f]["grandes"] for p in c["piernas"]]]
