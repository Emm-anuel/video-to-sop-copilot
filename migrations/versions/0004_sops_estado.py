"""Estado de la conversión de cada SOP: `sops.estado` y `sops.error` (POST /sops asíncrono).

La conversión corre en el trabajador de la cola: la fila se crea en "en_cola" con el archivo
original y sin título ni contenido, pasa a "convirtiendo" y termina en "listo" (con título y
SOP del contrato) o en "error" (con el mensaje en `error`). Los SOP anteriores quedan "listo".
`titulo` y `contenido` aceptan NULL mientras no esté listo; una CHECK exige los dos en "listo".

El downgrade borra los SOP que no están listos (no tienen contenido que conservar) y suelta los
videos que los esperaban (`sop_id` a NULL) antes de volver a exigir NOT NULL.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sops", sa.Column("estado", sa.String(), server_default="listo", nullable=False))
    op.add_column("sops", sa.Column("error", sa.Text(), nullable=True))
    op.alter_column("sops", "titulo", existing_type=sa.String(length=300), nullable=True)
    op.alter_column(
        "sops", "contenido", existing_type=postgresql.JSONB(astext_type=sa.Text()), nullable=True
    )
    op.create_check_constraint(
        op.f("ck_sops_estado"), "sops", "estado IN ('en_cola', 'convirtiendo', 'listo', 'error')"
    )
    op.create_check_constraint(
        op.f("ck_sops_listo_completo"),
        "sops",
        "estado <> 'listo' OR (titulo IS NOT NULL AND contenido IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE videos SET sop_id = NULL "
        "WHERE sop_id IN (SELECT id FROM sops WHERE estado <> 'listo')"
    )
    op.execute("DELETE FROM sops WHERE estado <> 'listo'")
    op.drop_constraint(op.f("ck_sops_listo_completo"), "sops", type_="check")
    op.drop_constraint(op.f("ck_sops_estado"), "sops", type_="check")
    op.alter_column(
        "sops", "contenido", existing_type=postgresql.JSONB(astext_type=sa.Text()), nullable=False
    )
    op.alter_column("sops", "titulo", existing_type=sa.String(length=300), nullable=False)
    op.drop_column("sops", "error")
    op.drop_column("sops", "estado")
