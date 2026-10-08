"""
ft_news/fuentes.py — Lista blanca de fuentes (diseño §6) con su estado de
condiciones de uso. NADA SE LEE CON autorizada=0 (ajuste de Rubén 08/10:
"antes de automatizar las fuentes ITF y UTR, confirma las condiciones de
uso y las autorizaciones necesarias").

En la Fase 0 NO hay lectores: este módulo solo siembra el catálogo y
expone `permitida(dominio)`, que cualquier lector futuro debe consultar
antes de pedir una sola página. FUENTES-AUTORIZACION.md tiene el detalle
de lo que dice cada condición de uso y qué decisión falta.

estado_tc: PENDIENTE | REVISADO_OK | REVISADO_NO | REQUIERE_LICENCIA
"""
from __future__ import annotations

from typing import Optional

from ft_news.db import ahora_iso, ejecutar_con_reintento

# (dominio, nombre, tipo, idioma, nivel_maximo, circuitos, acceso, estado_tc, nota)
CATALOGO = (
    # Propias / ya licenciadas por FullTenis
    ("rankingftr.interno", "RankingFTR match_log / fixtures (BOT)", "PROPIA", "es", "A", "atp,wta,challenger,itf",
     "API", "REVISADO_OK", "Datos propios de la plataforma; ret./w.o. y cuotas ya capturadas."),
    # Oficiales
    ("itftennis.com", "ITF — torneos, acceptance lists, cuadros, OOP", "OFICIAL", "en", "A", "itf",
     "HTML/PDF (JSON interno no documentado)", "PENDIENTE",
     "T&C prohíben uso automatizado y uso para apuestas sin licencia; la ITF vende el dato vía Sportradar. "
     "Decisión D-ITF pendiente de Rubén. No usar la API JSON interna."),
    ("atptour.com", "ATP — RSS oficial, entry lists, cuadros Challenger", "OFICIAL", "en", "A", "atp,challenger",
     "RSS/HTML", "PENDIENTE", "RSS público pensado para lectores de feeds; ToS prohíbe scraping comercial. Confirmar."),
    ("wtatennis.com", "WTA — acceptance lists WTA 125, cuadros", "OFICIAL", "en", "A", "wta,wta125",
     "PDF/HTML (API interna no documentada)", "PENDIENTE", "ToS restrictivos; PDFs públicos. Confirmar."),
    ("app.utrsports.net", "UTR Sports — eventos UTR PTT, cuadros, W.O.", "OFICIAL", "en", "A", "utr",
     "HTML (API interna con JWT)", "PENDIENTE",
     "ToS prohíbe scraping; la API Engage oficial no expone eventos. Decisión D-UTRPTT pendiente."),
    ("developer.sportradar.com", "Sportradar Tennis API (ITF/Challenger/125, retired/walkover)", "OFICIAL", "en", "A",
     "itf,challenger,wta125,atp,wta", "API", "REQUIERE_LICENCIA", "Legal y completo; costo enterprise."),
    # Prensa especializada
    ("tennistourtalk.com", "Tennis TourTalk", "PRENSA", "en", "B", "challenger,itf", "RSS", "PENDIENTE",
     "RSS público; verificar aviso legal del sitio."),
    ("puntodebreak.com", "Puntodebreak", "PRENSA", "es", "B", "atp,wta,challenger,itf", "RSS", "PENDIENTE", ""),
    ("livetennis.it", "LiveTennis.it", "PRENSA", "it", "B", "challenger,itf", "RSS", "PENDIENTE", ""),
    ("ubitennis.com", "Ubitennis", "PRENSA", "it", "B", "atp,wta,challenger", "RSS", "PENDIENTE", ""),
    ("tennisworldit.com", "Tennis World", "PRENSA", "it", "C", "atp,wta,challenger", "HTML", "PENDIENTE",
     "Calidad desigual: nivel máximo C."),
    ("tennisactu.net", "Tennis Actu", "PRENSA", "fr", "B", "challenger,itf", "HTML", "PENDIENTE", ""),
    # Federaciones
    ("feeds.feedburner.com/tennis-australia", "Tennis Australia (RSS)", "FEDERACION", "en", "B", "itf,atp,wta",
     "RSS", "PENDIENTE", ""),
    ("ustaflorida.com", "USTA Florida (RSS)", "FEDERACION", "en", "B", "itf", "RSS", "PENDIENTE", ""),
    ("fft.fr", "FFT", "FEDERACION", "fr", "B", "itf,challenger", "HTML", "PENDIENTE", ""),
    ("fitp.it", "FITP / Supertennis", "FEDERACION", "it", "B", "itf,challenger", "HTML", "PENDIENTE", ""),
    ("rfet.es", "RFET", "FEDERACION", "es", "B", "itf,challenger", "HTML", "PENDIENTE", ""),
    ("cbtenis.com.br", "CBT", "FEDERACION", "pt", "B", "itf,challenger", "HTML", "PENDIENTE", ""),
    ("aat.com.ar", "AAT", "FEDERACION", "es", "B", "itf,challenger", "HTML", "PENDIENTE", ""),
    ("fedecoltenis.com", "Fedecoltenis", "FEDERACION", "es", "B", "itf", "HTML", "PENDIENTE", ""),
    # Agregadores (son el camino legal a la prensa; cada uno con su clave y ToS propio)
    ("api.tavily.com", "Tavily (búsqueda con include_domains)", "AGREGADOR", "multi", "B", "todos", "API",
     "PENDIENTE", "Plan y ToS a confirmar; es el proveedor principal propuesto (D2)."),
    ("api.exa.ai", "Exa", "AGREGADOR", "multi", "B", "todos", "API", "PENDIENTE", "Segundo proveedor (Fase 5)."),
    ("gnews.io", "GNews", "AGREGADOR", "multi", "B", "todos", "API", "PENDIENTE", "Respaldo por idioma."),
    # Redes
    ("x.com", "X/Twitter (@ATPChallenger, @ProTennisTour, trackers)", "RED", "en", "B", "challenger,utr,itf",
     "API de pago", "PENDIENTE", "Solo por API oficial; Fase 5 (D11)."),
    # Explícitamente NO
    ("flashscore.com", "Flashscore", "PRENSA", "multi", "A", "todos", "JSON interno", "REVISADO_NO",
     "Sus términos prohíben scraping, extracción y uso comercial. NO usar."),
    ("sofascore.com", "Sofascore", "PRENSA", "multi", "A", "todos", "JSON interno", "REVISADO_NO",
     "API interna, bloqueo por IP, ToS prohíbe acceso automatizado. NO usar."),
    ("tennisexplorer.com", "TennisExplorer", "PRENSA", "en", "A", "itf,challenger", "HTML", "PENDIENTE",
     "ret./w.o. de todo ITF; riesgo legal medio. Decisión D-TE: recomendado NO."),
)


def sembrar(conn, iniciales: Optional[list] = None) -> int:
    """Inserta lo que falte sin tocar lo ya revisado (autorizada / estado_tc
    guardados mandan). Las fuentes de `iniciales` (config.FUENTES_INICIALES,
    decisión de Rubén 08/10/2026) nacen autorizadas con estado REVISADO_OK y
    la nota de quién lo decidió; si después se quita desde la pestaña, no se
    vuelve a autorizar. Devuelve cuántas filas nuevas."""
    from ft_news import config as _cfg
    iniciales = set(_cfg.FUENTES_INICIALES if iniciales is None else iniciales)
    existentes = {r["dominio"] for r in conn.execute("SELECT dominio FROM news_fuente").fetchall()}
    nuevas = [c for c in CATALOGO if c[0] not in existentes]
    if not nuevas:
        return 0
    ahora = ahora_iso()

    def _fila(d, n, t, i, nv, c, a, e, nota):
        if d in iniciales and e == "PENDIENTE":
            return (d, n, t, i, nv, c, a, 1, "REVISADO_OK",
                    "Autorizada en el despliegue (decisión de Rubén, 08/10/2026). " + (nota or ""), ahora, "ruben", ahora)
        return (d, n, t, i, nv, c, a, 0, e, nota, None, None, ahora)

    def _w():
        conn.executemany(
            "INSERT INTO news_fuente (dominio, nombre, tipo, idioma, nivel_maximo, circuitos, acceso, autorizada, "
            "estado_tc, nota_tc, revisado_en, revisado_por, actualizado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [_fila(*c) for c in nuevas])
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)
    return len(nuevas)


def listar(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM news_fuente ORDER BY tipo, nombre").fetchall()]


def permitida(conn, dominio: str, cfg: dict) -> bool:
    """La compuerta que todo lector futuro debe pasar. Con
    NEWS_FUENTES_AUTORIZADAS_SOLO=1 (default) solo pasa autorizada=1."""
    if not cfg.get("NEWS_FUENTES_AUTORIZADAS_SOLO", 1):
        return True
    r = conn.execute("SELECT autorizada FROM news_fuente WHERE dominio=?", (dominio,)).fetchone()
    return bool(r and r["autorizada"])


def autorizar(conn, dominio: str, autorizada: bool, estado_tc: str, nota: str, por: str) -> dict:
    if estado_tc not in ("PENDIENTE", "REVISADO_OK", "REVISADO_NO", "REQUIERE_LICENCIA"):
        raise ValueError("estado_tc inválido")
    if autorizada and estado_tc != "REVISADO_OK":
        raise ValueError("Solo se puede autorizar una fuente con estado_tc=REVISADO_OK")
    ahora = ahora_iso()

    def _w():
        conn.execute("UPDATE news_fuente SET autorizada=?, estado_tc=?, nota_tc=?, revisado_en=?, revisado_por=?, "
                     "actualizado_en=? WHERE dominio=?",
                     (1 if autorizada else 0, estado_tc, nota, ahora, por, ahora, dominio))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)
    r = conn.execute("SELECT * FROM news_fuente WHERE dominio=?", (dominio,)).fetchone()
    if not r:
        raise ValueError("Fuente desconocida")
    return dict(r)
