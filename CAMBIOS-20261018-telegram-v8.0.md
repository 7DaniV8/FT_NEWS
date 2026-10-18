# FT_NEWS v8.0 · 📡 pistas de canales de Telegram (18/10/2026)

Rubén: «que funcione, que envíe alertas» · «al ser varios canales, que se puedan configurar todos desde el Admin».
Regla de siempre (12/10): el canal entra **solo como pista**: se comprueba con fuentes autorizadas y se redacta con texto propio.

## Recorrido
RankingFTR → Admin → 📰 FT NEWS → **📡 Canales de Telegram** (lista editable) → **Reenvio_MTO** los lee →
RankingFTR `/news-telegram/registrar` → **FT_NEWS `POST /news/telegram/pista`** (`ft_news/lectores/telegram.py`).

## Qué hace FT_NEWS con cada mensaje
1. **DUPLICADA** si el mismo texto ya llegó por otro canal (ALL News / Injuries / Withdrawals repiten): se suma el canal.
2. **¿De quién?** Primera línea = apellido («Pinnington Jones», «Burel»). Varios con ese apellido → el que tiene partido
   programado y el género del texto (she/he); si siguen varios → **AMBIGUA** (no se adivina).
3. **¿Interesa?** Canal «lesiones»: solo si habla de lesión/baja/retiro/enfermedad/regreso/MTO. Canal «todo»: también lo demás si
   hay partido cerca. Lo otro → **SIN_INTERES**, sin gastar IA.
4. El clasificador de siempre (Gemini/Claude) la lee para ese jugador y escribe un **resumen propio** en español.
5. Fuerte y no de dobles → **VERIFICANDO**: el jugador pasa al frente del radar (fuentes autorizadas). Débil → INFORMATIVA.
6. **CONFIRMADA** cuando una fuente autorizada (o un retiro en nuestros resultados) deja una noticia vigente del mismo tipo
   (`memoria.guardar_evento_db` → `confirmar_por_evento`). La alerta sale por el camino normal con la noticia confirmada.
   Sin confirmación en `NEWS_TELEGRAM_CONFIRMAR_H` (72 h) → **SIN_CONFIRMAR** (nunca sale).

**Una pista sola nunca crea una noticia, una alerta ni aparece en la portada.**

## Nuevo
- `ft_news/lectores/telegram.py` (tabla `news_pista`), `POST /news/telegram/pista`, `GET /news/telegram/pistas`.
- Paso `telegram` en cada ciclo + lectura inmediata en un hilo al recibir (`tareas.procesar_pistas_ya`).
- Parámetros: `NEWS_TELEGRAM_ACTIVO` (1), `NEWS_TELEGRAM_MAX_DIA` (80 lecturas con IA), `NEWS_TELEGRAM_CONFIRMAR_H` (72).
- `tests/test_v80_telegram.py` (14 pruebas con los mensajes reales del 18/10).

Sin variables nuevas en Railway. Pruebas: 146 OK; la única falla (`test_endpoints_alertas_diagnostico_buscador`) ya estaba en v7.9.
