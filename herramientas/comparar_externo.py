"""Compara el LIVE de FT NEWS con una lista de novedades de referencia (CSV que TÚ preparas a mano: fecha_hora, etiqueta, jugador, titulo).

Uso:  python herramientas/comparar_externo.py referencia.csv [ruta_base.db]
Dice, por etiqueta, qué % de las novedades de la lista ya estaba en nuestro LIVE (mismo jugador, ±36 h) y cuánto
antes/después salió el nuestro. No lee ninguna web: solo tu CSV y nuestra base."""
import csv
import sqlite3
import sys
import unicodedata
from datetime import datetime, timedelta, timezone


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def _dt(s):
    try:
        d = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def comparar(filas_ref: list[dict], live: list[dict], ventana_h: int = 36) -> dict:
    por_et: dict = {}
    for r in filas_ref:
        et, jug, t = (r.get("etiqueta") or "?").upper(), _n(r.get("jugador")), _dt(r.get("fecha_hora"))
        res = por_et.setdefault(et, {"total": 0, "cubiertas": 0, "diffs_min": []})
        res["total"] += 1
        if not t or not jug:
            continue
        cand = [x for x in live if _n(x.get("jugador")) == jug and _dt(x.get("ocurrio_en"))
                and abs(_dt(x["ocurrio_en"]) - t) <= timedelta(hours=ventana_h)]
        if cand:
            res["cubiertas"] += 1
            mejor = min(cand, key=lambda x: _dt(x["publicado_en"]) if _dt(x.get("publicado_en")) else t)
            res["diffs_min"].append(round((_dt(mejor["publicado_en"]) - t).total_seconds() / 60))
    out = {}
    for et, r in sorted(por_et.items()):
        d = sorted(r["diffs_min"])
        out[et] = {"total": r["total"], "cubiertas": r["cubiertas"],
                   "cobertura_pct": round(100 * r["cubiertas"] / r["total"], 1) if r["total"] else 0.0,
                   "mediana_min": d[len(d) // 2] if d else None}
    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    with open(argv[1], newline="", encoding="utf-8-sig") as f:
        ref = list(csv.DictReader(f))
    if len(argv) > 2:
        import os
        os.environ["FT_NEWS_DB_PATH"] = argv[2]
    from ft_news.db import get_conn
    conn = get_conn()
    live = [dict(r) for r in conn.execute("SELECT jugador, ocurrio_en, publicado_en FROM news_live WHERE estado='PUBLICADO'")]
    for et, r in comparar(ref, live).items():
        print(f"{et:14} {r['cubiertas']:>3}/{r['total']:<3} ({r['cobertura_pct']}%)  mediana de retraso (min): {r['mediana_min']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
