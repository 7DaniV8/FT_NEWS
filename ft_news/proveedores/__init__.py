"""Proveedores externos de FT_NEWS (Fase 1). Dos y solo dos:
  tavily.py — búsqueda de noticias con lista blanca de dominios.
  gemini.py — clasificación y resumen (Gemini 2.5 Flash, JSON estricto).
Ninguno se llama sin NEWS_ACTIVO=1, sin clave, sin fuente autorizada
(fuentes.permitida) ni sin presupuesto (costos.puede_gastar)."""
