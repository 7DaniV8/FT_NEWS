"""Motor 3 (contexto), Motor 5 (cierre), Excel, RSS, listas ITF (compuerta),
segunda lectura con Claude y cola de revisión. Sin red."""
import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from ft_news import cierre, config, contexto, excel, fuentes, memoria, tareas
from ft_news import jugadores as jg
from ft_news.app import app
from ft_news.lectores import itf_listas, rss
from ft_news.proveedores.claude import Claude, discrepa
from ft_news.proveedores.gemini import Gemini
from ft_news.proveedores.tavily import Tavily

HOY = datetime(2026, 10, 8, 15, tzinfo=timezone.utc)


def _h(dias, jugador, rival, score="6-4 6-4", torneo="Challenger Lima", pais="Peru"):
    return {"match_id": 1, "player_id": 10, "opponent_id": 11, "fecha": (HOY - timedelta(days=dias)).isoformat(),
            "nivel_torneo": "challenger", "superficie": "clay", "score": score, "games_ganados": 12, "games_perdidos": 8,
            "sets_ganados": 2, "sets_perdidos": 0 if score.count("-") == 2 else 1, "torneo": torneo, "jugador": jugador,
            "rival": rival, "pais_torneo": pais}


class FTR:
    """RankingFTR falso con historial, antecedentes y defensa."""
    llamadas = 0

    def __init__(self, historial=None, antecedentes=None, defensa=None, veredicto="CALIBRADAS_OK"):
        self._h, self._a, self._d, self.veredicto = historial or [], antecedentes or [], defensa or [], veredicto

    def utr_padron(self, desde_id=0, limite=2000):
        return {"jugadores": [
            {"player_id": 10, "nombre_ftr": "Juan Perez", "nombre_utr": "Juan Perez", "genero": "M", "nacionalidad": "PER",
             "utr_player_id": 501, "utr_singles": 12.9, "fecha_captura": (HOY - timedelta(days=3)).isoformat()},
            {"player_id": 11, "nombre_ftr": "Luca Rossi", "nombre_utr": "Luca Rossi", "genero": "M", "nacionalidad": "ITA",
             "utr_player_id": 502, "utr_singles": 12.4, "fecha_captura": (HOY - timedelta(days=3)).isoformat()}],
            "siguiente_desde_id": None}

    def fixtures(self, horas_adelante=72):
        return {"fixtures": [{"fixture_id": 777, "fecha": (HOY + timedelta(hours=20)).isoformat(), "torneo": "Challenger Lima",
                              "superficie": "clay", "genero": "M", "jugador1": "Perez J.", "jugador2": "Rossi L.",
                              "odd1": 1.40, "odd2": 2.90}]}

    def calibracion(self):
        return {"veredicto": self.veredicto, "muestra": 400, "razones": []}

    def historial(self, desde_fecha, hasta_fecha=None):
        self.llamadas += 1
        return {"partidos": self._h}

    def antecedentes(self, player_id, torneo):
        return {"partidos": self._a if player_id == 10 else []}

    def defensa(self):
        return {"jugadores": self._d}


def _sin_proveedores(conn, cfg):
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    return dict(cfg, NEWS_ACTIVO=1, NEWS_BANDAS_AUTO=1)


# ── Motor 3 ──────────────────────────────────────────────────────────────
def test_contexto_carga_viaje_localia_antecedentes_defensa(conn, cfg):
    c = _sin_proveedores(conn, cfg)
    hist = [_h(1, "Juan Perez", "X Uno", "6-4 3-6 7-5", "Challenger Bogota", "Colombia"),
            _h(2, "Juan Perez", "X Dos", "7-6 6-7 6-3", "Challenger Bogota", "Colombia"),
            _h(3, "Juan Perez", "X Tres", "6-2 4-6 6-4", "Challenger Bogota", "Colombia"),
            _h(4, "Juan Perez", "X Cuatro", "6-1 6-1", "Challenger Bogota", "Colombia"),
            _h(6, "Luca Rossi", "Y Uno", "6-3 6-3", "Challenger Lima", "Peru")]
    antec = [{"games_ganados": 12, "games_perdidos": 6}] * 4 + [{"games_ganados": 6, "games_perdidos": 12}]
    defensa = [{"nombre": "Luca Rossi", "dropping_points": 80, "current_points": 500, "defense_percentage": 0.16,
                "dropping_tournament_id": "lima", "participation_status": "juega"}]
    ftr = FTR(hist, antec, defensa)
    r = tareas.ciclo(conn, cliente=ftr, cfg=c, ahora=HOY)
    ctx = r["pasos"]["contexto"]
    assert ctx["partidos"] == 1 and ctx["historial"] == 5
    jp = jg.buscar_por_nombre(conn, "Juan Perez")
    lr = jg.buscar_por_nombre(conn, "Luca Rossi")
    cats_p = {e["categoria"]: e for e in memoria.historial_db(conn, jp["id"])}
    cats_r = {e["categoria"]: e for e in memoria.historial_db(conn, lr["id"])}
    # Perez: 4 partidos en 7 días, 3 de ellos a 3 sets → v7 (Rubén 10/10): es una semana NORMAL de competición,
    # NO deja evento de carga (antes sí); vino de Colombia hace 1 día → VIAJE; es peruano y juega en Perú → LOCALIA;
    # 4/5 ganados en Lima (80 %) → ANTECEDENTE positivo. Todo nivel A, fuente propia.
    assert {"VIAJE_CALENDARIO", "LOCALIA", "ANTECEDENTE_TORNEO"} <= set(cats_p) and "CARGA_FISICA" not in cats_p
    assert all(cats_p[k]["nivel"] == "A" and cats_p[k]["fuente"] == contexto.FUENTE for k in cats_p)
    assert cats_p["ANTECEDENTE_TORNEO"]["direccion"] == "POSITIVA" and "4/5" in cats_p["ANTECEDENTE_TORNEO"]["resumen_es"]
    # Rossi: solo defensa de puntos (16 % ≥ 12 %) → PUNTOS_DEFENDIDOS mixta, estimado
    assert set(cats_r) == {"PUNTOS_DEFENDIDOS"} and cats_r["PUNTOS_DEFENDIDOS"]["direccion"] == "MIXTA"
    assert "(estimado)" in cats_r["PUNTOS_DEFENDIDOS"]["resumen_es"]
    # news_contexto guarda cada dato con fuente; la carga declara duracion NULL
    carga = json.loads(conn.execute("SELECT valor_json FROM news_contexto WHERE jugador_id=? AND clave='CARGA'", (jp["id"],)).fetchone()[0])
    assert carga["partidos_7d"] == 4 and carga["tres_sets_7d"] == 3 and carga["duracion"] is None
    assert carga["clase"] == "NORMAL" and "No hay evidencia suficiente para considerarlo fatigado" in carga["texto"]
    # segunda pasada en la misma hora: no duplica eventos
    tareas.ciclo(conn, cliente=ftr, cfg=c, ahora=HOY + timedelta(minutes=15))
    assert len(memoria.historial_db(conn, jp["id"])) == 3
    # el descubridor con contexto: Perez (X) tiene VIAJE (negativa, débil) vs LOCALIA/ANTECEDENTE (positivas, débiles)
    e = conn.execute("SELECT * FROM news_evaluacion").fetchone()
    # v5: con contexto propio solamente (viaje, localía, antecedentes) NO hay 🔥: queda 🔎
    assert e["tipo_alerta"] == "INTERESANTE" and e["motivo"] == "SIN_NOTICIA_EXTERNA_FUERTE" and e["direccion_neta"] == "POSITIVA"
    # v7: la evaluación lleva su lectura simple y el texto es PARTIDO EN ANÁLISIS, sin códigos
    lectura = json.loads(e["lectura_json"])
    assert lectura["lineas"][0] == "🔎 FULLTENNIS · PARTIDO EN ANÁLISIS" and any(l.startswith("🧭 CONCLUSIÓN") for l in lectura["lineas"])
    assert "SIN_NOTICIA_EXTERNA_FUERTE" not in e["texto_discord"] and "🎾 Juan Perez vs Luca Rossi" in e["texto_discord"]


# ── Motor 5 ──────────────────────────────────────────────────────────────
def _noticia_externa_perez(conn, categoria="LESION_MOLESTIA", direccion="NEGATIVA"):
    """v5: una 🔥 exige una noticia EXTERNA fuerte; la carga calculada sola no alcanza."""
    from ft_news import memoria
    jp = conn.execute("SELECT id FROM news_jugador WHERE nombre='Juan Perez'").fetchone()
    aid = conn.execute("INSERT INTO news_articulo (url, dominio, titulo, creado_en) VALUES (?,?,?,?)",
                       (f"https://tennistourtalk.com/perez-{categoria.lower()}", "tennistourtalk.com", "t", HOY.isoformat())).lastrowid
    ev = memoria.nuevo_evento(jp["id"], categoria, direccion, "DECLARACION", "B", (HOY - timedelta(days=1)).isoformat(),
                              fuente="tennistourtalk.com", enlace="https://tennistourtalk.com/perez", articulo_id=aid,
                              resumen_es="Perez declaró molestias en la muñeca", confianza_identidad=0.95)
    memoria.guardar_evento_db(conn, ev)
    # v5.1: una 🔥 exige investigación RECIENTE de los dos (frescura por búsqueda, no por
    # eventos vigentes): acá se simula que el radar los buscó hace 1 h.
    for nombre in ("Juan Perez", "Luca Rossi"):
        j = conn.execute("SELECT id FROM news_jugador WHERE nombre=?", (nombre,)).fetchone()
        if j:
            conn.execute("INSERT INTO news_jugador_cola (jugador_id, prioridad, motivo, situacion, circuito, proxima_busqueda_en, "
                         "ultima_busqueda_en, actualizado_en) VALUES (?,1,'PARTIDO_PROXIMO','PARTIDO_24H','challenger',?,?,?) "
                         "ON CONFLICT(jugador_id) DO UPDATE SET ultima_busqueda_en=excluded.ultima_busqueda_en",
                         (j["id"], (HOY + timedelta(hours=5)).isoformat(), (HOY - timedelta(hours=1)).isoformat(), HOY.isoformat()))
    conn.commit()


def test_cierre_resultado_retiro_r4_y_marca(conn, cfg):
    c = _sin_proveedores(conn, cfg)
    ftr = FTR([_h(1, "Juan Perez", "X Uno", "6-4 3-6 7-5"), _h(2, "Juan Perez", "X Dos", "7-6 6-7 6-3"),
               _h(3, "Juan Perez", "X Tres", "6-2 4-6 6-4"), _h(4, "Juan Perez", "X Cuatro", "6-1 6-1")])
    tareas.ciclo(conn, cliente=ftr, cfg=c, ahora=HOY)
    _noticia_externa_perez(conn)                       # v5: hace falta la noticia externa
    tareas.ciclo(conn, cliente=ftr, cfg=c, ahora=HOY + timedelta(minutes=15))
    e = conn.execute("SELECT * FROM news_evaluacion").fetchone()
    assert e["tipo_alerta"] == "FUEGO" and e["cuota_x"] == 1.40
    # el partido se juega; el mercado subió la cuota de Perez (hacia la noticia negativa) y Rossi gana por retiro
    despues = HOY + timedelta(hours=24)
    ftr2 = FTR(ftr._h + [dict(_h(0, "Luca Rossi", "Juan Perez", "6-3 2-1 RET"), fecha=(HOY + timedelta(hours=21)).isoformat())])
    ftr2.fixtures = lambda horas_adelante=72: {"fixtures": [{"fixture_id": 777, "fecha": (HOY + timedelta(hours=20)).isoformat(),
                                                             "torneo": "Challenger Lima", "genero": "M", "jugador1": "Perez J.",
                                                             "jugador2": "Rossi L.", "odd1": 1.55, "odd2": 2.40}]}
    r = tareas.ciclo(conn, cliente=ftr2, cfg=c, ahora=despues)
    assert r["pasos"]["cierre"]["cerrados"] == 1 and r["pasos"]["cierre"]["retiros"] == 1
    res = conn.execute("SELECT * FROM news_resultado").fetchone()
    assert res["retiro"] == 1 and res["cuota_cierre_x"] == 1.55 and res["mercado_hacia_noticia"] == 1
    assert res["ganador_id"] == e["rival_id"]
    jp = jg.buscar_por_nombre(conn, "Juan Perez")
    cats = [h["categoria"] for h in memoria.historial_db(conn, jp["id"])]
    assert "RETIRO_ABANDONO" in cats                       # el retiro entró como dato propio nivel A
    assert conn.execute("SELECT estado FROM news_partido").fetchone()[0] == "JUGADO"
    # marca manual
    cierre.marcar_interesante(conn, e["id"], "SI", "ruben")
    assert conn.execute("SELECT era_interesante FROM news_resultado").fetchone()[0] == "SI"
    # Excel
    datos = excel.construir(conn)
    assert datos[:2] == b"PK" and len(datos) > 5000
    fs = excel.filas(conn)
    assert fs[0]["era_interesante"] == "SI" and fs[0]["gano_x"] == 0 and fs[0]["retiro"] == 1
    r = excel.resumen(fs)
    assert r["por_tipo"]["FUEGO"]["n"] == 1 and r["por_tipo"]["FUEGO"]["lado_noticia_acerto"] == 1.0


def test_cierre_sin_resultado_y_partido_completo_verifica(conn, cfg):
    c = _sin_proveedores(conn, cfg)
    ftr = FTR()
    tareas.ciclo(conn, cliente=ftr, cfg=c, ahora=HOY)
    jp = jg.buscar_por_nombre(conn, "Juan Perez")
    # lesión + regreso → estado físico sin verificar
    memoria.guardar_evento_db(conn, memoria.nuevo_evento(jp["id"], "LESION_MOLESTIA", "NEGATIVA", "HECHO", "A", (HOY - timedelta(days=20)).isoformat()))
    memoria.guardar_evento_db(conn, memoria.nuevo_evento(jp["id"], "REGRESO", "POSITIVA", "DECLARACION", "B", (HOY - timedelta(days=10)).isoformat()))
    tareas.ciclo(conn, cliente=ftr, cfg=c, ahora=HOY + timedelta(minutes=15))
    e = conn.execute("SELECT * FROM news_evaluacion").fetchone()
    assert e["motivo"] == "ESTADO_FISICO_SIN_VERIFICAR"
    # se juega completo y Perez gana → partidos_completos_desde=1 (todavía sin verificar: hacen falta 2)
    ftr2 = FTR([dict(_h(0, "Juan Perez", "Luca Rossi", "6-4 6-4"), fecha=(HOY + timedelta(hours=21)).isoformat())])
    r = tareas.ciclo(conn, cliente=ftr2, cfg=c, ahora=HOY + timedelta(hours=24))
    assert r["pasos"]["cierre"]["cerrados"] == 1
    hist = memoria.historial_db(conn, jp["id"])
    les = next(h for h in hist if h["categoria"] == "LESION_MOLESTIA")
    assert les["partidos_completos_desde"] == 1 and les["verificar_estado_fisico"] == 1 and les["estado"] == "EN_SEGUIMIENTO"
    # sin resultado en 4 días → SIN_RESULTADO
    conn.execute("DELETE FROM news_resultado"); conn.execute("UPDATE news_partido SET estado='PROGRAMADO'"); conn.commit()
    r = tareas.ciclo(conn, cliente=FTR(), cfg=c, ahora=HOY + timedelta(days=5))
    assert r["pasos"]["cierre"]["sin_resultado"] == 1


# ── RSS ──────────────────────────────────────────────────────────────────
RSS_XML = """<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>Juan Perez withdraws from Lima with wrist injury</title><link>https://tennistourtalk.com/perez-wd</link>
<description><![CDATA[<p>Juan Perez, the Peruvian, has <b>withdrawn</b>...</p>]]></description>
<pubDate>Wed, 07 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Nadie Conocido wins</title><link>https://tennistourtalk.com/otro</link><description>x</description>
<pubDate>Wed, 07 Oct 2026 11:00:00 GMT</pubDate></item></channel></rss>"""


def test_rss_parsea_y_solo_clasifica_coincidencias(conn, cfg):
    arts = rss.parsear(RSS_XML, "tennistourtalk.com")
    assert len(arts) == 2 and arts[0]["fecha_publicacion"].startswith("2026-10-07") and "<" not in arts[0]["contenido"]
    c = _sin_proveedores(conn, cfg)
    tareas.ciclo(conn, cliente=FTR(), cfg=c, ahora=HOY)           # jugadores en cola
    llamadas = {"gemini": 0}

    def gem_h(req):
        llamadas["gemini"] += 1
        d = {"sobre_jugador": True, "confianza_identidad": 0.95, "categoria": "RETIRO_ABANDONO", "direccion": "NEGATIVA",
             "naturaleza": "HECHO", "fecha_evento": "2026-10-07", "resumen_es": "Perez se retiró de Lima por la muñeca",
             "relevancia_deportiva": "no juega", "fragmento_original": "has withdrawn", "idioma": "en"}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(d)}]}}],
                                         "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})
    gem = Gemini(api_key="g", transport=httpx.MockTransport(gem_h))
    pedidos = []

    def rss_h(req):
        pedidos.append(str(req.url))
        return httpx.Response(200, text=RSS_XML)
    r = rss.correr(conn, c, gem, HOY, transport=httpx.MockTransport(rss_h))
    # solo el feed autorizado se pidió; 2 artículos, 1 coincide con un jugador de la cola → 1 llamada a Gemini → 1 evento
    assert pedidos == ["https://tennistourtalk.com/feed/"] and r["feeds"] == 1
    assert r["nuevos"] == 2 and r["coincidencias"] == 1 and r["eventos"] == 1 and llamadas["gemini"] == 1
    # segunda corrida: nada nuevo
    r2 = rss.correr(conn, c, gem, HOY, transport=httpx.MockTransport(rss_h))
    assert r2["nuevos"] == 0 and llamadas["gemini"] == 1


# ── ITF listas (compuerta) ───────────────────────────────────────────────
def test_itf_listas_detras_de_la_compuerta(conn, cfg):
    texto = "ACCEPTANCE LIST\nWD  PEREZ, Juan (PER)  ATP 210\nALT ROSSI, Luca (ITA) 300\nWC  GOMEZ, Ana (COL)\n"
    b = itf_listas.extraer_bajas(texto)
    assert [(x["marca"], x["nombre"], x["pais"]) for x in b] == [("WD", "Juan Perez", "PER"), ("ALT", "Luca Rossi", "ITA"), ("WC", "Ana Gomez", "COL")]
    fuentes.sembrar(conn, iniciales=[])
    jg.upsert(conn, "Juan Perez", "M", "PER", "itf")
    r = itf_listas.leer(conn, cfg, "https://www.itftennis.com/x.pdf", "M25 Lima", descargar=lambda u: texto)
    assert r["ok"] is False and "no está autorizada" in r["motivo"]
    assert conn.execute("SELECT COUNT(*) FROM news_evento").fetchone()[0] == 0
    # si Rubén autoriza (D-ITF), la WD entra como RETIRO_ABANDONO nivel A
    fuentes.autorizar(conn, "itftennis.com", True, "REVISADO_OK", "D-ITF: PDFs públicos 1/día", "ruben")
    r = itf_listas.leer(conn, cfg, "https://www.itftennis.com/x.pdf", "M25 Lima", descargar=lambda u: texto)
    assert r["ok"] and r["bajas"] == 1
    ev = conn.execute("SELECT * FROM news_evento").fetchone()
    assert ev["categoria"] == "RETIRO_ABANDONO" and ev["nivel"] == "A" and ev["fuente"] == "itftennis.com"


# ── Segunda lectura con Claude ───────────────────────────────────────────
def test_segunda_lectura_discrepante_baja_a_c(conn, cfg):
    from ft_news import radar
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jid = jg.upsert(conn, "Juan Perez", "M", "PER", "challenger")
    jugador = {"jugador_id": jid, "nombre": "Juan Perez", "pais": "PER", "genero": "M", "circuito": "challenger"}
    g1 = {"sobre_jugador": True, "confianza_identidad": 0.95, "categoria": "LESION_MOLESTIA", "direccion": "NEGATIVA",
          "naturaleza": "DECLARACION", "fecha_evento": "2026-10-07", "resumen_es": "molestias", "relevancia_deportiva": "x",
          "fragmento_original": "y", "idioma": "en"}
    gem = Gemini(api_key="g", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "candidates": [{"content": {"parts": [{"text": json.dumps(g1)}]}}], "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})))
    pedidos = []

    def cl_h(req):
        pedidos.append(json.loads(req.content))
        assert req.headers["x-api-key"] == "k" and req.headers["anthropic-version"]
        d2 = dict(g1, categoria="REGRESO", direccion="MIXTA")
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(d2)}],
                                         "usage": {"input_tokens": 900, "output_tokens": 100}})
    cl = Claude(api_key="k", transport=httpx.MockTransport(cl_h))
    art = {"url": "https://tennistourtalk.com/a", "dominio": "tennistourtalk.com", "titulo": "t", "contenido": "c",
           "fecha_publicacion": "2026-10-07"}
    aid = radar._articulo_nuevo(conn, art)
    r = radar.procesar_articulo(conn, cfg, gem, jugador, art, aid, HOY, claude=cl)
    ev = conn.execute("SELECT * FROM news_evento WHERE id=?", (r["evento_id"],)).fetchone()
    assert ev["nivel"] == "C" and json.loads(ev["lectura2_json"])["categoria"] == "REGRESO"
    assert pedidos[0]["model"] == "claude-haiku-5-5" and cl.llamadas == 1
    assert discrepa(g1, dict(g1)) is False and discrepa(g1, dict(g1, fecha_evento="2026-09-01")) is True
    # una categoría débil no gasta segunda lectura
    art2 = dict(art, url="https://tennistourtalk.com/b")
    g1["categoria"] = "LOCALIA"; g1["direccion"] = "POSITIVA"
    radar.procesar_articulo(conn, cfg, gem, jugador, art2, radar._articulo_nuevo(conn, art2), HOY, claude=cl)
    assert cl.llamadas == 1
    assert conn.execute("SELECT usd_estimado FROM news_costos_dia WHERE proveedor='claude'").fetchone()[0] > 0


# ── API: revisión, interesante, excel ────────────────────────────────────
def test_api_revision_interesante_excel(conn, cfg, monkeypatch):
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", __import__("pathlib").Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    c = _sin_proveedores(conn, cfg)
    tareas.ciclo(conn, cliente=FTR(), cfg=c, ahora=HOY)
    jp = jg.buscar_por_nombre(conn, "Juan Perez")
    ev = memoria.nuevo_evento(jp["id"], "OTRA", "NEUTRA", "INTERPRETACION", "C", HOY.isoformat(), resumen_es="algo raro")
    eid = memoria.guardar_evento_db(conn, ev)
    conn.execute("INSERT INTO news_revision (tipo, evento_id, jugador_id, detalle, creado_en) VALUES ('OTRA',?,?,'{}','x')", (eid, jp["id"]))
    conn.commit()
    with TestClient(app) as t:
        h = {"X-FT-News-Secret": "secreto-pruebas"}
        rv = t.get("/news/revision", headers=h).json()["revision"]
        assert len(rv) == 1 and rv[0]["jugador"] == "Juan Perez" and rv[0]["categoria"] == "OTRA"
        assert t.post(f"/news/revision/{rv[0]['id']}", headers=h, json={"accion": "CATEGORIA", "categoria": "INVENTADA"}).status_code == 400
        r = t.post(f"/news/revision/{rv[0]['id']}", headers=h, json={"accion": "CATEGORIA", "categoria": "SITUACION_PERSONAL", "por": "daniel"})
        assert r.status_code == 200
        assert conn.execute("SELECT categoria FROM news_evento WHERE id=?", (eid,)).fetchone()[0] == "SITUACION_PERSONAL"
        assert t.get("/news/revision", headers=h).json()["revision"] == []
        e = conn.execute("SELECT id FROM news_evaluacion").fetchone()
        if e:
            assert t.post(f"/news/evaluaciones/{e[0]}/interesante", headers=h, json={"valor": "NO", "por": "ruben"}).status_code == 200
            assert t.post(f"/news/evaluaciones/{e[0]}/interesante", headers=h, json={"valor": "X"}).status_code == 400
        x = t.get("/news/excel", headers=h)
        assert x.status_code == 200 and x.content[:2] == b"PK" and "xlsx" in x.headers["content-disposition"]
        hoy = t.get("/news/hoy", headers=h).json()
        assert "era_interesante" in (hoy["evaluaciones"][0] if hoy["evaluaciones"] else {"era_interesante": None})


def test_dashboard_discord(conn, cfg, monkeypatch):
    """Dashboard: solo las 🔥 dichas; el pick es el lado de la noticia."""
    from ft_news import dashboard
    c = _sin_proveedores(conn, cfg)
    ftr = FTR([_h(1, "Juan Perez", "X Uno", "6-4 3-6 7-5"), _h(2, "Juan Perez", "X Dos", "7-6 6-7 6-3"),
               _h(3, "Juan Perez", "X Tres", "6-2 4-6 6-4"), _h(4, "Juan Perez", "X Cuatro", "6-1 6-1")])
    tareas.ciclo(conn, cliente=ftr, cfg=c, ahora=HOY)
    _noticia_externa_perez(conn)                       # v5: hace falta la noticia externa
    tareas.ciclo(conn, cliente=ftr, cfg=c, ahora=HOY + timedelta(minutes=15))
    e = conn.execute("SELECT * FROM news_evaluacion").fetchone()
    assert e["tipo_alerta"] == "FUEGO" and e["direccion_neta"] == "NEGATIVA"
    assert dashboard.armar(conn)["kpis"]["total"] == 0                      # todavía no se dijo
    conn.execute("UPDATE news_evaluacion SET dicho_discord=1, dicho_en=? WHERE id=?", (HOY.isoformat(), e["id"])); conn.commit()
    d = dashboard.armar(conn)
    assert d["kpis"]["total"] == 1 and d["kpis"]["pendientes"] == 1
    assert d["historial"][0]["seleccion"] == "Luca Rossi" and d["historial"][0]["cuota"] == 2.90   # contra Perez → el rival
    # Rossi gana → ganado, +1.90 u
    conn.execute("INSERT INTO news_resultado (evaluacion_id, ganador_id, retiro, score, cerrado_en) VALUES (?,?,0,'6-4 6-4',?)",
                 (e["id"], e["rival_id"], HOY.isoformat())); conn.commit()
    d = dashboard.armar(conn)
    k = d["kpis"]
    assert k["ganadas"] == 1 and k["unidades"] == 1.9 and k["hit_rate"] == 100.0 and k["roi"] == 190.0
    assert d["historial"][0]["unidades"] == 1.9 and "negativa para Juan Perez" in d["historial"][0]["detalle"]
    assert dashboard.armar(conn, genero="F")["kpis"]["total"] == 0
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", __import__("pathlib").Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    with TestClient(app) as t:
        r = t.get("/news/dashboard", headers={"X-FT-News-Secret": "secreto-pruebas"}).json()
        assert r["kpis"]["ganadas"] == 1 and r["vista"] == "discord"
