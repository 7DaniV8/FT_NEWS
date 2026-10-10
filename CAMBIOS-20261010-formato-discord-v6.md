# CAMBIOS — 10/10/2026 — FT_NEWS v6: formatos definitivos de Discord y activación de las tres alertas

Pedido de Rubén (09/10/2026 23:13): mensajes más cortos, fáciles de entender,
con el JUGADOR FAVORECIDO en MAYÚSCULAS y su cuota al lado; sin enlaces (las
fuentes quedan guardadas para verificar); mismos formatos para ATP/WTA,
Challenger, ITF y UTR; **solo cambia la presentación, no las reglas de
selección** (siguen las de v5.2). Y activar las tres alertas.

## Los formatos (`ft_news/textos.py`)

```
📰 FULLTENNIS · NOTICIA IMPORTANTE        🔎 FULLTENNIS · PARTIDO INTERESANTE      🔥 FULLTENNIS · POSIBLE VALOR EXPERIMENTAL
🎾 Mateo Quiroga                           🎾 Valentina Soler vs Hanna Kowal         🎾 Luca Bertolini vs Mateo Quiroga
🏆 Challenger Lima                         🏆 W75 Reus                               🏆 Challenger Lima
📊 UTR: 12.85                              📊 UTR: 10.62 vs 10.20                    📊 UTR: 12.41 vs 12.85
🚨 LESIÓN: Molestias en el tobillo derecho. 💰 Cuotas: 1.65 vs 2.20                  🟢 JUGADOR FAVORECIDO: LUCA BERTOLINI
🔴 PERJUDICA A: MATEO QUIROGA              🚨 NOTICIA: Molestias en el hombro.       💰 CUOTA: 2.85
🟢 PODRÍA FAVORECER A: LUCA BERTOLINI      🟢 PODRÍA FAVORECER A: HANNA KOWAL @2.20  🚨 MOTIVO: Molestias en el tobillo derecho.
💰 Quiroga 1.42 | Bertolini 2.85           ⏳ Pendiente de confirmar la reacción     📈 La cuota de Quiroga sigue en 1.42 después de la noticia.
                                              del mercado.                           ⚠️ Posible oportunidad sin validar estadísticamente.
```

Reglas de presentación:
- **Favorecido**: 📰 con noticia NEGATIVA y partido → PERJUDICA A: X y PODRÍA
  FAVORECER A: RIVAL; POSITIVA → FAVORECE A: X; mixta/neutra → AFECTA A: X **sin
  favorecido**. 🔎: el favorecido sale de la dirección de las noticias de los
  dos (negativa en X → rival @cuota; negativa en los dos → "⚪ Noticias en los
  dos: sin favorecido claro"; retiro del mismo torneo → sin favorecido y "⚠️ El
  partido podría no jugarse"). 🔥: el lado del valor del descubridor (CONTRA_X
  → rival) con su cuota. Si no hay evidencia, no se nombra a nadie.
- **Última línea de la 🔎** según el motivo real: "⏳ Pendiente de confirmar la
  reacción del mercado." (cuota sin actualizar), "📉 El mercado parece haber
  incorporado la noticia.", "⚠️ El partido podría no jugarse (retiro en el
  mismo torneo).", "⏳ Pendiente de investigar al rival.", "⚠️ Sin evidencia
  suficiente de valor en la cuota.", …
- **🔥 validada** (cuando Rubén habilite las bandas): encabezado "POSIBLE VALOR
  POR NOTICIAS" y última línea "✅ Lectura UTR/cuota validada con datos
  propios". Mientras, siempre **EXPERIMENTAL**; FT Discord v11 no deja que un
  encabezado personalizado de Admin le quite la etiqueta.
- **Sin enlaces**: `hay_prohibido()` ahora también rechaza `http(s)://`. Fuente,
  enlace, confirmación, justificación y frescura siguen en
  `news_alerta.evidencia_json` / `motivo_seleccion` (pestaña Alertas) y en
  `news_evento`.
- **Titular corto**: el clasificador (Gemini y Claude) devuelve además
  `titular` (≤ 60 caracteres, el hecho sin el nombre: "Molestias en el tobillo
  derecho"); se guarda en `news_evento.titular` y es lo que va en 🚨. Si no
  viene, se usa la primera frase del resumen recortada.
- **Voz**, corta: "Noticia importante. Quiroga: molestias en el tobillo derecho.
  Podría favorecer a Bertolini, cuota 2.85." / "Partido interesante. Soler
  contra Kowal. …" / "Posible valor experimental, sin validar. Bertolini, cuota
  2.85, contra Quiroga. …". FT Discord antepone "Atención FullTennis. Noticia."

## Activación

- FT_NEWS: `NEWS_DISCORD_ACTIVO` nace en **1** (si en `news_config` quedó en 0,
  encenderlo en Admin → FT NEWS). Vencimiento de pendientes > 12 h sigue.
- FT_DISCORD **v11**: `NEWS_VALOR`, `NEWS_INTERESANTE`, `NEWS_NOTICIA` de fábrica
  con texto y voz; la 🔥 EXPERIMENTAL conserva la etiqueta ante un encabezado
  personalizado.
- RankingFTR v38: Admin → Discord, las tres de FT NEWS en 1/1 por defecto,
  descripciones y encabezados FULLTENNIS.
- Filtros de calidad, dedupe y cobertura de circuitos: sin cambios (v5.2).
- `herramientas/verificar_real.py`: comprobación en producción de los tres
  servicios con noticias y cuotas reales (ver `DESPLIEGUE-v5.md` §4).

## Pruebas

Las de texto se reescribieron al formato nuevo (descubridor, recorrido Fase 1,
v5, v5.1, recorrido Discord). `pytest tests`: **88 OK** (con FT_INTELLIGENCE y
FT_DISCORD al lado). FT Discord v11: 8 OK en `test_news.py`, suite TODO OK.
RankingFTR `test_discord_config.py` +1.

## Archivos tocados (v6 sobre v5.2)

- `ft_news/__init__.py`, `ft_news/textos.py` (reescrito), `ft_news/alertas.py`,
  `ft_news/config.py`, `ft_news/db.py`, `ft_news/evaluador.py`,
  `ft_news/memoria.py`, `ft_news/radar.py`, `ft_news/proveedores/gemini.py`,
  `ft_news/proveedores/claude.py`, `herramientas/recorrido_discord.py`,
  `herramientas/verificar_real.py` (nuevo), `EJEMPLOS-ALERTAS-20261010.md`
- `tests/test_descubridor.py`, `tests/test_recorrido_fase1.py`,
  `tests/test_v5_alertas.py`, `tests/test_v51_justificacion.py`,
  `tests/test_recorrido_discord.py`, `tests/test_apagado_y_fuentes.py`
- `README.md`, `DESPLIEGUE-v5.md`, este archivo
