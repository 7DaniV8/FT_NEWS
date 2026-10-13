"""
ft_news/dashboard.py — Dashboard "estilo Historial de Picks" de FT NEWS
(08/10/2026 noche, Rubén: "que el panel salga el histórico y su dashboard de
ganadas y perdidas; solo las que llegan a Discord").

10/10/2026 (Rubén): el historial lista TODO lo dicho en Discord (📰 🔎 🔥 🔥 exp),
nunca se borra; las apuestas (KPI) son solo las 🔥. Un pick = la 🔥 que se DIJO en Discord (dicho_discord=1). Lado del pick: si
la noticia era NEGATIVA para X, el pick es el RIVAL a su cuota; si era
POSITIVA, es X a su cuota. Ganado/perdido por el resultado del Motor 5
(news_resultado.ganador_id). Mismas fórmulas que Picks de RankingFTR:
apuesta fija de 1 unidad, ganado = cuota − 1, perdido = −1, % de acierto
sobre decididas, ROI = Yield = unidades ÷ liquidadas. Sin probabilidades.
"""
from __future__ import annotations

import json
import re

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


SEGUIMIENTO = "seguimiento"
FUEGOS = ("FUEGO", "FUEGO_EXPERIMENTAL")
ETIQUETA = {"FUEGO": "🔥", "FUEGO_EXPERIMENTAL": "🔥 exp", "INTERESANTE": "🔎", "NOTICIA": "📰"}
_NIVEL = {"A": "hecho confirmado", "B": "fuente fiable", "C": "sin confirmar"}
_FAV = re.compile(r"🟢 (?:JUGADOR FAVORECIDO|PODRÍA FAVORECER A): ([^@\n]+?)(?: @([\d.,]+))?\s*$", re.MULTILINE)


def _favorecido(texto: str, jx: str, jr: str, cuota_x, cuota_r):
    """El favorecido que dice el mensaje (en MAYÚSCULAS) → nombre real y su cuota."""
    m = _FAV.search(texto or "")
    if not m:
        return None, None
    nombre = m.group(1).strip().casefold()
    for n, c in ((jx, cuota_x), (jr, cuota_r)):
        if n and n.casefold() == nombre:
            return n, c
    try:
        return m.group(1).strip().title(), float(m.group(2).replace(",", ".")) if m.group(2) else None
    except (TypeError, ValueError):
        return m.group(1).strip().title(), None


def picks(conn, genero: str = "", limite: int = 500) -> list[dict]:
    """10/10/2026 (Rubén: "las alertas enviadas nunca se borran de sus vistas"):
    TODO lo dicho en Discord (news_alerta.dicho_discord=1): 📰, 🔎, 🔥 y 🔥 exp,
    para siempre. Apuesta (ganado/perdido/unidades) solo las 🔥; 📰 y 🔎 quedan
    como 'seguimiento' con el resultado del partido si lo hay."""
    where = ["a.dicho_discord=1", "COALESCE(a.prueba,0)=0"]          # v7.2: las PRUEBA nunca cuentan
    args: list = []
    if genero:
        where.append("UPPER(SUBSTR(COALESCE(p.genero,''),1,1)) = ?")
        args.append(genero.strip().upper()[:1])
    out, vistos = [], set()
    for a in conn.execute(
            "SELECT a.id, a.tipo, a.dicho_en, a.creado_en, a.texto_discord, a.evidencia_json, a.evaluacion_id, a.jugador_id, a.rival_id, "
            "jx.nombre AS jx, jr.nombre AS jr, p.torneo, p.fecha_estimada, p.genero, e.motivo, e.cuota_x, e.cuota_rival, e.nivel, "
            "e.direccion_neta, e.jugador_x_id, e.rival_id AS e_rival_id, e.lectura_json, r.ganador_id, r.retiro, r.score "
            "FROM news_alerta a LEFT JOIN news_jugador jx ON jx.id=a.jugador_id LEFT JOIN news_jugador jr ON jr.id=a.rival_id "
            "LEFT JOIN news_partido p ON p.id=a.partido_id LEFT JOIN news_evaluacion e ON e.id=a.evaluacion_id "
            "LEFT JOIN news_resultado r ON r.evaluacion_id=a.evaluacion_id WHERE " + " AND ".join(where)
            + " ORDER BY COALESCE(a.dicho_en, a.creado_en) DESC", args).fetchall():
        jx, jr = a["jx"] or "?", a["jr"]
        # cuotas del lado de la alerta (la evaluación puede tener X = el rival de la alerta)
        cx, cr = a["cuota_x"], a["cuota_rival"]
        if a["jugador_x_id"] is not None and a["jugador_x_id"] == a["rival_id"]:
            cx, cr = cr, cx
        try:
            ev = json.loads(a["evidencia_json"] or "{}")
        except (TypeError, ValueError):
            ev = {}
        if cx is None and isinstance(ev.get("cuotas"), dict):
            cx, cr = ev["cuotas"].get("x"), ev["cuotas"].get("rival")
        sel, cuota = _favorecido(a["texto_discord"], jx, jr, cx, cr)
        es_fuego = a["tipo"] in FUEGOS
        if es_fuego and not sel and a["evaluacion_id"]:
            contra = a["motivo"] == "CONTRA_X" or a["direccion_neta"] == "NEGATIVA"
            sel = (jr if contra else jx) if a["jugador_x_id"] == a["jugador_id"] else (jx if contra else jr)
            cuota = cr if sel == jr else cx
        sel_id = a["rival_id"] if sel == jr else a["jugador_id"] if sel == jx else None
        if not es_fuego:
            res = SEGUIMIENTO
        elif a["ganador_id"] is None or sel_id is None:
            res = PENDIENTE
        else:
            res = GANADO if a["ganador_id"] == sel_id else PERDIDO
        marcador = ""
        if a["ganador_id"] is not None:
            gan = jx if a["ganador_id"] == a["jugador_id"] else jr if a["ganador_id"] == a["rival_id"] else ""
            marcador = (f"ganó {gan} " if gan else "") + (a["score"] or "") + (" (ret.)" if a["retiro"] else "")
        try:
            lectura = json.loads(a["lectura_json"] or "{}")
        except (TypeError, ValueError):
            lectura = {}
        detalle = lectura.get("resumen") or ((a["texto_discord"] or "").split("\n")[1:2] or [""])[0]
        out.append({"id": a["id"], "evaluacion_id": a["evaluacion_id"], "fecha": a["dicho_en"] or a["creado_en"],
                    "partido": f"{jx} vs {jr}" if jr else jx, "seleccion": sel, "etiqueta": ETIQUETA.get(a["tipo"], a["tipo"]),
                    "tipo": a["tipo"], "torneo": a["torneo"], "cuota": cuota, "resultado": res, "marcador": marcador,
                    "detalle": detalle,
                    "unidades": None if res in (PENDIENTE, SEGUIMIENTO) else _r((cuota - 1) if (res == GANADO and cuota) else -1.0)})
        if a["evaluacion_id"]:
            vistos.add(a["evaluacion_id"])
    # Compatibilidad: 🔥 dichas antes de que existiera news_alerta (solo la marca en la evaluación)
    for r in conn.execute(
            "SELECT e.id, e.dicho_en, e.creado_en, e.direccion_neta, e.cuota_x, e.cuota_rival, e.nivel, e.tipo_alerta, "
            "p.torneo, p.genero, jx.nombre AS jx, jr.nombre AS jr, r.ganador_id, r.retiro, r.score, e.jugador_x_id, e.rival_id "
            "FROM news_evaluacion e JOIN news_partido p ON p.id=e.partido_id JOIN news_jugador jx ON jx.id=e.jugador_x_id "
            "JOIN news_jugador jr ON jr.id=e.rival_id LEFT JOIN news_resultado r ON r.evaluacion_id=e.id "
            "WHERE e.dicho_discord=1 AND e.tipo_alerta IN ('FUEGO','FUEGO_EXPERIMENTAL')"
            + (" AND UPPER(SUBSTR(COALESCE(p.genero,''),1,1)) = ?" if genero else ""), args).fetchall():
        if r["id"] in vistos:
            continue
        contra_x = r["direccion_neta"] == "NEGATIVA"
        sel, sel_id = (r["jr"], r["rival_id"]) if contra_x else (r["jx"], r["jugador_x_id"])
        cuota = r["cuota_rival"] if contra_x else r["cuota_x"]
        res = PENDIENTE if r["ganador_id"] is None else (GANADO if r["ganador_id"] == sel_id else PERDIDO)
        out.append({"id": -r["id"], "evaluacion_id": r["id"], "fecha": r["dicho_en"] or r["creado_en"], "partido": f"{r['jx']} vs {r['jr']}",
                    "seleccion": sel, "etiqueta": ETIQUETA.get(r["tipo_alerta"], "🔥"), "tipo": r["tipo_alerta"], "torneo": r["torneo"],
                    "cuota": cuota, "resultado": res, "marcador": (r["score"] or "") + (" (ret.)" if r["retiro"] else ""),
                    "detalle": (f"La noticia {'perjudica a' if contra_x else 'favorece a'} {r['jx']} · {_NIVEL.get(r['nivel'] or '', 'evidencia s/d')}"),
                    "unidades": None if res == PENDIENTE else _r((cuota - 1) if (res == GANADO and cuota) else -1.0)})
    out.sort(key=lambda x: x["fecha"] or "", reverse=True)
    return out[:limite] if limite else out


def armar(conn, genero: str = "", valor_unidad: float = 1.0, limite: int = 500) -> dict:
    todos = picks(conn, genero, 0)
    apuestas = [p for p in todos if p["tipo"] in FUEGOS]          # los KPI son de apuestas (🔥); 📰/🔎 solo se listan
    k = kpis(list(reversed(apuestas)), valor_unidad)
    k["seguimiento"] = len(todos) - len(apuestas)
    k["alertas_dichas"] = len(todos)
    return {"kpis": k, "historial": todos[:limite], "truncado": len(todos) > limite, "vista": "discord", "vistas": VISTAS}
