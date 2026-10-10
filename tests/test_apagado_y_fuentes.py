"""Fase 0: apagado de verdad, fuentes sin autorizar no se leen, API responde."""
import httpx
from fastapi.testclient import TestClient

from ft_news import config, costos, fuentes, tareas
from ft_news.app import app


class ClienteContador:
    """Cliente falso: cuenta llamadas. Con NEWS_ACTIVO=0 debe quedar en 0."""
    llamadas = 0


def test_apagado_no_llama_a_nadie(conn, cfg):
    cli = ClienteContador()
    r = tareas.ciclo(conn, cliente=cli, cfg=cfg)
    assert r["motivo"] == "APAGADO" and r["llamadas_externas"] == 0 and cli.llamadas == 0
    est = {k: v["valor"] for k, v in __import__("ft_news.db", fromlist=["estado_todo"]).estado_todo(conn).items()}
    assert est["activo"] == "0" and "apagado" in est["motivo"]


class ClienteVacio(ClienteContador):
    """RankingFTR falso sin padrón ni fixtures; cuenta llamadas."""
    def utr_padron(self, desde_id=0, limite=2000):
        self.llamadas += 1
        return {"jugadores": [], "siguiente_desde_id": None}

    def fixtures(self, horas_adelante=72):
        self.llamadas += 1
        return {"fixtures": []}

    def calibracion(self):
        self.llamadas += 1
        return {"veredicto": "NO_CALIBRADAS", "muestra": 12, "razones": ["Muestra insuficiente: 12 partidos (mínimo 300)."]}

    def historial(self, desde_fecha, hasta_fecha=None):
        self.llamadas += 1
        return {"partidos": []}

    def defensa(self):
        self.llamadas += 1
        return {"jugadores": []}


def test_activo_sin_claves_no_llama_a_proveedores(conn, cfg):
    cli = ClienteVacio()
    c = dict(cfg, NEWS_ACTIVO=1)
    r = tareas.ciclo(conn, cliente=cli, cfg=c)
    assert r["motivo"] == "OK" and cli.llamadas == 5                 # padrón, calibración, fixtures, historial, defensa
    assert r["pasos"]["calibracion"]["veredicto"] == "NO_CALIBRADAS" and r["pasos"]["calibracion"]["bandas_calibradas"] == 0
    assert r["pasos"]["radar"] == {"motivo": "SIN_CLAVES"}
    assert r["pasos"]["cierre"]["revisados"] == 0 and r["pasos"]["rss"] == {"motivo": "SIN_CLAVES"}


def test_activo_duerme_por_tope(conn, cfg):
    c = dict(cfg, NEWS_ACTIVO=1, NEWS_MAX_BUSQUEDAS_DIA=5)
    costos.anotar(conn, "tavily", busquedas=5, usd=0.04)
    r = tareas.ciclo(conn, cliente=ClienteVacio(), cfg=c)
    assert r["pasos"]["radar"] == {"motivo": "TOPE_BUSQUEDAS_DIA"}
    assert costos.puede_gastar(conn, c)["ok"] is False


def test_fuentes_iniciales_autorizadas_y_el_resto_no(conn, cfg):
    n = fuentes.sembrar(conn)
    assert n == len(fuentes.CATALOGO) and fuentes.sembrar(conn) == 0
    for f in fuentes.listar(conn):
        if f["dominio"] in config.FUENTES_INICIALES:
            assert f["autorizada"] == 1 and f["estado_tc"] == "REVISADO_OK" and f["revisado_por"] == "ruben"
            assert fuentes.permitida(conn, f["dominio"], cfg)
        else:
            assert f["autorizada"] == 0
            assert not fuentes.permitida(conn, f["dominio"], cfg)
    assert set(config.FUENTES_INICIALES) == {"tennistourtalk.com", "puntodebreak.com", "livetennis.it", "ubitennis.com",
                                             "tennisactu.net", "atptour.com"}
    for d in ("itftennis.com", "app.utrsports.net", "flashscore.com"):
        assert not fuentes.permitida(conn, d, cfg)
    # quitada desde la pestaña: sembrar de nuevo NO la vuelve a autorizar
    fuentes.autorizar(conn, "atptour.com", False, "REVISADO_OK", "quitada", "ruben")
    fuentes.sembrar(conn)
    assert not fuentes.permitida(conn, "atptour.com", cfg)


def test_fuentes_sin_iniciales(conn, cfg):
    n = fuentes.sembrar(conn, iniciales=[])
    assert n == len(fuentes.CATALOGO)
    for f in fuentes.listar(conn):
        assert f["autorizada"] == 0
        assert not fuentes.permitida(conn, f["dominio"], cfg)
    # las que ya se revisaron como NO quedan marcadas
    estados = {f["dominio"]: f["estado_tc"] for f in fuentes.listar(conn)}
    assert estados["flashscore.com"] == "REVISADO_NO" and estados["itftennis.com"] == "PENDIENTE"
    # no se puede autorizar sin REVISADO_OK
    try:
        fuentes.autorizar(conn, "itftennis.com", True, "PENDIENTE", "", "daniel")
        assert False
    except ValueError:
        pass
    f = fuentes.autorizar(conn, "tennistourtalk.com", True, "REVISADO_OK", "RSS público", "ruben")
    assert f["autorizada"] == 1 and fuentes.permitida(conn, "tennistourtalk.com", cfg)


def test_cliente_rankingftr_sin_config_no_llama():
    from ft_news.cliente_rankingftr import Cliente, ErrorFTR
    c = Cliente(base="", secreto="", pausa=0)
    try:
        c.fixtures()
        assert False
    except ErrorFTR:
        assert c.llamadas == 0


def test_cliente_rankingftr_no_reintenta_401():
    from ft_news.cliente_rankingftr import Cliente, ErrorFTR
    estado = {"n": 0}

    def handler(req):
        estado["n"] += 1
        return httpx.Response(401)
    c = Cliente(base="http://ftr", secreto="s", pausa=0, transport=httpx.MockTransport(handler))
    try:
        c.utr_padron()
        assert False
    except ErrorFTR:
        assert estado["n"] == 1


def test_api(monkeypatch):
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    with TestClient(app) as t:
        assert t.get("/salud").json()["fase"] == 1
        assert t.get("/news/estado").status_code == 401
        h = {"X-FT-News-Secret": "secreto-pruebas"}
        e = t.get("/news/estado", headers=h).json()
        assert e["activo"] is True and e["bandas_calibradas"] is False and e["fuentes"]["autorizadas"] == 6
        # v6: Discord nace encendido (Rubén 09/10 23:13: "activemos las tres alertas"); apagar es un clic
        assert e["discord_activo"] is True
        assert t.get("/news/senales", headers=h).json() == {"senales": []}          # activo, sin señales todavía
        t.post("/news/config", headers=h, json={"clave": "NEWS_DISCORD_ACTIVO", "valor": "0", "por": "t"})
        assert t.get("/news/senales", headers=h).json() == {"senales": [], "motivo": "NEWS_DISCORD_ACTIVO=0"}
        t.post("/news/config", headers=h, json={"clave": "NEWS_DISCORD_ACTIVO", "valor": "1", "por": "t"})
        r = t.post("/news/config", headers=h, json={"clave": "NEWS_MAX_FUEGO_DIA", "valor": "7", "por": "t"})
        assert r.json()["efectivo"] == 7
        assert t.post("/news/config", headers=h, json={"clave": "INVENTADA", "valor": "1"}).status_code == 400
        p = {x["clave"]: x for x in t.get("/news/config", headers=h).json()["parametros"]}
        assert p["NEWS_ACTIVO"]["valor"] == 1 and p["NEWS_MAX_FUEGO_DIA"]["valor"] == 7
        assert len(t.get("/news/fuentes", headers=h).json()["fuentes"]) == len(fuentes.CATALOGO)
        assert t.get("/news/costos", headers=h).json()["puede_gastar"]["ok"] is True
        assert t.get("/news/jugadores/1/memoria", headers=h).json()["eventos"] == []
