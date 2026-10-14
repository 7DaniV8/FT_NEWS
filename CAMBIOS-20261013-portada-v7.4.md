# FT NEWS v7.4 · Portada tipo periódico (13/10/2026)

Rubén: «que FT NEWS se vea así como lo habíamos planeado» (boceto «FT NEWS · Portada FullTennis»).

## Qué agrega
- `ft_news/portada.py` (nuevo) y `GET /news/portada`: arma la portada SOLO LEYENDO lo que FT NEWS ya guarda.
  No crea alertas, no cambia filtros, no gasta búsquedas.
  - **Titular / partido del día**: la alerta 🔥 o 🔎 más fuerte de un partido que todavía no terminó; es la misma fila
    que viaja a Discord. Una 🔥 sin calibración respaldada por datos sale SIEMPRE como «POSIBLE VALOR · EXPERIMENTAL»
    (la casilla manual sola no alcanza). Sin alertas: abre la noticia externa más fuerte; nunca se inventa un partido.
  - **Partidos interesantes**, **noticias** (solo de un medio, con su línea de confirmación ✅ / 📰 / 🗣️ / ❔ y la
    fuente), **lesiones, retiros y bajas** y **agenda** (próximas 30 h de jugadores vigilados, UTR y cuotas).
  - Secciones ATP / WTA / Challenger / ITF / UTR PTT.
  - Fotos: todavía no hay fotos con licencia → tarjeta propia de FullTennis (iniciales, país, UTR). Nunca una foto sin licencia.
  - Sin códigos del motor, sin bandas, sin Elo ni FTR.
- Fechas de prensa en formato «Thu, 08 Oct 2026 …» se leen bien para ordenar y filtrar.
- `tests/test_v74_portada.py` (nuevo, 4 pruebas). Todo FT NEWS: 117 OK.
- `ft_news/__init__.py`: versión `ft-news-v7.4-20261013` (en /salud).

Requiere RankingFTR v52 para verse en la pestaña.
