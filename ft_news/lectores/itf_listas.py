"""
ft_news/lectores/itf_listas.py — Acceptance lists de la ITF (WD / ALT / WC)
como eventos nivel A. DETRÁS DE LA COMPUERTA: itftennis.com no está
autorizada (D-ITF pendiente: sus T&C prohíben uso automatizado y uso para
apuestas sin licencia). `leer()` se niega sin autorización; `extraer_bajas()`
es puro y está probado con texto sintético para que, el día que Rubén
autorice (y solo PDFs públicos, 1 lectura/día por torneo), funcione.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from ft_news import fuentes, memoria
from ft_news import jugadores as jg

DOMINIO = "itftennis.com"
# Líneas típicas de una acceptance list: "WD  SMITH, John (USA)  ..." / "ALT ..." / "WC ..."
_LINEA = re.compile(r"^\s*(WD|ALT|WC|SE)\s+([A-ZÀ-Ý' \-]+),\s*([A-Za-zÀ-ÿ' \-]+)\s*\(([A-Z]{3})\)", re.MULTILINE)


def extraer_bajas(texto: str) -> list[dict]:
    """Devuelve [{'marca': 'WD'|'ALT'|'WC'|'SE', 'nombre': 'John Smith', 'pais': 'USA'}]."""
    out = []
    for m in _LINEA.finditer(texto or ""):
        marca, apellido, nombre, pais = m.groups()
        out.append({"marca": marca, "nombre": f"{nombre.strip().title()} {apellido.strip().title()}", "pais": pais})
    return out


def registrar(conn, bajas: list[dict], torneo: str, ahora: Optional[datetime] = None) -> int:
    """Solo las WD se vuelven eventos (RETIRO_ABANDONO nivel A, dato oficial)."""
    ahora = ahora or datetime.now(timezone.utc)
    n = 0
    for b in bajas:
        if b["marca"] != "WD":
            continue
        j = jg.buscar_por_nombre(conn, b["nombre"])
        if not j:
            continue
        enlace = f"itf-lista:{jg.normalizar(torneo)}"
        if conn.execute("SELECT 1 FROM news_evento WHERE jugador_id=? AND categoria='RETIRO_ABANDONO' AND enlace=?",
                        (j["id"], enlace)).fetchone():
            continue
        memoria.guardar_evento_db(conn, memoria.nuevo_evento(
            j["id"], "RETIRO_ABANDONO", "NEGATIVA", "HECHO", "A", ahora.isoformat(), fuente=DOMINIO, enlace=enlace,
            resumen_es=f"baja (WD) en la acceptance list de {torneo}", confianza_identidad=0.9))
        n += 1
    return n


def leer(conn, cfg: dict, url_pdf_o_html: str, torneo: str, descargar=None) -> dict:
    """Se niega sin autorización. `descargar(url) -> texto` lo inyecta quien llama."""
    if not fuentes.permitida(conn, DOMINIO, cfg):
        return {"ok": False, "motivo": "itftennis.com no está autorizada (D-ITF pendiente)", "bajas": 0}
    if descargar is None:
        return {"ok": False, "motivo": "sin descargador", "bajas": 0}
    texto = descargar(url_pdf_o_html)
    bajas = extraer_bajas(texto)
    return {"ok": True, "bajas": registrar(conn, bajas, torneo), "encontradas": len(bajas)}
