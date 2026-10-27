"""Contratos del pipeline: análisis del video, pasos del video (RF-13) y SOP (RF-03).

`Analisis` es el JSON que produce el pipeline de video: idioma, transcripción con tiempo por
palabra y fotogramas descritos. `PasoVideo` es cada paso que la extracción obtiene de él;
`Fusion` registra qué pasos del video se unieron antes de emparejar (ADR-013), `Par` es cada
pareja que elige el algoritmo húngaro (ADR-012), `Clasificacion` es el estado de cada paso tras
los umbrales de la cascada, el juez de la zona gris (`Juicio`) y la revisión del orden
(`ResultadoPaso`) con su resumen, y
`ResultadoEmparejamiento` junta todo lo que devuelve `emparejar`. `ResultadoValidacion` es lo que
se guarda del reporte (con el porcentaje, el semáforo y los metadatos) y `ReporteValidacion`, lo
que responde la API con una fila por paso.

`SOP` es el esquema de la sección 10 del documento SOP V1.0, con tres diferencias deliberadas:
lleva `version_contrato`, `t_inicio`/`t_fin` de cada paso pueden ser `None` (un SOP cargado no
tiene tiempos; los llena el SOP generado desde el video) y todo el resumen tiene valores por
defecto, para que un SOP mínimo (título y pasos) valide.

Todo tiempo de estos contratos sale de la transcripción o del video, nunca del LLM (regla 4 de
CLAUDE.md). Reglas comunes: campos extra prohibidos, tiempos finitos y ≥ 0, fin ≥ inicio, y las
listas vacías se escriben `[]`, nunca `null`. Los mensajes de error solo citan ids, números de
paso y tiempos, nunca texto de la transcripción ni del SOP (puede ser material del cliente).

Los JSON Schema se exportan a docs/contrato/ (analisis, sop y reporte .schema.json) con
`python scripts/exportar_contrato.py`; no se editan a mano.
"""

import math
from datetime import datetime
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
# UMBRAL_BAJO y UMBRAL_ALTO que espera al juez Gemma 4 (`lenguaje/juez.py`). El juez lo
# convierte en Cumple, Parcial o en un Falta más un Sobra. Un "zona_gris" solo llega al reporte
# si el juez no pudo decidir (Ollama caído o respuestas inválidas): lleva un `Juicio` de
# respaldo y el reporte lo muestra como "sin revisar", nunca como un estado inventado.
EstadoPaso = Literal["Cumple", "Parcial", "Falta", "Sobra", "zona_gris"]
ESTADOS: tuple[EstadoPaso, ...] = get_args(EstadoPaso)
# Los pares que revisa `orden` y los únicos que pueden llevar la marca de fuera de orden.
ESTADOS_CON_ORDEN: tuple[EstadoPaso, ...] = ("Cumple", "Parcial", "zona_gris")

# Lo que decide el juez de un par de la zona gris (ADR-012, punto 3); "no_corresponde" rompe el
# par en un Falta (paso del SOP) más un Sobra (paso del video).
Veredicto = Literal["Cumple", "Parcial", "no_corresponde"]
VEREDICTOS: tuple[Veredicto, ...] = get_args(Veredicto)
# "llm": el juez decidió con una cita verificada; "respaldo": no pudo decidir y el par sigue en
# zona gris.
OrigenJuicio = Literal["llm", "respaldo"]
# Por qué un juicio es de respaldo: Ollama no responde o rechazó la petición, el modelo no dio
# una respuesta válida tras los reintentos, o el paso del video no tiene narración que citar.
MotivoRespaldo = Literal["llm_no_disponible", "respuesta_invalida", "sin_narracion"]
# Claves de `ResumenClasificacion.juez`: los veredictos más los pares que quedaron en respaldo.
ResultadoJuez = Literal["Cumple", "Parcial", "no_corresponde", "respaldo"]
RESULTADOS_JUEZ: tuple[ResultadoJuez, ...] = get_args(ResultadoJuez)
# Marca de un Sobra que es el marco de la narración (ADR-016): empieza antes del primer paso
# emparejado ("intro") o después del último ("cierre").
MarcoOperador = Literal["intro", "cierre"]
# Color del cumplimiento en el reporte (RF-19); los cortes viven en la configuración.
Semaforo = Literal["verde", "amarillo", "rojo"]


class Juicio(_Modelo):
    """Decisión del juez sobre un par de la zona gris (ADR-012, punto 3).

    Con `origen="llm"` lleva veredicto, justificación y una cita que el código verificó contra
    la narración del paso del video (regla 4: aparece tal cual en la transcripción). Con
    `origen="respaldo"` el juez no pudo decidir: sin veredicto, justificación ni cita, y con
    `motivo`. `similitud` es el coseno del par, que se conserva aunque el par se rompa.
    `prompt` es la versión del prompt (p. ej. "juez_zona_gris_v1") e `intentos`, las llamadas
    al LLM (0 si no se llamó).
    """

    origen: OrigenJuicio
    veredicto: Veredicto | None = None
    justificacion: str = ""
    cita: str = ""
    similitud: float = Field(ge=-1, le=1)
    prompt: str = Field(min_length=1)
    modelo: str | None = None
    intentos: int = Field(ge=0)
    motivo: MotivoRespaldo | None = None

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        if self.origen == "llm":
            if self.veredicto is None or not self.cita.strip() or not self.justificacion.strip():
                raise ValueError("juicio del LLM: lleva veredicto, justificación y cita")
            if self.motivo is not None or self.intentos < 1:
                raise ValueError("juicio del LLM: sin motivo de respaldo y con al menos 1 intento")
        elif self.veredicto is not None or self.cita or self.justificacion or self.motivo is None:
            raise ValueError("juicio de respaldo: sin veredicto, justificación ni cita; con motivo")
        return self


class ResultadoPaso(_Modelo):
    """Estado de un paso del SOP o del video tras la cascada (ADR-012).

    Cumple, Parcial y zona_gris son un par: llevan los dos índices y la similitud. Falta es un
    paso del SOP sin pareja (o cuyo par se rompió por similitud baja): solo `indice_sop`. Sobra
    es un paso del video sin pareja: solo `indice_video`. Los índices son posiciones desde 0,
    como en `Par`; la similitud es la del par, así que un Falta o un Sobra no la llevan.

    `t_inicio`, `cita` y `confianza` salen del paso del video (regla 4: ningún tiempo nuevo); un
    Falta no tiene paso del video y los deja en `None`, `""` y `None`. Si la cita está vacía, la
    confianza es "baja".

    *Fuera de orden* es una marca, no un estado: un Cumple, Parcial o zona_gris puede estar fuera
    de orden a la vez (lo decide `orden`, con código; regla 5). Con la marca van
    `posicion_esperada` (lugar del paso en el SOP entre los pasos emparejados) y
    `posicion_observada` (lugar en el video entre los mismos), ambas desde 0; sin la marca, las
    dos quedan en `None`.

    `juicio` es la decisión del juez de la zona gris, si el par pasó por él: un Cumple o Parcial
    lleva su mismo veredicto, un Falta y un Sobra que salen de romper el par llevan
    "no_corresponde", y un zona_gris solo puede llevar un juicio de respaldo. Parcial siempre
    lleva juicio (solo el juez lo asigna).

    `marco_operador` es otra marca (ADR-016), solo para Sobra: "intro" o "cierre" si el paso
    empieza antes del primer paso emparejado o después del último. El paso sigue siendo Sobra,
    con su cita y su segundo, pero el resumen no lo cuenta en `conteo["Sobra"]`.
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
    juicio: Juicio | None = None
    marco_operador: MarcoOperador | None = None

    @model_validator(mode="after")
    def _marco_solo_en_sobra(self) -> Self:
        if self.marco_operador is not None and self.estado != "Sobra":
            raise ValueError(f"{self.estado}: solo un Sobra puede llevar marco_operador")
        return self

    @model_validator(mode="after")
    def _juicio_coherente(self) -> Self:
        j = self.juicio
        if j is None:
            if self.estado == "Parcial":
                raise ValueError("Parcial: solo lo asigna el juez, así que lleva juicio")
            return self
        if j.origen == "respaldo":
            esperado: tuple[EstadoPaso, ...] = ("zona_gris",)
        elif j.veredicto == "no_corresponde":
            esperado = ("Falta", "Sobra")
        else:
            esperado = (j.veredicto,) if j.veredicto else ()
        if self.estado not in esperado:
            raise ValueError(
                f"{self.estado}: no concuerda con el juicio ({j.origen}, {j.veredicto})"
            )
        return self

    @model_validator(mode="after")
    def _marca_de_orden(self) -> Self:
        if self.fuera_de_orden and self.estado not in ESTADOS_CON_ORDEN:
            raise ValueError(
                f"{self.estado}: solo Cumple, Parcial y zona_gris pueden ir fuera de orden"
            )
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
    la métrica del paper (ADR-012). La revisión de EPP y puntos de validación de los Cumple
    (punto 4 de ADR-012, diferida con RF-18) no cuenta aquí. `fuera_de_orden` cuenta aparte los
    pasos con esa marca (0 hasta que corre `orden`); no cambia el conteo por estado.

    `juez` queda en `None` hasta que corre el juez de la zona gris; después cuenta qué decidió
    en cada par que le llegó (todos los `RESULTADOS_JUEZ`, aunque sea 0): su suma es
    `pares_llm` y "respaldo" es el conteo de zona_gris que quedó. Sin juez, `pares_llm` es el
    conteo de zona_gris.

    `segundos_juez` es lo que tardó el juez en toda la clasificación (`time.perf_counter`), para
    el paper; va junto con `juez`: los dos en `None` si no corrió.

    `conteo["Sobra"]` no incluye los Sobra con `marco_operador` (intro y cierre del operador,
    ADR-016): esos se cuentan aparte en `marco_operador` (0 hasta que corre `marcar_marco`).
    """

    conteo: dict[EstadoPaso, Annotated[int, Field(ge=0)]]
    pares: int = Field(ge=0)
    pares_llm: int = Field(ge=0)
    pct_pares_llm: float = Field(ge=0, le=100)
    fuera_de_orden: int = Field(default=0, ge=0)
    juez: dict[ResultadoJuez, Annotated[int, Field(ge=0)]] | None = None
    segundos_juez: float | None = Field(default=None, ge=0)
    marco_operador: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        if (self.juez is None) != (self.segundos_juez is None):
            raise ValueError("juez y segundos_juez van juntos: los dos o ninguno")
        if set(self.conteo) != set(ESTADOS):
            raise ValueError("el conteo lleva todos los estados, aunque sea en 0")
        if self.pares_llm > self.pares:
            raise ValueError(
                f"pares_llm ({self.pares_llm}) no puede ser más que los pares ({self.pares})"
            )
        if self.juez is None:
            if self.pares_llm != self.conteo["zona_gris"]:
                raise ValueError(
                    f"pares_llm ({self.pares_llm}) debe ser el conteo de zona_gris "
                    f"({self.conteo['zona_gris']})"
                )
        else:
            if set(self.juez) != set(RESULTADOS_JUEZ):
                raise ValueError("el resumen del juez lleva todos sus resultados, aunque sea en 0")
            if sum(self.juez.values()) != self.pares_llm:
                raise ValueError(
                    f"el juez decidió {sum(self.juez.values())} pares y fueron "
                    f"{self.pares_llm} al LLM"
                )
            if self.juez["respaldo"] != self.conteo["zona_gris"]:
                raise ValueError(
                    f"{self.juez['respaldo']} pares en respaldo y "
                    f"{self.conteo['zona_gris']} zona_gris"
                )
        esperado = 100 * self.pares_llm / self.pares if self.pares else 0.0
        if not math.isclose(self.pct_pares_llm, esperado, abs_tol=1e-9):
            raise ValueError(f"pct_pares_llm ({self.pct_pares_llm}) no es {esperado}")
        return self


class Clasificacion(_Modelo):
    """Salida de `clasificar` y de `orden`: un resultado por paso y su resumen.

    Primero un resultado por paso del SOP, en su orden; después los Sobra, en el orden del video.
    Los Sobra con `marco_operador` siguen en `pasos`, pero no cuentan en `conteo["Sobra"]`.
    """

    pasos: list[ResultadoPaso]
    resumen: ResumenClasificacion

    @model_validator(mode="after")
    def _resumen_coherente(self) -> Self:
        for estado in ESTADOS:
            n = sum(p.estado == estado and p.marco_operador is None for p in self.pasos)
            if self.resumen.conteo[estado] != n:
                raise ValueError(
                    f"el resumen cuenta {self.resumen.conteo[estado]} {estado} y hay {n}"
                )
        n = sum(p.marco_operador is not None for p in self.pasos)
        if self.resumen.marco_operador != n:
            raise ValueError(
                f"el resumen cuenta {self.resumen.marco_operador} pasos de marco y hay {n}"
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


# ── Reporte de validación (RF-14, RF-19, base de RF-20; ADR-017) ────────────────────────────

# Por qué un reporte es provisional (ADR-017): Ollama falló después de la revisión inicial.
# "segmentacion_heuristica": los pasos del video salieron de la heurística de respaldo;
# "juez_sin_revisar": quedaron pares en zona_gris; "pasos_sin_redactar": respondió la llamada de
# fronteras pero no la de redacción, y esos pasos van sin cita ni descripción (confianza baja).
TipoAviso = Literal["segmentacion_heuristica", "juez_sin_revisar", "pasos_sin_redactar"]


class Aviso(_Modelo):
    """Falla del sistema que afecta al reporte. `detalle` no lleva texto del video ni del SOP."""

    tipo: TipoAviso
    detalle: str


class Umbrales(_Modelo):
    """Los umbrales de la configuración con que se calculó el reporte (RNF-14)."""

    bajo: float = Field(ge=0, le=1)
    alto: float = Field(ge=0, le=1)
    fusion: float = Field(ge=0, le=1)
    semaforo_verde: float = Field(ge=0, le=100)
    semaforo_amarillo: float = Field(ge=0, le=100)


class MetadatosValidacion(_Modelo):
    """Cómo se obtuvo el reporte: segmentación, modelos, umbrales, tiempos y avisos.

    `segundos` lleva lo que tardó cada etapa (duracion, audio, transcripcion, segmentacion,
    emparejamiento); al repetir solo la validación (ADR-017) no trae las del análisis. Lo que
    tardó el juez va aparte, en `resultado.clasificacion.resumen.segundos_juez`.
    """

    segmentacion: Literal["llm", "heuristica"]
    motivo_respaldo: str | None = None
    modelo_llm: str | None = None  # el de la segmentación; el del juez va en cada `Juicio`
    embedder: str
    umbrales: Umbrales
    segundos: dict[str, Annotated[float, Field(ge=0)]]
    avisos: list[Aviso] = []


class ResultadoValidacion(_Modelo):
    """Lo que se guarda en `reportes.resultado` (JSONB).

    `cumplimiento` va sin redondear (la columna `reportes.cumplimiento` guarda el valor a dos
    decimales) y `semaforo` se calculó con él, nunca con el redondeado.
    """

    version_contrato: Literal[1] = 1
    resultado: ResultadoEmparejamiento
    cumplimiento: float = Field(ge=0, le=100)
    semaforo: Semaforo
    metadatos: MetadatosValidacion


class PasoSOPReporte(_Modelo):
    numero: int = Field(ge=1)
    nombre: str = Field(min_length=1)
    descripcion: str = ""


class SOPReporte(_Modelo):
    id: int
    codigo: str
    titulo: str
    pasos: list[PasoSOPReporte]


class FilaReporte(_Modelo):
    """Una fila de la tabla del reporte: un `ResultadoPaso`, en el mismo orden.

    `paso_sop` es el número del paso del SOP (desde 1), sin él en un Sobra; `paso_video`, el
    número del paso del video ya fusionado, sin él en un Falta. `t_inicio` y `cita` salen solo de
    la transcripción (regla 4). Un zona_gris se muestra como "sin revisar". `justificacion` es la
    del juez cuando decidió el par.
    """

    estado: EstadoPaso
    paso_sop: int | None = Field(default=None, ge=1)
    nombre_sop: str | None = None
    paso_video: int | None = Field(default=None, ge=1)
    nombre_video: str | None = None
    t_inicio: Tiempo | None = None
    cita: str = ""
    confianza: Confianza | None = None
    fuera_de_orden: bool = False
    marco_operador: MarcoOperador | None = None
    justificacion: str | None = None


class ConteoReporte(_Modelo):
    """Conteo de la clasificación. `sobra` no incluye los de `marco_operador` (ADR-016)."""

    cumple: int = Field(ge=0)
    parcial: int = Field(ge=0)
    fuera_de_orden: int = Field(ge=0)
    falta: int = Field(ge=0)
    sobra: int = Field(ge=0)
    sin_revisar: int = Field(ge=0)
    marco_operador: int = Field(ge=0)


class ReporteValidacion(_Modelo):
    """Respuesta de `GET /videos/{id}/reporte`.

    `cumplimiento` es el guardado (dos decimales); `semaforo`, el calculado con el valor sin
    redondear. `provisional` es true si hay avisos (ADR-017). `afinidad` queda en `None` hasta
    RF-17 (post-MVP).
    """

    version_contrato: Literal[1] = 1
    video_id: int
    sop: SOPReporte
    cumplimiento: float = Field(ge=0, le=100)
    semaforo: Semaforo
    provisional: bool
    afinidad: int | None = Field(default=None, ge=0, le=100)
    conteo: ConteoReporte
    filas: list[FilaReporte]
    metadatos: MetadatosValidacion
    creado: datetime

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        if self.provisional != bool(self.metadatos.avisos):
            raise ValueError("provisional va en true si y solo si hay avisos")
        filas = self.filas
        esperado = ConteoReporte(
            cumple=sum(f.estado == "Cumple" for f in filas),
            parcial=sum(f.estado == "Parcial" for f in filas),
            fuera_de_orden=sum(f.fuera_de_orden for f in filas),
            falta=sum(f.estado == "Falta" for f in filas),
            sobra=sum(f.estado == "Sobra" and f.marco_operador is None for f in filas),
            sin_revisar=sum(f.estado == "zona_gris" for f in filas),
            marco_operador=sum(f.marco_operador is not None for f in filas),
        )
        if self.conteo != esperado:
            raise ValueError("el conteo no coincide con las filas")
        n_sop = len(self.sop.pasos)
        for fila in filas:
            if fila.paso_sop is not None and fila.paso_sop > n_sop:
                raise ValueError(f"paso_sop {fila.paso_sop} fuera de los {n_sop} pasos del SOP")
        return self


def esquema_analisis() -> dict[str, Any]:
    """JSON Schema (draft 2020-12) de `Analisis`, tal como se exporta a docs/contrato/."""
    return {"$schema": URI_JSON_SCHEMA, **Analisis.model_json_schema()}


def esquema_sop() -> dict[str, Any]:
    """JSON Schema (draft 2020-12) de `SOP`, tal como se exporta a docs/contrato/."""
    return {"$schema": URI_JSON_SCHEMA, **SOP.model_json_schema()}


def esquema_reporte() -> dict[str, Any]:
    """JSON Schema (draft 2020-12) de `ReporteValidacion`, tal como se exporta a docs/contrato/."""
    return {"$schema": URI_JSON_SCHEMA, **ReporteValidacion.model_json_schema()}
