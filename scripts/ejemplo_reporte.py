"""Genera los ejemplos de `ReporteValidacion` para la pantalla del reporte (RF-20).

- tests/fixtures/reporte_ejemplo.json: reporte definitivo con todos los casos de la tabla.
- tests/fixtures/reporte_ejemplo_provisional.json: el mismo video con el juez caído (ADR-017):
  un paso "sin revisar" y el aviso `juez_sin_revisar`.

Datos INVENTADOS (tests/fixtures/README.md): la transcripción de `analisis_ejemplo.json` (Laura,
cambio del cartucho del filtro) y el SOP de `sop_ejemplo.json` con dos cambios para que salgan
todos los casos: los pasos 1 y 2 intercambiados (Laura se pone los guantes antes de cerrar la
llave: fuera de orden) y un paso 7 que no narra (bitácora: Falta).

Corre el código real de `emparejar` (fusión, húngaro, umbrales, juez, orden y marco del
operador), `porcentaje`, `semaforo`, `avisos_de` y `armar_reporte`. Solo los pasos del video, el
vectorizador y el juez están guionados (sin Gemma 4 ni MiniLM), así que el resultado es siempre
el mismo. Los tiempos y las citas salen de la transcripción (regla 4). Los umbrales son los
valores por defecto de `Settings`, sin leer `.env`.

Uso:
    python scripts/ejemplo_reporte.py
    python scripts/ejemplo_reporte.py --comprobar   # sale con 1 si algún archivo difiere
"""

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from sopvid.contrato import (
    SOP,
    Analisis,
    Dispositivos,
    Juicio,
    MetadatosValidacion,
    PasoSOP,
    PasoVideo,
    ReporteValidacion,
    ResultadoValidacion,
    Umbrales,
)
from sopvid.lenguaje import emparejamiento as emp
from sopvid.lenguaje.juez import respaldo
from sopvid.lenguaje.reporte import armar_reporte, porcentaje, semaforo
from sopvid.lenguaje.validacion import avisos_de
from sopvid.percepcion.segmentacion import Segmentacion
from sopvid.plataforma.config import Settings

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / "tests" / "fixtures"
SALIDAS = {
    "definitivo": FIXTURES / "reporte_ejemplo.json",
    "provisional": FIXTURES / "reporte_ejemplo_provisional.json",
}
RESPONSABLE = "Técnica de mantenimiento"

# Pasos del video como los titularía Gemma 4: (primer segmento, último, nombre, cita literal).
PASOS_VIDEO = [
    (1, 3, "Presentación del cambio de cartucho", "les muestro cómo se cambia el cartucho"),
    (4, 5, "Guantes y lentes de seguridad", "me pongo los guantes de nitrilo y los lentes"),
    (6, 7, "Cierre de la llave de paso", "cierro la llave de paso que está antes del filtro"),
    (8, 8, "Aviso al supervisor si la llave está dura", "mejor avisen al supervisor de turno"),
    (9, 10, "Liberación de la presión", "libero la presión con el botón rojo"),
    (11, 16, "Retiro del vaso y del cartucho usado", "giro el vaso hacia la izquierda"),
    (17, 20, "Colocación del cartucho nuevo", "tomo el cartucho nuevo y le quito el plástico"),
    (21, 24, "Apertura de la llave y revisión de fugas", "abro la llave de paso despacio"),
    (25, 25, "Cierre del video", "con eso queda listo el cambio del cartucho"),
]

# Concepto (índice del paso del SOP del ejemplo, desde 1) y coseno de cada texto según su
# prefijo. El SOP queda en el vector base; un paso del video con coseno s, a ese coseno de él.
# Los pasos del video que no están aquí (intro, aviso, cierre) no se parecen a nada.
GUION = {
    "Cerrar la llave de paso": (1, 1.0),
    "Ponerse guantes y lentes": (2, 1.0),
    "Liberar la presión": (3, 1.0),
    "Retirar la carcasa y el cartucho usado": (4, 1.0),
    "Colocar el cartucho nuevo": (5, 1.0),
    "Abrir la llave y revisar fugas": (6, 1.0),
    "Registrar el cambio en la bitácora": (7, 1.0),
    "Cierre de la llave de paso": (1, 0.9),
    "Guantes y lentes de seguridad": (2, 1.0),
    "Liberación de la presión": (3, 0.65),  # zona gris: decide el juez
    "Retiro del vaso y del cartucho usado": (4, 0.85),
    "Colocación del cartucho nuevo": (5, 0.95),
    "Apertura de la llave y revisión de fugas": (6, 0.8),
}
JUSTIFICACION = (
    "Libera la presión con el botón rojo, pero no menciona colocar la cubeta debajo del filtro."
)
SEGUNDOS = {
    "duracion": 0.2,
    "audio": 0.6,
    "transcripcion": 11.8,
    "segmentacion": 74.3,
    "emparejamiento": 9.6,
}
CREADO = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


class VectorizadorGuionado:
    """El vector de cada texto según el prefijo más largo de `GUION` con que empieza."""

    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray:
        prefijos = sorted(GUION, key=len, reverse=True)
        x = np.zeros((len(sentences), emp.DIMENSION))
        for i, texto in enumerate(sentences):
            prefijo = next((p for p in prefijos if texto.startswith(p)), None)
            if prefijo is None:
                x[i, 100 + _indice(texto)] = 1.0
                continue
            concepto, coseno = GUION[prefijo]
            x[i, concepto] = coseno
            x[i, 100 + _indice(prefijo)] = math.sqrt(max(0.0, 1 - coseno**2))
        return x


def _indice(texto: str) -> int:
    return int(hashlib.md5(texto.encode()).hexdigest(), 16) % (emp.DIMENSION - 100)


class JuezGuionado:
    """Parcial con justificación, o respaldo "llm_no_disponible" si el juez está caído."""

    def __init__(self, caido: bool):
        self.caido = caido

    def juzgar(
        self, paso_sop: PasoSOP, paso_video: PasoVideo, similitud: float, narracion: str
    ) -> Juicio:
        if self.caido:
            return respaldo(similitud, "llm_no_disponible", 1)
        return Juicio(
            origen="llm",
            veredicto="Parcial",
            justificacion=JUSTIFICACION,
            cita=" ".join(narracion.split()[:8]),
            similitud=similitud,
            prompt="juez_zona_gris_v1",
            modelo="gemma4:e4b-it-q4_K_M",
            intentos=1,
        )


def sop_del_ejemplo() -> SOP:
    sop = SOP.model_validate_json((FIXTURES / "sop_ejemplo.json").read_text(encoding="utf-8"))
    pasos = [sop.pasos[1], sop.pasos[0], *sop.pasos[2:]]
    pasos.append(
        PasoSOP(
            numero=7,
            nombre="Registrar el cambio en la bitácora",
            descripcion="Anotar la fecha, el cartucho instalado y la presión final.",
            responsable="Técnico de mantenimiento",
            puntos_validacion=["Bitácora firmada"],
        )
    )
    return sop.model_copy(
        update={"pasos": [p.model_copy(update={"numero": n}) for n, p in enumerate(pasos, 1)]}
    )


def pasos_del_video(analisis: Analisis) -> list[PasoVideo]:
    por_id = {s.id: s for s in analisis.transcripcion}
    pasos = []
    for numero, (primero, ultimo, nombre, cita) in enumerate(PASOS_VIDEO, start=1):
        tramo = " ".join(por_id[i].texto for i in range(primero, ultimo + 1))
        assert cita in tramo, f"la cita del paso {numero} no es literal"
        pasos.append(
            PasoVideo(
                numero=numero,
                nombre=nombre,
                descripcion="",
                responsable=RESPONSABLE,
                t_inicio=por_id[primero].t_inicio,
                t_fin=por_id[ultimo].t_fin,
                cita=cita,
                fuente="audio",
                confianza="alta",
            )
        )
    return pasos


def construir(caido: bool) -> ReporteValidacion:
    """El reporte del ejemplo; con `caido`, el juez no responde y el reporte es provisional."""
    settings = Settings(_env_file=None)
    analisis = Analisis.model_validate_json(
        (FIXTURES / "analisis_ejemplo.json").read_text(encoding="utf-8")
    )
    sop = sop_del_ejemplo()
    pasos = pasos_del_video(analisis)
    embedder = emp.Embedder(
        "vectorizador-guionado", RAIZ, cargador=lambda m, c: VectorizadorGuionado()
    )
    with mock.patch.object(emp, "get_settings", lambda: settings):
        resultado = emp.emparejar(
            sop,
            pasos,
            embedder,
            juez=JuezGuionado(caido),
            transcripcion=analisis.transcripcion,
        )
    # segundos_juez depende del reloj: el ejemplo lleva un valor fijo.
    resumen = resultado.clasificacion.resumen.model_copy(update={"segundos_juez": 2.4})
    resultado = resultado.model_copy(
        update={"clasificacion": resultado.clasificacion.model_copy(update={"resumen": resumen})}
    )
    segmentacion = Segmentacion(pasos, "llm", None, settings.llm_model, 1, 1)
    pct = porcentaje(resultado)
    validacion = ResultadoValidacion(
        resultado=resultado,
        cumplimiento=pct,
        semaforo=semaforo(pct, settings),
        metadatos=MetadatosValidacion(
            segmentacion="llm",
            modelo_llm=settings.llm_model,
            embedder=settings.embedder_model,
            umbrales=Umbrales(
                bajo=settings.umbral_bajo,
                alto=settings.umbral_alto,
                fusion=settings.umbral_fusion,
                semaforo_verde=settings.semaforo_verde,
                semaforo_amarillo=settings.semaforo_amarillo,
            ),
            segundos=SEGUNDOS,
            avisos=avisos_de(segmentacion, resultado),
            # Equipo de ejemplo: Whisper y Gemma en la GPU, MiniLM en CPU (ADR-018).
            dispositivos=Dispositivos(
                gpu="GPU de ejemplo", transcripcion="gpu", llm="gpu", embedder="cpu"
            ),
        ),
    )
    return armar_reporte(
        validacion,
        sop,
        video_id=1,
        sop_id=1,
        codigo="SOP-0001",
        cumplimiento=round(pct, 2),
        creado=CREADO,
    )


def serializar(reporte: ReporteValidacion) -> str:
    return json.dumps(reporte.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"


def textos() -> dict[str, str]:
    return {
        "definitivo": serializar(construir(caido=False)),
        "provisional": serializar(construir(caido=True)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--comprobar", action="store_true", help="no escribe; falla si algún archivo difiere"
    )
    args = parser.parse_args()
    desactualizados = 0
    for clave, texto in textos().items():
        destino = SALIDAS[clave]
        actual = destino.read_text(encoding="utf-8") if destino.exists() else None
        if args.comprobar:
            if actual != texto:
                print(f"{destino} está desactualizado: corre scripts/ejemplo_reporte.py")
                desactualizados += 1
            continue
        destino.write_text(texto, encoding="utf-8", newline="\n")
        print(f"{'sin cambios' if actual == texto else 'escrito'}: {destino}")
    return 1 if desactualizados else 0


if __name__ == "__main__":
    sys.exit(main())
