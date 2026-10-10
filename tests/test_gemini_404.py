"""09/10/2026 — Gemini 404 (caso real: 67 ciclos seguidos con 'gemini-2.5-flash 404'):
el proveedor busca otro modelo, la clave no viaja en la URL, y un artículo que
falla no tumba el radar ni hace pagar Tavily de nuevo."""
import json

import httpx

from ft_news.proveedores.gemini import Gemini
from ft_news.proveedores.tavily import ErrorProveedor

DATOS = {"sobre_jugador": True, "confianza_identidad": 0.9, "categoria": "LESION_MOLESTIA", "direccion": "NEGATIVA",
         "naturaleza": "DECLARACION", "fecha_evento": "2026-10-08", "resumen_es": "x", "relevancia_deportiva": "y",
         "fragmento_original": "z", "idioma": "en"}
OK = {"candidates": [{"content": {"parts": [{"text": json.dumps(DATOS)}]}}],
      "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}}


def _handler(llamadas, modelos):
    def h(req: httpx.Request):
        llamadas.append((req.method, str(req.url), req.headers.get("x-goog-api-key")))
        assert "key=" not in str(req.url), "la clave no va en la URL"
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"models": [{"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]}
                                                        for m in modelos]})
        modelo = req.url.path.split("/models/")[1].split(":")[0]
        if modelo not in modelos:
            return httpx.Response(404, json={"error": {"code": 404, "message": f"models/{modelo} is not found"}})
        return httpx.Response(200, json=OK)
    return h


def test_404_elige_otro_modelo_y_sigue():
    llamadas = []
    g = Gemini(api_key="AQ.clave", modelo="gemini-2.5-flash",
               transport=httpx.MockTransport(_handler(llamadas, ["gemini-2.0-flash", "gemini-pro-x"])))
    r = g.clasificar({"nombre": "A"}, {"url": "u", "titulo": "t", "contenido": "c"})
    assert r["ok"] and r["datos"]["categoria"] == "LESION_MOLESTIA"
    assert g.modelo == "gemini-2.0-flash" and "no disponible (404)" in g.aviso
    assert [m for m, _u, _k in llamadas] == ["POST", "GET", "POST"]
    assert all(k == "AQ.clave" for _m, _u, k in llamadas)
    # la segunda clasificación ya va directo al modelo elegido
    g.clasificar({"nombre": "A"}, {"url": "u2", "titulo": "t", "contenido": "c"})
    assert llamadas[-1][1].endswith("/models/gemini-2.0-flash:generateContent")


def test_404_sin_alternativa_es_error_fatal_claro():
    g = Gemini(api_key="k", modelo="gemini-2.5-flash", transport=httpx.MockTransport(_handler([], ["gemini-pro-x"])))
    try:
        g.clasificar({"nombre": "A"}, {"url": "u", "titulo": "t", "contenido": "c"})
        assert False, "debía fallar"
    except ErrorProveedor as e:
        assert e.fatal and "gemini-pro-x" in str(e) and "GEMINI_API_KEY" in str(e)


def test_otro_4xx_no_escapa_como_httpstatuserror():
    g = Gemini(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad request")))
    try:
        g.clasificar({"nombre": "A"}, {"url": "u", "titulo": "t", "contenido": "c"})
        assert False
    except ErrorProveedor as e:
        assert "400" in str(e) and not e.fatal


def test_radar_no_muere_por_un_articulo_y_reprograma(conn, cfg):
    """Antes: un HTTPStatusError de Gemini abortaba el paso radar entero y el
    jugador quedaba sin reprogramar (Tavily pagado de nuevo cada 15 min)."""
    from datetime import datetime, timezone
    from ft_news import fuentes, radar
    from ft_news import jugadores as jg
    from ft_news.proveedores.tavily import Tavily
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    c = dict(cfg, NEWS_ACTIVO=1, NEWS_IDIOMAS="en")
    jid = jg.upsert(conn, "Juan Perez", "M", "ARG", "atp")
    conn.execute("INSERT OR REPLACE INTO news_jugador_cola (jugador_id, prioridad, motivo, situacion, actualizado_en) "
                 "VALUES (?,?,?,?,?)", (jid, 1, "PARTIDO_PROXIMO", "PARTIDO_24H", "2026-10-09T00:00:00+00:00"))
    conn.commit()
    hoy = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    tav = Tavily(api_key="t", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": [
        {"title": "x", "url": "https://tennistourtalk.com/a", "content": "c", "published_date": "Thu, 08 Oct 2026 10:00:00 GMT",
         "score": 0.9}], "response_time": 0.1})))

    class GeminiRoto:
        modelo, aviso, llamadas = "gemini-2.5-flash", None, 0

        def clasificar(self, jugador, art):
            self.llamadas += 1
            raise httpx.HTTPStatusError("404", request=httpx.Request("POST", "https://x"), response=httpx.Response(404))

    g = GeminiRoto()
    r = radar.correr(conn, c, tav, g, hoy)
    assert r["jugadores"] == 1 and r["busquedas"] == 1 and r["articulos_nuevos"] == 1 and r["errores"]
    fila = conn.execute("SELECT proxima_busqueda_en, ultimo_error FROM news_jugador_cola WHERE jugador_id=?", (jid,)).fetchone()
    assert fila["proxima_busqueda_en"] and fila["proxima_busqueda_en"] > hoy.isoformat()
    # segunda vuelta: el jugador ya no está pendiente → Tavily no se vuelve a pagar
    r2 = radar.correr(conn, c, tav, g, hoy)
    assert r2["jugadores"] == 0 and r2["busquedas"] == 0


# ── 09/10/2026: Claude como clasificador principal (NEWS_CLASIFICADOR) ──
def _claude_handler(llamadas, modelos_ok=("claude-haiku-5-5",)):
    def h(req: httpx.Request):
        cuerpo = json.loads(req.content)
        llamadas.append((cuerpo["model"], req.headers.get("x-api-key")))
        if cuerpo["model"] not in modelos_ok:
            return httpx.Response(404, json={"type": "error", "error": {"type": "not_found_error", "message": "model not found"}})
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(DATOS)}],
                                         "usage": {"input_tokens": 400, "output_tokens": 90}})
    return h


def test_claude_clasifica_con_el_mismo_contrato_y_prueba_modelos_alternativos():
    from ft_news.proveedores.claude import Claude
    llamadas = []
    c = Claude(api_key="sk-ant-x", modelo="claude-haiku-5-5", transport=httpx.MockTransport(_claude_handler(llamadas, ("claude-haiku-4-5",))))
    r = c.clasificar({"nombre": "A"}, {"url": "u", "titulo": "t", "contenido": "c"})
    assert r["ok"] and r["datos"]["categoria"] == "LESION_MOLESTIA" and r["datos"]["confianza_identidad"] == 0.9
    assert r["tokens_entrada"] == 400 and r["usd"] > 0 and c.nombre == "claude"
    assert c.modelo == "claude-haiku-4-5" and "no disponible" in c.aviso
    assert [m for m, _k in llamadas] == ["claude-haiku-5-5", "claude-haiku-4-5"]


def test_elegir_clasificador_modos_y_failover():
    from ft_news import tareas

    class P:
        def __init__(self, n): self.nombre, self.modelo, self.aviso = n, "m", None
    g, c = P("gemini"), P("claude")
    assert tareas.elegir_clasificador({"NEWS_CLASIFICADOR": "auto"}, g, c, {}) == (g, c)
    assert tareas.elegir_clasificador({"NEWS_CLASIFICADOR": "claude"}, g, c, {}) == (c, g)
    assert tareas.elegir_clasificador({"NEWS_CLASIFICADOR": "gemini"}, g, c, {}) == (g, c)
    assert tareas.elegir_clasificador({"NEWS_CLASIFICADOR": "auto"}, None, c, {}) == (c, None)
    assert tareas.elegir_clasificador({"NEWS_CLASIFICADOR": "claude"}, g, None, {}) == (g, None)
    assert tareas.elegir_clasificador({"NEWS_CLASIFICADOR": "auto"}, None, None, {}) == (None, None)
    # Gemini marcado caído hace 1 h → Claude; hace 7 h → se vuelve a probar Gemini
    from datetime import datetime, timedelta, timezone
    hace1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    hace7 = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    assert tareas.elegir_clasificador({"NEWS_CLASIFICADOR": "auto"}, g, c, {"clasificador_caido": {"valor": f"gemini {hace1} 404"}}) == (c, g)
    assert tareas.elegir_clasificador({"NEWS_CLASIFICADOR": "auto"}, g, c, {"clasificador_caido": {"valor": f"gemini {hace7} 404"}}) == (g, c)


def test_ciclo_con_claude_como_principal(conn, cfg):
    """Sin GEMINI_API_KEY: el ciclo clasifica con Claude y lo deja en el estado."""
    from datetime import datetime, timezone
    from ft_news import fuentes, tareas
    from ft_news import jugadores as jg
    from ft_news.db import estado_todo
    from ft_news.proveedores.claude import Claude
    from ft_news.proveedores.tavily import Tavily
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    c = dict(cfg, NEWS_ACTIVO=1, NEWS_IDIOMAS="en", NEWS_CLASIFICADOR="auto")
    jid = jg.upsert(conn, "Juan Perez", "M", "ARG", "atp")
    conn.execute("INSERT OR REPLACE INTO news_jugador_cola (jugador_id, prioridad, motivo, situacion, actualizado_en) "
                 "VALUES (?,?,?,?,?)", (jid, 1, "PARTIDO_PROXIMO", "PARTIDO_24H", "2026-10-09T00:00:00+00:00"))
    conn.commit()
    hoy = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    tav = Tavily(api_key="t", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": [
        {"title": "x", "url": "https://tennistourtalk.com/p1", "content": "c", "published_date": "Thu, 08 Oct 2026 10:00:00 GMT",
         "score": 0.9}], "response_time": 0.1})))
    llamadas = []
    cl = Claude(api_key="sk", transport=httpx.MockTransport(_claude_handler(llamadas)))

    from tests.test_recorrido_fase1 import ClienteFTR as FTR
    r = tareas.ciclo(conn, cliente=FTR(), cfg=c, tavily=tav, gemini=None, claude=cl, ahora=hoy)
    assert r["pasos"]["radar"]["eventos"] == 1 and len(llamadas) == 1
    est = estado_todo(conn)
    assert est["clasificador"]["valor"].startswith("claude · claude-haiku-5-5")
    assert conn.execute("SELECT proveedor FROM news_costos_dia WHERE proveedor='claude'").fetchone()
