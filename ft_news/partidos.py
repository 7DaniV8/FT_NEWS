"""
ft_news/partidos.py — Radar inverso mínimo (Fase 1): los próximos partidos
salen de /ft-intel/fixtures (lo que el BOT ya captura, con cuotas). Las
listas oficiales de ITF/ATP/WTA/UTR llegan cuando Rubén autorice esas
fuentes (FUENTES-AUTORIZACION.md).

Por cada fixture en ≤ NEWS_VENTANA_PARTIDO_HORAS:
  - upsert de los dos jugadores (identidad por nombre contra el padrón);
  - upsert del partido con cuotas (primera vista = apertura; última = actual);
  - los dos entran a la cola con la situación por horas al partido;
  - prioridad por circuito: atp/wta 1, challenger/wta125 2, itf/utr 3.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ft_news import jugadores as jg
from ft_news.db import ahora_iso, ejecutar_con_reintento

_PRIORIDAD = {"atp": 1, "wta": 1, "challenger": 2, "wta125": 2, "itf": 3, "utr": 3}


def _dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _jugador(conn, nombre: str, genero: Optional[str], circuito: str, torneo: str) -> int:
    j = jg.buscar_por_nombre(conn, nombre, genero)
    if j:
        jg.upsert(conn, j["nombre"], genero, None, circuito, ultimo_torneo=torneo)
        return j["id"]
    return jg.upsert(conn, nombre, genero, None, circuito, ultimo_torneo=torneo)


def sincronizar(conn, cliente, cfg: dict, ahora: Optional[datetime] = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    ventana = int(cfg.get("NEWS_VENTANA_PARTIDO_HORAS", 72))
    circuitos = {c.strip() for c in str(cfg.get("NEWS_CIRCUITOS", "")).split(",") if c.strip()}
    r = cliente.fixtures(horas_adelante=ventana)
    n = fuera = 0
    for fx in r.get("fixtures") or []:
        j1, j2 = fx.get("jugador1"), fx.get("jugador2")
        if not j1 or not j2 or not fx.get("fixture_id"):
            continue
        circuito = jg.circuito_de(fx.get("torneo"), fx.get("genero"))
        if circuitos and circuito not in circuitos:
            fuera += 1
            continue
        fecha = _dt(fx.get("fecha"))
        horas = (fecha - ahora).total_seconds() / 3600 if fecha else None
        if horas is not None and horas < -6:
            continue                                  # ya jugado hace rato
        id1 = _jugador(conn, j1, fx.get("genero"), circuito, fx.get("torneo") or "")
        id2 = _jugador(conn, j2, fx.get("genero"), circuito, fx.get("torneo") or "")
        _upsert_partido(conn, fx, circuito, id1, id2, ahora)
        sit, cad = jg.situacion_por_horas(horas, False)
        pr = _PRIORIDAD.get(circuito, 3)
        for jid in (id1, id2):
            jg.encolar(conn, jid, sit, cad, "PARTIDO_PROXIMO", pr, circuito, ahora)
        n += 1
    return {"partidos": n, "fuera_de_circuitos": fuera}


VENTANA_MISMO_PARTIDO_H = 3


def _mismo_partido(conn, id1: int, id2: int, fecha: Optional[str]) -> Optional[dict]:
    """v5 (09/10/2026, Rubén: "un partido real debe contar una sola vez"): el
    mismo par de jugadores, en cualquier orden, con hora a ≤ 3 h → es el mismo
    encuentro aunque venga con otro fixture_id de otro proveedor."""
    f = _dt(fecha)
    for r in conn.execute("SELECT * FROM news_partido WHERE estado='PROGRAMADO' AND "
                          "((jugador1_id=? AND jugador2_id=?) OR (jugador1_id=? AND jugador2_id=?))",
                          (id1, id2, id2, id1)).fetchall():
        fr = _dt(r["fecha_estimada"])
        if f is None or fr is None or abs((f - fr).total_seconds()) <= VENTANA_MISMO_PARTIDO_H * 3600:
            return dict(r)
    return None


def _proveedor(fx: dict) -> str:
    return str(fx.get("proveedor") or fx.get("fuente") or fx.get("casa") or "FIXTURES_FTR")


def _anotar_fuente(conn, fixture_id: int, partido_id: int, fx: dict) -> None:
    conn.execute("INSERT INTO news_partido_fuente (fixture_id, partido_id, proveedor, torneo, fecha, visto_en) "
                 "VALUES (?,?,?,?,?,?) ON CONFLICT(fixture_id) DO UPDATE SET partido_id=excluded.partido_id, "
                 "visto_en=excluded.visto_en",
                 (fixture_id, partido_id, _proveedor(fx), fx.get("torneo"), fx.get("fecha"), ahora_iso()))


def _observar_cuota(conn, partido_id: int, fx: dict, o1, o2, ahora: Optional[datetime] = None) -> None:
    """v5.1: guarda la observación (proveedor, hora, precio) si cambió respecto
    de la última del mismo proveedor, y deja en news_partido la cuota VIGENTE:
    la observación más reciente por hora de captura (empate → la última vista)."""
    if not (o1 and o2):
        return
    prov = _proveedor(fx)
    cap = fx.get("actualizado_en") or fx.get("cuotas_en") or (ahora.isoformat() if ahora else ahora_iso())
    ult = conn.execute("SELECT id, cuota1, cuota2, hasta_en FROM news_cuota_obs WHERE partido_id=? AND proveedor=? "
                       "ORDER BY id DESC LIMIT 1", (partido_id, prov)).fetchone()
    if not ult or (ult["cuota1"], ult["cuota2"]) != (o1, o2):
        conn.execute("INSERT INTO news_cuota_obs (partido_id, fixture_id, proveedor, cuota1, cuota2, capturada_en, hasta_en, visto_en) "
                     "VALUES (?,?,?,?,?,?,?,?)", (partido_id, fx.get("fixture_id"), prov, o1, o2, cap, cap, ahora_iso()))
    else:
        # v5.2: el mismo precio visto otra vez = el precio sigue vigente a esta hora
        # (Rubén: hace falta una cuota confirmada DESPUÉS de la noticia).
        conn.execute("UPDATE news_cuota_obs SET hasta_en=MAX(COALESCE(hasta_en, capturada_en), ?), visto_en=? WHERE id=?",
                     (cap, ahora_iso(), ult["id"]))
    v = conn.execute("SELECT proveedor, cuota1, cuota2, capturada_en, COALESCE(hasta_en, capturada_en) hasta FROM news_cuota_obs "
                     "WHERE partido_id=? ORDER BY hasta DESC, id DESC LIMIT 1", (partido_id,)).fetchone()
    conn.execute("UPDATE news_partido SET cuota1=?, cuota2=?, cuota_en=?, cuota_proveedor=?, "
                 "cuota1_apertura=COALESCE(cuota1_apertura, ?), cuota2_apertura=COALESCE(cuota2_apertura, ?), "
                 "actualizado_en=? WHERE id=?",
                 (v["cuota1"], v["cuota2"], v["hasta"], v["proveedor"], v["cuota1"], v["cuota2"], ahora_iso(), partido_id))


def observaciones(conn, partido_id: int) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM news_cuota_obs WHERE partido_id=? ORDER BY id", (partido_id,)).fetchall():
        d = dict(r)
        d["hasta_en"] = d.get("hasta_en") or d.get("capturada_en")
        out.append(d)
    return out


def cuota_antes_y_despues(conn, partido_id: int, jugador_id: int, momento) -> dict:
    """v5.2: la cuota del jugador vigente ANTES de `momento` (la noticia) y la
    confirmada DESPUÉS (precio visto con hasta_en > momento). Devuelve
    {'antes': {...}|None, 'despues': {...}|None, 'mismo_precio': bool}."""
    p = conn.execute("SELECT jugador1_id FROM news_partido WHERE id=?", (partido_id,)).fetchone()
    if not p or momento is None:
        return {"antes": None, "despues": None, "mismo_precio": False}
    lado = "cuota1" if p["jugador1_id"] == jugador_id else "cuota2"
    antes = despues = None
    for o in observaciones(conn, partido_id):
        d0, d1 = _dt(o.get("capturada_en")), _dt(o.get("hasta_en"))
        if d0 and d0 <= momento:
            antes = o
        if d1 and d1 > momento and (despues is None or d1 >= _dt(despues["hasta_en"])):
            despues = o
    f = lambda o: {"cuota": o[lado], "proveedor": o["proveedor"], "desde": o.get("capturada_en"), "hasta": o.get("hasta_en")} if o else None  # noqa: E731
    return {"antes": f(antes), "despues": f(despues), "mismo_precio": bool(antes and despues and antes["id"] == despues["id"])}


def _upsert_partido(conn, fx: dict, circuito: str, id1: int, id2: int, ahora_dt: Optional[datetime] = None) -> None:
    ahora = ahora_iso()
    o1, o2 = fx.get("odd1"), fx.get("odd2")
    prev = conn.execute("SELECT id, cuota1_apertura, cuota2_apertura FROM news_partido WHERE fixture_id=?",
                        (fx["fixture_id"],)).fetchone()
    mismo = None
    if prev is None:
        via = conn.execute("SELECT partido_id FROM news_partido_fuente WHERE fixture_id=?", (fx["fixture_id"],)).fetchone()
        if via:
            mismo = conn.execute("SELECT * FROM news_partido WHERE id=?", (via["partido_id"],)).fetchone()
            mismo = dict(mismo) if mismo else None
    if prev is None and mismo is None:
        mismo = _mismo_partido(conn, id1, id2, fx.get("fecha"))
    if mismo and mismo.get("jugador1_id") == id2:       # la otra fuente lo trae invertido
        o1, o2 = o2, o1

    def _w():
        if mismo:
            # Otra fuente del mismo partido: se conserva la fila, se suma la fuente y
            # la cuota entra como observación (la vigente es la más reciente).
            _anotar_fuente(conn, fx["fixture_id"], mismo["id"], fx)
            _observar_cuota(conn, mismo["id"], fx, o1, o2, ahora_dt)
            conn.commit()
            return
        if prev:
            conn.execute("UPDATE news_partido SET torneo=?, circuito=?, fecha_estimada=?, jugador1_id=?, jugador2_id=?, "
                         "genero=?, superficie=?, jugador1_nombre=?, jugador2_nombre=?, actualizado_en=? WHERE id=?",
                         (fx.get("torneo"), circuito, fx.get("fecha"), id1, id2, fx.get("genero"), fx.get("superficie"),
                          fx.get("jugador1"), fx.get("jugador2"), ahora, prev["id"]))
        else:
            conn.execute("INSERT INTO news_partido (fixture_id, torneo, circuito, ronda, fecha_estimada, jugador1_id, "
                         "jugador2_id, origen, estado, genero, superficie, jugador1_nombre, jugador2_nombre, creado_en, "
                         "actualizado_en) VALUES (?,?,?,?,?,?,?,'FIXTURES_FTR','PROGRAMADO',?,?,?,?,?,?)",
                         (fx["fixture_id"], fx.get("torneo"), circuito, None, fx.get("fecha"), id1, id2,
                          fx.get("genero"), fx.get("superficie"), fx.get("jugador1"), fx.get("jugador2"), ahora, ahora))
        pid = prev["id"] if prev else conn.execute("SELECT id FROM news_partido WHERE fixture_id=?", (fx["fixture_id"],)).fetchone()[0]
        _anotar_fuente(conn, fx["fixture_id"], pid, fx)
        _observar_cuota(conn, pid, fx, o1, o2, ahora_dt)
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def fusionar_duplicados(conn) -> dict:
    """Una vez (al subir v5): junta los partidos PROGRAMADOS repetidos (mismo par,
    ≤ 3 h). Se conserva el de menor id; evaluaciones, contexto y eventos de
    carga de los otros se reasignan o se marcan SUPERADO."""
    filas = [dict(r) for r in conn.execute("SELECT * FROM news_partido WHERE estado='PROGRAMADO' ORDER BY id").fetchall()]
    vistos: list[dict] = []
    fusionados = 0

    def _w(dup: dict, base: dict):
        for x in (dup, base):
            conn.execute("INSERT OR IGNORE INTO news_partido_fuente (fixture_id, partido_id, proveedor, torneo, fecha, visto_en) "
                         "VALUES (?,?,?,?,?,?)", (x["fixture_id"], base["id"], x.get("origen"), x.get("torneo"),
                                                 x.get("fecha_estimada"), ahora_iso()))
        if conn.execute("SELECT 1 FROM news_evaluacion WHERE partido_id=?", (base["id"],)).fetchone():
            conn.execute("DELETE FROM news_evaluacion WHERE partido_id=? AND dicho_discord=0", (dup["id"],))
        conn.execute("UPDATE news_evaluacion SET partido_id=? WHERE partido_id=?", (base["id"], dup["id"]))
        conn.execute("DELETE FROM news_contexto WHERE partido_id=? AND (jugador_id, clave) IN "
                     "(SELECT jugador_id, clave FROM news_contexto WHERE partido_id=?)", (dup["id"], base["id"]))
        conn.execute("UPDATE news_contexto SET partido_id=? WHERE partido_id=?", (base["id"], dup["id"]))
        for e in conn.execute("SELECT id, jugador_id, categoria FROM news_evento WHERE enlace=?",
                              (f"contexto:{dup['id']}",)).fetchall():
            b = conn.execute("SELECT id FROM news_evento WHERE enlace=? AND jugador_id=? AND categoria=?",
                             (f"contexto:{base['id']}", e["jugador_id"], e["categoria"])).fetchone()
            if b:
                conn.execute("UPDATE news_evento SET estado='SUPERADO', superado_por=?, actualizado_en=? WHERE id=?",
                             (b["id"], ahora_iso(), e["id"]))
            else:
                conn.execute("UPDATE news_evento SET enlace=?, actualizado_en=? WHERE id=?",
                             (f"contexto:{base['id']}", ahora_iso(), e["id"]))
        conn.execute("UPDATE news_cuota_obs SET partido_id=? WHERE partido_id=?", (base["id"], dup["id"]))
        if dup.get("cuota1") and dup.get("cuota2") and not conn.execute(
                "SELECT 1 FROM news_cuota_obs WHERE partido_id=? AND fixture_id=?", (base["id"], dup["fixture_id"])).fetchone():
            inv = dup["jugador1_id"] != base["jugador1_id"]
            conn.execute("INSERT INTO news_cuota_obs (partido_id, fixture_id, proveedor, cuota1, cuota2, capturada_en, visto_en) "
                         "VALUES (?,?,?,?,?,?,?)", (base["id"], dup["fixture_id"], dup.get("origen") or "FIXTURES_FTR",
                                                   dup["cuota2"] if inv else dup["cuota1"], dup["cuota1"] if inv else dup["cuota2"],
                                                   dup.get("cuota_en"), ahora_iso()))
        conn.execute("UPDATE news_partido SET estado='DUPLICADO', actualizado_en=? WHERE id=?", (ahora_iso(), dup["id"]))
        conn.commit()

    for p in filas:
        f = _dt(p.get("fecha_estimada"))
        base = None
        for v in vistos:
            if {v["jugador1_id"], v["jugador2_id"]} == {p["jugador1_id"], p["jugador2_id"]}:
                fv = _dt(v.get("fecha_estimada"))
                if f is None or fv is None or abs((f - fv).total_seconds()) <= VENTANA_MISMO_PARTIDO_H * 3600:
                    base = v
                    break
        if base is None:
            vistos.append(p)
            continue
        ejecutar_con_reintento(lambda d=p, b=base: _w(d, b), conn=conn)
        fusionados += 1
    return {"fusionados": fusionados, "unicos": len(vistos)}


def proximos(conn, ahora: Optional[datetime] = None, horas: int = 72) -> list[dict]:
    ahora = ahora or datetime.now(timezone.utc)
    out = []
    for r in conn.execute("SELECT * FROM news_partido WHERE estado='PROGRAMADO' ORDER BY fecha_estimada").fetchall():
        d = dict(r)
        f = _dt(d.get("fecha_estimada"))
        if f and (f - ahora).total_seconds() / 3600 > horas:
            continue
        out.append(d)
    return out
