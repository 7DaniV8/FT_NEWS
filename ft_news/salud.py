"""
ft_news/salud.py — Semáforo simple de FT NEWS (v7.2, 13/10/2026).

Rubén: "quiero un indicador sencillo de FUNCIONANDO, SIN DATOS o ERROR" y
"necesito poder comprobar que el bot está trabajando incluso cuando no genera
ningún pick". Cero alertas NO es un error: si el worker corre, busca, lee y
evalúa, está FUNCIONANDO aunque no haya nada que avisar.

  🔴 ERROR      algo impide trabajar o entregar: el worker no corre, un paso
                falló, el clasificador está caído, faltan claves, alertas que
                vencen sin que FT Intelligence las recoja, FT Intelligence no
                lee /news/senales, o "bandas calibradas" activada sin veredicto.
  🟡 SIN DATOS  el worker corre pero no le llega materia prima: sin partidos con
                cuota, sin búsquedas o sin artículos en 24 h, o radar en pausa por tope.
  🟢 FUNCIONANDO todo lo anterior en orden (con o sin alertas).

Cada estado viene con sus `motivos` en palabras y los indicadores que pidió Rubén.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import config, costos, descartes
from ft_news.db import estado_todo

FUNCIONANDO, SIN_DATOS, ERROR = "FUNCIONANDO", "SIN_DATOS", "ERROR"
PASOS_CRITICOS = ("padron", "partidos", "radar", "reintentos", "tematico", "rss", "contexto", "descubridor",
                  "alertas_vencidas", "cierre")
# v7.3 (Rubén: "toda la información visible en lenguaje sencillo, sin códigos técnicos")
NOMBRE_PASO = {"padron": "la lista de jugadores", "partidos": "la carga de partidos y cuotas",
               "radar": "la búsqueda de noticias", "reintentos": "la relectura de artículos pendientes",
               "tematico": "la búsqueda por temas (lesiones, retiros…)", "rss": "la lectura de los feeds de prensa",
               "contexto": "el cálculo de carga y viajes", "descubridor": "la evaluación de partidos",
               "alertas_vencidas": "la limpieza de alertas viejas", "cierre": "el cierre de resultados"}
VEREDICTO = {"CALIBRADAS_OK": "respaldada por nuestros datos", "NO_CALIBRADAS": "todavía no respaldada por nuestros datos",
             None: "todavía sin revisar"}
SENALES_MAX_MIN = 60          # FT Intelligence debería leer /news/senales al menos una vez por hora


def _dt(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        try:
            d = datetime.fromisoformat(str(s)[:19].replace(" ", "T"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _hace(d: Optional[datetime], ahora: datetime) -> str:
    if not d:
        return "nunca"
    m = max(0.0, (ahora - d).total_seconds() / 60)
    return f"hace {m:.0f} min" if m < 120 else (f"hace {m / 60:.1f} h" if m < 2880 else f"hace {m / 1440:.1f} días")


def _uno(conn, sql: str, args=()):
    r = conn.execute(sql, args).fetchone()
    return r[0] if r else None


def calcular(conn, cfg: Optional[dict] = None, ahora: Optional[datetime] = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    cfg = cfg or config.leer_config(conn)
    est = estado_todo(conn)
    v = lambda k: (est.get(k) or {}).get("valor")  # noqa: E731
    rojo, amarillo = [], []
    d24 = (ahora - timedelta(hours=24)).isoformat()

    # ── el worker
    ult = _dt(v("ultimo_ciclo_en"))
    limite = timedelta(seconds=2 * config.CICLO_SEGUNDOS + 300)
    if not cfg.get("NEWS_ACTIVO"):
        rojo.append("el motor está apagado")
    elif not ult or ahora - ult > limite:
        rojo.append(f"el bot no completa una revisión desde {_hace(ult, ahora)} (debería hacerlo cada "
                    f"{config.CICLO_SEGUNDOS // 60} min)")
    errores_pasos = []
    for p in PASOS_CRITICOS:
        val = str(v(f"paso_{p}") or "")
        if val.startswith("ERROR"):
            errores_pasos.append({"paso": p, "detalle": val[:300]})
            rojo.append(f"falló {NOMBRE_PASO.get(p, p)} (el detalle técnico está en Administración)")
    caido = v("clasificador_caido")
    if caido and _dt(str(caido).split(" ")[1] if len(str(caido).split(" ")) > 1 else None) and \
            ahora - _dt(str(caido).split(" ")[1]) < timedelta(hours=6):
        rojo.append("la IA que lee las noticias no responde (se reintenta sola)")
    motivo = str(v("motivo") or "")
    if motivo.startswith("radar sin"):
        rojo.append("faltan las claves del buscador de noticias o de la IA")
    elif motivo.startswith("radar dormido"):
        amarillo.append("la búsqueda de noticias está en pausa porque se alcanzó el tope de gasto")

    # ── entrega a FT Intelligence
    discord = bool(cfg.get("NEWS_DISCORD_ACTIVO"))
    leidas = _dt(v("senales_leidas_en"))
    vencidas = _uno(conn, "SELECT COUNT(*) FROM news_alerta WHERE dicho_discord=2 AND dicho_motivo='VENCIDA' "
                          "AND COALESCE(prueba,0)=0 AND dicho_en>=?", (d24,)) or 0
    if discord:
        if vencidas:
            rojo.append(f"{vencidas} alerta(s) vencieron en 24 h sin que FT Intelligence las recogiera")
        if not leidas:
            amarillo.append("todavía no hay registro de que FT Intelligence revise la cola de alertas")
        elif ahora - leidas > timedelta(minutes=SENALES_MAX_MIN):
            rojo.append(f"FT Intelligence no revisa la cola de alertas desde {_hace(leidas, ahora)}")
    else:
        amarillo.append("el envío a Discord está apagado: las alertas se generan pero no salen")

    # ── bandas
    veredicto = v("calibracion_veredicto")
    if int(cfg.get("NEWS_BANDAS_CALIBRADAS", 0)) and veredicto != "CALIBRADAS_OK":
        rojo.append("«bandas calibradas» está activada, pero la calibración "
                    f"está {VEREDICTO.get(veredicto, VEREDICTO[None])}"
                    + (" (no se aplica: los 🔥 salen como experimentales)" if int(cfg.get("NEWS_BANDAS_EXIGIR_VEREDICTO", 1))
                       else " y SE ESTÁ APLICANDO: los 🔥 salen como validados sin evidencia"))

    # ── materia prima
    fut = 0
    for r in conn.execute("SELECT fecha_estimada, cuota1, cuota2 FROM news_partido WHERE estado='PROGRAMADO'").fetchall():
        f = _dt(r["fecha_estimada"])
        if f and ahora < f <= ahora + timedelta(hours=int(cfg.get("NEWS_VENTANA_PARTIDO_HORAS", 72))) and r["cuota1"] and r["cuota2"]:
            fut += 1
    busq24 = _uno(conn, "SELECT COUNT(*) FROM news_busqueda WHERE creado_en>=?", (d24,)) or 0
    art24 = _uno(conn, "SELECT COUNT(*) FROM news_articulo WHERE creado_en>=?", (d24,)) or 0
    if cfg.get("NEWS_ACTIVO"):
        if not fut:
            amarillo.append("no hay partidos próximos con cuota (¿llegan los partidos desde FullTennis?)")
        if not busq24 and not motivo.startswith("radar"):
            amarillo.append("ninguna búsqueda de noticias en 24 h")
        if not art24:
            amarillo.append("ningún artículo leído en 24 h")

    # ── indicadores (los que pidió Rubén)
    ext = descartes._EXTERNO_SQL
    ultima_busqueda = _dt(_uno(conn, "SELECT MAX(creado_en) FROM news_busqueda"))
    proxima = (ult + timedelta(seconds=config.CICLO_SEGUNDOS)) if ult else None
    errores_conexion = (_uno(conn, "SELECT COUNT(*) FROM news_articulo WHERE resultado IN ('ERROR','PENDIENTE','AGOTADO') "
                                   "AND creado_en>=?", (d24,)) or 0)
    indicadores = {
        "ultima_busqueda_exitosa": ultima_busqueda.isoformat() if ultima_busqueda else None,
        "ultima_busqueda_hace": _hace(ultima_busqueda, ahora),
        "proxima_busqueda_programada": proxima.isoformat() if proxima else None,
        "ultimo_ciclo_hace": _hace(ult, ahora),
        "jugadores_vigilados": _uno(conn, "SELECT COUNT(*) FROM news_jugador_cola") or 0,
        "partidos_proximos_con_cuota": fut,
        "partidos_analizados_24h": _uno(conn, "SELECT COUNT(*) FROM news_evaluacion WHERE COALESCE(actualizado_en, creado_en)>=?",
                                        (d24,)) or 0,
        "busquedas_24h": busq24,
        "articulos_leidos_24h": art24,
        "noticias_encontradas_24h": _uno(conn, f"SELECT COUNT(*) FROM news_evento e WHERE {ext} AND e.creado_en>=?", (d24,)) or 0,
        "noticias_verificadas_24h": _uno(conn, f"SELECT COUNT(*) FROM news_evento e WHERE {ext} AND e.creado_en>=? "
                                              "AND e.naturaleza='HECHO' AND e.nivel IN ('A','B') "
                                              "AND e.estado IN ('VIGENTE','EN_SEGUIMIENTO')", (d24,)) or 0,
        "noticias_descartadas_24h": (_uno(conn, "SELECT COUNT(*) FROM news_articulo WHERE creado_en>=? "
                                                "AND COALESCE(resultado,'')<>'EVENTO'", (d24,)) or 0)
                                    + (_uno(conn, "SELECT COUNT(*) FROM news_descarte WHERE etapa='NOTICIA' AND ultima_en>=?",
                                            (d24,)) or 0),
        "partidos_interesantes_24h": _uno(conn, "SELECT COUNT(*) FROM news_alerta WHERE tipo='INTERESANTE' "
                                                "AND COALESCE(prueba,0)=0 AND creado_en>=?", (d24,)) or 0,
        "picks_generados_24h": _uno(conn, "SELECT COUNT(*) FROM news_alerta WHERE tipo IN ('FUEGO','FUEGO_EXPERIMENTAL') "
                                          "AND COALESCE(prueba,0)=0 AND creado_en>=?", (d24,)) or 0,
        "picks_procesados_intel_24h": _uno(conn, "SELECT COUNT(*) FROM news_alerta WHERE tipo IN ('FUEGO','FUEGO_EXPERIMENTAL') "
                                         "AND COALESCE(prueba,0)=0 AND dicho_discord=1 AND creado_en>=?", (d24,)) or 0,
        # v7.3: "recibida" (FT Intelligence la procesó) ≠ "publicada" (FT Discord lo confirmó)
        "alertas_recibidas_intel_24h": _uno(conn, "SELECT COUNT(*) FROM news_alerta WHERE COALESCE(prueba,0)=0 "
                                                  "AND entregada_en>=?", (d24,)) or 0,
        "alertas_procesadas_intel_24h": _uno(conn, "SELECT COUNT(*) FROM news_alerta WHERE COALESCE(prueba,0)=0 AND dicho_discord=1 "
                                                   "AND dicho_en>=?", (d24,)) or 0,
        "alertas_publicadas_confirmadas_24h": _uno(conn, "SELECT COUNT(*) FROM news_alerta WHERE COALESCE(prueba,0)=0 "
                                                         "AND publicado=1 AND publicado_en>=?", (d24,)) or 0,
        "alertas_fallo_publicacion_24h": _uno(conn, "SELECT COUNT(*) FROM news_alerta WHERE COALESCE(prueba,0)=0 "
                                                    "AND publicado=0 AND publicado_en>=?", (d24,)) or 0,
        "errores_de_pasos": [dict(e, nombre=NOMBRE_PASO.get(e["paso"], e["paso"])) for e in errores_pasos],
        "errores_clasificacion_24h": errores_conexion,
        "ft_intelligence_leyo_senales": _hace(leidas, ahora),
        "calibracion": {"veredicto": veredicto, "texto": VEREDICTO.get(veredicto, VEREDICTO[None]),
                        "configurada": int(cfg.get("NEWS_BANDAS_CALIBRADAS", 0)),
                        "efectiva": int(descartes.bandas_efectivas(cfg, veredicto)),
                        "muestra": v("calibracion_muestra"), "revisada": _hace(_dt(v("calibracion_en")), ahora)},
        "gasto_hoy": costos.hoy(conn),
    }
    estado = ERROR if rojo else (SIN_DATOS if amarillo else FUNCIONANDO)
    return {"estado": estado, "icono": {"FUNCIONANDO": "🟢", "SIN_DATOS": "🟡", "ERROR": "🔴"}[estado],
            "motivos": rojo + amarillo, "errores": rojo, "avisos": amarillo,
            "indicadores": indicadores, "calculado_en": ahora.isoformat()}
