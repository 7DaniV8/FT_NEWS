"""
ft_news/descubridor.py — Motor 4, descubridor autónomo v2 (diseño §4),
PURO: recibe datos ya leídos y devuelve una evaluación. Sin IO, sin IA.

Orden de compuertas (si una falla, baja al tipo indicado con su motivo):
  0  bandas sin calibrar (NEWS_BANDAS_CALIBRADAS=0) → nunca 🔥; todo 🔎
     con motivo BANDAS_NO_CALIBRADAS y SIN afirmar nada del mercado
     (ajuste de Rubén 08/10: "no afirmar que el mercado no descontó una
     noticia sin evidencia suficiente").
  1  identidad confirmada                         → NADA  IDENTIDAD_DUDOSA
  2  hay eventos activos                          → NADA  SIN_EVENTOS
  3  partido no empezado                          → NADA  PARTIDO_EMPEZADO
  4  dirección neta clara (no MIXTA/NEUTRA, no contradictoria,
     no estado físico sin verificar)              → 🔎   CONTEXTO / DIRECCION_CONTRADICTORIA /
                                                          ESTADO_FISICO_SIN_VERIFICAR
  5  evidencia: nivel ≥ mínimo y (categoría fuerte o ≥2 débiles concordantes)
                                                  → 🔎   EVIDENCIA_INSUFICIENTE
  6  UTR de ambos y fresco                        → 🔎   SIN_UTR / UTR_VIEJO
  7  cuota disponible                             → 🔎   SIN_MERCADO
  8  mercado no se movió ya hacia la noticia      → 🔎   MERCADO_EN_MOVIMIENTO
  9  cruce dirección × desvío (tabla §4 paso 4)   → 🔥   o 🔎 MERCADO_YA_DESCONTO
 10  tope diario / un 🔥 por jugador y torneo     → 🔎   TOPE_DIARIO / YA_AVISADO

Tipos de alerta: FUEGO (🔥 posible valor por noticias, bandas validadas),
FUEGO_EXPERIMENTAL (🔥 experimental: todas las compuertas menos la 8),
INTERESANTE (🔎), NOTICIA (📰, la decide alertas.py desde el radar), NADA.
v5 (09/10/2026, Rubén): compuerta 5b — sin noticia EXTERNA fuerte no hay 🔥
(la carga calculada acompaña, no decide); y "explicaciones" del mercado.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ft_news import bandas as bd
from ft_news import taxonomia as tx
from ft_news.config import cortes_bandas

VERSION_MOTOR = "news-descubridor-v4-claro"
_RANGO_NIVEL = {"A": 3, "B": 2, "C": 1}
FUENTE_INTERNA = "rankingftr.interno"


def es_externo(e: dict) -> bool:
    """Noticia de una fuente externa (artículo) vs dato calculado por nosotros
    (Motor 3: carga, antecedentes, viaje...). v5: una 🔥 exige lo primero."""
    if e.get("origen") in ("EXTERNO", "INTERNO"):
        return e["origen"] == "EXTERNO"
    if e.get("articulo_id"):
        return True
    return str(e.get("fuente") or "") != FUENTE_INTERNA and not str(e.get("enlace") or "").startswith("contexto:")


def sin_repetidos(eventos: list[dict]) -> list[dict]:
    """v7 (Rubén: "una misma condición no se contabiliza varias veces"): un
    evento calculado por categoría (queda el más nuevo) y un evento externo por
    artículo (o por categoría + resumen si no tiene artículo)."""
    vistos: dict = {}
    for e in sorted(eventos, key=lambda x: x.get("id") or 0, reverse=True):
        if es_externo(e):
            clave = ("EXT", e.get("articulo_id") or (e.get("categoria"), (e.get("resumen_es") or "").strip().lower()))
        else:
            clave = ("INT", e.get("categoria"))
        if clave in vistos:
            continue
        vistos[clave] = e
    return sorted(vistos.values(), key=lambda x: x.get("id") or 0)


def _dt(s):
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _direccion_de(eventos: list[dict]) -> dict:
    """Resume los eventos activos de UN jugador. Un estado físico sin verificar
    vuelve todo MIXTA (ajuste de Rubén: el regreso no borra el antecedente)."""
    if any(e.get("verificar_estado_fisico") for e in eventos):
        return {"direccion": tx.MIXTA, "motivo": "ESTADO_FISICO_SIN_VERIFICAR", "eventos": eventos}
    neg = [e for e in eventos if e["direccion"] == tx.NEGATIVA]
    pos = [e for e in eventos if e["direccion"] == tx.POSITIVA]
    if neg and pos:
        fn, fp = _fuerza(neg), _fuerza(pos)
        if fn == fp:
            return {"direccion": tx.MIXTA, "motivo": "DIRECCION_CONTRADICTORIA", "eventos": eventos}
        return {"direccion": tx.NEGATIVA if fn > fp else tx.POSITIVA, "motivo": None,
                "eventos": neg if fn > fp else pos}
    if neg:
        return {"direccion": tx.NEGATIVA, "motivo": None, "eventos": neg}
    if pos:
        return {"direccion": tx.POSITIVA, "motivo": None, "eventos": pos}
    return {"direccion": tx.NEUTRA, "motivo": "CONTEXTO", "eventos": eventos}


def _fuerza(eventos: list[dict]) -> tuple:
    """Orden de evidencia, sin aritmética de probabilidades: (hay fuerte A/B,
    mejor nivel, cantidad)."""
    fuerte = any(tx.es_fuerte_evento(e) and e["nivel"] in ("A", "B") for e in eventos)
    mejor = max((_RANGO_NIVEL[e["nivel"]] for e in eventos), default=0)
    return (1 if fuerte else 0, mejor, len(eventos))


def _evidencia_suficiente(eventos: list[dict], nivel_min: str) -> tuple[bool, str, str]:
    """(ok, nivel, modo). Fuerte sola con nivel ≥ mínimo; o ≥2 débiles
    concordantes con nivel ≥ mínimo (acumulación)."""
    minimo = _RANGO_NIVEL.get(nivel_min, 2)
    validos = [e for e in eventos if _RANGO_NIVEL[e["nivel"]] >= minimo]
    fuertes = [e for e in validos if tx.es_fuerte_evento(e)]
    if fuertes:
        return True, max(fuertes, key=lambda e: _RANGO_NIVEL[e["nivel"]])["nivel"], "FUERTE"
    if len(validos) >= 2:
        return True, max(validos, key=lambda e: _RANGO_NIVEL[e["nivel"]])["nivel"], "ACUMULACION"
    return False, max((e["nivel"] for e in eventos), key=lambda n: _RANGO_NIVEL[n], default="C"), "INSUFICIENTE"


def evaluar(*, cfg: dict, ahora: Optional[datetime] = None,
            eventos_x: list[dict], eventos_rival: list[dict],
            identidad_x: float = 1.0, identidad_rival: float = 1.0,
            utr_x: Optional[float], utr_rival: Optional[float],
            utr_x_en: Optional[str] = None, utr_rival_en: Optional[str] = None,
            cuota_x: Optional[float], cuota_rival: Optional[float] = None,
            cuota_apertura_x: Optional[float] = None,
            inicio_partido: Optional[str] = None,
            fuego_hoy: int = 0, ya_avisado: bool = False) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    eventos_x, eventos_rival = sin_repetidos(eventos_x or []), sin_repetidos(eventos_rival or [])
    cortes = cortes_bandas(cfg)
    calibradas = bool(cfg.get("NEWS_BANDAS_CALIBRADAS"))
    experimental = bool(cfg.get("NEWS_EXPERIMENTAL_ACTIVO", 1))
    r = {"version_motor": VERSION_MOTOR, "tipo_alerta": "NADA", "motivo": None, "conclusion": "",
         "banda_utr": None, "banda_mercado": None, "desvio": None, "direccion_neta": None,
         "nivel": None, "modo_evidencia": None, "eventos_usados": [], "bandas_calibradas": int(calibradas),
         "delta_utr": None, "externo": 0, "explicaciones": []}

    def baja(tipo, motivo, conclusion=""):
        r.update(tipo_alerta=tipo, motivo=motivo, conclusion=conclusion)
        return r

    # 1 identidad
    minimo_id = float(cfg.get("NEWS_IDENTIDAD_MIN", 0.8))
    if identidad_x < minimo_id or identidad_rival < minimo_id:
        return baja("NADA", "IDENTIDAD_DUDOSA", "No se puede confirmar de qué jugador habla la noticia.")
    # 2 eventos
    if not eventos_x and not eventos_rival:
        return baja("NADA", "SIN_EVENTOS")
    # 3 empezado
    ini = _dt(inicio_partido)
    if ini and ini <= ahora:
        return baja("NADA", "PARTIDO_EMPEZADO")
    # 4 dirección neta vista desde X: lo negativo del rival es positivo para X
    dx, dr = _direccion_de(eventos_x), _direccion_de(eventos_rival) if eventos_rival else None
    if dx["motivo"] in ("ESTADO_FISICO_SIN_VERIFICAR", "DIRECCION_CONTRADICTORIA"):
        return baja("INTERESANTE", dx["motivo"], _conclusion_contexto(dx["motivo"]))
    if dr and dr["motivo"] in ("ESTADO_FISICO_SIN_VERIFICAR", "DIRECCION_CONTRADICTORIA"):
        return baja("INTERESANTE", dr["motivo"] + "_RIVAL", _conclusion_contexto(dr["motivo"]))
    direccion = dx["direccion"]
    usados = list(dx["eventos"])
    if dr and dr["direccion"] in (tx.NEGATIVA, tx.POSITIVA):
        desde_x = tx.POSITIVA if dr["direccion"] == tx.NEGATIVA else tx.NEGATIVA
        if direccion in (tx.NEGATIVA, tx.POSITIVA) and desde_x != direccion:
            return baja("INTERESANTE", "DIRECCION_CONTRADICTORIA", _conclusion_contexto("DIRECCION_CONTRADICTORIA"))
        if direccion not in (tx.NEGATIVA, tx.POSITIVA):
            direccion, usados = desde_x, list(dr["eventos"])
        else:
            usados += dr["eventos"]
    r["direccion_neta"] = direccion
    r["eventos_usados"] = [e.get("id") for e in usados]
    if direccion not in (tx.NEGATIVA, tx.POSITIVA):
        return baja("INTERESANTE", "CONTEXTO", "Hay contexto, sin dirección deportiva clara.")
    # 5 evidencia
    ok, nivel, modo = _evidencia_suficiente(usados, str(cfg.get("NEWS_NIVEL_MIN_FUEGO", "B")))
    r.update(nivel=nivel, modo_evidencia=modo)
    if not ok:
        return baja("INTERESANTE", "EVIDENCIA_INSUFICIENTE",
                    "La noticia no alcanza el nivel de evidencia exigido para hablar de valor.")
    # 5b (v5, Rubén 09/10): sin una noticia EXTERNA fuerte no hay 🔥. Un cálculo
    # propio de carga o antecedentes acompaña, pero no es una oportunidad.
    externos = [e for e in usados if es_externo(e) and tx.es_fuerte_evento(e)
                and _RANGO_NIVEL[e["nivel"]] >= _RANGO_NIVEL.get(str(cfg.get("NEWS_NIVEL_MIN_FUEGO", "B")), 2)]
    r["externo"] = int(bool(externos))
    if not externos:
        return baja("INTERESANTE", "SIN_NOTICIA_EXTERNA_FUERTE",
                    "Solo hay contexto calculado por nosotros (carga, antecedentes); sin noticia externa no se habla de valor.")
    # Posibles explicaciones del mercado (para el texto; no deciden solas).
    if dr and dr["eventos"]:
        r["explicaciones"].append("el rival también tiene noticias/contexto vigente: " +
                                  ", ".join(sorted({e["categoria"] for e in dr["eventos"]})[:3]))
    # 6 UTR
    if utr_x is None or utr_rival is None:
        return baja("INTERESANTE", "SIN_UTR", "Sin UTR de ambos jugadores no se compara con el mercado.")
    max_dias = int(cfg.get("NEWS_UTR_MAX_DIAS", 30))
    for en in (utr_x_en, utr_rival_en):
        d = _dt(en)
        if d is None or (ahora - d).days > max_dias:
            return baja("INTERESANTE", "UTR_VIEJO", f"UTR con más de {max_dias} días (o sin fecha).")
    delta = round(utr_x - utr_rival, 2)
    r["delta_utr"] = delta
    r["banda_utr"] = bd.banda_utr(delta, cortes["utr"])
    # 7 cuota
    if cuota_x is None:
        return baja("INTERESANTE", "SIN_MERCADO", "Sin cuota disponible: contexto, no señal de mercado.")
    r["banda_mercado"] = bd.banda_mercado(cuota_x, cortes["cuota"])
    r["desvio"] = bd.desvio(r["banda_utr"], r["banda_mercado"])
    # 0 bandas sin calibrar (v5): ya no corta acá. Si TODO lo demás pasa y
    # NEWS_EXPERIMENTAL_ACTIVO=1, sale como 🔥 EXPERIMENTAL (nunca como valor
    # validado); si está apagado, 🔎 BANDAS_NO_CALIBRADAS como antes.
    if not calibradas and not experimental:
        return baja("INTERESANTE", "BANDAS_NO_CALIBRADAS",
                    "Bandas UTR/cuota sin calibrar con datos propios: no se emite lectura de mercado.")
    # 8 mercado en movimiento
    if cuota_apertura_x is not None:
        b0 = bd.banda_mercado(cuota_apertura_x, cortes["cuota"])
        mov = bd.desvio(b0, r["banda_mercado"])          # pasos > 0: X mejoró para el mercado
        if mov and mov.get("pasos"):
            r["explicaciones"].append(f"la cuota de X se movió desde la apertura ({cuota_apertura_x:.2f} → {cuota_x:.2f})")
        if mov and ((direccion == tx.NEGATIVA and mov["pasos"] < 0) or (direccion == tx.POSITIVA and mov["pasos"] > 0)):
            return baja("INTERESANTE", "MERCADO_EN_MOVIMIENTO",
                        "El mercado ya se movió una banda en la dirección de la noticia.")
    # 9 cruce
    tipo_desvio = r["desvio"]["tipo"]
    if direccion == tx.NEGATIVA and tipo_desvio in ("ALINEADO", "MERCADO_MAS_OPTIMISTA"):
        tipo, lado = "FUEGO", "CONTRA_X"
    elif direccion == tx.POSITIVA and tipo_desvio in ("ALINEADO", "MERCADO_MAS_PESIMISTA"):
        tipo, lado = "FUEGO", "A_FAVOR_X"
    else:
        return baja("INTERESANTE", "MERCADO_YA_DESCONTO",
                    "El mercado ya está más allá de lo que el UTR justifica, en la dirección de la noticia.")
    # 10 topes
    if ya_avisado:
        return baja("INTERESANTE", "YA_AVISADO")
    if fuego_hoy >= int(cfg.get("NEWS_MAX_FUEGO_DIA", 10)):
        return baja("INTERESANTE", "TOPE_DIARIO")
    if not calibradas:
        tipo = "FUEGO_EXPERIMENTAL"
        r["explicaciones"].append("bandas UTR/cuota todavía sin validar con datos propios (señal experimental)")
    r.update(tipo_alerta=tipo, motivo=lado,
             conclusion=(f"Por UTR X debería ser {r['banda_utr']}; el mercado lo tiene {r['banda_mercado']}; "
                         f"la noticia es {direccion} para X. "
                         + ("El mercado no parece haberla descontado." if calibradas
                            else "Lectura EXPERIMENTAL: el mercado no parece haberla descontado, con bandas sin validar.")))
    return r


def _conclusion_contexto(motivo: str) -> str:
    return {
        "ESTADO_FISICO_SIN_VERIFICAR": "Regreso reciente con antecedente físico en seguimiento: "
                                        "falta verificar el estado físico con partidos completos.",
        "DIRECCION_CONTRADICTORIA": "Hay noticias en sentidos opuestos; contexto, no señal.",
    }.get(motivo, "Contexto, sin señal de mercado.")
