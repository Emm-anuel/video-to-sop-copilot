r"""Medición de la descripción opcional de imágenes (RF-11, ADR-024): A–E, con y sin imágenes,
con Gemma en GPU y en CPU.

Para cada video y dispositivo corre, con Gemma en frío (como en el procesador, que lo carga
después de soltar Whisper):

- **sin imágenes:** la ficha de contexto sola;
- **con imágenes:** N imágenes repartidas de forma pareja (`fotogramas.describir_fotogramas`, la
  misma N del procesamiento: los pasos del SOP para A–D, la duración para E) y la ficha con
  ellas.

Mide los segundos de cada etapa, los tokens y dónde quedó Gemma, y calcula:

- segundos por imagen "brutos" (lo que tarda la etapa de imágenes ÷ N) y "extra" (lo que suma
  describir: imágenes + ficha con imágenes − ficha sin imágenes, ÷ N). El extra es lo que promete
  `GET /videos/estimacion`, así que de él salen `SEG_IMAGEN_GPU` y `SEG_IMAGEN_CPU` (mediana);
- la estimación con los valores actuales de Settings contra el tiempo real;
- la ficha campo por campo y la afinidad (A–D, contra el SOP del filtro) con y sin imágenes;
- las descripciones, para revisarlas a mano (¿salen el equipo y el texto que deberían?).

Uso, desde la raíz del repo con el entorno activado, Ollama en GPU (docker-compose.gpu.yml,
profile llm) y sin otra API usando la GPU:

    python scripts/medir_imagenes.py                       # gpu y cpu, A–E
    python scripts/medir_imagenes.py --config gpu --video video_c

La transcripción de cada video se hace una vez con Whisper y se guarda en `data/interim/imagenes/`
(ignorada por git); las siguientes corridas la reusan. El informe va a
`docs/adr/datos/imagenes/medicion-imagenes-<fecha>.{md,json}`. Los videos son del equipo, no del
cliente; el informe no lleva imágenes, solo texto, números y conteos de personas (sin nombres ni
rasgos). No modifica código, datos de entrada ni la base.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from medir_contexto import comparar as comparar_fichas
from medir_mvp import estado_git, preparar
from medir_sop_generado import confirmar_dispositivo

from sopvid.contrato import SOP, Analisis, Contexto
from sopvid.lenguaje.afinidad import afinidad
from sopvid.lenguaje.emparejamiento import get_embedder
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.percepcion.contexto import generar_contexto
from sopvid.percepcion.fotogramas import PROMPT, cuantas_imagenes, describir_fotogramas
from sopvid.plataforma.config import PROJECT_ROOT, Settings, get_settings

SALIDA = PROJECT_ROOT / "data" / "interim" / "imagenes"
DOCS = PROJECT_ROOT / "docs" / "adr" / "datos" / "imagenes"
SOP_REFERENCIA = PROJECT_ROOT / "tests" / "fixtures" / "sop_filtro_agua.md"
VIDEOS = {
    "video_a": PROJECT_ROOT / "media" / "videos" / "VIDEO-A.mp4",
    "video_b": PROJECT_ROOT / "media" / "videos" / "VIDEO-B.mp4",
    "video_c": PROJECT_ROOT / "data" / "synthetic" / "video_c" / "VIDEO-C.mp4",
    "video_d": PROJECT_ROOT / "data" / "synthetic" / "video_d" / "VIDEO-D.mp4",
    "video_e": PROJECT_ROOT / "data" / "synthetic" / "video_e" / "VIDEO-E.mp4",
}
GENERAR = {"video_e"}
IDIOMA = {"video_e": "en"}
CONFIGS = ("gpu", "cpu")

logger = logging.getLogger("medir_imagenes")


# ── Una corrida ──────────────────────────────────────────────────────────────────────────────


@dataclass
class Corrida:
    """Una combinación video × dispositivo × con o sin imágenes."""

    video: str
    config: str
    con_imagenes: bool
    imagenes_pedidas: int = 0
    imagenes_descritas: int = 0
    segundos_fotogramas: float = 0.0
    segundos_contexto: float = 0.0
    tokens_entrada_imagenes: int | None = None
    tokens_salida_imagenes: int | None = None
    lotes: int = 0
    llamadas_imagenes: int = 0
    motivo_imagenes: str | None = None
    dispositivo_llm: str = "desconocido"
    contexto_generado: bool = False
    ficha: dict[str, Any] = field(default_factory=dict)
    afinidad: int | None = None
    afinidad_componentes: dict[str, int] = field(default_factory=dict)
    descripciones: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def correr(
    clave: str,
    video: Path,
    analisis: Analisis,
    config: str,
    con_imagenes: bool,
    settings: Settings,
    sop: SOP | None,
    trabajo: Path,
) -> Corrida:
    """Una corrida con Gemma en frío: [imágenes →] ficha; después, la afinidad (sin Gemma)."""
    corrida = Corrida(video=clave, config=config, con_imagenes=con_imagenes)
    modo = "generar" if clave in GENERAR else "validar"
    n = cuantas_imagenes(modo, len(sop.pasos) if sop else None, analisis.duracion_s, settings)
    with ClienteLLM.desde_settings(settings) as llm:
        llm.descargar()  # en frío, como después de Whisper
        try:
            if con_imagenes:
                inicio = time.perf_counter()
                r = describir_fotogramas(
                    video, trabajo / f"{clave}-{config}", analisis.duracion_s, n, llm,
                    settings=settings,
                )  # fmt: skip
                corrida.segundos_fotogramas = round(time.perf_counter() - inicio, 2)
                corrida.imagenes_pedidas, corrida.imagenes_descritas = n, r.descritas
                corrida.tokens_entrada_imagenes = r.tokens_entrada
                corrida.tokens_salida_imagenes = r.tokens_salida
                corrida.lotes, corrida.llamadas_imagenes = r.lotes, r.llamadas
                corrida.motivo_imagenes = r.motivo
                corrida.descripciones = [f.model_dump(mode="json") for f in r.fotogramas]
                analisis = analisis.model_copy(update={"fotogramas": r.fotogramas})
            inicio = time.perf_counter()
            rc = generar_contexto(analisis, llm)
            corrida.segundos_contexto = round(time.perf_counter() - inicio, 2)
            corrida.contexto_generado = rc.generado
            corrida.ficha = rc.contexto.model_dump(mode="json")
        finally:
            corrida.dispositivo_llm = llm.dispositivo_cargado()
            llm.descargar()
    if sop is not None and corrida.contexto_generado:
        a = afinidad(sop, Contexto.model_validate(corrida.ficha), get_embedder(), settings)
        if a is not None:
            corrida.afinidad, corrida.afinidad_componentes = a.valor, dict(a.componentes)
    return corrida


# ── Cálculos (puros) ─────────────────────────────────────────────────────────────────────────


def por_imagen(con: Corrida, sin: Corrida) -> dict[str, float | None]:
    """Segundos por imagen brutos y extra (lo que suma describir contra la ficha sola)."""
    n = con.imagenes_pedidas
    if not n:
        return {"bruto": None, "extra": None, "extra_total": None}
    extra = con.segundos_fotogramas + con.segundos_contexto - sin.segundos_contexto
    return {
        "bruto": round(con.segundos_fotogramas / n, 2),
        "extra": round(extra / n, 2),
        "extra_total": round(extra, 1),
    }


def pares(corridas: Sequence[Corrida]) -> list[tuple[Corrida, Corrida]]:
    """(con, sin) de cada video × dispositivo que tenga las dos corridas sin error."""
    sin = {(c.video, c.config): c for c in corridas if not c.con_imagenes and not c.error}
    return [
        (c, sin[(c.video, c.config)])
        for c in corridas
        if c.con_imagenes and not c.error and (c.video, c.config) in sin
    ]


def recomendacion(corridas: Sequence[Corrida]) -> dict[str, float | None]:
    """`SEG_IMAGEN_GPU` y `SEG_IMAGEN_CPU`: la mediana del extra por imagen de cada dispositivo,
    a un decimal (None si no hay corridas de ese dispositivo)."""
    valores: dict[str, list[float]] = {c: [] for c in CONFIGS}
    for con, sin in pares(corridas):
        extra = por_imagen(con, sin)["extra"]
        if extra is not None:
            valores[con.config].append(extra)
    return {
        f"seg_imagen_{c}": round(max(statistics.median(v), 0.0), 1) if v else None
        for c, v in valores.items()
    }


def estimacion(con: Corrida, sin: Corrida, seg_imagen: float) -> dict[str, float]:
    """La estimación de `GET /videos/estimacion` con `seg_imagen` contra el extra real."""
    estimado = round(con.imagenes_pedidas * seg_imagen, 1)
    real = por_imagen(con, sin)["extra_total"] or 0.0
    return {"estimado": estimado, "real": real, "error": round(estimado - real, 1)}


# ── Informe ──────────────────────────────────────────────────────────────────────────────────


def _f(valor: Any) -> str:
    if valor is None:
        return "—"
    return f"{valor:g}" if isinstance(valor, float) else str(valor)


def _lista(valores: Sequence[Any]) -> str:
    return "; ".join(str(v) for v in valores) if valores else "—"


def informe(datos: dict[str, Any]) -> str:
    corridas = [Corrida(**c) for c in datos["corridas"]]
    ajustes = datos["settings"]
    rec = recomendacion(corridas)
    lineas = [
        "# Medición de la descripción de imágenes (ADR-024)",
        "",
        f"{datos['fecha']} · git `{datos['git'].get('commit')}`"
        f"{' (con cambios sin commit)' if datos['git'].get('cambios_sin_commit') else ''} · "
        f"prompt `{PROMPT}` · "
        f"lote {ajustes['fotogramas_lote']} · lado {ajustes['fotogramas_lado_px']} px · "
        f"`{ajustes['llm_model']}`. Videos del equipo (no del cliente). Gemma en frío en "
        "cada corrida, como en el procesador. Una corrida por combinación.",
        "",
        "## Tiempo y estimación",
        "",
        "Extra = imágenes + ficha con imágenes − ficha sin imágenes: lo que suma encender la "
        "opción. La estimación usa los `SEG_IMAGEN_*` de Settings al medir "
        f"(GPU {ajustes['seg_imagen_gpu']} s, CPU {ajustes['seg_imagen_cpu']} s).",
        "",
        "| Video | Dispositivo | N (descritas) | Imágenes s | Ficha con / sin s | Extra s | "
        "s por imagen (bruto / extra) | Estimado s | Error s | Tokens entrada / salida |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for con, sin in pares(corridas):
        pi = por_imagen(con, sin)
        est = estimacion(con, sin, ajustes[f"seg_imagen_{con.config}"])
        lineas.append(
            f"| {con.video} | {con.config} ({con.dispositivo_llm}) | {con.imagenes_pedidas} "
            f"({con.imagenes_descritas}) | {_f(con.segundos_fotogramas)} | "
            f"{_f(con.segundos_contexto)} / {_f(sin.segundos_contexto)} | "
            f"{_f(pi['extra_total'])} | "
            f"{_f(pi['bruto'])} / {_f(pi['extra'])} | {_f(est['estimado'])} | {_f(est['error'])} | "
            f"{_f(con.tokens_entrada_imagenes)} / {_f(con.tokens_salida_imagenes)} |"
        )
    lineas += [
        "",
        "**Recomendación (mediana del extra por imagen):** "
        f"`SEG_IMAGEN_GPU={_f(rec['seg_imagen_gpu'])}`, "
        f"`SEG_IMAGEN_CPU={_f(rec['seg_imagen_cpu'])}`.",
        "",
        "## Ficha y afinidad con y sin imágenes",
        "",
        "| Video | Dispositivo | Afinidad sin → con | Datos con fuente visual | "
        "Equipos solo sin / solo con "
        "| Mismas personas | Datos que cambian de valor |",
        "|---|---|---|---|---|---|---|",
    ]
    for con, sin in pares(corridas):
        if not (con.contexto_generado and sin.contexto_generado):
            lineas.append(f"| {con.video} | {con.config} | ficha sin generar | | | | |")
            continue
        comp = comparar_fichas(sin.ficha, con.ficha)
        visuales = [k for k, v in comp["datos"].items() if v["fuente"][1] == "visual"]
        cambian = [k for k, v in comp["datos"].items() if not v["mismo_valor"]]
        solo_sin, solo_con = comp["equipos_solo"]
        lineas.append(
            f"| {con.video} | {con.config} | {_f(sin.afinidad)} → {_f(con.afinidad)} | "
            f"{_lista(visuales)} | {_lista(solo_sin)} / {_lista(solo_con)} | "
            f"{'sí' if comp['mismas_personas'] else 'no'} | {_lista(cambian)} |"
        )
    lineas += [
        "",
        "## Descripciones (para revisar a mano)",
        "",
        "Cada imagen con su segundo (puesto por el código), personas (conteo), equipos, texto "
        "legible y riesgos.",
    ]
    for c in corridas:
        if not c.con_imagenes or c.error:
            continue
        lineas += ["", f"### {c.video} · {c.config}", ""]
        lineas += ["| t s | Descripción | Personas | Equipos | Texto visible | Riesgos |"]
        lineas += ["|---|---|---|---|---|---|"]
        for d in c.descripciones:
            lineas.append(
                f"| {d['t']:g} | {d['descripcion']} | {d['personas']} | {_lista(d['equipos'])} | "
                f"{_lista(d['texto_visible'])} | {_lista(d['riesgos'])} |"
            )
    errores = [c for c in corridas if c.error]
    if errores:
        lineas += ["", "## Errores", ""]
        lineas += [
            f"- {c.video} · {c.config} · imágenes {c.con_imagenes}: {c.error}" for c in errores
        ]
    return "\n".join(lineas) + "\n"


# ── Principal ────────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", action="append", choices=CONFIGS, help="gpu, cpu o las dos")
    parser.add_argument(
        "--video", action="append", choices=sorted(VIDEOS), help="por defecto C, D, E"
    )
    parser.add_argument("--salida", type=Path, default=DOCS)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    configs = args.config or list(CONFIGS)
    claves = args.video or sorted(VIDEOS)
    base = get_settings()
    sop = convertir_sop(SOP_REFERENCIA.read_text(encoding="utf-8")).sop
    SALIDA.mkdir(parents=True, exist_ok=True)

    analisis: dict[str, Analisis] = {}
    for clave in claves:
        guardado = SALIDA / f"{clave}.analisis.json"
        if guardado.is_file():
            analisis[clave] = Analisis.model_validate_json(guardado.read_text(encoding="utf-8"))
            continue
        with tempfile.TemporaryDirectory() as trabajo:
            a, _, _ = preparar(clave, VIDEOS[clave], base, Path(trabajo), IDIOMA.get(clave))
        guardado.write_text(a.model_dump_json(), encoding="utf-8")
        analisis[clave] = a

    corridas: list[Corrida] = []
    with tempfile.TemporaryDirectory() as trabajo:
        for config in configs:
            settings = base.model_copy(
                update={"llm_dispositivo": "cpu" if config == "cpu" else "auto"}
            )
            with ClienteLLM.desde_settings(settings) as llm:
                confirmar_dispositivo(llm, pedido_cpu=config == "cpu")
            for clave in claves:
                for con in (False, True):
                    logger.info("%s · %s · %s imágenes", clave, config, "con" if con else "sin")
                    try:
                        corridas.append(
                            correr(
                                clave,
                                VIDEOS[clave],
                                analisis[clave],
                                config,
                                con,
                                settings,
                                None if clave in GENERAR else sop,
                                Path(trabajo),
                            )  # fmt: skip
                        )
                    except Exception as exc:
                        logger.exception("Corrida fallida")
                        corridas.append(
                            Corrida(
                                video=clave,
                                config=config,
                                con_imagenes=con,
                                error=type(exc).__name__,
                            )  # fmt: skip
                        )

    publicos = (
        "llm_model", "fotogramas_lote", "fotogramas_lado_px", "fotogramas_min", "fotogramas_max",
        "pasos_por_min", "seg_imagen_gpu", "seg_imagen_cpu", "llm_num_ctx",
    )  # fmt: skip
    datos = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "git": estado_git(),
        "settings": {k: getattr(base, k) for k in publicos},
        "corridas": [asdict(c) for c in corridas],
        "recomendacion": recomendacion(corridas),
    }
    args.salida.mkdir(parents=True, exist_ok=True)
    nombre = f"medicion-imagenes-{datetime.now():%Y%m%d-%H%M}"
    (args.salida / f"{nombre}.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.salida / f"{nombre}.md").write_text(informe(datos), encoding="utf-8")
    print(f"Informe: {args.salida / nombre}.md")
    return 1 if any(c.error for c in corridas) else 0


if __name__ == "__main__":
    sys.exit(main())
