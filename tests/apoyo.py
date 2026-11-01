"""Apoyo de las pruebas: arma a mano un `ResultadoEmparejamiento`.

`emparejar` necesita MiniLM (470 MB de pesos la primera vez) y, con juez, Ollama. Las pruebas del
reporte y del endpoint no quieren ninguna de las dos cosas, así que estas funciones construyen la
misma estructura que devuelve `emparejar`, ya coherente con el contrato, a partir de los estados
que pida cada prueba. Los pasos son inventados, como el resto de `tests/`: nada del cliente.
"""

from sopvid.contrato import (
    ESTADOS,
    SOP,
    Clasificacion,
    Fusion,
    PasoSOP,
    PasoVideo,
    ResultadoEmparejamiento,
    ResultadoPaso,
    ResumenClasificacion,
)

CITAS = (
    "Primero preparo el filtro nuevo.",
    "Después cierro la válvula de entrada.",
    "Al final anoto la lectura del manómetro.",
)


def sop_de_prueba(
    nombres: tuple[str, ...] = ("Preparar el filtro", "Cerrar la válvula", "Anotar la lectura"),
) -> SOP:
    """Un SOP de tres pasos (o los que se pidan), con el responsable obligatorio."""
    return SOP(
        titulo="Cambio de filtro de agua",
        pasos=[
            PasoSOP(numero=numero, nombre=nombre, responsable="Operador")
            for numero, nombre in enumerate(nombres, start=1)
        ],
    )


def pasos_del_video(citas: tuple[str, ...] = CITAS) -> list[PasoVideo]:
    """Un paso del video por cita, de 5 s cada uno, con el tiempo que va al reporte."""
    return [
        PasoVideo(
            numero=numero,
            nombre=cita.split()[0].rstrip(".,"),
            descripcion=cita,
            responsable="Operador",
            t_inicio=(numero - 1) * 5.0,
            t_fin=numero * 5.0,
            cita=cita,
            fuente="audio",
            confianza="alta",
        )
        for numero, cita in enumerate(citas, start=1)
    ]


def fila(
    estado: str,
    *,
    sop: int | None = None,
    video: int | None = None,
    pasos_video: list[PasoVideo],
    similitud: float | None = 0.9,
    fuera_de_orden: bool = False,
    posiciones: tuple[int, int] | None = None,
    juicio=None,
    marco_operador: str | None = None,
) -> ResultadoPaso:
    """Un `ResultadoPaso` con el tiempo y la cita de su paso del video (índices desde 0).

    `sop` y `video` son índices; el tiempo y la cita se copian del paso del video, como exige el
    contrato. `posiciones` es (esperada, observada) y solo va con `fuera_de_orden`.
    """
    paso_video = pasos_video[video] if video is not None else None
    esperada, observada = posiciones if posiciones is not None else (None, None)
    return ResultadoPaso(
        estado=estado,
        indice_sop=sop,
        indice_video=video,
        similitud=similitud if paso_video is not None and sop is not None else None,
        t_inicio=paso_video.t_inicio if paso_video is not None else None,
        cita=paso_video.cita if paso_video is not None else "",
        confianza=paso_video.confianza if paso_video is not None else None,
        fuera_de_orden=fuera_de_orden,
        posicion_esperada=esperada,
        posicion_observada=observada,
        juicio=juicio,
        marco_operador=marco_operador,
    )


def resultado(
    sop: SOP, pasos_video: list[PasoVideo], filas: list[ResultadoPaso]
) -> ResultadoEmparejamiento:
    """Envuelve las filas en el `ResultadoEmparejamiento` que devolvería `emparejar`.

    El resumen se calcula aquí como lo hace `clasificar`: cuenta por estado sin los Sobra del
    marco del operador (ADR-016), y los pares son las filas con paso del SOP y del video.
    """
    conteo = {estado: 0 for estado in ESTADOS}
    for una in filas:
        if una.marco_operador is None:
            conteo[una.estado] += 1
    pares = sum(1 for una in filas if una.indice_sop is not None and una.indice_video is not None)
    pct = 100 * conteo["zona_gris"] / pares if pares else 0.0
    resumen = ResumenClasificacion(
        conteo=conteo,
        pares=pares,
        pares_llm=conteo["zona_gris"],
        pct_pares_llm=pct,
        fuera_de_orden=sum(1 for una in filas if una.fuera_de_orden),
        marco_operador=sum(1 for una in filas if una.marco_operador is not None),
    )
    fusiones = [
        Fusion(
            numero=paso.numero,
            originales=[paso.numero],
            paso_sop=1,
            citas=[paso.cita],
            similitudes=[0.9],
        )
        for paso in pasos_video
    ]
    return ResultadoEmparejamiento(
        clasificacion=Clasificacion(pasos=filas, resumen=resumen),
        fusiones=fusiones,
        pasos_video=pasos_video,
    )
