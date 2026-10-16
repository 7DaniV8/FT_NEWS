"""
ft_news/control.py — 📋 Control: qué está mirando y haciendo FT NEWS, partido por partido (v7.9, 16/10/2026).

Rubén: «me gustaría crear eso [el control de UNDER UTR] en las siguientes tabs, es que no sé si están funcionando o
leyendo o qué están haciendo». Para cada partido que FT NEWS tiene en su ventana (de 12 h atrás a 48 h adelante):

  - los dos jugadores y, de cada uno: en qué situación está en la cola de búsqueda, cuándo se lo buscó por última
    vez y cuándo toca de nuevo, cuántas búsquedas se hicieron en 24 h y cuántas noticias vigentes tiene;
  - la última evaluación del partido (🔥 / 🔎 / 📰 / nada, con su motivo) y si generó alerta (y si salió a Discord);
  - cuántas cuotas se observaron.

Arriba, el último ciclo del worker y el resultado de cada paso (OK / ERROR con su detalle).

Solo lectura. Las fechas se comparan en Python (las tablas guardan ISO con o sin zona).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news.db import estado_todo

NOMBRE_PASO = {"padron": "padrón de jugadores", "calibracion": "calibración", "partidos": "partidos próximos",
               "contexto": "contexto propio", "radar": "búsqueda de noticias", "rss": "fuentes RSS",
               "descubridor": "evaluación de partidos", "cierre": "resultados", "costos": "costos",
               "vencimientos": "vencimientos", "fusion_duplicados": "duplicados",
               "alertas_vencidas": "alertas vencidas", "reintentos": "reintentos", "tematico": "búsqueda temática",
               "fotos": "fotos"}


def _dt(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _paso(valor: str) -> dict:
    """«OK 2026-10-16T… {…}» / «ERROR 2026-10-16T… detalle» → {estado, en, detalle}."""
    partes = str(valor or "").split(" ", 2)
    return {"estado": partes[0] if partes else "", "en": partes[1] if len(partes) > 1 else None,
            "detalle": (partes[2] if len(partes) > 2 else "")[:400]}


def _en(ids) -> tuple[str, list]:
    ids = [i for i in ids if i is not None]
    return ",".join("?" * len(ids)) or "NULL", ids


def control(conn, horas_atras: int = 12, horas_adelante: int = 48, limite: int = 300,
            ahora: Optional[datetime] = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    est = estado_todo(conn)
    v = lambda k: (est.get(k) or {}).get("valor")  # noqa: E731
    pasos = [{"paso": k[5:], "nombre": NOMBRE_PASO.get(k[5:], k[5:]), **_paso(d.get("valor"))}
             for k, d in sorted(est.items()) if k.startswith("paso_")]
    out = {"ultimo_ciclo_en": v("ultimo_ciclo_en"), "activo": v("activo"), "motivo": v("motivo"), "pasos": pasos,
           "ventana": {"horas_atras": horas_atras, "horas_adelante": horas_adelante}, "partidos": [], "resumen": {}}

    desde, hasta = ahora - timedelta(hours=horas_atras), ahora + timedelta(hours=horas_adelante)
    filas = conn.execute(
        "SELECT p.id, p.fixture_id, p.torneo, p.circuito, p.ronda, p.fecha_estimada, p.estado, p.jugador1_id, "
        "p.jugador2_id, j1.nombre AS jugador1, j2.nombre AS jugador2 FROM news_partido p "
        "LEFT JOIN news_jugador j1 ON j1.id=p.jugador1_id LEFT JOIN news_jugador j2 ON j2.id=p.jugador2_id "
        "WHERE substr(p.fecha_estimada,1,10) BETWEEN ? AND ?",
        (desde.date().isoformat(), hasta.date().isoformat())).fetchall()
    partidos = [dict(r) for r in filas if (lambda d: d is not None and desde <= d <= hasta)(_dt(r["fecha_estimada"]))]
    partidos.sort(key=lambda p: _dt(p["fecha_estimada"]))
    partidos = partidos[:limite]
    jids = {p[k] for p in partidos for k in ("jugador1_id", "jugador2_id") if p[k] is not None}
    pids = [p["id"] for p in partidos]

    marcas, args = _en(jids)
    cola = {r["jugador_id"]: dict(r) for r in conn.execute(
        f"SELECT jugador_id, situacion, motivo, ultima_busqueda_en, proxima_busqueda_en FROM news_jugador_cola "
        f"WHERE jugador_id IN ({marcas})", args).fetchall()}
    d24 = (ahora - timedelta(hours=24)).isoformat()
    busq = {r[0]: r[1] for r in conn.execute(
        f"SELECT jugador_id, COUNT(*) FROM news_busqueda WHERE jugador_id IN ({marcas}) AND creado_en >= ? "
        f"GROUP BY jugador_id", args + [d24]).fetchall()}
    evs = {r[0]: r[1] for r in conn.execute(
        f"SELECT jugador_id, COUNT(*) FROM news_evento WHERE jugador_id IN ({marcas}) "
        f"AND estado IN ('VIGENTE','EN_SEGUIMIENTO') GROUP BY jugador_id", args).fetchall()}
    marcas_p, args_p = _en(pids)
    ultima_eval = {}
    for r in conn.execute(f"SELECT partido_id, tipo_alerta, motivo, conclusion, creado_en, id FROM news_evaluacion "
                          f"WHERE partido_id IN ({marcas_p}) ORDER BY id", args_p).fetchall():
        ultima_eval[r["partido_id"]] = dict(r)
    alertas = {}
    for r in conn.execute(f"SELECT partido_id, tipo, dicho_discord, dicho_motivo FROM news_alerta "
                          f"WHERE partido_id IN ({marcas_p}) AND COALESCE(prueba,0)=0 ORDER BY id", args_p).fetchall():
        alertas[r["partido_id"]] = dict(r)
    cuotas = {r[0]: (r[1], r[2]) for r in conn.execute(
        f"SELECT partido_id, COUNT(*), MAX(visto_en) FROM news_cuota_obs WHERE partido_id IN ({marcas_p}) "
        f"GROUP BY partido_id", args_p).fetchall()}

    def jug(jid, nombre):
        c = cola.get(jid) or {}
        return {"nombre": nombre, "situacion": c.get("situacion"), "ultima_busqueda_en": c.get("ultima_busqueda_en"),
                "proxima_busqueda_en": c.get("proxima_busqueda_en"), "busquedas_24h": busq.get(jid, 0),
                "noticias_vigentes": evs.get(jid, 0), "en_cola": bool(c)}

    for p in partidos:
        e = ultima_eval.get(p["id"]) or {}
        a = alertas.get(p["id"]) or {}
        nc, cu = cuotas.get(p["id"], (0, None))
        out["partidos"].append({
            "id": p["id"], "fecha": p["fecha_estimada"], "torneo": p["torneo"], "circuito": p["circuito"],
            "ronda": p["ronda"], "estado": p["estado"],
            "j1": jug(p["jugador1_id"], p["jugador1"]), "j2": jug(p["jugador2_id"], p["jugador2"]),
            "evaluacion": e.get("tipo_alerta"), "evaluacion_motivo": (e.get("motivo") or "")[:300] or None,
            "evaluado_en": e.get("creado_en"), "alerta": a.get("tipo"),
            "alerta_discord": {0: "pendiente", 1: "dicha", 2: "omitida"}.get(a.get("dicho_discord")) if a else None,
            "alerta_motivo": a.get("dicho_motivo"), "cuotas_vistas": nc, "ultima_cuota_en": cu})
    ps = out["partidos"]
    out["resumen"] = {
        "partidos": len(ps),
        "con_jugador_buscado_24h": sum(1 for p in ps if p["j1"]["busquedas_24h"] or p["j2"]["busquedas_24h"]),
        "con_noticias_vigentes": sum(1 for p in ps if p["j1"]["noticias_vigentes"] or p["j2"]["noticias_vigentes"]),
        "evaluados": sum(1 for p in ps if p["evaluacion"]),
        "con_alerta": sum(1 for p in ps if p["alerta"]),
        "con_cuotas": sum(1 for p in ps if p["cuotas_vistas"]),
        "busquedas_24h_total": conn.execute("SELECT COUNT(*) FROM news_busqueda WHERE creado_en >= ?",
                                            (d24,)).fetchone()[0],
        "articulos_24h": conn.execute("SELECT COUNT(*) FROM news_articulo WHERE creado_en >= ?", (d24,)).fetchone()[0],
        "noticias_24h": conn.execute("SELECT COUNT(*) FROM news_evento WHERE creado_en >= ?", (d24,)).fetchone()[0]}
    return out
