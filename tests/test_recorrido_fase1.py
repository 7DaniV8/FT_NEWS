"""Recorrido completo Fase 1–3 sin red: RankingFTR, Tavily y Gemini simulados
con el formato real de cada API (httpx.MockTransport)."""
import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from ft_news import config, evaluador, fuentes, memoria, tareas
from ft_news.app import app
from ft_news.proveedores.gemini import Gemini
from ft_news.proveedores.tavily import Tavily

HOY = datetime(2026, 10, 8, 15, tzinfo=timezone.utc)
MANANA = (HOY + timedelta(hours=20)).isoformat()


class ClienteFTR:
    llamadas = 0
    veredicto = "NO_CALIBRADAS"

    def calibracion(self):
        self.llamadas += 1
        return {"veredicto": self.veredicto, "muestra": 420 if self.veredicto == "CALIBRADAS_OK" else 20,
                "razones": [] if self.veredicto == "CALIBRADAS_OK" else ["Muestra insuficiente"]}

    def utr_padron(self, desde_id=0, limite=2000):
        self.llamadas += 1
        return {"jugadores": [
            {"player_id": 1, "nombre_ftr": "Juan Perez", "nombre_utr": "Juan Perez", "genero": "M", "nacionalidad": "ARG",
             "utr_player_id": 501, "utr_singles": 12.9, "fecha_captura": (HOY - timedelta(days=3)).isoformat()},
            {"player_id": 2, "nombre_ftr": "Luca Rossi", "nombre_utr": "Luca Rossi", "genero": "M", "nacionalidad": "ITA",
             "utr_player_id": 502, "utr_singles": 12.4, "fecha_captura": (HOY - timedelta(days=3)).isoformat()},
        ], "siguiente_desde_id": None}

    def fixtures(self, horas_adelante=72):
        self.llamadas += 1
        return {"fixtures": [{"fixture_id": 777, "fecha": MANANA, "torneo": "Challenger Lima", "superficie": "clay",
                              "genero": "M", "jugador1": "Perez J.", "jugador2": "Rossi L.", "odd1": 1.40, "odd2": 2.90}]}


def _tavily_handler(estado):
    def h(req: httpx.Request):
        estado["tavily"].append(json.loads(req.content))
        assert req.headers["authorization"] == "Bearer tvly-test"
        q = json.loads(req.content)["query"]
        if "Perez" in q and "tennis" in q:
            return httpx.Response(200, json={"results": [
                {"title": "Perez sufre molestias en la muñeca", "url": "https://tennistourtalk.com/perez-wrist",
                 "content": "Juan Perez, the Argentine, said after the match he felt pain in his right wrist...",
                 "published_date": (HOY - timedelta(days=1)).strftime("%a, %d %b %Y 10:00:00 GMT"), "score": 0.9}],
                "response_time": 0.8})
        return httpx.Response(200, json={"results": [], "response_time": 0.3})
    return h


def _gemini_handler(estado):
    def h(req: httpx.Request):
        cuerpo = json.loads(req.content)
        estado["gemini"].append(cuerpo)
        assert cuerpo["generationConfig"]["responseMimeType"] == "application/json"
        datos = {"sobre_jugador": True, "confianza_identidad": 0.93, "categoria": "LESION_MOLESTIA",
                 "direccion": "NEGATIVA", "naturaleza": "DECLARACION",
                 "fecha_evento": (HOY - timedelta(days=1)).strftime("%Y-%m-%d"),
                 "resumen_es": "Perez declaró molestias en la muñeca derecha tras su partido.",
                 "relevancia_deportiva": "podría afectar el saque", "fragmento_original": "felt pain in his right wrist",
                 "idioma": "en"}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(datos)}]}}],
                                         "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 120}})
    return h


def _armar(conn, cfg_base, autorizar=True):
    # solo tennistourtalk.com autorizada, para que las aserciones de include_domains sean exactas
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"] if autorizar else [])
    estado = {"tavily": [], "gemini": []}
    tav = Tavily(api_key="tvly-test", transport=httpx.MockTransport(_tavily_handler(estado)))
    gem = Gemini(api_key="g-test", transport=httpx.MockTransport(_gemini_handler(estado)))
    cfg = dict(cfg_base, NEWS_ACTIVO=1, NEWS_IDIOMAS="en,es,it")
    return estado, tav, gem, cfg


def test_sin_fuentes_autorizadas_no_busca(conn, cfg):
    estado, tav, gem, c = _armar(conn, cfg, autorizar=False)
    r = tareas.ciclo(conn, cliente=ClienteFTR(), cfg=c, tavily=tav, gemini=gem, ahora=HOY)
    assert r["pasos"]["radar"]["motivo"] == "SIN_FUENTES_AUTORIZADAS" and tav.llamadas == 0 and gem.llamadas == 0
    assert r["pasos"]["partidos"]["partidos"] == 1                 # los partidos sí se sincronizan


def test_recorrido_completo_sin_calibrar_y_calibrado(conn, cfg, monkeypatch):
    estado, tav, gem, c = _armar(conn, cfg)
    r = tareas.ciclo(conn, cliente=ClienteFTR(), cfg=c, tavily=tav, gemini=gem, ahora=HOY)
    assert r["motivo"] == "OK"
    # identidad: 'Perez J.' del fixture se unió a 'Juan Perez' del padrón
    assert conn.execute("SELECT COUNT(*) FROM news_jugador").fetchone()[0] == 2
    # radar: Perez (en, es) y Rossi (en, es, it) → 5 búsquedas, todas con lista blanca
    assert tav.llamadas == 5 and all(b["include_domains"] == ["tennistourtalk.com"] for b in estado["tavily"])
    assert all(b["topic"] == "news" for b in estado["tavily"])
    # 1 artículo nuevo → 1 llamada a Gemini → 1 evento
    assert gem.llamadas == 1 and r["pasos"]["radar"]["eventos"] == 1
    ev = conn.execute("SELECT * FROM news_evento").fetchone()
    assert ev["categoria"] == "LESION_MOLESTIA" and ev["nivel"] == "B" and ev["estado"] == "VIGENTE"
    assert ev["fuente"] == "tennistourtalk.com" and ev["relevancia_deportiva"] == "podría afectar el saque"
    # costos anotados
    costos = r["pasos"]["costos"]
    assert costos["busquedas"] == 5 and costos["tokens"] == 1020 and costos["usd"] > 0
    # descubridor: bandas SIN calibrar → 🔎 BANDAS_NO_CALIBRADAS, nunca 🔥
    e = conn.execute("SELECT * FROM news_evaluacion").fetchone()
    assert e["tipo_alerta"] == "INTERESANTE" and e["motivo"] == "BANDAS_NO_CALIBRADAS"
    assert e["banda_utr"] == "FAVORITO" and e["banda_mercado"] == "FAVORITO" and e["cuota_x"] == 1.40
    assert "sin calibrar" in e["texto_discord"] and "%" not in e["texto_discord"]
    # segundo ciclo: nada se vuelve a pagar (misma URL, cola reprogramada)
    r2 = tareas.ciclo(conn, cliente=ClienteFTR(), cfg=c, tavily=tav, gemini=gem, ahora=HOY + timedelta(minutes=15))
    assert tav.llamadas == 5 and gem.llamadas == 1 and r2["pasos"]["radar"]["jugadores"] == 0
    # la calibración automática: RankingFTR dijo NO → bandas en 0 y quedó anotado
    assert r["pasos"]["calibracion"]["veredicto"] == "NO_CALIBRADAS" and r["pasos"]["calibracion"]["bandas_calibradas"] == 0
    # 6 h después RankingFTR responde CALIBRADAS_OK → el motor enciende las bandas solo y sale 🔥 contra Perez
    ftr_ok = ClienteFTR(); ftr_ok.veredicto = "CALIBRADAS_OK"
    c2 = dict(c)
    r3 = tareas.ciclo(conn, cliente=ftr_ok, cfg=c2, tavily=tav, gemini=gem, ahora=HOY + timedelta(hours=7))
    assert r3["pasos"]["calibracion"] == {"veredicto": "CALIBRADAS_OK", "muestra": 420, "bandas_calibradas": 1, "cambio": 1}
    assert config.leer_config(conn)["NEWS_BANDAS_CALIBRADAS"] == 1          # quedó guardado en news_config
    c2["NEWS_BANDAS_CALIBRADAS"] = 1
    e = conn.execute("SELECT * FROM news_evaluacion").fetchone()
    assert r3["pasos"]["descubridor"]["FUEGO"] == 1 and e["tipo_alerta"] == "FUEGO" and e["motivo"] == "CONTRA_X"
    assert e["texto_discord"].startswith("🔥 FULLTENIS") and "Juan Perez" in e["texto_discord"]
    assert "Challenger Lima" in e["texto_discord"]
    assert conn.execute("SELECT COUNT(*) FROM news_evaluacion").fetchone()[0] == 1   # una por partido
    # señales: con NEWS_DISCORD_ACTIVO=0 nada; con 1, la 🔥
    assert evaluador.senales(conn, c2) and evaluador.senales(conn, c2)[0]["jugador_x"] == "Juan Perez"
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", __import__("pathlib").Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    with TestClient(app) as t:
        h = {"X-FT-News-Secret": "secreto-pruebas"}
        t.post("/news/config", headers=h, json={"clave": "NEWS_DISCORD_ACTIVO", "valor": "0", "por": "t"})
        assert t.get("/news/senales", headers=h).json() == {"senales": [], "motivo": "NEWS_DISCORD_ACTIVO=0"}
        t.post("/news/config", headers=h, json={"clave": "NEWS_DISCORD_ACTIVO", "valor": "1", "por": "t"})
        s = t.get("/news/senales", headers=h).json()["senales"]
        assert len(s) == 1 and s[0]["tipo_alerta"] == "FUEGO" and s[0]["texto_voz"]
        r = t.post("/news/senales/dicho", headers=h, json={"avisos": [{"id": s[0]["id"], "dicho": True, "en": HOY.isoformat()}]})
        assert r.json()["marcadas"] == 1
        assert t.get("/news/senales", headers=h).json()["senales"] == []          # no se repite
        hoy = t.get("/news/hoy", headers=h).json()
        assert hoy["evaluaciones"][0]["dicho_discord"] == 1 and hoy["eventos"][0]["categoria"] == "LESION_MOLESTIA"
        assert hoy["cola"].get("PARTIDO_24H") == 2
    # una 🔥 ya dicha no se degrada si después cambia la lectura
    c3 = dict(c2, NEWS_BANDAS_CALIBRADAS=0)
    tareas.ciclo(conn, cliente=ClienteFTR(), cfg=c3, tavily=tav, gemini=gem, ahora=HOY + timedelta(hours=7, minutes=15))
    e = conn.execute("SELECT * FROM news_evaluacion").fetchone()
    assert e["tipo_alerta"] == "FUEGO" and e["dicho_motivo"] == "INTERESANTE:BANDAS_NO_CALIBRADAS"


def test_regreso_no_borra_lesion_en_el_recorrido(conn, cfg):
    estado, tav, gem, c = _armar(conn, cfg)
    c["NEWS_BANDAS_CALIBRADAS"] = 1
    c["NEWS_BANDAS_AUTO"] = 0
    tareas.ciclo(conn, cliente=ClienteFTR(), cfg=c, tavily=tav, gemini=gem, ahora=HOY)
    jid = conn.execute("SELECT jugador_id FROM news_evento").fetchone()[0]
    # llega un regreso declarado → la lesión queda en seguimiento y la evaluación baja a 🔎
    memoria.guardar_evento_db(conn, memoria.nuevo_evento(jid, "REGRESO", "POSITIVA", "DECLARACION", "B",
                                                         HOY.isoformat(), resumen_es="vuelve a jugar"))
    hist = memoria.historial_db(conn, jid)
    assert [h["estado"] for h in hist] == ["EN_SEGUIMIENTO", "VIGENTE"]
    tareas.ciclo(conn, cliente=ClienteFTR(), cfg=c, tavily=tav, gemini=gem, ahora=HOY + timedelta(minutes=15))
    e = conn.execute("SELECT * FROM news_evaluacion").fetchone()
    assert e["tipo_alerta"] == "INTERESANTE" and e["motivo"] == "ESTADO_FISICO_SIN_VERIFICAR"


def test_articulo_viejo_nace_vencido_y_otro_jugador_se_descarta(conn, cfg):
    from ft_news import radar
    fuentes.sembrar(conn)
    fuentes.autorizar(conn, "puntodebreak.com", True, "REVISADO_OK", "", "r")
    from ft_news import jugadores as jg
    jid = jg.upsert(conn, "Ana Alta", "F", "COL", "wta")
    jugador = {"jugador_id": jid, "nombre": "Ana Alta", "pais": "COL", "genero": "F", "circuito": "wta"}
    respuestas = iter([
        {"sobre_jugador": True, "confianza_identidad": 0.95, "categoria": "LESION_MOLESTIA", "direccion": "NEGATIVA",
         "naturaleza": "HECHO", "fecha_evento": "2023-05-01", "resumen_es": "lesión de 2023", "relevancia_deportiva": "x",
         "fragmento_original": "y", "idioma": "es"},
        {"sobre_jugador": False, "confianza_identidad": 0.1, "categoria": "OTRA", "direccion": "NEUTRA",
         "naturaleza": "INTERPRETACION", "fecha_evento": None, "resumen_es": "", "relevancia_deportiva": "",
         "fragmento_original": "", "idioma": "es"},
        {"sobre_jugador": True, "confianza_identidad": 0.6, "categoria": "LOCALIA", "direccion": "POSITIVA",
         "naturaleza": "HECHO", "fecha_evento": None, "resumen_es": "juega en casa", "relevancia_deportiva": "",
         "fragmento_original": "", "idioma": "es"},
    ])

    def h(req):
        d = next(respuestas)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(d)}]}}],
                                         "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})
    gem = Gemini(api_key="g", transport=httpx.MockTransport(h))
    art = {"url": "https://puntodebreak.com/a", "dominio": "puntodebreak.com", "titulo": "t", "contenido": "c",
           "fecha_publicacion": None}
    nuevo = lambda a: radar._articulo_nuevo(conn, a)  # noqa: E731
    r1 = radar.procesar_articulo(conn, cfg, gem, jugador, art, nuevo(art), HOY)
    assert r1["resultado"] == "EVENTO" and r1["estado"] == "VENCIDO"
    a2 = dict(art, url="https://puntodebreak.com/b")
    r2 = radar.procesar_articulo(conn, cfg, gem, jugador, a2, nuevo(a2), HOY)
    assert r2["resultado"] == "OTRO_JUGADOR"
    a3 = dict(art, url="https://puntodebreak.com/c", fecha_publicacion="2026-10-07")
    r3 = radar.procesar_articulo(conn, cfg, gem, jugador, a3, nuevo(a3), HOY)
    assert r3["resultado"] == "IDENTIDAD_DUDOSA"
    assert conn.execute("SELECT COUNT(*) FROM news_revision WHERE tipo='IDENTIDAD_DUDOSA'").fetchone()[0] == 1
    # sin fecha de evento ni de publicación → se descarta
    gem2 = Gemini(api_key="g", transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
        "candidates": [{"content": {"parts": [{"text": json.dumps({
            "sobre_jugador": True, "confianza_identidad": 0.9, "categoria": "ENFERMEDAD", "direccion": "NEGATIVA",
            "naturaleza": "HECHO", "fecha_evento": None, "resumen_es": "", "relevancia_deportiva": "",
            "fragmento_original": "", "idioma": "es"})}]}}], "usageMetadata": {}})))
    a4 = dict(art, url="https://puntodebreak.com/d")
    assert radar.procesar_articulo(conn, cfg, gem2, jugador, a4, nuevo(a4), HOY)["resultado"] == "SIN_FECHA"


def test_proveedores_errores():
    from ft_news.proveedores.tavily import ErrorProveedor
    t = Tavily(api_key="", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    try:
        t.buscar("x", ["a.com"]); assert False
    except ErrorProveedor as e:
        assert e.fatal and t.llamadas == 0
    t = Tavily(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    try:
        t.buscar("x", ["a.com"]); assert False
    except ErrorProveedor as e:
        assert e.fatal and t.llamadas == 1
    t = Tavily(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    try:
        t.buscar("x", []); assert False
    except ErrorProveedor as e:
        assert "sin dominios" in str(e) and t.llamadas == 0
    g = Gemini(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": [
        {"content": {"parts": [{"text": "no es json"}]}}], "usageMetadata": {"promptTokenCount": 1}})))
    r = g.clasificar({"nombre": "x"}, {"url": "u"})
    assert r["ok"] is False and "esquema" in r["error"] and r["tokens_entrada"] == 1
