"""Fixtures compartidas.

Los tests usan una base PostgreSQL real (docker compose localmente o el servicio
de GitHub Actions en CI). Si la base no está arriba, fallan: no se saltan.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sopvid.plataforma.api.main import create_app
from sopvid.plataforma.db import get_engine


@pytest.fixture(scope="session")
def engine() -> Engine:
    return get_engine()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
