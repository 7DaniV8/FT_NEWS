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
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import costos, fuentes, memoria
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


def pendientes(conn, ahora: datetime, limite: int) -> list[dict]:
    filas = conn.execute(
        "SELECT c.*, j.nombre, j.pais, j.genero, j.circuito AS jcircuito FROM news_jugador_cola c "
        "JOIN news_jugador j ON j.id = c.jugador_id WHERE c.proxima_busqueda_en IS NULL OR c.proxima_busqueda_en <= ? "
        "ORDER BY c.prioridad, CASE c.situacion WHEN 'PARTIDO_24H' THEN 0 WHEN 'PARTIDO_72H' THEN 1 ELSE 2 END, "
        "c.ultima_busqueda_en LIMIT ?", (ahora.isoformat(), limite)).fetchall()
    return [dict(f) for f in filas]


def _articulo_nuevo(conn, art: dict) -> Optional[int]:
    """Inserta si la URL no existe. None = ya visto (no se paga IA)."""
    if conn.execute("SELECT 1 FROM news_articulo WHERE url=?", (art["url"],)).fetchone():
        return None

    def _w():
        cur = conn.execute("INSERT INTO news_articulo (url, dominio, titulo, fecha_publicacion, idioma, fragmento, creado_en) "
                           "VALUES (?,?,?,?,?,?,?)", (art["url"], art.get("dominio"), art.get("titulo"),
                                                      art.get("fecha_publicacion"), art.get("idioma"),
                                                      (art.get("contenido") or "")[:2000], ahora_iso()))
        conn.commit()
        return cur.lastrowid
    return ejecutar_con_reintento(_w, conn=conn)


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
    res = gemini.clasificar(jugador, art)
    costos.anotar(conn, "gemini", tokens_entrada=res["tokens_entrada"], tokens_salida=res["tokens_salida"],
                  usd=res["usd"], articulos=1)
    if not res["ok"]:
        return {"resultado": "FUERA_DE_ESQUEMA", "error": res["error"]}
    d = res["datos"]
    lectura2 = None
    if claude is not None and d.get("sobre_jugador") and tx.es_fuerte(d.get("categoria", "OTRA")):
        try:
            r2 = claude.clasificar(jugador, art)
            costos.anotar(conn, "claude", tokens_entrada=r2["tokens_entrada"], tokens_salida=r2["tokens_salida"], usd=r2["usd"])
            if r2["ok"]:
                lectura2 = r2["datos"]
        except ErrorProveedor as e:
            lectura2 = {"error": str(e)}
    conf = d["confianza_identidad"]
    if not d.get("sobre_jugador") or conf < IDENTIDAD_REVISION_MIN:
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
        return {"resultado": "SIN_FECHA"}
    if fecha_evento > ahora + timedelta(days=1):
        fecha_evento = _dt(art.get("fecha_publicacion")) or ahora
    ev = memoria.nuevo_evento(
        jugador["jugador_id"], d["categoria"], d["direccion"], d["naturaleza"], nivel, fecha_evento.isoformat(),
        articulo_id=articulo_id, fecha_publicacion=art.get("fecha_publicacion"), fuente=art.get("dominio"),
        enlace=art["url"], fragmento_original=(d.get("fragmento_original") or "")[:300],
        resumen_es=(d.get("resumen_es") or "")[:280], relevancia_deportiva=(d.get("relevancia_deportiva") or "")[:160],
        confianza_identidad=conf, lectura1_json=json.dumps(d, ensure_ascii=False),
        lectura2_json=json.dumps(lectura2, ensure_ascii=False) if lectura2 else None)
    if conf < float(cfg.get("NEWS_IDENTIDAD_MIN", 0.8)):
        ev["estado"] = "DESCARTADO"                 # queda en historial, no cuenta
        eid = memoria.guardar_evento_db(conn, ev)
        _revision(conn, "IDENTIDAD_DUDOSA", eid, jugador["jugador_id"],
                  {"confianza": conf, "titulo": art.get("titulo"), "url": art["url"]})
        return {"resultado": "IDENTIDAD_DUDOSA", "evento_id": eid}
    if _dt(ev["vigente_hasta"]) < ahora:
        ev["estado"] = "VENCIDO"
    eid = memoria.guardar_evento_db(conn, ev)
    if d["categoria"] == "OTRA":
        _revision(conn, "OTRA", eid, jugador["jugador_id"], {"titulo": art.get("titulo"), "url": art["url"],
                                                             "resumen": d.get("resumen_es")})
    return {"resultado": "EVENTO", "evento_id": eid, "estado": ev["estado"], "categoria": d["categoria"]}


def correr(conn, cfg: dict, tavily, gemini, ahora: Optional[datetime] = None, limite_jugadores: int = 40,
           claude=None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    res = {"jugadores": 0, "busquedas": 0, "articulos_nuevos": 0, "eventos": 0, "revision": 0, "descartados": 0,
           "motivo": None}
    dominios = _dominios_autorizados(conn, cfg)
    if not dominios:
        res["motivo"] = "SIN_FUENTES_AUTORIZADAS"
        return res
    idiomas = [i.strip() for i in str(cfg.get("NEWS_IDIOMAS", "en,es")).split(",") if i.strip()]
    for j in pendientes(conn, ahora, limite_jugadores):
        gasto = costos.puede_gastar(conn, cfg)
        if not gasto["ok"]:
            res["motivo"] = gasto["motivo"]
            break
        res["jugadores"] += 1
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
                    aid = _articulo_nuevo(conn, art)
                    if aid is None:
                        continue
                    res["articulos_nuevos"] += 1
                    out = procesar_articulo(conn, cfg, gemini, jugador, art, aid, ahora, claude=claude)
                    if out["resultado"] == "EVENTO":
                        res["eventos"] += 1
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
        _reprogramar(conn, j, ahora, horas=_cadencia_h(j["situacion"]), error=None)
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


def _anotar_busqueda(conn, consulta, idioma, jugador_id, n, creditos, usd) -> None:
    def _w():
        conn.execute("INSERT INTO news_busqueda (proveedor, consulta, idioma, jugador_id, resultados, creditos, usd_estimado, "
                     "cache_hasta, creado_en) VALUES ('tavily',?,?,?,?,?,?,?,?)",
                     (consulta, idioma, jugador_id, n, creditos, usd,
                      (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(), ahora_iso()))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)
