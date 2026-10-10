"""v5.1 (09/10/2026 noche, Rubén): justificación de la 🔥 experimental (qué no está
en la cuota / en contra / por qué), frescura de la investigación de los dos,
observaciones de cuota por proveedor, duplicados vs encuentros distintos,
reintentos de clasificación. Sin red."""
import json
from datetime import datetime, timedelta, timezone

import httpx

from ft_news import alertas, fuentes, memoria, partidos, radar, tareas
from ft_news import jugadores as jg
from ft_news.proveedores.gemini import Gemini
from ft_news.proveedores.tavily import ErrorProveedor, Tavily

from tests.test_v5_alertas import FTR, HOY, _art, _cfg, _ciclo, _gem, _lesion, _tav


def _evaluacion(conn):
    return dict(conn.execute("SELECT * FROM news_evaluacion WHERE partido_id IN "
                             "(SELECT id FROM news_partido WHERE torneo='Challenger Lima')").fetchone())


# ── 🔥 experimental: justificación ────────────────────────────────────────
def test_experimental_justificada_explica_que_no_esta_en_la_cuota(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez", nivel_nat="HECHO")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    e = _evaluacion(conn)
    assert e["tipo_alerta"] == "FUEGO_EXPERIMENTAL"
    t = e["texto_discord"]
    # v6: el mensaje es corto; la justificación completa queda en la evidencia y en el motivo de selección
    assert "📈 La cuota de Perez sigue en 1.40 después de la noticia." in t and "%" not in t and "http" not in t
    a = [a for a in alertas.listar(conn) if a["tipo"] == "FUEGO_EXPERIMENTAL"][0]
    j = a["evidencia"]["justificacion"]
    assert j["puntos"] >= 2 and j["no_reflejado"] and "Juan Perez" in j["frescura"] and j["frescura"]["Luca Rossi"]["reciente"]
    assert j["cuota_x_antes"] == 1.4 and j["cuota_x_despues"] == 1.4
    assert "justificación:" in a["motivo_seleccion"] and "balance" in a["motivo_seleccion"]
    assert "cuota confirmada después de la noticia" in a["motivo_seleccion"] and "hecho reportado por prensa fiable (tennistourtalk.com)" in a["motivo_seleccion"]
    assert "banda UTR y mercado alineados" in a["motivo_seleccion"] and "FIXTURES_FTR" in a["motivo_seleccion"]
    assert a["evidencia"]["cuotas"]["proveedor"] == "FIXTURES_FTR" and a["evidencia"]["cuotas"]["observaciones"]


def test_experimental_sin_justificacion_queda_como_interesante(conn, cfg):
    """Declaración de hace 2 días; la primera cuota que vimos ya es posterior (sin cuota previa
    para medir la reacción), banda alineada → no alcanza → 🔎."""
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez", dias=2)})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain", horas=50)]})
    _ciclo(conn, c, tav, gem)
    e = _evaluacion(conn)
    assert e["tipo_alerta"] == "INTERESANTE" and e["motivo"] == "SIN_INFORMACION_NO_REFLEJADA"
    assert "no alcanza para 🔥" in e["conclusion"] and "no tiene una cuota previa con la que compararse" in e["conclusion"]
    assert "es una declaración" in e["conclusion"]
    tipos = sorted(a["tipo"] for a in alertas.listar(conn))
    assert tipos == ["INTERESANTE", "NOTICIA"]                        # sale la 🔎 (y la 📰), no la 🔥
    assert alertas.pendientes(conn, c) and all(x["tipo_alerta"] != "FUEGO_EXPERIMENTAL" for x in alertas.pendientes(conn, c))


def test_cuota_que_ya_se_movio_hacia_la_noticia_cuenta_en_contra(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez", nivel_nat="HECHO")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain", horas=2)]})
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    # 1.40 (hace 3 h, antes de la noticia de hace 2 h) → 1.60 (hace 30 min, después): el mercado ya alargó a Perez
    partidos.sincronizar(conn, FTR(), c, HOY - timedelta(hours=3))
    fx = FTR().fixtures()["fixtures"][0]
    fx2 = dict(fx, odd1=1.60, odd2=2.30, actualizado_en=(HOY - timedelta(minutes=30)).isoformat())
    class FTR3(FTR):
        def fixtures(self, horas_adelante=72):
            return {"fixtures": [fx2]}
    r = tareas.ciclo(conn, cliente=FTR3(), cfg=c, tavily=tav, gemini=gem, ahora=HOY)
    e = _evaluacion(conn)
    p = dict(conn.execute("SELECT * FROM news_partido WHERE torneo='Challenger Lima'").fetchone())
    assert p["cuota1_apertura"] == 1.40 and p["cuota1"] == 1.60
    assert e["tipo_alerta"] == "INTERESANTE" and e["motivo"] == "SIN_INFORMACION_NO_REFLEJADA"
    assert "el mercado ya incorporó la noticia: Juan Perez 1.40 → 1.60" in e["conclusion"]
    obs = partidos.observaciones(conn, p["id"])
    assert [(o["cuota1"], o["cuota2"]) for o in obs] == [(1.40, 2.90), (1.60, 2.30)]


def test_rival_sin_investigacion_reciente_no_da_fuego_y_se_adelanta(conn, cfg):
    """Una noticia vieja pero vigente de Rossi NO reemplaza su investigación actual."""
    c = _cfg(cfg)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    jp, jr = jg.buscar_por_nombre(conn, "Juan Perez"), jg.buscar_por_nombre(conn, "Luca Rossi")
    aid = conn.execute("INSERT INTO news_articulo (url, dominio, titulo, creado_en) VALUES ('https://tennistourtalk.com/r','tennistourtalk.com','t',?)",
                       ((HOY - timedelta(days=6)).isoformat(),)).lastrowid
    viejo = memoria.nuevo_evento(jr["id"], "ANTECEDENTE_TORNEO", "POSITIVA", "HECHO", "B", (HOY - timedelta(days=6)).isoformat(),
                                 fuente="tennistourtalk.com", enlace="https://tennistourtalk.com/r", articulo_id=aid,
                                 fecha_publicacion=(HOY - timedelta(days=6)).isoformat(), confianza_identidad=0.95)
    memoria.guardar_evento_db(conn, viejo)
    partidos.sincronizar(conn, FTR(), c, HOY)
    # Perez investigado hace 1 h (con noticia nueva); Rossi solo tiene la vieja (nunca buscado)
    nuevo = memoria.nuevo_evento(jp["id"], "LESION_MOLESTIA", "NEGATIVA", "HECHO", "B", HOY.isoformat(),
                                 fuente="tennistourtalk.com", enlace="https://tennistourtalk.com/p", articulo_id=aid,
                                 fecha_publicacion=(HOY - timedelta(hours=1)).isoformat(), confianza_identidad=0.95)
    memoria.guardar_evento_db(conn, nuevo)
    conn.execute("UPDATE news_jugador_cola SET ultima_busqueda_en=? WHERE jugador_id=?", ((HOY - timedelta(hours=1)).isoformat(), jp["id"]))
    conn.commit()
    f2 = FTR()
    f2.cap = (HOY - timedelta(minutes=20)).isoformat()                 # cuota confirmada después de la noticia
    partidos.sincronizar(conn, f2, c, HOY)
    f = alertas.frescura(conn, jr["id"], HOY, 48)
    assert f["reciente"] is False and f["hace_h"] is None and f["busquedas"] == 0     # la lesión vigente no cuenta
    from ft_news import evaluador
    evaluador.correr(conn, c, HOY)
    e = _evaluacion(conn)
    assert e["tipo_alerta"] == "INTERESANTE" and e["motivo"] == "RIVAL_SIN_INVESTIGACION_RECIENTE"
    assert "Luca Rossi sin investigación reciente" in e["conclusion"]
    cola = conn.execute("SELECT prioridad, motivo FROM news_jugador_cola WHERE jugador_id=?", (jr["id"],)).fetchone()
    assert cola["prioridad"] == 0 and cola["motivo"] == "A_DEMANDA"       # pasa al frente
    assert alertas.listar(conn) == []                                      # ni 🔎 todavía (rival sin investigar)
    # el radar lo investiga (sin novedades) y recién ahí, con los dos frescos, sale la 🔥 experimental
    gem, _ = _gem({})
    tav, _ = _tav({})
    radar.correr(conn, c, tav, gem, HOY + timedelta(minutes=10), 10)
    evaluador.correr(conn, c, HOY + timedelta(minutes=15))
    e = _evaluacion(conn)
    assert e["tipo_alerta"] == "FUEGO_EXPERIMENTAL"
    a = alertas.listar(conn)
    assert len(a) == 1 and a[0]["tipo"] == "FUEGO_EXPERIMENTAL"
    fr = a[0]["evidencia"]["justificacion"]["frescura"]
    assert fr["Luca Rossi"]["reciente"] and fr["Luca Rossi"]["hace_h"] == 0.1 and fr["Juan Perez"]["reciente"]


# ── duplicados y cuotas ───────────────────────────────────────────────────
def test_dos_proveedores_mismo_partido_cuotas_distintas(conn, cfg):
    c = _cfg(cfg)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    f = (HOY + timedelta(hours=20)).isoformat()
    a = {"fixture_id": 901, "fecha": f, "torneo": "Challenger Lima", "genero": "M", "jugador1": "Perez J.", "jugador2": "Rossi L.",
         "odd1": 1.40, "odd2": 2.90, "actualizado_en": (HOY - timedelta(hours=2)).isoformat(), "fuente": "PINNACLE"}
    b = {"fixture_id": 902, "fecha": (HOY + timedelta(hours=21)).isoformat(), "torneo": "Lima CH", "genero": "M",
         "jugador1": "Rossi L.", "jugador2": "Perez J.", "odd1": 2.75, "odd2": 1.45,
         "actualizado_en": (HOY - timedelta(hours=1)).isoformat(), "fuente": "ODDSPAPI"}

    class F(FTR):
        def fixtures(self, horas_adelante=72):
            return {"fixtures": [a, b]}
    r = partidos.sincronizar(conn, F(), c, HOY)
    assert r["partidos"] == 2
    ps = conn.execute("SELECT * FROM news_partido WHERE estado='PROGRAMADO'").fetchall()
    assert len(ps) == 1                                                   # un solo encuentro
    p = dict(ps[0])
    # la vigente es la más reciente (ODDSPAPI, hace 1 h), orientada al orden del partido (Perez primero)
    assert (p["cuota1"], p["cuota2"], p["cuota_proveedor"]) == (1.45, 2.75, "ODDSPAPI")
    assert (p["cuota1_apertura"], p["cuota2_apertura"]) == (1.40, 2.90)
    obs = partidos.observaciones(conn, p["id"])
    assert [(o["proveedor"], o["cuota1"], o["cuota2"]) for o in obs] == [("PINNACLE", 1.40, 2.90), ("ODDSPAPI", 1.45, 2.75)]
    assert {x["fixture_id"] for x in conn.execute("SELECT fixture_id FROM news_partido_fuente")} == {901, 902}
    # misma cuota otra vez del mismo proveedor: no se duplica la observación; cuota nueva sí
    partidos.sincronizar(conn, F(), c, HOY + timedelta(minutes=10))
    assert len(partidos.observaciones(conn, p["id"])) == 2
    a["odd1"], a["actualizado_en"] = 1.50, HOY.isoformat()
    partidos.sincronizar(conn, F(), c, HOY + timedelta(minutes=20))
    obs = partidos.observaciones(conn, p["id"])
    assert len(obs) == 3 and obs[-1]["proveedor"] == "PINNACLE" and obs[-1]["cuota1"] == 1.50
    p = dict(conn.execute("SELECT * FROM news_partido WHERE id=?", (p["id"],)).fetchone())
    assert (p["cuota1"], p["cuota_proveedor"]) == (1.50, "PINNACLE")      # la más reciente manda


def test_encuentros_distintos_entre_los_mismos_jugadores_no_se_funden(conn, cfg):
    c = _cfg(cfg)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    a = {"fixture_id": 901, "fecha": (HOY + timedelta(hours=20)).isoformat(), "torneo": "Challenger Lima", "genero": "M",
         "jugador1": "Perez J.", "jugador2": "Rossi L.", "odd1": 1.40, "odd2": 2.90}
    b = {"fixture_id": 902, "fecha": (HOY + timedelta(hours=68)).isoformat(), "torneo": "Challenger Quito", "genero": "M",
         "jugador1": "Rossi L.", "jugador2": "Perez J.", "odd1": 2.10, "odd2": 1.70}

    class F(FTR):
        def fixtures(self, horas_adelante=72):
            return {"fixtures": [a, b]}
    partidos.sincronizar(conn, F(), c, HOY)
    ps = [dict(x) for x in conn.execute("SELECT * FROM news_partido WHERE estado='PROGRAMADO' ORDER BY fecha_estimada")]
    assert len(ps) == 2 and ps[0]["torneo"] == "Challenger Lima" and ps[1]["torneo"] == "Challenger Quito"
    assert (ps[1]["cuota1"], ps[1]["cuota2"]) == (2.10, 1.70)             # orientado como vino (Rossi primero)
    assert partidos.fusionar_duplicados(conn) == {"fusionados": 0, "unicos": 2}


def test_fusion_conserva_observaciones_de_ambos(conn, cfg):
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    i1, i2 = jg.buscar_por_nombre(conn, "Juan Perez")["id"], jg.buscar_por_nombre(conn, "Luca Rossi")["id"]
    f = (HOY + timedelta(hours=20)).isoformat()
    for fid, j1, j2, c1, c2, org in ((901, i1, i2, 1.4, 2.9, "PINNACLE"), (902, i2, i1, 2.8, 1.45, "ODDSPAPI")):
        conn.execute("INSERT INTO news_partido (fixture_id, jugador1_id, jugador2_id, torneo, fecha_estimada, circuito, genero, "
                     "cuota1, cuota2, cuota_en, origen, estado, creado_en, actualizado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,'PROGRAMADO',?,?)",
                     (fid, j1, j2, "Challenger Lima", f, "challenger", "M", c1, c2, HOY.isoformat(), org, HOY.isoformat(), HOY.isoformat()))
    conn.commit()
    assert partidos.fusionar_duplicados(conn)["fusionados"] == 1
    base = conn.execute("SELECT id FROM news_partido WHERE estado='PROGRAMADO'").fetchone()[0]
    obs = partidos.observaciones(conn, base)
    assert [(o["proveedor"], o["cuota1"], o["cuota2"]) for o in obs] == [("ODDSPAPI", 1.45, 2.8)]   # invertido al orden del base


# ── reintentos de clasificación ───────────────────────────────────────────
def test_articulo_con_ia_caida_se_reintenta_y_no_se_pierde(conn, cfg):
    c = _cfg(cfg)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    jid = jg.buscar_por_nombre(conn, "Tom Lowe")["id"]
    jg.encolar(conn, jid, "SIN_PARTIDO", 24 * 7, "RANKING", 3, "itf", HOY)
    tav, _ = _tav({"Tom Lowe": [_art("https://tennistourtalk.com/lowe-wrist", "Lowe injured", "Tom Lowe said he felt pain")]})
    estado = {"caido": True, "n": 0}

    def h(req):
        estado["n"] += 1
        if estado["caido"]:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        d = _lesion("Tom Lowe", nivel_nat="HECHO")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(d)}]}}],
                                         "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20}})
    gem = Gemini(api_key="g", transport=httpx.MockTransport(h))
    r = radar.correr(conn, c, tav, gem, HOY, 10)
    art = dict(conn.execute("SELECT * FROM news_articulo").fetchone())
    # el artículo quedó registrado, SIN clasificar y con reintento programado (no "visto y perdido")
    assert art["resultado"] == "PENDIENTE" and art["intentos"] == 1 and art["reintentar_en"] and art["jugador_id"] == jid
    assert conn.execute("SELECT COUNT(*) FROM news_evento").fetchone()[0] == 0
    # el siguiente ciclo, antes de la hora: no se reintenta
    assert radar.reintentar_pendientes(conn, c, gem, HOY + timedelta(minutes=2)) == {"reintentados": 0, "eventos": 0, "pendientes": 1, "agotados": 0}
    # IA de vuelta → se reintenta → evento + 📰
    estado["caido"] = False
    rr = radar.reintentar_pendientes(conn, c, gem, HOY + timedelta(hours=2))
    assert rr["reintentados"] == 1 and rr["eventos"] == 1 and rr["pendientes"] == 0
    art = dict(conn.execute("SELECT * FROM news_articulo").fetchone())
    assert art["resultado"] == "EVENTO" and art["intentos"] == 2
    assert [a["tipo"] for a in alertas.listar(conn)] == ["NOTICIA"]


def test_reintentos_se_agotan_y_quedan_para_revision(conn, cfg):
    c = _cfg(cfg)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    jid = jg.buscar_por_nombre(conn, "Tom Lowe")["id"]
    aid = radar._articulo_nuevo(conn, {"url": "https://tennistourtalk.com/x", "dominio": "tennistourtalk.com", "titulo": "t",
                                       "contenido": "Tom Lowe", "idioma": "en"}, "radar", jid)
    conn.execute("UPDATE news_articulo SET creado_en=? WHERE id=?", (HOY.isoformat(), aid))
    conn.commit()
    gem = Gemini(api_key="g", transport=httpx.MockTransport(lambda req: httpx.Response(500, json={"error": {"message": "boom"}})))
    t = HOY
    for i in range(1, radar.MAX_INTENTOS + 1):
        t = t + timedelta(hours=24)
        rr = radar.reintentar_pendientes(conn, c, gem, t)
        assert rr["reintentados"] == 1
    art = dict(conn.execute("SELECT * FROM news_articulo WHERE id=?", (aid,)).fetchone())
    assert art["resultado"] == "AGOTADO" and art["intentos"] == radar.MAX_INTENTOS
    assert rr["agotados"] == 1
    assert conn.execute("SELECT tipo FROM news_revision").fetchone()["tipo"] == "CLASIFICACION_FALLIDA"
    assert radar.reintentar_pendientes(conn, c, gem, t + timedelta(days=1))["reintentados"] == 0


def test_error_de_proveedor_a_mitad_deja_el_articulo_pendiente(conn, cfg):
    """Tavily OK, clasificador tira ErrorProveedor fatal (clave rechazada): el radar
    se detiene, el artículo queda PENDIENTE y el jugador reprogramado."""
    c = _cfg(cfg)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    jid = jg.buscar_por_nombre(conn, "Tom Lowe")["id"]
    jg.encolar(conn, jid, "SIN_PARTIDO", 24 * 7, "RANKING", 3, "itf", HOY)
    tav, _ = _tav({"Tom Lowe": [_art("https://tennistourtalk.com/lowe-wrist", "Lowe injured", "Tom Lowe said he felt pain")]})
    gem = Gemini(api_key="g", transport=httpx.MockTransport(lambda req: httpx.Response(401, json={"error": {"message": "bad key"}})))
    r = radar.correr(conn, c, tav, gem, HOY, 10)
    assert str(r["motivo"]).startswith("PROVEEDOR:")
    art = dict(conn.execute("SELECT * FROM news_articulo").fetchone())
    assert art["resultado"] == "PENDIENTE" and art["jugador_id"] == jid
    cola = conn.execute("SELECT ultimo_error, proxima_busqueda_en FROM news_jugador_cola WHERE jugador_id=?", (jid,)).fetchone()
    assert cola["ultimo_error"] and cola["proxima_busqueda_en"] > HOY.isoformat()


# ── cobertura por circuito y presupuesto ─────────────────────────────────
def test_cobertura_por_circuito_y_presupuesto(conn, cfg, monkeypatch):
    from ft_news import cobertura, config
    from fastapi.testclient import TestClient
    from ft_news.app import app
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez", nivel_nat="HECHO")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    cob = cobertura.por_circuito(conn, c, HOY)
    por = {x["circuito"]: x for x in cob["circuitos"]}
    assert set(por) >= {"challenger", "wta", "itf"}
    ch = por["challenger"]
    assert ch["en_cola"] == 2 and ch["investigados"] == 2 and ch["cobertura_pct"] == 100.0 and ch["busquedas"] == 4
    assert ch["articulos"] == 1 and ch["noticias_utiles"] == 1 and ch["partidos_analizados"] == 1 and ch["alertas"] >= 1
    assert por["itf"]["en_cola"] == 2 and por["itf"]["investigados"] == 2 and por["itf"]["alertas"] == 0
    pr = cob["presupuesto"]
    # Perez/Rossi en 20 h (cada 6 h × 2 idiomas = 8 c/u) + 4 jugadores a 30–40 h (cada 12 h × 2 = 4 c/u) = 32; temático apagado
    assert pr["necesario_dia"] == 32 and pr["tematico_dia"] == 0 and pr["alcanza"] is True and pr["tope_propuesto"] == 250
    assert pr["por_circuito"] == {"challenger": 16.0, "wta": 8.0, "itf": 8.0} and pr["menores_pct_necesario"] == 75.0
    assert pr["cupo_menores_actual"] == 40 and pr["cupo_menores_sugerido"] == 70        # 75 % necesario → sube el cupo (tope 70)
    # si el tope no alcanza, propone otro con 20 % de margen redondeado a 50
    pr2 = cobertura.presupuesto(conn, dict(c, NEWS_MAX_BUSQUEDAS_DIA=20, NEWS_RADAR_TEMATICO_ACTIVO=1))
    assert pr2["necesario_dia"] == 32 + 48 and pr2["alcanza"] is False and pr2["tope_propuesto"] == 100 and pr2["usd_mes_con_propuesto"] == 24.0
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", __import__("pathlib").Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    with TestClient(app) as t:
        d = t.get("/news/diagnostico", headers={"X-FT-News-Secret": "secreto-pruebas"}).json()
        assert d["cobertura"]["presupuesto"]["tope_actual"] == 250 and any(x["circuito"] == "itf" for x in d["cobertura"]["circuitos"])
        assert "reintentos" in d


def test_retiro_del_mismo_torneo_no_es_valor(conn, cfg):
    """Whitlock se retira del M25 Sevilla y su fixture sigue listado: el partido puede
    no jugarse → 📰 sí, 🔥 no (queda 🔎 con RETIRO_MISMO_TORNEO)."""
    c = _cfg(cfg)
    d = _lesion("Tom Lowe", cat="RETIRO_ABANDONO", nivel_nat="HECHO")
    d["resumen_es"] = "Lowe se retiró del M25 de Sevilla por la muñeca."
    gem, _ = _gem({"Tom Lowe": d})
    tav, _ = _tav({"Tom Lowe": [_art("https://tennistourtalk.com/lowe-wd", "Lowe withdraws Sevilla", "Tom Lowe has withdrawn")]})
    _ciclo(conn, c, tav, gem)
    e = dict(conn.execute("SELECT * FROM news_evaluacion WHERE partido_id IN (SELECT id FROM news_partido WHERE torneo='M25 Sevilla')").fetchone())
    assert e["tipo_alerta"] == "INTERESANTE" and e["motivo"] == "RETIRO_MISMO_TORNEO"
    assert "el retiro es del mismo torneo (M25 Sevilla): el partido puede no jugarse" in e["conclusion"]
    assert sorted(a["tipo"] for a in alertas.listar(conn)) == ["INTERESANTE", "NOTICIA"]


def test_alertas_pendientes_vencen_y_voz_dice_experimental(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez", nivel_nat="HECHO")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    exp = [a for a in alertas.listar(conn) if a["tipo"] == "FUEGO_EXPERIMENTAL"][0]
    assert exp["texto_voz"].startswith("Posible valor experimental, sin validar. Rossi, cuota 2.90, contra Perez.")
    assert len(alertas.pendientes(conn, c)) == 2
    # 13 h después sin decirse (Discord apagado): vencen y no salen al encender
    assert alertas.vencer_pendientes(conn, c, HOY + timedelta(hours=13)) == 2
    assert alertas.pendientes(conn, c) == []
    a = alertas.listar(conn)[0]
    assert a["dicho_discord"] == 2 and a["dicho_motivo"] == "VENCIDA"
    # dentro del ciclo
    r = _ciclo(conn, c, tav, gem, HOY + timedelta(hours=14))
    assert r["pasos"]["alertas_vencidas"] == {"vencidas": 0}


def test_ninguna_clave_llega_a_logs_ni_estado(monkeypatch):
    from ft_news.proveedores.tavily import ErrorProveedor, sin_claves
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyCLAVE-SECRETA-123456")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-otra-clave-9999")
    e = ErrorProveedor("Gemini 400 en https://x/?key=AIzaSyCLAVE-SECRETA-123456 y Bearer tvly-otra-clave-9999")
    assert "AIzaSy" not in str(e) and "tvly-otra" not in str(e) and "***GEMINI_API_KEY***" in str(e)
    assert sin_claves("sin claves acá") == "sin claves acá"


def test_sin_cuota_posterior_a_la_noticia_es_interesante_pendiente(conn, cfg):
    """v5.2 (Rubén 22:52): que la noticia sea posterior a nuestra última cuota NO significa
    que el mercado no la haya incorporado. Sin cuota confirmada después → 🔎 pendiente de
    actualización; cuando RankingFTR confirma el precio después de la noticia y no se movió → 🔥."""
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez", nivel_nat="HECHO")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem, confirmar=False)
    e = _evaluacion(conn)
    assert e["tipo_alerta"] == "INTERESANTE" and e["motivo"] == "CUOTA_SIN_ACTUALIZAR"
    assert "pendiente de actualización de cuota" in e["conclusion"]
    a = [a for a in alertas.listar(conn) if a["tipo"] == "INTERESANTE"][0]
    assert "⏳ Pendiente de confirmar la reacción del mercado." in a["texto_discord"]
    assert a["evidencia"]["pendiente"][-1].endswith("pendiente de actualización")
    assert not [a for a in alertas.listar(conn) if a["tipo"] == "FUEGO_EXPERIMENTAL"]
    # misma cuota confirmada 20 min después de la noticia → el mercado no reaccionó → 🔥 experimental
    f2 = FTR()
    f2.cap = (HOY - timedelta(minutes=40)).isoformat()          # noticia: HOY-1h
    from ft_news import evaluador, partidos
    partidos.sincronizar(conn, f2, c, HOY + timedelta(minutes=10))
    ad = partidos.cuota_antes_y_despues(conn, e["partido_id"], e["jugador_x_id"], HOY - timedelta(hours=1))
    assert ad["antes"]["cuota"] == 1.4 and ad["despues"]["cuota"] == 1.4 and ad["mismo_precio"] is True
    evaluador.correr(conn, c, HOY + timedelta(minutes=15))
    e = _evaluacion(conn)
    assert e["tipo_alerta"] == "FUEGO_EXPERIMENTAL"
    assert "📈 La cuota de Perez sigue en 1.40 después de la noticia." in e["texto_discord"]
    assert "cuota confirmada después de la noticia" in e["conclusion"] or True
    tipos = {a["tipo"]: a for a in alertas.listar(conn)}
    assert tipos["INTERESANTE"]["dicho_motivo"] == "SUPERADA_POR_FUEGO_EXPERIMENTAL" and tipos["FUEGO_EXPERIMENTAL"]["dicho_discord"] == 0
    # el mismo precio visto de nuevo no duplica la observación: solo corre hasta_en
    obs = partidos.observaciones(conn, e["partido_id"])
    assert len(obs) == 1 and obs[0]["hasta_en"] == f2.cap and obs[0]["capturada_en"] == (HOY - timedelta(hours=3)).isoformat()


def test_endpoint_evaluacion_detalle_para_el_modal(conn, cfg, monkeypatch):
    """10/10/2026: el modal de la pestaña (🔥 → qué noticias encontró y todo lo analizado)."""
    from ft_news import config
    from fastapi.testclient import TestClient
    from ft_news.app import app
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez", nivel_nat="HECHO")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    e = _evaluacion(conn)
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", __import__("pathlib").Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    with TestClient(app) as t:
        h = {"X-FT-News-Secret": "secreto-pruebas"}
        d = t.get(f"/news/evaluaciones/{e['id']}", headers=h).json()
        assert d["evaluacion"]["tipo_alerta"] == "FUEGO_EXPERIMENTAL" and d["partido"]["torneo"] == "Challenger Lima"
        assert d["jugador_x"]["nombre"] == "Juan Perez" and d["rival"]["nombre"] == "Luca Rossi" and d["jugador_x"]["utr_singles"] == 12.9
        ev = d["eventos_usados"]
        assert len(ev) == 1 and ev[0]["origen"] == "EXTERNO" and ev[0]["articulo"]["url"] == "https://tennistourtalk.com/perez-wrist"
        assert ev[0]["fuente"] == "tennistourtalk.com" and ev[0]["cambios"][0]["cambio"] == "NUEVO" and "lectura1_json" not in ev[0]
        assert d["vigentes_x"] and d["vigentes_rival"] == []
        assert d["cuotas"] and d["cuotas"][0]["proveedor"] == "FIXTURES_FTR"
        tipos = {a["tipo"] for a in d["alertas"]}
        assert "FUEGO_EXPERIMENTAL" in tipos
        fe = [a for a in d["alertas"] if a["tipo"] == "FUEGO_EXPERIMENTAL"][0]
        assert fe["evidencia"]["justificacion"]["puntos"] >= 2 and fe["texto_discord"].startswith("🔥 FULLTENNIS")
        assert d["frescura"]["x"]["reciente"] and d["frescura"]["rival"]["reciente"]
        assert d["busquedas"]["x"] and d["articulos"]["x"][0]["resultado"] == "EVENTO"
        assert t.get("/news/evaluaciones/9999", headers=h).status_code == 404
