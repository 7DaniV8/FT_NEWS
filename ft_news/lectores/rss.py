"""
ft_news/lectores/rss.py — RSS de la prensa AUTORIZADA (segunda entrega).

Gratis y complementario a Tavily: cada hora se leen los feeds de las fuentes
con autorizada=1 que tengan feed conocido, se descartan las URLs ya vistas y
cada artículo nuevo se cruza con los jugadores de la cola (el nombre completo
tiene que aparecer en título o resumen). Solo los que coinciden pasan a
Gemini (radar.procesar_articulo), así que el costo es solo la clasificación.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx

from ft_news import costos, fuentes, radar
from ft_news import jugadores as jg
from ft_news.proveedores.tavily import dominio_de

FEEDS = {
    "tennistourtalk.com": "https://tennistourtalk.com/feed/",
    "puntodebreak.com": "https://www.puntodebreak.com/rss.xml",
    "livetennis.it": "https://www.livetennis.it/feed/",
    "ubitennis.com": "https://www.ubitennis.com/feed/",
    "atptour.com": "https://www.atptour.com/en/media/rss-feed/xml-feed",
    "feeds.feedburner.com/tennis-australia": "https://feeds.feedburner.com/tennis-australia",
    "ustaflorida.com": "https://www.ustaflorida.com/feed/",
}
_IDIOMA = {"tennistourtalk.com": "en", "puntodebreak.com": "es", "livetennis.it": "it", "ubitennis.com": "it",
           "atptour.com": "en"}


def _fecha(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
        except Exception:
            return None


def parsear(xml: str, dominio: str) -> list[dict]:
    """RSS 2.0 o Atom → artículos."""
    out = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//a:entry", ns)
    for it in items:
        def g(tag, attr=None):
            el = it.find(tag) if not tag.startswith("a:") else it.find(tag, ns)
            if el is None:
                return None
            return el.get(attr) if attr else (el.text or "").strip()
        url = g("link") or g("a:link", "href") or ""
        if not url:
            continue
        titulo = g("title") or g("a:title") or ""
        desc = g("description") or g("a:summary") or g("a:content") or ""
        desc = re.sub(r"<[^>]+>", " ", desc)
        out.append({"url": url, "dominio": dominio_de(url) or dominio, "titulo": titulo,
                    "contenido": re.sub(r"\s+", " ", desc).strip()[:4000],
                    "fecha_publicacion": _fecha(g("pubDate") or g("a:published") or g("a:updated")),
                    "idioma": _IDIOMA.get(dominio)})
    return out


def _coincide(nombre: str, texto: str) -> bool:
    t = jg.normalizar(texto)
    toks = jg.normalizar(nombre).split()
    return len(toks) >= 2 and all(tok in t.split() for tok in toks)


def correr(conn, cfg: dict, gemini, ahora: Optional[datetime] = None, transport=None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    res = {"feeds": 0, "articulos": 0, "nuevos": 0, "coincidencias": 0, "eventos": 0, "errores": []}
    if gemini is None:
        res["errores"].append("sin GEMINI_API_KEY")
        return res
    jugadores = [dict(r) for r in conn.execute(
        "SELECT j.* FROM news_jugador j JOIN news_jugador_cola c ON c.jugador_id=j.id").fetchall()]
    cli = httpx.Client(timeout=20, transport=transport, headers={"User-Agent": "FT-News/1 (FullTenis)"})
    for dominio, url in FEEDS.items():
        if not fuentes.permitida(conn, dominio, cfg):
            continue
        res["feeds"] += 1
        try:
            r = cli.get(url, follow_redirects=True)
            r.raise_for_status()
            arts = parsear(r.text, dominio)
        except Exception as e:
            res["errores"].append(f"{dominio}: {e}")
            continue
        res["articulos"] += len(arts)
        for art in arts:
            aid = radar._articulo_nuevo(conn, art)
            if aid is None:
                continue
            res["nuevos"] += 1
            texto = f"{art['titulo']} {art['contenido']}"
            for j in jugadores:
                if not _coincide(j["nombre"], texto):
                    continue
                res["coincidencias"] += 1
                if not costos.puede_gastar(conn, cfg)["ok"]:
                    return res
                jug = {"jugador_id": j["id"], "nombre": j["nombre"], "pais": j["pais"], "genero": j["genero"],
                       "circuito": j["circuito"]}
                try:
                    out = radar.procesar_articulo(conn, cfg, gemini, jug, art, aid, ahora)
                except Exception as e:
                    res["errores"].append(f"gemini: {e}")
                    break
                if out["resultado"] == "EVENTO":
                    res["eventos"] += 1
    return res
