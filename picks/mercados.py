"""Catálogo de mercados: claves, nombres en español, grupos para quitar margen y liquidación.

Formato de clave:  familia:linea:seleccion  (la línea es opcional)
  1x2:1 | 1x2:X | 1x2:2               resultado final
  dc:1X | dc:12 | dc:X2               doble oportunidad
  dnb:1 | dnb:2                       apuesta sin empate (empate = devolución)
  ou:2.5:over | ou:2.5:under          goles totales
  btts:si | btts:no                   ambos marcan
  tl:1.5:over / tv:0.5:under          goles del local / de la visita
  ah:-1.5:1 | ah:-1.5:2               hándicap asiático (línea aplicada al LOCAL)
  ht1x2:1 | ht1x2:X | ht1x2:2         resultado al medio tiempo
  htou:0.5:over                       goles en el primer tiempo
  corners:9.5:over                    córners totales
  cards:4.5:over                      tarjetas totales
"""

FAMILIAS = {
    "1x2": "Resultado final", "dc": "Doble oportunidad", "dnb": "Apuesta sin empate",
    "ou": "Goles totales", "btts": "Ambos marcan", "tl": "Goles del local", "tv": "Goles de la visita",
    "ah": "Hándicap asiático", "ht1x2": "Resultado 1er tiempo", "htou": "Goles 1er tiempo",
    "corners": "Córners totales", "cards": "Tarjetas totales",
}

LINEAS = {
    "ou": [0.5, 1.5, 2.5, 3.5, 4.5],
    "tl": [0.5, 1.5, 2.5], "tv": [0.5, 1.5, 2.5],
    "ah": [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5],
    "htou": [0.5, 1.5],
    "corners": [7.5, 8.5, 9.5, 10.5, 11.5, 12.5],
    "cards": [2.5, 3.5, 4.5, 5.5, 6.5],
}

# Líneas principales que se guardan para medir el error de cada fuente
CALIBRACION = ["1x2:1", "1x2:X", "1x2:2", "dc:1X", "dc:X2", "ou:1.5:over", "ou:2.5:over",
               "ou:3.5:over", "btts:si", "ht1x2:1", "ht1x2:X", "ht1x2:2", "corners:9.5:over",
               "cards:4.5:over"]


def familia(clave: str) -> str:
    return clave.split(":")[0]


def grupo(clave: str) -> str:
    """Selecciones que forman un mercado completo (para quitar margen)."""
    return clave.rsplit(":", 1)[0]


def suma_grupo(clave: str) -> float:
    return 2.0 if familia(clave) == "dc" else 1.0


def todas_las_claves() -> list[str]:
    c = ["1x2:1", "1x2:X", "1x2:2", "dc:1X", "dc:12", "dc:X2", "dnb:1", "dnb:2",
         "btts:si", "btts:no", "ht1x2:1", "ht1x2:X", "ht1x2:2"]
    for fam in ("ou", "tl", "tv", "htou", "corners", "cards"):
        for ln in LINEAS[fam]:
            c += [f"{fam}:{ln}:over", f"{fam}:{ln}:under"]
    for ln in LINEAS["ah"]:
        c += [f"ah:{ln:+}:1", f"ah:{ln:+}:2"]
    return c


def nombre(clave: str, local: str = "Local", visita: str = "Visita") -> str:
    p = clave.split(":")
    fam = p[0]
    eq = {"1": local, "2": visita, "X": "Empate"}
    if fam == "1x2":
        return f"Gana {eq[p[1]]}" if p[1] != "X" else "Empate"
    if fam == "dc":
        return {"1X": f"{local} o empate", "12": f"{local} o {visita}", "X2": f"Empate o {visita}"}[p[1]]
    if fam == "dnb":
        return f"{eq[p[1]]} (sin empate)"
    if fam == "btts":
        return "Ambos marcan: Sí" if p[1] == "si" else "Ambos marcan: No"
    if fam == "ht1x2":
        return f"1er tiempo: {eq[p[1]] if p[1] != 'X' else 'Empate'}"
    if fam == "ah":
        ln = float(p[1])
        return f"{local} {ln:+g}" if p[2] == "1" else f"{visita} {-ln:+g}"
    mm = "Más de" if p[2] == "over" else "Menos de"
    sujeto = {"ou": "goles", "tl": f"goles de {local}", "tv": f"goles de {visita}",
              "htou": "goles 1er tiempo", "corners": "córners", "cards": "tarjetas"}[fam]
    return f"{mm} {p[1]} {sujeto}"


def resultado(clave: str, r: dict) -> str | None:
    """'ganada' | 'perdida' | 'nula' | None (si falta el dato).
    r: gl, gv, htl, htv, corners, cards (cualquiera puede faltar)."""
    p = clave.split(":")
    fam = p[0]
    gl, gv = r.get("gl"), r.get("gv")

    def gp(ok):
        return None if ok is None else ("ganada" if ok else "perdida")

    def ou(valor, ln, lado):
        if valor is None:
            return None
        return gp(valor > ln if lado == "over" else valor < ln)

    if fam in ("1x2", "dc", "dnb", "btts", "ou", "tl", "tv", "ah") and (gl is None or gv is None):
        return None
    if fam == "1x2":
        return gp({"1": gl > gv, "X": gl == gv, "2": gl < gv}[p[1]])
    if fam == "dc":
        return gp({"1X": gl >= gv, "12": gl != gv, "X2": gl <= gv}[p[1]])
    if fam == "dnb":
        return "nula" if gl == gv else gp((gl > gv) if p[1] == "1" else (gl < gv))
    if fam == "btts":
        ambos = gl > 0 and gv > 0
        return gp(ambos if p[1] == "si" else not ambos)
    if fam == "ou":
        return ou(gl + gv, float(p[1]), p[2])
    if fam == "tl":
        return ou(gl, float(p[1]), p[2])
    if fam == "tv":
        return ou(gv, float(p[1]), p[2])
    if fam == "ah":
        ln = float(p[1])
        return gp(gl + ln > gv if p[2] == "1" else gl + ln < gv)
    if fam == "ht1x2":
        htl, htv = r.get("htl"), r.get("htv")
        if htl is None or htv is None:
            return None
        return gp({"1": htl > htv, "X": htl == htv, "2": htl < htv}[p[1]])
    if fam == "htou":
        htl, htv = r.get("htl"), r.get("htv")
        return None if htl is None or htv is None else ou(htl + htv, float(p[1]), p[2])
    if fam == "corners":
        return ou(r.get("corners"), float(p[1]), p[2])
    if fam == "cards":
        return ou(r.get("cards"), float(p[1]), p[2])
    return None


def prob_empuje(clave: str, probs: dict) -> float:
    """Probabilidad de devolución (solo 'sin empate')."""
    return probs.get("1x2:X", 0.0) if familia(clave) == "dnb" else 0.0


def valor_esperado(p: float, cuota: float, p_push: float = 0.0) -> float:
    """EV por cada $1. En 'sin empate' p es la probabilidad condicionada a que no haya empate."""
    return (1 - p_push) * (p * cuota - 1)
