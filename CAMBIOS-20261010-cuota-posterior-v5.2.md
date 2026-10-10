# CAMBIOS — 10/10/2026 — FT_NEWS v5.2: la 🔥 exige una cuota confirmada DESPUÉS de la noticia

Corrección de Rubén (09/10/2026 22:52): "que una noticia sea posterior a nuestra
última cuota registrada no significa que el mercado todavía no la haya
incorporado". Va sobre v5.1. FT_INTELLIGENCE v18, RankingFTR v38 y FT_DISCORD v10
no cambian de contrato (RankingFTR solo muestra el cupo sugerido en la pestaña).

## Qué cambia

- **`partidos.cuota_antes_y_despues(partido, jugador, momento)`**: la cuota del
  jugador vigente ANTES de la noticia y la CONFIRMADA DESPUÉS (un precio visto
  con `hasta_en` > noticia). Para eso `news_cuota_obs` suma `hasta_en`: cuando
  RankingFTR trae el mismo precio otra vez, no se duplica la observación pero sí
  se corre `hasta_en` → "este precio seguía vigente a tal hora". La cuota
  vigente del partido es la de `hasta_en` más reciente.
- **`alertas.justificar`** reemplaza "la noticia es posterior a la última cuota"
  (ya no cuenta como información no reflejada) por:
  - **sin cuota confirmada después de la noticia** → la 🔥 **no sale**: queda
    **🔎 PARTIDO INTERESANTE pendiente de actualización** (motivo
    `CUOTA_SIN_ACTUALIZAR`; en el texto "⏳ cuota actualizada después de la
    noticia (hh:mm UTC); última cuota confirmada hh:mm UTC (proveedor) —
    pendiente de actualización"). Se reevalúa en cada ciclo; cuando llega el
    precio confirmado después de la noticia, decide.
  - **cuota después de la noticia igual a la de antes** (movimiento <
    `NEWS_EXP_MOV_CUOTA_PCT`) → 📌 "cuota confirmada después de la noticia: X
    sigue en 1.42 (antes 1.42; proveedor, hh:mm UTC): el mercado no reaccionó
    todavía" (+2).
  - **cuota que ya se movió hacia la noticia** → ⚖️ "el mercado ya incorporó la
    noticia: X 1.40 → 1.60 (proveedor, hh:mm UTC)" (−3) → 🔎.
  - **sin cuota previa a la noticia** (la primera que vimos ya es posterior) → no
    se puede medir la reacción: ⚖️; solo suma si además el precio va contra el
    UTR (`MERCADO_MAS_OPTIMISTA` para CONTRA_X) (+1) → en la práctica 🔎.
- Una 🔎 del mismo partido **todavía no dicha** (típicamente la "pendiente de
  cuota") queda `SUPERADA_POR_FUEGO_EXPERIMENTAL` cuando llega la 🔥; si ya se
  dijo, la 🔥 sale igual (trae la cuota confirmada). Igual que experimental →
  validada.
- Presupuesto (`cobertura.presupuesto`): además del tope propuesto, el **cupo
  sugerido para circuitos menores** (`cupo_menores_sugerido`, tope 70 %) si los
  menores necesitan más búsquedas que el cupo actual. Se ve en la pestaña.

## Cómo se ve en el recorrido (`EJEMPLOS-ALERTAS-20261010.md`)

Ciclo 1 (la única cuota es de antes de las noticias): 📰 ×3 y 🔎 ×3 "pendiente
de actualización de cuota". Ciclo 2 (RankingFTR confirma las cuotas 15 min
después): Quiroga sigue 1.42 → **🔥 experimental** (y su 🔎 pendiente queda
superada); Soler 1.65 → 1.80 → la evaluación pasa a "el mercado ya incorporó la
noticia" (🔎); Whitlock → "retiro del mismo torneo" (🔎). FT Intelligence y FT
Discord: 6 mensajes, segundo ciclo nada.

## Pruebas

`tests/test_v51_justificacion.py` +1 (`test_sin_cuota_posterior_a_la_noticia_es_interesante_pendiente`),
recorrido Fase 1 y recorrido Discord actualizados a la regla nueva.
`pytest tests`: **88 OK** (con FT_INTELLIGENCE y FT_DISCORD al lado).

## Archivos tocados (v5.2 sobre v5.1)

- `ft_news/__init__.py`, `ft_news/alertas.py`, `ft_news/cobertura.py`,
  `ft_news/db.py`, `ft_news/evaluador.py`, `ft_news/partidos.py`,
  `ft_news/textos.py`, `herramientas/recorrido_discord.py`,
  `EJEMPLOS-ALERTAS-20261010.md` (generado; reemplaza al del 09/10)
- `tests/test_v51_justificacion.py`, `tests/test_v5_alertas.py`,
  `tests/test_recorrido_fase1.py`, `tests/test_recorrido_discord.py`
- `README.md`, `DESPLIEGUE-v5.md`, este archivo
