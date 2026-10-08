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

import logging
import threading
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

from ft_news import config, costos, evaluador, fuentes, jugadores, partidos, radar
from ft_news.db import ahora_iso, estado_set, estado_todo, get_conn

log = logging.getLogger("ft_news")

PASOS = ("padron", "calibracion", "partidos", "contexto", "radar", "rss", "descubridor", "cierre", "costos")
PADRON_CADA_H = 6
CALIBRACION_CADA_H = 6
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
          ahora: Optional[datetime] = None, claude=None, rss_transport=None) -> dict:
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

    def paso(nombre, fn):
        try:
            r = fn()
            resumen["pasos"][nombre] = r
            estado_set(conn, f"paso_{nombre}", f"OK {ahora_iso()} {r}")
        except Exception as e:                       # un paso no tumba a los demás
            resumen["pasos"][nombre] = {"error": str(e)}
            estado_set(conn, f"paso_{nombre}", f"ERROR {ahora_iso()} {e}")
            log.warning("[FT_NEWS] paso %s falló: %s\n%s", nombre, e, traceback.format_exc())

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
    paso("partidos", lambda: partidos.sincronizar(conn, cliente, cfg, ahora))
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
    elif tavily is None or gemini is None:
        resumen["pasos"]["radar"] = {"motivo": "SIN_CLAVES"}
        estado_set(conn, "motivo", "radar sin TAVILY_API_KEY / GEMINI_API_KEY")
    else:
        paso("radar", lambda: radar.correr(conn, cfg, tavily, gemini, ahora,
                                           int(cfg.get("NEWS_RADAR_JUGADORES_CICLO", 40)), claude=claude))
        if gasto["aviso_80"]:
            estado_set(conn, "aviso_costos", f"80 % del tope mensual alcanzado {ahora_iso()}")
    ult_rss = (est.get("rss_en") or {}).get("valor")
    if gemini is not None and (not ult_rss or datetime.fromisoformat(ult_rss) < ahora - timedelta(minutes=RSS_CADA_MIN)):
        def _rss():
            from ft_news.lectores import rss
            r = rss.correr(conn, cfg, gemini, ahora, transport=rss_transport)
            estado_set(conn, "rss_en", ahora.isoformat())
            return r
        paso("rss", _rss)
    else:
        resumen["pasos"]["rss"] = "al día" if gemini is not None else {"motivo": "SIN_CLAVES"}
    paso("descubridor", lambda: evaluador.correr(conn, cfg, ahora))
    def _cierre():
        from ft_news import cierre
        return cierre.correr(conn, cliente, cfg, ahora)
    paso("cierre", _cierre)
    resumen["pasos"]["costos"] = costos.hoy(conn)
    resumen["llamadas_externas"] = (getattr(cliente, "llamadas", 0) + getattr(tavily, "llamadas", 0)
                                    + getattr(gemini, "llamadas", 0))
    estado_set(conn, "motivo", "activo")
    resumen["motivo"] = "OK"
    return resumen


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
