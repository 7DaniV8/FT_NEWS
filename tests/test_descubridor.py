"""Los 12 casos del plan (§10 Fase 3) + los nuevos del diseño v2."""
from datetime import datetime, timedelta, timezone

from ft_news import descubridor as d
from ft_news import textos

HOY = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
FRESCO = (HOY - timedelta(days=3)).isoformat()
VIEJO = (HOY - timedelta(days=45)).isoformat()
MANANA = (HOY + timedelta(hours=20)).isoformat()


def ev(cat, direccion, nivel="B", nat="DECLARACION", **k):
    base = {"id": k.pop("id", 1), "categoria": cat, "direccion": direccion, "nivel": nivel, "naturaleza": nat,
            "verificar_estado_fisico": 0, "fecha_evento": FRESCO, "resumen_es": f"{cat} de prueba",
            "fuente": "prueba", "enlace": "https://x.test/1"}
    base.update(k)
    return base


def run(cfg, **k):
    base = dict(cfg=cfg, ahora=HOY, eventos_x=[], eventos_rival=[], utr_x=12.9, utr_rival=12.4,
                utr_x_en=FRESCO, utr_rival_en=FRESCO, cuota_x=1.40, cuota_rival=2.90, inicio_partido=MANANA)
    base.update(k)
    return d.evaluar(**base)


# ── Compuerta 0: sin calibrar nunca hay 🔥 y no se afirma nada del mercado
def test_sin_calibrar_nunca_fuego(cfg):
    r = run(cfg, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")])
    assert r["tipo_alerta"] == "INTERESANTE" and r["motivo"] == "BANDAS_NO_CALIBRADAS"
    assert r["banda_utr"] == "FAVORITO" and r["banda_mercado"] == "FAVORITO"   # se registra igual
    assert "descont" not in r["conclusion"].lower()
    assert r["bandas_calibradas"] == 0


# ── Caso 1: favorito lesionado, cuota 1.40, ΔUTR 0.5 → 🔥 contra X
def test_favorito_lesionado_no_descontado(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")])
    assert r["tipo_alerta"] == "FUEGO" and r["motivo"] == "CONTRA_X"
    assert r["desvio"]["tipo"] == "ALINEADO"


# ── Caso 2: misma noticia pero el mercado ya lo tiene PAREJO siendo FAVORITO por UTR → ya descontó
def test_mercado_ya_desconto(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")], cuota_x=2.00)
    assert r["tipo_alerta"] == "INTERESANTE" and r["motivo"] == "MERCADO_YA_DESCONTO"


# ── Caso 3 (correción 2 de Rubén): sin umbral de cuota. Favorito a 1.80 con tiempo médico → 🔥
def test_sin_umbral_de_cuota_favorito_a_1_80(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA", "A", "HECHO")], utr_x=12.6, utr_rival=12.4,
            cuota_x=1.80)
    # ΔUTR 0.2 → PAREJO; cuota 1.80 → PAREJO; alineado; noticia negativa → 🔥 contra X aunque la cuota sea 1.80
    assert r["tipo_alerta"] == "FUEGO" and r["banda_utr"] == "PAREJO"


# ── Caso 4: noticia POSITIVA a cuota 2.50: el mercado no la premió → 🔥 a favor de X
def test_positiva_a_cuota_larga(cfg_calibrado):
    evs = [ev("REGRESO", "POSITIVA", "A", "HECHO", id=1), ev("RESULTADO_RECIENTE", "POSITIVA", "A", "HECHO", id=2)]
    r = run(cfg_calibrado, eventos_x=evs, utr_x=12.0, utr_rival=12.1, cuota_x=2.50)
    # ΔUTR −0.1 → PAREJO; cuota 2.50 → NO_FAVORITO: mercado más pesimista que el UTR + noticia positiva
    assert r["tipo_alerta"] == "FUEGO" and r["motivo"] == "A_FAVOR_X"
    assert r["desvio"]["tipo"] == "MERCADO_MAS_PESIMISTA"


# ── Caso 5: una sola débil (localía) → 🔎 evidencia insuficiente
def test_debil_sola_no_da_fuego(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LOCALIA", "POSITIVA", "A", "HECHO")], cuota_x=2.50, utr_x=12.0,
            utr_rival=12.1)
    assert r["tipo_alerta"] == "INTERESANTE" and r["motivo"] == "EVIDENCIA_INSUFICIENTE"


# ── Caso 6: dos débiles concordantes nivel A/B → 🔥 por acumulación
def test_acumulacion_de_debiles(cfg_calibrado):
    evs = [ev("LOCALIA", "POSITIVA", "A", "HECHO", id=1), ev("ANTECEDENTE_TORNEO", "POSITIVA", "B", id=2)]
    r = run(cfg_calibrado, eventos_x=evs, cuota_x=2.50, utr_x=12.0, utr_rival=12.1)
    assert r["tipo_alerta"] == "FUEGO" and r["modo_evidencia"] == "ACUMULACION"


# ── Caso 7: nivel C nunca da 🔥
def test_nivel_c_no_da_fuego(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA", "C", "NO_VERIFICADA")])
    assert r["tipo_alerta"] == "INTERESANTE" and r["motivo"] == "EVIDENCIA_INSUFICIENTE"


# ── Caso 8: sin cuota → SIN_MERCADO (ITF normal)
def test_sin_mercado(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")], cuota_x=None)
    assert r["motivo"] == "SIN_MERCADO" and r["banda_utr"] == "FAVORITO"


# ── Caso 9: UTR viejo
def test_utr_viejo(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")], utr_rival_en=VIEJO)
    assert r["motivo"] == "UTR_VIEJO"


# ── Caso 10: identidad dudosa → nada
def test_identidad_dudosa(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")], identidad_x=0.5)
    assert r["tipo_alerta"] == "NADA" and r["motivo"] == "IDENTIDAD_DUDOSA"


# ── Caso 11 (ajuste 2 de Rubén): regreso con antecedente físico sin verificar → 🔎, nunca 🔥
def test_regreso_sin_verificar_estado_fisico(cfg_calibrado):
    evs = [ev("LESION_MOLESTIA", "NEGATIVA", "A", "HECHO", id=1, verificar_estado_fisico=1),
           ev("REGRESO", "MIXTA", "B", id=2, verificar_estado_fisico=1)]
    r = run(cfg_calibrado, eventos_x=evs, cuota_x=2.50, utr_x=12.0, utr_rival=12.1)
    assert r["tipo_alerta"] == "INTERESANTE" and r["motivo"] == "ESTADO_FISICO_SIN_VERIFICAR"


# ── Caso 12: noticias contradictorias en ambos jugadores
def test_direccion_contradictoria(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")],
            eventos_rival=[ev("ENFERMEDAD", "NEGATIVA", id=9)])
    assert r["motivo"] == "DIRECCION_CONTRADICTORIA"


# ── Rival con noticia negativa = positiva para X
def test_noticia_del_rival(cfg_calibrado):
    r = run(cfg_calibrado, eventos_rival=[ev("LESION_MOLESTIA", "NEGATIVA", "A", "HECHO", id=9)],
            utr_x=12.0, utr_rival=12.1, cuota_x=2.50)
    assert r["tipo_alerta"] == "FUEGO" and r["motivo"] == "A_FAVOR_X" and r["direccion_neta"] == "POSITIVA"


# ── Mercado en movimiento
def test_mercado_en_movimiento(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")], cuota_apertura_x=1.20, cuota_x=1.60)
    assert r["motivo"] == "MERCADO_EN_MOVIMIENTO"


# ── Partido empezado / topes
def test_partido_empezado_y_topes(cfg_calibrado):
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")], inicio_partido=(HOY - timedelta(minutes=5)).isoformat())
    assert r["motivo"] == "PARTIDO_EMPEZADO"
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")], fuego_hoy=10)
    assert r["motivo"] == "TOPE_DIARIO"
    r = run(cfg_calibrado, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")], ya_avisado=True)
    assert r["motivo"] == "YA_AVISADO"


# ── Nivel mínimo configurable: con A, una B no alcanza
def test_nivel_minimo_a(cfg_calibrado):
    c = dict(cfg_calibrado, NEWS_NIVEL_MIN_FUEGO="A")
    r = run(c, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA", "B")])
    assert r["motivo"] == "EVIDENCIA_INSUFICIENTE"


# ── Textos: plantilla fija, sin %, sin "probabilidad"
def test_textos_sin_prohibidos(cfg_calibrado):
    evs = [ev("LESION_MOLESTIA", "NEGATIVA", resumen_es="molestias en la muñeca derecha")]
    r = run(cfg_calibrado, eventos_x=evs)
    r.update(utr_x=12.9, utr_rival=12.4, cuota_x=1.40, cuota_rival=2.90)
    t = textos.armar(r, {"torneo": "Challenger Lima", "ronda": "R16", "fecha_estimada": MANANA},
                     {"nombre": "Jugador X"}, {"nombre": "Jugador Y"}, evs)
    assert t["texto"].startswith("🔥 FULLTENIS")
    assert not textos.hay_prohibido(t["texto"]) and not textos.hay_prohibido(t["voz"])
    assert "📊 ANÁLISIS:" in t["texto"] and "Posible valor en" in t["texto"] and "📰 Fuente:" in t["texto"]  # 08/10 noche: formato nuevo; el pie lo pone FT Discord
    assert textos.hay_prohibido("tiene 62% de probabilidad")
    # sin calibrar, el texto no habla del mercado
    r2 = run(cfg_calibrado.__class__(cfg_calibrado, NEWS_BANDAS_CALIBRADAS=0), eventos_x=evs)
    r2.update(utr_x=12.9, utr_rival=12.4, cuota_x=1.40)
    t2 = textos.armar(r2, {"torneo": "T"}, {"nombre": "X"}, {"nombre": "Y"}, evs)
    assert "sin calibrar" in t2["texto"] and "descont" not in t2["texto"]
