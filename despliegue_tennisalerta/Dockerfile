# Despliegue del recolector de TennisAlerta como servicio aparte en Railway (05/11/2026, Daniel).
# Corre siempre, headless (sin pantalla): lee la sesión guardada en el Admin de RankingFTR
# (NEWS_TENNISALERTA_SESION), así que NO necesita Volume ni subir nada por la CLI de Railway.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app
COPY herramientas/tennisalerta_senal.py ./herramientas/tennisalerta_senal.py

CMD ["sh", "-c", "python herramientas/tennisalerta_senal.py --url \"$TA_URL\" --nube --cada-min \"${TA_CADA_MIN:-10}\""]
