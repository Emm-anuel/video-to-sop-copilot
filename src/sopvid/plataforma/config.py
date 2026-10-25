"""Configuración de la aplicación leída de variables de entorno y de `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
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

    # Videos subidos, audio extraído, fotogramas y PDF. Ignorada por git (material del cliente).
    media_dir: Path = Path("media")
    # Tope por llamada a ffmpeg/ffprobe. Extraer mp3 mono va decenas de veces más rápido que el
    # tiempo real: 300 s cubre videos de una hora con margen.
    ffmpeg_timeout_s: float = Field(default=300.0, gt=0)

    # Transcripción con faster-whisper (RF-09, RF-10). Perfil CPU por defecto; perfil gpu:
    # WHISPER_MODELO=large-v3-turbo, WHISPER_DISPOSITIVO=cuda, WHISPER_COMPUTE_TYPE=float16.
    # El modelo es un nombre de faster-whisper ("small", "large-v3-turbo") o una carpeta local.
    whisper_modelo: str = "small"
    # "auto": cuda si ctranslate2 ve una GPU NVIDIA; si falla antes del primer segmento, CPU.
    whisper_dispositivo: Literal["auto", "cpu", "cuda"] = "auto"
    # "auto": float16 en cuda, int8 en cpu. Cualquier otro valor se pasa tal cual a ctranslate2.
    whisper_compute_type: str = "auto"
    # Pesos descargados la primera vez (ignorada por git; en Docker, el volumen "modelos").
    whisper_cache_dir: Path = Path("models/whisper")

    # LLM local vía Ollama (ADR-006). Desde el host, 127.0.0.1 y no "localhost": en Windows
    # "localhost" prueba ::1 primero y pierde ~2 s por conexión. La API en Docker usa el
    # valor que le pasa docker-compose.yml.
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "gemma4:e4b-it-q4_K_M"
    # Cubre la carga en frío: la primera llamada tras arrancar tardó 56-107 s (ADR-006).
    llm_timeout_s: float = 180.0
    llm_num_ctx: int = 8192
    llm_health_timeout_s: float = 2.0

    # MiniLM para emparejar pasos (ADR-012), siempre en CPU. Los pesos se descargan la primera
    # vez a esta carpeta (ignorada por git; en Docker, el volumen "modelos").
    embedder_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedder_cache_dir: Path = Path("models/embedder")
    # Umbrales de coseno MiniLM (RNF-14). Cascada (ADR-012): por debajo de `umbral_bajo` no hay
    # pareja; entre `umbral_bajo` y `umbral_alto` decide Gemma 4; desde `umbral_alto` se acepta.
    # Fusión (ADR-013): pasos consecutivos del video con el mismo paso del SOP más parecido y
    # coseno ≥ `umbral_fusion` se unen antes de emparejar.
    umbral_bajo: float = Field(default=0.55, ge=0, le=1)
    umbral_alto: float = Field(default=0.75, ge=0, le=1)
    umbral_fusion: float = Field(default=0.55, ge=0, le=1)

    @model_validator(mode="after")
    def _umbrales_ordenados(self) -> Self:
        if self.umbral_bajo > self.umbral_alto:
            raise ValueError(
                f"UMBRAL_BAJO ({self.umbral_bajo}) no puede ser mayor que "
                f"UMBRAL_ALTO ({self.umbral_alto})"
            )
        return self

    @property
    def data_path(self) -> Path:
        """`data_dir` absoluto; si es relativo, se resuelve contra la raíz del proyecto."""
        return _absoluta(self.data_dir)

    @property
    def media_path(self) -> Path:
        """`media_dir` absoluto; si es relativo, contra la raíz del proyecto."""
        return _absoluta(self.media_dir)

    @property
    def whisper_cache_path(self) -> Path:
        """`whisper_cache_dir` absoluto; si es relativo, contra la raíz del proyecto."""
        return _absoluta(self.whisper_cache_dir)

    @property
    def embedder_cache_path(self) -> Path:
        """`embedder_cache_dir` absoluto; si es relativo, contra la raíz del proyecto."""
        return _absoluta(self.embedder_cache_dir)

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


def _absoluta(ruta: Path) -> Path:
    return ruta if ruta.is_absolute() else PROJECT_ROOT / ruta


@lru_cache
def get_settings() -> Settings:
    return Settings()
