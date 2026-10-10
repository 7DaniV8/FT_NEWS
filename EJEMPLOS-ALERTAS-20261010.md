# Recorrido FT NEWS → FT Intelligence → FT Discord (código real, fuentes simuladas)

Generado 2026-10-10T06:36 UTC. Sin claves ni red: Tavily, el clasificador y RankingFTR
están simulados con el formato real de cada API; FT Intelligence y FT Discord corren con su código tal cual.

## FT NEWS

- ciclo 1: radar {'jugadores': 6, 'busquedas': 12, 'articulos_nuevos': 3, 'eventos': 3, 'revision': 0, 'descartados': 0, 'alertas': 3, 'menores': 6, 'motivo': None} · descubridor {'partidos': 3, 'evaluados': 3, 'FUEGO': 0, 'FUEGO_EXPERIMENTAL': 0, 'INTERESANTE': 3, 'NADA': 0, 'alertas': 3} · costos 0.0976 US$
- ciclo 2: radar {'jugadores': 0, 'busquedas': 0, 'articulos_nuevos': 0, 'eventos': 0, 'revision': 0, 'descartados': 0, 'alertas': 0, 'menores': 0, 'motivo': None} · descubridor {'partidos': 3, 'evaluados': 3, 'FUEGO': 0, 'FUEGO_EXPERIMENTAL': 1, 'INTERESANTE': 2, 'NADA': 0, 'alertas': 1} · costos 0.0976 US$

Búsquedas Tavily: 12 · llamadas al clasificador: 3

### Alertas seleccionadas (news_alerta)

- **NOTICIA** · Mateo Quiroga vs Luca Bertolini · dicho_discord=1
  - por qué (usuario): Noticia importante confirmada (lesión o molestia) sobre Mateo Quiroga.
  - por qué (técnico, admin): noticia externa LESION_MOLESTIA nivel B (hecho) de puntodebreak.com, hecho del 2026-10-08, identidad 0.95; próximo partido vs Luca Bertolini 2026-10-10T12:00
- **NOTICIA** · Valentina Soler vs Hanna Kowal · dicho_discord=1
  - por qué (usuario): Noticia importante confirmada (lesión o molestia) sobre Valentina Soler.
  - por qué (técnico, admin): noticia externa LESION_MOLESTIA nivel B (declaracion) de puntodebreak.com, hecho del 2026-10-08, identidad 0.92; próximo partido vs Hanna Kowal 2026-10-10T17:00
- **NOTICIA** · Tom Whitlock vs Nicolás Ferreyra · dicho_discord=1
  - por qué (usuario): Noticia importante confirmada (retiro o abandono) sobre Tom Whitlock.
  - por qué (técnico, admin): noticia externa RETIRO_ABANDONO nivel B (hecho) de tennistourtalk.com, hecho del 2026-10-09, identidad 0.97; próximo partido vs Nicolás Ferreyra 2026-10-11T11:00
- **INTERESANTE** · Mateo Quiroga vs Luca Bertolini · dicho_discord=2 (SUPERADA_POR_FUEGO_EXPERIMENTAL)
  - por qué (usuario): Noticia externa (lesión o molestia) y los dos jugadores investigados. Pendiente: ⏳ cuota actualizada después de la noticia (09/10 13:00 UTC); última cuota confirmada 09/10 11:00 UTC (FIXTURES_FTR) — pendiente de actualización.
  - por qué (técnico, admin): noticia externa LESION_MOLESTIA nivel B en Mateo Quiroga; Mateo Quiroga: investigado hace 0.0 h (2 búsqueda(s), 1 artículo(s), 1 noticia(s) externa(s)); Luca Bertolini: investigado hace 0.0 h (2 búsqueda(s), 0 artículo(s), 0 noticia(s) externa(s)); motivo del descubridor: CUOTA_SIN_ACTUALIZAR
- **INTERESANTE** · Valentina Soler vs Hanna Kowal · dicho_discord=1
  - por qué (usuario): Noticia externa (lesión o molestia) y los dos jugadores investigados. Pendiente: ⏳ cuota actualizada después de la noticia (09/10 12:00 UTC); última cuota confirmada 09/10 11:00 UTC (FIXTURES_FTR) — pendiente de actualización; confirmar la declaración con un hecho u otra fuente.
  - por qué (técnico, admin): noticia externa LESION_MOLESTIA nivel B en Valentina Soler; Valentina Soler: investigado hace 0.0 h (2 búsqueda(s), 1 artículo(s), 1 noticia(s) externa(s)); Hanna Kowal: investigado hace 0.0 h (2 búsqueda(s), 0 artículo(s), 0 noticia(s) externa(s)); motivo del descubridor: CUOTA_SIN_ACTUALIZAR
- **INTERESANTE** · Tom Whitlock vs Nicolás Ferreyra · dicho_discord=1
  - por qué (usuario): Noticia externa (retiro o abandono) y los dos jugadores investigados. Pendiente: ⏳ cuota actualizada después de la noticia (09/10 14:00 UTC); última cuota confirmada 09/10 11:00 UTC (FIXTURES_FTR) — pendiente de actualización.
  - por qué (técnico, admin): noticia externa RETIRO_ABANDONO nivel B en Tom Whitlock; Tom Whitlock: investigado hace 0.0 h (2 búsqueda(s), 1 artículo(s), 1 noticia(s) externa(s)); Nicolás Ferreyra: investigado hace 0.0 h (2 búsqueda(s), 0 artículo(s), 0 noticia(s) externa(s)); motivo del descubridor: RETIRO_MISMO_TORNEO
- **FUEGO_EXPERIMENTAL** · Mateo Quiroga vs Luca Bertolini · dicho_discord=1
  - por qué (usuario): Noticia externa fuerte, UTR y cuota comparados: la cuota todavía no parece reflejar la noticia (lectura experimental).
  - por qué (técnico, admin): EXPERIMENTAL (bandas sin validar): noticia externa LESION_MOLESTIA nivel B · UTR 12.85 vs 12.41 (FAVORITO) · mercado FAVORITO (1.42) · ALINEADO · lado CONTRA_X; explicaciones posibles: bandas UTR/cuota todavía sin validar con datos propios (señal experimental) · justificación: cuota confirmada después de la noticia (09/10 13:00 UTC): Mateo Quiroga sigue en 1.42 (antes 1.42; FIXTURES_FTR, 09/10 15:05 UTC): el mercado no reaccionó todavía; a favor: hecho reportado por prensa fiable (puntodebreak.com); circuito challenger: mercado menos líquido, suele tardar en incorporar noticias; en contra: banda UTR y mercado alineados: la ventaja, si existe, está solo en la noticia; balance +4 (mínimo 2)

### Evaluaciones · lectura simple (v7, lo que ve el usuario)

- evaluación #1 · técnico: FUEGO_EXPERIMENTAL / CONTRA_X
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

- evaluación #2 · técnico: INTERESANTE / MERCADO_EN_MOVIMIENTO
```
🔎 FULLTENNIS · PARTIDO EN ANÁLISIS
🎾 Valentina Soler vs Hanna Kowal
🏆 W75 Reus
📊 UTR: 10.62 vs 10.20
💰 Soler 1.80 | Kowal 2.00
⚖️ NIVEL: Soler parte ligeramente por encima por UTR.
🚨 NOTICIA: Soler — Molestias en el hombro.
🔴 PERJUDICA A: Valentina Soler
🟢 PODRÍA FAVORECER A: HANNA KOWAL @2.00
🧭 CONCLUSIÓN: La cuota ya se está moviendo en la dirección de la noticia.
```

- evaluación #3 · técnico: INTERESANTE / RETIRO_MISMO_TORNEO
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


## FT Intelligence

- pasada 1: news: 6 recibida(s), 6 emitida(s), 6 reportada(s)
- pasada 2: news: 0 recibida(s), 0 emitida(s), 0 reportada(s)
- señales guardadas: [('NEWS_NOTICIA', 'news:NOTICIA:1'), ('NEWS_NOTICIA', 'news:NOTICIA:2'), ('NEWS_NOTICIA', 'news:NOTICIA:3'), ('NEWS_INTERESANTE', 'news:INTERESANTE:5'), ('NEWS_INTERESANTE', 'news:INTERESANTE:6'), ('NEWS_VALOR', 'news:FUEGO_EXPERIMENTAL:7')]

## FT Discord

- ciclo 1: {'texto': 6, 'voz': 6, 'viejas': 0, 'voz_omitida': 0, 'errores': 0, 'agrupadas': 0, 'apagadas': 0}
- ciclo 2: {'texto': 0, 'voz': 0, 'viejas': 0, 'voz_omitida': 0, 'errores': 0, 'agrupadas': 0, 'apagadas': 0}

### Mensajes publicados (tal cual irían al canal)

```
**📰 FULLTENNIS · NOTICIA IMPORTANTE**
🎾 Mateo Quiroga
🏆 Challenger Lima
📊 UTR: 12.85
🚨 LESIÓN: Molestias en el tobillo derecho.
🔴 PERJUDICA A: MATEO QUIROGA
🟢 PODRÍA FAVORECER A: LUCA BERTOLINI
💰 Quiroga 1.42 | Bertolini 2.85
🕐 partido <t:1791633600:R> · _investigación de noticias; no es una recomendación_
```

```
**📰 FULLTENNIS · NOTICIA IMPORTANTE**
🎾 Valentina Soler
🏆 W75 Reus
📊 UTR: 10.62
🚨 LESIÓN: Molestias en el hombro.
🔴 PERJUDICA A: VALENTINA SOLER
🟢 PODRÍA FAVORECER A: HANNA KOWAL
💰 Soler 1.65 | Kowal 2.20
🕐 partido <t:1791651600:R> · _investigación de noticias; no es una recomendación_
```

```
**📰 FULLTENNIS · NOTICIA IMPORTANTE**
🎾 Tom Whitlock
🏆 M25 Sevilla
📊 UTR: 11.05
🚨 RETIRO: Se retiró del M25 de Sevilla por la muñeca.
🔴 PERJUDICA A: TOM WHITLOCK
⚠️ El partido podría no jugarse (retiro en el mismo torneo).
💰 Whitlock 1.90 | Ferreyra 1.90
🕐 partido <t:1791716400:R> · _investigación de noticias; no es una recomendación_
```

```
**🔎 FULLTENNIS · PARTIDO INTERESANTE**
🎾 Valentina Soler vs Hanna Kowal
🏆 W75 Reus
📊 UTR: 10.62 vs 10.20
💰 Cuotas: 1.65 vs 2.20
🚨 NOTICIA: Molestias en el hombro.
🟢 PODRÍA FAVORECER A: HANNA KOWAL @2.20
⏳ Pendiente de confirmar la reacción del mercado.
🕐 partido <t:1791651600:R> · _investigación de noticias; no es una recomendación_
```

```
**🔎 FULLTENNIS · PARTIDO INTERESANTE**
🎾 Tom Whitlock vs Nicolás Ferreyra
🏆 M25 Sevilla
📊 UTR: 11.05 vs 11.30
💰 Cuotas: 1.90 vs 1.90
🚨 NOTICIA: Se retiró del M25 de Sevilla por la muñeca.
⚠️ El partido podría no jugarse (retiro en el mismo torneo).
🕐 partido <t:1791716400:R> · _investigación de noticias; no es una recomendación_
```

```
**🔥 FULLTENNIS · POSIBLE VALOR EXPERIMENTAL**
🎾 Luca Bertolini vs Mateo Quiroga
🏆 Challenger Lima
📊 UTR: 12.41 vs 12.85
🟢 JUGADOR FAVORECIDO: LUCA BERTOLINI
💰 CUOTA: 2.85
🚨 MOTIVO: Molestias en el tobillo derecho.
📈 La cuota de Quiroga sigue en 1.42 después de la noticia.
⚠️ Posible oportunidad sin validar estadísticamente.
🕐 partido <t:1791633600:R> · _investigación de noticias; no es una recomendación_
```

### Frases de voz

- Atención FullTennis. Noticia. Noticia importante. Quiroga: Molestias en el tobillo derecho. Podría favorecer a Bertolini, cuota 2.85.
- Atención FullTennis. Noticia. Noticia importante. Soler: Molestias en el hombro. Podría favorecer a Kowal, cuota 2.20.
- Atención FullTennis. Noticia. Noticia importante. Whitlock: Se retiró del M25 de Sevilla por la muñeca.
- Atención FullTennis. Noticia. Partido interesante. Soler contra Kowal. Soler: Molestias en el hombro. Podría favorecer a Kowal, cuota 2.20.
- Atención FullTennis. Noticia. Partido interesante. Whitlock contra Ferreyra. Whitlock: Se retiró del M25 de Sevilla por la muñeca.
- Atención FullTennis. Noticia. Posible valor experimental, sin validar. Bertolini, cuota 2.85, contra Quiroga. Molestias en el tobillo derecho.