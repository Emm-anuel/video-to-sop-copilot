"""Porcentaje de cumplimiento y semáforo del reporte de validación (RF-19, SOP V1.0 §5.6).

`porcentaje` puntúa cada paso del SOP según su estado tras `emparejar`: Cumple vale 1; Parcial,
0.5; un Cumple o un Parcial con la marca de fuera de orden, 0.5 una sola vez (la marca no se
suma a la penalización del Parcial). Falta y zona_gris ("sin revisar") valen 0. Los Sobra no
restan, tampoco los marcados como intro o cierre del operador (ADR-016). `semaforo` traduce el
porcentaje a verde, amarillo o rojo con los cortes de la configuración (RNF-14).

`armar_reporte` arma la respuesta de `GET /videos/{id}/reporte` (`ReporteValidacion`) a partir
de lo guardado (`ResultadoValidacion`) y del SOP: una fila por resultado, con el nombre del paso
del SOP y del video, el segundo y la cita (siempre de la transcripción, regla 4). La afinidad,
los roles y el responsable de cada par (RF-15, RF-17, ADR-020) se copian de lo guardado, igual
que el tiempo de cada par, el total y el horario (RF-16, ADR-021). Un reporte guardado antes de
ADR-020 sale con la afinidad en None, sin roles ni responsables; uno anterior a ADR-021, sin
tiempos.
"""

from datetime import datetime

from sopvid.contrato import (
    SOP,
    ConteoReporte,
    FilaReporte,
    PasoSOPReporte,
    ReporteValidacion,
    ResultadoEmparejamiento,
    ResultadoValidacion,
    Semaforo,
    SOPReporte,
)
from sopvid.plataforma.config import Settings, get_settings


def porcentaje(resultado: ResultadoEmparejamiento) -> float:
    """(Cumple + 0.5 × (Parcial + Fuera de orden)) / pasos del SOP × 100, sin redondear.

    Los pasos del SOP se cuentan desde la clasificación: un resultado por paso, con `indice_sop`
    de 0 a n-1 sin repetir. Si no es así (incluido un SOP sin pasos), `ValueError`. Se calcula
    `100 * puntos / n` en ese orden: los puntos son múltiplos de 0.5, así que un 90 o un 70
    exactos salen exactos en flotante y el semáforo no cambia de color por redondeo.
    """
    pasos_sop = [p for p in resultado.clasificacion.pasos if p.indice_sop is not None]
    n = len(pasos_sop)
    if n == 0:
        raise ValueError("la clasificación no tiene pasos del SOP")
    indices = sorted(p.indice_sop for p in pasos_sop if p.indice_sop is not None)
    if indices != list(range(n)):
        raise ValueError(
            f"los indice_sop de la clasificación deben ser 0..{n - 1} sin repetir "
            f"(llegaron {indices})"
        )
    puntos = 0.0
    for p in pasos_sop:
        if p.estado == "Cumple":
            puntos += 0.5 if p.fuera_de_orden else 1.0
        elif p.estado == "Parcial":
            puntos += 0.5
    return 100 * puntos / n


def semaforo(pct: float, settings: Settings | None = None) -> Semaforo:
    """Verde si `pct` ≥ SEMAFORO_VERDE; amarillo si ≥ SEMAFORO_AMARILLO; rojo si no.

    `pct` es el porcentaje sin redondear que devuelve `porcentaje`, nunca el valor guardado en
    `reportes.cumplimiento` (Numeric(5,2)): con 89.996 el semáforo es amarillo aunque la columna
    guarde 90.00. Sin `settings`, usa `get_settings()`.
    """
    settings = settings or get_settings()
    if pct >= settings.semaforo_verde:
        return "verde"
    if pct >= settings.semaforo_amarillo:
        return "amarillo"
    return "rojo"


def armar_reporte(
    validacion: ResultadoValidacion,
    sop: SOP,
    *,
    video_id: int,
    sop_id: int,
    codigo: str,
    cumplimiento: float,
    creado: datetime,
) -> ReporteValidacion:
    """La respuesta de la API con lo guardado. `cumplimiento` es el de la columna (dos decimales).

    Las filas siguen el orden de la clasificación: primero los pasos del SOP y después los Sobra,
    en el orden del video. El conteo sale del resumen de la clasificación, más las personas con
    diferencias (§5.6, ADR-020) y los pasos que exceden su tiempo (ADR-021).
    """
    resultado = validacion.resultado
    n = len(resultado.clasificacion.pasos)
    responsables = validacion.responsables or [None] * n
    tiempos = validacion.tiempos or [None] * n
    filas = []
    for paso, responsable, tiempo in zip(
        resultado.clasificacion.pasos, responsables, tiempos, strict=True
    ):
        video = None if paso.indice_video is None else resultado.pasos_video[paso.indice_video]
        del_sop = None if paso.indice_sop is None else sop.pasos[paso.indice_sop]
        juicio = paso.juicio
        filas.append(
            FilaReporte(
                estado=paso.estado,
                paso_sop=None if del_sop is None else del_sop.numero,
                nombre_sop=None if del_sop is None else del_sop.nombre,
                paso_video=None if video is None else video.numero,
                nombre_video=None if video is None else video.nombre,
                t_inicio=paso.t_inicio,
                cita=paso.cita,
                confianza=paso.confianza,
                fuera_de_orden=paso.fuera_de_orden,
                marco_operador=paso.marco_operador,
                justificacion=juicio.justificacion if juicio and juicio.justificacion else None,
                responsable=responsable,
                tiempo=tiempo,
            )
        )
    resumen = resultado.clasificacion.resumen
    conteo = ConteoReporte(
        cumple=resumen.conteo["Cumple"],
        parcial=resumen.conteo["Parcial"],
        fuera_de_orden=resumen.fuera_de_orden,
        falta=resumen.conteo["Falta"],
        sobra=resumen.conteo["Sobra"],
        sin_revisar=resumen.conteo["zona_gris"],
        marco_operador=resumen.marco_operador,
        # §5.6: responsables distintos más roles ausentes que son responsables de algún paso.
        personas_con_diferencias=(
            sum(f.responsable is not None and f.responsable.estado == "distinto" for f in filas)
            + sum(r.estado == "ausente" and r.con_pasos for r in validacion.roles)
        ),
        # ADR-021: solo "excede"; "menor" es más rápido de lo esperado, no un incumplimiento.
        pasos_fuera_de_tiempo=sum(
            f.tiempo is not None and f.tiempo.estado == "excede" for f in filas
        ),
    )
    return ReporteValidacion(
        video_id=video_id,
        sop=SOPReporte(
            id=sop_id,
            codigo=codigo,
            titulo=sop.titulo,
            pasos=[
                PasoSOPReporte(numero=p.numero, nombre=p.nombre, descripcion=p.descripcion)
                for p in sop.pasos
            ],
        ),
        cumplimiento=cumplimiento,
        semaforo=validacion.semaforo,
        provisional=bool(validacion.metadatos.avisos),
        afinidad=validacion.afinidad,
        conteo=conteo,
        filas=filas,
        roles=validacion.roles,
        tiempo_total=validacion.tiempo_total,
        horario=validacion.horario,
        metadatos=validacion.metadatos,
        creado=creado,
    )
