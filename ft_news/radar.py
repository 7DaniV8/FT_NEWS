"""
ft_news/radar.py — Motor 1, radar DIRECTO (Fase 1): jugador → noticias.

Por cada jugador de la cola con proxima_busqueda_en vencida (ordenados por
prioridad y por cercanía del partido), mientras haya presupuesto:
  1. consulta por idioma (inglés, español y el local del país si está
     activo) contra la lista blanca AUTORIZADA (fuentes.permitida) — si no
     hay ninguna autorizada, el radar no busca y lo deja escrito;
  2. dedupe por URL (news_articulo) ANTES de pagar IA;
  3. cada artículo nuevo se clasifica con Gemini para ESE jugador;
  4. identidad: confianza ≥ NEWS_IDENTIDAD_MIN → evento; entre 0,4 y el
     mínimo → cola de revisión IDENTIDAD_DUDOSA; menos → se descarta;
  5. fecha: sin fecha_evento ni fecha_publicacion → se descarta (R1); si
     la fecha es más vieja que la vigencia de la categoría → nace VENCIDO
     (se guarda como historial, no como vigente);
  6. nivel = taxonomia.nivel_evidencia con la fuente (oficial / fiable /
     nivel máximo de la fuente);
  7. OTRA → además, cola de revisión;
  8. costos anotados por proveedor; cola actualizada (próxima búsqueda).

v5 (09/10/2026, Rubén): la cola se ordena por un score (situación del
partido, gravedad de lo vigente, antigüedad de la última revisión) con un
CUPO para challenger/ITF/UTR (NEWS_RADAR_CUPO_MENORES_PCT) para que no queden
"siempre al final"; cada artículo deja escrito su resultado y motivo
(news_articulo.resultado); un evento externo fuerte dispara 📰 NOTICIA
IMPORTANTE (alertas.noticia_importante), pone al jugador en EVENTO_VIGENTE
(se lo sigue aunque no tenga partido) y adelanta al rival si tiene partido;
y hay un radar TEMÁTICO (correr_tematico) que busca por tema, no por
jugador, y cruza los artículos contra todo el padrón.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import alertas, costos, fuentes, memoria
from ft_news import jugadores as jg
from ft_news import taxonomia as tx
from ft_news.db import ahora_iso, ejecutar_con_reintento
from ft_news.proveedores.tavily import ErrorProveedor

CONSULTA = {
    "en": '"{nombre}" tennis',
    "es": '"{nombre}" tenis',
    "it": '"{nombre}" tennis',
    "fr": '"{nombre}" tennis',
    "pt": '"{nombre}" tênis',
}
IDENTIDAD_REVISION_MIN = 0.4
log = logging.getLogger("ft_news")


def _dominios_autorizados(conn, cfg: dict) -> list[str]:
    out = []
    for f in fuentes.listar(conn):
        if f["tipo"] in ("AGREGADOR", "PROPIA"):
            continue
        if fuentes.permitida(conn, f["dominio"], cfg):
            out.append(f["dominio"].split("/")[0])
    return sorted(set(out))


def _fuente_de(conn, dominio: str) -> Optional[dict]:
    r = conn.execute("SELECT * FROM news_fuente WHERE dominio=? OR dominio LIKE ?", (dominio, dominio + "/%")).fetchone()
    return dict(r) if r else None


def _cap_nivel(nivel: str, maximo: str) -> str:
    orden = {"A": 3, "B": 2, "C": 1}
    return nivel if orden[nivel] <= orden.get(maximo, 2) else maximo


def _dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s)[:19].replace(" ", "T"))
    except ValueError:
        try:
            d = datetime.strptime(str(s)[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


CIRCUITOS_MENORES = ("challenger", "wta125", "itf", "utr")
_PESO_SITUACION = {"PARTIDO_24H": 100, "PARTIDO_72H": 60, "EVENTO_VIGENTE": 40, "MANUAL": 40, "SIN_PARTIDO": 0}


def _score(f: dict, ahora: datetime) -> float:
    """Más alto = antes. Situación (proximidad del partido) > prioridad manual
    (0 = a demanda) > gravedad de lo vigente > antigüedad de la última revisión."""
    s = _PESO_SITUACION.get(f.get("situacion"), 0)
    if f.get("prioridad") is not None and int(f["prioridad"]) == 0:
        s += 80                                       # a demanda (rival de un partido interesante)
    s += 10 * int(f.get("fuertes_vigentes") or 0)
    u = _dt(f.get("ultima_busqueda_en"))
    s += 30 if u is None else min(30.0, (ahora - u).total_seconds() / 3600 / 24 * 5)   # nunca buscado = 30
    return s


def pendientes(conn, ahora: datetime, limite: int, cupo_menores_pct: int = 40) -> list[dict]:
    """Cola vencida ordenada por score, con cupo para circuitos menores:
    de cada `limite`, al menos `cupo_menores_pct` % va a challenger/ITF/UTR
    si hay candidatos (Rubén §9: "no quiero que ITF y UTR queden siempre al
    final hasta agotar el presupuesto")."""
    filas = [dict(f) for f in conn.execute(
        "SELECT c.*, j.nombre, j.pais, j.genero, j.circuito AS jcircuito, "
        "(SELECT COUNT(*) FROM news_evento e WHERE e.jugador_id=c.jugador_id AND e.estado IN ('VIGENTE','EN_SEGUIMIENTO') "
        " AND e.articulo_id IS NOT NULL AND e.categoria IN ('LESION_MOLESTIA','ENFERMEDAD','RETIRO_ABANDONO','REGRESO')) "
        "AS fuertes_vigentes FROM news_jugador_cola c JOIN news_jugador j ON j.id = c.jugador_id "
        "WHERE c.proxima_busqueda_en IS NULL OR c.proxima_busqueda_en <= ?", (ahora.isoformat(),)).fetchall()]
    for f in filas:
        f["score"] = _score(f, ahora)
        f["menor"] = (f.get("circuito") or f.get("jcircuito") or "") in CIRCUITOS_MENORES
    filas.sort(key=lambda f: (-f["score"], f.get("ultima_busqueda_en") or ""))
    if limite <= 0 or len(filas) <= limite:
        return filas
    menores = [f for f in filas if f["menor"]]
    mayores = [f for f in filas if not f["menor"]]
    n_men = min(len(menores), max(0, round(limite * cupo_menores_pct / 100)))
    out = menores[:n_men] + mayores[:limite - n_men]
    if len(out) < limite:                             # sobró cupo de un lado
        resto = [f for f in filas if f not in out]
        out += resto[:limite - len(out)]
    out.sort(key=lambda f: -f["score"])
    return out


MAX_INTENTOS = 4
REINTENTABLES = ("PENDIENTE", "ERROR", "FUERA_DE_ESQUEMA")


def _articulo_nuevo(conn, art: dict, origen: str = "radar", jugador_id: Optional[int] = None,
                    ahora: Optional[datetime] = None) -> Optional[int]:
    """Inserta si la URL no existe. None = ya visto (no se paga IA). Nace
    PENDIENTE con el jugador para el que se buscó: si la IA falla antes de
    clasificarlo, reintentar_pendientes lo retoma (v5.1, Rubén §2)."""
    if conn.execute("SELECT 1 FROM news_articulo WHERE url=?", (art["url"],)).fetchone():
        return None

    def _w():
        cur = conn.execute("INSERT INTO news_articulo (url, dominio, titulo, fecha_publicacion, idioma, fragmento, origen, "
                           "resultado, jugador_id, intentos, creado_en) VALUES (?,?,?,?,?,?,?,'PENDIENTE',?,0,?)",
                           (art["url"], art.get("dominio"), art.get("titulo"), art.get("fecha_publicacion"),
                            art.get("idioma"), (art.get("contenido") or "")[:4000], origen, jugador_id,
                            ahora.isoformat() if ahora else ahora_iso()))
        conn.commit()
        return cur.lastrowid
    return ejecutar_con_reintento(_w, conn=conn)


def _fallo_clasificacion(conn, articulo_id: int, ahora: datetime, error: str, pausa_seg: int = 3600,
                         resultado: str = "PENDIENTE", jugador_id: Optional[int] = None) -> None:
    """La IA (o el proceso) falló con este artículo: intento += 1 y hora de
    reintento; al MAX_INTENTOS pasa a AGOTADO y a la cola de revisión."""
    r = conn.execute("SELECT intentos, jugador_id FROM news_articulo WHERE id=?", (articulo_id,)).fetchone()
    intentos = int((r["intentos"] if r else 0) or 0) + 1
    jid = jugador_id or (r["jugador_id"] if r else None)

    def _w():
        if intentos >= MAX_INTENTOS:
            conn.execute("UPDATE news_articulo SET resultado='AGOTADO', motivo=?, intentos=?, reintentar_en=NULL, "
                         "jugador_id=COALESCE(jugador_id, ?) WHERE id=?", (f"{intentos} intentos: {error}"[:300], intentos, jid, articulo_id))
            if jid:
                conn.execute("INSERT INTO news_revision (tipo, evento_id, jugador_id, detalle, creado_en) VALUES (?,?,?,?,?)",
                             ("CLASIFICACION_FALLIDA", None, jid, json.dumps({"articulo_id": articulo_id, "error": error[:200]},
                                                                             ensure_ascii=False), ahora_iso()))
        else:
            espera = max(300, pausa_seg) * intentos
            conn.execute("UPDATE news_articulo SET resultado=?, motivo=?, intentos=?, reintentar_en=?, "
                         "jugador_id=COALESCE(jugador_id, ?) WHERE id=?",
                         (resultado, error[:300], intentos, (ahora + timedelta(seconds=espera)).isoformat(), jid, articulo_id))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def reintentar_pendientes(conn, cfg: dict, gemini, ahora: Optional[datetime] = None, claude=None, limite: int = 30) -> dict:
    """v5.1 (Rubén §2: "si Gemini, Claude o el proceso falla, reintentos
    controlados para no perder noticias"): retoma los artículos PENDIENTE /
    ERROR / FUERA_DE_ESQUEMA cuya hora de reintento venció."""
    ahora = ahora or datetime.now(timezone.utc)
    res = {"reintentados": 0, "eventos": 0, "pendientes": 0, "agotados": 0}
    filas = [dict(r) for r in conn.execute(
        "SELECT * FROM news_articulo WHERE resultado IN ('PENDIENTE','ERROR','FUERA_DE_ESQUEMA') AND intentos < ? "
        "AND intentos > 0 AND (reintentar_en IS NULL OR reintentar_en <= ?) ORDER BY id LIMIT ?",
        (MAX_INTENTOS, ahora.isoformat(), limite)).fetchall()]
    # Los PENDIENTE con 0 intentos son los que la IA ni llegó a ver (el radar se cortó
    # por ErrorProveedor antes de marcarlos): también cuentan, sin esperar.
    filas += [dict(r) for r in conn.execute(
        "SELECT * FROM news_articulo WHERE resultado='PENDIENTE' AND intentos=0 AND creado_en <= ? ORDER BY id LIMIT ?",
        ((ahora - timedelta(minutes=10)).isoformat(), limite)).fetchall()]
    for art in filas:
        if gemini is None or not costos.puede_gastar(conn, cfg)["ok"]:
            break
        jugadores = []
        if art.get("jugador_id"):
            j = conn.execute("SELECT * FROM news_jugador WHERE id=?", (art["jugador_id"],)).fetchone()
            if j:
                jugadores = [dict(j)]
        if not jugadores:
            jugadores = jg.buscar_en_texto(conn, f"{art.get('titulo') or ''} {art.get('fragmento') or ''}")[:3]
        if not jugadores:
            _marcar_articulo(conn, art["id"], "SIN_JUGADOR_DEL_PADRON", "reintento: no nombra a nadie del padrón")
            continue
        a = {"url": art["url"], "dominio": art.get("dominio"), "titulo": art.get("titulo"), "contenido": art.get("fragmento"),
             "fecha_publicacion": art.get("fecha_publicacion"), "idioma": art.get("idioma")}
        res["reintentados"] += 1
        for j in jugadores:
            jugador = {"jugador_id": j["id"], "nombre": j["nombre"], "pais": j.get("pais"), "genero": j.get("genero"),
                       "circuito": j.get("circuito")}
            try:
                out = procesar_articulo(conn, cfg, gemini, jugador, a, art["id"], ahora, claude=claude)
            except ErrorProveedor as e:
                _fallo_clasificacion(conn, art["id"], ahora, str(e), e.pausa_seg, jugador_id=j["id"])
                if e.fatal:
                    res["motivo"] = f"PROVEEDOR: {e}"
                    return _cerrar(conn, res)
                break
            except Exception as e:
                _fallo_clasificacion(conn, art["id"], ahora, str(e), 3600, "ERROR", jugador_id=j["id"])
                break
            if out["resultado"] == "FUERA_DE_ESQUEMA":
                _fallo_clasificacion(conn, art["id"], ahora, str(out.get("error") or "fuera de esquema"), 1800,
                                     "FUERA_DE_ESQUEMA", jugador_id=j["id"])
            elif out["resultado"] == "EVENTO":
                res["eventos"] += 1
                conn.execute("UPDATE news_articulo SET intentos=intentos+1 WHERE id=?", (art["id"],))
                conn.commit()
            else:
                conn.execute("UPDATE news_articulo SET intentos=intentos+1 WHERE id=?", (art["id"],))
                conn.commit()
    return _cerrar(conn, res)


def _cerrar(conn, res: dict) -> dict:
    res["pendientes"] = conn.execute("SELECT COUNT(*) FROM news_articulo WHERE resultado IN ('PENDIENTE','ERROR','FUERA_DE_ESQUEMA') "
                                     "AND intentos < ?", (MAX_INTENTOS,)).fetchone()[0]
    res["agotados"] = conn.execute("SELECT COUNT(*) FROM news_articulo WHERE resultado='AGOTADO'").fetchone()[0]
    return res


def _articulo_id(conn, url: str) -> Optional[int]:
    r = conn.execute("SELECT id FROM news_articulo WHERE url=?", (url,)).fetchone()
    return r["id"] if r else None


def _marcar_articulo(conn, articulo_id: int, resultado: str, motivo: str = "", jugador_id: Optional[int] = None) -> None:
    """v5: cada artículo deja escrito qué pasó con él (diagnóstico de Rubén §3:
    "artículos descartados y motivo")."""
    def _w():
        # un artículo que ya dio EVENTO para un jugador no se "degrada" por otro jugador
        conn.execute("UPDATE news_articulo SET resultado=CASE WHEN resultado='EVENTO' AND ?<>'EVENTO' THEN resultado ELSE ? END, "
                     "motivo=CASE WHEN resultado='EVENTO' AND ?<>'EVENTO' THEN motivo ELSE ? END, "
                     "jugador_id=CASE WHEN resultado='EVENTO' AND ?<>'EVENTO' THEN jugador_id ELSE COALESCE(?, jugador_id) END "
                     "WHERE id=?", (resultado, resultado, resultado, (motivo or "")[:300], resultado, jugador_id, articulo_id))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def _revision(conn, tipo: str, evento_id: Optional[int], jugador_id: int, detalle: dict) -> None:
    def _w():
        conn.execute("INSERT INTO news_revision (tipo, evento_id, jugador_id, detalle, creado_en) VALUES (?,?,?,?,?)",
                     (tipo, evento_id, jugador_id, json.dumps(detalle, ensure_ascii=False)[:2000], ahora_iso()))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def procesar_articulo(conn, cfg: dict, gemini, jugador: dict, art: dict, articulo_id: int,
                      ahora: datetime, claude=None) -> dict:
    """Clasifica y guarda. Devuelve {'resultado': ..., 'evento_id': ...}.
    Con `claude` (segunda lectura, opcional): lo que es categoría fuerte y
    aspira a 🔥 se lee dos veces; si discrepan, nivel C."""
    res = gemini.clasificar(jugador, art)          # `gemini` = el clasificador principal (Gemini o Claude)
    costos.anotar(conn, getattr(gemini, "nombre", "gemini"), tokens_entrada=res["tokens_entrada"],
                  tokens_salida=res["tokens_salida"], usd=res["usd"], articulos=1)
    if not res["ok"]:
        _fallo_clasificacion(conn, articulo_id, ahora, str(res.get("error") or "fuera de esquema"), 1800,
                             "FUERA_DE_ESQUEMA", jugador_id=jugador["jugador_id"])
        return {"resultado": "FUERA_DE_ESQUEMA", "error": res["error"]}
    d = res["datos"]
    lectura2 = None
    if claude is not None and claude is not gemini and d.get("sobre_jugador") and tx.es_fuerte(d.get("categoria", "OTRA")):
        try:
            r2 = claude.clasificar(jugador, art)
            costos.anotar(conn, getattr(claude, "nombre", "claude"), tokens_entrada=r2["tokens_entrada"],
                          tokens_salida=r2["tokens_salida"], usd=r2["usd"])
            if r2["ok"]:
                lectura2 = r2["datos"]
        except ErrorProveedor as e:
            lectura2 = {"error": str(e)}
    conf = d["confianza_identidad"]
    if not d.get("sobre_jugador") or conf < IDENTIDAD_REVISION_MIN:
        _marcar_articulo(conn, articulo_id, "OTRO_JUGADOR", f"identidad {conf:.2f} para {jugador['nombre']}",
                         jugador["jugador_id"])
        return {"resultado": "OTRO_JUGADOR"}
    f = _fuente_de(conn, art.get("dominio") or "")
    nivel = tx.nivel_evidencia(d["naturaleza"], fuentes_independientes=1,
                               fuente_oficial=bool(f and f["tipo"] == "OFICIAL"), fuente_fiable=bool(f))
    nivel = _cap_nivel(nivel, (f or {}).get("nivel_maximo", "C"))
    if lectura2 and "error" not in lectura2:
        from ft_news.proveedores.claude import discrepa
        if discrepa(d, lectura2):
            nivel = "C"
    fecha_evento = _dt(d.get("fecha_evento")) or _dt(art.get("fecha_publicacion"))
    if fecha_evento is None:
        _marcar_articulo(conn, articulo_id, "SIN_FECHA", "sin fecha del hecho ni de publicación", jugador["jugador_id"])
        return {"resultado": "SIN_FECHA"}
    if fecha_evento > ahora + timedelta(days=1):
        fecha_evento = _dt(art.get("fecha_publicacion")) or ahora
    ev = memoria.nuevo_evento(
        jugador["jugador_id"], d["categoria"], d["direccion"], d["naturaleza"], nivel, fecha_evento.isoformat(),
        articulo_id=articulo_id, fecha_publicacion=art.get("fecha_publicacion"), fuente=art.get("dominio"),
        enlace=art["url"], fragmento_original=(d.get("fragmento_original") or "")[:300],
        resumen_es=(d.get("resumen_es") or "")[:280], relevancia_deportiva=(d.get("relevancia_deportiva") or "")[:160],
        titular=(d.get("titular") or "")[:80] or None,
        confianza_identidad=conf, lectura1_json=json.dumps(d, ensure_ascii=False),
        lectura2_json=json.dumps(lectura2, ensure_ascii=False) if lectura2 else None)
    if conf < float(cfg.get("NEWS_IDENTIDAD_MIN", 0.8)):
        ev["estado"] = "DESCARTADO"                 # queda en historial, no cuenta
        eid = memoria.guardar_evento_db(conn, ev)
        _revision(conn, "IDENTIDAD_DUDOSA", eid, jugador["jugador_id"],
                  {"confianza": conf, "titulo": art.get("titulo"), "url": art["url"]})
        _marcar_articulo(conn, articulo_id, "IDENTIDAD_DUDOSA", f"identidad {conf:.2f}: a revisión", jugador["jugador_id"])
        _guardar_motivo_noticia(conn, eid, jugador["jugador_id"], {"alerta_id": None, "motivo": "IDENTIDAD_DUDOSA"}, ahora)
        return {"resultado": "IDENTIDAD_DUDOSA", "evento_id": eid}
    if _dt(ev["vigente_hasta"]) < ahora:
        ev["estado"] = "VENCIDO"
    eid = memoria.guardar_evento_db(conn, ev)
    if d["categoria"] == "OTRA":
        _revision(conn, "OTRA", eid, jugador["jugador_id"], {"titulo": art.get("titulo"), "url": art["url"],
                                                             "resumen": d.get("resumen_es")})
    _marcar_articulo(conn, articulo_id, "EVENTO", f"{d['categoria']} {nivel} {d['naturaleza']} ({ev['estado']})",
                     jugador["jugador_id"])
    out = {"resultado": "EVENTO", "evento_id": eid, "estado": ev["estado"], "categoria": d["categoria"]}
    if ev["estado"] == "VIGENTE":
        out["alerta"] = _tras_evento_externo(conn, cfg, ev, jugador, ahora)
    else:
        out["alerta"] = {"alerta_id": None, "motivo": f"ESTADO:{ev['estado']}"}
    _guardar_motivo_noticia(conn, eid, jugador["jugador_id"], out["alerta"], ahora)
    return out


def _guardar_motivo_noticia(conn, evento_id, jugador_id, alerta: dict, ahora: datetime) -> None:
    """v7.2: por qué esta noticia externa salió (o no) como 📰, para siempre:
    en el propio evento (noticia_motivo) y en news_descarte si no salió."""
    try:
        from ft_news import descartes
        from ft_news.db import ejecutar_con_reintento
        mot = (alerta or {}).get("motivo")
        if (alerta or {}).get("alerta_id"):
            txt = f"ALERTA #{alerta['alerta_id']} (NOTICIA)"
        else:
            descartes.registrar(conn, "NOTICIA", mot, ahora=ahora, evento_id=evento_id, jugador_id=jugador_id)
            txt = f"NO ENVIADA · {descartes.grupo(mot)} ({mot})"

        def _w():
            conn.execute("UPDATE news_evento SET noticia_motivo=? WHERE id=?", (txt[:300], evento_id))
            conn.commit()
        if evento_id:
            ejecutar_con_reintento(_w, conn=conn)
    except Exception as e:                                        # pragma: no cover — nunca tumba el radar
        log.warning("[FT_NEWS] motivo de la noticia %s: %s", evento_id, e)


def _tras_evento_externo(conn, cfg: dict, ev: dict, jugador: dict, ahora: datetime) -> dict:
    """v5: después de un evento externo vigente
      1. 📰 NOTICIA IMPORTANTE si pasa las reglas de alertas.noticia_importante;
      2. el jugador queda en EVENTO_VIGENTE (se lo sigue aunque no tenga partido);
      3. si tiene partido próximo, el rival pasa al frente de la cola
         (Rubén §5: "investigar también al rival")."""
    res = {"alerta_id": None, "motivo": None}
    try:
        jrow = conn.execute("SELECT * FROM news_jugador WHERE id=?", (jugador["jugador_id"],)).fetchone()
        jd = dict(jrow) if jrow else {"id": jugador["jugador_id"], "nombre": jugador["nombre"]}
        res = alertas.noticia_importante(conn, cfg, ev, jd, ahora)
    except Exception as e:                                        # la alerta nunca tumba el radar
        res = {"alerta_id": None, "motivo": f"error: {e}"[:200]}
    try:
        if tx.es_fuerte(ev.get("categoria", "")):
            cola = conn.execute("SELECT situacion FROM news_jugador_cola WHERE jugador_id=?", (jugador["jugador_id"],)).fetchone()
            if not cola or cola["situacion"] in ("SIN_PARTIDO", "EVENTO_VIGENTE"):
                jg.encolar(conn, jugador["jugador_id"], "EVENTO_VIGENTE", 24, "EVENTO_VIGENTE", 2,
                           jugador.get("circuito"), ahora)
            prox = alertas.proximo_partido(conn, jugador["jugador_id"], ahora)
            if prox and not alertas.investigado(conn, prox["rival_id"], ahora, int(cfg.get("NEWS_RIVAL_HORAS", 48))):
                alertas.adelantar(conn, prox["rival_id"], ahora, "RIVAL_A_DEMANDA")
                res["rival_adelantado"] = prox["rival_id"]
    except Exception as e:                                        # pragma: no cover
        res["cola_error"] = str(e)[:200]
    return res


def correr(conn, cfg: dict, tavily, gemini, ahora: Optional[datetime] = None, limite_jugadores: int = 40,
           claude=None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    res = {"jugadores": 0, "busquedas": 0, "articulos_nuevos": 0, "eventos": 0, "revision": 0, "descartados": 0,
           "alertas": 0, "menores": 0, "motivo": None}
    dominios = _dominios_autorizados(conn, cfg)
    if not dominios:
        res["motivo"] = "SIN_FUENTES_AUTORIZADAS"
        return res
    idiomas = [i.strip() for i in str(cfg.get("NEWS_IDIOMAS", "en,es")).split(",") if i.strip()]
    for j in pendientes(conn, ahora, limite_jugadores, int(cfg.get("NEWS_RADAR_CUPO_MENORES_PCT", 40))):
        gasto = costos.puede_gastar(conn, cfg)
        if not gasto["ok"]:
            res["motivo"] = gasto["motivo"]
            break
        res["jugadores"] += 1
        res["menores"] += int(bool(j.get("menor")))
        jugador = {"jugador_id": j["jugador_id"], "nombre": j["nombre"], "pais": j["pais"], "genero": j["genero"],
                   "circuito": j["jcircuito"] or j["circuito"]}
        error = None
        try:
            for idioma in jg.idiomas_para(j, idiomas):
                consulta = CONSULTA.get(idioma, CONSULTA["en"]).format(nombre=j["nombre"])
                r = tavily.buscar(consulta, dominios, dias=7)
                res["busquedas"] += 1
                costos.anotar(conn, "tavily", busquedas=1, usd=r["usd"])
                _anotar_busqueda(conn, consulta, idioma, j["jugador_id"], len(r["articulos"]), r["creditos"], r["usd"])
                for art in r["articulos"]:
                    art["idioma"] = idioma
                    aid = _articulo_nuevo(conn, art, "radar", j["jugador_id"], ahora)
                    if aid is None:
                        continue
                    res["articulos_nuevos"] += 1
                    try:
                        out = procesar_articulo(conn, cfg, gemini, jugador, art, aid, ahora, claude=claude)
                    except ErrorProveedor as e:
                        # v5.1: el artículo queda PENDIENTE con reintento (no "visto y perdido")
                        _fallo_clasificacion(conn, aid, ahora, str(e), e.pausa_seg, jugador_id=j["jugador_id"])
                        raise
                    except Exception as e:
                        # 09/10/2026: un artículo roto no tumba el radar entero
                        # (antes un HTTPStatusError de Gemini abortaba el paso,
                        # el jugador no se reprogramaba y Tavily se volvía a
                        # pagar cada 15 min por el mismo jugador). v5.1: queda
                        # ERROR con reintento.
                        res.setdefault("errores", []).append(f"{art.get('url')}: {e}"[:300])
                        _fallo_clasificacion(conn, aid, ahora, str(e), 3600, "ERROR", jugador_id=j["jugador_id"])
                        res["descartados"] += 1
                        continue
                    if out["resultado"] == "EVENTO":
                        res["eventos"] += 1
                        if (out.get("alerta") or {}).get("alerta_id"):
                            res["alertas"] += 1
                    elif out["resultado"] in ("IDENTIDAD_DUDOSA",):
                        res["revision"] += 1
                    else:
                        res["descartados"] += 1
        except ErrorProveedor as e:
            error = str(e)
            res["motivo"] = f"PROVEEDOR: {e}"
            _reprogramar(conn, j, ahora, horas=max(1, e.pausa_seg // 3600 or 1), error=error)
            if e.fatal:
                break
            continue
        except Exception as e:
            # Cualquier otra cosa (red, JSON, base): se anota, se reprograma y sigue.
            res.setdefault("errores", []).append(f"{j['nombre']}: {e}"[:300])
            _reprogramar(conn, j, ahora, horas=1, error=str(e)[:300])
            continue
        _reprogramar(conn, j, ahora, horas=_cadencia_h(j["situacion"]), error=None)
    if getattr(gemini, "aviso", None):
        res["gemini"] = {"modelo": gemini.modelo, "aviso": gemini.aviso}
    return res


def _cadencia_h(situacion: str) -> int:
    return {"PARTIDO_24H": 6, "PARTIDO_72H": 12, "EVENTO_VIGENTE": 24, "MANUAL": 24}.get(situacion, 24 * 7)


def _reprogramar(conn, j: dict, ahora: datetime, horas: int, error: Optional[str]) -> None:
    def _w():
        conn.execute("UPDATE news_jugador_cola SET ultima_busqueda_en=?, proxima_busqueda_en=?, ultimo_error=?, "
                     "actualizado_en=? WHERE jugador_id=?",
                     (ahora.isoformat(), (ahora + timedelta(hours=horas)).isoformat(), error, ahora.isoformat(),
                      j["jugador_id"]))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def _anotar_busqueda(conn, consulta, idioma, jugador_id, n, creditos, usd, origen: str = "radar") -> None:
    def _w():
        conn.execute("INSERT INTO news_busqueda (proveedor, consulta, idioma, jugador_id, resultados, creditos, usd_estimado, "
                     "cache_hasta, origen, creado_en) VALUES ('tavily',?,?,?,?,?,?,?,?,?)",
                     (consulta, idioma, jugador_id, n, creditos, usd,
                      (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(), origen, ahora_iso()))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


# ═════════════════════════════════════════════════════════════════════
#  Radar TEMÁTICO (v5): por tema, no por jugador
# ═════════════════════════════════════════════════════════════════════
# Rubén §4: "que investigue jugadores continuamente, incluso cuando no tengan
# partidos programados". Buscar jugador por jugador a todo el padrón es
# impagable; buscar por TEMA (lesión, retiro, enfermedad, regreso) en la
# prensa autorizada y cruzar cada artículo contra TODO el padrón sí: pocas
# búsquedas, y cada artículo se clasifica solo para los jugadores que nombra.

TEMAS = {
    "en": ["tennis injury withdraws", "tennis retires injured match", "tennis illness withdrawal",
           "tennis returns from injury", "challenger tennis withdrawal injury", "itf tennis injury retired"],
    "es": ["tenis lesión baja", "tenis abandona lesionado", "tenis regresa tras lesión", "challenger tenis baja lesión"],
    "it": ["tennis infortunio ritiro", "tennis rientro infortunio"],
    "fr": ["tennis blessure forfait", "tennis retour blessure"],
    "pt": ["tênis lesão desistência"],
}


def correr_tematico(conn, cfg: dict, tavily, gemini, ahora: Optional[datetime] = None, claude=None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    res = {"busquedas": 0, "articulos": 0, "articulos_nuevos": 0, "coincidencias": 0, "eventos": 0, "alertas": 0,
           "descartados": 0, "motivo": None}
    if not int(cfg.get("NEWS_RADAR_TEMATICO_ACTIVO", 1)):
        res["motivo"] = "NEWS_RADAR_TEMATICO_ACTIVO=0"
        return res
    dominios = _dominios_autorizados(conn, cfg)
    if not dominios:
        res["motivo"] = "SIN_FUENTES_AUTORIZADAS"
        return res
    idiomas = [i.strip() for i in str(cfg.get("NEWS_IDIOMAS", "en,es")).split(",") if i.strip()]
    tope = int(cfg.get("NEWS_RADAR_TEMATICO_BUSQUEDAS", 12))
    consultas = []
    for idioma in idiomas:
        consultas += [(idioma, t) for t in TEMAS.get(idioma, [])]
    # rotación: en cada corrida arrancan por un punto distinto para que todas pasen
    if consultas:
        off = (int(ahora.timestamp()) // 3600) % len(consultas)
        consultas = (consultas[off:] + consultas[:off])[:tope]
    for idioma, consulta in consultas:
        gasto = costos.puede_gastar(conn, cfg)
        if not gasto["ok"]:
            res["motivo"] = gasto["motivo"]
            break
        try:
            r = tavily.buscar(consulta, dominios, dias=1)
        except ErrorProveedor as e:
            res["motivo"] = f"PROVEEDOR: {e}"
            break
        except Exception as e:
            res.setdefault("errores", []).append(f"{consulta}: {e}"[:300])
            continue
        res["busquedas"] += 1
        costos.anotar(conn, "tavily", busquedas=1, usd=r["usd"])
        _anotar_busqueda(conn, consulta, idioma, None, len(r["articulos"]), r["creditos"], r["usd"], "tematico")
        res["articulos"] += len(r["articulos"])
        for art in r["articulos"]:
            art["idioma"] = idioma
            aid = _articulo_nuevo(conn, art, "tematico", None, ahora)
            if aid is None:
                continue
            res["articulos_nuevos"] += 1
            texto = f"{art.get('titulo') or ''} {art.get('contenido') or ''}"
            nombrados = jg.buscar_en_texto(conn, texto)
            if not nombrados:
                _marcar_articulo(conn, aid, "SIN_JUGADOR_DEL_PADRON", "no nombra a nadie del padrón")
                res["descartados"] += 1
                continue
            for j in nombrados[:3]:                               # un artículo rara vez es sobre más de 3
                res["coincidencias"] += 1
                if not costos.puede_gastar(conn, cfg)["ok"]:
                    res["motivo"] = "PRESUPUESTO"
                    return res
                jugador = {"jugador_id": j["id"], "nombre": j["nombre"], "pais": j.get("pais"), "genero": j.get("genero"),
                           "circuito": j.get("circuito")}
                try:
                    out = procesar_articulo(conn, cfg, gemini, jugador, art, aid, ahora, claude=claude)
                except ErrorProveedor as e:
                    _fallo_clasificacion(conn, aid, ahora, str(e), e.pausa_seg, jugador_id=j["id"])
                    res["motivo"] = f"PROVEEDOR: {e}"
                    return res
                except Exception as e:
                    res.setdefault("errores", []).append(f"{art.get('url')}: {e}"[:300])
                    _fallo_clasificacion(conn, aid, ahora, str(e), 3600, "ERROR", jugador_id=j["id"])
                    continue
                if out["resultado"] == "EVENTO":
                    res["eventos"] += 1
                    if (out.get("alerta") or {}).get("alerta_id"):
                        res["alertas"] += 1
                else:
                    res["descartados"] += 1
    return res
