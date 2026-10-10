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

from ft_news import alertas, descubridor, memoria, partidos, textos
from ft_news.db import ahora_iso, ejecutar_con_reintento


def _jugador(conn, jid: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM news_jugador WHERE id=?", (jid,)).fetchone()
    return dict(r) if r else None


FUEGOS = ("FUEGO", "FUEGO_EXPERIMENTAL")


def _fuego_hoy(conn, ahora: datetime) -> int:
    return conn.execute("SELECT COUNT(*) FROM news_evaluacion WHERE tipo_alerta IN ('FUEGO','FUEGO_EXPERIMENTAL') "
                        "AND creado_en >= ?", (ahora.date().isoformat(),)).fetchone()[0]


def _ya_avisado(conn, jugador_id: int, torneo: Optional[str], partido_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM news_evaluacion e JOIN news_partido p ON p.id = e.partido_id "
        "WHERE e.tipo_alerta IN ('FUEGO','FUEGO_EXPERIMENTAL') "
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
    # v5.1: una 🔥 (experimental o validada) tiene que poder decir qué información
    # podría no estar en la cuota, qué hay en contra y por qué merece la alerta;
    # si no alcanza, queda como 🔎 (Rubén, 09/10 noche).
    if r["tipo_alerta"] in FUEGOS:
        try:
            j = alertas.justificar(conn, cfg, r, p, jx, jr, ex, er, ahora)
        except Exception as e:                       # pragma: no cover
            j = {"suficiente": False, "motivo": f"error: {e}", "no_reflejado": [], "a_favor": [], "en_contra": [], "sin_fresca": []}
        r["justificacion"] = j
        if not j["suficiente"] and (r["tipo_alerta"] == "FUEGO_EXPERIMENTAL" or j.get("sin_fresca")):
            if j.get("cuota_pendiente") and not j.get("sin_fresca") and j["motivo"] != "RETIRO_MISMO_TORNEO":
                r["conclusion"] = (f"Noticia externa; 🔥 pendiente de actualización de cuota: falta {j['cuota_pendiente']}. "
                                   f"Se reevalúa cuando llegue un precio confirmado después de la noticia.")
            else:
                r["conclusion"] = (f"Noticia externa, pero no alcanza para 🔥 ({j['motivo'].split(':')[0].replace('_', ' ').lower()})"
                                   + (f": {'; '.join(j['en_contra'])}" if j.get("en_contra") else "") + ".")
            r.update(tipo_alerta="INTERESANTE", motivo=j["motivo"].split(":")[0])
            for n in j.get("sin_fresca") or []:
                jid = jx["id"] if n == jx["nombre"] else jr["id"]
                alertas.adelantar(conn, jid, ahora)
    usados = [e for e in ex + er if e.get("id") in (r.get("eventos_usados") or [])] or ex or er
    try:
        t = textos.armar(r, p, jx, jr, usados)
    except ValueError as e:
        r.update(tipo_alerta="INTERESANTE", motivo="TEXTO_PROHIBIDO", conclusion=str(e))
        t = {"texto": "", "voz": ""}
    eid = _guardar(conn, p, jx, jr, r, t, usados, prev, ahora)
    # v5: lo que va a Discord lo decide alertas.py (selección, dedupe, topes, motivo).
    try:
        if r["tipo_alerta"] in FUEGOS:
            r["alerta"] = alertas.fuego(conn, cfg, r, p, jx, jr, usados, eid, t["texto"], t["voz"], ahora)
        elif r["tipo_alerta"] == "INTERESANTE":
            r["alerta"] = alertas.partido_interesante(conn, cfg, r, p, jx, jr, ex, er, eid, ahora)
    except Exception as e:                           # la alerta nunca tumba la evaluación
        r["alerta"] = {"alerta_id": None, "motivo": f"error: {e}"}
    return r


def _guardar(conn, p, jx, jr, r, t, usados, prev, ahora) -> Optional[int]:
    tipo = r["tipo_alerta"]
    dicho_motivo = None
    # Una 🔥 ya dicha no se degrada (validada → experimental tampoco); experimental → validada sí sube.
    rango = {"FUEGO": 2, "FUEGO_EXPERIMENTAL": 1}
    if prev and prev["tipo_alerta"] in FUEGOS and prev["dicho_discord"] == 1 and rango.get(tipo, 0) < rango[prev["tipo_alerta"]]:
        dicho_motivo = f"{tipo}:{r.get('motivo')}"
        tipo, motivo = prev["tipo_alerta"], prev["motivo"]
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
        return prev["id"] if prev else conn.execute("SELECT id FROM news_evaluacion WHERE partido_id=?", (p["id"],)).fetchone()[0]
    return ejecutar_con_reintento(_w, conn=conn)


def correr(conn, cfg: dict, ahora: Optional[datetime] = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    res = {"partidos": 0, "evaluados": 0, "FUEGO": 0, "FUEGO_EXPERIMENTAL": 0, "INTERESANTE": 0, "NADA": 0, "alertas": 0}
    for p in partidos.proximos(conn, ahora, int(cfg.get("NEWS_VENTANA_PARTIDO_HORAS", 72))):
        res["partidos"] += 1
        r = evaluar_partido(conn, cfg, p, ahora)
        if r is None:
            continue
        res["evaluados"] += 1
        res[r["tipo_alerta"]] = res.get(r["tipo_alerta"], 0) + 1
        if (r.get("alerta") or {}).get("alerta_id"):
            res["alertas"] += 1
    return res


def senales(conn, cfg: dict, limite: int = 50) -> list[dict]:
    """Lo que viaja a FT Intelligence (v5): las alertas seleccionadas en
    news_alerta (📰, 🔎, 🔥 validada, 🔥 experimental), no dichas."""
    return alertas.pendientes(conn, cfg, limite)


def marcar_dichas(conn, avisos: list[dict]) -> int:
    """dicho_discord: 0 pendiente · 1 dicho · 2 omitido por FT Intelligence/Discord."""
    return alertas.marcar_dichas(conn, avisos)
