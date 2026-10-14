"""
ft_news/taxonomia.py — Taxonomía ABIERTA de eventos (diseño v2 §3).

Tres ejes por evento: categoría (qué pasó), dirección (a quién favorece),
naturaleza (hecho / declaración / no verificada / interpretación) → nivel
de evidencia A/B/C. La prioridad solo ordena la cola; no excluye nada.
`OTRA` nunca se descarta: va a la cola de revisión.
"""
from __future__ import annotations

import re

NEGATIVA, POSITIVA, NEUTRA, MIXTA = "NEGATIVA", "POSITIVA", "NEUTRA", "MIXTA"
HECHO, DECLARACION, NO_VERIFICADA, INTERPRETACION = "HECHO", "DECLARACION", "NO_VERIFICADA", "INTERPRETACION"

# categoria: (prioridad 1=muy alta 2=alta 3=media, vigencia_dias, peso FUERTE/DEBIL, direccion_tipica)
CATEGORIAS = {
    "LESION_MOLESTIA":          (1, 14, "FUERTE", NEGATIVA),
    "ENFERMEDAD":               (1, 7,  "FUERTE", NEGATIVA),
    "RETIRO_ABANDONO":          (1, 21, "FUERTE", NEGATIVA),
    "REGRESO":                  (1, 30, "FUERTE", MIXTA),
    "CARGA_FISICA":             (2, 5,  "FUERTE", NEGATIVA),
    "VIAJE_CALENDARIO":         (2, 5,  "DEBIL",  NEGATIVA),
    "PUNTOS_DEFENDIDOS":        (2, 10, "DEBIL",  MIXTA),
    "DECLARACION_PREPARACION":  (2, 14, "DEBIL",  POSITIVA),
    "DECLARACION_MOTIVACION":   (2, 14, "DEBIL",  MIXTA),
    "ANTECEDENTE_TORNEO":       (3, 10, "DEBIL",  MIXTA),
    "LOCALIA":                  (3, 10, "DEBIL",  POSITIVA),
    "SUPERFICIE":               (3, 30, "DEBIL",  MIXTA),
    "CAMBIO_EQUIPO":            (3, 45, "DEBIL",  MIXTA),
    "SITUACION_PERSONAL":       (2, 14, "DEBIL",  MIXTA),
    "SANCION_DISCIPLINA":       (1, 30, "FUERTE", NEGATIVA),
    "RANKING_OBJETIVO":         (3, 10, "DEBIL",  MIXTA),
    "RESULTADO_RECIENTE":       (3, 7,  "DEBIL",  MIXTA),
    "OTRA":                     (3, 7,  "DEBIL",  NEUTRA),
}
FUERTES = frozenset(c for c, v in CATEGORIAS.items() if v[2] == "FUERTE")
DIRECCIONES = (NEGATIVA, POSITIVA, NEUTRA, MIXTA)
NATURALEZAS = (HECHO, DECLARACION, NO_VERIFICADA, INTERPRETACION)
NIVELES = ("A", "B", "C")


def es_fuerte(categoria: str) -> bool:
    return categoria in FUERTES


# v7.5 (13/10/2026, caso Andrade Da Silva: «Derrota por walkover en dobles» salió como retiro suyo en individuales):
# un resultado de DOBLES (walkover, retiro o derrota) no dice qué le pasa al jugador en individuales — ni siquiera
# quién de la pareja se bajó. Queda como contexto: nunca es noticia fuerte.
_DOBLES = re.compile(r"\b(dobles|doubles|doble mixto|dobles mixtos|mixed doubles|en pareja con|pareja de dobles|"
                     r"doubles partner|compañer[oa] de dobles|partner)\b", re.IGNORECASE)


def es_dobles(ev: dict) -> bool:
    texto = " ".join(str(ev.get(k) or "") for k in ("titular", "resumen_es", "fragmento_original", "relevancia_deportiva"))
    return bool(_DOBLES.search(texto))


def es_fuerte_evento(ev: dict) -> bool:
    """Categoría fuerte y NO es un resultado de dobles."""
    return es_fuerte(str(ev.get("categoria") or "")) and not es_dobles(ev)


def vigencia_dias(categoria: str) -> int:
    return CATEGORIAS.get(categoria, CATEGORIAS["OTRA"])[1]


def prioridad(categoria: str) -> int:
    return CATEGORIAS.get(categoria, CATEGORIAS["OTRA"])[0]


def nivel_evidencia(naturaleza: str, fuentes_independientes: int, fuente_oficial: bool,
                    fuente_fiable: bool, dato_propio: bool = False) -> str:
    """A = hecho confirmado (oficial, dos fuentes, o dato duro propio);
    B = declaración directa en fuente fiable; C = lo demás."""
    if dato_propio:
        return "A"
    if naturaleza == HECHO and (fuente_oficial or fuentes_independientes >= 2):
        return "A"
    if naturaleza in (HECHO, DECLARACION) and fuente_fiable:
        return "B"
    return "C"


def validar_evento(categoria: str, direccion: str, naturaleza: str, nivel: str) -> list[str]:
    errores = []
    if categoria not in CATEGORIAS:
        errores.append(f"categoria desconocida: {categoria} (usar OTRA)")
    if direccion not in DIRECCIONES:
        errores.append(f"direccion inválida: {direccion}")
    if naturaleza not in NATURALEZAS:
        errores.append(f"naturaleza inválida: {naturaleza}")
    if nivel not in NIVELES:
        errores.append(f"nivel inválido: {nivel}")
    if naturaleza in (NO_VERIFICADA, INTERPRETACION) and nivel != "C":
        errores.append("una no verificada / interpretación solo puede ser nivel C")
    return errores
