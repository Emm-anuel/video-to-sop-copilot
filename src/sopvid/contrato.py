"""Contrato entre el pipeline de video y la extracción de pasos del video (RF-13).

`Analisis` es el JSON que produce el pipeline de video: idioma, transcripción con tiempo por
palabra y fotogramas descritos. `PasoVideo` es cada paso que la extracción obtiene de él. Todo
tiempo de este contrato sale de la transcripción o del video, nunca del LLM (regla 4 de
CLAUDE.md).

Reglas comunes: campos extra prohibidos, tiempos finitos y ≥ 0, fin ≥ inicio, y las listas
vacías se escriben `[]`, nunca `null`. Los mensajes de error solo citan ids y tiempos, nunca
texto de la transcripción (puede ser material del cliente).

El JSON Schema de `Analisis` se exporta a docs/contrato/analisis.schema.json con
`python scripts/exportar_contrato.py`; no se edita a mano.
"""

from itertools import pairwise
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

URI_JSON_SCHEMA = "https://json-schema.org/draft/2020-12/schema"

Tiempo = Annotated[float, Field(ge=0, description="Segundos desde el inicio del video.")]
# De dónde sale la evidencia de un paso y qué tan sólida es (RNF-06).
Fuente = Literal["audio", "visual", "inferido"]
Confianza = Literal["alta", "media", "baja"]


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _verificar_rango(inicio: float, fin: float) -> None:
    if fin < inicio:
        raise ValueError(f"t_fin ({fin}) es menor que el inicio ({inicio})")


class Idioma(_Modelo):
    codigo: str = Field(min_length=1, description="Código ISO 639-1, p. ej. 'es'.")
    confianza: float = Field(ge=0, le=1)
    fijado_a_mano: bool = False


class Palabra(_Modelo):
    w: str
    t: Tiempo
    t_fin: Tiempo

    @model_validator(mode="after")
    def _rango(self) -> Self:
        _verificar_rango(self.t, self.t_fin)
        return self


class Segmento(_Modelo):
    id: int
    t_inicio: Tiempo
    t_fin: Tiempo
    texto: str
    palabras: list[Palabra] = []

    @model_validator(mode="after")
    def _rango(self) -> Self:
        _verificar_rango(self.t_inicio, self.t_fin)
        for a, b in pairwise(self.palabras):
            if b.t < a.t:
                raise ValueError(f"segmento {self.id}: palabras fuera de orden ({a.t} → {b.t})")
        return self


class Fotograma(_Modelo):
    t: Tiempo
    archivo: str
    descripcion: str
    equipos: list[str] = []
    personas: int = Field(default=0, ge=0)
    texto_visible: list[str] = []
    riesgos: list[str] = []


class Analisis(_Modelo):
    """Salida del pipeline de video y entrada de la extracción de pasos."""

    version_contrato: Literal[1] = 1
    video_id: int
    duracion_s: Tiempo
    idioma: Idioma
    transcripcion: list[Segmento]
    fotogramas: list[Fotograma] = []

    @model_validator(mode="after")
    def _transcripcion_ordenada(self) -> Self:
        """Ids estrictamente crecientes (sin duplicados) y segmentos sin solaparse."""
        for a, b in pairwise(self.transcripcion):
            if b.id == a.id:
                raise ValueError(f"id de segmento duplicado: {b.id}")
            if b.id < a.id:
                raise ValueError(f"ids de segmento no crecientes: {a.id} → {b.id}")
            if b.t_inicio < a.t_fin:
                raise ValueError(
                    f"el segmento {b.id} empieza ({b.t_inicio}) antes de que termine "
                    f"el {a.id} ({a.t_fin})"
                )
        return self


class PasoVideo(_Modelo):
    """Paso extraído del video. Tiempos y cita salen de la transcripción, no del LLM."""

    numero: int = Field(ge=1)
    nombre: str = Field(min_length=1)
    descripcion: str
    responsable: str
    t_inicio: Tiempo
    t_fin: Tiempo
    cita: str
    fuente: Fuente
    confianza: Confianza

    @model_validator(mode="after")
    def _rango(self) -> Self:
        _verificar_rango(self.t_inicio, self.t_fin)
        return self


def esquema_analisis() -> dict[str, Any]:
    """JSON Schema (draft 2020-12) de `Analisis`, tal como se exporta a docs/contrato/."""
    return {"$schema": URI_JSON_SCHEMA, **Analisis.model_json_schema()}
