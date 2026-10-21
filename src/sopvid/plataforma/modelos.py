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
MODOS_VIDEO = ("validar", "generar")
PROCESOS_VIDEO = ("en_cola", "procesando", "listo", "error")


def _en(columna: str, valores: tuple[str, ...]) -> str:
    """Expresión SQL `columna IN (...)` para una CHECK."""
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


def _creado() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Sop(Base):
    """SOP de referencia, cargado por el usuario o generado desde un video."""

    __tablename__ = "sops"
    __table_args__ = (CheckConstraint(_en("origen", ORIGENES_SOP), name="origen"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Columna generada: la base la calcula en el mismo INSERT a partir del id, así que no
    # puede quedar vacía ni desalineada. Equivale a f"SOP-{id:04d}" (desde 10 000 no trunca).
    codigo: Mapped[str] = mapped_column(
        String(20),
        Computed("'SOP-' || lpad(id::text, greatest(4, length(id::text)), '0')", persisted=True),
        unique=True,
    )
    titulo: Mapped[str] = mapped_column(String(300))
    origen: Mapped[str] = mapped_column(String)
    archivo_original: Mapped[str | None] = mapped_column(String)
    contenido: Mapped[dict[str, Any]] = mapped_column(JSONB)
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
    transcripcion: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fotogramas: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    contexto: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pasos_video: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
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
