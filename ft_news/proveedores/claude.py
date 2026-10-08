"""
ft_news/proveedores/claude.py — Segunda lectura (Claude Haiku) de lo que
aspira a 🔥 (segunda entrega). Mismo esquema JSON que Gemini; si la segunda
lectura discrepa en categoría, dirección o fecha del evento, el evento baja
a nivel C (no puede dar 🔥). Opcional: sin ANTHROPIC_API_KEY no se usa y
queda anotado. Messages API por httpx (sin SDK).
"""
from __future__ import annotations

import json
import os
from typing import Optional

import httpx

from ft_news import taxonomia as tx
from ft_news.proveedores.gemini import INSTRUCCION
from ft_news.proveedores.tavily import ErrorProveedor

MODELO = os.getenv("CLAUDE_MODELO", "claude-haiku-5-5")
URL = "https://api.anthropic.com/v1/messages"
USD_ENTRADA_1K, USD_SALIDA_1K = 0.001, 0.005


class Claude:
    def __init__(self, api_key: Optional[str] = None, modelo: Optional[str] = None, transport=None, timeout: float = 60):
        self.api_key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.modelo = modelo or MODELO
        self._cli = httpx.Client(timeout=timeout, transport=transport)
        self.llamadas = 0

    def clasificar(self, jugador: dict, articulo: dict) -> dict:
        if not self.api_key:
            raise ErrorProveedor("ANTHROPIC_API_KEY sin configurar", fatal=True)
        texto = (f"JUGADOR: {jugador.get('nombre')} · país: {jugador.get('pais') or '?'} · circuito: {jugador.get('circuito') or '?'}\n"
                 f"ARTÍCULO\nfuente: {articulo.get('dominio')}\nurl: {articulo.get('url')}\npublicado: {articulo.get('fecha_publicacion') or '?'}\n"
                 f"título: {articulo.get('titulo')}\ntexto: {(articulo.get('contenido') or '')[:4000]}\n\n"
                 "Campos del JSON: sobre_jugador (bool), confianza_identidad (0..1), categoria (" + ", ".join(tx.CATEGORIAS) +
                 "), direccion (NEGATIVA|POSITIVA|NEUTRA|MIXTA), naturaleza (HECHO|DECLARACION|NO_VERIFICADA|INTERPRETACION), "
                 "fecha_evento (AAAA-MM-DD o null), resumen_es, relevancia_deportiva, fragmento_original, idioma.")
        cuerpo = {"model": self.modelo, "max_tokens": 800, "temperature": 0, "system": INSTRUCCION,
                  "messages": [{"role": "user", "content": texto}]}
        self.llamadas += 1
        r = self._cli.post(URL, json=cuerpo, headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                                                      "content-type": "application/json"})
        if r.status_code in (401, 403):
            raise ErrorProveedor(f"Claude rechazó la clave ({r.status_code})", pausa_seg=3600, fatal=True)
        if r.status_code == 429:
            raise ErrorProveedor("Claude: límite alcanzado (429)", pausa_seg=600)
        if r.status_code >= 500:
            raise ErrorProveedor(f"Claude {r.status_code}", pausa_seg=300)
        r.raise_for_status()
        d = r.json()
        uso = d.get("usage") or {}
        te, ts = int(uso.get("input_tokens") or 0), int(uso.get("output_tokens") or 0)
        salida = {"ok": False, "datos": None, "tokens_entrada": te, "tokens_salida": ts,
                  "usd": round(te / 1000 * USD_ENTRADA_1K + ts / 1000 * USD_SALIDA_1K, 6), "error": None}
        try:
            crudo = "".join(b.get("text", "") for b in d.get("content") or [] if b.get("type") == "text")
            ini, fin = crudo.find("{"), crudo.rfind("}")
            datos = json.loads(crudo[ini:fin + 1])
        except (ValueError, TypeError) as e:
            salida["error"] = f"respuesta fuera de esquema: {e}"
            return salida
        salida.update(ok=True, datos=datos)
        return salida


def discrepa(l1: dict, l2: dict) -> bool:
    """Segunda lectura ≠ primera en lo que importa: categoría, dirección o fecha (día)."""
    if not l2.get("sobre_jugador"):
        return True
    if l1.get("categoria") != l2.get("categoria") or l1.get("direccion") != l2.get("direccion"):
        return True
    f1, f2 = (l1.get("fecha_evento") or "")[:10], (l2.get("fecha_evento") or "")[:10]
    return bool(f1 and f2 and f1 != f2)
