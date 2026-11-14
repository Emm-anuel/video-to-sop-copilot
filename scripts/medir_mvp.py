r"""Mide el criterio del MVP de validación (plan §5.1) con repeticiones y deja la evidencia.

Criterio, el mismo de `scripts/medir_dispositivos.py` (`criterio`): el video sin pasos
omitidos debe dar verde (≥ `SEMAFORO_VERDE`) y sin *Falta*; el que omite pasos debe dar
exactamente esas *Falta* y cada paso agregado como *Sobra* dentro de su tramo anotado. La intro y
el cierre del operador (ADR-016) no cuentan como *Sobra*.

Whisper es determinista (medido el 27 oct), así que cada video se transcribe una sola vez. Gemma
no lo es: con temperatura 0 y semilla fija, 1 de 3 corridas movió una frontera. Por eso la
validación (pasos con Gemma 4, emparejamiento con MiniLM y juez, porcentaje) se repite
`--repeticiones` veces por video, con el código de producción (`validar`) y descargando Gemma de
Ollama antes de cada una, como hace la API.

Además del criterio, cada corrida anota los *Sobra* falsos (fuera de los tramos agregados), si la
segmentación cayó a la heurística o salió con avisos (la corrida no es válida) y los segundos. El
informe registra el commit, si había cambios sin commit, los modelos, los umbrales y dónde corrió
cada modelo: el plan pide medir "con el commit registrado".

Uso, desde la raíz del repo, con el entorno activado y Ollama arriba:

    python scripts/medir_mvp.py --sop tests/fixtures/sop_filtro_agua.md \
        --anotacion media/anotacion_ab.json --repeticiones 3 \
        video_a=media/videos/VIDEO-A.mp4 video_b=media/videos/VIDEO-B.mp4

La clave antes del "=" es la de la anotación. Si la ruta termina en `.json`, se toma como un
`Analisis` ya calculado (p. ej. `media/video_a_v3/analisis.json`) y no se corre Whisper.

Salida en `data/interim/mvp/` (ignorada por git): `mvp-<fecha>.json` y `mvp-<fecha>.md`. Con
`--docs`, también en `docs/adr/datos/mvp/`: solo números de paso, segundos y estados, sin texto del
video ni del SOP. No modifica código, datos de entrada ni la base.

Código de salida: 0 si todas las corridas son válidas y pasan; 1 si alguna no pasa; 2 si alguna
no es válida (heurística o avisos), aunque las demás pasen.
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from medir_dispositivos import Esperado, criterio, esperado_de

from sopvid.contrato import AVISOS_INFORMATIVOS, SOP, Analisis, Dispositivos, ResultadoValidacion
from sopvid.lenguaje.juez import JuezGemma
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.lenguaje.validacion import DependenciasValidacion, validar
from sopvid.percepcion.pipeline import analizar_video
from sopvid.percepcion.transcripcion import AlSegmento, Transcripcion, TranscriptorWhisper
from sopvid.plataforma.config import PROJECT_ROOT, Settings, get_settings
from sopvid.plataforma.hardware import get_hardware

SALIDA = PROJECT_ROOT / "data" / "interim" / "mvp"
DOCS = PROJECT_ROOT / "docs" / "adr" / "datos" / "mvp"

logger = logging.getLogger("medir_mvp")


# ── Commit ───────────────────────────────────────────────────────────────────────────────────


def _git(*args: str, raiz: Path) -> str | None:
    try:
        salida = subprocess.run(
            ["git", *args], cwd=raiz, capture_output=True, text=True, check=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return salida.stdout.strip()


def estado_git(raiz: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Commit, rama y cuántos archivos versionados tenían cambios sin commit (sin contar los
    nuevos sin seguimiento). Si git no está o la carpeta no es un repo, todo va en None."""
    commit = _git("rev-parse", "HEAD", raiz=raiz)
    if commit is None:
        return {"commit": None, "rama": None, "cambios_sin_commit": None}
    cambios = _git("status", "--porcelain", "--untracked-files=no", raiz=raiz) or ""
    return {
        "commit": commit,
        "rama": _git("rev-parse", "--abbrev-ref", "HEAD", raiz=raiz),
        "cambios_sin_commit": len([linea for linea in cambios.splitlines() if linea.strip()]),
    }


# ── Una corrida ──────────────────────────────────────────────────────────────────────────────


def sobra_falsos(guardado: ResultadoValidacion, esperado: Esperado) -> list[float]:
    """Segundos de los *Sobra* fuera de los tramos de pasos agregados (sin intro ni cierre)."""
    return [
        f.t_inicio
        for f in guardado.resultado.clasificacion.pasos
        if f.estado == "Sobra"
        and f.marco_operador is None
        and f.t_inicio is not None
        and not any(a <= f.t_inicio < b for a, b in esperado.extras)
    ]


@dataclass
class Corrida:
    video: str
    repeticion: int
    cumplimiento: float | None = None
    semaforo: str | None = None
    conteo: dict[str, int] = field(default_factory=dict)
    criterio: dict[str, Any] = field(default_factory=dict)
    sobra_falsos: list[float] = field(default_factory=list)
    segmentacion: str | None = None
    avisos: list[str] = field(default_factory=list)
    segundos: float = 0.0
    dispositivos: dict[str, Any] = field(default_factory=dict)

    @property
    def valida(self) -> bool:
        return self.segmentacion == "llm" and not self.avisos

    @property
    def pasa(self) -> bool:
        return self.valida and bool(self.criterio.get("pasa"))


def anotar(
    corrida: Corrida,
    guardado: ResultadoValidacion,
    sop: SOP,
    esperado: Esperado,
    settings: Settings,
) -> Corrida:
    meta = guardado.metadatos
    corrida.cumplimiento = round(guardado.cumplimiento, 2)
    corrida.semaforo = guardado.semaforo
    corrida.conteo = dict(guardado.resultado.clasificacion.resumen.conteo)
    corrida.criterio = criterio(guardado, sop, esperado, settings)
    corrida.sobra_falsos = [round(t, 1) for t in sobra_falsos(guardado, esperado)]
    corrida.segmentacion = meta.segmentacion
    # Los informativos (p. ej. sin_imagen, ADR-024) no invalidan la corrida.
    corrida.avisos = [a.tipo for a in meta.avisos if a.tipo not in AVISOS_INFORMATIVOS]
    corrida.dispositivos = meta.dispositivos.model_dump() if meta.dispositivos else {}
    return corrida


class _Registrado:
    def __init__(self, base: TranscriptorWhisper):
        self._base, self.ultima = base, None

    def transcribir(
        self, audio: Path, idioma: str | None = None, al_segmento: AlSegmento | None = None
    ) -> Transcripcion:
        self.ultima = self._base.transcribir(audio, idioma, al_segmento=al_segmento)
        return self.ultima


def preparar(
    clave: str, ruta: Path, settings: Settings, trabajo: Path, idioma: str | None = None
) -> tuple[Analisis, dict[str, float], Dispositivos]:
    """El `Analisis` del video (o el ya guardado si `ruta` es un .json), los segundos de cada etapa
    y dónde corrió Whisper (None si no corrió)."""
    gpu = get_hardware().gpu
    nombre_gpu = None if gpu is None else gpu.nombre
    if ruta.suffix.lower() == ".json":
        analisis = Analisis.model_validate_json(ruta.read_text(encoding="utf-8"))
        return analisis, {}, Dispositivos(gpu=nombre_gpu)
    transcriptor = _Registrado(TranscriptorWhisper(settings))
    marcas: list[tuple[str, float]] = []

    def al_avanzar(etapa: str, _porcentaje: int) -> None:
        if not marcas or marcas[-1][0] != etapa:
            marcas.append((etapa, time.perf_counter()))

    carpeta = trabajo / clave
    carpeta.mkdir(parents=True, exist_ok=True)
    analisis = analizar_video(ruta, 0, idioma, transcriptor, carpeta, al_avanzar)
    segundos = {e: round(b - a, 2) for (e, a), (_, b) in itertools.pairwise(marcas)}
    t = transcriptor.ultima
    dispositivos = Dispositivos(
        gpu=nombre_gpu,
        transcripcion="gpu" if t and t.dispositivo == "cuda" else "cpu",
        transcripcion_respaldo_cpu=bool(t and t.respaldo_cpu),
    )
    return analisis, segundos, dispositivos


# ── Informe ──────────────────────────────────────────────────────────────────────────────────


def resumen(corridas: Sequence[Corrida]) -> dict[str, dict[str, Any]]:
    """Por video: cuántas corridas pasan, rango del porcentaje y semáforos vistos."""
    por_video: dict[str, dict[str, Any]] = {}
    for video, grupo in itertools.groupby(corridas, key=lambda c: c.video):
        grupo = list(grupo)
        porcentajes = [c.cumplimiento for c in grupo if c.cumplimiento is not None]
        por_video[video] = {
            "pasan": sum(c.pasa for c in grupo),
            "corridas": len(grupo),
            "no_validas": sum(not c.valida for c in grupo),
            "cumplimiento_min": min(porcentajes, default=None),
            "cumplimiento_max": max(porcentajes, default=None),
            "semaforos": sorted({c.semaforo for c in grupo if c.semaforo}),
        }
    return por_video


def veredicto(corridas: Sequence[Corrida]) -> str:
    if not corridas:
        return "sin corridas"
    if not all(c.valida for c in corridas):
        return "no válida"
    return "pasa" if all(c.pasa for c in corridas) else "no pasa"


def codigo_salida(corridas: Sequence[Corrida]) -> int:
    v = veredicto(corridas)
    return {"pasa": 0, "no pasa": 1}.get(v, 2)


def _f(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:g}"


def _lista(valores: Sequence[Any]) -> str:
    return ", ".join(str(v) for v in valores) or "—"


def informe(datos: dict[str, Any], corridas: Sequence[Corrida]) -> str:
    git, conf = datos["git"], datos["configuracion"]
    sin_commit = git["cambios_sin_commit"]
    lineas = [
        f"# Medición del MVP de validación · {datos['fecha']}",
        "",
        f"**Veredicto: {veredicto(corridas)}** · {len(corridas)} corridas "
        f"({datos['repeticiones']} por video).",
        "",
        "## Cómo se midió",
        "",
        f"- Commit `{git['commit'] or 'desconocido'}` en la rama `{git['rama'] or '—'}`"
        + (
            f" · **{sin_commit} archivo(s) con cambios sin commit**"
            if sin_commit
            else " · sin cambios sin commit"
            if sin_commit == 0
            else ""
        )
        + ".",
        f"- Whisper `{conf['whisper']}` · LLM `{conf['llm']}` · embedder `{conf['embedder']}`.",
        f"- Umbrales: bajo {conf['umbral_bajo']}, alto {conf['umbral_alto']}, fusión "
        f"{conf['umbral_fusion']}; semáforo verde ≥ {conf['semaforo_verde']}, amarillo ≥ "
        f"{conf['semaforo_amarillo']}.",
        f"- GPU: {conf['gpu'] or 'ninguna'}. Whisper corre una vez por video; la validación se "
        "repite y Gemma se descarga antes de cada corrida.",
        "- Criterio (plan §5.1): sin pasos omitidos → verde y sin *Falta*; con pasos omitidos → "
        "exactamente esas *Falta* y cada paso agregado como *Sobra* en su tramo. Intro y cierre "
        "(ADR-016) no cuentan.",
        "",
        "## Resumen por video",
        "",
        "| Video | Pasan | No válidas | Cumplimiento | Semáforo |",
        "|---|---|---|---|---|",
    ]
    for video, r in datos["resumen"].items():
        rango = (
            _f(r["cumplimiento_min"])
            if r["cumplimiento_min"] == r["cumplimiento_max"]
            else f"{_f(r['cumplimiento_min'])}–{_f(r['cumplimiento_max'])}"
        )
        lineas.append(
            f"| {video} | {r['pasan']}/{r['corridas']} | {r['no_validas']} | {rango} % | "
            f"{_lista(r['semaforos'])} |"
        )
    lineas += [
        "",
        "## Corridas",
        "",
        "| Video | # | % | Semáforo | Falta (esperada) | Agregados como Sobra | Sobra falsos (s) "
        "| Segmentación | Segundos | ¿Pasa? |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in corridas:
        cr = c.criterio
        motivo = _lista(c.avisos) if c.avisos else c.segmentacion
        nota = "" if c.valida else f" (no válida: {motivo})"
        lineas.append(
            f"| {c.video} | {c.repeticion} | {_f(c.cumplimiento)} | {c.semaforo or '—'} | "
            f"{_lista(cr.get('falta_obtenida', []))} ({_lista(cr.get('falta_esperada', []))}) | "
            f"{cr.get('extras_encontrados', '—')} | {_lista(c.sobra_falsos)} | "
            f"{c.segmentacion or '—'} | {c.segundos:.1f} | {'sí' if c.pasa else 'no'}{nota} |"
        )
    lineas += [
        "",
        "Los *Sobra* falsos no bajan el porcentaje, pero aparecen en la tabla del reporte "
        "(absorción pendiente de ADR-013).",
        "",
    ]
    return "\n".join(lineas)


# ── Principal ────────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+", help="clave=ruta del video o de su analisis.json")
    parser.add_argument("--sop", type=Path, required=True, help="SOP en Markdown (ADR-015)")
    parser.add_argument("--anotacion", type=Path, required=True, help="JSON de la anotación")
    parser.add_argument("--repeticiones", type=int, default=3, help="validaciones por video")
    parser.add_argument("--idioma", help="ISO 639-1 para Whisper; sin él, lo detecta")
    parser.add_argument(
        "--docs", action="store_true", help="copia el informe a docs/adr/datos/mvp/"
    )
    args = parser.parse_args(argv)
    if args.repeticiones < 1:
        parser.error("--repeticiones debe ser al menos 1")

    settings = get_settings()
    sop = convertir_sop(args.sop.read_text(encoding="utf-8")).sop
    anotaciones = json.loads(args.anotacion.read_text(encoding="utf-8"))
    entradas = []
    for par in args.videos:
        clave, _, ruta = par.partition("=")
        if clave not in anotaciones or not Path(ruta).is_file():
            parser.error(f"{par}: la clave no está en la anotación o el archivo no existe")
        entradas.append((clave, Path(ruta)))

    gpu = get_hardware().gpu
    marca = datetime.now().strftime("%Y%m%d-%H%M")
    llm = ClienteLLM.desde_settings(settings)
    corridas: list[Corrida] = []
    try:
        if not llm.disponible(10):
            print(f"Ollama no responde en {llm.base_url} o no tiene {llm.modelo}", file=sys.stderr)
            return 2
        for clave, ruta in entradas:
            print(f"{clave}: preparando el análisis…", file=sys.stderr)
            analisis, segundos, dispositivos = preparar(
                clave, ruta, settings, SALIDA / marca, args.idioma
            )
            esperado = esperado_de(anotaciones[clave], sop, analisis.duracion_s)
            for n in range(1, args.repeticiones + 1):
                llm.descargar()  # carga en frío en cada corrida, como en la API
                inicio = time.perf_counter()
                validacion = validar(
                    analisis,
                    sop,
                    DependenciasValidacion(llm, JuezGemma(llm)),
                    segundos_analisis=segundos,
                    dispositivos=dispositivos,
                )
                corrida = anotar(Corrida(clave, n), validacion.resultado, sop, esperado, settings)
                corrida.segundos = round(time.perf_counter() - inicio, 1)
                corridas.append(corrida)
                print(
                    f"  [{n}/{args.repeticiones}] {corrida.cumplimiento} % {corrida.semaforo}"
                    f" · Falta {corrida.criterio['falta_obtenida']}"
                    f" · Sobra falsos {len(corrida.sobra_falsos)}"
                    f" · {'pasa' if corrida.pasa else 'NO pasa'}",
                    file=sys.stderr,
                )
    finally:
        llm.close()

    datos = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "repeticiones": args.repeticiones,
        "git": estado_git(),
        "configuracion": {
            "whisper": settings.whisper_modelo,
            "llm": settings.llm_model,
            "embedder": settings.embedder_model,
            "umbral_bajo": settings.umbral_bajo,
            "umbral_alto": settings.umbral_alto,
            "umbral_fusion": settings.umbral_fusion,
            "semaforo_verde": settings.semaforo_verde,
            "semaforo_amarillo": settings.semaforo_amarillo,
            "gpu": None if gpu is None else gpu.nombre,
        },
        "veredicto": veredicto(corridas),
        "resumen": resumen(corridas),
        "corridas": [asdict(c) | {"valida": c.valida, "pasa": c.pasa} for c in corridas],
    }
    texto = informe(datos, corridas)
    for carpeta in [SALIDA] + ([DOCS] if args.docs else []):
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = f"mvp-{marca}"
        (carpeta / f"{nombre}.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n"
        )
        (carpeta / f"{nombre}.md").write_text(texto, "utf-8", newline="\n")
        print(f"  {carpeta / nombre}.md", file=sys.stderr)
    print(texto)
    return codigo_salida(corridas)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
