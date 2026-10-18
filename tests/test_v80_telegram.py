"""v8.0 (18/10/2026): 📡 pistas de canales de Telegram — se comprueban con fuentes autorizadas, nunca salen solas."""
from datetime import datetime, timedelta, timezone

from ft_news import jugadores as jg
from ft_news import memoria
from ft_news.lectores import telegram as tg

AHORA = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


class Clasif:
    nombre, modelo, aviso = "falso", "falso-1", None

    def __init__(self, datos):
        self.datos, self.llamadas, self.vistos = datos, 0, []

    def clasificar(self, jugador, art):
        self.llamadas += 1
        self.vistos.append((jugador["nombre"], art["dominio"], art["url"]))
        d = self.datos(jugador, art) if callable(self.datos) else dict(self.datos)
        return {"ok": True, "datos": d, "tokens_entrada": 10, "tokens_salida": 5, "usd": 0.0}


def _lesion(**k):
    d = {"sobre_jugador": True, "confianza_identidad": 0.95, "categoria": "LESION_MOLESTIA", "direccion": "NEGATIVA",
         "naturaleza": "HECHO", "fecha_evento": "2026-10-18", "resumen_es": "Se bajó por una lesión en el tobillo derecho.",
         "titular": "Baja por el tobillo derecho", "relevancia_deportiva": "no juega", "fragmento_original": "x", "idioma": "en"}
    d.update(k)
    return d


def _padron(conn):
    ids = {}
    for n, g in (("Kenya Pinnington Jones", "F"), ("Clara Burel", "F"), ("Daniil Medvedev", "M"), ("Bianca Andreescu", "F"),
                 ("Jan Martinez", "M"), ("Lucia Martinez", "F"), ("Pedro Martinez", "M"), ("Rival Uno", "M"), ("Rival Dos", "F")):
        ids[n] = jg.upsert(conn, n, g)
    return ids


def _partido(conn, a, b, horas=20):
    conn.execute("INSERT INTO news_partido (torneo, fecha_estimada, jugador1_id, jugador2_id, estado, creado_en, actualizado_en) "
                 "VALUES ('Challenger Fort Worth', ?, ?, ?, 'PROGRAMADO', ?, ?)",
                 ((AHORA + timedelta(hours=horas)).isoformat(), a, b, AHORA.isoformat(), AHORA.isoformat()))
    conn.commit()


def _cfg(cfg):
    return dict(cfg, NEWS_ACTIVO=1, NEWS_TELEGRAM_ACTIVO=1, NEWS_TELEGRAM_MAX_DIA=80, NEWS_TELEGRAM_CONFIRMAR_H=72)


def _rec(conn, texto, msg, canal="ALL News", chat="-1001", modo="lesiones"):
    return tg.recibir(conn, {"texto": texto, "canal": canal, "chat_id": chat, "msg_id": msg, "modo": modo,
                             "fecha": AHORA.isoformat()}, AHORA)


def _estado(conn, pid):
    return dict(conn.execute("SELECT * FROM news_pista WHERE id=?", (pid,)).fetchone())


def test_apellido_en_primera_linea():
    assert tg.apellido_de("Pinnington Jones\nhas withdrawn from the doubles") == "Pinnington Jones"
    assert tg.apellido_de("Burel\nafter beating Bouzas Maneiro in Lisbon today: “I’m very happy”") == "Burel"
    assert tg.apellido_de("Andreescu\n def. Havlickova 6/3 6/1 in Rovereto.") == "Andreescu"
    assert tg.apellido_de("I came back to Singapore after 7 years!") is None


def test_lesion_fuerte_verificando_y_radar_adelantado(conn, cfg):
    ids = _padron(conn)
    _partido(conn, ids["Kenya Pinnington Jones"], ids["Rival Dos"])
    r = _rec(conn, "Pinnington Jones\nhas withdrawn from the singles at the Challenger event in Fort Worth with a right ankle injury.", 1)
    assert r["nuevo"]
    cl = Clasif(_lesion())
    out = tg.procesar(conn, _cfg(cfg), cl, AHORA)
    p = _estado(conn, r["id"])
    assert p["estado"] == "VERIFICANDO" and p["jugador_id"] == ids["Kenya Pinnington Jones"], p
    assert cl.llamadas == 1 and cl.vistos[0][1] == "telegram" and out["por_estado"] == {"VERIFICANDO": 1}
    assert "Rival Dos" in (p["partido_txt"] or "")
    cola = conn.execute("SELECT prioridad, motivo FROM news_jugador_cola WHERE jugador_id=?", (ids["Kenya Pinnington Jones"],)).fetchone()
    assert cola["prioridad"] == 0 and cola["motivo"] == "PISTA_TELEGRAM"
    # una pista sola NO es noticia ni alerta
    assert conn.execute("SELECT COUNT(*) FROM news_evento").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM news_alerta").fetchone()[0] == 0


def test_dobles_no_es_fuerte(conn, cfg):
    _padron(conn)
    r = _rec(conn, "Pinnington Jones\nhas withdrawn from the doubles at the Challenger event in Fort Worth with a right ankle injury.", 2)
    tg.procesar(conn, _cfg(cfg), Clasif(_lesion(resumen_es="Se bajó del cuadro de dobles por el tobillo.")), AHORA)
    p = _estado(conn, r["id"])
    assert p["estado"] == "INFORMATIVA" and "dobles" in p["motivo"]


def test_declaracion_sin_palabras_no_gasta_ia(conn, cfg):
    _padron(conn)
    r = _rec(conn, "Medvedev\non Jodar's playing style: “He moves well and returns very well.”", 3)
    cl = Clasif(_lesion())
    tg.procesar(conn, _cfg(cfg), cl, AHORA)
    assert _estado(conn, r["id"])["estado"] == "SIN_INTERES" and cl.llamadas == 0


def test_canal_todo_lee_declaracion_si_hay_partido(conn, cfg):
    ids = _padron(conn)
    _partido(conn, ids["Daniil Medvedev"], ids["Rival Uno"])
    r = _rec(conn, "Medvedev\non Jodar's playing style: “He moves well.”", 4, modo="todo")
    cl = Clasif(_lesion(categoria="DECLARACION_MOTIVACION", direccion="MIXTA", naturaleza="DECLARACION"))
    tg.procesar(conn, _cfg(cfg), cl, AHORA)
    assert _estado(conn, r["id"])["estado"] == "INFORMATIVA" and cl.llamadas == 1


def test_duplicada_entre_canales(conn, cfg):
    _padron(conn)
    t = "Pinnington Jones\nhas withdrawn from Fort Worth with a right ankle injury."
    a = _rec(conn, t, 10, canal="ALL News", chat="-1001")
    b = _rec(conn, t, 77, canal="Injuries", chat="-1002")
    cl = Clasif(_lesion())
    tg.procesar(conn, _cfg(cfg), cl, AHORA)
    assert cl.llamadas == 1
    pb = _estado(conn, b["id"])
    assert pb["estado"] == "DUPLICADA" and pb["duplicada_de"] == a["id"]
    assert "Injuries" in tg.listar(conn, ahora=AHORA)["pistas"][-1]["canales"]
    # el mismo mensaje dos veces (reintento del reenviador) no se guarda dos veces
    assert _rec(conn, t, 10)["nuevo"] is False


def test_apellido_ambiguo_y_desempate(conn, cfg):
    ids = _padron(conn)
    r = _rec(conn, "Martinez\nwithdrew from Lima with a wrist injury.", 20)
    cl = Clasif(_lesion())
    tg.procesar(conn, _cfg(cfg), cl, AHORA)
    p = _estado(conn, r["id"])
    assert p["estado"] == "AMBIGUA" and cl.llamadas == 0
    # con el género del texto (she) y uno solo con partido → se identifica
    _partido(conn, ids["Lucia Martinez"], ids["Rival Dos"])
    r2 = _rec(conn, "Martinez\nretired in her match today with a wrist injury.", 21)
    tg.procesar(conn, _cfg(cfg), cl, AHORA)
    assert _estado(conn, r2["id"])["jugador_id"] == ids["Lucia Martinez"]


def test_sin_jugador(conn, cfg):
    _padron(conn)
    r = _rec(conn, "Kawachi\n\"I came back to Singapore after 7 years!\"", 30)
    tg.procesar(conn, _cfg(cfg), Clasif(_lesion()), AHORA)
    assert _estado(conn, r["id"])["estado"] == "SIN_JUGADOR"


def test_confirmada_por_fuente_autorizada(conn, cfg):
    ids = _padron(conn)
    r = _rec(conn, "Burel\nwithdrew from Lisbon final with an abdominal strain.", 40)
    tg.procesar(conn, _cfg(cfg), Clasif(_lesion()), AHORA)
    assert _estado(conn, r["id"])["estado"] == "VERIFICANDO"
    # la noticia de un medio autorizado (radar) confirma la pista
    ev = memoria.nuevo_evento(ids["Clara Burel"], "LESION_MOLESTIA", "NEGATIVA", "HECHO", "B", AHORA.date().isoformat(),
                              fuente="tennistourtalk.com", enlace="https://tennistourtalk.com/x", resumen_es="Abdominal",
                              titular="Molestia abdominal")
    eid = memoria.guardar_evento_db(conn, ev)
    p = _estado(conn, r["id"])
    assert p["estado"] == "CONFIRMADA" and p["evento_id"] == eid
    f = [x for x in tg.listar(conn, ahora=AHORA)["pistas"] if x["id"] == r["id"]][0]
    assert f["estado_txt"].startswith("confirmada")


def test_no_confirma_otro_tipo_ni_dato_calculado(conn, cfg):
    ids = _padron(conn)
    r = _rec(conn, "Burel\nwithdrew from Lisbon with an abdominal strain.", 41)
    tg.procesar(conn, _cfg(cfg), Clasif(_lesion()), AHORA)
    hoy = AHORA.date().isoformat()
    memoria.guardar_evento_db(conn, memoria.nuevo_evento(ids["Clara Burel"], "LOCALIA", "POSITIVA", "HECHO", "B", hoy,
                                                         fuente="tennistourtalk.com", enlace="https://t/1"))
    memoria.guardar_evento_db(conn, memoria.nuevo_evento(ids["Clara Burel"], "CARGA_FISICA", "NEGATIVA", "HECHO", "A", hoy,
                                                         fuente="rankingftr.interno", enlace="contexto:carga"))
    assert _estado(conn, r["id"])["estado"] == "VERIFICANDO"


def test_vence_sin_confirmar(conn, cfg):
    _padron(conn)
    r = _rec(conn, "Andreescu\nretired from Rovereto with a back injury.", 50)
    tg.procesar(conn, _cfg(cfg), Clasif(_lesion()), AHORA)
    tg.vencer(conn, _cfg(cfg), AHORA + timedelta(hours=73))
    assert _estado(conn, r["id"])["estado"] == "SIN_CONFIRMAR"


def test_tope_diario_y_apagado(conn, cfg):
    _padron(conn)
    r = _rec(conn, "Andreescu\nretired with a back injury.", 60)
    cl = Clasif(_lesion())
    tg.procesar(conn, dict(_cfg(cfg), NEWS_TELEGRAM_MAX_DIA=0), cl, AHORA)
    assert _estado(conn, r["id"])["estado"] == "RECIBIDA" and cl.llamadas == 0
    out = tg.procesar(conn, dict(_cfg(cfg), NEWS_TELEGRAM_ACTIVO=0), cl, AHORA)
    assert out["motivo"] == "NEWS_TELEGRAM_ACTIVO=0" and cl.llamadas == 0


def test_error_de_lectura_se_reintenta(conn, cfg):
    _padron(conn)
    r = _rec(conn, "Andreescu\nretired with a back injury.", 70)

    class Roto(Clasif):
        def clasificar(self, jugador, art):
            self.llamadas += 1
            return {"ok": False, "error": "503", "tokens_entrada": 0, "tokens_salida": 0, "usd": 0.0}
    roto = Roto(None)
    tg.procesar(conn, _cfg(cfg), roto, AHORA)
    assert _estado(conn, r["id"])["estado"] == "ERROR"
    tg.procesar(conn, _cfg(cfg), Clasif(_lesion()), AHORA)
    assert _estado(conn, r["id"])["estado"] == "VERIFICANDO"


def test_api_pista_y_listado(conn):
    from fastapi.testclient import TestClient
    from ft_news.app import app
    c = TestClient(app)
    h = {"X-FT-News-Secret": "secreto-pruebas"}
    assert c.post("/news/telegram/pista", json={"texto": "x"}).status_code == 401
    r = c.post("/news/telegram/pista", headers=h, json={"texto": "Burel\nwithdrew with an injury", "canal": "ALL News",
                                                         "chat_id": "-100999", "msg_id": 5, "modo": "lesiones"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["nuevo"]
    l = c.get("/news/telegram/pistas", headers=h).json()
    assert l["pistas"][0]["canales"] == ["ALL News"] and l["ultimas_24h"]["total"] >= 1 and "regla" in l
