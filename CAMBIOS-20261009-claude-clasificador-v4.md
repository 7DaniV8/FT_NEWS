# CAMBIOS — 09/10/2026 — FT_NEWS v4: Claude (Anthropic) como clasificador

Pregunta de Rubén (09/10/2026, 20:55): "¿y si usamos Anthropic?". Incluye v3
(Gemini 404: modelo alternativo, clave fuera de la URL, radar que no muere).

## Qué cambia

- **`NEWS_CLASIFICADOR` = auto | gemini | claude** (Admin → FT NEWS /
  `/news/config`, o variable). `auto` (default): Gemini si hay
  `GEMINI_API_KEY` y responde; si no hay clave, o Gemini cae (clave rechazada,
  modelo no disponible), **Claude** con `ANTHROPIC_API_KEY`. El que no es
  principal hace la segunda lectura de lo que aspira a 🔥 (como antes hacía
  Claude). Un clasificador caído se vuelve a probar a las 6 h.
- `proveedores/claude.py`: mismo contrato que Gemini (validación de taxonomía,
  confianza 0–1, 4xx como `ErrorProveedor`, nunca una excepción suelta); si
  `CLAUDE_MODELO` da 404 prueba `claude-haiku-5-5` → `claude-haiku-4-5` →
  `claude-3-5-haiku-latest` → `claude-sonnet-5-5`.
- Radar y RSS usan el clasificador elegido; el costo se anota con su nombre
  (`gemini` / `claude`) en costos y en la pestaña.
- `/news/estado` → `clasificador`: "claude · claude-haiku-5-5 · segunda
  lectura: gemini" (o el que sea). `clasificador_caido` cuando hubo failover.

## Para usar Anthropic ya

En Railway (FT_NEWS): `ANTHROPIC_API_KEY=sk-ant-…`. Con `NEWS_CLASIFICADOR` en
`auto`, si la clave de Gemini sigue sin modelos, pasa solo a Claude; para no
depender de Gemini, `NEWS_CLASIFICADOR=claude`. Costo estimado con Haiku:
~US$ 0,002 por artículo (≈ 120/día → ~US$ 7/mes), dentro del tope
`NEWS_MAX_USD_MES` (100). Gemini Flash sale ~3× más barato por token; por eso
`auto` lo prefiere cuando funciona.

## Pruebas

`tests/test_gemini_404.py` (+3: Claude con el mismo contrato y modelos
alternativos; elección auto/gemini/claude y failover con vencimiento a 6 h;
ciclo completo sin Gemini clasificando con Claude y anotando el costo).
`pytest tests`: 58 OK.

## Archivos tocados (v4 sobre v3)

ft_news/__init__.py · ft_news/config.py · ft_news/tareas.py · ft_news/radar.py ·
ft_news/proveedores/claude.py · ft_news/proveedores/gemini.py · README.md ·
tests/test_gemini_404.py · CAMBIOS-20261009-claude-clasificador-v4.md
