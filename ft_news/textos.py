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
    """Devuelve {'texto', 'voz'} con plantilla fija."""
    tipo = ev.get("tipo_alerta", "INTERESANTE")
    cab = ENCABEZADOS.get(tipo, ENCABEZADOS["INTERESANTE"])
    ux = f" (UTR {ev['utr_x']:.2f})" if ev.get("utr_x") is not None else ""
    ur = f" (UTR {ev['utr_rival']:.2f})" if ev.get("utr_rival") is not None else ""
    cuotas = ""
    if ev.get("cuota_x") is not None:
        cuotas = f" · cuota {jugador_x['nombre']} {ev['cuota_x']:.2f}"
        if ev.get("cuota_rival") is not None:
            cuotas += f" / {rival['nombre']} {ev['cuota_rival']:.2f}"
    lineas = [cab,
              f"{partido.get('torneo', '?')} · {partido.get('ronda') or ''} · {(partido.get('fecha_estimada') or '')[:16]}".strip(" ·"),
              f"**{jugador_x['nombre']}**{ux} vs **{rival['nombre']}**{ur}{cuotas}"]
    for e in eventos[:3]:
        lineas.append("Noticia: " + _ev(e))
    lineas.append(_lectura(ev))
    lineas.append("Lo que no sabemos: gravedad real y estado físico actual; esto no es una recomendación.")
    texto = "\n".join(lineas)
    voz = f"{jugador_x['nombre']} contra {rival['nombre']}. {eventos[0].get('resumen_es', '') if eventos else ''}".strip()
    if hay_prohibido(texto) or hay_prohibido(voz):
        raise ValueError("El texto contiene algo prohibido (porcentaje / probabilidad / apostar).")
    return {"texto": texto, "voz": voz}
