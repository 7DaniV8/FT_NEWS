#!/usr/bin/env python3
"""
herramientas/calibrar_bandas.py — Informe de calibración de bandas UTR/cuota
con DATOS PROPIOS (utr_value_registro de RankingFTR). Fase 0.

Dos formas de correrlo:

  a) Contra RankingFTR en Railway (lo normal):
       FTR_SERVICE_URL=https://... FTR_INTERNAL_SECRET=... \\
       python herramientas/calibrar_bandas.py --salida INFORME-CALIBRACION.md

  b) Contra un archivo .db (copia/backup de la base de producción):
       python herramientas/calibrar_bandas.py --db /ruta/ftr.db --salida INFORME-CALIBRACION.md
     (necesita RANKINGFTR_REPO apuntando a la copia del repo para importar
      production/engines/news_calibracion.py)

Nunca escribe en ninguna base. El veredicto CALIBRADAS_OK es la condición
para poner NEWS_BANDAS_CALIBRADAS=1 — y aun así lo decide Rubén, no el script.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys


def _markdown_desde_json(inf: dict) -> str:
    repo = os.getenv("RANKINGFTR_REPO")
    if repo:
        sys.path.insert(0, repo)
        try:
            from production.engines import news_calibracion as nc
            return nc.informe_markdown(inf)
        except Exception:
            pass
    # Sin el repo a mano: un markdown mínimo con lo esencial.
    L = [f"# Calibración de bandas — {inf.get('veredicto')}", "", f"Muestra: {inf.get('muestra')} partidos", ""]
    L += [f"- {r}" for r in inf.get("razones", [])]
    L += ["", "```json", json.dumps(inf, ensure_ascii=False, indent=2), "```"]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="archivo .db de RankingFTR (en vez de pedirlo por HTTP)")
    ap.add_argument("--desde", help="solo partidos vistos desde esta fecha ISO")
    ap.add_argument("--salida", default="INFORME-CALIBRACION.md")
    ap.add_argument("--json", help="guardar también el JSON crudo acá")
    a = ap.parse_args()

    if a.db:
        repo = os.getenv("RANKINGFTR_REPO")
        if not repo:
            print("Con --db hace falta RANKINGFTR_REPO=/ruta/al/repo/RankingFTR", file=sys.stderr)
            return 2
        sys.path.insert(0, repo)
        from production.engines import news_calibracion as nc
        uri = f"file:{os.path.abspath(a.db)}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            inf = nc.informe(conn, a.desde)
        finally:
            conn.close()
        md = nc.informe_markdown(inf)
    else:
        from ft_news.cliente_rankingftr import Cliente
        cli = Cliente(pausa=0)
        inf = cli._get("/ft-intel/news/calibracion", {"desde": a.desde} if a.desde else {})
        md = _markdown_desde_json(inf)

    with open(a.salida, "w", encoding="utf-8") as f:
        f.write(md)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(inf, f, ensure_ascii=False, indent=2)
    print(f"{inf['veredicto']} · muestra {inf['muestra']} · informe en {a.salida}")
    for r in inf.get("razones", []):
        print(" -", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
