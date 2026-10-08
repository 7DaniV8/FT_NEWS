"""
ft_news/proveedores/gemini.py — Clasificación y resumen de UN artículo
para UN jugador (Fase 1). Gemini 2.5 Flash, salida JSON con esquema
estricto: el modelo CLASIFICA y RESUME; no decide nada deportivo ni da
números. Si devuelve algo fuera del esquema, el artículo queda sin evento
(nunca se "arregla" a mano).

Lo que se le pide (en español, con el fragmento original en su idioma):
  sobre_jugador (bool) + confianza_identidad (0..1): ¿habla de ESTE jugador?
  categoria (de la taxonomía o OTRA), direccion, naturaleza,
  fecha_evento (ISO, o null si el artículo no la deja inferir),
  resumen_es (≤ 280 caracteres), relevancia_deportiva (≤ 160, texto),
  fragmento_original (≤ 300, literal del artículo), idioma (ISO 639-1).
"""
from __future__ import annotations

import json
import os
from typing import Optional

import httpx

from ft_news import taxonomia as tx
from ft_news.proveedores.tavily import ErrorProveedor

MODELO = os.getenv("GEMINI_MODELO", "gemini-2.5-flash")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
# Precios de lista (US$ por 1k tokens) para la estimación.
USD_ENTRADA_1K, USD_SALIDA_1K = 0.0003, 0.0025

ESQUEMA = {
    "type": "OBJECT",
    "properties": {
        "sobre_jugador": {"type": "BOOLEAN"},
        "confianza_identidad": {"type": "NUMBER"},
        "categoria": {"type": "STRING", "enum": list(tx.CATEGORIAS.keys())},
        "direccion": {"type": "STRING", "enum": list(tx.DIRECCIONES)},
        "naturaleza": {"type": "STRING", "enum": list(tx.NATURALEZAS)},
        "fecha_evento": {"type": "STRING", "nullable": True},
        "resumen_es": {"type": "STRING"},
        "relevancia_deportiva": {"type": "STRING"},
        "fragmento_original": {"type": "STRING"},
        "idioma": {"type": "STRING"},
    },
    "required": ["sobre_jugador", "confianza_identidad", "categoria", "direccion", "naturaleza",
                 "resumen_es", "relevancia_deportiva", "fragmento_original", "idioma"],
}

INSTRUCCION = """Eres un clasificador de noticias de tenis para un sistema que NO apuesta ni calcula probabilidades.
Tu única tarea: decidir si el artículo habla del jugador indicado y, si es así, clasificar QUÉ pasó.
Reglas:
- "sobre_jugador": true solo si el artículo trata de ESE jugador (nombre completo y contexto coherentes: país, circuito). Homónimos → false. "confianza_identidad" entre 0 y 1.
- "categoria": una de la lista. Si no encaja ninguna, OTRA. No inventes lesiones: solo si el texto lo dice.
- "direccion": NEGATIVA si perjudica al jugador en lo deportivo inmediato (lesión, enfermedad, abandono, cansancio, sanción); POSITIVA si lo favorece (buena preparación, regreso confirmado al 100 %, antecedentes buenos, localía); MIXTA si hay de las dos o no está claro (un regreso tras lesión es MIXTA); NEUTRA si no afecta.
- "naturaleza": HECHO (ocurrió y la fuente lo afirma: abandono, baja, resultado), DECLARACION (lo dice el jugador o su equipo, citado), NO_VERIFICADA (rumor, "podría", fuentes no identificadas), INTERPRETACION (opinión del periodista).
- "fecha_evento": fecha en que OCURRIÓ lo narrado (no la de publicación), formato AAAA-MM-DD; null si el texto no permite inferirla. Si el artículo habla de algo de hace meses o años, pon esa fecha antigua, nunca la actual.
- "resumen_es": en español, ≤ 280 caracteres, sin opinar, sin números de probabilidad.
- "relevancia_deportiva": ≤ 160 caracteres, texto, p. ej. "podría afectar el saque" o "sin efecto esperado". Nunca un número.
- "fragmento_original": copia literal (≤ 300 caracteres) de la parte del artículo que sostiene la clasificación, en su idioma original.
Responde SOLO con el JSON del esquema."""


class Gemini:
    def __init__(self, api_key: Optional[str] = None, modelo: Optional[str] = None, transport=None, timeout: float = 60):
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "").strip()
        self.modelo = modelo or MODELO
        self._cli = httpx.Client(timeout=timeout, transport=transport)
        self.llamadas = 0

    def clasificar(self, jugador: dict, articulo: dict) -> dict:
        """Devuelve {'ok': bool, 'datos': {...}|None, 'tokens_entrada', 'tokens_salida', 'usd', 'error'}."""
        if not self.api_key:
            raise ErrorProveedor("GEMINI_API_KEY sin configurar", fatal=True)
        texto = (f"JUGADOR: {jugador.get('nombre')} · país: {jugador.get('pais') or '?'} · "
                 f"circuito: {jugador.get('circuito') or '?'} · género: {jugador.get('genero') or '?'}\n"
                 f"ARTÍCULO\nfuente: {articulo.get('dominio')}\nurl: {articulo.get('url')}\n"
                 f"publicado: {articulo.get('fecha_publicacion') or '?'}\ntítulo: {articulo.get('titulo')}\n"
                 f"texto: {(articulo.get('contenido') or '')[:4000]}")
        cuerpo = {
            "systemInstruction": {"parts": [{"text": INSTRUCCION}]},
            "contents": [{"role": "user", "parts": [{"text": texto}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": ESQUEMA,
                                 "temperature": 0.1, "maxOutputTokens": 1024},
        }
        self.llamadas += 1
        r = self._cli.post(URL.format(modelo=self.modelo), params={"key": self.api_key}, json=cuerpo)
        if r.status_code in (401, 403):
            raise ErrorProveedor(f"Gemini rechazó la clave ({r.status_code})", pausa_seg=3600, fatal=True)
        if r.status_code == 429:
            raise ErrorProveedor("Gemini: límite alcanzado (429)", pausa_seg=600)
        if r.status_code >= 500:
            raise ErrorProveedor(f"Gemini {r.status_code}", pausa_seg=300)
        r.raise_for_status()
        d = r.json()
        uso = d.get("usageMetadata") or {}
        te, ts = int(uso.get("promptTokenCount") or 0), int(uso.get("candidatesTokenCount") or 0)
        usd = te / 1000 * USD_ENTRADA_1K + ts / 1000 * USD_SALIDA_1K
        salida = {"ok": False, "datos": None, "tokens_entrada": te, "tokens_salida": ts, "usd": round(usd, 6),
                  "error": None}
        try:
            partes = d["candidates"][0]["content"]["parts"]
            crudo = "".join(p.get("text", "") for p in partes)
            datos = json.loads(crudo)
        except (KeyError, IndexError, TypeError, ValueError) as e:
            salida["error"] = f"respuesta fuera de esquema: {e}"
            return salida
        errores = tx.validar_evento(datos.get("categoria", "OTRA"), datos.get("direccion", ""),
                                    datos.get("naturaleza", ""), "C")
        errores = [x for x in errores if "nivel" not in x]
        if errores:
            salida["error"] = "; ".join(errores)
            return salida
        datos["confianza_identidad"] = max(0.0, min(1.0, float(datos.get("confianza_identidad") or 0)))
        salida.update(ok=True, datos=datos)
        return salida
