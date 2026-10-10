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
    # v5 (Rubén 09/10): con bandas sin calibrar y TODO lo demás en regla, sale
    # 🔥 EXPERIMENTAL (nunca FUEGO validado) y lo dice; con el experimental
    # apagado, 🔎 BANDAS_NO_CALIBRADAS como antes.
    r = run(cfg, eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")])
    assert r["tipo_alerta"] == "FUEGO_EXPERIMENTAL" and r["motivo"] == "CONTRA_X"
    assert r["banda_utr"] == "FAVORITO" and r["banda_mercado"] == "FAVORITO"
    assert "EXPERIMENTAL" in r["conclusion"] and "sin validar" in r["conclusion"]
    assert r["bandas_calibradas"] == 0 and r["externo"] == 1
    assert any("sin validar" in x for x in r["explicaciones"])
    r2 = run(dict(cfg, NEWS_EXPERIMENTAL_ACTIVO=0), eventos_x=[ev("LESION_MOLESTIA", "NEGATIVA")])
    assert r2["tipo_alerta"] == "INTERESANTE" and r2["motivo"] == "BANDAS_NO_CALIBRADAS"
    assert "descont" not in r2["conclusion"].lower()


def test_solo_contexto_interno_nunca_fuego(cfg_calibrado):
    # v5: la carga calculada por nosotros no es una noticia: acompaña, no dispara.
    e = ev("CARGA_FISICA", "NEGATIVA", "A", "HECHO")
    e.update(fuente="rankingftr.interno", enlace="contexto:7", articulo_id=None)
    r = run(cfg_calibrado, eventos_x=[e])
    assert r["tipo_alerta"] == "INTERESANTE" and r["motivo"] == "SIN_NOTICIA_EXTERNA_FUERTE" and r["externo"] == 0


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
    # v5: dos débiles concordantes alcanzan como evidencia, pero sin una noticia
    # externa FUERTE no hay 🔥 (Rubén: "no una simple diferencia UTR" ni contexto solo).
    evs = [ev("LOCALIA", "POSITIVA", "A", "HECHO", id=1), ev("ANTECEDENTE_TORNEO", "POSITIVA", "B", id=2)]
    r = run(cfg_calibrado, eventos_x=evs, cuota_x=2.50, utr_x=12.0, utr_rival=12.1)
    assert r["tipo_alerta"] == "INTERESANTE" and r["modo_evidencia"] == "ACUMULACION"
    assert r["motivo"] == "SIN_NOTICIA_EXTERNA_FUERTE"
    # con una fuerte externa además, sí
    evs2 = evs + [ev("REGRESO", "POSITIVA", "B", "DECLARACION", id=3)]
    r2 = run(cfg_calibrado, eventos_x=evs2, cuota_x=2.50, utr_x=12.0, utr_rival=12.1)
    assert r2["tipo_alerta"] == "FUEGO"


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
    assert t["texto"].startswith("🔥 FULLTENNIS · POSIBLE VALOR POR NOTICIAS")
    assert not textos.hay_prohibido(t["texto"]) and not textos.hay_prohibido(t["voz"])
    # v6 (formato definitivo): favorecido en MAYÚSCULAS con su cuota, motivo, sin enlaces
    assert "🟢 JUGADOR FAVORECIDO: JUGADOR Y" in t["texto"] and "💰 CUOTA: 2.90" in t["texto"] and "🚨 MOTIVO:" in t["texto"]
    assert "http" not in t["texto"] and "✅ Lectura UTR/cuota validada" in t["texto"]
    assert t["voz"].startswith("Posible valor por noticias. Jugador Y, cuota 2.90, contra Jugador X.")
    assert textos.hay_prohibido("tiene 62% de probabilidad")
    # sin calibrar (v5): sale como EXPERIMENTAL y lo dice; nunca afirma "descontó" a secas
    r2 = run(cfg_calibrado.__class__(cfg_calibrado, NEWS_BANDAS_CALIBRADAS=0), eventos_x=evs)
    r2.update(utr_x=12.9, utr_rival=12.4, cuota_x=1.40)
    t2 = textos.armar(r2, {"torneo": "T"}, {"nombre": "X"}, {"nombre": "Y"}, evs)
    assert t2["texto"].startswith("🔥 FULLTENNIS · POSIBLE VALOR EXPERIMENTAL") and "⚠️ Posible oportunidad sin validar estadísticamente." in t2["texto"]
    assert not textos.hay_prohibido(t2["texto"])
    # sin calibrar y con el experimental apagado: no habla del mercado
    r3 = run(cfg_calibrado.__class__(cfg_calibrado, NEWS_BANDAS_CALIBRADAS=0, NEWS_EXPERIMENTAL_ACTIVO=0), eventos_x=evs)
    r3.update(utr_x=12.9, utr_rival=12.4, cuota_x=1.40)
    t3 = textos.armar(r3, {"torneo": "T"}, {"nombre": "X"}, {"nombre": "Y"}, evs)
    assert t3["texto"].startswith("🔎 FULLTENNIS · PARTIDO INTERESANTE") and "⚠️ Sin lectura de mercado validada." in t3["texto"]
    assert "descont" not in t3["texto"] and "JUGADOR FAVORECIDO" not in t3["texto"]
