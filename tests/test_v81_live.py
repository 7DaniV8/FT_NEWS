"""v8.1 (04/11/2026): 📡 LIVE automático — eventos, pistas (apagadas por defecto), calculados y mesa de redacción."""
from datetime import datetime, timedelta, timezone

import pytest

from ft_news import jugadores as jg
from ft_news import live

AHORA = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _cfg(cfg, **k):
    base = dict(cfg, NEWS_LIVE_ACTIVO=1, NEWS_LIVE_PISTAS=0, NEWS_LIVE_CALCULADOS=1, NEWS_LIVE_DIAS=3)
    base.update(k)
    return base


def _evento(conn, jid, cat="LESION_MOLESTIA", estado="VIGENTE", resumen="Se retiró con molestia en el hombro.", horas=2):
    f = (AHORA - timedelta(hours=horas)).isoformat()
    cur = conn.execute(
        "INSERT INTO news_evento (jugador_id, categoria, direccion, naturaleza, nivel, fecha_evento, fecha_publicacion, fuente, enlace, "
        "resumen_es, estado, creado_en, actualizado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (jid, cat, "NEGATIVA", "HECHO", "A", f, f, "atptour.com", "https://www.atptour.com/x", resumen, estado, f, f))
    conn.commit()
    return cur.lastrowid


def _partido(conn, a, b, horas=5, c1=1.4, c2=3.0):
    conn.execute("INSERT INTO news_partido (torneo, fecha_estimada, jugador1_id, jugador2_id, estado, cuota1, cuota2, creado_en, actualizado_en) "
                 "VALUES ('Challenger Fort Worth', ?, ?, ?, 'PROGRAMADO', ?, ?, ?, ?)",
                 ((AHORA + timedelta(hours=horas)).isoformat(), a, b, c1, c2, AHORA.isoformat(), AHORA.isoformat()))
    conn.commit()


def test_evento_confirmado_entra_con_etiqueta(conn, cfg):
    a = jg.upsert(conn, "Daniil Medvedev", "M")
    _evento(conn, a)
    _evento(conn, a, cat="DECLARACION_MOTIVACION", resumen="Dijo que llega con ganas.")
    _evento(conn, a, cat="OTRA", resumen="Algo menor.")             # sin etiqueta: no es de LIVE
    r = live.sincronizar(conn, _cfg(cfg), AHORA)
    assert r["eventos"]["nuevo"] == 2, r
    items = live.listar(conn)["items"]
    assert {i["etiqueta"] for i in items} == {"MOLESTIAS", "DECLARACIONES"}
    assert all(i["nivel"] == "CONFIRMADO" and i["origen"] == "EVENTO" for i in items)


def test_idempotente_y_orden(conn, cfg):
    a = jg.upsert(conn, "Daniil Medvedev", "M")
    _evento(conn, a, horas=5)
    _evento(conn, a, cat="REGRESO", resumen="Vuelve tras una pausa.", horas=1)
    live.sincronizar(conn, _cfg(cfg), AHORA)
    r2 = live.sincronizar(conn, _cfg(cfg), AHORA)
    assert r2["eventos"] == {"nuevo": 0, "actualizado": 0, "igual": 2}
    items = live.listar(conn)["items"]
    assert [i["etiqueta"] for i in items] == ["INFORMACIÓN", "MOLESTIAS"]      # lo más nuevo primero


def test_evento_desmentido_se_oculta_y_oculto_a_mano_no_reabre(conn, cfg):
    a = jg.upsert(conn, "Daniil Medvedev", "M")
    e = _evento(conn, a)
    live.sincronizar(conn, _cfg(cfg), AHORA)
    conn.execute("UPDATE news_evento SET estado='DESMENTIDO' WHERE id=?", (e,))
    conn.commit()
    live.sincronizar(conn, _cfg(cfg), AHORA)
    assert live.listar(conn)["items"] == []
    e2 = _evento(conn, a, cat="REGRESO", resumen="Vuelve.")
    live.sincronizar(conn, _cfg(cfg), AHORA)
    lid = live.listar(conn)["items"][0]["id"]
    live.cambiar_estado(conn, lid, "OCULTO", "ruben")
    live.sincronizar(conn, _cfg(cfg), AHORA)
    assert live.listar(conn)["items"] == []


def test_pistas_apagadas_por_defecto_y_sin_confirmar_rotulada(conn, cfg):
    a = jg.upsert(conn, "Daniil Medvedev", "M")
    from ft_news.lectores import telegram as tg
    conn.executescript(tg._TABLA)
    conn.execute("INSERT INTO news_pista (canal, chat_id, msg_id, texto, huella, recibido_en, estado, jugador_id, categoria, titular) "
                 "VALUES ('c','1',1,'t','h',?, 'VERIFICANDO', ?, 'LESION_MOLESTIA', 'Medvedev con molestia')", (AHORA.isoformat(), a))
    conn.commit()
    assert live.sincronizar(conn, _cfg(cfg), AHORA)["pistas"] == {"activo": 0}
    assert live.listar(conn)["items"] == []
    live.sincronizar(conn, _cfg(cfg, NEWS_LIVE_PISTAS=1), AHORA)
    it = live.listar(conn)["items"][0]
    assert it["nivel"] == "SIN_CONFIRMAR" and it["origen"] == "PISTA"
    assert live.listar(conn, incluir_sin_confirmar=False)["items"] == []
    conn.execute("UPDATE news_pista SET estado='CONFIRMADA'")
    conn.commit()
    live.sincronizar(conn, _cfg(cfg, NEWS_LIVE_PISTAS=1), AHORA)
    assert live.listar(conn)["items"][0]["nivel"] == "CONFIRMADO"


def test_calculado_cruza_lesion_con_agenda(conn, cfg):
    a = jg.upsert(conn, "Daniil Medvedev", "M")
    b = jg.upsert(conn, "Rival Uno", "M")
    _evento(conn, a)
    _partido(conn, a, b)
    live.sincronizar(conn, _cfg(cfg), AHORA)
    calc = [i for i in live.listar(conn)["items"] if i["origen"] == "CALCULADO"]
    assert len(calc) == 1 and calc[0]["etiqueta"] == "SEGUIMIENTO"
    assert "Rival Uno" in calc[0]["titulo"] and "1.4" in calc[0]["texto"]
    assert live.sincronizar(conn, _cfg(cfg), AHORA)["calculados"]["nuevo"] == 0
    live.sincronizar(conn, _cfg(cfg, NEWS_LIVE_CALCULADOS=0), AHORA)         # apagado no rompe


def test_manual_borrador_aprobar(conn, cfg):
    r = live.manual(conn, {"etiqueta": "ENTRY LIST", "titulo": "Se publicó la entry list de Metz", "estado": "BORRADOR"}, "ruben", AHORA)
    assert live.listar(conn)["items"] == []
    assert len(live.listar(conn, borradores=True)["items"]) == 1
    assert live.cambiar_estado(conn, r["id"], "PUBLICADO", "ruben")
    assert live.listar(conn)["items"][0]["etiqueta"] == "ENTRY LIST"
    with pytest.raises(ValueError):
        live.manual(conn, {"etiqueta": "XX", "titulo": "t"}, "r", AHORA)
    with pytest.raises(ValueError):
        live.manual(conn, {"etiqueta": "INFORMACIÓN", "titulo": " "}, "r", AHORA)


def test_apagado_no_hace_nada(conn, cfg):
    assert live.sincronizar(conn, dict(cfg, NEWS_LIVE_ACTIVO=0), AHORA) == {"activo": 0}


def test_comparar_externo():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "herramientas"))
    import comparar_externo as ce
    ref = [{"fecha_hora": "2026-11-04T10:00:00Z", "etiqueta": "MOLESTIAS", "jugador": "Daniil Médvedev"},
           {"fecha_hora": "2026-11-04T10:00:00Z", "etiqueta": "MOLESTIAS", "jugador": "Otro Jugador"}]
    live = [{"jugador": "Daniil Medvedev", "ocurrio_en": "2026-11-04T10:05:00+00:00", "publicado_en": "2026-11-04T10:20:00+00:00"}]
    r = ce.comparar(ref, live)
    assert r["MOLESTIAS"]["cubiertas"] == 1 and r["MOLESTIAS"]["total"] == 2 and r["MOLESTIAS"]["mediana_min"] == 20
