"""
ft_news/memoria.py — Memoria inteligente del jugador (Motor 2), con el
ajuste de Rubén (08/10/2026): UN REGRESO NO BORRA LA LESIÓN.

Estados de un evento:
  VIGENTE         cuenta para el descubridor con su dirección.
  EN_SEGUIMIENTO  antecedente físico que un regreso puso "en observación":
                  sigue en el historial, sigue contando (como MIXTA) hasta
                  que el estado físico se VERIFIQUE con partidos completos.
  SUPERADO        lo reemplazó un evento más reciente de la misma familia
                  (una lesión nueva supera a la anterior; un abandono supera
                  a un regreso). Queda en el historial.
  VENCIDO         pasó su vigencia sin nada nuevo.
  DESCARTADO      revisión manual lo marcó como falso / jugador equivocado.

Reglas fijas (no por IA):
  R1  Lesión/enfermedad nueva → la anterior de la misma categoría queda SUPERADA.
  R2  REGRESO → lesión/enfermedad/abandono anteriores pasan a EN_SEGUIMIENTO con
      verificar_estado_fisico=1; su vigencia se extiende hasta regreso + 14 días.
      El REGRESO nace con verificar_estado_fisico=1 (dirección MIXTA hasta verificar).
  R3  RETIRO_ABANDONO después de un REGRESO → el regreso queda SUPERADO y el
      antecedente físico vuelve a VIGENTE.
  R4  Partido completo jugado (dato propio, sin retiro) → suma 1 a
      partidos_completos_desde en los eventos físicos EN_SEGUIMIENTO; con
      PARTIDOS_PARA_VERIFICAR completos y sin negativa nueva, el estado físico
      se considera verificado (verificar_estado_fisico=0): el antecedente deja
      de bloquear señales positivas, pero NO se borra.
  R5  Vencimiento por fecha, solo cuando no pasó nada nuevo.

Todo es puro sobre listas de dicts (tests) + envoltorios sobre SQLite.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import taxonomia as tx
from ft_news.db import ahora_iso, ejecutar_con_reintento

FISICAS = ("LESION_MOLESTIA", "ENFERMEDAD", "RETIRO_ABANDONO")
PARTIDOS_PARA_VERIFICAR = 2
DIAS_SEGUIMIENTO_TRAS_REGRESO = 14


def _dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def nuevo_evento(jugador_id: int, categoria: str, direccion: str, naturaleza: str, nivel: str,
                 fecha_evento: str, **extra) -> dict:
    errores = tx.validar_evento(categoria, direccion, naturaleza, nivel)
    if errores:
        raise ValueError("; ".join(errores))
    fe = _dt(fecha_evento) or datetime.now(timezone.utc)
    ev = {
        "id": None, "jugador_id": jugador_id, "categoria": categoria, "direccion": direccion,
        "naturaleza": naturaleza, "nivel": nivel, "fecha_evento": _iso(fe),
        "estado": "VIGENTE", "vigente_hasta": _iso(fe + timedelta(days=tx.vigencia_dias(categoria))),
        "superado_por": None, "verificar_estado_fisico": 0, "partidos_completos_desde": 0,
    }
    ev.update(extra)
    if categoria == "REGRESO":
        ev["verificar_estado_fisico"] = 1
        ev["direccion"] = tx.MIXTA if direccion == tx.POSITIVA else direccion
    return ev


def aplicar_reglas(historial: list[dict], nuevo: dict) -> list[dict]:
    """Devuelve el historial actualizado (mismos dicts, mutados) con `nuevo`
    agregado al final. Solo mira eventos del mismo jugador."""
    fe = _dt(nuevo["fecha_evento"])
    cat = nuevo["categoria"]
    for ev in historial:
        if ev["jugador_id"] != nuevo["jugador_id"] or ev["estado"] in ("SUPERADO", "DESCARTADO"):
            continue
        fev = _dt(ev["fecha_evento"])
        if fev and fe and fev > fe:
            continue                                  # el nuevo es más viejo: no toca nada
        # R1: misma categoría física → la anterior queda superada
        if cat in FISICAS and ev["categoria"] == cat:
            ev["estado"], ev["superado_por"] = "SUPERADO", nuevo.get("id") or "nuevo"
        # R2: regreso → antecedentes físicos a seguimiento (NUNCA superados)
        elif cat == "REGRESO" and ev["categoria"] in FISICAS:
            ev["estado"] = "EN_SEGUIMIENTO"
            ev["verificar_estado_fisico"] = 1
            ev["partidos_completos_desde"] = 0
            ev["vigente_hasta"] = _iso(fe + timedelta(days=DIAS_SEGUIMIENTO_TRAS_REGRESO))
        # R3: abandono después de un regreso → el regreso queda superado y lo físico vuelve
        elif cat == "RETIRO_ABANDONO" and ev["categoria"] == "REGRESO":
            ev["estado"], ev["superado_por"] = "SUPERADO", nuevo.get("id") or "nuevo"
        elif cat == "RETIRO_ABANDONO" and ev["categoria"] in FISICAS and ev["estado"] == "EN_SEGUIMIENTO":
            ev["estado"] = "VIGENTE"
            ev["vigente_hasta"] = _iso(fe + timedelta(days=tx.vigencia_dias(ev["categoria"])))
    historial.append(nuevo)
    return historial


def registrar_partido_completo(historial: list[dict], jugador_id: int, fecha: str,
                               retiro: bool = False) -> list[dict]:
    """R4. Un partido jugado completo verifica poco a poco el estado físico;
    un retiro NO cuenta (y debería llegar como RETIRO_ABANDONO aparte)."""
    if retiro:
        return historial
    f = _dt(fecha)
    for ev in historial:
        if ev["jugador_id"] != jugador_id or ev["estado"] not in ("EN_SEGUIMIENTO", "VIGENTE"):
            continue
        if not ev.get("verificar_estado_fisico"):
            continue
        fev = _dt(ev["fecha_evento"])
        if fev and f and f < fev:
            continue
        ev["partidos_completos_desde"] = int(ev.get("partidos_completos_desde") or 0) + 1
        if ev["partidos_completos_desde"] >= PARTIDOS_PARA_VERIFICAR:
            ev["verificar_estado_fisico"] = 0
    return historial


def vencer(historial: list[dict], ahora: Optional[datetime] = None) -> list[dict]:
    """R5."""
    ahora = ahora or datetime.now(timezone.utc)
    for ev in historial:
        if ev["estado"] in ("VIGENTE", "EN_SEGUIMIENTO"):
            vh = _dt(ev.get("vigente_hasta"))
            if vh and vh < ahora:
                ev["estado"] = "VENCIDO"
    return historial


def activos(historial: list[dict], jugador_id: int, ahora: Optional[datetime] = None) -> list[dict]:
    """Lo que cuenta para el descubridor: VIGENTE y EN_SEGUIMIENTO, no vencidos."""
    vencer(historial, ahora)
    return [e for e in historial if e["jugador_id"] == jugador_id and e["estado"] in ("VIGENTE", "EN_SEGUIMIENTO")]


def estado_fisico_sin_verificar(historial: list[dict], jugador_id: int) -> bool:
    return any(e["jugador_id"] == jugador_id and e["estado"] in ("VIGENTE", "EN_SEGUIMIENTO")
               and e.get("verificar_estado_fisico") for e in historial)


def lectura_contextual(historial: list[dict], jugador_id: int, ahora: Optional[datetime] = None) -> list[str]:
    """La 'lectura' del ejemplo de Rubén: una línea por evento, en orden, con
    hace-cuánto y estado. Texto para la tab; nunca una conclusión."""
    ahora = ahora or datetime.now(timezone.utc)
    lineas = []
    for e in sorted((x for x in historial if x["jugador_id"] == jugador_id), key=lambda x: x["fecha_evento"]):
        d = (ahora - _dt(e["fecha_evento"])).days
        cuando = "hoy" if d == 0 else ("ayer" if d == 1 else f"hace {d} días")
        marca = ""
        if e["estado"] == "EN_SEGUIMIENTO":
            marca = " · en seguimiento: estado físico sin verificar" if e.get("verificar_estado_fisico") \
                else " · en seguimiento: verificado con partidos completos"
        elif e["estado"] != "VIGENTE":
            marca = f" · {e['estado'].lower()}"
        lineas.append(f"{cuando}: {e['categoria']} ({e['direccion'].lower()}, nivel {e['nivel']}){marca}")
    return lineas


# ── SQLite ─────────────────────────────────────────────────────────────
_CAMPOS = ("jugador_id", "articulo_id", "categoria", "direccion", "naturaleza", "nivel", "fecha_evento",
           "fecha_publicacion", "fuente", "enlace", "fragmento_original", "resumen_es", "relevancia_deportiva",
           "confianza_identidad", "estado", "vigente_hasta", "superado_por", "verificar_estado_fisico",
           "lectura1_json", "lectura2_json")


def _asegurar_columna(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(news_evento)")}
    if "partidos_completos_desde" not in cols:
        conn.execute("ALTER TABLE news_evento ADD COLUMN partidos_completos_desde INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def historial_db(conn, jugador_id: int) -> list[dict]:
    _asegurar_columna(conn)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM news_evento WHERE jugador_id=? ORDER BY fecha_evento, id", (jugador_id,)).fetchall()]


def guardar_evento_db(conn, ev: dict) -> int:
    """Aplica las reglas contra el historial guardado y persiste todo."""
    _asegurar_columna(conn)
    hist = historial_db(conn, ev["jugador_id"])
    aplicar_reglas(hist, ev)
    ahora = ahora_iso()

    def _w():
        cur = conn.execute(
            f"INSERT INTO news_evento ({', '.join(_CAMPOS)}, partidos_completos_desde, creado_en, actualizado_en) "
            f"VALUES ({', '.join('?' * len(_CAMPOS))}, ?, ?, ?)",
            tuple(_json(ev.get(c)) for c in _CAMPOS) + (int(ev.get("partidos_completos_desde") or 0), ahora, ahora))
        nuevo_id = cur.lastrowid
        for e in hist:
            if e is ev or e.get("id") is None:
                continue
            sup = nuevo_id if e.get("superado_por") == "nuevo" else e.get("superado_por")
            conn.execute("UPDATE news_evento SET estado=?, vigente_hasta=?, superado_por=?, "
                         "verificar_estado_fisico=?, partidos_completos_desde=?, actualizado_en=? WHERE id=?",
                         (e["estado"], e.get("vigente_hasta"), sup, int(e.get("verificar_estado_fisico") or 0),
                          int(e.get("partidos_completos_desde") or 0), ahora, e["id"]))
        conn.commit()
        return nuevo_id
    nuevo_id = ejecutar_con_reintento(_w, conn=conn)
    ev["id"] = nuevo_id
    return nuevo_id


def _json(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v
