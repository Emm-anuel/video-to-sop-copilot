"""Cliente delgado del LLM local servido por Ollama (ADR-006).

Solo httpx contra `/api/chat`, sin frameworks. La salida estructurada se pide pasando un
JSON Schema en el parámetro `format` de Ollama; la decodificación es determinista
(temperature 0 y semilla fija) para que una corrida se pueda repetir.

Dónde corre el modelo lo decide Ollama (GPU si la ve) salvo que se pase `num_gpu`: con 0,
todas las capas van a la CPU (`LLM_DISPOSITIVO=cpu`, ADR-018). `dispositivo_cargado` pregunta
después dónde quedó de verdad.

Las excepciones de httpx no salen de este módulo: se traducen a `LLMNoDisponible` o
`LLMRespuestaInvalida`, que heredan de `LLMError`. Los mensajes de error nunca incluyen el
texto enviado ni el devuelto (pueden contener material del cliente).
"""

import json
import logging
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Self

import httpx

from sopvid.contrato import Dispositivo
from sopvid.plataforma.config import Settings, get_settings

logger = logging.getLogger(__name__)

SEMILLA = 42

# Campos de rendimiento que Ollama devuelve al terminar (duraciones en nanosegundos).
CAMPOS_METRICAS = (
    "total_duration",
    "load_duration",
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
)

# Solo se reintenta cuando la petición pudo no haber llegado o no haber terminado.
_ERRORES_REINTENTABLES = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
# Plazo para pedir que Ollama suelte el modelo: no carga nada, así que responde rápido.
PLAZO_DESCARGA_S = 10.0


class LLMError(Exception):
    """Base de los errores del cliente LLM (incluye peticiones rechazadas con 4xx)."""


class LLMNoDisponible(LLMError):  # noqa: N818 (nombres de dominio acordados)
    """Ollama no responde, no tiene el modelo descargado o falló del lado del servidor."""


class LLMRespuestaInvalida(LLMError):  # noqa: N818
    """Ollama respondió, pero la respuesta no tiene la forma esperada (p. ej. JSON roto)."""


@dataclass(frozen=True)
class RespuestaLLM:
    """Respuesta de `/api/chat`. `datos` es el JSON ya interpretado si se pidió un esquema."""

    texto: str
    datos: Any
    modelo: str
    razon_fin: str | None
    metricas: dict[str, int]


class ClienteLLM:
    """Cliente síncrono de `/api/chat`. Úsalo como context manager para cerrar la conexión."""

    def __init__(
        self,
        base_url: str,
        modelo: str,
        *,
        timeout_s: float = 180.0,
        num_ctx: int = 8192,
        seed: int = SEMILLA,
        think: bool = False,
        num_gpu: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.modelo = modelo
        self.timeout_s = timeout_s
        self.num_ctx = num_ctx
        self.seed = seed
        self.think = think
        # None: Ollama decide; 0: solo CPU; n: n capas en la GPU (opción `num_gpu` de Ollama).
        self.num_gpu = num_gpu
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport)

    @classmethod
    def desde_settings(cls, settings: Settings | None = None, **kwargs: Any) -> Self:
        """Crea el cliente con las variables LLM_* del entorno (o de `.env`)."""
        s = settings or get_settings()
        return cls(
            s.llm_base_url,
            s.llm_model,
            timeout_s=s.llm_timeout_s,
            num_ctx=s.llm_num_ctx,
            num_gpu=0 if s.llm_dispositivo == "cpu" else None,
            **kwargs,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def chat(
        self,
        mensajes: list[dict[str, str]],
        *,
        esquema: dict[str, Any] | None = None,
        think: bool | None = None,
        num_ctx: int | None = None,
    ) -> RespuestaLLM:
        """Envía `mensajes` y devuelve la respuesta completa (sin streaming).

        Con `esquema`, Ollama restringe la salida a ese JSON Schema y aquí se interpreta el
        JSON; validar el contenido contra las reglas del dominio le toca a quien llama. Con
        `num_ctx`, esa ventana de contexto solo en esta petición (Ollama recarga el modelo si
        cambia).
        """
        cuerpo = self.cuerpo(mensajes, esquema=esquema, think=think, num_ctx=num_ctx)
        return self._interpretar(self._post("/api/chat", cuerpo), con_esquema=esquema is not None)

    def cuerpo(
        self,
        mensajes: list[dict[str, str]],
        *,
        esquema: dict[str, Any] | None = None,
        think: bool | None = None,
        stream: bool = False,
        num_ctx: int | None = None,
    ) -> dict[str, Any]:
        """Cuerpo de `/api/chat` con las opciones fijas del cliente (lo reutiliza el benchmark)."""
        cuerpo: dict[str, Any] = {
            "model": self.modelo,
            "messages": mensajes,
            "stream": stream,
            "think": self.think if think is None else think,
            "options": {
                "num_ctx": num_ctx or self.num_ctx,
                "temperature": 0,
                "seed": self.seed,
            },
        }
        if self.num_gpu is not None:
            cuerpo["options"]["num_gpu"] = self.num_gpu
        if esquema is not None:
            cuerpo["format"] = esquema
        return cuerpo

    def disponible(self, timeout_s: float | None = None) -> bool:
        """True si Ollama responde y tiene descargado `modelo`. Nunca lanza excepciones.

        `timeout_s` es un plazo total. Los timeouts de httpx no cubren la resolución DNS (en
        Docker Desktop, un nombre inexistente como "ollama" sin el profile tarda ~4 s en
        fallar), así que la consulta corre en un hilo y se abandona al vencer el plazo.
        """
        plazo = timeout_s or self.timeout_s
        ejecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-health")
        try:
            return ejecutor.submit(self._modelo_descargado, plazo).result(timeout=plazo)
        except Exception as exc:  # incluye el plazo vencido: equivale a "no disponible"
            logger.debug("LLM no disponible en %s: %s", self.base_url, type(exc).__name__)
            return False
        finally:
            ejecutor.shutdown(wait=False)

    def descargar(self, timeout_s: float = PLAZO_DESCARGA_S) -> bool:
        """Pide a Ollama que suelte `modelo` de la memoria ya (`keep_alive: 0`). Nunca lanza.

        Libera la VRAM si Ollama corre en GPU y la RAM si corre en CPU: no depende de que haya
        GPU. Sin esto, el modelo se queda cargado `OLLAMA_KEEP_ALIVE` (30 min en docker compose)
        y el siguiente Whisper no tendría dónde cargar (ADR-014, ADR-019). Devuelve True si
        Ollama aceptó la petición; si no responde, solo lo registra.
        """
        try:
            respuesta = self._http.post(
                "/api/generate", json={"model": self.modelo, "keep_alive": 0}, timeout=timeout_s
            )
            respuesta.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("LLM: no se pudo descargar %s (%s)", self.modelo, type(exc).__name__)
            return False
        logger.info("LLM: %s descargado de la memoria", self.modelo)
        return True

    def dispositivo_cargado(self, timeout_s: float = PLAZO_DESCARGA_S) -> Dispositivo:
        """Dónde tiene Ollama cargado `modelo` ahora: "gpu", "cpu" o "desconocido".

        Lee `size_vram` de `/api/ps`. Hay que llamarlo antes de `descargar`: con el modelo ya
        descargado no aparece y queda "desconocido". En Ollama 0.40.2 `size_vram` no mide bien
        cuánta VRAM usa (docs/dev/llm.md), así que solo se distingue nada (cpu) de algo (gpu); el
        reparto exacto se ve en los logs de Ollama (`offloaded N/N layers`). Nunca lanza.
        """
        try:
            respuesta = self._http.get("/api/ps", timeout=timeout_s)
            respuesta.raise_for_status()
            modelos = respuesta.json()["models"]
            buscado = _nombre_completo(self.modelo)
            for m in modelos:
                if _nombre_completo(str(m.get("name") or m.get("model") or "")) == buscado:
                    return dispositivo_de(m.get("size"), m.get("size_vram"))
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.debug("LLM: no se pudo consultar /api/ps (%s)", type(exc).__name__)
        return "desconocido"

    def _modelo_descargado(self, timeout_s: float) -> bool:
        respuesta = self._http.get("/api/tags", timeout=timeout_s)
        respuesta.raise_for_status()
        nombres = {_nombre_completo(m["name"]) for m in respuesta.json()["models"]}
        return _nombre_completo(self.modelo) in nombres

    def _post(self, ruta: str, cuerpo: dict[str, Any]) -> httpx.Response:
        for intento in (1, 2):
            try:
                respuesta = self._http.post(ruta, json=cuerpo)
                break
            except _ERRORES_REINTENTABLES as exc:
                if intento == 2:
                    raise LLMNoDisponible(
                        f"Ollama no respondió en {self.base_url} tras 2 intentos "
                        f"({type(exc).__name__})"
                    ) from exc
                logger.warning("LLM: %s; se reintenta una vez", type(exc).__name__)
            except httpx.HTTPError as exc:
                raise LLMNoDisponible(
                    f"Error de transporte con {self.base_url} ({type(exc).__name__})"
                ) from exc

        if respuesta.status_code == 404 or respuesta.status_code >= 500:
            raise LLMNoDisponible(
                f"Ollama respondió {respuesta.status_code}: {_mensaje_de_error(respuesta)}"
            )
        if respuesta.is_error:
            raise LLMError(
                f"Ollama rechazó la petición ({respuesta.status_code}): "
                f"{_mensaje_de_error(respuesta)}"
            )
        return respuesta

    def _interpretar(self, respuesta: httpx.Response, *, con_esquema: bool) -> RespuestaLLM:
        try:
            cuerpo = respuesta.json()
            texto = cuerpo["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMRespuestaInvalida("Ollama devolvió un cuerpo sin message.content") from exc
        if not isinstance(texto, str):
            raise LLMRespuestaInvalida("message.content no es texto")

        razon_fin = cuerpo.get("done_reason")
        datos = None
        if con_esquema:
            try:
                datos = json.loads(texto)
            except json.JSONDecodeError as exc:
                raise LLMRespuestaInvalida(
                    f"El modelo no devolvió JSON válido ({len(texto)} caracteres, "
                    f"done_reason={razon_fin})"
                ) from exc

        return RespuestaLLM(
            texto=texto,
            datos=datos,
            modelo=cuerpo.get("model", self.modelo),
            razon_fin=razon_fin,
            metricas={c: cuerpo[c] for c in CAMPOS_METRICAS if c in cuerpo},
        )


def get_cliente_llm() -> Iterator[ClienteLLM]:
    """Dependencia de FastAPI: un cliente por petición, cerrado al terminar."""
    with ClienteLLM.desde_settings() as cliente:
        yield cliente


def dispositivo_de(tamano: Any, en_vram: Any) -> Dispositivo:
    """Nada del modelo en VRAM: "cpu"; algo: "gpu"; tamaños que no son enteros: "desconocido"."""
    if not isinstance(tamano, int) or not isinstance(en_vram, int) or tamano <= 0:
        return "desconocido"
    return "gpu" if en_vram > 0 else "cpu"


def _nombre_completo(modelo: str) -> str:
    """Ollama trata `gemma4` y `gemma4:latest` como el mismo modelo."""
    return modelo if ":" in modelo else f"{modelo}:latest"


def _mensaje_de_error(respuesta: httpx.Response) -> str:
    """Campo `error` de Ollama (p. ej. "model not found"), recortado."""
    try:
        return str(respuesta.json().get("error", ""))[:200]
    except ValueError:
        return ""
