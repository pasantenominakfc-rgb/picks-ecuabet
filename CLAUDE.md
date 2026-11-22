# Picks Ecuabet: contexto del proyecto para Claude Code

## Qué es
Sistema que todos los días analiza partidos de fútbol (Europa, Norteamérica y
Sudamérica, de hoy a +5 días) y entrega picks para apostar en **Ecuabet**
(Ecuador). Se usa desde una **app web instalable (PWA)** en `web/`. El motor en
Python corre en GitHub Actions y publica la web en GitHub Pages.

**Perfil activo: plan GRATIS de API-Football** (100 consultas/día, 10/min): hoy +1 día, 11 ligas
(LigaPro, Champions, Europa League, Premier, LaLiga, Serie A, Bundesliga, Ligue 1, Libertadores,
Sudamericana, MLS) y pocas predicciones. El perfil completo (todas las ligas, +5 días) está
documentado como `perfil_pro` en `config.yaml` y requiere un plan de pago.

**Repositorio público sin dinero:** la banca, los montos y las ganancias en dólares NO se publican
(`hoy.json` no trae banca; `historial.json` trae `u` = resultado en unidades de apuesta, solo de picks
`registrado=1`). La banca vive en el navegador (localStorage) y en la variable `BANCA` (solo Telegram).
La base SQLite NO está en `main` ni en claro en ningún lado: vive **CIFRADA** como `sistema.db.enc`
(openssl AES-256-CBC, PBKDF2 200000, sal aleatoria) en la rama huérfana `datos`, junto con `web_data/`
(JSON públicos). El secret `DB_KEY` la descifra al inicio de cada job y la cifra al final; si falta, el job
falla. Si pierdes `DB_KEY` se pierde el historial. `web/data/*.json` está en `.gitignore` de `main`.

El usuario está en Ecuador (zona horaria America/Guayaquil) y habla español.
**Todo texto para el usuario va en español.**

## Niveles de picks (Seguras, Valor, Grandes, Locas y Combinadas)
- **Seguras:** simples con probabilidad ≥ 72% y cuota 1.25–1.60 (2% de la banca). Usan la
  **cuota estimada de Ecuabet** (justa × 0.94, o la real si la anotaste), no una cuota verificada.
- **Valor:** EV ≥ 4% contra la mejor cuota (Kelly 1/4, tope 3% por pick y 10% por día). El consenso
  de **≥ 2 fuentes** se exige solo aquí. La IA ajusta la probabilidad pero **no cuenta como fuente**.
  `elo`, `modelo` y `penaltyblog` forman UN solo grupo estadístico (cuentan 1 en conjunto): Valor exige además
  al menos una fuente externa (mercado, Forebet o API-Football).
  **LigaPro Ecuador no tiene `odds_key`** (no se verificó una clave de The Odds API): sin cuotas de casas no hay
  fuente "mercado" ni cuota real, así que ahí no sale Valor (sí Seguras con cuota estimada).
- **Grandes:** combinadas con objetivo de **cobro total** `grandes_objetivos: [100, 200, 500]` y monto
  `grandes_monto` (config.yaml); la cuota objetivo es objetivo/monto. (CLAUDE.md decía $50–$1000: era
  el rango de la web; el motor usa la lista del config.) Lo público es la ganancia NETA
  `monto*(cuota-1)` y `cobro_total` aparte. El algoritmo elige las piernas con mejor eficiencia
  `-log(p)/log(cuota)`, una por partido.
- **Locas (ALTO RIESGO):** simples de cuota 3-12, p >= 0.12, EV >= 0.10 con cuota REAL de casas (`cuota_ecuabet` o
  `mejor_cuota`); sin cuota real NO se generan. Mismo consenso que Valor (fuente externa, min_fuentes, dispersión,
  acuerdo). Stake `locas_stake_pct` (0.5%, mínimo `stake_minimo`), máx. `locas_max_dia` (3) y exposición
  `locas_exposicion_dia_pct` (1.5%). Tipo `locas` en el tracker (ROI separado). `hoy.json`: `dias[f].locas` (campos de
  `valor` + `nivel`, `stake`). Descarta NaN/inf, p fuera de (0,1), "sin empate" y todo partido que ya tenga pick de
  Valor/Alta/Seguras. Con stake mínimo 1.0 y 1.5% de exposición: banca 100 admite 1 Loca/día, 200+ admiten 3; si ni
  una cabe se imprime un aviso. La IA revisa las Locas primero.
  El `acuerdo` (min_acuerdo) cuenta el grupo estadístico (elo+modelo+penaltyblog) como UN voto (mayoría del grupo).
  Las Combinadas no repiten las piernas de Grandes. ClubElo solo por https (sin fallback http).
- **Combinadas:** `dias[f].combinadas`: candidatas con cuota 3-60, p >= 0.05, máx. 10/día, piernas como Grandes, `objetivo` None.
- **Forebet asíncrono:** run de Apify con sondeo cada ~10 s hasta `forebet_espera_max_seg` (480 s); al agotarse se aborta y
  se sigue sin Forebet. `partidos[].forebet_ctx` (forma, posición, tendencia, marcador, goles, valor %, clima) es solo
  informativo. Sus **cuotas** (`cuotas_ref`) son REFERENCIA ESTIMADA (casa no nombrada, no de Ecuabet): no entran a
  `mercado`, ni cuentan como fuente, ni sirven para EV. Los nombres de campos de forma/posición/clima son suposiciones
  (no probado con el actor real).
- Mercados de resultado: se liquidan a los **90 minutos** (tiempo reglamentario, sin prórroga/AET).

## Arquitectura
```
main.py                     CLI: hoy | liquidar | resumen | pendientes | registrar | omitir |
                            registrar-web | omitir-web | backtest | verificar | ligas
config.yaml                 TODO lo ajustable: banca, filtros, ligas (40+), pesos, IA, fechas
picks/
  pipeline.py               analizar(): partidos hoy..+N días, fuentes → ensamble; picks_por_dia()
  fuentes/apifootball.py    API-Football (base): partidos, cuotas de todos los mercados, predicciones, stats
  fuentes/forebet.py        Forebet vía el actor de Apify solidcode/forebet-scraper (requiere APIFY_TOKEN)
  fuentes/oddsapi.py        The Odds API (Pinnacle/Betfair); requiere ODDS_API_KEY (sin ella no hay cuotas de casas)
  fuentes/clubelo.py        ClubElo (gratis, sin clave): ratings Elo -> 1X2/dc/dnb; fuente "elo" solo en ligas de Europa; elo+modelo+penaltyblog = UN solo grupo estadístico (cuentan 1 en conjunto)
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
.github/workflows/          diario (07:00 y 13:00 de Ecuador), registrar (lote JSON), backtest (domingos), verificar.
                            Grupos: `picks-datos` (diario+backtest) y `picks-registrar` (propio); los tres escriben la
                            rama `datos` (base cifrada `sistema.db.enc`): descifrar->aplicar->cifrar->push se reintenta
                            3 veces y reaplica sobre la versión remota. Permisos mínimos; el token solo en el último paso.
tests/simulacion.py         simulación de punta a punta con fuentes falsas (sin internet)
tests/ultimos30.py          prueba con DATOS REALES de los últimos 30 días (descarga football-data)
tests/test_exportar.py      pytest: los JSON públicos no filtran banca/dólares y no tienen NaN
```

## Secrets (GitHub → Settings → Secrets → Actions)
ClubElo no necesita clave. `API_FOOTBALL_KEY` (obligatoria), `DB_KEY` (obligatoria: clave larga que cifra la base), `APIFY_TOKEN`, `ODDS_API_KEY`, `GROQ_API_KEY`,
`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`. Variable opcional: `BANCA`.
Nunca subas claves al repositorio.

## Workflows: comportamiento a respetar
- `registrar`: `registrar-lote` corre con `continue-on-error`; re-exportar, guardar y publicar corren siempre (si
  se descifró bien) y un paso final deja el job en rojo si el lote tuvo errores (lo válido ya quedó guardado).
- Un `204` de `workflow_dispatch` solo significa "encolado": la app debe esperar al workflow y no dar por guardada
  la apuesta. GitHub conserva 1 run pendiente por grupo (por eso un único lote).
- `diario` avisa con `::warning::` si `main.py hoy` imprime "sin datos: no se publica" (no cambies ese texto sin
  ajustar el `grep` de diario.yml).
- Si la rama `datos` trae un `sistema.db` en claro, los jobs se niegan a continuar (borrar y recrear la rama).
- Pendiente: fijar por SHA las actions (`checkout`, `setup-python`, `cache`, `upload-pages-artifact`, `deploy-pages`).

## Resultados verificados (no inventar otros)
Provienen de `tests/ultimos30.py` (backtest con cuotas de Bet365/Betfair), **no del tracker** de
apuestas reales. El ROI real (`historial.json`) cuenta solo apuestas que el usuario registró; el ROI
teórico del backtest no es una promesa de ganancia.
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
- Tras cambiar código, correr `python tests/simulacion.py` (usa un directorio temporal; no toca
  `datos/` ni `web/data` reales) y `pytest tests/test_exportar.py`.
  Si hay internet, también `python tests/ultimos30.py`.
- La UI es mobile-first. Revisarla a 390 px de ancho, en modo claro y oscuro.
- Ser honesto: ningún sistema garantiza ganar. Mostrar siempre la probabilidad real
  de las combinadas.
