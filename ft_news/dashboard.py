"""
ft_news/dashboard.py — Dashboard "estilo Historial de Picks" de FT NEWS
(08/10/2026 noche, Rubén: "que el panel salga el histórico y su dashboard de
ganadas y perdidas; solo las que llegan a Discord").

Un pick = la 🔥 que se DIJO en Discord (dicho_discord=1). Lado del pick: si
la noticia era NEGATIVA para X, el pick es el RIVAL a su cuota; si era
POSITIVA, es X a su cuota. Ganado/perdido por el resultado del Motor 5
(news_resultado.ganador_id). Mismas fórmulas que Picks de RankingFTR:
apuesta fija de 1 unidad, ganado = cuota − 1, perdido = −1, % de acierto
sobre decididas, ROI = Yield = unidades ÷ liquidadas. Sin probabilidades.
"""
from __future__ import annotations

GANADO, PERDIDO, PENDIENTE = "ganado", "perdido", "pendiente"
VISTAS = {"discord": "📣 Dichas en Discord"}


def _r(v, n=2):
    return None if v is None else round(v, n)


def _rachas(res: list[str]) -> tuple[int, int]:
    mg = mp = g = p = 0
    for r in res:
        if r == GANADO:
            g, p = g + 1, 0
        elif r == PERDIDO:
            p, g = p + 1, 0
        else:
            continue
        mg, mp = max(mg, g), max(mp, p)
    return mg, mp


def kpis(picks: list[dict], valor_unidad: float = 1.0) -> dict:
    res = [p["resultado"] for p in picks]
    g, pe, pend = res.count(GANADO), res.count(PERDIDO), res.count(PENDIENTE)
    liq = g + pe
    unidades, cuotas, cuotas_g = 0.0, [], []
    for p in picks:
        if p["resultado"] not in (GANADO, PERDIDO):
            continue
        c = p.get("cuota")
        unidades += (c - 1) if (p["resultado"] == GANADO and c) else (-1.0 if p["resultado"] == PERDIDO else 0.0)
        if c:
            cuotas.append(c)
            if p["resultado"] == GANADO:
                cuotas_g.append(c)
    rend = (unidades / liq * 100) if liq else None
    mg, mp = _rachas(res)
    return {"total": len(picks), "ganadas": g, "perdidas": pe, "push": 0, "pendientes": pend, "indeterminados": 0,
            "liquidadas": liq, "hit_rate": _r(g / liq * 100 if liq else None), "unidades": _r(unidades),
            "roi": _r(rend), "yield": _r(rend),
            "cuota_promedio": _r(sum(cuotas) / len(cuotas)) if cuotas else None,
            "cuota_promedio_ganadas": _r(sum(cuotas_g) / len(cuotas_g)) if cuotas_g else None,
            "racha_victorias": mg, "racha_derrotas": mp, "valor_unidad": _r(valor_unidad),
            "ganancia_dinero": _r(unidades * valor_unidad), "arriesgado_dinero": _r(liq * valor_unidad)}


def picks(conn, genero: str = "", limite: int = 500) -> list[dict]:
    where = ["e.tipo_alerta='FUEGO'", "e.dicho_discord=1"]
    args: list = []
    if genero:
        where.append("UPPER(SUBSTR(COALESCE(p.genero,''),1,1)) = ?")
        args.append(genero.strip().upper()[:1])
    out = []
    for r in conn.execute(
            "SELECT e.id, e.dicho_en, e.creado_en, e.direccion_neta, e.cuota_x, e.cuota_rival, e.nivel, e.conclusion, "
            "p.torneo, p.fecha_estimada, jx.nombre AS jx, jr.nombre AS jr, r.ganador_id, r.retiro, r.score, "
            "e.jugador_x_id, e.rival_id FROM news_evaluacion e JOIN news_partido p ON p.id=e.partido_id "
            "JOIN news_jugador jx ON jx.id=e.jugador_x_id JOIN news_jugador jr ON jr.id=e.rival_id "
            "LEFT JOIN news_resultado r ON r.evaluacion_id=e.id WHERE " + " AND ".join(where)
            + " ORDER BY COALESCE(e.dicho_en, e.creado_en) DESC", args).fetchall():
        contra_x = r["direccion_neta"] == "NEGATIVA"
        sel = r["jr"] if contra_x else r["jx"]
        sel_id = r["rival_id"] if contra_x else r["jugador_x_id"]
        cuota = r["cuota_rival"] if contra_x else r["cuota_x"]
        if r["ganador_id"] is None:
            res = PENDIENTE
        else:
            res = GANADO if r["ganador_id"] == sel_id else PERDIDO
        out.append({"id": r["id"], "fecha": r["dicho_en"] or r["creado_en"], "partido": f"{r['jx']} vs {r['jr']}",
                    "seleccion": sel, "etiqueta": "🔥", "torneo": r["torneo"], "cuota": cuota, "resultado": res,
                    "marcador": (r["score"] or "") + (" (ret.)" if r["retiro"] else ""),
                    # v7: en palabras (nada de "nivel B")
                    "detalle": (f"La noticia {'perjudica a' if contra_x else 'favorece a'} {r['jx']}"
                                f" · {({'A': 'hecho confirmado', 'B': 'fuente fiable', 'C': 'sin confirmar'}).get(r['nivel'] or '', 'evidencia s/d')}"),
                    "unidades": None if res == PENDIENTE else _r((cuota - 1) if (res == GANADO and cuota) else -1.0)})
    return out[:limite] if limite else out


def armar(conn, genero: str = "", valor_unidad: float = 1.0, limite: int = 500) -> dict:
    todos = picks(conn, genero, 0)
    return {"kpis": kpis(list(reversed(todos)), valor_unidad), "historial": todos[:limite],
            "truncado": len(todos) > limite, "vista": "discord", "vistas": VISTAS}
