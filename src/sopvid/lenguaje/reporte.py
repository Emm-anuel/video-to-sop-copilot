"""Reporte de validación de un video contra un SOP (RF-14, RF-19, RF-20).

Junta lo que devuelve `emparejar` en lo que ve el usuario: una fila por paso —del SOP o del
video— con su estado, su cita y su segundo, el porcentaje de cumplimiento y el semáforo.

El porcentaje y el semáforo son los del documento SOP V1.0, sección 5.6:

- **Cumple** vale 1; **Cumple o Parcial fuera de orden** y **Parcial** valen 0.5; **Falta**,
  **Sobra** y **zona_gris** valen 0. Los *Sobra* no restan.
- El denominador es el número de pasos del SOP, así que un video que se salta pasos no puede
  compensarlos con pasos de más.
- Semáforo: verde desde 90 %, amarillo desde 70 %, rojo por debajo.

Ningún tiempo se calcula aquí: `t_inicio` y `t_fin` de cada fila son los del paso del video
(regla 4 de CLAUDE.md). El reporte no guarda texto fuera de lo que ya trae la transcripción (la
cita) y el SOP; los mensajes de error del modelo, si los hubiera, solo citan números.

Lo usan `plataforma.validacion` (al terminar el análisis) y `scripts/diagnosticar_emparejamiento.py`
(que comparte `porcentaje` y `semaforo` para que el diagnóstico y el producto midan igual).
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sopvid.contrato import (
    ESTADOS,
    SOP,
    Confianza,
    EstadoPaso,
    MarcoOperador,
    ResultadoEmparejamiento,
    ResumenClasificacion,
)

Semaforo = Literal["verde", "amarillo", "rojo"]
# Umbrales de la sección 5.6 del documento SOP V1.0.
UMBRAL_VERDE = 90.0
UMBRAL_AMARILLO = 70.0


class _Modelo(BaseModel):
    """Base del reporte, con las mismas reglas que los contratos de `sopvid.contrato`."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def porcentaje(resultado: ResultadoEmparejamiento, n_sop: int) -> float:
    """(Cumple + 0.5 × (Parcial + fuera de orden)) / pasos del SOP × 100.

    Fuera de orden es una marca: un Cumple o Parcial marcado cuenta 0.5 una sola vez. Los Sobra
    no restan; Falta y los zona_gris (con o sin respaldo) cuentan 0.
    """
    if n_sop <= 0:
        return 0.0
    puntos = 0.0
    for paso in resultado.clasificacion.pasos:
        if paso.estado == "Cumple":
            puntos += 0.5 if paso.fuera_de_orden else 1.0
        elif paso.estado == "Parcial":
            puntos += 0.5
    return 100 * puntos / n_sop


def semaforo(pct: float) -> Semaforo:
    """Verde desde 90 %, amarillo desde 70 %, rojo por debajo (sección 5.6)."""
    if pct >= UMBRAL_VERDE:
        return "verde"
    return "amarillo" if pct >= UMBRAL_AMARILLO else "rojo"


class OrigenPasos(_Modelo):
    """Cómo se extrajeron los pasos del video (RF-13), para la trazabilidad del reporte (RNF-06).

    `metodo` es "llm" si Gemma 4 propuso las fronteras y "heuristica" si se usó el respaldo;
    `modelo` es el nombre del modelo en el primer caso y `pasos` cuántos se obtuvieron.
    """

    metodo: Literal["llm", "heuristica"]
    modelo: str | None = None
    pasos: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _modelo_solo_con_llm(self) -> Self:
        if self.metodo == "heuristica" and self.modelo is not None:
            raise ValueError("la heurística no lleva modelo")
        return self


class FilaReporte(_Modelo):
    """Un renglón de la tabla del reporte (RF-20): estado, cita y segundo.

    `orden` es la posición en la tabla: primero los pasos del SOP en su orden y después los
    *Sobra* en el orden del video (el mismo que `Clasificacion`). `paso_sop` y `paso_video` son
    los números que ve el usuario (desde 1); un *Falta* no tiene paso del video y un *Sobra* no
    tiene paso del SOP.

    `t_inicio` y `t_fin` son el tramo del video que sostiene el hallazgo (el paso del video, ya
    fusionado), para que el reproductor salte al segundo; `justificacion` es la del juez de la
    zona gris y va vacía si el par no pasó por él.
    """

    orden: Annotated[int, Field(ge=1)]
    estado: EstadoPaso
    nombre: str
    paso_sop: Annotated[int, Field(ge=1)] | None = None
    paso_video: Annotated[int, Field(ge=1)] | None = None
    t_inicio: Annotated[float, Field(ge=0)] | None = None
    t_fin: Annotated[float, Field(ge=0)] | None = None
    cita: str = ""
    confianza: Confianza | None = None
    similitud: Annotated[float, Field(ge=-1, le=1)] | None = None
    fuera_de_orden: bool = False
    marco_operador: MarcoOperador | None = None
    justificacion: str = ""

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        if self.marco_operador is not None and self.estado != "Sobra":
            raise ValueError(f"{self.estado}: solo un Sobra lleva marco_operador")
        if self.fuera_de_orden and self.estado not in ("Cumple", "Parcial", "zona_gris"):
            raise ValueError(f"{self.estado}: no puede ir fuera de orden")
        con_sop, con_video = self.estado != "Sobra", self.estado != "Falta"
        if (self.paso_sop is not None) != con_sop or (self.paso_video is not None) != con_video:
            raise ValueError(
                f"{self.estado}: índices incompatibles "
                f"(paso_sop={self.paso_sop}, paso_video={self.paso_video})"
            )
        if not con_video:
            if self.t_inicio is not None or self.t_fin is not None:
                raise ValueError("Falta: sin paso del video no hay tiempos")
        elif self.t_inicio is None:
            raise ValueError(f"{self.estado}: el paso del video lleva t_inicio")
        if self.t_inicio is not None and self.t_fin is not None and self.t_fin < self.t_inicio:
            raise ValueError(f"t_fin ({self.t_fin}) es menor que t_inicio ({self.t_inicio})")
        return self


class Reporte(_Modelo):
    """Reporte de validación: cabecera (porcentaje, semáforo, conteo) y filas (RF-19, RF-20).

    `cumplimiento` va redondeado a dos decimales, que es lo que guarda `reportes.cumplimiento`
    (`Numeric(5,2)`) y lo que se muestra. `resumen` es el de la clasificación, tal cual: trae el
    conteo por estado, los pares, los que fueron al juez y sus segundos. `faltan` y `sobran`
    listan números de paso para el resumen de arriba de la tabla.

    `sop_id` queda en `None` mientras el reporte no se guarda (el ORM lo conoce).
    """

    version_contrato: Literal[1] = 1
    video_id: int
    sop_id: int | None = None
    sop_titulo: str
    cumplimiento: Annotated[float, Field(ge=0, le=100)]
    semaforo: Semaforo
    resumen: ResumenClasificacion
    faltan: list[int] = []
    sobran: list[int] = []
    filas: list[FilaReporte]
    pasos_del_video: OrigenPasos

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        if self.semaforo != semaforo(self.cumplimiento):
            raise ValueError(f"semaforo ({self.semaforo}) no corresponde a {self.cumplimiento} %")
        esperadas = sum(self.resumen.conteo.values()) + self.resumen.marco_operador
        if len(self.filas) != esperadas:
            raise ValueError(f"{len(self.filas)} filas para {esperadas} pasos contados")
        if [f.orden for f in self.filas] != list(range(1, len(self.filas) + 1)):
            raise ValueError("las filas van numeradas 1, 2, 3… en el orden de la tabla")
        if not set(self.resumen.conteo) == set(ESTADOS):
            raise ValueError("el resumen no trae todos los estados")
        return self


def armar_reporte(
    video_id: int,
    sop: SOP,
    resultado: ResultadoEmparejamiento,
    origen: OrigenPasos,
    *,
    sop_id: int | None = None,
) -> Reporte:
    """Arma el `Reporte` de un `emparejar` ya hecho, con el porcentaje y el semáforo de la 5.6.

    Las filas salen en el orden de `resultado.clasificacion.pasos`; el nombre del paso es el del
    SOP, o el del video cuando es un *Sobra*. `faltan` y `sobran` llevan los números de paso (los
    que ve el usuario, desde 1) de los *Falta* y los *Sobra* sin `marco_operador`; la intro y el
    cierre del operador (ADR-016) no se cuentan como Sobra, pero sí aparecen como fila.
    """
    filas: list[FilaReporte] = []
    faltan: list[int] = []
    sobran: list[int] = []
    for orden, paso in enumerate(resultado.clasificacion.pasos, start=1):
        de_sop = sop.pasos[paso.indice_sop] if paso.indice_sop is not None else None
        de_video = (
            resultado.pasos_video[paso.indice_video] if paso.indice_video is not None else None
        )
        if paso.estado == "Falta" and de_sop is not None:
            faltan.append(de_sop.numero)
        if paso.estado == "Sobra" and de_video is not None and paso.marco_operador is None:
            sobran.append(de_video.numero)
        filas.append(
            FilaReporte(
                orden=orden,
                estado=paso.estado,
                nombre=(de_sop or de_video).nombre,
                paso_sop=de_sop.numero if de_sop is not None else None,
                paso_video=de_video.numero if de_video is not None else None,
                t_inicio=de_video.t_inicio if de_video is not None else None,
                t_fin=de_video.t_fin if de_video is not None else None,
                cita=paso.cita,
                confianza=paso.confianza,
                similitud=paso.similitud,
                fuera_de_orden=paso.fuera_de_orden,
                marco_operador=paso.marco_operador,
                justificacion=paso.juicio.justificacion if paso.juicio is not None else "",
            )
        )
    pct = round(porcentaje(resultado, len(sop.pasos)), 2)
    return Reporte(
        video_id=video_id,
        sop_id=sop_id,
        sop_titulo=sop.titulo,
        cumplimiento=pct,
        semaforo=semaforo(pct),
        resumen=resultado.clasificacion.resumen,
        faltan=faltan,
        sobran=sobran,
        filas=filas,
        pasos_del_video=origen,
    )
