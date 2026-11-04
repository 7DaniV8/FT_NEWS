"""📡 Señal interna desde TennisAlerta → FT NEWS.   (v8.2, 04/11/2026)

AUTORIZACIÓN (TennisAlerta, por escrito, 04/11/2026): usar sus mensajes SOLO como señal interna para saber a qué jugador o partido
mirar, y verificarlo con fuentes propias. Consultas moderadas, acceso habitual a la página con una cuenta autorizada, SIN compartir
credenciales. NO se republican sus textos, mensajes ni imágenes (cualquier difusión futura necesita su aprobación y reconocerlos).

Cómo cumple eso este programa:
  · Corre en TU computador, con TU sesión. No guarda ni envía usuario/contraseña: inicias sesión tú, a mano, una vez (--login) y el
    navegador deja la sesión en una carpeta local.
  · Abre la página como lo haría una persona (una carga cada --cada-min minutos, por defecto 10, mínimo 5, con variación aleatoria) y
    lee lo que la propia página ya recibió. No llama a ninguna API suya por su cuenta ni usa tokens copiados.
  · Se detiene solo si la página pide iniciar sesión, muestra un bloqueo/captcha o responde 401/403/429.
  · Solo envía a FT NEWS las novedades físicas (molestia, lesión, retiro, baja, enfermedad, regreso, MTO) como PISTA. FT NEWS la usa para
    poner al jugador al frente del radar y buscarla en fuentes autorizadas; la pista NO sale nunca a usuarios ni a Discord (ft_news/live.py
    la excluye a propósito). Lo demás (entry list, información…) solo se guarda en un CSV local para medir cobertura.

Uso (una vez):   pip install playwright && playwright install chromium
  python herramientas/tennisalerta_senal.py --url https://LA_PAGINA_DEL_LIVE --login      # inicias sesión a mano y cierras
Uso (siempre):   FT_NEWS_URL=https://<tu-ft-news> FT_NEWS_SECRET=<secreto> python herramientas/tennisalerta_senal.py --url https://LA_PAGINA_DEL_LIVE
Prueba sin enviar:  añade --seco       Una sola vuelta:  añade --una-vez"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CANAL = "TennisAlerta (señal interna)"
CHAT_ID = "tennisalerta"
MIN_CADA_MIN = 5
MAX_DIA_DEFECTO = 120
_FISICAS = re.compile(r"molest|lesi|retir|baja|enferm|regres|injur|withdr|medical|mto", re.IGNORECASE)


def _n(s) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def es_fisica(tag: str) -> bool:
    return bool(_FISICAS.search(_n(tag)))


def msg_id_de(clave: str) -> int:
    return int(hashlib.sha1(clave.encode("utf-8")).hexdigest()[:12], 16)


def extraer(respuestas: list[dict]) -> list[dict]:
    """respuestas: [{'url':..., 'json': <lo que devolvió>}] de lo que la PROPIA página cargó. Devuelve novedades normalizadas."""
    out, vistos = [], set()
    for r in respuestas:
        url, datos = r.get("url", ""), r.get("json")
        if not isinstance(datos, list):
            continue
        for d in datos:
            if not isinstance(d, dict):
                continue
            if "news_items" in url and d.get("id") and d.get("title") is not None:
                it = {"clave": "ni:" + str(d["id"]), "tipo": "NOVEDAD", "etiqueta": str(d.get("tag") or ""), "jugador": str(d.get("title") or "").strip(),
                      "ocurrio_en": d.get("occurred_at") or d.get("created_at"), "detalle": ""}
            elif "public_mto_events" in url and d.get("id") and d.get("player_name"):
                it = {"clave": "mto:" + str(d["id"]), "tipo": "MTO", "etiqueta": "MTO", "jugador": str(d["player_name"]).strip(),
                      "ocurrio_en": d.get("occurred_at"),
                      "detalle": f"Medical timeout vs {d.get('opponent_name') or '?'} ({d.get('tournament') or ''}) {d.get('score') or ''}".strip()}
            else:
                continue
            if it["jugador"] and it["clave"] not in vistos:
                vistos.add(it["clave"])
                out.append(it)
    return out


def a_pista(it: dict) -> dict:
    """El cuerpo que recibe FT NEWS en /news/telegram/pista. Primera línea = solo el jugador (así lo lee FT NEWS)."""
    texto = f"{it['jugador']}\n" + (it["detalle"] or f"{it['etiqueta']}: molestia / lesión / baja (señal interna)")
    return {"texto": texto, "canal_id": CHAT_ID, "canal": CANAL, "chat_id": CHAT_ID, "msg_id": msg_id_de(it["clave"]),
            "modo": "lesiones", "fecha": it.get("ocurrio_en")}


class Memoria:
    """Qué ya se envió (para no repetir) y cuántas pistas van hoy. Un JSON local."""
    def __init__(self, ruta: Path):
        self.ruta = ruta
        try:
            self.d = json.loads(ruta.read_text("utf-8"))
        except (OSError, ValueError):
            self.d = {}
        self.d.setdefault("vistos", {})
        self.d.setdefault("dia", "")
        self.d.setdefault("hoy", 0)

    def nuevo(self, clave: str) -> bool:
        return clave not in self.d["vistos"]

    def marcar(self, clave: str) -> None:
        self.d["vistos"][clave] = datetime.now(timezone.utc).isoformat()
        if len(self.d["vistos"]) > 5000:
            for k in sorted(self.d["vistos"], key=self.d["vistos"].get)[:1000]:
                self.d["vistos"].pop(k, None)

    def cupo(self, tope: int) -> bool:
        hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.d["dia"] != hoy:
            self.d["dia"], self.d["hoy"] = hoy, 0
        return self.d["hoy"] < tope

    def sumar(self) -> None:
        self.d["hoy"] += 1

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(json.dumps(self.d), "utf-8")


def procesar(items: list[dict], mem: Memoria, enviar, csv_ruta: Path = None, tope_dia: int = MAX_DIA_DEFECTO) -> dict:
    """enviar(cuerpo) -> bool. Devuelve el conteo. Lo que no es físico solo va al CSV local."""
    res = {"vistas": len(items), "nuevas": 0, "enviadas": 0, "solo_csv": 0, "tope": 0, "fallo_envio": 0}
    filas = []
    for it in items:
        if not mem.nuevo(it["clave"]):
            continue
        res["nuevas"] += 1
        filas.append({"fecha_hora": it.get("ocurrio_en") or "", "etiqueta": it["etiqueta"].upper(), "jugador": it["jugador"], "titulo": it["jugador"]})
        if es_fisica(it["etiqueta"]):
            if not mem.cupo(tope_dia):
                res["tope"] += 1
                continue                                       # no se marca: se intentará otro día
            if enviar(a_pista(it)):
                mem.sumar()
                res["enviadas"] += 1
            else:
                res["fallo_envio"] += 1
                continue
        else:
            res["solo_csv"] += 1
        mem.marcar(it["clave"])
    if csv_ruta and filas:
        nuevo = not csv_ruta.exists()
        csv_ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_ruta, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["fecha_hora", "etiqueta", "jugador", "titulo"])
            if nuevo:
                w.writeheader()
            w.writerows(filas)
    mem.guardar()
    return res


def enviar_a_ft_news(base: str, secreto: str):
    def _f(cuerpo: dict) -> bool:
        req = urllib.request.Request(base.rstrip("/") + "/news/telegram/pista", data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json", "X-FT-News-Secret": secreto}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return 200 <= r.status < 300
        except Exception as e:  # noqa: BLE001
            print("  no se pudo enviar a FT NEWS:", e)
            return False
    return _f


def espera_seg(cada_min: float) -> float:
    cada = max(MIN_CADA_MIN, float(cada_min))
    return cada * 60 * random.uniform(0.85, 1.25)


def _una_vuelta(pw_ctx, url: str):
    """Abre la página una vez y devuelve (items, motivo_de_parada)."""
    pagina = pw_ctx.new_page()
    capturas, parada = [], []

    def _resp(r):
        try:
            if r.status in (401, 403, 429):
                parada.append(f"HTTP {r.status} en {r.url[:80]}")
            u = r.url
            if ("news_items" in u or "public_mto_events" in u) and r.status == 200:
                capturas.append({"url": u, "json": r.json()})
        except Exception:  # noqa: BLE001
            pass
    pagina.on("response", _resp)
    pagina.goto(url, wait_until="networkidle", timeout=60000)
    pagina.wait_for_timeout(4000)
    cuerpo = (pagina.inner_text("body") or "").lower()
    if any(x in cuerpo for x in ("iniciar sesión", "inicia sesión", "log in", "captcha", "verify you are human")) and not capturas:
        parada.append("la página pide iniciar sesión o muestra un bloqueo")
    pagina.close()
    return extraer(capturas), (parada[0] if parada else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.getenv("TA_URL", ""), help="dirección de la página del LIVE (la que abres normalmente)")
    ap.add_argument("--perfil", default=str(Path.home() / ".ftnews_tennisalerta"), help="carpeta local con TU sesión del navegador")
    ap.add_argument("--cada-min", type=float, default=10.0)
    ap.add_argument("--max-dia", type=int, default=MAX_DIA_DEFECTO)
    ap.add_argument("--login", action="store_true", help="abre el navegador para que inicies sesión a mano")
    ap.add_argument("--una-vez", action="store_true")
    ap.add_argument("--seco", action="store_true", help="no envía nada a FT NEWS, solo muestra")
    a = ap.parse_args(argv)
    if not a.url:
        print("Falta --url (o la variable TA_URL).")
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Falta Playwright:  pip install playwright && playwright install chromium")
        return 2
    base, sec = os.getenv("FT_NEWS_URL", ""), os.getenv("FT_NEWS_SECRET", "")
    if not a.seco and not a.login and (not base or not sec):
        print("Faltan FT_NEWS_URL y FT_NEWS_SECRET (o usa --seco).")
        return 2
    perfil = Path(a.perfil)
    perfil.mkdir(parents=True, exist_ok=True)
    mem = Memoria(perfil / "estado.json")
    enviar = (lambda c: (print("  [seco]", c["texto"].replace("\n", " | ")) or True)) if a.seco else enviar_a_ft_news(base, sec)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(perfil / "navegador"), headless=not a.login)
        try:
            if a.login:
                pg = ctx.new_page()
                pg.goto(a.url)
                input("Inicia sesión en la ventana. Cuando veas el LIVE, vuelve aquí y pulsa Enter para guardar la sesión…")
                return 0
            while True:
                items, parada = _una_vuelta(ctx, a.url)
                if parada:
                    print("DETENIDO:", parada, "— no se insiste. Revisa la sesión (--login) o espera.")
                    return 3
                r = procesar(items, mem, enviar, perfil / "capturas.csv", a.max_dia)
                print(datetime.now().strftime("%H:%M"), r)
                if a.una_vez:
                    return 0
                time.sleep(espera_seg(a.cada_min))
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(main())
