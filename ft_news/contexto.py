"""
ft_news/contexto.py — Motor 3: contexto del torneo y del jugador, SIN IA
(segunda entrega, 08/10/2026). Todo sale de datos propios de RankingFTR:

  carga        partidos y sets de los últimos 7/14 días, último partido hace N
               días (match_log por ventana). Sin duración: nunca se estima.
  viaje        país del último partido vs país del torneo que viene (ftr_torneos.pais).
  localia      país del jugador (padrón UTR) == país del torneo.
  antecedentes partidos del jugador en ediciones anteriores del mismo torneo.
  defensa      snapshot semanal de Defensa de Puntos (puntos que vencen, presión).

Cada dato se guarda en news_contexto con su fuente y la marca `estimado`, y
cuando cruza un umbral se convierte en un EVENTO de la memoria (nivel A =
dato propio, fuente 'rankingftr.interno', enlace 'contexto:<partido_id>'),
una sola vez por jugador, partido y categoría. Umbrales fijos y declarados:
no hay probabilidades ni pesos.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import jugadores as jg
from ft_news import memoria
from ft_news.db import ahora_iso, ejecutar_con_reintento

FUENTE = "rankingftr.interno"
# v7 (10/10/2026, Rubén: "3 partidos y 9 sets en 7 días es normal"): la carga se
# CLASIFICA (NORMAL / CONSIDERABLE / EXCEPCIONAL / INACTIVIDAD / SIN_DATOS) con
# umbrales provisorios de config; solo CONSIDERABLE y EXCEPCIONAL dejan un
# evento, uno solo vigente por jugador, y ninguno decide una 🔥 por sí solo.
CLASES_CARGA = ("SIN_DATOS", "INACTIVIDAD", "NORMAL", "CONSIDERABLE", "EXCEPCIONAL")
VERSION_CARGA = "carga-news-v7-20261010"
UMBRAL_VIAJE_DIAS = 3            # cambió de país con ≤ 3 días entre partidos → VIAJE_CALENDARIO
UMBRAL_ANTECEDENTES_MIN = 5      # mínimo de partidos en el torneo para opinar
UMBRAL_ANTECEDENTE_BUENO = 0.70
UMBRAL_ANTECEDENTE_MALO = 0.30
UMBRAL_PRESION_DEFENSA = 0.12    # defense_percentage ≥ 12 % → PUNTOS_DEFENDIDOS (mixta)


def _dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s)[:19].replace(" ", "T"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _sets(score: str) -> int:
    return len([p for p in re.split(r"[\s,]+", score or "") if re.match(r"^\d+-\d+", p)])


def _retiro(score: str) -> bool:
    s = (score or "").lower()
    return "ret" in s or "w/o" in s or "w.o" in s or "walkover" in s or "def" in s


# ── lectura del historial por jugador ────────────────────────────────────
def indexar_historial(filas: list[dict]) -> dict:
    """{nombre_norm: [partidos del jugador, ordenados por fecha]} con ambas caras."""
    idx: dict[str, list] = {}
    for f in filas:
        for yo, otro, gano in ((f.get("jugador"), f.get("rival"), True), (f.get("rival"), f.get("jugador"), False)):
            if not yo:
                continue
            idx.setdefault(jg.normalizar(yo), []).append({
                "fecha": f.get("fecha"), "torneo": f.get("torneo"), "pais_torneo": f.get("pais_torneo"),
                "rival": otro, "gano": gano, "score": f.get("score"), "sets": _sets(f.get("score")),
                "retiro": _retiro(f.get("score")), "superficie": f.get("superficie"), "player_id": f.get("player_id") if gano else f.get("opponent_id")})
    for v in idx.values():
        v.sort(key=lambda x: x["fecha"] or "")
    return idx


def _games(score: str) -> int:
    """'6-4 3-6 7-6(5)' → 32 games. Sin estimar nada: lo que dice el marcador."""
    n = 0
    for p in re.split(r"[\s,]+", score or ""):
        m = re.match(r"^(\d+)-(\d+)", p)
        if m:
            n += int(m.group(1)) + int(m.group(2))
    return n


def carga(partidos: list[dict], ahora: datetime) -> dict:
    """Hechos de los últimos 3/7/14 días (sin duración: nunca se estima)."""
    d3 = [p for p in partidos if _dt(p["fecha"]) and _dt(p["fecha"]) >= ahora - timedelta(days=3)]
    d7 = [p for p in partidos if _dt(p["fecha"]) and _dt(p["fecha"]) >= ahora - timedelta(days=7)]
    d14 = [p for p in partidos if _dt(p["fecha"]) and _dt(p["fecha"]) >= ahora - timedelta(days=14)]
    ultimo = partidos[-1] if partidos else None
    hace = (ahora - _dt(ultimo["fecha"])).days if ultimo and _dt(ultimo["fecha"]) else None
    dias3: dict = {}
    for p in d3:
        dias3[str(p["fecha"])[:10]] = dias3.get(str(p["fecha"])[:10], 0) + 1
    return {"partidos_3d": len(d3), "partidos_7d": len(d7), "partidos_14d": len(d14),
            "tres_sets_7d": sum(1 for p in d7 if p["sets"] >= 3), "sets_7d": sum(p["sets"] for p in d7),
            "games_7d": sum(_games(p.get("score")) for p in d7), "doble_jornada": int(any(v >= 2 for v in dias3.values())),
            "ultimo_hace_dias": hace, "ultimo_tres_sets": bool(ultimo and ultimo["sets"] >= 3),
            "ultimo_retiro": bool(ultimo and ultimo.get("retiro")), "partidos_historial": len(partidos),
            "duracion": None, "version": VERSION_CARGA}


def clasificar_carga(c: dict, cfg: dict) -> str:
    """PUERTA 1 (misma filosofía que Cuota Mal Puesta V3): clase por la carga
    ABSOLUTA del jugador. Umbrales provisorios de config."""
    g = lambda k, d: int(cfg.get(k, d) or d)  # noqa: E731
    if not c.get("partidos_historial"):
        return "SIN_DATOS"
    hace = c.get("ultimo_hace_dias")
    if hace is None or hace >= g("NEWS_CARGA_INACTIVIDAD_DIAS", 10):
        return "INACTIVIDAD"
    if c["partidos_7d"] >= g("NEWS_CARGA_EXCEPCIONAL_PARTIDOS_7D", 6) or c["tres_sets_7d"] >= g("NEWS_CARGA_EXCEPCIONAL_TRES_SETS_7D", 5):
        return "EXCEPCIONAL"
    # 3 partidos en 3 días es el camino normal de un cuadro (una ronda por día): no cuenta solo.
    if (c["partidos_7d"] >= g("NEWS_CARGA_CONSIDERABLE_PARTIDOS_7D", 5) or c["tres_sets_7d"] >= g("NEWS_CARGA_CONSIDERABLE_TRES_SETS_7D", 4)
            or c.get("doble_jornada")):
        return "CONSIDERABLE"
    return "NORMAL"


def describir_carga(c: dict, nombre: str) -> str:
    """🟡 CARGA FÍSICA en una frase para el usuario (sin códigos)."""
    clase = c.get("clase") or "SIN_DATOS"
    if clase == "SIN_DATOS":
        return f"Sin partidos recientes registrados de {nombre}: no se puede medir su carga."
    if clase == "INACTIVIDAD":
        return f"{nombre} lleva {c.get('ultimo_hace_dias')} días sin competir. Llega descansado, pero puede faltarle ritmo."
    hechos = f"{nombre} disputó {c['partidos_7d']} partido(s) y {c['sets_7d']} sets en 7 días"
    extras = []
    if c.get("tres_sets_7d"):
        extras.append(f"{c['tres_sets_7d']} a tres sets")
    if c.get("partidos_3d", 0) >= 3:
        extras.append(f"{c['partidos_3d']} en los últimos 3 días")
    if c.get("doble_jornada"):
        extras.append("doble jornada")
    if c.get("ultimo_retiro"):
        extras.append("se retiró en su último partido")
    if extras:
        hechos += " (" + ", ".join(extras) + ")"
    if clase == "NORMAL":
        return hechos + ". No hay evidencia suficiente para considerarlo fatigado."
    if clase == "CONSIDERABLE":
        return hechos + ". Es una carga considerable: se investiga si hay molestias, pero por sí sola no lo perjudica."
    return hechos + ". Es una carga excepcional para una semana: podría pesar en el partido; se investiga."


def viaje(partidos: list[dict], pais_torneo: Optional[str], fecha_partido: Optional[datetime]) -> dict:
    ultimo = partidos[-1] if partidos else None
    if not ultimo or not pais_torneo or not ultimo.get("pais_torneo") or not fecha_partido or not _dt(ultimo["fecha"]):
        return {"cambio_pais": None, "dias_entre": None, "desde": (ultimo or {}).get("pais_torneo"), "hacia": pais_torneo}
    dias = (fecha_partido - _dt(ultimo["fecha"])).days
    return {"cambio_pais": ultimo["pais_torneo"] != pais_torneo, "dias_entre": dias, "desde": ultimo["pais_torneo"],
            "hacia": pais_torneo}


def antecedentes(filas: list[dict]) -> dict:
    n = len(filas)
    g = sum(1 for f in filas if (f.get("games_ganados") or 0) >= (f.get("games_perdidos") or 0))
    return {"partidos": n, "ganados": g, "frecuencia": round(g / n, 2) if n else None}


# ── conversión a eventos ─────────────────────────────────────────────────
def _guardar_contexto(conn, jugador_id: int, partido_id: int, clave: str, valor: dict, estimado: bool, fuente: str) -> None:
    def _w():
        conn.execute("INSERT INTO news_contexto (jugador_id, partido_id, clave, valor_json, estimado, fuente, creado_en) "
                     "VALUES (?,?,?,?,?,?,?) ON CONFLICT(jugador_id, partido_id, clave) DO UPDATE SET "
                     "valor_json=excluded.valor_json, estimado=excluded.estimado, creado_en=excluded.creado_en",
                     (jugador_id, partido_id, clave, json.dumps(valor, ensure_ascii=False), int(estimado), fuente, ahora_iso()))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def _vigente_interno(conn, jugador_id: int, categoria: str):
    """El evento calculado (origen interno) VIGENTE de esa categoría para el
    jugador, si hay. v7: uno solo por jugador y categoría (no uno por partido)."""
    return conn.execute(
        "SELECT id, enlace, resumen_es, direccion FROM news_evento WHERE jugador_id=? AND categoria=? AND fuente=? "
        "AND estado IN ('VIGENTE','EN_SEGUIMIENTO') ORDER BY id DESC LIMIT 1", (jugador_id, categoria, FUENTE)).fetchone()


def _evento_contexto(conn, jugador_id: int, partido_id: int, categoria: str, direccion: str, resumen: str,
                     fecha: datetime, estimado: bool = False) -> Optional[int]:
    enlace = f"contexto:{partido_id}"
    if conn.execute("SELECT 1 FROM news_evento WHERE jugador_id=? AND categoria=? AND enlace=?",
                    (jugador_id, categoria, enlace)).fetchone():
        return None
    # v7 (Rubén: "una misma condición no se muestra cuatro veces"): si ya hay uno
    # VIGENTE de la misma categoría calculada (otro fixture del mismo partido, la
    # ronda siguiente), se actualiza ese en vez de crear otro.
    prev = _vigente_interno(conn, jugador_id, categoria)
    if prev:
        texto = resumen + (" (estimado)" if estimado else "")
        if prev["resumen_es"] != texto or prev["direccion"] != direccion:
            def _u():
                conn.execute("UPDATE news_evento SET resumen_es=?, direccion=?, enlace=?, actualizado_en=? WHERE id=?",
                             (texto, direccion, enlace, ahora_iso(), prev["id"]))
                memoria.anotar_historial(conn, prev["id"], "ACTUALIZADO", f"recalculado para el partido {partido_id}: {texto[:200]}")
                conn.commit()
            ejecutar_con_reintento(_u, conn=conn)
        return None
    ev = memoria.nuevo_evento(jugador_id, categoria, direccion, "HECHO", "A", fecha.isoformat(), fuente=FUENTE,
                              enlace=enlace, resumen_es=resumen + (" (estimado)" if estimado else ""),
                              relevancia_deportiva="contexto calculado, no es una noticia", confianza_identidad=1.0)
    return memoria.guardar_evento_db(conn, ev)


def _vencer_interno(conn, jugador_id: int, categoria: str, detalle: str) -> int:
    """Vence TODOS los eventos calculados vigentes de esa categoría (p. ej. la
    carga volvió a NORMAL, o quedaron duplicados de versiones anteriores)."""
    n = 0
    for f in conn.execute("SELECT id FROM news_evento WHERE jugador_id=? AND categoria=? AND fuente=? "
                          "AND estado IN ('VIGENTE','EN_SEGUIMIENTO')", (jugador_id, categoria, FUENTE)).fetchall():
        if memoria.cambiar_estado_db(conn, f["id"], "VENCIDO", detalle):
            n += 1
    return n


def dedupe_internos(conn) -> int:
    """v7, una vez por ciclo: si un jugador tiene más de un evento calculado
    VIGENTE de la misma categoría (versiones anteriores creaban uno por fixture),
    queda el más nuevo y el resto vence. Devuelve cuántos venció."""
    n = 0
    filas = conn.execute("SELECT jugador_id, categoria, COUNT(*) c, MAX(id) ultimo FROM news_evento WHERE fuente=? "
                         "AND estado IN ('VIGENTE','EN_SEGUIMIENTO') GROUP BY jugador_id, categoria HAVING c > 1", (FUENTE,)).fetchall()
    for f in filas:
        for e in conn.execute("SELECT id FROM news_evento WHERE jugador_id=? AND categoria=? AND fuente=? AND id<>? "
                              "AND estado IN ('VIGENTE','EN_SEGUIMIENTO')", (f["jugador_id"], f["categoria"], FUENTE, f["ultimo"])).fetchall():
            if memoria.cambiar_estado_db(conn, e["id"], "VENCIDO", "duplicado de la misma condición calculada (v7)"):
                n += 1
    return n


def evaluar_jugador(conn, j: dict, p: dict, hist: dict, defensa_idx: dict, cliente, ahora: datetime,
                    paises_torneo: dict, cfg: Optional[dict] = None) -> dict:
    """Motor 3 para un jugador en un partido. Devuelve lo calculado y los eventos creados."""
    out = {"eventos": []}
    partidos = hist.get(j["nombre_norm"], [])
    fecha_p = _dt(p.get("fecha_estimada"))
    # carga (v7: por clases; NORMAL / INACTIVIDAD / SIN_DATOS no dejan evento)
    c = carga(partidos, ahora)
    c["clase"] = clasificar_carga(c, cfg or {})
    c["texto"] = describir_carga(c, j.get("nombre") or "El jugador")
    _guardar_contexto(conn, j["id"], p["id"], "CARGA", c, False, FUENTE)
    out["carga"] = c
    if c["clase"] in ("CONSIDERABLE", "EXCEPCIONAL"):
        resumen = (f"{c['partidos_7d']} partidos y {c['sets_7d']} sets en 7 días"
                   + (f", {c['tres_sets_7d']} a tres sets" if c.get("tres_sets_7d") else "")
                   + (f", {c['partidos_3d']} en 3 días" if c.get("partidos_3d", 0) >= 2 else "")
                   + (", doble jornada" if c.get("doble_jornada") else "")
                   + f"; último hace {c['ultimo_hace_dias']} día(s) · carga {c['clase'].lower()}")
        # CONSIDERABLE = seguimiento (dirección MIXTA: no empuja la lectura); EXCEPCIONAL = negativa.
        eid = _evento_contexto(conn, j["id"], p["id"], "CARGA_FISICA", "NEGATIVA" if c["clase"] == "EXCEPCIONAL" else "MIXTA",
                               resumen, ahora)
        if eid:
            out["eventos"].append(("CARGA_FISICA", eid))
        # se investiga (Rubén: "una carga verdaderamente excepcional sí pueda ser investigada")
        try:
            from ft_news import alertas as _al
            _al.adelantar(conn, j["id"], ahora, motivo=f"CARGA_{c['clase']}")
        except Exception:
            pass
    else:
        _vencer_interno(conn, j["id"], "CARGA_FISICA", f"la carga volvió a {c['clase'].lower()} (v7)")
    # viaje
    pais_t = paises_torneo.get(jg.normalizar(p.get("torneo") or ""))
    v = viaje(partidos, pais_t, fecha_p)
    _guardar_contexto(conn, j["id"], p["id"], "VIAJE", v, False, FUENTE)
    if v["cambio_pais"] and v["dias_entre"] is not None and 0 <= v["dias_entre"] <= UMBRAL_VIAJE_DIAS:
        eid = _evento_contexto(conn, j["id"], p["id"], "VIAJE_CALENDARIO", "NEGATIVA",
                               f"viene de jugar en {v['desde']} hace {v['dias_entre']} día(s); ahora en {v['hacia']}", ahora)
        if eid:
            out["eventos"].append(("VIAJE_CALENDARIO", eid))
    # localía
    if pais_t and j.get("pais") and _mismo_pais(j["pais"], pais_t):
        _guardar_contexto(conn, j["id"], p["id"], "LOCALIA", {"pais": pais_t}, False, FUENTE)
        eid = _evento_contexto(conn, j["id"], p["id"], "LOCALIA", "POSITIVA", f"juega en su país ({pais_t})", ahora)
        if eid:
            out["eventos"].append(("LOCALIA", eid))
    # antecedentes (una llamada a RankingFTR por jugador y partido, cacheada en news_contexto)
    pid = j.get("player_id_ftr")
    if pid and p.get("torneo") and not conn.execute(
            "SELECT 1 FROM news_contexto WHERE jugador_id=? AND partido_id=? AND clave='ANTECEDENTE'", (j["id"], p["id"])).fetchone():
        try:
            a = antecedentes((cliente.antecedentes(pid, p["torneo"]) or {}).get("partidos") or [])
        except Exception as e:
            a = {"error": str(e)}
        _guardar_contexto(conn, j["id"], p["id"], "ANTECEDENTE", a, False, FUENTE)
        if a.get("partidos", 0) >= UMBRAL_ANTECEDENTES_MIN:
            if a["frecuencia"] >= UMBRAL_ANTECEDENTE_BUENO:
                eid = _evento_contexto(conn, j["id"], p["id"], "ANTECEDENTE_TORNEO", "POSITIVA",
                                       f"{a['ganados']}/{a['partidos']} ganados en ediciones anteriores de {p['torneo']}", ahora)
            elif a["frecuencia"] <= UMBRAL_ANTECEDENTE_MALO:
                eid = _evento_contexto(conn, j["id"], p["id"], "ANTECEDENTE_TORNEO", "NEGATIVA",
                                       f"{a['ganados']}/{a['partidos']} ganados en ediciones anteriores de {p['torneo']}", ahora)
            else:
                eid = None
            if eid:
                out["eventos"].append(("ANTECEDENTE_TORNEO", eid))
    # defensa de puntos (snapshot semanal; marcado estimado)
    d = defensa_idx.get(j["nombre_norm"])
    if d:
        _guardar_contexto(conn, j["id"], p["id"], "PUNTOS_DEFENDIDOS", d, True, "ranking_defense_snapshot")
        if (d.get("defense_percentage") or 0) >= UMBRAL_PRESION_DEFENSA:
            eid = _evento_contexto(conn, j["id"], p["id"], "PUNTOS_DEFENDIDOS", "MIXTA",
                                   f"defiende {d.get('dropping_points')} puntos ({(d.get('defense_percentage') or 0):.0%} de su total)",
                                   ahora, estimado=True)
            if eid:
                out["eventos"].append(("PUNTOS_DEFENDIDOS", eid))
    return out


def _mismo_pais(a: str, b: str) -> bool:
    na, nb = jg.normalizar(a), jg.normalizar(b)
    return bool(na and nb and (na == nb or na in nb or nb in na or _PAIS.get(na) == nb or _PAIS.get(nb) == na))


_PAIS = {"arg": "argentina", "col": "colombia", "esp": "espana", "ita": "italia", "fra": "francia", "bra": "brasil",
         "usa": "estados unidos", "chi": "chile", "per": "peru", "mex": "mexico", "ger": "alemania", "gbr": "reino unido",
         "aus": "australia", "por": "portugal", "sui": "suiza", "aut": "austria", "bel": "belgica", "ned": "paises bajos",
         "jpn": "japon", "chn": "china", "ind": "india", "can": "canada", "uru": "uruguay", "ecu": "ecuador", "ven": "venezuela",
         "cze": "chequia", "svk": "eslovaquia", "pol": "polonia", "srb": "serbia", "cro": "croacia", "rus": "rusia",
         "tun": "tunez", "egy": "egipto", "tur": "turquia", "gre": "grecia", "rou": "rumania", "hun": "hungria"}


def correr(conn, cliente, cfg: dict, ahora: Optional[datetime] = None, dias_historial: int = 21) -> dict:
    """Para cada partido en ventana: Motor 3 de los dos jugadores."""
    from ft_news import partidos as pm
    ahora = ahora or datetime.now(timezone.utc)
    desde = (ahora - timedelta(days=dias_historial)).date().isoformat()
    filas = (cliente.historial(desde) or {}).get("partidos") or []
    hist = indexar_historial(filas)
    paises = {}
    for f in filas:
        if f.get("torneo") and f.get("pais_torneo"):
            paises[jg.normalizar(f["torneo"])] = f["pais_torneo"]
    try:
        defensa_idx = {jg.normalizar(d["nombre"]): d for d in (cliente.defensa() or {}).get("jugadores") or []}
    except Exception:
        defensa_idx = {}
    res = {"partidos": 0, "eventos": 0, "historial": len(filas), "defensa": len(defensa_idx),
           "duplicados_vencidos": dedupe_internos(conn), "carga": {c: 0 for c in CLASES_CARGA}}
    for p in pm.proximos(conn, ahora, int(cfg.get("NEWS_VENTANA_PARTIDO_HORAS", 72))):
        res["partidos"] += 1
        for jid in (p["jugador1_id"], p["jugador2_id"]):
            j = conn.execute("SELECT * FROM news_jugador WHERE id=?", (jid,)).fetchone()
            if not j:
                continue
            r = evaluar_jugador(conn, dict(j), p, hist, defensa_idx, cliente, ahora, paises, cfg)
            res["eventos"] += len(r["eventos"])
            if r.get("carga"):
                res["carga"][r["carga"]["clase"]] = res["carga"].get(r["carga"]["clase"], 0) + 1
    return res


def carga_de(conn, jugador_id: int, partido_id: Optional[int] = None) -> Optional[dict]:
    """La carga calculada guardada para ese jugador (del partido dado o la última)."""
    if partido_id:
        r = conn.execute("SELECT valor_json FROM news_contexto WHERE jugador_id=? AND partido_id=? AND clave='CARGA'",
                         (jugador_id, partido_id)).fetchone()
    else:
        r = None
    if not r:
        r = conn.execute("SELECT valor_json FROM news_contexto WHERE jugador_id=? AND clave='CARGA' ORDER BY id DESC LIMIT 1",
                         (jugador_id,)).fetchone()
    if not r:
        return None
    try:
        c = json.loads(r["valor_json"] or "{}")
    except (TypeError, ValueError):
        return None
    if "clase" not in c:                                   # fila de versiones anteriores
        c.setdefault("partidos_3d", 0)
        c.setdefault("partidos_historial", 1 if c.get("partidos_7d") or c.get("partidos_14d") else 0)
        c["clase"] = clasificar_carga(c, {})
    return c
