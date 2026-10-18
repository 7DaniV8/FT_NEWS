"""
ft_news/lectores/telegram.py — 📡 PISTAS DE CANALES DE TELEGRAM (v8.0, 18/10/2026).

Rubén (12/10): el canal de noticias de Telegram («ALL News»: MTO, retiros, bajas, declaraciones) entra SOLO COMO PISTA:
se comprueba con fuentes permitidas y se redacta con texto propio, sin copiar ni republicar sus mensajes.
Rubén (18/10): «que funcione, que envíe alertas» y «al ser varios canales, que se puedan configurar todos desde el Admin».

Recorrido:
  Reenvio_MTO (Telethon) lee los canales elegidos en Admin → 📰 FT NEWS → 📡 Canales de Telegram
    → RankingFTR /news-telegram/registrar → FT_NEWS POST /news/telegram/pista  (este módulo: `recibir`)
  `procesar` (al recibir, en segundo plano, y en cada ciclo del worker):
    1. DUPLICADA: el mismo texto ya llegó por otro canal (los canales de noticias se repiten entre sí) → se suma el canal.
    2. ¿De quién habla? Los mensajes empiezan con el APELLIDO en la primera línea («Pinnington Jones», «Burel»): se
       busca en el padrón; si hay varios con ese apellido, se queda el que tiene partido programado (y el género del
       texto: she/her vs he/his); si siguen varios → AMBIGUA (no se adivina). Sin apellido arriba, nombres completos.
    3. ¿Interesa? En canales «lesiones» solo pasa lo que habla de lesión, baja, retiro, enfermedad, regreso o MTO;
       en canales «todo», también lo demás si el jugador tiene partido cerca. Lo otro: SIN_INTERES (sin gastar IA).
    4. El clasificador (Gemini/Claude, el mismo de los artículos) lo lee para ESE jugador y escribe un resumen en
       español con texto propio. No se crea ninguna noticia con esto.
    5. Si es fuerte (lesión, enfermedad, retiro/baja, regreso, sanción) y no es de dobles → VERIFICANDO: el jugador
       pasa al frente de la cola del radar, que lo busca en las fuentes AUTORIZADAS. Lo débil → INFORMATIVA.
    6. CONFIRMADA: cuando una fuente permitida (o un retiro en nuestros propios resultados) deja una noticia vigente del
       mismo tipo para ese jugador dentro de la ventana (`memoria.guardar_evento_db` llama a `confirmar_por_evento`).
       La alerta 📰 / 🔎 / 🔥 sale por el camino de siempre, con la noticia confirmada. Si nada la confirma en
       NEWS_TELEGRAM_CONFIRMAR_H horas → SIN_CONFIRMAR (queda guardada, nunca sale).
Una pista sola nunca crea una alerta ni aparece en la portada.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import costos
from ft_news import jugadores as jg
from ft_news import taxonomia as tx
from ft_news.db import ejecutar_con_reintento

log = logging.getLogger("ft_news")

_TABLA = """
CREATE TABLE IF NOT EXISTS news_pista (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    canal_id          TEXT,                 -- id del canal en Admin de RankingFTR
    canal             TEXT,                 -- título del canal
    chat_id           TEXT,
    msg_id            INTEGER,
    modo              TEXT,                 -- lesiones | todo
    texto             TEXT NOT NULL,        -- solo para leerlo; nunca se publica
    huella            TEXT NOT NULL,        -- texto normalizado → hash (duplicados entre canales)
    fecha_mensaje     TEXT,
    recibido_en       TEXT NOT NULL,
    estado            TEXT NOT NULL,        -- RECIBIDA | PROCESANDO | DUPLICADA | SIN_JUGADOR | AMBIGUA | SIN_INTERES |
                                            -- DESCARTADA | INFORMATIVA | VERIFICANDO | CONFIRMADA | SIN_CONFIRMAR | ERROR
    motivo            TEXT,
    duplicada_de      INTEGER,
    canales_json      TEXT,                 -- otros canales que mandaron lo mismo
    apellido          TEXT,
    jugador_id        INTEGER,
    candidatos_json   TEXT,
    palabras          TEXT,                 -- palabras de lesión/baja/regreso encontradas
    categoria         TEXT,
    direccion         TEXT,
    naturaleza        TEXT,
    resumen_es        TEXT,                 -- texto propio del clasificador
    titular           TEXT,
    confianza         REAL,
    partido_id        INTEGER,
    partido_txt       TEXT,
    evento_id         INTEGER,              -- la noticia de fuente permitida que la confirmó
    confirmada_en     TEXT,
    intentos          INTEGER DEFAULT 0,
    procesado_en      TEXT,
    actualizado_en    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pista_msg ON news_pista(chat_id, msg_id);
CREATE INDEX IF NOT EXISTS idx_pista_huella ON news_pista(huella, recibido_en);
CREATE INDEX IF NOT EXISTS idx_pista_estado ON news_pista(estado, recibido_en);
CREATE INDEX IF NOT EXISTS idx_pista_jugador ON news_pista(jugador_id, estado);
"""

ESTADO_TXT = {
    "RECIBIDA": "recibida, esperando lectura",
    "PROCESANDO": "leyéndose",
    "DUPLICADA": "ya había llegado por otro canal",
    "SIN_JUGADOR": "no nombra a nadie que vigilemos",
    "AMBIGUA": "hay varios jugadores con ese apellido: no se adivina",
    "SIN_INTERES": "no habla de lesión, baja, retiro, enfermedad ni regreso",
    "DESCARTADA": "el clasificador dice que no es de ese jugador o no es un hecho",
    "INFORMATIVA": "leída: no es una noticia fuerte (no se verifica)",
    "VERIFICANDO": "noticia fuerte: buscándola en fuentes autorizadas",
    "CONFIRMADA": "confirmada por una fuente autorizada: sigue el camino normal de alertas",
    "SIN_CONFIRMAR": "ninguna fuente autorizada la confirmó a tiempo: no sale",
    "ERROR": "no se pudo leer (se reintenta)",
}
MAX_INTENTOS = 4
_PALABRAS = re.compile(
    r"\b(withdr\w*|pull(?:ed|s|ing)? out|out of (?:the )?(?:tournament|event|draw|qualifying|match|season|tour)|walkover|w/o|"
    r"retire[ds]?|retiring|retirement|injur\w*|ankle|knee|wrist|shoulder|elbow|back (?:injury|pain|problem)|hip|abdominal|"
    r"hamstring|calf|thigh|groin|strain\w*|sprain\w*|torn|fractur\w*|surgery|illness|sick\w*|virus|flu|fever|covid|"
    r"stomach|blister\w*|cramp\w*|pain|medical|mto|physio|unwell|exhaust\w*|comeback|"
    r"return(?:s|ed|ing)? (?:to|from) (?:action|court|competition|the tour|play|tennis|injury)|back (?:on court|in action)|"
    r"sidelined|lay ?off|suspen(?:ded|sion)|banned|"
    r"lesi[oó]n\w*|lesionad\w*|baja|retir[oó]|retirad\w*|abandon\w*|enferm\w*|molestia\w*|regres\w*|"
    r"infortun\w*|ritir\w*|forfait|bless\w*)\b", re.IGNORECASE)
_ELLA = re.compile(r"\b(she|her|hers|herself)\b", re.IGNORECASE)
_EL = re.compile(r"\b(he|his|him|himself)\b", re.IGNORECASE)
_FAMILIA = {"LESION_MOLESTIA": "fisico", "ENFERMEDAD": "fisico", "RETIRO_ABANDONO": "fisico", "CARGA_FISICA": "fisico",
            "REGRESO": "regreso", "SANCION_DISCIPLINA": "sancion"}


def ensure(conn) -> None:
    conn.executescript(_TABLA)


def _ahora(ahora: Optional[datetime]) -> datetime:
    return ahora or datetime.now(timezone.utc)


def _plano(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def huella(texto: str) -> str:
    return hashlib.sha1(_plano(texto)[:600].encode()).hexdigest()


def _dt(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _upd(conn, pid: int, **campos) -> None:
    campos["actualizado_en"] = datetime.now(timezone.utc).isoformat()
    cols = ", ".join(f"{k}=?" for k in campos)

    def _w():
        conn.execute(f"UPDATE news_pista SET {cols} WHERE id=?", tuple(campos.values()) + (pid,))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


# ─────────────────────────────────────────────────────────────────────────────
#  Recepción
# ─────────────────────────────────────────────────────────────────────────────

def recibir(conn, datos: dict, ahora: Optional[datetime] = None) -> dict:
    """Guarda el mensaje (rápido, sin IA). Devuelve {ok, id, nuevo, estado}."""
    ensure(conn)
    ahora = _ahora(ahora)
    texto = str(datos.get("texto") or "").strip()
    if not texto:
        return {"ok": False, "motivo": "texto vacío"}
    chat_id, msg_id = str(datos.get("chat_id") or ""), datos.get("msg_id")
    if chat_id and msg_id is not None:
        r = conn.execute("SELECT id, estado FROM news_pista WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)).fetchone()
        if r:
            return {"ok": True, "id": r["id"], "nuevo": False, "estado": r["estado"]}
    modo = "todo" if str(datos.get("modo") or "").lower() == "todo" else "lesiones"

    def _w():
        cur = conn.execute(
            "INSERT INTO news_pista (canal_id, canal, chat_id, msg_id, modo, texto, huella, fecha_mensaje, recibido_en, estado, "
            "intentos, actualizado_en) VALUES (?,?,?,?,?,?,?,?,?, 'RECIBIDA', 0, ?)",
            (str(datos.get("canal_id") or ""), (datos.get("canal") or "")[:120], chat_id, msg_id, modo, texto[:4000],
             huella(texto), datos.get("fecha") or ahora.isoformat(), ahora.isoformat(), ahora.isoformat()))
        conn.commit()
        return cur.lastrowid
    pid = ejecutar_con_reintento(_w, conn=conn)
    return {"ok": True, "id": pid, "nuevo": True, "estado": "RECIBIDA"}


# ─────────────────────────────────────────────────────────────────────────────
#  ¿De quién habla?
# ─────────────────────────────────────────────────────────────────────────────

def apellido_de(texto: str) -> Optional[str]:
    """La primera línea, si es solo un apellido (1–4 palabras, sin puntuación de frase)."""
    for linea in (texto or "").splitlines():
        l = linea.strip().strip("*_").strip()
        if not l:
            continue
        if len(l) <= 40 and re.fullmatch(r"[^\W\d_][^\W\d_'’\-. ]*(?:[ '’\-][^\W\d_][^\W\d_'’\-.]*){0,3}\.?", l):
            return l.rstrip(".")
        return None
    return None


def _persona(fila: dict):
    return ("u", fila["utr_player_id"]) if fila.get("utr_player_id") else \
        (("f", fila["player_id_ftr"]) if fila.get("player_id_ftr") else ("i", fila["id"]))


def _con_partido(conn, ids: list, ahora: datetime) -> set:
    if not ids:
        return set()
    q = ",".join("?" * len(ids))
    desde, hasta = (ahora - timedelta(days=1)).isoformat(), (ahora + timedelta(days=7)).isoformat()
    filas = conn.execute(f"SELECT jugador1_id, jugador2_id FROM news_partido WHERE estado='PROGRAMADO' "
                         f"AND (jugador1_id IN ({q}) OR jugador2_id IN ({q})) "
                         f"AND (fecha_estimada IS NULL OR (fecha_estimada >= ? AND fecha_estimada <= ?))",
                         tuple(ids) + tuple(ids) + (desde, hasta)).fetchall()
    out = set()
    for f in filas:
        out.update({f[0], f[1]})
    return out & set(ids)


def candidatos_por_apellido(conn, apellido: str) -> list[dict]:
    toks = [t for t in jg.normalizar(apellido).split() if len(t) >= 2]
    if not toks:
        return []
    cond = " AND ".join("(' ' || nombre_norm || ' ') LIKE ?" for _ in toks)
    filas = [dict(r) for r in conn.execute(
        f"SELECT id, nombre, nombre_norm, genero, pais, circuito, utr_player_id, player_id_ftr FROM news_jugador WHERE {cond}",
        tuple(f"% {t} %" for t in toks)).fetchall()]
    return [f for f in filas if len(f["nombre_norm"].split()) > len(toks)]       # apellido + al menos un nombre


def identificar(conn, texto: str, ahora: Optional[datetime] = None) -> dict:
    """{'jugador': fila | None, 'apellido', 'candidatos': [...], 'motivo'}"""
    ahora = _ahora(ahora)
    ap = apellido_de(texto)
    filas = candidatos_por_apellido(conn, ap) if ap else []
    if not filas:                                      # sin apellido arriba (o no está): nombres completos del texto
        filas = jg.buscar_en_texto(conn, texto)[:6]
        filas = [dict(conn.execute("SELECT id, nombre, nombre_norm, genero, pais, circuito, utr_player_id, player_id_ftr "
                                   "FROM news_jugador WHERE id=?", (f["id"],)).fetchone()) for f in filas]
    if not filas:
        return {"jugador": None, "apellido": ap, "candidatos": [], "motivo": "SIN_JUGADOR"}
    personas: dict = {}
    for f in filas:
        personas.setdefault(_persona(f), []).append(f)
    con_p = _con_partido(conn, [f["id"] for f in filas], ahora)

    def elegir(grupo):                                  # de las filas de una persona: la que tiene partido, si no la más larga
        g = sorted(grupo, key=lambda f: (f["id"] not in con_p, -len(f["nombre"] or "")))
        return g[0]
    elegidas = [elegir(g) for g in personas.values()]
    resto = elegidas
    if len(resto) > 1:
        genero = "F" if _ELLA.search(texto) and not _EL.search(texto) else ("M" if _EL.search(texto) and not _ELLA.search(texto) else None)
        if genero:
            r2 = [f for f in resto if (f.get("genero") or genero) == genero]
            resto = r2 or resto
    if len(resto) > 1:
        r2 = [f for f in resto if f["id"] in con_p]
        resto = r2 if r2 else resto
    cand = [{"id": f["id"], "nombre": f["nombre"], "partido": f["id"] in con_p} for f in elegidas][:8]
    if len(resto) != 1:
        return {"jugador": None, "apellido": ap, "candidatos": cand, "motivo": "AMBIGUA"}
    return {"jugador": resto[0], "apellido": ap, "candidatos": cand, "motivo": None}


# ─────────────────────────────────────────────────────────────────────────────
#  Procesamiento
# ─────────────────────────────────────────────────────────────────────────────

def _tomar(conn, pid: int, ahora: datetime) -> bool:
    """Reserva la pista para que el worker y el procesamiento inmediato no la lean dos veces."""
    def _w():
        cur = conn.execute("UPDATE news_pista SET estado='PROCESANDO', procesado_en=?, actualizado_en=? "
                           "WHERE id=? AND (estado IN ('RECIBIDA','ERROR') OR (estado='PROCESANDO' AND procesado_en < ?))",
                           (ahora.isoformat(), ahora.isoformat(), pid, (ahora - timedelta(minutes=10)).isoformat()))
        conn.commit()
        return cur.rowcount == 1
    return bool(ejecutar_con_reintento(_w, conn=conn))


def _clasificadas_hoy(conn, ahora: datetime) -> int:
    return conn.execute("SELECT COUNT(*) FROM news_pista WHERE categoria IS NOT NULL AND procesado_en >= ?",
                        (ahora.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),)).fetchone()[0]


def procesar(conn, cfg: dict, clasificador, ahora: Optional[datetime] = None, limite: int = 40) -> dict:
    ensure(conn)
    ahora = _ahora(ahora)
    res = {"leidas": 0, "por_estado": {}, "vencidas": vencer(conn, cfg, ahora)}
    if not int(cfg.get("NEWS_TELEGRAM_ACTIVO", 1)):
        res["motivo"] = "NEWS_TELEGRAM_ACTIVO=0"
        return res
    filas = conn.execute("SELECT id FROM news_pista WHERE (estado='RECIBIDA' OR (estado='ERROR' AND intentos < ?) "
                         "OR (estado='PROCESANDO' AND procesado_en < ?)) ORDER BY recibido_en LIMIT ?",
                         (MAX_INTENTOS, (ahora - timedelta(minutes=10)).isoformat(), limite)).fetchall()
    for f in filas:
        if not _tomar(conn, f["id"], ahora):
            continue
        try:
            estado = _procesar_una(conn, cfg, clasificador, f["id"], ahora)
        except Exception as e:                                    # una pista rota no tumba las demás
            log.warning("[FT_NEWS] pista %s: %s", f["id"], e)
            conn.execute("UPDATE news_pista SET intentos=COALESCE(intentos,0)+1 WHERE id=?", (f["id"],))
            conn.commit()
            _upd(conn, f["id"], estado="ERROR", motivo=f"error: {e}"[:300])
            estado = "ERROR"
        res["leidas"] += 1
        res["por_estado"][estado] = res["por_estado"].get(estado, 0) + 1
    return res


def _procesar_una(conn, cfg: dict, clasificador, pid: int, ahora: datetime) -> str:
    p = dict(conn.execute("SELECT * FROM news_pista WHERE id=?", (pid,)).fetchone())
    texto = p["texto"]
    # 1. el mismo mensaje por otro canal (48 h)
    orig = conn.execute("SELECT id, canales_json FROM news_pista WHERE huella=? AND id<>? AND estado<>'DUPLICADA' "
                        "AND recibido_en >= ? ORDER BY id LIMIT 1",
                        (p["huella"], pid, (ahora - timedelta(hours=48)).isoformat())).fetchone()
    if orig and orig["id"] < pid:
        canales = json.loads(orig["canales_json"] or "[]")
        if p["canal"] and p["canal"] not in canales:
            canales.append(p["canal"])
            _upd(conn, orig["id"], canales_json=json.dumps(canales, ensure_ascii=False))
        _upd(conn, pid, estado="DUPLICADA", duplicada_de=orig["id"], motivo=f"igual a la pista #{orig['id']}")
        return "DUPLICADA"
    # 2. ¿de quién?
    idn = identificar(conn, texto, ahora)
    palabras = sorted({m.group(0).lower() for m in _PALABRAS.finditer(texto)})[:12]
    base = {"apellido": idn["apellido"], "candidatos_json": json.dumps(idn["candidatos"], ensure_ascii=False),
            "palabras": ", ".join(palabras) or None}
    if idn["jugador"] is None:
        motivo = ("nadie del padrón con ese apellido" if idn["apellido"] else "no nombra a nadie del padrón") \
            if idn["motivo"] == "SIN_JUGADOR" else f"{len(idn['candidatos'])} jugadores posibles"
        _upd(conn, pid, estado=idn["motivo"], motivo=motivo, **base)
        return idn["motivo"]
    j = idn["jugador"]
    from ft_news import alertas
    prox = alertas.proximo_partido(conn, j["id"], ahora)
    partido = {"partido_id": prox["id"] if prox else None,
               "partido_txt": (f"vs {prox['rival']} · {prox.get('torneo') or ''} · {prox.get('fecha_estimada') or ''}".strip(" ·")
                               if prox else None)}
    # 3. ¿interesa?
    if not palabras and not (p["modo"] == "todo" and prox):
        _upd(conn, pid, estado="SIN_INTERES", jugador_id=j["id"],
             motivo="no habla de lesión, baja, retiro, enfermedad ni regreso" + ("" if prox else " (y no tiene partido cerca)"),
             **base, **partido)
        return "SIN_INTERES"
    # 4. lectura con IA (con tope diario y presupuesto)
    if clasificador is None:
        _upd(conn, pid, estado="RECIBIDA", jugador_id=j["id"], motivo="sin clasificador (GEMINI_API_KEY / ANTHROPIC_API_KEY)",
             **base, **partido)
        return "RECIBIDA"
    tope = int(cfg.get("NEWS_TELEGRAM_MAX_DIA", 80))
    if _clasificadas_hoy(conn, ahora) >= tope or not costos.puede_gastar(conn, cfg)["ok"]:
        _upd(conn, pid, estado="RECIBIDA", jugador_id=j["id"], motivo=f"tope diario de lecturas ({tope}) o presupuesto: mañana",
             **base, **partido)
        return "RECIBIDA"
    jug = {"jugador_id": j["id"], "nombre": j["nombre"], "pais": j.get("pais"), "genero": j.get("genero"),
           "circuito": j.get("circuito")}
    primera = next((l.strip() for l in texto.splitlines() if l.strip()), "")
    art = {"url": f"telegram://{p['chat_id']}/{p['msg_id']}", "dominio": "telegram", "titulo": primera[:120],
           "contenido": texto, "fecha_publicacion": p["fecha_mensaje"], "idioma": None}
    r = clasificador.clasificar(jug, art)
    costos.anotar(conn, getattr(clasificador, "nombre", "gemini"), tokens_entrada=r.get("tokens_entrada", 0),
                  tokens_salida=r.get("tokens_salida", 0), usd=r.get("usd", 0.0), articulos=1)
    if not r.get("ok"):
        conn.execute("UPDATE news_pista SET intentos=COALESCE(intentos,0)+1 WHERE id=?", (pid,))
        conn.commit()
        _upd(conn, pid, estado="ERROR", jugador_id=j["id"], motivo=f"lectura: {r.get('error')}"[:300], **base, **partido)
        return "ERROR"
    d = r["datos"]
    leido = {"jugador_id": j["id"], "categoria": d.get("categoria"), "direccion": d.get("direccion"),
             "naturaleza": d.get("naturaleza"), "resumen_es": (d.get("resumen_es") or "")[:280],
             "titular": (d.get("titular") or "")[:80] or None, "confianza": float(d.get("confianza_identidad") or 0)}
    if not d.get("sobre_jugador") or leido["confianza"] < 0.6:
        _upd(conn, pid, estado="DESCARTADA", motivo=f"no es de {j['nombre']} (identidad {leido['confianza']:.2f})",
             **leido, **base, **partido)
        return "DESCARTADA"
    ev_txt = {"titular": leido["titular"], "resumen_es": leido["resumen_es"], "fragmento_original": texto[:600],
              "categoria": leido["categoria"]}
    if tx.es_dobles(ev_txt):
        _upd(conn, pid, estado="INFORMATIVA", motivo="es de dobles: no dice nada de su individual", **leido, **base, **partido)
        return "INFORMATIVA"
    if not tx.es_fuerte(leido["categoria"] or "") or leido["direccion"] == "NEUTRA":
        _upd(conn, pid, estado="INFORMATIVA", motivo=f"{leido['categoria']}: no es noticia fuerte", **leido, **base, **partido)
        return "INFORMATIVA"
    # 5. fuerte → que el radar la busque YA en las fuentes autorizadas
    alertas.adelantar(conn, j["id"], ahora, "PISTA_TELEGRAM")
    _upd(conn, pid, estado="VERIFICANDO", motivo=f"{leido['categoria']}: el radar la busca en fuentes autorizadas",
         **leido, **base, **partido)
    return "VERIFICANDO"


# ─────────────────────────────────────────────────────────────────────────────
#  Confirmación y vencimiento
# ─────────────────────────────────────────────────────────────────────────────

def confirmar_por_evento(conn, ev: dict, evento_id: int) -> int:
    """La llama memoria.guardar_evento_db: una noticia vigente de fuente permitida (o un retiro en nuestros propios
    resultados) confirma las pistas del mismo jugador y tipo que estaban VERIFICANDO. Devuelve cuántas confirmó."""
    try:
        if ev.get("estado") != "VIGENTE" or str(ev.get("fuente") or "") == "telegram":
            return 0
        fam = _FAMILIA.get(str(ev.get("categoria") or ""))
        if not fam:
            return 0
        if ev.get("origen") == "INTERNO" and ev.get("categoria") != "RETIRO_ABANDONO":
            return 0                                            # lo calculado (carga, calendario) no confirma nada
        if tx.es_dobles(ev):
            return 0
        if not conn.execute("SELECT name FROM sqlite_master WHERE name='news_pista'").fetchone():
            return 0
        ahora = datetime.now(timezone.utc)
        filas = conn.execute("SELECT id, categoria, recibido_en FROM news_pista WHERE jugador_id=? AND estado='VERIFICANDO'",
                             (ev.get("jugador_id"),)).fetchall()
        fecha_ev = _dt(ev.get("fecha_evento"))
        n = 0
        for f in filas:
            if _FAMILIA.get(f["categoria"] or "") != fam:
                continue
            rec = _dt(f["recibido_en"])
            if fecha_ev and rec and fecha_ev < rec - timedelta(days=3):
                continue                                        # la noticia es de otro episodio, más viejo
            conn.execute("UPDATE news_pista SET estado='CONFIRMADA', evento_id=?, confirmada_en=?, actualizado_en=?, "
                         "motivo=? WHERE id=?",
                         (evento_id, ahora.isoformat(), ahora.isoformat(),
                          f"confirmada por {ev.get('fuente') or 'nuestros resultados'} (noticia #{evento_id})", f["id"]))
            n += 1
        if n:
            conn.commit()
        return n
    except Exception as e:                                       # nunca tumba el guardado de la noticia
        log.warning("[FT_NEWS] confirmar pistas: %s", e)
        return 0


def vencer(conn, cfg: dict, ahora: Optional[datetime] = None) -> int:
    ensure(conn)
    ahora = _ahora(ahora)
    h = int(cfg.get("NEWS_TELEGRAM_CONFIRMAR_H", 72))

    def _w():
        cur = conn.execute("UPDATE news_pista SET estado='SIN_CONFIRMAR', actualizado_en=?, "
                           "motivo=? WHERE estado='VERIFICANDO' AND recibido_en < ?",
                           (ahora.isoformat(), f"ninguna fuente autorizada la confirmó en {h} h",
                            (ahora - timedelta(hours=h)).isoformat()))
        conn.commit()
        return cur.rowcount
    return ejecutar_con_reintento(_w, conn=conn) or 0


# ─────────────────────────────────────────────────────────────────────────────
#  Para Admin
# ─────────────────────────────────────────────────────────────────────────────

def listar(conn, limite: int = 100, estado: Optional[str] = None, ahora: Optional[datetime] = None) -> dict:
    ensure(conn)
    ahora = _ahora(ahora)
    q = ("SELECT p.*, j.nombre AS jugador FROM news_pista p LEFT JOIN news_jugador j ON j.id=p.jugador_id "
         + ("WHERE p.estado=? " if estado else "") + "ORDER BY p.id DESC LIMIT ?")
    filas = [dict(r) for r in conn.execute(q, ((estado,) if estado else ()) + (limite,)).fetchall()]
    for f in filas:
        f["estado_txt"] = ESTADO_TXT.get(f["estado"], f["estado"])
        f["canales"] = [f["canal"]] + json.loads(f.get("canales_json") or "[]")
        f["candidatos"] = json.loads(f.get("candidatos_json") or "[]")
        rec, conf = _dt(f.get("recibido_en")), _dt(f.get("confirmada_en"))
        f["minutos_hasta_confirmar"] = round((conf - rec).total_seconds() / 60) if rec and conf else None
        for k in ("canales_json", "candidatos_json", "huella"):
            f.pop(k, None)
    desde = (ahora - timedelta(hours=24)).isoformat()
    por_estado = dict(conn.execute("SELECT estado, COUNT(*) FROM news_pista WHERE recibido_en >= ? GROUP BY estado",
                                   (desde,)).fetchall())
    por_canal = [dict(zip(("canal", "mensajes", "ultimo"), r)) for r in conn.execute(
        "SELECT canal, COUNT(*), MAX(recibido_en) FROM news_pista WHERE recibido_en >= ? GROUP BY canal ORDER BY 2 DESC",
        (desde,)).fetchall()]
    return {"pistas": filas, "ultimas_24h": {"por_estado": por_estado, "por_canal": por_canal,
                                             "total": sum(por_estado.values())},
            "estados": ESTADO_TXT,
            "regla": ("Una pista de Telegram nunca es noticia ni alerta por sí sola: si es fuerte, FT NEWS la busca en las "
                      "fuentes autorizadas y solo lo confirmado sigue el camino normal (📰 / 🔎 / 🔥).")}
