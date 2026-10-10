"""v7 (10/10/2026, Rubén): carga física por clases + todo en palabras simples.

  1. Gea vs Humbert: 3 partidos y 9 sets en 7 días → carga NORMAL, sin evento,
     sin 🔥; la lectura dice exactamente lo que Rubén pidió.
  2. Una misma condición no se cuenta varias veces (dedupe en memoria y en el
     descubridor); los duplicados viejos vencen.
  3. Carga EXCEPCIONAL sí deja evento y se investiga, pero sola nunca es 🔥.
  4. Inactividad: se guarda e informa, sin ventaja ni castigo.
  5. Una lesión real externa sigue pudiendo ser 🔥 (con carga normal al lado).
  6. explicar: sin códigos en nada que vea el usuario; endpoints con lectura.
"""
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from ft_news import config, contexto, descubridor, explicar, fuentes, memoria, tareas
from ft_news import jugadores as jg
from ft_news.app import app

HOY = datetime(2026, 10, 10, 15, tzinfo=timezone.utc)
H = {"X-FT-News-Secret": "secreto-pruebas"}


def _h(dias, jugador, rival, score="6-4 6-4", torneo="Shanghai Masters", pais="China", horas=0):
    tres = score.count("-") == 3
    return {"match_id": 1, "player_id": 10, "opponent_id": 11, "fecha": (HOY - timedelta(days=dias, hours=horas)).isoformat(),
            "nivel_torneo": "atp", "superficie": "hard", "score": score, "games_ganados": 12, "games_perdidos": 8,
            "sets_ganados": 2, "sets_perdidos": 1 if tres else 0, "torneo": torneo, "jugador": jugador,
            "rival": rival, "pais_torneo": pais}


class FTR:
    def __init__(self, historial, fixtures=None):
        self._h = historial
        self._f = fixtures

    def utr_padron(self, desde_id=0, limite=2000):
        return {"jugadores": [
            {"player_id": 10, "nombre_ftr": "Arthur Gea", "nombre_utr": "Arthur Gea", "genero": "M", "nacionalidad": "FRA",
             "utr_player_id": 501, "utr_singles": 15.81, "fecha_captura": (HOY - timedelta(days=2)).isoformat()},
            {"player_id": 11, "nombre_ftr": "Ugo Humbert", "nombre_utr": "Ugo Humbert", "genero": "M", "nacionalidad": "FRA",
             "utr_player_id": 502, "utr_singles": 15.75, "fecha_captura": (HOY - timedelta(days=2)).isoformat()},
            {"player_id": 12, "nombre_ftr": "Pedro Tercero", "nombre_utr": "Pedro Tercero", "genero": "M", "nacionalidad": "ESP",
             "utr_player_id": 503, "utr_singles": 14.9, "fecha_captura": (HOY - timedelta(days=2)).isoformat()}],
            "siguiente_desde_id": None}

    def fixtures(self, horas_adelante=72):
        return {"fixtures": self._f or [{"fixture_id": 148, "fecha": (HOY + timedelta(hours=20)).isoformat(), "torneo": "Shanghai Masters",
                                         "superficie": "hard", "genero": "M", "jugador1": "Gea A.", "jugador2": "Humbert U.",
                                         "odd1": 2.01, "odd2": 1.79}]}

    def calibracion(self):
        return {"veredicto": "SIN_DATOS", "muestra": 0, "razones": []}

    def historial(self, desde_fecha, hasta_fecha=None):
        return {"partidos": self._h}

    def antecedentes(self, player_id, torneo):
        return {"partidos": []}

    def defensa(self):
        return {"jugadores": []}


def _cfg(cfg):
    fuentes_ok = dict(cfg, NEWS_ACTIVO=1, NEWS_BANDAS_AUTO=0)
    return fuentes_ok


GEA_3_PARTIDOS = [_h(1, "Arthur Gea", "Rival Uno", "6-4 3-6 7-5"), _h(3, "Arthur Gea", "Rival Dos", "7-6 6-7 6-3"),
                  _h(5, "Arthur Gea", "Rival Tres", "6-2 4-6 6-4"), _h(2, "Ugo Humbert", "Otro Uno", "6-3 6-3")]


# ── 1 · Gea vs Humbert ───────────────────────────────────────────────────
def test_gea_humbert_3_partidos_9_sets_es_normal_y_no_hay_fuego(conn, cfg):
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    c = _cfg(cfg)
    r = tareas.ciclo(conn, cliente=FTR(GEA_3_PARTIDOS), cfg=c, ahora=HOY)
    gea = jg.buscar_por_nombre(conn, "Arthur Gea")
    hum = jg.buscar_por_nombre(conn, "Ugo Humbert")
    # carga guardada, clase NORMAL, texto de Rubén
    carga = contexto.carga_de(conn, gea["id"])
    assert carga["partidos_7d"] == 3 and carga["sets_7d"] == 9 and carga["tres_sets_7d"] == 3
    assert carga["clase"] == "NORMAL"
    assert carga["texto"] == "Arthur Gea disputó 3 partido(s) y 9 sets en 7 días (3 a tres sets). No hay evidencia suficiente para considerarlo fatigado."
    # sin evento de carga, sin 🔥
    assert not any(e["categoria"] == "CARGA_FISICA" for e in memoria.historial_db(conn, gea["id"]))
    assert conn.execute("SELECT COUNT(*) FROM news_evaluacion WHERE tipo_alerta IN ('FUEGO','FUEGO_EXPERIMENTAL')").fetchone()[0] == 0
    assert r["pasos"]["contexto"]["carga"]["NORMAL"] == 2 and r["pasos"]["contexto"]["eventos"] == 0
    # la lectura simple de ese partido (sin evaluación porque no hay eventos) es el formato pedido
    ev = {"tipo_alerta": "INTERESANTE", "motivo": "SIN_NOTICIA_EXTERNA_FUERTE", "utr_x": 15.81, "utr_rival": 15.75,
          "cuota_x": 2.01, "cuota_rival": 1.79}
    l = explicar.evaluacion(ev, {"torneo": "Shanghai Masters"}, gea, hum, [], carga, contexto.carga_de(conn, hum["id"]), c)
    assert l["lineas"] == [
        "🔎 FULLTENNIS · PARTIDO EN ANÁLISIS", "🎾 Arthur Gea vs Ugo Humbert", "🏆 Shanghai Masters", "📊 UTR: 15.81 vs 15.75",
        "💰 Gea 2.01 | Humbert 1.79", "⚖️ NIVEL: Jugadores prácticamente igualados por UTR.",
        "🟡 CARGA FÍSICA: Arthur Gea disputó 3 partido(s) y 9 sets en 7 días (3 a tres sets). No hay evidencia suficiente para considerarlo fatigado.",
        "🧭 CONCLUSIÓN: No se identifica una ventaja clara por desgaste físico."]
    assert l["favorecido"] is None
    for prohibido in ("CONTRA_X", "FUEGO", "PAREJO", "ALINEADO", "DIRECCIÓN NETA", "DESCUBRIDOR", "SIN_NOTICIA"):
        assert prohibido not in l["texto"]


# ── 2 · duplicados ───────────────────────────────────────────────────────
def test_una_misma_condicion_no_se_cuenta_varias_veces(conn, cfg):
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    c = _cfg(cfg)
    # Gea con 6 partidos en 7 días (EXCEPCIONAL) y DOS partidos próximos distintos (hoy y pasado mañana)
    hist = [_h(i, "Arthur Gea", f"Rival {i}", "6-4 3-6 7-5") for i in range(1, 7)]
    fx = [{"fixture_id": 148, "fecha": (HOY + timedelta(hours=20)).isoformat(), "torneo": "Shanghai Masters", "superficie": "hard",
           "genero": "M", "jugador1": "Gea A.", "jugador2": "Humbert U.", "odd1": 2.01, "odd2": 1.79},
          {"fixture_id": 149, "fecha": (HOY + timedelta(hours=60)).isoformat(), "torneo": "Shanghai Masters", "superficie": "hard",
           "genero": "M", "jugador1": "Gea A.", "jugador2": "Tercero P.", "odd1": 1.50, "odd2": 2.60}]
    gea_id = None
    # versiones anteriores dejaban uno por fixture: simulamos dos viejos vigentes
    tareas.ciclo(conn, cliente=FTR([], fx), cfg=c, ahora=HOY - timedelta(hours=12))
    gea = jg.buscar_por_nombre(conn, "Arthur Gea")
    gea_id = gea["id"]
    for k in (1, 2):
        e = memoria.nuevo_evento(gea_id, "CARGA_FISICA", "NEGATIVA", "HECHO", "A", (HOY - timedelta(hours=2)).isoformat(),
                                 fuente=contexto.FUENTE, enlace=f"contexto:viejo{k}", resumen_es="4 partidos (regla vieja)")
        memoria.guardar_evento_db(conn, e)
    assert len([e for e in memoria.activos(memoria.historial_db(conn, gea_id), gea_id, HOY) if e["categoria"] == "CARGA_FISICA"]) == 2
    r = tareas.ciclo(conn, cliente=FTR(hist, fx), cfg=c, ahora=HOY)
    act = [e for e in memoria.activos(memoria.historial_db(conn, gea_id), gea_id, HOY) if e["categoria"] == "CARGA_FISICA"]
    assert len(act) == 1, act                                   # uno solo vigente, aunque haya dos partidos y dos viejos
    assert act[0]["direccion"] == "NEGATIVA" and "carga excepcional" in act[0]["resumen_es"]
    assert r["pasos"]["contexto"]["duplicados_vencidos"] >= 1
    # el descubridor tampoco cuenta repetidos aunque se los pasen
    repetidos = [dict(act[0], id=100 + i) for i in range(4)]
    assert len(descubridor.sin_repetidos(repetidos)) == 1
    # y no hay 🔥 por carga sola, en ninguno de los dos partidos
    tipos = [r["tipo_alerta"] for r in conn.execute("SELECT tipo_alerta FROM news_evaluacion").fetchall()]
    assert tipos and all(t == "INTERESANTE" for t in tipos)
    assert all(r["motivo"] == "SIN_NOTICIA_EXTERNA_FUERTE" for r in conn.execute("SELECT motivo FROM news_evaluacion").fetchall())


# ── 3 · excepcional: se investiga, no decide ─────────────────────────────
def test_carga_excepcional_se_investiga_pero_sola_no_es_fuego(conn, cfg):
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    c = _cfg(cfg)
    hist = [_h(i, "Arthur Gea", f"Rival {i}", "6-4 3-6 7-5") for i in range(1, 7)] + [_h(2, "Ugo Humbert", "Otro", "6-3 6-3")]
    tareas.ciclo(conn, cliente=FTR(hist), cfg=c, ahora=HOY)
    gea = jg.buscar_por_nombre(conn, "Arthur Gea")
    carga = contexto.carga_de(conn, gea["id"])
    assert carga["clase"] == "EXCEPCIONAL" and carga["partidos_7d"] == 6
    assert "carga excepcional" in carga["texto"] and "se investiga" in carga["texto"]
    cola = conn.execute("SELECT prioridad, motivo FROM news_jugador_cola WHERE jugador_id=?", (gea["id"],)).fetchone()
    assert cola["prioridad"] == 0 and cola["motivo"] == "CARGA_EXCEPCIONAL"
    e = conn.execute("SELECT * FROM news_evaluacion").fetchone()
    assert e["tipo_alerta"] == "INTERESANTE" and e["motivo"] == "SIN_NOTICIA_EXTERNA_FUERTE"
    l = json.loads(e["lectura_json"])
    assert any(l_.startswith("🟡 CARGA FÍSICA: Arthur Gea disputó 6 partido(s)") for l_ in l["lineas"])
    assert l["lineas"][-1] == "🧭 CONCLUSIÓN: La carga reciente es excepcional y se está investigando; sin una noticia que lo confirme, no se afirma una ventaja."
    assert l["favorecido"] is None and "🟢" not in l["texto"]
    # al ciclo siguiente la carga baja (los partidos salen de la ventana) → el evento vence solo
    hist2 = [_h(i + 6, "Arthur Gea", f"Rival {i}", "6-4 3-6 7-5") for i in range(1, 7)] + [_h(2, "Ugo Humbert", "Otro", "6-3 6-3")]
    tareas.ciclo(conn, cliente=FTR(hist2), cfg=c, ahora=HOY + timedelta(hours=2))   # el Motor 3 corre cada hora
    assert not [x for x in memoria.activos(memoria.historial_db(conn, gea["id"]), gea["id"], HOY + timedelta(hours=2)) if x["categoria"] == "CARGA_FISICA"]
    assert contexto.carga_de(conn, gea["id"])["clase"] == "NORMAL"


# ── 4 · inactividad ──────────────────────────────────────────────────────
def test_inactividad_se_informa_sin_ventaja(conn, cfg):
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    c = _cfg(cfg)
    hist = [_h(12, "Arthur Gea", "Rival Viejo", "6-4 6-4"), _h(2, "Ugo Humbert", "Otro", "6-3 6-3")]
    tareas.ciclo(conn, cliente=FTR(hist), cfg=c, ahora=HOY)
    gea = jg.buscar_por_nombre(conn, "Arthur Gea")
    carga = contexto.carga_de(conn, gea["id"])
    assert carga["clase"] == "INACTIVIDAD" and carga["ultimo_hace_dias"] == 12
    assert carga["texto"] == "Arthur Gea lleva 12 días sin competir. Llega descansado, pero puede faltarle ritmo."
    assert not any(e["categoria"] == "CARGA_FISICA" for e in memoria.historial_db(conn, gea["id"]))
    # sin datos
    assert contexto.clasificar_carga(contexto.carga([], HOY), c) == "SIN_DATOS"
    # umbrales configurables
    assert contexto.clasificar_carga(carga, dict(c, NEWS_CARGA_INACTIVIDAD_DIAS=20)) == "NORMAL"


# ── 5 · lesión real + carga normal → sigue pudiendo ser 🔥 ─────────────────
def test_lesion_externa_con_carga_normal_sigue_siendo_investigable(cfg):
    fresco = (HOY - timedelta(days=1)).isoformat()
    ext = {"id": 1, "categoria": "LESION_MOLESTIA", "direccion": "NEGATIVA", "nivel": "B", "naturaleza": "DECLARACION",
           "verificar_estado_fisico": 0, "fecha_evento": fresco, "resumen_es": "molestia en el hombro", "titular": "Molestia en el hombro",
           "fuente": "prueba", "enlace": "https://x.test/1", "articulo_id": 5, "origen": "EXTERNO", "jugador_id": 7}
    interno = {"id": 2, "categoria": "CARGA_FISICA", "direccion": "NEGATIVA", "nivel": "A", "naturaleza": "HECHO",
               "verificar_estado_fisico": 0, "fecha_evento": fresco, "resumen_es": "6 partidos", "fuente": contexto.FUENTE,
               "enlace": "contexto:1", "origen": "INTERNO", "jugador_id": 7}
    base = dict(cfg=cfg, ahora=HOY, eventos_rival=[], utr_x=12.9, utr_rival=12.4, utr_x_en=fresco, utr_rival_en=fresco,
                cuota_x=1.40, cuota_rival=2.90, inicio_partido=(HOY + timedelta(hours=20)).isoformat())
    r = descubridor.evaluar(eventos_x=[ext], **base)
    assert r["tipo_alerta"] == "FUEGO_EXPERIMENTAL" and r["motivo"] == "CONTRA_X"
    r2 = descubridor.evaluar(eventos_x=[ext, interno, dict(interno, id=3), dict(interno, id=4)], **base)
    assert r2["tipo_alerta"] == "FUEGO_EXPERIMENTAL" and len(r2["eventos_usados"]) == 2   # la carga repetida cuenta una vez
    r3 = descubridor.evaluar(eventos_x=[interno, dict(interno, id=3)], **base)
    assert r3["tipo_alerta"] == "INTERESANTE" and r3["motivo"] == "SIN_NOTICIA_EXTERNA_FUERTE"
    # lectura de la 🔥: favorecido en mayúsculas, cuota, sin códigos
    jx, jr = {"id": 7, "nombre": "Arthur Gea"}, {"id": 8, "nombre": "Ugo Humbert"}
    l = explicar.evaluacion(dict(r2, utr_x=12.9, utr_rival=12.4, cuota_x=1.40, cuota_rival=2.90), {"torneo": "Shanghai Masters"}, jx, jr, [ext, interno])
    assert l["lineas"][0] == "🔥 FULLTENNIS · POSIBLE VALOR EXPERIMENTAL"
    assert "🚨 NOTICIA: Gea — Molestia en el hombro." in l["lineas"]
    assert "🔴 PERJUDICA A: Arthur Gea" in l["lineas"] and "🟢 JUGADOR FAVORECIDO: UGO HUMBERT" in l["lineas"] and "💰 CUOTA: 2.90" in l["lineas"]
    assert l["lineas"][-1].startswith("🧭 CONCLUSIÓN: La noticia podría favorecer a Ugo Humbert") and "experimental" in l["lineas"][-1]
    assert "CONTRA_X" not in l["texto"] and "%" not in l["texto"]


# ── 6 · todo en palabras ─────────────────────────────────────────────────
def test_explicar_sin_codigos():
    for cod in list(explicar.MOTIVOS) + ["REPETIDA:12", "SUPERADA_POR_VALIDADA", "VENCIDA:13h", "error: boom", "RIVAL_SIN_INVESTIGAR:Humbert", "CARGA_EXCEPCIONAL"]:
        t = explicar.motivo_simple(cod)
        assert t and t.endswith(".") and "_" not in t and not any(w.isupper() and len(w) > 3 for w in t.replace(".", "").split()), (cod, t)
    assert explicar.motivo_simple("ALGO_NUEVO_RARO") == "Algo nuevo raro."
    assert explicar.categoria_es("LESION_MOLESTIA") == "Lesión o molestia" and explicar.categoria_es("CARGA_FISICA") == "Carga física"
    ev = {"categoria": "LESION_MOLESTIA", "direccion": "NEGATIVA", "titular": "Molestia en el hombro", "articulo_id": 3, "origen": "EXTERNO"}
    assert explicar.evento_simple(ev, "Gea") == "🔴 Lesión o molestia · perjudica a Gea: Molestia en el hombro."
    evi = {"categoria": "CARGA_FISICA", "direccion": "MIXTA", "resumen_es": "5 partidos en 7 días", "fuente": contexto.FUENTE, "enlace": "contexto:1", "origen": "INTERNO"}
    assert explicar.evento_simple(evi, "Gea") == "🟡 Carga física · Gea: puede pesar en los dos sentidos (dato calculado por nosotros): 5 partidos en 7 días."
    a = {"tipo": "INTERESANTE", "evidencia": {"eventos_x": [{"categoria": "LESION_MOLESTIA"}], "pendiente": ["cuota del mercado"]}}
    assert explicar.alerta_simple(a) == "Noticia externa (lesión o molestia) y los dos jugadores investigados. Pendiente: cuota del mercado."
    assert explicar.alerta_simple({"tipo": "FUEGO_EXPERIMENTAL", "evidencia": {}}).endswith("(lectura experimental).")


def test_endpoints_con_lectura_y_diagnostico_de_carga(conn, cfg, monkeypatch):
    monkeypatch.setattr(config, "NEWS_SECRET", "secreto-pruebas")
    monkeypatch.setattr("ft_news.config.DB_PATH", __import__("pathlib").Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    c = _cfg(cfg)
    hist = [_h(i, "Arthur Gea", f"Rival {i}", "6-4 3-6 7-5") for i in range(1, 7)] + [_h(2, "Ugo Humbert", "Otro", "6-3 6-3")]
    tareas.ciclo(conn, cliente=FTR(hist), cfg=c, ahora=HOY)
    gea = jg.buscar_por_nombre(conn, "Arthur Gea")
    with TestClient(app) as t:
        hoy = t.get("/news/hoy", headers=H).json()
        e = hoy["evaluaciones"][0]
        assert e["lectura"]["lineas"][0] == "🔎 FULLTENNIS · PARTIDO EN ANÁLISIS" and e["lectura"]["resumen"]
        assert e["motivo_simple"] == explicar.MOTIVOS["SIN_NOTICIA_EXTERNA_FUERTE"]
        assert all(x.get("categoria_es") and x.get("texto_simple") for x in hoy["eventos"])
        det = t.get(f"/news/evaluaciones/{e['id']}", headers=H).json()
        assert det["lectura"]["lineas"] == e["lectura"]["lineas"] and det["carga"]["x"]["clase"] == "EXCEPCIONAL"
        assert det["evaluacion"]["motivo_simple"] and all(u.get("texto_simple") for u in det["eventos_usados"])
        m = t.get(f"/news/jugadores/{gea['id']}/memoria", headers=H).json()
        assert m["carga"]["clase"] == "EXCEPCIONAL" and m["lectura_simple"] and "CARGA_FISICA" not in " ".join(m["lectura_simple"])
        d = t.get("/news/diagnostico?dias=7", headers=H).json()["carga"]
        assert d["regla_anterior"]["habria_marcado"] >= 1 and d["regla_v7"]["muestras_por_clase"]["EXCEPCIONAL"] == 1
        assert d["regla_v7"]["muestras_por_clase"]["NORMAL"] == 1 and d["evaluaciones"]["solo_estadistica_interna"] == {"INTERESANTE": 1}
        assert d["evaluaciones"]["con_carga"] == {"INTERESANTE": 1} and d["duplicados"]["evaluaciones_con_carga_repetida"] == 0
        assert d["distribucion"]["variables"]["partidos_7d"]["percentiles"]["n"] == 2
        assert "resultados_del_cargado" in d
