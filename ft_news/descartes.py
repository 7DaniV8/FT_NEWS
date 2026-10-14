"""
ft_news/descartes.py — Motivos de descarte PERMANENTES (v7.2, 13/10/2026).

Rubén: "quiero que el sistema guarde permanentemente los motivos de descarte"
y "no quiero bajar filtros a ciegas". Hasta v7.1 el motor calculaba por qué
una noticia o un partido no salía a Discord y lo tiraba: no había forma de
saber, días después, qué filtro estaba frenando todo.

Cada decisión de NO enviar se guarda en `news_descarte`, una fila por
(día, etapa, objeto, grupo). Si el ciclo siguiente descarta lo mismo por lo
mismo, suma `veces`; nunca se borra. Con eso `embudo()` responde:

  1. cuántas noticias externas reales entran por día;
  2. cuántas se descartan y por qué (grupo + código original);
  3. cuántos partidos interesantes se pierden porque falta investigar al rival;
  4. cuántas oportunidades quedan bloqueadas por cuotas sin actualizar;
  5. si las alertas pasan por FT Intelligence (latido de /news/senales y marca "dicha");
  6. si "bandas calibradas" está activada sin veredicto que la respalde.

Registrar NUNCA cambia una decisión ni levanta excepción: es solo memoria.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news.db import ejecutar_con_reintento

log = logging.getLogger("ft_news")

# Grupo normalizado → texto simple (para la pestaña). El código original queda en `motivo`.
GRUPOS = {
    "RIVAL_SIN_INVESTIGAR": "falta investigar a uno de los dos jugadores (búsqueda de más de 48 h)",
    "CUOTA_SIN_ACTUALIZAR": "no hay cuota confirmada después de la noticia",
    "SIN_MERCADO": "el partido no tiene cuota",
    "SOLO_DATOS_INTERNOS": "solo hay datos calculados por nosotros (carga, viaje…), ninguna noticia de un medio",
    "CATEGORIA_NO_RELEVANTE": "la noticia no es de un tipo que se avise (no es lesión, retiro, regreso…)",
    "FUENTE_DEBIL": "la fuente no alcanza el nivel mínimo (nivel C)",
    "RUMOR_NO_CONFIRMADO": "es un rumor o una interpretación, no un hecho ni una declaración",
    "IDENTIDAD_DUDOSA": "no se puede confirmar de qué jugador habla",
    "HECHO_VIEJO": "el hecho tiene más días de los permitidos",
    "NOTICIA_SUPERADA": "la noticia ya fue superada o venció",
    "REPETIDA": "ya se avisó lo mismo hace pocos días",
    "TOPE_DIARIO": "se alcanzó el tope diario de alertas de ese tipo",
    "CANAL_APAGADO": "ese tipo de alerta está apagado en la configuración",
    "RETIRO_MISMO_TORNEO": "el retiro es del mismo torneo: el partido puede no jugarse",
    "JUSTIFICACION_INSUFICIENTE": "no se puede explicar qué no estaría reflejado en la cuota",
    "MERCADO_YA_DESCONTO": "el mercado ya refleja la noticia",
    "MERCADO_EN_MOVIMIENTO": "la cuota ya se movió en la dirección de la noticia",
    "UTR_FALTA_O_VIEJO": "falta el UTR de alguno o tiene más de 30 días",
    "EVIDENCIA_INSUFICIENTE": "la noticia no alcanza el nivel de evidencia para hablar de valor",
    "CONTRADICTORIA": "hay información contradictoria: queda como no confirmada",
    "SIN_DIRECCION": "hay contexto, pero sin un efecto deportivo claro",
    "ESTADO_FISICO_SIN_VERIFICAR": "regreso con lesión previa sin verificar con partidos completos",
    "BANDAS_NO_CALIBRADAS": "bandas sin calibrar y la señal experimental apagada",
    "YA_AVISADO": "ese jugador ya tuvo 🔥 en el mismo torneo",
    "DOBLES": "es un resultado de dobles: no dice nada del jugador en individuales",
    "HECHO_YA_AVISADO": "ese mismo hecho ya salió en otra alerta del mismo tipo",
    "MERCADO_YA_LO_REFLEJA": "FT NEWS concluyó que el mercado ya tiene la noticia: nada que avisar",
    "TEXTO_PROHIBIDO": "el texto generado no pasó el control de palabras prohibidas",
    "ERROR": "error interno al decidir (ver detalle)",
    "OTRO": "otro motivo (ver código)",
}

_MAPA = {
    "RIVAL_SIN_INVESTIGAR": "RIVAL_SIN_INVESTIGAR", "RIVAL_SIN_INVESTIGACION_RECIENTE": "RIVAL_SIN_INVESTIGAR",
    "CUOTA_SIN_ACTUALIZAR": "CUOTA_SIN_ACTUALIZAR", "CUOTA_PENDIENTE": "CUOTA_SIN_ACTUALIZAR",
    "SIN_MERCADO": "SIN_MERCADO",
    "INTERNO": "SOLO_DATOS_INTERNOS", "SIN_NOTICIA_EXTERNA": "SOLO_DATOS_INTERNOS",
    "SIN_NOTICIA_EXTERNA_FUERTE": "SOLO_DATOS_INTERNOS",
    "CATEGORIA_NO_RELEVANTE": "CATEGORIA_NO_RELEVANTE", "NIVEL_C": "FUENTE_DEBIL",
    "NATURALEZA": "RUMOR_NO_CONFIRMADO", "IDENTIDAD_DUDOSA": "IDENTIDAD_DUDOSA",
    "HECHO_VIEJO": "HECHO_VIEJO", "ESTADO": "NOTICIA_SUPERADA", "REPETIDA": "REPETIDA",
    "TOPE_DIARIO": "TOPE_DIARIO", "RETIRO_MISMO_TORNEO": "RETIRO_MISMO_TORNEO",
    "SIN_INFORMACION_NO_REFLEJADA": "JUSTIFICACION_INSUFICIENTE",
    "JUSTIFICACION_INSUFICIENTE": "JUSTIFICACION_INSUFICIENTE",
    "MERCADO_YA_DESCONTO": "MERCADO_YA_DESCONTO", "MERCADO_EN_MOVIMIENTO": "MERCADO_EN_MOVIMIENTO",
    "SIN_UTR": "UTR_FALTA_O_VIEJO", "UTR_VIEJO": "UTR_FALTA_O_VIEJO",
    "EVIDENCIA_INSUFICIENTE": "EVIDENCIA_INSUFICIENTE",
    "DIRECCION_CONTRADICTORIA": "CONTRADICTORIA", "DIRECCION_CONTRADICTORIA_RIVAL": "CONTRADICTORIA",
    "CONTEXTO": "SIN_DIRECCION",
    "ESTADO_FISICO_SIN_VERIFICAR": "ESTADO_FISICO_SIN_VERIFICAR",
    "ESTADO_FISICO_SIN_VERIFICAR_RIVAL": "ESTADO_FISICO_SIN_VERIFICAR",
    "BANDAS_NO_CALIBRADAS": "BANDAS_NO_CALIBRADAS", "YA_AVISADO": "YA_AVISADO",
    "TEXTO_PROHIBIDO": "TEXTO_PROHIBIDO",
    "DOBLES": "DOBLES", "HECHO_YA_AVISADO": "HECHO_YA_AVISADO", "MERCADO_YA_LO_REFLEJA": "MERCADO_YA_LO_REFLEJA",
}

# Motivos que NO son un descarte (la alerta salió, o no correspondía evaluar esa etapa).
NO_ES_DESCARTE = {None, "", "NO_ES_INTERESANTE", "NO_ES_FUEGO", "CONTRA_X", "A_FAVOR_X"}


def grupo(motivo: Optional[str]) -> str:
    m = str(motivo or "").strip()
    if m.lower().startswith("error"):
        return "ERROR"
    if m.startswith("NEWS_DISCORD_") or m.startswith("NEWS_EXPERIMENTAL"):
        return "CANAL_APAGADO"
    base = m.split(":")[0]
    return _MAPA.get(base, "OTRO")


def texto(grupo_: str) -> str:
    return GRUPOS.get(grupo_, GRUPOS["OTRO"])


def registrar(conn, etapa: str, motivo: Optional[str], *, ahora: Optional[datetime] = None,
              partido_id=None, evento_id=None, jugador_id=None, rival_id=None, evaluacion_id=None,
              detalle: str = "", grupo_forzado: Optional[str] = None) -> Optional[str]:
    """Guarda (o suma) un descarte. Devuelve el grupo, o None si no es un descarte.
    Nunca levanta excepción."""
    if motivo in NO_ES_DESCARTE and not grupo_forzado:
        return None
    ahora = ahora or datetime.now(timezone.utc)
    g = grupo_forzado or grupo(motivo)
    objeto = f"partido:{partido_id}" if partido_id else (f"evento:{evento_id}" if evento_id else f"jugador:{jugador_id}")
    dia, ts = ahora.date().isoformat(), ahora.isoformat()

    def _w():
        conn.execute(
            "INSERT INTO news_descarte (dia, etapa, objeto, grupo, motivo, detalle, jugador_id, rival_id, partido_id, "
            "evento_id, evaluacion_id, veces, primera_en, ultima_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?) "
            "ON CONFLICT(dia, etapa, objeto, grupo) DO UPDATE SET veces=veces+1, ultima_en=excluded.ultima_en, "
            "motivo=excluded.motivo, detalle=excluded.detalle, evaluacion_id=COALESCE(excluded.evaluacion_id, evaluacion_id)",
            (dia, etapa, objeto, g, str(motivo or g)[:300], str(detalle or "")[:500], jugador_id, rival_id, partido_id,
             evento_id, evaluacion_id, ts, ts))
        conn.commit()
    try:
        ejecutar_con_reintento(_w, conn=conn)
    except Exception as e:                                   # pragma: no cover — la memoria nunca tumba el motor
        log.warning("[FT_NEWS] no se pudo guardar el descarte %s/%s: %s", etapa, motivo, e)
        return None
    return g


# ═════════════════════════════════════════════════════════════════════
# Embudo: las seis preguntas de Rubén, por día
# ═════════════════════════════════════════════════════════════════════

_EXTERNO_SQL = "(e.origen='EXTERNO' OR (e.origen IS NULL AND e.articulo_id IS NOT NULL))"


def _filas(conn, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _perdidos(conn, grupo_: str, desde: str, ahora: datetime) -> dict:
    """Partidos que tuvieron este bloqueo: cuántos terminaron con alerta igual
    (se recuperaron en un ciclo posterior), cuántos ya empezaron sin alerta
    (perdidos) y cuántos siguen en juego."""
    ids = [r["partido_id"] for r in _filas(
        conn, "SELECT DISTINCT partido_id FROM news_descarte WHERE grupo=? AND dia>=? AND partido_id IS NOT NULL",
        (grupo_, desde))]
    rec = per = abiertos = 0
    for pid in ids:
        if conn.execute("SELECT 1 FROM news_alerta WHERE partido_id=? AND COALESCE(prueba,0)=0 "
                        "AND tipo IN ('INTERESANTE','FUEGO','FUEGO_EXPERIMENTAL')", (pid,)).fetchone():
            rec += 1
            continue
        p = conn.execute("SELECT fecha_estimada, estado FROM news_partido WHERE id=?", (pid,)).fetchone()
        ini = None
        if p and p["fecha_estimada"]:
            try:
                ini = datetime.fromisoformat(str(p["fecha_estimada"])[:19].replace(" ", "T")).replace(tzinfo=timezone.utc)
            except ValueError:
                ini = None
        if (p and p["estado"] != "PROGRAMADO") or (ini and ini <= ahora):
            per += 1
        else:
            abiertos += 1
    return {"partidos": len(ids), "recuperados_despues": rec, "perdidos": per, "todavia_en_juego": abiertos}


def embudo(conn, dias: int = 7, ahora: Optional[datetime] = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    desde = (ahora - timedelta(days=dias - 1)).date().isoformat()

    # 1 · noticias externas por día (y lo calculado aparte, para no confundir)
    externas = _filas(conn, f"SELECT substr(e.creado_en,1,10) dia, COUNT(*) n, COUNT(DISTINCT e.jugador_id) jugadores "
                            f"FROM news_evento e WHERE {_EXTERNO_SQL} AND e.creado_en>=? GROUP BY 1 ORDER BY 1", (desde,))
    internas = _filas(conn, f"SELECT substr(e.creado_en,1,10) dia, COUNT(*) n FROM news_evento e "
                            f"WHERE NOT {_EXTERNO_SQL} AND e.creado_en>=? GROUP BY 1 ORDER BY 1", (desde,))
    articulos = _filas(conn, "SELECT substr(creado_en,1,10) dia, COALESCE(resultado,'SIN_CLASIFICAR') resultado, COUNT(*) n "
                             "FROM news_articulo WHERE creado_en>=? GROUP BY 1,2 ORDER BY 1,3 DESC", (desde,))

    # 2 · descartes por etapa y motivo (objetos distintos, no repeticiones de ciclo)
    desc = _filas(conn, "SELECT etapa, grupo, COUNT(*) objetos, SUM(veces) veces, MAX(ultima_en) ultima "
                        "FROM news_descarte WHERE dia>=? GROUP BY etapa, grupo ORDER BY etapa, objetos DESC", (desde,))
    for d in desc:
        d["texto"] = texto(d["grupo"])
    desc_dia = _filas(conn, "SELECT dia, etapa, COUNT(*) objetos FROM news_descarte WHERE dia>=? GROUP BY 1,2 ORDER BY 1",
                      (desde,))
    art_desc = _filas(conn, "SELECT COALESCE(resultado,'SIN_CLASIFICAR') resultado, COALESCE(motivo,'') motivo, COUNT(*) n "
                            "FROM news_articulo WHERE creado_en>=? AND COALESCE(resultado,'')<>'EVENTO' "
                            "GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15", (desde,))

    # 3 y 4 · partidos bloqueados por rival sin investigar y por cuota sin actualizar
    rival = _perdidos(conn, "RIVAL_SIN_INVESTIGAR", desde, ahora)
    cuota = _perdidos(conn, "CUOTA_SIN_ACTUALIZAR", desde, ahora)
    sin_mercado = _perdidos(conn, "SIN_MERCADO", desde, ahora)

    # 5 · entrega (sin las PRUEBA)
    alertas = _filas(conn, "SELECT substr(creado_en,1,10) dia, tipo, dicho_discord, COUNT(*) n FROM news_alerta "
                           "WHERE COALESCE(prueba,0)=0 AND creado_en>=? GROUP BY 1,2,3 ORDER BY 1", (desde,))
    omitidas = _filas(conn, "SELECT COALESCE(dicho_motivo,'?') motivo, COUNT(*) n FROM news_alerta "
                            "WHERE COALESCE(prueba,0)=0 AND dicho_discord=2 AND creado_en>=? GROUP BY 1 ORDER BY 2 DESC",
                      (desde,))
    ultima_dicha = conn.execute("SELECT MAX(dicho_en) FROM news_alerta WHERE dicho_discord=1 AND COALESCE(prueba,0)=0"
                                ).fetchone()[0]
    est = {r["clave"]: r for r in _filas(conn, "SELECT clave, valor, actualizado_en FROM news_estado")}
    entrega = {
        "alertas_por_dia": alertas,
        "omitidas_por_motivo": omitidas,
        "ultima_dicha_en": ultima_dicha,
        "ft_intelligence_leyo_senales_en": (est.get("senales_leidas_en") or {}).get("valor"),
        "ft_intelligence_ultima_lectura": (est.get("senales_ultima_lectura") or {}).get("valor"),
        "ft_intelligence_marco_dichas_en": (est.get("senales_dicho_en") or {}).get("valor"),
        "vencidas_sin_recoger": sum(r["n"] for r in omitidas if r["motivo"] == "VENCIDA"),
        # v7.3: los tres pasos, por separado (recibida ≠ publicada)
        "pasos": _filas(conn, "SELECT COUNT(*) creadas, SUM(CASE WHEN entregada_en IS NOT NULL THEN 1 ELSE 0 END) recibidas, "
                              "SUM(CASE WHEN dicho_discord=1 THEN 1 ELSE 0 END) procesadas, "
                              "SUM(CASE WHEN publicado=1 THEN 1 ELSE 0 END) publicadas, "
                              "SUM(CASE WHEN publicado=0 THEN 1 ELSE 0 END) fallo_publicacion, "
                              "SUM(CASE WHEN dicho_discord=2 THEN 1 ELSE 0 END) omitidas "
                              "FROM news_alerta WHERE COALESCE(prueba,0)=0 AND creado_en>=?", (desde,))[0],
    }

    # 6 · bandas
    from ft_news import config as _cfg
    cfg = _cfg.leer_config(conn)
    cambio = conn.execute("SELECT valor, actualizado_en, actualizado_por FROM news_config WHERE clave='NEWS_BANDAS_CALIBRADAS'"
                          ).fetchone()
    veredicto = (est.get("calibracion_veredicto") or {}).get("valor")
    bandas = {"configurada": int(cfg.get("NEWS_BANDAS_CALIBRADAS", 0)), "auto": int(cfg.get("NEWS_BANDAS_AUTO", 0)),
              "veredicto": veredicto, "muestra": (est.get("calibracion_muestra") or {}).get("valor"),
              "razones": (est.get("calibracion_razones") or {}).get("valor"),
              "cambiada_en": cambio["actualizado_en"] if cambio else None,
              "cambiada_por": cambio["actualizado_por"] if cambio else None,
              "efectiva": int(bandas_efectivas(cfg, veredicto)),
              "incorrecta": bool(int(cfg.get("NEWS_BANDAS_CALIBRADAS", 0)) and veredicto != "CALIBRADAS_OK")}

    # picks (🔥) generados vs enviados
    picks = _filas(conn, "SELECT substr(creado_en,1,10) dia, tipo, SUM(CASE WHEN dicho_discord=1 THEN 1 ELSE 0 END) enviados, "
                         "COUNT(*) generados FROM news_alerta WHERE COALESCE(prueba,0)=0 AND tipo IN ('FUEGO','FUEGO_EXPERIMENTAL') "
                         "AND creado_en>=? GROUP BY 1,2 ORDER BY 1", (desde,))
    return {"dias": dias, "desde": desde, "generado_en": ahora.isoformat(),
            "1_noticias_externas_por_dia": externas, "datos_calculados_por_dia": internas,
            "articulos_por_dia": articulos,
            "2_descartes": desc, "2_descartes_por_dia": desc_dia, "2_articulos_descartados": art_desc,
            "3_rival_sin_investigar": rival, "4_cuota_sin_actualizar": cuota, "4b_sin_cuota": sin_mercado,
            "5_entrega": entrega, "6_bandas": bandas, "picks": picks}


def bandas_efectivas(cfg: dict, veredicto: Optional[str]) -> bool:
    """v7.2: 'bandas calibradas' solo vale si el veredicto de RankingFTR lo respalda
    (NEWS_BANDAS_EXIGIR_VEREDICTO=1, default). Con 0 vuelve el comportamiento v7.1."""
    if not int(cfg.get("NEWS_BANDAS_CALIBRADAS", 0)):
        return False
    if not int(cfg.get("NEWS_BANDAS_EXIGIR_VEREDICTO", 1)):
        return True
    return veredicto == "CALIBRADAS_OK"
