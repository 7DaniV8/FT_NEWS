import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

os.environ["FT_NEWS_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "ft_news.db")
os.environ["FT_NEWS_SECRET"] = "secreto-pruebas"
os.environ["FT_NEWS_SIN_WORKER"] = "1"
os.environ.pop("NEWS_ACTIVO", None)

from ft_news import config  # noqa: E402
from ft_news.db import get_conn  # noqa: E402


@pytest.fixture
def conn():
    p = Path(tempfile.mkdtemp()) / "t.db"
    c = get_conn(p)
    yield c
    c.close()


@pytest.fixture
def cfg():
    c = config.leer_config()
    assert c["NEWS_BANDAS_CALIBRADAS"] == 0
    c["NEWS_ACTIVO"] = 0                      # las pruebas encienden explícitamente
    c["NEWS_DISCORD_ACTIVO"] = 0
    return c


@pytest.fixture
def cfg_calibrado(cfg):
    c = dict(cfg)
    c["NEWS_BANDAS_CALIBRADAS"] = 1
    return c
