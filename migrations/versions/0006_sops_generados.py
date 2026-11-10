"""SOP generado desde el video: biblioteca y registro de la generación (ADR-023).

- `sops.en_biblioteca`: si el SOP se puede usar como referencia en otro video (RF-27). Los
  cargados ya están (true por defecto, también los que existían); un SOP generado entra al
  guardarlo con `POST /sops/{id}/biblioteca`.
- `sops.generacion` (JSONB): cómo se generó (`GeneracionSOP`: modelo, llamadas con segundos y
  tokens, grupos de pasos del video y dispositivo de Gemma). NULL en un SOP cargado.

El vínculo con el video es `videos.sop_id`, como en la sección 10 del documento SOP V1.0 ("sop_id
apunta al SOP generado"); no hace falta columna. El downgrade borra las dos columnas.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sops",
        sa.Column("en_biblioteca", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("sops", sa.Column("generacion", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("sops", "generacion")
    op.drop_column("sops", "en_biblioteca")
