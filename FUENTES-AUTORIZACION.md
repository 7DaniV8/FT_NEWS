# 📰 FT NEWS INTELLIGENCE — Fuentes: condiciones de uso y autorizaciones (Fase 0)

**Regla de la Fase 0 (ajuste 3 de Rubén, 08/10/2026):** ninguna fuente se lee de forma automatizada hasta que sus condiciones de uso estén revisadas y la fuente tenga `autorizada=1` en `news_fuente`. Hoy **ninguna** la tiene. En el código, `fuentes.permitida()` es la compuerta que todo lector futuro debe pasar; con `NEWS_FUENTES_AUTORIZADAS_SOLO=1` (default) solo pasan las autorizadas. No existe todavía ningún lector.

Estados posibles: `PENDIENTE` (sin revisar), `REVISADO_OK` (se puede autorizar), `REVISADO_NO` (no se usa), `REQUIERE_LICENCIA` (solo con contrato). Solo una fuente `REVISADO_OK` se puede autorizar (lo exige `fuentes.autorizar()` y lo prueba `tests/test_apagado_y_fuentes.py`).

Lo que sigue es lo que **se encontró el 08/10/2026** (✅ verificado leyendo la página/documentación; ⚠️ conocido por uso común pero no verificado ese día porque el proxy bloqueó el sitio) y **qué decisión falta**. Nada de esto es asesoría legal: es el resumen técnico para que Rubén decida.

## 1. Fuentes oficiales (eventos nivel A)

| Fuente | Qué dice su condición de uso | Riesgo | Decisión pendiente |
|---|---|---|---|
| **itftennis.com** (acceptance lists PDF/HTML, cuadros, order of play, resultados ret./w.o.) | ⚠️ Sus T&C prohíben el uso automatizado del sitio y, de forma explícita, el uso de sus datos para apuestas sin licencia; la ITF comercializa el dato en vivo vía Sportradar. El sitio carga datos por una API JSON interna no documentada (`/tennis/api/TournamentApi/...`). | **Alto** si se usa la API interna o se lee con frecuencia; medio si se leen solo PDFs públicos de listas una vez al día para uso interno. | **D-ITF**: (a) PDFs públicos de acceptance lists, 1 lectura/día por torneo, uso interno, sin API interna — recomendado si Rubén acepta el riesgo; (b) no leer ITF oficial: ITF solo por prensa y `match_log`; (c) Sportradar. Revisar `itftennis.com/en/terms-and-conditions/` antes de decidir. |
| **atptour.com** (RSS oficial `…/media/rss-feed/xml-feed` ✅, entry lists, cuadros Challenger) | RSS público pensado para lectores de feeds. El ToS del sitio prohíbe scraping con fines comerciales. | Bajo para el RSS; medio para cuadros HTML. | Confirmar que leer el RSS oficial encaja con su ToS; si sí → `REVISADO_OK` para el RSS, cuadros aparte. |
| **wtatennis.com** (acceptance lists PDF, cuadros; API interna `api.wtatennis.com` ⚠️) | ToS restrictivos; los PDFs son públicos. | Medio. | Igual que ATP: PDFs públicos sí/no; API interna **no**. |
| **app.utrsports.net** (eventos UTR PTT: Players, Draws, live scoring ✅) | ToS prohíbe scraping. La web usa una API interna con JWT de sesión (ya la usa UTR Power con la cuenta propia, a baja frecuencia y con pausa por 429). La **API Engage oficial** ✅ solo expone ratings/perfil con consentimiento; **no expone eventos ni cuadros**. | Medio (mismo que UTR Power hoy). | **D-UTRPTT**: leer cuadros con la misma cuenta y cadencia que UTR Power, o no leerlos. Consultar a UTR si Engage puede ampliarse a eventos (contrato). |
| **Sportradar Tennis API** ✅ | Licencia comercial; cubre ITF/Challenger/125 con `retired`/`walkover` estructurado. | Nulo. | Solo si el presupuesto lo permite (miles €/año). `REQUIERE_LICENCIA`. |
| **RankingFTR** (`match_log`, `fixtures`, `utr_*`) | Datos propios. | Nulo. | `REVISADO_OK` de hecho; se autoriza en la Fase 1 al encender. |

## 2. Prensa y federaciones (eventos nivel B)

| Fuente | Acceso | Qué revisar antes de autorizar |
|---|---|---|
| Tennis TourTalk ✅ RSS | `tennistourtalk.com/feed/` | Aviso legal del sitio; uso de RSS para lectura interna suele estar permitido. |
| Puntodebreak ✅ RSS | `puntodebreak.com/rss.xml` | Ídem. |
| LiveTennis.it ⚠️, Ubitennis ⚠️ (RSS WordPress probable), Tennis World, Tennis Actu | RSS/HTML | Confirmar que el feed existe y su aviso legal. |
| Tennis Australia ✅ RSS, USTA Florida ✅ RSS; FFT, FITP, RFET, DTB, CBT, AAT, Fedecoltenis, Tennis Canada, JTA (HTML) | RSS / HTML | Valor bajo para bajas; útil para regresos/lesiones de jugadores locales. Autorizar solo las que tengan RSS. |

**Camino recomendado para la prensa:** no leer los sitios directamente sino a través de un agregador con licencia (Tavily `include_domains` ✅, Exa `includeDomains` ✅, GNews por idioma ✅). El ToS que hay que revisar es entonces el del agregador (uso comercial permitido en planes de pago) y no el de 30 medios.

## 3. Redes

| Fuente | Condición | Decisión |
|---|---|---|
| X/Twitter (@ATPChallenger, @ProTennisTour, @WTA_insider, trackers ITF) | Solo por API oficial de pago (≥ US$ 100/mes); los espejos tipo Nitter violan ToS y no son fiables. | Fase 5 (D11). `PENDIENTE`. |
| Reddit r/tennis RSS | Público; ruido muy alto. | No se usa. |

## 4. Explícitamente NO (ya revisadas)

| Fuente | Por qué |
|---|---|
| **Flashscore / Livesport** ✅ | Sus términos prohíben uso comercial (2.2), extracción de base de datos (2.9) y peticiones automatizadas / scraping (2.10). `REVISADO_NO`. |
| **Sofascore** ⚠️ | API interna, bloqueo por IP/UA, ToS prohíbe acceso automatizado. `REVISADO_NO`. |
| **TennisExplorer** | HTML con ret./w.o. de todo ITF; ToS no verificado; riesgo legal medio. **D-TE**: recomendado no usar (`match_log` + listas cubren lo mismo con un día de retraso). `PENDIENTE` hasta decisión. |

## 5. Cómo se autoriza una fuente (cuando Rubén decida)

Desde la API de FT_NEWS (más adelante, desde la pestaña):

```
POST /news/fuentes/autorizar
{"dominio": "tennistourtalk.com", "autorizada": true, "estado_tc": "REVISADO_OK",
 "nota": "RSS público; aviso legal revisado 10/10/2026", "por": "ruben"}
```

Queda registrado quién y cuándo. Un lector futuro que pida una página de una fuente no autorizada falla en `fuentes.permitida()` antes de hacer la petición.

## 6. Decisiones que faltan (resumen)

- **D-ITF** (listas oficiales ITF): a / b / c.
- **D-UTRPTT** (cuadros UTR PTT con la cuenta de UTR Power): sí / no.
- **D-TE** (TennisExplorer): recomendado no.
- Confirmar ToS del **RSS de ATP** y de **Tavily** (plan de pago) para autorizarlos en la Fase 1.
- Lista blanca de prensa: aprobar la inicial (TourTalk, Puntodebreak, LiveTennis.it, Ubitennis, Tennis Actu) y agregar los periodistas/cuentas de confianza de Rubén.
