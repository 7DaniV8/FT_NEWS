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
        _upsert_partido(conn, fx, circuito, id1, id2)
        sit, cad = jg.situacion_por_horas(horas, False)
        pr = _PRIORIDAD.get(circuito, 3)
        for jid in (id1, id2):
            jg.encolar(conn, jid, sit, cad, "PARTIDO_PROXIMO", pr, circuito, ahora)
        n += 1
    return {"partidos": n, "fuera_de_circuitos": fuera}


def _upsert_partido(conn, fx: dict, circuito: str, id1: int, id2: int) -> None:
    ahora = ahora_iso()
    o1, o2 = fx.get("odd1"), fx.get("odd2")
    prev = conn.execute("SELECT id, cuota1_apertura, cuota2_apertura FROM news_partido WHERE fixture_id=?",
                        (fx["fixture_id"],)).fetchone()

    def _w():
        if prev:
            conn.execute("UPDATE news_partido SET torneo=?, circuito=?, fecha_estimada=?, jugador1_id=?, jugador2_id=?, "
                         "cuota1=?, cuota2=?, cuota1_apertura=COALESCE(cuota1_apertura, ?), "
                         "cuota2_apertura=COALESCE(cuota2_apertura, ?), cuota_en=?, genero=?, superficie=?, "
                         "jugador1_nombre=?, jugador2_nombre=?, actualizado_en=? WHERE id=?",
                         (fx.get("torneo"), circuito, fx.get("fecha"), id1, id2, o1, o2, o1, o2,
                          ahora if o1 else None, fx.get("genero"), fx.get("superficie"), fx.get("jugador1"),
                          fx.get("jugador2"), ahora, prev["id"]))
        else:
            conn.execute("INSERT INTO news_partido (fixture_id, torneo, circuito, ronda, fecha_estimada, jugador1_id, "
                         "jugador2_id, origen, estado, cuota1, cuota2, cuota1_apertura, cuota2_apertura, cuota_en, "
                         "genero, superficie, jugador1_nombre, jugador2_nombre, creado_en, actualizado_en) "
                         "VALUES (?,?,?,?,?,?,?,'FIXTURES_FTR','PROGRAMADO',?,?,?,?,?,?,?,?,?,?,?)",
                         (fx["fixture_id"], fx.get("torneo"), circuito, None, fx.get("fecha"), id1, id2, o1, o2, o1, o2,
                          ahora if o1 else None, fx.get("genero"), fx.get("superficie"), fx.get("jugador1"),
                          fx.get("jugador2"), ahora, ahora))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


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
