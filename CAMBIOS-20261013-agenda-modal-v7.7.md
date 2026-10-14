# FT_NEWS v7.7 — 13/10/2026 (noche)

Pedido de Rubén: «Colocar imágenes en FT_News · que en estos partidos también tenga la posibilidad de ver el modal»
(los partidos de la agenda que dicen «sin alerta»).

## Qué cambia
- **Agenda con fotos**: cada partido trae `jugador1_id`, `jugador2_id`, `partido_id` e `imagenes` (la foto con
  licencia de Wikimedia Commons o, si no hay, la tarjeta FullTennis con iniciales). Mismas reglas de v7.6: solo la
  ficha de Wikidata del tenista, licencia libre y autor obligatorios.
- **Más fotos por vuelta**: `fotos.jugadores_de_portada` suma los jugadores de la agenda (los partidos más cercanos
  primero) y `POR_VUELTA` pasa de 6 a 15 (≈ 60 jugadores por hora con el ciclo de 15 min). La caché de 30 días sigue.
- **Modal de cualquier partido de la agenda**: `portada.detalle_agenda(conn, partido_id)` y
  `GET /news/portada/agenda/{partido_id}` (solo lectura). Si el partido tiene una alerta 🔎/🔥 que la portada
  mostraría, devuelve su `alerta_id` (el panel abre el modal de la alerta). Si no: los dos jugadores (foto o
  tarjeta), qué investigó FT NEWS de cada uno (cuándo, búsquedas, artículos y noticias de medios de los últimos 3
  días), por qué no salió alerta (la última evaluación, en palabras), las noticias de medios de los últimos 21 días
  (marcando las de dobles) y los datos calculados. Sin códigos del motor, sin Elo ni FTR.

## No cambia
Filtros, alertas, envíos a Discord, presupuesto de búsquedas, clasificador.

## Pruebas
`tests/test_v77_agenda_modal.py` (3). Suite completa: 132 pasadas.
