"""SOP de referencia en la tabla `sops` (RF-03; la biblioteca completa es RF-05, en S5).

El SOP llega como Markdown o TXT y se convierte al esquema `SOP` con código, sin LLM
(ADR-015); el texto se lee en UTF-8 y el BOM se descarta, que es lo que agrega PowerShell. Aquí
solo se guarda el SOP convertido: el archivo original no se copia al volumen de medios.

Un mismo SOP convertido se reutiliza: si el título y el contenido coinciden con una fila que ya
existe, se devuelve esa (de ahí el `contenido` sin `creado` ni ids). Así, volver a validar el
mismo SOP no llena la biblioteca de copias y `reportes.sop_id` apunta siempre a la misma fila.

Si el texto no sigue la plantilla, `convertir_sop` lanza `ErrorSOP` y aquí no se guarda nada; el
mensaje de `ErrorSOP` cita el formato esperado y números de línea, nunca el texto del SOP.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from sopvid.contrato import SOP
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.plataforma.modelos import Sop

logger = logging.getLogger(__name__)

ORIGEN_CARGADO = "cargado"


class SinSOP(LookupError):  # noqa: N818 (nombre de dominio)
    """El SOP pedido no existe o el video no tiene uno."""


def guardar_sop(session: Session, texto: str) -> Sop:
    """Convierte `texto` y devuelve su fila de `sops` (la crea si no existe). No hace commit.

    Lanza `ErrorSOP` si el texto no sigue la plantilla; en ese caso no toca la sesión.
    """
    sop = convertir_sop(texto).sop
    contenido = sop.model_dump(mode="json")
    for fila in session.scalars(select(Sop).where(Sop.titulo == sop.titulo)):
        if fila.contenido == contenido:
            logger.info(
                "SOP %s reutilizado: %s (%d pasos)", fila.codigo, sop.titulo, len(sop.pasos)
            )
            return fila
    fila = Sop(
        titulo=sop.titulo,
        origen=ORIGEN_CARGADO,
        archivo_original=None,
        contenido=contenido,
    )
    session.add(fila)
    session.flush()  # asigna el id y el código generado
    logger.info("SOP %s guardado: %s (%d pasos)", fila.codigo, sop.titulo, len(sop.pasos))
    return fila


def sop_de(session: Session, sop_id: int) -> Sop:
    """La fila de `sops` con ese id; `SinSOP` si no existe."""
    fila = session.get(Sop, sop_id)
    if fila is None:
        raise SinSOP(f"el SOP {sop_id} no existe")
    return fila


def contrato_de(fila: Sop) -> SOP:
    """El `SOP` del contrato validado a partir de `sops.contenido`."""
    return SOP.model_validate(fila.contenido)
