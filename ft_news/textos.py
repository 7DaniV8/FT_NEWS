"""
ft_news/textos.py — Plantillas FIJAS de lo que saldría a Discord (diseño
§4). Campos, no texto libre de un modelo. Prohibido: porcentajes, la
palabra "probabilidad", "apostar". hay_prohibido() lo verifica y el test
lo exige.
"""
from __future__ import annotations

import re

ENCABEZADOS = {
    "FUEGO": "🔥 FULLTENIS · POSIBLE VALOR POR NOTICIAS",
    "INTERESANTE": "🔎 FULLTENIS · PARTIDO INTERESANTE",
    "NOTICIA": "📰 FULLTENIS · NOTICIA IMPORTANTE",
}
_PROHIBIDO = re.compile(r"(%|\bprobabilidad\w*|\bapostar\b|\bapuesta\b|\bstake\b)", re.IGNORECASE)


def hay_prohibido(texto: str) -> bool:
    return bool(_PROHIBIDO.search(texto or ""))


_NIVEL = {"A": ("🟢", 1), "B": ("🟡", 2), "C": ("🔴", 3)}
_QUE_PASA = {
    "LESION_MOLESTIA": "su problema físico", "ENFERMEDAD": "su problema de salud",
    "RETIRO_ABANDONO": "su retiro reciente", "CARGA_FISICA": "su carga física reciente",
    "REGRESO": "su regreso reciente", "SANCION_DISCIPLINA": "su sanción", "VIAJE_CALENDARIO": "su calendario de viajes",
    "DECLARACION_PREPARACION": "su buena preparación", "DECLARACION_MOTIVACION": "su motivación declarada",
    "LOCALIA": "jugar de local", "SITUACION_PERSONAL": "su situación personal",
}
_ESTADO_FUENTE = {"HECHO": "Hecho confirmado.", "DECLARACION": "Declaración.",
                  "NO_VERIFICADA": "Pendiente verificar noticia.", "INTERPRETACION": "Interpretación; pendiente verificar."}


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


def _analisis(ev: dict, x: str, r: str, fem: bool, categoria: str) -> str:
    """Una frase, sin números de probabilidad: quién tiene mejor UTR, quién es
    favorita por cuota y a qué cuota podría darle valor la noticia."""
    if not ev.get("bandas_calibradas"):
        return "bandas sin calibrar; no hay lectura de mercado."
    ux, ur = ev.get("utr_x"), ev.get("utr_rival")
    cx, cr = ev.get("cuota_x"), ev.get("cuota_rival")
    fav = "favorita" if fem else "favorito"
    if ux is not None and ur is not None:
        utr = (f"{x} tiene mejor UTR" if ux > ur + 0.05 else f"{x} tiene peor UTR" if ux < ur - 0.05
               else f"{x} y {r} tienen UTR parejo")
    else:
        utr = f"{x} sin UTR comparable"
    if cx is not None and cr is not None:
        es_fav = cx < cr
        quien = f"es {fav}" if es_fav else f"no es {fav}"
    else:
        es_fav, quien = None, ""
    que = _QUE_PASA.get(categoria, "esta noticia")
    motivo = ev.get("motivo") or ""
    if ev.get("tipo_alerta") != "FUEGO":
        return ev.get("conclusion") or "contexto, sin señal de mercado."
    if motivo == "CONTRA_X":
        cuota = f" la cuota {cr:.2f} de {r}" if cr is not None else f" la cuota de {r}"
        nexo = "pero" if es_fav or (ux is not None and ur is not None and ux > ur) else "y"
        return f"{utr}{' y ' + quien if quien else ''}, {nexo} {que} podría darle valor a{cuota}."
    cuota = f" su cuota {cx:.2f}" if cx is not None else " su cuota"
    return f"{utr}{' y ' + quien if quien else ''}; {que} podría darle valor a{cuota}."


def _ev(e: dict) -> str:
    frag = (e.get("resumen_es") or e.get("fragmento_original") or e.get("categoria") or "").strip()
    nat = {"HECHO": "hecho confirmado", "DECLARACION": "declaración", "NO_VERIFICADA": "no verificada",
           "INTERPRETACION": "interpretación"}.get(e.get("naturaleza"), "")
    fecha = (e.get("fecha_evento") or "")[:10]
    fuente = e.get("fuente") or ""
    enlace = e.get("enlace") or ""
    partes = [f"*\"{frag}\"*", nat, fecha, fuente, enlace, f"Nivel {e.get('nivel', '?')}"]
    return " — ".join(p for p in partes if p)


def _lectura(ev: dict) -> str:
    """Sin bandas calibradas no se dice nada del mercado."""
    if not ev.get("bandas_calibradas"):
        return "Lectura: bandas sin calibrar; no hay lectura de mercado."
    if ev.get("tipo_alerta") == "FUEGO":
        return "Lectura: " + ev.get("conclusion", "")
    return "Lectura: " + (ev.get("conclusion") or "contexto, sin señal de mercado.")


def armar(ev: dict, partido: dict, jugador_x: dict, rival: dict, eventos: list[dict]) -> dict:
    """Devuelve {'texto', 'voz'} con plantilla fija (formato 08/10/2026 noche, Rubén):

        🔥 FULLTENIS · POSIBLE VALOR POR NOTICIAS

        🎾 Pace (UTR 9.12) vs Fakih (UTR 9.84)
        🏆 W15 Monastir · 10/10 · 14:30

        💰 Cuotas: Pace 2.40 | Fakih 1.55

        🚨 NOTICIA (06/10): Fakih se retiró en Antalya por molestias en el hombro derecho.

        📊 ANÁLISIS: Fakih tiene mejor UTR y es favorita, pero su problema físico podría darle valor a la cuota 2.40 de Pace.

        🟡 Nivel 2 · Posible valor en Pace
        📰 Fuente: TennisTourTalk · Pendiente verificar noticia.

    El lado con posible valor es el de la noticia si es a favor de X (A_FAVOR_X)
    o la rival si es en contra (CONTRA_X). Nivel A/B/C → 1/2/3. El pie
    ("investigación de noticias; no es una recomendación") lo pone FT Discord."""
    tipo = ev.get("tipo_alerta", "INTERESANTE")
    cab = ENCABEZADOS.get(tipo, ENCABEZADOS["INTERESANTE"])
    x, r = apellido(jugador_x["nombre"]), apellido(rival["nombre"])
    if x == r:
        x, r = jugador_x["nombre"], rival["nombre"]
    fem = str(partido.get("genero") or "").upper()[:1] in ("F", "W")
    ux = f" (UTR {ev['utr_x']:.2f})" if ev.get("utr_x") is not None else ""
    ur = f" (UTR {ev['utr_rival']:.2f})" if ev.get("utr_rival") is not None else ""
    # El lado con posible valor va primero en la línea del partido.
    contra = tipo == "FUEGO" and (ev.get("motivo") or "") == "CONTRA_X"
    valor_en = r if contra else x
    if contra:
        linea_vs = f"🎾 {r}{ur} vs {x}{ux}"
    else:
        linea_vs = f"🎾 {x}{ux} vs {r}{ur}"
    f_est = partido.get("fecha_estimada") or ""
    cuando = " · ".join(p for p in (_fecha_corta(f_est), _hora_corta(f_est)) if p)
    torneo = " · ".join(p for p in (partido.get("torneo") or "", partido.get("ronda") or "", cuando) if p)
    lineas = [cab, "", linea_vs]
    if torneo:
        lineas.append(f"🏆 {torneo}")
    if ev.get("cuota_x") is not None and ev.get("cuota_rival") is not None:
        cx, cr = ev["cuota_x"], ev["cuota_rival"]
        lineas += ["", f"💰 Cuotas: {r} {cr:.2f} | {x} {cx:.2f}" if contra else f"💰 Cuotas: {x} {cx:.2f} | {r} {cr:.2f}"]
    lineas.append("")
    for i, e in enumerate(eventos[:3]):
        frag = (e.get("resumen_es") or e.get("fragmento_original") or e.get("categoria") or "").strip().rstrip(".")
        fecha = _fecha_corta(e.get("fecha_evento"))
        lineas.append(f"{'🚨 NOTICIA' if i == 0 else '➕ TAMBIÉN'}{f' ({fecha})' if fecha else ''}: {frag}.")
    cat = (eventos[0].get("categoria") if eventos else None) or ""
    lineas += ["", f"📊 ANÁLISIS: {_analisis(ev, x, r, fem, cat)}", ""]
    nivel = (eventos[0].get("nivel") if eventos else None) or "C"
    ico, num = _NIVEL.get(str(nivel).upper()[:1], ("⚪", "?"))
    if tipo == "FUEGO":
        lineas.append(f"{ico} Nivel {num} · Posible valor en {valor_en}")
    elif tipo == "NOTICIA":
        lineas.append(f"{ico} Nivel {num} · Noticia importante sobre {x}")
    else:
        lineas.append(f"{ico} Nivel {num} · Contexto, sin señal de mercado")
    if eventos:
        e0 = eventos[0]
        estado = _ESTADO_FUENTE.get(e0.get("naturaleza"), "Pendiente verificar noticia.")
        if e0.get("naturaleza") == "HECHO" and str(nivel).upper()[:1] != "A":
            estado = "Hecho reportado; pendiente confirmar con otra fuente."
        lineas.append(f"📰 Fuente: {_fuente_corta(e0.get('fuente'))} · {estado}")
    texto = "\n".join(lineas)
    voz = f"{x} contra {r}. {eventos[0].get('resumen_es', '') if eventos else ''}".strip()
    if hay_prohibido(texto) or hay_prohibido(voz):
        raise ValueError("El texto contiene algo prohibido (porcentaje / probabilidad / apostar).")
    return {"texto": texto, "voz": voz}
