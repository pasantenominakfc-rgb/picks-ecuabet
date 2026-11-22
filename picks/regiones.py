"""País → región (para el modo 'todas las ligas' y los filtros de la app)."""
EUROPA = {"England", "Spain", "Italy", "Germany", "France", "Netherlands", "Portugal", "Belgium", "Turkey", "Scotland",
          "Greece", "Austria", "Switzerland", "Denmark", "Norway", "Sweden", "Poland", "Czech-Republic", "Croatia",
          "Serbia", "Romania", "Ukraine", "Russia", "Hungary", "Slovakia", "Slovenia", "Bulgaria", "Cyprus", "Israel",
          "Ireland", "Wales", "Northern-Ireland", "Finland", "Iceland", "Bosnia", "Albania", "World"}
SUDAMERICA = {"Brazil", "Argentina", "Colombia", "Chile", "Peru", "Ecuador", "Uruguay", "Paraguay", "Bolivia", "Venezuela"}
NORTEAMERICA = {"USA", "Mexico", "Canada", "Costa-Rica", "Honduras", "Guatemala", "El-Salvador", "Panama", "Jamaica",
                "Nicaragua"}


def region(pais: str | None, liga: str = "") -> str | None:
    p = (pais or "").replace(" ", "-")
    if p in SUDAMERICA or "CONMEBOL" in liga.upper():
        return "Sudamérica"
    if p in NORTEAMERICA or "CONCACAF" in liga.upper():
        return "Norteamérica"
    if p in EUROPA or "UEFA" in liga.upper():
        return "Europa"
    return None
