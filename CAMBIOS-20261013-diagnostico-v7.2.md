# FT NEWS v7.2 — Diagnóstico permanente del envío (13/10/2026)

Pedido de Rubén: *"FT NEWS casi no está enviando alertas y no sabemos si funciona. Quiero
saber cuántas noticias externas reales entran por día, cuántas se descartan y por qué,
cuántos partidos se pierden por falta de investigar al rival, cuántas oportunidades
bloquea una cuota sin actualizar, si las alertas pasan por FT Intelligence y llegan a
Discord, y si 'bandas calibradas' está activada mal. Sin bajar filtros a ciegas ni
inventar oportunidades."*

**Ningún filtro cambió.** Las reglas de 📰 / 🔎 / 🔥 son las mismas de v7.1. Lo nuevo
solo **registra** por qué no salió algo, más un control: la casilla "bandas calibradas"
deja de aplicarse si no hay veredicto.

## Qué hay de nuevo

| Pieza | Qué hace |
|---|---|
| `news_descarte` (tabla nueva) | Guarda para siempre cada decisión de NO enviar: una fila por (día, etapa 📰/🔎/🔥, partido o noticia, motivo). Si el ciclo siguiente vuelve a descartar lo mismo, suma `veces`. No se borra nada. |
| `ft_news/descartes.py` | Agrupa los códigos del motor en motivos con texto simple (p. ej. `RIVAL_SIN_INVESTIGACION_RECIENTE:…` → *falta investigar a uno de los dos*). `embudo()` responde las seis preguntas por día. |
| `news_evaluacion.alerta_motivo` / `news_evento.noticia_motivo` | En cada partido y cada noticia queda escrito "ALERTA #n" o "NO ENVIADA · motivo". |
| `ft_news/salud.py` | Semáforo **🟢 FUNCIONANDO / 🟡 SIN DATOS / 🔴 ERROR**, con sus motivos y los indicadores pedidos. Cero alertas **no** es un error. |
| Latido de FT Intelligence | `/news/senales` anota `senales_leidas_en` cada vez que FT Intelligence lee, aunque no haya nada que entregar; `/news/senales/dicho` anota `senales_dicho_en`. |
| `NEWS_BANDAS_EXIGIR_VEREDICTO=1` (nuevo, default) | `NEWS_BANDAS_CALIBRADAS=1` solo se aplica si el veredicto de RankingFTR es `CALIBRADAS_OK`. Si no, el motor trabaja como sin calibrar (🔥 solo EXPERIMENTAL), el semáforo marca ERROR y la configuración guardada no se toca. `POST /news/config` ya no permite activarla sin ese veredicto (409). |
| Prueba de Discord | `POST /news/prueba` deja una alerta tipo `PRUEBA` (`prueba=1`) con el texto "🧪 PRUEBA DE FT NEWS — NO ES UNA OPORTUNIDAD". Viaja a FT Intelligence con `tipo_alerta=NOTICIA` y `prueba=true`. Queda fuera del historial, el dashboard, los topes, la cobertura, el resumen y las estadísticas. `GET /news/prueba/{id}` dice si sigue pendiente, si FT Intelligence la marcó como enviada o si la omitió. |
| `herramientas/diagnostico_alertas.py` | Solo lectura. Reconstruye el embudo **con la historia anterior a v7.2** (antes no se guardaban los motivos). |

## Endpoints nuevos (todos con `X-FT-News-Secret`)

- `GET /news/salud`: el semáforo.
- `GET /news/embudo?dias=7`: semáforo y embudo.
- `POST /news/prueba` y `GET /news/prueba/{id}`.
- `/news/estado` incluye `salud`; `/news/senales` incluye `prueba` en cada señal.

## Cambio de comportamiento (el único)

Hoy "bandas calibradas" está marcada y el veredicto es `NO_CALIBRADAS`. Con v7.2, las 🔥 que
salieran como *validadas* salen como **EXPERIMENTAL**. Para volver a v7.1:
`NEWS_BANDAS_EXIGIR_VEREDICTO=0`.

## Pruebas

`tests/test_v72_diagnostico.py` tiene 8 pruebas: grupos, registro sin duplicar, rival sin
investigar guardado → recuperado → perdido, cuota sin actualizar, motivo en cada noticia,
bandas mal activadas, semáforo en sus tres estados y prueba de Discord fuera de historial
y estadísticas. Suite completa: **105 OK, 1 omitida** (la del recorrido con FT Intelligence
y FT Discord, que necesita esos repos al lado).

## Pasos en Railway (en este orden; nada se enciende solo)

1. **Antes de desplegar** (solo lectura): `railway ssh --service FT_NEWS` y luego
   `python herramientas/diagnostico_alertas.py --horas 72`. Si el archivo todavía no está
   en el contenedor: `cat > /tmp/diag.py`, pegar, Ctrl+D, `python /tmp/diag.py --horas 72`.
   Guardar la salida: es la foto "antes".
2. Desplegar FT_NEWS v7.2. Las tablas y columnas nuevas se crean solas (ADD COLUMN idempotente).
3. Desplegar RankingFTR v48 (pestaña FT NEWS → "¿FT NEWS está funcionando?").
4. Esperar dos ciclos (30 min) y abrir la pestaña: semáforo y embudo.
5. Pulsar **🧪 Enviar PRUEBA a Discord** y mirar el canal de FT NEWS.
6. `python herramientas/verificar_real.py` desde una máquina con las variables.

---

# v7.3 — La prueba distingue recibida de publicada y solo va a admin (13/10/2026)

Rubén: *"ENVIADA no puede leerse como confirmación de publicación si solo significa que FT
Intelligence la recogió. Hay que distinguir: FT NEWS la creó → FT Intelligence la recibió →
FT Discord la publicó, y si falla, en qué paso y por qué. La prueba es solo para administradores,
no cuenta en estadísticas y no va a la comunidad."*

- **Tres pasos por alerta** (`alertas.pasos_alerta`), en palabras:
  1. *FT NEWS creó la alerta*.
  2. *FT Intelligence la recibió*: se anota `entregada_en` cuando `/news/senales` la entrega.
  3. *FT Discord la publicó*: solo con `publicado: true/false` en `/news/senales/dicho`.
  "Dicho" sin `publicado` queda **sin confirmar**; nunca se presenta como publicada. Si
  falla, el resumen dice "Falló en el paso N" y por qué (vencida sin recoger, omitida por
  FT Intelligence o error de FT Discord).
- **Candado `NEWS_PRUEBA_SOLO_ADMIN_VERIFICADA=0` (default)**: la PRUEBA no se puede crear
  ni viaja a FT Intelligence hasta comprobar en el código de FT Intelligence y FT Discord
  que una señal con `prueba=true` / `solo_admin=true` / `destino=ADMIN` va solo al canal
  de administradores.
- **Indicadores separados**: recibidas por FT Intelligence / procesadas por FT Intelligence /
  publicación confirmada por FT Discord / falló la publicación. El embudo trae `5_entrega.pasos`.
- **Textos del semáforo sin códigos técnicos** (hay una prueba que lo verifica). El detalle
  técnico de cada paso fallido sigue en `indicadores.errores_de_pasos`.

**Pendiente de los repos FT_INTELLIGENCE y FT_DISCORD**:
- que FT Intelligence acepte una señal sin jugador;
- que la mande solo al canal de admin;
- que FT Intelligence informe `publicado`, `canal` y `error` con lo que devuelve FT Discord.

Pruebas: **108 OK, 1 omitida**.

## v7.3 · añadidos del 13/10 de madrugada (pedido de Rubén, 00:35)

- **Las alertas reales siguen yendo a la comunidad.** FT NEWS no las retiene: con
  `NEWS_DISCORD_ACTIVO=1` las tres categorías (📰, 🔎, 🔥) salen hacia FT Intelligence sin
  aprobación manual. Solo la PRUEBA va marcada para el canal de administradores (y bloqueada
  hasta verificarlo).
- **Recorrido de cada alerta** (`/news/alertas` → `recorrido`). Guarda la hora de detección,
  el jugador y el partido, el tipo, el motivo, si FT Intelligence la recibió, si la procesó
  o la descartó y por qué, si FT Discord confirmó la publicación, el canal (`publicado_canal`)
  y el error (`publicado_error`). Nunca figura como publicada sin la confirmación de FT Discord.
- **Las noticias no confirmadas no se presentan como hechos.** Cada alerta 📰/🔎/🔥 lleva una
  línea nueva:
  - «✅ Confirmado por fuente oficial (ATP Tour)»;
  - «📰 Informado por Punto de Break; sin confirmación oficial»;
  - «🗣️ Según declaraciones recogidas por …; sin confirmación oficial»;
  - «📊 Dato calculado por FullTennis».

  Solo cambia la presentación: no cambia qué sale.
- **El diagnóstico abre con un resumen de 72 h** que responde las 10 cifras pedidas, y cierra
  con una sección de problemas: API, cuotas, identificación, rivales y conexión entre servicios.
  Funciona sobre la base actual de producción (v7.1), probado. Instrucciones exactas en
  `herramientas/DIAGNOSTICO-RAILWAY.md`.

Pruebas: **110 OK, 1 omitida**.

## v7.3 · integración cerrada con FT Intelligence v24 y FT Discord v16 (13/10/2026, mediodía)

Con los repos de los dos servicios, el recorrido de ida y vuelta quedó comprobado con el
código real de los cuatro (`tests/test_recorrido_discord.py`, 3 pruebas):

- 📰 / 🔎 / 🔥 publicadas en la comunidad y **confirmadas de vuelta**: FT Discord da el acuse,
  FT Intelligence lo reenvía y FT NEWS guarda `publicado` / `publicado_canal` /
  `publicado_error`.
- La PRUEBA sale **solo** por el canal de administradores (`DISCORD_CANAL_ADMIN_ID` en FT
  Discord), sin voz. Sin ese canal, no sale por ningún lado.
- Una 🔎 reemplazada por la 🔥 del mismo partido figura como **REEMPLAZADA**, no como fallo.
- Interruptor «Prueba de Discord habilitada» en la pestaña (`NEWS_PRUEBA_SOLO_ADMIN_VERIFICADA`).

Pruebas: **113 OK**, con los tres repos.
