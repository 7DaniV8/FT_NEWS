# FT NEWS v7 — carga física por clases + todo en palabras simples (10/10/2026)

Pedidos de Rubén (10/10, 01:03–01:07): evaluación #148 **Arthur Gea vs Ugo
Humbert** favorecía a Humbert por "carga física" de Gea (3 partidos y 9 sets
en 7 días), con UTR 15.81 vs 15.75 y cuotas 2.01 / 1.79; la carga aparecía
cuatro veces; y la vista estaba llena de códigos (CONTRA_X, FUEGO, PAREJO,
DESVÍO ALINEADO, DIRECCIÓN NETA, MOTOR NEWS-DESCUBRIDOR). Objetivo: "un
investigador inteligente, no un bot que interprete cualquier estadística como
una oportunidad", y "investigación profesional por dentro, presentación
sencilla por fuera". Nada de otros bots cambió.

## 1. Diagnóstico de las reglas que estaban

| Regla | Dónde | Qué hacía | Problema |
|---|---|---|---|
| Carga = `≥ 4 partidos en 7 días` **o** `≥ 3 partidos a 3+ sets en 7 días` | `contexto.py` (`UMBRAL_PARTIDOS_7D`, `UMBRAL_TRES_SETS_7D`) | creaba un evento `CARGA_FISICA` **NEGATIVO**, nivel A, categoría **FUERTE** en la taxonomía | 3 partidos a tres sets (Gea) ya disparaba; una semana normal quedaba marcada "en contra". Umbral arbitrario, sin datos. |
| Un evento por **fixture** (`enlace = contexto:<partido_id>`) | `contexto._evento_contexto` | el mismo partido llegaba por varios proveedores (antes de la fusión v5) y por la ronda siguiente → 2–4 eventos iguales vigentes | el descubridor cuenta `len(eventos)` para la "fuerza" de la dirección: la misma condición inflaba la lectura y se mostraba cuatro veces. |
| Dirección de la carga = NEGATIVA siempre | `contexto.py` | cualquier carga marcada empujaba la lectura "contra" el jugador | "no perjudicar automáticamente al jugador". |
| Sin clase de inactividad ni de datos insuficientes | — | "0 partidos" no se distinguía de "no tenemos su historial" | igual que en Cuota Mal Puesta: la ausencia de datos no puede producir nada. |
| 🔥 con carga sola | `descubridor.py` v2–v4 (producción el 10/10 seguía en v2) | #148 salió **FUEGO · CONTRA_X** solo con carga | desde v5 (09/10) la compuerta 5b exige noticia EXTERNA fuerte: ya no podía dar 🔥, pero seguía marcando negativo y duplicado. |
| Vista con códigos | `/news/hoy`, modal, alertas, memoria | `motivo`, bandas, desvío, dirección neta, nivel, motor | ilegible para un usuario. |

**Cuántas señales salieron solo por estadística interna y qué resultados las
respaldan**: no puedo leer la base de Railway desde acá; lo calcula ahora el
servicio y lo muestra la pestaña: `GET /news/diagnostico` → `carga`
(`evaluaciones.solo_estadistica_interna` por tipo, `con_carga`,
`duplicados.evaluaciones_con_carga_repetida`, `jugadores_con_varios_vigentes`,
`resultados_del_cargado` = ganó / perdió / retiro / sin resultado, y la
distribución de partidos / sets / games / días de descanso con el % que caería
en cada clase con los umbrales de hoy y el % que habría marcado la regla
anterior). Con 24–48 h de datos se fijan juntos los umbrales.

## 2. Correcciones

### Carga por clases (`contexto.py`, misma filosofía que Cuota Mal Puesta V3)

| Clase | Condición (provisoria; Admin → FT NEWS → config) | Evento | Investiga |
|---|---|---|---|
| `SIN_DATOS` | sin partidos en el historial que trae RankingFTR | no | — |
| `INACTIVIDAD` | ≥ `NEWS_CARGA_INACTIVIDAD_DIAS` (10) días sin competir | no (se informa: "lleva N días sin competir; descansado, pero puede faltarle ritmo") | — |
| `NORMAL` | lo demás (incluye 3 partidos / 9 sets; 4 partidos con 3 a tres sets; una ronda por día) | no — y si había uno vigente, **vence** ("la carga volvió a normal") | — |
| `CONSIDERABLE` | ≥ `NEWS_CARGA_CONSIDERABLE_PARTIDOS_7D` (5) partidos, o ≥ `…_TRES_SETS_7D` (4) a tres sets, o doble jornada | sí, dirección **MIXTA** (seguimiento: no empuja la lectura) | sí (pasa al frente de la cola) |
| `EXCEPCIONAL` | ≥ `NEWS_CARGA_EXCEPCIONAL_PARTIDOS_7D` (6) partidos o ≥ `…_TRES_SETS_7D` (5) a tres sets | sí, NEGATIVO | sí |

Se guarda todo en `news_contexto` (`CARGA`): partidos 3/7/14 d, sets, games
(del marcador, sin estimar duración), a tres sets, doble jornada, días desde el
último partido, retiro en el último, clase, texto y versión `carga-news-v7`.

**Un solo evento vigente por jugador y categoría calculada**: otro fixture o la
ronda siguiente actualizan el mismo evento (queda en su historial de cambios);
los duplicados que dejaron versiones anteriores vencen en el primer ciclo
(`dedupe_internos`). El descubridor además descarta repetidos
(`sin_repetidos`: un calculado por categoría, un externo por artículo) antes de
contar nada. Ninguna carga decide una 🔥 sola (compuerta 5b, intacta).

### Todo en palabras (`explicar.py`)

Cada evaluación guarda su **lectura** (`news_evaluacion.lectura_json`) y, si
no es 🔥, ese es su texto:

```
🔎 FULLTENNIS · PARTIDO EN ANÁLISIS
🎾 Arthur Gea vs Ugo Humbert
🏆 Shanghai Masters
📊 UTR: 15.81 vs 15.75
💰 Gea 2.01 | Humbert 1.79
⚖️ NIVEL: Jugadores prácticamente igualados por UTR.
🟡 CARGA FÍSICA: Arthur Gea disputó 3 partido(s) y 9 sets en 7 días (3 a tres sets). No hay evidencia suficiente para considerarlo fatigado.
🧭 CONCLUSIÓN: No se identifica una ventaja clara por desgaste físico.
```

Con noticia externa y lectura 🔥 (del recorrido de prueba):

```
🔥 FULLTENNIS · POSIBLE VALOR EXPERIMENTAL
🎾 Mateo Quiroga vs Luca Bertolini
🏆 Challenger Lima
📊 UTR: 12.85 vs 12.41
💰 Quiroga 1.42 | Bertolini 2.85
⚖️ NIVEL: Quiroga parte ligeramente por encima por UTR.
🚨 NOTICIA: Quiroga — Molestias en el tobillo derecho.
🔴 PERJUDICA A: Mateo Quiroga
🟢 JUGADOR FAVORECIDO: LUCA BERTOLINI
💰 CUOTA: 2.85
🧭 CONCLUSIÓN: La noticia podría favorecer a Luca Bertolini y la cuota todavía no parece reflejarla. Lectura experimental, sin validar estadísticamente.
```

Sin favorecido inventado (retiro en el mismo torneo):

```
🔎 FULLTENNIS · PARTIDO EN ANÁLISIS
🎾 Tom Whitlock vs Nicolás Ferreyra
🏆 M25 Sevilla
📊 UTR: 11.05 vs 11.30
💰 Whitlock 1.90 | Ferreyra 1.90
⚖️ NIVEL: Jugadores prácticamente igualados por UTR.
🚨 NOTICIA: Whitlock — Se retiró del M25 de Sevilla por la muñeca.
🧭 CONCLUSIÓN: El jugador se retiró en este mismo torneo: el partido podría no jugarse.
```

Además: cada motivo del motor tiene su frase (`MOTIVOS`: "Solo hay datos
calculados por nosotros…", "Falta una cuota actualizada después de la
noticia…", "La cuota ya refleja la noticia…", etc.); categorías y estados en
español; cada evento en una frase ("🔴 Lesión o molestia · perjudica a Gea:
Molestia en el hombro."); cada alerta con "por qué se seleccionó" en palabras;
el historial de un jugador en frases; el dashboard 🔥 dice "La noticia
perjudica a X · fuente fiable" en vez de "nivel B". Los campos técnicos
(`motivo`, bandas, desvío, dirección neta, nivel, motor, `motivo_seleccion`)
siguen en la API para el admin. Los tres formatos de Discord (📰 / 🔎 / 🔥) no
cambian; siguen sin enlaces, sin porcentajes y sin inventar favorecido.

### Endpoints

- `/news/hoy`: cada evaluación con `lectura` {encabezado, lineas, texto,
  resumen, favorecido, cuota_favorecido, motivo}, `motivo_simple`,
  `dicho_motivo_simple`; cada evento con `categoria_es`, `texto_simple`,
  `estado_es`.
- `/news/evaluaciones/{id}`: + `lectura`, `carga` {x, rival}, eventos con
  `texto_simple`, `evaluacion.motivo_simple`.
- `/news/jugadores/{id}/memoria`: + `lectura_simple`, `carga`, eventos con
  `texto_simple`.
- `/news/alertas`: cada alerta con `motivo_simple` y `dicho_motivo_simple`.
- `/news/diagnostico`: + `carga` (diagnóstico de reglas, §1).

### Pestaña FT NEWS (RankingFTR v39)

Tabla "Hoy": sin columnas de bandas / mercado / nivel / motivo; columna
**Lectura** (🟢 FAVORECIDO @cuota · resumen). Modal: **🧭 Lectura** arriba,
noticias y datos en frases, 🟡 carga de los dos, y **🔧 Detalles técnicos
(admin)** colapsado con todo lo del motor. Alertas: "por qué" en palabras
(técnico en el tooltip). Noticias recientes: "qué pasó" en una frase, evidencia
como "hecho confirmado / fuente fiable / sin confirmar", estado en español.
Jugador: carga + historial en frases, detalle por noticia colapsado.
Diagnóstico: bloque **🏃 Reglas de carga física** (regla anterior vs v7,
evaluaciones solo con estadística interna, duplicados, resultados del
cargado, percentiles e histogramas).

## 3. Pruebas

- `tests/test_v7_carga_claro.py` (nuevo, 7): Gea vs Humbert (3 partidos / 9
  sets → NORMAL, sin evento, sin 🔥, lectura exacta); una misma condición no
  se cuenta varias veces (dos partidos próximos + dos duplicados viejos → un
  solo vigente; `sin_repetidos`); carga EXCEPCIONAL deja evento, pasa al
  frente de la cola y sigue siendo 🔎 SIN_NOTICIA_EXTERNA_FUERTE, y vence
  sola cuando la carga baja; inactividad informada sin ventaja; lesión real
  externa + carga normal → sigue siendo 🔥 experimental (y la carga repetida
  cuenta una vez); `explicar` sin códigos en ningún texto; endpoints con
  lectura y diagnóstico de carga.
- Ajustados: `test_segunda_entrega` (Perez 4 partidos / 3 a tres sets ya no
  es carga), `test_v5_alertas` (un evento de carga que vuelve a normal vence).
- Suite completa FT_NEWS: **97 passed** (incluye el recorrido real con FT
  Intelligence v19 y FT Discord v11). FT Intelligence `correr_todo.sh` →
  TODO OK (contrato con FT_NEWS 7 OK). RankingFTR `correr_todo.sh` → "Todo en
  orden" (`test_news_fase0` con 3 comprobaciones v39).
- `EJEMPLOS-ALERTAS-20261010.md` regenerado con la lectura simple de cada
  evaluación y el "por qué" en las dos versiones (usuario / técnico).

## 4. Despliegue

FT_NEWS v7 (`ft-news-v7-20261010`) + RankingFTR v39. Migración automática:
`news_evaluacion.lectura_json` (ADD COLUMN); las evaluaciones viejas se
explican al vuelo. Primer ciclo: `dedupe_internos` vence los eventos de carga
repetidos y el Motor 3 reclasifica la carga de todos los jugadores en ventana
(las cargas "normales" marcadas por la regla anterior vencen con detalle "la
carga volvió a normal (v7)"). Variables nuevas (opcionales, defaults
provisorios): `NEWS_CARGA_CONSIDERABLE_PARTIDOS_7D` 5 ·
`NEWS_CARGA_CONSIDERABLE_TRES_SETS_7D` 4 · `NEWS_CARGA_EXCEPCIONAL_PARTIDOS_7D`
6 · `NEWS_CARGA_EXCEPCIONAL_TRES_SETS_7D` 5 · `NEWS_CARGA_INACTIVIDAD_DIAS` 10.
FT Intelligence y FT Discord: sin cambios (el contrato `/news/senales` es el
mismo).

## Archivos modificados (FT_NEWS)

- `ft_news/__init__.py` (v7)
- `ft_news/config.py` (5 parámetros de carga)
- `ft_news/contexto.py` (clases, texto, un evento por jugador, dedupe, `carga_de`)
- `ft_news/descubridor.py` (`sin_repetidos`, versión del motor)
- `ft_news/evaluador.py` (lectura guardada; texto de la evaluación 🔎)
- `ft_news/explicar.py` (nuevo)
- `ft_news/diagnostico_carga.py` (nuevo)
- `ft_news/alertas.py` (`motivo_simple` en `listar`)
- `ft_news/app.py` (`/news/hoy`, `/news/evaluaciones/{id}`, `/news/jugadores/{id}/memoria`, `/news/diagnostico`)
- `ft_news/db.py` (`lectura_json`)
- `ft_news/dashboard.py` (detalle en palabras)
- `herramientas/recorrido_discord.py`, `herramientas/verificar_real.py`
- `tests/test_v7_carga_claro.py` (nuevo), `tests/test_segunda_entrega.py`, `tests/test_v5_alertas.py`
- `README.md`, `DESPLIEGUE-v5.md`, `EJEMPLOS-ALERTAS-20261010.md`, `CAMBIOS-20261010-carga-y-claro-v7.md` (este)
