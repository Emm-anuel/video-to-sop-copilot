"""Dobles compartidos por las pruebas de la API y de la validación (sin GPU, Ollama ni MiniLM).

- `TranscriptorFalso`: entrega `SEGMENTOS` (tres frases inventadas de 0 a 2.8 s).
- `OllamaFalso`: Ollama simulado con `httpx.MockTransport` para `ClienteLLM`: `/api/tags`, las
  dos llamadas de la segmentación (fronteras y redacción, según el esquema pedido),
  `/api/generate` con `keep_alive: 0` y `/api/ps` (el modelo en GPU, salvo `vram=0`).
- `JuezFalso`: decide cada par de la zona gris con un veredicto fijo, o deja el respaldo.
- `VectorizadorGuionado`: el vector de cada texto según su prefijo, para fijar el coseno de cada
  par sin MiniLM.
- `Entorno`: la app con la sesión de la prueba, ajustes en `tmp_path`, trabajos que corren a mano
  y estos dobles inyectados.

Todo es inventado por el equipo (CLAUDE.md §2.1). `eventos` es una lista compartida que registra,
en orden, cuándo Whisper soltó la memoria y cada petición a Ollama (ADR-014).
"""

import hashlib
import json
import math
from collections.abc import Callable, Iterator
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from sqlalchemy.orm import Session

from sopvid.contrato import SOP, Idioma, Juicio, Palabra, PasoSOP, PasoVideo, Segmento
from sopvid.lenguaje import emparejamiento as emp
from sopvid.lenguaje.juez import respaldo
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.validacion import DependenciasValidacion
from sopvid.percepcion.segmentacion import ESQUEMA_FRONTERAS, ESQUEMA_REDACCION
from sopvid.percepcion.transcripcion import AlSegmento, Transcripcion
from sopvid.plataforma.api.main import create_app
from sopvid.plataforma.api.videos import get_procesador, get_transcriptor, get_validacion
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.modelos import Sop, Video
from sopvid.plataforma.procesamiento import Procesador

# ── Transcripción ────────────────────────────────────────────────────────────────────────────


def _segmento(id_: int, t: float, t_fin: float, texto: str) -> Segmento:
    palabras = texto.split()
    paso = (t_fin - t) / len(palabras)
    return Segmento(
        id=id_,
        t_inicio=t,
        t_fin=t_fin,
        texto=texto,
        palabras=[
            Palabra(w=w, t=round(t + i * paso, 3), t_fin=round(t + (i + 1) * paso, 3))
            for i, w in enumerate(palabras)
        ],
    )


SEGMENTOS = [
    _segmento(0, 0.0, 0.9, "Primero reviso el manómetro."),
    _segmento(1, 1.0, 1.9, "Después cierro la válvula."),
    _segmento(2, 2.0, 2.8, "Por último anoto la lectura."),
]


class TranscriptorFalso:
    """Entrega SEGMENTOS por `al_segmento`; `antes(i)` corre antes de cada uno.

    Al devolver agrega "whisper_liberado" a `eventos`: el `TranscriptorWhisper` real suelta el
    modelo antes de devolver (ADR-014).
    """

    def __init__(
        self,
        antes: Callable[[int], None] | None = None,
        error: Exception | None = None,
        eventos: list[str] | None = None,
    ):
        self.antes, self.error = antes, error
        self.eventos = eventos if eventos is not None else []
        self.idiomas: list[str | None] = []

    def transcribir(
        self, audio: Path, idioma: str | None = None, al_segmento: AlSegmento | None = None
    ) -> Transcripcion:
        self.idiomas.append(idioma)
        for i, segmento in enumerate(SEGMENTOS):
            if self.antes is not None:
                self.antes(i)
            if self.error is not None:
                raise self.error
            if al_segmento is not None:
                al_segmento(segmento)
        self.eventos.append("whisper_liberado")
        return Transcripcion(
            idioma=Idioma(
                codigo=idioma or "es", confianza=1.0 if idioma else 0.97, fijado_a_mano=bool(idioma)
            ),
            segmentos=list(SEGMENTOS),
            duracion_s=3.0,
            modelo="falso",
            dispositivo="cpu",
            compute_type="int8",
            segundos=0.0,
        )


# ── SOP inventado para SEGMENTOS ─────────────────────────────────────────────────────────────

SOP_PRUEBA = SOP(
    titulo="Revisión de la línea de agua",
    pasos=[
        PasoSOP(numero=1, nombre="Revisar el manómetro", responsable="Técnico"),
        PasoSOP(numero=2, nombre="Cerrar la válvula", responsable="Técnico"),
        PasoSOP(numero=3, nombre="Anotar la lectura", responsable="Técnico"),
    ],
)


def guardar_sop(session: Session, sop: SOP = SOP_PRUEBA) -> Sop:
    fila = Sop(titulo=sop.titulo, origen="cargado", contenido=sop.model_dump(mode="json"))
    session.add(fila)
    session.commit()
    return fila


# ── Ollama simulado ──────────────────────────────────────────────────────────────────────────

MODELO = "falso"
# Lo que respondería Gemma 4 para SEGMENTOS (los títulos no coinciden con los nombres del SOP).
FRONTERAS = [
    {"segmento_id": 0, "titulo": "Revisión del manómetro"},
    {"segmento_id": 1, "titulo": "Cierre de la válvula"},
    {"segmento_id": 2, "titulo": "Anotación de la lectura"},
]
REDACCION = [
    {"numero": n, "descripcion": "", "responsable": "Técnico", "cita": s.texto}
    for n, s in enumerate(SEGMENTOS, start=1)
]


class OllamaFalso:
    """Ollama simulado. `disponible=False`: no responde a nada; `caido_en_chat=True`: responde
    `/api/tags` pero se cae en `/api/chat` y `/api/generate` (Ollama cae a medias).

    Registra en `eventos` "tags", "chat:fronteras", "chat:redaccion" y "descargar"; `al_pedir`
    corre en cada petición (para ver el estado del video mientras segmenta).
    """

    def __init__(self, eventos: list[str], *, disponible: bool = True):
        self.eventos = eventos
        self.disponible = disponible
        self.caido_en_chat = False
        self.al_pedir: Callable[[], None] | None = None
        self.descargas: list[dict[str, Any]] = []
        # Bytes del modelo en VRAM que informa /api/ps, sobre un total de 100.
        self.vram = 100

    def cliente(self) -> ClienteLLM:
        return ClienteLLM(
            "http://ollama.test:11434", MODELO, transport=httpx.MockTransport(self._manejar)
        )

    def _manejar(self, request: httpx.Request) -> httpx.Response:
        if self.al_pedir is not None:
            self.al_pedir()
        ruta = request.url.path
        if not self.disponible:
            raise httpx.ConnectError("Ollama apagado", request=request)
        if ruta == "/api/tags":
            self.eventos.append("tags")
            return httpx.Response(200, json={"models": [{"name": f"{MODELO}:latest"}]})
        if ruta == "/api/ps":  # no se registra: solo informa, no cambia nada en Ollama
            modelo = {"name": f"{MODELO}:latest", "size": 100, "size_vram": self.vram}
            return httpx.Response(200, json={"models": [modelo]})
        cuerpo = json.loads(request.content)
        if ruta == "/api/generate":
            self.eventos.append("descargar")
            self.descargas.append(cuerpo)
            if self.caido_en_chat:
                raise httpx.ConnectError("Ollama se cayó", request=request)
            return httpx.Response(200, json={"model": MODELO, "done": True})
        assert ruta == "/api/chat", ruta
        if cuerpo.get("format") == ESQUEMA_FRONTERAS:
            self.eventos.append("chat:fronteras")
            contenido = FRONTERAS
        else:
            assert cuerpo.get("format") == ESQUEMA_REDACCION
            self.eventos.append("chat:redaccion")
            contenido = REDACCION
        if self.caido_en_chat:
            raise httpx.ConnectError("Ollama se cayó", request=request)
        return httpx.Response(
            200,
            json={
                "model": MODELO,
                "message": {"role": "assistant", "content": json.dumps(contenido)},
            },
        )


# ── Juez y vectorizador ──────────────────────────────────────────────────────────────────────


class JuezFalso:
    """Decide con `veredicto`; con None, respaldo "llm_no_disponible" (sin revisar).

    `error` se lanza en vez de decidir. Registra el número del paso del SOP de cada par.
    """

    def __init__(self, veredicto: str | None = "Parcial", error: Exception | None = None):
        self.veredicto, self.error = veredicto, error
        self.llamadas: list[int] = []

    def juzgar(
        self, paso_sop: PasoSOP, paso_video: PasoVideo, similitud: float, narracion: str
    ) -> Juicio:
        self.llamadas.append(paso_sop.numero)
        if self.error is not None:
            raise self.error
        if self.veredicto is None:
            return respaldo(similitud, "llm_no_disponible", 1)
        return Juicio(
            origen="llm",
            veredicto=self.veredicto,
            justificacion="No dice que revisa el sello de la válvula.",
            cita=narracion,
            similitud=similitud,
            prompt="juez_falso",
            modelo=MODELO,
            intentos=1,
        )


class VectorizadorGuionado:
    """El vector de cada texto según el primer prefijo de `guion` con que empieza.

    `guion` asigna a cada prefijo un concepto y un coseno: el paso del SOP con coseno 1 es el
    vector base del concepto, y un paso del video con coseno s queda a ese coseno de él (con una
    componente propia ortogonal). Un texto sin prefijo recibe un vector propio, ortogonal a todo.
    """

    def __init__(self, guion: dict[str, tuple[int, float]]):
        self.guion = guion

    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray:
        x = np.zeros((len(sentences), emp.DIMENSION))
        for i, texto in enumerate(sentences):
            for prefijo, (concepto, coseno) in self.guion.items():
                if texto.startswith(prefijo):
                    x[i, concepto] = coseno
                    x[i, 100 + _indice(prefijo)] = math.sqrt(max(0.0, 1 - coseno**2))
                    break
            else:
                x[i, 100 + _indice(texto)] = 1.0
        return x


def _indice(texto: str) -> int:
    return int(hashlib.md5(texto.encode()).hexdigest(), 16) % (emp.DIMENSION - 100)


# Paso 1 y 3: Cumple; paso 2 en zona gris (0.65): lo decide el juez.
GUION_PRUEBA = {
    "Revisar el manómetro": (1, 1.0),
    "Cerrar la válvula": (2, 1.0),
    "Anotar la lectura": (3, 1.0),
    "Revisión del manómetro": (1, 1.0),
    "Cierre de la válvula": (2, 0.65),
    "Anotación de la lectura": (3, 1.0),
}


def embedder_guionado(guion: dict[str, tuple[int, float]], cache: Path) -> emp.Embedder:
    vectorizador = VectorizadorGuionado(guion)
    return emp.Embedder("vectorizador-guionado", cache, cargador=lambda m, c: vectorizador)


# ── La app con los dobles ────────────────────────────────────────────────────────────────────


class Entorno:
    """App con la sesión de la prueba, ajustes en `tmp_path` y trabajos que corren a mano."""

    def __init__(self, db_session: Session, tmp_path: Path):
        self.session = db_session
        self.settings = Settings(media_dir=tmp_path / "media", subida_max_mb=1)
        self.pendientes: list[Callable[[], None]] = []
        self.eventos: list[str] = []
        self.transcriptor = TranscriptorFalso(eventos=self.eventos)
        self.ollama = OllamaFalso(self.eventos)
        self.juez = JuezFalso()
        self.guion = dict(GUION_PRUEBA)
        self.clientes: list[ClienteLLM] = []
        self.procesador = procesador = Procesador(
            lambda: nullcontext(db_session),
            self.settings.media_path,
            self.pendientes.append,
            gpu=lambda: "GPU de prueba",
        )

        def dependencias() -> DependenciasValidacion:
            cliente = self.ollama.cliente()
            self.clientes.append(cliente)
            return DependenciasValidacion(
                cliente, self.juez, embedder_guionado(self.guion, tmp_path / "modelos")
            )

        def sesion() -> Iterator[Session]:
            yield db_session

        self.app = create_app(
            sesiones=lambda: nullcontext(db_session), recuperar_interrumpidos=False
        )
        self.app.dependency_overrides[get_session] = sesion
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        self.app.dependency_overrides[get_procesador] = lambda: procesador
        self.app.dependency_overrides[get_transcriptor] = lambda: self.transcriptor
        self.app.dependency_overrides[get_validacion] = lambda: dependencias

    def correr_pendientes(self) -> None:
        while self.pendientes:
            self.pendientes.pop(0)()

    def video(self, video_id: int) -> Video:
        video = self.session.get(Video, video_id)
        self.session.refresh(video)
        return video
