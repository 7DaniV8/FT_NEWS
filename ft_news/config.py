"""
ft_news/config.py — Toda la configuración en un solo lugar (Fase 0).

Dos capas:
  1. Variables de entorno (Railway): dónde está la base, cómo hablarle a
     RankingFTR, y los valores por DEFECTO de los interruptores.
  2. Tabla news_config (editable por la API /news/config y, más adelante,
     desde Admin → Estrategias de RankingFTR): pisa los defaults.

TODO ARRANCA APAGADO. Con NEWS_ACTIVO=0 el worker no hace ninguna llamada
externa (ni a RankingFTR ni a ningún proveedor); solo escribe su estado.
"""
from __future__ import annotations

import os
from pathlib import Path

DB_PATH = Path(os.getenv("FT_NEWS_DB_PATH", "/data/ft_news.db"))

# RankingFTR, solo lectura, por /ft-intel/* (mismo secreto que FT Intelligence).
FTR_URL = os.getenv("FTR_SERVICE_URL", "").strip().rstrip("/")
FTR_SECRET = os.getenv("FTR_INTERNAL_SECRET", "").strip()
FTR_PAUSA = float(os.getenv("FT_NEWS_PAUSA_FTR", "0.5"))

# Quién puede leer la API de FT_NEWS (RankingFTR para la tab, FT Intelligence
# para las señales). Vacío = solo /salud responde.
NEWS_SECRET = os.getenv("FT_NEWS_SECRET", "").strip()

CICLO_SEGUNDOS = int(os.getenv("FT_NEWS_CICLO_SEGUNDOS", "900"))     # 15 min
# Proveedores (Fase 1). Sin clave, el paso que la necesita se saltea y lo deja escrito.
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
# Fuentes que nacen autorizadas (decisión de Rubén, 08/10/2026: prensa por Tavily
# + RSS oficial de ATP; ITF oficial y UTR PTT quedan fuera hasta D-ITF/D-UTRPTT).
# Se aplican UNA vez al sembrar; después manda lo que se cambie desde la pestaña.
FUENTES_INICIALES = [d.strip() for d in os.getenv(
    "NEWS_FUENTES_AUTORIZADAS_INICIALES",
    "tennistourtalk.com,puntodebreak.com,livetennis.it,ubitennis.com,tennisactu.net,atptour.com").split(",") if d.strip()]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()      # segunda lectura (opcional)

# ── Interruptores y topes: defaults. (clave, valor_default, tipo, descripción)
PARAMETROS = (
    ("NEWS_ACTIVO", 1, "bool", "Interruptor general. 0 = el worker no llama a nadie. (08/10/2026: nace encendido, "
                               "decisión de Rubén: un solo despliegue.)"),
    ("NEWS_BANDAS_CALIBRADAS", 0, "bool",
     "1 = las bandas UTR/cuota están validadas con datos propios y el descubridor puede emitir 🔥. "
     "Con 0 NUNCA afirma que el mercado no descontó una noticia: todo queda en 🔎 (BANDAS_NO_CALIBRADAS). "
     "Con NEWS_BANDAS_AUTO=1 la enciende/apaga el propio motor según el veredicto de "
     "RankingFTR /ft-intel/news/calibracion."),
    ("NEWS_BANDAS_AUTO", 0, "bool",
     "1 = cada 6 h pide la calibración a RankingFTR y sigue su veredicto (CALIBRADAS_OK → 1; NO → 0). "
     "0 = la decide Rubén a mano (v5: default 0; la calibración informa, no activa)."),
    ("NEWS_FUENTES_AUTORIZADAS_SOLO", 1, "bool",
     "1 = solo se leen fuentes con autorizada=1 en news_fuente (hoy: ninguna)."),
    ("NEWS_DISCORD_ACTIVO", 1, "bool",
     "0 = ninguna señal sale a /news/senales (las alertas se generan igual y se ven en la pestaña). "
     "v6 (09/10/2026 23:13, Rubén: 'activemos las tres alertas'): nace ENCENDIDO; Admin → FT NEWS lo apaga en un clic."),
    ("NEWS_SENAL_MAX_HORAS", 12, "int",
     "v5.1: una alerta pendiente de más de N h ya no viaja a Discord (queda 'omitida: VENCIDA'); evita una avalancha al encender."),
    ("NEWS_DISCORD_INTERESANTE", 1, "bool",
     "1 = salen las 🔎 PARTIDO INTERESANTE seleccionadas (noticia externa nivel ≥ B, los dos investigados); "
     "0 = no. (v5, 09/10/2026: nace encendido, pedido de Rubén.)"),
    ("NEWS_DISCORD_NOTICIA", 1, "bool",
     "1 = salen las 📰 NOTICIA IMPORTANTE (noticia externa fuerte y verificada, con o sin partido)."),
    ("NEWS_EXPERIMENTAL_ACTIVO", 1, "bool",
     "1 = con bandas SIN calibrar, una oportunidad con noticia externa sólida + UTR + cuota sale como "
     "🔥 POSIBLE VALOR EXPERIMENTAL (nunca como valor validado). 0 = queda en 🔎."),
    ("NEWS_MAX_NOTICIA_DIA", 8, "int", "Tope diario de 📰."),
    ("NEWS_MAX_INTERESANTE_DIA", 6, "int", "Tope diario de 🔎."),
    ("NEWS_ALERTA_REPETIR_DIAS", 7, "int",
     "Una misma noticia (jugador + categoría) o el mismo partido no se repite en N días salvo información nueva."),
    ("NEWS_NOTICIA_MAX_DIAS", 7, "int", "Una noticia con hecho de más de N días no es 📰."),
    ("NEWS_RIVAL_HORAS", 48, "int", "Si el rival no fue investigado en N h, se lo adelanta en la cola (a demanda)."),
    ("NEWS_EXP_MIN_PUNTOS", 2, "int",
     "v5.1: balance mínimo (a favor − en contra) para que una 🔥 experimental salga; si no, queda como 🔎."),
    ("NEWS_EXP_MOV_CUOTA_PCT", 3.0, "float", "v5.1: movimiento de cuota (desde apertura) que cuenta como 'el mercado ya se movió'."),
    ("NEWS_RADAR_TEMATICO_ACTIVO", 1, "bool",
     "Radar por TEMA (lesión, retiro, baja…) por idioma y circuito: encuentra noticias de cualquier jugador del "
     "padrón, tenga o no partido. Los nombres se cruzan contra el padrón antes de pagar IA."),
    ("NEWS_RADAR_TEMATICO_BUSQUEDAS", 12, "int", "Búsquedas por corrida del radar temático."),
    ("NEWS_RADAR_TEMATICO_CADA_H", 6, "int", "Cada cuántas horas corre el radar temático."),
    ("NEWS_RADAR_CUPO_MENORES_PCT", 40, "int",
     "Porcentaje de los cupos por ciclo reservado a ITF y UTR PTT (no quedan para el final)."),
    ("NEWS_CLASIFICADOR", "auto", "str",
     "Quién clasifica los artículos: gemini | claude | auto. auto (default) = Gemini si hay GEMINI_API_KEY y responde; "
     "si no, Claude (ANTHROPIC_API_KEY). El otro, si existe, hace la segunda lectura de lo que aspira a 🔥."),
    ("NEWS_RADAR_JUGADORES_CICLO", 40, "int", "Jugadores que el radar directo atiende por ciclo (15 min)."),
    ("NEWS_MAX_BUSQUEDAS_DIA", 250, "int", "Tope diario de consultas a Tavily (v5: 120 → 250; ≈ US$ 50/mes sobre el plan)."),
    ("NEWS_MAX_TOKENS_DIA", 2_000_000, "int", "Tope diario de tokens de IA."),
    ("NEWS_MAX_USD_MES", 100.0, "float", "Tope mensual estimado; al 80 % avisa, al 100 % duerme."),
    ("NEWS_MAX_FUEGO_DIA", 10, "int", "Tope diario de 🔥."),
    ("NEWS_UTR_MAX_DIAS", 30, "int", "UTR más viejo que esto → UTR_VIEJO (no hay 🔥)."),
    ("NEWS_NIVEL_MIN_FUEGO", "B", "str", "Nivel mínimo de evidencia para 🔥: A o B."),
    ("NEWS_IDENTIDAD_MIN", 0.8, "float", "Confianza mínima de identidad para avanzar."),
    ("NEWS_VENTANA_PARTIDO_HORAS", 72, "int", "Partidos a evaluar: los que empiezan en ≤ N h."),
    # Cortes de bandas (puntos de partida; se calibran con datos propios — R14).
    ("NEWS_BANDA_UTR_PAREJO", 0.30, "float", "|ΔUTR| < esto → PAREJO."),
    ("NEWS_BANDA_UTR_FAVORITO", 0.80, "float", "|ΔUTR| < esto → FAVORITO / NO_FAVORITO."),
    ("NEWS_BANDA_UTR_MUY", 1.50, "float", "|ΔUTR| < esto → MUY_FAVORITO; más → ABISMO."),
    ("NEWS_BANDA_CUOTA_MUY_FAV", 1.35, "float", "cuota ≤ esto → MUY_FAVORITO."),
    ("NEWS_BANDA_CUOTA_FAV", 1.75, "float", "cuota ≤ esto → FAVORITO."),
    ("NEWS_BANDA_CUOTA_PAREJO", 2.30, "float", "cuota ≤ esto → PAREJO."),
    ("NEWS_BANDA_CUOTA_NO_FAV", 3.50, "float", "cuota ≤ esto → NO_FAVORITO; más → MUY_NO_FAVORITO."),
    ("NEWS_IDIOMAS", "en,es,it,fr,pt", "str", "Idiomas de búsqueda (Fase 1)."),
    ("NEWS_CIRCUITOS", "atp,wta,challenger,wta125,itf,utr", "str", "Circuitos dentro del proyecto."),
)
DEFAULTS = {k: v for k, v, _t, _d in PARAMETROS}
TIPOS = {k: t for k, _v, t, _d in PARAMETROS}


def _convertir(clave: str, valor):
    t = TIPOS.get(clave, "str")
    if valor is None:
        return DEFAULTS.get(clave)
    try:
        if t == "bool":
            return 1 if str(valor).strip().lower() in ("1", "true", "si", "sí", "on") else 0
        if t == "int":
            return int(float(valor))
        if t == "float":
            return float(valor)
    except (TypeError, ValueError):
        return DEFAULTS.get(clave)
    return str(valor)


def leer_config(conn=None) -> dict:
    """Defaults ← variables de entorno ← tabla news_config (si hay conexión)."""
    cfg = {}
    for k, v in DEFAULTS.items():
        cfg[k] = _convertir(k, os.getenv(k, v))
    if conn is not None:
        try:
            for r in conn.execute("SELECT clave, valor FROM news_config").fetchall():
                if r["clave"] in DEFAULTS:
                    cfg[r["clave"]] = _convertir(r["clave"], r["valor"])
        except Exception:
            pass
    return cfg


def cortes_bandas(cfg: dict) -> dict:
    return {
        "utr": (cfg["NEWS_BANDA_UTR_PAREJO"], cfg["NEWS_BANDA_UTR_FAVORITO"], cfg["NEWS_BANDA_UTR_MUY"]),
        "cuota": (cfg["NEWS_BANDA_CUOTA_MUY_FAV"], cfg["NEWS_BANDA_CUOTA_FAV"],
                  cfg["NEWS_BANDA_CUOTA_PAREJO"], cfg["NEWS_BANDA_CUOTA_NO_FAV"]),
    }
