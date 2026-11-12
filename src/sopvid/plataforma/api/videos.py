"""Subida de videos completos (RF-06 del MVP), consulta del análisis y del reporte.

`POST /videos` guarda el archivo en `MEDIA_DIR/videos/<id>/video.<ext>`, crea la fila con
`proceso="en_cola"` y encola el análisis; responde 202 con el id. El archivo se copia por
bloques; en la fila va la ruta relativa a `MEDIA_DIR`, nunca el nombre original. El tamaño se
limita dos veces: `limitar_content_length` rechaza la petición antes de recibirla si el
`Content-Length` ya excede el límite, y la copia cuenta los bytes reales.

En modo validar hace falta un SOP de referencia y el trabajo sigue con la validación (pasos del
video, emparejamiento y reporte). El SOP es uno de la biblioteca (`sop_id`) o uno nuevo adjunto
(`sop`, RF-02). El adjunto sigue el mismo camino que `POST /sops`: la petición revisa que se
pueda leer (`leer_archivo_sop`: 415, 413 o 422 antes de guardar nada), crea el SOP en "en_cola"
en la misma transacción que el video y encola su conversión antes que el video. El video espera
a su SOP (va después en la cola); si la conversión falla, el video queda en error con el mensaje
del SOP. Un `sop_id` de un SOP en error da 422; uno que todavía convierte se acepta y espera.
`POST /videos/{id}/validar` repite la validación sin volver a transcribir (ADR-019) y
`GET /videos/{id}/reporte` devuelve el reporte (`ReporteValidacion`).
Afinidad baja (ADR-020): si el video parece no ser del SOP, la validación se detiene con
`proceso="afinidad_baja"` y `GET /videos/{id}` trae la `afinidad` (valor y explicación) para
advertirlo; `POST /videos/{id}/validar?continuar=true` sigue sin detenerse.
`GET /videos/{id}/video` entrega el archivo con `Range` para el reproductor del reporte (RF-20).
`GET /videos/{id}/contexto` devuelve la ficha de contexto (RF-12) si ya se generó.

Imágenes (RF-11, ADR-024): `analizar_imagenes` en `POST /videos` pide describir imágenes con
Gemma antes de la ficha y gana sobre `FOTOGRAMAS_DESCRIBIR` (apagado por defecto).
`GET /videos/estimacion` dice antes de subir cuántas imágenes se describirían y cuánto tiempo
sumarían con y sin GPU; nunca prohíbe nada. `GET /videos/{id}/thumb?t=` entrega la miniatura del
segundo `t` (la guardada a ≤ 1 s o una nueva, solo ffmpeg), con cabeceras de caché.

La subida por partes de 16 MB con reintentos es de S5; aquí no está.
"""

import logging
import math
import mimetypes
import re
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, BinaryIO, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sopvid.contrato import (
    SOP,
    Afinidad,
    Analisis,
    Contexto,
    ReporteValidacion,
    ResultadoValidacion,
)
from sopvid.lenguaje.lectura_sop import AjustesConversion
from sopvid.lenguaje.llm import ClienteLLM, get_cliente_llm
from sopvid.lenguaje.reporte import armar_reporte
from sopvid.lenguaje.validacion import DependenciasValidacion, FabricaValidacion
from sopvid.percepcion import miniaturas
from sopvid.percepcion.fotogramas import cuantas_imagenes
from sopvid.percepcion.medios import ErrorMedios, duracion, imagen_visible, tiene_imagen
from sopvid.percepcion.pipeline import ARCHIVO_TXT
from sopvid.percepcion.transcripcion import Transcriptor, TranscriptorWhisper
from sopvid.plataforma.api.sops import (
    FabricaLLM,
    carpeta_sop,
    get_fabrica_llm,
    get_procesador,
    leer_archivo_sop,
)
from sopvid.plataforma.config import Settings, get_settings
from sopvid.plataforma.db import get_session
from sopvid.plataforma.hardware import (
    PlanDispositivos,
    dispositivo_llm_probable,
    get_plan_dispositivos,
)
from sopvid.plataforma.modelos import MODOS_VIDEO, Sop, Video
from sopvid.plataforma.procesamiento import (
    AFINIDAD_BAJA,
    EN_COLA,
    LISTO,
    PROCESANDO,
    SOP_ERROR,
    SOP_LISTO,
    Procesador,
    crear_sop_en_cola,
    error_de_sop,
    leer_analisis,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["videos"])

EXTENSIONES = (".mp4", ".mov", ".mkv", ".webm")
BLOQUE = 1024 * 1024
# Holgura para los campos del formulario y los separadores multipart en el Content-Length. No
# cubre un SOP adjunto grande (hasta `sops.SOP_DOCUMENTO_MAX_BYTES`): con un video justo en el
# límite, el middleware rechaza la petición antes de leerla; con los límites reales (GB) no pasa.
HOLGURA_FORMULARIO = 1024 * 1024
_IDIOMA = re.compile(r"^[a-z]{2,3}$")
# La miniatura de un segundo no cambia: el navegador la guarda un día sin volver a pedirla.
CACHE_MINIATURA = "private, max-age=86400, immutable"


class VideoCreado(BaseModel):
    """`sop_id`: el SOP de referencia; con uno adjunto, el nuevo (su estado, en
    `GET /sops/{sop_id}/estado`)."""

    id: int
    proceso: str
    sop_id: int | None = None


class EstadoVideo(BaseModel):
    id: int
    titulo: str
    modo: str
    proceso: str
    etapa: str | None
    progreso: int
    duracion: float | None
    idioma: str | None
    error: str | None
    creado: datetime
    # SOP de referencia; uno adjunto puede seguir convirtiéndose (GET /sops/{id}/estado).
    sop_id: int | None = None
    # Afinidad de contexto (RF-17, ADR-020): con "afinidad_baja", la de la detención (la pantalla
    # advierte y ofrece continuar); con "listo", la del reporte. None sin ficha o sin validación.
    afinidad: Afinidad | None = None


class EstimacionImagenes(BaseModel):
    """Respuesta de `GET /videos/estimacion` (ADR-024): cuánto sumaría describir las imágenes.

    `imagenes_estimadas` es la N que se usaría; los segundos extra son N por `SEG_IMAGEN_GPU` o
    `SEG_IMAGEN_CPU` (sin calibrar hasta la medición de ADR-024). `dispositivo` es dónde correría
    Gemma; `dispositivo_supuesto`, si no se pudo saber y se supuso CPU. `aviso` va listo para la
    pantalla. Solo informa: nunca prohíbe describir.
    """

    imagenes_estimadas: int
    segundos_extra_gpu: float
    segundos_extra_cpu: float
    dispositivo: Literal["cpu", "gpu"]
    dispositivo_supuesto: bool
    aviso: str


def get_transcriptor(settings: Annotated[Settings, Depends(get_settings)]) -> Transcriptor:
    """Transcriptor según WHISPER_*; el modelo solo se carga al transcribir."""
    return TranscriptorWhisper(settings)


def get_validacion(settings: Annotated[Settings, Depends(get_settings)]) -> FabricaValidacion:
    """Fábrica de las dependencias de la validación (Gemma 4 por Ollama, juez y MiniLM).

    Se llama dentro del trabajo: en modo validar para la validación, y en modo generar solo para
    la ficha de contexto (MiniLM no se carga). El procesador cierra el cliente.
    """
    return lambda: DependenciasValidacion.desde_settings(settings)


async def limitar_content_length(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Middleware: 413 antes de recibir el cuerpo si `Content-Length` ya excede el límite."""
    if request.method == "POST" and request.url.path == "/videos":
        settings = request.app.dependency_overrides.get(get_settings, get_settings)()
        largo = request.headers.get("content-length")
        maximo = settings.subida_max_bytes + HOLGURA_FORMULARIO
        if largo and largo.isdigit() and int(largo) > maximo:
            return JSONResponse(status_code=413, content={"detail": _detalle_tamano(settings)})
    return await call_next(request)


@router.post("/videos", status_code=202, response_model=VideoCreado)
def subir_video(
    response: Response,
    archivo: Annotated[UploadFile, File(description="Video completo: mp4, mov, mkv o webm")],
    titulo: Annotated[str, Form(min_length=1, max_length=300)],
    modo: Annotated[str, Form(description="validar | generar")],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    procesador: Annotated[Procesador, Depends(get_procesador)],
    transcriptor: Annotated[Transcriptor, Depends(get_transcriptor)],
    validacion: Annotated[FabricaValidacion, Depends(get_validacion)],
    fabrica_llm: Annotated[FabricaLLM, Depends(get_fabrica_llm)],
    idioma: Annotated[str | None, Form(description="ISO 639-1 para fijarlo (p. ej. es)")] = None,
    sop_id: Annotated[
        int | None, Form(description="SOP de la biblioteca; con modo=validar, este o `sop`")
    ] = None,
    sop: Annotated[
        UploadFile | None,
        File(description="SOP nuevo (.md, .txt, .pdf o .docx); con modo=validar, este o sop_id"),
    ] = None,
    analizar_imagenes: Annotated[
        bool | None,
        Form(
            description="Describir imágenes con Gemma antes de la ficha (ADR-024); sin el campo, "
            "FOTOGRAMAS_DESCRIBIR de la instalación"
        ),
    ] = None,
) -> VideoCreado:
    extension = Path(archivo.filename or "").suffix.lower()
    if extension not in EXTENSIONES:
        raise HTTPException(415, f"extensión no permitida; usa {', '.join(EXTENSIONES)}")
    if modo not in MODOS_VIDEO:
        raise HTTPException(422, f"modo debe ser uno de {', '.join(MODOS_VIDEO)}")
    titulo = titulo.strip()
    if not titulo:
        raise HTTPException(422, "el título no puede ir vacío")
    idioma = (idioma or "").strip().lower() or None
    if idioma is not None and not _IDIOMA.match(idioma):
        raise HTTPException(422, "idioma debe ser un código ISO 639-1, p. ej. 'es'")
    if sop is not None and sop_id is not None:
        raise HTTPException(422, "usa sop_id o sop, no los dos")
    if modo == "validar" and sop_id is None and sop is None:
        raise HTTPException(422, "sop_id o sop es obligatorio con modo=validar")
    if modo == "generar" and (sop_id is not None or sop is not None):
        raise HTTPException(422, "sop_id y sop no van con modo=generar: el SOP sale del video")
    if sop_id is not None:
        referencia = session.get(Sop, sop_id)
        if referencia is None:
            raise HTTPException(404, "SOP no encontrado")
        if referencia.estado == SOP_ERROR:
            raise HTTPException(422, error_de_sop(referencia))
        if not referencia.en_biblioteca:
            raise HTTPException(
                422,
                f"El SOP {referencia.codigo} se generó desde un video y no está en la biblioteca: "
                "guárdalo con POST /sops/{id}/biblioteca para usarlo como referencia",
            )
    # Del SOP adjunto se revisa aquí que se pueda leer; lo convierte el trabajador.
    adjunto = leer_archivo_sop(sop) if sop is not None else None

    carpetas: list[Path] = []
    try:
        if adjunto is not None:
            fila_sop = crear_sop_en_cola(
                session, settings.media_path, adjunto.datos, adjunto.extension
            )
            carpetas.append(carpeta_sop(settings.media_path, fila_sop.id))
            sop_id = fila_sop.id
        video = Video(
            titulo=titulo, archivo="", modo=modo, idioma=idioma, sop_id=sop_id, proceso=EN_COLA
        )
        session.add(video)
        session.flush()  # asigna el id
        relativa = PurePosixPath("videos", str(video.id), f"video{extension}")
        destino = settings.media_path / relativa
        carpetas.append(destino.parent)
        _copiar(archivo.file, destino, settings.subida_max_bytes)
        video.archivo = str(relativa)
        session.commit()
    except BaseException as exc:
        session.rollback()
        for carpeta in carpetas:
            shutil.rmtree(carpeta, ignore_errors=True)
        if isinstance(exc, _TamanoExcedido):
            raise HTTPException(413, _detalle_tamano(settings)) from None
        raise
    # El parámetro del video gana sobre la instalación, en los dos sentidos (ADR-024).
    imagenes = settings.fotogramas_describir if analizar_imagenes is None else analizar_imagenes
    logger.info(
        "Video %d recibido (%s, %.1f MB%s%s)",
        video.id,
        extension,
        destino.stat().st_size / 1e6,
        f", SOP adjunto {sop_id} {adjunto.extension}" if adjunto is not None else "",
        ", con imágenes" if imagenes else "",
    )

    if adjunto is not None:  # antes que el video, que lo espera
        assert sop_id is not None
        procesador.encolar_sop(sop_id, fabrica_llm, AjustesConversion.desde_settings(settings))
    procesador.encolar(video.id, idioma, transcriptor, validacion, imagenes=imagenes)
    response.headers["Location"] = f"/videos/{video.id}"
    return VideoCreado(id=video.id, proceso=video.proceso, sop_id=sop_id)


@router.get("/videos/estimacion", response_model=EstimacionImagenes)
def estimar_imagenes(
    duracion_s: Annotated[float, Query(gt=0, description="Duración del video en segundos")],
    modo: Annotated[Literal["validar", "generar"], Query(description="validar | generar")],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    plan: Annotated[PlanDispositivos, Depends(get_plan_dispositivos)],
    llm: Annotated[ClienteLLM, Depends(get_cliente_llm)],
    sop_id: Annotated[int | None, Query(description="SOP de referencia (modo validar)")] = None,
) -> EstimacionImagenes:
    """Cuántas imágenes se describirían y cuánto tiempo sumarían, con y sin GPU (ADR-024).

    N es la misma que usaría el procesamiento: los pasos del SOP (si `sop_id` ya está listo) o la
    duración por `PASOS_POR_MIN`, entre `FOTOGRAMAS_MIN` y `FOTOGRAMAS_MAX`. Va declarada antes de
    `/videos/{video_id}`. 404 si el SOP no existe; nunca prohíbe describir, solo informa.
    """
    if not math.isfinite(duracion_s):
        raise HTTPException(422, "duracion_s debe ser un número finito")
    pasos_sop = None
    if sop_id is not None:
        fila = session.get(Sop, sop_id)
        if fila is None:
            raise HTTPException(404, "SOP no encontrado")
        if fila.estado == SOP_LISTO and fila.contenido:
            pasos_sop = len(SOP.model_validate(fila.contenido).pasos)
    n = cuantas_imagenes(modo, pasos_sop, duracion_s, settings)
    extra_gpu = round(n * settings.seg_imagen_gpu, 1)
    extra_cpu = round(n * settings.seg_imagen_cpu, 1)
    dispositivo, supuesto = dispositivo_llm_probable(
        settings.llm_dispositivo,
        plan.gpu,
        lambda: llm.dispositivo_cargado(timeout_s=settings.llm_health_timeout_s),
    )
    return EstimacionImagenes(
        imagenes_estimadas=n,
        segundos_extra_gpu=extra_gpu,
        segundos_extra_cpu=extra_cpu,
        dispositivo=dispositivo,
        dispositivo_supuesto=supuesto,
        aviso=_aviso_estimacion(n, dispositivo, supuesto, extra_gpu, extra_cpu),
    )


def _aviso_estimacion(
    n: int, dispositivo: str, supuesto: bool, extra_gpu: float, extra_cpu: float
) -> str:
    """El texto para la pantalla: cuánto sumaría describir las `n` imágenes."""
    describir = f"describir {n} imágenes sumará"
    if supuesto:
        return (
            f"No se pudo saber si hay GPU: {describir} {_duracion(extra_gpu)} con GPU o "
            f"{_duracion(extra_cpu)} sin ella."
        )
    if dispositivo == "gpu":
        return f"Con GPU: {describir} {_duracion(extra_gpu)}."
    return f"Sin GPU: {describir} {_duracion(extra_cpu)}."


def _duracion(segundos: float) -> str:
    """'~40 s' o '~4 min', redondeado para leerse de un vistazo."""
    if segundos < 90:
        return f"~{max(round(segundos), 1)} s"
    return f"~{round(segundos / 60)} min"


@router.post("/videos/{video_id}/validar", status_code=202, response_model=VideoCreado)
def revalidar_video(
    video_id: int,
    session: Annotated[Session, Depends(get_session)],
    procesador: Annotated[Procesador, Depends(get_procesador)],
    validacion: Annotated[FabricaValidacion, Depends(get_validacion)],
    continuar: Annotated[
        bool,
        Query(description="true: no detenerse por afinidad baja (quien carga ya la vio)"),
    ] = False,
    segmentar: Annotated[
        bool,
        Query(description="true: volver a segmentar con Gemma en lugar de reusar los pasos"),
    ] = False,
) -> VideoCreado:
    """Repite solo la validación con la transcripción guardada (ADR-019).

    Se acepta en "listo", "error" y "afinidad_baja". Con `continuar=true` no se detiene por
    afinidad baja (ADR-020) y el reporte lleva la afinidad con `bajo_umbral=true`. Reusa los
    pasos del video guardados (RNF-07: mismo porcentaje; la redacción del juez puede variar);
    con `segmentar=true`
    los vuelve a pedir a Gemma. Si los guardados son de la heurística de respaldo o quedaron
    incompletos, siempre se vuelve a segmentar.
    """
    video = _buscar(session, video_id)
    if video.modo != "validar":
        raise HTTPException(422, "solo un video de modo validar tiene validación")
    if video.proceso in (EN_COLA, PROCESANDO):
        raise HTTPException(409, {"mensaje": "el video está en proceso", "proceso": video.proceso})
    if video.transcripcion is None:
        raise HTTPException(409, "el video no tiene análisis guardado: vuelve a subirlo")
    video.proceso, video.error = EN_COLA, None
    session.commit()
    procesador.revalidar(video.id, validacion, continuar=continuar, segmentar=segmentar)
    return VideoCreado(id=video.id, proceso=video.proceso)


@router.post("/videos/{video_id}/generar", status_code=202, response_model=VideoCreado)
def regenerar_video(
    video_id: int,
    session: Annotated[Session, Depends(get_session)],
    procesador: Annotated[Procesador, Depends(get_procesador)],
    validacion: Annotated[FabricaValidacion, Depends(get_validacion)],
    segmentar: Annotated[
        bool,
        Query(description="true: volver a segmentar con Gemma en lugar de reusar los pasos"),
    ] = False,
) -> VideoCreado:
    """Repite la generación del SOP con la transcripción guardada, sin Whisper (ADR-023,
    criterio de ADR-019).

    Reusa la ficha de contexto y los pasos del video guardados (RNF-07); con `segmentar=true` los
    pasos se vuelven a pedir a Gemma (una segmentación de la heurística o incompleta siempre se
    repite). Reescribe el SOP generado del video, salvo que ya esté en la biblioteca: entonces
    crea uno nuevo. Se acepta en "listo" y "error"; 422 si el video no es de modo generar, 409 si
    está en proceso o no tiene análisis guardado.
    """
    video = _buscar(session, video_id)
    if video.modo != "generar":
        raise HTTPException(422, "solo un video de modo generar genera un SOP")
    if video.proceso in (EN_COLA, PROCESANDO):
        raise HTTPException(409, {"mensaje": "el video está en proceso", "proceso": video.proceso})
    if video.transcripcion is None:
        raise HTTPException(409, "el video no tiene análisis guardado: vuelve a subirlo")
    video.proceso, video.error = EN_COLA, None
    session.commit()
    procesador.regenerar(video.id, validacion, segmentar=segmentar)
    return VideoCreado(id=video.id, proceso=video.proceso, sop_id=video.sop_id)


@router.get("/videos/{video_id}/sop", response_model=SOP)
def sop_generado(video_id: int, session: Annotated[Session, Depends(get_session)]) -> SOP:
    """El SOP generado desde el video (modo generar, RF-22 a RF-25). 409 mientras no esté listo
    (con el proceso del video y el estado del SOP); 422 si el video es de modo validar. Sus
    advertencias, si quedó incompleto, y cómo se generó: `GET /sops/{sop_id}`."""
    video = _buscar(session, video_id)
    if video.modo != "generar":
        raise HTTPException(422, "el video es de modo validar: su SOP es el de referencia")
    fila = session.get(Sop, video.sop_id) if video.sop_id is not None else None
    if fila is None or fila.estado != SOP_LISTO:
        raise HTTPException(
            409,
            {
                "mensaje": "el SOP generado no está listo",
                "proceso": video.proceso,
                "estado": fila.estado if fila is not None else None,
                "error": video.error or (fila.error if fila is not None else None),
            },
        )
    return SOP.model_validate(fila.contenido)


@router.get("/videos/{video_id}", response_model=EstadoVideo)
def estado_video(video_id: int, session: Annotated[Session, Depends(get_session)]) -> EstadoVideo:
    video = _buscar(session, video_id)
    estado = EstadoVideo.model_validate(video, from_attributes=True)
    return estado.model_copy(update={"afinidad": _afinidad(video)})


def _afinidad(video: Video) -> Afinidad | None:
    """La afinidad guardada en el reporte (de la detención o del reporte de pasos), o None. La
    `DetencionAfinidad` y el `ResultadoValidacion` la llevan en la misma clave."""
    reporte = video.reporte
    if video.proceso not in (LISTO, AFINIDAD_BAJA) or reporte is None:
        return None
    datos = (reporte.resultado or {}).get("afinidad")
    return None if datos is None else Afinidad.model_validate(datos)


@router.get("/videos/{video_id}/transcripcion.txt")
def transcripcion_txt(
    video_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """El TXT tal como va (RF-10): vacío si la transcripción todavía no empieza."""
    video = _buscar(session, video_id)
    ruta = settings.media_path / "videos" / str(video.id) / ARCHIVO_TXT
    contenido = ruta.read_bytes() if ruta.is_file() else b""
    return Response(
        content=contenido,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="transcripcion-{video.id}.txt"'},
    )


@router.get("/videos/{video_id}/video", response_class=FileResponse)
def archivo_video(
    video_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    """El archivo del video para el reproductor del reporte (RF-20), en cualquier estado.

    `FileResponse` de Starlette atiende `Range` (206 con `Content-Range`, 416 si el rango no
    cabe) y anuncia `Accept-Ranges: bytes`, así que el navegador puede saltar al segundo de cada
    hallazgo. La ruta sale de la fila, nunca de la petición.
    """
    video = _buscar(session, video_id)
    ruta = settings.media_path / video.archivo
    if not video.archivo or not ruta.is_file():
        raise HTTPException(404, {"mensaje": "el archivo del video no está en disco"})
    tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
    return FileResponse(ruta, media_type=tipo)


@router.get("/videos/{video_id}/thumb", response_class=FileResponse)
def miniatura_video(
    video_id: int,
    t: Annotated[float, Query(description="Segundo del video, p. ej. 12.5")],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    """La miniatura del segundo `t` (RF-11, ADR-024): solo ffmpeg, sin modelo.

    Si hay una guardada a ≤ 1 s (RNF-03) la devuelve; si no, la saca y la deja en
    `media/videos/<id>/miniaturas/` como caché. 404 si el video no existe o no tiene imagen
    visible (sin pista de video o negro); 400 si `t` está fuera de la duración. La imagen de un
    segundo no cambia: va con `Cache-Control` de un día. La ruta sale de la fila, nunca de la
    petición.
    """
    video = _buscar(session, video_id)
    archivo = settings.media_path / video.archivo
    if not video.archivo or not archivo.is_file():
        raise HTTPException(404, {"mensaje": "el archivo del video no está en disco"})
    carpeta = miniaturas.carpeta_miniaturas(archivo.parent)
    if miniaturas.sin_imagen_marcado(carpeta):
        raise HTTPException(404, {"mensaje": "el video no tiene imagen"})
    try:
        total = video.duracion if video.duracion is not None else duracion(archivo)
    except ErrorMedios:
        raise HTTPException(404, {"mensaje": "el video no se pudo leer"}) from None
    if not math.isfinite(t) or t < 0 or t > total:
        raise HTTPException(400, f"t debe estar entre 0 y {total:g} s")
    ruta = miniaturas.buscar(carpeta, t)
    if ruta is None:
        try:
            # La primera vez (un video procesado antes de las miniaturas) se revisa que tenga
            # imagen visible; después basta con que tenga pista de video.
            primera = not carpeta.is_dir() or not any(carpeta.glob("t*.jpg"))
            visible = imagen_visible(archivo, total) if primera else tiene_imagen(archivo)
            if not visible:
                miniaturas.marcar_sin_imagen(carpeta)
                raise HTTPException(404, {"mensaje": "el video no tiene imagen"})
            ruta = miniaturas.asegurar(archivo, carpeta, t, total, settings.miniatura_lado_px)
        except ErrorMedios as exc:
            logger.warning("Video %d: miniatura en %.1f s sin generar (%s)", video_id, t, exc)
            raise HTTPException(404, {"mensaje": "no se pudo sacar la miniatura"}) from None
    return FileResponse(ruta, media_type="image/jpeg", headers={"Cache-Control": CACHE_MINIATURA})


@router.get("/videos/{video_id}/analisis", response_model=Analisis)
def analisis_video(video_id: int, session: Annotated[Session, Depends(get_session)]) -> Analisis:
    video = _buscar(session, video_id)
    if video.proceso != LISTO:
        raise HTTPException(
            409, {"mensaje": "el análisis no ha terminado", "proceso": video.proceso}
        )
    return leer_analisis(video)


@router.get("/videos/{video_id}/contexto", response_model=Contexto)
def contexto_video(video_id: int, session: Annotated[Session, Depends(get_session)]) -> Contexto:
    """Ficha de contexto (RF-12): 409 mientras no se genere.

    Se genera en los dos modos, después de la transcripción. Queda sin generar si el video sigue
    en proceso, si Ollama falló (en modo validar el reporte lo dice con el aviso
    "contexto_sin_generar"; `POST /videos/{id}/validar` la vuelve a intentar) o si el video se
    procesó antes de que existiera la ficha.
    """
    video = _buscar(session, video_id)
    if video.contexto is None:
        raise HTTPException(
            409, {"mensaje": "la ficha de contexto no se ha generado", "proceso": video.proceso}
        )
    return Contexto.model_validate(video.contexto)


@router.get("/videos/{video_id}/reporte", response_model=ReporteValidacion)
def reporte_video(
    video_id: int, session: Annotated[Session, Depends(get_session)]
) -> ReporteValidacion:
    """Reporte de validación (RF-14, RF-19, base de RF-20): 409 si no está listo."""
    video = _buscar(session, video_id)
    if video.proceso != LISTO:
        raise HTTPException(409, {"mensaje": "el reporte no está listo", "proceso": video.proceso})
    reporte = video.reporte
    if reporte is None:
        raise HTTPException(404, "el video no tiene reporte")
    return armar_reporte(
        ResultadoValidacion.model_validate(reporte.resultado),
        SOP.model_validate(reporte.sop.contenido),
        video_id=video.id,
        sop_id=reporte.sop_id,
        codigo=reporte.sop.codigo,
        cumplimiento=float(reporte.cumplimiento),
        creado=reporte.creado,
    )


def _buscar(session: Session, video_id: int) -> Video:
    video = session.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "video no encontrado")
    return video


class _TamanoExcedido(Exception):  # noqa: N818 (nombre de dominio)
    pass


def _copiar(origen: BinaryIO, destino: Path, limite: int) -> None:
    """Copia por bloques sin cargar el archivo en memoria; falla si pasa de `limite` bytes."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destino.open("wb") as salida:
        while bloque := origen.read(BLOQUE):
            total += len(bloque)
            if total > limite:
                raise _TamanoExcedido
            salida.write(bloque)


def _detalle_tamano(settings: Settings) -> str:
    return f"el video pasa del límite de {settings.subida_max_mb} MB"
