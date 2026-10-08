# 📰 FT NEWS INTELLIGENCE — Un solo despliegue (08/10/2026)

Después de desplegar y poner las variables, **todo arranca solo**: fuentes de hoy autorizadas, motor encendido, calibración automática contra RankingFTR cada 6 h (habilita los 🔥 cuando dé `CALIBRADAS_OK`), señales a Discord encendidas. No hay que tocar ningún botón; la pestaña 📰 FT NEWS queda para mirar y, si hace falta, apagar.

## 1. Desplegar los cuatro servicios

| Servicio | ZIP | Qué cambia |
|---|---|---|
| **FT_NEWS** (nuevo) | `FT_NEWS-20261008-v1.zip` | servicio Railway nuevo, con volumen en `/data` |
| RankingFTR v25 | `RankingFTR-20261008-ft-news-v25(.zip / -solo-editados.zip)` | pestaña 📰 FT NEWS, 2 lecturas `/ft-intel/*`, 3 tipos en Admin → Discord |
| FT Intelligence v14 | `FT_INTELLIGENCE-20261008-news-v14.zip` | feed `news` (recoge las señales de FT_NEWS cada 60 s) |
| FT Discord v9 | `FT_DISCORD-20261008-news-v9.zip` | tipos `NEWS_VALOR` (suena de fábrica), `NEWS_INTERESANTE`, `NEWS_NOTICIA` |

## 2. Variables de Railway (lo único manual)

**FT_NEWS** (crear el servicio con un volumen montado en `/data`):

```
FT_NEWS_DB_PATH=/data/ft_news.db
FTR_SERVICE_URL=https://<rankingftr>          # el mismo que usa FT Intelligence
FTR_INTERNAL_SECRET=<el mismo secreto interno de RankingFTR>
FT_NEWS_SECRET=<inventar uno largo>            # quién puede leer la API de FT_NEWS
TAVILY_API_KEY=tvly-dev-...                    # la clave de la pantalla de Tavily
GEMINI_API_KEY=...                             # AI Studio
ANTHROPIC_API_KEY=...                          # OPCIONAL: segunda lectura (Claude Haiku) de lo que aspira a 🔥
```

Nada más: `NEWS_ACTIVO`, `NEWS_DISCORD_ACTIVO` y `NEWS_BANDAS_AUTO` ya valen 1 por defecto; `NEWS_MAX_USD_MES` = 100; `NEWS_MAX_BUSQUEDAS_DIA` = 120.

**RankingFTR** (agregar): `FT_NEWS_URL=https://<ft-news>` y `FT_NEWS_SECRET=<el mismo>`.

**FT Intelligence** (agregar): `FT_NEWS_URL` y `FT_NEWS_SECRET` (los mismos).

**FT Discord**: nada, salvo que tengan `FT_DISCORD_TIPOS_TEXTO` / `FT_DISCORD_TIPOS_VOZ` puestas a mano: agregarles `NEWS_VALOR` o borrarlas.

## 3. Qué pasa solo en los primeros 15 minutos

1. FT_NEWS siembra la lista blanca con **estas fuentes ya autorizadas** (decisión de ustedes, registrada con fecha y "ruben"): `tennistourtalk.com`, `puntodebreak.com`, `livetennis.it`, `ubitennis.com`, `tennisactu.net`, `atptour.com`. ITF oficial, UTR PTT, Flashscore, Sofascore y TennisExplorer quedan **no autorizadas** (FUENTES-AUTORIZACION.md). Si quieren otra lista, variable `NEWS_FUENTES_AUTORIZADAS_INICIALES` antes del primer arranque; después manda la pestaña.
2. Copia el padrón UTR y los fixtures de ≤ 72 h de RankingFTR; sus jugadores entran a la cola.
3. Pide la **calibración de bandas** a RankingFTR (`/ft-intel/news/calibracion`, sobre `utr_value_registro`). `CALIBRADAS_OK` → `NEWS_BANDAS_CALIBRADAS=1` solo y pueden salir 🔥. `NO_CALIBRADAS` → todo se investiga y se muestra como 🔎 en la pestaña, sin 🔥, y se vuelve a intentar cada 6 h. El veredicto y sus razones se ven en la pestaña ("Calibración automática").
4. Radar: Tavily (1 consulta por idioma: inglés, español y el local del país) solo sobre las fuentes autorizadas; Gemini clasifica; con `ANTHROPIC_API_KEY`, Claude Haiku relee lo que aspira a 🔥 y, si discrepa, lo baja a nivel C. Cada hora, además, se leen gratis los RSS de las fuentes autorizadas (TourTalk, Puntodebreak, LiveTennis.it, Ubitennis, ATP) y solo lo que nombra a un jugador de la cola pasa a Gemini.
4b. Motor 3 (cada hora, sin IA): carga de partidos y sets, viajes entre países, localía, antecedentes en el torneo y puntos defendidos (snapshot semanal de Defensa de Puntos, marcado "estimado"); cuando cruzan un umbral entran como eventos nivel A de dato propio.
4c. Motor 5: 3 h después de cada partido evaluado se busca el resultado en match_log: ganador, retiro (entra como evento nivel A), cuota de cierre, "¿se movió el mercado hacia la noticia?"; un partido completo va verificando el estado físico tras un regreso.
5. Cada 🔥 nueva viaja FT_NEWS → FT Intelligence → FT Discord en el acto, con texto y voz. Se gobierna en Admin → Discord, grupo "FT NEWS".

## 4. Qué mirar en la pestaña 📰 FT NEWS (admin)

- "Servicio FT_NEWS": motor, bandas, Discord, fuentes autorizadas, calibración automática (veredicto, muestra, razones) y el gasto.
- "Hoy · partidos evaluados": cada partido con 🔥/🔎, bandas UTR y mercado, nivel, motivo y si ya se dijo en Discord.
- "Noticias recientes": lo que el radar guardó, con fecha, fuente y enlace.
- "Revisión pendiente": lo que el clasificador puso en `OTRA` o no está seguro de qué jugador es; reclasificar / es este jugador / confirmar / descartar.
- Columna "¿Era interesante?" en cada 🔥: sí / no / mercado lo sabía (la métrica del diseño §8) y **📥 Excel HISTORICO + RESUMEN**.
- "Fuentes y autorización": autorizar o quitar fuentes (al autorizar confirman que revisaron las condiciones de uso).
- Interruptores (admin): apagar motor / bandas / Discord en un clic si algo no gusta.

Presupuesto: tope diario 120 búsquedas (≈ 3.600/mes; Researcher trae 1.500 y el resto a ~US$ 0,008 → ≤ US$ 17/mes), Gemini Flash centavos por día, tope duro US$ 100/mes; al 100 % el radar duerme y lo escribe en la pestaña.

## 5. Lo único que queda detrás de una decisión

El lector de acceptance lists de la ITF (`ft_news/lectores/itf_listas.py`) está escrito y probado, pero se niega a leer mientras `itftennis.com` no esté autorizada (D-ITF, FUENTES-AUTORIZACION.md). Lo mismo para UTR PTT. El día que lo decidan, es autorizar la fuente en la pestaña.
