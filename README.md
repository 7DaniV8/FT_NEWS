# 📰 FT NEWS INTELLIGENCE — servicio `FT_NEWS` (Fase 0, 08/10/2026)

Investigador autónomo de tenis para FullTenis: **primero la noticia, después el partido**, y UTR + cuotas solo para comprobar. Sin FTR ni Elo. Servicio independiente en Railway; no toca ningún motor existente.

Diseño aprobado: *FT NEWS INTELLIGENCE — Diseño definitivo (v2)* (documento del 08/10/2026). Esta versión (v1, Fases 1–3) tiene el flujo completo: padrón y fixtures desde RankingFTR → cola de vigilancia → búsqueda (Tavily, solo fuentes autorizadas) → clasificación (Gemini Flash, JSON estricto) → memoria del jugador → descubridor → 🔥/🔎 en la pestaña y a Discord vía FT Intelligence. Puesta en marcha: `DESPLIEGUE-HOY.md`. Fuentes: `FUENTES-AUTORIZACION.md`. Calibración: `INFORME-CALIBRACION.md`.

## Lo que hay

| Módulo | Qué hace | Estado |
|---|---|---|
| `ft_news/config.py` | parámetros con default (todo apagado) + tabla `news_config` que los pisa | listo |
| `ft_news/db.py` | tablas `news_*` (jugador, cola, fuente, búsqueda, artículo, evento, torneo, partido, contexto, evaluación, resultado, revisión, costos) con escritura con reintento | listo |
| `ft_news/taxonomia.py` | taxonomía abierta de eventos (18 categorías + `OTRA`), dirección, naturaleza, nivel A/B/C | listo |
| `ft_news/bandas.py` | bandas de expectativa UTR y mercado, desvío; sin probabilidades | listo, **sin calibrar** |
| `ft_news/memoria.py` | memoria del jugador: **un regreso no borra la lesión** (pasa a `EN_SEGUIMIENTO` y se verifica con partidos completos); v5: `origen` EXTERNO/INTERNO, historial de cambios (`news_evento_historial`), vencimiento persistido, DESMENTIDO | listo |
| `ft_news/descubridor.py` | Motor 4 puro: compuertas → cruce dirección × desvío → 🔥 / 🔎 / nada; **🔥 exige una noticia EXTERNA fuerte**; con `NEWS_BANDAS_CALIBRADAS=0` sale como 🔥 **EXPERIMENTAL** (v5, nunca "validada") | listo |
| `ft_news/alertas.py` | **v5**: qué va a Discord y por qué — 📰 NOTICIA IMPORTANTE (sin partido), 🔎 PARTIDO INTERESANTE (los dos investigados), 🔥 validada / experimental; dedupe (no repetir salvo info nueva), topes diarios, motivo de selección y evidencia (`news_alerta`). **v5.1**: `justificar()` — qué podría no estar en la cuota / en contra / por qué merece la alerta; sin justificación suficiente la 🔥 queda como 🔎; **v5.2**: la 🔥 exige una cuota **confirmada después de la noticia** que no se haya movido; sin ella, 🔎 "pendiente de actualización"; `frescura()` de la investigación de los dos (solo cuentan búsquedas recientes, no eventos vigentes); `vencer_pendientes()` | listo |
| `ft_news/cobertura.py` | **v5.1**: cobertura real por circuito (en cola, investigados, nunca buscados, búsquedas, artículos, noticias útiles, partidos analizados, alertas) y presupuesto necesario vs tope, con propuesta | listo |
| `ft_news/textos.py` | plantillas fijas de Discord (**v6, formatos definitivos de Rubén**: cortas, favorecido en MAYÚSCULAS con su cuota, sin enlaces); falla si hay `%`, "probabilidad", "apostar" o un enlace | listo |
| `ft_news/fuentes.py` | lista blanca con `autorizada=0` y estado de condiciones de uso; compuerta `permitida()` | listo |
| `ft_news/proveedores/tavily.py` | búsqueda de noticias (`topic=news`, `include_domains` = fuentes autorizadas, `days=7`) | listo |
| `ft_news/proveedores/gemini.py` | clasificación y resumen por artículo y jugador, esquema JSON estricto, sin números | listo |
| `ft_news/jugadores.py` | identidad: padrón UTR, unión "Apellido I." ↔ "Nombre Apellido", idiomas por país, cola | listo |
| `ft_news/partidos.py` | radar inverso mínimo: fixtures del BOT (≤ 72 h) con cuotas → partidos + cola; v5: funde el mismo encuentro de varios proveedores (`news_partido_fuente`); **v5.1**: cada observación de cuota con proveedor, hora y precio (`news_cuota_obs`); la vigente es la más reciente; **v5.2**: `hasta_en` (hasta cuándo se vio ese precio) y `cuota_antes_y_despues()` de una noticia | listo |
| `ft_news/radar.py` | radar directo: cola por score con **cupo para challenger/ITF/UTR**, búsqueda por jugador e idioma, dedupe por URL, clasificación, resultado por artículo (`news_articulo.resultado/motivo`), 📰 al encontrar, rival a demanda; **radar temático** (por tema, cruzado contra todo el padrón); **v5.1**: `reintentar_pendientes()` — un artículo cuya clasificación falló (IA caída, 5xx, JSON roto) no se pierde: queda PENDIENTE/ERROR con reintentos escalonados (4) y al agotarse va a revisión | listo |
| `ft_news/evaluador.py` | Motor 4 aplicado a cada partido; una evaluación por partido (se congela al empezar); señales y marca `dicho_discord` | listo |
| `ft_news/contexto.py` | Motor 3 sin IA: carga, viaje, localía, antecedentes, puntos defendidos (estimado) → `news_contexto` y eventos nivel A. **v7**: la carga se **clasifica** (NORMAL / CONSIDERABLE / EXCEPCIONAL / INACTIVIDAD / SIN_DATOS, umbrales provisorios en config): una semana normal no deja evento; CONSIDERABLE deja un evento mixto (seguimiento, se investiga); EXCEPCIONAL uno negativo; **un solo evento vigente por jugador y categoría** (los duplicados vencen); la inactividad se informa, no premia ni castiga | listo |
| `ft_news/explicar.py` | **v7**: todo FT NEWS en palabras simples — lectura de cada evaluación (🎾 / 🏆 / 📊 / 💰 / ⚖️ NIVEL / 🚨 NOTICIA / 🔴 / 🟢 / 🟡 CARGA FÍSICA / 🧭 CONCLUSIÓN), motivos del motor → frases, categorías y eventos en español, "por qué se seleccionó" de cada alerta. Los códigos siguen guardados para el admin | listo |
| `ft_news/diagnostico_carga.py` | **v7**: diagnóstico de las reglas de carga: qué marcaba la regla anterior, cuántas evaluaciones salieron solo de estadística interna, duplicados, resultados del "cargado", distribución de partidos/sets/games/descanso y cómo caería cada muestra con los umbrales de hoy (`/news/diagnostico` → `carga`) | listo |
| `ft_news/cierre.py` | Motor 5: resultado desde match_log, retiro → evento, cuota de cierre, "¿mercado hacia la noticia?", R4 de la memoria, marca "¿era interesante?" | listo |
| `ft_news/excel.py` | HISTORICO + RESUMEN (openpyxl), frecuencias observadas | listo |
| `ft_news/lectores/rss.py` | RSS de las fuentes autorizadas, gratis; coincidencias con **todo el padrón** (v5) pasan al clasificador | listo |
| `ft_news/lectores/itf_listas.py` | acceptance lists ITF (WD → RETIRO_ABANDONO nivel A); se niega sin autorización | listo (bloqueado por D-ITF) |
| `ft_news/proveedores/claude.py` | segunda lectura (Claude Haiku) de lo fuerte; discrepancia → nivel C; opcional | listo |
| `ft_news/costos.py` | contador diario por proveedor, topes, aviso al 80 % | listo |
| `ft_news/cliente_rankingftr.py` | lectura de `/ft-intel/*` (padrón UTR, fixtures, partidos, calibración) | listo, no se llama con `NEWS_ACTIVO=0` |
| `ft_news/tareas.py` | worker cada 15 min: padrón → calibración → partidos (+ fusión de duplicados una vez) → vencimientos → contexto → radar → temático (cada 6 h) → RSS → descubridor → cierre → costos; apagado no llama a nadie | listo |
| `ft_news/app.py` | API: `/salud`, `/news/estado`, `/news/config`, `/news/fuentes(+/autorizar)`, `/news/senales(+/dicho)`, `/news/hoy`, `/news/revision(+/{id})`, `/news/evaluaciones/{id}/interesante`, `/news/excel`, `/news/costos`, `/news/jugadores/{id}/memoria`; v5: `/news/alertas`, `/news/diagnostico`, `/news/jugadores/buscar?q=`; v6.1: `/news/evaluaciones/{id}`; **v7**: cada evaluación, evento y alerta viaja con su `lectura` / `texto_simple` / `motivo_simple` | listo |
| `herramientas/calibrar_bandas.py` | informe de calibración contra RankingFTR (HTTP) o un `.db` | listo |

## Variables de Railway

| Variable | Para qué | Default |
|---|---|---|
| `FT_NEWS_DB_PATH` | base propia (volumen `/data`) | `/data/ft_news.db` |
| `FTR_SERVICE_URL`, `FTR_INTERNAL_SECRET` | leer RankingFTR por `/ft-intel/*` | — |
| `FT_NEWS_SECRET` | quién puede leer esta API (RankingFTR para la pestaña, FT Intelligence para señales) | — (sin él solo responde `/salud`) |
| `FT_NEWS_CICLO_SEGUNDOS` | cadencia del worker | 900 |
| `TAVILY_API_KEY` | búsqueda; sin ella el radar no corre y lo anota | — |
| `GEMINI_API_KEY` y/o `ANTHROPIC_API_KEY` | clasificador (Gemini Flash o Claude Haiku). Con una alcanza. `NEWS_CLASIFICADOR` = auto (Gemini si hay; si no o si falla, Claude) / gemini / claude. El otro, si existe, hace la segunda lectura de lo que aspira a 🔥 | — |
| `GEMINI_MODELO`, `CLAUDE_MODELO` | modelo a usar; ante un 404 se prueban alternativos y queda en `/news/estado` (`clasificador`) | gemini-2.5-flash / claude-haiku-5-5 |
| `NEWS_ACTIVO` | interruptor general | **1** (08/10: nace encendido) |
| `NEWS_BANDAS_CALIBRADAS` | habilita la 🔥 **validada**; con `NEWS_BANDAS_AUTO=1` la enciende/apaga el motor según el veredicto de RankingFTR cada 6 h (v5: default 0 — Rubén: "no activar 🔥 automáticamente por cantidad de partidos") | 0 |
| `NEWS_DISCORD_ACTIVO` | si `/news/senales` entrega algo. **v6: nace en 1** (Rubén 09/10 23:13: las tres alertas activas); Admin → FT NEWS lo apaga en un clic. `NEWS_SENAL_MAX_HORAS` (12): lo pendiente más viejo vence | **1** |
| `NEWS_EXP_MIN_PUNTOS`, `NEWS_EXP_MOV_CUOTA_PCT` | v5.1: balance mínimo de la justificación para que una 🔥 experimental salga (si no, 🔎); movimiento de cuota que cuenta como "el mercado ya se movió" | 2 / 3.0 |
| `NEWS_DISCORD_NOTICIA`, `NEWS_DISCORD_INTERESANTE`, `NEWS_EXPERIMENTAL_ACTIVO` | v5: 📰, 🔎 y 🔥 experimental a Discord | 1 / 1 / 1 |
| `NEWS_MAX_NOTICIA_DIA`, `NEWS_MAX_INTERESANTE_DIA`, `NEWS_ALERTA_REPETIR_DIAS`, `NEWS_NOTICIA_MAX_DIAS` | topes y dedupe de alertas | 8 / 6 / 7 / 7 |
| `NEWS_RADAR_TEMATICO_ACTIVO`, `NEWS_RADAR_TEMATICO_BUSQUEDAS`, `NEWS_RADAR_TEMATICO_CADA_H` | radar por tema (lesión, retiro, enfermedad, regreso) contra todo el padrón | 1 / 12 / 6 |
| `NEWS_RADAR_CUPO_MENORES_PCT`, `NEWS_RIVAL_HORAS` | cupo de la cola para challenger/ITF/UTR; rival a demanda si no fue investigado en N h | 40 / 48 |
| `NEWS_MAX_BUSQUEDAS_DIA` | tope diario de Tavily (v5: 120 → **250**) | 250 |
| `NEWS_FUENTES_AUTORIZADAS_INICIALES` | fuentes que nacen autorizadas al sembrar (decisión de Rubén 08/10) | tourtalk, puntodebreak, livetennis.it, ubitennis, tennisactu, atptour.com |
| `NEWS_FUENTES_AUTORIZADAS_SOLO` | solo fuentes `autorizada=1` | 1 |
| `NEWS_MAX_*`, `NEWS_BANDA_*`, `NEWS_NIVEL_MIN_FUEGO`, … | topes y cortes (ver `config.PARAMETROS`) | ver código |

En RankingFTR, para que la pestaña 📰 FT NEWS vea el servicio: `FT_NEWS_URL` y `FT_NEWS_SECRET`.

## Pruebas

```
pip install -r requirements.txt -r requirements-dev.txt
bash tests/correr_todo.sh          # = python -m pytest tests (+ recorrido Discord si FT_INTELLIGENCE y FT_DISCORD están al lado)
FT_INTELLIGENCE_REPO=../FT_INTELLIGENCE FT_DISCORD_REPO=../FT_DISCORD python herramientas/recorrido_discord.py --salida EJEMPLOS-ALERTAS.md
FT_NEWS_URL=… FT_NEWS_SECRET=… FTR_SERVICE_URL=… FTR_INTERNAL_SECRET=… FT_INTEL_URL=… python herramientas/verificar_real.py   # en producción
```

88 pruebas (v6: formatos definitivos de Discord en todas las pruebas de texto; v5.2: sin cuota confirmada después de la noticia → 🔎 pendiente; con cuota igual → 🔥; v5.1: justificación de la 🔥 experimental y degradación a 🔎; cuota que ya se movió; rival sin investigación reciente; dos proveedores con cuotas distintas; encuentros distintos entre los mismos jugadores; fusión conserva observaciones; reintentos de clasificación (IA caída, agotados, proveedor fatal); cobertura por circuito y presupuesto; retiro del mismo torneo; alertas vencidas; claves fuera de logs; **recorrido FT NEWS → FT Intelligence → FT Discord con el código real de los tres** (`tests/test_recorrido_discord.py`, con `FT_INTELLIGENCE_REPO` y `FT_DISCORD_REPO`); v5: alertas 📰/🔎/🔥exp con motivo, dedupe, topes; cola con cupo; radar temático y RSS contra el padrón; historial, vencimiento, desmentido; fusión de duplicados; endpoints nuevos; además Motor 3, Motor 5, Excel, RSS, listas ITF, segunda lectura, revisión; calibración automática; fuentes iniciales): recorrido completo con RankingFTR, Tavily y Gemini simulados (formato real de cada API: sin calibrar → 🔎; calibrado → 🔥; segundo ciclo no vuelve a pagar; señal, dicho, hoy; una 🔥 dicha no se degrada; regreso no borra lesión en el recorrido; artículo viejo nace vencido; otro jugador se descarta; identidad dudosa a revisión; sin fecha se descarta; errores de proveedores), bandas (cortes, desvío), memoria (ejemplo de Rubén lesión → regreso → molestias; partidos completos verifican pero no borran; abandono reabre; vencimiento; persistencia), descubridor (18 casos: sin calibrar nunca 🔥; favorito lesionado; mercado ya descontó; **cuota 1,80 y 2,50 sin umbral**; débil sola no; acumulación sí; nivel C no; sin mercado; UTR viejo; identidad dudosa; regreso sin verificar; contradicción; noticia del rival; mercado en movimiento; empezado; topes; nivel mínimo A; textos sin prohibidos), apagado (0 llamadas), fuentes (nacen sin autorizar; no se autoriza sin `REVISADO_OK`), API.

## Qué queda detrás de una decisión

Listas oficiales ITF (`lectores/itf_listas.py`) y cuadros UTR PTT: escritos/gated, se activan autorizando la fuente (D-ITF / D-UTRPTT).
