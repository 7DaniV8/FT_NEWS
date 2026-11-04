"""v8.2 (04/11/2026): señal interna de TennisAlerta — con su autorización: solo pista interna, nunca republicada."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "herramientas"))
import tennisalerta_senal as ts  # noqa: E402

from ft_news import jugadores as jg  # noqa: E402
from ft_news import live  # noqa: E402
from ft_news.lectores import telegram as tg  # noqa: E402

AHORA = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)

NEWS = [{"id": "a1", "tag": "Molestias", "title": "Cardozo", "occurred_at": "2026-11-04T13:05:00+00:00", "section": "live"},
        {"id": "a2", "tag": "Entry List", "title": "Wayenburg", "occurred_at": "2026-11-04T09:38:00+00:00", "section": "live"},
        {"id": "a3", "tag": "Lesión", "title": "Pinnington Jones", "occurred_at": "2026-11-04T10:00:00+00:00"}]
MTO = [{"id": "m1", "event_type": "medical_timeout_start", "player_name": "Learner Tien", "opponent_name": "Luca van Assche",
        "tournament": "Paris", "score": "1-2", "occurred_at": "2026-11-04T11:46:30+00:00"}]
RESP = [{"url": "https://x.supabase.co/rest/v1/news_items?select=id", "json": NEWS},
        {"url": "https://x.supabase.co/rest/v1/rpc/public_mto_events", "json": MTO},
        {"url": "https://x.supabase.co/rest/v1/rpc/otra_cosa", "json": [{"id": "z", "title": "no"}]}]


def test_extrae_solo_lo_que_la_pagina_ya_cargo():
    it = ts.extraer(RESP)
    assert [i["clave"] for i in it] == ["ni:a1", "ni:a2", "ni:a3", "mto:m1"]
    assert ts.es_fisica("Molestias") and ts.es_fisica("Lesión") and not ts.es_fisica("Entry List") and not ts.es_fisica("Información")


def test_pista_primera_linea_es_el_jugador_y_FT_NEWS_la_lee(conn):
    it = ts.extraer(RESP)[0]
    c = ts.a_pista(it)
    assert tg.apellido_de(c["texto"]) == "Cardozo" and c["canal"].startswith("TennisAlerta") and c["modo"] == "lesiones"
    assert tg._PALABRAS.search(c["texto"])                      # el lector la considera de lesión/molestia
    r = tg.recibir(conn, c, AHORA)
    assert r["nuevo"] and not tg.recibir(conn, c, AHORA)["nuevo"]     # el mismo mensaje no se duplica


def test_procesar_envia_solo_fisicas_dedup_y_tope(tmp_path):
    mem = ts.Memoria(tmp_path / "e.json")
    enviados = []
    r = ts.procesar(ts.extraer(RESP), mem, lambda c: enviados.append(c) or True, tmp_path / "c.csv", tope_dia=2)
    assert r["nuevas"] == 4 and r["enviadas"] == 2 and r["solo_csv"] == 1 and r["tope"] == 1
    r2 = ts.procesar(ts.extraer(RESP), ts.Memoria(tmp_path / "e.json"), lambda c: enviados.append(c) or True, tmp_path / "c.csv", tope_dia=2)
    assert r2["enviadas"] == 0 and r2["nuevas"] == 1               # solo queda la que topó ayer
    assert (tmp_path / "c.csv").read_text("utf-8").splitlines()[0] == "fecha_hora,etiqueta,jugador,titulo"
    fallo = ts.procesar(ts.extraer(RESP[:1]), ts.Memoria(tmp_path / "x.json"), lambda c: False)
    assert fallo["fallo_envio"] == 2 and fallo["enviadas"] == 0     # si FT NEWS no responde, se reintenta luego


def test_ritmo_minimo_de_5_minutos():
    for _ in range(50):
        assert ts.espera_seg(1) >= 5 * 60 * 0.85 - 1


def test_la_pista_de_tennisalerta_nunca_llega_al_LIVE(conn, cfg):
    a = jg.upsert(conn, "Daniil Medvedev", "M")
    conn.executescript(tg._TABLA)
    for canal, cid in (("TennisAlerta (señal interna)", "tennisalerta"), ("ALL News", "-100")):
        conn.execute("INSERT INTO news_pista (canal_id, canal, chat_id, msg_id, texto, huella, recibido_en, estado, jugador_id, categoria, titular) "
                     "VALUES (?,?,?,?,'t',?,?, 'CONFIRMADA', ?, 'LESION_MOLESTIA', 'Titular propio')",
                     (cid, canal, cid, 1, canal, AHORA.isoformat(), a))
    conn.commit()
    c = dict(cfg, NEWS_LIVE_ACTIVO=1, NEWS_LIVE_PISTAS=1, NEWS_LIVE_CALCULADOS=1, NEWS_LIVE_DIAS=3)
    live.sincronizar(conn, c, AHORA)
    filas = live.listar(conn)["items"]
    assert len(filas) == 1 and filas[0]["origen"] == "PISTA"
