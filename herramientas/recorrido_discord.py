#!/usr/bin/env python3
"""
herramientas/recorrido_discord.py — Recorrido completo FT NEWS → FT Intelligence
→ FT Discord, con el código REAL de los tres servicios y las fuentes
externas simuladas (Tavily / clasificador / RankingFTR con el formato real de
cada API). Sin red, sin claves, sin tocar Discord: lo que FT Discord
publicaría queda impreso (y, con --salida, en un Markdown).

    FT_INTELLIGENCE_REPO=/ruta/FT_INTELLIGENCE FT_DISCORD_REPO=/ruta/FT_DISCORD \\
        python herramientas/recorrido_discord.py --salida EJEMPLOS-ALERTAS.md

Qué demuestra (Rubén, 09/10/2026 §6 y 22:52): una 📰, una 🔎 y una 🔥
experimental llegan a Discord con texto correcto, fuentes y cuotas; la 🔥 solo
sale cuando hay una cuota CONFIRMADA después de la noticia que no se movió
(ciclo 2); la cuota que ya se movió hacia la noticia queda 🔎; un retiro del
mismo torneo queda 🔎; un segundo ciclo no repite nada (clave única en los
tres servicios).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

HOY = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)


# ── 1. FT NEWS con fuentes simuladas ─────────────────────────────────────
class RankingFTR:
    """Padrón UTR + fixtures con cuotas (formato de /ft-intel/*). `cap` = hora de
    captura de la cuota (actualizado_en); `soler` = cuota de Soler (se mueve en el 2.º ciclo)."""
    veredicto = "NO_CALIBRADAS"
    cap = (HOY - timedelta(hours=4)).isoformat()
    soler = (1.65, 2.20)

    def calibracion(self):
        return {"veredicto": self.veredicto, "muestra": 187, "razones": ["Muestra insuficiente (187 < 300)"]}

    def utr_padron(self, desde_id=0, limite=2000):
        js = [("Mateo Quiroga", "M", "ARG", 7101, 12.85), ("Luca Bertolini", "M", "ITA", 7102, 12.41),
              ("Valentina Soler", "F", "ESP", 7103, 10.62), ("Hanna Kowal", "F", "POL", 7104, 10.20),
              ("Nicolás Ferreyra", "M", "ARG", 7105, 11.30), ("Tom Whitlock", "M", "GBR", 7106, 11.05)]
        return {"jugadores": [{"player_id": i + 1, "nombre_ftr": n, "nombre_utr": n, "genero": g, "nacionalidad": p,
                               "utr_player_id": u, "utr_singles": s, "fecha_captura": (HOY - timedelta(days=2)).isoformat()}
                              for i, (n, g, p, u, s) in enumerate(js)], "siguiente_desde_id": None}

    def fixtures(self, horas_adelante=72):
        cap = self.cap
        return {"fixtures": [
            {"fixture_id": 88001, "fecha": (HOY + timedelta(hours=21)).isoformat(), "torneo": "Challenger Lima", "superficie": "clay",
             "genero": "M", "jugador1": "Quiroga M.", "jugador2": "Bertolini L.", "odd1": 1.42, "odd2": 2.85, "actualizado_en": cap},
            {"fixture_id": 88002, "fecha": (HOY + timedelta(hours=26)).isoformat(), "torneo": "W75 Reus", "superficie": "clay",
             "genero": "F", "jugador1": "Soler V.", "jugador2": "Kowal H.", "odd1": self.soler[0], "odd2": self.soler[1], "actualizado_en": cap},
            {"fixture_id": 88003, "fecha": (HOY + timedelta(hours=44)).isoformat(), "torneo": "M25 Sevilla", "superficie": "clay",
             "genero": "M", "jugador1": "Ferreyra N.", "jugador2": "Whitlock T.", "odd1": 1.90, "odd2": 1.90, "actualizado_en": cap}]}

    def historial(self, desde, hasta=None):
        return {"partidos": []}

    def antecedentes(self, player_id, torneo):
        return {"partidos": []}

    def defensa(self):
        return {"jugadores": []}


def _rfc(d: datetime) -> str:
    return d.strftime("%a, %d %b %Y %H:%M:%S GMT")


ARTICULOS = {
    # 🔥 experimental: hecho reportado por prensa, publicado DESPUÉS de la última cuota, en challenger
    "Mateo Quiroga": [{"title": "Quiroga jugó infiltrado y llega tocado a Lima", "url": "https://www.puntodebreak.com/quiroga-lima-tobillo",
                       "content": "Mateo Quiroga confirmó que jugó infiltrado la final de Bogotá por una molestia en el tobillo derecho y "
                                  "que llega a Lima 'con lo justo'. Su equipo evaluará mañana si sale a la pista.",
                       "published_date": _rfc(HOY - timedelta(hours=2)), "score": 0.93}],
    # 🔎: declaración (no hecho) y la cuota confirmada después de la noticia ya se movió → PARTIDO INTERESANTE
    "Valentina Soler": [{"title": "Soler: 'Llego a Reus con molestias en el hombro'", "url": "https://www.puntodebreak.com/soler-reus-hombro",
                         "content": "Valentina Soler reconoció molestias en el hombro tras una semana de carga alta: 'Veremos cómo amanezco'.",
                         "published_date": _rfc(HOY - timedelta(hours=3)), "score": 0.9}],
    # 📰 sin partido… (Whitlock sí tiene partido; la 📰 se demuestra con Whitlock y además sin partido con otro) → retiro
    "Tom Whitlock": [{"title": "Whitlock withdraws from Sevilla with wrist injury", "url": "https://tennistourtalk.com/whitlock-withdraws-sevilla",
                      "content": "British player Tom Whitlock has withdrawn from the M25 Sevilla event with a right wrist injury, the ITF confirmed.",
                      "published_date": _rfc(HOY - timedelta(hours=1)), "score": 0.95}],
}
LECTURAS = {
    "Mateo Quiroga": {"sobre_jugador": True, "confianza_identidad": 0.95, "categoria": "LESION_MOLESTIA", "direccion": "NEGATIVA",
                      "naturaleza": "HECHO", "fecha_evento": (HOY - timedelta(days=1)).strftime("%Y-%m-%d"),
                      "resumen_es": "Quiroga jugó infiltrado la final de Bogotá por una molestia en el tobillo derecho y llega a Lima con lo justo.",
                      "titular": "Molestias en el tobillo derecho",
                      "relevancia_deportiva": "movilidad y desplazamientos en polvo de ladrillo", "fragmento_original": "jugó infiltrado la final", "idioma": "es"},
    "Valentina Soler": {"sobre_jugador": True, "confianza_identidad": 0.92, "categoria": "LESION_MOLESTIA", "direccion": "NEGATIVA",
                        "naturaleza": "DECLARACION", "fecha_evento": (HOY - timedelta(days=1)).strftime("%Y-%m-%d"),
                        "resumen_es": "Soler reconoció molestias en el hombro tras una semana de carga alta.",
                        "titular": "Molestias en el hombro",
                        "relevancia_deportiva": "saque", "fragmento_original": "molestias en el hombro", "idioma": "es"},
    "Tom Whitlock": {"sobre_jugador": True, "confianza_identidad": 0.97, "categoria": "RETIRO_ABANDONO", "direccion": "NEGATIVA",
                     "naturaleza": "HECHO", "fecha_evento": HOY.strftime("%Y-%m-%d"),
                     "resumen_es": "Whitlock se retiró del M25 de Sevilla por una lesión en la muñeca derecha (confirmado por la ITF).",
                     "titular": "Se retiró del M25 de Sevilla por la muñeca",
                     "relevancia_deportiva": "no juega", "fragmento_original": "has withdrawn", "idioma": "en"},
}


def _tavily():
    from ft_news.proveedores.tavily import Tavily
    pedidos = []

    def h(req: httpx.Request):
        c = json.loads(req.content)
        pedidos.append(c)
        for nombre, arts in ARTICULOS.items():
            if nombre in c["query"]:
                return httpx.Response(200, json={"results": arts, "response_time": 0.4})
        return httpx.Response(200, json={"results": [], "response_time": 0.2})
    return Tavily(api_key="tvly-simulada", transport=httpx.MockTransport(h)), pedidos


def _clasificador():
    from ft_news.proveedores.gemini import Gemini
    llamadas = {"n": 0}

    def h(req: httpx.Request):
        llamadas["n"] += 1
        cuerpo = json.dumps(json.loads(req.content))
        datos = next((d for n, d in LECTURAS.items() if n in cuerpo), None) or {
            "sobre_jugador": False, "confianza_identidad": 0.1, "categoria": "OTRA", "direccion": "NEUTRA",
            "naturaleza": "NO_VERIFICADA", "fecha_evento": None, "resumen_es": "", "relevancia_deportiva": "", "fragmento_original": "", "idioma": "en"}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(datos)}]}}],
                                         "usageMetadata": {"promptTokenCount": 820, "candidatesTokenCount": 110}})
    return Gemini(api_key="g-simulada", transport=httpx.MockTransport(h)), llamadas


def correr_ft_news(db: Path) -> dict:
    os.environ["FT_NEWS_DB_PATH"] = str(db)
    os.environ["FT_NEWS_SECRET"] = "secreto-recorrido"
    os.environ["FT_NEWS_SIN_WORKER"] = "1"
    from ft_news import config, fuentes, tareas
    from ft_news.db import get_conn
    config.NEWS_SECRET, config.DB_PATH = "secreto-recorrido", db      # por si ft_news ya estaba importado (pytest)
    conn = get_conn(db)
    fuentes.sembrar(conn, iniciales=["tennistourtalk.com", "puntodebreak.com"])
    cfg = config.leer_config(conn)
    cfg.update(NEWS_ACTIVO=1, NEWS_DISCORD_ACTIVO=1, NEWS_IDIOMAS="en,es", NEWS_RADAR_TEMATICO_ACTIVO=0)
    tav, pedidos = _tavily()
    gem, llamadas = _clasificador()
    # Ciclo 1: noticias encontradas; la única cuota es de ANTES de las noticias → 🔎 pendientes de cuota
    r1 = tareas.ciclo(conn, cliente=RankingFTR(), cfg=cfg, tavily=tav, gemini=gem, ahora=HOY)
    # Ciclo 2 (15 min después): RankingFTR confirma las cuotas DESPUÉS de las noticias. Quiroga sigue 1.42
    # (el mercado no reaccionó → 🔥 experimental); Soler ya se alargó 1.65 → 1.80 (el mercado la incorporó → 🔎).
    f2 = RankingFTR()
    f2.cap = (HOY + timedelta(minutes=5)).isoformat()
    f2.soler = (1.80, 2.00)
    r2 = tareas.ciclo(conn, cliente=f2, cfg=cfg, tavily=tav, gemini=gem, ahora=HOY + timedelta(minutes=15))
    from ft_news.db import config_guardar
    config_guardar(conn, "NEWS_DISCORD_ACTIVO", "1", "recorrido")
    config_guardar(conn, "NEWS_ACTIVO", "1", "recorrido")
    return {"conn": conn, "ciclos": [r1, r2], "tavily": len(pedidos), "ia": llamadas["n"]}


# ── 2. FT Intelligence (transporte) ──────────────────────────────────────
def correr_ft_intelligence(ruta_repo: str, ft_news_app, tmp: Path, ahora: datetime) -> dict:
    sys.path.insert(0, ruta_repo)
    os.environ.update({"FT_INTEL_DB_PATH": str(tmp / "fti.db"), "FTR_SERVICE_URL": "http://rankingftr.test",
                       "FTR_INTERNAL_SECRET": "s", "FT_NEWS_URL": "http://ftnews.test", "FT_NEWS_SECRET": "secreto-recorrido"})
    from fastapi.testclient import TestClient
    from ft_intelligence import news
    from ft_intelligence.cliente_http import cliente_news
    from ft_intelligence.db import conectar
    from ft_intelligence.senales import leer
    tc = TestClient(ft_news_app)
    tc.__enter__()

    def h(req: httpx.Request):
        r = tc.request(req.method, str(req.url.path) + (f"?{req.url.query.decode()}" if req.url.query else ""),
                       headers=dict(req.headers), content=req.content)
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": r.headers.get("content-type", "application/json")})
    conn = conectar(tmp / "fti.db")
    cli = cliente_news(transport=httpx.MockTransport(h))
    r1 = news.sincronizar(conn, cli, ahora)
    r2 = news.sincronizar(conn, cli, ahora + timedelta(minutes=1))       # nada nuevo: no repite
    # v7.3: el TestClient queda abierto: después de FT Discord, FT Intelligence le informa a FT
    # NEWS la publicación real (acuse). correr_todo lo cierra.
    return {"conn": conn, "pasadas": [r1, r2], "senales": leer(conn)["senales"], "cli": cli, "tc": tc}


# ── 3. FT Discord (anunciador real, publicación capturada) ───────────────
def correr_ft_discord(ruta_repo: str, conn_fti: sqlite3.Connection, ahora: datetime,
                      canal_admin: bool = True) -> dict:
    sys.path.insert(0, ruta_repo)
    os.environ.setdefault("DISCORD_TOKEN", "x")
    os.environ.setdefault("FT_INTEL_URL", "https://ft-intel.test")
    os.environ.setdefault("FTR_INTERNAL_SECRET", "s")
    from ft_discord.anunciador import Anunciador
    from ft_discord.fuente import Fuente
    sys.path.insert(0, os.environ.get("FT_INTELLIGENCE_REPO", ""))
    from ft_intelligence.senales import leer
    cfg_remota = {"tipos": {t: {"texto": True, "voz": True, "encabezado": None, "voz_inicio": None}
                            for t in ("NEWS_VALOR", "NEWS_INTERESANTE", "NEWS_NOTICIA")}}

    async def h(req: httpx.Request):
        if req.url.path == "/discord-config":
            return httpx.Response(200, json=cfg_remota)
        if req.url.path == "/senales/acuse":                  # v7.3: el acuse vuelve a FT Intelligence (código real)
            import json as _json
            from ft_intelligence.implicacion import guardar_acuses
            acuses.extend(_json.loads(req.content)["acuses"])
            return httpx.Response(200, json={"ok": True, "guardados": guardar_acuses(conn_fti, _json.loads(req.content)["acuses"])})
        desde = int(req.url.params.get("desde_id", 0))
        d = leer(conn_fti, desde)
        return httpx.Response(200, json=d)
    publicados, voces, admin, acuses = [], [], [], []

    async def publicar(texto):
        publicados.append(texto)

    async def publicar_admin(texto):
        admin.append(texto)
    fuente = Fuente("https://ft-intel.test", "s", transport=httpx.MockTransport(h))
    an = Anunciador(fuente, publicar, lambda v: voces.append(v) or True, "America/Bogota",
                    {"NEWS_VALOR", "NEWS_INTERESANTE", "NEWS_NOTICIA"}, {"NEWS_VALOR", "NEWS_NOTICIA"},
                    max_antiguedad_min=60, reloj=lambda: ahora,
                    **({"publicar_admin": publicar_admin} if canal_admin else {}))

    async def _go():
        await an.arrancar(0)                      # cursor en 0: lee todo lo que FT Intelligence tenga
        r1 = await an.ciclo()
        r2 = await an.ciclo()
        await fuente.cerrar()
        return r1, r2
    r1, r2 = asyncio.run(_go())
    return {"ciclos": [dict(r1), dict(r2)], "publicados": publicados, "voces": voces, "admin": admin, "acuses": acuses}


def correr_todo(ruta_fti: str, ruta_disc: str, con_prueba: bool = False, canal_admin: bool = True) -> dict:
    """Ida y vuelta: FT NEWS → FT Intelligence → FT Discord → (acuse) → FT Intelligence → FT NEWS.
    con_prueba: además, la 🧪 PRUEBA de admin (debe salir SOLO por el canal de administradores).
    canal_admin=False: FT Discord sin DISCORD_CANAL_ADMIN_ID (la prueba no debe salir por ningún lado)."""
    tmp = Path(tempfile.mkdtemp())
    n = correr_ft_news(tmp / "ft_news.db")
    from ft_news import alertas
    from ft_news.app import app
    from ft_news.db import config_guardar
    ahora = HOY + timedelta(minutes=16)
    prueba = None
    if con_prueba:
        config_guardar(n["conn"], "NEWS_PRUEBA_SOLO_ADMIN_VERIFICADA", "1", "recorrido")
        prueba = alertas.crear_prueba(n["conn"], "recorrido", ahora=ahora)
    i = correr_ft_intelligence(ruta_fti, app, tmp, ahora)
    d = correr_ft_discord(ruta_disc, i["conn"], ahora, canal_admin=canal_admin)
    from ft_intelligence import news as fti_news
    vuelta = fti_news.reportar_publicaciones(i["conn"], i["cli"], ahora + timedelta(minutes=1))
    vuelta2 = fti_news.reportar_publicaciones(i["conn"], i["cli"], ahora + timedelta(minutes=2))   # no repite
    i["tc"].__exit__(None, None, None)
    return {"news": n, "intel": i, "discord": d, "alertas": alertas.listar(n["conn"]),
            "vuelta": [vuelta, vuelta2],
            "prueba": alertas.estado_prueba(n["conn"], prueba["id"]) if prueba else None}


def informe(r: dict) -> str:
    out = ["# Recorrido FT NEWS → FT Intelligence → FT Discord (código real, fuentes simuladas)", "",
           f"Generado {datetime.now(timezone.utc).isoformat()[:16]} UTC. Sin claves ni red: Tavily, el clasificador y RankingFTR",
           "están simulados con el formato real de cada API; FT Intelligence y FT Discord corren con su código tal cual.", "",
           "## FT NEWS", ""]
    for k, c in enumerate(r["news"]["ciclos"], 1):
        p = c["pasos"]
        out.append(f"- ciclo {k}: radar {p.get('radar')} · descubridor {p.get('descubridor')} · costos {p.get('costos', {}).get('usd')} US$")
    out += ["", f"Búsquedas Tavily: {r['news']['tavily']} · llamadas al clasificador: {r['news']['ia']}", "", "### Alertas seleccionadas (news_alerta)", ""]
    for a in reversed(r["alertas"]):
        out.append(f"- **{a['tipo']}** · {a.get('jugador')}{' vs ' + a['rival'] if a.get('rival') else ' (sin partido)'} · "
                   f"dicho_discord={a['dicho_discord']}{' (' + str(a.get('dicho_motivo')) + ')' if a.get('dicho_motivo') else ''}")
        out.append(f"  - por qué (usuario): {a.get('motivo_simple')}")
        out.append(f"  - por qué (técnico, admin): {a['motivo_seleccion']}")
    # v7: la lectura simple de cada evaluación (lo que ve el usuario en la pestaña)
    out += ["", "### Evaluaciones · lectura simple (v7, lo que ve el usuario)", ""]
    for e in r["news"]["conn"].execute("SELECT id, tipo_alerta, motivo, lectura_json FROM news_evaluacion ORDER BY id").fetchall():
        try:
            l = json.loads(e["lectura_json"] or "{}")
        except (TypeError, ValueError):
            l = {}
        out += [f"- evaluación #{e['id']} · técnico: {e['tipo_alerta']} / {e['motivo']}", "```", l.get("texto") or "(sin lectura)", "```", ""]
    out += ["", "## FT Intelligence", ""]
    for k, p in enumerate(r["intel"]["pasadas"], 1):
        out.append(f"- pasada {k}: {p['detalle']}")
    out.append(f"- señales guardadas: {[(s['tipo'], s['clave']) for s in r['intel']['senales']]}")
    out += ["", "## FT Discord", ""]
    for k, c in enumerate(r["discord"]["ciclos"], 1):
        out.append(f"- ciclo {k}: {c}")
    out += ["", "### Mensajes publicados (tal cual irían al canal)", ""]
    for t in r["discord"]["publicados"]:
        out += ["```", t, "```", ""]
    out += ["### Frases de voz", ""] + [f"- {v}" for v in r["discord"]["voces"]]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="")
    a = ap.parse_args()
    fti, disc = os.environ.get("FT_INTELLIGENCE_REPO", ""), os.environ.get("FT_DISCORD_REPO", "")
    if not fti or not disc:
        print("Definir FT_INTELLIGENCE_REPO y FT_DISCORD_REPO (rutas a los repos).")
        return 2
    r = correr_todo(fti, disc)
    txt = informe(r)
    print(txt)
    if a.salida:
        Path(a.salida).write_text(txt, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
