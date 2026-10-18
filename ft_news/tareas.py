"""
ft_news/tareas.py — El worker (Fases 1–3).

Un ciclo cada CICLO_SEGUNDOS. Con NEWS_ACTIVO=0 (default) el ciclo NO hace
ninguna llamada externa; solo escribe su estado. Con NEWS_ACTIVO=1, en
orden (diseño §5), cada paso aislado: si uno falla, los demás siguen y el
error queda en news_estado:
  padron        identidad maestra desde RankingFTR (cada 6 h)
  partidos      radar inverso mínimo: fixtures del BOT en ≤ 72 h → cola
  radar         radar directo: Tavily + Gemini sobre la cola (presupuesto)
  descubridor   evaluación de cada partido en ventana → 🔥 / 🔎
  cierre        (Fase 4) resultados: todavía no
  costos        contadores y aviso al 80 %
Ningún paso lee una fuente sin autorizar: el radar usa solo los dominios
con autorizada=1 (fuentes.permitida).
"""
from __future__ import annotations

import os

import logging
import threading
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import alertas, config, costos, descartes, evaluador, fuentes, jugadores, memoria, partidos, radar
from ft_news.db import ahora_iso, estado_set, estado_todo, get_conn

log = logging.getLogger("ft_news")

PASOS = ("padron", "calibracion", "partidos", "contexto", "radar", "rss", "telegram", "descubridor", "cierre", "costos")
PADRON_CADA_H = 6
CALIBRACION_CADA_H = 6
CAIDO_REINTENTO_H = 6          # un clasificador caído (clave/modelo) se vuelve a probar a las 6 h
RSS_CADA_MIN = 60
CONTEXTO_CADA_MIN = 60


def calibrar_automatico(conn, cliente, cfg: dict, ahora: datetime) -> dict:
    """Pide el informe de calibración a RankingFTR y, con NEWS_BANDAS_AUTO=1,
    sigue su veredicto: CALIBRADAS_OK → NEWS_BANDAS_CALIBRADAS=1 (habilita 🔥);
    NO_CALIBRADAS → 0. Es la regla de Rubén (no afirmar sin evidencia) sin
    necesitar un clic. El informe completo queda en news_estado."""
    inf = cliente.calibracion()
    veredicto = inf.get("veredicto", "NO_CALIBRADAS")
    estado_set(conn, "calibracion_veredicto", veredicto)
    estado_set(conn, "calibracion_muestra", inf.get("muestra", 0))
    estado_set(conn, "calibracion_razones", " | ".join(inf.get("razones") or [])[:900])
    estado_set(conn, "calibracion_en", ahora.isoformat())
    cambio = None
    if cfg.get("NEWS_BANDAS_AUTO"):
        nuevo = 1 if veredicto == "CALIBRADAS_OK" else 0
        if int(cfg.get("NEWS_BANDAS_CALIBRADAS", 0)) != nuevo:
            from ft_news.db import config_guardar
            config_guardar(conn, "NEWS_BANDAS_CALIBRADAS", str(nuevo), "auto-calibracion")
            cfg["NEWS_BANDAS_CALIBRADAS"] = nuevo
            cambio = nuevo
    return {"veredicto": veredicto, "muestra": inf.get("muestra", 0), "bandas_calibradas": int(cfg.get("NEWS_BANDAS_CALIBRADAS", 0)),
            "cambio": cambio}


def elegir_clasificador(cfg: dict, gemini, claude, estado: Optional[dict] = None):
    """(principal, segunda). NEWS_CLASIFICADOR: gemini | claude | auto.
    auto: Gemini si existe y no está marcado caído (clasificador_caido en el
    estado, lo pone el failover); si no, Claude. El otro hace la segunda
    lectura. Sin ninguno → (None, None)."""
    modo = str(cfg.get("NEWS_CLASIFICADOR", "auto") or "auto").strip().lower()
    caido = ((estado or {}).get("clasificador_caido") or {}).get("valor") or ""
    # La marca de "caído" vence a las CAIDO_REINTENTO_H: se vuelve a probar el principal.
    try:
        partes = caido.split(" ", 2)
        if len(partes) >= 2 and datetime.fromisoformat(partes[1]) < datetime.now(timezone.utc) - timedelta(hours=CAIDO_REINTENTO_H):
            caido = ""
    except (ValueError, TypeError):
        caido = ""
    if modo == "claude":
        return (claude, gemini) if claude is not None else (gemini, None)
    if modo == "gemini":
        return (gemini, claude) if gemini is not None else (claude, None)
    # auto
    if gemini is not None and not caido.startswith("gemini"):
        return gemini, claude
    if claude is not None and not caido.startswith("claude"):
        return claude, gemini
    if gemini is not None:
        return gemini, claude
    return claude, None


def _proveedores(cliente_tavily=None, cliente_gemini=None, cliente_claude=None):
    """Los reales solo si hay clave; si no, None y el radar lo anota."""
    if cliente_tavily is None and config.TAVILY_API_KEY:
        from ft_news.proveedores.tavily import Tavily
        cliente_tavily = Tavily()
    if cliente_gemini is None and config.GEMINI_API_KEY:
        from ft_news.proveedores.gemini import Gemini
        cliente_gemini = Gemini()
    if cliente_claude is None and config.ANTHROPIC_API_KEY:
        from ft_news.proveedores.claude import Claude
        cliente_claude = Claude()
    return cliente_tavily, cliente_gemini, cliente_claude


def ciclo(conn, cliente=None, cfg: Optional[dict] = None, tavily=None, gemini=None,
          ahora: Optional[datetime] = None, claude=None, rss_transport=None, fotos_cli=None) -> dict:
    """Un ciclo. Devuelve un resumen (para tests y para /news/estado)."""
    ahora = ahora or datetime.now(timezone.utc)
    cfg = cfg or config.leer_config(conn)
    fuentes.sembrar(conn)
    resumen = {"activo": bool(cfg["NEWS_ACTIVO"]), "pasos": {}, "llamadas_externas": 0}
    estado_set(conn, "ultimo_ciclo_en", ahora.isoformat())
    estado_set(conn, "activo", int(cfg["NEWS_ACTIVO"]))
    estado_set(conn, "bandas_calibradas", int(cfg["NEWS_BANDAS_CALIBRADAS"]))
    estado_set(conn, "fuentes_autorizadas", conn.execute("SELECT COUNT(*) FROM news_fuente WHERE autorizada=1").fetchone()[0])
    if not cfg["NEWS_ACTIVO"]:
        estado_set(conn, "motivo", "NEWS_ACTIVO=0: apagado; sin llamadas externas")
        resumen["motivo"] = "APAGADO"
        return resumen
    if cliente is None:
        from ft_news.cliente_rankingftr import Cliente
        cliente = Cliente()
    tavily, gemini, claude = _proveedores(tavily, gemini, claude)
    # 09/10/2026 (Rubén: "¿y si usamos Anthropic?"): el clasificador principal
    # puede ser Gemini o Claude. `clasificador` es el que lee todo; `segunda`
    # (el otro, si hay) relee lo que aspira a 🔥.
    clasificador, segunda = elegir_clasificador(cfg, gemini, claude, estado_todo(conn))

    def paso(nombre, fn):
        try:
            r = fn()
            resumen["pasos"][nombre] = r
            estado_set(conn, f"paso_{nombre}", f"OK {ahora_iso()} {r}")
        except Exception as e:                       # un paso no tumba a los demás
            from ft_news.proveedores.tavily import sin_claves
            msg = sin_claves(str(e))
            resumen["pasos"][nombre] = {"error": msg}
            estado_set(conn, f"paso_{nombre}", f"ERROR {ahora_iso()} {msg}")
            log.warning("[FT_NEWS] paso %s falló: %s\n%s", nombre, msg, sin_claves(traceback.format_exc()))

    est = estado_todo(conn)
    ult_padron = (est.get("padron_en") or {}).get("valor")
    if not ult_padron or datetime.fromisoformat(ult_padron) < ahora - timedelta(hours=PADRON_CADA_H):
        def _padron():
            r = jugadores.sincronizar_padron(conn, cliente)
            estado_set(conn, "padron_en", ahora.isoformat())
            return r
        paso("padron", _padron)
    else:
        resumen["pasos"]["padron"] = "al día"
    ult_cal = (est.get("calibracion_en") or {}).get("valor")
    if not ult_cal or datetime.fromisoformat(ult_cal) < ahora - timedelta(hours=CALIBRACION_CADA_H):
        paso("calibracion", lambda: calibrar_automatico(conn, cliente, cfg, ahora))
    else:
        resumen["pasos"]["calibracion"] = f"al día ({(est.get('calibracion_veredicto') or {}).get('valor')})"
    # v7.2 (13/10/2026): "bandas calibradas" marcada a mano sin veredicto CALIBRADAS_OK
    # no se aplica (las 🔥 saldrían como validadas sin evidencia). Solo en memoria,
    # para este ciclo: la configuración guardada no se toca; el semáforo lo marca.
    veredicto = (estado_todo(conn).get("calibracion_veredicto") or {}).get("valor")
    if int(cfg.get("NEWS_BANDAS_CALIBRADAS", 0)) and not descartes.bandas_efectivas(cfg, veredicto):
        cfg = dict(cfg, NEWS_BANDAS_CALIBRADAS=0)
        estado_set(conn, "bandas_aviso", f"NEWS_BANDAS_CALIBRADAS=1 sin veredicto CALIBRADAS_OK ({veredicto}): "
                                         f"se trabaja como SIN calibrar · {ahora_iso()}")
    else:
        estado_set(conn, "bandas_aviso", "")
    estado_set(conn, "bandas_efectivas", int(cfg.get("NEWS_BANDAS_CALIBRADAS", 0)))
    paso("partidos", lambda: partidos.sincronizar(conn, cliente, cfg, ahora))
    # v5: una sola vez, los partidos duplicados que ya estaban en la base se funden
    if not (est.get("fusion_duplicados_en") or {}).get("valor"):
        def _fusion():
            r = partidos.fusionar_duplicados(conn)
            estado_set(conn, "fusion_duplicados_en", ahora.isoformat())
            return r
        paso("fusion_duplicados", _fusion)
    paso("vencimientos", lambda: memoria.vencer_db(conn, ahora))
    ult_ctx = (est.get("contexto_en") or {}).get("valor")
    if not ult_ctx or datetime.fromisoformat(ult_ctx) < ahora - timedelta(minutes=CONTEXTO_CADA_MIN):
        def _ctx():
            from ft_news import contexto
            r = contexto.correr(conn, cliente, cfg, ahora)
            estado_set(conn, "contexto_en", ahora.isoformat())
            return r
        paso("contexto", _ctx)
    else:
        resumen["pasos"]["contexto"] = "al día"
    gasto = costos.puede_gastar(conn, cfg)
    if not gasto["ok"]:
        resumen["pasos"]["radar"] = {"motivo": gasto["motivo"]}
        estado_set(conn, "motivo", f"radar dormido por {gasto['motivo']}")
    elif tavily is None or clasificador is None:
        resumen["pasos"]["radar"] = {"motivo": "SIN_CLAVES"}
        estado_set(conn, "motivo", "radar sin TAVILY_API_KEY o sin clasificador (GEMINI_API_KEY / ANTHROPIC_API_KEY)")
    else:
        def _radar():
            r = radar.correr(conn, cfg, tavily, clasificador, ahora,
                             int(cfg.get("NEWS_RADAR_JUGADORES_CICLO", 40)), claude=segunda)
            m = str(r.get("motivo") or "")
            # Failover: el principal murió (clave/modelo) y hay otro → se anota
            # para que el PRÓXIMO ciclo arranque con el otro.
            if m.startswith("PROVEEDOR:") and segunda is not None and any(
                    k in m for k in ("rechazó la clave", "no disponible", "ningún modelo", "sin configurar")):
                estado_set(conn, "clasificador_caido", f"{clasificador.nombre} {ahora_iso()} {m[:200]}")
                r["failover"] = f"{clasificador.nombre} caído: el próximo ciclo usa {segunda.nombre}"
            return r
        paso("radar", _radar)
        paso("reintentos", lambda: radar.reintentar_pendientes(conn, cfg, clasificador, ahora, claude=segunda))
        try:
            estado_set(conn, "clasificador", f"{clasificador.nombre} · {clasificador.modelo}"
                       + (f" · {clasificador.aviso}" if getattr(clasificador, "aviso", None) else "")
                       + (f" · segunda lectura: {segunda.nombre}" if segunda is not None else ""))
            if clasificador.nombre == "gemini":
                estado_set(conn, "gemini_modelo", f"{clasificador.modelo}" + (f" · {clasificador.aviso}" if clasificador.aviso else ""))
        except Exception:                                   # pragma: no cover
            pass
        if gasto["aviso_80"]:
            estado_set(conn, "aviso_costos", f"80 % del tope mensual alcanzado {ahora_iso()}")
    ult_tem = (est.get("tematico_en") or {}).get("valor")
    cada_tem = int(cfg.get("NEWS_RADAR_TEMATICO_CADA_H", 6))
    if tavily is not None and clasificador is not None and gasto["ok"] and (
            not ult_tem or datetime.fromisoformat(ult_tem) < ahora - timedelta(hours=cada_tem)):
        def _tematico():
            r = radar.correr_tematico(conn, cfg, tavily, clasificador, ahora, claude=segunda)
            estado_set(conn, "tematico_en", ahora.isoformat())
            return r
        paso("tematico", _tematico)
    else:
        resumen["pasos"]["tematico"] = "al día" if tavily is not None and clasificador is not None else {"motivo": "SIN_CLAVES"}
    ult_rss = (est.get("rss_en") or {}).get("valor")
    if clasificador is not None and (not ult_rss or datetime.fromisoformat(ult_rss) < ahora - timedelta(minutes=RSS_CADA_MIN)):
        def _rss():
            from ft_news.lectores import rss
            r = rss.correr(conn, cfg, clasificador, ahora, transport=rss_transport)
            estado_set(conn, "rss_en", ahora.isoformat())
            return r
        paso("rss", _rss)
    else:
        resumen["pasos"]["rss"] = "al día" if clasificador is not None else {"motivo": "SIN_CLAVES"}
    # v8.0: pistas de Telegram (las que no se leyeron al llegar, reintentos y vencimiento de las no confirmadas)
    def _telegram():
        from ft_news.lectores import telegram
        return telegram.procesar(conn, cfg, clasificador, ahora)
    paso("telegram", _telegram)
    paso("descubridor", lambda: evaluador.correr(conn, cfg, ahora))
    paso("alertas_vencidas", lambda: {"vencidas": alertas.vencer_pendientes(conn, cfg, ahora)})
    # v7.6: fotos con licencia (Wikimedia Commons) de los jugadores que puede mostrar la portada. Pocas por vuelta;
    # en las pruebas (FT_NEWS_SIN_WORKER=1) solo con un cliente falso.
    if fotos_cli is not None or os.getenv("FT_NEWS_SIN_WORKER") != "1":
        from ft_news import fotos
        paso("fotos", lambda: fotos.completar(conn, cfg, fotos.jugadores_de_portada(conn, ahora), ahora, cli=fotos_cli))
    def _cierre():
        from ft_news import cierre
        return cierre.correr(conn, cliente, cfg, ahora)
    paso("cierre", _cierre)
    resumen["pasos"]["costos"] = costos.hoy(conn)
    resumen["llamadas_externas"] = (getattr(cliente, "llamadas", 0) + getattr(tavily, "llamadas", 0)
                                    + getattr(clasificador, "llamadas", 0) + getattr(segunda, "llamadas", 0))
    estado_set(conn, "motivo", "activo")
    resumen["motivo"] = "OK"
    return resumen


def procesar_pistas_ya() -> dict:
    """v8.0: lee enseguida las pistas de Telegram recién llegadas (en un hilo, al recibirlas), sin esperar el ciclo."""
    conn = get_conn()
    try:
        cfg = config.leer_config(conn)
        if not cfg["NEWS_ACTIVO"]:
            return {"motivo": "APAGADO"}
        _t, gemini, claude = _proveedores(cliente_tavily=False)
        clasificador, _seg = elegir_clasificador(cfg, gemini, claude, estado_todo(conn))
        from ft_news.lectores import telegram
        return telegram.procesar(conn, cfg, clasificador, limite=10)
    except Exception as e:                                       # pragma: no cover
        log.warning("[FT_NEWS] pistas: %s", e)
        return {"error": str(e)[:200]}
    finally:
        conn.close()


class Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="ft-news-worker")
        self.parar = threading.Event()

    def run(self) -> None:
        while not self.parar.is_set():
            try:
                conn = get_conn()
                try:
                    r = ciclo(conn)
                    log.info("[FT_NEWS] ciclo: %s", r.get("motivo"))
                finally:
                    conn.close()
            except Exception:
                log.exception("[FT_NEWS] ciclo falló")
            self.parar.wait(config.CICLO_SEGUNDOS)
