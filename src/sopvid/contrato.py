"""Contratos del pipeline: análisis del video, pasos del video (RF-13) y SOP (RF-03).

`Analisis` es el JSON que produce el pipeline de video: idioma, transcripción con tiempo por
palabra y fotogramas descritos. `PasoVideo` es cada paso que la extracción obtiene de él;
`Fusion` registra qué pasos del video se unieron antes de emparejar (ADR-013).

`SOP` es el esquema de la sección 10 del documento SOP V1.0, con tres diferencias deliberadas:
lleva `version_contrato`, `t_inicio`/`t_fin` de cada paso pueden ser `None` (un SOP cargado no
tiene tiempos; los llena el SOP generado desde el video) y todo el resumen tiene valores por
defecto, para que un SOP mínimo (título y pasos) valide.

Todo tiempo de estos contratos sale de la transcripción o del video, nunca del LLM (regla 4 de
CLAUDE.md). Reglas comunes: campos extra prohibidos, tiempos finitos y ≥ 0, fin ≥ inicio, y las
listas vacías se escriben `[]`, nunca `null`. Los mensajes de error solo citan ids, números de
paso y tiempos, nunca texto de la transcripción ni del SOP (puede ser material del cliente).

Los JSON Schema se exportan a docs/contrato/ (analisis.schema.json y sop.schema.json) con
`python scripts/exportar_contrato.py`; no se editan a mano.
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


class Fusion(_Modelo):
    """Registro de un paso del video tras la fusión (ADR-013): qué pasos originales lo forman.

    Hay uno por paso fusionado; si `originales` tiene un solo número, el paso no se unió con
    nada. `citas` y `similitudes` van en el orden de `originales`: la cita íntegra de cada
    original (la del paso fusionado las une en un solo texto) y su coseno con `paso_sop`.
    """

    numero: int = Field(ge=1, description="Número del paso fusionado.")
    originales: list[int] = Field(min_length=1, description="Números de los pasos originales.")
    paso_sop: int = Field(ge=1, description="Paso del SOP más parecido.")
    citas: list[str]
    similitudes: list[Annotated[float, Field(ge=-1, le=1)]]

    @model_validator(mode="after")
    def _listas_alineadas(self) -> Self:
        for a, b in pairwise(self.originales):
            if b <= a:
                raise ValueError(f"paso {self.numero}: originales no crecientes ({a} → {b})")
        n = len(self.originales)
        if len(self.citas) != n or len(self.similitudes) != n:
            raise ValueError(
                f"paso {self.numero}: {n} originales, {len(self.citas)} citas y "
                f"{len(self.similitudes)} similitudes"
            )
        return self


# ── SOP (sección 10 del documento SOP V1.0) ─────────────────────────────────────────────────

# A diferencia de `Fuente`, un dato del SOP también puede venir del documento cargado.
FuenteSOP = Literal["documento", "audio", "visual", "inferido"]


class Dato(_Modelo):
    """Dato del resumen con su evidencia: de dónde sale, qué tan sólido es y en qué segundo."""

    valor: str | None = None
    confianza: Confianza = "alta"
    fuente: FuenteSOP = "documento"
    t: Tiempo | None = None


class Elemento(_Modelo):
    """Equipo de operación o rol del SOP."""

    nombre: str = Field(min_length=1)
    descripcion: str = ""


class Riesgo(_Modelo):
    descripcion: str
    nivel: Literal["alto", "medio", "bajo"]
    paso: int | None = None
    control: str = ""


class Falla(_Modelo):
    situacion: str
    accion: str


class Resumen(_Modelo):
    objetivo: Dato = Dato()
    alcance: Dato = Dato()
    responsable: Dato = Dato()
    lugar: Dato = Dato()
    horario_frecuencia: Dato = Dato()
    duracion_total_min: float | None = Field(default=None, ge=0)
    equipo_operacion: list[Elemento] = []
    roles: list[Elemento] = []
    riesgos: list[Riesgo] = []
    en_caso_de_falla: list[Falla] = []


class PasoSOP(_Modelo):
    """Paso del SOP. Sin tiempos si el SOP se cargó; con tiempos si se generó desde el video."""

    numero: int = Field(ge=1)
    nombre: str = Field(min_length=1)
    descripcion: str = ""
    responsable: str
    equipo: list[str] = []
    puntos_validacion: list[str] = []
    tiempo_esperado_min: float | None = Field(default=None, ge=0)
    t_inicio: Tiempo | None = None
    t_fin: Tiempo | None = None
    confianza: Confianza = "alta"
    campos_inferidos: list[str] = []

    @model_validator(mode="after")
    def _rango(self) -> Self:
        if self.t_inicio is not None and self.t_fin is not None:
            _verificar_rango(self.t_inicio, self.t_fin)
        return self


class PuntoClave(_Modelo):
    texto: str
    t: Tiempo | None = None


class PalabraClave(_Modelo):
    termino: str
    categoria: Literal["equipo", "accion", "seguridad", "calidad", "lugar", "material", "otro"]


class SOP(_Modelo):
    """SOP de referencia (cargado) o generado desde el video."""

    version_contrato: Literal[1] = 1
    titulo: str = Field(min_length=1)
    resumen: Resumen = Resumen()
    pasos: list[PasoSOP] = Field(min_length=1)
    puntos_clave: list[PuntoClave] = []
    palabras_clave: list[PalabraClave] = []

    @model_validator(mode="after")
    def _pasos_numerados(self) -> Self:
        """Los pasos se numeran 1, 2, 3… en el orden en que aparecen."""
        for esperado, paso in enumerate(self.pasos, start=1):
            if paso.numero != esperado:
                raise ValueError(
                    f"numeración de pasos: se esperaba el paso {esperado} y llegó el {paso.numero}"
                )
        return self


def esquema_analisis() -> dict[str, Any]:
    """JSON Schema (draft 2020-12) de `Analisis`, tal como se exporta a docs/contrato/."""
    return {"$schema": URI_JSON_SCHEMA, **Analisis.model_json_schema()}


def esquema_sop() -> dict[str, Any]:
    """JSON Schema (draft 2020-12) de `SOP`, tal como se exporta a docs/contrato/."""
    return {"$schema": URI_JSON_SCHEMA, **SOP.model_json_schema()}
