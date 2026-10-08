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
| `ft_news/memoria.py` | memoria del jugador: **un regreso no borra la lesión** (pasa a `EN_SEGUIMIENTO` y se verifica con partidos completos) | listo |
| `ft_news/descubridor.py` | Motor 4 puro: compuertas → cruce dirección × desvío → 🔥 / 🔎 / nada; **con `NEWS_BANDAS_CALIBRADAS=0` nunca 🔥** | listo |
| `ft_news/textos.py` | plantilla fija de Discord; falla si hay `%`, "probabilidad" o "apostar" | listo |
| `ft_news/fuentes.py` | lista blanca con `autorizada=0` y estado de condiciones de uso; compuerta `permitida()` | listo |
| `ft_news/proveedores/tavily.py` | búsqueda de noticias (`topic=news`, `include_domains` = fuentes autorizadas, `days=7`) | listo |
| `ft_news/proveedores/gemini.py` | clasificación y resumen por artículo y jugador, esquema JSON estricto, sin números | listo |
| `ft_news/jugadores.py` | identidad: padrón UTR, unión "Apellido I." ↔ "Nombre Apellido", idiomas por país, cola | listo |
| `ft_news/partidos.py` | radar inverso mínimo: fixtures del BOT (≤ 72 h) con cuotas → partidos + cola | listo |
| `ft_news/radar.py` | radar directo: búsqueda por jugador e idioma, dedupe por URL, clasificación, fecha obligatoria, identidad, revisión | listo |
| `ft_news/evaluador.py` | Motor 4 aplicado a cada partido; una evaluación por partido (se congela al empezar); señales y marca `dicho_discord` | listo |
| `ft_news/contexto.py` | Motor 3 sin IA: carga, viaje, localía, antecedentes, puntos defendidos (estimado) → `news_contexto` y eventos nivel A | listo |
| `ft_news/cierre.py` | Motor 5: resultado desde match_log, retiro → evento, cuota de cierre, "¿mercado hacia la noticia?", R4 de la memoria, marca "¿era interesante?" | listo |
| `ft_news/excel.py` | HISTORICO + RESUMEN (openpyxl), frecuencias observadas | listo |
| `ft_news/lectores/rss.py` | RSS de las fuentes autorizadas, gratis; solo coincidencias con la cola pasan a Gemini | listo |
| `ft_news/lectores/itf_listas.py` | acceptance lists ITF (WD → RETIRO_ABANDONO nivel A); se niega sin autorización | listo (bloqueado por D-ITF) |
| `ft_news/proveedores/claude.py` | segunda lectura (Claude Haiku) de lo fuerte; discrepancia → nivel C; opcional | listo |
| `ft_news/costos.py` | contador diario por proveedor, topes, aviso al 80 % | listo |
| `ft_news/cliente_rankingftr.py` | lectura de `/ft-intel/*` (padrón UTR, fixtures, partidos, calibración) | listo, no se llama con `NEWS_ACTIVO=0` |
| `ft_news/tareas.py` | worker cada 15 min: padrón → partidos → radar → descubridor → costos; apagado no llama a nadie | listo |
| `ft_news/app.py` | API: `/salud`, `/news/estado`, `/news/config`, `/news/fuentes(+/autorizar)`, `/news/senales(+/dicho)`, `/news/hoy`, `/news/revision(+/{id})`, `/news/evaluaciones/{id}/interesante`, `/news/excel`, `/news/costos`, `/news/jugadores/{id}/memoria` | listo |
| `herramientas/calibrar_bandas.py` | informe de calibración contra RankingFTR (HTTP) o un `.db` | listo |

## Variables de Railway

| Variable | Para qué | Default |
|---|---|---|
| `FT_NEWS_DB_PATH` | base propia (volumen `/data`) | `/data/ft_news.db` |
| `FTR_SERVICE_URL`, `FTR_INTERNAL_SECRET` | leer RankingFTR por `/ft-intel/*` | — |
| `FT_NEWS_SECRET` | quién puede leer esta API (RankingFTR para la pestaña, FT Intelligence para señales) | — (sin él solo responde `/salud`) |
| `FT_NEWS_CICLO_SEGUNDOS` | cadencia del worker | 900 |
| `TAVILY_API_KEY`, `GEMINI_API_KEY` | proveedores; sin ellas el radar no corre y lo anota | — |
| `NEWS_ACTIVO` | interruptor general | **1** (08/10: nace encendido) |
| `NEWS_BANDAS_CALIBRADAS` | habilita 🔥; con `NEWS_BANDAS_AUTO=1` (default) la enciende/apaga el motor según el veredicto de RankingFTR cada 6 h | 0 → automático |
| `NEWS_DISCORD_ACTIVO` | si `/news/senales` entrega algo | **1** |
| `NEWS_FUENTES_AUTORIZADAS_INICIALES` | fuentes que nacen autorizadas al sembrar (decisión de Rubén 08/10) | tourtalk, puntodebreak, livetennis.it, ubitennis, tennisactu, atptour.com |
| `NEWS_FUENTES_AUTORIZADAS_SOLO` | solo fuentes `autorizada=1` | 1 |
| `NEWS_MAX_*`, `NEWS_BANDA_*`, `NEWS_NIVEL_MIN_FUEGO`, … | topes y cortes (ver `config.PARAMETROS`) | ver código |

En RankingFTR, para que la pestaña 📰 FT NEWS vea el servicio: `FT_NEWS_URL` y `FT_NEWS_SECRET`.

## Pruebas

```
pip install -r requirements.txt -r requirements-dev.txt
bash tests/correr_todo.sh          # = python -m pytest tests
```

50 pruebas (Motor 3, Motor 5, Excel, RSS, listas ITF, segunda lectura, revisión; calibración automática; fuentes iniciales): recorrido completo con RankingFTR, Tavily y Gemini simulados (formato real de cada API: sin calibrar → 🔎; calibrado → 🔥; segundo ciclo no vuelve a pagar; señal, dicho, hoy; una 🔥 dicha no se degrada; regreso no borra lesión en el recorrido; artículo viejo nace vencido; otro jugador se descarta; identidad dudosa a revisión; sin fecha se descarta; errores de proveedores), bandas (cortes, desvío), memoria (ejemplo de Rubén lesión → regreso → molestias; partidos completos verifican pero no borran; abandono reabre; vencimiento; persistencia), descubridor (18 casos: sin calibrar nunca 🔥; favorito lesionado; mercado ya descontó; **cuota 1,80 y 2,50 sin umbral**; débil sola no; acumulación sí; nivel C no; sin mercado; UTR viejo; identidad dudosa; regreso sin verificar; contradicción; noticia del rival; mercado en movimiento; empezado; topes; nivel mínimo A; textos sin prohibidos), apagado (0 llamadas), fuentes (nacen sin autorizar; no se autoriza sin `REVISADO_OK`), API.

## Qué queda detrás de una decisión

Listas oficiales ITF (`lectores/itf_listas.py`) y cuadros UTR PTT: escritos/gated, se activan autorizando la fuente (D-ITF / D-UTRPTT).
