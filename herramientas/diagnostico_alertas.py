#!/usr/bin/env python3
"""
herramientas/diagnostico_alertas.py — ¿Por qué FT NEWS no envía alertas?
(13/10/2026, Rubén: "no estoy recibiendo alertas y no sabemos si FT NEWS está
funcionando realmente").

SOLO LECTURA: abre la base en modo `ro`, no escribe, no llama a ningún
proveedor ni a Discord. Reconstruye el embudo completo con los datos reales:

  1. ¿El worker está vivo?          (último ciclo, estado de cada paso)
  2. ¿Llegan partidos y cuotas?      (RankingFTR → news_partido)
  3. ¿Investiga?                     (búsquedas, artículos y su resultado)
  4. ¿Encuentra noticias?            (eventos externos vs calculados)
  5. 📰 ¿Por qué cada noticia salió o no?   (mismas reglas que alertas.noticia_importante)
  6. 🔎/🔥 ¿Por qué cada partido salió o no? (mismas reglas que alertas.partido_interesante)
  7. ¿Se entregó?                    (news_alerta: pendiente / dicha / omitida + motivo)
  8. Configuración efectiva y gasto

Las reglas 5 y 6 están copiadas de ft_news/alertas.py v7.1 SIN importarlo,
para que el script no tenga efectos secundarios (noticia_importante inserta
filas). Si se cambian esas reglas, actualizar este archivo.

Uso, dentro del servicio FT_NEWS en Railway (la base está en el volumen):

    railway ssh --service FT_NEWS
    python herramientas/diagnostico_alertas.py            # usa FT_NEWS_DB_PATH o /data/ft_news.db
    python herramientas/diagnostico_alertas.py --horas 48 --json /tmp/diag.json

o sobre una copia descargada de la base:

    python herramientas/diagnostico_alertas.py --db ./ft_news.db
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

# ── reglas copiadas de ft_news (v7.1) ───────────────────────────────────────
FUENTE_INTERNA = "rankingftr.interno"
FUERTES = {"CARGA_FISICA", "ENFERMEDAD", "LESION_MOLESTIA", "REGRESO", "RETIRO_ABANDONO", "SANCION_DISCIPLINA"}
NOTICIA_FUERTE = {"LESION_MOLESTIA", "ENFERMEDAD", "RETIRO_ABANDONO", "REGRESO", "SANCION_DISCIPLINA"}
NOTICIA_OFICIAL = {"DECLARACION_PREPARACION", "DECLARACION_MOTIVACION", "VIAJE_CALENDARIO",
                   "SITUACION_PERSONAL", "CAMBIO_EQUIPO"}
RANGO = {"A": 3, "B": 2, "C": 1}
DEFAULTS = {"NEWS_ACTIVO": 1, "NEWS_DISCORD_ACTIVO": 1, "NEWS_DISCORD_NOTICIA": 1, "NEWS_DISCORD_INTERESANTE": 1,
            "NEWS_EXPERIMENTAL_ACTIVO": 1, "NEWS_BANDAS_CALIBRADAS": 0, "NEWS_BANDAS_AUTO": 0,
            "NEWS_IDENTIDAD_MIN": 0.8, "NEWS_NOTICIA_MAX_DIAS": 7, "NEWS_RIVAL_HORAS": 48,
            "NEWS_SENAL_MAX_HORAS": 12, "NEWS_VENTANA_PARTIDO_HORAS": 72, "NEWS_MAX_NOTICIA_DIA": 8,
            "NEWS_MAX_INTERESANTE_DIA": 6, "NEWS_MAX_BUSQUEDAS_DIA": 250}

AHORA = datetime.now(timezone.utc)
salida: dict = {"generado_en": AHORA.isoformat()}


def dt(s):
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


def hace(s) -> str:
    d = dt(s)
    if not d:
        return "nunca"
    m = (AHORA - d).total_seconds() / 60
    return f"hace {m:.0f} min" if m < 120 else (f"hace {m / 60:.1f} h" if m < 2880 else f"hace {m / 1440:.1f} días")


def titulo(t: str) -> None:
    print(f"\n{'═' * 78}\n{t}\n{'═' * 78}")


def fila(icono: str, texto: str) -> None:
    print(f"  {icono} {texto}")


def q(conn, sql: str, args=()) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError as e:
        fila("⚠️", f"consulta no disponible en esta versión de la base: {e}")
        return []


def cols(conn, tabla: str) -> set:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})")}
    except sqlite3.Error:
        return set()


def uno(conn, sql: str, args=()):
    try:
        r = conn.execute(sql, args).fetchone()
        return r[0] if r else None
    except sqlite3.OperationalError:
        return None


def es_externo(e: dict) -> bool:
    if e.get("origen") in ("EXTERNO", "INTERNO"):
        return e["origen"] == "EXTERNO"
    if e.get("articulo_id"):
        return True
    return str(e.get("fuente") or "") != FUENTE_INTERNA and not str(e.get("enlace") or "").startswith("contexto:")


def config_efectiva(conn) -> dict:
    cfg = dict(DEFAULTS)
    for k in list(cfg):
        if os.getenv(k) not in (None, ""):
            cfg[k] = os.getenv(k)
    for r in q(conn, "SELECT clave, valor, actualizado_en, actualizado_por FROM news_config"):
        cfg[r["clave"]] = r["valor"]
    for k, v in list(cfg.items()):
        try:
            cfg[k] = float(v) if "." in str(v) else int(v)
        except (TypeError, ValueError):
            pass
    return cfg


# ── 0 · RESUMEN (las preguntas de Rubén, en orden) ─────────────────────
def seccion_resumen(conn, cfg, horas: int) -> None:
    titulo(f"0 · RESUMEN DE LAS ÚLTIMAS {horas} HORAS (lo que pidió Rubén, en orden)")
    desde = (AHORA - timedelta(hours=horas)).isoformat()
    ca = cols(conn, "news_alerta")
    ext = "(origen='EXTERNO' OR (origen IS NULL AND articulo_id IS NOT NULL))" if "origen" in cols(conn, "news_evento") \
        else "(articulo_id IS NOT NULL)"
    r = {}
    r["1_jugadores_vigilados"] = uno(conn, "SELECT COUNT(*) FROM news_jugador_cola")
    r["1b_jugadores_buscados"] = uno(conn, "SELECT COUNT(DISTINCT jugador_id) FROM news_busqueda WHERE creado_en>=? AND jugador_id IS NOT NULL", (desde,))
    r["2_partidos_recibidos"] = uno(conn, "SELECT COUNT(*) FROM news_partido WHERE actualizado_en>=?", (desde,))
    r["2b_con_cuota"] = uno(conn, "SELECT COUNT(*) FROM news_partido WHERE actualizado_en>=? AND cuota1 IS NOT NULL AND cuota2 IS NOT NULL", (desde,))
    r["3_busquedas_externas"] = uno(conn, "SELECT COUNT(*) FROM news_busqueda WHERE creado_en>=?", (desde,))
    r["3b_busquedas_sin_resultado"] = uno(conn, "SELECT COUNT(*) FROM news_busqueda WHERE creado_en>=? AND COALESCE(resultados,0)=0", (desde,))
    r["4_articulos_leidos"] = uno(conn, "SELECT COUNT(*) FROM news_articulo WHERE creado_en>=?", (desde,))
    r["4b_noticias_externas"] = uno(conn, f"SELECT COUNT(*) FROM news_evento WHERE {ext} AND creado_en>=?", (desde,))
    r["4c_datos_calculados"] = uno(conn, f"SELECT COUNT(*) FROM news_evento WHERE NOT {ext} AND creado_en>=?", (desde,))
    r["5_articulos_descartados"] = uno(conn, "SELECT COUNT(*) FROM news_articulo WHERE creado_en>=? AND COALESCE(resultado,'')<>'EVENTO'", (desde,))
    eva = q(conn, "SELECT tipo_alerta, COUNT(*) n FROM news_evaluacion WHERE COALESCE(actualizado_en, creado_en)>=? GROUP BY 1", (desde,))
    r["6_partidos_evaluados"] = sum(x["n"] for x in eva)
    r["6b_evaluados_por_tipo"] = {x["tipo_alerta"]: x["n"] for x in eva}
    r["7_oportunidades_detectadas_fuego"] = sum(x["n"] for x in eva if x["tipo_alerta"] in ("FUEGO", "FUEGO_EXPERIMENTAL"))
    r["7b_partidos_interesantes"] = sum(x["n"] for x in eva if x["tipo_alerta"] == "INTERESANTE")
    sin_prueba = "AND COALESCE(prueba,0)=0" if "prueba" in ca else ""
    al = q(conn, f"SELECT tipo, dicho_discord, COALESCE(dicho_motivo,'') motivo, COUNT(*) n FROM news_alerta "
                 f"WHERE creado_en>=? {sin_prueba} GROUP BY 1,2,3", (desde,))
    r["8_alertas_creadas"] = sum(x["n"] for x in al)
    por_tipo = Counter()
    for x in al:
        por_tipo[x["tipo"]] += x["n"]
    r["8b_alertas_por_tipo"] = dict(por_tipo)
    if "entregada_en" in ca:
        r["9_recibidas_por_ft_intelligence"] = uno(conn, f"SELECT COUNT(*) FROM news_alerta WHERE creado_en>=? {sin_prueba} AND entregada_en IS NOT NULL", (desde,))
    else:
        r["9_recibidas_por_ft_intelligence"] = None
        r["9_aproximado_procesadas_por_ft_intelligence"] = sum(x["n"] for x in al if x["dicho_discord"] == 1)
    r["9c_vencidas_sin_recoger"] = sum(x["n"] for x in al if x["dicho_discord"] == 2 and x["motivo"] == "VENCIDA")
    r["9d_omitidas_otros_motivos"] = {x["motivo"]: x["n"] for x in al if x["dicho_discord"] == 2 and x["motivo"] != "VENCIDA"}
    r["9e_todavia_pendientes"] = sum(x["n"] for x in al if x["dicho_discord"] == 0)
    if "publicado" in ca:
        r["10_publicadas_confirmadas_por_ft_discord"] = uno(conn, f"SELECT COUNT(*) FROM news_alerta WHERE creado_en>=? {sin_prueba} AND publicado=1", (desde,))
        r["10b_fallo_publicacion"] = uno(conn, f"SELECT COUNT(*) FROM news_alerta WHERE creado_en>=? {sin_prueba} AND publicado=0", (desde,))
    else:
        r["10_publicadas_confirmadas_por_ft_discord"] = None
    salida["resumen"] = r

    def n(v):
        return "—" if v is None else v
    fila("1.", f"Jugadores vigilados: {n(r['1_jugadores_vigilados'])} (buscados al menos una vez en {horas} h: {n(r['1b_jugadores_buscados'])})")
    fila("2.", f"Partidos recibidos de FullTennis: {n(r['2_partidos_recibidos'])} (con cuota: {n(r['2b_con_cuota'])})")
    fila("3.", f"Búsquedas externas: {n(r['3_busquedas_externas'])} (sin ningún resultado: {n(r['3b_busquedas_sin_resultado'])})")
    fila("4.", f"Noticias encontradas: {n(r['4b_noticias_externas'])} de medios, a partir de {n(r['4_articulos_leidos'])} artículos leídos "
               f"(aparte, {n(r['4c_datos_calculados'])} datos calculados por nosotros, que no son noticias)")
    fila("5.", f"Artículos descartados: {n(r['5_articulos_descartados'])} (motivos en las secciones 3 y 5)")
    fila("6.", f"Partidos evaluados: {r['6_partidos_evaluados']} → {r['6b_evaluados_por_tipo']}")
    fila("7.", f"Oportunidades detectadas (🔥): {r['7_oportunidades_detectadas_fuego']} · partidos interesantes (🔎): {r['7b_partidos_interesantes']}")
    fila("8.", f"Alertas creadas: {r['8_alertas_creadas']} → {r['8b_alertas_por_tipo']}")
    if r["9_recibidas_por_ft_intelligence"] is None:
        fila("9.", f"Recibidas por FT Intelligence: esta versión no lo registra. Aproximación: FT Intelligence marcó como procesadas "
                   f"{r['9_aproximado_procesadas_por_ft_intelligence']}")
    else:
        fila("9.", f"Recibidas por FT Intelligence: {r['9_recibidas_por_ft_intelligence']}")
    fila(" ", f"   vencieron sin que FT Intelligence las recogiera: {r['9c_vencidas_sin_recoger']} · descartadas por otros motivos: "
              f"{r['9d_omitidas_otros_motivos'] or 0} · todavía pendientes: {r['9e_todavia_pendientes']}")
    if r["10_publicadas_confirmadas_por_ft_discord"] is None:
        fila("10.", "Publicadas realmente por FT Discord: NO se puede saber desde FT NEWS (antes de v7.3 nadie lo informaba). "
                    "Hay que contrastar con el canal de Discord o con FT Intelligence.")
    else:
        fila("10.", f"Publicadas, confirmadas por FT Discord: {r['10_publicadas_confirmadas_por_ft_discord']} (fallaron: {r.get('10b_fallo_publicacion')})")
    dias = q(conn, f"SELECT substr(creado_en,1,10) dia, COUNT(*) n FROM news_busqueda WHERE creado_en>=? GROUP BY 1 ORDER BY 1", (desde,))
    dext = {x["dia"]: x["n"] for x in q(conn, f"SELECT substr(creado_en,1,10) dia, COUNT(*) n FROM news_evento WHERE {ext} AND creado_en>=? GROUP BY 1", (desde,))}
    dal = {x["dia"]: x["n"] for x in q(conn, f"SELECT substr(creado_en,1,10) dia, COUNT(*) n FROM news_alerta WHERE creado_en>=? {sin_prueba} GROUP BY 1", (desde,))}
    fila("•", "por día (búsquedas · noticias externas · alertas creadas):")
    for x in dias:
        fila(" ", f"   {x['dia']}: {x['n']:>4} · {dext.get(x['dia'], 0):>3} · {dal.get(x['dia'], 0):>3}")


# ── 9 · problemas por área ──────────────────────────────────────────────
def seccion_problemas(conn, cfg, horas: int) -> None:
    titulo("9 · PROBLEMAS POR ÁREA (API, cuotas, identificación, rivales, conexión)")
    desde = (AHORA - timedelta(hours=horas)).isoformat()
    est = {r["clave"]: r["valor"] for r in q(conn, "SELECT clave, valor FROM news_estado")}
    out = {}
    # API / proveedores
    errs = {k[5:]: v for k, v in est.items() if k.startswith("paso_") and str(v).startswith("ERROR")}
    art_err = {x["resultado"]: x["n"] for x in q(conn, "SELECT resultado, COUNT(*) n FROM news_articulo WHERE creado_en>=? "
                                                       "AND resultado IN ('ERROR','PENDIENTE','AGOTADO','FUERA_DE_ESQUEMA') GROUP BY 1", (desde,))}
    bus = uno(conn, "SELECT COUNT(*) FROM news_busqueda WHERE creado_en>=?", (desde,)) or 0
    vac = uno(conn, "SELECT COUNT(*) FROM news_busqueda WHERE creado_en>=? AND COALESCE(resultados,0)=0", (desde,)) or 0
    tope = int(cfg.get("NEWS_MAX_BUSQUEDAS_DIA", 250))
    max_dia = max([x["n"] for x in q(conn, "SELECT substr(creado_en,1,10) d, COUNT(*) n FROM news_busqueda WHERE creado_en>=? GROUP BY 1", (desde,))] or [0])
    fila("🔴" if errs else "🟢", f"API · pasos con error ahora: {errs or 'ninguno'}")
    fila("🔴" if est.get("clasificador_caido") else "🟢", f"API · IA clasificadora: {est.get('clasificador')} {('· CAÍDA: ' + est['clasificador_caido']) if est.get('clasificador_caido') else ''}")
    fila("🟡" if art_err else "🟢", f"API · artículos que la IA no pudo leer: {art_err or 'ninguno'}")
    fila("🟡" if bus and vac / bus > 0.8 else "•", f"API · búsquedas sin resultado: {vac}/{bus} ({(100 * vac / bus) if bus else 0:.0f} %)")
    fila("🟡" if max_dia >= tope else "•", f"API · máximo de búsquedas en un día: {max_dia} (tope {tope})" + (" ← se llegó al tope: el radar se durmió" if max_dia >= tope else ""))
    out["api"] = {"pasos_error": errs, "articulos_error": art_err, "busquedas": bus, "sin_resultado": vac, "max_dia": max_dia, "tope": tope}
    # cuotas
    fut = [dict(x) for x in q(conn, "SELECT id, fecha_estimada, cuota1, cuota2, cuota_en FROM news_partido WHERE estado='PROGRAMADO'")]
    fut = [x for x in fut if dt(x["fecha_estimada"]) and AHORA < dt(x["fecha_estimada"]) <= AHORA + timedelta(hours=72)]
    con = [x for x in fut if x["cuota1"] and x["cuota2"]]
    fres = [x for x in con if dt(x.get("cuota_en")) and dt(x["cuota_en"]) > AHORA - timedelta(hours=2)]
    edades = sorted(((AHORA - dt(x["cuota_en"])).total_seconds() / 3600) for x in con if dt(x.get("cuota_en")))
    med = edades[len(edades) // 2] if edades else None
    obs = uno(conn, "SELECT COUNT(*) FROM news_cuota_obs WHERE capturada_en>=?", (desde,))
    fila("🔴" if not con else ("🟡" if len(fres) < len(con) / 2 else "🟢"),
         f"Cuotas · próximos {len(fut)} partidos: con cuota {len(con)} · actualizada en < 2 h {len(fres)} · antigüedad mediana "
         f"{'—' if med is None else f'{med:.1f} h'} · observaciones de cuota en {horas} h: {obs if obs is not None else '—'}")
    out["cuotas"] = {"proximos": len(fut), "con_cuota": len(con), "frescas_2h": len(fres), "mediana_h": med}
    # identificación
    idd = uno(conn, "SELECT COUNT(*) FROM news_articulo WHERE creado_en>=? AND resultado='IDENTIDAD_DUDOSA'", (desde,)) or 0
    otro = uno(conn, "SELECT COUNT(*) FROM news_articulo WHERE creado_en>=? AND resultado='OTRO_JUGADOR'", (desde,)) or 0
    rev = uno(conn, "SELECT COUNT(*) FROM news_revision WHERE estado='PENDIENTE' AND tipo='IDENTIDAD_DUDOSA'") or 0
    sin_utr = uno(conn, "SELECT COUNT(*) FROM news_jugador WHERE utr_singles IS NULL") or 0
    tot_j = uno(conn, "SELECT COUNT(*) FROM news_jugador") or 0
    fila("🟡" if idd or rev else "🟢", f"Identificación · artículos con jugador dudoso: {idd} · de otro jugador: {otro} · "
                                       f"en revisión sin resolver: {rev} · jugadores sin UTR: {sin_utr}/{tot_j}")
    out["identificacion"] = {"dudosos": idd, "otro_jugador": otro, "revision_pendiente": rev, "sin_utr": sin_utr, "jugadores": tot_j}
    # rivales
    horas_r = int(cfg.get("NEWS_RIVAL_HORAS", 48))
    sin_rival = 0
    con_noticia = 0
    for x in fut:
        p = q(conn, "SELECT jugador1_id, jugador2_id FROM news_partido WHERE id=?", (x["id"],))
        if not p:
            continue
        j1, j2 = p[0]["jugador1_id"], p[0]["jugador2_id"]
        evs = activos(conn, j1) + activos(conn, j2)
        if not any(es_externo(e) and e.get("categoria") in FUERTES and RANGO.get(str(e.get("nivel") or "C"), 1) >= 2 for e in evs):
            continue
        con_noticia += 1
        if not (fresco(conn, j1, horas_r)[0] and fresco(conn, j2, horas_r)[0]):
            sin_rival += 1
    fila("🟡" if sin_rival else "🟢", f"Rivales · próximos partidos con noticia fuerte: {con_noticia} · a los que les falta investigar a uno "
                                     f"de los dos (> {horas_r} h): {sin_rival}")
    out["rivales"] = {"con_noticia": con_noticia, "falta_investigar": sin_rival}
    # conexión entre servicios
    ult = est.get("ultimo_ciclo_en")
    padron, partidos_ = str(est.get("paso_padron") or ""), str(est.get("paso_partidos") or "")
    upd = uno(conn, "SELECT MAX(actualizado_en) FROM news_partido")
    leidas = est.get("senales_leidas_en")
    ult_dicho = uno(conn, "SELECT MAX(dicho_en) FROM news_alerta WHERE dicho_discord=1")
    fila("🟢" if dt(ult) and AHORA - dt(ult) < timedelta(minutes=35) else "🔴", f"Conexión · último ciclo de FT NEWS: {hace(ult)}")
    fila("🟢" if padron.startswith("OK") and partidos_.startswith("OK") else "🔴",
         f"Conexión · FullTennis → FT NEWS: jugadores {padron[:2] or '—'}, partidos {partidos_[:2] or '—'} · última actualización de partidos {hace(upd)}")
    if leidas:
        fila("🟢" if dt(leidas) and AHORA - dt(leidas) < timedelta(hours=1) else "🔴", f"Conexión · FT NEWS → FT Intelligence: FT Intelligence revisó la cola {hace(leidas)}")
    else:
        fila("🟡", f"Conexión · FT NEWS → FT Intelligence: esta versión no registra cuándo FT Intelligence revisa la cola; "
                   f"la última alerta que marcó como procesada fue {hace(ult_dicho)}")
    fila("•", "Conexión · FT Intelligence → FT Discord → comunidad: no se ve desde FT NEWS; se comprueba con el código de los dos y la prueba de admin.")
    out["conexion"] = {"ultimo_ciclo": ult, "padron": padron[:80], "partidos": partidos_[:80], "partidos_actualizados": upd,
                       "intel_leyo": leidas, "ultima_procesada": ult_dicho}
    salida["problemas"] = out


# ── 1 · worker ─────────────────────────────────────────────────────────────
def seccion_worker(conn) -> None:
    titulo("1 · ¿EL WORKER ESTÁ VIVO?")
    est = {r["clave"]: r for r in q(conn, "SELECT clave, valor, actualizado_en FROM news_estado")}
    salida["estado"] = {k: v["valor"] for k, v in est.items()}
    ult = (est.get("ultimo_ciclo_en") or {}).get("valor")
    d = dt(ult)
    vivo = bool(d and d > AHORA - timedelta(minutes=35))
    fila("🟢" if vivo else "🔴", f"último ciclo: {ult or 'nunca'} ({hace(ult)})" + ("" if vivo else "  ← el worker NO está corriendo"))
    fila("•", f"motivo: {(est.get('motivo') or {}).get('valor')}")
    fila("•", f"clasificador: {(est.get('clasificador') or {}).get('valor')}")
    if est.get("clasificador_caido"):
        fila("🔴", f"clasificador caído: {est['clasificador_caido']['valor']}")
    for paso in ("padron", "calibracion", "partidos", "vencimientos", "contexto", "radar", "reintentos",
                 "tematico", "rss", "descubridor", "alertas_vencidas", "cierre"):
        v = (est.get(f"paso_{paso}") or {}).get("valor")
        ic = "⚪" if not v else ("🟢" if str(v).startswith("OK") else "🔴")
        fila(ic, f"{paso:<16} {str(v or 'nunca corrió')[:150]}")
    fila("•", f"calibración: {(est.get('calibracion_veredicto') or {}).get('valor')} · muestra "
              f"{(est.get('calibracion_muestra') or {}).get('valor')} · {hace((est.get('calibracion_en') or {}).get('valor'))}")
    raz = (est.get("calibracion_razones") or {}).get("valor")
    if raz:
        fila(" ", f"razones: {raz[:300]}")


# ── 2 · partidos y cuotas ──────────────────────────────────────────────────
def seccion_partidos(conn, cfg) -> list[dict]:
    titulo("2 · ¿LLEGAN PARTIDOS Y CUOTAS DESDE RANKINGFTR?")
    ventana = int(cfg.get("NEWS_VENTANA_PARTIDO_HORAS", 72))
    filas = q(conn, "SELECT * FROM news_partido WHERE estado='PROGRAMADO'")
    prox = []
    for p in filas:
        f = dt(p.get("fecha_estimada"))
        if f and (f - AHORA).total_seconds() / 3600 > ventana:
            continue
        prox.append(p)
    futuros = [p for p in prox if dt(p.get("fecha_estimada")) and dt(p["fecha_estimada"]) > AHORA]
    con_cuota = [p for p in futuros if p.get("cuota1") and p.get("cuota2")]
    frescas = [p for p in con_cuota if dt(p.get("cuota_en")) and dt(p["cuota_en"]) > AHORA - timedelta(hours=2)]
    ult = q(conn, "SELECT MAX(actualizado_en) m FROM news_partido")
    fila("🟢" if futuros else "🔴", f"partidos PROGRAMADOS que aún no empezaron (≤ {ventana} h): {len(futuros)}")
    fila("🟢" if con_cuota else "🔴", f"con cuota: {len(con_cuota)} · cuota actualizada en las últimas 2 h: {len(frescas)}")
    fila("•", f"última actualización de partidos: {hace(ult[0]['m'] if ult else None)}")
    viejos = [p for p in prox if dt(p.get("fecha_estimada")) and dt(p["fecha_estimada"]) < AHORA - timedelta(hours=12)]
    if viejos:
        fila("⚠️", f"{len(viejos)} partidos siguen PROGRAMADO con fecha de hace más de 12 h (el cierre no los está cerrando)")
    circ = Counter((p.get("circuito") or "?") for p in futuros)
    fila("•", f"por circuito: {dict(circ)}")
    salida["partidos"] = {"futuros": len(futuros), "con_cuota": len(con_cuota), "cuota_fresca_2h": len(frescas),
                          "por_circuito": dict(circ), "programados_viejos": len(viejos)}
    return futuros


# ── 3 · investigación ──────────────────────────────────────────────────────
def seccion_radar(conn, horas: int) -> None:
    titulo(f"3 · ¿INVESTIGA? (últimas {horas} h)")
    desde = (AHORA - timedelta(hours=horas)).isoformat()
    b = q(conn, "SELECT COALESCE(origen,'radar') origen, proveedor, COUNT(*) n, SUM(CASE WHEN COALESCE(resultados,0)=0 THEN 1 ELSE 0 END) vacias, "
                "MAX(creado_en) ultima FROM news_busqueda WHERE creado_en>=? GROUP BY 1,2", (desde,))
    tot = sum(r["n"] for r in b)
    ult = max((r["ultima"] for r in b if r["ultima"]), default=None)
    fila("🟢" if tot else "🔴", f"búsquedas: {tot} · última: {ult or 'ninguna'} ({hace(ult)})")
    for r in b:
        fila(" ", f"{r['origen']:<9} {r['proveedor']:<8} {r['n']:>5} búsquedas · {r['vacias']} sin resultado")
    a = q(conn, "SELECT COALESCE(resultado,'(sin resultado)') resultado, COUNT(*) n FROM news_articulo WHERE creado_en>=? GROUP BY 1 ORDER BY 2 DESC", (desde,))
    fila("🟢" if a else "🟡", f"artículos leídos: {sum(r['n'] for r in a)}")
    for r in a:
        fila(" ", f"{r['resultado']:<22} {r['n']}")
    mot = q(conn, "SELECT resultado, motivo, COUNT(*) n FROM news_articulo WHERE creado_en>=? AND COALESCE(resultado,'')<>'EVENTO' "
                  "GROUP BY 1,2 ORDER BY 3 DESC LIMIT 8", (desde,))
    if mot:
        fila("•", "motivos de descarte más frecuentes:")
        for r in mot:
            fila(" ", f"{r['n']:>4} · {r['resultado']} · {str(r['motivo'] or '')[:100]}")
    cola = q(conn, "SELECT circuito, COUNT(*) n, SUM(CASE WHEN ultima_busqueda_en IS NULL THEN 1 ELSE 0 END) nunca, "
                   "SUM(CASE WHEN ultima_busqueda_en>=? THEN 1 ELSE 0 END) recientes FROM news_jugador_cola GROUP BY 1",
             ((AHORA - timedelta(hours=48)).isoformat(),))
    fila("•", "cola de vigilancia (jugadores · nunca buscados · buscados en 48 h):")
    for r in cola:
        fila(" ", f"{str(r['circuito'] or '?'):<12} {r['n']:>6} · {r['nunca']:>6} · {r['recientes']:>5}")
    err = q(conn, "SELECT ultimo_error, COUNT(*) n FROM news_jugador_cola WHERE COALESCE(ultimo_error,'')<>'' GROUP BY 1 ORDER BY 2 DESC LIMIT 5")
    for r in err:
        fila("🔴", f"error en cola ({r['n']}): {str(r['ultimo_error'])[:140]}")
    salida["radar"] = {"busquedas": tot, "ultima_busqueda": ult, "articulos": {r["resultado"]: r["n"] for r in a},
                       "cola": cola}


# ── 4 · noticias ───────────────────────────────────────────────────────────
def seccion_eventos(conn, horas: int) -> list[dict]:
    titulo(f"4 · ¿ENCUENTRA NOTICIAS? (eventos creados en las últimas {horas} h)")
    desde = (AHORA - timedelta(hours=horas)).isoformat()
    ev = q(conn, "SELECT e.*, j.nombre FROM news_evento e LEFT JOIN news_jugador j ON j.id=e.jugador_id WHERE e.creado_en>=?", (desde,))
    ext = [e for e in ev if es_externo(e)]
    fila("🟢" if ext else "🟡", f"eventos: {len(ev)} · externos (noticia de un medio): {len(ext)} · calculados por nosotros: {len(ev) - len(ext)}")
    fila("•", f"externos por categoría: {dict(Counter(e['categoria'] for e in ext).most_common())}")
    fila("•", f"externos por nivel: {dict(Counter(e['nivel'] for e in ext))} · naturaleza: {dict(Counter(e['naturaleza'] for e in ext))}")
    fila("•", f"calculados por categoría: {dict(Counter(e['categoria'] for e in ev if not es_externo(e)).most_common())}")
    salida["eventos"] = {"total": len(ev), "externos": len(ext),
                         "externos_categoria": dict(Counter(e["categoria"] for e in ext))}
    return ext


# ── 5 · 📰 reglas de noticia importante ────────────────────────────────────
def motivo_noticia(e: dict, cfg: dict) -> str:
    cat, nivel, nat = e.get("categoria"), str(e.get("nivel") or "C"), e.get("naturaleza")
    if not (cat in NOTICIA_FUERTE or (cat in NOTICIA_OFICIAL and nivel == "A")):
        return f"CATEGORIA_NO_RELEVANTE:{cat}"
    if RANGO.get(nivel, 1) < 2:
        return "NIVEL_C"
    if nat not in ("HECHO", "DECLARACION"):
        return f"NATURALEZA:{nat}"
    if float(e.get("confianza_identidad") or 0) < float(cfg.get("NEWS_IDENTIDAD_MIN", 0.8)):
        return "IDENTIDAD_DUDOSA"
    fe = dt(e.get("fecha_evento"))
    if fe is None or fe < AHORA - timedelta(days=int(cfg.get("NEWS_NOTICIA_MAX_DIAS", 7))):
        return "HECHO_VIEJO" if fe else "SIN_FECHA_EVENTO"
    return "PASA_REGLAS"


def seccion_noticias(conn, ext: list[dict], cfg: dict) -> None:
    titulo("5 · 📰 ¿POR QUÉ CADA NOTICIA SALIÓ O NO A DISCORD?")
    alertas_noticia = {r["jugador_id"]: r for r in q(conn, "SELECT * FROM news_alerta WHERE tipo='NOTICIA'")}
    c = Counter()
    ejemplos: dict[str, list] = {}
    for e in ext:
        m = motivo_noticia(e, cfg)
        if m == "PASA_REGLAS":
            m = "ALERTA_CREADA" if e["jugador_id"] in alertas_noticia else "PASA_REGLAS_PERO_SIN_ALERTA (repetida, tope diario o error)"
        c[m] += 1
        ejemplos.setdefault(m, [])
        if len(ejemplos[m]) < 3:
            ejemplos[m].append(f"{e.get('nombre')} · {e.get('categoria')} {e.get('nivel')} {e.get('naturaleza')} · "
                               f"identidad {e.get('confianza_identidad')} · hecho {str(e.get('fecha_evento'))[:10]} · {e.get('fuente')}")
    if not ext:
        fila("🟡", "no hubo noticias externas en la ventana: no puede salir ninguna 📰")
    for m, n in c.most_common():
        fila("🟢" if m == "ALERTA_CREADA" else ("🟡" if m.startswith("PASA") else "•"), f"{n:>4} · {m}")
        for x in ejemplos[m]:
            fila(" ", f"   ej.: {x}")
    salida["noticias_motivos"] = dict(c)


# ── 6 · 🔎/🔥 reglas de partido ────────────────────────────────────────────
def fresco(conn, jid: int, horas: int) -> tuple[bool, str]:
    r = q(conn, "SELECT ultima_busqueda_en FROM news_jugador_cola WHERE jugador_id=?", (jid,))
    t = dt(r[0]["ultima_busqueda_en"]) if r and r[0]["ultima_busqueda_en"] else None
    a = q(conn, "SELECT MAX(creado_en) m FROM news_articulo WHERE jugador_id=?", (jid,))
    t2 = dt(a[0]["m"]) if a and a[0]["m"] else None
    ult = max([x for x in (t, t2) if x], default=None)
    return bool(ult and ult >= AHORA - timedelta(hours=horas)), (hace(ult.isoformat()) if ult else "nunca")


def activos(conn, jid: int) -> list[dict]:
    out = []
    for e in q(conn, "SELECT * FROM news_evento WHERE jugador_id=? AND estado IN ('VIGENTE','EN_SEGUIMIENTO')", (jid,)):
        vh = dt(e.get("vigente_hasta"))
        if vh and vh < AHORA:
            continue
        out.append(e)
    return out


def seccion_partidos_alerta(conn, futuros: list[dict], cfg: dict) -> None:
    titulo("6 · 🔎/🔥 ¿POR QUÉ CADA PARTIDO SALIÓ O NO A DISCORD? (partidos que aún no empezaron)")
    horas = int(cfg.get("NEWS_RIVAL_HORAS", 48))
    evals = {r["partido_id"]: r for r in q(conn, "SELECT * FROM news_evaluacion")}
    alertas_p = {r["partido_id"]: r for r in q(conn, "SELECT * FROM news_alerta WHERE tipo IN ('INTERESANTE','FUEGO','FUEGO_EXPERIMENTAL')")}
    nombres = {r["id"]: r["nombre"] for r in q(conn, "SELECT id, nombre FROM news_jugador")}
    c, ej = Counter(), {}
    tipos = Counter()
    for p in futuros:
        e1, e2 = activos(conn, p["jugador1_id"]), activos(conn, p["jugador2_id"])
        ev = evals.get(p["id"])
        if ev:
            tipos[ev["tipo_alerta"]] += 1
        if not e1 and not e2:
            m = "1_NINGUNO_TIENE_EVENTOS"
        else:
            fuertes = [e for e in e1 + e2 if es_externo(e) and e.get("categoria") in FUERTES and RANGO.get(str(e.get("nivel") or "C"), 1) >= 2]
            if not ev:
                m = "2_TIENE_EVENTOS_PERO_SIN_EVALUACION (¿error en el descubridor?)"
            elif not fuertes:
                solo_int = all(not es_externo(e) for e in e1 + e2)
                m = "3_SOLO_EVENTOS_CALCULADOS (carga, viaje…): nunca 🔎" if solo_int else "3_NOTICIA_EXTERNA_DEBIL (categoría no fuerte o nivel C)"
            elif ev["tipo_alerta"] == "NADA":
                m = f"4_DESCUBRIDOR_DICE_NADA:{ev.get('motivo')}"
            else:
                f1, h1 = fresco(conn, p["jugador1_id"], horas)
                f2, h2 = fresco(conn, p["jugador2_id"], horas)
                if p["id"] in alertas_p:
                    m = f"7_ALERTA_CREADA:{alertas_p[p['id']]['tipo']}"
                elif not (f1 and f2):
                    falta = [f"{nombres.get(p['jugador1_id'])} ({h1})" if not f1 else None,
                             f"{nombres.get(p['jugador2_id'])} ({h2})" if not f2 else None]
                    m = f"5_FALTA_INVESTIGAR_A_UNO (búsqueda > {horas} h)"
                    ev = dict(ev, _falta=", ".join(x for x in falta if x))
                else:
                    m = f"6_PASA_REGLAS_PERO_SIN_ALERTA ({ev['tipo_alerta']}:{ev.get('motivo')}: repetida, tope o justificación)"
        c[m] += 1
        ej.setdefault(m, [])
        if len(ej[m]) < 3 and not m.startswith("1_"):
            extra = f" · falta: {ev.get('_falta')}" if ev and ev.get("_falta") else ""
            ej[m].append(f"{nombres.get(p['jugador1_id'])} vs {nombres.get(p['jugador2_id'])} · {p.get('torneo')} · "
                         f"{str(p.get('fecha_estimada'))[:16]} · cuotas {p.get('cuota1')}/{p.get('cuota2')}{extra}")
    fila("•", f"evaluaciones de estos partidos por tipo: {dict(tipos)}")
    for m, n in sorted(c.items()):
        fila("🟢" if m.startswith("7_") else "•", f"{n:>5} · {m}")
        for x in ej.get(m, []):
            fila(" ", f"    ej.: {x}")
    salida["partidos_motivos"] = dict(c)
    salida["evaluaciones_tipo"] = dict(tipos)


# ── 7 · entrega ────────────────────────────────────────────────────────────
def seccion_entrega(conn, cfg: dict) -> None:
    titulo("7 · ¿SE ENTREGÓ? FT NEWS → FT Intelligence → FT Discord")
    fila("🟢" if int(cfg.get("NEWS_DISCORD_ACTIVO", 0)) else "🔴",
         f"NEWS_DISCORD_ACTIVO={cfg.get('NEWS_DISCORD_ACTIVO')} (con 0, /news/senales devuelve vacío)")
    estados = {0: "pendiente", 1: "dicha", 2: "omitida"}
    por = q(conn, "SELECT tipo, dicho_discord, COUNT(*) n, MAX(creado_en) ultima FROM news_alerta GROUP BY 1,2 ORDER BY 1,2")
    if not por:
        fila("🔴", "news_alerta está VACÍA: FT NEWS nunca seleccionó una alerta (el problema está antes de la entrega)")
    for r in por:
        fila("•", f"{r['tipo']:<20} {estados.get(r['dicho_discord'], r['dicho_discord']):<10} {r['n']:>4} · última {hace(r['ultima'])}")
    mot = q(conn, "SELECT dicho_motivo, COUNT(*) n FROM news_alerta WHERE dicho_discord=2 GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
    for r in mot:
        fila("•", f"omitidas por: {r['dicho_motivo']} ({r['n']})")
    venc = [r for r in mot if r["dicho_motivo"] == "VENCIDA"]
    if venc:
        fila("🔴", f"{venc[0]['n']} alertas VENCIERON sin que FT Intelligence las recogiera (> {cfg.get('NEWS_SENAL_MAX_HORAS')} h pendientes): "
                   "FT Intelligence no está leyendo /news/senales, o lo lee con otro secreto")
    pend = q(conn, "SELECT id, tipo, creado_en FROM news_alerta WHERE dicho_discord=0 ORDER BY id")
    if pend:
        fila("🟡", f"{len(pend)} pendientes ahora; la más vieja {hace(pend[0]['creado_en'])}")
    ult = q(conn, "SELECT a.id, a.tipo, a.dicho_discord, a.dicho_en, a.dicho_motivo, a.creado_en, j.nombre "
                  "FROM news_alerta a LEFT JOIN news_jugador j ON j.id=a.jugador_id ORDER BY a.id DESC LIMIT 8")
    if ult:
        fila("•", "últimas alertas:")
        for r in ult:
            fila(" ", f"#{r['id']} {r['tipo']:<18} {r['nombre']} · creada {str(r['creado_en'])[:16]} · "
                      f"{estados.get(r['dicho_discord'])} {str(r['dicho_en'] or '')[:16]} {r['dicho_motivo'] or ''}")
    salida["entrega"] = {"por_tipo_estado": por, "omitidas_motivo": mot, "pendientes": len(pend)}


# ── 8 · config y gasto ─────────────────────────────────────────────────────
def seccion_config(conn, cfg: dict) -> None:
    titulo("8 · CONFIGURACIÓN EFECTIVA Y GASTO")
    for r in q(conn, "SELECT clave, valor, actualizado_en, actualizado_por FROM news_config ORDER BY clave"):
        fila("•", f"{r['clave']} = {r['valor']}  (cambiado {str(r['actualizado_en'])[:16]} por {r['actualizado_por']})")
    est = {r["clave"]: r["valor"] for r in q(conn, "SELECT clave, valor FROM news_estado WHERE clave LIKE 'calibracion_%'")}
    if int(cfg.get("NEWS_BANDAS_CALIBRADAS", 0)) and est.get("calibracion_veredicto") != "CALIBRADAS_OK":
        fila("🔴", f"NEWS_BANDAS_CALIBRADAS=1 pero el veredicto es {est.get('calibracion_veredicto')}: "
                   "las 🔥 saldrían como VALIDADAS sin evidencia. Desmarcar o activar NEWS_BANDAS_AUTO=1")
    for r in q(conn, "SELECT dia, proveedor, busquedas, articulos, usd_estimado FROM news_costos_dia ORDER BY dia DESC, proveedor LIMIT 12"):
        fila("•", f"{r['dia']} {r['proveedor']:<8} búsquedas {r['busquedas']:>4} · artículos {r['articulos']:>4} · US$ {r['usd_estimado']:.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--db", default=os.getenv("FT_NEWS_DB_PATH", "/data/ft_news.db"))
    ap.add_argument("--horas", type=int, default=72, help="ventana para búsquedas y eventos (default 72)")
    ap.add_argument("--json", help="además, guardar el resumen en este archivo")
    a = ap.parse_args()
    if not os.path.exists(a.db):
        print(f"No existe la base {a.db}. Usar --db o FT_NEWS_DB_PATH.")
        return 2
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    print(f"FT NEWS · diagnóstico de alertas · {AHORA.isoformat()[:16]} UTC · base {a.db} (solo lectura)")
    cfg = config_efectiva(conn)
    seccion_resumen(conn, cfg, a.horas)
    seccion_worker(conn)
    futuros = seccion_partidos(conn, cfg)
    seccion_radar(conn, a.horas)
    ext = seccion_eventos(conn, max(a.horas, 24 * int(cfg.get("NEWS_NOTICIA_MAX_DIAS", 7))))
    seccion_noticias(conn, ext, cfg)
    seccion_partidos_alerta(conn, futuros, cfg)
    seccion_entrega(conn, cfg)
    seccion_config(conn, cfg)
    seccion_problemas(conn, cfg, a.horas)
    print("\nFIN. Copia TODO lo que imprimió este comando y pégaselo a Daniel (no contiene claves).")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=1, default=str)
        print(f"\nresumen JSON: {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
