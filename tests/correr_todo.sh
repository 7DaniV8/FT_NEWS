#!/usr/bin/env bash
# Corre todas las pruebas de FT_NEWS. Ninguna usa la red ni una base real.
# v5.1: si al lado de este repo hay copias de FT_INTELLIGENCE y FT_DISCORD (o se
# definen FT_INTELLIGENCE_REPO / FT_DISCORD_REPO), también corre el recorrido
# completo FT NEWS → FT Intelligence → FT Discord (tests/test_recorrido_discord.py).
set -u
cd "$(dirname "$0")/.."
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x /opt/venv/bin/python ]; then PY=/opt/venv/bin/python; else PY=python3; fi
fi
for d in ../FT_INTELLIGENCE ../FT_INTELLIGENCE-main; do
  [ -z "${FT_INTELLIGENCE_REPO:-}" ] && [ -d "$d/ft_intelligence" ] && export FT_INTELLIGENCE_REPO="$(cd "$d" && pwd)"
done
for d in ../FT_DISCORD ../FT_DISCORD-main; do
  [ -z "${FT_DISCORD_REPO:-}" ] && [ -d "$d/ft_discord" ] && export FT_DISCORD_REPO="$(cd "$d" && pwd)"
done
"$PY" -m pytest -q tests
