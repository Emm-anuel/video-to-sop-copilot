"""Fixtures compartidas.

Los tests usan una base PostgreSQL real (docker compose localmente o el servicio
de GitHub Actions en CI). Si la base no está arriba, fallan: no se saltan.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from sopvid.plataforma.api.main import create_app
from sopvid.plataforma.db import get_engine


@pytest.fixture(scope="session")
def engine() -> Engine:
    return get_engine()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """Sesión dentro de una transacción que se revierte al final: no deja filas en la base.

    `commit()` y `rollback()` del test actúan sobre un savepoint, así que una IntegrityError
    no invalida la transacción externa.
    """
    with engine.connect() as conn:
        transaccion = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaccion.rollback()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
