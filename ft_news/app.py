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
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from ft_news import VERSION, config, costos, evaluador, fuentes, memoria, tareas
from ft_news.db import config_guardar, estado_todo, get_conn

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
            "fuentes": {"total": n("news_fuente"),
                        "autorizadas": conn.execute("SELECT COUNT(*) FROM news_fuente WHERE autorizada=1").fetchone()[0]},
            "contadores": {t: n(t) for t in ("news_jugador", "news_jugador_cola", "news_evento", "news_partido",
                                             "news_evaluacion", "news_revision")},
            "estado": estado_todo(conn), "costos_hoy": costos.hoy(conn), "costos_mes": costos.mes(conn)}


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
    if not cfg["NEWS_DISCORD_ACTIVO"]:
        return {"senales": [], "motivo": "NEWS_DISCORD_ACTIVO=0"}
    campos = ("id", "tipo_alerta", "motivo", "conclusion", "texto_discord", "texto_voz", "jugador_x", "rival", "torneo",
              "fecha_estimada", "genero", "circuito", "fixture_id", "cuota_x", "cuota_rival", "utr_x", "utr_rival",
              "banda_utr", "banda_mercado", "nivel", "creado_en", "actualizado_en")
    return {"senales": [{k: f.get(k) for k in campos} for f in evaluador.senales(conn, cfg)]}


class DichoIn(BaseModel):
    avisos: list[dict]


@app.post("/news/senales/dicho", dependencies=[Depends(_auth)])
def senales_dicho(body: DichoIn, conn=Depends(_conn)):
    """FT Intelligence informa qué pasó con cada señal: {id, dicho: bool, en, motivo}."""
    return {"marcadas": evaluador.marcar_dichas(conn, body.avisos)}


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
    if acc not in ("CONFIRMAR", "DESCARTAR", "ES_EL_JUGADOR", "CATEGORIA"):
        raise HTTPException(status_code=400, detail="acción inválida")
    if acc == "CATEGORIA" and body.categoria not in tx.CATEGORIAS:
        raise HTTPException(status_code=400, detail="categoría desconocida")

    def _w():
        if rv["evento_id"]:
            if acc == "DESCARTAR":
                conn.execute("UPDATE news_evento SET estado='DESCARTADO', actualizado_en=? WHERE id=?", (ahora_iso(), rv["evento_id"]))
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


@app.get("/news/hoy", dependencies=[Depends(_auth)])
def hoy(conn=Depends(_conn), limite: int = 60):
    """Para la pestaña 📰: evaluaciones recientes, eventos recientes, cola y revisión."""
    evs = [dict(r) for r in conn.execute(
        "SELECT e.id, e.tipo_alerta, e.motivo, e.conclusion, e.nivel, e.banda_utr, e.banda_mercado, e.desvio, "
        "e.direccion_neta, e.utr_x, e.utr_rival, e.cuota_x, e.cuota_rival, e.dicho_discord, e.dicho_motivo, "
        "e.bandas_calibradas, e.texto_discord, e.actualizado_en, p.torneo, p.fecha_estimada, p.circuito, p.estado AS partido_estado, "
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
    return {"evaluaciones": evs, "eventos": eventos, "cola": cola, "revision_pendiente": revision,
            "estado": estado_todo(conn), "costos_hoy": costos.hoy(conn), "costos_mes": costos.mes(conn)}


@app.get("/news/costos", dependencies=[Depends(_auth)])
def costos_get(conn=Depends(_conn)):
    cfg = config.leer_config(conn)
    return {"hoy": costos.hoy(conn), "mes": costos.mes(conn), "puede_gastar": costos.puede_gastar(conn, cfg),
            "topes": {k: cfg[k] for k in ("NEWS_MAX_BUSQUEDAS_DIA", "NEWS_MAX_TOKENS_DIA", "NEWS_MAX_USD_MES")}}


@app.get("/news/jugadores/{jugador_id}/memoria", dependencies=[Depends(_auth)])
def memoria_get(jugador_id: int, conn=Depends(_conn)):
    hist = memoria.historial_db(conn, jugador_id)
    return {"jugador_id": jugador_id, "eventos": hist, "lectura": memoria.lectura_contextual(hist, jugador_id),
            "estado_fisico_sin_verificar": memoria.estado_fisico_sin_verificar(hist, jugador_id)}
