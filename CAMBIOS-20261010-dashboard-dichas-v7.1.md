# FT NEWS v7.1 — el dashboard lista TODO lo dicho en Discord, para siempre (10/10/2026)

Rubén (10/10 14:09): "¿Por qué las alertas que se están enviando no están
sumando al recuento del dashboard? Estas alertas nunca se deben borrar de sus
vistas y cuando lleguen a 10 se empiezan a paginar."

## Por qué daba 0

`ft_news/dashboard.py` solo contaba `news_evaluacion.tipo_alerta='FUEGO'` con
`dicho_discord=1`: la 🔥 **validada**, que no existe hasta que Rubén habilite
las bandas. Lo que sí se está enviando (📰 NOTICIA IMPORTANTE, 🔎 PARTIDO
INTERESANTE, 🔥 EXPERIMENTAL) quedaba fuera. Además, la marca "dicho" de v5+
vive en `news_alerta` (FT Intelligence confirma por `POST /news/senales/dicho`),
no en la evaluación.

## Ahora

- El historial sale de `news_alerta` con `dicho_discord=1`: **todas** las
  alertas que FT Intelligence confirmó dichas (📰 🔎 🔥 🔥 exp), ordenadas por
  cuándo se dijeron. Nada se filtra por versión ni por lo que la evaluación
  haga después (si una 🔎 pasa a 🔥 o una 🔥 deja de serlo, la alerta dicha
  queda).
- **Apuestas (KPI)** = solo las 🔥 (validadas y experimentales): selección =
  el favorecido del mensaje, cuota = la suya, ganado/perdido por el resultado
  del Motor 5, unidades 1 fija. 📰 y 🔎 se listan como **seguimiento** (con el
  favorecido y su cuota si el mensaje lo dijo, y el marcador del partido
  cuando lo hay) sin contar como apuesta.
- `kpis.alertas_dichas` y `kpis.seguimiento` acompañan a los KPI de siempre;
  la pestaña dice "N alerta(s) dicha(s) · M apuesta(s) 🔥 · K en seguimiento".
- Compatibilidad: una 🔥 dicha antes de que existiera `news_alerta` (solo la
  marca en la evaluación) sigue contando.
- Paginación: la hace RankingFTR, de a 10 (ya estaba).

## Pruebas

`tests/test_v7_carga_claro.py::test_dashboard_lista_todo_lo_dicho_y_apuesta_solo_las_fuego`
(📰 + 🔎 + 🔥 exp dichas → 3 listadas, 1 apuesta, 2 en seguimiento; una omitida
no aparece; resultado del partido → la 🔥 exp ganada +0.79 y las otras con el
marcador; cambiar la evaluación después no borra nada). Suite: **98 passed**.

## Archivos modificados

- `ft_news/__init__.py` (v7.1)
- `ft_news/dashboard.py`
- `tests/test_v7_carga_claro.py`, `tests/test_segunda_entrega.py`, `tests/test_v51_justificacion.py` (frescura contra la hora real)
- `CAMBIOS-20261010-dashboard-dichas-v7.1.md` (este)
