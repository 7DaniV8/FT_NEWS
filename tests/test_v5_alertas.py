"""v5 (09/10/2026): alertas 📰 / 🔎 / 🔥 experimental, dedupe y topes; radar
temático y RSS contra el padrón; historial de eventos; cola con cupo para
circuitos menores; endpoints nuevos (alertas, diagnóstico, buscador). Sin red."""
import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from ft_news import alertas, config, fuentes, memoria, radar, tareas, textos
from ft_news import jugadores as jg
from ft_news.app import app
from ft_news.lectores import rss
from ft_news.proveedores.gemini import Gemini
from ft_news.proveedores.tavily import Tavily

HOY = datetime(2026, 10, 8, 15, tzinfo=timezone.utc)


# ── fakes ─────────────────────────────────────────────────────────────────
class FTR:
    veredicto = "NO_CALIBRADAS"
    cap = (HOY - timedelta(hours=3)).isoformat()          # hora de captura de la cuota

    def calibracion(self):
        return {"veredicto": self.veredicto, "muestra": 20, "razones": ["Muestra insuficiente"]}

    def utr_padron(self, desde_id=0, limite=2000):
        js = [("Juan Perez", "M", "ARG", 501, 12.9), ("Luca Rossi", "M", "ITA", 502, 12.4),
              ("Ana Alta", "F", "COL", 503, 10.1), ("Mia Baja", "F", "USA", 504, 9.0),
              ("Pedro Itf", "M", "ESP", 505, 11.0), ("Tom Lowe", "M", "GBR", 506, 11.2)]
        return {"jugadores": [{"player_id": i + 1, "nombre_ftr": n, "nombre_utr": n, "genero": g, "nacionalidad": p,
                               "utr_player_id": u, "utr_singles": s, "fecha_captura": (HOY - timedelta(days=2)).isoformat()}
                              for i, (n, g, p, u, s) in enumerate(js)], "siguiente_desde_id": None}

    def fixtures(self, horas_adelante=72):
        cap = self.cap                                                # hora de captura de la cuota (v5.1)
        return {"fixtures": [
            {"fixture_id": 777, "fecha": (HOY + timedelta(hours=20)).isoformat(), "torneo": "Challenger Lima", "superficie": "clay",
             "genero": "M", "jugador1": "Perez J.", "jugador2": "Rossi L.", "odd1": 1.40, "odd2": 2.90, "actualizado_en": cap},
            {"fixture_id": 778, "fecha": (HOY + timedelta(hours=30)).isoformat(), "torneo": "WTA Beijing", "superficie": "hard",
             "genero": "F", "jugador1": "Alta A.", "jugador2": "Baja M.", "odd1": 1.30, "odd2": 3.40, "actualizado_en": cap},
            {"fixture_id": 779, "fecha": (HOY + timedelta(hours=40)).isoformat(), "torneo": "M25 Sevilla", "superficie": "clay",
             "genero": "M", "jugador1": "Itf P.", "jugador2": "Lowe T.", "odd1": 1.90, "odd2": 1.90, "actualizado_en": cap}]}

    def historial(self, desde, hasta=None):
        return {"partidos": []}

    def antecedentes(self, player_id, torneo):
        return {"partidos": []}

    def defensa(self):
        return {"jugadores": []}


def _gem(datos_por_nombre):
    """Clasificador falso: responde según el nombre del jugador que aparece en el prompt."""
    llamadas = {"n": 0, "nombres": []}

    def h(req):
        llamadas["n"] += 1
        cuerpo = json.loads(req.content)
        texto = json.dumps(cuerpo)
        datos = None
        for nombre, d in datos_por_nombre.items():
            if nombre in texto:
                datos, llamadas["nombres"] = d, llamadas["nombres"] + [nombre]
                break
        datos = datos or {"sobre_jugador": False, "confianza_identidad": 0.1, "categoria": "OTRA", "direccion": "NEUTRA",
                          "naturaleza": "NO_VERIFICADA", "fecha_evento": None, "resumen_es": "", "relevancia_deportiva": "",
                          "fragmento_original": "", "idioma": "en"}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(datos)}]}}],
                                         "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20}})
    return Gemini(api_key="g", transport=httpx.MockTransport(h)), llamadas


def _lesion(nombre, dias=0, nivel_nat="DECLARACION", cat="LESION_MOLESTIA"):
    return {"sobre_jugador": True, "confianza_identidad": 0.93, "categoria": cat, "direccion": "NEGATIVA",
            "naturaleza": nivel_nat, "fecha_evento": (HOY - timedelta(days=dias)).strftime("%Y-%m-%d"),
            "resumen_es": f"{nombre} declaró molestias en la muñeca derecha.", "relevancia_deportiva": "podría afectar el saque",
            "fragmento_original": "felt pain in his right wrist", "idioma": "en"}


def _tav(articulos_por_consulta):
    pedidos = []

    def h(req):
        c = json.loads(req.content)
        pedidos.append(c)
        arts = []
        for clave, lista in articulos_por_consulta.items():
            if clave in c["query"]:
                arts = lista
        return httpx.Response(200, json={"results": arts, "response_time": 0.3})
    return Tavily(api_key="tvly-test", transport=httpx.MockTransport(h)), pedidos


def _art(url, titulo, contenido, horas=1):
    return {"title": titulo, "url": url, "content": contenido, "score": 0.9,
            "published_date": (HOY - timedelta(hours=horas)).strftime("%a, %d %b %Y %H:%M:%S GMT")}


def _cfg(cfg, **k):
    c = dict(cfg, NEWS_ACTIVO=1, NEWS_IDIOMAS="en,es", NEWS_RADAR_TEMATICO_ACTIVO=0, NEWS_DISCORD_ACTIVO=1)
    c.update(k)
    return c


def _ciclo(conn, c, tav, gem, ahora=HOY, confirmar=True):
    """Un ciclo con la cuota capturada 3 h antes y, si `confirmar`, un segundo ciclo
    10 min después en el que RankingFTR confirma la misma cuota DESPUÉS de la noticia
    (v5.2: sin cuota posterior a la noticia no hay 🔥). Devuelve el primero."""
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    f1 = FTR()
    f1.cap = (ahora - timedelta(hours=3)).isoformat()
    r = tareas.ciclo(conn, cliente=f1, cfg=c, tavily=tav, gemini=gem, ahora=ahora)
    if confirmar:
        f2 = FTR()
        f2.cap = (ahora + timedelta(minutes=5)).isoformat()
        tareas.ciclo(conn, cliente=f2, cfg=c, tavily=tav, gemini=gem, ahora=ahora + timedelta(minutes=10))
    return r


# ── 📰 NOTICIA IMPORTANTE ─────────────────────────────────────────────────
def test_noticia_importante_sale_con_motivo_y_sin_partido(conn, cfg):
    """Una lesión externa nivel B de un jugador SIN partido programado llega a Discord
    como 📰 (Rubén: "no necesita que el jugador tenga un partido programado")."""
    c = _cfg(cfg)
    gem, ll = _gem({"Tom Lowe": _lesion("Tom Lowe")})
    tav, pedidos = _tav({"Tom Lowe": [_art("https://tennistourtalk.com/lowe-wrist", "Lowe injured", "Tom Lowe said he felt pain")]})
    # Lowe tiene partido en el fixture 779; lo sacamos para probar "sin partido"
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    jid = jg.buscar_por_nombre(conn, "Tom Lowe")["id"]
    jg.encolar(conn, jid, "SIN_PARTIDO", 24 * 7, "RANKING", 3, "itf", HOY)
    r = radar.correr(conn, c, tav, gem, HOY, 10)
    assert r["eventos"] == 1 and r["alertas"] == 1
    a = alertas.listar(conn)[0]
    assert a["tipo"] == "NOTICIA" and a["partido_id"] is None and a["rival"] is None and a["dicho_discord"] == 0
    assert a["motivo_seleccion"].startswith("noticia externa LESION_MOLESTIA nivel B (declaracion) de tennistourtalk.com")
    assert "sin partido programado" in a["motivo_seleccion"]
    t = a["texto_discord"]
    assert t.startswith("📰 FULLTENNIS · NOTICIA IMPORTANTE\n🎾 Tom Lowe\n🏆 Sin partido programado\n📊 UTR: 11.20\n🚨 LESIÓN: ")
    assert "🔴 PERJUDICA A: TOM LOWE" in t and "FAVORECER" not in t and "💰" not in t      # sin partido: no se inventa favorecido
    assert "%" not in t and "http" not in t                                               # sin enlaces: la fuente queda en la evidencia
    assert a["evidencia"]["evento"]["fuente"] == "tennistourtalk.com" and a["evidencia"]["evento"]["enlace"].startswith("https://")
    assert a["texto_voz"].startswith("Noticia importante. Lowe:")
    # el artículo quedó marcado y el jugador pasó a EVENTO_VIGENTE (se lo sigue sin partido)
    art = conn.execute("SELECT resultado, motivo, origen FROM news_articulo").fetchone()
    assert art["resultado"] == "EVENTO" and art["motivo"].startswith("LESION_MOLESTIA B DECLARACION") and art["origen"] == "radar"
    cola = conn.execute("SELECT situacion FROM news_jugador_cola WHERE jugador_id=?", (jid,)).fetchone()
    assert cola["situacion"] == "EVENTO_VIGENTE"
    # historial del evento: NUEVO
    ev = conn.execute("SELECT id, origen FROM news_evento").fetchone()
    assert ev["origen"] == "EXTERNO"
    assert [h["cambio"] for h in memoria.historial_cambios(conn, ev["id"])] == ["NUEVO"]
    # feed para FT Intelligence
    s = alertas.pendientes(conn, c)
    assert len(s) == 1 and s[0]["tipo_alerta"] == "NOTICIA" and s[0]["jugador_x"] == "Tom Lowe" and s[0]["rival"] is None


def test_noticia_no_se_repite_salvo_info_nueva_y_tope(conn, cfg):
    c = _cfg(cfg, NEWS_MAX_NOTICIA_DIA=2)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    j = jg.buscar_por_nombre(conn, "Tom Lowe")
    aid = conn.execute("INSERT INTO news_articulo (url, dominio, titulo, creado_en) VALUES ('https://tennistourtalk.com/a','tennistourtalk.com','t',?)",
                       (HOY.isoformat(),)).lastrowid

    def ev(nat="DECLARACION", nivel="B", dias=1):
        e = memoria.nuevo_evento(j["id"], "LESION_MOLESTIA", "NEGATIVA", nat, nivel, (HOY - timedelta(days=dias)).isoformat(),
                                 fuente="tennistourtalk.com", enlace="https://tennistourtalk.com/a", articulo_id=aid,
                                 resumen_es="molestias", confianza_identidad=0.95)
        memoria.guardar_evento_db(conn, e)
        return e
    r1 = alertas.noticia_importante(conn, c, ev(), j, HOY)
    assert r1["alerta_id"]
    r2 = alertas.noticia_importante(conn, c, ev(), j, HOY + timedelta(hours=1))
    assert r2["alerta_id"] is None and r2["motivo"].startswith("REPETIDA")
    # pasa de declaración a hecho → información nueva → sale
    r3 = alertas.noticia_importante(conn, c, ev(nat="HECHO"), j, HOY + timedelta(hours=2))
    assert r3["alerta_id"] and "pasa de declaración a hecho" in r3["motivo"]
    # tope diario (2)
    r4 = alertas.noticia_importante(conn, c, ev(nat="HECHO", nivel="A"), j, HOY + timedelta(hours=3))
    assert r4["motivo"] == "TOPE_DIARIO"
    # hecho viejo / nivel C / interno / categoría irrelevante
    assert alertas.noticia_importante(conn, c, ev(dias=20), j, HOY)["motivo"] == "HECHO_VIEJO"
    assert alertas.noticia_importante(conn, c, ev(nivel="C"), j, HOY)["motivo"] == "NIVEL_C"
    interno = memoria.nuevo_evento(j["id"], "CARGA_FISICA", "NEGATIVA", "HECHO", "A", HOY.isoformat(),
                                   fuente="rankingftr.interno", enlace="contexto:carga")
    assert alertas.noticia_importante(conn, c, interno, j, HOY)["motivo"] == "INTERNO"
    otra = memoria.nuevo_evento(j["id"], "ANTECEDENTE_TORNEO", "POSITIVA", "HECHO", "A", HOY.isoformat(),
                                fuente="tennistourtalk.com", enlace="https://x", articulo_id=aid)
    assert alertas.noticia_importante(conn, c, otra, j, HOY)["motivo"].startswith("CATEGORIA_NO_RELEVANTE")


# ── 🔎 PARTIDO INTERESANTE + rival a demanda ──────────────────────────────
def test_partido_interesante_investiga_al_rival_y_explica(conn, cfg):
    c = _cfg(cfg, NEWS_EXPERIMENTAL_ACTIVO=0)        # sin experimental: la lesión de Perez da 🔎
    gem, ll = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, pedidos = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    r = _ciclo(conn, c, tav, gem)
    assert r["pasos"]["radar"]["eventos"] == 1
    tipos = [a["tipo"] for a in alertas.listar(conn)]
    assert "NOTICIA" in tipos and "INTERESANTE" in tipos
    a = [a for a in alertas.listar(conn) if a["tipo"] == "INTERESANTE"][0]
    t = a["texto_discord"]
    assert t.startswith("🔎 FULLTENNIS · PARTIDO INTERESANTE\n🎾 Juan Perez vs Luca Rossi\n🏆 Challenger Lima\n📊 UTR: 12.90 vs 12.40\n💰 Cuotas: 1.40 vs 2.90\n🚨 NOTICIA: ")
    assert "🟢 PODRÍA FAVORECER A: LUCA ROSSI @2.90" in t and "%" not in t and "http" not in t
    assert t.rstrip().endswith("⚠️ Sin lectura de mercado validada.")      # NEWS_EXPERIMENTAL_ACTIVO=0 → BANDAS_NO_CALIBRADAS
    assert a["motivo_seleccion"].startswith("noticia externa LESION_MOLESTIA")   # el por qué queda en la evidencia, no en Discord
    # el rival fue investigado en el mismo ciclo (estaba en cola: ambos tienen partido)
    assert any("Luca Rossi" in p["query"] for p in pedidos)
    # el mismo partido no se repite sin eventos nuevos
    r2 = _ciclo(conn, c, tav, gem, HOY + timedelta(minutes=15))
    assert len([a for a in alertas.listar(conn) if a["tipo"] == "INTERESANTE"]) == 1
    ev = alertas.listar(conn)[0]["evidencia"]
    assert isinstance(ev, dict)


def test_contexto_interno_solo_no_da_interesante_ni_noticia(conn, cfg):
    """Un evento de carga calculado por nosotros no es noticia (Rubén §2)."""
    c = _cfg(cfg)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    j = jg.buscar_por_nombre(conn, "Juan Perez")
    e = memoria.nuevo_evento(j["id"], "CARGA_FISICA", "NEGATIVA", "HECHO", "A", HOY.isoformat(),
                             fuente="rankingftr.interno", enlace="contexto:carga", resumen_es="3 partidos largos")
    memoria.guardar_evento_db(conn, e)
    assert conn.execute("SELECT origen FROM news_evento").fetchone()["origen"] == "INTERNO"
    tav, _ = _tav({})
    gem, _ = _gem({})
    _ciclo(conn, c, tav, gem)
    assert alertas.listar(conn) == []
    # v7 (Rubén 10/10): el Motor 3 recalcula la carga de Perez → NORMAL → el evento
    # de carga "3 partidos largos" VENCE ("la carga volvió a normal") y, sin nada
    # más, no hay evaluación ni alerta. Si quedara vigente, seguiría siendo 🔎
    # SIN_NOTICIA_EXTERNA_FUERTE (test_descubridor lo cubre).
    e2 = conn.execute("SELECT estado FROM news_evento WHERE categoria='CARGA_FISICA'").fetchone()
    assert e2["estado"] == "VENCIDO"
    assert conn.execute("SELECT COUNT(*) FROM news_evaluacion WHERE tipo_alerta IN ('FUEGO','FUEGO_EXPERIMENTAL')").fetchone()[0] == 0


# ── 🔥 EXPERIMENTAL ───────────────────────────────────────────────────────
def test_fuego_experimental_con_evidencia_y_explicaciones(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    a = [a for a in alertas.listar(conn) if a["tipo"] == "FUEGO_EXPERIMENTAL"]
    assert len(a) == 1
    t = a[0]["texto_discord"]
    assert t.startswith("🔥 FULLTENNIS · POSIBLE VALOR EXPERIMENTAL\n🎾 Luca Rossi vs Juan Perez\n🏆 Challenger Lima\n📊 UTR: 12.40 vs 12.90\n🟢 JUGADOR FAVORECIDO: LUCA ROSSI\n💰 CUOTA: 2.90\n🚨 MOTIVO: ")
    assert "⚠️ Posible oportunidad sin validar estadísticamente." in t and "%" not in t and "http" not in t
    assert "EXPERIMENTAL (bandas sin validar)" in a[0]["motivo_seleccion"]
    s = alertas.pendientes(conn, c)
    assert {x["tipo_alerta"] for x in s} == {"NOTICIA", "FUEGO_EXPERIMENTAL"}
    # con NEWS_EXPERIMENTAL_ACTIVO=0 el feed no la entrega
    assert {x["tipo_alerta"] for x in alertas.pendientes(conn, dict(c, NEWS_EXPERIMENTAL_ACTIVO=0))} == {"NOTICIA"}
    # marcar dicha: espeja a la evaluación
    alertas.marcar_dichas(conn, [{"id": a[0]["id"], "dicho": True}])
    assert conn.execute("SELECT dicho_discord FROM news_evaluacion").fetchone()[0] == 1


# ── cola con cupo para circuitos menores ──────────────────────────────────
def test_cola_cupo_menores_e_itf_no_queda_al_final(conn, cfg):
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    ids = {n: jg.buscar_por_nombre(conn, n)["id"] for n in ("Juan Perez", "Luca Rossi", "Ana Alta", "Mia Baja", "Pedro Itf", "Tom Lowe")}
    for n in ("Juan Perez", "Luca Rossi", "Ana Alta", "Mia Baja"):
        jg.encolar(conn, ids[n], "PARTIDO_24H", 6, "PARTIDO_PROXIMO", 1, "atp", HOY)
    for n in ("Pedro Itf", "Tom Lowe"):
        jg.encolar(conn, ids[n], "PARTIDO_72H", 12, "PARTIDO_PROXIMO", 3, "itf", HOY)
    # sin cupo: los 4 ATP/WTA (score más alto) van primero y los ITF quedan afuera con límite 4
    sin = radar.pendientes(conn, HOY, 4, cupo_menores_pct=0)
    assert all(not f["menor"] for f in sin)
    con = radar.pendientes(conn, HOY, 4, cupo_menores_pct=40)
    assert sum(1 for f in con if f["menor"]) == 2 and len(con) == 4
    # a demanda (prioridad 0) sube al frente
    alertas.adelantar(conn, ids["Tom Lowe"], HOY, "RIVAL_A_DEMANDA")
    assert radar.pendientes(conn, HOY, 6)[0]["jugador_id"] == ids["Tom Lowe"]


# ── radar temático y RSS contra el padrón ─────────────────────────────────
def test_radar_tematico_cruza_padron_y_emite_noticia(conn, cfg):
    c = _cfg(cfg, NEWS_RADAR_TEMATICO_ACTIVO=1, NEWS_RADAR_TEMATICO_BUSQUEDAS=3)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    gem, ll = _gem({"Mia Baja": _lesion("Mia Baja", cat="ENFERMEDAD", nivel_nat="HECHO")})
    tav, pedidos = _tav({"injury": [
        _art("https://tennistourtalk.com/baja-ill", "Mia Baja withdraws ill", "Mia Baja has withdrawn from Beijing with illness"),
        _art("https://tennistourtalk.com/nadie", "Weather delays", "Rain delayed play in Beijing")]})
    r = radar.correr_tematico(conn, c, tav, gem, HOY)
    assert r["busquedas"] == 3 and all(p["days"] == 1 for p in pedidos)
    assert r["articulos_nuevos"] == 2 and r["coincidencias"] == 1 and r["eventos"] == 1 and r["alertas"] == 1
    assert ll["n"] == 1                                                  # solo se pagó IA por el que nombra a alguien
    arts = {a["url"]: a for a in (dict(x) for x in conn.execute("SELECT * FROM news_articulo"))}
    assert arts["https://tennistourtalk.com/nadie"]["resultado"] == "SIN_JUGADOR_DEL_PADRON"
    assert arts["https://tennistourtalk.com/baja-ill"]["resultado"] == "EVENTO" and arts["https://tennistourtalk.com/baja-ill"]["origen"] == "tematico"
    b = conn.execute("SELECT origen, jugador_id FROM news_busqueda").fetchone()
    assert b["origen"] == "tematico" and b["jugador_id"] is None
    a = alertas.listar(conn)[0]
    assert a["tipo"] == "NOTICIA" and "Mia Baja" in a["texto_discord"]
    # segunda corrida: las URLs ya vistas no se vuelven a pagar
    r2 = radar.correr_tematico(conn, c, tav, gem, HOY)
    assert r2["articulos_nuevos"] == 0 and ll["n"] == 1
    # dentro del ciclo con cadencia
    r3 = _ciclo(conn, c, tav, gem, HOY + timedelta(hours=1))
    assert r3["pasos"]["tematico"]["busquedas"] == 3
    r4 = _ciclo(conn, c, tav, gem, HOY + timedelta(hours=2))
    assert r4["pasos"]["tematico"] == "al día"


def test_rss_cruza_todo_el_padron_no_solo_la_cola(conn, cfg):
    c = _cfg(cfg)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())                                 # nadie en cola
    assert conn.execute("SELECT COUNT(*) FROM news_jugador_cola").fetchone()[0] == 0
    gem, ll = _gem({"Pedro Itf": _lesion("Pedro Itf", cat="RETIRO_ABANDONO", nivel_nat="HECHO")})
    xml = f"""<rss><channel><item><title>Pedro Itf retires in Sevilla</title><link>https://tennistourtalk.com/itf-ret</link>
    <description>Pedro Itf retired hurt in the second set</description><pubDate>{(HOY - timedelta(days=1)).strftime('%a, %d %b %Y 10:00:00 GMT')}</pubDate></item>
    <item><title>Li Na</title><link>https://tennistourtalk.com/x</link><description>short names</description></item></channel></rss>"""
    r = rss.correr(conn, c, gem, HOY, transport=httpx.MockTransport(lambda req: httpx.Response(200, text=xml)))
    assert r["coincidencias"] == 1 and r["eventos"] == 1 and r["alertas"] == 1
    assert conn.execute("SELECT origen FROM news_articulo WHERE url LIKE '%itf-ret'").fetchone()[0] == "rss"
    assert conn.execute("SELECT situacion FROM news_jugador_cola").fetchone()[0] == "EVENTO_VIGENTE"


def test_buscar_en_texto_exige_nombre_completo(conn):
    jg.upsert(conn, "Juan Perez", "M", "ARG", "atp")
    jg.upsert(conn, "Li Na", "F", "CHN", "wta")
    assert [j["nombre"] for j in jg.buscar_en_texto(conn, "Juan Pérez ganó en Lima")] == ["Juan Perez"]
    assert jg.buscar_en_texto(conn, "Perez ganó") == []
    assert jg.buscar_en_texto(conn, "Li Na is back") == []           # tokens cortos: no alcanza


# ── historial, vencimiento, desmentido y fusión de duplicados ─────────────
def test_historial_vencimiento_y_desmentido(conn, cfg):
    jid = jg.upsert(conn, "Juan Perez", "M", "ARG", "atp")
    e1 = memoria.nuevo_evento(jid, "LESION_MOLESTIA", "NEGATIVA", "DECLARACION", "B", (HOY - timedelta(days=10)).isoformat(),
                              fuente="tennistourtalk.com", enlace="https://x/1")
    memoria.guardar_evento_db(conn, e1)
    e2 = memoria.nuevo_evento(jid, "LESION_MOLESTIA", "NEGATIVA", "HECHO", "A", (HOY - timedelta(days=2)).isoformat(),
                              fuente="tennistourtalk.com", enlace="https://x/2")
    memoria.guardar_evento_db(conn, e2)
    assert [h["cambio"] for h in memoria.historial_cambios(conn, e1["id"])] == ["NUEVO", "SUPERADO"]
    assert memoria.cambiar_estado_db(conn, e2["id"], "DESMENTIDO", "la fuente se retractó", "ruben")
    assert conn.execute("SELECT estado FROM news_evento WHERE id=?", (e2["id"],)).fetchone()[0] == "DESMENTIDO"
    assert not memoria.cambiar_estado_db(conn, e2["id"], "DESMENTIDO")
    e3 = memoria.nuevo_evento(jid, "ENFERMEDAD", "NEGATIVA", "HECHO", "B", (HOY - timedelta(days=30)).isoformat(),
                              fuente="tennistourtalk.com", enlace="https://x/3")
    e3["vigente_hasta"] = (HOY - timedelta(days=1)).isoformat()
    memoria.guardar_evento_db(conn, e3)
    assert memoria.vencer_db(conn, HOY) == {"vencidos": 1}
    assert memoria.historial_cambios(conn, e3["id"])[-1]["cambio"] == "VENCIDO"


def test_fusion_de_duplicados_corre_una_vez_en_el_ciclo(conn, cfg):
    from ft_news import partidos
    c = _cfg(cfg)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    i1, i2 = jg.buscar_por_nombre(conn, "Juan Perez")["id"], jg.buscar_por_nombre(conn, "Luca Rossi")["id"]
    f = (HOY + timedelta(hours=20)).isoformat()
    for fid in (901, 902):
        conn.execute("INSERT INTO news_partido (fixture_id, jugador1_id, jugador2_id, torneo, fecha_estimada, circuito, genero, "
                     "cuota1, cuota2, estado, creado_en, actualizado_en) VALUES (?,?,?,?,?,?,?,?,?,'PROGRAMADO',?,?)",
                     (fid, i1 if fid == 901 else i2, i2 if fid == 901 else i1, "Challenger Lima", f, "challenger", "M",
                      1.4 if fid == 901 else 2.9, 2.9 if fid == 901 else 1.4, HOY.isoformat(), HOY.isoformat()))
    conn.commit()
    tav, _ = _tav({})
    gem, _ = _gem({})
    r = _ciclo(conn, c, tav, gem)
    assert r["pasos"]["fusion_duplicados"]["fusionados"] == 1
    assert conn.execute("SELECT COUNT(*) FROM news_partido WHERE estado='DUPLICADO'").fetchone()[0] == 1
    r2 = _ciclo(conn, c, tav, gem, HOY + timedelta(minutes=15))
    assert "fusion_duplicados" not in r2["pasos"]


# ── endpoints ─────────────────────────────────────────────────────────────
def test_endpoints_alertas_diagnostico_buscador(conn, cfg, monkeypatch):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")],
                   "Luca Rossi": [_art("https://tennistourtalk.com/rossi-nada", "Rossi fine", "Luca Rossi practiced")]})
    _ciclo(conn, c, tav, gem)
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", __import__("pathlib").Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    with TestClient(app) as t:
        h = {"X-FT-News-Secret": "secreto-pruebas"}
        t.post("/news/config", headers=h, json={"clave": "NEWS_DISCORD_ACTIVO", "valor": "1", "por": "t"})
        s = t.get("/news/senales", headers=h).json()["senales"]
        assert {x["tipo_alerta"] for x in s} == {"NOTICIA", "FUEGO_EXPERIMENTAL"}
        exp = [x for x in s if x["tipo_alerta"] == "FUEGO_EXPERIMENTAL"][0]
        assert exp["experimental"] is True and exp["clave"].startswith("FUEGO_EXPERIMENTAL:") and exp["partido_id"]
        al = t.get("/news/alertas", headers=h).json()
        assert len(al["alertas"]) == 3 and al["resumen"]["pendientes"] == {"NOTICIA": 1, "FUEGO_EXPERIMENTAL": 1}
        assert [a for a in al["alertas"] if a["tipo"] == "INTERESANTE"][0]["dicho_motivo"] == "SUPERADA_POR_FUEGO_EXPERIMENTAL"
        assert all(isinstance(a["evidencia"], dict) and a["motivo_seleccion"] for a in al["alertas"])
        d = t.get("/news/diagnostico", headers=h).json()
        assert d["busquedas"] and sum(b["n"] for b in d["busquedas"]) == 12           # 6 jugadores × (en, es)
        assert {a["resultado"] for a in d["articulos"]} == {"EVENTO", "OTRO_JUGADOR"}
        assert d["hoy"] == {"externos": 1, "internos": 0} and d["descartados"][0]["motivo"].startswith("identidad")
        assert any(p["proveedor"] == "tavily" for p in d["costos_por_proveedor"]) and d["partidos"]["unicos"] == 3
        assert any(b["circuito"] == "challenger" for b in d["busquedas_por_circuito"])
        j = t.get("/news/jugadores/buscar?q=perez", headers=h).json()["jugadores"]
        assert len(j) == 1 and j[0]["nombre"] == "Juan Perez" and j[0]["externos"] == 1 and j[0]["alertas"] == 3
        m = t.get(f"/news/jugadores/{j[0]['id']}/memoria", headers=h).json()
        assert m["jugador"]["utr_singles"] == 12.9 and m["eventos"][0]["origen"] == "EXTERNO"
        assert m["eventos"][0]["cambios"][0]["cambio"] == "NUEVO" and len(m["alertas"]) == 3 and m["partidos"] and m["busquedas"]
        hoy = t.get("/news/hoy", headers=h).json()
        assert hoy["eventos"][0]["origen"] == "EXTERNO" and hoy["alertas_resumen"]["pendientes"]["NOTICIA"] == 1
        est = t.get("/news/estado", headers=h).json()
        assert est["contadores"]["news_alerta"] == 3 and est["alertas"]["pendientes"]["NOTICIA"] == 1
        # DESMENTIR por revisión
        eid = conn.execute("SELECT id FROM news_evento").fetchone()[0]
        conn.execute("INSERT INTO news_revision (tipo, evento_id, jugador_id, detalle, creado_en) VALUES ('OTRA',?,?,'{}',?)",
                     (eid, j[0]["id"], HOY.isoformat()))
        conn.commit()
        rid = conn.execute("SELECT id FROM news_revision").fetchone()[0]
        assert t.post(f"/news/revision/{rid}", headers=h, json={"accion": "DESMENTIR", "por": "ruben"}).json() == {"ok": True}
        assert conn.execute("SELECT estado FROM news_evento WHERE id=?", (eid,)).fetchone()[0] == "DESMENTIDO"
        assert memoria.historial_cambios(conn, eid)[-1]["cambio"] == "DESMENTIDO"


def test_textos_experimental_e_interesante_sin_prohibidos():
    for tipo in ("FUEGO", "FUEGO_EXPERIMENTAL", "INTERESANTE", "NOTICIA"):
        assert tipo in textos.ENCABEZADOS
    assert "EXPERIMENTAL" in textos.ENCABEZADOS["FUEGO_EXPERIMENTAL"]
