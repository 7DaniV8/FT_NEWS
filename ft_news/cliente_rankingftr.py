"""
ft_news/cliente_rankingftr.py — Lo ÚNICO externo que FT_NEWS lee en la
Fase 0: RankingFTR, por sus endpoints de solo lectura /ft-intel/*
(mismo secreto y mismas costumbres que FT Intelligence: pausa entre
llamadas, nunca reintentar un 401/403/429).

Endpoints que usa:
  GET /ft-intel/utr/padron           (nuevo en RankingFTR, Fase 0)
  GET /ft-intel/fixtures             (ya existía: próximos partidos con cuotas)
  GET /ft-intel/partidos             (ya existía: match_log, ret./w.o.)
  GET /ft-intel/news/calibracion     (nuevo: informe de calibración de bandas)
Con NEWS_ACTIVO=0 el worker no llama a ninguno.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

from ft_news import config


class ErrorFTR(Exception):
    pass


class Cliente:
    def __init__(self, base: Optional[str] = None, secreto: Optional[str] = None, pausa: Optional[float] = None,
                 transport=None):
        self.base = (base if base is not None else config.FTR_URL).rstrip("/")
        self.secreto = secreto if secreto is not None else config.FTR_SECRET
        self.pausa = config.FTR_PAUSA if pausa is None else pausa
        self._cli = httpx.Client(timeout=30, transport=transport)
        self.llamadas = 0

    def _get(self, ruta: str, params: Optional[dict] = None) -> dict:
        if not self.base or not self.secreto:
            raise ErrorFTR("FTR_SERVICE_URL / FTR_INTERNAL_SECRET sin configurar")
        self.llamadas += 1
        r = self._cli.get(self.base + ruta, params=params or {}, headers={"X-FTR-Internal-Secret": self.secreto})
        if self.pausa:
            time.sleep(self.pausa)
        if r.status_code in (401, 403):
            raise ErrorFTR(f"RankingFTR rechazó el secreto ({r.status_code})")
        if r.status_code == 429:
            raise ErrorFTR("RankingFTR limitó la lectura (429): se pausa, no se reintenta")
        if r.status_code >= 500:
            raise ErrorFTR(f"RankingFTR {r.status_code}")
        r.raise_for_status()
        return r.json()

    def utr_padron(self, desde_id: int = 0, limite: int = 2000) -> dict:
        return self._get("/ft-intel/utr/padron", {"desde_id": desde_id, "limite": limite})

    def fixtures(self, horas_adelante: int = 72) -> dict:
        return self._get("/ft-intel/fixtures", {"horas_atras": 0, "horas_adelante": horas_adelante, "limite": 1000})

    def partidos(self, desde_id: int = 0) -> dict:
        return self._get("/ft-intel/partidos", {"desde_id": desde_id, "limite": 5000})

    def calibracion(self) -> dict:
        return self._get("/ft-intel/news/calibracion")

    # ── Motor 3 / Motor 5 (segunda entrega) ───────────────────────────
    def historial(self, desde_fecha: str, hasta_fecha: Optional[str] = None) -> dict:
        p = {"desde_fecha": desde_fecha, "limite": 50000}
        if hasta_fecha:
            p["hasta_fecha"] = hasta_fecha
        return self._get("/ft-intel/news/historial", p)

    def antecedentes(self, player_id: int, torneo: str) -> dict:
        return self._get("/ft-intel/news/antecedentes", {"player_id": player_id, "torneo": torneo})

    def defensa(self) -> dict:
        return self._get("/ft-intel/news/defensa")
