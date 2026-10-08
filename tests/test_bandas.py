from ft_news import bandas as bd


def test_banda_utr_cortes_default():
    assert bd.banda_utr(0.0) == "PAREJO"
    assert bd.banda_utr(0.29) == "PAREJO"
    assert bd.banda_utr(0.30) == "FAVORITO"
    assert bd.banda_utr(-0.5) == "NO_FAVORITO"
    assert bd.banda_utr(0.8) == "MUY_FAVORITO"
    assert bd.banda_utr(-1.2) == "MUY_NO_FAVORITO"
    assert bd.banda_utr(1.5) == "ABISMO"
    assert bd.banda_utr(-2.0) == "ABISMO_CONTRA"
    assert bd.banda_utr(None) is None


def test_banda_mercado_cortes_default():
    assert bd.banda_mercado(1.20) == "MUY_FAVORITO"
    assert bd.banda_mercado(1.35) == "MUY_FAVORITO"
    assert bd.banda_mercado(1.60) == "FAVORITO"
    assert bd.banda_mercado(1.85) == "PAREJO"
    assert bd.banda_mercado(2.50) == "NO_FAVORITO"
    assert bd.banda_mercado(3.00) == "NO_FAVORITO"
    assert bd.banda_mercado(4.00) == "MUY_NO_FAVORITO"
    assert bd.banda_mercado(None) is None
    assert bd.banda_mercado(1.0) is None


def test_cortes_configurables():
    assert bd.banda_utr(0.5, cortes=(0.6, 1.0, 2.0)) == "PAREJO"
    assert bd.banda_mercado(1.5, cortes=(1.5, 1.9, 2.5, 4.0)) == "MUY_FAVORITO"


def test_desvio():
    assert bd.desvio("FAVORITO", "FAVORITO")["tipo"] == "ALINEADO"
    d = bd.desvio("FAVORITO", "MUY_FAVORITO")
    assert d["tipo"] == "MERCADO_MAS_OPTIMISTA" and d["pasos"] == 1
    d = bd.desvio("FAVORITO", "PAREJO")
    assert d["tipo"] == "MERCADO_MAS_PESIMISTA" and d["pasos"] == -1
    # ABISMO se compara como MUY_
    assert bd.desvio("ABISMO", "MUY_FAVORITO")["tipo"] == "ALINEADO"
    assert bd.desvio("ABISMO_CONTRA", "NO_FAVORITO")["tipo"] == "MERCADO_MAS_OPTIMISTA"
    assert bd.desvio(None, "PAREJO") is None


def test_sin_probabilidades_en_el_modulo():
    import inspect
    src = inspect.getsource(bd)
    assert "prob" not in src.lower().replace("probabilidad. son", "")  # solo la frase del docstring
