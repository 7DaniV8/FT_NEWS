"""v7.4 (13/10/2026): 📰 portada tipo periódico. Solo lectura; titular = la misma alerta que va a Discord;
una 🔥 sin calibración respaldada sale SIEMPRE como EXPERIMENTAL; nada de códigos del motor, Elo ni FTR. Sin red."""
import json
import re
from datetime import timedelta

from fastapi.testclient import TestClient

from ft_news import alertas, memoria, portada
from ft_news import jugadores as jg
from ft_news.app import app
from tests.test_v5_alertas import FTR, HOY, _art, _cfg, _ciclo, _gem, _lesion, _tav

CODIGOS = re.compile(r"\b(LESION_MOLESTIA|RETIRO_ABANDONO|CONTRA_X|A_FAVOR_X|FUEGO_EXPERIMENTAL|BANDAS_NO_CALIBRADAS|"
                     r"SIN_NOTICIA_EXTERNA_FUERTE|INTERESANTE:|Elo|FTR)\b")


def _visible(p: dict) -> str:
    """Todo lo que la pestaña muestra (sin las claves internas `tipo`/`seccion`/`id`)."""
    def limpia(x):
        if isinstance(x, dict):
            return {k: limpia(v) for k, v in x.items() if k not in ("tipo", "seccion", "id", "version")}
        if isinstance(x, list):
            return [limpia(v) for v in x]
        return x
    return json.dumps(limpia(p), ensure_ascii=False)


def _con_fuego(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    return c


def test_titular_es_la_alerta_y_sale_experimental(conn, cfg):
    _con_fuego(conn, cfg)
    assert any(a["tipo"] == "FUEGO_EXPERIMENTAL" for a in alertas.listar(conn))
    antes = conn.total_changes
    p = portada.armar(conn, ahora=HOY + timedelta(minutes=20))
    assert conn.total_changes == antes                                   # solo lectura
    t = p["titular"]
    assert t["tipo"] == "FUEGO_EXPERIMENTAL" and t["experimental"] and "EXPERIMENTAL" in t["etiqueta"]
    assert {t["jugador"], t["rival"]} == {"Juan Perez", "Luca Rossi"} and t["torneo"] == "Challenger Lima"
    assert t["favorece"] == "Luca Rossi" and t["cuota_favorece"] == "2,90"
    assert t["confirmacion"].startswith("🗣️") and "tennistourtalk" in t["confirmacion"].lower()
    assert t["imagen"]["tipo"] == "tarjeta" and t["imagen"]["iniciales"]   # sin fotos sin licencia
    assert p["titular_noticia"] is None
    # noticias y lesiones: la de Perez, con su confirmación; agenda con el partido marcado (nunca «validado»)
    assert any(n["jugador"] == "Juan Perez" and n["externa"] and n["enlace"].startswith("https://") for n in p["noticias"] + p["lesiones"])
    assert any(l["jugador"] == "Juan Perez" for l in p["lesiones"])
    lima = [a for a in p["agenda"] if a["torneo"] == "Challenger Lima"]
    assert lima and lima[0]["ft_news"] == "POSIBLE VALOR · EXPERIMENTAL" and lima[0]["cuotas"] == ["1,40", "2,90"]
    assert [a["hora"] for a in p["agenda"]] == sorted(a["hora"] for a in p["agenda"])
    v = _visible(p)
    assert not CODIGOS.search(v), CODIGOS.search(v)
    assert "%" not in v


def test_casilla_manual_no_valida_la_portada(conn, cfg):
    """«Bandas calibradas» marcada a mano sin el veredicto CALIBRADAS_OK: en la portada sigue EXPERIMENTAL."""
    c = _con_fuego(conn, cfg)
    conn.execute("UPDATE news_alerta SET tipo='FUEGO' WHERE tipo='FUEGO_EXPERIMENTAL'")
    conn.execute("UPDATE news_evaluacion SET bandas_calibradas=1")
    conn.commit()
    p = portada.armar(conn, ahora=HOY + timedelta(minutes=20), cfg=dict(c, NEWS_BANDAS_CALIBRADAS=1))
    assert p["titular"]["tipo"] == "FUEGO_EXPERIMENTAL" and "EXPERIMENTAL" in p["titular"]["etiqueta"]
    assert all(a["ft_news"] != "POSIBLE VALOR" for a in p["agenda"])


def test_sin_alertas_abre_la_noticia_mas_fuerte_o_nada(conn, cfg):
    c = _cfg(cfg)
    jg.sincronizar_padron(conn, FTR())
    p0 = portada.armar(conn, ahora=HOY, cfg=c)
    assert p0["titular"] is None and p0["titular_noticia"] is None and p0["noticias"] == [] and p0["lesiones"] == []
    # un dato calculado por nosotros (carga) NO es noticia de portada
    j = jg.buscar_por_nombre(conn, "Juan Perez")
    memoria.guardar_evento_db(conn, memoria.nuevo_evento(j["id"], "CARGA_FISICA", "NEGATIVA", "HECHO", "A", HOY.isoformat(),
                                                         fuente="rankingftr.interno", enlace="contexto:carga",
                                                         resumen_es="3 partidos largos"))
    p1 = portada.armar(conn, ahora=HOY, cfg=c)
    assert p1["titular_noticia"] is None and p1["noticias"] == []
    # una noticia externa de un medio sí abre la portada (sin partido del día inventado)
    e = memoria.nuevo_evento(j["id"], "REGRESO", "POSITIVA", "HECHO", "B", HOY.isoformat(), fuente="https://tennistourtalk.com",
                             enlace="https://tennistourtalk.com/perez-vuelve", resumen_es="Juan Perez vuelve a competir tras tres meses.")
    e["origen"] = "EXTERNO"
    memoria.guardar_evento_db(conn, e)
    p2 = portada.armar(conn, ahora=HOY + timedelta(minutes=5), cfg=c)
    assert p2["titular"] is None and p2["titular_noticia"]["jugador"] == "Juan Perez"
    assert p2["titular_noticia"]["confirmacion"].startswith("📰") and p2["titular_noticia"]["imagen"]["tipo"] == "tarjeta"


def test_endpoint_portada(conn, cfg, monkeypatch):
    from ft_news import config
    _con_fuego(conn, cfg)
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", __import__("pathlib").Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    with TestClient(app) as cl:
        assert cl.get("/news/portada").status_code == 401
        r = cl.get("/news/portada", headers={"X-FT-News-Secret": "secreto-pruebas"})
        assert r.status_code == 200 and "agenda" in r.json() and "titular" in r.json()
