#!/usr/bin/env bash
# Corre todas las pruebas de FT_NEWS. Ninguna usa la red ni una base real.
set -u
cd "$(dirname "$0")/.."
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x /opt/venv/bin/python ]; then PY=/opt/venv/bin/python; else PY=python3; fi
fi
"$PY" -m pytest -q tests
