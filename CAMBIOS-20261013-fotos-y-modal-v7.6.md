# FT NEWS v7.6 · Fotos con licencia, detalle para el modal y portada más limpia (13/10/2026)

Rubén: «¿podemos usar imágenes de la web, dando créditos al autor?», «¿qué es partido interesante?, si le doy clic se
debe abrir el modal con todo lo que encontró».

## 📷 Fotos con licencia (`ft_news/fotos.py`, nuevo)
- Dar crédito no alcanza para usar una foto cualquiera: hace falta una licencia que permita reutilizarla. Se usan solo
  fotos de **Wikimedia Commons** con CC0, dominio público, CC BY o CC BY-SA, **siempre con autor, licencia y enlace**.
- Para no poner la cara de otra persona: la foto sale de la **ficha de Wikidata del tenista** (ocupación = tenista,
  mismo nombre); si hay dos tenistas con ese nombre, no se arriesga. Sin licencia válida o sin autor → sin foto
  (tarjeta propia de FullTennis).
- Se guarda en `news_foto` (también el «no hay»): cada jugador se busca una vez cada 30 días (24 h si hubo error).
  Corre en el ciclo, 6 jugadores por vuelta, solo los que puede mostrar la portada. Interruptor `NEWS_FOTOS_ACTIVO`.
- Los jugadores de ITF casi nunca tienen ficha con foto: para ellos sigue la tarjeta.

## 🔎 El modal (`portada.detalle_partido` / `detalle_noticia`, `GET /news/portada/partido/{id}` y `/noticia/{id}`)
- Qué es ese tipo de alerta, los dos jugadores, torneo, hora, UTR, cuotas, a quién perjudica / podría favorecer, qué
  concluye FT NEWS, **todas las noticias de medios** de los dos jugadores (marcada la que generó la alerta, con su
  confirmación y fuente), los datos calculados por FullTennis, lo que falta confirmar y el mensaje tal como salió a
  Discord. Solo lectura; sin códigos del motor, sin Elo ni FTR.

## Portada
- Una alerta vieja solo aparece si **hoy también saldría** (v7.5): no por un resultado de dobles, ni un 🔎 cuya
  conclusión fue «el mercado ya la tiene». (La de Andrade Da Silva deja de abrir la portada.)
- Agenda: se marca **solo** el partido con una alerta vigente (antes «INTERESANTE» salía para cualquier partido
  evaluado aunque solo hubiera datos calculados por nosotros); el resto dice «sin alerta». Cada marca abre el modal.
- Titular con el nombre completo cuando tiene más de dos palabras («Lucas Andrade Da Silva: …», no «Silva: …»).
- «Hoy · partidos evaluados» (Administración): solo las últimas 24 h (mostraba partidos del 09-10/10).

Pruebas: `tests/test_v76_fotos_y_detalle.py` (6). Todo FT NEWS: 129 OK. Versión `ft-news-v7.6-20261013`.
Requiere RankingFTR v53 para verse (modal, fotos y CSP).

## Archivos
```
ft_news/fotos.py            NUEVO
ft_news/portada.py          MODIF
ft_news/app.py              MODIF  /news/portada/partido, /news/portada/noticia; «Hoy» 24 h
ft_news/tareas.py           MODIF  paso «fotos»
ft_news/config.py           MODIF  NEWS_FOTOS_ACTIVO
ft_news/db.py               MODIF  tabla news_foto
ft_news/__init__.py         MODIF  v7.6
tests/test_v76_fotos_y_detalle.py  NUEVO
CAMBIOS-20261013-fotos-y-modal-v7.6.md NUEVO
```
