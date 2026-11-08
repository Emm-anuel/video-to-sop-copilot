"""Cómo se convirtió cada SOP cargado: `sops.metodo` y `sops.advertencias` (ADR-015).

`metodo` es "plantilla" (parser con código) o "llm" (Gemma 4); queda NULL en un SOP generado
desde el video y en los cargados antes de esta migración. `advertencias` guarda las de la
conversión (tipo, línea y mensaje, sin texto del SOP), para la pantalla de corrección (RF-04);
los SOP anteriores quedan con la lista vacía. Columnas aparte y no dentro de `contenido`: ese
JSONB es el SOP del contrato, que se valida con `extra="forbid"`.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sops", sa.Column("metodo", sa.String(), nullable=True))
    op.add_column(
        "sops",
        sa.Column(
            "advertencias",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(op.f("ck_sops_metodo"), "sops", "metodo IN ('plantilla', 'llm')")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_sops_metodo"), "sops", type_="check")
    op.drop_column("sops", "advertencias")
    op.drop_column("sops", "metodo")
