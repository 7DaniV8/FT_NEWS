"""
ft_news/db.py — Base propia de FT_NEWS (SQLite, prefijo news_).

Mismas reglas que RankingFTR/FT Intelligence: toda escritura pasa por
ejecutar_con_reintento (SQLite ocupado → reintento con espera), WAL,
busy_timeout. Las tablas se crean idempotentes; las columnas nuevas se
agregan con ADD COLUMN para no romper una base ya desplegada.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ft_news import config

_LOCK = threading.RLock()


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn(path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(path or config.DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_tablas(conn)
    return conn


def ejecutar_con_reintento(fn: Callable, conn=None, con_lock: bool = True, intentos: int = 5):
    """Escrituras: reintenta en 'database is locked' con espera creciente."""
    ultimo = None
    for i in range(intentos):
        try:
            if con_lock:
                with _LOCK:
                    return fn()
            return fn()
        except sqlite3.OperationalError as e:
            ultimo = e
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            time.sleep(0.2 * (i + 1))
    raise ultimo  # type: ignore[misc]


_ESQUEMA = """
CREATE TABLE IF NOT EXISTS news_config (
    clave            TEXT PRIMARY KEY,
    valor            TEXT,
    actualizado_en   TEXT NOT NULL,
    actualizado_por  TEXT);

CREATE TABLE IF NOT EXISTS news_estado (
    clave            TEXT PRIMARY KEY,
    valor            TEXT,
    actualizado_en   TEXT NOT NULL);

-- Jugador: identidad maestra = padrón UTR de RankingFTR.
CREATE TABLE IF NOT EXISTS news_jugador (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    utr_player_id    INTEGER,
    player_id_ftr    INTEGER,
    nombre           TEXT NOT NULL,
    nombre_norm      TEXT NOT NULL,
    pais             TEXT,
    genero           TEXT,
    circuito         TEXT,
    aliases_json     TEXT,
    ultimo_torneo    TEXT,
    creado_en        TEXT NOT NULL,
    actualizado_en   TEXT NOT NULL,
    UNIQUE (nombre_norm, genero));

CREATE TABLE IF NOT EXISTS news_jugador_cola (
    jugador_id           INTEGER PRIMARY KEY REFERENCES news_jugador(id),
    prioridad            INTEGER NOT NULL DEFAULT 5,
    motivo               TEXT NOT NULL,              -- PARTIDO_PROXIMO | EVENTO_VIGENTE | RANKING | MANUAL
    situacion            TEXT NOT NULL,              -- ver cadencia.SITUACIONES
    circuito             TEXT,
    proxima_busqueda_en  TEXT,
    ultima_busqueda_en   TEXT,
    actualizado_en       TEXT NOT NULL);

-- Lista blanca de fuentes. NADA se lee con autorizada=0.
CREATE TABLE IF NOT EXISTS news_fuente (
    dominio          TEXT PRIMARY KEY,
    nombre           TEXT NOT NULL,
    tipo             TEXT NOT NULL,                  -- OFICIAL | PRENSA | FEDERACION | RED | AGREGADOR | PROPIA
    idioma           TEXT,
    nivel_maximo     TEXT NOT NULL DEFAULT 'B',      -- A | B | C
    circuitos        TEXT,
    acceso           TEXT,                           -- RSS | HTML | PDF | API | JSON_INTERNO
    autorizada       INTEGER NOT NULL DEFAULT 0,     -- 1 solo tras revisar condiciones de uso
    estado_tc        TEXT NOT NULL DEFAULT 'PENDIENTE', -- PENDIENTE | REVISADO_OK | REVISADO_NO | REQUIERE_LICENCIA
    nota_tc          TEXT,
    revisado_en      TEXT,
    revisado_por     TEXT,
    actualizado_en   TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS news_busqueda (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor        TEXT NOT NULL,
    consulta         TEXT NOT NULL,
    idioma           TEXT,
    jugador_id       INTEGER,
    resultados       INTEGER,
    creditos         REAL,
    usd_estimado     REAL,
    cache_hasta      TEXT,
    creado_en        TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS news_articulo (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    url              TEXT NOT NULL UNIQUE,
    dominio          TEXT,
    titulo           TEXT,
    fecha_publicacion TEXT,
    idioma           TEXT,
    fragmento        TEXT,
    hash_contenido   TEXT,
    creado_en        TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS news_evento (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    jugador_id       INTEGER NOT NULL REFERENCES news_jugador(id),
    articulo_id      INTEGER REFERENCES news_articulo(id),
    categoria        TEXT NOT NULL,
    direccion        TEXT NOT NULL,                  -- NEGATIVA | POSITIVA | NEUTRA | MIXTA
    naturaleza       TEXT NOT NULL,                  -- HECHO | DECLARACION | NO_VERIFICADA | INTERPRETACION
    nivel            TEXT NOT NULL,                  -- A | B | C
    fecha_evento     TEXT,
    fecha_publicacion TEXT,
    fuente           TEXT,
    enlace           TEXT,
    fragmento_original TEXT,
    resumen_es       TEXT,
    relevancia_deportiva TEXT,                       -- texto corto, NUNCA un número
    confianza_identidad REAL,
    estado           TEXT NOT NULL DEFAULT 'VIGENTE', -- VIGENTE | EN_SEGUIMIENTO | SUPERADO | VENCIDO | DESCARTADO
    vigente_hasta    TEXT,
    superado_por     INTEGER,
    verificar_estado_fisico INTEGER NOT NULL DEFAULT 0,
    lectura1_json    TEXT,
    lectura2_json    TEXT,
    creado_en        TEXT NOT NULL,
    actualizado_en   TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS news_torneo (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre           TEXT NOT NULL,
    circuito         TEXT,
    pais             TEXT,
    superficie       TEXT,
    semana           TEXT,
    fuente_listas    TEXT,
    leido_en         TEXT,
    creado_en        TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS news_partido (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id       INTEGER,
    torneo_id        INTEGER,
    torneo           TEXT,
    circuito         TEXT,
    ronda            TEXT,
    fecha_estimada   TEXT,
    jugador1_id      INTEGER REFERENCES news_jugador(id),
    jugador2_id      INTEGER REFERENCES news_jugador(id),
    origen           TEXT,                           -- MATCH_LOG | FIXTURES_FTR | LISTA_OFICIAL
    estado           TEXT NOT NULL DEFAULT 'PROGRAMADO',
    creado_en        TEXT NOT NULL,
    actualizado_en   TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS news_contexto (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    jugador_id       INTEGER NOT NULL,
    partido_id       INTEGER NOT NULL,
    clave            TEXT NOT NULL,                  -- PUNTOS_DEFENDIDOS | ANTECEDENTE | LOCALIA | CARGA | VIAJE
    valor_json       TEXT,
    estimado         INTEGER NOT NULL DEFAULT 1,
    fuente           TEXT,
    creado_en        TEXT NOT NULL,
    UNIQUE (jugador_id, partido_id, clave));

CREATE TABLE IF NOT EXISTS news_evaluacion (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    partido_id       INTEGER NOT NULL,
    jugador_x_id     INTEGER NOT NULL,               -- el jugador con la noticia
    rival_id         INTEGER NOT NULL,
    eventos_json     TEXT,
    utr_x            REAL, utr_rival REAL, delta_utr REAL,
    utr_x_en         TEXT, utr_rival_en TEXT,
    cuota_x          REAL, cuota_rival REAL, cuota_en TEXT,
    banda_utr        TEXT, banda_mercado TEXT, desvio TEXT,
    direccion_neta   TEXT, nivel TEXT, categoria_fuerte INTEGER,
    conclusion       TEXT,
    tipo_alerta      TEXT NOT NULL,                  -- FUEGO | INTERESANTE | NOTICIA | NADA
    motivo           TEXT,
    texto_discord    TEXT,
    dicho_discord    INTEGER NOT NULL DEFAULT 0,
    dicho_en         TEXT,
    bandas_calibradas INTEGER NOT NULL DEFAULT 0,
    version_motor    TEXT,
    creado_en        TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS news_resultado (
    evaluacion_id    INTEGER PRIMARY KEY,
    ganador_id       INTEGER,
    retiro           INTEGER,
    score            TEXT,
    cuota_cierre_x   REAL,
    cuota_cierre_rival REAL,
    mercado_hacia_noticia INTEGER,
    era_interesante  TEXT,                           -- SI | NO | MERCADO_LO_SABIA (marca manual)
    marcado_por      TEXT,
    cerrado_en       TEXT);

CREATE TABLE IF NOT EXISTS news_revision (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo             TEXT NOT NULL,                  -- OTRA | IDENTIDAD_DUDOSA | CATEGORIA_NUEVA
    evento_id        INTEGER,
    jugador_id       INTEGER,
    detalle          TEXT,
    estado           TEXT NOT NULL DEFAULT 'PENDIENTE',
    resuelto_por     TEXT,
    resuelto_en      TEXT,
    creado_en        TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS news_costos_dia (
    dia              TEXT NOT NULL,
    proveedor        TEXT NOT NULL,
    busquedas        INTEGER NOT NULL DEFAULT 0,
    articulos        INTEGER NOT NULL DEFAULT 0,
    tokens_entrada   INTEGER NOT NULL DEFAULT 0,
    tokens_salida    INTEGER NOT NULL DEFAULT 0,
    usd_estimado     REAL NOT NULL DEFAULT 0,
    actualizado_en   TEXT NOT NULL,
    PRIMARY KEY (dia, proveedor));

CREATE INDEX IF NOT EXISTS ix_news_evento_jugador ON news_evento (jugador_id, estado);
CREATE INDEX IF NOT EXISTS ix_news_partido_fecha ON news_partido (fecha_estimada);
CREATE INDEX IF NOT EXISTS ix_news_eval_partido ON news_evaluacion (partido_id);
"""

# Columnas agregadas después de la Fase 0 (ADD COLUMN idempotente).
_COLUMNAS_NUEVAS = (
    ("news_evento", "partidos_completos_desde", "INTEGER NOT NULL DEFAULT 0"),
    ("news_jugador", "utr_singles", "REAL"),
    ("news_jugador", "utr_en", "TEXT"),
    ("news_jugador", "utr_display", "TEXT"),
    ("news_partido", "cuota1", "REAL"),
    ("news_partido", "cuota2", "REAL"),
    ("news_partido", "cuota1_apertura", "REAL"),
    ("news_partido", "cuota2_apertura", "REAL"),
    ("news_partido", "cuota_en", "TEXT"),
    ("news_partido", "genero", "TEXT"),
    ("news_partido", "superficie", "TEXT"),
    ("news_partido", "jugador1_nombre", "TEXT"),
    ("news_partido", "jugador2_nombre", "TEXT"),
    ("news_evaluacion", "texto_voz", "TEXT"),
    ("news_evaluacion", "fixture_id", "INTEGER"),
    ("news_evaluacion", "actualizado_en", "TEXT"),
    ("news_evaluacion", "dicho_motivo", "TEXT"),
    ("news_jugador_cola", "ultimo_error", "TEXT"),
)


def ensure_tablas(conn: sqlite3.Connection) -> None:
    """Idempotente y barato (IF NOT EXISTS + ADD COLUMN si falta); se corre al
    abrir cada conexión. No se cachea por id(conn): los ids se reutilizan."""
    conn.executescript(_ESQUEMA)
    for tabla, col, tipo in _COLUMNAS_NUEVAS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")
    conn.commit()


def estado_set(conn, clave: str, valor) -> None:
    def _w():
        conn.execute("INSERT INTO news_estado (clave, valor, actualizado_en) VALUES (?,?,?) "
                     "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor, "
                     "actualizado_en=excluded.actualizado_en", (clave, str(valor), ahora_iso()))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def estado_todo(conn) -> dict:
    return {r["clave"]: {"valor": r["valor"], "en": r["actualizado_en"]}
            for r in conn.execute("SELECT * FROM news_estado").fetchall()}


def config_guardar(conn, clave: str, valor, por: str = "") -> None:
    if clave not in config.DEFAULTS:
        raise ValueError(f"Parámetro desconocido: {clave}")

    def _w():
        conn.execute("INSERT INTO news_config (clave, valor, actualizado_en, actualizado_por) VALUES (?,?,?,?) "
                     "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor, actualizado_en=excluded.actualizado_en, "
                     "actualizado_por=excluded.actualizado_por", (clave, str(valor), ahora_iso(), por))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)
