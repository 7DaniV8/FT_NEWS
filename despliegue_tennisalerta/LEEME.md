# Recolector de TennisAlerta en Railway — guía paso a paso (05/11/2026, v2)

La idea: el programa corre siempre en un servicio de Railway, sin depender de tu computador.
El único paso que SÍ necesita tu computador es el login inicial, porque Railway no tiene pantalla
para que entres con tu usuario y contraseña. Esta versión NO usa Volume ni CLI de Railway: la
sesión se guarda en el Admin, como un parámetro más.

## Paso 1 — Despliega primero el FT_NEWS normal

Antes de este servicio nuevo, sube a FT_NEWS el ZIP con los cambios de hoy (el que trae
`ft_news/config.py` con la clave `NEWS_TENNISALERTA_SESION`). Sin eso, el Admin no tiene dónde
guardar la sesión.

## Paso 2 — Inicia sesión en tu computador (una sola vez)

En tu computador, carpeta FT_NEWS, con las mismas variables que ya usas para enviar al LIVE:

    $env:FT_NEWS_URL="https://TU-FT-NEWS-EN-RAILWAY"
    $env:FT_NEWS_SECRET="el-secreto-de-siempre"
    python herramientas/tennisalerta_senal.py --url "https://tennisalerta.com/" --login

Entra con tu cuenta, espera a ver el LIVE, vuelve a la consola y pulsa Enter. El programa:
- guarda la sesión en tu computador (por si acaso), y
- la sube SOLO al Admin de FT_NEWS (clave `NEWS_TENNISALERTA_SESION`).

Si no tenías puestas esas dos variables, el programa te lo dice y te deja el archivo
`sesion_nube.json` para que pegues su contenido a mano en el Admin.

## Paso 3 — Crea el servicio en Railway

1. En tu proyecto de Railway, "New" → "Empty Service". Nómbralo, por ejemplo,
   `tennisalerta-recolector`.
2. En Settings → Source, conéctalo al repo de FT_NEWS. En "Root Directory" pon
   `despliegue_tennisalerta` (usa este Dockerfile), o ajusta las rutas si prefieres mantener
   todo en la raíz del repo.
3. En Variables, agrega:

       TA_URL=https://tennisalerta.com/
       FT_NEWS_URL=https://TU-FT-NEWS-EN-RAILWAY
       FT_NEWS_SECRET=el-mismo-secreto-de-siempre
       TA_CADA_MIN=10

4. Despliega. No necesita Volume: en cada arranque lee la sesión guardada en el Admin.

## Revisar que funciona

En los "Logs" del servicio nuevo debe salir una línea cada ~10 minutos con el resumen
(vistas, enviadas, live_enviados). En el Admin de RankingFTR, pestaña News → LIVE, deben
aparecer avisos con fuente "TennisAlerta".

## Si la sesión expira

Si los logs muestran "DETENIDO: la página pide iniciar sesión...", repite el Paso 2 desde tu
computador (con las mismas variables puestas, para que la sesión nueva se suba sola al Admin).
El servicio de Railway la recoge solo en su siguiente vuelta, sin que tengas que tocar nada ahí.
