"""Engine, sesión y Base declarativa de SQLAlchemy.

El engine se crea de forma perezosa: importar este módulo no abre conexiones.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from sopvid.plataforma.config import get_settings


class Base(DeclarativeBase):
    """Base de los modelos ORM; Alembic usa `Base.metadata` para autogenerar."""


@lru_cache
def get_engine() -> Engine:
    # Sin connect_timeout, libpq espera indefinidamente si el puerto no responde (en Windows,
    # con Docker detenido, la conexión no se rechaza: se queda colgada).
    return create_engine(
        get_settings().sqlalchemy_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por petición."""
    with get_sessionmaker()() as session:
        yield session


def ping(session: Session) -> None:
    """Lanza `SQLAlchemyError` si la base no responde."""
    session.execute(text("SELECT 1"))
