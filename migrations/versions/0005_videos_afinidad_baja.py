"""Estado `afinidad_baja` en `videos.proceso` (ADR-020).

Con afinidad de contexto menor que AFINIDAD_MIN (RF-17, SOP V1.0 §5.2), la validación se detiene
después de la ficha de contexto y el video queda en "afinidad_baja" hasta que quien carga decide
continuar. La afinidad se guarda en `reportes` (columna `afinidad`, `cumplimiento` en NULL y la
detención en `resultado`), sin columnas nuevas.

El downgrade pasa esos videos a "error" con un mensaje que dice repetir la validación, y borra sus
reportes de detención (no tienen pasos que conservar).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANTES = "proceso IN ('en_cola', 'procesando', 'listo', 'error')"
DESPUES = "proceso IN ('en_cola', 'procesando', 'listo', 'error', 'afinidad_baja')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_videos_proceso"), "videos", type_="check")
    op.create_check_constraint(op.f("ck_videos_proceso"), "videos", DESPUES)


def downgrade() -> None:
    op.execute(
        "DELETE FROM reportes WHERE video_id IN "
        "(SELECT id FROM videos WHERE proceso = 'afinidad_baja')"
    )
    op.execute(
        "UPDATE videos SET proceso = 'error', error = 'afinidad baja: repite la validación con "
        "POST /videos/{id}/validar' WHERE proceso = 'afinidad_baja'"
    )
    op.drop_constraint(op.f("ck_videos_proceso"), "videos", type_="check")
    op.create_check_constraint(op.f("ck_videos_proceso"), "videos", ANTES)
