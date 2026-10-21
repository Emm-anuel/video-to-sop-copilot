"""Tablas del modelo de datos (sección 10 del documento SOP V1.0).

En PostgreSQL con JSONB (ADR-005). Crea `sops`, `videos`, `reportes`, `palabras` y `busquedas`.
Generada con autogenerate y revisada a mano: todas las restricciones llevan nombre explícito
(convención de `Base.metadata`) y `sops.codigo` es una columna generada a partir del id.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "codigo",
            sa.String(length=20),
            sa.Computed(
                "'SOP-' || lpad(id::text, greatest(4, length(id::text)), '0')", persisted=True
            ),
            nullable=False,
        ),
        sa.Column("titulo", sa.String(length=300), nullable=False),
        sa.Column("origen", sa.String(), nullable=False),
        sa.Column("archivo_original", sa.String(), nullable=True),
        sa.Column("contenido", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "creado", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("origen IN ('cargado', 'generado')", name=op.f("ck_sops_origen")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sops")),
        sa.UniqueConstraint("codigo", name=op.f("uq_sops_codigo")),
    )

    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("titulo", sa.String(length=300), nullable=False),
        sa.Column("archivo", sa.String(), nullable=False),
        sa.Column("duracion", sa.Float(), nullable=True),
        sa.Column("idioma", sa.String(length=10), nullable=True),
        sa.Column("modo", sa.String(), nullable=False),
        sa.Column("sop_id", sa.Integer(), nullable=True),
        sa.Column("proceso", sa.String(), server_default="en_cola", nullable=False),
        sa.Column("etapa", sa.String(), nullable=True),
        sa.Column("progreso", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("transcripcion", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fotogramas", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("contexto", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pasos_video", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("publicado", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "creado", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("duracion >= 0", name=op.f("ck_videos_duracion")),
        sa.CheckConstraint("modo IN ('validar', 'generar')", name=op.f("ck_videos_modo")),
        sa.CheckConstraint(
            "proceso IN ('en_cola', 'procesando', 'listo', 'error')",
            name=op.f("ck_videos_proceso"),
        ),
        sa.CheckConstraint("progreso BETWEEN 0 AND 100", name=op.f("ck_videos_progreso")),
        sa.ForeignKeyConstraint(
            ["sop_id"], ["sops.id"], name=op.f("fk_videos_sop_id_sops"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_videos")),
    )
    op.create_index(op.f("ix_videos_sop_id"), "videos", ["sop_id"])

    op.create_table(
        "reportes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("sop_id", sa.Integer(), nullable=False),
        sa.Column("afinidad", sa.Integer(), nullable=True),
        sa.Column("cumplimiento", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("resultado", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "creado", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("afinidad BETWEEN 0 AND 100", name=op.f("ck_reportes_afinidad")),
        sa.CheckConstraint("cumplimiento BETWEEN 0 AND 100", name=op.f("ck_reportes_cumplimiento")),
        sa.ForeignKeyConstraint(
            ["sop_id"], ["sops.id"], name=op.f("fk_reportes_sop_id_sops"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["videos.id"],
            name=op.f("fk_reportes_video_id_videos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reportes")),
        sa.UniqueConstraint("video_id", name=op.f("uq_reportes_video_id")),
    )
    op.create_index(op.f("ix_reportes_sop_id"), "reportes", ["sop_id"])

    op.create_table(
        "palabras",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("palabra_normalizada", sa.String(length=100), nullable=False),
        sa.Column("palabra_original", sa.String(length=100), nullable=False),
        sa.Column("t_inicio", sa.Float(), nullable=False),
        sa.Column("t_fin", sa.Float(), nullable=False),
        sa.Column("posicion", sa.Integer(), nullable=False),
        sa.CheckConstraint("t_inicio >= 0", name=op.f("ck_palabras_t_inicio")),
        sa.CheckConstraint("t_fin >= t_inicio", name=op.f("ck_palabras_t_fin")),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["videos.id"],
            name=op.f("fk_palabras_video_id_videos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_palabras")),
        sa.UniqueConstraint("video_id", "posicion", name=op.f("uq_palabras_video_id_posicion")),
    )
    op.create_index(
        op.f("ix_palabras_palabra_normalizada_video_id_posicion"),
        "palabras",
        ["palabra_normalizada", "video_id", "posicion"],
    )

    op.create_table(
        "busquedas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consulta", sa.Text(), nullable=False),
        sa.Column("num_resultados", sa.Integer(), nullable=False),
        sa.Column(
            "fecha", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("num_resultados >= 0", name=op.f("ck_busquedas_num_resultados")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_busquedas")),
    )


def downgrade() -> None:
    # Orden inverso al de creación; los índices se van con su tabla.
    op.drop_table("busquedas")
    op.drop_table("palabras")
    op.drop_table("reportes")
    op.drop_table("videos")
    op.drop_table("sops")
