"""Ajuste de Rubén (08/10): un regreso NO borra la lesión; se verifica el
estado físico actual."""
from datetime import datetime, timedelta, timezone

import pytest

from ft_news import memoria as m

J = 1
HOY = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def _d(dias_atras):
    return (HOY - timedelta(days=dias_atras)).isoformat()


def _ev(cat, dias, direccion="NEGATIVA", nat="HECHO", nivel="A", **k):
    return m.nuevo_evento(J, cat, direccion, nat, nivel, _d(dias), **k)


def test_ejemplo_de_ruben_lesion_regreso_molestias():
    hist = []
    m.aplicar_reglas(hist, _ev("LESION_MOLESTIA", 20))
    m.aplicar_reglas(hist, _ev("REGRESO", 12, "POSITIVA", "DECLARACION", "B"))
    lesion, regreso = hist[0], hist[1]
    # la lesión NO queda superada: pasa a seguimiento y sigue en el historial
    assert lesion["estado"] == "EN_SEGUIMIENTO"
    assert lesion["verificar_estado_fisico"] == 1
    assert lesion["superado_por"] is None
    # el regreso nace MIXTO hasta verificar
    assert regreso["direccion"] == "MIXTA" and regreso["verificar_estado_fisico"] == 1
    # molestias nuevas: superan la lesión vieja (misma categoría) y quedan vigentes
    m.aplicar_reglas(hist, _ev("LESION_MOLESTIA", 5, nat="DECLARACION", nivel="B"))
    assert hist[0]["estado"] == "SUPERADO" and hist[2]["estado"] == "VIGENTE"
    act = m.activos(hist, J, HOY)
    assert {e["categoria"] for e in act} == {"REGRESO", "LESION_MOLESTIA"}
    assert m.estado_fisico_sin_verificar(hist, J)
    lineas = m.lectura_contextual(hist, J, HOY)
    assert len(lineas) == 3 and "hace 20 días" in lineas[0] and "superado" in lineas[0]


def test_partidos_completos_verifican_pero_no_borran():
    hist = []
    m.aplicar_reglas(hist, _ev("LESION_MOLESTIA", 20))
    m.aplicar_reglas(hist, _ev("REGRESO", 10, "POSITIVA", "DECLARACION", "B"))
    m.registrar_partido_completo(hist, J, _d(8))
    assert m.estado_fisico_sin_verificar(hist, J)          # con 1 partido todavía no
    m.registrar_partido_completo(hist, J, _d(6), retiro=True)
    assert m.estado_fisico_sin_verificar(hist, J)          # un retiro no cuenta
    m.registrar_partido_completo(hist, J, _d(4))
    assert not m.estado_fisico_sin_verificar(hist, J)      # 2 completos: verificado
    assert hist[0]["estado"] == "EN_SEGUIMIENTO"           # pero la lesión sigue en el historial
    assert hist[0]["partidos_completos_desde"] == 2


def test_abandono_despues_del_regreso_reabre():
    hist = []
    m.aplicar_reglas(hist, _ev("LESION_MOLESTIA", 20))
    m.aplicar_reglas(hist, _ev("REGRESO", 10, "POSITIVA", "DECLARACION", "B"))
    m.aplicar_reglas(hist, _ev("RETIRO_ABANDONO", 2))
    assert hist[1]["estado"] == "SUPERADO"                 # el regreso
    assert hist[0]["estado"] == "VIGENTE"                  # la lesión vuelve
    assert hist[2]["estado"] == "VIGENTE"


def test_vencimiento_por_fecha_solo_si_no_paso_nada():
    hist = []
    m.aplicar_reglas(hist, _ev("ENFERMEDAD", 10))          # vigencia 7 días
    assert m.activos(hist, J, HOY) == []
    assert hist[0]["estado"] == "VENCIDO"
    hist = []
    m.aplicar_reglas(hist, _ev("LESION_MOLESTIA", 40))
    m.aplicar_reglas(hist, _ev("REGRESO", 3, "POSITIVA", "DECLARACION", "B"))
    # el regreso extendió la vigencia de la lesión: sigue activa en seguimiento
    assert [e["categoria"] for e in m.activos(hist, J, HOY)] == ["LESION_MOLESTIA", "REGRESO"]


def test_evento_mas_viejo_no_toca_lo_nuevo():
    hist = []
    m.aplicar_reglas(hist, _ev("REGRESO", 3, "POSITIVA", "DECLARACION", "B"))
    m.aplicar_reglas(hist, _ev("LESION_MOLESTIA", 30))     # llega tarde una noticia vieja
    assert hist[0]["estado"] == "VIGENTE" and hist[1]["estado"] == "VIGENTE"


def test_validacion():
    with pytest.raises(ValueError):
        m.nuevo_evento(J, "INVENTADA", "NEGATIVA", "HECHO", "A", _d(1))
    with pytest.raises(ValueError):
        m.nuevo_evento(J, "LESION_MOLESTIA", "NEGATIVA", "NO_VERIFICADA", "A", _d(1))  # no verificada ≠ A


def test_persistencia_sqlite(conn):
    conn.execute("INSERT INTO news_jugador (nombre, nombre_norm, genero, creado_en, actualizado_en) "
                 "VALUES ('A','a','M','x','x')")
    conn.commit()
    e1 = _ev("LESION_MOLESTIA", 20)
    m.guardar_evento_db(conn, e1)
    e2 = _ev("REGRESO", 12, "POSITIVA", "DECLARACION", "B")
    m.guardar_evento_db(conn, e2)
    hist = m.historial_db(conn, J)
    assert [h["estado"] for h in hist] == ["EN_SEGUIMIENTO", "VIGENTE"]
    assert hist[0]["verificar_estado_fisico"] == 1 and hist[0]["superado_por"] is None
    e3 = _ev("LESION_MOLESTIA", 5, nat="DECLARACION", nivel="B")
    m.guardar_evento_db(conn, e3)
    hist = m.historial_db(conn, J)
    assert hist[0]["estado"] == "SUPERADO" and hist[0]["superado_por"] == e3["id"]
