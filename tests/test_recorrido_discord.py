"""Recorrido FT NEWS → FT Intelligence → FT Discord con el código real de los tres
(herramientas/recorrido_discord.py). Corre solo si FT_INTELLIGENCE_REPO y
FT_DISCORD_REPO apuntan a copias de esos repos (bash tests/correr_todo.sh los
busca al lado de este repo)."""
import os
import sys
from pathlib import Path

import pytest

FTI = os.environ.get("FT_INTELLIGENCE_REPO") or ""
DISC = os.environ.get("FT_DISCORD_REPO") or ""
pytestmark = pytest.mark.skipif(not (FTI and DISC and Path(FTI).is_dir() and Path(DISC).is_dir()),
                                reason="definir FT_INTELLIGENCE_REPO y FT_DISCORD_REPO")


def test_recorrido_completo_tres_servicios():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "herramientas"))
    import recorrido_discord as rd
    r = rd.correr_todo(FTI, DISC)
    tipos = sorted(a["tipo"] for a in r["alertas"])
    assert tipos.count("FUEGO_EXPERIMENTAL") == 1 and tipos.count("INTERESANTE") == 3 and tipos.count("NOTICIA") == 3
    # v5.2: la 🔎 "pendiente de cuota" de Quiroga quedó superada por su 🔥 (no se había dicho);
    # las otras dos 🔎 (cuota ya movida; retiro del mismo torneo) sí viajan
    superadas = [a for a in r["alertas"] if a["dicho_discord"] == 2]
    assert len(superadas) == 1 and superadas[0]["tipo"] == "INTERESANTE" and superadas[0]["dicho_motivo"] == "SUPERADA_POR_FUEGO_EXPERIMENTAL"
    viajan = len(r["alertas"]) - len(superadas)
    # FT Intelligence: todas emitidas una vez; segunda pasada no repite
    assert r["intel"]["pasadas"][0]["emitidas"] == viajan and r["intel"]["pasadas"][1]["emitidas"] == 0
    assert len({s["clave"] for s in r["intel"]["senales"]}) == len(r["intel"]["senales"])
    # FT Discord: un mensaje por señal, segundo ciclo nada
    assert r["discord"]["ciclos"][0]["texto"] == viajan and r["discord"]["ciclos"][1]["texto"] == 0
    pubs = r["discord"]["publicados"]
    assert any(p.startswith("**🔥 FULLTENNIS · POSIBLE VALOR EXPERIMENTAL**") for p in pubs)
    assert any(p.startswith("**🔎 FULLTENNIS · PARTIDO INTERESANTE**") for p in pubs)
    assert any(p.startswith("**📰 FULLTENNIS · NOTICIA IMPORTANTE**") for p in pubs)
    for p in pubs:
        assert "%" not in p and "http" not in p and "no es una recomendación" in p      # sin enlaces (v6)
        assert len(p) < 600                                                                # cortos
    fuego = [p for p in pubs if p.startswith("**🔥")][0]
    # formato definitivo (Rubén 09/10 23:13): favorecido en MAYÚSCULAS, cuota al lado, motivo, cuota post-noticia, etiqueta experimental
    assert "🎾 Luca Bertolini vs Mateo Quiroga\n🏆 Challenger Lima\n📊 UTR: 12.41 vs 12.85\n🟢 JUGADOR FAVORECIDO: LUCA BERTOLINI\n💰 CUOTA: 2.85\n🚨 MOTIVO: Molestias en el tobillo derecho.\n📰 Informado por Punto de Break; sin confirmación oficial.\n📈 La cuota de Quiroga sigue en 1.42 después de la noticia.\n⚠️ Posible oportunidad sin validar estadísticamente." in fuego
    noticia = [p for p in pubs if "Mateo Quiroga\n" in p and p.startswith("**📰")][0]
    assert "🚨 LESIÓN: Molestias en el tobillo derecho.\n📰 Informado por Punto de Break; sin confirmación oficial.\n🔴 PERJUDICA A: MATEO QUIROGA\n🟢 PODRÍA FAVORECER A: LUCA BERTOLINI\n💰 Quiroga 1.42 | Bertolini 2.85" in noticia
    inter = [p for p in pubs if p.startswith("**🔎") and "Soler" in p][0]
    assert "💰 Cuotas: 1.65 vs 2.20\n🚨 NOTICIA: Molestias en el hombro.\n🗣️ Según declaraciones recogidas por Punto de Break; sin confirmación oficial.\n🟢 PODRÍA FAVORECER A: HANNA KOWAL @2.20\n⏳ Pendiente de confirmar la reacción del mercado." in inter
    wo = [p for p in pubs if p.startswith("**🔎") and "Whitlock" in p][0]
    assert "FAVORECER" not in wo and "⚠️ El partido podría no jugarse (retiro en el mismo torneo)." in wo
    # FT NEWS marcó todo lo que viajó como dicho
    assert all(a["dicho_discord"] == 1 for a in r["alertas"] if a["dicho_discord"] != 2)
    assert any(v.startswith("Atención FullTennis. Noticia. Posible valor experimental, sin validar. Bertolini, cuota 2.85, contra Quiroga.") for v in r["discord"]["voces"])

    # v7.3: el acuse de FT Discord vuelve a FT NEWS: cada alerta que viajó queda PUBLICADA en la comunidad
    viajaron = [a for a in r["alertas"] if a["dicho_discord"] == 1]
    assert r["vuelta"][0]["reportadas"] == viajan and r["vuelta"][0]["publicadas"] == viajan and r["vuelta"][1]["reportadas"] == 0
    assert all(a["recorrido"]["estado"] == "PUBLICADA" and a["publicado_canal"] == "comunidad" for a in viajaron)
    assert all(a["recorrido"]["pasos"][2]["detalle"] == "Publicada en el canal de la comunidad." for a in viajaron)
    assert r["discord"]["admin"] == [] and all(x["canal"] == "comunidad" for x in r["discord"]["acuses"])
    assert superadas[0]["recorrido"]["estado"] == "REEMPLAZADA"                        # no salir a propósito no es un fallo


def test_prueba_va_solo_al_canal_de_administradores():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "herramientas"))
    import recorrido_discord as rd
    r = rd.correr_todo(FTI, DISC, con_prueba=True)
    # sale SOLO por el canal de administradores, sin voz, marcada PRUEBA desde la primera línea
    assert len(r["discord"]["admin"]) == 1 and r["discord"]["admin"][0].startswith("**🧪 PRUEBA DE FT NEWS — NO ES UNA OPORTUNIDAD**")
    assert not any("PRUEBA" in p for p in r["discord"]["publicados"])           # nunca en la comunidad
    assert not any("Prueba de FT NEWS" in v for v in r["discord"]["voces"])     # ni por voz
    # FT NEWS ve los tres pasos completos, con el canal correcto, y la prueba no está en el historial
    p = r["prueba"]
    assert p["estado"] == "PUBLICADA" and [x["estado"] for x in p["pasos"]] == ["✅", "✅", "✅"]
    assert p["pasos"][2]["detalle"] == "Publicada en el canal de administradores."
    assert all(a["tipo"] != "PRUEBA" for a in r["alertas"])
    # las alertas reales siguen yendo a la comunidad
    assert all(a["publicado_canal"] == "comunidad" for a in r["alertas"] if a["dicho_discord"] == 1)


def test_prueba_sin_canal_de_admin_no_sale_por_ningun_lado():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "herramientas"))
    import recorrido_discord as rd
    r = rd.correr_todo(FTI, DISC, con_prueba=True, canal_admin=False)
    assert r["discord"]["admin"] == [] and not any("PRUEBA" in p for p in r["discord"]["publicados"])
    p = r["prueba"]
    assert p["estado"] == "FALLO" and p["pasos"][2]["estado"] == "❌" and "falta DISCORD_CANAL_ADMIN_ID" in p["resumen"]
