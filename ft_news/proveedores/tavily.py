"""
ft_news/proveedores/tavily.py — Búsqueda de noticias (Fase 1).

POST https://api.tavily.com/search con:
  topic=news, days=N, include_domains=<lista blanca autorizada>, max_results,
  search_depth=basic (1 crédito por consulta en el plan Researcher).
Devuelve artículos (url, título, contenido, fecha de publicación, dominio).

Reglas:
  - sin TAVILY_API_KEY → ErrorProveedor antes de llamar;
  - include_domains SIEMPRE: si la lista autorizada está vacía, NO se busca
    (fuentes sin autorizar no se leen);
  - 401/403 → clave inválida (no se reintenta); 429 → límite (pausa);
  - cada llamada se anota en costos (1 crédito ≈ US$ 0,008 fuera del plan).
"""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse

import httpx

URL = "https://api.tavily.com/search"
USD_POR_CREDITO = 0.008


class ErrorProveedor(Exception):
    def __init__(self, mensaje: str, pausa_seg: int = 300, fatal: bool = False):
        super().__init__(mensaje)
        self.pausa_seg, self.fatal = pausa_seg, fatal


def dominio_de(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


class Tavily:
    def __init__(self, api_key: Optional[str] = None, transport=None, timeout: float = 30):
        self.api_key = api_key if api_key is not None else os.getenv("TAVILY_API_KEY", "").strip()
        self._cli = httpx.Client(timeout=timeout, transport=transport)
        self.llamadas = 0

    def buscar(self, consulta: str, dominios: list[str], dias: int = 7, max_resultados: int = 6) -> dict:
        """{'articulos': [...], 'creditos': 1, 'usd': 0.008}"""
        if not self.api_key:
            raise ErrorProveedor("TAVILY_API_KEY sin configurar", fatal=True)
        if not dominios:
            raise ErrorProveedor("sin dominios autorizados: no se busca", fatal=True)
        cuerpo = {"query": consulta, "topic": "news", "days": dias, "search_depth": "basic",
                  "max_results": max_resultados, "include_domains": dominios[:300],
                  "include_answer": False, "include_raw_content": False}
        self.llamadas += 1
        r = self._cli.post(URL, json=cuerpo, headers={"Authorization": f"Bearer {self.api_key}"})
        if r.status_code in (401, 403):
            raise ErrorProveedor(f"Tavily rechazó la clave ({r.status_code})", pausa_seg=3600, fatal=True)
        if r.status_code == 429:
            raise ErrorProveedor("Tavily: límite alcanzado (429)", pausa_seg=900)
        if r.status_code == 432:
            raise ErrorProveedor("Tavily: plan sin créditos (432)", pausa_seg=3600, fatal=True)
        if r.status_code >= 500:
            raise ErrorProveedor(f"Tavily {r.status_code}", pausa_seg=300)
        r.raise_for_status()
        d = r.json()
        arts = []
        for x in d.get("results") or []:
            url = x.get("url") or ""
            if not url:
                continue
            arts.append({"url": url, "dominio": dominio_de(url), "titulo": (x.get("title") or "").strip(),
                         "contenido": (x.get("content") or "").strip(),
                         "fecha_publicacion": x.get("published_date") or None, "puntaje": x.get("score")})
        return {"articulos": arts, "creditos": 1, "usd": USD_POR_CREDITO, "tiempo_ms": d.get("response_time")}
