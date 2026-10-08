# 📰 FT NEWS INTELLIGENCE — Informe de calibración de bandas UTR / cuota (Fase 0)

**Fecha:** 08/10/2026 · **Estado:** método y herramienta listos; **corrida sobre datos de producción pendiente** (se corre desde la pestaña 📰 FT NEWS de RankingFTR o con `herramientas/calibrar_bandas.py`).
**Decisión que depende de este informe:** `NEWS_BANDAS_CALIBRADAS` (hoy = 0). Mientras sea 0, el descubridor **nunca** emite 🔥 ni afirma que el mercado "no descontó" una noticia: todo queda en 🔎 con motivo `BANDAS_NO_CALIBRADAS`.

## 1. Qué se calibra y por qué

El descubridor v2 (diseño §4) no usa un umbral de cuota: compara la **banda de expectativa por UTR** (ΔUTR entre los dos jugadores) con la **banda de expectativa del mercado** (cuota) y mira si el desvío entre ambas va a favor o en contra de la noticia. Eso solo tiene sentido si, **sin ninguna noticia**, las dos bandas se corresponden la mayoría de las veces. Si el mercado y el UTR discrepan a menudo por sí solos, un desvío no es evidencia de nada (riesgo R14 del diseño).

Por eso, antes de confiar en las bandas, se mide con partidos propios:

| Pregunta | Cómo se mide | Criterio para aprobar |
|---|---|---|
| ¿Hay datos suficientes? | partidos de `utr_value_registro` con UTR de ambos y cuota | ≥ 300 en total y ≥ 40 en cada banda central (PAREJO, FAVORITO, MUY_FAVORITO) |
| ¿Cada banda UTR cae en la banda de mercado que le corresponde? | para cada banda UTR: cuota mediana de A, banda de mercado moda, fracción de partidos a ≤ 1 paso de la esperada | ≥ 60 % a ≤ 1 paso en cada banda central |
| ¿El desvío es la excepción o la regla? | fracción de partidos ALINEADOS (misma banda) | ≥ 55 % alineados |
| ¿Las bandas ordenan? | frecuencia observada con que ganó el UTR superior, por banda (≥ 20 resultados por banda) | crece de PAREJO a MUY_FAVORITO |

Todo son **frecuencias observadas**, no probabilidades: el informe dice si las bandas ordenan bien, no cuánto va a ganar nadie. La palabra "probabilidad" no aparece en el informe (lo verifica `tests/test_news_fase0.py`).

**Fuente de datos:** `utr_value_registro` (motor UTR VALUE de RankingFTR), que guarda para cada partido visto con UTR de los dos jugadores el ΔUTR, la cuota de la primera vista, la de cierre y el ganador. Es solo lectura; la calibración no escribe nada.

**Límite conocido:** esa tabla está orientada al UTR superior (ΔUTR ≥ 0), así que las bandas NO_FAVORITO / MUY_NO_FAVORITO (jugador con noticia *positiva* en cuota larga) **no se pueden calibrar todavía**. Quedan con los cortes propuestos y se revisan cuando el motor tenga sus primeros casos (Fase 3).

## 2. Cortes propuestos (punto de partida, diseño D-BANDAS)

- ΔUTR: PAREJO < 0,30 · FAVORITO < 0,80 · MUY_FAVORITO < 1,50 · ABISMO ≥ 1,50
- Cuota: MUY_FAVORITO ≤ 1,35 · FAVORITO ≤ 1,75 · PAREJO ≤ 2,30 · NO_FAVORITO ≤ 3,50 · más → MUY_NO_FAVORITO

Son editables (`NEWS_BANDA_*` en FT_NEWS / Admin → Estrategias). El informe propone, si hay muestra, los cortes de cuota que salen de las medianas reales.

## 3. Cómo correrlo sobre producción

1. Desplegar RankingFTR v25 (este ZIP). No cambia nada de lo existente; agrega dos lecturas y la pestaña.
2. Entrar como admin a Research → 📰 FT NEWS → **🔄 Recalcular**. Aparece el veredicto, la tabla por banda, la línea base y los cortes sugeridos. **📄 Informe (Markdown)** descarga este mismo informe con datos reales.
3. O por línea de comandos: `FTR_SERVICE_URL=… FTR_INTERNAL_SECRET=… python herramientas/calibrar_bandas.py --salida INFORME-CALIBRACION.md`.
4. Si el veredicto es `CALIBRADAS_OK`, Rubén decide poner `NEWS_BANDAS_CALIBRADAS=1` (no lo hace el script). Si es `NO_CALIBRADAS`, el informe dice qué falló: esperar más partidos, ajustar cortes con los sugeridos y volver a correr.

## 4. Corridas de demostración (datos SINTÉTICOS — no son datos de FullTenis)

Sirven para ver el formato y comprobar que los criterios discriminan. La demo A es una muestra generada coherente con los cortes (15 % de ruido); la demo B es la misma generación con 80 partidos. El test también cubre un caso con el mercado "al revés" del UTR → `NO_CALIBRADAS` por alineación.

<!-- DEMO A: 600 partidos SINTÉTICOS coherentes -->
# Calibración de bandas UTR/cuota — CALIBRADAS_OK

Generado: 2026-10-08T20:58:47.331067+00:00 · versión news-calibracion-fase0 · muestra: 600 partidos
Cortes ΔUTR: [0.3, 0.8, 1.5] · cortes cuota: [1.35, 1.75, 2.3, 3.5]

## Por banda de ΔUTR (jugador A = UTR superior)

| Banda UTR | n | cuota mediana A | p25–p75 | banda mercado esperada | moda | a ≤1 paso | ganó A (frec.) | n res. | A fav. mercado |
|---|---|---|---|---|---|---|---|---|---|
| PAREJO | 99 | 2.02 | 1.86–2.14 | PAREJO | PAREJO | 100% | 55% | 99 | 37% |
| FAVORITO | 175 | 1.57 | 1.46–1.66 | FAVORITO | FAVORITO | 100% | 63% | 175 | 98% |
| MUY_FAVORITO | 230 | 1.23 | 1.17–1.28 | MUY_FAVORITO | MUY_FAVORITO | 100% | 71% | 230 | 100% |
| ABISMO | 96 | 1.11 | 1.07–1.16 | MUY_FAVORITO | MUY_FAVORITO | 100% | 76% | 96 | 100% |

## Desvío mercado–UTR sin noticia (línea base)

- Alineados: 553 · mercado más optimista con A: 15 · más pesimista: 32 · fracción alineados: 92%

## Cortes de cuota sugeridos por los datos

- [1.4, 1.79, 2.3, 3.5] — Solo los dos primeros cortes salen de datos (bandas con UTR superior como favorito); PAREJO/NO_FAVORITO se mantienen hasta tener partidos con noticia positiva en cuota larga.

## Notas
- Frecuencias observadas, no probabilidades; sirven para ver si las bandas ordenan, no para predecir.
- utr_value_registro guarda la cuota de la PRIMERA vista; la de cierre (cuota_cierre_a) se usa solo si existe.
- Partidos con UTR por intervalo (fuente_utr=INTERVALO) entran con el punto medio del intervalo: ruido conocido.
- La fuente está orientada al UTR superior (ΔUTR ≥ 0): las bandas NO_FAVORITO / MUY_NO_FAVORITO no se pueden calibrar con estos datos; quedan con los cortes propuestos hasta tener casos de noticia positiva en cuota larga.


<!-- DEMO B: 80 partidos SINTÉTICOS (muestra chica) -->
# Calibración de bandas UTR/cuota — NO_CALIBRADAS

Generado: 2026-10-08T20:58:47.332253+00:00 · versión news-calibracion-fase0 · muestra: 80 partidos
Cortes ΔUTR: [0.3, 0.8, 1.5] · cortes cuota: [1.35, 1.75, 2.3, 3.5]

## Por qué NO se pueden dar por calibradas
- Muestra insuficiente: 80 partidos (mínimo 300).
- Banda PAREJO: 8 partidos (mínimo 40).
- Banda FAVORITO: 21 partidos (mínimo 40).
- Banda MUY_FAVORITO: 36 partidos (mínimo 40).

## Por banda de ΔUTR (jugador A = UTR superior)

| Banda UTR | n | cuota mediana A | p25–p75 | banda mercado esperada | moda | a ≤1 paso | ganó A (frec.) | n res. | A fav. mercado |
|---|---|---|---|---|---|---|---|---|---|
| PAREJO | 8 | 2.0 | 1.86–2.14 | PAREJO | PAREJO | 100% | 62% | 8 | 50% |
| FAVORITO | 21 | 1.55 | 1.44–1.63 | FAVORITO | FAVORITO | 100% | 62% | 21 | 100% |
| MUY_FAVORITO | 36 | 1.215 | 1.17–1.26 | MUY_FAVORITO | MUY_FAVORITO | 100% | 75% | 36 | 100% |
| ABISMO | 15 | 1.13 | 1.1–1.19 | MUY_FAVORITO | MUY_FAVORITO | 100% | 80% | 15 | 100% |

## Desvío mercado–UTR sin noticia (línea base)

- Alineados: 72 · mercado más optimista con A: 2 · más pesimista: 6 · fracción alineados: 90%

## Notas
- Frecuencias observadas, no probabilidades; sirven para ver si las bandas ordenan, no para predecir.
- utr_value_registro guarda la cuota de la PRIMERA vista; la de cierre (cuota_cierre_a) se usa solo si existe.
- Partidos con UTR por intervalo (fuente_utr=INTERVALO) entran con el punto medio del intervalo: ruido conocido.
- La fuente está orientada al UTR superior (ΔUTR ≥ 0): las bandas NO_FAVORITO / MUY_NO_FAVORITO no se pueden calibrar con estos datos; quedan con los cortes propuestos hasta tener casos de noticia positiva en cuota larga.

## 5. Qué falta para cerrar este punto

- [ ] Corrida sobre producción (Rubén o Daniel, desde la pestaña).
- [ ] Revisar las razones si sale `NO_CALIBRADAS`; acordar cortes.
- [ ] Decisión explícita de `NEWS_BANDAS_CALIBRADAS=1` (queda registrada en `news_config` con quién y cuándo).
- [ ] Repetir mensualmente con el RESUMEN (R14): los cortes se revisan, no se fijan para siempre.
