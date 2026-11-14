"""Imágenes del video en `videos` (RF-08, RF-11, ADR-024): si se pidieron y cuántas van.

- `analizar_imagenes`: si se pidió describir imágenes, guardado en `POST /videos` ya resuelto
  contra `FOTOGRAMAS_DESCRIBIR` (el parámetro gana sobre la instalación). La pantalla de avance
  sabe desde el principio si la etapa "fotogramas" va a correr; hasta ahora el valor solo vivía
  en la cola, en memoria, y `metadatos.imagenes` llega al final. NULL en los videos anteriores:
  ninguno pudo describir imágenes, así que la API lo lee como false.
- `imagenes_hechas` e `imagenes_total`: cuántas de las imágenes sacadas ya pasaron por Gemma,
  puestos al día por lote durante la etapa "fotogramas". NULL si nunca se describieron.

El downgrade borra las tres columnas.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("analizar_imagenes", sa.Boolean(), nullable=True))
    op.add_column("videos", sa.Column("imagenes_hechas", sa.Integer(), nullable=True))
    op.add_column("videos", sa.Column("imagenes_total", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_videos_imagenes"),
        "videos",
        "imagenes_hechas >= 0 AND imagenes_total >= 0 AND imagenes_hechas <= imagenes_total",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_videos_imagenes"), "videos", type_="check")
    op.drop_column("videos", "imagenes_total")
    op.drop_column("videos", "imagenes_hechas")
    op.drop_column("videos", "analizar_imagenes")
