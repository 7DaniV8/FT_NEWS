"""
ft_news/diagnostico_carga.py — v7 (10/10/2026, Rubén §7: "revisar las reglas
históricas antes de modificar los umbrales"). Solo lectura. Responde:

  · qué condiciones generaron eventos de carga (regla anterior vs v7);
  · cuántas evaluaciones se produjeron SOLO con estadística interna, y de qué tipo;
  · si los duplicados inflaron (misma condición repetida en una evaluación,
    o varios eventos vigentes de la misma categoría para un jugador);
  · qué resultados históricos respaldan la condición (el "cargado" ¿perdió?);
  · la distribución de partidos / sets / games / descanso guardada en
    news_contexto, y cómo caería cada muestra con los umbrales de HOY.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ft_news import contexto

_PCT = (10, 25, 50, 75, 90, 95, 99)


def _percentiles(vals: list) -> dict:
    v = sorted(float(x) for x in vals if x is not None)
    if not v:
        return {"n": 0}
    out = {"n": len(v), "min": v[0], "max": v[-1], "media": round(sum(v) / len(v), 2)}
    for p in _PCT:
        k = min(len(v) - 1, max(0, int(round(p / 100.0 * (len(v) - 1)))))
        out[f"p{p}"] = v[k]
    return out


def _histograma(vals: list, cortes: list) -> list:
    v = [float(x) for x in vals if x is not None]
    out = []
    for i, a in enumerate(cortes):
        b = cortes[i + 1] if i + 1 < len(cortes) else None
        n = sum(1 for x in v if x >= a and (b is None or x < b))
        et = f"{a:g}+" if b is None else (f"{a:g}" if b - a == 1 else f"{a:g}–{b:g}")
        out.append({"tramo": et, "n": n, "pct": round(100.0 * n / len(v), 1) if v else 0.0})
    return out


_CORTES = {"partidos_3d": [0, 1, 2, 3, 4], "partidos_7d": [0, 1, 2, 3, 4, 5, 6, 7], "partidos_14d": [0, 1, 2, 3, 4, 5, 6, 8],
           "sets_7d": [0, 2, 4, 6, 8, 10, 12, 15], "games_7d": [0, 20, 40, 60, 80, 100, 120], "tres_sets_7d": [0, 1, 2, 3, 4],
           "ultimo_hace_dias": [0, 1, 2, 3, 5, 7, 10, 14, 21, 30]}


def reglas(conn, cfg: dict, dias: int = 30) -> dict:
    ahora = datetime.now(timezone.utc)
    desde = (ahora - timedelta(days=dias)).isoformat()
    q = lambda sql, *a: [dict(r) for r in conn.execute(sql, a).fetchall()]  # noqa: E731
    # 1 · eventos de carga
    ev_carga = q("SELECT estado, direccion, COUNT(*) n FROM news_evento WHERE categoria='CARGA_FISICA' AND creado_en>=? "
                 "GROUP BY estado, direccion ORDER BY n DESC", desde)
    dup_vigentes = q("SELECT jugador_id, categoria, COUNT(*) n FROM news_evento WHERE fuente=? AND estado IN ('VIGENTE','EN_SEGUIMIENTO') "
                     "GROUP BY jugador_id, categoria HAVING n>1", contexto.FUENTE)
    dup_vencidos = conn.execute("SELECT COUNT(*) FROM news_evento_historial WHERE detalle LIKE 'duplicado de la misma condición%'").fetchone()[0]
    # 2 · evaluaciones: solo internas / con carga / carga repetida / resultados
    internos = {r["id"]: r for r in conn.execute(
        "SELECT id, jugador_id, categoria, direccion, articulo_id, fuente, enlace FROM news_evento").fetchall()}

    def es_ext(e) -> bool:
        return bool(e["articulo_id"]) or (str(e["fuente"] or "") != contexto.FUENTE and not str(e["enlace"] or "").startswith("contexto:"))
    evals = q("SELECT e.id, e.tipo_alerta, e.motivo, e.eventos_json, e.jugador_x_id, e.rival_id, e.dicho_discord, r.ganador_id, "
              "r.retiro FROM news_evaluacion e LEFT JOIN news_resultado r ON r.evaluacion_id=e.id WHERE e.creado_en>=?", desde)
    solo_internas, con_carga, repetida = {}, {}, 0
    res_cargado = {"gano": 0, "perdio": 0, "retiro": 0, "sin_resultado": 0}
    for e in evals:
        try:
            ids = [int(i) for i in json.loads(e["eventos_json"] or "[]") if i is not None]
        except (TypeError, ValueError):
            ids = []
        usados = [internos[i] for i in ids if i in internos]
        if not usados:
            continue
        tipo = e["tipo_alerta"]
        if not any(es_ext(u) for u in usados):
            solo_internas[tipo] = solo_internas.get(tipo, 0) + 1
        cargas = [u for u in usados if u["categoria"] == "CARGA_FISICA"]
        if cargas:
            con_carga[tipo] = con_carga.get(tipo, 0) + 1
            por_j = {}
            for c in cargas:
                por_j[c["jugador_id"]] = por_j.get(c["jugador_id"], 0) + 1
            if any(n > 1 for n in por_j.values()):
                repetida += 1
            # el "cargado" (evento negativo) ¿perdió?
            negs = [c for c in cargas if c["direccion"] == "NEGATIVA"]
            if negs:
                cargado = negs[0]["jugador_id"]
                if e["ganador_id"] is None:
                    res_cargado["sin_resultado"] += 1
                elif e["retiro"] and e["ganador_id"] != cargado:
                    res_cargado["retiro"] += 1
                elif e["ganador_id"] == cargado:
                    res_cargado["gano"] += 1
                else:
                    res_cargado["perdio"] += 1
    # 3 · distribución de lo guardado en news_contexto (CARGA)
    muestras = []
    for r in conn.execute("SELECT valor_json FROM news_contexto WHERE clave='CARGA' AND creado_en>=? ORDER BY id DESC LIMIT 20000", (desde,)).fetchall():
        try:
            c = json.loads(r["valor_json"] or "{}")
        except (TypeError, ValueError):
            continue
        c.setdefault("partidos_3d", 0)
        c.setdefault("partidos_historial", 1 if (c.get("partidos_7d") or c.get("partidos_14d") or c.get("ultimo_hace_dias") is not None) else 0)
        c["clase_hoy"] = contexto.clasificar_carga(c, cfg)
        c["clase_regla_anterior"] = "CARGA_FISICA" if (c.get("partidos_7d", 0) >= 4 or c.get("tres_sets_7d", 0) >= 3) else "nada"
        muestras.append(c)
    variables = {}
    for k in _CORTES:
        vals = [m.get(k) for m in muestras if m.get(k) is not None]
        variables[k] = {"percentiles": _percentiles(vals), "histograma": _histograma(vals, _CORTES[k])}
    clases_hoy = {c: 0 for c in contexto.CLASES_CARGA}
    anterior = {"CARGA_FISICA": 0, "nada": 0}
    for m in muestras:
        clases_hoy[m["clase_hoy"]] = clases_hoy.get(m["clase_hoy"], 0) + 1
        anterior[m["clase_regla_anterior"]] += 1
    n = max(len(muestras), 1)
    return {
        "dias": dias,
        "regla_anterior": {"condicion": "≥ 4 partidos en 7 días o ≥ 3 partidos a 3+ sets en 7 días → evento CARGA_FISICA NEGATIVA (fuerte), "
                                        "uno por fixture (duplicados si el mismo partido llegaba por varios fixtures)",
                           "habria_marcado": anterior["CARGA_FISICA"], "habria_marcado_pct": round(100.0 * anterior["CARGA_FISICA"] / n, 1),
                           "muestras": len(muestras)},
        "regla_v7": {"clases": {k: cfg.get(k) for k in ("NEWS_CARGA_CONSIDERABLE_PARTIDOS_7D", "NEWS_CARGA_CONSIDERABLE_TRES_SETS_7D",
                                                        "NEWS_CARGA_EXCEPCIONAL_PARTIDOS_7D",
                                                        "NEWS_CARGA_EXCEPCIONAL_TRES_SETS_7D", "NEWS_CARGA_INACTIVIDAD_DIAS")},
                     "muestras_por_clase": clases_hoy, "muestras_por_clase_pct": {c: round(100.0 * v / n, 1) for c, v in clases_hoy.items()},
                     "nota": "NORMAL / INACTIVIDAD / SIN_DATOS no dejan evento. CONSIDERABLE deja un evento MIXTO (seguimiento, se investiga). "
                             "EXCEPCIONAL deja un evento NEGATIVO. Un solo evento vigente por jugador. Ninguno decide una 🔥 solo."},
        "eventos_carga": ev_carga,
        "duplicados": {"jugadores_con_varios_vigentes": len(dup_vigentes), "vencidos_por_v7": dup_vencidos,
                       "evaluaciones_con_carga_repetida": repetida},
        "evaluaciones": {"total": len(evals), "solo_estadistica_interna": solo_internas, "con_carga": con_carga},
        "resultados_del_cargado": res_cargado,
        "distribucion": {"n": len(muestras), "variables": variables},
    }
