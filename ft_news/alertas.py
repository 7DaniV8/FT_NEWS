"""
ft_news/alertas.py — 📣 Selección de lo que va a Discord (v5, 09/10/2026,
pedido de Rubén: "calidad, no cantidad; explicar por qué se seleccionó cada
alerta; no repetir; límite configurable").

Tres canales independientes, cada uno con su regla, su tope diario y su
dedupe. Todo queda en `news_alerta` con motivo_seleccion y evidencia_json.

  📰 NOTICIA IMPORTANTE (noticia_importante): la decide el radar al guardar
     un evento. Solo evidencia EXTERNA (un artículo), categoría fuerte
     (lesión, enfermedad, retiro, regreso, sanción) o débil solo si viene de
     fuente oficial (nivel A); nivel ≥ B; HECHO o DECLARACION (los rumores
     no salen); identidad ≥ NEWS_IDENTIDAD_MIN; hecho de ≤ NEWS_NOTICIA_MAX_DIAS.
     No necesita partido. Misma (jugador, categoría) no se repite en
     NEWS_ALERTA_REPETIR_DIAS salvo información nueva (sube el nivel o pasa
     de declaración a hecho). Tope NEWS_MAX_NOTICIA_DIA.

  🔎 PARTIDO INTERESANTE (partido_interesante): la decide el evaluador. Exige
     al menos una noticia EXTERNA fuerte nivel ≥ B en alguno de los dos y que
     LOS DOS estén investigados (búsqueda externa ≤ NEWS_RIVAL_HORAS, o
     eventos externos); si el rival no lo está, se lo adelanta en la cola y
     se espera al próximo ciclo. Un partido único no se repite salvo evento
     nuevo. Tope NEWS_MAX_INTERESANTE_DIA. Un cálculo de carga solo NUNCA
     produce 🔎.

  🔥 FUEGO / FUEGO_EXPERIMENTAL (fuego): el descubridor ya decidió (todas sus
     compuertas); acá solo dedupe por partido y registro. El texto ya viene
     armado (textos.armar).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import descubridor, textos
from ft_news import taxonomia as tx
from ft_news.db import ahora_iso, ejecutar_con_reintento

CATEGORIAS_NOTICIA_FUERTE = {"LESION_MOLESTIA", "ENFERMEDAD", "RETIRO_ABANDONO", "REGRESO", "SANCION_DISCIPLINA"}
CATEGORIAS_NOTICIA_OFICIAL = {"DECLARACION_PREPARACION", "DECLARACION_MOTIVACION", "VIAJE_CALENDARIO",
                              "SITUACION_PERSONAL", "CAMBIO_EQUIPO"}
_RANGO = {"A": 3, "B": 2, "C": 1}
_RANGO_NAT = {"HECHO": 3, "DECLARACION": 2, "INTERPRETACION": 1, "NO_VERIFICADA": 0}


def _dt(s):
    """ISO ('2026-10-08T14:00:00+00:00', '2026-10-08') o RFC 2822 (Tavily/RSS:
    'Thu, 08 Oct 2026 14:00:00 GMT') → datetime UTC."""
    if not s:
        return None
    s = str(s)
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T")[:25] if "T" in s or len(s) == 10 else s)
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            d = parsedate_to_datetime(s)
        except (TypeError, ValueError):
            try:
                d = datetime.fromisoformat(s[:19].replace(" ", "T"))
            except ValueError:
                return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _hoy(conn, tipo: str, ahora: datetime) -> int:
    return conn.execute("SELECT COUNT(*) FROM news_alerta WHERE tipo=? AND creado_en >= ?",
                        (tipo, ahora.date().isoformat())).fetchone()[0]


def _reciente(conn, clave_base: str, dias: int, ahora: datetime) -> Optional[dict]:
    r = conn.execute("SELECT * FROM news_alerta WHERE (clave=? OR clave LIKE ?) AND creado_en >= ? "
                     "ORDER BY id DESC LIMIT 1",
                     (clave_base, clave_base + ":%", (ahora - timedelta(days=dias)).isoformat())).fetchone()
    return dict(r) if r else None


def _insertar(conn, tipo: str, clave: str, jugador_id, rival_id, partido_id, evaluacion_id, evento_ids: list,
              motivo: str, evidencia: dict, texto: str, voz: str, ahora: datetime) -> int:
    def _w():
        cur = conn.execute(
            "INSERT INTO news_alerta (tipo, clave, jugador_id, rival_id, partido_id, evaluacion_id, evento_ids_json, "
            "motivo_seleccion, evidencia_json, texto_discord, texto_voz, dicho_discord, dicho_en, dicho_motivo, "
            "creado_en, actualizado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,NULL,NULL,?,?)",
            (tipo, clave, jugador_id, rival_id, partido_id, evaluacion_id, json.dumps(evento_ids), motivo,
             json.dumps(evidencia, ensure_ascii=False, default=str), texto, voz, ahora.isoformat(), ahora.isoformat()))
        conn.commit()
        return cur.lastrowid
    return ejecutar_con_reintento(_w, conn=conn)


def frescura(conn, jugador_id: int, ahora: datetime, horas: int) -> dict:
    """v5.1 (Rubén §3: "que una noticia antigua todavía vigente no sustituya la
    investigación actualizada"): cuenta SOLO la búsqueda externa reciente
    (radar directo o temático/RSS que lo nombró), no los eventos vigentes.
    Devuelve {'reciente': bool, 'hace_h': float|None, 'busquedas': n, 'articulos': n, 'externos': n}."""
    r = conn.execute("SELECT ultima_busqueda_en FROM news_jugador_cola WHERE jugador_id=?", (jugador_id,)).fetchone()
    t = _dt(r["ultima_busqueda_en"]) if r and r["ultima_busqueda_en"] else None
    desde = (ahora - timedelta(hours=horas)).isoformat()
    b = conn.execute("SELECT COUNT(*) FROM news_busqueda WHERE jugador_id=? AND creado_en>=?", (jugador_id, desde)).fetchone()[0]
    a = conn.execute("SELECT COUNT(*) FROM news_articulo WHERE jugador_id=? AND creado_en>=?", (jugador_id, desde)).fetchone()[0]
    e = conn.execute("SELECT COUNT(*) FROM news_evento WHERE jugador_id=? AND articulo_id IS NOT NULL AND creado_en>=?",
                     (jugador_id, desde)).fetchone()[0]
    # un artículo temático/RSS que lo nombró hace poco también es investigación reciente
    ta = conn.execute("SELECT MAX(creado_en) FROM news_articulo WHERE jugador_id=?", (jugador_id,)).fetchone()[0]
    t2 = _dt(ta) if ta else None
    ult = max([x for x in (t, t2) if x], default=None)
    hace = round(max(0.0, (ahora - ult).total_seconds() / 3600), 1) if ult else None
    return {"reciente": bool(ult and ult >= ahora - timedelta(hours=horas)), "hace_h": hace,
            "busquedas": b, "articulos": a, "externos": e}


def investigado(conn, jugador_id: int, ahora: datetime, horas: int) -> bool:
    return frescura(conn, jugador_id, ahora, horas)["reciente"]


def _frescura_txt(nombre: str, f: dict) -> str:
    if not f.get("reciente"):
        return f"{nombre}: sin investigación reciente" + (f" (hace {f['hace_h']} h)" if f.get("hace_h") is not None else " (nunca)")
    return (f"{nombre}: investigado hace {f['hace_h']} h ({f['busquedas']} búsqueda(s), {f['articulos']} artículo(s), "
            f"{f['externos']} noticia(s) externa(s))")


def adelantar(conn, jugador_id: int, ahora: datetime, motivo: str = "A_DEMANDA") -> None:
    """Investigación a demanda (Rubén: "investigar también al rival"): el
    jugador pasa al frente de la cola en este mismo ciclo."""
    def _w():
        r = conn.execute("SELECT 1 FROM news_jugador_cola WHERE jugador_id=?", (jugador_id,)).fetchone()
        if r:
            conn.execute("UPDATE news_jugador_cola SET prioridad=0, motivo=?, proxima_busqueda_en=?, actualizado_en=? "
                         "WHERE jugador_id=?", (motivo, ahora.isoformat(), ahora.isoformat(), jugador_id))
        else:
            conn.execute("INSERT INTO news_jugador_cola (jugador_id, prioridad, motivo, situacion, circuito, "
                         "proxima_busqueda_en, ultima_busqueda_en, actualizado_en) VALUES (?,0,?,'PARTIDO_24H',NULL,?,NULL,?)",
                         (jugador_id, motivo, ahora.isoformat(), ahora.isoformat()))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def proximo_partido(conn, jugador_id: int, ahora: datetime) -> Optional[dict]:
    for r in conn.execute("SELECT p.*, j1.nombre AS n1, j2.nombre AS n2 FROM news_partido p "
                          "JOIN news_jugador j1 ON j1.id=p.jugador1_id JOIN news_jugador j2 ON j2.id=p.jugador2_id "
                          "WHERE p.estado='PROGRAMADO' AND (p.jugador1_id=? OR p.jugador2_id=?) ORDER BY p.fecha_estimada",
                          (jugador_id, jugador_id)).fetchall():
        f = _dt(r["fecha_estimada"])
        if f is None or f >= ahora - timedelta(hours=6):
            d = dict(r)
            d["rival"] = d["n2"] if d["jugador1_id"] == jugador_id else d["n1"]
            d["rival_id"] = d["jugador2_id"] if d["jugador1_id"] == jugador_id else d["jugador1_id"]
            d["cuota_jugador"] = d.get("cuota1") if d["jugador1_id"] == jugador_id else d.get("cuota2")
            d["cuota_rival"] = d.get("cuota2") if d["jugador1_id"] == jugador_id else d.get("cuota1")
            return d
    return None


# ═════════════════════════════════════════════════════════════════════
#  📰 NOTICIA IMPORTANTE
# ═════════════════════════════════════════════════════════════════════

def noticia_importante(conn, cfg: dict, evento: dict, jugador: dict, ahora: Optional[datetime] = None) -> dict:
    """Devuelve {'alerta_id' | None, 'motivo'}. Nunca levanta excepción por reglas."""
    ahora = ahora or datetime.now(timezone.utc)
    if not cfg.get("NEWS_DISCORD_NOTICIA", 1):
        return {"alerta_id": None, "motivo": "NEWS_DISCORD_NOTICIA=0"}
    if not descubridor.es_externo(evento):
        return {"alerta_id": None, "motivo": "INTERNO"}
    cat, nivel, nat = evento.get("categoria"), str(evento.get("nivel") or "C"), evento.get("naturaleza")
    if cat in CATEGORIAS_NOTICIA_FUERTE:
        pass
    elif cat in CATEGORIAS_NOTICIA_OFICIAL and nivel == "A":
        pass
    else:
        return {"alerta_id": None, "motivo": f"CATEGORIA_NO_RELEVANTE:{cat}"}
    if _RANGO.get(nivel, 1) < 2:
        return {"alerta_id": None, "motivo": "NIVEL_C"}
    if nat not in ("HECHO", "DECLARACION"):
        return {"alerta_id": None, "motivo": f"NATURALEZA:{nat}"}
    if float(evento.get("confianza_identidad") or 0) < float(cfg.get("NEWS_IDENTIDAD_MIN", 0.8)):
        return {"alerta_id": None, "motivo": "IDENTIDAD_DUDOSA"}
    fe = _dt(evento.get("fecha_evento"))
    max_dias = int(cfg.get("NEWS_NOTICIA_MAX_DIAS", 7))
    if fe is None or fe < ahora - timedelta(days=max_dias):
        return {"alerta_id": None, "motivo": "HECHO_VIEJO"}
    if evento.get("estado") not in (None, "VIGENTE", "EN_SEGUIMIENTO"):
        return {"alerta_id": None, "motivo": f"ESTADO:{evento.get('estado')}"}
    clave = f"NOTICIA:{jugador['id']}:{cat}"
    prev = _reciente(conn, clave, int(cfg.get("NEWS_ALERTA_REPETIR_DIAS", 7)), ahora)
    nuevo = None
    if prev:
        ev_prev = (json.loads(prev.get("evidencia_json") or "{}") or {}).get("evento") or {}
        sube_nivel = _RANGO.get(nivel, 1) > _RANGO.get(str(ev_prev.get("nivel") or "C"), 1)
        sube_nat = _RANGO_NAT.get(nat, 0) > _RANGO_NAT.get(ev_prev.get("naturaleza"), 0)
        if not (sube_nivel or sube_nat):
            return {"alerta_id": None, "motivo": f"REPETIDA:{prev['id']}"}
        nuevo = "sube de nivel" if sube_nivel else "pasa de declaración a hecho"
        clave = f"{clave}:{prev['id']}"
    tope = int(cfg.get("NEWS_MAX_NOTICIA_DIA", 8))
    if _hoy(conn, "NOTICIA", ahora) >= tope:
        return {"alerta_id": None, "motivo": "TOPE_DIARIO"}
    prox = proximo_partido(conn, jugador["id"], ahora)
    motivo = (f"noticia externa {cat} nivel {nivel} ({nat.lower()}) de {evento.get('fuente')}, hecho del "
              f"{str(evento.get('fecha_evento') or '')[:10]}, identidad {float(evento.get('confianza_identidad') or 0):.2f}"
              + (f"; información nueva: {nuevo}" if nuevo else "")
              + (f"; próximo partido vs {prox['rival']} {str(prox.get('fecha_estimada') or '')[:16]}" if prox else "; sin partido programado"))
    t = textos.armar_noticia(evento, jugador, prox, motivo)
    aid = _insertar(conn, "NOTICIA", clave, jugador["id"], prox["rival_id"] if prox else None,
                    prox["id"] if prox else None, None, [evento.get("id")], motivo,
                    {"evento": {k: evento.get(k) for k in ("id", "categoria", "nivel", "naturaleza", "fecha_evento",
                                                           "fuente", "enlace", "resumen_es", "confianza_identidad")},
                     "proximo_partido": {k: prox.get(k) for k in ("id", "torneo", "fecha_estimada", "rival")} if prox else None},
                    t["texto"], t["voz"], ahora)
    return {"alerta_id": aid, "motivo": motivo}


# ═════════════════════════════════════════════════════════════════════
#  🔎 PARTIDO INTERESANTE y 🔥
# ═════════════════════════════════════════════════════════════════════

def _externos_fuertes(eventos: list[dict]) -> list[dict]:
    return [e for e in eventos if descubridor.es_externo(e) and tx.es_fuerte(e.get("categoria", ""))
            and _RANGO.get(str(e.get("nivel") or "C"), 1) >= 2]


def partido_interesante(conn, cfg: dict, r: dict, p: dict, jx: dict, jr: dict, ex: list[dict], er: list[dict],
                        evaluacion_id: Optional[int], ahora: Optional[datetime] = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    if not cfg.get("NEWS_DISCORD_INTERESANTE", 1):
        return {"alerta_id": None, "motivo": "NEWS_DISCORD_INTERESANTE=0"}
    if r.get("tipo_alerta") != "INTERESANTE" or r.get("motivo") == "TEXTO_PROHIBIDO":
        return {"alerta_id": None, "motivo": "NO_ES_INTERESANTE"}
    fx, fr = _externos_fuertes(ex), _externos_fuertes(er)
    if not fx and not fr:
        return {"alerta_id": None, "motivo": "SIN_NOTICIA_EXTERNA"}
    horas = int(cfg.get("NEWS_RIVAL_HORAS", 48))
    faltan, fres = [], {}
    for j in (jx, jr):
        fres[j["id"]] = frescura(conn, j["id"], ahora, horas)
        if not fres[j["id"]]["reciente"]:
            adelantar(conn, j["id"], ahora)
            faltan.append(j["nombre"])
    if faltan:
        return {"alerta_id": None, "motivo": "RIVAL_SIN_INVESTIGAR:" + ", ".join(faltan)}
    clave = f"INTERESANTE:{p['id']}"
    ids = sorted(e.get("id") for e in fx + fr if e.get("id"))
    prev = _reciente(conn, clave, int(cfg.get("NEWS_ALERTA_REPETIR_DIAS", 7)), ahora)
    nuevo = []
    if prev:
        previos = set(json.loads(prev.get("evento_ids_json") or "[]"))
        nuevo = [i for i in ids if i not in previos]
        if not nuevo:
            return {"alerta_id": None, "motivo": f"REPETIDA:{prev['id']}"}
        clave = f"{clave}:{prev['id']}"
    if _hoy(conn, "INTERESANTE", ahora) >= int(cfg.get("NEWS_MAX_INTERESANTE_DIA", 6)):
        return {"alerta_id": None, "motivo": "TOPE_DIARIO"}
    pendiente = []
    if r.get("utr_x") is None or r.get("utr_rival") is None:
        pendiente.append("UTR de alguno de los dos")
    if r.get("cuota_x") is None:
        pendiente.append("cuota del mercado")
    if (r.get("justificacion") or {}).get("cuota_pendiente"):
        pendiente.append("⏳ " + r["justificacion"]["cuota_pendiente"] + " — pendiente de actualización")
    if r.get("motivo") in ("ESTADO_FISICO_SIN_VERIFICAR", "ESTADO_FISICO_SIN_VERIFICAR_RIVAL"):
        pendiente.append("estado físico tras el regreso (falta un partido completo)")
    if any(e.get("naturaleza") == "DECLARACION" for e in fx + fr):
        pendiente.append("confirmar la declaración con un hecho u otra fuente")
    motivo = (f"noticia externa {', '.join(sorted({e['categoria'] for e in fx + fr}))} nivel "
              f"{max((e.get('nivel') or 'C') for e in fx + fr)} en "
              + ("los dos" if fx and fr else jx["nombre"] if fx else jr["nombre"])
              + f"; {_frescura_txt(jx['nombre'], fres[jx['id']])}; {_frescura_txt(jr['nombre'], fres[jr['id']])}"
              + f"; motivo del descubridor: {r.get('motivo')}"
              + (f"; evento(s) nuevo(s): {nuevo}" if nuevo else ""))
    t = textos.armar_interesante(r, p, jx, jr, fx, fr, er if not fr else [], pendiente, motivo)
    aid = _insertar(conn, "INTERESANTE", clave, jx["id"], jr["id"], p["id"], evaluacion_id, ids, motivo,
                    {"eventos_x": [_ev_resumen(e) for e in fx], "eventos_rival": [_ev_resumen(e) for e in fr],
                     "contexto_rival": [_ev_resumen(e) for e in er if not descubridor.es_externo(e)][:4],
                     "utr": {"x": r.get("utr_x"), "rival": r.get("utr_rival")},
                     "cuotas": _cuotas_ev(conn, r, p), "frescura": {jx["nombre"]: fres[jx["id"]], jr["nombre"]: fres[jr["id"]]},
                     "pendiente": pendiente, "descubridor": {"motivo": r.get("motivo"), "conclusion": r.get("conclusion")}},
                    t["texto"], t["voz"], ahora)
    return {"alerta_id": aid, "motivo": motivo}


def _ev_resumen(e: dict) -> dict:
    return {k: e.get(k) for k in ("id", "categoria", "direccion", "nivel", "naturaleza", "fecha_evento", "fuente",
                                  "enlace", "resumen_es")}


def _cuotas_ev(conn, r: dict, p: dict) -> dict:
    obs = []
    try:
        obs = [{"proveedor": o["proveedor"], "cuota1": o["cuota1"], "cuota2": o["cuota2"], "capturada_en": o["capturada_en"]}
               for o in conn.execute("SELECT proveedor, cuota1, cuota2, capturada_en FROM news_cuota_obs WHERE partido_id=? "
                                     "ORDER BY id DESC LIMIT 6", (p["id"],)).fetchall()]
    except Exception:                                   # pragma: no cover
        pass
    return {"x": r.get("cuota_x"), "rival": r.get("cuota_rival"), "en": p.get("cuota_en"),
            "proveedor": p.get("cuota_proveedor"), "observaciones": obs}


# ═════════════════════════════════════════════════════════════════════
#  v5.1: justificación de la 🔥 experimental (Rubén: "qué información podría
#  no estar reflejada en la cuota, argumentos en contra y por qué merece la
#  alerta; si no alcanza, 🔎")
# ═════════════════════════════════════════════════════════════════════

def _tokens(s) -> list[str]:
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return [w for w in re.split(r"[^a-z0-9]+", t) if len(w) >= 4 and w not in ("challenger", "open", "cup", "tennis", "tenis", "torneo")]


def _pct(a, b):
    try:
        return (float(b) - float(a)) / float(a) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def justificar(conn, cfg: dict, r: dict, p: dict, jx: dict, jr: dict, ex: list[dict], er: list[dict],
               ahora: datetime) -> dict:
    """Devuelve {'no_reflejado': [...], 'a_favor': [...], 'en_contra': [...], 'puntos': n,
    'suficiente': bool, 'motivo': str, 'frescura': {...}}. Puro: no escribe."""
    horas = int(cfg.get("NEWS_RIVAL_HORAS", 48))
    min_puntos = int(cfg.get("NEWS_EXP_MIN_PUNTOS", 2))
    mov_pct = float(cfg.get("NEWS_EXP_MOV_CUOTA_PCT", 3.0))
    contra = (r.get("motivo") or "") == "CONTRA_X"            # el valor estaría en el rival
    fx = _externos_fuertes(ex)
    fr = _externos_fuertes(er)
    no_ref, favor, contra_args = [], [], []
    puntos = 0
    cuota_en = _dt(p.get("cuota_en"))
    # 1 + 2 (v5.2, Rubén 09/10 22:52: "que la noticia sea posterior a nuestra última
    # cuota no significa que el mercado no la haya incorporado"): hace falta una
    # cuota CONFIRMADA DESPUÉS de la noticia, y compararla con la de antes.
    fechas = [d for d in (_dt(e.get("fecha_publicacion")) or _dt(e.get("fecha_evento")) for e in fx) if d]
    ultima_noticia = max(fechas) if fechas else None
    cuota_pendiente = None
    cuota_antes = cuota_despues = None
    des = r.get("desvio") if isinstance(r.get("desvio"), dict) else {}
    if ultima_noticia and r.get("cuota_x"):
        from ft_news import partidos as _pt
        ad = _pt.cuota_antes_y_despues(conn, p["id"], jx["id"], ultima_noticia)
        antes, despues = ad["antes"], ad["despues"]
        cuota_antes = antes["cuota"] if antes else None
        cuota_despues = despues["cuota"] if despues else None
        hn = ultima_noticia.strftime("%d/%m %H:%M")
        if despues is None:
            # no hay precio confirmado después de la noticia: no se puede afirmar nada del mercado
            ult = cuota_en.strftime("%d/%m %H:%M") if cuota_en else "s/d"
            cuota_pendiente = (f"cuota actualizada después de la noticia ({hn} UTC); última cuota confirmada {ult} UTC"
                               f"{' (' + p.get('cuota_proveedor') + ')' if p.get('cuota_proveedor') else ''}")
            contra_args.append("sin cuota confirmada después de la noticia: no se sabe si el mercado ya la incorporó")
            puntos -= 10
        else:
            hd = (_dt(despues["hasta"]) or ahora).strftime("%d/%m %H:%M")
            if antes is None:
                # la primera cuota que vimos ya es posterior a la noticia: no hay con qué comparar
                contra_args.append(f"la cuota posterior a la noticia ({despues['cuota']:.2f}, {despues['proveedor']}, {hd} UTC) "
                                   f"no tiene una cuota previa con la que compararse")
                if (des.get("tipo") == "MERCADO_MAS_OPTIMISTA" and contra) or (des.get("tipo") == "MERCADO_MAS_PESIMISTA" and not contra):
                    no_ref.append(f"aun así, el precio posterior a la noticia va contra el UTR ({des.get('tipo').replace('_', ' ').lower()})")
                    puntos += 1
            else:
                mov = _pct(antes["cuota"], despues["cuota"])
                hacia = mov >= mov_pct if contra else mov <= -mov_pct       # CONTRA_X: X se alarga; A_FAVOR_X: X se acorta
                if hacia:
                    contra_args.append(f"el mercado ya incorporó la noticia: {jx['nombre']} {antes['cuota']:.2f} → {despues['cuota']:.2f} "
                                       f"({despues['proveedor']}, {hd} UTC)")
                    puntos -= 3
                elif abs(mov) < mov_pct:
                    no_ref.append(f"cuota confirmada después de la noticia ({hn} UTC): {jx['nombre']} sigue en {despues['cuota']:.2f} "
                                  f"(antes {antes['cuota']:.2f}; {despues['proveedor']}, {hd} UTC): el mercado no reaccionó todavía")
                    puntos += 2
                else:
                    contra_args.append(f"la cuota de {jx['nombre']} se movió en sentido contrario a la noticia "
                                       f"({antes['cuota']:.2f} → {despues['cuota']:.2f})")
                    puntos -= 1
    elif r.get("cuota_x") is None:
        cuota_pendiente = "cuota del mercado (sin precio)"
        contra_args.append("sin cuota del mercado")
        puntos -= 10
    # 3. Calidad de la evidencia
    mejor = max(fx, key=lambda e: (_RANGO.get(str(e.get("nivel") or "C"), 1), _RANGO_NAT.get(e.get("naturaleza"), 0)), default=None)
    if mejor:
        if str(mejor.get("nivel") or "C") == "A" and mejor.get("naturaleza") == "HECHO":
            favor.append(f"hecho confirmado por fuente oficial ({mejor.get('fuente')})")
            puntos += 2
        elif mejor.get("naturaleza") == "HECHO":
            favor.append(f"hecho reportado por prensa fiable ({mejor.get('fuente')})")
            puntos += 1
        else:
            contra_args.append(f"es una declaración, no un hecho confirmado ({mejor.get('fuente')})")
        if len({e.get("fuente") for e in fx}) >= 2:
            favor.append("dos o más fuentes independientes")
            puntos += 1
        fe = _dt(mejor.get("fecha_evento"))
        if fe and (ahora - fe) > timedelta(days=5):
            contra_args.append(f"el hecho tiene {(ahora - fe).days} días: puede estar ya asimilado")
            puntos -= 1
        if float(mejor.get("confianza_identidad") or 1.0) < 0.9:
            contra_args.append(f"identidad del jugador con confianza {float(mejor.get('confianza_identidad') or 0):.2f}")
            puntos -= 1
    # 3b. Retiro del MISMO torneo del partido: el partido puede no jugarse (W.O.) → no es valor
    tor = set(_tokens(p.get("torneo")))
    for e in fx:
        if e.get("categoria") == "RETIRO_ABANDONO" and tor & set(_tokens(e.get("resumen_es"))) and \
                (_dt(e.get("fecha_evento")) or ahora) >= ahora - timedelta(days=3):
            contra_args.insert(0, f"el retiro es del mismo torneo ({p.get('torneo')}): el partido puede no jugarse")
            puntos -= 10
            break
    # 4. El rival
    if fr:
        contra_args.append(f"{jr['nombre']} también tiene noticia externa ({', '.join(sorted({e['categoria'] for e in fr}))})")
        puntos -= 1
    # 5. Bandas y circuito
    if des.get("tipo") == "MERCADO_MAS_OPTIMISTA" and contra:
        no_ref.append(f"el mercado está más optimista con {jx['nombre']} de lo que dice el UTR, y encima llega una noticia negativa")
        puntos += 1
    elif des.get("tipo") == "ALINEADO":
        contra_args.append("banda UTR y mercado alineados: la ventaja, si existe, está solo en la noticia")
    if (p.get("circuito") or "") in ("challenger", "wta125", "itf", "utr"):
        favor.append(f"circuito {p.get('circuito')}: mercado menos líquido, suele tardar en incorporar noticias")
        puntos += 1
    # 6. UTR desactualizado
    for j in (jx, jr):
        u = _dt(j.get("utr_en"))
        if u and (ahora - u) > timedelta(days=30):
            contra_args.append(f"UTR de {j['nombre']} con {(ahora - u).days} días")
            puntos -= 1
    # 7. Frescura de la investigación de los dos
    fres = {jx["nombre"]: frescura(conn, jx["id"], ahora, horas), jr["nombre"]: frescura(conn, jr["id"], ahora, horas)}
    sin_fresca = [n for n, f in fres.items() if not f["reciente"]]
    for n in sin_fresca:
        contra_args.append(f"{n} sin investigación reciente (≤ {horas} h)")
    suficiente = bool(no_ref) and puntos >= min_puntos and not sin_fresca
    if not fx:
        suficiente = False
        contra_args.insert(0, "no hay noticia externa fuerte")
    if sin_fresca:
        motivo = "RIVAL_SIN_INVESTIGACION_RECIENTE:" + ", ".join(sin_fresca)
    elif any(a.startswith("el retiro es del mismo torneo") for a in contra_args):
        motivo = "RETIRO_MISMO_TORNEO"
    elif cuota_pendiente:
        motivo = "CUOTA_SIN_ACTUALIZAR"
    elif not no_ref:
        motivo = "SIN_INFORMACION_NO_REFLEJADA"
    elif puntos < min_puntos:
        motivo = f"JUSTIFICACION_INSUFICIENTE:{puntos}<{min_puntos}"
    else:
        motivo = f"JUSTIFICADA:{puntos}"
    if cuota_pendiente:
        suficiente = False
    porque = ""
    if suficiente:
        porque = (f"{'; '.join(no_ref)}; a favor: {'; '.join(favor) if favor else 'solo lo anterior'}; "
                  f"en contra: {'; '.join(contra_args) if contra_args else 'nada relevante'}; balance {puntos:+d} "
                  f"(mínimo {min_puntos})")
    return {"no_reflejado": no_ref, "a_favor": favor, "en_contra": contra_args, "puntos": puntos,
            "suficiente": suficiente, "motivo": motivo, "frescura": fres, "porque": porque,
            "sin_fresca": sin_fresca, "cuota_pendiente": cuota_pendiente,
            "cuota_x_antes": cuota_antes, "cuota_x_despues": cuota_despues}


def fuego(conn, cfg: dict, r: dict, p: dict, jx: dict, jr: dict, usados: list[dict], evaluacion_id: Optional[int],
          texto: str, voz: str, ahora: Optional[datetime] = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    tipo = r.get("tipo_alerta")
    if tipo not in ("FUEGO", "FUEGO_EXPERIMENTAL") or not texto:
        return {"alerta_id": None, "motivo": "NO_ES_FUEGO"}
    clave = f"{tipo}:{p['id']}"
    if conn.execute("SELECT 1 FROM news_alerta WHERE clave=?", (clave,)).fetchone():
        return {"alerta_id": None, "motivo": "REPETIDA"}
    if tipo == "FUEGO":
        # La validada reemplaza a la experimental del mismo partido si todavía no se dijo;
        # si ya sonó la experimental, la validada va igual (es información nueva: bandas validadas).
        conn.execute("UPDATE news_alerta SET dicho_discord=2, dicho_en=?, dicho_motivo='SUPERADA_POR_VALIDADA', "
                     "actualizado_en=? WHERE clave=? AND dicho_discord=0",
                     (ahora.isoformat(), ahora.isoformat(), f"FUEGO_EXPERIMENTAL:{p['id']}"))
    # v5.2: una 🔎 del mismo partido todavía no dicha (p. ej. "pendiente de actualización de
    # cuota") queda superada por la 🔥; si ya se dijo, la 🔥 sale igual (trae la cuota confirmada).
    conn.execute("UPDATE news_alerta SET dicho_discord=2, dicho_en=?, dicho_motivo=?, actualizado_en=? "
                 "WHERE tipo='INTERESANTE' AND partido_id=? AND dicho_discord=0",
                 (ahora.isoformat(), f"SUPERADA_POR_{tipo}", ahora.isoformat(), p["id"]))
    ext = _externos_fuertes(usados)
    motivo = (f"{'validada' if tipo == 'FUEGO' else 'EXPERIMENTAL (bandas sin validar)'}: noticia externa "
              f"{', '.join(sorted({e['categoria'] for e in ext}))} nivel {r.get('nivel')} · UTR {r.get('utr_x')} vs "
              f"{r.get('utr_rival')} ({r.get('banda_utr')}) · mercado {r.get('banda_mercado')} ({r.get('cuota_x')}) · "
              f"{r.get('desvio', {}).get('tipo') if isinstance(r.get('desvio'), dict) else ''} · lado {r.get('motivo')}"
              + ("; explicaciones posibles: " + "; ".join(r.get("explicaciones") or []) if r.get("explicaciones") else ""))
    j = r.get("justificacion") or {}
    if j.get("porque"):
        motivo += " · justificación: " + j["porque"]
    aid = _insertar(conn, tipo, clave, jx["id"], jr["id"], p["id"], evaluacion_id, [e.get("id") for e in usados], motivo,
                    {"eventos": [_ev_resumen(e) for e in usados], "utr": {"x": r.get("utr_x"), "rival": r.get("utr_rival")},
                     "cuotas": _cuotas_ev(conn, r, p),
                     "bandas": {"utr": r.get("banda_utr"), "mercado": r.get("banda_mercado"), "desvio": r.get("desvio")},
                     "explicaciones": r.get("explicaciones"), "bandas_calibradas": r.get("bandas_calibradas"),
                     "justificacion": {k: j.get(k) for k in ("no_reflejado", "a_favor", "en_contra", "puntos", "frescura",
                                                             "cuota_x_antes", "cuota_x_despues")}},
                    texto, voz, ahora)
    return {"alerta_id": aid, "motivo": motivo}


# ═════════════════════════════════════════════════════════════════════
#  Feed y marcas
# ═════════════════════════════════════════════════════════════════════

def vencer_pendientes(conn, cfg: dict, ahora: Optional[datetime] = None) -> int:
    """v5.1: lo que lleva más de NEWS_SENAL_MAX_HORAS sin decirse ya no vale (la
    noticia vale AHORA): queda omitida con motivo VENCIDA. Así, al encender
    NEWS_DISCORD_ACTIVO después de días apagado, no sale una avalancha."""
    ahora = ahora or datetime.now(timezone.utc)
    lim = (ahora - timedelta(hours=int(cfg.get("NEWS_SENAL_MAX_HORAS", 12)))).isoformat()

    def _w():
        n = conn.execute("UPDATE news_alerta SET dicho_discord=2, dicho_en=?, dicho_motivo='VENCIDA', actualizado_en=? "
                         "WHERE dicho_discord=0 AND creado_en < ?", (ahora.isoformat(), ahora.isoformat(), lim)).rowcount
        conn.commit()
        return n
    return ejecutar_con_reintento(_w, conn=conn)


def pendientes(conn, cfg: dict, limite: int = 50) -> list[dict]:
    """Lo no dicho (el vencimiento por NEWS_SENAL_MAX_HORAS lo aplica el ciclo: vencer_pendientes)."""
    tipos = []
    if cfg.get("NEWS_DISCORD_NOTICIA", 1):
        tipos.append("NOTICIA")
    if cfg.get("NEWS_DISCORD_INTERESANTE", 1):
        tipos.append("INTERESANTE")
    tipos.append("FUEGO")
    if cfg.get("NEWS_EXPERIMENTAL_ACTIVO", 1):
        tipos.append("FUEGO_EXPERIMENTAL")
    if cfg.get("NEWS_PRUEBA_SOLO_ADMIN_VERIFICADA", 0):
        tipos.append("PRUEBA")                  # v7.3: solo con el destino de admin verificado
    q = ("SELECT a.*, jx.nombre AS jugador_x, jr.nombre AS rival, p.torneo, p.fecha_estimada, p.genero, p.circuito, "
         "p.fixture_id, p.cuota1, p.cuota2, p.jugador1_id FROM news_alerta a "
         "LEFT JOIN news_jugador jx ON jx.id=a.jugador_id LEFT JOIN news_jugador jr ON jr.id=a.rival_id "
         "LEFT JOIN news_partido p ON p.id=a.partido_id WHERE a.dicho_discord=0 AND a.tipo IN (%s) "
         "AND a.texto_discord<>'' ORDER BY a.id LIMIT ?" % ",".join("?" * len(tipos)))
    out = []
    for r in conn.execute(q, (*tipos, limite)).fetchall():
        d = dict(r)
        d["tipo_alerta"] = d["tipo"]
        if d["tipo"] == "PRUEBA":
            # viaja con el formato de 📰 (el tipo que FT Intelligence ya conoce) y la marca prueba=1
            d["tipo_alerta"], d["prueba"] = "NOTICIA", 1
            d["solo_admin"], d["destino"] = True, "ADMIN"     # nunca al canal de la comunidad
        d["motivo"] = d.get("motivo_seleccion")
        try:
            ev = json.loads(d.get("evidencia_json") or "{}")
        except ValueError:
            ev = {}
        d["conclusion"] = ((ev.get("descubridor") or {}).get("conclusion")) if isinstance(ev, dict) else None
        u, c = (ev.get("utr") or {}), (ev.get("cuotas") or {})
        d["utr_x"], d["utr_rival"], d["cuota_x"], d["cuota_rival"] = u.get("x"), u.get("rival"), c.get("x"), c.get("rival")
        b = ev.get("bandas") or {}
        d["banda_utr"], d["banda_mercado"] = b.get("utr"), b.get("mercado")
        d["nivel"] = None
        out.append(d)
    return out


def marcar_dichas(conn, avisos: list[dict]) -> int:
    ahora = ahora_iso()

    def _w():
        n = 0
        for a in avisos:
            n += conn.execute("UPDATE news_alerta SET dicho_discord=?, dicho_en=?, dicho_motivo=COALESCE(?, dicho_motivo), "
                              "actualizado_en=? WHERE id=? AND dicho_discord=0",
                              (1 if a.get("dicho") else 2, a.get("en") or ahora, a.get("motivo"), ahora, a.get("id"))).rowcount
            ev = conn.execute("SELECT evaluacion_id, tipo FROM news_alerta WHERE id=?", (a.get("id"),)).fetchone()
            if ev and ev["evaluacion_id"] and ev["tipo"] in ("FUEGO", "FUEGO_EXPERIMENTAL"):
                conn.execute("UPDATE news_evaluacion SET dicho_discord=?, dicho_en=?, dicho_motivo=COALESCE(?, dicho_motivo) "
                             "WHERE id=? AND dicho_discord=0",
                             (1 if a.get("dicho") else 2, a.get("en") or ahora, a.get("motivo"), ev["evaluacion_id"]))
        conn.commit()
        return n
    return ejecutar_con_reintento(_w, conn=conn)


def listar(conn, limite: int = 100, tipo: Optional[str] = None) -> list[dict]:
    # v7.2: las PRUEBA no son alertas: solo aparecen si se piden explícitamente
    w, args = "WHERE COALESCE(a.prueba,0)=0", []
    if tipo == "PRUEBA":
        w, args = "WHERE a.tipo='PRUEBA'", []
    elif tipo:
        w, args = "WHERE COALESCE(a.prueba,0)=0 AND a.tipo=?", [tipo]
    out = []
    for r in conn.execute(
            "SELECT a.*, jx.nombre AS jugador, jr.nombre AS rival, p.torneo, p.fecha_estimada, p.estado AS partido_estado, "
            "res.ganador_id, res.retiro, res.score, res.cuota_cierre_x, res.era_interesante FROM news_alerta a "
            "LEFT JOIN news_jugador jx ON jx.id=a.jugador_id LEFT JOIN news_jugador jr ON jr.id=a.rival_id "
            "LEFT JOIN news_partido p ON p.id=a.partido_id LEFT JOIN news_resultado res ON res.evaluacion_id=a.evaluacion_id "
            f"{w} ORDER BY a.id DESC LIMIT ?", (*args, limite)).fetchall():
        d = dict(r)
        try:
            d["evidencia"] = json.loads(d.pop("evidencia_json") or "{}")
        except ValueError:
            d["evidencia"] = {}
        # v7.3: recorrido de cada alerta (creada → recibida → publicada), sin dar por publicada lo no confirmado
        d["recorrido"] = pasos_alerta(d)
        # v7: por qué se seleccionó, en palabras; el técnico sigue en motivo_seleccion
        try:
            from ft_news import explicar
            d["motivo_simple"] = explicar.alerta_simple(d)
            d["dicho_motivo_simple"] = explicar.motivo_simple(d.get("dicho_motivo")) if d.get("dicho_motivo") else None
        except Exception:                            # pragma: no cover
            d["motivo_simple"], d["dicho_motivo_simple"] = d.get("motivo_seleccion"), d.get("dicho_motivo")
        out.append(d)
    return out


# ═════════════════════════════════════════════════════════════════════
# v7.2 (13/10/2026) — Prueba REAL de Discord, solo administradores
# ═════════════════════════════════════════════════════════════════════

PRUEBA_ENCABEZADO = "🧪 PRUEBA DE FT NEWS — NO ES UNA OPORTUNIDAD"
PRUEBA_BLOQUEADA = ("La prueba de Discord está bloqueada hasta comprobar que FT Intelligence y FT Discord la "
                    "mandan solo al canal de administradores y no a la comunidad.")


def crear_prueba(conn, por: str = "", ahora: Optional[datetime] = None, cfg: Optional[dict] = None) -> dict:
    """Deja en la cola de FT Intelligence una alerta marcada PRUEBA (tipo PRUEBA,
    prueba=1, solo_admin). Viaja con el formato de 📰 NOTICIA y su texto lo dice en la
    primera línea. No cuenta en historial, dashboard, topes ni estadísticas.
    v7.3: bloqueada mientras NEWS_PRUEBA_SOLO_ADMIN_VERIFICADA=0 (no se sabe todavía
    si FT Intelligence / FT Discord la mandarían a la comunidad)."""
    from ft_news import config as _config
    cfg = cfg or _config.leer_config(conn)
    if not int(cfg.get("NEWS_PRUEBA_SOLO_ADMIN_VERIFICADA", 0)):
        raise PermissionError(PRUEBA_BLOQUEADA)
    ahora = ahora or datetime.now(timezone.utc)
    prev = conn.execute("SELECT id FROM news_alerta WHERE tipo='PRUEBA' AND dicho_discord=0 ORDER BY id DESC LIMIT 1").fetchone()
    if prev:
        r = estado_prueba(conn, prev["id"], ahora)
        r["aviso"] = "Ya había una prueba en curso: se sigue esa."
        return r
    quien = (por or "admin").strip()[:60]
    hora = ahora.strftime("%d/%m/%Y %H:%M")
    texto = (f"{PRUEBA_ENCABEZADO}\n"
             f"Mensaje de comprobación pedido por {quien} el {hora} UTC.\n"
             f"Recorrido: FT NEWS → FT Intelligence → FT Discord.\n"
             f"Ignorar: no hay ningún partido ni cuota detrás de este mensaje.")
    voz = "Prueba de FT NEWS. No es una oportunidad."
    if textos.hay_prohibido(texto):                       # pragma: no cover — defensa
        raise ValueError("texto de prueba con palabras prohibidas")

    def _w():
        cur = conn.execute(
            "INSERT INTO news_alerta (tipo, clave, jugador_id, rival_id, partido_id, evaluacion_id, evento_ids_json, "
            "motivo_seleccion, evidencia_json, texto_discord, texto_voz, dicho_discord, prueba, creado_en, actualizado_en) "
            "VALUES ('PRUEBA', ?, NULL, NULL, NULL, NULL, '[]', ?, ?, ?, ?, 0, 1, ?, ?)",
            (f"PRUEBA:{ahora.isoformat()}", f"PRUEBA pedida por {quien}",
             json.dumps({"prueba": True, "por": quien}), texto, voz, ahora.isoformat(), ahora.isoformat()))
        conn.commit()
        return cur.lastrowid
    pid = ejecutar_con_reintento(_w, conn=conn)
    return estado_prueba(conn, pid, ahora)


def registrar_entrega(conn, ids: list, ahora: Optional[datetime] = None) -> None:
    """Paso 2: FT Intelligence recogió estas alertas de /news/senales."""
    if not ids:
        return
    ts = (ahora or datetime.now(timezone.utc)).isoformat()

    def _w():
        conn.executemany("UPDATE news_alerta SET entregada_en=COALESCE(entregada_en, ?), entregas=entregas+1 WHERE id=?",
                         [(ts, i) for i in ids])
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def registrar_publicacion(conn, avisos: list[dict]) -> int:
    """Paso 3: lo que informe FT Intelligence sobre la publicación real en FT Discord.
    Cada aviso puede traer `publicado` (true/false), `publicado_en` y `canal` o `error`.
    Sin `publicado`, la publicación queda SIN CONFIRMAR (nunca se da por hecha)."""
    ahora = ahora_iso()
    filas = [(1 if a["publicado"] else 0, a.get("publicado_en") or ahora,
              str(a.get("canal") or a.get("error") or "")[:300],
              str(a.get("canal") or "")[:120] or None, str(a.get("error") or "")[:300] or None, a.get("id"))
             for a in avisos if a.get("id") is not None and a.get("publicado") is not None]
    if not filas:
        return 0

    def _w():
        n = conn.executemany("UPDATE news_alerta SET publicado=?, publicado_en=?, publicado_detalle=?, publicado_canal=?, "
                             "publicado_error=? WHERE id=?", filas).rowcount
        conn.commit()
        return n
    return ejecutar_con_reintento(_w, conn=conn)


def pasos_alerta(d: dict, leida_en: Optional[str] = None, ahora: Optional[datetime] = None) -> dict:
    """Los tres pasos de una alerta, en palabras, sin códigos:
       1 FT NEWS la creó · 2 FT Intelligence la recibió · 3 FT Discord la publicó.
    'Recibida' NUNCA se presenta como 'publicada'."""
    ahora = ahora or datetime.now(timezone.utc)
    ok, espera, falla = "✅", "⏳", "❌"
    p1 = {"paso": 1, "nombre": "FT NEWS creó la alerta", "estado": ok, "en": d.get("creado_en"), "detalle": ""}
    # No salir a propósito NO es un fallo: una 🔎 que reemplazó una 🔥 del mismo partido
    if d.get("dicho_discord") == 2 and str(d.get("dicho_motivo") or "").startswith("SUPERADA") and not d.get("entregada_en"):
        nuevo = "una 🔥 del mismo partido" if "FUEGO" in str(d.get("dicho_motivo")) else "una alerta más completa del mismo partido"
        return {"estado": "REEMPLAZADA", "resumen": f"No se envió porque la reemplazó {nuevo}.",
                "pasos": [p1, {"paso": 2, "nombre": "FT Intelligence la recibió", "estado": "➖", "en": d.get("dicho_en"),
                               "detalle": f"Reemplazada por {nuevo} antes de salir."},
                          {"paso": 3, "nombre": "FT Discord la publicó", "estado": "➖", "en": None, "detalle": "No correspondía."}]}
    if d.get("entregada_en"):
        p2 = {"paso": 2, "nombre": "FT Intelligence la recibió", "estado": ok, "en": d["entregada_en"], "detalle": ""}
    elif d.get("dicho_discord") == 2:
        p2 = {"paso": 2, "nombre": "FT Intelligence la recibió", "estado": falla, "en": d.get("dicho_en"),
              "detalle": ("FT Intelligence nunca la recogió y venció." if d.get("dicho_motivo") == "VENCIDA"
                          else f"Se descartó antes de llegar: {d.get('dicho_motivo') or 'sin motivo'}.")}
    else:
        p2 = {"paso": 2, "nombre": "FT Intelligence la recibió", "estado": espera, "en": None,
              "detalle": "Esperando que FT Intelligence revise la cola"
                         + (f" (la revisó por última vez el {str(leida_en)[:16].replace('T', ' ')} UTC)." if leida_en
                            else " (no hay registro de que la haya revisado nunca).")}
    canal = {"comunidad": "el canal de la comunidad", "admin": "el canal de administradores"}.get(
        d.get("publicado_canal") or "", d.get("publicado_canal") or "")
    if d.get("publicado") == 1:
        p3 = {"paso": 3, "nombre": "FT Discord la publicó", "estado": ok, "en": d.get("publicado_en"),
              "detalle": f"Publicada{(' en ' + canal) if canal else ''}."}
    elif d.get("publicado") == 0:
        p3 = {"paso": 3, "nombre": "FT Discord la publicó", "estado": falla, "en": d.get("publicado_en"),
              "detalle": f"No se publicó: {d.get('publicado_error') or d.get('publicado_detalle') or 'sin detalle'}."}
    elif d.get("dicho_discord") == 2 and d.get("entregada_en"):
        p3 = {"paso": 3, "nombre": "FT Discord la publicó", "estado": falla, "en": d.get("dicho_en"),
              "detalle": f"FT Intelligence la recibió pero no la pasó a Discord: {d.get('dicho_motivo') or 'sin motivo'}."}
    elif d.get("dicho_discord") == 1:
        p3 = {"paso": 3, "nombre": "FT Discord la publicó", "estado": espera, "en": None,
              "detalle": "FT Intelligence dice que la procesó, pero FT Discord todavía no confirmó la publicación. "
                         "No se da por publicada hasta que llegue esa confirmación (o la veas en el canal)."}
    else:
        p3 = {"paso": 3, "nombre": "FT Discord la publicó", "estado": espera, "en": None, "detalle": "Todavía no llegó a este paso."}
    pasos = [p1, p2, p3]
    fallo = next((x for x in pasos if x["estado"] == falla), None)
    if fallo:
        resumen = f"Falló en el paso {fallo['paso']} ({fallo['nombre'].lower()}): {fallo['detalle']}"
        estado = "FALLO"
    elif p3["estado"] == ok:
        resumen, estado = "Recorrido completo: publicada en Discord.", "PUBLICADA"
    elif p2["estado"] == ok:
        resumen, estado = "Recibida por FT Intelligence; falta la confirmación de publicación de FT Discord.", "RECIBIDA"
    else:
        resumen, estado = "Creada; esperando que FT Intelligence la recoja.", "CREADA"
    return {"estado": estado, "resumen": resumen, "pasos": pasos}


def estado_prueba(conn, pid: int, ahora: Optional[datetime] = None) -> Optional[dict]:
    r = conn.execute("SELECT * FROM news_alerta WHERE id=? AND tipo='PRUEBA'", (pid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    leida = conn.execute("SELECT valor FROM news_estado WHERE clave='senales_leidas_en'").fetchone()
    pa = pasos_alerta(d, leida["valor"] if leida else None, ahora)
    return {"id": d["id"], "estado": pa["estado"], "resumen": pa["resumen"], "pasos": pa["pasos"],
            "creada_en": d["creado_en"], "texto": d["texto_discord"]}
