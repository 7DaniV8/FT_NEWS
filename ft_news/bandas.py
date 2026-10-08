"""
ft_news/bandas.py — Bandas de expectativa (diseño v2 §4, pasos 1–3).

Nada acá es una probabilidad. Son cajones ordenados:
  UTR:     ABISMO_CONTRA < MUY_NO_FAVORITO < NO_FAVORITO < PAREJO < FAVORITO < MUY_FAVORITO < ABISMO
  Mercado: MUY_NO_FAVORITO < NO_FAVORITO < PAREJO < FAVORITO < MUY_FAVORITO
El "desvío" es cuántos cajones separan lo que dice el mercado de lo que
dice el UTR, y hacia qué lado. Los cortes vienen de la configuración y
DEBEN calibrarse con datos propios antes de confiar en ellos
(NEWS_BANDAS_CALIBRADAS; informe en RankingFTR /ft-intel/news/calibracion).
"""
from __future__ import annotations

from typing import Optional

ORDEN = {"MUY_NO_FAVORITO": -2, "NO_FAVORITO": -1, "PAREJO": 0, "FAVORITO": 1, "MUY_FAVORITO": 2}
CORTES_UTR_DEFAULT = (0.30, 0.80, 1.50)
CORTES_CUOTA_DEFAULT = (1.35, 1.75, 2.30, 3.50)


def banda_utr(delta: Optional[float], cortes=CORTES_UTR_DEFAULT) -> Optional[str]:
    """delta = UTR del jugador X − UTR del rival. ABISMO se mapea a ±2 para
    comparar con el mercado (que no tiene cajón más allá de MUY_)."""
    if delta is None:
        return None
    parejo, fav, muy = cortes
    a = abs(delta)
    if a < parejo:
        return "PAREJO"
    if a < fav:
        return "FAVORITO" if delta > 0 else "NO_FAVORITO"
    if a < muy:
        return "MUY_FAVORITO" if delta > 0 else "MUY_NO_FAVORITO"
    return "ABISMO" if delta > 0 else "ABISMO_CONTRA"


def banda_mercado(cuota: Optional[float], cortes=CORTES_CUOTA_DEFAULT) -> Optional[str]:
    if cuota is None or cuota <= 1.0:
        return None
    muy_fav, fav, parejo, no_fav = cortes
    if cuota <= muy_fav:
        return "MUY_FAVORITO"
    if cuota <= fav:
        return "FAVORITO"
    if cuota <= parejo:
        return "PAREJO"
    if cuota <= no_fav:
        return "NO_FAVORITO"
    return "MUY_NO_FAVORITO"


def _orden(banda: str) -> int:
    if banda == "ABISMO":
        return 2
    if banda == "ABISMO_CONTRA":
        return -2
    return ORDEN[banda]


def desvio(banda_u: Optional[str], banda_m: Optional[str]) -> Optional[dict]:
    """Mercado vs UTR, visto desde el jugador X.
    pasos > 0 → MERCADO_MAS_OPTIMISTA (lo paga mejor de lo que el UTR dice);
    pasos < 0 → MERCADO_MAS_PESIMISTA; 0 → ALINEADO."""
    if banda_u is None or banda_m is None:
        return None
    pasos = _orden(banda_m) - _orden(banda_u)
    if pasos > 0:
        tipo = "MERCADO_MAS_OPTIMISTA"
    elif pasos < 0:
        tipo = "MERCADO_MAS_PESIMISTA"
    else:
        tipo = "ALINEADO"
    return {"tipo": tipo, "pasos": pasos, "banda_utr": banda_u, "banda_mercado": banda_m}


def cuota_a_banda_esperada(banda_u: str) -> str:
    """Qué banda de mercado 'corresponde' a cada banda UTR (para el informe)."""
    return {"ABISMO": "MUY_FAVORITO", "ABISMO_CONTRA": "MUY_NO_FAVORITO"}.get(banda_u, banda_u)
