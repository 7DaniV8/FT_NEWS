# CAMBIOS — 10/10/2026 — FT_NEWS v6.1: detalle de la evaluación para el modal + Gemini 404 en cadena

## 1. `GET /news/evaluaciones/{id}` (Rubén 00:31: "cuando seleccione un partido 🔥, ver qué noticias encontró y todo lo que analizó")

Devuelve la evaluación completa de un partido para el modal de la pestaña
(RankingFTR v38): evaluación, partido (cuota vigente, proveedor, hora),
jugador X y rival (UTR y fecha), **noticias usadas** (con artículo: título,
URL, dominio, publicación; titular, resumen, fragmento original, nivel,
naturaleza, identidad, vigencia, origen externo/calculado, historial de
cambios), todo lo vigente de los dos, cuotas observadas, alertas del partido
(con evidencia → justificación y texto de Discord), frescura y búsquedas y
artículos recientes de los dos, resultado si ya se jugó. `lectura1/2_json`
no viajan. 404 si no existe. Prueba en `test_v51_justificacion.py` (+1).

## 2. Gemini: "model … is no longer available to new users" (pestaña: Errores (30), PENDIENTE 104)

El modelo configurado (`gemini-2.5-flash`) daba 404; v3 elegía otro de la lista
de la clave (`gemini-2.5-flash-lite`) y ese también daba 404 ("no longer
available to new users. Please update your code to use models/…") → cada
artículo terminaba en `Gemini HTTP 404` con pausa de 15 min y la cola de
reintentos creció a 104. Ahora `clasificar()` prueba hasta 4 modelos en la
misma llamada, **recuerda los que dieron 404** (`modelos_malos`, no se
repiten), usa primero el que el propio mensaje de Google sugiere
(`use models/<x>`), y la lista de modelos se pide una sola vez. Orden
preferido nuevo: 2.5-flash → flash-latest → 2.0-flash → 2.5-flash-lite →
2.0-flash-lite → flash-lite-latest → 1.5-flash. Si todos dan 404: error fatal
claro ("Revisar GEMINI_API_KEY o pasar a Claude (NEWS_CLASIFICADOR=claude)") y
el failover a Claude de v4 actúa si hay `ANTHROPIC_API_KEY`. `/news/estado` →
`clasificador` muestra el modelo en uso y el aviso. Prueba en
`test_gemini_404.py` (+1). Los 104 PENDIENTE se retoman solos con el paso
`reintentos` en cuanto haya modelo.

**Recomendación**: con `ANTHROPIC_API_KEY` puesta, `NEWS_CLASIFICADOR=claude`
deja de depender de qué modelos de Gemini quedan disponibles para la clave.

## Archivos tocados (v6.1 sobre v6)

- `ft_news/__init__.py`, `ft_news/app.py`, `ft_news/proveedores/gemini.py`,
  `tests/test_gemini_404.py`, `tests/test_v51_justificacion.py`, este archivo
