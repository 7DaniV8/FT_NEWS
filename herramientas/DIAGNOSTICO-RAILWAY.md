# Diagnóstico real de FT NEWS en Railway (solo lectura)

El diagnóstico **no cambia nada**: abre la base de FT NEWS en modo solo lectura, no llama a
proveedores, no escribe en Discord y no hace falta desplegar nada antes. No muestra claves.

## A · Dentro de FT NEWS (responde las 10 preguntas de las últimas 72 h)

1. Instala la CLI de Railway, una sola vez: `npm i -g @railway/cli`
2. `railway login` (abre el navegador).
3. En cualquier carpeta: `railway link` y elige el proyecto de FullTennis y el entorno de producción.
4. `railway ssh --service FT_NEWS` (usa el nombre del servicio tal como aparece en Railway).
5. Ya dentro del contenedor, escribe `cat > /tmp/diag.py` y pulsa Enter. Pega **todo** el
   contenido de `herramientas/diagnostico_alertas.py`, pulsa Enter otra vez y luego **Ctrl+D**.
6. `python /tmp/diag.py --horas 72`
   (si dice que no encuentra `python`, usa `/opt/venv/bin/python /tmp/diag.py --horas 72`).
7. Copia toda la salida, desde «FT NEWS · diagnóstico de alertas» hasta «FIN.», y pégasela a Daniel.
8. `exit`.

Qué trae la salida:
- **Sección 0**: las 10 cifras en el orden pedido:
  1. jugadores vigilados;
  2. partidos recibidos;
  3. búsquedas;
  4. noticias encontradas;
  5. descartadas;
  6. partidos evaluados;
  7. oportunidades;
  8. alertas creadas;
  9. recibidas por FT Intelligence;
  10. publicadas.
- **Secciones 1 a 8**: el detalle y por qué se descartó cada noticia y cada partido.
- **Sección 9**: problemas con las API, las cuotas, la identificación de jugadores, los rivales
  y la conexión entre servicios.

Con la versión que hoy está en producción, los puntos 9 y 10 no se pueden medir exactos:
nadie registraba esa información. El script da la mejor aproximación y lo dice.

## B · Desde tu PC (comprueba FT Intelligence y la configuración de Discord)

En PowerShell, dentro de la carpeta del repo FT_NEWS, con los valores de las variables de Railway:

```
$env:FT_NEWS_URL="https://…"; $env:FT_NEWS_SECRET="…"
$env:FTR_SERVICE_URL="https://…"; $env:FTR_INTERNAL_SECRET="…"
$env:FT_INTEL_URL="https://…"
python herramientas/verificar_real.py
```

Pega la salida; no incluye las claves.

## C · Lo que solo se ve en Discord

Cuenta cuántos mensajes de FT NEWS (📰, 🔎 y 🔥) aparecieron en los canales de la comunidad
en las últimas 72 horas, y en qué canal. Es la única forma de saber cuántas alertas llegaron
de verdad antes de v7.3.
