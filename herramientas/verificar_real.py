#!/usr/bin/env python3
"""
herramientas/verificar_real.py — Comprobación en PRODUCCIÓN (Railway) de que los
tres servicios están funcionando con noticias y cuotas reales, antes/después de
encender Discord. Solo lee (GET). Correr desde cualquier máquina con red:

    FT_NEWS_URL=https://<ft-news> FT_NEWS_SECRET=... \\
    FTR_SERVICE_URL=https://<rankingftr> FTR_INTERNAL_SECRET=... \\
    FT_INTEL_URL=https://<ft-intelligence> \\
    python herramientas/verificar_real.py

Imprime ✅ / ⚠️ / ❌ por punto y un veredicto final: LISTO PARA ENCENDER (o qué
falta). No cambia nada: encender es Admin → FT NEWS → "Señales a Discord".
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

OK, WARN, BAD = "✅", "⚠️", "❌"
problemas: list[str] = []


def _dt(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def linea(icono, texto):
    print(f"  {icono} {texto}")
    if icono == BAD:
        problemas.append(texto)


def get(url, ruta, headers):
    try:
        r = httpx.get(url.rstrip("/") + ruta, headers=headers, timeout=30)
    except Exception as e:
        linea(BAD, f"{ruta}: sin respuesta ({e})")
        return None
    if r.status_code != 200:
        linea(BAD, f"{ruta}: HTTP {r.status_code} {r.text[:120]}")
        return None
    return r.json()


def main() -> int:
    ahora = datetime.now(timezone.utc)
    news_url, news_sec = os.getenv("FT_NEWS_URL", ""), os.getenv("FT_NEWS_SECRET", "")
    ftr_url, ftr_sec = os.getenv("FTR_SERVICE_URL", ""), os.getenv("FTR_INTERNAL_SECRET", "")
    intel_url = os.getenv("FT_INTEL_URL", "")
    if not (news_url and news_sec and ftr_url and ftr_sec and intel_url):
        print("Faltan variables: FT_NEWS_URL, FT_NEWS_SECRET, FTR_SERVICE_URL, FTR_INTERNAL_SECRET, FT_INTEL_URL")
        return 2
    hn, hf = {"X-FT-News-Secret": news_sec}, {"X-FTR-Internal-Secret": ftr_sec}

    print("\n1 · RankingFTR (padrón UTR y cuotas)")
    fx = get(ftr_url, "/ft-intel/fixtures?horas_adelante=72&limite=1000", hf) or {}
    filas = fx.get("fixtures") or []
    con_cuota = [f for f in filas if f.get("odd1") and f.get("odd2")]
    frescas = [f for f in con_cuota if _dt(f.get("actualizado_en")) and _dt(f["actualizado_en"]) > ahora - timedelta(hours=2)]
    linea(OK if filas else BAD, f"fixtures ≤ 72 h: {len(filas)} · con cuota: {len(con_cuota)} · cuota actualizada en las últimas 2 h: {len(frescas)}")
    if con_cuota and not frescas:
        linea(WARN, "ninguna cuota se actualizó en 2 h: las 🔥 quedarán 'pendiente de confirmar la reacción del mercado' hasta que el bot refresque")
    circ = {}
    for f in filas:
        t = (f.get("torneo") or "").lower()
        c = "challenger" if "challenger" in t else "itf" if any(k in t for k in ("m15", "m25", "w15", "w35", "w50", "w75", "w100", "itf")) else "utr" if "utr" in t else "atp/wta"
        circ[c] = circ.get(c, 0) + 1
    linea(OK, f"por circuito: {circ}")
    pad = get(ftr_url, "/ft-intel/utr/padron?limite=1", hf) or {}
    linea(OK if pad.get("jugadores") is not None else BAD, f"padrón UTR responde ({'sí' if pad.get('jugadores') is not None else 'no'})")

    print("\n2 · FT NEWS")
    sal = get(news_url, "/salud", {}) or {}
    linea(OK if str(sal.get("version", "")).startswith("ft-news-v6") else WARN, f"versión {sal.get('version')} (se espera ft-news-v6-…)")
    est = get(news_url, "/news/estado", hn) or {}
    e = est.get("estado") or {}
    linea(OK if est.get("activo") else BAD, f"motor {'encendido' if est.get('activo') else 'APAGADO'} · Discord {'ENCENDIDO' if est.get('discord_activo') else 'apagado'}")
    for paso in ("padron", "partidos", "radar", "reintentos", "descubridor", "alertas_vencidas", "cierre"):
        v = (e.get(f"paso_{paso}") or {}).get("valor") or "nunca corrió"
        linea(OK if str(v).startswith("OK") else (WARN if v == "nunca corrió" else BAD), f"paso {paso}: {str(v)[:110]}")
    linea(OK if (e.get("clasificador") or {}).get("valor") else BAD, f"clasificador: {(e.get('clasificador') or {}).get('valor')}")
    ult = _dt((e.get("ultimo_ciclo_en") or {}).get("valor"))
    linea(OK if ult and ult > ahora - timedelta(minutes=30) else BAD, f"último ciclo: {ult.isoformat()[:16] if ult else 'nunca'} UTC")
    d = get(news_url, "/news/diagnostico?dias=2", hn) or {}
    hoy = d.get("hoy") or {}
    linea(OK if hoy.get("externos") else WARN, f"noticias externas hoy: {hoy.get('externos', 0)} · eventos calculados: {hoy.get('internos', 0)}")
    busq = sum(b.get("n", 0) for b in d.get("busquedas") or [])
    sinres = sum(b.get("sin_resultados", 0) for b in d.get("busquedas") or [])
    linea(OK if busq else BAD, f"búsquedas (2 días): {busq} · sin resultado: {sinres}")
    arts = {a["resultado"]: a["n"] for a in d.get("articulos") or []}
    linea(OK if arts.get("EVENTO") else WARN, f"artículos por resultado: {arts}")
    rei = {r["resultado"]: r["n"] for r in d.get("reintentos") or []}
    linea(WARN if rei.get("AGOTADO") else OK, f"clasificación pendiente/reintentos: {rei or 'ninguno'}")
    cob = (d.get("cobertura") or {}).get("circuitos") or []
    for c in cob:
        ic = OK if c.get("investigados") else (WARN if c.get("en_cola") else OK)
        linea(ic, f"cobertura {c['circuito']}: en cola {c['en_cola']} · investigados {c['investigados']} · nunca {c['nunca_buscados']} · "
                  f"noticias útiles {c['noticias_utiles']} · partidos {c['partidos_analizados']} · alertas {c['alertas']}")
    pr = (d.get("cobertura") or {}).get("presupuesto") or {}
    linea(OK if pr.get("alcanza", True) else WARN, f"presupuesto: necesita {pr.get('necesario_dia')}/día · tope {pr.get('tope_actual')} · "
                                                  f"{'alcanza' if pr.get('alcanza') else 'NO alcanza → proponer ' + str(pr.get('tope_propuesto'))} · "
                                                  f"menores {pr.get('menores_pct_necesario')} % (cupo {pr.get('cupo_menores_actual')} → sugerido {pr.get('cupo_menores_sugerido')})")
    al = get(news_url, "/news/alertas?limite=200", hn) or {}
    res = al.get("resumen") or {}
    linea(OK, f"alertas pendientes {res.get('pendientes')} · dichas hoy {res.get('dichas_hoy')} · omitidas hoy {res.get('omitidas_hoy')}")
    for a in (al.get("alertas") or [])[:6]:
        t = (a.get("texto_discord") or "").split("\n")
        linea(OK if "http" not in (a.get("texto_discord") or "") else BAD, f"{a['tipo']} · {t[0] if t else ''} · {t[1] if len(t) > 1 else ''}"
              + (" · CONTIENE ENLACE" if "http" in (a.get("texto_discord") or "") else ""))
    costos = est.get("costos_hoy") or {}
    linea(OK, f"gasto hoy US$ {costos.get('usd')} · búsquedas {costos.get('busquedas')} · mes US$ {(est.get('costos_mes') or {}).get('usd')}")

    print("\n3 · FT Intelligence → FT Discord")
    si = get(intel_url, "/salud", {}) or {}
    linea(OK if si else BAD, f"FT Intelligence /salud: {str(si)[:100]}")
    sen = get(intel_url, "/senales?desde_id=0&limite=100", hf) or {}
    news = [s for s in (sen.get("senales") or []) if str(s.get("tipo", "")).startswith("NEWS_")]
    tipos = {}
    for s in news:
        tipos[s["tipo"]] = tipos.get(s["tipo"], 0) + 1
    linea(OK if news or not est.get("discord_activo") else WARN, f"señales NEWS_* en FT Intelligence: {tipos or 'ninguna todavía'}")
    claves = [s.get("clave") for s in news]
    linea(OK if len(claves) == len(set(claves)) else BAD, f"claves únicas: {len(set(claves))}/{len(claves)}")
    cfg = get(intel_url, "/discord-config", hf) or {}
    t = cfg.get("tipos") or {}
    for tipo in ("NEWS_VALOR", "NEWS_INTERESANTE", "NEWS_NOTICIA"):
        v = t.get(tipo) or {}
        linea(OK if v.get("texto") else WARN, f"Admin → Discord {tipo}: texto {v.get('texto')} · voz {v.get('voz')}"
              + (f" · encabezado personalizado: {v.get('encabezado')}" if v.get("encabezado") else ""))

    print("\n" + ("LISTO PARA ENCENDER" if not problemas else f"FALTA: {len(problemas)} punto(s) ❌") +
          (" (Discord ya encendido)" if est.get("discord_activo") else ""))
    for p in problemas:
        print(f"  - {p}")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
