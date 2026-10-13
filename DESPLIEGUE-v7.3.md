# Despliegue FT NEWS v7.3 — los 4 servicios (13/10/2026)

| Servicio | Versión | Qué cambia |
|---|---|---|
| FT_NEWS | v7.3 | Motivos de descarte, semáforo, recorrido de cada alerta, 🔥 sin calibración siempre EXPERIMENTAL, línea «confirmada / sin confirmar», prueba de Discord |
| FT_INTELLIGENCE | v24 | Le pasa a FT NEWS si cada alerta **se publicó de verdad** y en qué canal; marca la PRUEBA como solo admin |
| FT_DISCORD | v16 | Canal de administradores para la PRUEBA; acuse de publicación de las tres alertas de FT NEWS |
| RankingFTR | v48 | Pestaña FT NEWS (admin): semáforo, motivos, botones de apagado, prueba de Discord |

**Lo que no se tocó:** ningún filtro, ni Cuota Mal Puesta, Favorito Remonta, UTR VALUE,
Implicación ni los demás motores. Las alertas reales (📰 / 🔎 / 🔥 EXPERIMENTAL) siguen yendo
solas a la comunidad, sin aprobación manual.

**Recorrido probado con el código real de los cuatro:**
- 6 alertas publicadas en la comunidad y confirmadas de vuelta en FT NEWS;
- la PRUEBA sale solo por el canal de administradores, sin voz;
- sin canal de administradores, la PRUEBA no sale por ningún lado;
- nada se repite.

---

## Paso 1 · Subir el código (en este orden)

Copia cada carpeta del zip encima de su repo, respetando las rutas, y haz push.

1. `FT_NEWS/` → repo **FT_NEWS**
2. `FT_INTELLIGENCE/` → repo **FT_INTELLIGENCE**
3. `FT_DISCORD/` → repo **FT_DISCORD**
4. `RankingFTR/` → repo **RankingFTR**. Está rebasado sobre tu último RankingFTR, el de
   Implicación v47: no pisa nada de eso.

Espera a que cada uno quede **Active** en Railway antes del siguiente. Cualquier orden es
seguro, porque cada versión entiende a la anterior; este es el más limpio.

No hacen falta variables nuevas, salvo la del paso 3. Las tablas nuevas se crean solas y no
se borra nada.

## Paso 2 · Activar FT NEWS (pestaña FT NEWS, como admin)

1. Comprueba la versión en `https://<dominio de FT_NEWS>/salud`: debe decir `ft-news-v7.3-20261013`.
2. Arriba de la pestaña: **⛔ Apagar FT NEWS** y **🔇 Detener envíos a Discord** visibles
   significa que está encendido y enviando. Si ves «▶️ Encender» o «📢 Reanudar», púlsalos.
3. **Desmarca «Bandas calibradas».** Las 🔥 siguen saliendo, como EXPERIMENTALES.
4. En **Admin → Discord**, 📰 / 🔎 / 🔥 de FT NEWS con texto encendido.

## Paso 3 · Canal de administradores para la prueba (5 minutos)

1. En Discord, crea un canal de texto **privado** (por ejemplo `#ft-admin-pruebas`) que solo
   vean los administradores. Dale al bot de FT Discord permiso de **Ver canal** y
   **Enviar mensajes** en ese canal.
2. Con el modo desarrollador activado: clic derecho en el canal → **Copiar ID**.
3. Railway → servicio **FT_DISCORD** → Variables → `DISCORD_CANAL_ADMIN_ID = <ese id>`.
   Railway reinicia el servicio. En el log debe verse `listo como … | admin: sí`.
4. En la pestaña FT NEWS, marca **«Prueba de Discord habilitada»**.
5. Pulsa **🧪 Enviar PRUEBA a Discord**. En un par de minutos deberías ver:
   - ✅ FT NEWS creó la alerta;
   - ✅ FT Intelligence la recibió;
   - ✅ FT Discord la publicó, «en el canal de administradores».

   El mensaje aparece **solo** en `#ft-admin-pruebas`, no en la comunidad ni por voz.

Si algún paso queda en ❌, el propio mensaje dice en cuál y por qué.

## Paso 4 · Qué mirar las primeras horas

- **Semáforo** 🟢 (o el motivo exacto si no).
- Cada alerta real en «Alertas a Discord» muestra su recorrido:
  - creada → recibida → **publicada en el canal de la comunidad**;
  - o **en qué paso falló y por qué** (por ejemplo, «tipo apagado en Admin → Discord»);
  - o «FT Discord no confirmó».
- Si algo sale mal: **🔇 Detener envíos a Discord** (FT NEWS sigue investigando y guardando
  todo) o **⛔ Apagar FT NEWS**.
- Para volver atrás: Railway → servicio → Deployments → el deploy anterior → **Redeploy**.

## Revisa esto si no llegan alertas reales

- **FT_DISCORD → Variables:** si existen `FT_DISCORD_TIPOS_TEXTO` o `FT_DISCORD_TIPOS_VOZ` de
  una versión vieja, solo mandan cuando FT Discord no recibe la configuración de Admin → Discord.
  Si las tienen, conviene que incluyan `NEWS_VALOR,NEWS_INTERESANTE,NEWS_NOTICIA`, o borrarlas.
- **El recorrido de la alerta en la pestaña ahora dice dónde se cortó.** Ese es el dato para
  corregir, sin tocar filtros a ciegas.

## Aviso aparte (no es de FT NEWS)

En FT Discord, `tests/test_recorrido_completo.py` tiene **7 fallas que ya venían** en el código
recibido, todas de 🚨 **UTR Market Anomaly** (RankingFTR): la señal en vivo no se publica en el
recorrido de prueba. No se tocó, porque es otro motor; conviene que lo revise quien lo mantiene.
