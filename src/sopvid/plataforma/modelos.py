"""Modelos ORM de la sección 10 "Modelo de datos" del documento SOP V1.0, en PostgreSQL (ADR-005).

Cinco tablas: `sops`, `videos`, `reportes`, `palabras` y `busquedas`. El SOP, el análisis y el
reporte se guardan como JSONB con los esquemas del contrato (`sopvid.contrato`). Los archivos
viven en el volumen de medios; aquí solo se guarda su ruta relativa, nunca el contenido.

Las reglas de integridad (CHECK, RESTRICT, CASCADE) las aplica la base; las relaciones usan
`passive_deletes` para que el ORM no las esquive al borrar.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sopvid.plataforma.db import Base

ORIGENES_SOP = ("cargado", "generado")
METODOS_SOP = ("plantilla", "llm")  # cómo se convirtió un SOP cargado (ADR-015)
ESTADOS_SOP = ("en_cola", "convirtiendo", "listo", "error")  # conversión en el trabajador
MODOS_VIDEO = ("validar", "generar")
# "afinidad_baja" (migración 0005, ADR-020): la validación se detuvo porque el video parece no ser
# del SOP; espera a que quien carga decida continuar (POST /videos/{id}/validar?continuar=true).
PROCESOS_VIDEO = ("en_cola", "procesando", "listo", "error", "afinidad_baja")


def _en(columna: str, valores: tuple[str, ...]) -> str:
    """Expresión SQL `columna IN (...)` para una CHECK."""
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


def _creado() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Sop(Base):
    """SOP de referencia, cargado por el usuario o generado desde un video."""

    __tablename__ = "sops"
    __table_args__ = (
        CheckConstraint(_en("origen", ORIGENES_SOP), name="origen"),
        CheckConstraint(_en("metodo", METODOS_SOP), name="metodo"),
        CheckConstraint(_en("estado", ESTADOS_SOP), name="estado"),
        CheckConstraint(
            "estado <> 'listo' OR (titulo IS NOT NULL AND contenido IS NOT NULL)",
            name="listo_completo",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Columna generada: la base la calcula en el mismo INSERT a partir del id, así que no
    # puede quedar vacía ni desalineada. Equivale a f"SOP-{id:04d}" (desde 10 000 no trunca).
    codigo: Mapped[str] = mapped_column(
        String(20),
        Computed("'SOP-' || lpad(id::text, greatest(4, length(id::text)), '0')", persisted=True),
        unique=True,
    )
    # Título y SOP del contrato: None hasta que la conversión termina (migración 0004).
    titulo: Mapped[str | None] = mapped_column(String(300))
    origen: Mapped[str] = mapped_column(String)
    archivo_original: Mapped[str | None] = mapped_column(String)
    contenido: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Conversión en el trabajador: en_cola → convirtiendo → listo | error (mensaje en `error`).
    estado: Mapped[str] = mapped_column(String, default="listo", server_default="listo")
    error: Mapped[str | None] = mapped_column(Text)
    # Cómo se convirtió (migración 0003): "plantilla" o "llm"; None en un SOP generado o en los
    # cargados antes. `advertencias`: las de la conversión (tipo, línea, mensaje), para RF-04.
    metodo: Mapped[str | None] = mapped_column(String)
    advertencias: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # Biblioteca (RF-27, migración 0006): si se puede usar como referencia en otro video. Los
    # cargados entran solos; un generado, al guardarlo. `generacion`: cómo se generó desde el
    # video (`GeneracionSOP`, ADR-023); NULL en un SOP cargado.
    en_biblioteca: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    generacion: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    creado: Mapped[datetime] = _creado()

    # passive_deletes="all": el ORM no pone videos.sop_id = NULL al borrar el SOP; la base
    # aplica el RESTRICT (RF-05: no se borra un SOP en uso).
    videos: Mapped[list["Video"]] = relationship(back_populates="sop", passive_deletes="all")


class Video(Base):
    """Video subido, su estado de proceso y los resultados del análisis."""

    __tablename__ = "videos"
    __table_args__ = (
        CheckConstraint("duracion >= 0", name="duracion"),
        CheckConstraint(_en("modo", MODOS_VIDEO), name="modo"),
        CheckConstraint(_en("proceso", PROCESOS_VIDEO), name="proceso"),
        CheckConstraint("progreso BETWEEN 0 AND 100", name="progreso"),
        CheckConstraint(
            "imagenes_hechas >= 0 AND imagenes_total >= 0 AND imagenes_hechas <= imagenes_total",
            name="imagenes",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    titulo: Mapped[str] = mapped_column(String(300))
    archivo: Mapped[str] = mapped_column(String)
    duracion: Mapped[float | None] = mapped_column(Float)
    idioma: Mapped[str | None] = mapped_column(String(10))
    modo: Mapped[str] = mapped_column(String)
    # En modo generar queda vacío hasta que exista el SOP generado.
    sop_id: Mapped[int | None] = mapped_column(
        ForeignKey("sops.id", ondelete="RESTRICT"), index=True
    )
    proceso: Mapped[str] = mapped_column(String, default="en_cola", server_default="en_cola")
    etapa: Mapped[str | None] = mapped_column(String)
    progreso: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    # Si se pidió describir imágenes (ADR-024), ya resuelto contra FOTOGRAMAS_DESCRIBIR al subir.
    # NULL en los videos anteriores a la columna (0007): ninguno las describió; se lee como false.
    analizar_imagenes: Mapped[bool | None] = mapped_column(Boolean)
    # Cuántas de las imágenes sacadas ya pasaron por Gemma, al día por lote durante "fotogramas"
    # (RF-08). NULL si nunca se describieron; al repetir sin describir, quedan las del proceso.
    imagenes_hechas: Mapped[int | None] = mapped_column(Integer)
    imagenes_total: Mapped[int | None] = mapped_column(Integer)
    transcripcion: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fotogramas: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    contexto: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # `SegmentacionGuardada` (dict, RNF-07); las filas anteriores guardaban solo la lista.
    pasos_video: Mapped[dict[str, Any] | list[dict[str, Any]] | None] = mapped_column(JSONB)
    publicado: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    creado: Mapped[datetime] = _creado()

    sop: Mapped[Sop | None] = relationship(back_populates="videos")
    # passive_deletes: el ORM no intenta poner reportes.video_id = NULL; la base borra en cascada.
    reporte: Mapped["Reporte | None"] = relationship(
        back_populates="video", cascade="all, delete-orphan", passive_deletes=True
    )


class Reporte(Base):
    """Reporte de validación de un video contra un SOP (uno por video)."""

    __tablename__ = "reportes"
    __table_args__ = (
        CheckConstraint("afinidad BETWEEN 0 AND 100", name="afinidad"),
        CheckConstraint("cumplimiento BETWEEN 0 AND 100", name="cumplimiento"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), unique=True)
    # Índice para que el RESTRICT al borrar un SOP no recorra toda la tabla.
    sop_id: Mapped[int] = mapped_column(ForeignKey("sops.id", ondelete="RESTRICT"), index=True)
    afinidad: Mapped[int | None] = mapped_column(Integer)
    # Numeric(5,2): Postgres redondea antes de evaluar la CHECK, así que un 100.00000000000001
    # calculado con flotantes no la rompe, y se guarda exactamente lo que se muestra.
    cumplimiento: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    resultado: Mapped[dict[str, Any]] = mapped_column(JSONB)
    creado: Mapped[datetime] = _creado()

    video: Mapped[Video] = relationship(back_populates="reporte")
    sop: Mapped[Sop] = relationship()


class Palabra(Base):
    """Índice de búsqueda exacta: una fila por palabra transcrita de un video publicado."""

    __tablename__ = "palabras"
    __table_args__ = (
        CheckConstraint("t_inicio >= 0", name="t_inicio"),
        CheckConstraint("t_fin >= t_inicio", name="t_fin"),
        UniqueConstraint("video_id", "posicion"),
        # Búsqueda exacta de palabras y frases (RNF-02: < 1 s con 50 videos).
        Index(None, "palabra_normalizada", "video_id", "posicion"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    palabra_normalizada: Mapped[str] = mapped_column(String(100))
    palabra_original: Mapped[str] = mapped_column(String(100))
    t_inicio: Mapped[float] = mapped_column(Float)
    t_fin: Mapped[float] = mapped_column(Float)
    posicion: Mapped[int] = mapped_column(Integer)


class Busqueda(Base):
    """Historial de búsquedas y métricas de uso."""

    __tablename__ = "busquedas"
    __table_args__ = (CheckConstraint("num_resultados >= 0", name="num_resultados"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consulta: Mapped[str] = mapped_column(Text)
    num_resultados: Mapped[int] = mapped_column(Integer)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
