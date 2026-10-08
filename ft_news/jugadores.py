"""
ft_news/jugadores.py — Identidad de jugadores (Fase 1).

La identidad maestra es el padrón UTR de RankingFTR (/ft-intel/utr/padron):
nombre, país, UTR y fecha de captura. Los jugadores entran a news_jugador
cuando aparecen en un partido (radar inverso mínimo = fixtures del BOT) o
cuando el padrón se sincroniza. La cola de vigilancia se alimenta desde
partidos.py según la situación (horas al partido).
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news.db import ahora_iso, ejecutar_con_reintento

# nacionalidad (código UTR/ITF) → idioma de prensa local
IDIOMA_POR_PAIS = {
    "ITA": "it", "FRA": "fr", "BEL": "fr", "SUI": "fr", "MON": "fr",
    "BRA": "pt", "POR": "pt",
    "ESP": "es", "ARG": "es", "COL": "es", "CHI": "es", "MEX": "es", "PER": "es", "URU": "es", "ECU": "es",
    "VEN": "es", "BOL": "es", "PAR": "es", "DOM": "es", "GUA": "es", "CRC": "es",
}


def normalizar(nombre: str) -> str:
    n = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-z0-9 ]+", " ", n.lower())
    toks = sorted(t for t in n.split() if len(t) > 1 or t.isdigit())
    return " ".join(toks)


def claves_apellido_inicial(nombre: str) -> set[str]:
    """Para unir 'Apellido I.' (fixtures del BOT, Formato A) con 'Nombre Apellido'
    (padrón, Formato B). Claves: 'apellido inicial' y 'ultimo_apellido inicial'."""
    n = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    if "," in n:                                     # 'Perez, Juan' → 'Juan Perez'
        ap, _, nom = n.partition(",")
        n = f"{nom.strip()} {ap.strip()}"
    n = re.sub(r"[^a-z ]+", " ", n)
    toks = [t for t in n.split() if t]
    if len(toks) < 2:
        return set()
    if len(toks[-1]) == 1:                           # Formato A: 'perez j'
        apellido, inicial = toks[:-1], toks[-1]
    else:                                            # Formato B: 'juan perez'
        apellido, inicial = toks[1:], toks[0][0]
    return {f"{' '.join(apellido)} {inicial}", f"{apellido[-1]} {inicial}"}


def circuito_de(torneo: Optional[str], genero: Optional[str]) -> str:
    t = (torneo or "").lower()
    if "challenger" in t or re.search(r"\bch\b", t):
        return "challenger"
    if re.search(r"\b(m15|m25|w15|w35|w50|w75|w100|itf)\b", t):
        return "itf"
    if "utr" in t:
        return "utr"
    if "125" in t and (genero or "").upper().startswith("F"):
        return "wta125"
    return "wta" if (genero or "").upper().startswith("F") else "atp"


def upsert(conn, nombre: str, genero: Optional[str] = None, pais: Optional[str] = None,
           circuito: Optional[str] = None, utr_player_id: Optional[int] = None, player_id_ftr: Optional[int] = None,
           utr_singles: Optional[float] = None, utr_en: Optional[str] = None, utr_display: Optional[str] = None,
           ultimo_torneo: Optional[str] = None) -> int:
    nn = normalizar(nombre)
    g = (genero or "").upper()[:1] or None
    ahora = ahora_iso()
    r = conn.execute("SELECT id FROM news_jugador WHERE nombre_norm=? AND (genero=? OR genero IS NULL OR ? IS NULL)",
                     (nn, g, g)).fetchone()

    def _w():
        if r:
            conn.execute(
                "UPDATE news_jugador SET nombre=COALESCE(?, nombre), genero=COALESCE(?, genero), pais=COALESCE(?, pais), "
                "circuito=COALESCE(?, circuito), utr_player_id=COALESCE(?, utr_player_id), "
                "player_id_ftr=COALESCE(?, player_id_ftr), utr_singles=COALESCE(?, utr_singles), "
                "utr_en=COALESCE(?, utr_en), utr_display=COALESCE(?, utr_display), ultimo_torneo=COALESCE(?, ultimo_torneo), "
                "actualizado_en=? WHERE id=?",
                (nombre, g, pais, circuito, utr_player_id, player_id_ftr, utr_singles, utr_en, utr_display,
                 ultimo_torneo, ahora, r["id"]))
            conn.commit()
            return r["id"]
        cur = conn.execute(
            "INSERT INTO news_jugador (utr_player_id, player_id_ftr, nombre, nombre_norm, pais, genero, circuito, "
            "aliases_json, ultimo_torneo, utr_singles, utr_en, utr_display, creado_en, actualizado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (utr_player_id, player_id_ftr, nombre, nn, pais, g, circuito, json.dumps([]), ultimo_torneo,
             utr_singles, utr_en, utr_display, ahora, ahora))
        conn.commit()
        return cur.lastrowid
    return ejecutar_con_reintento(_w, conn=conn)


def buscar_por_nombre(conn, nombre: str, genero: Optional[str] = None) -> Optional[dict]:
    nn = normalizar(nombre)
    g = (genero or "").upper()[:1] or None
    r = conn.execute("SELECT * FROM news_jugador WHERE nombre_norm=? AND (? IS NULL OR genero=? OR genero IS NULL)",
                     (nn, g, g)).fetchone()
    if r:
        return dict(r)
    # 'Apellido I.' contra nombres completos
    claves = claves_apellido_inicial(nombre)
    if not claves:
        return None
    cands = []
    for f in conn.execute("SELECT * FROM news_jugador WHERE (? IS NULL OR genero=? OR genero IS NULL)", (g, g)):
        if claves & claves_apellido_inicial(f["nombre"]):
            cands.append(dict(f))
    return cands[0] if len(cands) == 1 else None


def sincronizar_padron(conn, cliente) -> dict:
    """Copia el padrón UTR (identidad maestra) a news_jugador."""
    n, desde = 0, 0
    while True:
        r = cliente.utr_padron(desde_id=desde, limite=2000)
        for j in r.get("jugadores") or []:
            nombre = j.get("nombre_utr") or j.get("nombre_ftr")
            if not nombre:
                continue
            utr = j.get("utr_singles")
            upsert(conn, nombre, j.get("genero"), j.get("nacionalidad"), None, j.get("utr_player_id"),
                   j.get("player_id_ftr") or j.get("player_id"), float(utr) if utr else None,
                   j.get("fecha_captura"), j.get("utr_display"))
            if j.get("nombre_ftr") and normalizar(j["nombre_ftr"]) != normalizar(nombre):
                upsert(conn, j["nombre_ftr"], j.get("genero"), j.get("nacionalidad"), None, j.get("utr_player_id"),
                       j.get("player_id_ftr") or j.get("player_id"), float(utr) if utr else None,
                       j.get("fecha_captura"), j.get("utr_display"))
            n += 1
        desde = r.get("siguiente_desde_id")
        if not desde:
            break
    return {"padron": n}


def utr_de(j: dict) -> tuple[Optional[float], Optional[str]]:
    return (j.get("utr_singles"), j.get("utr_en")) if j else (None, None)


def idiomas_para(j: dict, idiomas_activos: list[str]) -> list[str]:
    """Inglés siempre; español siempre (es la casa); el idioma local del país si está activo."""
    out = [i for i in ("en", "es") if i in idiomas_activos]
    local = IDIOMA_POR_PAIS.get((j.get("pais") or "").upper())
    if local and local in idiomas_activos and local not in out:
        out.append(local)
    return out or ["en"]


def situacion_por_horas(horas: Optional[float], tiene_evento_fuerte: bool) -> tuple[str, int]:
    """(situacion, cadencia_horas) según el diseño §5."""
    if horas is not None and horas <= 24:
        return "PARTIDO_24H", 6
    if horas is not None and horas <= 72:
        return "PARTIDO_72H", 12
    if tiene_evento_fuerte:
        return "EVENTO_VIGENTE", 24
    return "SIN_PARTIDO", 24 * 7


def encolar(conn, jugador_id: int, situacion: str, cadencia_h: int, motivo: str, prioridad: int,
            circuito: Optional[str], ahora: Optional[datetime] = None) -> None:
    ahora = ahora or datetime.now(timezone.utc)
    r = conn.execute("SELECT * FROM news_jugador_cola WHERE jugador_id=?", (jugador_id,)).fetchone()

    def _w():
        if r:
            ultima = r["ultima_busqueda_en"]
            prox = r["proxima_busqueda_en"]
            # si la situación se volvió más urgente, se adelanta la próxima búsqueda
            if ultima:
                nueva = (datetime.fromisoformat(ultima) + timedelta(hours=cadencia_h)).isoformat()
                prox = min(prox or nueva, nueva)
            conn.execute("UPDATE news_jugador_cola SET prioridad=?, motivo=?, situacion=?, circuito=?, "
                         "proxima_busqueda_en=?, actualizado_en=? WHERE jugador_id=?",
                         (prioridad, motivo, situacion, circuito, prox, ahora.isoformat(), jugador_id))
        else:
            conn.execute("INSERT INTO news_jugador_cola (jugador_id, prioridad, motivo, situacion, circuito, "
                         "proxima_busqueda_en, ultima_busqueda_en, actualizado_en) VALUES (?,?,?,?,?,?,NULL,?)",
                         (jugador_id, prioridad, motivo, situacion, circuito, ahora.isoformat(), ahora.isoformat()))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)
