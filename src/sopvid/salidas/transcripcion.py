"""TXT, SRT y nombre del archivo de la transcripción para descargar (RF-31).

Reciben los segmentos guardados del `Analisis`: los de `resegmentar` (frases y pausas armadas con
las palabras de Whisper), no las ventanas crudas del TXT en vivo. Tiempos y textos salen tal cual
de la transcripción (regla 4); el código solo les da formato y, en el SRT, recorta el fin de un
segmento que se encima con el siguiente.
"""

from collections.abc import Iterable

from sopvid.contrato import Segmento
from sopvid.percepcion.transcripcion import linea_txt
from sopvid.texto import normalizar

LARGO_NOMBRE_MAX = 80  # caracteres del nombre sin la extensión


def txt(segmentos: Iterable[Segmento]) -> str:
    """La transcripción completa en el formato del TXT en vivo: `[mm:ss] texto` por línea."""
    return "".join(linea_txt(s) for s in segmentos)


def tiempo_srt(segundos: float) -> str:
    """`HH:MM:SS,mmm`, redondeado al milisegundo."""
    return _formato_ms(_ms(segundos))


def srt(segmentos: Iterable[Segmento]) -> str:
    """Subtítulos SubRip: un bloque por segmento con texto, numerados desde 1.

    Los segmentos sin texto no se escriben (y no gastan número). El texto va en una línea, con
    los espacios y saltos colapsados: un salto doble partiría el bloque. Fin ≥ inicio y sin
    solaparse: si un segmento empieza antes de que termine el anterior, el fin del anterior se
    recorta a ese inicio. "" si no hay ningún segmento con texto.
    """
    bloques = [
        (_ms(s.t_inicio), _ms(s.t_fin), texto)
        for s in segmentos
        if (texto := " ".join(s.texto.split()))
    ]
    bloques.sort(key=lambda b: b[0])  # estable: los que empiezan igual conservan su orden
    salida = []
    for i, (inicio, fin, texto) in enumerate(bloques):
        if i + 1 < len(bloques):
            fin = min(fin, bloques[i + 1][0])
        salida.append(f"{i + 1}\n{_formato_ms(inicio)} --> {_formato_ms(fin)}\n{texto}\n")
    return "\n".join(salida)


def nombre_archivo(titulo: str, extension: str, respaldo: str) -> str:
    """`titulo` en minúsculas, sin acentos (ñ → n) ni signos, con `_` entre palabras, más la
    extensión: "Cambio de filtro: línea 3" → "cambio_de_filtro_linea_3.srt". Solo ASCII, así
    que va tal cual en `Content-Disposition`. Si del título no queda nada, `respaldo`."""
    base = "_".join(normalizar(titulo).split())[:LARGO_NOMBRE_MAX].strip("_")
    return f"{base or respaldo}.{extension}"


def _ms(segundos: float) -> int:
    return max(0, round(segundos * 1000))


def _formato_ms(ms: int) -> str:
    horas, resto = divmod(ms, 3_600_000)
    minutos, resto = divmod(resto, 60_000)
    segundos, milis = divmod(resto, 1000)
    return f"{horas:02d}:{minutos:02d}:{segundos:02d},{milis:03d}"
