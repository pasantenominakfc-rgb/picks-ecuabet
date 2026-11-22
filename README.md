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
| `API_FOOTBALL_KEY` (**obligatoria**) | <https://dashboard.api-football.com> → regístrate → copia tu API key | Gratis (100 consultas/día, 10/min): es el perfil activo. Pro (USD 19/mes) permite el perfil completo |
| `APIFY_TOKEN` (Forebet) | <https://console.apify.com> → Settings → API & Integrations | ~USD 0.10 por 1 000 partidos (el crédito gratis mensual alcanza) |
| `ODDS_API_KEY` (Pinnacle/Betfair) | <https://the-odds-api.com> | Gratis (500 créditos/mes) |
| `GROQ_API_KEY` (IA que revisa noticias) | <https://console.groq.com> → API Keys | Gratis con límites |
| `DB_KEY` (**obligatoria**) | La inventas tú: ver **Cifrado de la base** | Gratis |
| `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` | Escribe a **@BotFather** → `/newbot` para el token. Luego escríbele a tu bot y a **@userinfobot** para tu chat id | Gratis |

### 2. Crea el repositorio en GitHub

1. Entra a <https://github.com/new>, ponle un nombre (p. ej. `picks-ecuabet`) y créalo.
2. Sube todo el contenido de esta carpeta: **Add file → Upload files** (arrastra
   todo, incluida la carpeta `.github`) → **Commit**.

> **¿Público o privado?** GitHub Pages es gratis en repositorios públicos. En uno
> privado necesitas GitHub Pro (USD 4/mes). Con el repo público, cualquiera puede ver
> tus picks y tu historial en **unidades** (`u`), pero la banca, los montos y las ganancias
> en dólares no se publican: la banca vive solo en tu navegador. **La base de datos no está en
> `main`: vive CIFRADA (`sistema.db.enc`) en la rama `datos`** (se crea sola en la primera ejecución).
> Sin la clave `DB_KEY` esa rama no revela tus montos: lee la sección **Cifrado de la base**.
> Alternativa gratis con repositorio privado: Cloudflare Pages (ver al final).

### 3. Configura

En tu repositorio:

1. **Settings → Secrets and variables → Actions → New repository secret:** agrega
   cada clave del paso 1 con su nombre exacto.
2. (Opcional) En la pestaña **Variables**, agrega `BANCA` con tu banca (por ejemplo `100`):
   solo se usa para el mensaje de Telegram. En la web la banca se escribe en **Ajustes** y se guarda en tu teléfono.
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

### Cifrado de la base

La base SQLite tiene tus apuestas, montos y ganancias reales. El repo es público, así que **nunca se
sube en claro**: los workflows la guardan cifrada (AES-256-CBC, PBKDF2 con 200 000 iteraciones y sal
aleatoria) como `sistema.db.enc` en la rama `datos`. Al empezar cada job la descifran con `DB_KEY`; al
terminar la cifran de nuevo y solo suben `sistema.db.enc` y `web_data/` (los JSON públicos, sin dólares).
`DB_KEY` se pasa solo por variable de entorno en esos pasos. Si falta, el job **falla** con un mensaje
en español en vez de subir algo en claro.

1. **Crea una `DB_KEY` larga y aleatoria** (30 caracteres o más), por ejemplo con
   `openssl rand -base64 32`.
2. **Guárdala como secret:** Settings → Secrets and variables → Actions → New repository secret, con el
   nombre exacto `DB_KEY`. Guárdala también en tu gestor de contraseñas.
3. **Aviso importante:** si pierdes `DB_KEY` **pierdes el historial** (no hay forma de recuperarlo), y si
   la cambias, los workflows no podrán descifrar la base anterior. Para empezar de cero borra la rama
   `datos` y deja que se recree.

**Si la rama `datos` se publicó alguna vez sin cifrar** (versiones anteriores guardaban `sistema.db`),
el historial de git sigue teniendo los montos aunque la borres del último commit. Hay que **borrar la
rama y recrearla** (Settings → Branches, o `git push origin --delete datos`) antes de usar `DB_KEY`.
Los workflows se niegan a continuar si encuentran un `sistema.db` en claro en la rama. Además, la rama
`datos` trae un `.gitignore` con `*.db` para que una base en claro no se suba por accidente.
---

## Ligas y fechas

- **Perfil activo (plan gratis): 11 ligas** (LigaPro, Champions, Europa League, Premier, LaLiga, Serie A,
  Bundesliga, Ligue 1, Libertadores, Sudamericana, MLS), hoy +2 días, `max_predicciones_af: 10`. Si la cuota
  diaria de la API se agota, la web muestra un aviso. El perfil completo está documentado como `perfil_pro`
  en `config.yaml` (hay que cambiar a mano los valores indicados y pasar `ligas_extra` a `ligas`).
- **Más de 40 ligas disponibles (perfil pro):**
  - Europa: las 5 grandes y sus segundas divisiones, Países Bajos, Portugal, Bélgica, Turquía, Escocia, Grecia, Austria, Suiza, Dinamarca, Noruega, Suecia, Polonia, Champions, Europa League y Conference.
  - Norte y Centroamérica: MLS, Liga MX y Concacaf.
  - Sudamérica: LigaPro, Brasil A y B, Argentina, Colombia, Chile, Perú, Uruguay, Paraguay, Bolivia, Venezuela, Libertadores y Sudamericana.
- **Modo "todas las ligas"** (perfil pro, `incluir_todas_las_ligas: true`): además de la lista, analiza cualquier liga de Europa, Norteamérica y Sudamérica que tenga partidos esas fechas.
- **Fechas:** el perfil gratis analiza hoy +2 días (`dias_adelante: 2`); el pro, hasta +5. En la app eliges el día y filtras por región y por liga.
- Con tantas ligas se usan muchas consultas: el plan **Pro de API-Football** (USD 19/mes, 7 500 consultas/día) es lo recomendado.

## Los tres niveles de la app

| Nivel | Qué es | Cuánto |
|---|---|---|
| ✅ **Seguras** | Simples con probabilidad ≥ 72% y cuota 1.25–1.60. La cuota es la **estimada de Ecuabet** (justa × 0.94) hasta que anotes la real | 2% de la banca |
| 💎 **Valor** | La cuota paga más de lo que vale. Exige consenso de ≥ 2 fuentes | Kelly 1/4, tope 3% por pick y 10% por día |
| 🚀 **Grandes** | Combinadas con objetivo de cobro de $100, $200 o $500 (`grandes_objetivos`, con `grandes_monto` de $5). Se muestra la ganancia neta y el cobro total | Lo que quieras arriesgar |

Los resultados de los mercados de resultado se liquidan a los **90 minutos** (sin prórroga).

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

Resultado del 23/10 al 21/11/2026 (154 partidos; son cifras de `tests/ultimos30.py` con cuotas de
Bet365/Betfair, **no** de apuestas reales en el tracker):
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
5. En la app, **Ver ticket → Registrar apuestas** (se envía un solo lote). Al día siguiente se liquidan
   solas. El **ROI real** de **Rendimiento** cuenta solo las apuestas que tú registraste; el ROI del
   backtest es teórico y no garantiza nada.

## Cómo decide (y por qué el error es bajo)

- **5 fuentes + IA.** (La IA ajusta la probabilidad pero no cuenta como fuente para el consenso.)
  - El mercado: cuotas sin el margen de la casa.
  - Modelos propios: Dixon-Coles y binomial negativa para córners y tarjetas.
  - penaltyblog: Poisson bivariado, una librería de código abierto muy usada.
  - Forebet.
  - API-Football.
  - IA con Groq.
- **Pesos que aprenden solos.** Cada día se mide el error de cada fuente en cada
  mercado, y la que más se equivoca pierde peso. Lo ves en la pestaña **Fuentes**.
- **Consenso obligatorio (solo en Valor).**
  - Opinan al menos 2 fuentes (la IA no cuenta).
  - La diferencia entre ellas es de 8 puntos o menos.
  - 2 de cada 3 ven valor.
  - El valor esperado es de +4% o más.
- **Gestión de banca.**
  - 1/4 de Kelly.
  - Máximo 3% de la banca por pick y 10% por día.
  - Un pick por partido.
- **Backtest con CLV.** Mide si la estrategia consigue mejores cuotas que el cierre
  de Pinnacle, la señal más confiable de una ventaja real.

## Cómo funcionan los workflows (y sus límites)

- **`diario`** (07:00 y 13:00) y **`backtest`** (domingos) comparten el grupo de concurrencia `picks-datos`.
  **`registrar`** tiene su propio grupo (`picks-registrar`) para no esperar a un job largo. Como los tres escriben
  la rama `datos`, el paso "descifrar → aplicar → cifrar → push" se reintenta hasta 3 veces: si el push choca,
  se baja la versión remota, se descifra y se reaplica el cambio (registrar vuelve a aplicar el lote; diario y
  backtest traen las apuestas registradas mientras corrían). Último recurso: `--force-with-lease` con el SHA inicial.
- **La app espera al workflow.** Un `204` de la API de GitHub solo significa que el run quedó **encolado**, no
  que tu apuesta se guardó. Si hay otro registro en curso, GitHub conserva solo 1 pendiente por grupo: por eso
  la app manda un único lote. Comprueba en **Pendientes** que quedó registrada.
- **Lote parcial:** si algunos ítems del lote son inválidos, los válidos igual quedan guardados y publicados;
  el run termina en rojo para que lo notes.
- **Sin datos:** si `main.py hoy` no encuentra partidos (cuota de API agotada, fuentes caídas), el run no se pone
  en rojo pero emite un aviso amarillo "Sin datos hoy" y conserva lo ya publicado.
- **`web/data/*.json` no se versiona en `main`**: se generan en cada corrida y viven en `web_data/` de la rama `datos`.
  Los JSON de ejemplo que hubiera en el historial de `main` (`hoy.json`, `simulacion30.json`, con banca/montos de
  EJEMPLO) siguen en el historial de git; reescribirlo es decisión tuya.
- Las actions siguen por etiqueta (`@v4`…); conviene fijarlas por SHA (ver los `TODO` de cada workflow).

## Ajustes (`config.yaml`)

| Parámetro | Qué controla |
|---|---|
| `ventaja_minima`, `min_fuentes`, `max_dispersion`, `min_acuerdo` | Qué tan exigente es para dar un pick |
| `mercados_activos` | Qué mercados analizar |
| `peso_roja` | Cómo cuenta Ecuabet una roja en "tarjetas totales" |
| `ligas` | Ligas a analizar (ids con `python main.py ligas`) |
| `perfil`, `af_plan`, `af_max_por_minuto`, `dias_adelante` | Perfil gratis (activo) o pro |
| `max_predicciones_af` | Consultas /predictions por día (10 en el plan gratis) |

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
