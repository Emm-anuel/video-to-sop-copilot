"""Índice de la búsqueda exacta (RF-32, RF-33): las palabras de un video publicado en `palabras`.

Publicar un video arma una fila por palabra de su transcripción, en el orden en que se dijo:

- `posicion` es consecutiva en **todo el video** (0, 1, 2…), no por segmento: una frase que cruza
  de un segmento al siguiente se encuentra igual.
- `palabra_normalizada` sale de `texto.forma_busqueda`, la misma función por la que pasa la
  consulta (sin acentos ni mayúsculas, sin signos, plural simple). No hay otra normalización.
- `palabra_original` es la palabra como la escribió Whisper (con acentos y signos), para mostrar
  la frase; `t_inicio` y `t_fin` son los suyos, sin redondear (RNF-03, regla 4 de CLAUDE.md).
- Una palabra de Whisper que da varios tokens al normalizar ("11:30" → "11" "30", "O-rings" →
  "o" "ring") da una fila por token, con posiciones seguidas y el mismo tiempo y original.
- Una palabra que queda vacía al normalizar (solo signos, "%", "°", un emoji, otra escritura) no
  se indexa ni gasta posición. Como la consulta pierde los mismos símbolos, una frase sigue
  coincidiendo: "50 % de carga" se busca como "50 de carga" y la encuentra, y "A — B" coincide con
  "A B". Lo que no se puede es buscar el símbolo solo.
- Un segmento sin tiempos por palabra (análisis viejos; hoy Whisper siempre los da) indexa los
  tokens de su texto con el inicio y el fin del segmento: ahí el segundo puede quedar a más de
  1 s de la palabra (RNF-03 no se garantiza).

`indexar` y `desindexar` no hacen commit: quien llama junta el índice y las columnas del video
(`publicar`, `despublicar`) en una sola transacción. Con `PUBLICAR_AL_TERMINAR=true`, el
trabajador publica cada video al quedar listo (`publicar_al_terminar`).
"""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from sopvid.contrato import Analisis, EstadoPublicacion
from sopvid.plataforma.modelos import Palabra, Video
from sopvid.plataforma.procesamiento import leer_analisis
from sopvid.texto import forma_busqueda

logger = logging.getLogger(__name__)

LARGO_PALABRA = 100  # `palabras.palabra_normalizada` y `palabra_original` son String(100)


@dataclass(frozen=True)
class PalabraIndice:
    """Una fila del índice, sin el video."""

    posicion: int
    palabra_normalizada: str
    palabra_original: str
    t_inicio: float
    t_fin: float


def palabras_indexables(analisis: Analisis) -> list[PalabraIndice]:
    """Las filas del índice de un análisis, en orden y con posiciones 0..n-1 (ver el módulo)."""
    crudas: list[tuple[str, float, float]] = []
    for segmento in analisis.transcripcion:
        if segmento.palabras:
            crudas += [(p.w, p.t, p.t_fin) for p in segmento.palabras]
        else:
            crudas += [(w, segmento.t_inicio, segmento.t_fin) for w in segmento.texto.split()]
    filas: list[PalabraIndice] = []
    for palabra, t_inicio, t_fin in crudas:
        original = palabra.strip()[:LARGO_PALABRA]
        for token in forma_busqueda(original).split():
            filas.append(
                PalabraIndice(len(filas), token[:LARGO_PALABRA], original, t_inicio, t_fin)
            )
    return filas


def indexar(session: Session, video: Video) -> int:
    """Reemplaza las palabras de `video` en el índice por las de su transcripción guardada, en
    bloque. Devuelve cuántas filas quedaron. No hace commit."""
    filas = palabras_indexables(leer_analisis(video))
    desindexar(session, video)
    if filas:
        session.execute(insert(Palabra), [{"video_id": video.id, **asdict(f)} for f in filas])
    return len(filas)


def desindexar(session: Session, video: Video) -> int:
    """Borra las palabras de `video` del índice. Devuelve cuántas había. No hace commit."""
    return session.execute(delete(Palabra).where(Palabra.video_id == video.id)).rowcount


def contar(session: Session, video: Video) -> int:
    """Cuántas palabras tiene `video` en el índice."""
    consulta = select(func.count()).select_from(Palabra).where(Palabra.video_id == video.id)
    return session.scalar(consulta) or 0


def publicar(session: Session, video: Video, ahora: datetime) -> EstadoPublicacion:
    """Indexa `video` y lo marca publicado en `ahora` (otra vez: reemplaza el índice y pone la
    fecha al día). Quien llama revisa que el análisis esté terminado y hace commit."""
    n = indexar(session, video)
    video.publicado, video.publicado_en = True, ahora
    return EstadoPublicacion(
        video_id=video.id, publicado=True, publicado_en=ahora, palabras_indexadas=n
    )


def despublicar(session: Session, video: Video) -> EstadoPublicacion:
    """Quita `video` del índice y lo marca sin publicar. Quien llama hace commit."""
    desindexar(session, video)
    video.publicado, video.publicado_en = False, None
    return EstadoPublicacion(video_id=video.id, publicado=False, palabras_indexadas=0)


def publicar_al_terminar(session: Session, video_id: int) -> None:
    """Gancho del trabajador con `PUBLICAR_AL_TERMINAR=true`: publica el video que acaba de
    quedar listo, salvo que ya estuviera publicado (repetir la validación no toca la
    transcripción). Hace commit."""
    video = session.get(Video, video_id, with_for_update=True)
    if video is None or video.publicado:
        return
    estado = publicar(session, video, datetime.now(UTC))
    session.commit()
    logger.info("Video %d publicado al terminar: %d palabras", video_id, estado.palabras_indexadas)
