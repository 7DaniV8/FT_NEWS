"""v8.1 (04/11/2026): 📡 LIVE — el flujo cronológico de novedades (estilo «últimas noticias»), hecho de forma AUTOMÁTICA.

Qué es: una sola lista, de más nueva a más vieja, con etiqueta (ENTRY LIST · INFORMACIÓN · DECLARACIONES · MOLESTIAS · LESIÓN ·
SEGUIMIENTO), jugador, torneo y si está CONFIRMADO o SIN_CONFIRMAR. Se alimenta SOLO de lo que FT NEWS ya sabe:

  · EVENTO    noticias ya clasificadas y con fuente (news_evento). Siempre CONFIRMADO por la regla de FT NEWS.
  · PISTA     canales de Telegram. Solo si NEWS_LIVE_PISTAS=1 (por defecto 0) y siempre marcadas SIN_CONFIRMAR hasta que una
              fuente autorizada las confirme; entonces pasan solas a CONFIRMADO.
  · CALCULADO «Fulano, con una molestia reportada, juega hoy contra Mengano» (cruce de nuestras noticias con la agenda).
  · MANUAL    mesa de redacción (admin): se escribe a mano o se aprueba un borrador.

Nada se copia de otra web. Es solo lectura sobre nuestras propias tablas más su propia tabla `news_live` (idempotente por `clave`).
Un fallo aquí nunca tumba el resto del ciclo (va como un paso más del worker)."""
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import portada

ETIQUETAS = ("ENTRY LIST", "INFORMACIÓN", "DECLARACIONES", "MOLESTIAS", "LESIÓN", "DESGASTE", "VIAJES", "SEGUIMIENTO")
ESTADOS = ("PUBLICADO", "BORRADOR", "OCULTO")
ORIGENES = ("EVENTO", "PISTA", "CALCULADO", "MANUAL")
MAX_LISTA = 200
VENTANA_CALCULADO_H = 30          # partidos de las próximas horas

# categoría de FT NEWS → etiqueta del LIVE. Lo que no está aquí (OTRA, RESULTADO_RECIENTE…) no es noticia de LIVE.
ETIQUETA_DE = {
    "LESION_MOLESTIA": "MOLESTIAS", "ENFERMEDAD": "MOLESTIAS", "RETIRO_ABANDONO": "LESIÓN",
    "DECLARACION_PREPARACION": "DECLARACIONES", "DECLARACION_MOTIVACION": "DECLARACIONES",
    "REGRESO": "INFORMACIÓN", "SANCION_DISCIPLINA": "INFORMACIÓN", "CAMBIO_EQUIPO": "INFORMACIÓN",
    "SITUACION_PERSONAL": "INFORMACIÓN", "PUNTOS_DEFENDIDOS": "INFORMACIÓN", "RANKING_OBJETIVO": "INFORMACIÓN",
    "VIAJE_CALENDARIO": "VIAJES", "CARGA_FISICA": "DESGASTE",
}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS news_live (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clave       TEXT NOT NULL UNIQUE,
    ocurrio_en  TEXT NOT NULL,
    publicado_en TEXT NOT NULL,
    etiqueta    TEXT NOT NULL,
    titulo      TEXT NOT NULL,
    texto       TEXT,
    jugador_id  INTEGER,
    jugador     TEXT,
    torneo      TEXT,
    circuito    TEXT,
    nivel       TEXT NOT NULL DEFAULT 'CONFIRMADO',
    origen      TEXT NOT NULL,
    fuente      TEXT,
    enlace      TEXT,
    ref_id      INTEGER,
    estado      TEXT NOT NULL DEFAULT 'PUBLICADO',
    por         TEXT);
CREATE INDEX IF NOT EXISTS idx_live_fecha ON news_live(ocurrio_en);
"""


def asegurar(conn) -> None:
    conn.executescript(_ESQUEMA)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def _tiene(conn, tabla: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)).fetchone())


def _poner(conn, f: dict) -> str:
    """Inserta o actualiza por clave. Devuelve 'nuevo' | 'actualizado' | 'igual'. Una fila OCULTA a mano NO se reabre sola."""
    r = conn.execute("SELECT id, nivel, estado, titulo, texto, etiqueta FROM news_live WHERE clave=?", (f["clave"],)).fetchone()
    if r is None:
        conn.execute(
            "INSERT INTO news_live (clave, ocurrio_en, publicado_en, etiqueta, titulo, texto, jugador_id, jugador, torneo, circuito, "
            "nivel, origen, fuente, enlace, ref_id, estado, por) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["clave"], f["ocurrio_en"], f["publicado_en"], f["etiqueta"], f["titulo"], f.get("texto"), f.get("jugador_id"),
             f.get("jugador"), f.get("torneo"), f.get("circuito"), f.get("nivel", "CONFIRMADO"), f["origen"], f.get("fuente"),
             f.get("enlace"), f.get("ref_id"), f.get("estado", "PUBLICADO"), f.get("por")))
        return "nuevo"
    cambios = {}
    if f["origen"] in ("EVENTO", "CALCULADO") and f.get("etiqueta") and f["etiqueta"] != r["etiqueta"]:
        cambios["etiqueta"] = f["etiqueta"]
    if f.get("nivel") and f["nivel"] != r["nivel"]:
        cambios["nivel"] = f["nivel"]
    if f.get("estado") == "OCULTO" and r["estado"] == "PUBLICADO":
        cambios["estado"] = "OCULTO"                 # la noticia ya no vale (desmentida/vencida)
    if f.get("titulo") and f["titulo"] != r["titulo"] and f["origen"] in ("EVENTO", "CALCULADO"):
        cambios["titulo"] = f["titulo"]
        cambios["texto"] = f.get("texto")
    if not cambios:
        return "igual"
    sets = ", ".join(f"{k}=?" for k in cambios)
    conn.execute(f"UPDATE news_live SET {sets} WHERE id=?", (*cambios.values(), r["id"]))
    return "actualizado"


def desde_eventos(conn, cfg, ahora: datetime) -> dict:
    dias = int(cfg.get("NEWS_LIVE_DIAS", 3) or 3)
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(news_evento)")}
    extra = [c for c in ("origen", "titular") if c in cols]
    filas = [dict(r) for r in cur.execute(
        "SELECT id, jugador_id, articulo_id, categoria, direccion, naturaleza, nivel, fecha_evento, fecha_publicacion, fuente, enlace, "
        f"resumen_es, fragmento_original, confianza_identidad, estado, creado_en{''.join(', ' + c for c in extra)} FROM news_evento "
        "WHERE creado_en >= ? ORDER BY id DESC LIMIT 600", ((ahora - timedelta(days=dias + 7)).isoformat(),)).fetchall()]
    jug = portada._jugadores(conn, {f["jugador_id"] for f in filas})
    corte = ahora - timedelta(days=dias)
    out = {"nuevo": 0, "actualizado": 0, "igual": 0}
    for ev in filas:
        et = ETIQUETA_DE.get(ev["categoria"])
        if not et:
            continue
        j = jug.get(ev["jugador_id"]) or {}
        fecha = portada._fecha_ev(ev) or ahora
        fuera = ev["estado"] in portada.ESTADOS_FUERA
        if fecha < corte and not fuera:
            continue
        pub = portada._evento_publico(ev, j)
        f = {"clave": f"ev:{ev['id']}", "ocurrio_en": _iso(fecha), "publicado_en": _iso(ahora), "etiqueta": et,
             "titulo": pub["titular"], "texto": pub["resumen"] or pub["afecta"] or None, "jugador_id": ev["jugador_id"],
             "jugador": pub["jugador"], "torneo": j.get("ultimo_torneo"), "circuito": pub["circuito"] or None,
             "nivel": "CONFIRMADO", "origen": "EVENTO", "fuente": pub["fuente"], "enlace": pub["enlace"], "ref_id": ev["id"],
             "estado": "OCULTO" if fuera else "PUBLICADO"}
        out[_poner(conn, f)] += 1
    conn.commit()
    return out


def desde_pistas(conn, cfg, ahora: datetime) -> dict:
    """Pistas de Telegram. Apagado por defecto: decide Rubén si el LIVE enseña algo SIN_CONFIRMAR (siempre rotulado así)."""
    if not int(cfg.get("NEWS_LIVE_PISTAS", 0) or 0) or not _tiene(conn, "news_pista"):
        return {"activo": 0}
    dias = int(cfg.get("NEWS_LIVE_DIAS", 3) or 3)
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    filas = [dict(r) for r in cur.execute(
        "SELECT id, jugador_id, categoria, estado, titular, resumen_es, recibido_en, fecha_mensaje FROM news_pista "
        "WHERE recibido_en >= ? AND jugador_id IS NOT NULL AND categoria IS NOT NULL "
        "AND COALESCE(canal_id,'') != 'tennisalerta' AND COALESCE(canal,'') NOT LIKE 'TennisAlerta%' "
        "AND estado IN ('VERIFICANDO','CONFIRMADA','SIN_CONFIRMAR') ORDER BY id DESC LIMIT 300",
        ((ahora - timedelta(days=dias)).isoformat(),)).fetchall()]
    jug = portada._jugadores(conn, {f["jugador_id"] for f in filas})
    out = {"nuevo": 0, "actualizado": 0, "igual": 0}
    for p in filas:
        et = ETIQUETA_DE.get(p["categoria"])
        titulo = (p.get("titular") or p.get("resumen_es") or "").strip()
        if not et or not titulo:
            continue
        j = jug.get(p["jugador_id"]) or {}
        fecha = portada._dt(p.get("fecha_mensaje")) or portada._dt(p["recibido_en"]) or ahora
        f = {"clave": f"pi:{p['id']}", "ocurrio_en": _iso(fecha), "publicado_en": _iso(ahora), "etiqueta": et, "titulo": titulo,
             "texto": (p.get("resumen_es") or None) if p.get("resumen_es") != titulo else None, "jugador_id": p["jugador_id"],
             "jugador": j.get("nombre"), "torneo": j.get("ultimo_torneo"),
             "circuito": portada.CIRCUITO_ES.get((j.get("circuito") or "").lower()) or None,
             "nivel": "CONFIRMADO" if p["estado"] == "CONFIRMADA" else "SIN_CONFIRMAR", "origen": "PISTA", "fuente": "Canal de Telegram",
             "ref_id": p["id"], "estado": "OCULTO" if p["estado"] == "SIN_CONFIRMAR" and fecha < ahora - timedelta(
                 hours=int(cfg.get("NEWS_TELEGRAM_CONFIRMAR_H", 72) or 72)) else "PUBLICADO"}
        out[_poner(conn, f)] += 1
    conn.commit()
    return out


def calculados(conn, cfg, ahora: datetime) -> dict:
    """«Jugador con molestia reportada juega hoy contra X» — cruza las noticias de lesión vigentes con la agenda."""
    if not int(cfg.get("NEWS_LIVE_CALCULADOS", 1) or 0):
        return {"activo": 0}
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    lesion = {}
    for r in cur.execute(
            "SELECT l.jugador_id, l.titulo, l.ocurrio_en FROM news_live l WHERE l.origen='EVENTO' AND l.estado='PUBLICADO' "
            "AND l.etiqueta IN ('MOLESTIAS','LESIÓN') AND l.ocurrio_en >= ? ORDER BY l.ocurrio_en",
            (_iso(ahora - timedelta(days=int(cfg.get("NEWS_LIVE_DIAS", 3) or 3))),)).fetchall():
        lesion[r["jugador_id"]] = dict(r)
    if not lesion:
        return {"nuevo": 0, "actualizado": 0, "igual": 0}
    cols = {r[1] for r in conn.execute("PRAGMA table_info(news_partido)")}
    pc = "".join(", " + c for c in ("cuota1", "cuota2") if c in cols)
    filas = [dict(r) for r in cur.execute(
        f"SELECT id, torneo, circuito, ronda, fecha_estimada, jugador1_id, jugador2_id{pc} FROM news_partido "
        "WHERE fecha_estimada >= ? AND fecha_estimada <= ? AND COALESCE(estado,'PROGRAMADO') NOT IN ('JUGADO','SIN_RESULTADO','DUPLICADO') "
        "ORDER BY fecha_estimada LIMIT 400",
        (_iso(ahora - timedelta(hours=1)), _iso(ahora + timedelta(hours=VENTANA_CALCULADO_H)))).fetchall()]
    jug = portada._jugadores(conn, {f["jugador1_id"] for f in filas} | {f["jugador2_id"] for f in filas})
    out = {"nuevo": 0, "actualizado": 0, "igual": 0}
    for p in filas:
        for yo, rival, cuota_yo, cuota_rival in ((p["jugador1_id"], p["jugador2_id"], p.get("cuota1"), p.get("cuota2")),
                                                 (p["jugador2_id"], p["jugador1_id"], p.get("cuota2"), p.get("cuota1"))):
            if yo not in lesion:
                continue
            a, b = jug.get(yo) or {}, jug.get(rival) or {}
            if not a.get("nombre") or not b.get("nombre"):
                continue
            hora = portada._dt(p["fecha_estimada"])
            cuotas = f" Cuotas: {a['nombre']} {cuota_yo:g} · {b['nombre']} {cuota_rival:g}." if cuota_yo and cuota_rival else ""
            f = {"clave": f"calc:{p['id']}:{yo}", "ocurrio_en": _iso(lesion[yo]["ocurrio_en"] and portada._dt(lesion[yo]["ocurrio_en"]) or ahora),
                 "publicado_en": _iso(ahora), "etiqueta": "SEGUIMIENTO",
                 "titulo": f"{a['nombre']} tiene una noticia física reciente y juega pronto contra {b['nombre']}",
                 "texto": f"Última noticia: {lesion[yo]['titulo']}.{cuotas} Partido: {p.get('torneo') or ''}"
                          f"{' · ' + p['ronda'] if p.get('ronda') else ''} ({hora.strftime('%d/%m %H:%M') + ' UTC' if hora else 'hora por confirmar'}).",
                 "jugador_id": yo, "jugador": a["nombre"], "torneo": p.get("torneo"),
                 "circuito": portada.CIRCUITO_ES.get((p.get("circuito") or "").lower()) or None, "nivel": "CONFIRMADO",
                 "origen": "CALCULADO", "fuente": "FullTennis", "ref_id": p["id"]}
            out[_poner(conn, f)] += 1
    conn.commit()
    return out


def viajes(conn, cfg, ahora: datetime) -> dict:
    """✈️ Ciudad a ciudad: quien juega pronto y viene de otra ciudad lejos / con otro huso y pocos días de descanso (ver viajes.py).
    Calculado con nuestras tablas; si no se reconoce la ciudad de un torneo no se inventa nada y se lista en «sin_ciudad»."""
    if not int(cfg.get("NEWS_LIVE_VIAJES", 1) or 0):
        return {"activo": 0}
    from ft_news import viajes as vj
    km_min = float(cfg.get("NEWS_LIVE_VIAJE_KM_MIN", 1500) or 1500)
    huso_min = float(cfg.get("NEWS_LIVE_VIAJE_HUSO_MIN", 3) or 3)
    dias_max = float(cfg.get("NEWS_LIVE_VIAJE_DIAS_MAX", 4) or 4)
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    filas = [dict(r) for r in cur.execute(
        "SELECT id, torneo, circuito, ronda, fecha_estimada, jugador1_id, jugador2_id FROM news_partido "
        "WHERE fecha_estimada >= ? AND fecha_estimada <= ? AND COALESCE(estado,'PROGRAMADO') NOT IN ('JUGADO','SIN_RESULTADO','DUPLICADO') "
        "ORDER BY fecha_estimada LIMIT 400",
        (_iso(ahora - timedelta(hours=1)), _iso(ahora + timedelta(hours=VENTANA_CALCULADO_H)))).fetchall()]
    jug = portada._jugadores(conn, {f["jugador1_id"] for f in filas} | {f["jugador2_id"] for f in filas})
    out = {"nuevo": 0, "actualizado": 0, "igual": 0}
    sin = set()
    for p in filas:
        hasta = vj.ciudad_de(p["torneo"])
        fecha_p = portada._dt(p["fecha_estimada"])
        if not hasta:
            sin.add(p["torneo"] or "?")
            continue
        for yo, rival in ((p["jugador1_id"], p["jugador2_id"]), (p["jugador2_id"], p["jugador1_id"])):
            a, b = jug.get(yo) or {}, jug.get(rival) or {}
            ant = cur.execute(
                "SELECT torneo, fecha_estimada FROM news_partido WHERE (jugador1_id=? OR jugador2_id=?) AND id<>? AND fecha_estimada < ? "
                "AND fecha_estimada >= ? AND COALESCE(estado,'') NOT IN ('DUPLICADO') ORDER BY fecha_estimada DESC LIMIT 1",
                (yo, yo, p["id"], p["fecha_estimada"], _iso(fecha_p - timedelta(days=14)))).fetchone()
            if not ant or not a.get("nombre"):
                continue
            desde = vj.ciudad_de(ant["torneo"])
            if not desde:
                sin.add(ant["torneo"] or "?")
                continue
            if desde["nombre"] == hasta["nombre"]:
                continue
            dias = (fecha_p - (portada._dt(ant["fecha_estimada"]) or fecha_p)).total_seconds() / 86400
            v = vj.entre(desde, hasta)
            if dias > dias_max or (v["km"] < km_min and abs(v["huso"]) < huso_min):
                continue
            huso = f"{v['huso']:+g} h de huso" if v["huso"] else "sin cambio de huso"
            f = {"clave": f"via:{p['id']}:{yo}", "ocurrio_en": _iso(fecha_p - timedelta(days=dias)), "publicado_en": _iso(ahora),
                 "etiqueta": "VIAJES",
                 "titulo": f"{a['nombre']} viene de {desde['nombre']} a {hasta['nombre']}: ≈ {v['km']:,} km, ~{v['horas']:g} h de viaje".replace(",", "."),
                 "texto": f"Jugó por última vez hace {max(0, int(round(dias)))} día(s) en {desde['nombre']}. {huso.capitalize()}"
                          f"{'; cambia de continente' if v['continente_cambia'] else ''}. Ahora: {p.get('torneo') or ''}"
                          f"{' · ' + p['ronda'] if p.get('ronda') else ''}" + (f", contra {b['nombre']}" if b.get("nombre") else "")
                          + ". (Horas estimadas puerta a puerta; no es su vuelo real.)",
                 "jugador_id": yo, "jugador": a["nombre"], "torneo": p.get("torneo"),
                 "circuito": portada.CIRCUITO_ES.get((p.get("circuito") or "").lower()) or None, "nivel": "CONFIRMADO",
                 "origen": "CALCULADO", "fuente": "FullTennis", "ref_id": p["id"]}
            out[_poner(conn, f)] += 1
    conn.commit()
    if sin:
        out["sin_ciudad"] = sorted(sin)[:20]
    return out


def sincronizar(conn, cfg, ahora: Optional[datetime] = None) -> dict:
    """Paso del worker: eventos → pistas (si se permite) → calculados. Cada parte aislada de las demás."""
    ahora = ahora or datetime.now(timezone.utc)
    asegurar(conn)
    if not int(cfg.get("NEWS_LIVE_ACTIVO", 1) or 0):
        return {"activo": 0}
    res = {}
    for nombre, fn in (("eventos", desde_eventos), ("pistas", desde_pistas), ("calculados", calculados), ("viajes", viajes)):
        try:
            res[nombre] = fn(conn, cfg, ahora)
        except Exception as e:                     # una parte no tumba a las otras
            res[nombre] = {"error": str(e)[:200]}
    return res


def manual(conn, datos: dict, por: str, ahora: Optional[datetime] = None) -> dict:
    """Mesa de redacción: una entrada escrita a mano. estado BORRADOR (se aprueba luego) o PUBLICADO."""
    asegurar(conn)
    ahora = ahora or datetime.now(timezone.utc)
    etiqueta = str(datos.get("etiqueta") or "INFORMACIÓN").upper()
    titulo = str(datos.get("titulo") or "").strip()
    if etiqueta not in ETIQUETAS:
        raise ValueError("etiqueta no válida")
    if not titulo:
        raise ValueError("falta el título")
    estado = datos.get("estado") if datos.get("estado") in ("PUBLICADO", "BORRADOR") else "PUBLICADO"
    nivel = datos.get("nivel") if datos.get("nivel") in ("CONFIRMADO", "SIN_CONFIRMAR") else "CONFIRMADO"
    clave = f"man:{_iso(ahora)}:{abs(hash(titulo)) % 100000}"
    enlace = datos.get("enlace")
    f = {"clave": clave, "ocurrio_en": _iso(portada._dt(datos.get("ocurrio_en")) or ahora), "publicado_en": _iso(ahora),
         "etiqueta": etiqueta, "titulo": titulo[:300], "texto": (str(datos.get("texto") or "").strip()[:1500] or None),
         "jugador": (str(datos.get("jugador") or "").strip()[:120] or None), "torneo": (str(datos.get("torneo") or "").strip()[:120] or None),
         "circuito": datos.get("circuito"), "nivel": nivel, "origen": "MANUAL", "fuente": (str(datos.get("fuente") or "FullTennis")[:80]),
         "enlace": enlace if str(enlace or "").startswith("https://") else None, "estado": estado, "por": por}
    _poner(conn, f)
    conn.commit()
    return {"ok": True, "id": conn.execute("SELECT id FROM news_live WHERE clave=?", (clave,)).fetchone()[0]}


def cambiar_estado(conn, live_id: int, estado: str, por: str) -> bool:
    asegurar(conn)
    if estado not in ESTADOS:
        raise ValueError("estado no válido")
    cur = conn.execute("UPDATE news_live SET estado=?, por=? WHERE id=?", (estado, por, live_id))
    conn.commit()
    return cur.rowcount > 0


def listar(conn, limite: int = 60, etiqueta: Optional[str] = None, incluir_sin_confirmar: bool = True,
           desde_id: int = 0, borradores: bool = False) -> dict:
    asegurar(conn)
    limite = max(1, min(int(limite or 60), MAX_LISTA))
    where, args = ["id > ?"], [int(desde_id or 0)]
    where.append("estado IN ('PUBLICADO','BORRADOR')" if borradores else "estado='PUBLICADO'")
    if etiqueta:
        where.append("etiqueta=?")
        args.append(etiqueta)
    if not incluir_sin_confirmar:
        where.append("nivel='CONFIRMADO'")
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    filas = [dict(r) for r in cur.execute(
        "SELECT id, ocurrio_en, publicado_en, etiqueta, titulo, texto, jugador_id, jugador, torneo, circuito, nivel, origen, fuente, "
        f"enlace, estado FROM news_live WHERE {' AND '.join(where)} ORDER BY ocurrio_en DESC, id DESC LIMIT ?", (*args, limite)).fetchall()]
    return {"items": filas, "total": len(filas), "etiquetas": list(ETIQUETAS)}
