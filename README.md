# Picks Ecuabet: sistema + app web

Un sistema que **todos los días** analiza los partidos y los mercados que ofrece
Ecuabet (1X2, doble oportunidad, goles, ambos marcan, hándicap, primer tiempo,
córners, tarjetas…), cruza varias fuentes (Forebet, cuotas de muchas casas,
modelos estadísticos propios y API-Football) y te muestra en tu celular **qué
apostar, a qué cuota mínima y cuánto**.

```
GitHub Actions (gratis, corre solo)            Tu celular
┌──────────────────────────────────┐          ┌──────────────────────┐
│ 07:00 y 13:00  → analiza partidos │ ──────►  │ App web (instalable) │
│ cada mañana    → liquida resultados│  publica │ Hoy · Partidos ·     │
│ domingos       → backtest          │ ◄──────  │ Rendimiento · Fuentes│
│ al registrar   → guarda tu apuesta │ registra │ + Telegram           │
└──────────────────────────────────┘          └──────────────────────┘
```

---

## Puesta en marcha (unos 20 minutos, una sola vez)

### 1. Saca tus claves

| Clave | Dónde | Costo |
|---|---|---|
| `API_FOOTBALL_KEY` (**obligatoria**) | <https://dashboard.api-football.com> → regístrate → copia tu API key | Gratis (100 consultas/día). Recomendado: Pro, USD 19/mes |
| `APIFY_TOKEN` (Forebet) | <https://console.apify.com> → Settings → API & Integrations | ~USD 0.10 por 1 000 partidos (el crédito gratis mensual alcanza) |
| `ODDS_API_KEY` (Pinnacle/Betfair) | <https://the-odds-api.com> | Gratis (500 créditos/mes) |
| `GROQ_API_KEY` (IA que revisa noticias) | <https://console.groq.com> → API Keys | Gratis con límites |
| `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` | Escribe a **@BotFather** → `/newbot` para el token. Luego escríbele a tu bot y a **@userinfobot** para tu chat id | Gratis |

### 2. Crea el repositorio en GitHub

1. Entra a <https://github.com/new>, ponle un nombre (p. ej. `picks-ecuabet`) y créalo.
2. Sube todo el contenido de esta carpeta: **Add file → Upload files** (arrastra
   todo, incluida la carpeta `.github`) → **Commit**.

> **¿Público o privado?** GitHub Pages es gratis en repositorios públicos. En uno
> privado necesitas GitHub Pro (USD 4/mes). Si lo dejas público, cualquiera con el
> enlace puede ver tus picks e historial.
> Alternativa gratis con repositorio privado: Cloudflare Pages (ver al final).

### 3. Configura

En tu repositorio:

1. **Settings → Secrets and variables → Actions → New repository secret:** agrega
   cada clave del paso 1 con su nombre exacto.
2. En la pestaña **Variables** de esa misma pantalla, agrega `BANCA` con tu banca
   (por ejemplo `100`).
3. **Settings → Pages → Source: GitHub Actions.**
4. **Settings → Actions → General → Workflow permissions: Read and write.**

### 4. Verifica y arranca

1. **Actions → Verificar puesta en marcha → Run workflow.** Todo debe salir con ✔.
   Si una liga sale ✘, corrige su id en `config.yaml`.
2. **Actions → Picks diarios → Run workflow.** En 3–5 minutos queda publicada tu
   página en `https://TU-USUARIO.github.io/picks-ecuabet/`.
3. **Actions → Backtest semanal → Run workflow** (opcional, ~10 min): muestra cómo
   le habría ido a la estrategia la temporada pasada.
4. Pon esa dirección en `url_web` dentro de `config.yaml`, para que llegue en el mensaje de Telegram.

### 5. Instala la app en tu celular

Abre la página. En iPhone: Safari → Compartir → **Agregar a inicio**. En Android:
Chrome → ⋮ → **Instalar app**.

Para registrar apuestas desde la app, entra a **Ajustes** y pon tu usuario, el
repositorio y un token de GitHub. Para crear el token: GitHub → Settings →
Developer settings → **Fine-grained tokens** → solo este repositorio → permiso
**Actions: Read and write**. El token se guarda solo en tu teléfono.

---

## Los tres niveles de la app

| Nivel | Qué es | Cuánto |
|---|---|---|
| ✅ **Seguras** | Simples con probabilidad ≥ 72% y cuota 1.25–1.60 | 2% de la banca |
| 💎 **Valor** | La cuota paga más de lo que vale. Es lo más rentable a largo plazo | Kelly 1/4 |
| 🚀 **Grandes** | Combinadas para ganar $50, $100, $200, $500 o $1000 con poco. Tú eliges el monto y el objetivo | Lo que quieras arriesgar |

Cada combinada muestra su **probabilidad real** (p. ej. "3,2% ≈ 1 de cada 31").

## IA: analista con Groq

Con `GROQ_API_KEY`, cada pick candidato pasa por `groq/compound`, que **busca en
la web** lesiones, suspensiones, alineaciones, rotaciones y noticias, y responde
con su probabilidad, su nivel de riesgo, sus alertas y un resumen en español.
- Su opinión mueve la probabilidad como máximo ±8 puntos.
- Un pick con **riesgo alto** sale de las seguras y de las combinadas.
- Su acierto se mide igual que el de las demás fuentes.

## Prueba con datos reales

`python tests/ultimos30.py` simula los últimos 30 días con partidos y cuotas
reales de las 5 grandes ligas, como si el sistema hubiera estado funcionando.
Se actualiza solo cada domingo y se ve en **Rendimiento**.

Resultado del 23/10 al 21/11/2026 (154 partidos):
- El favorito del sistema acertó el 1X2 en el 58% de los partidos.
- **Seguras:** ganaron 63 de 79 (80%), cuando el sistema esperaba un 75%. Neto +$3,52 (+2,2%) con $2 por apuesta.
- **Grandes:** se perdieron las 10. Su probabilidad era ~4% cada una, y 3 quedaron a una pierna de ganarse.
- **Valor:** solo apareció 1 pick. Las cuotas de Bet365 casi nunca pagan un 4% más que Betfair.

Conclusión: **las probabilidades del sistema son confiables**. Ganar depende de
tomar cuotas que paguen lo suficiente, y por eso la app te pide la cuota de Ecuabet.

## Uso diario

1. A las 7:00 te llega un Telegram con los picks. Abre la app.
2. En **Hoy**, toca **+ Ticket** en los picks que te interesan.
3. Abre Ecuabet, busca cada partido y **escribe en la app la cuota que ves**. La
   app te dice al instante: ✔ apostar $X o ✘ no apostar.
4. Arma ese cupón en Ecuabet y toca **guardar/reservar apuesta**: ese es tu código.
5. En la app, **Ver ticket → Registrar apuestas**. Al día siguiente se liquidan
   solas y ves tu ROI en **Rendimiento**.

## Cómo decide (y por qué el error es bajo)

- **6 fuentes.**
  - El mercado: cuotas sin el margen de la casa.
  - Modelos propios: Dixon-Coles y binomial negativa para córners y tarjetas.
  - penaltyblog: Poisson bivariado, una librería de código abierto muy usada.
  - Forebet.
  - API-Football.
  - IA con Groq.
- **Pesos que aprenden solos.** Cada día se mide el error de cada fuente en cada
  mercado, y la que más se equivoca pierde peso. Lo ves en la pestaña **Fuentes**.
- **Consenso obligatorio.**
  - Opinan al menos 2 fuentes.
  - La diferencia entre ellas es de 8 puntos o menos.
  - 2 de cada 3 ven valor.
  - El valor esperado es de +4% o más.
- **Gestión de banca.**
  - 1/4 de Kelly.
  - Máximo 3% de la banca por pick y 10% por día.
  - Un pick por partido.
- **Backtest con CLV.** Mide si la estrategia consigue mejores cuotas que el cierre
  de Pinnacle, la señal más confiable de una ventaja real.

## Ajustes (`config.yaml`)

| Parámetro | Qué controla |
|---|---|
| `ventaja_minima`, `min_fuentes`, `max_dispersion`, `min_acuerdo` | Qué tan exigente es para dar un pick |
| `mercados_activos` | Qué mercados analizar |
| `peso_roja` | Cómo cuenta Ecuabet una roja en "tarjetas totales" |
| `ligas` | Ligas a analizar (ids con `python main.py ligas`) |
| `max_predicciones_af` | Bájalo si usas el plan gratis de API-Football |

## En tu computadora (opcional)

```bash
pip install -r requirements.txt
export API_FOOTBALL_KEY=... APIFY_TOKEN=... ODDS_API_KEY=...
python main.py verificar
python main.py hoy
python -m http.server -d web 8000     # abre http://localhost:8000
python tests/simulacion.py            # prueba completa con datos simulados
```

## Alternativa: repositorio privado gratis con Cloudflare Pages

Cloudflare → Workers & Pages → Create → Pages → conecta tu repositorio → Build
command: (vacío) → Output directory: `web`. Se actualiza solo con cada commit del
sistema. En ese caso puedes borrar el job `publicar` de los workflows.

## Antes de apostar dinero real

Ningún sistema garantiza ganar. Este busca una ventaja pequeña y repetida. Los
pesos necesitan unas 150 muestras por mercado, y el ROI solo dice algo a partir de
~200 apuestas. Úsalo 2–4 semanas registrando picks con montos mínimos y mira el
backtest y el CLV. Rachas de 8–12 fallos seguidos son normales. Si apuestas para
recuperar pérdidas, para.
