"""Configuración de la aplicación leída de variables de entorno y de `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


def _find_env_file() -> Path | None:
    """Busca `.env` en el directorio actual y sus padres.

    Permite que un notebook en `docs/entregables/Semana N/` use el `.env` de la raíz.
    """
    cwd = Path.cwd()
    for folder in (cwd, *cwd.parents):
        candidate = folder / ".env"
        if candidate.is_file():
            return candidate
    return None


_ENV_FILE = _find_env_file()
# Raíz del proyecto: donde vive `.env`; sin `.env` (p. ej. en CI), el directorio actual.
PROJECT_ROOT = _ENV_FILE.parent if _ENV_FILE else Path.cwd()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_port: int = 8000
    app_secret_key: SecretStr | None = None

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "sopvid"
    postgres_user: str = "sopvid"
    postgres_password: SecretStr | None = None
    # Si se define (y no está vacía), tiene prioridad sobre las POSTGRES_*.
    database_url: str | None = None

    # Anotaciones públicas de CaptainCook4D (avances académicos). Nunca se versionan.
    data_dir: Path = Path("data/raw/captaincook4d")

    # LLM local vía Ollama (ADR-006). Desde el host, 127.0.0.1 y no "localhost": en Windows
    # "localhost" prueba ::1 primero y pierde ~2 s por conexión. La API en Docker usa el
    # valor que le pasa docker-compose.yml.
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "gemma4:e4b-it-q4_K_M"
    # Cubre la carga en frío: la primera llamada tras arrancar tardó 56-107 s (ADR-006).
    llm_timeout_s: float = 180.0
    llm_num_ctx: int = 8192
    llm_health_timeout_s: float = 2.0

    @property
    def data_path(self) -> Path:
        """`data_dir` absoluto; si es relativo, se resuelve contra la raíz del proyecto."""
        return self.data_dir if self.data_dir.is_absolute() else PROJECT_ROOT / self.data_dir

    @property
    def sqlalchemy_url(self) -> URL:
        if self.database_url:
            return make_url(self.database_url)
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=(
                self.postgres_password.get_secret_value() if self.postgres_password else None
            ),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
