# CAMBIOS — 09/10/2026 — FT_NEWS v5: investigador autónomo (📰 / 🔎 / 🔥 experimental)

Pedido de Rubén (09/10/2026, 13 puntos + aclaración): "FT NEWS debe usar
directamente nuestro ranking UTR y combinarlo con noticias y cuotas… que el
radar investigue noticias continuamente aunque no tengan partido… ATP, WTA,
Challenger, ITF y UTR sin dejar los circuitos pequeños para el final… no
depender de llegar a 300 partidos: con evidencia sólida puede salir como
🔥 POSIBLE VALOR EXPERIMENTAL… una simple diferencia UTR no es valor… sin Elo
ni FTR y sin modificar nuestros otros bots". Va sobre v4 (Claude clasificador).

## 1. Qué suena en Discord y por qué (`ft_news/alertas.py`, nuevo)

Todo lo que viaja a FT Intelligence sale ahora de la tabla `news_alerta`
(tipo, clave de dedupe, jugador, rival, partido, eventos usados, **motivo de
selección en texto**, evidencia JSON, texto, voz, dicho 0/1/2). Tres
categorías independientes:

- **📰 NOTICIA IMPORTANTE** (`NEWS_DISCORD_NOTICIA`): nace en el radar, en
  cuanto se guarda un evento EXTERNO vigente. Reglas: categoría fuerte
  (lesión, enfermedad, retiro, regreso) o categoría oficial (sanción,
  cambio de equipo, situación personal, viaje) con nivel A; nivel ≥ B;
  naturaleza HECHO o DECLARACION; identidad ≥ `NEWS_IDENTIDAD_MIN`; hecho de
  ≤ `NEWS_NOTICIA_MAX_DIAS` (7). **No necesita partido.** Texto: jugador +
  UTR, qué pasó y cuándo, fuente con enlace y grado de confirmación,
  "por qué importa", próximo partido si lo hay y "🧭 Seleccionada porque…".
- **🔎 PARTIDO INTERESANTE** (`NEWS_DISCORD_INTERESANTE`): un partido con
  noticia externa fuerte (nivel ≥ B) en alguno de los dos, **con los dos
  investigados** (si el rival no fue buscado en `NEWS_RIVAL_HORAS` se lo
  adelanta en la cola —"a demanda"— y la 🔎 espera al próximo ciclo). Texto:
  UTR de ambos, cuotas con hora de consulta, qué se encontró y a quién
  afecta, antecedentes del rival, qué falta confirmar y por qué se
  seleccionó.
- **🔥 POSIBLE VALOR**: ahora exige una noticia externa fuerte (compuerta
  nueva `SIN_NOTICIA_EXTERNA_FUERTE` en el descubridor: **la carga calculada
  sola nunca da 🔥**). Con bandas validadas → `FUEGO` (como antes). Sin
  validar y `NEWS_EXPERIMENTAL_ACTIVO=1` → `FUEGO_EXPERIMENTAL`: texto
  "🔥 FULLTENIS · POSIBLE VALOR EXPERIMENTAL (por noticias)", línea "bandas
  sin validar" y "⚠️ posibles explicaciones del mercado" (noticia del rival,
  cuota en movimiento). Si después llega la validada del mismo partido, la
  experimental pendiente queda `SUPERADA_POR_VALIDADA`; una 🔥 ya dicha no
  se degrada (tampoco de validada a experimental).

Dedupe y topes: una 📰 por jugador y categoría cada `NEWS_ALERTA_REPETIR_DIAS`
salvo que suba de nivel o pase de declaración a hecho; una 🔎 por partido
salvo eventos nuevos; `NEWS_MAX_NOTICIA_DIA` (8), `NEWS_MAX_INTERESANTE_DIA`
(6), `NEWS_MAX_FUEGO_DIA` como antes.

## 2. Radar continuo y cobertura pareja (`radar.py`, `jugadores.py`, `lectores/rss.py`)

- **Cola por score** (situación del partido > a demanda > gravedad de lo
  vigente > antigüedad de la última revisión) **con cupo**
  `NEWS_RADAR_CUPO_MENORES_PCT` (40 %) para challenger / WTA 125 / ITF / UTR:
  de cada 40 jugadores por ciclo, al menos 16 son de circuitos menores si
  hay candidatos. Antes el `ORDER BY prioridad` los dejaba siempre al final.
- **Radar temático** (`correr_tematico`, cada `NEWS_RADAR_TEMATICO_CADA_H`
  = 6 h, `NEWS_RADAR_TEMATICO_BUSQUEDAS` = 12): busca por tema ("tennis
  injury withdraws", "tenis lesión baja", …) en las fuentes autorizadas con
  `days=1`, y cruza cada artículo contra **todo el padrón**
  (`jugadores.buscar_en_texto`: nombre completo, ≥ 1 token de 4 letras).
  Solo se paga IA por los artículos que nombran a alguien. Así se investiga
  a jugadores sin partido con 48 búsquedas/día, no 20.000.
- **RSS** cruza con todo el padrón, no solo con la cola.
- Tras un evento externo fuerte: el jugador pasa a `EVENTO_VIGENTE` (se lo
  sigue cada 24 h aunque no tenga partido) y, si tiene partido, el rival se
  adelanta.
- Cada artículo deja escrito su resultado y motivo
  (`news_articulo.resultado`: EVENTO / OTRO_JUGADOR / IDENTIDAD_DUDOSA /
  SIN_FECHA / FUERA_DE_ESQUEMA / SIN_JUGADOR_DEL_PADRON / ERROR) y su origen
  (radar / tematico / rss); las búsquedas también (`news_busqueda.origen`).

## 3. Memoria verificable (`memoria.py`)

- `news_evento.origen` EXTERNO / INTERNO (los de contexto —carga, viaje,
  localía, antecedentes— son INTERNO y nunca cuentan como noticia).
- `news_evento_historial`: NUEVO, SUPERADO, EN_SEGUIMIENTO, VENCIDO,
  DESMENTIDO, CONFIRMADO, DESCARTADO, con detalle y quién. `vencer_db` corre
  en cada ciclo (antes el vencimiento era solo en memoria).
- Revisión: acción nueva `DESMENTIR`.

## 4. Partidos duplicados (`partidos.py`)

`_upsert_partido` funde un fixture nuevo con un partido existente del mismo
par (± 3 h) aunque venga de otro proveedor (tabla `news_partido_fuente`
conserva todos los fixture_id); `fusionar_duplicados` corre **una vez** al
subir (estado `fusion_duplicados_en`) sobre lo que ya estaba: se queda el
menor id, se reasignan evaluaciones y contexto, los duplicados quedan
`estado='DUPLICADO'`. Las estadísticas y `/news/diagnostico` cuentan únicos.

## 5. Calibración

`NEWS_BANDAS_AUTO` pasa a **0** por defecto: el motor ya no enciende las
bandas solo por llegar a la muestra (Rubén §8). La 🔥 validada sigue
bloqueada hasta que Rubén ponga `NEWS_BANDAS_CALIBRADAS=1` a mano, después
de revisar cortes, dirección y fuera de muestra. Mientras tanto, lo que
pasa todas las compuertas sale como experimental, diferenciado.

## 6. API (`app.py`)

- `GET /news/senales`: ahora desde `news_alerta`; suma `partido_id`,
  `evaluacion_id`, `jugador_id`, `rival_id`, `clave`, `experimental`. Las 📰
  pueden venir sin rival ni fixture.
- `GET /news/alertas?tipo=&limite=`: panel de alertas (enviadas, pendientes,
  omitidas, motivo, evidencia, estado del partido, resultado).
- `GET /news/diagnostico?dias=7`: búsquedas por origen/idioma/circuito y sin
  resultado, artículos por resultado y origen, descartados con motivo,
  fuentes usadas, eventos externos vs internos (hoy y por categoría), costo
  por proveedor, cola por situación/circuito con "nunca buscados", errores,
  último estado de cada paso, partidos únicos / fundidos.
- `GET /news/jugadores/buscar?q=`: buscador; `GET /news/jugadores/{id}/memoria`
  trae también origen y cambios de cada evento, partidos, alertas y
  búsquedas del jugador.
- `/news/estado` y `/news/hoy`: contadores y resumen de alertas; eventos con
  `origen`.

## 7. Presupuesto propuesto (Rubén §11: "propón el nuevo límite")

| | antes (v4) | v5 | por qué |
|---|---|---|---|
| `NEWS_MAX_BUSQUEDAS_DIA` (Tavily) | 120 | **250** | radar directo 40 jugadores × 2–3 idiomas por ciclo, con cupo menores, + temático 48/día |
| `NEWS_RADAR_TEMATICO_BUSQUEDAS` | — | 12 cada 6 h | 48/día cubren lesión/retiro/regreso en 5 idiomas |
| `NEWS_MAX_USD_MES` | 100 | 100 (sin cambio) | sigue sobrando |

Estimación con todo encendido: Tavily 250 × US$ 0,008 × 30 ≈ **US$ 60/mes**
(si el plan tiene créditos incluidos, menos); clasificador: ~150
artículos/día × ~US$ 0,002 (Haiku) ≈ **US$ 9/mes** (Gemini Flash ≈ 3); total
**≈ US$ 50–70/mes**, dentro del tope. Si Rubén prefiere más cobertura ITF/UTR:
`NEWS_RADAR_CUPO_MENORES_PCT=50` y `NEWS_MAX_BUSQUEDAS_DIA=350` (≈ +US$ 25).

## 8. Lo que NO cambia

Sin Elo ni FTR. Cuota Mal Puesta, UTR Value, UTR Anomalía y FT Discord no
se tocan. FT Intelligence solo aprende a transportar la experimental
(v18, ver su CAMBIOS). Nada se lee de fuentes sin autorizar (sin fuentes
nuevas en esta entrega: `FUENTES-AUTORIZACION.md` sigue siendo la lista de
pendientes a revisar).

## Pruebas

`tests/test_v5_alertas.py` (nuevo, 13): 📰 con motivo y sin partido; no se
repite salvo info nueva y tope; 🔎 investiga al rival y explica; contexto
interno solo no da ni 🔎 ni 📰; 🔥 experimental con evidencia y explicaciones
(y `NEWS_EXPERIMENTAL_ACTIVO=0` la retiene); cola con cupo y a demanda;
radar temático cruza el padrón y emite 📰 (segunda corrida no paga);
RSS contra todo el padrón; `buscar_en_texto`; historial / vencimiento /
desmentido; fusión de duplicados una sola vez; endpoints (senales, alertas,
diagnóstico, buscador, memoria, hoy, estado, DESMENTIR). Recorrido Fase 1
actualizado (📰 + 🔥 experimental → validada supera a la experimental).
`pytest tests`: **72 OK**.

## Despliegue

Sin variables nuevas obligatorias. Al arrancar crea `news_alerta`,
`news_partido_fuente`, `news_evento_historial` y las columnas nuevas; la
fusión de duplicados corre sola una vez. Subir **FT_INTELLIGENCE v18** junto
(sin él, la 🔥 experimental y las 📰 sin partido no se transportan: v17 las
ignora, no rompe). RankingFTR v38 trae el panel en la pestaña.

## Archivos tocados (v5 sobre v4)

- `ft_news/__init__.py` (versión), `ft_news/alertas.py` (nuevo),
  `ft_news/app.py`, `ft_news/config.py`, `ft_news/db.py`,
  `ft_news/descubridor.py`, `ft_news/evaluador.py`, `ft_news/jugadores.py`,
  `ft_news/memoria.py`, `ft_news/partidos.py`, `ft_news/radar.py`,
  `ft_news/tareas.py`, `ft_news/textos.py`, `ft_news/lectores/rss.py`
- `tests/test_v5_alertas.py` (nuevo), `tests/test_descubridor.py`,
  `tests/test_recorrido_fase1.py`, `tests/test_segunda_entrega.py`
- `README.md`, este archivo
