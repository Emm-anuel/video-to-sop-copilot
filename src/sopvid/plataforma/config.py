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
    # Tamaño máximo de un video en POST /videos (subida completa, RF-06 del MVP).
    subida_max_mb: int = Field(default=1024, gt=0)

    # Transcripción con faster-whisper (RF-09, RF-10). El mismo modelo en CPU y en GPU
    # (ADR-018, decidido el 8 nov): large-v3-turbo, int8 en CPU y float16 en cuda. El modelo es
    # un nombre de faster-whisper ("large-v3-turbo", "small") o una carpeta local.
    whisper_modelo: str = "large-v3-turbo"
    # Modelo cuando Whisper corre en CPU (WHISPER_DISPOSITIVO=cpu, "auto" sin GPU o el respaldo si
    # cuda falla); vacío, el mismo WHISPER_MODELO. El de referencia es large-v3-turbo: con otro
    # (p. ej. small, más rápido en CPU), el reporte y la ficha llevan el aviso
    # "transcripcion_no_referencia" y el reporte queda provisional.
    whisper_modelo_cpu: str | None = "large-v3-turbo"
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
    # Ventana para convertir un SOP sin plantilla cuando el documento no cabe en `llm_num_ctx`
    # (ADR-015); más allá, 422. Con 16384, Gemma 4 sigue entero en la GPU de 8 GB (docs/dev/llm.md).
    llm_num_ctx_sop: int = 16384
    llm_health_timeout_s: float = 2.0
    # Conversión de un SOP con Gemma en flujo (`ClienteLLM.chat_en_flujo`): corta si pasan
    # `llm_inactividad_s` sin un token (después del primero, que espera `llm_timeout_s`) o, aunque
    # siga generando, al llegar a `llm_timeout_sop_s` en total. En CPU tarda 150-200 s (ADR-018).
    llm_inactividad_s: float = 60.0
    llm_timeout_sop_s: float = 900.0
    # Ficha de contexto del video (RF-12): los mismos cortes que la conversión del SOP (primer
    # token en `llm_timeout_s`, `llm_inactividad_s` sin tokens) y este tope total, que cubre los
    # reintentos por JSON inválido.
    llm_timeout_contexto_s: float = Field(default=600.0, gt=0)
    # Dónde corre Gemma (ADR-018): "auto" deja que Ollama use la GPU si la ve; "cpu" pide
    # num_gpu=0 y lo fuerza a la CPU (medir sin GPU, o un equipo donde no cabe en la VRAM).
    llm_dispositivo: Literal["auto", "cpu"] = "auto"

    # Imágenes del video (RF-11, ADR-024). La miniatura por paso se saca siempre, con ffmpeg y sin
    # modelo: un JPEG con este lado mayor, en media/videos/<id>/miniaturas/.
    miniatura_lado_px: int = Field(default=320, ge=32, le=1920)
    # Describir imágenes con Gemma antes de la ficha de contexto: el valor por defecto de la
    # instalación. `analizar_imagenes` de POST /videos gana sobre él, video por video.
    fotogramas_describir: bool = False
    # Cuántas se describen: los pasos del SOP (modo validar) o la duración por `pasos_por_min`
    # (modo generar), entre `fotogramas_min` y `fotogramas_max` (tope de 20, ADR-002), repartidas
    # de forma pareja en el video. SIN CALIBRAR: `pasos_por_min` es la mediana de pasos reales por
    # minuto de A, B, C y E (2.67, 3.14, 1.79, 1.58; D no sigue su SOP), medida el 10 nov.
    pasos_por_min: float = Field(default=2.2, gt=0)
    fotogramas_min: int = Field(default=4, ge=1, le=20)
    fotogramas_max: int = Field(default=20, ge=1, le=20)
    # JPEG que recibe Gemma (lado mayor) y cuántos van por llamada. FOTOGRAMAS_LOTE es la palanca
    # para equipos con menos memoria: con 8 la GPU de referencia (8 GB) llega a 7.2 GB (ADR-024).
    # Si Ollama responde sin memoria, el lote baja solo a la mitad una vez y sigue así; si tampoco
    # cabe, las imágenes que falten no se describen (aviso "imagenes_incompletas") y el análisis
    # sigue. En un equipo con menos VRAM, baja este valor (4, 2…) para no perder la primera llamada.
    fotogramas_lado_px: int = Field(default=512, ge=64, le=1920)
    fotogramas_lote: int = Field(default=8, ge=1, le=20)
    # Tope por lote, en flujo (primer token incluido: en CPU leer las imágenes tarda).
    llm_timeout_fotogramas_s: float = Field(default=600.0, gt=0)
    # Segundos que suma cada imagen descrita (imágenes + ficha con ellas − ficha sola), para avisar
    # antes de procesar (GET /videos/estimacion). Mediana de C, D y E, una corrida por
    # combinación (11 nov, ADR-024): GPU 0.4–1.3 s, CPU 10.4–12.9 s. Pocos videos: orientativo.
    seg_imagen_gpu: float = Field(default=1.2, ge=0)
    seg_imagen_cpu: float = Field(default=10.7, ge=0)

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
    # Candado del SOP generado (ADR-023): si Gemma dice que un paso del video "continua" el
    # anterior pero su coseno MiniLM (minúsculas, nombre, descripción y cita) es menor que
    # `umbral_fusion`, el código lo parte ahí en un paso nuevo.
    sop_candado: bool = False
    # Equipo de operación del SOP generado (ADR-023): dos nombres (ya en español) con coseno
    # MiniLM ≥ `umbral_equipo`, en minúsculas, se unen en uno. Medido solo con el video E.
    umbral_equipo: float = Field(default=0.85, ge=0, le=1)

    # Cortes del semáforo de cumplimiento (RF-19, RNF-14; SOP V1.0 §5.6): verde desde
    # `semaforo_verde`, amarillo desde `semaforo_amarillo`, rojo por debajo.
    semaforo_verde: float = Field(default=90, ge=0, le=100)
    semaforo_amarillo: float = Field(default=70, ge=0, le=100)

    # Contexto, personas y tiempos del reporte (RNF-14; SOP V1.0 §5.2, §5.4, §5.5).
    # Afinidad mínima (0–100) para no advertir que el video no es de este SOP (RF-17).
    afinidad_min: float = Field(default=60, ge=0, le=100)
    # Mapeo de un coseno MiniLM a 0–100 para cada componente de la afinidad (ADR-020): el coseno
    # `afinidad_cos_cero` o menos vale 0, `afinidad_cos_cien` o más vale 100, lineal entre los
    # dos. Un equipo del SOP está "en común" si su mejor equipo de la ficha tiene coseno ≥
    # `afinidad_umbral_equipo`. SIN CALIBRAR: valores de la sonda del 8 nov (ADR-020).
    afinidad_cos_cero: float = Field(default=0.30, ge=-1, le=1)
    afinidad_cos_cien: float = Field(default=0.80, ge=-1, le=1)
    afinidad_umbral_equipo: float = Field(default=0.75, ge=0, le=1)
    # Margen sobre el tiempo esperado de cada paso y del total (RF-16): 0.20 = ±20 %.
    tolerancia_tiempo: float = Field(default=0.20, ge=0, le=1)
    # Coseno MiniLM desde el que un rol del SOP coincide con el de una persona (RF-15).
    # SIN CALIBRAR. Medido el 7 nov con roles inventados: "Técnico" ~ "Técnica de mantenimiento"
    # 0.88, pero "Supervisor de mantenimiento" ~ "Técnico de mantenimiento" también 0.89, y con
    # el nombre de la persona ("Laura (técnica…)") baja a 0.58. Comparar rol contra rol, sin el
    # nombre, y no depender solo del coseno.
    umbral_rol: float = Field(default=0.85, ge=0, le=1)
    # Desde ADR-020 `umbral_rol` compara los núcleos de los roles ("técnico", "supervisor") y, si
    # los dos roles traen complemento ("de mantenimiento"), los complementos deben llegar a
    # `umbral_rol_complemento` (o compartir palabras). SIN CALIBRAR.
    umbral_rol_complemento: float = Field(default=0.70, ge=0, le=1)
    # Coseno MiniLM (en minúsculas) desde el que el horario del SOP y el que menciona el video
    # coinciden, si ninguno contiene al otro (RF-16, ADR-021). SIN CALIBRAR.
    umbral_horario: float = Field(default=0.75, ge=0, le=1)

    @model_validator(mode="after")
    def _umbrales_ordenados(self) -> Self:
        if self.umbral_bajo > self.umbral_alto:
            raise ValueError(
                f"UMBRAL_BAJO ({self.umbral_bajo}) no puede ser mayor que "
                f"UMBRAL_ALTO ({self.umbral_alto})"
            )
        return self

    @model_validator(mode="after")
    def _cortes_ordenados(self) -> Self:
        if self.semaforo_verde <= self.semaforo_amarillo:
            raise ValueError(
                f"SEMAFORO_VERDE ({self.semaforo_verde}) debe ser mayor que "
                f"SEMAFORO_AMARILLO ({self.semaforo_amarillo})"
            )
        return self

    @model_validator(mode="after")
    def _mapeo_afinidad(self) -> Self:
        if self.afinidad_cos_cero >= self.afinidad_cos_cien:
            raise ValueError(
                f"AFINIDAD_COS_CERO ({self.afinidad_cos_cero}) debe ser menor que "
                f"AFINIDAD_COS_CIEN ({self.afinidad_cos_cien})"
            )
        return self

    @model_validator(mode="after")
    def _fotogramas_ordenados(self) -> Self:
        if self.fotogramas_min > self.fotogramas_max:
            raise ValueError(
                f"FOTOGRAMAS_MIN ({self.fotogramas_min}) no puede ser mayor que "
                f"FOTOGRAMAS_MAX ({self.fotogramas_max})"
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
    def subida_max_bytes(self) -> int:
        return self.subida_max_mb * 1024 * 1024

    def modelo_whisper(self, dispositivo: str) -> str:
        """El modelo de Whisper para `dispositivo` ya resuelto ("cpu" o "cuda")."""
        if dispositivo == "cpu" and self.whisper_modelo_cpu:
            return self.whisper_modelo_cpu
        return self.whisper_modelo

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
