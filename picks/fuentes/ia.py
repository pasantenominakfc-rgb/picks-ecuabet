"""Analista de IA con Groq (groq/compound busca en la web en tiempo real).

Para cada pick candidato busca lesiones, suspensiones, alineaciones, rotaciones y
noticias, y devuelve: su propia probabilidad, alertas, nivel de riesgo y un
resumen en español. Se usa como fuente adicional de bajo peso y como filtro:
un pick con riesgo "alto" sale de las seguras y de las combinadas.
"""
import json
import re
import time
from datetime import date

import requests

from ..config import DATOS

URL = "https://api.groq.com/openai/v1/chat/completions"

PROMPT = """Eres un analista de apuestas deportivas. Partido: {local} vs {visita} ({liga}), {fecha}.
Selección a evaluar: "{nombre}" (mercado: {mercado}). Los modelos estadísticos le dan {p:.0%} de probabilidad.
Busca en la web noticias de las últimas 72 horas: lesiones y suspensiones importantes, alineaciones probables,
rotaciones por otras competiciones, motivación (descenso, título, clásico), clima o cambio de entrenador.
Responde SOLO con un JSON válido, sin texto adicional:
{{"probabilidad": <tu estimación entre 0 y 1 para que se cumpla la selección>,
  "riesgo": "bajo" | "medio" | "alto",
  "alertas": ["máximo 3 alertas cortas y concretas"],
  "resumen": "máximo 2 frases en español explicando tu conclusión"}}"""


def _json(texto: str) -> dict | None:
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class AnalistaIA:
    def __init__(self, clave: str, modelo: str = "groq/compound", max_consultas: int = 15):
        self.clave, self.modelo, self.max = clave, modelo, max_consultas
        self.usadas = 0
        self.cache_ruta = DATOS / "cache" / f"ia_{date.today()}.json"
        self.cache_ruta.parent.mkdir(exist_ok=True)
        self.cache = json.loads(self.cache_ruta.read_text()) if self.cache_ruta.exists() else {}

    @property
    def activa(self):
        return bool(self.clave)

    def analizar(self, s: dict) -> dict | None:
        k = f"{s['uid']}|{s['clave']}"
        if k in self.cache:
            return self.cache[k]
        if not self.activa or self.usadas >= self.max:
            return None
        self.usadas += 1
        msg = PROMPT.format(local=s["local"], visita=s["visita"], liga=s.get("liga", ""), fecha=s["inicio"][:10],
                            nombre=s["nombre"], mercado=s.get("mercado", ""), p=s["p"])
        for intento in range(2):
            try:
                r = requests.post(URL, headers={"Authorization": f"Bearer {self.clave}"}, timeout=90,
                                  json={"model": self.modelo, "messages": [{"role": "user", "content": msg}],
                                        "temperature": 0.2})
                if r.status_code == 429:
                    time.sleep(8)
                    continue
                r.raise_for_status()
                d = _json(r.json()["choices"][0]["message"]["content"])
                if d and isinstance(d.get("probabilidad"), (int, float)):
                    d["probabilidad"] = min(max(float(d["probabilidad"]), 0.01), 0.99)
                    d["riesgo"] = d.get("riesgo") if d.get("riesgo") in ("bajo", "medio", "alto") else "medio"
                    self.cache[k] = d
                    self.cache_ruta.write_text(json.dumps(self.cache, ensure_ascii=False))
                    return d
            except Exception as e:  # noqa: BLE001
                print(f"  ! Groq: {e}")
        return None

    def revisar(self, partidos: list[dict], candidatos: list[dict], cfg: dict) -> int:
        """Analiza candidatos; ajusta pa['probs'][clave] (peso bajo, con tope) y guarda pa['ia'][clave]."""
        por_uid = {pa["uid"]: pa for pa in partidos}
        w, tope = cfg.get("ia_peso", 0.15), cfg.get("ia_ajuste_max", 0.08)
        n, vistos = 0, set()
        for c in sorted(candidatos, key=lambda c: -c.get("p", 0)):
            key = (c["uid"], c["clave"])
            pa = por_uid.get(c["uid"])
            if key in vistos or not pa or c["clave"] not in pa["probs"]:
                continue
            vistos.add(key)
            info = pa["probs"][c["clave"]]
            d = self.analizar({**c, "p": info["p"]})
            if not d:
                continue
            n += 1
            delta = max(-tope, min(tope, w * (d["probabilidad"] - info["p"])))
            info["p_previa"], info["p"] = info["p"], min(max(info["p"] + delta, 0.01), 0.99)
            info["detalle"] = {**info["detalle"], "ia": d["probabilidad"]}
            info["n"] = len(info["detalle"])
            pa.setdefault("ia", {})[c["clave"]] = {"riesgo": d["riesgo"], "alertas": d.get("alertas", [])[:3],
                                                   "resumen": d.get("resumen", ""), "p_ia": d["probabilidad"]}
            pa["fuentes"].setdefault("ia", {})[c["clave"]] = d["probabilidad"]
        return n
