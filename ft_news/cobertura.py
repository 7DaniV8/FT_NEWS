"""
ft_news/cobertura.py — v5.1 (Rubén §5: "verificar cobertura real por circuito").

Por circuito (atp, wta, challenger, wta125, itf, utr): jugadores en cola,
investigados en la ventana, nunca buscados, búsquedas, artículos externos,
noticias útiles (eventos externos fuertes), partidos analizados y alertas.
Y una propuesta de presupuesto: cuántas búsquedas/día hacen falta para
atender la cola a su cadencia, contra NEWS_MAX_BUSQUEDAS_DIA.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import jugadores as jg

CIRCUITOS = ("atp", "wta", "challenger", "wta125", "itf", "utr")
_CADENCIA_H = {"PARTIDO_24H": 6, "PARTIDO_72H": 12, "EVENTO_VIGENTE": 24, "MANUAL": 24, "SIN_PARTIDO": 24 * 7}
_FUERTES = ("LESION_MOLESTIA", "ENFERMEDAD", "RETIRO_ABANDONO", "REGRESO", "SANCION_DISCIPLINA")


def _circ(c: Optional[str]) -> str:
    c = (c or "").lower()
    return c if c in CIRCUITOS else ("otro" if c else "sin_circuito")


def por_circuito(conn, cfg: dict, ahora: Optional[datetime] = None, dias: int = 7) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    desde = (ahora - timedelta(days=dias)).isoformat()
    filas = {c: {"circuito": c, "en_cola": 0, "investigados": 0, "nunca_buscados": 0, "busquedas": 0, "sin_resultado": 0,
                 "articulos": 0, "articulos_externos_evento": 0, "noticias_utiles": 0, "partidos_analizados": 0,
                 "evaluaciones": 0, "alertas": 0, "alertas_por_tipo": {}} for c in CIRCUITOS + ("otro", "sin_circuito")}
    circ_j = {}
    for r in conn.execute("SELECT c.jugador_id, COALESCE(c.circuito, j.circuito) circ, c.ultima_busqueda_en "
                          "FROM news_jugador_cola c JOIN news_jugador j ON j.id=c.jugador_id"):
        c = _circ(r["circ"])
        circ_j[r["jugador_id"]] = c
        f = filas[c]
        f["en_cola"] += 1
        if r["ultima_busqueda_en"] is None:
            f["nunca_buscados"] += 1
        elif r["ultima_busqueda_en"] >= desde:
            f["investigados"] += 1
    # jugadores fuera de la cola (padrón) con circuito conocido: para el denominador
    for r in conn.execute("SELECT id, circuito FROM news_jugador"):
        circ_j.setdefault(r["id"], _circ(r["circuito"]))
    for r in conn.execute("SELECT jugador_id, resultados FROM news_busqueda WHERE creado_en>=? AND jugador_id IS NOT NULL", (desde,)):
        f = filas[circ_j.get(r["jugador_id"], "sin_circuito")]
        f["busquedas"] += 1
        if not r["resultados"]:
            f["sin_resultado"] += 1
    for r in conn.execute("SELECT jugador_id, resultado FROM news_articulo WHERE creado_en>=? AND jugador_id IS NOT NULL", (desde,)):
        f = filas[circ_j.get(r["jugador_id"], "sin_circuito")]
        f["articulos"] += 1
        if r["resultado"] == "EVENTO":
            f["articulos_externos_evento"] += 1
    for r in conn.execute("SELECT jugador_id, categoria FROM news_evento WHERE creado_en>=? AND articulo_id IS NOT NULL "
                          "AND estado IN ('VIGENTE','EN_SEGUIMIENTO')", (desde,)):
        if r["categoria"] in _FUERTES:
            filas[circ_j.get(r["jugador_id"], "sin_circuito")]["noticias_utiles"] += 1
    for r in conn.execute("SELECT p.circuito, COUNT(DISTINCT e.partido_id) n, COUNT(*) ev FROM news_evaluacion e "
                          "JOIN news_partido p ON p.id=e.partido_id WHERE e.actualizado_en>=? GROUP BY p.circuito", (desde,)):
        f = filas[_circ(r["circuito"])]
        f["partidos_analizados"] += r["n"]
        f["evaluaciones"] += r["ev"]
    for r in conn.execute("SELECT a.tipo, COALESCE(p.circuito, j.circuito) circ FROM news_alerta a "
                          "LEFT JOIN news_partido p ON p.id=a.partido_id LEFT JOIN news_jugador j ON j.id=a.jugador_id "
                          "WHERE a.creado_en>=? AND COALESCE(a.prueba,0)=0", (desde,)):
        f = filas[_circ(r["circ"])]
        f["alertas"] += 1
        f["alertas_por_tipo"][r["tipo"]] = f["alertas_por_tipo"].get(r["tipo"], 0) + 1
    out = [f for f in filas.values() if any(v for k, v in f.items() if k not in ("circuito", "alertas_por_tipo"))]
    for f in out:
        f["cobertura_pct"] = round(100.0 * f["investigados"] / f["en_cola"], 1) if f["en_cola"] else None
    return {"dias": dias, "circuitos": out, "presupuesto": presupuesto(conn, cfg)}


def presupuesto(conn, cfg: dict) -> dict:
    """Búsquedas/día necesarias para atender la cola a su cadencia (idiomas × 24/cadencia)
    + radar temático, contra el tope. Propone un tope nuevo si no alcanza."""
    idiomas = [i.strip() for i in str(cfg.get("NEWS_IDIOMAS", "en,es")).split(",") if i.strip()]
    por_circ: dict = {}
    total = 0.0
    for r in conn.execute("SELECT c.situacion, COALESCE(c.circuito, j.circuito) circ, j.pais FROM news_jugador_cola c "
                          "JOIN news_jugador j ON j.id=c.jugador_id"):
        n_idiomas = len(jg.idiomas_para({"pais": r["pais"]}, idiomas))
        por_dia = n_idiomas * 24.0 / _CADENCIA_H.get(r["situacion"], 24 * 7)
        c = _circ(r["circ"])
        por_circ[c] = round(por_circ.get(c, 0.0) + por_dia, 1)
        total += por_dia
    tematico = 0
    if int(cfg.get("NEWS_RADAR_TEMATICO_ACTIVO", 1)):
        tematico = int(cfg.get("NEWS_RADAR_TEMATICO_BUSQUEDAS", 12)) * max(1, 24 // max(1, int(cfg.get("NEWS_RADAR_TEMATICO_CADA_H", 6))))
    necesario = int(round(total + tematico))
    tope = int(cfg.get("NEWS_MAX_BUSQUEDAS_DIA", 250))
    usd_busqueda = 0.008
    propuesto = tope
    if necesario > tope * 0.9:
        propuesto = int(((necesario * 1.2) // 50 + 1) * 50)         # 20 % de margen, redondeado a 50
    menores_pct = round(100.0 * sum(v for k, v in por_circ.items() if k in ("challenger", "wta125", "itf", "utr")) / total, 1) if total else None
    cupo = int(cfg.get("NEWS_RADAR_CUPO_MENORES_PCT", 40))
    # v5.2 (Rubén: "sin dejar fuera los circuitos pequeños"): si los menores necesitan más
    # búsquedas que el cupo que tienen reservado, se propone subir el cupo (tope 70 %).
    cupo_sugerido = cupo if menores_pct is None or menores_pct <= cupo else min(70, int(5 * round(menores_pct / 5)))
    return {"necesario_dia": necesario, "por_circuito": por_circ, "tematico_dia": tematico, "tope_actual": tope,
            "alcanza": necesario <= tope * 0.9, "tope_propuesto": propuesto,
            "usd_mes_con_propuesto": round(propuesto * usd_busqueda * 30, 2),
            "menores_pct_necesario": menores_pct, "cupo_menores_actual": cupo, "cupo_menores_sugerido": cupo_sugerido}
