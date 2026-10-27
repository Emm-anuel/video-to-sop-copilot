"""Validación de un video contra un SOP: pasos del video → emparejamiento → porcentaje.

Corre después del análisis (transcripción) y no toca la base: `validar` recibe el `Analisis` y el
SOP y devuelve los pasos del video y el `ResultadoValidacion` que se guarda en `reportes`
(RF-13, RF-14, RF-19).

Whisper ya soltó la memoria al terminar de transcribir (ADR-014). Antes de segmentar se revisa
que Ollama responda y tenga el modelo; si no, `LLMNoDisponible` y el procesador deja el video en
error reprocesable (ADR-017). Si Ollama se cae después, `segmentar` cae a la heurística y el juez
deja los pares en zona_gris: el reporte se guarda con avisos y queda provisional. Al terminar la
etapa del LLM, con o sin error, se pide a Ollama que suelte el modelo (`ClienteLLM.descargar`).

Las dependencias se inyectan (RNF-14): el LLM, el juez y el embedder. Los umbrales y los cortes
del semáforo salen de la configuración, la misma que usa `emparejar`. Los logs y los avisos solo
llevan conteos y motivos, nunca texto del video ni del SOP.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Self

from sopvid.contrato import (
    SOP,
    Analisis,
    Aviso,
    MetadatosValidacion,
    PasoVideo,
    ResultadoEmparejamiento,
    ResultadoValidacion,
    Umbrales,
)
from sopvid.lenguaje.emparejamiento import Embedder, emparejar, get_embedder
from sopvid.lenguaje.juez import Juez, JuezGemma
from sopvid.lenguaje.llm import ClienteLLM, LLMNoDisponible
from sopvid.lenguaje.reporte import porcentaje, semaforo
from sopvid.percepcion.segmentacion import Segmentacion, segmentar
from sopvid.plataforma.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Avance global con que empieza cada etapa de la validación. El análisis ocupa de 0 a 45 (lo
# escala el procesador) y "listo" (100) llega con el reporte guardado.
INICIO_ETAPA = {"segmentacion": 45, "emparejamiento": 80, "reporte": 95}

AlAvanzar = Callable[[str, int], None]


@dataclass
class DependenciasValidacion:
    """Lo que la validación necesita de fuera. Sin `embedder`, el del proceso (MiniLM en CPU)."""

    llm: ClienteLLM
    juez: Juez
    embedder: Embedder | None = None

    @classmethod
    def desde_settings(cls, settings: Settings | None = None) -> Self:
        """Gemma 4 por Ollama (LLM_*) para segmentar y para el juez de la zona gris."""
        llm = ClienteLLM.desde_settings(settings)
        return cls(llm, JuezGemma(llm))

    def cerrar(self) -> None:
        self.llm.close()


# La API inyecta una fábrica: las dependencias se crean en el hilo del trabajo, solo si el video
# es de modo validar, y el procesador las cierra al terminar.
FabricaValidacion = Callable[[], DependenciasValidacion]


@dataclass(frozen=True)
class Validacion:
    """`pasos_video` son los de `segmentar`, antes de fusionar (van a `videos.pasos_video`)."""

    pasos_video: list[PasoVideo]
    resultado: ResultadoValidacion


def validar(
    analisis: Analisis,
    sop: SOP,
    deps: DependenciasValidacion,
    *,
    al_avanzar: AlAvanzar | None = None,
    segundos_analisis: Mapping[str, float] | None = None,
    reloj: Callable[[], float] = time.perf_counter,
) -> Validacion:
    """Segmenta, empareja (con el juez) y calcula el porcentaje y el semáforo.

    `segundos_analisis` (duracion, audio, transcripcion) se copia a los metadatos junto con los
    de esta etapa. Errores: `LLMNoDisponible` si Ollama no responde antes de empezar; los demás
    salen tal cual.
    """
    settings = get_settings()
    if not deps.llm.disponible(settings.llm_health_timeout_s):
        raise LLMNoDisponible(
            f"Ollama no responde en {deps.llm.base_url} o no tiene el modelo {deps.llm.modelo}"
        )
    avanzar = al_avanzar or (lambda etapa, pct: None)
    embedder = deps.embedder or get_embedder()
    segundos = dict(segundos_analisis or {})
    try:
        avanzar("segmentacion", INICIO_ETAPA["segmentacion"])
        inicio = reloj()
        segmentacion = segmentar(analisis, deps.llm)
        segundos["segmentacion"] = reloj() - inicio

        avanzar("emparejamiento", INICIO_ETAPA["emparejamiento"])
        inicio = reloj()
        # Sin transcripción no hay pasos ni narración que leer: el juez no hace falta.
        juez = deps.juez if analisis.transcripcion else None
        resultado = emparejar(
            sop,
            segmentacion.pasos,
            embedder,
            juez=juez,
            transcripcion=analisis.transcripcion,
        )
        segundos["emparejamiento"] = reloj() - inicio
    finally:
        deps.llm.descargar()

    avanzar("reporte", INICIO_ETAPA["reporte"])
    pct = porcentaje(resultado)
    avisos = avisos_de(segmentacion, resultado)
    metadatos = MetadatosValidacion(
        segmentacion=segmentacion.metodo,
        motivo_respaldo=segmentacion.motivo_respaldo,
        modelo_llm=segmentacion.modelo,
        embedder=embedder.modelo,
        umbrales=Umbrales(
            bajo=settings.umbral_bajo,
            alto=settings.umbral_alto,
            fusion=settings.umbral_fusion,
            semaforo_verde=settings.semaforo_verde,
            semaforo_amarillo=settings.semaforo_amarillo,
        ),
        segundos={etapa: round(s, 2) for etapa, s in segundos.items()},
        avisos=avisos,
    )
    conteo = resultado.clasificacion.resumen.conteo
    logger.info(
        "Validación del video %d: %.1f %% (%s), %s%s",
        analisis.video_id,
        pct,
        semaforo(pct, settings),
        ", ".join(f"{e} {n}" for e, n in conteo.items() if n),
        f"; provisional ({', '.join(a.tipo for a in avisos)})" if avisos else "",
    )
    return Validacion(
        pasos_video=segmentacion.pasos,
        resultado=ResultadoValidacion(
            resultado=resultado,
            cumplimiento=pct,
            semaforo=semaforo(pct, settings),
            metadatos=metadatos,
        ),
    )


def avisos_de(segmentacion: Segmentacion, resultado: ResultadoEmparejamiento) -> list[Aviso]:
    """Las fallas del LLM que vuelven provisional al reporte (ADR-017)."""
    avisos = []
    if segmentacion.metodo == "heuristica":
        avisos.append(
            Aviso(
                tipo="segmentacion_heuristica",
                detalle=f"pasos del video con la heurística de respaldo: "
                f"{segmentacion.motivo_respaldo}",
            )
        )
    if segmentacion.pasos_sin_redactar:
        avisos.append(
            Aviso(
                tipo="pasos_sin_redactar",
                detalle=f"{segmentacion.pasos_sin_redactar} pasos del video sin cita ni "
                f"descripción: {segmentacion.motivo_sin_redaccion}",
            )
        )
    sin_revisar = [p for p in resultado.clasificacion.pasos if p.estado == "zona_gris"]
    if sin_revisar:
        motivos = Counter(
            (p.juicio.motivo if p.juicio else None) or "sin juez" for p in sin_revisar
        )
        avisos.append(
            Aviso(
                tipo="juez_sin_revisar",
                detalle=f"{len(sin_revisar)} pares de la zona gris sin revisar ("
                + ", ".join(f"{m}: {n}" for m, n in sorted(motivos.items()))
                + ")",
            )
        )
    return avisos
