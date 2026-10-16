# FT_NEWS v7.9 · 16/10/2026 · 📋 /news/control

Va junto con **RankingFTR v54j**, que lo muestra en la pestaña 📰 News (sección «📋 Control», solo admin).

## El pedido

> Rubén (16/10/2026): «Me gustaría crear eso [el control de UNDER UTR] en las siguientes tabs, es que no sé si están
> funcionando o leyendo o qué están haciendo» (entre ellas, News).

## Qué agrega

`GET /news/control` (con `X-FT-News-Secret`), solo lectura, en `ft_news/control.py`:

* **Worker:** último ciclo, encendido o no, motivo, y cada paso con OK / ERROR y su detalle.
* **24 h:** búsquedas, artículos leídos y noticias registradas.
* **Partidos en la ventana** (12 h atrás, 48 h adelante):
  * de cada jugador: situación en la cola, última y próxima búsqueda, búsquedas de 24 h y noticias vigentes;
  * la última evaluación del partido y su motivo;
  * la alerta (pendiente / dicha / omitida) y las cuotas observadas.

No cambia ninguna regla, alerta ni costo: solo cuenta lo que ya está en la base.

## Archivos

* `ft_news/control.py` (nuevo)
* `ft_news/app.py` (ruta)
* `ft_news/__init__.py` (v7.9)
* `tests/test_v79_control.py` (nuevo, 3 pruebas)
* este archivo

Pruebas: `bash tests/correr_todo.sh` → 136 passed.
