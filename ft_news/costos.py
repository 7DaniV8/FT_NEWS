"""
ft_news/costos.py — Contador de costos por día y proveedor, y los topes
(diseño §8/§10). Cualquier llamada externa futura debe pasar por
`puede_gastar()` antes y `anotar()` después.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ft_news.db import ahora_iso, ejecutar_con_reintento

# Precios de lista (octubre 2026) para la ESTIMACIÓN; no son facturas.
PRECIOS = {
    "tavily": {"busqueda_usd": 0.008},
    "exa": {"busqueda_usd": 0.005},
    "gemini-flash": {"usd_por_1k_entrada": 0.0003, "usd_por_1k_salida": 0.0025},
    "claude-haiku": {"usd_por_1k_entrada": 0.001, "usd_por_1k_salida": 0.005},
}


def _dia() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def anotar(conn, proveedor: str, busquedas: int = 0, articulos: int = 0, tokens_entrada: int = 0,
           tokens_salida: int = 0, usd: float = 0.0) -> None:
    def _w():
        conn.execute(
            "INSERT INTO news_costos_dia (dia, proveedor, busquedas, articulos, tokens_entrada, tokens_salida, "
            "usd_estimado, actualizado_en) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(dia, proveedor) DO UPDATE SET "
            "busquedas=busquedas+excluded.busquedas, articulos=articulos+excluded.articulos, "
            "tokens_entrada=tokens_entrada+excluded.tokens_entrada, tokens_salida=tokens_salida+excluded.tokens_salida, "
            "usd_estimado=usd_estimado+excluded.usd_estimado, actualizado_en=excluded.actualizado_en",
            (_dia(), proveedor, busquedas, articulos, tokens_entrada, tokens_salida, usd, ahora_iso()))
        conn.commit()
    ejecutar_con_reintento(_w, conn=conn)


def hoy(conn) -> dict:
    filas = [dict(r) for r in conn.execute("SELECT * FROM news_costos_dia WHERE dia=?", (_dia(),)).fetchall()]
    return {"dia": _dia(), "proveedores": filas,
            "busquedas": sum(f["busquedas"] for f in filas),
            "tokens": sum(f["tokens_entrada"] + f["tokens_salida"] for f in filas),
            "usd": round(sum(f["usd_estimado"] for f in filas), 4)}


def mes(conn) -> dict:
    pref = _dia()[:7]
    r = conn.execute("SELECT COALESCE(SUM(usd_estimado),0) u, COALESCE(SUM(busquedas),0) b FROM news_costos_dia "
                     "WHERE dia LIKE ?", (pref + "%",)).fetchone()
    return {"mes": pref, "usd": round(r["u"], 4), "busquedas": r["b"]}


def puede_gastar(conn, cfg: dict) -> dict:
    """{'ok': bool, 'motivo': str, 'aviso_80': bool}."""
    h, m = hoy(conn), mes(conn)
    tope_usd = float(cfg.get("NEWS_MAX_USD_MES", 100))
    if h["busquedas"] >= int(cfg.get("NEWS_MAX_BUSQUEDAS_DIA", 300)):
        return {"ok": False, "motivo": "TOPE_BUSQUEDAS_DIA", "aviso_80": True}
    if h["tokens"] >= int(cfg.get("NEWS_MAX_TOKENS_DIA", 2_000_000)):
        return {"ok": False, "motivo": "TOPE_TOKENS_DIA", "aviso_80": True}
    if m["usd"] >= tope_usd:
        return {"ok": False, "motivo": "TOPE_USD_MES", "aviso_80": True}
    return {"ok": True, "motivo": "", "aviso_80": m["usd"] >= 0.8 * tope_usd}
