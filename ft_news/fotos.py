"""
ft_news/fotos.py — 📷 FOTOS CON LICENCIA para la portada (v7.6, 13/10/2026).

Rubén (12/10): «fotos de Wikimedia Commons con crédito y licencia, o tarjetas propias de FullTennis, sin contratar
agencias por ahora». (13/10): «¿podemos usar imágenes de la web, dando créditos al autor?» → solo las que tienen una
licencia que permite reutilizarlas (dar crédito no alcanza para una foto cualquiera): Wikimedia Commons con CC0,
dominio público, CC BY o CC BY-SA, y SIEMPRE con autor, licencia y enlace.

CÓMO SE ELIGE LA FOTO (para no poner la cara de otra persona):
  1. Wikidata: se busca el nombre del jugador y solo vale una ficha que sea **tenista** (P106 = Q10833314) y cuyo
     nombre coincida con el nuestro. Si hay más de una que cumple, es ambiguo → sin foto.
  2. Su imagen oficial de la ficha (P18) en Wikimedia Commons, y de ahí la licencia, el autor y el enlace.
  3. Licencia fuera de la lista, sin autor o sin imagen → sin foto (la portada usa la tarjeta propia de FullTennis).

Todo queda en `news_foto` (también el «no hay»), así cada jugador se busca una vez cada 30 días. Corre en el ciclo,
pocas búsquedas por vuelta; la portada solo lee la tabla. Interruptor: NEWS_FOTOS_ACTIVO.
"""
from __future__ import annotations

import html
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from ft_news.db import ejecutar_con_reintento

log = logging.getLogger("ft_news")

WIKIDATA = "https://www.wikidata.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
TENISTA = "Q10833314"
UA = "FullTennis-FTNEWS/7.6 (fotos con licencia de Wikimedia Commons; portada de noticias de tenis)"
LICENCIAS_OK = re.compile(r"^(cc0|cc[ -]?0|public domain|pd|cc by( |-)?(\d|sa))", re.IGNORECASE)
REBUSCAR_DIAS = 30
REINTENTO_ERROR_H = 24
POR_VUELTA = 15          # v7.7: también la agenda (≈ 60 por hora con el ciclo de 15 min)

_TABLA = """
CREATE TABLE IF NOT EXISTS news_foto (
    jugador_id   INTEGER PRIMARY KEY,
    estado       TEXT NOT NULL,            -- OK | SIN_FOTO | AMBIGUO | ERROR
    qid          TEXT,
    archivo      TEXT,
    url          TEXT,                     -- miniatura (upload.wikimedia.org)
    pagina       TEXT,                     -- página del archivo en Commons (crédito)
    autor        TEXT,
    licencia     TEXT,
    licencia_url TEXT,
    detalle      TEXT,
    buscado_en   TEXT NOT NULL);
"""


def ensure(conn) -> None:
    conn.executescript(_TABLA)


def _norm(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def mismo_nombre(nuestro: str, etiqueta: str) -> bool:
    """Todas las palabras de nuestro nombre están en la ficha (y la ficha no tiene un apellido de más)."""
    a, b = _norm(nuestro), _norm(etiqueta)
    return bool(a) and set(a) <= set(b) and len(set(b) - set(a)) <= 1


def _texto(v) -> str:
    """Autor de Commons viene en HTML: texto plano, corto."""
    t = re.sub(r"<[^>]+>", " ", str(v or ""))
    return re.sub(r"\s+", " ", html.unescape(t)).strip()[:120]


def licencia_valida(lic: str) -> bool:
    l = (lic or "").strip()
    return bool(LICENCIAS_OK.search(l)) and not re.search(r"\b(nc|nd)\b", l, re.IGNORECASE)


class Wikimedia:
    def __init__(self, transport=None, timeout: float = 12):
        self._cli = httpx.Client(timeout=timeout, transport=transport, headers={"User-Agent": UA})

    def _get(self, url: str, params: dict) -> dict:
        r = self._cli.get(url, params={**params, "format": "json"})
        r.raise_for_status()
        return r.json()

    def ficha_tenista(self, nombre: str) -> tuple[Optional[dict], str]:
        """(ficha con qid y archivo de imagen, motivo). Solo una ficha de TENISTA con el mismo nombre."""
        s = self._get(WIKIDATA, {"action": "wbsearchentities", "search": nombre, "language": "en", "type": "item", "limit": 7})
        ids = [x["id"] for x in s.get("search") or [] if x.get("id")]
        if not ids:
            return None, "SIN_FICHA"
        e = self._get(WIKIDATA, {"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels|aliases"})
        buenas = []
        for qid, ent in (e.get("entities") or {}).items():
            claims = ent.get("claims") or {}
            ocup = {((c.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id") for c in claims.get("P106") or []}
            if TENISTA not in ocup:
                continue
            nombres = [v.get("value") for v in (ent.get("labels") or {}).values()]
            nombres += [a.get("value") for lst in (ent.get("aliases") or {}).values() for a in lst]
            if not any(mismo_nombre(nombre, n) for n in nombres if n):
                continue
            img = [((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") for c in claims.get("P18") or []]
            buenas.append({"qid": qid, "archivo": next((i for i in img if i), None)})
        if not buenas:
            return None, "SIN_FICHA"
        if len(buenas) > 1:
            return None, "AMBIGUO"
        return buenas[0], "OK"

    def licencia(self, archivo: str) -> dict:
        d = self._get(COMMONS, {"action": "query", "titles": f"File:{archivo}", "prop": "imageinfo",
                                "iiprop": "url|extmetadata", "iiurlwidth": 640})
        pag = next(iter((d.get("query") or {}).get("pages", {}).values()), {})
        ii = (pag.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata") or {}
        val = lambda k: (md.get(k) or {}).get("value")
        return {"url": ii.get("thumburl") or ii.get("url"), "pagina": ii.get("descriptionurl"),
                "autor": _texto(val("Artist") or val("Credit")), "licencia": _texto(val("LicenseShortName")),
                "licencia_url": val("LicenseUrl")}


def buscar(cli: Wikimedia, nombre: str) -> dict:
    """{'estado': OK | SIN_FOTO | AMBIGUO, ...}. Nunca devuelve una foto sin licencia válida y sin autor."""
    ficha, motivo = cli.ficha_tenista(nombre)
    if not ficha:
        return {"estado": "AMBIGUO" if motivo == "AMBIGUO" else "SIN_FOTO", "detalle": motivo}
    if not ficha.get("archivo"):
        return {"estado": "SIN_FOTO", "qid": ficha["qid"], "detalle": "la ficha no tiene imagen"}
    lic = cli.licencia(ficha["archivo"])
    if not lic.get("url") or not lic.get("pagina"):
        return {"estado": "SIN_FOTO", "qid": ficha["qid"], "archivo": ficha["archivo"], "detalle": "Commons no devolvió la imagen"}
    if not licencia_valida(lic.get("licencia")):
        return {"estado": "SIN_FOTO", "qid": ficha["qid"], "archivo": ficha["archivo"],
                "detalle": f"licencia no admitida: {lic.get('licencia') or 'sin licencia'}"}
    if not lic.get("autor"):
        return {"estado": "SIN_FOTO", "qid": ficha["qid"], "archivo": ficha["archivo"], "detalle": "sin autor para dar crédito"}
    return {"estado": "OK", "qid": ficha["qid"], "archivo": ficha["archivo"], **lic}


def guardar(conn, jugador_id: int, r: dict, ahora: datetime) -> None:
    def _w():
        conn.execute("INSERT OR REPLACE INTO news_foto (jugador_id, estado, qid, archivo, url, pagina, autor, licencia, licencia_url, "
                     "detalle, buscado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (jugador_id, r["estado"], r.get("qid"), r.get("archivo"), r.get("url"), r.get("pagina"), r.get("autor"),
                      r.get("licencia"), r.get("licencia_url"), (r.get("detalle") or "")[:200], ahora.isoformat()))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def de_jugadores(conn, ids) -> dict:
    """{jugador_id: foto} solo con las fotos OK (lo que usa la portada)."""
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r[0]: {"tipo": "foto", "url": r[1], "pagina": r[2], "autor": r[3], "licencia": r[4], "licencia_url": r[5],
                   "credito": f"Foto: {r[3]} · {r[4]} · Wikimedia Commons"}
            for r in conn.execute(f"SELECT jugador_id, url, pagina, autor, licencia, licencia_url FROM news_foto "
                                  f"WHERE estado='OK' AND jugador_id IN ({q})", ids).fetchall()}


def pendientes(conn, ids, ahora: datetime) -> list[int]:
    """Jugadores sin búsqueda reciente (OK/SIN_FOTO/AMBIGUO: 30 días; ERROR: 24 h)."""
    ensure(conn)
    ids = [int(i) for i in dict.fromkeys(ids) if i]
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    vistos = {r[0]: (r[1], r[2]) for r in conn.execute(f"SELECT jugador_id, estado, buscado_en FROM news_foto WHERE jugador_id IN ({q})", ids)}
    out = []
    for i in ids:
        if i not in vistos:
            out.append(i)
            continue
        estado, en = vistos[i]
        try:
            t = datetime.fromisoformat(str(en))
        except ValueError:
            out.append(i)
            continue
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        if ahora - t > (timedelta(hours=REINTENTO_ERROR_H) if estado == "ERROR" else timedelta(days=REBUSCAR_DIAS)):
            out.append(i)
    return out


def completar(conn, cfg: dict, ids, ahora: Optional[datetime] = None, cli: Optional[Wikimedia] = None,
              tope: int = POR_VUELTA) -> dict:
    """Busca la foto de hasta `tope` jugadores pendientes (los de la portada). Nunca levanta excepción."""
    ahora = ahora or datetime.now(timezone.utc)
    if not int(cfg.get("NEWS_FOTOS_ACTIVO", 1)):
        return {"apagado": True}
    out = {"buscadas": 0, "con_foto": 0, "errores": 0}
    try:
        faltan = pendientes(conn, ids, ahora)[:tope]
    except Exception as e:  # pragma: no cover
        return {"error": str(e)[:200]}
    if not faltan:
        return out
    cli = cli or Wikimedia()
    for jid in faltan:
        row = conn.execute("SELECT nombre FROM news_jugador WHERE id=?", (jid,)).fetchone()
        if not row:
            continue
        try:
            r = buscar(cli, row[0])
        except Exception as e:  # red, 429, formato: se reintenta en 24 h
            r = {"estado": "ERROR", "detalle": str(e)[:200]}
            out["errores"] += 1
        guardar(conn, jid, r, ahora)
        out["buscadas"] += 1
        out["con_foto"] += int(r["estado"] == "OK")
    return out


def jugadores_de_portada(conn, ahora: datetime) -> list[int]:
    """Los jugadores que la portada puede mostrar: alertas vivas, noticias externas recientes y la agenda."""
    ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT jugador_id FROM news_alerta WHERE creado_en >= ? AND jugador_id IS NOT NULL ORDER BY id DESC LIMIT 40",
        ((ahora - timedelta(days=3)).isoformat(),))]
    ids += [r[0] for r in conn.execute(
        "SELECT DISTINCT jugador_id FROM news_evento WHERE creado_en >= ? AND COALESCE(origen,'EXTERNO')='EXTERNO' "
        "ORDER BY id DESC LIMIT 60", ((ahora - timedelta(days=3)).isoformat(),))]
    # v7.7: después, los de la agenda (los partidos más cercanos primero)
    for r in conn.execute(
            "SELECT jugador1_id, jugador2_id FROM news_partido WHERE fecha_estimada >= ? AND fecha_estimada <= ? "
            "AND COALESCE(estado,'PROGRAMADO') NOT IN ('JUGADO','SIN_RESULTADO','DUPLICADO') ORDER BY fecha_estimada LIMIT 200",
            ((ahora - timedelta(hours=1)).isoformat(), (ahora + timedelta(hours=30)).isoformat())):
        ids += [i for i in (r[0], r[1]) if i]
    return list(dict.fromkeys(ids))
