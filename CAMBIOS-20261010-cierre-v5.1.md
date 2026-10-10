# CAMBIOS — 10/10/2026 — FT_NEWS v5.1: cierre antes de encender Discord

Revisión de Rubén a v5 (09/10/2026 22:18, 8 puntos). Va sobre v5; FT_INTELLIGENCE
sigue en v18 (+ prueba de contrato), RankingFTR v38 (+ cobertura en la pestaña),
FT_DISCORD v10 sin cambios.

## 1. 🔥 experimental con justificación (`alertas.justificar`, `evaluador`)

Una noticia externa + banda UTR alineada con el mercado **ya no alcanza**. Para
cada 🔥 (experimental o validada) el motor arma, y escribe en el texto:

- **📌 Qué podría no estar en la cuota** — la noticia se publicó DESPUÉS de la
  última cuota observada (hora y proveedor); la cuota del jugador no se movió
  desde la apertura; el mercado está más optimista con él que el UTR.
- **➕ A favor** — hecho confirmado (fuente oficial / prensa fiable), dos fuentes,
  circuito menor (mercado menos líquido).
- **⚖️ En contra** — la cuota se capturó > 24 h después de la noticia; ya se
  movió hacia la noticia (≥ `NEWS_EXP_MOV_CUOTA_PCT` %); es declaración, no
  hecho; el hecho tiene > 5 días; identidad < 0,90; el rival también tiene
  noticia; bandas alineadas ("la ventaja, si existe, está solo en la noticia");
  UTR con > 30 días; alguno de los dos sin investigación reciente; **el retiro
  es del mismo torneo del partido** (puede no jugarse → nunca es valor).
- **🧭 Por qué merece la alerta** — balance a favor − en contra (mínimo
  `NEWS_EXP_MIN_PUNTOS` = 2) y al menos un ítem en "qué podría no estar en la
  cuota".

Si no alcanza, la evaluación queda **🔎 PARTIDO INTERESANTE** con motivo
`JUSTIFICACION_INSUFICIENTE` / `SIN_INFORMACION_NO_REFLEJADA` /
`RIVAL_SIN_INVESTIGACION_RECIENTE` / `RETIRO_MISMO_TORNEO` y la conclusión
dice qué faltó. La justificación completa queda en `news_alerta.evidencia_json`
y en el motivo de selección. La voz de la experimental empieza con "Posible
valor experimental, bandas sin validar".

## 2. Noticias que no se pierden si la IA falla (`radar.reintentar_pendientes`)

Antes: el artículo entraba a `news_articulo` (dedupe por URL) y, si Gemini/Claude
fallaba o el proceso se cortaba, quedaba "visto" sin clasificar para siempre.
Ahora nace `PENDIENTE` con el jugador para el que se buscó; un fallo lo deja con
`intentos` + `reintentar_en` (espera escalonada: pausa del proveedor × intento);
el paso `reintentos` de cada ciclo retoma PENDIENTE / ERROR / FUERA_DE_ESQUEMA
vencidos; al cuarto intento pasa a `AGOTADO` y a la cola de revisión
(`CLASIFICACION_FALLIDA`). Los PENDIENTE con 0 intentos (la IA ni los vio porque
el radar se cortó) también se retoman. `/news/diagnostico` → `reintentos`.

## 3. Investigación reciente de los dos (`alertas.frescura`)

`investigado()` ya no cuenta eventos vigentes: solo la búsqueda externa reciente
(radar directo, o un artículo temático/RSS que lo nombró) dentro de
`NEWS_RIVAL_HORAS`. Una lesión antigua todavía vigente del rival no sustituye su
investigación de hoy. El motivo de la 🔎 y la evidencia de la 🔥 traen la
frescura de cada uno ("investigado hace 0.3 h: 2 búsquedas, 1 artículo, 1
noticia externa"). Sin frescura → se adelanta en la cola y la alerta espera.

## 4. Duplicados y cuotas (`partidos`, `news_cuota_obs`)

Cada observación de cuota se guarda con **proveedor, hora de captura
(`actualizado_en` del fixture) y precio**, orientada al orden del partido; se
inserta solo si cambió respecto de la última del mismo proveedor. La cuota
vigente de `news_partido` (y la que usan las alertas) es la **más reciente por
hora de captura**, con `cuota_proveedor`; la apertura es la primera. La fusión
de duplicados conserva las observaciones de los dos registros. Pruebas: mismo
partido por dos proveedores con cuotas distintas (uno solo, dos observaciones,
manda la más reciente), encuentros distintos entre los mismos jugadores (> 3 h:
dos partidos), fusión con observaciones.

## 5. Cobertura ITF/UTR (`cobertura.py`, `/news/diagnostico`, pestaña)

Por circuito y ventana (7 días): en cola, investigados, % cobertura, nunca
buscados, búsquedas y sin resultado, artículos, noticias útiles (externas
fuertes), partidos analizados, alertas por tipo. Y el **presupuesto**: búsquedas/
día que la cola necesita a su cadencia (idiomas × 24/cadencia) + temático, contra
`NEWS_MAX_BUSQUEDAS_DIA`; si no alcanza propone el tope (necesario × 1,2,
redondeado a 50) con su costo en Tavily. Se ve en Admin → FT NEWS → Diagnóstico.
**Propuesta**: dejar 250 hasta ver la cola real en producción; si el panel dice
"no alcanza", subir al propuesto (cada 50 búsquedas/día ≈ US$ 12/mes).

## 6. Prueba completa FT NEWS → FT Intelligence → FT Discord

`herramientas/recorrido_discord.py` (y `tests/test_recorrido_discord.py`): corre
el código REAL de los tres servicios —FT_NEWS (ciclo completo), FT Intelligence
(`news.sincronizar` contra la app de FT_NEWS), FT Discord (`Anunciador` real con
la fuente apuntando a la base de FT Intelligence)— con Tavily, clasificador y
RankingFTR simulados en el formato real de cada API. Resultado en
`EJEMPLOS-ALERTAS-20261009.md`: 📰 ×3, 🔎 ×2, 🔥 experimental ×1, con texto,
fuentes, cuotas con proveedor y hora; segundo ciclo en los tres: nada
repetido. Contrato FT Intelligence ↔ FT_NEWS: `tests/test_contrato_ft_news.py`
(en FT_INTELLIGENCE). Contrato RankingFTR v38 ↔ FT Intelligence: 26 OK.

## 7. Discord nace apagado; nada vence sin control

`NEWS_DISCORD_ACTIVO` pasa a **0 por defecto** (Rubén: activar cuando la prueba
real convenza). Las alertas se generan igual y se ven en la pestaña con su
motivo. Al encender no sale una avalancha: lo pendiente con más de
`NEWS_SENAL_MAX_HORAS` (12) queda `omitida: VENCIDA` (paso `alertas_vencidas`).
Ninguna clave de API puede terminar en logs, `news_estado` ni la pestaña
(`proveedores.tavily.sin_claves`, aplicado a `ErrorProveedor` y a los pasos).

## Pruebas

`tests/test_v51_justificacion.py` (nuevo, 14) + `tests/test_recorrido_discord.py`
(nuevo, 1). `pytest tests`: **87 OK** (con FT_INTELLIGENCE y FT_DISCORD al lado).

## Archivos tocados (v5.1 sobre v5)

- `ft_news/__init__.py`, `ft_news/alertas.py`, `ft_news/app.py`,
  `ft_news/cobertura.py` (nuevo), `ft_news/config.py`, `ft_news/db.py`,
  `ft_news/evaluador.py`, `ft_news/partidos.py`, `ft_news/radar.py`,
  `ft_news/tareas.py`, `ft_news/textos.py`, `ft_news/lectores/rss.py`,
  `ft_news/proveedores/tavily.py`
- `herramientas/recorrido_discord.py` (nuevo), `EJEMPLOS-ALERTAS-20261009.md`
  (generado), `DESPLIEGUE-v5.md` (nuevo)
- `tests/test_v51_justificacion.py` (nuevo), `tests/test_recorrido_discord.py`
  (nuevo), `tests/correr_todo.sh`, `tests/test_apagado_y_fuentes.py`,
  `tests/test_recorrido_fase1.py`, `tests/test_segunda_entrega.py`,
  `tests/test_v5_alertas.py`
- `README.md`, este archivo
