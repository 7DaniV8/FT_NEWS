"""
ft_news/proveedores/claude.py — Claude (Haiku) como clasificador.

Hasta el 09/10/2026 era solo la "segunda lectura" de lo que aspira a 🔥.
Desde FT_NEWS v4 (Rubén: "¿y si usamos Anthropic?") puede ser EL
clasificador principal: NEWS_CLASIFICADOR = claude (o auto, cuando no hay
GEMINI_API_KEY o Gemini falla). Mismo contrato que Gemini.clasificar():
{'ok', 'datos', 'tokens_entrada', 'tokens_salida', 'usd', 'error'}; misma
validación de taxonomía; un 4xx nunca escapa como excepción suelta. Si el
modelo configurado da 404, prueba los alternativos de ALTERNATIVOS.
Messages API por httpx (sin SDK).
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
ALTERNATIVOS = ("claude-haiku-5-5", "claude-haiku-4-5", "claude-3-5-haiku-latest", "claude-sonnet-5-5")
URL = "https://api.anthropic.com/v1/messages"
USD_ENTRADA_1K, USD_SALIDA_1K = 0.001, 0.005
NOMBRE = "claude"


class Claude:
    def __init__(self, api_key: Optional[str] = None, modelo: Optional[str] = None, transport=None, timeout: float = 60):
        self.api_key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.modelo = modelo or MODELO
        self.modelo_configurado = self.modelo
        self._cli = httpx.Client(timeout=timeout, transport=transport)
        self.llamadas = 0
        self.nombre = NOMBRE
        self.aviso: Optional[str] = None

    def _post(self, cuerpo: dict):
        self.llamadas += 1
        return self._cli.post(URL, json=cuerpo, headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                                                         "content-type": "application/json"})

    def clasificar(self, jugador: dict, articulo: dict) -> dict:
        if not self.api_key:
            raise ErrorProveedor("ANTHROPIC_API_KEY sin configurar", fatal=True)
        texto = (f"JUGADOR: {jugador.get('nombre')} · país: {jugador.get('pais') or '?'} · circuito: {jugador.get('circuito') or '?'}\n"
                 f"ARTÍCULO\nfuente: {articulo.get('dominio')}\nurl: {articulo.get('url')}\npublicado: {articulo.get('fecha_publicacion') or '?'}\n"
                 f"título: {articulo.get('titulo')}\ntexto: {(articulo.get('contenido') or '')[:4000]}\n\n"
                 "Campos del JSON: sobre_jugador (bool), confianza_identidad (0..1), categoria (" + ", ".join(tx.CATEGORIAS) +
                 "), direccion (NEGATIVA|POSITIVA|NEUTRA|MIXTA), naturaleza (HECHO|DECLARACION|NO_VERIFICADA|INTERPRETACION), "
                 "fecha_evento (AAAA-MM-DD o null), resumen_es, titular (≤ 60 caracteres, el hecho sin el nombre del jugador), "
                 "relevancia_deportiva, fragmento_original, idioma.")
        cuerpo = {"model": self.modelo, "max_tokens": 800, "temperature": 0, "system": INSTRUCCION,
                  "messages": [{"role": "user", "content": texto}]}
        r = self._post(cuerpo)
        if r.status_code == 404 or (r.status_code == 400 and "model" in r.text.lower() and "not" in r.text.lower()):
            # Modelo no disponible para esta clave: se prueban los alternativos una vez.
            probados = [self.modelo]
            for alt in ALTERNATIVOS:
                if alt in probados:
                    continue
                probados.append(alt)
                r = self._post({**cuerpo, "model": alt})
                if r.status_code < 400:
                    self.aviso = f"modelo '{self.modelo}' no disponible: se usa '{alt}'"
                    self.modelo = alt
                    break
            else:
                raise ErrorProveedor(f"Claude: ningún modelo disponible para esta clave ({', '.join(probados)}); "
                                     f"revisar ANTHROPIC_API_KEY o CLAUDE_MODELO", pausa_seg=3600, fatal=True)
        if r.status_code in (401, 403):
            raise ErrorProveedor(f"Claude rechazó la clave ({r.status_code})", pausa_seg=3600, fatal=True)
        if r.status_code == 429:
            raise ErrorProveedor("Claude: límite alcanzado (429)", pausa_seg=600)
        if r.status_code >= 500:
            raise ErrorProveedor(f"Claude {r.status_code}", pausa_seg=300)
        if r.status_code >= 400:
            raise ErrorProveedor(f"Claude HTTP {r.status_code}: {r.text[:160]}", pausa_seg=900)
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
        errores = tx.validar_evento(datos.get("categoria", "OTRA"), datos.get("direccion", ""),
                                    datos.get("naturaleza", ""), "C")
        errores = [x for x in errores if "nivel" not in x]
        if errores:
            salida["error"] = "; ".join(errores)
            return salida
        try:
            datos["confianza_identidad"] = max(0.0, min(1.0, float(datos.get("confianza_identidad") or 0)))
        except (TypeError, ValueError):
            datos["confianza_identidad"] = 0.0
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
