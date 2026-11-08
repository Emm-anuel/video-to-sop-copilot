"""Validación de un video contra un SOP: ficha de contexto → afinidad → pasos del video →
emparejamiento → porcentaje.

Corre después del análisis (transcripción) y no toca la base: `validar` recibe el `Analisis` y el
SOP y devuelve la ficha de contexto (RF-12), los pasos del video y el `ResultadoValidacion` que se
guarda en `reportes` (RF-13, RF-14, RF-19).

La ficha de contexto va primero, en la misma ventana de Gemma que los pasos y el juez (una sola
carga del modelo, ADR-014). Nunca ve el SOP (regla 5). Si ya hay una guardada (repetir solo la
validación, ADR-019), se reusa sin llamar al modelo. Si queda vacía (`generar_contexto` no lanza),
la validación sigue y el reporte lleva el aviso "contexto_sin_generar".

Después del emparejamiento, ya sin Gemma, los roles del SOP y el responsable de cada paso
emparejado (RF-15, ADR-020; `lenguaje/personas.py`) y los tiempos: la duración de cada par, el
total y el horario (RF-16, ADR-021; `lenguaje/tiempos.py`, solo código y MiniLM). Con la ficha
se calcula la afinidad de contexto (RF-17, ADR-020; MiniLM, sin LLM). Si queda bajo
`AFINIDAD_MIN` y no se pidió `continuar`, la validación se detiene ahí, antes de segmentar:
`validar` devuelve una `Detenida` y el procesador deja el video en "afinidad_baja" hasta que
quien carga decida. Sin ficha no hay afinidad y la validación sigue.

Whisper ya soltó la memoria al terminar de transcribir (ADR-014). Antes de segmentar se revisa
que Ollama responda y tenga el modelo; si no, `LLMNoDisponible` y el procesador deja el video en
error reprocesable (ADR-019). Si Ollama se cae después, `segmentar` cae a la heurística y el juez
deja los pares en zona_gris: el reporte se guarda con avisos y queda provisional. Al terminar la
etapa del LLM, con o sin error, se pregunta a Ollama dónde tenía el modelo (GPU o CPU,
ADR-018) y se le pide que lo suelte (`ClienteLLM.descargar`).

Las dependencias se inyectan (RNF-14): el LLM, el juez y el embedder. Los umbrales y los cortes
del semáforo salen de la configuración, la misma que usa `emparejar`. Los logs y los avisos solo
llevan conteos y motivos, nunca texto del video ni del SOP.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Self

from sopvid.contrato import (
    SOP,
    Analisis,
    Aviso,
    Contexto,
    DetencionAfinidad,
    Dispositivo,
    Dispositivos,
    MetadatosValidacion,
    PasoVideo,
    ResultadoEmparejamiento,
    ResultadoValidacion,
    Umbrales,
)
from sopvid.lenguaje.afinidad import afinidad
from sopvid.lenguaje.emparejamiento import Embedder, emparejar, get_embedder
from sopvid.lenguaje.juez import Juez, JuezGemma
from sopvid.lenguaje.llm import ClienteLLM, LLMNoDisponible
from sopvid.lenguaje.personas import (
    ComparadorRoles,
    asignar_responsables,
    emparejar_roles,
    roles_del_sop,
)
from sopvid.lenguaje.reporte import porcentaje, semaforo
from sopvid.lenguaje.tiempos import comparar_horario, tiempo_total, tiempos_por_paso
from sopvid.percepcion.contexto import ResultadoContexto, aviso_contexto, generar_contexto
from sopvid.percepcion.segmentacion import Segmentacion, segmentar
from sopvid.percepcion.transcripcion import aviso_transcripcion
from sopvid.plataforma.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Avance global con que empieza cada etapa de la validación. El análisis ocupa de 0 a 40 (lo
# escala el procesador) y "listo" (100) llega con el reporte guardado.
INICIO_ETAPA = {"contexto": 40, "segmentacion": 50, "emparejamiento": 80, "reporte": 95}

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
    """`pasos_video` son los de `segmentar`, antes de fusionar (van a `videos.pasos_video`).

    `contexto` es la ficha con que se validó: la generada aquí o la que se pasó. Con
    `resultado_contexto` en None se reusó la guardada; si no, dice si se generó (y entonces va a
    `videos.contexto`) o por qué quedó vacía.
    """

    pasos_video: list[PasoVideo]
    resultado: ResultadoValidacion
    contexto: Contexto = field(default_factory=Contexto)
    resultado_contexto: ResultadoContexto | None = None


@dataclass(frozen=True)
class Detenida:
    """La validación se detuvo por afinidad baja (ADR-020), antes de segmentar.

    `detencion` va a `reportes.resultado`; `contexto` y `resultado_contexto`, como en
    `Validacion` (la ficha se guarda si se generó aquí).
    """

    detencion: DetencionAfinidad
    contexto: Contexto
    resultado_contexto: ResultadoContexto | None = None


def validar(
    analisis: Analisis,
    sop: SOP,
    deps: DependenciasValidacion,
    *,
    al_avanzar: AlAvanzar | None = None,
    segundos_analisis: Mapping[str, float] | None = None,
    dispositivos: Dispositivos | None = None,
    contexto: Contexto | None = None,
    continuar: bool = False,
    reloj: Callable[[], float] = time.perf_counter,
) -> Validacion | Detenida:
    """Genera la ficha de contexto, calcula la afinidad, segmenta, empareja (con el juez) y
    calcula el porcentaje y el semáforo.

    Con `contexto` (la ficha guardada) no se vuelve a generar. Si la afinidad queda bajo
    `AFINIDAD_MIN`, devuelve una `Detenida` sin segmentar, salvo con `continuar` (quien carga ya
    vio la advertencia): entonces sigue y el reporte lleva la afinidad con `bajo_umbral`.

    `segundos_analisis` (duracion, audio, transcripcion) se copia a los metadatos junto con los
    de esta etapa (incluida "afinidad"). `dispositivos`
    trae la GPU y dónde corrió Whisper; aquí se completa con dónde corrió Gemma. Errores:
    `LLMNoDisponible` si Ollama no responde antes de empezar; los demás salen tal cual.
    """
    settings = get_settings()
    if not deps.llm.disponible(settings.llm_health_timeout_s):
        raise LLMNoDisponible(
            f"Ollama no responde en {deps.llm.base_url} o no tiene el modelo {deps.llm.modelo}"
        )
    avanzar = al_avanzar or (lambda etapa, pct: None)
    embedder = deps.embedder or get_embedder()
    segundos = dict(segundos_analisis or {})
    llm_en: Dispositivo = "desconocido"
    resultado_contexto: ResultadoContexto | None = None
    detencion: DetencionAfinidad | None = None
    try:
        # Cuando existan los fotogramas (RF-11), su descripción con Gemma va antes de la ficha,
        # en esta misma ventana: la ficha los usa como evidencia.
        if contexto is None:
            avanzar("contexto", INICIO_ETAPA["contexto"])
            inicio = reloj()
            resultado_contexto = generar_contexto(analisis, deps.llm)
            segundos["contexto"] = reloj() - inicio
            contexto = resultado_contexto.contexto

        inicio = reloj()
        con_ficha = resultado_contexto is None or resultado_contexto.generado
        afinidad_video = afinidad(sop, contexto if con_ficha else None, embedder, settings)
        segundos["afinidad"] = reloj() - inicio
        if afinidad_video is not None and afinidad_video.bajo_umbral and not continuar:
            aviso = aviso_transcripcion(analisis)
            detencion = DetencionAfinidad(
                afinidad=afinidad_video,
                umbrales=umbrales_de(settings),
                embedder=embedder.modelo,
                segundos={etapa: round(s, 2) for etapa, s in segundos.items()},
                avisos=[aviso] if aviso else [],
            )
            # El `finally` descarga Gemma; los dispositivos se completan abajo.
            return Detenida(detencion, contexto, resultado_contexto)

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
        # Antes de descargar: después Ollama ya no lo lista.
        llm_en = deps.llm.dispositivo_cargado()
        deps.llm.descargar()
        if detencion is not None:
            # El objeto es inmutable para quien lo recibe, pero aquí todavía no salió de la
            # función: se completa con dónde corrió Gemma.
            detencion.dispositivos = (dispositivos or Dispositivos()).model_copy(
                update={"llm": llm_en}
            )
            logger.info(
                "Validación del video %d detenida: afinidad %d < %s",
                analisis.video_id,
                detencion.afinidad.valor,
                settings.afinidad_min,
            )

    avanzar("reporte", INICIO_ETAPA["reporte"])
    # Personas (RF-15, ADR-020): MiniLM y código, con Gemma ya descargado.
    inicio = reloj()
    personas = contexto.personas if con_ficha else []
    comparador = ComparadorRoles(embedder, settings)
    roles = emparejar_roles(
        roles_del_sop(sop),
        personas,
        responsables=[p.responsable for p in sop.pasos],
        comparador=comparador,
    )
    responsables = asignar_responsables(
        resultado,
        sop,
        contexto if con_ficha else None,
        analisis.transcripcion,
        segmentacion.pasos,
        comparador=comparador,
    )
    segundos["personas"] = reloj() - inicio
    # Tiempos (RF-16, ADR-021): código sobre la transcripción; MiniLM solo para el horario.
    inicio = reloj()
    tiempos = tiempos_por_paso(resultado, sop, analisis.transcripcion, settings.tolerancia_tiempo)
    total = tiempo_total(tiempos, sop, settings.tolerancia_tiempo)
    horario = comparar_horario(
        sop,
        contexto if con_ficha else None,
        analisis.transcripcion,
        embedder,
        settings.umbral_horario,
    )
    segundos["tiempos"] = reloj() - inicio
    pct = porcentaje(resultado)
    avisos = avisos_de(segmentacion, resultado, resultado_contexto, analisis)
    metadatos = MetadatosValidacion(
        segmentacion=segmentacion.metodo,
        motivo_respaldo=segmentacion.motivo_respaldo,
        modelo_llm=segmentacion.modelo,
        embedder=embedder.modelo,
        umbrales=umbrales_de(settings),
        segundos={etapa: round(s, 2) for etapa, s in segundos.items()},
        avisos=avisos,
        dispositivos=(dispositivos or Dispositivos()).model_copy(update={"llm": llm_en}),
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
            afinidad=afinidad_video,
            roles=roles,
            responsables=responsables,
            tiempos=tiempos,
            tiempo_total=total,
            horario=horario,
        ),
        contexto=contexto,
        resultado_contexto=resultado_contexto,
    )


def umbrales_de(settings: Settings) -> Umbrales:
    """Los umbrales de la configuración que se registran en el reporte (RNF-14)."""
    return Umbrales(
        bajo=settings.umbral_bajo,
        alto=settings.umbral_alto,
        fusion=settings.umbral_fusion,
        semaforo_verde=settings.semaforo_verde,
        semaforo_amarillo=settings.semaforo_amarillo,
        afinidad_min=settings.afinidad_min,
        tolerancia_tiempo=settings.tolerancia_tiempo,
        umbral_rol=settings.umbral_rol,
        afinidad_cos_cero=settings.afinidad_cos_cero,
        afinidad_cos_cien=settings.afinidad_cos_cien,
        afinidad_umbral_equipo=settings.afinidad_umbral_equipo,
        umbral_rol_complemento=settings.umbral_rol_complemento,
        umbral_horario=settings.umbral_horario,
    )


def avisos_de(
    segmentacion: Segmentacion,
    resultado: ResultadoEmparejamiento,
    resultado_contexto: ResultadoContexto | None = None,
    analisis: Analisis | None = None,
) -> list[Aviso]:
    """Lo que vuelve provisional al reporte (ADR-019), en el orden de las etapas: Whisper que no
    es el de referencia (ADR-018) y las fallas del LLM. Sin `resultado_contexto` (ficha
    reusada), no hay aviso de la ficha."""
    avisos = []
    if analisis is not None and (aviso := aviso_transcripcion(analisis)):
        avisos.append(aviso)
    if resultado_contexto is not None and (aviso := aviso_contexto(resultado_contexto)):
        avisos.append(aviso)
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
