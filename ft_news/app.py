"""
ft_news/app.py — API de FT_NEWS (Fase 0).

  GET  /salud                      sin clave (healthcheck de Railway)
  GET  /news/estado                estado del worker, interruptores, contadores
  GET  /news/config                parámetros efectivos
  POST /news/config                {clave, valor, por}  (lo usará Admin → Estrategias)
  GET  /news/fuentes               lista blanca con su estado de autorización
  POST /news/fuentes/autorizar     {dominio, autorizada, estado_tc, nota, por}
  GET  /news/senales               lo que FT Intelligence recogería: vacío con NEWS_DISCORD_ACTIVO=0
  GET  /news/costos                hoy y mes
  GET  /news/jugadores/{id}/memoria   línea de tiempo (lectura contextual)
Todo menos /salud exige X-FT-News-Secret = FT_NEWS_SECRET.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from ft_news import VERSION, alertas, cobertura, config, costos, descartes, evaluador, explicar, fuentes, memoria, tareas
from ft_news import salud as salud_mod
from ft_news.db import config_guardar, estado_set, estado_todo, get_conn

log = logging.getLogger("ft_news")
_worker: Optional[tareas.Worker] = None


@asynccontextmanager
async def _vida(app: FastAPI):
    global _worker
    if os.getenv("FT_NEWS_SIN_WORKER", "0") != "1":
        _worker = tareas.Worker()
        _worker.start()
    yield
    if _worker:
        _worker.parar.set()


app = FastAPI(title="FT NEWS INTELLIGENCE", version=VERSION, lifespan=_vida)


def _auth(x_ft_news_secret: str = Header(default="", alias="X-FT-News-Secret")):
    if not config.NEWS_SECRET or x_ft_news_secret != config.NEWS_SECRET:
        raise HTTPException(status_code=401, detail="Secreto inválido")


def _conn():
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


@app.get("/salud")
def salud():
    return {"ok": True, "version": VERSION, "fase": 1}


@app.get("/news/estado", dependencies=[Depends(_auth)])
def estado(conn=Depends(_conn)):
    cfg = config.leer_config(conn)
    fuentes.sembrar(conn)
    n = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
    return {"version": VERSION, "fase": 1, "activo": bool(cfg["NEWS_ACTIVO"]),
            "bandas_calibradas": bool(cfg["NEWS_BANDAS_CALIBRADAS"]),
            "discord_activo": bool(cfg["NEWS_DISCORD_ACTIVO"]),
            "prueba_desbloqueada": bool(cfg.get("NEWS_PRUEBA_SOLO_ADMIN_VERIFICADA")),     # v7.3
            "fuentes": {"total": n("news_fuente"),
                        "autorizadas": conn.execute("SELECT COUNT(*) FROM news_fuente WHERE autorizada=1").fetchone()[0]},
            "contadores": {t: n(t) for t in ("news_jugador", "news_jugador_cola", "news_evento", "news_partido",
                                             "news_evaluacion", "news_revision", "news_alerta", "news_articulo")},
            "alertas": _alertas_resumen(conn),
            "estado": estado_todo(conn), "costos_hoy": costos.hoy(conn), "costos_mes": costos.mes(conn),
            # v7.2: semáforo FUNCIONANDO / SIN_DATOS / ERROR con sus motivos e indicadores
            "salud": salud_mod.calcular(conn, cfg)}


def _alertas_resumen(conn) -> dict:
    hoy = datetime.now(timezone.utc).date().isoformat()
    out = {"pendientes": {}, "dichas_hoy": {}, "omitidas_hoy": {}}
    for r in conn.execute("SELECT tipo, dicho_discord, COUNT(*) n FROM news_alerta WHERE COALESCE(prueba,0)=0 "
                          "AND (dicho_discord=0 OR creado_en>=?) GROUP BY tipo, dicho_discord", (hoy,)).fetchall():
        k = {0: "pendientes", 1: "dichas_hoy", 2: "omitidas_hoy"}[r["dicho_discord"]]
        out[k][r["tipo"]] = r["n"]
    return out


@app.get("/news/config", dependencies=[Depends(_auth)])
def config_get(conn=Depends(_conn)):
    cfg = config.leer_config(conn)
    return {"parametros": [{"clave": k, "valor": cfg[k], "tipo": t, "descripcion": d, "default": v}
                           for k, v, t, d in config.PARAMETROS]}


class ConfigIn(BaseModel):
    clave: str
    valor: str
    por: str = ""


@app.post("/news/config", dependencies=[Depends(_auth)])
def config_post(body: ConfigIn, conn=Depends(_conn)):
    # v7.2: "bandas calibradas" no se puede encender a mano sin el veredicto que la respalde
    if body.clave == "NEWS_BANDAS_CALIBRADAS" and config._convertir(body.clave, body.valor) == 1:
        cfg = config.leer_config(conn)
        ver = (estado_todo(conn).get("calibracion_veredicto") or {}).get("valor")
        if int(cfg.get("NEWS_BANDAS_EXIGIR_VEREDICTO", 1)) and ver != "CALIBRADAS_OK":
            raise HTTPException(status_code=409, detail=f"No se puede activar «bandas calibradas»: la calibración dice "
                                                        f"{ver or 'sin veredicto'}. Se activa sola cuando el veredicto sea "
                                                        f"CALIBRADAS_OK (o con NEWS_BANDAS_AUTO=1).")
    try:
        config_guardar(conn, body.clave, body.valor, body.por)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "efectivo": config.leer_config(conn)[body.clave]}


@app.get("/news/fuentes", dependencies=[Depends(_auth)])
def fuentes_get(conn=Depends(_conn)):
    fuentes.sembrar(conn)
    return {"fuentes": fuentes.listar(conn)}


class AutorizarIn(BaseModel):
    dominio: str
    autorizada: bool
    estado_tc: str
    nota: str = ""
    por: str = ""


@app.post("/news/fuentes/autorizar", dependencies=[Depends(_auth)])
def fuentes_autorizar(body: AutorizarIn, conn=Depends(_conn)):
    try:
        return {"ok": True, "fuente": fuentes.autorizar(conn, body.dominio, body.autorizada, body.estado_tc,
                                                         body.nota, body.por)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/news/senales", dependencies=[Depends(_auth)])
def senales(conn=Depends(_conn)):
    """Lo que FT Intelligence recoge y FT Discord anuncia. Vacío con
    NEWS_DISCORD_ACTIVO=0. Cada fila: id, tipo_alerta, texto_discord, texto_voz,
    jugador_x, rival, torneo, fecha_estimada, fixture_id, motivo, conclusion."""
    cfg = config.leer_config(conn)
    # v7.2: latido — prueba de que FT Intelligence está leyendo (aunque no haya nada que entregar)
    estado_set(conn, "senales_leidas_en", datetime.now(timezone.utc).isoformat())
    if not cfg["NEWS_DISCORD_ACTIVO"]:
        estado_set(conn, "senales_ultima_lectura", "0 señales (NEWS_DISCORD_ACTIVO=0)")
        return {"senales": [], "motivo": "NEWS_DISCORD_ACTIVO=0"}
    campos = ("id", "tipo_alerta", "motivo", "conclusion", "texto_discord", "texto_voz", "jugador_x", "rival", "torneo",
              "fecha_estimada", "genero", "circuito", "fixture_id", "cuota_x", "cuota_rival", "utr_x", "utr_rival",
              "banda_utr", "banda_mercado", "nivel", "creado_en", "actualizado_en",
              "partido_id", "evaluacion_id", "jugador_id", "rival_id", "clave")      # v5
    out = []
    for f in evaluador.senales(conn, cfg):
        d = {k: f.get(k) for k in campos}
        d["experimental"] = f.get("tipo_alerta") == "FUEGO_EXPERIMENTAL"
        d["prueba"] = bool(f.get("prueba"))                                      # v7.2
        if d["prueba"]:
            d["solo_admin"], d["destino"] = True, "ADMIN"                        # v7.3
        out.append(d)
    estado_set(conn, "senales_ultima_lectura", f"{len(out)} señal(es) entregada(s)")
    alertas.registrar_entrega(conn, [d["id"] for d in out])                    # v7.3: paso 2
    return {"senales": out}


class DichoIn(BaseModel):
    avisos: list[dict]


@app.post("/news/senales/dicho", dependencies=[Depends(_auth)])
def senales_dicho(body: DichoIn, conn=Depends(_conn)):
    """FT Intelligence informa qué pasó con cada señal: {id, dicho: bool, en, motivo}."""
    estado_set(conn, "senales_dicho_en", datetime.now(timezone.utc).isoformat())           # v7.2: latido
    # v7.3: si el aviso trae `publicado` (confirmación de FT Discord), es el paso 3; si no, queda sin confirmar
    return {"marcadas": evaluador.marcar_dichas(conn, body.avisos),
            "publicaciones": alertas.registrar_publicacion(conn, body.avisos)}


# ═════════════════════════════════════════════════════════════════════
# v7.2 (13/10/2026) — diagnóstico permanente y prueba de Discord
# ═════════════════════════════════════════════════════════════════════

@app.get("/news/salud", dependencies=[Depends(_auth)])
def salud_get(conn=Depends(_conn)):
    """Semáforo FUNCIONANDO / SIN_DATOS / ERROR con motivos e indicadores."""
    return salud_mod.calcular(conn)


@app.get("/news/embudo", dependencies=[Depends(_auth)])
def embudo_get(conn=Depends(_conn), dias: int = 7):
    """Las seis preguntas de Rubén, por día: noticias externas, descartes y motivo,
    rival sin investigar, cuota sin actualizar, entrega a FT Intelligence y bandas."""
    return {"salud": salud_mod.calcular(conn), "embudo": descartes.embudo(conn, max(1, min(int(dias), 60)))}


class PruebaIn(BaseModel):
    por: str = ""


@app.post("/news/prueba", dependencies=[Depends(_auth)])
def prueba_post(body: PruebaIn, conn=Depends(_conn)):
    """Prueba REAL de Discord, solo para administradores (RankingFTR exige admin):
    deja una alerta marcada PRUEBA en la cola que lee FT Intelligence. No cuenta en
    el historial, el dashboard, los topes ni las estadísticas."""
    cfg = config.leer_config(conn)
    if not cfg["NEWS_DISCORD_ACTIVO"]:
        raise HTTPException(status_code=409, detail="El envío a Discord está apagado: la prueba no saldría.")
    try:
        return alertas.crear_prueba(conn, body.por, cfg=cfg)
    except PermissionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/news/prueba/{pid}", dependencies=[Depends(_auth)])
def prueba_get(pid: int, conn=Depends(_conn)):
    r = alertas.estado_prueba(conn, pid)
    if r is None:
        raise HTTPException(status_code=404, detail="No existe esa prueba")
    return r


@app.get("/news/revision", dependencies=[Depends(_auth)])
def revision_get(conn=Depends(_conn), limite: int = 100):
    """Cola de revisión: OTRA, IDENTIDAD_DUDOSA, CATEGORIA_NUEVA pendientes."""
    filas = [dict(r) for r in conn.execute(
        "SELECT rv.*, j.nombre AS jugador, ev.categoria, ev.resumen_es, ev.enlace, ev.fuente, ev.estado AS evento_estado, "
        "ev.confianza_identidad FROM news_revision rv LEFT JOIN news_jugador j ON j.id=rv.jugador_id "
        "LEFT JOIN news_evento ev ON ev.id=rv.evento_id WHERE rv.estado='PENDIENTE' ORDER BY rv.id DESC LIMIT ?",
        (limite,)).fetchall()]
    return {"revision": filas}


class ResolverIn(BaseModel):
    accion: str        # CONFIRMAR | DESCARTAR | ES_EL_JUGADOR | CATEGORIA  (con `categoria`)
    categoria: str = ""
    por: str = ""


@app.post("/news/revision/{rid}", dependencies=[Depends(_auth)])
def revision_post(rid: int, body: ResolverIn, conn=Depends(_conn)):
    from ft_news.db import ejecutar_con_reintento, ahora_iso
    from ft_news import taxonomia as tx
    rv = conn.execute("SELECT * FROM news_revision WHERE id=?", (rid,)).fetchone()
    if not rv:
        raise HTTPException(status_code=404, detail="revisión no encontrada")
    acc = body.accion.upper()
    if acc not in ("CONFIRMAR", "DESCARTAR", "ES_EL_JUGADOR", "CATEGORIA", "DESMENTIR"):
        raise HTTPException(status_code=400, detail="acción inválida")
    if acc == "CATEGORIA" and body.categoria not in tx.CATEGORIAS:
        raise HTTPException(status_code=400, detail="categoría desconocida")

    def _w():
        if rv["evento_id"]:
            if acc == "DESCARTAR":
                conn.execute("UPDATE news_evento SET estado='DESCARTADO', actualizado_en=? WHERE id=?", (ahora_iso(), rv["evento_id"]))
                memoria.anotar_historial(conn, rv["evento_id"], "DESCARTADO", "revisión manual", body.por or "revision")
            elif acc == "DESMENTIR":
                # v5 (Rubén §4: estado confirmado / pendiente / desmentido)
                conn.execute("UPDATE news_evento SET estado='DESMENTIDO', actualizado_en=? WHERE id=?", (ahora_iso(), rv["evento_id"]))
                memoria.anotar_historial(conn, rv["evento_id"], "DESMENTIDO", "revisión manual", body.por or "revision")
            elif acc == "CONFIRMAR":
                memoria.anotar_historial(conn, rv["evento_id"], "CONFIRMADO", "revisión manual", body.por or "revision")
            elif acc == "ES_EL_JUGADOR":
                conn.execute("UPDATE news_evento SET estado='VIGENTE', confianza_identidad=1.0, actualizado_en=? WHERE id=? "
                             "AND estado='DESCARTADO'", (ahora_iso(), rv["evento_id"]))
            elif acc == "CATEGORIA":
                conn.execute("UPDATE news_evento SET categoria=?, actualizado_en=? WHERE id=?", (body.categoria, ahora_iso(), rv["evento_id"]))
        conn.execute("UPDATE news_revision SET estado='RESUELTA', resuelto_por=?, resuelto_en=? WHERE id=?",
                     (f"{body.por}:{acc}", ahora_iso(), rid))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)
    return {"ok": True}


class InteresanteIn(BaseModel):
    valor: str         # SI | NO | MERCADO_LO_SABIA
    por: str = ""


@app.post("/news/evaluaciones/{eid}/interesante", dependencies=[Depends(_auth)])
def evaluacion_interesante(eid: int, body: InteresanteIn, conn=Depends(_conn)):
    from ft_news import cierre
    if not conn.execute("SELECT 1 FROM news_evaluacion WHERE id=?", (eid,)).fetchone():
        raise HTTPException(status_code=404, detail="evaluación no encontrada")
    try:
        cierre.marcar_interesante(conn, eid, body.valor.upper(), body.por)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.get("/news/dashboard", dependencies=[Depends(_auth)])
def dashboard_get(conn=Depends(_conn), genero: str = "", valor_unidad: float = 1.0, limite: int = 500):
    """Dashboard de ganadas/perdidas de las 🔥 dichas en Discord (ver dashboard.py)."""
    from ft_news import dashboard
    return dashboard.armar(conn, genero, valor_unidad, limite)


@app.get("/news/excel", dependencies=[Depends(_auth)])
def excel_get(conn=Depends(_conn)):
    from fastapi.responses import Response
    from ft_news import excel
    datos = excel.construir(conn)
    return Response(datos, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="ft_news_historico.xlsx"'})


def _lectura(conn, e: dict, cfg: dict) -> dict:
    """La lectura simple guardada (lectura_json) o, si la fila es anterior a v7, armada ahora."""
    import json as _json
    try:
        l = _json.loads(e.get("lectura_json") or "{}")
    except (TypeError, ValueError):
        l = {}
    if l.get("lineas"):
        return l
    try:
        return explicar.evaluacion_desde_db(conn, e, cfg)
    except Exception as ex:                          # pragma: no cover
        return {"lineas": [], "texto": "", "resumen": explicar.motivo_simple(e.get("motivo")), "motivo": explicar.motivo_simple(e.get("motivo")),
                "error": str(ex)}


@app.get("/news/hoy", dependencies=[Depends(_auth)])
def hoy(conn=Depends(_conn), limite: int = 60):
    """Para la pestaña 📰: evaluaciones recientes, eventos recientes, cola y revisión."""
    evs = [dict(r) for r in conn.execute(
        "SELECT e.id, e.tipo_alerta, e.motivo, e.conclusion, e.nivel, e.banda_utr, e.banda_mercado, e.desvio, "
        "e.direccion_neta, e.utr_x, e.utr_rival, e.cuota_x, e.cuota_rival, e.dicho_discord, e.dicho_motivo, "
        "e.bandas_calibradas, e.texto_discord, e.actualizado_en, e.lectura_json, e.eventos_json, e.partido_id, "
        "e.jugador_x_id, e.rival_id, p.torneo, p.fecha_estimada, p.circuito, p.estado AS partido_estado, "
        "jx.nombre AS jugador_x, jr.nombre AS rival, r.score, r.retiro, r.era_interesante, r.mercado_hacia_noticia, "
        "jg.nombre AS ganador FROM news_evaluacion e JOIN news_partido p ON p.id=e.partido_id "
        "JOIN news_jugador jx ON jx.id=e.jugador_x_id JOIN news_jugador jr ON jr.id=e.rival_id "
        "LEFT JOIN news_resultado r ON r.evaluacion_id=e.id LEFT JOIN news_jugador jg ON jg.id=r.ganador_id "
        "ORDER BY CASE e.tipo_alerta WHEN 'FUEGO' THEN 0 WHEN 'INTERESANTE' THEN 1 ELSE 2 END, p.fecha_estimada "
        "LIMIT ?", (limite,)).fetchall()]
    eventos = [dict(r) for r in conn.execute(
        "SELECT ev.id, ev.categoria, ev.direccion, ev.naturaleza, ev.nivel, ev.fecha_evento, ev.fecha_publicacion, "
        "ev.fuente, ev.enlace, ev.resumen_es, ev.relevancia_deportiva, ev.estado, ev.verificar_estado_fisico, "
        "ev.confianza_identidad, j.nombre AS jugador, j.pais FROM news_evento ev JOIN news_jugador j ON j.id=ev.jugador_id "
        "ORDER BY ev.id DESC LIMIT ?", (limite,)).fetchall()]
    cola = {r["situacion"]: r["n"] for r in conn.execute(
        "SELECT situacion, COUNT(*) n FROM news_jugador_cola GROUP BY situacion").fetchall()}
    revision = conn.execute("SELECT COUNT(*) FROM news_revision WHERE estado='PENDIENTE'").fetchone()[0]
    for ev in eventos:
        ev["origen"] = "EXTERNO" if ev.get("enlace") and not str(ev["enlace"]).startswith("contexto:") else "INTERNO"
        ev["categoria_es"] = explicar.categoria_es(ev.get("categoria"))
        ev["texto_simple"] = explicar.evento_simple(ev, ev.get("jugador"))
        ev["estado_es"] = explicar.ESTADOS.get(ev.get("estado"), ev.get("estado"))
    # v7 (Rubén): cada evaluación con su lectura en palabras simples (la técnica queda en los campos de siempre)
    cfg = config.leer_config(conn)
    for e in evs:
        e["lectura"] = _lectura(conn, e, cfg)
        e["motivo_simple"] = explicar.motivo_simple(e.get("motivo"))
        e["dicho_motivo_simple"] = explicar.motivo_simple(e.get("dicho_motivo")) if e.get("dicho_motivo") else None
        e.pop("eventos_json", None)
        e.pop("lectura_json", None)
    return {"evaluaciones": evs, "eventos": eventos, "cola": cola, "revision_pendiente": revision,
            "alertas": alertas.listar(conn, limite), "alertas_resumen": _alertas_resumen(conn),
            "estado": estado_todo(conn), "costos_hoy": costos.hoy(conn), "costos_mes": costos.mes(conn)}


@app.get("/news/portada", dependencies=[Depends(_auth)])
def portada_get(conn=Depends(_conn)):
    """v7.4 (13/10/2026): la portada tipo periódico (titular, partidos interesantes, noticias, lesiones y agenda),
    solo con datos aptos para usuarios. Solo lectura. Ver portada.py."""
    from ft_news import portada
    return portada.armar(conn)


@app.get("/news/costos", dependencies=[Depends(_auth)])
def costos_get(conn=Depends(_conn)):
    cfg = config.leer_config(conn)
    return {"hoy": costos.hoy(conn), "mes": costos.mes(conn), "puede_gastar": costos.puede_gastar(conn, cfg),
            "topes": {k: cfg[k] for k in ("NEWS_MAX_BUSQUEDAS_DIA", "NEWS_MAX_TOKENS_DIA", "NEWS_MAX_USD_MES")}}


@app.get("/news/jugadores/buscar", dependencies=[Depends(_auth)])
def jugadores_buscar(conn=Depends(_conn), q: str = "", limite: int = 20):
    """v5 (Rubén §10: "buscar un jugador y consultar todo su historial de noticias")."""
    from ft_news import jugadores as jg
    qn = jg.normalizar(q)
    if len(qn) < 3:
        return {"jugadores": []}
    toks = qn.split()
    filas = [dict(r) for r in conn.execute(
        "SELECT j.id, j.nombre, j.pais, j.genero, j.circuito, j.utr_singles, j.utr_en, j.nombre_norm, "
        "(SELECT COUNT(*) FROM news_evento e WHERE e.jugador_id=j.id) AS eventos, "
        "(SELECT COUNT(*) FROM news_evento e WHERE e.jugador_id=j.id AND e.articulo_id IS NOT NULL) AS externos, "
        "(SELECT COUNT(*) FROM news_alerta a WHERE a.jugador_id=j.id OR a.rival_id=j.id) AS alertas, "
        "c.situacion, c.ultima_busqueda_en, c.proxima_busqueda_en FROM news_jugador j "
        "LEFT JOIN news_jugador_cola c ON c.jugador_id=j.id WHERE " + " AND ".join(["j.nombre_norm LIKE ?"] * len(toks)) +
        " ORDER BY eventos DESC, j.nombre LIMIT ?", (*[f"%{t}%" for t in toks], limite)).fetchall()]
    return {"jugadores": filas}


@app.get("/news/evaluaciones/{eid}", dependencies=[Depends(_auth)])
def evaluacion_detalle(eid: int, conn=Depends(_conn)):
    """10/10/2026 (Rubén: "cuando seleccione un partido 🔥, ver qué noticias encontró
    y todo lo que analizó"): la evaluación completa de un partido — noticias
    usadas (fuente, enlace, titular, nivel, confirmación), todo lo vigente de los
    dos (externo y calculado), lectura del descubridor, justificación de la 🔥,
    cuotas observadas, investigación reciente y las alertas que salieron."""
    import json as _json
    from ft_news import partidos as _pt
    e = conn.execute("SELECT * FROM news_evaluacion WHERE id=?", (eid,)).fetchone()
    if not e:
        raise HTTPException(status_code=404, detail="evaluación no encontrada")
    e = dict(e)
    p = conn.execute("SELECT * FROM news_partido WHERE id=?", (e["partido_id"],)).fetchone()
    p = dict(p) if p else {}
    js = {}
    for k in ("jugador_x_id", "rival_id"):
        j = conn.execute("SELECT id, nombre, pais, genero, circuito, utr_singles, utr_en, utr_display FROM news_jugador WHERE id=?",
                         (e[k],)).fetchone()
        js[k] = dict(j) if j else {"id": e[k], "nombre": "?"}
    try:
        usados_ids = [int(i) for i in _json.loads(e.get("eventos_json") or "[]") if i is not None]
    except (TypeError, ValueError):
        usados_ids = []

    def _ev(r):
        d = dict(r)
        d["origen"] = d.get("origen") or ("EXTERNO" if d.get("articulo_id") else "INTERNO")
        if d.get("articulo_id"):
            a = conn.execute("SELECT titulo, url, dominio, fecha_publicacion, idioma, origen AS via FROM news_articulo WHERE id=?",
                             (d["articulo_id"],)).fetchone()
            d["articulo"] = dict(a) if a else None
        d["cambios"] = memoria.historial_cambios(conn, d["id"])
        for k in ("lectura1_json", "lectura2_json"):
            d.pop(k, None)
        return d
    usados = [_ev(r) for r in conn.execute(
        f"SELECT * FROM news_evento WHERE id IN ({','.join('?' * len(usados_ids)) or 'NULL'}) ORDER BY fecha_evento", usados_ids)] if usados_ids else []
    vigentes = {}
    for k in ("jugador_x_id", "rival_id"):
        vigentes[k] = [_ev(r) for r in conn.execute(
            "SELECT * FROM news_evento WHERE jugador_id=? AND estado IN ('VIGENTE','EN_SEGUIMIENTO') ORDER BY fecha_evento DESC LIMIT 20",
            (e[k],))]
    al = []
    for a in alertas.listar(conn, 50):
        if a.get("partido_id") == e["partido_id"]:
            al.append(a)
    horas = int(config.leer_config(conn).get("NEWS_RIVAL_HORAS", 48))
    ahora = datetime.now(timezone.utc)
    fres = {k: alertas.frescura(conn, e[k], ahora, horas) for k in ("jugador_x_id", "rival_id")}
    busq = {k: [dict(r) for r in conn.execute(
        "SELECT consulta, idioma, resultados, creado_en FROM news_busqueda WHERE jugador_id=? ORDER BY id DESC LIMIT 8", (e[k],))]
        for k in ("jugador_x_id", "rival_id")}
    arts = {k: [dict(r) for r in conn.execute(
        "SELECT id, titulo, url, dominio, resultado, motivo, creado_en FROM news_articulo WHERE jugador_id=? ORDER BY id DESC LIMIT 12", (e[k],))]
        for k in ("jugador_x_id", "rival_id")}
    res = conn.execute("SELECT * FROM news_resultado WHERE evaluacion_id=?", (eid,)).fetchone()
    # v7: lectura simple + carga calculada de los dos + cada evento en una frase
    from ft_news import contexto as _ctx
    cfg_l = config.leer_config(conn)
    lectura = _lectura(conn, e, cfg_l)
    for lista in (usados, vigentes["jugador_x_id"], vigentes["rival_id"]):
        for d in lista:
            d["categoria_es"] = explicar.categoria_es(d.get("categoria"))
            d["texto_simple"] = explicar.evento_simple(d, js["jugador_x_id"]["nombre"] if d.get("jugador_id") == e["jugador_x_id"] else js["rival_id"]["nombre"])
            d["estado_es"] = explicar.ESTADOS.get(d.get("estado"), d.get("estado"))
    carga = {"x": _ctx.carga_de(conn, e["jugador_x_id"], e["partido_id"]), "rival": _ctx.carga_de(conn, e["rival_id"], e["partido_id"])}
    e["motivo_simple"] = explicar.motivo_simple(e.get("motivo"))
    e["dicho_motivo_simple"] = explicar.motivo_simple(e.get("dicho_motivo")) if e.get("dicho_motivo") else None
    e.pop("lectura_json", None)
    return {"evaluacion": e, "partido": p, "jugador_x": js["jugador_x_id"], "rival": js["rival_id"], "lectura": lectura, "carga": carga,
            "eventos_usados": usados, "vigentes_x": vigentes["jugador_x_id"], "vigentes_rival": vigentes["rival_id"],
            "cuotas": _pt.observaciones(conn, e["partido_id"]) if e.get("partido_id") else [],
            "alertas": al, "frescura": {"x": fres["jugador_x_id"], "rival": fres["rival_id"]},
            "busquedas": {"x": busq["jugador_x_id"], "rival": busq["rival_id"]},
            "articulos": {"x": arts["jugador_x_id"], "rival": arts["rival_id"]},
            "resultado": dict(res) if res else None}


@app.get("/news/jugadores/{jugador_id}/memoria", dependencies=[Depends(_auth)])
def memoria_get(jugador_id: int, conn=Depends(_conn)):
    hist = memoria.historial_db(conn, jugador_id)
    j = conn.execute("SELECT id, nombre, pais, genero, circuito, utr_singles, utr_en FROM news_jugador WHERE id=?",
                     (jugador_id,)).fetchone()
    for ev in hist:
        ev["origen"] = ev.get("origen") or ("EXTERNO" if ev.get("articulo_id") else "INTERNO")
        ev["cambios"] = memoria.historial_cambios(conn, ev["id"])
        ev["categoria_es"] = explicar.categoria_es(ev.get("categoria"))
        ev["texto_simple"] = explicar.evento_simple(ev, (dict(j) if j else {}).get("nombre"))
        ev["estado_es"] = explicar.ESTADOS.get(ev.get("estado"), ev.get("estado"))
    alertas_j = alertas.listar(conn, 50)
    alertas_j = [a for a in alertas_j if a.get("jugador_id") == jugador_id or a.get("rival_id") == jugador_id]
    partidos_j = [dict(r) for r in conn.execute(
        "SELECT p.id, p.torneo, p.fecha_estimada, p.estado, p.cuota1, p.cuota2, j1.nombre AS jugador1, j2.nombre AS jugador2 "
        "FROM news_partido p JOIN news_jugador j1 ON j1.id=p.jugador1_id JOIN news_jugador j2 ON j2.id=p.jugador2_id "
        "WHERE (p.jugador1_id=? OR p.jugador2_id=?) AND p.estado<>'DUPLICADO' ORDER BY p.fecha_estimada DESC LIMIT 20",
        (jugador_id, jugador_id)).fetchall()]
    busquedas = [dict(r) for r in conn.execute(
        "SELECT consulta, idioma, resultados, creado_en FROM news_busqueda WHERE jugador_id=? ORDER BY id DESC LIMIT 20",
        (jugador_id,)).fetchall()]
    from ft_news import contexto as _ctx
    return {"jugador_id": jugador_id, "jugador": dict(j) if j else None, "eventos": hist,
            "lectura": memoria.lectura_contextual(hist, jugador_id),
            "lectura_simple": explicar.lectura_jugador([x for x in hist if x.get("jugador_id") == jugador_id], (dict(j) if j else {}).get("nombre") or ""),
            "carga": _ctx.carga_de(conn, jugador_id),
            "estado_fisico_sin_verificar": memoria.estado_fisico_sin_verificar(hist, jugador_id),
            "alertas": alertas_j, "partidos": partidos_j, "busquedas": busquedas}


@app.get("/news/alertas", dependencies=[Depends(_auth)])
def alertas_get(conn=Depends(_conn), limite: int = 100, tipo: str = ""):
    """v5 panel de alertas: enviadas, pendientes, omitidas; motivo de selección,
    evidencia, estado del partido y resultado final."""
    return {"alertas": alertas.listar(conn, limite, tipo or None), "resumen": _alertas_resumen(conn)}


@app.get("/news/diagnostico", dependencies=[Depends(_auth)])
def diagnostico_get(conn=Depends(_conn), dias: int = 7):
    """v5 (Rubén §3): búsquedas, artículos, descartados y motivo, fuentes, errores,
    externos vs internos, costo por proveedor. Todo por los últimos `dias`."""
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    q = lambda sql, *a: [dict(r) for r in conn.execute(sql, a).fetchall()]  # noqa: E731
    busq = q("SELECT COALESCE(origen,'radar') origen, idioma, COUNT(*) n, SUM(CASE WHEN resultados=0 THEN 1 ELSE 0 END) sin_resultados, "
             "SUM(resultados) resultados, ROUND(SUM(usd_estimado),4) usd FROM news_busqueda WHERE creado_en>=? "
             "GROUP BY origen, idioma ORDER BY n DESC", desde)
    busq_circuito = q("SELECT COALESCE(j.circuito,'?') circuito, COUNT(*) n, SUM(CASE WHEN b.resultados=0 THEN 1 ELSE 0 END) sin_resultados "
                      "FROM news_busqueda b LEFT JOIN news_jugador j ON j.id=b.jugador_id WHERE b.creado_en>=? AND b.jugador_id IS NOT NULL "
                      "GROUP BY circuito ORDER BY n DESC", desde)
    arts = q("SELECT COALESCE(resultado,'(sin marcar)') resultado, COUNT(*) n FROM news_articulo WHERE creado_en>=? "
             "GROUP BY resultado ORDER BY n DESC", desde)
    arts_origen = q("SELECT COALESCE(origen,'radar') origen, COUNT(*) n FROM news_articulo WHERE creado_en>=? GROUP BY origen", desde)
    fuentes_usadas = q("SELECT dominio, COUNT(*) n, SUM(CASE WHEN resultado='EVENTO' THEN 1 ELSE 0 END) eventos "
                       "FROM news_articulo WHERE creado_en>=? GROUP BY dominio ORDER BY n DESC LIMIT 40", desde)
    descartados = q("SELECT id, dominio, titulo, url, resultado, motivo, creado_en FROM news_articulo WHERE creado_en>=? "
                    "AND resultado NOT IN ('EVENTO','PENDIENTE') ORDER BY id DESC LIMIT 60", desde)
    eventos = q("SELECT CASE WHEN articulo_id IS NULL THEN 'INTERNO' ELSE 'EXTERNO' END origen, categoria, estado, COUNT(*) n "
                "FROM news_evento WHERE creado_en>=? GROUP BY origen, categoria, estado ORDER BY origen, n DESC", desde)
    externos_hoy = conn.execute("SELECT COUNT(*) FROM news_evento WHERE articulo_id IS NOT NULL AND creado_en>=?",
                                (datetime.now(timezone.utc).date().isoformat(),)).fetchone()[0]
    internos_hoy = conn.execute("SELECT COUNT(*) FROM news_evento WHERE articulo_id IS NULL AND creado_en>=?",
                                (datetime.now(timezone.utc).date().isoformat(),)).fetchone()[0]
    costos_prov = q("SELECT proveedor, SUM(busquedas) busquedas, SUM(articulos) articulos, SUM(tokens_entrada+tokens_salida) tokens, "
                    "ROUND(SUM(usd_estimado),4) usd FROM news_costos_dia WHERE dia>=? GROUP BY proveedor", desde[:10])
    cola = q("SELECT situacion, COALESCE(circuito,'?') circuito, COUNT(*) n, SUM(CASE WHEN ultima_busqueda_en IS NULL THEN 1 ELSE 0 END) nunca "
             "FROM news_jugador_cola GROUP BY situacion, circuito ORDER BY situacion, n DESC")
    errores = q("SELECT c.jugador_id, j.nombre, c.ultimo_error, c.actualizado_en FROM news_jugador_cola c JOIN news_jugador j ON j.id=c.jugador_id "
                "WHERE c.ultimo_error IS NOT NULL AND c.ultimo_error<>'' ORDER BY c.actualizado_en DESC LIMIT 30")
    est = estado_todo(conn)
    pasos = {k[5:]: v.get("valor") for k, v in est.items() if k.startswith("paso_")}
    partidos_unicos = conn.execute("SELECT COUNT(*) FROM news_partido WHERE estado<>'DUPLICADO'").fetchone()[0]
    duplicados = conn.execute("SELECT COUNT(*) FROM news_partido WHERE estado='DUPLICADO'").fetchone()[0]
    cfg = config.leer_config(conn)
    reintentos = q("SELECT resultado, COUNT(*) n FROM news_articulo WHERE resultado IN ('PENDIENTE','ERROR','FUERA_DE_ESQUEMA','AGOTADO') "
                   "GROUP BY resultado")
    from ft_news import diagnostico_carga
    return {"dias": dias, "busquedas": busq, "busquedas_por_circuito": busq_circuito, "articulos": arts,
            "cobertura": cobertura.por_circuito(conn, cfg, dias=dias), "reintentos": reintentos,
            "carga": diagnostico_carga.reglas(conn, cfg, dias=max(dias, 30)),
            "articulos_por_origen": arts_origen, "fuentes": fuentes_usadas, "descartados": descartados,
            "eventos": eventos, "hoy": {"externos": externos_hoy, "internos": internos_hoy},
            "costos_por_proveedor": costos_prov, "cola": cola, "errores": errores, "pasos": pasos,
            "partidos": {"unicos": partidos_unicos, "duplicados_fundidos": duplicados},
            "alertas": _alertas_resumen(conn), "clasificador": (est.get("clasificador") or {}).get("valor")}
