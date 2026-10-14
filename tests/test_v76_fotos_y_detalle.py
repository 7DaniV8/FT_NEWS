"""v7.6 (13/10/2026, Rubén: «¿podemos usar imágenes de la web dando créditos al autor?», «¿qué es partido interesante?,
si le doy clic se debe abrir el modal con todo lo que encontró»). Fotos con licencia de Wikimedia Commons (solo la
ficha de Wikidata del TENISTA, nunca una foto sin licencia o sin autor), el detalle del modal y la portada sin
alertas viejas que hoy no saldrían. Sin red."""
import json
import re
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient

from ft_news import alertas, fotos, portada
from ft_news.app import app
from tests.test_v5_alertas import HOY, _art, _cfg, _ciclo, _gem, _lesion, _tav

CODIGOS = re.compile(r"\b(LESION_MOLESTIA|RETIRO_ABANDONO|CONTRA_X|A_FAVOR_X|FUEGO_EXPERIMENTAL|SIN_INFORMACION_NO_REFLEJADA|Elo|FTR)\b")


def _wm(entidades: dict, licencia="CC BY-SA 4.0", autor='<a href="//commons.wikimedia.org/wiki/User:X">Ana Fotógrafa</a>'):
    """Wikidata + Commons falsos. entidades = {qid: (etiqueta, es_tenista, archivo)}."""
    pedidos = []

    def h(req):
        q = dict(req.url.params)
        pedidos.append(q.get("action"))
        if q.get("action") == "wbsearchentities":
            return httpx.Response(200, json={"search": [{"id": k} for k in entidades]})
        if q.get("action") == "wbgetentities":
            ents = {}
            for qid, (etq, tenista, archivo) in entidades.items():
                claims = {"P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q10833314" if tenista else "Q937857"}}}}]}
                if archivo:
                    claims["P18"] = [{"mainsnak": {"datavalue": {"value": archivo}}}]
                ents[qid] = {"labels": {"en": {"value": etq}}, "aliases": {}, "claims": claims}
            return httpx.Response(200, json={"entities": ents})
        if q.get("action") == "query":
            return httpx.Response(200, json={"query": {"pages": {"1": {"imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Juan.jpg/640px-Juan.jpg",
                "url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Juan.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Juan.jpg",
                "extmetadata": {"Artist": {"value": autor}, "LicenseShortName": {"value": licencia},
                                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"}}}]}}}})
        return httpx.Response(404)
    return fotos.Wikimedia(transport=httpx.MockTransport(h)), pedidos


# ── 1 · fotos ──────────────────────────────────────────────────────────────
def test_foto_solo_de_la_ficha_del_tenista_con_licencia_y_autor():
    cli, _ = _wm({"Q1": ("Juan Perez", True, "Juan Perez 2024.jpg"), "Q2": ("Juan Perez", False, "Futbolista.jpg")})
    r = fotos.buscar(cli, "Juan Perez")
    assert r["estado"] == "OK" and r["qid"] == "Q1" and r["autor"] == "Ana Fotógrafa" and r["licencia"] == "CC BY-SA 4.0"
    assert r["url"].startswith("https://upload.wikimedia.org/") and r["pagina"].startswith("https://commons.wikimedia.org/")
    # dos tenistas con el mismo nombre → no se arriesga
    cli, _ = _wm({"Q1": ("Juan Perez", True, "a.jpg"), "Q3": ("Juan Perez", True, "b.jpg")})
    assert fotos.buscar(cli, "Juan Perez")["estado"] == "AMBIGUO"
    # otro nombre (otra persona) → sin foto
    cli, _ = _wm({"Q1": ("Juan Perez Gomez Ruiz", True, "a.jpg")})
    assert fotos.buscar(cli, "Juan Perez")["estado"] == "SIN_FOTO"
    # licencia que no permite reutilizarla, o sin autor → sin foto
    for lic, autor in (("Fair use", "X"), ("CC BY-NC 2.0", "X"), ("CC BY 2.0", "")):
        cli, _ = _wm({"Q1": ("Juan Perez", True, "a.jpg")}, licencia=lic, autor=autor)
        assert fotos.buscar(cli, "Juan Perez")["estado"] == "SIN_FOTO", lic
    for lic in ("CC0", "Public domain", "CC BY 2.0", "CC BY-SA 3.0"):
        assert fotos.licencia_valida(lic), lic
    cli, _ = _wm({"Q1": ("Juan Perez", True, None)})
    assert fotos.buscar(cli, "Juan Perez")["estado"] == "SIN_FOTO"          # la ficha no tiene imagen


def test_fotos_se_guardan_y_no_se_vuelven_a_buscar(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    cli, pedidos = _wm({"Q1": ("Juan Perez", True, "Juan Perez 2024.jpg")})
    ids = fotos.jugadores_de_portada(conn, HOY + timedelta(minutes=20))
    r = fotos.completar(conn, c, ids, HOY + timedelta(minutes=20), cli=cli)
    assert r["buscadas"] >= 1 and r["con_foto"] >= 1
    n = len(pedidos)
    fotos.completar(conn, c, ids, HOY + timedelta(days=2), cli=cli)
    assert len(pedidos) == n                                                  # 30 días de caché (también el «no hay»)
    p = portada.armar(conn, ahora=HOY + timedelta(minutes=20), cfg=c)
    imgs = [x["imagen"] for x in [p["titular"]] + p["lesiones"] if x and x.get("imagen")]
    foto = next(i for i in imgs if i["tipo"] == "foto")
    assert foto["credito"] == "Foto: Ana Fotógrafa · CC BY-SA 4.0 · Wikimedia Commons" and foto["pagina"]
    assert fotos.completar(conn, dict(c, NEWS_FOTOS_ACTIVO=0), ids, HOY, cli=cli) == {"apagado": True}


def test_error_de_red_se_reintenta_en_24_h(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    caido = fotos.Wikimedia(transport=httpx.MockTransport(lambda req: httpx.Response(429)))
    ids = fotos.jugadores_de_portada(conn, HOY)
    assert fotos.completar(conn, c, ids, HOY, cli=caido)["errores"] >= 1
    assert fotos.pendientes(conn, ids, HOY + timedelta(hours=2)) == []
    assert fotos.pendientes(conn, ids, HOY + timedelta(hours=25))


# ── 2 · el modal: todo lo que encontró ────────────────────────────────────
def test_detalle_del_partido_y_de_la_noticia(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    a = next(x for x in alertas.listar(conn) if x["tipo"] in ("FUEGO_EXPERIMENTAL", "INTERESANTE"))
    antes = conn.total_changes
    d = portada.detalle_partido(conn, a["id"], HOY + timedelta(minutes=20))
    assert conn.total_changes == antes
    assert d["que_es"] and d["partido"]["torneo"] == "Challenger Lima" and d["partido"]["cuotas"] == ["1,40", "2,90"]
    assert d["noticias"] and d["noticias"][0]["usada"] and d["noticias"][0]["enlace"].startswith("https://tennistourtalk.com")
    assert d["noticias"][0]["confirmacion"].startswith("🗣️") and d["lectura"] and d["conclusion"]
    assert {j["nombre"] for j in d["jugadores"]} == {"Juan Perez", "Luca Rossi"} and d["vigente"]
    if d["tipo"] != "INTERESANTE":
        assert d["experimental"] and "EXPERIMENTAL" in d["etiqueta"]
    v = json.dumps({k: v for k, v in d.items() if k not in ("tipo",)}, ensure_ascii=False)
    assert not CODIGOS.search(v), CODIGOS.search(v)
    assert portada.detalle_partido(conn, 99999) is None
    ev_id = d["noticias"][0]["id"]
    n = portada.detalle_noticia(conn, ev_id, HOY + timedelta(minutes=20))
    assert n["noticia"]["jugador"] == "Juan Perez" and n["proximo_partido"]["rival"] == "Luca Rossi" and not n["dobles"]
    assert portada.detalle_noticia(conn, 99999) is None


def test_endpoints_del_modal(conn, cfg, monkeypatch):
    from ft_news import config
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    aid = alertas.listar(conn)[0]["id"]
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", __import__("pathlib").Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    h = {"X-FT-News-Secret": "secreto-pruebas"}
    with TestClient(app) as cl:
        assert cl.get(f"/news/portada/partido/{aid}").status_code == 401
        tipos = {x["tipo"]: x["id"] for x in alertas.listar(conn)}
        pid = tipos.get("FUEGO_EXPERIMENTAL") or tipos.get("INTERESANTE")
        assert cl.get(f"/news/portada/partido/{pid}", headers=h).status_code == 200
        assert cl.get("/news/portada/partido/99999", headers=h).status_code == 404
        assert cl.get("/news/portada/noticia/1", headers=h).status_code == 200


# ── 3 · la portada no muestra alertas que hoy no saldrían ─────────────────
def test_portada_sin_alertas_viejas_de_dobles_ni_agenda_inflada(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    ahora = HOY + timedelta(minutes=20)
    assert portada.armar(conn, ahora=ahora, cfg=c)["titular"]
    # el hecho resulta ser de dobles (como el caso Andrade): la alerta vieja ya no abre la portada
    conn.execute("UPDATE news_evento SET titular='Derrota por walkover en dobles', resumen_es='No jugó su partido de dobles.'")
    conn.commit()
    p = portada.armar(conn, ahora=ahora, cfg=c)
    assert p["titular"] is None and p["interesantes"] == []
    # la agenda ya no marca «interesante» a un partido sin alerta vigente
    assert all(a["ft_news"] == "sin alerta" and a["alerta_id"] is None for a in p["agenda"])
    # nombre largo: va completo en el titular
    assert portada._con_nombre("Lucas Andrade Da Silva", "Derrota por walkover").startswith("Lucas Andrade Da Silva: derrota")
    assert portada._con_nombre("Juan Perez", "Se retiró").startswith("Perez: se retiró")
