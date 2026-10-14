# FT NEWS v7.5 · Cinco correcciones de alertas (13/10/2026, caso Andrade Da Silva)

El 13/10 salió un 🔎 «Lucas Andrade Da Silva vs Victor Bini» con «Derrota por walkover en dobles» (hecho del 07/10, ya
avisado como 📰 el 12/10, leído de una página del stats centre de atptour.com que trajo el buscador) y «podría favorecer
a Victor Bini @13.22», aunque el propio FT NEWS había concluido que el mercado ya tenía la noticia. Rubén aprobó:

1. **Dobles fuera de las noticias fuertes** (`taxonomia.es_dobles` / `es_fuerte_evento`): un resultado de dobles (walkover,
   retiro o derrota) se guarda como contexto, pero no es noticia fuerte: no dispara 📰, 🔎 ni 🔥, ni cuenta como evidencia.
2. **Un mismo hecho no vuelve a Discord en otra alerta del mismo tipo** (`alertas.hechos_ya_avisados`): un hecho sale una
   vez como 📰 y una vez como 🔎 del partido al que afecta; no vuelve en cada ronda mientras siga vigente (un retiro vale
   21 días). Las omitidas y las pruebas no cuentan. La 🔥 no pasa por acá: trae información nueva (la oportunidad).
3. **Sin 🔎 cuando FT NEWS concluye que no hay nada**: con motivo «el mercado ya tiene la noticia»
   (`SIN_INFORMACION_NO_REFLEJADA`, `MERCADO_YA_DESCONTO`) el partido se guarda y se ve en la portada, pero no sale a Discord.
4. **atptour.com, wtatennis.com e itftennis.com solo por su RSS oficial** (`fuentes.solo_rss`): el buscador ya no las
   pide (ahorra créditos) y una página suya que llegue por el buscador no se lee.
5. **La confirmación dice qué está confirmado** (`textos.fiabilidad`): «✅ Walkover confirmado por ATP Tour; el motivo no se
   informó.» — un retiro o walkover confirmado no se presenta como lesión confirmada.

Motivos nuevos en «qué se descartó y por qué»: DOBLES, HECHO_YA_AVISADO, MERCADO_YA_LO_REFLEJA.
No se bajó ningún filtro; no se tocan otros bots. Pruebas: `tests/test_v75_andrade.py` (6) y
`tests/test_v51_justificacion.py` actualizado a la regla 3. Todo FT NEWS: 123 OK. Versión `ft-news-v7.5-20261013`.

## Archivos
```
ft_news/taxonomia.py        MODIF  es_dobles / es_fuerte_evento
ft_news/descubridor.py      MODIF  la evidencia fuerte excluye dobles
ft_news/alertas.py          MODIF  dobles, hecho ya avisado, mercado ya lo tiene
ft_news/radar.py            MODIF  webs oficiales solo por RSS; cola sin dobles
ft_news/fuentes.py          MODIF  solo_rss
ft_news/textos.py           MODIF  confirmación precisa en retiros / walkovers
ft_news/explicar.py         MODIF  motivos nuevos en palabras
ft_news/descartes.py        MODIF  grupos nuevos del embudo
ft_news/__init__.py         MODIF  v7.5
tests/test_v75_andrade.py   NUEVO
tests/test_v51_justificacion.py MODIF
CAMBIOS-20261013-correcciones-alertas-v7.5.md NUEVO
```
