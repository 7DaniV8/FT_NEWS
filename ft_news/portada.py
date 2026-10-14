"""
ft_news/portada.py — 📰 PORTADA de FT NEWS (v7.4, 13/10/2026).

Rubén (12/10): «un portal de noticias de tenis estilo periódico digital (portada con titulares, fotos,
secciones, agenda del día)»; «los titulares son los partidos con más valor que encuentra FT NEWS»; y (13/10)
«que FT NEWS se vea así como lo habíamos planeado» (el boceto de la portada).

Solo LEE lo que FT NEWS ya guardó. No crea alertas, no cambia filtros, no gasta búsquedas. Todo en palabras
para el usuario: sin códigos del motor, sin bandas, sin Elo ni FTR.

  · titular      → la alerta más fuerte del día (🔥 > 🔎) de un partido que todavía no terminó; la misma fila
                   que viaja a Discord, así portada y Discord no se contradicen. Una 🔥 sin calibración
                   respaldada sale SIEMPRE como «POSIBLE VALOR · EXPERIMENTAL». Sin alerta: la noticia externa
                   más fuerte de los últimos días (nunca se inventa un partido del día).
  · interesantes → las demás alertas 🔥/🔎 de partidos por jugar.
  · noticias     → noticias EXTERNAS recientes (de un medio), con su confirmación (✅ / 📰 / 🗣️ / ❔).
  · lesiones     → lesiones, enfermedades y retiros recientes (de un medio o de nuestros resultados).
  · agenda       → los partidos de las próximas horas de jugadores que FT NEWS vigila, con UTR y cuotas.

Fotos (v7.6): la de la ficha de Wikidata del tenista en Wikimedia Commons, con licencia libre, autor y enlace (ver
fotos.py). Sin foto válida, la tarjeta propia de FullTennis (iniciales, país, UTR); nunca una foto sin licencia.

v7.6 (13/10/2026, Rubén: «¿qué es partido interesante?, si le doy clic se debe abrir el modal con todo lo que
encontró»): `detalle_partido` y `detalle_noticia` arman, también solo con datos para usuarios, lo que muestra el
modal. Y la portada deja fuera las alertas viejas que hoy no saldrían (resultado de dobles, o «el mercado ya la
tenía»: v7.5).
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import config, descubridor, explicar, fotos, textos
from ft_news import taxonomia as tx

VERSION = "portada-v2-20261013"
DIAS_NOTICIAS = 3
HORAS_AGENDA = 30
MAX_NOTICIAS = 14
MAX_INTERESANTES = 6
MAX_AGENDA = 30
CIRCUITO_ES = {"atp": "ATP", "wta": "WTA", "wta125": "WTA", "challenger": "Challenger", "itf": "ITF", "utr": "UTR PTT"}
SECCION = {"atp": "atp", "wta": "wta", "wta125": "wta", "challenger": "challenger", "itf": "itf", "utr": "utr"}
LESIONES = ("LESION_MOLESTIA", "ENFERMEDAD", "RETIRO_ABANDONO")
ESTADOS_FUERA = ("DESCARTADO", "DESMENTIDO", "VENCIDO")
ETIQUETA = {"FUEGO": "POSIBLE VALOR", "FUEGO_EXPERIMENTAL": "POSIBLE VALOR · EXPERIMENTAL",
            "INTERESANTE": "PARTIDO INTERESANTE", "NOTICIA": "NOTICIA"}


def _dt(s) -> Optional[datetime]:
    """ISO o RFC 2822 («Thu, 08 Oct 2026 14:00:00 GMT», como la dan algunos buscadores) → datetime UTC."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            d = parsedate_to_datetime(str(s))
        except (TypeError, ValueError, IndexError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _fecha_ev(ev: dict) -> Optional[datetime]:
    return _dt(ev.get("fecha_publicacion")) or _dt(ev.get("fecha_evento")) or _dt(ev.get("creado_en"))


def _con_nombre(nombre: str, frase: str) -> str:
    """«Perez: se retiró con 3-3», salvo que la frase ya nombre al jugador. Con nombres de más de dos palabras
    («Lucas Andrade Da Silva») va el nombre completo: «Silva» solo no lo identifica."""
    partes = (nombre or "").split()
    ap = (textos.apellido(nombre) if len(partes) <= 2 else nombre) if nombre else ""
    if not ap or ap.lower() in (frase or "").lower() or textos.apellido(nombre).lower() in (frase or "").lower():
        return frase
    if len(frase) > 1 and frase[0].isupper() and frase[1].islower():
        frase = frase[0].lower() + frase[1:]          # «Barrios: jugó con…» (no «Jugó»)
    return f"{ap}: {frase}"


def _igual(a, b) -> bool:
    n = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    return bool(n(a)) and n(a) == n(b)


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat(timespec="seconds") if d else None


def _cols(conn, tabla: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}


def _seccion(circ: Optional[str], torneo: Optional[str] = None, genero: Optional[str] = None) -> str:
    c = (circ or "").lower()
    if c not in SECCION and torneo:
        from ft_news.jugadores import circuito_de
        c = circuito_de(torneo, genero)
    return SECCION.get(c, "")


def _iniciales(nombre: Optional[str]) -> str:
    partes = [p for p in re.split(r"[\s\-]+", (nombre or "").replace(".", " ")) if p]
    if not partes:
        return "?"
    return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()


def _utr(v) -> Optional[str]:
    try:
        return f"{float(v):.2f}".replace(".", ",") if v is not None else None
    except (TypeError, ValueError):
        return None


def _cuota(v) -> Optional[str]:
    try:
        return f"{float(v):.2f}".replace(".", ",") if v else None
    except (TypeError, ValueError):
        return None


def _tarjeta(j: dict) -> dict:
    """La «foto» mientras no haya fotos con licencia: una tarjeta propia de FullTennis."""
    return {"tipo": "tarjeta", "iniciales": _iniciales(j.get("nombre")), "nombre": j.get("nombre"),
            "pais": j.get("pais"), "utr": _utr(j.get("utr_singles")), "credito": "Tarjeta FullTennis · sin foto"}


def _confirmacion(ev: dict) -> str:
    try:
        return textos.fiabilidad(ev)
    except Exception:                                # pragma: no cover
        return ""


def _evento_publico(ev: dict, jug: dict) -> dict:
    nombre = jug.get("nombre") or ev.get("jugador") or ""
    frase = textos._frase(ev, 140)
    d = ev.get("direccion")
    afecta = ("perjudica a " + nombre) if d == "NEGATIVA" else ("favorece a " + nombre) if d == "POSITIVA" else ""
    externo = descubridor.es_externo(ev)
    return {"id": ev["id"], "jugador_id": ev.get("jugador_id"), "jugador": nombre, "pais": jug.get("pais"), "categoria": explicar.categoria_es(ev.get("categoria")),
            "lesion": ev.get("categoria") in LESIONES, "titular": _con_nombre(nombre, frase),
            "resumen": (None if _igual(ev.get("resumen_es"), frase) else (ev.get("resumen_es") or "").strip() or None), "afecta": afecta,
            "direccion": {"NEGATIVA": "contra", "POSITIVA": "a_favor"}.get(d, "neutra"),
            "fuente": textos._fuente_corta(ev.get("fuente") or "") if externo else "FullTennis",
            "enlace": ev.get("enlace") if (externo and str(ev.get("enlace") or "").startswith("https://")) else None,
            "externa": externo, "confirmacion": _confirmacion(ev),
            "fecha": _iso(_fecha_ev(ev)),
            "seccion": _seccion(jug.get("circuito"), jug.get("ultimo_torneo"), jug.get("genero")),
            "circuito": CIRCUITO_ES.get((jug.get("circuito") or "").lower(), ""),
            "imagen": _tarjeta(dict(jug, nombre=nombre))}


def _jugadores(conn, ids: set) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    cols = _cols(conn, "news_jugador")
    extra = [c for c in ("utr_singles", "pais", "circuito", "genero", "ultimo_torneo") if c in cols]
    q = ",".join("?" * len(ids))
    return {r[0]: dict(zip(["id", "nombre"] + extra, r)) for r in conn.execute(
        f"SELECT id, nombre{''.join(', ' + c for c in extra)} FROM news_jugador WHERE id IN ({q})", tuple(ids)).fetchall()}


def _eventos_recientes(conn, ahora: datetime, dias: int) -> list[dict]:
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    cols = _cols(conn, "news_evento")
    extra = [c for c in ("origen", "titular") if c in cols]
    filas = [dict(r) for r in cur.execute(
        "SELECT id, jugador_id, articulo_id, categoria, direccion, naturaleza, nivel, fecha_evento, fecha_publicacion, fuente, enlace, "
        f"resumen_es, fragmento_original, confianza_identidad, estado, creado_en{''.join(', ' + c for c in extra)} FROM news_evento "
        "WHERE creado_en >= ? AND estado NOT IN (%s) ORDER BY id DESC LIMIT 600" % ",".join("?" * len(ESTADOS_FUERA)),
        ((ahora - timedelta(days=dias + 7)).isoformat(), *ESTADOS_FUERA)).fetchall()]
    # la fecha de la NOTICIA (no la de lectura) decide si es reciente; las fechas vienen en formatos distintos
    lim = ahora - timedelta(days=dias)
    filas = [f for f in filas if (_fecha_ev(f) or lim) >= lim and (_fecha_ev(f) or ahora) <= ahora + timedelta(hours=1)]
    filas.sort(key=lambda f: (_fecha_ev(f) or lim, f["id"]), reverse=True)
    return descubridor.sin_repetidos(filas)


def _lectura(e: dict) -> dict:
    try:
        return json.loads(e.get("lectura_json") or "{}") or {}
    except (TypeError, ValueError):
        return {}


def _perjudica(lineas: list) -> Optional[str]:
    for l in lineas or []:
        if "PERJUDICA A:" in l:
            return l.split("PERJUDICA A:", 1)[1].strip()
    return None


def _alertas_vivas(conn, ahora: datetime, cfg: dict) -> list[dict]:
    """Las alertas 🔥/🔎 de partidos que todavía no terminaron (o empezaron hace poco), sin las omitidas."""
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    cols_a = _cols(conn, "news_alerta")
    prueba = "AND COALESCE(a.prueba,0)=0" if "prueba" in cols_a else ""
    cols_p = _cols(conn, "news_partido")
    pc = [c for c in ("cuota1", "cuota2", "genero", "superficie", "ronda") if c in cols_p]
    lect = ", e.lectura_json" if "lectura_json" in _cols(conn, "news_evaluacion") else ", NULL AS lectura_json"
    filas = [dict(r) for r in cur.execute(
        "SELECT a.id, a.tipo, a.jugador_id, a.rival_id, a.partido_id, a.evaluacion_id, a.evento_ids_json, a.dicho_discord, a.creado_en, "
        "p.torneo, p.circuito, p.fecha_estimada, p.estado AS partido_estado, p.jugador1_id, p.jugador2_id"
        + "".join(", p." + c for c in pc)
        + ", e.utr_x, e.utr_rival, e.cuota_x, e.cuota_rival, e.bandas_calibradas, e.motivo AS eval_motivo" + lect
        + " FROM news_alerta a JOIN news_partido p ON p.id=a.partido_id LEFT JOIN news_evaluacion e ON e.id=a.evaluacion_id "
        f"WHERE a.tipo IN ('FUEGO','FUEGO_EXPERIMENTAL','INTERESANTE') {prueba} AND a.dicho_discord <> 2 "
        "AND COALESCE(p.estado,'PROGRAMADO') NOT IN ('JUGADO','SIN_RESULTADO','DUPLICADO') "
        "AND p.fecha_estimada >= ? ORDER BY a.id DESC LIMIT 60",
        ((ahora - timedelta(hours=3)).isoformat(),)).fetchall()]
    vistos, out = set(), []
    for f in filas:                                   # una por partido: la más fuerte
        if f["partido_id"] in vistos:
            continue
        vistos.add(f["partido_id"])
        out.append(f)
    orden = {"FUEGO": 0, "FUEGO_EXPERIMENTAL": 1, "INTERESANTE": 2}
    out.sort(key=lambda f: (orden.get(f["tipo"], 9), f.get("fecha_estimada") or ""))
    return out


def _tipo_publico(f: dict, cfg: dict) -> str:
    """Una 🔥 solo se muestra como validada si es FUEGO y la calibración está respaldada; si no, EXPERIMENTAL."""
    if f["tipo"] == "FUEGO" and f.get("bandas_calibradas") and cfg.get("_bandas_respaldadas", False):
        return "FUEGO"
    return "FUEGO_EXPERIMENTAL" if f["tipo"] in ("FUEGO", "FUEGO_EXPERIMENTAL") else f["tipo"]


def _bajada(principal: Optional[dict], titular: str, l: dict) -> str:
    """Debajo del titular: el resumen de la noticia si dice algo más; si no, la lectura de FT NEWS."""
    res = ((principal or {}).get("resumen_es") or "").strip()
    if res and not _igual(res, titular.split(": ", 1)[-1]) and not _igual(res, titular):
        return res
    return l.get("resumen") or ""


def _partido_publico(f: dict, jug: dict, ev_por_id: dict, cfg: dict) -> dict:
    jx, jr = jug.get(f["jugador_id"]) or {}, jug.get(f["rival_id"]) or {}
    l = _lectura(f)
    lineas = l.get("lineas") or []
    try:
        ids = json.loads(f.get("evento_ids_json") or "[]") or []
    except (TypeError, ValueError):
        ids = []
    evs = [ev_por_id[i] for i in ids if i in ev_por_id]
    ext = [e for e in evs if descubridor.es_externo(e)]
    principal = (ext or evs or [None])[0]
    x, r = jx.get("nombre") or "?", jr.get("nombre") or "?"
    tipo = _tipo_publico(f, cfg)
    if principal:
        quien = x if principal.get("jugador_id") in (None, f["jugador_id"]) else r
        titular = _con_nombre(quien, textos._frase(principal, 110))
    else:
        titular = f"{x} vs {r}"
    # cuotas por jugador: las de la evaluación (x / rival) o las del partido (orden del partido)
    cx, cr = f.get("cuota_x"), f.get("cuota_rival")
    if cx is None and cr is None and f.get("cuota1") is not None:
        cx, cr = (f.get("cuota1"), f.get("cuota2")) if f.get("jugador1_id") == f["jugador_id"] else (f.get("cuota2"), f.get("cuota1"))
    fav = l.get("favorecido")
    return {"id": f["id"], "tipo": tipo, "etiqueta": ETIQUETA.get(tipo, ""), "experimental": tipo == "FUEGO_EXPERIMENTAL",
            "titular": titular, "bajada": _bajada(principal, titular, l),
            "jugador": x, "rival": r, "torneo": f.get("torneo"), "ronda": f.get("ronda"), "hora": f.get("fecha_estimada"),
            "circuito": CIRCUITO_ES.get((f.get("circuito") or "").lower(), ""),
            "seccion": _seccion(f.get("circuito"), f.get("torneo"), f.get("genero")),
            "utr": [_utr(f.get("utr_x") if f.get("utr_x") is not None else jx.get("utr_singles")),
                    _utr(f.get("utr_rival") if f.get("utr_rival") is not None else jr.get("utr_singles"))],
            "cuotas": [_cuota(cx), _cuota(cr)],
            "favorece": fav, "cuota_favorece": _cuota(l.get("cuota_favorecido")), "perjudica": _perjudica(lineas),
            "por_que": l.get("motivo") or "", "conclusion": next((x_.split(":", 1)[1].strip() for x_ in lineas if "CONCLUSIÓN:" in x_), ""),
            "confirmacion": _confirmacion(principal) if principal else "", "fuente": (textos._fuente_corta(principal.get("fuente") or "")
                                                                                     if principal and descubridor.es_externo(principal) else None),
            "imagen": _tarjeta(jx), "publicada_en_discord": f.get("dicho_discord") == 1,
            "evento_id": (principal or {}).get("id"), "jugador_id": f["jugador_id"]}


def armar(conn, ahora: Optional[datetime] = None, cfg: Optional[dict] = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    cfg = dict(cfg or config.leer_config(conn))
    # ¿la calibración está respaldada por datos? (v7.2: la casilla manual sola no alcanza)
    try:
        from ft_news.db import estado_todo
        from ft_news.descartes import bandas_efectivas
        cfg["_bandas_respaldadas"] = bool(bandas_efectivas(cfg, (estado_todo(conn).get("calibracion_veredicto") or {}).get("valor")))
    except Exception:                                # pragma: no cover
        cfg["_bandas_respaldadas"] = False

    eventos = _eventos_recientes(conn, ahora, DIAS_NOTICIAS)
    ev_por_id = {e["id"]: e for e in eventos}
    alertas = _alertas_vivas(conn, ahora, cfg)
    # eventos de las alertas que quedaron fuera de la ventana de noticias
    faltan = set()
    for a in alertas:
        try:
            faltan |= {i for i in json.loads(a.get("evento_ids_json") or "[]") or [] if i not in ev_por_id}
        except (TypeError, ValueError):
            pass
    if faltan:
        cur = conn.cursor()
        cur.row_factory = sqlite3.Row
        for r in cur.execute("SELECT * FROM news_evento WHERE id IN (%s)" % ",".join("?" * len(faltan)), tuple(faltan)).fetchall():
            ev_por_id[r["id"]] = dict(r)
    jug = _jugadores(conn, {e["jugador_id"] for e in ev_por_id.values()} | {a["jugador_id"] for a in alertas}
                     | {a["rival_id"] for a in alertas})

    alertas = [a for a in alertas if vigente_hoy(a, ev_por_id)]
    partidos = [_partido_publico(a, jug, ev_por_id, cfg) for a in alertas]
    externas = [e for e in eventos if descubridor.es_externo(e) and (e.get("confianza_identidad") is None or e["confianza_identidad"] >= 0.6)]
    # una noticia por jugador y categoría (la más reciente)
    vistos, noticias = set(), []
    for e in externas:
        k = (e["jugador_id"], e.get("categoria"))
        if k in vistos:
            continue
        vistos.add(k)
        noticias.append(_evento_publico(e, jug.get(e["jugador_id"]) or {}))
    nivel = {"A": 0, "B": 1, "C": 2}

    titular, tit_noticia = None, None
    if partidos:
        titular = partidos[0]
    elif noticias:                                    # sin alerta: abre la noticia más fuerte (nivel, luego la más reciente)
        orden = sorted(externas, key=lambda e: (nivel.get(str(e.get("nivel") or "C"), 3), e.get("categoria") not in LESIONES))
        e0 = orden[0]
        tit_noticia = _evento_publico(e0, jug.get(e0["jugador_id"]) or {})
        tit_noticia["tipo"], tit_noticia["etiqueta"] = "NOTICIA", "NOTICIA DESTACADA"
        noticias = [n for n in noticias if n["id"] != e0["id"]]
    interesantes = partidos[1:1 + MAX_INTERESANTES]
    # una noticia que ya es titular (o la abre) no se repite en la columna de noticias
    usadas = {x.get("evento_id") for x in ([titular] if titular else []) + interesantes}
    noticias = [n for n in noticias if n["id"] not in usadas]

    # 🚑 lesiones, enfermedades y retiros: de un medio o de nuestros propios resultados (eso lo dice la fuente)
    lesiones, vistos_l = [], set()
    for e in eventos:
        if e.get("categoria") not in LESIONES or e["jugador_id"] in vistos_l:
            continue
        if descubridor.es_externo(e) and e.get("confianza_identidad") is not None and e["confianza_identidad"] < 0.6:
            continue
        vistos_l.add(e["jugador_id"])
        lesiones.append(_evento_publico(e, jug.get(e["jugador_id"]) or {}))
        if len(lesiones) >= 10:
            break

    _poner_fotos(conn, [titular, tit_noticia] + interesantes + noticias + lesiones)
    return {"version": VERSION, "actualizado": _iso(ahora), "titular": titular, "titular_noticia": tit_noticia,
            "interesantes": interesantes, "noticias": noticias[:MAX_NOTICIAS], "lesiones": lesiones,
            "agenda": agenda(conn, ahora, {a["partido_id"]: (a["tipo"], a["id"]) for a in alertas}),
            "secciones": [{"id": k, "nombre": v} for k, v in (("atp", "ATP"), ("wta", "WTA"), ("challenger", "Challenger"),
                                                              ("itf", "ITF"), ("utr", "UTR PTT"))],
            "fotos": ("Fotos de Wikimedia Commons con licencia libre, con autor y licencia debajo de cada una; sin foto válida, "
                      "una tarjeta propia de FullTennis."),
            "nota": ("Los titulares son los partidos con más valor que encontró FT NEWS (la misma alerta que va a Discord). "
                     "Un posible valor sin respaldo estadístico sale siempre como EXPERIMENTAL. Cada noticia dice si está confirmada.")}


def agenda(conn, ahora: datetime, marcadas: Optional[dict] = None) -> list[dict]:
    """Partidos de las próximas horas de jugadores que FT NEWS vigila. Se marcan SOLO los que tienen una alerta
    vigente (la misma de la portada); el resto dice «sin alerta» (v7.6: antes «INTERESANTE» salía para cualquier
    partido evaluado, aunque solo hubiera datos calculados por nosotros)."""
    marcadas = marcadas or {}
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    cols_p = _cols(conn, "news_partido")
    pc = [c for c in ("cuota1", "cuota2", "genero", "jugador1_nombre", "jugador2_nombre") if c in cols_p]
    filas = [dict(r) for r in cur.execute(
        "SELECT p.id, p.torneo, p.circuito, p.ronda, p.fecha_estimada, p.estado, p.jugador1_id, p.jugador2_id"
        + "".join(", p." + c for c in pc) + " FROM news_partido p "
        "WHERE p.fecha_estimada >= ? AND p.fecha_estimada <= ? "
        "AND COALESCE(p.estado,'PROGRAMADO') NOT IN ('JUGADO','SIN_RESULTADO','DUPLICADO') "
        "ORDER BY p.fecha_estimada LIMIT 400",
        ((ahora - timedelta(hours=1)).isoformat(), (ahora + timedelta(hours=HORAS_AGENDA)).isoformat())).fetchall()]
    if not filas:
        return []
    jug = _jugadores(conn, {f["jugador1_id"] for f in filas} | {f["jugador2_id"] for f in filas})
    out = []
    for f in filas:
        tipo, aid = marcadas.get(f["id"], (None, None))
        if tipo in ("FUEGO", "FUEGO_EXPERIMENTAL"):
            marca = "POSIBLE VALOR · EXPERIMENTAL"          # en la agenda nunca se presenta como validada
        elif tipo == "INTERESANTE":
            marca = "PARTIDO INTERESANTE"
        else:
            marca = "sin alerta"
        j1, j2 = jug.get(f["jugador1_id"]) or {}, jug.get(f["jugador2_id"]) or {}
        out.append({"id": f["id"], "hora": f["fecha_estimada"], "torneo": f.get("torneo"), "ronda": f.get("ronda"),
                    "circuito": CIRCUITO_ES.get((f.get("circuito") or "").lower(), ""),
                    "seccion": _seccion(f.get("circuito"), f.get("torneo"), f.get("genero")),
                    "jugador1": j1.get("nombre") or f.get("jugador1_nombre"), "jugador2": j2.get("nombre") or f.get("jugador2_nombre"),
                    "utr": [_utr(j1.get("utr_singles")), _utr(j2.get("utr_singles"))],
                    "cuotas": [_cuota(f.get("cuota1")), _cuota(f.get("cuota2"))], "ft_news": marca,
                    "destacado": tipo is not None, "alerta_id": aid})
    # primero los que tienen alerta; después el resto, por hora
    out.sort(key=lambda x: (0 if x["destacado"] else 1, x["hora"] or ""))
    top = out[:MAX_AGENDA]
    top.sort(key=lambda x: x["hora"] or "")
    return top


# ═════════════════════════════════════════════════════════════════════
# v7.6 · alertas que hoy no saldrían, fotos y el detalle para el modal
# ═════════════════════════════════════════════════════════════════════

def vigente_hoy(a: dict, ev_por_id: dict) -> bool:
    """Una alerta vieja entra en la portada solo si hoy también saldría: con al menos una noticia de un medio que
    siga siendo fuerte (no un resultado de dobles) y, si es 🔎, sin la conclusión «el mercado ya la tiene» (v7.5)."""
    from ft_news.alertas import MERCADO_YA_LO_TIENE
    if a["tipo"] == "INTERESANTE" and str(a.get("eval_motivo") or "").split(":")[0] in MERCADO_YA_LO_TIENE:
        return False
    try:
        ids = json.loads(a.get("evento_ids_json") or "[]") or []
    except (TypeError, ValueError):
        ids = []
    evs = [ev_por_id[i] for i in ids if i in ev_por_id]
    return any(descubridor.es_externo(e) and tx.es_fuerte_evento(e) for e in evs)


def _poner_fotos(conn, items: list) -> None:
    """Cambia la tarjeta por la foto con licencia, si el jugador la tiene."""
    items = [x for x in items if x]
    try:
        f = fotos.de_jugadores(conn, {x.get("jugador_id") for x in items})
    except sqlite3.OperationalError:                 # base vieja sin la tabla de fotos
        f = {}
    for x in items:
        if x.get("jugador_id") in f:
            x["imagen"] = dict(f[x["jugador_id"]], nombre=x.get("jugador"))


QUE_ES = {
    "INTERESANTE": ("🔎 Partido interesante: hay una noticia de un medio que puede influir en este partido, pero no alcanza "
                    "para decir que la cuota tenga valor. Es para seguirlo, no una recomendación."),
    "FUEGO_EXPERIMENTAL": ("🔥 Posible valor EXPERIMENTAL: la noticia, el UTR y la cuota apuntan a que el mercado todavía no la "
                           "refleja. Sin respaldo estadístico todavía: se mide, no está validado."),
    "FUEGO": "🔥 Posible valor: la noticia, el UTR y la cuota apuntan a que el mercado todavía no la refleja.",
}


def _eventos_de(conn, jugador_ids: list, ahora: datetime, dias: int) -> list[dict]:
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    ids = [i for i in jugador_ids if i]
    if not ids:
        return []
    filas = [dict(r) for r in cur.execute(
        "SELECT * FROM news_evento WHERE jugador_id IN (%s) AND creado_en >= ? AND estado NOT IN (%s) ORDER BY id DESC LIMIT 80"
        % (",".join("?" * len(ids)), ",".join("?" * len(ESTADOS_FUERA))),
        (*ids, (ahora - timedelta(days=dias)).isoformat(), *ESTADOS_FUERA)).fetchall()]
    return descubridor.sin_repetidos(filas)


def detalle_partido(conn, alerta_id: int, ahora: Optional[datetime] = None) -> Optional[dict]:
    """Todo lo que FT NEWS encontró para un 🔎/🔥 de la portada, en palabras para usuarios (lo que abre el modal)."""
    ahora = ahora or datetime.now(timezone.utc)
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    prueba = "AND COALESCE(prueba,0)=0" if "prueba" in _cols(conn, "news_alerta") else ""
    a = cur.execute(f"SELECT * FROM news_alerta WHERE id=? AND tipo IN ('FUEGO','FUEGO_EXPERIMENTAL','INTERESANTE') {prueba}",
                    (int(alerta_id),)).fetchone()
    if not a:
        return None
    a = dict(a)
    p = cur.execute("SELECT * FROM news_partido WHERE id=?", (a["partido_id"],)).fetchone()
    p = dict(p) if p else {}
    e = cur.execute("SELECT * FROM news_evaluacion WHERE id=?", (a["evaluacion_id"],)).fetchone() if a.get("evaluacion_id") else None
    e = dict(e) if e else {}
    cfg = dict(config.leer_config(conn))
    try:
        from ft_news.db import estado_todo
        from ft_news.descartes import bandas_efectivas
        cfg["_bandas_respaldadas"] = bool(bandas_efectivas(cfg, (estado_todo(conn).get("calibracion_veredicto") or {}).get("valor")))
    except Exception:                                # pragma: no cover
        cfg["_bandas_respaldadas"] = False
    tipo = _tipo_publico(dict(a, bandas_calibradas=e.get("bandas_calibradas")), cfg)
    jug = _jugadores(conn, {a["jugador_id"], a["rival_id"]})
    jx, jr = jug.get(a["jugador_id"]) or {}, jug.get(a["rival_id"]) or {}
    try:
        usados = {int(i) for i in json.loads(a.get("evento_ids_json") or "[]") or []}
    except (TypeError, ValueError):
        usados = set()
    evs = _eventos_de(conn, [a["jugador_id"], a["rival_id"]], ahora, 21)
    vistos = {x["id"] for x in evs}
    if usados - vistos:                               # los de la alerta, aunque sean más viejos
        evs += [dict(r) for r in cur.execute("SELECT * FROM news_evento WHERE id IN (%s)" % ",".join("?" * len(usados - vistos)),
                                             tuple(usados - vistos)).fetchall()]
    noticias, calculados = [], []
    for ev in evs:
        j = jug.get(ev["jugador_id"]) or {}
        if descubridor.es_externo(ev):
            n = _evento_publico(ev, j)
            n["usada"] = ev["id"] in usados
            n["dobles"] = tx.es_dobles(ev)
            noticias.append(n)
        else:
            calculados.append({"jugador": j.get("nombre"), "texto": explicar.evento_simple(ev, j.get("nombre")),
                               "fecha": _iso(_fecha_ev(ev))})
    noticias.sort(key=lambda n: n.get("fecha") or "", reverse=True)       # la más nueva primero…
    noticias.sort(key=lambda n: not n["usada"])                          # …y arriba las que dieron la alerta
    l = _lectura(e)
    lineas = [x for x in (l.get("lineas") or []) if x]
    try:
        evid = json.loads(a.get("evidencia_json") or "{}") or {}
    except (TypeError, ValueError):
        evid = {}
    cx, cr = e.get("cuota_x"), e.get("cuota_rival")
    if cx is None and p.get("cuota1") is not None:
        cx, cr = (p.get("cuota1"), p.get("cuota2")) if p.get("jugador1_id") == a["jugador_id"] else (p.get("cuota2"), p.get("cuota1"))
    out = {"id": a["id"], "tipo": tipo, "etiqueta": ETIQUETA.get(tipo, ""), "que_es": QUE_ES.get(tipo, ""),
           "experimental": tipo == "FUEGO_EXPERIMENTAL",
           "partido": {"jugador": jx.get("nombre"), "rival": jr.get("nombre"), "torneo": p.get("torneo"), "ronda": p.get("ronda"),
                       "hora": p.get("fecha_estimada"), "circuito": CIRCUITO_ES.get((p.get("circuito") or "").lower(), ""),
                       "utr": [_utr(e.get("utr_x") if e.get("utr_x") is not None else jx.get("utr_singles")),
                               _utr(e.get("utr_rival") if e.get("utr_rival") is not None else jr.get("utr_singles"))],
                       "cuotas": [_cuota(cx), _cuota(cr)]},
           "jugadores": [dict(_tarjeta(jx), jugador_id=a["jugador_id"]), dict(_tarjeta(jr), jugador_id=a["rival_id"])],
           "favorece": l.get("favorecido"), "cuota_favorece": _cuota(l.get("cuota_favorecido")), "perjudica": _perjudica(lineas),
           "conclusion": next((x.split(":", 1)[1].strip() for x in lineas if "CONCLUSIÓN:" in x), "") or l.get("resumen") or "",
           "por_que": l.get("motivo") or "", "lectura": lineas, "pendiente": [str(x) for x in (evid.get("pendiente") or [])],
           "noticias": noticias, "datos_calculados": calculados[:8],
           "publicada_en_discord": a.get("dicho_discord") == 1, "creada": a.get("creado_en"),
           "vigente": vigente_hoy(dict(a, eval_motivo=e.get("motivo")), {x["id"]: x for x in evs})}
    fts = fotos.de_jugadores(conn, {a["jugador_id"], a["rival_id"]}) if "news_foto" in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} else {}
    out["jugadores"] = [dict(fts[j["jugador_id"]], nombre=j["nombre"], jugador_id=j["jugador_id"]) if j["jugador_id"] in fts else j
                        for j in out["jugadores"]]
    return out


def detalle_noticia(conn, evento_id: int, ahora: Optional[datetime] = None) -> Optional[dict]:
    """Una noticia de la portada: lo que dice, de dónde viene, si está confirmada, otras noticias recientes del mismo
    jugador y su próximo partido."""
    ahora = ahora or datetime.now(timezone.utc)
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    ev = cur.execute("SELECT * FROM news_evento WHERE id=?", (int(evento_id),)).fetchone()
    if not ev:
        return None
    ev = dict(ev)
    j = _jugadores(conn, {ev["jugador_id"]}).get(ev["jugador_id"]) or {}
    n = _evento_publico(ev, j)
    otras = [_evento_publico(x, j) for x in _eventos_de(conn, [ev["jugador_id"]], ahora, 30)
             if x["id"] != ev["id"] and descubridor.es_externo(x)][:6]
    try:
        from ft_news.alertas import proximo_partido
        prox = proximo_partido(conn, ev["jugador_id"], ahora)
    except Exception:                                # pragma: no cover
        prox = None
    _poner_fotos(conn, [n])
    return {"noticia": n, "otras": otras, "dobles": tx.es_dobles(ev),
            "proximo_partido": {k: prox.get(k) for k in ("torneo", "fecha_estimada", "rival")} if prox else None}
