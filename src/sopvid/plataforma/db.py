"""Engine, sesión y Base declarativa de SQLAlchemy.

El engine se crea de forma perezosa: importar este módulo no abre conexiones.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from sopvid.plataforma.config import get_settings

# Nombres deterministas para índices y restricciones: las migraciones no dependen de los
# nombres que invente Postgres. Las CHECK necesitan `name=` explícito en el modelo.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base de los modelos ORM; Alembic usa `Base.metadata` para autogenerar."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


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
