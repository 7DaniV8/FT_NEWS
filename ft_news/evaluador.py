"""
ft_news/evaluador.py — Motor 4 aplicado (Fase 3): recorre los partidos en
ventana, junta los eventos activos de los dos jugadores, el UTR de cada
uno (padrón) y la cuota (fixtures) y llama al descubridor puro.

Una evaluación por partido (se actualiza en cada ciclo). Una 🔥 ya dicha en
Discord no se degrada: queda con su tipo y se anota el nuevo motivo en
`dicho_motivo` (la tab lo muestra).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from ft_news import descubridor, memoria, partidos, textos
from ft_news.db import ahora_iso, ejecutar_con_reintento


def _jugador(conn, jid: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM news_jugador WHERE id=?", (jid,)).fetchone()
    return dict(r) if r else None


def _fuego_hoy(conn, ahora: datetime) -> int:
    return conn.execute("SELECT COUNT(*) FROM news_evaluacion WHERE tipo_alerta='FUEGO' AND creado_en >= ?",
                        (ahora.date().isoformat(),)).fetchone()[0]


def _ya_avisado(conn, jugador_id: int, torneo: Optional[str], partido_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM news_evaluacion e JOIN news_partido p ON p.id = e.partido_id WHERE e.tipo_alerta='FUEGO' "
        "AND e.dicho_discord=1 AND e.jugador_x_id=? AND p.torneo=? AND e.partido_id<>?",
        (jugador_id, torneo, partido_id)).fetchone() is not None


def _dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s)[:19].replace(" ", "T"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def evaluar_partido(conn, cfg: dict, p: dict, ahora: datetime) -> Optional[dict]:
    # Un partido ya empezado no se vuelve a evaluar: la última evaluación
    # previa al inicio es la que vale (y la que el cierre va a medir).
    ini = _dt(p.get("fecha_estimada"))
    if ini and ini <= ahora and conn.execute("SELECT 1 FROM news_evaluacion WHERE partido_id=?", (p["id"],)).fetchone():
        return None
    j1, j2 = _jugador(conn, p["jugador1_id"]), _jugador(conn, p["jugador2_id"])
    if not j1 or not j2:
        return None
    h1, h2 = memoria.historial_db(conn, j1["id"]), memoria.historial_db(conn, j2["id"])
    e1, e2 = memoria.activos(h1, j1["id"], ahora), memoria.activos(h2, j2["id"], ahora)
    if not e1 and not e2:
        return None
    # X = el que tiene noticias; si los dos, el de más eventos fuertes
    x_es_1 = bool(e1) and (not e2 or len(e1) >= len(e2))
    jx, jr = (j1, j2) if x_es_1 else (j2, j1)
    ex, er = (e1, e2) if x_es_1 else (e2, e1)
    cuota_x, cuota_r = (p.get("cuota1"), p.get("cuota2")) if x_es_1 else (p.get("cuota2"), p.get("cuota1"))
    ap_x = p.get("cuota1_apertura") if x_es_1 else p.get("cuota2_apertura")
    prev = conn.execute("SELECT * FROM news_evaluacion WHERE partido_id=?", (p["id"],)).fetchone()
    r = descubridor.evaluar(
        cfg=cfg, ahora=ahora, eventos_x=ex, eventos_rival=er,
        identidad_x=min([e.get("confianza_identidad") or 1.0 for e in ex] or [1.0]),
        identidad_rival=min([e.get("confianza_identidad") or 1.0 for e in er] or [1.0]),
        utr_x=jx.get("utr_singles"), utr_rival=jr.get("utr_singles"), utr_x_en=jx.get("utr_en"),
        utr_rival_en=jr.get("utr_en"), cuota_x=cuota_x, cuota_rival=cuota_r,
        cuota_apertura_x=ap_x if ap_x and cuota_x and ap_x != cuota_x else None,
        inicio_partido=p.get("fecha_estimada"), fuego_hoy=_fuego_hoy(conn, ahora),
        ya_avisado=_ya_avisado(conn, jx["id"], p.get("torneo"), p["id"]))
    r.update(utr_x=jx.get("utr_singles"), utr_rival=jr.get("utr_singles"), cuota_x=cuota_x, cuota_rival=cuota_r)
    usados = [e for e in ex + er if e.get("id") in (r.get("eventos_usados") or [])] or ex or er
    try:
        t = textos.armar(r, p, {"nombre": jx["nombre"]}, {"nombre": jr["nombre"]}, usados)
    except ValueError as e:
        r.update(tipo_alerta="INTERESANTE", motivo="TEXTO_PROHIBIDO", conclusion=str(e))
        t = {"texto": "", "voz": ""}
    _guardar(conn, p, jx, jr, r, t, usados, prev, ahora)
    return r


def _guardar(conn, p, jx, jr, r, t, usados, prev, ahora) -> None:
    tipo = r["tipo_alerta"]
    dicho_motivo = None
    if prev and prev["tipo_alerta"] == "FUEGO" and prev["dicho_discord"] and tipo != "FUEGO":
        dicho_motivo = f"{tipo}:{r.get('motivo')}"
        tipo, motivo = "FUEGO", prev["motivo"]
    else:
        motivo = r.get("motivo")
    des = r.get("desvio") or {}
    vals = (p["id"], jx["id"], jr["id"], json.dumps([e.get("id") for e in usados]), r.get("utr_x"), r.get("utr_rival"),
            r.get("delta_utr"), jx.get("utr_en"), jr.get("utr_en"), r.get("cuota_x"), r.get("cuota_rival"),
            p.get("cuota_en"), r.get("banda_utr"), r.get("banda_mercado"), des.get("tipo"), r.get("direccion_neta"),
            r.get("nivel"), int(r.get("modo_evidencia") == "FUERTE"), r.get("conclusion"), tipo, motivo,
            t["texto"], t["voz"], int(r.get("bandas_calibradas") or 0), r.get("version_motor"), p.get("fixture_id"),
            dicho_motivo, ahora.isoformat())

    def _w():
        if prev:
            conn.execute(
                "UPDATE news_evaluacion SET partido_id=?, jugador_x_id=?, rival_id=?, eventos_json=?, utr_x=?, utr_rival=?, "
                "delta_utr=?, utr_x_en=?, utr_rival_en=?, cuota_x=?, cuota_rival=?, cuota_en=?, banda_utr=?, banda_mercado=?, "
                "desvio=?, direccion_neta=?, nivel=?, categoria_fuerte=?, conclusion=?, tipo_alerta=?, motivo=?, "
                "texto_discord=?, texto_voz=?, bandas_calibradas=?, version_motor=?, fixture_id=?, dicho_motivo=?, "
                "actualizado_en=? WHERE id=?", vals + (prev["id"],))
        else:
            conn.execute(
                "INSERT INTO news_evaluacion (partido_id, jugador_x_id, rival_id, eventos_json, utr_x, utr_rival, delta_utr, "
                "utr_x_en, utr_rival_en, cuota_x, cuota_rival, cuota_en, banda_utr, banda_mercado, desvio, direccion_neta, "
                "nivel, categoria_fuerte, conclusion, tipo_alerta, motivo, texto_discord, texto_voz, bandas_calibradas, "
                "version_motor, fixture_id, dicho_motivo, actualizado_en, creado_en) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", vals + (ahora_iso(),))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def correr(conn, cfg: dict, ahora: Optional[datetime] = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    res = {"partidos": 0, "evaluados": 0, "FUEGO": 0, "INTERESANTE": 0, "NADA": 0}
    for p in partidos.proximos(conn, ahora, int(cfg.get("NEWS_VENTANA_PARTIDO_HORAS", 72))):
        res["partidos"] += 1
        r = evaluar_partido(conn, cfg, p, ahora)
        if r is None:
            continue
        res["evaluados"] += 1
        res[r["tipo_alerta"]] = res.get(r["tipo_alerta"], 0) + 1
    return res


def senales(conn, cfg: dict, limite: int = 50) -> list[dict]:
    """Lo que viaja a FT Intelligence: 🔥 no dichas (y 🔎 si NEWS_DISCORD_INTERESANTE=1),
    solo con bandas calibradas para las 🔥."""
    tipos = ["FUEGO"]
    if cfg.get("NEWS_DISCORD_INTERESANTE"):
        tipos.append("INTERESANTE")
    q = ("SELECT e.*, p.torneo, p.fecha_estimada, p.genero, p.circuito, jx.nombre AS jugador_x, jr.nombre AS rival "
         "FROM news_evaluacion e JOIN news_partido p ON p.id=e.partido_id JOIN news_jugador jx ON jx.id=e.jugador_x_id "
         "JOIN news_jugador jr ON jr.id=e.rival_id WHERE e.dicho_discord=0 AND e.tipo_alerta IN (%s) "
         "AND (e.tipo_alerta<>'FUEGO' OR e.bandas_calibradas=1) AND e.texto_discord<>'' "
         "ORDER BY e.id LIMIT ?" % ",".join("?" * len(tipos)))
    return [dict(r) for r in conn.execute(q, (*tipos, limite)).fetchall()]


def marcar_dichas(conn, avisos: list[dict]) -> int:
    ahora = ahora_iso()

    def _w():
        n = 0
        for a in avisos:
            n += conn.execute("UPDATE news_evaluacion SET dicho_discord=?, dicho_en=?, dicho_motivo=COALESCE(?, dicho_motivo) "
                              "WHERE id=? AND dicho_discord=0",
                              (1 if a.get("dicho") else 2, a.get("en") or ahora, a.get("motivo"), a.get("id"))).rowcount
            # dicho_discord: 0 pendiente · 1 dicho · 2 omitido por FT Intelligence/Discord (motivo en dicho_motivo)
        conn.commit()
        return n
    return ejecutar_con_reintento(_w, conn=conn)
