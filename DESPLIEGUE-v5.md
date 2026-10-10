# 📰 FT NEWS v6 — Despliegue, contratos, variables y migraciones (10/10/2026)

Complementa `DESPLIEGUE-HOY.md` (08/10, primer despliegue). Esto es lo que
cambia al subir v6 + FT_INTELLIGENCE v18 + RankingFTR v38 + **FT Discord v11**.

## 1. Versiones que van juntas y qué habla con qué

| Servicio | Versión | Habla con | Contrato probado por |
|---|---|---|---|
| FT_NEWS | `ft-news-v6-20261010` | lee RankingFTR `/ft-intel/utr/padron`, `/fixtures`, `/historial`, `/antecedentes`, `/defensa`, `/news/calibracion` | `tests/test_recorrido_fase1.py` (RankingFTR simulado con el formato real) |
| FT Intelligence | v18 (`news.py` v2) | lee FT_NEWS `GET /news/senales`, escribe `POST /news/senales/dicho` | **`tests/test_contrato_ft_news.py`** (app real de FT_NEWS) · 7 OK |
| FT Intelligence | v18 | lee RankingFTR `/ft-intel/*` | `tests/test_contrato_rankingftr.py` (router real de RankingFTR v38) · 26 OK |
| RankingFTR | v38 | lee FT_NEWS `/news/estado`, `/hoy`, `/alertas`, `/diagnostico`, `/jugadores/buscar`, `/jugadores/{id}/memoria`, `/revision`, `/config`, `/fuentes`, `/excel` (proxies admin) | `tests/test_news_fase0.py` (sin FT_NEWS_URL lo dicen, no rompen) |
| FT Discord | **v11** (las tres de FT NEWS de fábrica) | lee FT Intelligence `/senales`, `/discord-config` | **`herramientas/recorrido_discord.py`** (anunciador real) |

Orden sugerido: **FT_NEWS → FT Intelligence → RankingFTR**. Un FT Intelligence
v17 con FT_NEWS v5.1 no rompe: transporta 📰 y 🔎 (con clave vieja `news:<id>`)
e ignora la 🔥 experimental (queda pendiente y vence a las 12 h). Un RankingFTR v37 con FT_NEWS v5.1: la pestaña funciona
sin los paneles nuevos.

## 2. Variables de Railway

**FT_NEWS** — ninguna nueva obligatoria. Las que vale revisar:

| Variable / parámetro | v5.1 | Nota |
|---|---|---|
| `GEMINI_API_KEY` | **regenerar** | la anterior apareció en los logs de Railway el 09/10 (iba en la URL `?key=`; desde v3 va en header y v5.1 enmascara cualquier clave en logs/estado). Google AI Studio → API keys → borrar la vieja → crear una nueva → pegarla en Railway → redeploy. |
| `NEWS_DISCORD_ACTIVO` | **1** | v6: nace encendido (Rubén 09/10 23:13). Si en `news_config` quedó en 0 por la guía anterior, encenderlo en Admin → FT NEWS → "Señales a Discord". Apagar es el mismo clic. |
| `NEWS_BANDAS_AUTO` | 0 | ídem: si quedó en 1 en `news_config`, ponerlo en 0 (la 🔥 validada la habilita Rubén). |
| `NEWS_MAX_BUSQUEDAS_DIA` | 250 | la pestaña (Diagnóstico → Presupuesto) dice si alcanza y qué tope propone. |
| `NEWS_EXPERIMENTAL_ACTIVO` | 1 | la 🔥 experimental viaja (cuando Discord esté encendido). |
| `NEWS_EXP_MIN_PUNTOS` / `NEWS_EXP_MOV_CUOTA_PCT` | 2 / 3.0 | justificación mínima de la 🔥 experimental. |
| `NEWS_SENAL_MAX_HORAS` | 12 | pendientes más viejas vencen (no hay avalancha al encender). |
| `NEWS_RADAR_TEMATICO_*`, `NEWS_RADAR_CUPO_MENORES_PCT`, `NEWS_RIVAL_HORAS` | 1·12·6 / 40 / 48 | radar temático, cupo menores, frescura del rival. |

Todo lo anterior son parámetros de `config.PARAMETROS`: se pueden fijar como
variable de Railway o desde la pestaña (`news_config` pisa el default).

**FT Intelligence**: nada nuevo (`FT_NEWS_URL`, `FT_NEWS_SECRET` ya están).
**RankingFTR**: nada nuevo (`FT_NEWS_URL`, `FT_NEWS_SECRET` ya están).
**FT Discord v11**: nada nuevo salvo que `FT_DISCORD_TIPOS_TEXTO` /
`FT_DISCORD_TIPOS_VOZ` estén puestas a mano en Railway: agregarles
`NEWS_VALOR,NEWS_INTERESANTE,NEWS_NOTICIA` o borrarlas. Con RankingFTR v38 manda
Admin → Discord → grupo FT NEWS, donde las tres nacen en texto + voz.

## 3. Migraciones de base (automáticas al arrancar FT_NEWS)

`db.py` crea lo que falte con `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ADD
COLUMN` (idempotente; no toca datos):

| Nuevo | Para qué |
|---|---|
| tabla `news_alerta` | las alertas seleccionadas (📰/🔎/🔥), motivo, evidencia, dicho |
| tabla `news_partido_fuente` | todos los fixture_id de un mismo encuentro |
| tabla `news_cuota_obs` + índice + `hasta_en` | cada observación de cuota: proveedor, hora, precio, hasta cuándo se vio vigente |
| tabla `news_evento_historial` | cambios de estado de cada evento |
| `news_partido.cuota_proveedor` | de quién es la cuota vigente |
| `news_articulo.resultado/motivo/jugador_id/origen/intentos/reintentar_en` | diagnóstico y reintentos |
| `news_busqueda.origen`, `news_evento.origen` | radar / temático / rss · EXTERNO / INTERNO |

Una sola vez (estado `fusion_duplicados_en`): `partidos.fusionar_duplicados`
funde los partidos repetidos que ya estaban. Los eventos viejos sin `origen`
se interpretan por `fuente`/`enlace` (los de contexto son INTERNO).

**Volumen**: el mismo `/data/ft_news.db`. Conviene bajar una copia antes
(Railway → volumen) por si hay que volver a v4; v4 ignora las tablas nuevas.

## 4. Pasos

1. Bajar copia de `/data/ft_news.db`.
2. Regenerar `GEMINI_API_KEY` (punto 2) y revocar la vieja.
3. Poner `NEWS_DISCORD_ACTIVO=0` y `NEWS_BANDAS_AUTO=0` en la pestaña si estaban en 1.
4. Subir FT_NEWS v5.1 → esperar un ciclo (15 min) → `/news/estado` debe decir
   `version: ft-news-v6-20261010`, `paso_fusion_duplicados`, `paso_reintentos`,
   `paso_alertas_vencidas` en `estado`. **Discord ya está encendido** en FT_NEWS:
   si se prefiere verificar primero con Discord apagado, poner
   `NEWS_DISCORD_ACTIVO=0` en la pestaña antes de este paso.
5. Subir FT Intelligence v18 → en sus logs, feed `news` cada 60 s.
6. Subir RankingFTR v38 → Admin → FT NEWS: paneles Alertas / Buscar jugador /
   Diagnóstico (con cobertura por circuito y presupuesto). Admin → Discord →
   grupo FT NEWS: las tres en texto + voz.
7. Subir FT Discord v11.
8. **Verificar con noticias y cuotas reales** (lo que Rubén pidió antes de
   habilitar): `python herramientas/verificar_real.py` con las URL y secretos de
   Railway. Chequea RankingFTR (fixtures con cuota y `actualizado_en` fresco,
   padrón), FT_NEWS (versión, pasos OK, clasificador, noticias externas hoy,
   búsquedas, cobertura por circuito, presupuesto, alertas sin enlaces, gasto)
   y FT Intelligence (señales NEWS_* con claves únicas, Admin → Discord). Termina
   en "LISTO PARA ENCENDER" o lista lo que falta. Si algo falla, apagar
   `NEWS_DISCORD_ACTIVO` en la pestaña mientras se corrige: las alertas siguen
   generándose y lo pendiente > 12 h vence solo (no hay avalancha al reencender).

## 5. Qué revisar en los primeros días (y dónde)

- `/news/diagnostico` → `hoy.externos` > 0 (si es 0 con búsquedas > 0: fuentes
  sin cobertura o consultas; ver `descartados` y `busquedas` sin resultado).
- `cobertura.circuitos`: itf/utr con `investigados` > 0 y `nunca_buscados`
  bajando; `presupuesto.alcanza`.
- `reintentos`: PENDIENTE/ERROR que no se acumulen; AGOTADO → revisión.
- `/news/alertas`: cada 🔥 experimental con su justificación (📌/⚖️/🧭);
  🔎 con `RIVAL_SIN_INVESTIGACION_RECIENTE` deberían resolverse al ciclo
  siguiente (el rival pasa al frente); 🔎 con `CUOTA_SIN_ACTUALIZAR` se
  resuelven cuando RankingFTR vuelve a traer la cuota (cada ~10 min el bot;
  si muchas quedan así, revisar que `/ft-intel/fixtures` traiga
  `actualizado_en` moviéndose).

## 6. Revisión del presupuesto (Rubén 09/10 22:52)

El tope de 250 es provisorio. Después de 24–48 h con Discord apagado, en
Diagnóstico → Presupuesto:

1. `necesario_dia` = búsquedas/día que la cola real pide a su cadencia
   (PARTIDO_24H cada 6 h, PARTIDO_72H cada 12 h, EVENTO_VIGENTE cada 24 h,
   SIN_PARTIDO semanal) × idiomas + temático. Si `alcanza` = no →
   `NEWS_MAX_BUSQUEDAS_DIA` = `tope_propuesto` (≈ US$ `usd_mes_con_propuesto`
   en Tavily).
2. `menores_pct_necesario` vs `cupo_menores_actual`: si los menores necesitan
   más de lo que el cupo reserva → `NEWS_RADAR_CUPO_MENORES_PCT` =
   `cupo_menores_sugerido` (tope 70 %), para que ITF/UTR no esperen a que
   sobre presupuesto.
3. Cobertura por circuito: `nunca_buscados` de itf/utr tiene que bajar día a
   día; si no baja con el tope alcanzando, el cuello es la cadencia (subir
   `NEWS_RADAR_JUGADORES_CICLO`, hoy 40).
- Calibración: sigue cada 6 h en paralelo; `NEWS_BANDAS_CALIBRADAS` lo pone
  Rubén cuando `INFORME-CALIBRACION.md` / `/api/news/calibracion` convenza.
