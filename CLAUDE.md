# Picks Ecuabet: contexto del proyecto para Claude Code

## Qué es
Sistema que todos los días analiza partidos de fútbol (Europa, Norteamérica y
Sudamérica, de hoy a +5 días) y entrega picks para apostar en **Ecuabet**
(Ecuador). Se usa desde una **app web instalable (PWA)** en `web/`. El motor en
Python corre en GitHub Actions y publica la web en GitHub Pages.

El usuario está en Ecuador (zona horaria America/Guayaquil) y habla español.
**Todo texto para el usuario va en español.**

## Tres niveles de picks
- **Seguras:** simples con probabilidad ≥ 72% y cuota 1.25–1.60 (2% de la banca).
- **Valor:** EV ≥ 4% contra la mejor cuota, con consenso entre fuentes (Kelly 1/4).
- **Grandes:** combinadas para cobrar un objetivo ($50–$1000) con poco monto. El
  algoritmo elige las piernas con mejor eficiencia `-log(p)/log(cuota)`, una por partido.

## Arquitectura
```
main.py                     CLI: hoy | liquidar | resumen | pendientes | registrar | omitir |
                            registrar-web | omitir-web | backtest | verificar | ligas
config.yaml                 TODO lo ajustable: banca, filtros, ligas (40+), pesos, IA, fechas
picks/
  pipeline.py               analizar(): partidos hoy..+N días, fuentes → ensamble; picks_por_dia()
  fuentes/apifootball.py    API-Football (base): partidos, cuotas de todos los mercados, predicciones, stats
  fuentes/forebet.py        Forebet vía el actor de Apify solidcode/forebet-scraper
  fuentes/oddsapi.py        The Odds API (Pinnacle/Betfair)
  fuentes/footballdata.py   histórico football-data.co.uk (goles, córners, tarjetas, cuotas)
  fuentes/ia.py             Groq groq/compound (busca noticias): ajusta p ±8 pts y marca riesgo
  modelos/goles.py          Dixon-Coles + derivación de los 73 mercados desde la matriz de goles
  modelos/pb.py             penaltyblog (Poisson bivariado) como fuente adicional
  modelos/conteos.py        córners y tarjetas: tasas por equipo + binomial negativa
  mercados.py               claves de mercado (1x2, dc, dnb, ou, btts, tl, tv, ah, ht1x2, htou, corners, cards),
                            nombres en español, liquidación
  ensamble.py               quitar margen (método de potencia), probs de mercado, pesos por log-loss
  seleccion.py              picks de valor (filtros de consenso + Kelly)
  niveles.py                seguras y grandes (combinadas por objetivo)
  tracker.py                SQLite datos/sistema.db: picks, predicciones por fuente, resultados, calibración
  exportar.py               web/data/*.json (hoy.json con "fechas" y "dias")
  report.py                 texto para Telegram + HTML simple
  backtest.py               walk-forward con football-data
  regiones.py               país → Europa / Sudamérica / Norteamérica
web/index.html              app (vanilla JS): Hoy (fechas, región, liga; Seguras/Valor/Grandes),
                            Partidos, Rendimiento, Fuentes, Ajustes. Registra apuestas con workflow_dispatch.
.github/workflows/          diario (07:00 y 13:00 de Ecuador), registrar, backtest (domingos), verificar
tests/simulacion.py         simulación de punta a punta con fuentes falsas (sin internet)
tests/ultimos30.py          prueba con DATOS REALES de los últimos 30 días (descarga football-data)
```

## Secrets (GitHub → Settings → Secrets → Actions)
`API_FOOTBALL_KEY` (obligatoria), `APIFY_TOKEN`, `ODDS_API_KEY`, `GROQ_API_KEY`,
`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`. Variable opcional: `BANCA`.
Nunca subas claves al repositorio.

## Resultados verificados (no inventar otros)
- Prueba real del 23/10 al 21/11/2026, 154 partidos de las 5 grandes ligas:
  - El favorito acertó el 1X2 en el 58% de los partidos.
  - **Seguras:** ganaron 63 de 79 (80%), contra un 75% esperado. Neto +2,2%.
  - **Grandes:** 0 de 10. La probabilidad de cada una era ~4%, y las piernas acertaron el 63% esperado.
  - **Valor:** solo 1 pick.
- Conclusión: las probabilidades están bien calibradas, y la ganancia depende de la cuota de Ecuabet.

## Reglas para Claude Code
- Ecuabet NO tiene API pública. El código de cupón se obtiene armando el cupón en su
  web y tocando "guardar/reservar apuesta". Nunca colocar apuestas reales ni manejar
  dinero o credenciales del usuario.
- No hacer scraping masivo de sitios que limitan (Forebet devuelve 429). Usar las
  fuentes oficiales: API-Football y Apify para Forebet.
- Tras cambiar código, correr `python tests/simulacion.py` (debe terminar sin errores).
  Si hay internet, también `python tests/ultimos30.py`.
- La UI es mobile-first. Revisarla a 390 px de ancho, en modo claro y oscuro.
- Ser honesto: ningún sistema garantiza ganar. Mostrar siempre la probabilidad real
  de las combinadas.
