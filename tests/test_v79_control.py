"""v7.9 (16/10/2026, Rubén: «no sé si están funcionando o leyendo o qué están haciendo»): 📋 /news/control, partido
por partido, qué está mirando y haciendo FT NEWS. Solo lectura. Sin red."""
from datetime import timedelta

from fastapi.testclient import TestClient

from ft_news import control
from ft_news.app import app
from tests.test_v74_portada import _con_fuego
from tests.test_v5_alertas import HOY


def test_control_partido_por_partido(conn, cfg):
    _con_fuego(conn, cfg)
    antes = conn.total_changes
    c = control.control(conn, ahora=HOY + timedelta(minutes=20))
    assert conn.total_changes == antes                                     # solo lectura
    assert c["ultimo_ciclo_en"] and any(p["paso"] == "partidos" and p["estado"] == "OK" for p in c["pasos"])
    lima = [p for p in c["partidos"] if p["torneo"] == "Challenger Lima"]
    assert lima, c["partidos"]
    p = lima[0]
    nombres = {p["j1"]["nombre"], p["j2"]["nombre"]}
    assert nombres == {"Juan Perez", "Luca Rossi"}
    perez = p["j1"] if p["j1"]["nombre"] == "Juan Perez" else p["j2"]
    assert perez["en_cola"] and perez["busquedas_24h"] >= 1 and perez["noticias_vigentes"] >= 1
    assert p["evaluacion"] and p["alerta"] == "FUEGO_EXPERIMENTAL" and p["alerta_discord"] in ("pendiente", "dicha", "omitida")
    r = c["resumen"]
    assert r["partidos"] >= 1 and r["evaluados"] >= 1 and r["con_alerta"] >= 1 and r["busquedas_24h_total"] >= 1


def test_control_ventana_y_paso_con_error(conn, cfg):
    from ft_news.db import estado_set
    estado_set(conn, "paso_radar", "ERROR 2026-10-16T10:00:00+00:00 Tavily 401: clave inválida")
    c = control.control(conn, ahora=HOY)
    radar = [p for p in c["pasos"] if p["paso"] == "radar"][0]
    assert radar["estado"] == "ERROR" and "401" in radar["detalle"] and radar["nombre"] == "búsqueda de noticias"
    assert c["partidos"] == [] and c["resumen"]["partidos"] == 0          # base vacía: nada que mostrar, sin errores


def test_endpoint_con_secreto():
    from ft_news import config
    with TestClient(app) as t:
        assert t.get("/news/control").status_code == 401
        r = t.get("/news/control", headers={"X-FT-News-Secret": config.NEWS_SECRET})
        assert r.status_code == 200 and "partidos" in r.json() and "pasos" in r.json()
