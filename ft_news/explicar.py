"""
ft_news/explicar.py — v7 (10/10/2026, Rubén): TODO FT NEWS en palabras
simples. "Investigación profesional por dentro y una presentación sencilla por
fuera": acá se traduce lo que el motor calculó (códigos, bandas, motivos) a
frases cortas que cualquier usuario entiende en pocos segundos. Los códigos
siguen guardados y viajan aparte (detalles técnicos, solo admin).

Cada análisis responde:
  🎾 quién juega · 🚨 qué noticia o situación · 🔴 a quién perjudica ·
  🟢 a quién podría favorecer · 💰 cuota · 📊 UTR · 🧭 por qué importa.
Sin probabilidades, sin porcentajes, sin "apostar", sin enlaces, sin inventar
un favorecido cuando no hay evidencia.
"""
from __future__ import annotations

import json
from typing import Optional

from ft_news import contexto, descubridor
from ft_news import taxonomia as tx
from ft_news.textos import _cuota, _frase, _mayus, _torneo, _utr, apellido

FUEGOS = ("FUEGO", "FUEGO_EXPERIMENTAL")

ENCABEZADOS = {
    "FUEGO": "🔥 FULLTENNIS · POSIBLE VALOR POR NOTICIAS",
    "FUEGO_EXPERIMENTAL": "🔥 FULLTENNIS · POSIBLE VALOR EXPERIMENTAL",
    "INTERESANTE": "🔎 FULLTENNIS · PARTIDO EN ANÁLISIS",
    "NOTICIA": "📰 FULLTENNIS · NOTICIA IMPORTANTE",
    "NADA": "⚪ FULLTENNIS · SIN SEÑAL",
}

CATEGORIAS = {
    "LESION_MOLESTIA": "Lesión o molestia", "ENFERMEDAD": "Enfermedad", "RETIRO_ABANDONO": "Retiro o abandono",
    "REGRESO": "Regreso a la competencia", "SANCION_DISCIPLINA": "Sanción", "CARGA_FISICA": "Carga física",
    "VIAJE_CALENDARIO": "Viaje y calendario", "PUNTOS_DEFENDIDOS": "Puntos que defiende",
    "DECLARACION_PREPARACION": "Declaración sobre su preparación", "DECLARACION_MOTIVACION": "Declaración",
    "ANTECEDENTE_TORNEO": "Antecedentes en el torneo", "LOCALIA": "Juega en su país", "SUPERFICIE": "Superficie",
    "CAMBIO_EQUIPO": "Cambio de equipo", "SITUACION_PERSONAL": "Situación personal", "RANKING_OBJETIVO": "Objetivo de ranking",
    "RESULTADO_RECIENTE": "Resultado reciente", "OTRA": "Otra noticia",
}
ESTADOS = {"VIGENTE": "vigente", "EN_SEGUIMIENTO": "en seguimiento", "VENCIDO": "vencida", "DESMENTIDO": "desmentida",
           "VERIFICADO": "verificada", "DESCARTADO": "descartada", "SUPERADO": "superada"}
DIRECCIONES = {tx.NEGATIVA: "perjudica", tx.POSITIVA: "favorece", tx.MIXTA: "puede pesar en los dos sentidos", tx.NEUTRA: "no cambia nada"}
NIVELES = {"A": "hecho confirmado", "B": "fuente fiable", "C": "sin confirmar"}

# Motivos del motor → una frase. Lo que no está acá se muestra en palabras genéricas.
MOTIVOS = {
    "SIN_NOTICIA_EXTERNA_FUERTE": "Solo hay datos calculados por nosotros (carga, calendario, antecedentes). Sin una noticia externa no se habla de valor.",
    "CONTEXTO": "Hay contexto, pero no marca una dirección clara a favor de ninguno.",
    "EVIDENCIA_INSUFICIENTE": "La información encontrada no alcanza el nivel de evidencia necesario.",
    "SIN_UTR": "Falta el UTR de alguno de los dos para comparar con la cuota.",
    "UTR_VIEJO": "El UTR de alguno de los dos está desactualizado.",
    "SIN_MERCADO": "Todavía no hay cuota disponible.",
    "MERCADO_EN_MOVIMIENTO": "La cuota ya se está moviendo en la dirección de la noticia.",
    "MERCADO_YA_DESCONTO": "La cuota ya refleja la noticia: no hay oportunidad.",
    "BANDAS_NO_CALIBRADAS": "Sin lectura de mercado validada todavía.",
    "YA_AVISADO": "Ya se avisó de este jugador en este torneo.",
    "TOPE_DIARIO": "Se alcanzó el tope diario de alertas.",
    "CUOTA_SIN_ACTUALIZAR": "Falta una cuota actualizada después de la noticia para saber si el mercado ya la incorporó.",
    "RIVAL_SIN_INVESTIGACION_RECIENTE": "Falta investigar al rival antes de hablar de ventaja.",
    "RIVAL_SIN_INVESTIGAR": "Falta investigar al rival antes de hablar de ventaja.",
    "RETIRO_MISMO_TORNEO": "El jugador se retiró en este mismo torneo: el partido podría no jugarse.",
    "SIN_INFORMACION_NO_REFLEJADA": "El mercado parece haber incorporado la noticia.",
    "JUSTIFICACION_INSUFICIENTE": "No hay evidencia suficiente de valor en la cuota.",
    "DIRECCION_CONTRADICTORIA": "Hay noticias en los dos sentidos: sin favorecido claro.",
    "DIRECCION_CONTRADICTORIA_RIVAL": "Hay noticias en los dos sentidos: sin favorecido claro.",
    "ESTADO_FISICO_SIN_VERIFICAR": "Regreso reciente sin un partido completo que confirme el estado físico.",
    "ESTADO_FISICO_SIN_VERIFICAR_RIVAL": "Regreso reciente del rival sin un partido completo que confirme su estado físico.",
    "IDENTIDAD_DUDOSA": "No se pudo confirmar de qué jugador habla la noticia.",
    "SIN_EVENTOS": "Sin noticias ni contexto para este partido.",
    "PARTIDO_EMPEZADO": "El partido ya empezó.",
    "TEXTO_PROHIBIDO": "El texto no cumplía las reglas de publicación.",
    "CONTRA_X": "La noticia perjudica al jugador y la cuota todavía no parece reflejarla.",
    "A_FAVOR_X": "La noticia favorece al jugador y la cuota todavía no parece reflejarla.",
    "NEWS_DISCORD_INTERESANTE=0": "Las alertas 🔎 están apagadas.",
    "SIN_NOTICIA_EXTERNA": "Sin noticia externa: no sale a Discord.",
    "NO_ES_INTERESANTE": "No es un partido interesante.",
    "ERROR": "Error del motor.",
}
_MOTIVOS_PREFIJO = {
    "REPETIDA": "Ya se avisó de este partido con la misma información.",
    "SUPERADA_POR_VALIDADA": "Fue superada por una alerta validada del mismo partido.",
    "SUPERADA_POR": "Fue superada por otra alerta del mismo partido.",
    "VENCIDA": "Venció antes de salir (más de 12 h pendiente).",
    "RIVAL_SIN_INVESTIGAR": "Falta investigar al rival antes de hablar de ventaja.",
    "CARGA_": "Se investiga por carga física.",
}


def motivo_simple(codigo: Optional[str]) -> str:
    """Un código del motor (o 'CODIGO:detalle') → frase."""
    if not codigo:
        return ""
    c = str(codigo).strip()
    base = c.split(":")[0]
    if base in MOTIVOS:
        return MOTIVOS[base]
    for pref, txt in _MOTIVOS_PREFIJO.items():
        if base.startswith(pref):
            return txt
    if c.lower().startswith("error"):
        return "Error del motor."
    return base.replace("_", " ").capitalize() + "."


def categoria_es(cat: Optional[str]) -> str:
    return CATEGORIAS.get(str(cat or ""), str(cat or "").replace("_", " ").capitalize() or "Noticia")


def evento_simple(ev: dict, nombre: Optional[str] = None) -> str:
    """Un evento en una frase: '🔴 Lesión o molestia · perjudica a X: <qué pasó>.'"""
    d = ev.get("direccion")
    ico = "🔴" if d == tx.NEGATIVA else "🟢" if d == tx.POSITIVA else "🟡" if d == tx.MIXTA else "⚪"
    quien = nombre or ev.get("jugador") or ""
    verbo = DIRECCIONES.get(d, "")
    if d in (tx.NEGATIVA, tx.POSITIVA) and quien:
        verbo = f"{verbo} a {quien}"
    elif quien:
        verbo = f"{quien}: {verbo}"
    origen = "" if descubridor.es_externo(ev) else " (dato calculado por nosotros)"
    que = _frase(ev, 140) if (ev.get("titular") or ev.get("resumen_es") or ev.get("fragmento_original")) else ""
    return f"{ico} {categoria_es(ev.get('categoria'))} · {verbo}{origen}" + (f": {que}" if que else ".")


def _nivel_utr(ux, ur, x: str, r: str, cfg: Optional[dict] = None) -> str:
    if ux is None or ur is None:
        return "Falta el UTR de alguno de los dos."
    d = float(ux) - float(ur)
    parejo = float((cfg or {}).get("NEWS_BANDA_UTR_PAREJO", 0.30) or 0.30)
    fav = float((cfg or {}).get("NEWS_BANDA_UTR_FAVORITO", 0.80) or 0.80)
    if abs(d) < parejo:
        return "Jugadores prácticamente igualados por UTR."
    arriba = x if d > 0 else r
    if abs(d) < fav:
        return f"{arriba} parte ligeramente por encima por UTR."
    return f"{arriba} es claramente superior por UTR."


def _favorecido_externo(jx: dict, jr: dict, ev: dict, fx: list[dict], fr: list[dict]):
    """(nombre, cuota) solo con noticias EXTERNAS; (None, None) si no hay evidencia clara."""
    neg_x = any(e.get("direccion") == tx.NEGATIVA for e in fx)
    pos_x = any(e.get("direccion") == tx.POSITIVA for e in fx)
    neg_r = any(e.get("direccion") == tx.NEGATIVA for e in fr)
    pos_r = any(e.get("direccion") == tx.POSITIVA for e in fr)
    a_r = (neg_x and not neg_r) or (pos_r and not pos_x and not neg_r)
    a_x = (neg_r and not neg_x) or (pos_x and not pos_r and not neg_x)
    if a_r and not a_x:
        return jr["nombre"], ev.get("cuota_rival")
    if a_x and not a_r:
        return jx["nombre"], ev.get("cuota_x")
    return None, None


def evaluacion(ev: dict, partido: dict, jx: dict, jr: dict, eventos: list[dict],
               carga_x: Optional[dict] = None, carga_r: Optional[dict] = None, cfg: Optional[dict] = None,
               justificacion: Optional[dict] = None) -> dict:
    """La lectura simple de una evaluación. `eventos` = los que usó el motor
    (externos y calculados, ya sin repetidos). Devuelve encabezado, líneas,
    texto, resumen (una frase), favorecido y motivo en palabras."""
    tipo = str(ev.get("tipo_alerta") or "NADA")
    motivo = str(ev.get("motivo") or "")
    x, r = jx.get("nombre") or "?", jr.get("nombre") or "?"
    eventos = descubridor.sin_repetidos(eventos or [])
    ext = [e for e in eventos if descubridor.es_externo(e)]
    fx = [e for e in ext if e.get("jugador_id") in (None, jx.get("id"))]
    fr = [e for e in ext if jr.get("id") is not None and e.get("jugador_id") == jr.get("id")]
    lineas = [ENCABEZADOS.get(tipo, ENCABEZADOS["NADA"]), f"🎾 {x} vs {r}", f"🏆 {_torneo(partido) or 'Torneo s/d'}",
              f"📊 UTR: {_utr(ev.get('utr_x'))} vs {_utr(ev.get('utr_rival'))}",
              f"💰 {apellido(x)} {_cuota(ev.get('cuota_x'))} | {apellido(r)} {_cuota(ev.get('cuota_rival'))}",
              f"⚖️ NIVEL: {_nivel_utr(ev.get('utr_x'), ev.get('utr_rival'), apellido(x), apellido(r), cfg)}"]
    # 🚨 noticias externas (máximo 2, una por jugador si hay en los dos)
    noticias = []
    for lista, nombre in ((fx, x), (fr, r)):
        if lista:
            e = lista[0]
            noticias.append(f"🚨 NOTICIA: {apellido(nombre)} — {_frase(e, 110)}")
    lineas += noticias
    # 🔴 / 🟢 solo con evidencia externa; una 🔥 ya trae su favorecido decidido
    favorecido, cuota_fav = None, None
    if tipo in FUEGOS:
        contra = motivo == "CONTRA_X"
        favorecido = r if contra else x
        cuota_fav = ev.get("cuota_rival") if contra else ev.get("cuota_x")
        perjudicado = x if contra else None
        if perjudicado:
            lineas.append(f"🔴 PERJUDICA A: {perjudicado}")
        lineas.append(f"🟢 JUGADOR FAVORECIDO: {_mayus(favorecido)}")
        lineas.append(f"💰 CUOTA: {_cuota(cuota_fav)}")
    elif ext and motivo not in ("RETIRO_MISMO_TORNEO", "DIRECCION_CONTRADICTORIA", "DIRECCION_CONTRADICTORIA_RIVAL"):
        favorecido, cuota_fav = _favorecido_externo(jx, jr, ev, fx, fr)
        neg_x = any(e.get("direccion") == tx.NEGATIVA for e in fx)
        neg_r = any(e.get("direccion") == tx.NEGATIVA for e in fr)
        if neg_x and not neg_r:
            lineas.append(f"🔴 PERJUDICA A: {x}")
        elif neg_r and not neg_x:
            lineas.append(f"🔴 PERJUDICA A: {r}")
        if favorecido:
            lineas.append(f"🟢 PODRÍA FAVORECER A: {_mayus(favorecido)}" + (f" @{_cuota(cuota_fav)}" if cuota_fav else ""))
        elif fx and fr:
            lineas.append("⚪ Noticias en los dos: sin favorecido claro.")
    # 🟡 carga física: la de X siempre que haya dato; la del rival solo si no es normal
    carga_txt = []
    cx = carga_x or {}
    if cx.get("clase") and cx["clase"] != "SIN_DATOS":
        carga_txt.append(cx.get("texto") or contexto.describir_carga(cx, apellido(x)))
    cr = carga_r or {}
    if cr.get("clase") in ("CONSIDERABLE", "EXCEPCIONAL", "INACTIVIDAD"):
        carga_txt.append(cr.get("texto") or contexto.describir_carga(cr, apellido(r)))
    for t in carga_txt:
        lineas.append(f"🟡 CARGA FÍSICA: {t}")
    # 🧭 conclusión
    if tipo in FUEGOS:
        concl = (f"La noticia podría favorecer a {favorecido} y la cuota todavía no parece reflejarla. "
                 + ("Lectura validada." if tipo == "FUEGO" else "Lectura experimental, sin validar estadísticamente."))
    elif tipo == "INTERESANTE" and ext:
        concl = motivo_simple(motivo) or "Partido en análisis."
        if favorecido and motivo in ("CUOTA_SIN_ACTUALIZAR", "RIVAL_SIN_INVESTIGACION_RECIENTE", "RIVAL_SIN_INVESTIGAR", "BANDAS_NO_CALIBRADAS",
                                     "SIN_MERCADO", "SIN_UTR", "UTR_VIEJO"):
            concl = f"La noticia podría favorecer a {favorecido}, pero todavía no hay evidencia suficiente para confirmar una oportunidad. {concl}"
    elif carga_txt and not ext:
        clases = {cx.get("clase"), cr.get("clase")}
        if "EXCEPCIONAL" in clases:
            concl = "La carga reciente es excepcional y se está investigando; sin una noticia que lo confirme, no se afirma una ventaja."
        elif "CONSIDERABLE" in clases:
            concl = "La carga reciente merece seguimiento, pero no alcanza para hablar de ventaja por desgaste físico."
        else:
            concl = "No se identifica una ventaja clara por desgaste físico."
    else:
        concl = motivo_simple(motivo) or "No se identifica una ventaja clara."
    lineas.append(f"🧭 CONCLUSIÓN: {concl}")
    resumen = concl if not favorecido else f"Podría favorecer a {favorecido}" + (f" ({_cuota(cuota_fav)})" if cuota_fav else "") + f". {concl}"
    return {"encabezado": lineas[0], "lineas": lineas, "texto": "\n".join(lineas), "resumen": resumen,
            "favorecido": favorecido, "cuota_favorecido": cuota_fav, "motivo": motivo_simple(motivo),
            "tiene_noticia_externa": bool(ext), "carga": carga_txt}


def evaluacion_desde_db(conn, e: dict, cfg: Optional[dict] = None) -> dict:
    """Arma la lectura simple de una fila de news_evaluacion (para /news/hoy y
    el detalle): lee partido, jugadores, eventos usados y la carga guardada."""
    from ft_news import memoria  # noqa: F401  (import local: evita ciclos)
    p = conn.execute("SELECT * FROM news_partido WHERE id=?", (e.get("partido_id"),)).fetchone()
    p = dict(p) if p else {"torneo": e.get("torneo")}
    js = {}
    for k in ("jugador_x_id", "rival_id"):
        j = conn.execute("SELECT id, nombre FROM news_jugador WHERE id=?", (e.get(k),)).fetchone()
        js[k] = dict(j) if j else {"id": e.get(k), "nombre": e.get("jugador_x" if k == "jugador_x_id" else "rival") or "?"}
    try:
        ids = [int(i) for i in json.loads(e.get("eventos_json") or "[]") if i is not None]
    except (TypeError, ValueError):
        ids = []
    evs = [dict(r) for r in conn.execute(
        f"SELECT * FROM news_evento WHERE id IN ({','.join('?' * len(ids)) or 'NULL'})", ids)] if ids else []
    return evaluacion(e, p, js["jugador_x_id"], js["rival_id"], evs,
                      contexto.carga_de(conn, js["jugador_x_id"]["id"], e.get("partido_id")),
                      contexto.carga_de(conn, js["rival_id"]["id"], e.get("partido_id")), cfg)


def alerta_simple(a: dict) -> str:
    """Por qué se seleccionó una alerta, en una frase (el motivo técnico queda en motivo_seleccion)."""
    tipo = a.get("tipo")
    ev = a.get("evidencia") or {}
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except (TypeError, ValueError):
            ev = {}
    cats = set()
    for k in ("eventos_x", "eventos_rival", "eventos"):
        for e in ev.get(k) or []:
            if e.get("categoria"):
                cats.add(categoria_es(e["categoria"]))
    if ev.get("evento") and ev["evento"].get("categoria"):
        cats.add(categoria_es(ev["evento"]["categoria"]))
    que = ", ".join(sorted(cats)).lower() or "noticia externa"
    if tipo == "NOTICIA":
        return f"Noticia importante confirmada ({que}) sobre {a.get('jugador') or 'el jugador'}."
    if tipo == "INTERESANTE":
        pend = ev.get("pendiente") or []
        return f"Noticia externa ({que}) y los dos jugadores investigados." + (" Pendiente: " + "; ".join(str(x) for x in pend) + "." if pend else "")
    if tipo in FUEGOS:
        return ("Noticia externa fuerte, UTR y cuota comparados: la cuota todavía no parece reflejar la noticia"
                + (" (lectura experimental)." if tipo == "FUEGO_EXPERIMENTAL" else "."))
    return motivo_simple(a.get("motivo_seleccion"))


def lectura_jugador(eventos: list[dict], nombre: str) -> list[str]:
    """Historial de un jugador en frases (sin códigos)."""
    out = []
    for e in sorted(eventos, key=lambda x: x.get("fecha_evento") or ""):
        est = ESTADOS.get(str(e.get("estado") or ""), str(e.get("estado") or "").lower())
        out.append(f"{str(e.get('fecha_evento') or '')[:10]}: {evento_simple(e, apellido(nombre))} ({est})")
    return out
