"""Contratos del pipeline: análisis del video, pasos del video (RF-13) y SOP (RF-03).

`Analisis` es el JSON que produce el pipeline de video: idioma, transcripción con tiempo por
palabra y fotogramas descritos. `PasoVideo` es cada paso que la extracción obtiene de él;
`Fusion` registra qué pasos del video se unieron antes de emparejar (ADR-013), `Par` es cada
pareja que elige el algoritmo húngaro (ADR-012), `Clasificacion` es el estado de cada paso tras
los umbrales de la cascada y la revisión del orden (`ResultadoPaso`) con su resumen, y
`ResultadoEmparejamiento` junta todo lo que devuelve `emparejar`.

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

import math
from itertools import pairwise
from typing import Annotated, Any, Literal, Self, get_args

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
    original (el paso fusionado conserva solo una, la del más parecido) y su coseno con
    `paso_sop`. `responsables_distintos` lista los responsables de los originales, en orden de
    aparición, cuando no coinciden (el paso fusionado se queda con el del más parecido); si
    coinciden, va vacía.
    """

    numero: int = Field(ge=1, description="Número del paso fusionado.")
    originales: list[int] = Field(min_length=1, description="Números de los pasos originales.")
    paso_sop: int = Field(ge=1, description="Paso del SOP más parecido.")
    citas: list[str]
    similitudes: list[Annotated[float, Field(ge=-1, le=1)]]
    responsables_distintos: list[str] = []

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
        distintos = self.responsables_distintos
        if distintos and (len(distintos) < 2 or len(set(distintos)) != len(distintos)):
            raise ValueError(
                f"paso {self.numero}: responsables_distintos debe ir vacía o tener dos o más "
                f"valores sin repetir (llegaron {len(distintos)})"
            )
        return self


class Par(_Modelo):
    """Pareja que elige el algoritmo húngaro (ADR-012): un paso del SOP con uno del video.

    Los índices son posiciones desde 0 en las listas que se emparejaron (filas y columnas de la
    matriz de similitud), no el `numero` de los pasos.
    """

    indice_sop: int = Field(ge=0)
    indice_video: int = Field(ge=0)
    similitud: float = Field(ge=-1, le=1, description="Coseno MiniLM entre los dos pasos.")


# ── Clasificación por umbrales (cascada, ADR-012) ────────────────────────────────────────────

# Estados del documento SOP V1.0 más "zona_gris", que es interno: un par con similitud entre
# UMBRAL_BAJO y UMBRAL_ALTO que espera al juez Gemma 4 (S4). El juez lo convertirá en Cumple,
# Parcial o en un Falta más un Sobra; ningún "zona_gris" debe llegar al reporte.
EstadoPaso = Literal["Cumple", "Parcial", "Falta", "Sobra", "zona_gris"]
ESTADOS: tuple[EstadoPaso, ...] = get_args(EstadoPaso)
# Los pares que revisa `orden` y los únicos que pueden llevar la marca de fuera de orden.
ESTADOS_CON_ORDEN: tuple[EstadoPaso, ...] = ("Cumple", "zona_gris")


class ResultadoPaso(_Modelo):
    """Estado de un paso del SOP o del video tras la cascada (ADR-012).

    Cumple, Parcial y zona_gris son un par: llevan los dos índices y la similitud. Falta es un
    paso del SOP sin pareja (o cuyo par se rompió por similitud baja): solo `indice_sop`. Sobra
    es un paso del video sin pareja: solo `indice_video`. Los índices son posiciones desde 0,
    como en `Par`; la similitud es la del par, así que un Falta o un Sobra no la llevan.

    `t_inicio`, `cita` y `confianza` salen del paso del video (regla 4: ningún tiempo nuevo); un
    Falta no tiene paso del video y los deja en `None`, `""` y `None`. Si la cita está vacía, la
    confianza es "baja".

    *Fuera de orden* es una marca, no un estado: un Cumple o un zona_gris puede estar fuera de
    orden a la vez (lo decide `orden`, con código; regla 5). Con la marca van
    `posicion_esperada` (lugar del paso en el SOP entre los pasos emparejados) y
    `posicion_observada` (lugar en el video entre los mismos), ambas desde 0; sin la marca, las
    dos quedan en `None`.
    """

    estado: EstadoPaso
    indice_sop: int | None = Field(default=None, ge=0)
    indice_video: int | None = Field(default=None, ge=0)
    similitud: float | None = Field(default=None, ge=-1, le=1)
    t_inicio: Tiempo | None = None
    cita: str = ""
    confianza: Confianza | None = None
    fuera_de_orden: bool = False
    posicion_esperada: int | None = Field(default=None, ge=0)
    posicion_observada: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _marca_de_orden(self) -> Self:
        if self.fuera_de_orden and self.estado not in ESTADOS_CON_ORDEN:
            raise ValueError(f"{self.estado}: solo Cumple y zona_gris pueden ir fuera de orden")
        posiciones = (self.posicion_esperada, self.posicion_observada)
        if self.fuera_de_orden:
            coherente = all(p is not None for p in posiciones)
        else:
            coherente = all(p is None for p in posiciones)
        if not coherente:
            raise ValueError(
                f"{self.estado}: las posiciones van si y solo si el paso está fuera de orden "
                f"(fuera_de_orden={self.fuera_de_orden}, esperada={self.posicion_esperada}, "
                f"observada={self.posicion_observada})"
            )
        return self

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        con_sop, con_video = self.estado != "Sobra", self.estado != "Falta"
        if (self.indice_sop is not None) != con_sop or (self.indice_video is not None) != con_video:
            raise ValueError(
                f"{self.estado}: índices incompatibles "
                f"(indice_sop={self.indice_sop}, indice_video={self.indice_video})"
            )
        if (self.similitud is not None) != (con_sop and con_video):
            raise ValueError(f"{self.estado}: la similitud solo va en un par")
        if not con_video:
            if self.t_inicio is not None or self.cita or self.confianza is not None:
                raise ValueError("Falta: sin paso del video no hay t_inicio, cita ni confianza")
        elif self.t_inicio is None or self.confianza is None:
            raise ValueError(f"{self.estado}: el paso del video lleva t_inicio y confianza")
        elif not self.cita.strip() and self.confianza != "baja":
            raise ValueError(f"{self.estado}: sin cita, la confianza es 'baja'")
        return self


class ResumenClasificacion(_Modelo):
    """Conteo por estado (todos, aunque sea 0) y cuántos pares irían a Gemma 4.

    `pares` son los que formó el algoritmo húngaro, incluidos los que se rompieron por similitud
    baja; `pares_llm`, los de zona gris; `pct_pares_llm` = 100 · pares_llm / pares (0 sin pares),
    la métrica del paper (ADR-012). La revisión de EPP y puntos de validación de los Cumple (S4)
    no cuenta aquí. `fuera_de_orden` cuenta aparte los pasos con esa marca (0 hasta que corre
    `orden`); no cambia el conteo por estado.
    """

    conteo: dict[EstadoPaso, Annotated[int, Field(ge=0)]]
    pares: int = Field(ge=0)
    pares_llm: int = Field(ge=0)
    pct_pares_llm: float = Field(ge=0, le=100)
    fuera_de_orden: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        if set(self.conteo) != set(ESTADOS):
            raise ValueError("el conteo lleva todos los estados, aunque sea en 0")
        if self.pares_llm != self.conteo["zona_gris"] or self.pares_llm > self.pares:
            raise ValueError(
                f"pares_llm ({self.pares_llm}) debe ser el conteo de zona_gris "
                f"({self.conteo['zona_gris']}) y no más que los pares ({self.pares})"
            )
        esperado = 100 * self.pares_llm / self.pares if self.pares else 0.0
        if not math.isclose(self.pct_pares_llm, esperado, abs_tol=1e-9):
            raise ValueError(f"pct_pares_llm ({self.pct_pares_llm}) no es {esperado}")
        return self


class Clasificacion(_Modelo):
    """Salida de `clasificar` y de `orden`: un resultado por paso y su resumen.

    Primero un resultado por paso del SOP, en su orden; después los Sobra, en el orden del video.
    """

    pasos: list[ResultadoPaso]
    resumen: ResumenClasificacion

    @model_validator(mode="after")
    def _resumen_coherente(self) -> Self:
        for estado in ESTADOS:
            n = sum(p.estado == estado for p in self.pasos)
            if self.resumen.conteo[estado] != n:
                raise ValueError(
                    f"el resumen cuenta {self.resumen.conteo[estado]} {estado} y hay {n}"
                )
        n = sum(p.fuera_de_orden for p in self.pasos)
        if self.resumen.fuera_de_orden != n:
            raise ValueError(
                f"el resumen cuenta {self.resumen.fuera_de_orden} fuera de orden y hay {n}"
            )
        return self


class ResultadoEmparejamiento(_Modelo):
    """Salida de `emparejar`: la clasificación con el orden revisado, el registro de la fusión y
    los pasos del video ya fusionados.

    Los `indice_video` de la clasificación apuntan a `pasos_video` (los fusionados, no los que
    llegaron), y hay un `Fusion` por cada uno, en el mismo orden. El tiempo y la cita de cada
    resultado son los de su paso del video (regla 4).
    """

    clasificacion: Clasificacion
    fusiones: list[Fusion]
    pasos_video: list[PasoVideo]

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        numeros = [p.numero for p in self.pasos_video]
        if [f.numero for f in self.fusiones] != numeros:
            raise ValueError(
                f"{len(self.fusiones)} registros de fusión para {len(numeros)} pasos del video, "
                "o con números distintos"
            )
        for paso in self.clasificacion.pasos:
            if paso.indice_video is None:
                continue
            if paso.indice_video >= len(self.pasos_video):
                raise ValueError(
                    f"indice_video {paso.indice_video} fuera de los {len(numeros)} pasos del video"
                )
            origen = self.pasos_video[paso.indice_video]
            if paso.t_inicio != origen.t_inicio or paso.cita != origen.cita:
                raise ValueError(
                    f"el resultado del paso del video {paso.indice_video} no lleva su tiempo "
                    "y su cita (regla 4)"
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
