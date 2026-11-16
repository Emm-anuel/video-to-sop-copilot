"""Cuándo se publicó un video (RF-32): `videos.publicado_en`.

`POST /videos/{id}/publicar` arma el índice de `palabras`, marca `videos.publicado` (columna de la
0002) y guarda aquí la hora; publicar otra vez la pone al día. `DELETE /videos/{id}/publicar` la
vuelve NULL. NULL en los videos que nunca se publicaron. No agrega índices: el de `palabras`
(`palabra_normalizada, video_id, posicion`) y el único (`video_id, posicion`) ya existen.

El downgrade borra la columna.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("publicado_en", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("videos", "publicado_en")
