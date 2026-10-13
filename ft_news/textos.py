"""
ft_news/textos.py — Plantillas FIJAS de lo que sale a Discord. Campos, no
texto libre de un modelo. Prohibido: porcentajes, la palabra "probabilidad",
"apostar". hay_prohibido() lo verifica y el test lo exige.

v6 (09/10/2026 23:13, Rubén — "formatos definitivos"): mensajes cortos, sin
enlaces (las fuentes y la evidencia quedan en news_alerta.evidencia_json y en
la pestaña), con el JUGADOR FAVORECIDO en MAYÚSCULAS y su cuota al lado. Si no
hay evidencia para nombrar un favorecido, no se inventa. Mismos formatos para
ATP/WTA, Challenger, ITF y UTR. Las reglas de selección no cambian: esto es
solo presentación.

    📰 FULLTENNIS · NOTICIA IMPORTANTE
    🎾 Mateo Quiroga
    🏆 Challenger Lima
    📊 UTR: 12.85
    🚨 LESIÓN: Molestias en el tobillo derecho.
    🔴 PERJUDICA A: MATEO QUIROGA
    🟢 PODRÍA FAVORECER A: LUCA BERTOLINI
    💰 Quiroga 1.42 | Bertolini 2.85

    🔎 FULLTENNIS · PARTIDO INTERESANTE
    🎾 Valentina Soler vs Hanna Kowal
    🏆 W75 Reus
    📊 UTR: 10.62 vs 10.20
    💰 Cuotas: 1.65 vs 2.20
    🚨 NOTICIA: Soler presenta molestias en el hombro.
    🟢 PODRÍA FAVORECER A: HANNA KOWAL @2.20
    ⏳ Pendiente de confirmar la reacción del mercado.

    🔥 FULLTENNIS · POSIBLE VALOR EXPERIMENTAL
    🎾 Luca Bertolini vs Mateo Quiroga
    🏆 Challenger Lima
    📊 UTR: 12.41 vs 12.85
    🟢 JUGADOR FAVORECIDO: LUCA BERTOLINI
    💰 CUOTA: 2.85
    🚨 MOTIVO: Quiroga llega con molestias en el tobillo derecho.
    📈 La cuota de Quiroga sigue en 1.42 después de la noticia.
    ⚠️ Posible oportunidad sin validar estadísticamente.
"""
from __future__ import annotations

import re
from typing import Optional

ENCABEZADOS = {
    "FUEGO": "🔥 FULLTENNIS · POSIBLE VALOR POR NOTICIAS",
    "FUEGO_EXPERIMENTAL": "🔥 FULLTENNIS · POSIBLE VALOR EXPERIMENTAL",
    "INTERESANTE": "🔎 FULLTENNIS · PARTIDO INTERESANTE",
    "NOTICIA": "📰 FULLTENNIS · NOTICIA IMPORTANTE",
}
FUEGOS = ("FUEGO", "FUEGO_EXPERIMENTAL")
_PROHIBIDO = re.compile(r"(%|\bprobabilidad\w*|\bapostar\b|\bapuesta\b|\bstake\b|https?://)", re.IGNORECASE)

_CAT = {"LESION_MOLESTIA": "LESIÓN", "ENFERMEDAD": "ENFERMEDAD", "RETIRO_ABANDONO": "RETIRO", "REGRESO": "REGRESO",
        "SANCION_DISCIPLINA": "SANCIÓN", "DECLARACION_PREPARACION": "DECLARACIÓN", "DECLARACION_MOTIVACION": "DECLARACIÓN",
        "VIAJE_CALENDARIO": "VIAJE", "SITUACION_PERSONAL": "SITUACIÓN PERSONAL", "CAMBIO_EQUIPO": "CAMBIO DE EQUIPO",
        "CARGA_FISICA": "CARGA FÍSICA", "ANTECEDENTE_TORNEO": "ANTECEDENTE", "LOCALIA": "LOCALÍA",
        "PUNTOS_DEFENDIDOS": "PUNTOS DEFENDIDOS", "RESULTADO_RECIENTE": "RESULTADO RECIENTE", "SUPERFICIE": "SUPERFICIE",
        "RANKING_OBJETIVO": "RANKING"}
_ESTADO = {"CUOTA_SIN_ACTUALIZAR": "⏳ Pendiente de confirmar la reacción del mercado.",
           "RIVAL_SIN_INVESTIGACION_RECIENTE": "⏳ Pendiente de investigar al rival.",
           "RIVAL_SIN_INVESTIGAR": "⏳ Pendiente de investigar al rival.",
           "RETIRO_MISMO_TORNEO": "⚠️ El partido podría no jugarse (retiro en el mismo torneo).",
           "SIN_INFORMACION_NO_REFLEJADA": "📉 El mercado parece haber incorporado la noticia.",
           "JUSTIFICACION_INSUFICIENTE": "⚠️ Sin evidencia suficiente de valor en la cuota.",
           "BANDAS_NO_CALIBRADAS": "⚠️ Sin lectura de mercado validada.",
           "SIN_NOTICIA_EXTERNA_FUERTE": "⚠️ Solo contexto calculado, sin noticia externa fuerte.",
           "DIRECCION_CONTRADICTORIA": "⚪ Noticias en los dos: sin favorecido claro.",
           "ESTADO_FISICO_SIN_VERIFICAR": "⏳ Regreso sin verificar con un partido completo.",
           "ESTADO_FISICO_SIN_VERIFICAR_RIVAL": "⏳ Regreso del rival sin verificar con un partido completo.",
           "MERCADO_EN_MOVIMIENTO": "📉 La cuota ya se está moviendo.",
           "MERCADO_YA_DESCONTO": "📉 El mercado ya descontó la noticia.",
           "SIN_MERCADO": "⏳ Sin cuota del mercado todavía."}


def hay_prohibido(texto: str) -> bool:
    return bool(_PROHIBIDO.search(texto or ""))


def apellido(nombre: str) -> str:
    """'Kate Fakih' → 'Fakih'; 'Perez J.' → 'Perez'; nombres cortos quedan igual."""
    partes = [p for p in (nombre or "").replace(",", " ").split() if len(p.strip(".")) >= 2]
    if not partes:
        return nombre or "?"
    largas = [p for p in partes if len(p.strip(".")) >= 3]
    return (largas[-1] if largas else partes[-1]).strip(".")


def _fecha_corta(iso: str) -> str:
    s = str(iso or "")
    return f"{s[8:10]}/{s[5:7]}" if len(s) >= 10 else ""


def _hora_corta(iso: str) -> str:
    s = str(iso or "")
    return s[11:16] if len(s) >= 16 else ""


def _fuente_corta(f: str) -> str:
    f = (f or "").strip().lower()
    for pre in ("https://", "http://", "www."):
        if f.startswith(pre):
            f = f[len(pre):]
    f = f.split("/")[0]
    base = f.rsplit(".", 1)[0] if "." in f else f
    return {"tennistourtalk": "TennisTourTalk", "puntodebreak": "Punto de Break", "livetennis": "LiveTennis",
            "ubitennis": "Ubitennis", "tennisactu": "Tennis Actu", "atptour": "ATP Tour", "wtatennis": "WTA",
            "itftennis": "ITF"}.get(base, base.capitalize() if base else "fuente")


def _frase(e: dict, maximo: int = 120, corta: bool = True) -> str:
    """La noticia en una frase corta, con mayúscula inicial y punto final. Si el
    clasificador dio `titular` (≤ 60 caracteres, el hecho sin el nombre), ese."""
    t = ((e.get("titular") if corta else "") or e.get("resumen_es") or e.get("fragmento_original")
         or _CAT.get(e.get("categoria"), "") or "").strip()
    t = re.sub(r"\s+", " ", t)
    primera = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0] if t else ""
    t = primera or t
    if len(t) > maximo:
        t = t[:maximo].rsplit(" ", 1)[0].rstrip(",;:…")
    t = t.rstrip(".")
    return (t[:1].upper() + t[1:] + ".") if t else ""


def _utr(v) -> str:
    return f"{float(v):.2f}" if v is not None else "s/d"


def _cuota(v) -> str:
    return f"{float(v):.2f}" if v is not None else "s/d"


def _mayus(nombre: str) -> str:
    return (nombre or "?").upper()


def _torneo(partido: Optional[dict]) -> str:
    return (partido or {}).get("torneo") or ""


def _tokens(t: str) -> set:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return {w for w in re.split(r"[^a-z0-9]+", t) if len(w) >= 4 and w not in ("challenger", "open", "cup", "tennis", "tenis", "torneo")}


def _retiro_del_torneo(evento: dict, torneo: str) -> bool:
    return evento.get("categoria") == "RETIRO_ABANDONO" and bool(_tokens(torneo) & _tokens(
        f"{evento.get('titular') or ''} {evento.get('resumen_es') or ''}"))


def fiabilidad(e: dict) -> str:
    """v7.3 (13/10/2026, Rubén: "las noticias no verificadas no se presenten como hechos
    confirmados"): una línea que dice de dónde viene la noticia y si está confirmada.
    Solo presentación: no cambia qué sale ni qué no."""
    if not e:
        return ""
    fuente = str(e.get("fuente") or "")
    if fuente == "rankingftr.interno" or str(e.get("enlace") or "").startswith("contexto:") or e.get("origen") == "INTERNO":
        return "📊 Dato calculado por FullTennis (no es una noticia de prensa)."
    f = _fuente_corta(fuente)
    nat, nivel = e.get("naturaleza"), str(e.get("nivel") or "C")
    if nat == "HECHO" and nivel == "A":
        return f"✅ Confirmado por fuente oficial ({f})."
    if nat == "HECHO":
        return f"📰 Informado por {f}; sin confirmación oficial."
    if nat == "DECLARACION":
        return f"🗣️ Según declaraciones recogidas por {f}; sin confirmación oficial."
    return f"❔ Sin confirmar ({f})."


def _verificar(texto: str, voz: str) -> dict:
    if hay_prohibido(texto) or hay_prohibido(voz):
        raise ValueError("El texto contiene algo prohibido (porcentaje / probabilidad / apostar / enlace).")
    return {"texto": texto, "voz": voz}


# ═════════════════════════════════════════════════════════════════════
#  📰 NOTICIA IMPORTANTE
# ═════════════════════════════════════════════════════════════════════

def armar_noticia(evento: dict, jugador: dict, prox: Optional[dict], motivo_seleccion: str = "") -> dict:
    """`prox` = próximo partido del jugador (rival, cuota_jugador, cuota_rival, torneo) o None.
    Con noticia NEGATIVA y partido: 🔴 PERJUDICA A: X · 🟢 PODRÍA FAVORECER A: RIVAL · 💰 cuotas.
    POSITIVA: 🟢 FAVORECE A: X. Mixta/neutra: ⚪ AFECTA A: X (sin inventar favorecido)."""
    nombre = jugador.get("nombre") or "?"
    ap = apellido(nombre)
    cat = _CAT.get(evento.get("categoria"), str(evento.get("categoria") or "NOTICIA"))
    direccion = evento.get("direccion")
    rival = (prox or {}).get("rival")
    torneo = _torneo(prox) or jugador.get("ultimo_torneo") or ""
    lineas = [ENCABEZADOS["NOTICIA"], f"🎾 {nombre}", f"🏆 {torneo or 'Sin partido programado'}",
              f"📊 UTR: {_utr(jugador.get('utr_singles'))}", f"🚨 {cat}: {_frase(evento)}", fiabilidad(evento)]
    voz_fav = ""
    wo = bool(prox) and _retiro_del_torneo(evento, _torneo(prox))
    if direccion == "NEGATIVA":
        lineas.append(f"🔴 PERJUDICA A: {_mayus(nombre)}")
        if wo:
            lineas.append("⚠️ El partido podría no jugarse (retiro en el mismo torneo).")
        elif rival:
            lineas.append(f"🟢 PODRÍA FAVORECER A: {_mayus(rival)}")
            voz_fav = f" Podría favorecer a {apellido(rival)}"
            if prox.get("cuota_rival"):
                voz_fav += f", cuota {_cuota(prox['cuota_rival'])}"
            voz_fav += "."
    elif direccion == "POSITIVA":
        lineas.append(f"🟢 FAVORECE A: {_mayus(nombre)}")
        voz_fav = f" Favorece a {ap}."
    else:
        lineas.append(f"⚪ AFECTA A: {_mayus(nombre)}")
    if prox and prox.get("cuota_jugador") and prox.get("cuota_rival"):
        lineas.append(f"💰 {ap} {_cuota(prox['cuota_jugador'])} | {apellido(rival)} {_cuota(prox['cuota_rival'])}")
    texto = "\n".join(lineas)
    voz = f"Noticia importante. {ap}: {_frase(evento, 90)}{voz_fav}".strip()
    return _verificar(texto, voz)


# ═════════════════════════════════════════════════════════════════════
#  🔎 PARTIDO INTERESANTE
# ═════════════════════════════════════════════════════════════════════

def _favorecido_interesante(jx: dict, jr: dict, ev: dict, fx: list[dict], fr: list[dict]):
    """(nombre, cuota) del que podría salir favorecido, o (None, None) si no hay evidencia clara."""
    neg_x = any(e.get("direccion") == "NEGATIVA" for e in fx)
    pos_x = any(e.get("direccion") == "POSITIVA" for e in fx)
    neg_r = any(e.get("direccion") == "NEGATIVA" for e in fr)
    pos_r = any(e.get("direccion") == "POSITIVA" for e in fr)
    a_r = (neg_x and not neg_r) or (pos_r and not pos_x and not neg_r)
    a_x = (neg_r and not neg_x) or (pos_x and not pos_r and not neg_x)
    if a_r and not a_x:
        return jr["nombre"], ev.get("cuota_rival")
    if a_x and not a_r:
        return jx["nombre"], ev.get("cuota_x")
    return None, None


def armar_interesante(ev: dict, partido: dict, jx: dict, jr: dict, fx: list[dict], fr: list[dict],
                      contexto_rival: list[dict] = None, pendiente: list[str] = None, motivo_seleccion: str = "") -> dict:
    x, r = jx["nombre"], jr["nombre"]
    lineas = [ENCABEZADOS["INTERESANTE"], f"🎾 {x} vs {r}", f"🏆 {_torneo(partido) or 'Torneo s/d'}",
              f"📊 UTR: {_utr(ev.get('utr_x'))} vs {_utr(ev.get('utr_rival'))}",
              f"💰 Cuotas: {_cuota(ev.get('cuota_x'))} vs {_cuota(ev.get('cuota_rival'))}"]
    primero = (fx or fr or [{}])[0]
    quien = apellido(x) if fx else apellido(r)
    frase = _frase(primero) if primero else "Contexto relevante."
    lineas.append(f"🚨 NOTICIA: {frase}")
    if primero:
        lineas.append(fiabilidad(primero))
    fav, cuota = _favorecido_interesante(jx, jr, ev, fx, fr)
    if str(ev.get("motivo") or "") in ("RETIRO_MISMO_TORNEO", "DIRECCION_CONTRADICTORIA"):
        fav, cuota = None, None                      # el partido puede no jugarse / noticias en los dos: no se inventa
    voz_fav = ""
    if fav:
        lineas.append(f"🟢 PODRÍA FAVORECER A: {_mayus(fav)}" + (f" @{_cuota(cuota)}" if cuota else ""))
        voz_fav = f" Podría favorecer a {apellido(fav)}" + (f", cuota {_cuota(cuota)}." if cuota else ".")
    elif fx and fr:
        lineas.append("⚪ Noticias en los dos: sin favorecido claro.")
    estado = _ESTADO.get(str(ev.get("motivo") or ""), "⏳ Pendiente de confirmar la reacción del mercado.")
    lineas.append(estado)
    texto = "\n".join(lineas)
    voz = f"Partido interesante. {apellido(x)} contra {apellido(r)}. {quien}: {_frase(primero, 90) if primero else ''}{voz_fav}".strip()
    return _verificar(texto, voz)


# ═════════════════════════════════════════════════════════════════════
#  🔥 POSIBLE VALOR (validado / EXPERIMENTAL) — y 🔎 para la evaluación
# ═════════════════════════════════════════════════════════════════════

def armar(ev: dict, partido: dict, jugador_x: dict, rival: dict, eventos: list[dict]) -> dict:
    """Texto de la evaluación de un partido. Para 🔥 (validada o experimental) es
    el mensaje definitivo; para una evaluación 🔎 arma el formato de PARTIDO
    INTERESANTE con lo que tiene (la alerta 🔎 que viaja la arma alertas.py con
    armar_interesante y la investigación de los dos)."""
    tipo = ev.get("tipo_alerta", "INTERESANTE")
    x, r = jugador_x["nombre"], rival["nombre"]
    if tipo not in FUEGOS:
        fx = [e for e in eventos if e.get("jugador_id") in (None, jugador_x.get("id"))]
        fr = [e for e in eventos if rival.get("id") is not None and e.get("jugador_id") == rival.get("id")]
        return armar_interesante(ev, partido, jugador_x, rival, fx or eventos[:1], fr)
    contra = (ev.get("motivo") or "") == "CONTRA_X"
    fav, cuota_fav = (r, ev.get("cuota_rival")) if contra else (x, ev.get("cuota_x"))
    ax, ar = apellido(x), apellido(r)
    if ax == ar:                                      # apellidos iguales (o nombres cortos): nombre completo
        ax, ar = x, r
    afectado = ax
    primero = eventos[0] if eventos else {}
    lineas = [ENCABEZADOS[tipo],
              f"🎾 {fav} vs {x if contra else r}",
              f"🏆 {_torneo(partido) or 'Torneo s/d'}",
              f"📊 UTR: {_utr(ev.get('utr_rival') if contra else ev.get('utr_x'))} vs {_utr(ev.get('utr_x') if contra else ev.get('utr_rival'))}",
              f"🟢 JUGADOR FAVORECIDO: {_mayus(fav)}",
              f"💰 CUOTA: {_cuota(cuota_fav)}",
              f"🚨 MOTIVO: {_frase(primero) if primero else 'Noticia externa.'}"]
    if primero:
        lineas.append(fiabilidad(primero))
    j = ev.get("justificacion") or {}
    ca, cd = j.get("cuota_x_antes"), j.get("cuota_x_despues")
    if cd is not None and ca is not None:
        if abs(float(cd) - float(ca)) < 0.005:
            lineas.append(f"📈 La cuota de {afectado} sigue en {_cuota(cd)} después de la noticia.")
        else:
            lineas.append(f"📈 La cuota de {afectado} pasó de {_cuota(ca)} a {_cuota(cd)} después de la noticia.")
    elif cd is not None:
        lineas.append(f"📈 Cuota de {afectado} confirmada en {_cuota(cd)} después de la noticia.")
    if tipo == "FUEGO_EXPERIMENTAL":
        lineas.append("⚠️ Posible oportunidad sin validar estadísticamente.")
    else:
        lineas.append("✅ Lectura UTR/cuota validada con datos propios.")
    texto = "\n".join(lineas)
    pref = "Posible valor experimental, sin validar. " if tipo == "FUEGO_EXPERIMENTAL" else "Posible valor por noticias. "
    voz = (f"{pref}{ar if contra else ax}, cuota {_cuota(cuota_fav)}, contra {ax if contra else ar}. "
           f"{_frase(primero, 90) if primero else ''}").strip()
    return _verificar(texto, voz)
