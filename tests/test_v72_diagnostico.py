"""v7.2 (13/10/2026, Rubén: "no estoy recibiendo alertas y no sabemos si FT NEWS está
funcionando"): motivos de descarte permanentes, embudo de las seis preguntas,
semáforo FUNCIONANDO / SIN_DATOS / ERROR, guardia de "bandas calibradas" y prueba
real de Discord solo para admin, fuera de historial y estadísticas. Sin red."""
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from ft_news import alertas, config, dashboard, descartes, evaluador, fuentes, memoria, partidos, radar, salud
from ft_news import jugadores as jg
from ft_news.app import app
from ft_news.db import config_guardar, estado_set, estado_todo

from tests.test_v5_alertas import FTR, HOY, _art, _cfg, _ciclo, _gem, _lesion, _tav

H = {"X-FT-News-Secret": "secreto-pruebas"}


def _api(conn, monkeypatch):
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    return TestClient(app)


def _descartes(conn, **w):
    q = "SELECT * FROM news_descarte" + (" WHERE " + " AND ".join(f"{k}=?" for k in w) if w else "")
    return [dict(r) for r in conn.execute(q, tuple(w.values())).fetchall()]


# ── grupos y registro ─────────────────────────────────────────────────────
def test_grupos_normalizan_los_codigos_del_motor():
    assert descartes.grupo("RIVAL_SIN_INVESTIGAR:Luca Rossi") == "RIVAL_SIN_INVESTIGAR"
    assert descartes.grupo("RIVAL_SIN_INVESTIGACION_RECIENTE:Luca Rossi") == "RIVAL_SIN_INVESTIGAR"
    assert descartes.grupo("CUOTA_SIN_ACTUALIZAR") == "CUOTA_SIN_ACTUALIZAR"
    assert descartes.grupo("SIN_NOTICIA_EXTERNA_FUERTE") == "SOLO_DATOS_INTERNOS"
    assert descartes.grupo("NATURALEZA:NO_VERIFICADA") == "RUMOR_NO_CONFIRMADO"
    assert descartes.grupo("NEWS_DISCORD_NOTICIA=0") == "CANAL_APAGADO"
    assert descartes.grupo("error: boom") == "ERROR"
    assert descartes.grupo("ALGO_NUEVO") == "OTRO"
    assert all(descartes.texto(g) for g in descartes.GRUPOS)


def test_registrar_suma_veces_y_no_duplica(conn):
    for _ in range(3):
        descartes.registrar(conn, "INTERESANTE", "RIVAL_SIN_INVESTIGAR:X", ahora=HOY, partido_id=5, jugador_id=1, rival_id=2)
    descartes.registrar(conn, "INTERESANTE", "TOPE_DIARIO", ahora=HOY, partido_id=5)
    descartes.registrar(conn, "INTERESANTE", "RIVAL_SIN_INVESTIGAR:X", ahora=HOY + timedelta(days=1), partido_id=5)
    filas = _descartes(conn)
    assert len(filas) == 3                                           # (día, etapa, objeto, grupo) único
    hoy = [f for f in filas if f["dia"] == HOY.date().isoformat() and f["grupo"] == "RIVAL_SIN_INVESTIGAR"][0]
    assert hoy["veces"] == 3 and hoy["objeto"] == "partido:5"
    assert descartes.registrar(conn, "FUEGO", "NO_ES_FUEGO", ahora=HOY, partido_id=5) is None      # no es un descarte


# ── preguntas 3 y 4 con el motor real ────────────────────────────────────
def _escenario_rival_sin_investigar(conn, c):
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    jg.sincronizar_padron(conn, FTR())
    jp, jr = jg.buscar_por_nombre(conn, "Juan Perez"), jg.buscar_por_nombre(conn, "Luca Rossi")
    aid = conn.execute("INSERT INTO news_articulo (url, dominio, titulo, creado_en) VALUES "
                       "('https://tennistourtalk.com/p','tennistourtalk.com','t',?)", ((HOY - timedelta(hours=1)).isoformat(),)).lastrowid
    partidos.sincronizar(conn, FTR(), c, HOY)
    ev = memoria.nuevo_evento(jp["id"], "LESION_MOLESTIA", "NEGATIVA", "HECHO", "B", HOY.isoformat(),
                              fuente="tennistourtalk.com", enlace="https://tennistourtalk.com/p", articulo_id=aid,
                              fecha_publicacion=(HOY - timedelta(hours=1)).isoformat(), confianza_identidad=0.95)
    memoria.guardar_evento_db(conn, ev)
    conn.execute("UPDATE news_jugador_cola SET ultima_busqueda_en=? WHERE jugador_id=?", ((HOY - timedelta(hours=1)).isoformat(), jp["id"]))
    conn.commit()
    f2 = FTR()
    f2.cap = (HOY - timedelta(minutes=20)).isoformat()                 # cuota confirmada después de la noticia
    partidos.sincronizar(conn, f2, c, HOY)
    return jp, jr


def test_rival_sin_investigar_queda_guardado_y_el_embudo_lo_cuenta(conn, cfg):
    c = _cfg(cfg)
    jp, jr = _escenario_rival_sin_investigar(conn, c)
    evaluador.correr(conn, c, HOY)
    d = _descartes(conn, grupo="RIVAL_SIN_INVESTIGAR")
    assert d and {x["etapa"] for x in d} == {"FUEGO", "INTERESANTE"} and "Luca Rossi" in d[0]["detalle"] + d[-1]["motivo"]
    ev = dict(conn.execute("SELECT * FROM news_evaluacion").fetchone())
    assert ev["alerta_motivo"].startswith("NO ENVIADA · RIVAL_SIN_INVESTIGAR")
    e = descartes.embudo(conn, 7, HOY)
    assert e["3_rival_sin_investigar"] == {"partidos": 1, "recuperados_despues": 0, "perdidos": 0, "todavia_en_juego": 1}
    # otro ciclo con lo mismo: no crea filas nuevas, suma veces
    evaluador.correr(conn, c, HOY + timedelta(minutes=1))
    assert len(_descartes(conn, grupo="RIVAL_SIN_INVESTIGAR")) == len(d)
    assert max(x["veces"] for x in _descartes(conn, grupo="RIVAL_SIN_INVESTIGAR")) == 2
    # el radar investiga al rival → sale la 🔥 → el embudo lo cuenta como recuperado
    gem, _ = _gem({})
    tav, _ = _tav({})
    radar.correr(conn, c, tav, gem, HOY + timedelta(minutes=10), 10)
    evaluador.correr(conn, c, HOY + timedelta(minutes=15))
    assert dict(conn.execute("SELECT alerta_motivo FROM news_evaluacion").fetchone())["alerta_motivo"].startswith("ALERTA #")
    assert descartes.embudo(conn, 7, HOY + timedelta(minutes=15))["3_rival_sin_investigar"]["recuperados_despues"] == 1
    # y cuando el partido empieza sin alerta, cuenta como perdido
    conn.execute("DELETE FROM news_alerta")
    conn.commit()
    assert descartes.embudo(conn, 7, HOY + timedelta(hours=21))["3_rival_sin_investigar"]["perdidos"] == 1


def test_cuota_sin_actualizar_queda_guardada(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez", nivel_nat="HECHO")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem, confirmar=False)
    d = _descartes(conn, grupo="CUOTA_SIN_ACTUALIZAR")
    assert len(d) == 1 and d[0]["etapa"] == "FUEGO" and "después de la noticia" in d[0]["detalle"]
    e = descartes.embudo(conn, 7, HOY)
    assert e["4_cuota_sin_actualizar"]["partidos"] == 1
    assert e["1_noticias_externas_por_dia"][0]["n"] == 1


def test_motivo_de_cada_noticia_queda_en_el_evento(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez"),
                   "Luca Rossi": _lesion("Luca Rossi", cat="DECLARACION_MOTIVACION")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")],
                   "Luca Rossi": [_art("https://tennistourtalk.com/rossi", "Rossi motivated", "Luca Rossi is motivated")]})
    _ciclo(conn, c, tav, gem)
    ev = {r["jugador"]: r["noticia_motivo"] for r in conn.execute(
        "SELECT j.nombre jugador, e.noticia_motivo FROM news_evento e JOIN news_jugador j ON j.id=e.jugador_id")}
    assert ev["Juan Perez"].startswith("ALERTA #")
    assert ev["Luca Rossi"].startswith("NO ENVIADA · CATEGORIA_NO_RELEVANTE")
    assert _descartes(conn, etapa="NOTICIA", grupo="CATEGORIA_NO_RELEVANTE")
    filas = {(x["etapa"], x["grupo"]) for x in descartes.embudo(conn, 7, HOY)["2_descartes"]}
    assert ("NOTICIA", "CATEGORIA_NO_RELEVANTE") in filas


# ── pregunta 6: bandas ───────────────────────────────────────────────────
def test_bandas_marcadas_a_mano_sin_veredicto_no_se_aplican(conn, cfg, monkeypatch):
    from ft_news import tareas
    config_guardar(conn, "NEWS_BANDAS_CALIBRADAS", "1", "alguien")
    c = config.leer_config(conn)
    c = _cfg(c)
    assert c["NEWS_BANDAS_CALIBRADAS"] == 1
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez", nivel_nat="HECHO")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)                                          # FTR dice NO_CALIBRADAS
    est = estado_todo(conn)
    assert est["bandas_efectivas"]["valor"] == "0" and "sin veredicto CALIBRADAS_OK" in est["bandas_aviso"]["valor"]
    assert not conn.execute("SELECT 1 FROM news_alerta WHERE tipo='FUEGO'").fetchone()           # nunca 🔥 validada
    assert conn.execute("SELECT 1 FROM news_alerta WHERE tipo='FUEGO_EXPERIMENTAL'").fetchone()  # sí experimental
    assert config.leer_config(conn)["NEWS_BANDAS_CALIBRADAS"] == 1     # la configuración guardada no se toca
    s = salud.calcular(conn, ahora=HOY + timedelta(minutes=11))
    assert s["estado"] == "ERROR" and any("bandas calibradas" in m and "NO_CALIBRADAS" not in m for m in s["errores"])
    b = descartes.embudo(conn, 7, HOY)["6_bandas"]
    assert b["incorrecta"] is True and b["efectiva"] == 0 and b["cambiada_por"] == "alguien"
    with _api(conn, monkeypatch) as t:
        r = t.post("/news/config", headers=H, json={"clave": "NEWS_BANDAS_CALIBRADAS", "valor": "1", "por": "x"})
        assert r.status_code == 409 and "NO_CALIBRADAS" in r.json()["detail"]
        assert t.post("/news/config", headers=H, json={"clave": "NEWS_BANDAS_CALIBRADAS", "valor": "0", "por": "x"}).status_code == 200
        estado_set(conn, "calibracion_veredicto", "CALIBRADAS_OK")
        assert t.post("/news/config", headers=H, json={"clave": "NEWS_BANDAS_CALIBRADAS", "valor": "1", "por": "x"}).status_code == 200


# ── semáforo ─────────────────────────────────────────────────────────────
def test_semaforo_error_sin_datos_y_funcionando(conn, cfg):
    c = _cfg(cfg)
    s = salud.calcular(conn, c, ahora=HOY)
    assert s["estado"] == "ERROR" and "no completa una revisión" in s["errores"][0]
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    estado_set(conn, "senales_leidas_en", (HOY + timedelta(minutes=12)).isoformat())
    s = salud.calcular(conn, c, ahora=HOY + timedelta(minutes=15))
    assert s["estado"] == "FUNCIONANDO", s["motivos"]
    i = s["indicadores"]
    assert i["jugadores_vigilados"] >= 6 and i["busquedas_24h"] > 0 and i["noticias_encontradas_24h"] == 1
    assert i["partidos_proximos_con_cuota"] == 3 and i["proxima_busqueda_programada"]
    # FT Intelligence deja de leer → ERROR, aunque el motor siga bien
    s = salud.calcular(conn, c, ahora=HOY + timedelta(hours=2))
    assert s["estado"] == "ERROR" and any("no revisa la cola de alertas" in m for m in s["errores"])
    # sin partidos ni búsquedas en 24 h (pero el worker vivo) → SIN DATOS
    conn.execute("UPDATE news_partido SET estado='TERMINADO'")
    conn.commit()
    later = HOY + timedelta(days=2)
    estado_set(conn, "ultimo_ciclo_en", later.isoformat())
    estado_set(conn, "senales_leidas_en", later.isoformat())
    s = salud.calcular(conn, c, ahora=later)
    assert s["estado"] == "SIN_DATOS" and any("partidos próximos" in m for m in s["avisos"])


# ── prueba real de Discord (v7.3: candado de admin y tres pasos) ─────────
def test_prueba_bloqueada_hasta_verificar_destino_admin(conn, cfg, monkeypatch):
    with _api(conn, monkeypatch) as t:
        t.post("/news/config", headers=H, json={"clave": "NEWS_DISCORD_ACTIVO", "valor": "1", "por": "t"})
        r = t.post("/news/prueba", headers=H, json={"por": "ruben"})
        assert r.status_code == 409 and "solo al canal de administradores" in r.json()["detail"]
        assert not conn.execute("SELECT 1 FROM news_alerta WHERE tipo='PRUEBA'").fetchone()
    # una PRUEBA que hubiera quedado en la base no viaja mientras el candado esté cerrado
    c = config.leer_config(conn)
    c["NEWS_PRUEBA_SOLO_ADMIN_VERIFICADA"] = 1
    alertas.crear_prueba(conn, "x", cfg=c)
    assert not [a for a in alertas.pendientes(conn, config.leer_config(conn)) if a.get("prueba")]


def test_prueba_tres_pasos_fuera_de_historial_y_estadisticas(conn, cfg, monkeypatch):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    antes_listar = len(alertas.listar(conn))
    antes_picks = dashboard.picks(conn)
    config_guardar(conn, "NEWS_PRUEBA_SOLO_ADMIN_VERIFICADA", "1", "ruben")
    with _api(conn, monkeypatch) as t:
        assert t.post("/news/prueba", json={"por": "ruben"}).status_code == 401            # sin secreto, nada
        t.post("/news/config", headers=H, json={"clave": "NEWS_DISCORD_ACTIVO", "valor": "0", "por": "t"})
        assert t.post("/news/prueba", headers=H, json={"por": "ruben"}).status_code == 409
        t.post("/news/config", headers=H, json={"clave": "NEWS_DISCORD_ACTIVO", "valor": "1", "por": "t"})
        p = t.post("/news/prueba", headers=H, json={"por": "ruben"}).json()
        assert p["estado"] == "CREADA" and [x["estado"] for x in p["pasos"]] == ["✅", "⏳", "⏳"]
        assert p["texto"].startswith(alertas.PRUEBA_ENCABEZADO) and "ruben" in p["texto"]
        assert t.post("/news/prueba", headers=H, json={"por": "otro"}).json()["id"] == p["id"]       # no duplica
        # paso 2: FT Intelligence la recoge (sale marcada solo para admin)
        s = t.get("/news/senales", headers=H).json()["senales"]
        pr = [x for x in s if x["prueba"]]
        assert len(pr) == 1 and pr[0]["tipo_alerta"] == "NOTICIA" and pr[0]["solo_admin"] is True and pr[0]["destino"] == "ADMIN"
        assert all(not x.get("solo_admin") for x in s if x["id"] != p["id"])
        e = t.get(f"/news/prueba/{p['id']}", headers=H).json()
        assert e["estado"] == "RECIBIDA" and [x["estado"] for x in e["pasos"]] == ["✅", "✅", "⏳"]
        # FT Intelligence dice "dicho" SIN confirmación de FT Discord → NO es publicada
        t.post("/news/senales/dicho", headers=H, json={"avisos": [{"id": p["id"], "dicho": True}]})
        e = t.get(f"/news/prueba/{p['id']}", headers=H).json()
        assert e["estado"] == "RECIBIDA" and e["pasos"][2]["estado"] == "⏳" and "todavía no confirmó" in e["pasos"][2]["detalle"]
        # FT Discord confirma
        r = t.post("/news/senales/dicho", headers=H, json={"avisos": [{"id": p["id"], "dicho": True, "publicado": True,
                                                                         "canal": "#admin-pruebas"}]}).json()
        assert r["publicaciones"] == 1
        e = t.get(f"/news/prueba/{p['id']}", headers=H).json()
        assert e["estado"] == "PUBLICADA" and e["pasos"][2]["estado"] == "✅" and "#admin-pruebas" in e["pasos"][2]["detalle"]
        # fuera de historial, dashboard, resumen, topes y estadísticas
        al = t.get("/news/alertas", headers=H).json()
        assert len(al["alertas"]) == antes_listar and "PRUEBA" not in str(al["resumen"])
        assert len(dashboard.picks(conn)) == len(antes_picks)
        i = salud.calcular(conn)["indicadores"]
        assert i["alertas_procesadas_intel_24h"] == 0 and i["alertas_publicadas_confirmadas_24h"] == 0
        emb = t.get("/news/embudo?dias=7", headers=H).json()
        assert "PRUEBA" not in str(emb["embudo"]["5_entrega"]["alertas_por_dia"])
        assert t.get("/news/prueba/99999", headers=H).status_code == 404


def test_prueba_falla_y_dice_en_que_paso(conn, cfg):
    from ft_news.db import config_guardar as cg
    cg(conn, "NEWS_PRUEBA_SOLO_ADMIN_VERIFICADA", "1", "t")
    a = alertas.crear_prueba(conn, "x", ahora=HOY)
    # nadie la recoge y vence → falla en el paso 2
    alertas.vencer_pendientes(conn, config.leer_config(conn), HOY + timedelta(hours=13))
    e = alertas.estado_prueba(conn, a["id"])
    assert e["estado"] == "FALLO" and e["pasos"][1]["estado"] == "❌" and "nunca la recogió" in e["resumen"]
    # recibida pero FT Discord no pudo publicar → falla en el paso 3, con el motivo
    b = alertas.crear_prueba(conn, "x", ahora=HOY + timedelta(hours=14))
    alertas.registrar_entrega(conn, [b["id"]])
    alertas.marcar_dichas(conn, [{"id": b["id"], "dicho": True}])
    alertas.registrar_publicacion(conn, [{"id": b["id"], "publicado": False, "error": "webhook rechazado (404)"}])
    e = alertas.estado_prueba(conn, b["id"])
    assert e["estado"] == "FALLO" and e["pasos"][2]["estado"] == "❌" and "webhook rechazado" in e["resumen"]
    assert "paso 3" in e["resumen"]


def test_textos_del_semaforo_sin_codigos(conn, cfg):
    import re
    c = _cfg(cfg, NEWS_DISCORD_ACTIVO=0)
    config_guardar(conn, "NEWS_BANDAS_CALIBRADAS", "1", "t")
    estado_set(conn, "calibracion_veredicto", "NO_CALIBRADAS")
    estado_set(conn, "paso_radar", "ERROR 2026 Traceback KeyError x")
    estado_set(conn, "motivo", "radar sin TAVILY_API_KEY o sin clasificador (GEMINI_API_KEY / ANTHROPIC_API_KEY)")
    s = salud.calcular(conn, c, ahora=HOY)
    for m in s["motivos"]:
        assert not re.search(r"[A-Z]{3,}_[A-Z_]+|/news/|Traceback|KeyError", m), m


def test_cada_alerta_guarda_su_recorrido_y_canal(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    a = [x for x in alertas.listar(conn) if x["tipo"] == "NOTICIA"][0]
    assert a["recorrido"]["estado"] == "CREADA" and a["creado_en"] and a["jugador"] == "Juan Perez" and a["motivo_seleccion"]
    alertas.registrar_entrega(conn, [a["id"]])
    alertas.marcar_dichas(conn, [{"id": a["id"], "dicho": True}])
    a = [x for x in alertas.listar(conn) if x["id"] == a["id"]][0]
    assert a["recorrido"]["estado"] == "RECIBIDA"                     # procesada ≠ publicada
    alertas.registrar_publicacion(conn, [{"id": a["id"], "publicado": True, "canal": "#ft-news"}])
    a = [x for x in alertas.listar(conn) if x["id"] == a["id"]][0]
    assert a["recorrido"]["estado"] == "PUBLICADA" and a["publicado_canal"] == "#ft-news" and a["publicado_error"] is None


def test_textos_dicen_si_la_noticia_esta_confirmada():
    from ft_news import textos
    base = {"categoria": "LESION_MOLESTIA", "direccion": "NEGATIVA", "resumen_es": "Molestias en la muñeca.",
            "fuente": "puntodebreak.com"}
    j = {"nombre": "Juan Perez", "utr_singles": 12.9}
    t = textos.armar_noticia(dict(base, naturaleza="DECLARACION", nivel="B"), j, None)["texto"]
    assert "Según declaraciones recogidas por Punto de Break; sin confirmación oficial." in t
    t = textos.armar_noticia(dict(base, naturaleza="HECHO", nivel="B"), j, None)["texto"]
    assert "Informado por Punto de Break; sin confirmación oficial." in t
    t = textos.armar_noticia(dict(base, naturaleza="HECHO", nivel="A", fuente="atptour.com"), j, None)["texto"]
    assert "Confirmado por fuente oficial (ATP Tour)." in t
    assert "Confirmado" not in textos.armar_noticia(dict(base, naturaleza="DECLARACION", nivel="A"), j, None)["texto"]
