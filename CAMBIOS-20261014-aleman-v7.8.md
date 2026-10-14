# FT NEWS v7.8 · 14/10/2026 · 🇩🇪 Alemán activado

Pedido de Rubén (14/10/2026): «activa alemán y traduce los conceptos de búsqueda».

* `NEWS_IDIOMAS` por defecto: `en,es,it,fr,pt,de`.
* Radar: consulta en alemán (`"{nombre}" Tennis`) y temas traducidos («Tennis Verletzung Absage», «Tennis Aufgabe
  verletzt», «Tennis Comeback nach Verletzung»).
* Jugadores de Alemania, Austria y Liechtenstein (GER / AUT / LIE) → se buscan también en alemán.
* Migración única: si la base ya tenía `NEWS_IDIOMAS` guardado, se le agrega `,de` una sola vez
  (marca `migracion_idioma_de` en `news_estado`).
* `NEWS_IDIOMAS` es un ajuste guardado en la base (`news_config`), no una variable de Railway: no hay que tocar nada
  en Railway. Si después alguien lo vuelve a guardar sin `de`, queda sin alemán (la migración corre una sola vez).
* Sin Elo/FTR en FT NEWS (como siempre). Ningún otro bot cambia.

## Archivos

Modificados: `ft_news/__init__.py` (VERSION `ft-news-v7.8-20261014`), `ft_news/config.py`, `ft_news/radar.py`,
`ft_news/jugadores.py`, `ft_news/db.py`, `tests/test_v77_agenda_modal.py` (`test_aleman_activo`).
Nuevo: este archivo.

Pruebas: `pytest` → 133 passed.
