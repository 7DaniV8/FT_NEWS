"""v7.5 (13/10/2026, caso Lucas Andrade Da Silva vs Victor Bini, ITF Quito): un 🔎 salió con «Derrota por walkover
en dobles» (de hace 7 días, ya avisada el 12/10, leída de una página de atptour.com que trajo el buscador) y
«podría favorecer a Bini @13.22» aunque el propio FT NEWS concluyó que el mercado ya la tenía. Rubén aprobó cinco
correcciones; acá se prueban (la 3, mercado, en test_v51_justificacion). Sin red."""
import json
from datetime import timedelta

from ft_news import alertas, descubridor, fuentes, radar, textos
from ft_news import taxonomia as tx
from tests.test_v5_alertas import FTR, HOY, _art, _cfg, _ciclo, _gem, _lesion, _tav

ANDRADE = {"categoria": "RETIRO_ABANDONO", "direccion": "NEGATIVA", "naturaleza": "HECHO", "nivel": "A", "fuente": "atptour.com",
           "titular": "Derrota por walkover en dobles",
           "resumen_es": "Andrade Da Silva y Gustavo Heide no disputaron su encuentro de dobles, cediendo el triunfo por walkover.",
           "fragmento_original": "Andrade Da Silva · G. Heide. 0. Winners: KESTELBOIM / ZORMANN by Walkover.", "origen": "EXTERNO"}


# ── 1 · dobles ────────────────────────────────────────────────────────────
def test_dobles_no_es_noticia_fuerte():
    assert tx.es_dobles(ANDRADE) and not tx.es_fuerte_evento(ANDRADE)
    assert tx.es_fuerte_evento(dict(ANDRADE, titular="se retiró con molestias", resumen_es="Se retiró en el 2.º set del individual.",
                                    fragmento_original="retired"))
    assert not descubridor._fuerza([dict(ANDRADE, id=1)])[0]                  # no cuenta como evidencia fuerte para 🔥


def _dobles(nombre):
    return {"sobre_jugador": True, "confianza_identidad": 0.95, "categoria": "RETIRO_ABANDONO", "direccion": "NEGATIVA",
            "naturaleza": "HECHO", "fecha_evento": HOY.strftime("%Y-%m-%d"), "titular": "Derrota por walkover en dobles",
            "resumen_es": f"{nombre} y su compañero no disputaron su partido de dobles: walkover.", "relevancia_deportiva": "",
            "fragmento_original": "Winners by Walkover (doubles)", "idioma": "en"}


def test_dobles_en_el_ciclo_no_manda_nada(conn, cfg):
    c = _cfg(cfg)
    gem, _ = _gem({"Juan Perez": _dobles("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-dobles", "Perez doubles", "Juan Perez doubles walkover")]})
    _ciclo(conn, c, tav, gem)
    assert conn.execute("SELECT COUNT(*) FROM news_evento WHERE categoria='RETIRO_ABANDONO'").fetchone()[0] == 1   # se guarda (contexto)
    assert alertas.listar(conn) == []                                          # ni 📰 ni 🔎 ni 🔥
    assert conn.execute("SELECT COUNT(*) FROM news_evaluacion WHERE tipo_alerta IN ('FUEGO','FUEGO_EXPERIMENTAL')").fetchone()[0] == 0


# ── 2 · un mismo hecho no vuelve en otra alerta del mismo tipo ────────────
def test_hechos_ya_avisados(conn):
    def alerta(i, tipo, ids, dicho=1, prueba=0):
        conn.execute("INSERT INTO news_alerta (id, tipo, clave, evento_ids_json, dicho_discord, prueba, creado_en, actualizado_en) "
                     "VALUES (?,?,?,?,?,?,?,?)", (i, tipo, f"{tipo}:{i}", json.dumps(ids), dicho, prueba, HOY.isoformat(), HOY.isoformat()))
    alerta(1, "NOTICIA", [10])
    alerta(2, "INTERESANTE", [10, 11])
    alerta(3, "INTERESANTE", [12], dicho=2)                                   # omitida: no cuenta
    alerta(4, "INTERESANTE", [13], prueba=1)                                  # prueba: no cuenta
    conn.commit()
    assert alertas.hechos_ya_avisados(conn, [10], "INTERESANTE") == 2
    assert alertas.hechos_ya_avisados(conn, [10, 11], "INTERESANTE") == 2
    assert alertas.hechos_ya_avisados(conn, [10, 14], "INTERESANTE") is None   # hay un hecho nuevo
    assert alertas.hechos_ya_avisados(conn, [12], "INTERESANTE") is None
    assert alertas.hechos_ya_avisados(conn, [13], "INTERESANTE") is None
    assert alertas.hechos_ya_avisados(conn, [11], "NOTICIA") is None          # 📰 y 🔎 se cuentan aparte


def test_misma_lesion_no_sale_en_cada_ronda(conn, cfg):
    """La 📰 y el 🔎 del partido salen; al día siguiente, con OTRO partido del mismo jugador y la misma lesión
    (sigue vigente), no sale otro 🔎."""
    c = _cfg(cfg, NEWS_EXPERIMENTAL_ACTIVO=0)
    gem, _ = _gem({"Juan Perez": _lesion("Juan Perez")})
    tav, _ = _tav({"Juan Perez": [_art("https://tennistourtalk.com/perez-wrist", "Perez wrist", "Juan Perez felt pain")]})
    _ciclo(conn, c, tav, gem)
    assert sorted(a["tipo"] for a in alertas.listar(conn)) == ["INTERESANTE", "NOTICIA"]
    alertas.marcar_dichas(conn, [{"id": a["id"], "dicho": True} for a in alertas.listar(conn)])   # salieron a Discord

    class FTR2(FTR):
        def fixtures(self, horas_adelante=72):
            f = super().fixtures()["fixtures"]
            f.append({"fixture_id": 790, "fecha": (HOY + timedelta(hours=44)).isoformat(), "torneo": "Challenger Lima",
                      "superficie": "clay", "genero": "M", "jugador1": "Perez J.", "jugador2": "Lowe T.", "odd1": 1.45,
                      "odd2": 2.80, "actualizado_en": (HOY + timedelta(hours=25)).isoformat()})
            return {"fixtures": f}
    from ft_news import tareas
    luego = HOY + timedelta(hours=26)
    tareas.ciclo(conn, cliente=FTR2(), cfg=c, tavily=tav, gemini=gem, ahora=luego)
    tareas.ciclo(conn, cliente=FTR2(), cfg=c, tavily=tav, gemini=gem, ahora=luego + timedelta(minutes=10))
    interesantes = [a for a in alertas.listar(conn) if a["tipo"] == "INTERESANTE"]
    assert len(interesantes) == 1, [(a["clave"], a["evento_ids_json"], a["dicho_discord"]) for a in interesantes]
    motivos = [r[0] for r in conn.execute("SELECT alerta_motivo FROM news_evaluacion").fetchall() if r[0]]
    assert any("HECHO_YA_AVISADO" in m for m in motivos), motivos


# ── 4 · atptour / wtatennis / itftennis solo por RSS ──────────────────────
def test_webs_oficiales_solo_por_rss(conn, cfg):
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com"])
    conn.execute("UPDATE news_fuente SET autorizada=1 WHERE dominio IN ('atptour.com','wtatennis.com')")
    conn.commit()
    doms = radar._dominios_autorizados(conn, dict(cfg, NEWS_FUENTES_AUTORIZADAS_SOLO=1))
    assert "tennistourtalk.com" in doms and not any(fuentes.solo_rss(d) for d in doms)    # el buscador no las pide
    assert fuentes.solo_rss("www.atptour.com") and fuentes.solo_rss("itftennis.com") and not fuentes.solo_rss("tennistourtalk.com")
    pagina = {"url": "https://www.atptour.com/es/scores/stats-centre/archive/2026/2895/md008", "dominio": "atptour.com",
              "titulo": "Kestelboim/Zormann", "contenido": "by Walkover"}
    assert radar._articulo_nuevo(conn, pagina, "radar", None, HOY) is None                # del buscador: no se lee
    assert radar._articulo_nuevo(conn, dict(pagina, url="https://www.atptour.com/en/news/rss-1"), "rss", None, HOY)  # del RSS: sí


# ── 5 · la confirmación dice qué está confirmado ──────────────────────────
def test_confirmacion_dice_que_esta_confirmado():
    assert textos.fiabilidad(ANDRADE) == "✅ Walkover confirmado por ATP Tour; el motivo no se informó."
    assert textos.fiabilidad(dict(ANDRADE, nivel="B", fuente="tennistourtalk.com")) == \
        "📰 Walkover informado por TennisTourTalk; sin confirmación oficial; el motivo no se informó."
    lesion = dict(ANDRADE, titular="se retiró por dolor en el hombro", resumen_es="Abandonó por dolor en el hombro.",
                  fragmento_original="retired with a shoulder injury")
    assert textos.fiabilidad(lesion) == "✅ Retiro confirmado por ATP Tour."
    assert textos.fiabilidad(dict(ANDRADE, categoria="LESION_MOLESTIA")) == "✅ Confirmado por fuente oficial (ATP Tour)."
