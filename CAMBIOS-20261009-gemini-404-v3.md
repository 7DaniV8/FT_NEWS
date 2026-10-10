# CAMBIOS — 09/10/2026 — FT_NEWS v3: Gemini 404 (el radar no clasificaba nada)

Diagnóstico con el log de Railway del 09/10: **67 ciclos seguidos** con
`paso radar falló: 404 Not Found … models/gemini-2.5-flash:generateContent`.
Tavily sí buscaba, pero el primer artículo que llegaba a Gemini tiraba un
HTTPStatusError que abortaba el paso radar entero. Consecuencias:

- ninguna noticia de prensa se clasificó nunca (todo lo de "Noticias
  recientes" es `rankingftr.interno`: carga y antecedentes del Motor 3);
- el jugador no se reprogramaba → Tavily se volvía a pagar cada 15 min por el
  mismo jugador (el gasto diario era todo eso);
- la clave de Gemini quedaba impresa en el log dentro de la URL del error.

## Qué cambia

- `proveedores/gemini.py`:
  - la clave va en la cabecera `x-goog-api-key`, nunca en la URL;
  - ante un **404 del modelo**, pide a la API la lista de modelos de esa clave
    y elige el primero disponible de `gemini-2.5-flash` → `2.5-flash-lite` →
    `2.0-flash` → `2.0-flash-lite` → `flash-latest` → `1.5-flash` (o cualquier
    "flash"); lo usa desde ahí y lo deja en el estado (`gemini_modelo`). Si no
    hay ninguno, error fatal con la lista de modelos de la clave y el consejo
    (revisar `GEMINI_API_KEY` / `GEMINI_MODELO`);
  - cualquier otro 4xx es un `ErrorProveedor` normal (pausa 15 min), no una
    excepción suelta.
- `radar.py`: un artículo que falla se anota en `errores` y se sigue con el
  siguiente; el jugador SIEMPRE se reprograma (nunca más Tavily repetido por un
  error de IA). Si Gemini cambió de modelo, el resumen del ciclo lo dice.
- `tareas.py`: `gemini_modelo` en `news_estado` (se ve en `/news/estado`).
- `GEMINI_MODELO` (variable) permite fijarlo a mano.

## Qué revisar en Railway

1. La clave del log tiene formato `AQ.…` (clave de Google Cloud). Si en la
   lista que ahora imprime el error no aparece ningún "flash", generar una
   clave en **AI Studio** (`AIza…`) y ponerla en `GEMINI_API_KEY`. Como la
   clave quedó impresa en logs viejos, conviene regenerarla de todos modos.
2. Tras el deploy, en `/news/estado` → `gemini_modelo` tiene que decir el
   modelo en uso; en la pestaña, "Noticias recientes" debería empezar a traer
   fuentes de prensa (tennistourtalk, puntodebreak…), no solo `rankingftr.interno`.

## Pruebas

`tests/test_gemini_404.py` (nuevo, 4): 404 → elige otro modelo y sigue (la
clave nunca en la URL); 404 sin alternativa → error fatal claro; otro 4xx no
escapa; un artículo roto no tumba el radar y el jugador se reprograma (Tavily
no se paga dos veces). `pytest tests`: 55 OK.

## Archivos tocados (v3 sobre v2)

ft_news/__init__.py · ft_news/proveedores/gemini.py · ft_news/radar.py ·
ft_news/tareas.py · tests/test_gemini_404.py (nuevo) ·
CAMBIOS-20261009-gemini-404-v3.md
