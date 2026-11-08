r"""Mide Whisper en CPU contra la referencia en GPU y su efecto en la ficha y los pasos (ADR-018).

Por video y configuración: segundos de Whisper (con la carga del modelo), factor de tiempo real
(segundos / duración del audio), RAM pico del proceso que transcribe y WER aproximado contra la
transcripción de referencia (`large-v3-turbo` en cuda, float16). Después corre la ruta completa
(`validar` contra `--sop`: ficha → pasos → emparejamiento) con Gemma en el dispositivo de la
configuración, y cuenta qué tramos que difieren de la referencia llegan a la ficha o a los pasos.

Configuraciones (`--config`, se puede repetir; por defecto todas):

- `referencia`: `large-v3-turbo` en cuda, float16; Gemma en GPU (la ruta de GPU).
- `turbo-int8`: `large-v3-turbo` en CPU, int8; Gemma en CPU.
- `turbo-int8_float32`: `large-v3-turbo` en CPU, int8_float32; Gemma en CPU.
- `small-int8`: `small` en CPU, int8 (el valor por defecto en CPU hoy); Gemma en CPU.

Cada transcripción corre en un subproceso para que la RAM pico sea solo la de esa configuración.
El WER se calcula por palabras, normalizadas como las citas (`sopvid.texto.comparable`: sin
acentos, mayúsculas ni puntuación), así que es aproximado: no castiga la puntuación ni los
acentos. Un tramo "afecta" a la ficha o a un paso si alguna de sus palabras nuevas (las que no
existen en la transcripción de referencia) aparece ahí. Se compara por palabra y no por frase
porque Gemma a veces corrige lo que cita en el valor: Whisper `small` dijo "clínica del jugue" y
la ficha dijo "Clínica del jugo".

`--reanalizar whisper-<fecha>` recalcula WER, tramos y afectados con las transcripciones y las
fichas ya guardadas en `data/interim/whisper/`, sin volver a transcribir ni a llamar a Gemma.

Uso, desde la raíz del repo, con el entorno activado (extra `gpu`) y Ollama arriba:

    python scripts/medir_whisper.py --sop tests/fixtures/sop_filtro_agua.md \
        video_a=media/videos/VIDEO-A.mp4 video_b=media/videos/VIDEO-B.mp4

Salida en `data/interim/whisper/` (ignorada por git): `whisper-<fecha>.json` y `.md`, y las
transcripciones de cada configuración en `whisper-<fecha>/`. Con `--docs`, el informe (sin las
transcripciones completas) también en `docs/adr/datos/whisper/`. Solo con videos del equipo.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from medir_mvp import estado_git

from sopvid.contrato import SOP, Analisis, Idioma, Segmento
from sopvid.lenguaje.juez import JuezGemma
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.lenguaje.validacion import DependenciasValidacion, validar
from sopvid.percepcion.medios import duracion, extraer_audio
from sopvid.percepcion.pipeline import DECIMALES, _recortar_a_duracion
from sopvid.percepcion.transcripcion import TranscriptorWhisper, resegmentar
from sopvid.plataforma.config import PROJECT_ROOT, get_settings
from sopvid.texto import comparable, contiene_cita

SALIDA = PROJECT_ROOT / "data" / "interim" / "whisper"
DOCS = PROJECT_ROOT / "docs" / "adr" / "datos" / "whisper"
REFERENCIA = "referencia"

CONFIGS: dict[str, dict[str, str]] = {
    REFERENCIA: {"modelo": "large-v3-turbo", "dispositivo": "cuda", "compute": "float16",
                 "llm": "auto"},
    "turbo-int8": {"modelo": "large-v3-turbo", "dispositivo": "cpu", "compute": "int8",
                   "llm": "cpu"},
    "turbo-int8_float32": {"modelo": "large-v3-turbo", "dispositivo": "cpu",
                           "compute": "int8_float32", "llm": "cpu"},
    "small-int8": {"modelo": "small", "dispositivo": "cpu", "compute": "int8", "llm": "cpu"},
}  # fmt: skip

logger = logging.getLogger("medir_whisper")


# ── Subproceso: una transcripción ────────────────────────────────────────────────────────────


def _ram_pico_mb() -> float | None:
    """RAM pico de este proceso (working set en Windows, ru_maxrss en Linux)."""
    try:
        import psutil

        info = psutil.Process().memory_info()
        pico = getattr(info, "peak_wset", None)
        if pico is not None:
            return round(pico / 2**20, 1)
    except ImportError:
        pass
    try:
        import resource

        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except ImportError:
        return None


def transcribir_aqui(audio: Path, config: str, salida: Path) -> None:
    """Corre en el subproceso: transcribe con `config` y escribe el resultado en `salida`."""
    c = CONFIGS[config]
    settings = get_settings().model_copy(
        update={
            "whisper_modelo": c["modelo"],
            "whisper_modelo_cpu": None,
            "whisper_dispositivo": c["dispositivo"],
            "whisper_compute_type": c["compute"],
        }
    )
    t = TranscriptorWhisper(settings).transcribir(audio)
    datos = {
        "idioma": t.idioma.model_dump(mode="json"),
        "segmentos": [s.model_dump(mode="json") for s in t.segmentos],
        "modelo": t.modelo,
        "dispositivo": t.dispositivo,
        "compute_type": t.compute_type,
        "respaldo_cpu": t.respaldo_cpu,
        "segundos": t.segundos,
        "ram_pico_mb": _ram_pico_mb(),
    }
    salida.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def transcribir_en_subproceso(audio: Path, config: str, salida: Path) -> dict[str, Any]:
    subprocess.run(
        [sys.executable, __file__, "--transcribir", str(audio), "--config", config,
         "--salida", str(salida)],
        check=True,
    )  # fmt: skip
    return json.loads(salida.read_text(encoding="utf-8"))


# ── WER y tramos que difieren ────────────────────────────────────────────────────────────────


def palabras(segmentos: list[Segmento]) -> list[str]:
    return comparable(" ".join(s.texto for s in segmentos)).split()


def alinear(ref: list[str], hip: list[str]) -> tuple[int, list[tuple[str, str]]]:
    """Distancia de edición por palabras y los tramos que difieren, como (ref, hip)."""
    n, m = len(ref), len(hip)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            costo = 0 if ref[i - 1] == hip[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + costo)
    # Recorrido hacia atrás: agrupa las operaciones distintas de "igual" en tramos.
    tramos: list[tuple[list[str], list[str]]] = []
    actual: tuple[list[str], list[str]] | None = None
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hip[j - 1] and d[i][j] == d[i - 1][j - 1]:
            actual = None
            i, j = i - 1, j - 1
            continue
        if actual is None:
            actual = ([], [])
            tramos.append(actual)
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + 1:
            actual[0].insert(0, ref[i - 1])
            actual[1].insert(0, hip[j - 1])
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            actual[0].insert(0, ref[i - 1])
            i -= 1
        else:
            actual[1].insert(0, hip[j - 1])
            j -= 1
    tramos.reverse()
    return d[n][m], [(" ".join(a), " ".join(b)) for a, b in tramos]


def textos_de_la_ficha(ficha: dict[str, Any]) -> dict[str, str]:
    textos = {
        campo: ficha[campo]["valor"] or ""
        for campo in ("actividad", "tema", "lugar", "horario_mencionado", "proposito", "resumen")
    }
    for n, p in enumerate(ficha["personas"], start=1):
        textos[f"persona {n}"] = " ".join(x for x in (p["nombre"], p["rol"] or "", p["cita"]) if x)
    for e in ficha["equipos"]:
        textos[f"equipo {e['nombre']}"] = e["nombre"]
    return textos


def textos_de_los_pasos(pasos: list[dict[str, Any]]) -> dict[str, str]:
    return {f"paso {p['numero']}": f"{p['nombre']} {p['descripcion']} {p['cita']}" for p in pasos}


def afectados(
    tramos: list[tuple[str, str]], vocabulario: set[str], textos: dict[str, str]
) -> list[dict[str, Any]]:
    """Tramos con alguna palabra nueva (fuera de `vocabulario`) que aparece en algún texto."""
    salida = []
    for ref, hip in tramos:
        nuevas = [p for p in hip.split() if p not in vocabulario]
        donde = [
            clave
            for clave, texto in textos.items()
            if any(contiene_cita(texto, palabra) for palabra in nuevas)
        ]
        if donde:
            salida.append({"referencia": ref, "whisper": hip, "en": donde})
    return salida


# ── Corrida ──────────────────────────────────────────────────────────────────────────────────


@dataclass
class Corrida:
    video: str
    config: str
    modelo: str
    dispositivo: str
    compute_type: str
    llm_dispositivo: str = "desconocido"
    duracion_audio_s: float = 0.0
    segundos_whisper: float = 0.0
    factor_tiempo_real: float = 0.0
    ram_pico_mb: float | None = None
    palabras: int = 0
    wer: float | None = None
    tramos_distintos: int = 0
    afectan_ficha: list[dict[str, Any]] = field(default_factory=list)
    afectan_pasos: list[dict[str, Any]] = field(default_factory=list)
    segundos_etapas: dict[str, float] = field(default_factory=dict)
    cumplimiento: float | None = None
    avisos: list[str] = field(default_factory=list)
    ficha: dict[str, Any] = field(default_factory=dict)
    pasos: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_s(self) -> float:
        return round(sum(self.segundos_etapas.values()), 1)


def medir_video(
    clave: str, video: Path, configs: list[str], sop: SOP, carpeta: Path
) -> list[Corrida]:
    base = get_settings()
    trabajo = carpeta / clave
    trabajo.mkdir(parents=True, exist_ok=True)
    inicio = time.perf_counter()
    duracion_s = round(duracion(video), DECIMALES)
    segundos_duracion = time.perf_counter() - inicio
    inicio = time.perf_counter()
    audio = extraer_audio(video, trabajo / "audio.mp3")
    segundos_audio = time.perf_counter() - inicio

    corridas: list[Corrida] = []
    referencia: list[str] | None = None
    for config in configs:
        c = CONFIGS[config]
        llm = ClienteLLM.desde_settings(base.model_copy(update={"llm_dispositivo": c["llm"]}))
        try:
            llm.descargar()  # Whisper y Gemma nunca a la vez (ADR-014)
            print(f"{clave} · {config}: transcribiendo…", file=sys.stderr)
            t = transcribir_en_subproceso(audio, config, trabajo / f"{config}.json")
            crudos = [Segmento.model_validate(s) for s in t["segmentos"]]
            segmentos = [s.model_dump() for s in resegmentar(crudos)]
            _recortar_a_duracion(segmentos, duracion_s)
            analisis = Analisis.model_validate(
                {
                    "video_id": 0,
                    "duracion_s": duracion_s,
                    "idioma": Idioma.model_validate(t["idioma"]).model_dump(),
                    "transcripcion": segmentos,
                    "modelo_transcripcion": t["modelo"],
                }
            )
            corrida = Corrida(clave, config, t["modelo"], t["dispositivo"], t["compute_type"])
            corrida.duracion_audio_s = duracion_s
            corrida.segundos_whisper = t["segundos"]
            corrida.factor_tiempo_real = round(t["segundos"] / duracion_s, 3)
            corrida.ram_pico_mb = t["ram_pico_mb"]
            hip = palabras(analisis.transcripcion)
            corrida.palabras = len(hip)
            print(f"{clave} · {config}: validando…", file=sys.stderr)
            validacion = validar(
                analisis,
                sop,
                DependenciasValidacion(llm, JuezGemma(llm)),
                segundos_analisis={
                    "duracion": round(segundos_duracion, 2),
                    "audio": round(segundos_audio, 2),
                    "transcripcion": t["segundos"],
                },
            )
        finally:
            llm.close()
        meta = validacion.resultado.metadatos
        corrida.llm_dispositivo = meta.dispositivos.llm if meta.dispositivos else "desconocido"
        corrida.segundos_etapas = dict(meta.segundos)
        corrida.cumplimiento = round(validacion.resultado.cumplimiento, 2)
        corrida.avisos = [a.tipo for a in meta.avisos]
        corrida.ficha = validacion.contexto.model_dump(mode="json")
        corrida.pasos = [p.model_dump(mode="json") for p in validacion.pasos_video]
        if config == REFERENCIA:
            referencia = hip
        if referencia is not None:
            distancia, tramos = alinear(referencia, hip)
            corrida.wer = round(distancia / len(referencia), 4) if referencia else None
            corrida.tramos_distintos = len(tramos)
            vocabulario = set(referencia)
            corrida.afectan_ficha = afectados(
                tramos, vocabulario, textos_de_la_ficha(corrida.ficha)
            )
            corrida.afectan_pasos = afectados(
                tramos, vocabulario, textos_de_los_pasos(corrida.pasos)
            )
        corridas.append(corrida)
        print(
            f"  {corrida.segundos_whisper} s de Whisper (x{corrida.factor_tiempo_real} tiempo real)"
            f" · RAM {corrida.ram_pico_mb} MB · WER {corrida.wer} · total {corrida.total_s} s",
            file=sys.stderr,
        )
    return corridas


def reanalizar(marca: str) -> tuple[dict[str, Any], list[Corrida]]:
    """Recalcula WER, tramos y afectados de una medición guardada (ver el docstring)."""
    datos = json.loads((SALIDA / f"{marca}.json").read_text(encoding="utf-8"))
    corridas = []
    referencias: dict[str, list[str]] = {}
    for d in datos["corridas"]:
        d = {k: v for k, v in d.items() if k != "total_s"}
        c = Corrida(**d)
        guardada = json.loads(
            (SALIDA / marca / c.video / f"{c.config}.json").read_text(encoding="utf-8")
        )
        crudos = [Segmento.model_validate(s) for s in guardada["segmentos"]]
        hip = palabras(resegmentar(crudos))
        if c.config == REFERENCIA:
            referencias[c.video] = hip
        ref = referencias[c.video]
        distancia, tramos = alinear(ref, hip)
        c.wer = round(distancia / len(ref), 4) if ref else None
        c.tramos_distintos = len(tramos)
        c.afectan_ficha = afectados(tramos, set(ref), textos_de_la_ficha(c.ficha))
        c.afectan_pasos = afectados(tramos, set(ref), textos_de_los_pasos(c.pasos))
        corridas.append(c)
    datos["corridas"] = [asdict(c) | {"total_s": c.total_s} for c in corridas]
    datos["reanalizado"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return datos, corridas


# ── Informe ──────────────────────────────────────────────────────────────────────────────────


def _f(valor: Any) -> str:
    if valor is None:
        return "—"
    return f"{valor:g}" if isinstance(valor, float) else str(valor)


def informe(datos: dict[str, Any], corridas: list[Corrida]) -> str:
    git = datos["git"]
    lineas = [
        f"# Whisper en CPU contra la referencia en GPU · {datos['fecha']}",
        "",
        f"- Commit `{git['commit'] or 'desconocido'}` en `{git['rama'] or '—'}` al empezar"
        + (f" · {git['cambios_sin_commit']} archivo(s) sin commit" if git["cambios_sin_commit"]
           else "")
        + f". CPU: {datos['cpu']}; GPU: {datos['gpu'] or 'ninguna'}; LLM `{datos['llm']}`.",
        "- WER aproximado por palabras normalizadas (sin acentos ni puntuación) contra "
        "`referencia` (large-v3-turbo en cuda, float16).",
        "- Total = duración + audio + Whisper (con su carga) + ficha + pasos + emparejamiento.",
        "",
        "## Whisper",
        "",
        "| Video | Config | Modelo · dispositivo · compute | Whisper (s) | × tiempo real "
        "| RAM pico (MB) | Palabras | WER | Tramos distintos | Afectan ficha | Afectan pasos |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for c in corridas:
        lineas.append(
            f"| {c.video} | {c.config} | {c.modelo} · {c.dispositivo} · {c.compute_type} | "
            f"{_f(c.segundos_whisper)} | {_f(c.factor_tiempo_real)} | {_f(c.ram_pico_mb)} | "
            f"{c.palabras} | {_f(c.wer)} | {c.tramos_distintos} | {len(c.afectan_ficha)} | "
            f"{len(c.afectan_pasos)} |"
        )
    lineas += [
        "",
        "## Ruta completa (segundos por etapa)",
        "",
        "| Video | Config | Gemma | transcripcion | contexto | segmentacion | emparejamiento | "
        "Total | Total / referencia de CPU (small) | Cumplimiento | Avisos |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in corridas:
        small = next((x for x in corridas if x.video == c.video and x.config == "small-int8"), None)
        razon = f"{c.total_s / small.total_s:.2f}" if small and small.total_s else "—"
        s = c.segundos_etapas
        lineas.append(
            f"| {c.video} | {c.config} | {c.llm_dispositivo} | {_f(s.get('transcripcion'))} | "
            f"{_f(s.get('contexto'))} | {_f(s.get('segmentacion'))} | "
            f"{_f(s.get('emparejamiento'))} | {_f(c.total_s)} | {razon} | "
            f"{_f(c.cumplimiento)} | {', '.join(c.avisos) or '—'} |"
        )
    lineas += ["", "## Tramos que llegan a la ficha o a los pasos", ""]
    for c in corridas:
        if not (c.afectan_ficha or c.afectan_pasos):
            continue
        lineas.append(f"**{c.video} · {c.config}**")
        lineas.append("")
        for tipo, lista in (("ficha", c.afectan_ficha), ("pasos", c.afectan_pasos)):
            for a in lista:
                lineas.append(
                    f"- {tipo}: «{a['referencia'] or '∅'}» → «{a['whisper']}» en "
                    f"{', '.join(a['en'])}"
                )
        lineas.append("")
    lugares = [f"{c.video}/{c.config}: {c.ficha.get('lugar', {}).get('valor')!r}" for c in corridas]
    lineas += ["## Lugar en la ficha", "", *[f"- {x}" for x in lugares], ""]
    return "\n".join(lineas)


# ── Principal ────────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="*", help="clave=ruta del video")
    parser.add_argument("--config", action="append", choices=sorted(CONFIGS))
    parser.add_argument("--sop", type=Path, help="SOP en Markdown para la ruta completa")
    parser.add_argument("--docs", action="store_true", help="copia el informe a docs/adr/datos/")
    parser.add_argument("--reanalizar", help="whisper-<fecha> ya medido: recalcula sin correr")
    parser.add_argument("--transcribir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--salida", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.transcribir:  # subproceso
        transcribir_aqui(args.transcribir, args.config[0], args.salida)
        return 0
    if args.reanalizar:
        datos, corridas = reanalizar(args.reanalizar)
        texto = informe(datos, corridas)
        for destino in [SALIDA] + ([DOCS] if args.docs else []):
            destino.mkdir(parents=True, exist_ok=True)
            (destino / f"{args.reanalizar}.json").write_text(
                json.dumps(datos, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n"
            )
            (destino / f"{args.reanalizar}.md").write_text(texto, "utf-8", newline="\n")
        print(texto)
        return 0
    if not args.videos or args.sop is None:
        parser.error("hacen falta los videos (clave=ruta) y --sop")
    configs = args.config or list(CONFIGS)
    if REFERENCIA not in configs:
        parser.error("la configuración 'referencia' hace falta para el WER")
    configs = [REFERENCIA] + [c for c in configs if c != REFERENCIA]
    sop = convertir_sop(args.sop.read_text(encoding="utf-8")).sop

    git = estado_git()  # al empezar: la medición dura y el árbol puede cambiar
    marca = datetime.now().strftime("%Y%m%d-%H%M")
    carpeta = SALIDA / f"whisper-{marca}"
    corridas: list[Corrida] = []
    for par in args.videos:
        clave, _, ruta = par.partition("=")
        if not clave or not Path(ruta).is_file():
            parser.error(f"{par}: usa clave=ruta a un archivo que exista")
        corridas += medir_video(clave, Path(ruta), configs, sop, carpeta)

    import platform

    from sopvid.plataforma.hardware import get_hardware

    gpu = get_hardware().gpu
    base = get_settings()
    datos = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "git": git,
        "cpu": platform.processor() or platform.machine(),
        "gpu": None if gpu is None else gpu.nombre,
        "llm": base.llm_model,
        "configs": {c: CONFIGS[c] for c in configs},
        "corridas": [asdict(c) | {"total_s": c.total_s} for c in corridas],
    }
    texto = informe(datos, corridas)
    for destino in [SALIDA] + ([DOCS] if args.docs else []):
        destino.mkdir(parents=True, exist_ok=True)
        nombre = f"whisper-{marca}"
        (destino / f"{nombre}.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n"
        )
        (destino / f"{nombre}.md").write_text(texto, "utf-8", newline="\n")
        print(f"  {destino / nombre}.md", file=sys.stderr)
    print(texto)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
