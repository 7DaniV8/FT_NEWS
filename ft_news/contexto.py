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
UMBRAL_PARTIDOS_7D = 4           # ≥ 4 partidos en 7 días → CARGA_FISICA
UMBRAL_TRES_SETS_7D = 3          # ≥ 3 partidos a 3+ sets en 7 días → CARGA_FISICA
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


def carga(partidos: list[dict], ahora: datetime) -> dict:
    d7 = [p for p in partidos if _dt(p["fecha"]) and _dt(p["fecha"]) >= ahora - timedelta(days=7)]
    d14 = [p for p in partidos if _dt(p["fecha"]) and _dt(p["fecha"]) >= ahora - timedelta(days=14)]
    ultimo = partidos[-1] if partidos else None
    hace = (ahora - _dt(ultimo["fecha"])).days if ultimo and _dt(ultimo["fecha"]) else None
    return {"partidos_7d": len(d7), "partidos_14d": len(d14), "tres_sets_7d": sum(1 for p in d7 if p["sets"] >= 3),
            "sets_7d": sum(p["sets"] for p in d7), "ultimo_hace_dias": hace,
            "ultimo_tres_sets": bool(ultimo and ultimo["sets"] >= 3), "duracion": None}


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


def _evento_contexto(conn, jugador_id: int, partido_id: int, categoria: str, direccion: str, resumen: str,
                     fecha: datetime, estimado: bool = False) -> Optional[int]:
    enlace = f"contexto:{partido_id}"
    if conn.execute("SELECT 1 FROM news_evento WHERE jugador_id=? AND categoria=? AND enlace=?",
                    (jugador_id, categoria, enlace)).fetchone():
        return None
    ev = memoria.nuevo_evento(jugador_id, categoria, direccion, "HECHO", "A", fecha.isoformat(), fuente=FUENTE,
                              enlace=enlace, resumen_es=resumen + (" (estimado)" if estimado else ""),
                              relevancia_deportiva="contexto calculado, no es una noticia", confianza_identidad=1.0)
    return memoria.guardar_evento_db(conn, ev)


def evaluar_jugador(conn, j: dict, p: dict, hist: dict, defensa_idx: dict, cliente, ahora: datetime,
                    paises_torneo: dict) -> dict:
    """Motor 3 para un jugador en un partido. Devuelve lo calculado y los eventos creados."""
    out = {"eventos": []}
    partidos = hist.get(j["nombre_norm"], [])
    fecha_p = _dt(p.get("fecha_estimada"))
    # carga
    c = carga(partidos, ahora)
    _guardar_contexto(conn, j["id"], p["id"], "CARGA", c, False, FUENTE)
    if c["partidos_7d"] >= UMBRAL_PARTIDOS_7D or c["tres_sets_7d"] >= UMBRAL_TRES_SETS_7D:
        eid = _evento_contexto(conn, j["id"], p["id"], "CARGA_FISICA", "NEGATIVA",
                               f"{c['partidos_7d']} partidos y {c['sets_7d']} sets en 7 días; último hace {c['ultimo_hace_dias']} día(s)",
                               ahora)
        if eid:
            out["eventos"].append(("CARGA_FISICA", eid))
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
    res = {"partidos": 0, "eventos": 0, "historial": len(filas), "defensa": len(defensa_idx)}
    for p in pm.proximos(conn, ahora, int(cfg.get("NEWS_VENTANA_PARTIDO_HORAS", 72))):
        res["partidos"] += 1
        for jid in (p["jugador1_id"], p["jugador2_id"]):
            j = conn.execute("SELECT * FROM news_jugador WHERE id=?", (jid,)).fetchone()
            if not j:
                continue
            r = evaluar_jugador(conn, dict(j), p, hist, defensa_idx, cliente, ahora, paises)
            res["eventos"] += len(r["eventos"])
    return res
