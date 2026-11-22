# Sistema de picks diarios: decisiones de diseño

## v4 (22/11/2026): todas las ligas y fechas
- 40+ ligas (Europa, Norte/Centroamérica, Sudamérica) más el modo "todas las ligas" por región.
- Analiza de hoy a +5 días. La app tiene selector de fecha y filtros por región y por liga.
- Picks calculados día por día (seguras, valor, grandes).

## v3: app web + puesta en marcha
- App web instalable (PWA) en `web/`, publicada en GitHub Pages; el motor Python corre en GitHub Actions.
- Pestañas: Hoy, Partidos, Rendimiento, Fuentes y Ajustes. Registro de apuestas desde la app con workflow_dispatch.
- Workflows: diario (12:00 y 18:00 UTC), registrar, backtest (domingos) y verificar.
- Backtest walk-forward contra Bet365 y la cuota máxima; CLV contra el cierre.

## v2: multi-mercado y multi-fuente
- 12 familias y 73 selecciones: 1X2, DC, DNB, goles, BTTS, goles por equipo, AH, 1er tiempo, córners y tarjetas.
- Fuentes:
  - API-Football (base).
  - Forebet vía Apify.
  - The Odds API.
  - Modelos propios: Dixon-Coles, y binomial negativa para córners y tarjetas.
  - penaltyblog.
  - IA con Groq.
- Ensamble con pesos ajustados por log-loss histórico.
- Filtros de consenso: al menos 2 fuentes, dispersión ≤ 8 pts, EV ≥ 4%.
- Monto: 1/4 de Kelly, máximo 3% por pick y 10% por día.
- Niveles: seguras (p ≥ 72%, cuota 1.25–1.60), valor y grandes (combinadas por objetivo).
- Ecuabet no tiene API: el código se genera a mano en el cupón.

## Pendiente con datos reales
- Verificar los ids de ligas de API-Football (`python main.py verificar`).
- Verificar el peso de la roja en Ecuabet y la línea de tarjetas de Forebet.
