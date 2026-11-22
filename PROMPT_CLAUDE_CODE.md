# Prompt para pegar en Claude Code

Primero descomprime el zip y abre la carpeta `apuestas` en Claude Code (en una
terminal: `cd apuestas` y luego `claude`). Después copia y pega todo lo que está
entre las líneas.

---

Hola. En esta carpeta está mi sistema "Picks Ecuabet": analiza partidos de fútbol
de Europa, Norteamérica y Sudamérica, de hoy a +5 días, y me da picks para apostar
en Ecuabet (Ecuador) en tres niveles: Seguras, Valor y Grandes (combinadas para
ganar $50–$1000 con poco dinero). Se usa desde una app web instalable en el celular.
Lee primero CLAUDE.md y README.md: ahí está toda la arquitectura y las reglas.

Quiero que lo pongas en marcha conmigo, paso a paso:

1. Revisa el proyecto, instala las dependencias (`pip install -r requirements.txt`) y
   corre `python tests/simulacion.py`. Debe terminar sin errores. Si algo falla, arréglalo.
2. Crea un repositorio PÚBLICO en mi GitHub llamado `picks-ecuabet` y sube todo. Si
   tengo `gh` instalado y con sesión iniciada, hazlo tú; si no, guíame.
3. Activa GitHub Pages con "Source: GitHub Actions" y en Actions → General marca
   "Workflow permissions: Read and write".
4. Dime exactamente qué secrets debo agregar y dónde: API_FOOTBALL_KEY (obligatoria),
   GROQ_API_KEY, APIFY_TOKEN, ODDS_API_KEY, TELEGRAM_TOKEN y TELEGRAM_CHAT_ID, y la
   variable BANCA. Las claves las pongo yo; no me las pidas en el chat.
5. Cuando te avise que ya puse las claves, corre el workflow "Verificar puesta en
   marcha" (`gh workflow run verificar.yml`) y corrige lo que salga con ✘. Por
   ejemplo, ids de ligas mal puestos en config.yaml: usa `python main.py ligas`.
6. Corre "Picks diarios" y "Backtest semanal" y pásame el enlace de mi página
   (https://MI-USUARIO.github.io/picks-ecuabet/). Ponlo también en `url_web` de config.yaml.
7. Explícame cómo instalar la app en mi celular y cómo crear el token de GitHub
   (fine-grained, solo este repo, Actions: Read and write) para registrar apuestas
   desde la app.

Reglas:
- Háblame siempre en español y en pasos cortos.
- Nunca coloques apuestas reales ni me pidas contraseñas.
- No hagas scraping masivo de Forebet ni de Ecuabet. Usa las APIs configuradas.
- Antes de dar por terminado un cambio, corre `python tests/simulacion.py`.

---

## Prompts útiles para después

- "Muéstrame los picks de hoy y de mañana desde web/data/hoy.json, ordenados por probabilidad."
- "Agrega la liga X: busca su id en API-Football con `python main.py ligas` y ponla en config.yaml."
- "Cambia la banca a $200 y el valor mínimo a 3%."
- "Corre `python tests/ultimos30.py` y explícame cómo le fue al sistema en los últimos 30 días."
- "Quiero que las combinadas tengan como máximo 5 selecciones."
