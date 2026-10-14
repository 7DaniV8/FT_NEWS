"""v7.7 (13/10/2026 noche, Rubén: «colocar imágenes en FT NEWS · que en estos partidos también tenga la posibilidad
de ver el modal»). Cada partido de la agenda trae la foto (o tarjeta) de los dos y abre un modal: si tiene alerta, el
de la alerta; si no, qué investigó FT NEWS de cada uno y por qué no salió alerta. Sin red."""
import json
import re
from datetime import timedelta

from fastapi.testclient import TestClient

from ft_news import fotos, portada
from ft_news.app import app
from tests.test_v5_alertas import HOY, _art, _cfg, _ciclo, _gem, _lesion, _tav
from tests.test_v76_fotos_y_detalle import _wm

CODIGOS = re.compile(r"\b(LESION_MOLESTIA|RETIRO_ABANDONO|CONTRA_X|A_FAVOR_X|FUEGO_EXPERIMENTAL|SIN_INFORMACION_NO_REFLEJADA|"
                     r"SIN_EVENTOS|JUSTIFICACION_INSUFICIENTE|Elo|FTR)\b")


def _preparar(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    return c


def test_agenda_con_fotos_y_ids(conn, cfg):
    c = _preparar(conn, cfg)
    ahora = HOY + timedelta(minutes=20)
    cli, _ = _wm({"Q1": ("Juan Perez", True, "Juan Perez 2024.jpg")})
    ids = fotos.jugadores_de_portada(conn, ahora)
    ag = portada.armar(conn, ahora=ahora, cfg=c)["agenda"]
    assert ag and all(x["partido_id"] and x["jugador1_id"] and x["jugador2_id"] for x in ag)
    assert {x["jugador1_id"] for x in ag} | {x["jugador2_id"] for x in ag} <= set(ids)       # la agenda también busca foto
    assert all(len(x["imagenes"]) == 2 and x["imagenes"][0]["tipo"] == "tarjeta" for x in ag)
    fotos.completar(conn, c, ids, ahora, cli=cli)
    ag = portada.armar(conn, ahora=ahora, cfg=c)["agenda"]
    perez = next(x for x in ag if "Perez" in (x["jugador1"] or "") + (x["jugador2"] or ""))
    img = next(i for i in perez["imagenes"] if i["nombre"] == "Juan Perez")
    assert img["tipo"] == "foto" and img["url"].startswith("https://upload.wikimedia.org/") and "Ana Fotógrafa" in img["credito"]


def test_modal_de_un_partido_de_la_agenda(conn, cfg):
    c = _preparar(conn, cfg)
    ahora = HOY + timedelta(minutes=20)
    ag = portada.armar(conn, ahora=ahora, cfg=c)["agenda"]
    con = next(x for x in ag if x["alerta_id"])
    d = portada.detalle_agenda(conn, con["partido_id"], ahora)
    assert d["alerta_id"] == con["alerta_id"]                                   # con alerta: abre el de la alerta
    antes = conn.total_changes
    # la noticia resulta ser de dobles → ya no hay alerta vigente: el modal explica qué se investigó
    conn.execute("UPDATE news_evento SET titular='Derrota por walkover en dobles', resumen_es='No jugó su partido de dobles.'")
    conn.commit()
    antes = conn.total_changes
    d = portada.detalle_agenda(conn, con["partido_id"], ahora)
    assert conn.total_changes == antes                                          # solo lectura
    assert d["alerta_id"] is None and d["etiqueta"] == "SIN ALERTA" and d["que_es"]
    assert {j["nombre"] for j in d["jugadores"]} == {"Juan Perez", "Luca Rossi"}
    assert all(j.get("investigacion") and j["investigacion"]["texto"] for j in d["jugadores"])
    assert d["noticias"] and d["noticias"][0]["dobles"] and d["noticias"][0]["enlace"].startswith("https://")
    assert d["partido"]["torneo"] == "Challenger Lima" and d["evaluado"]
    v = json.dumps(d, ensure_ascii=False)
    assert not CODIGOS.search(v), CODIGOS.search(v)
    assert portada.detalle_agenda(conn, 99999, ahora) is None


def test_endpoint_agenda(conn, cfg, monkeypatch):
    from ft_news import config
    c = _preparar(conn, cfg)
    pid = portada.armar(conn, ahora=HOY + timedelta(minutes=20), cfg=c)["agenda"][0]["partido_id"]
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", __import__("pathlib").Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    h = {"X-FT-News-Secret": "secreto-pruebas"}
    with TestClient(app) as cl:
        assert cl.get(f"/news/portada/agenda/{pid}").status_code == 401
        r = cl.get(f"/news/portada/agenda/{pid}", headers=h)
        assert r.status_code == 200 and r.json()["jugadores"]
        assert cl.get("/news/portada/agenda/99999", headers=h).status_code == 404
