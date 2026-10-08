"""
ft_news/cierre.py — Motor 5: seguimiento (segunda entrega, 08/10/2026).

Para cada partido evaluado que ya debió jugarse:
  - busca el resultado en match_log (historial de RankingFTR, últimos días)
    por el par de jugadores; ganador, score, retiro (ret./w.o.);
  - cuota de cierre = la última cuota vista en los fixtures (cuota1/cuota2
    al momento del último sync antes del partido);
  - "¿se movió el mercado hacia la noticia?": apertura vs cierre de X en la
    dirección de la noticia (NEGATIVA → la cuota de X subió; POSITIVA → bajó);
  - R4 de la memoria: un partido completo (sin retiro) suma a la
    verificación del estado físico de ambos; un retiro entra como evento
    RETIRO_ABANDONO nivel A (dato propio).
  - acierto del lado de la noticia: solo se REPORTA (RESUMEN); no decide nada.
La marca manual "¿era interesante?" (SI / NO / MERCADO_LO_SABIA) la pone
Rubén desde la pestaña: es la métrica que vale (diseño §8).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import contexto, memoria
from ft_news import jugadores as jg
from ft_news.db import ahora_iso, ejecutar_con_reintento

DIAS_BUSCAR = 4          # cuánto se espera un resultado antes de darlo por SIN_RESULTADO
HORAS_TRAS_INICIO = 3    # recién después de esto se busca


def _dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s)[:19].replace(" ", "T"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _par(a: str, b: str) -> frozenset:
    return frozenset((jg.normalizar(a), jg.normalizar(b)))


def _hacia_noticia(direccion: Optional[str], apertura: Optional[float], cierre: Optional[float]) -> Optional[int]:
    if not direccion or not apertura or not cierre or apertura == cierre:
        return None
    if direccion == "NEGATIVA":
        return 1 if cierre > apertura else 0
    if direccion == "POSITIVA":
        return 1 if cierre < apertura else 0
    return None


def _claves_par(nombre: str) -> set:
    return jg.claves_apellido_inicial(nombre)


def _buscar_resultado(filas: list[dict], jx: dict, jr: dict, desde: datetime) -> Optional[dict]:
    kx, kr = _claves_par(jx["nombre"]), _claves_par(jr["nombre"])
    for f in filas:
        fd = _dt(f.get("fecha"))
        if not fd or fd < desde - timedelta(days=1):
            continue
        a, b = f.get("jugador") or "", f.get("rival") or ""
        ka, kb = _claves_par(a), _claves_par(b)
        if (ka & kx and kb & kr) or (ka & kr and kb & kx):
            gano_x = bool(ka & kx)
            return {"gano_x": gano_x, "score": f.get("score"), "retiro": contexto._retiro(f.get("score")),
                    "fecha": f.get("fecha"), "ganador": a}
    return None


def correr(conn, cliente, cfg: dict, ahora: Optional[datetime] = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    res = {"revisados": 0, "cerrados": 0, "sin_resultado": 0, "retiros": 0}
    pendientes = [dict(r) for r in conn.execute(
        "SELECT e.id AS eval_id, e.partido_id, e.jugador_x_id, e.rival_id, e.direccion_neta, e.cuota_x, e.cuota_rival, "
        "p.fecha_estimada, p.cuota1, p.cuota2, p.cuota1_apertura, p.cuota2_apertura, p.jugador1_id, p.estado "
        "FROM news_evaluacion e JOIN news_partido p ON p.id = e.partido_id "
        "LEFT JOIN news_resultado r ON r.evaluacion_id = e.id WHERE r.evaluacion_id IS NULL "
        "AND p.estado IN ('PROGRAMADO','JUGADO')").fetchall()]
    candidatos = [p for p in pendientes if _dt(p["fecha_estimada"]) and _dt(p["fecha_estimada"]) + timedelta(hours=HORAS_TRAS_INICIO) <= ahora]
    if not candidatos:
        return res
    desde = min(_dt(p["fecha_estimada"]) for p in candidatos) - timedelta(days=1)
    filas = (cliente.historial(desde.date().isoformat()) or {}).get("partidos") or []
    for p in candidatos:
        res["revisados"] += 1
        jx = dict(conn.execute("SELECT * FROM news_jugador WHERE id=?", (p["jugador_x_id"],)).fetchone())
        jr = dict(conn.execute("SELECT * FROM news_jugador WHERE id=?", (p["rival_id"],)).fetchone())
        r = _buscar_resultado(filas, jx, jr, _dt(p["fecha_estimada"]))
        x_es_1 = p["jugador1_id"] == p["jugador_x_id"]
        cierre_x = p["cuota1"] if x_es_1 else p["cuota2"]
        cierre_r = p["cuota2"] if x_es_1 else p["cuota1"]
        apert_x = p["cuota1_apertura"] if x_es_1 else p["cuota2_apertura"]
        if r is None:
            if _dt(p["fecha_estimada"]) + timedelta(days=DIAS_BUSCAR) < ahora:
                _guardar(conn, p["eval_id"], None, None, None, cierre_x, cierre_r,
                         _hacia_noticia(p["direccion_neta"], apert_x, cierre_x), "SIN_RESULTADO", ahora)
                _estado_partido(conn, p["partido_id"], "SIN_RESULTADO")
                res["sin_resultado"] += 1
            continue
        _guardar(conn, p["eval_id"], jx["id"] if r["gano_x"] else jr["id"], int(r["retiro"]), r["score"], cierre_x, cierre_r,
                 _hacia_noticia(p["direccion_neta"], apert_x, cierre_x), "JUGADO", ahora)
        _estado_partido(conn, p["partido_id"], "JUGADO")
        res["cerrados"] += 1
        # memoria: R4 (partido completo verifica) o retiro (evento nivel A)
        for j in (jx, jr):
            hist = memoria.historial_db(conn, j["id"])
            if r["retiro"]:
                perdedor = jr if r["gano_x"] else jx
                if j["id"] == perdedor["id"] and not conn.execute(
                        "SELECT 1 FROM news_evento WHERE jugador_id=? AND categoria='RETIRO_ABANDONO' AND enlace=?",
                        (j["id"], f"resultado:{p['partido_id']}")).fetchone():
                    memoria.guardar_evento_db(conn, memoria.nuevo_evento(
                        j["id"], "RETIRO_ABANDONO", "NEGATIVA", "HECHO", "A", r["fecha"] or ahora.isoformat(),
                        fuente=contexto.FUENTE, enlace=f"resultado:{p['partido_id']}",
                        resumen_es=f"no completó el partido ({r['score']})", confianza_identidad=1.0))
                    res["retiros"] += 1
            else:
                memoria.registrar_partido_completo(hist, j["id"], r["fecha"] or ahora.isoformat())
                _persistir_verificacion(conn, hist)
    return res


def _persistir_verificacion(conn, hist: list[dict]) -> None:
    def _w():
        for e in hist:
            if e.get("id"):
                conn.execute("UPDATE news_evento SET verificar_estado_fisico=?, partidos_completos_desde=?, actualizado_en=? WHERE id=?",
                             (int(e.get("verificar_estado_fisico") or 0), int(e.get("partidos_completos_desde") or 0),
                              ahora_iso(), e["id"]))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def _guardar(conn, eval_id, ganador_id, retiro, score, cierre_x, cierre_r, hacia, estado, ahora) -> None:
    def _w():
        conn.execute("INSERT INTO news_resultado (evaluacion_id, ganador_id, retiro, score, cuota_cierre_x, cuota_cierre_rival, "
                     "mercado_hacia_noticia, cerrado_en) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(evaluacion_id) DO UPDATE SET "
                     "ganador_id=excluded.ganador_id, retiro=excluded.retiro, score=excluded.score, "
                     "cuota_cierre_x=excluded.cuota_cierre_x, cuota_cierre_rival=excluded.cuota_cierre_rival, "
                     "mercado_hacia_noticia=excluded.mercado_hacia_noticia, cerrado_en=excluded.cerrado_en",
                     (eval_id, ganador_id, retiro, score, cierre_x, cierre_r, hacia, ahora.isoformat()))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def _estado_partido(conn, partido_id: int, estado: str) -> None:
    def _w():
        conn.execute("UPDATE news_partido SET estado=?, actualizado_en=? WHERE id=?", (estado, ahora_iso(), partido_id))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def marcar_interesante(conn, eval_id: int, valor: str, por: str) -> bool:
    if valor not in ("SI", "NO", "MERCADO_LO_SABIA"):
        raise ValueError("valor inválido")

    def _w():
        conn.execute("INSERT INTO news_resultado (evaluacion_id, era_interesante, marcado_por, cerrado_en) VALUES (?,?,?,NULL) "
                     "ON CONFLICT(evaluacion_id) DO UPDATE SET era_interesante=excluded.era_interesante, "
                     "marcado_por=excluded.marcado_por", (eval_id, valor, por))
        conn.commit()
        return True
    return ejecutar_con_reintento(_w, conn=conn)
