r"""Mide la validación completa de videos anotados en CPU y con GPU (ADR-018, RNF-01, RNF-07).

Cada corrida es una configuración de dispositivos × un modelo de Whisper × un video, de punta a
punta y con el código de producción: `analizar_video` (duración, audio, transcripción) y
`validar` (pasos con Gemma 4, emparejamiento con MiniLM y juez, porcentaje). Antes de cada
corrida Gemma se descarga de Ollama, como en la API, para que todas paguen la carga en frío.

Configuraciones (`--config`, se puede repetir):

- `cpu`: Whisper en CPU (int8) y Gemma con `num_gpu=0`. Es la base que pide ADR-018.
- `auto`: Whisper en cuda si ctranslate2 ve la GPU y Gemma donde Ollama decida. Sin GPU, es igual
  a `cpu`.

Por corrida anota los segundos de cada etapa, dónde corrió cada modelo (`metadatos.dispositivos`),
la RAM máxima del proceso y de Ollama (si es nativo; en Docker no se ve), la VRAM máxima, el
porcentaje, el conteo por estado y si se cumple el criterio de la anotación. Con eso estima cuánto
tardaría un video de 10 minutos (RNF-01: menos de 5) y compara el resultado entre configuraciones
(RNF-07: debe ser el mismo).

Uso, desde la raíz del repo, con el entorno activado y Ollama arriba:

    python scripts/medir_dispositivos.py \
        --sop tests/fixtures/sop_filtro_agua.md --anotacion media/anotacion_ab.json \
        --config cpu --config auto --whisper small --whisper large-v3-turbo \
        video_a=media/videos/VIDEO-A.mp4 video_b=media/videos/VIDEO-B.mp4

La clave antes del "=" es la de la anotación. Sin `--whisper`, el de WHISPER_MODELO. Gemma en CPU
es lento: `--timeout-llm` (por defecto 900 s por petición) evita que una llamada larga caiga a la
heurística. Si aun así cae, la corrida se marca como no válida.

Salida en `data/interim/medicion/` (ignorada por git): `<fecha>.json` y `<fecha>.md`. Con
`--docs`, el resumen va también a `docs/adr/datos/`: solo números y estados, sin texto del video
ni del SOP. No modifica código, datos de entrada ni la base.
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import platform
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sopvid.contrato import SOP, Analisis, Dispositivos, ResultadoValidacion
from sopvid.lenguaje.juez import JuezGemma
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.lenguaje.validacion import DependenciasValidacion, validar
from sopvid.percepcion.pipeline import analizar_video
from sopvid.percepcion.transcripcion import AlSegmento, Transcripcion, TranscriptorWhisper
from sopvid.plataforma.config import PROJECT_ROOT, Settings, get_settings
from sopvid.plataforma.hardware import get_hardware, nvidia_smi, planear

SALIDA = PROJECT_ROOT / "data" / "interim" / "medicion"
DOCS = PROJECT_ROOT / "docs" / "adr" / "datos"

CONFIGS: dict[str, dict[str, Any]] = {
    "cpu": {"whisper_dispositivo": "cpu", "whisper_compute_type": "auto", "llm_dispositivo": "cpu"},
    "auto": {
        "whisper_dispositivo": "auto",
        "whisper_compute_type": "auto",
        "llm_dispositivo": "auto",
    },
}
# RNF-01: un video de 10 minutos en menos de 5.
VIDEO_RNF01_S = 600
META_RNF01_S = 300

logger = logging.getLogger("medir_dispositivos")


# ── Memoria ──────────────────────────────────────────────────────────────────────────────────


class Muestreo:
    """Picos de RAM (este proceso y Ollama nativo) y de VRAM usada, cada `intervalo` segundos."""

    def __init__(self, con_gpu: bool, intervalo: float = 1.0):
        import psutil

        self._psutil = psutil
        self._proceso = psutil.Process()
        self._con_gpu = con_gpu
        self._intervalo = intervalo
        self._alto = threading.Event()
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self.ram_mb = 0.0
        self.ram_ollama_mb: float | None = None
        self.vram_base_mb = self._vram()
        self.vram_mb = self.vram_base_mb

    def __enter__(self) -> Muestreo:
        self._hilo.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._alto.set()
        self._hilo.join(timeout=5)
        self._medir()

    def _bucle(self) -> None:
        while not self._alto.wait(self._intervalo):
            self._medir()

    def _medir(self) -> None:
        self.ram_mb = max(self.ram_mb, self._proceso.memory_info().rss / 2**20)
        ollama = 0.0
        for p in self._psutil.process_iter(["name", "memory_info"]):
            nombre = (p.info.get("name") or "").lower()
            if nombre.startswith("ollama") and p.info.get("memory_info") is not None:
                ollama += p.info["memory_info"].rss / 2**20
        if ollama:
            self.ram_ollama_mb = max(self.ram_ollama_mb or 0.0, ollama)
        vram = self._vram()
        if vram is not None:
            self.vram_mb = max(self.vram_mb or 0.0, vram)

    def _vram(self) -> float | None:
        if not self._con_gpu:
            return None
        try:
            salida = nvidia_smi(["--query-gpu=memory.used", "--format=csv,noheader,nounits"])
            return float(salida.splitlines()[0])
        except Exception:
            return None


# ── Anotación y criterio ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Esperado:
    falta: frozenset[int]  # números de paso del SOP que no aparecen en la anotación
    extras: tuple[tuple[float, float], ...]  # tramos [inicio, fin) de los pasos agregados


def esperado_de(anotacion: dict[str, Any], sop: SOP, duracion_s: float) -> Esperado:
    pasos = sorted(anotacion["pasos"], key=lambda p: p["t"])
    presentes = {p["sop"] for p in pasos if isinstance(p["sop"], int)}
    fines = [p["t"] for p in pasos[1:]] + [duracion_s]
    extras = tuple(
        (p["t"], fin) for p, fin in zip(pasos, fines, strict=True) if p["sop"] == "extra"
    )
    return Esperado(frozenset(p.numero for p in sop.pasos) - presentes, extras)


def criterio(
    guardado: ResultadoValidacion, sop: SOP, esperado: Esperado, settings: Settings
) -> dict[str, Any]:
    """MVP (plan §5.1): las Falta esperadas exactas, cada paso agregado como Sobra en su tramo y,
    si no se espera ninguna Falta, semáforo verde."""
    filas = guardado.resultado.clasificacion.pasos
    falta = {sop.pasos[f.indice_sop].numero for f in filas if f.estado == "Falta"}
    sobras = [
        f.t_inicio
        for f in filas
        if f.estado == "Sobra" and f.marco_operador is None and f.t_inicio is not None
    ]
    extras_vistos = [any(a <= t < b for t in sobras) for a, b in esperado.extras]
    verde = guardado.cumplimiento >= settings.semaforo_verde
    pasa = falta == set(esperado.falta) and all(extras_vistos) and (bool(esperado.falta) or verde)
    return {
        "pasa": pasa,
        "falta_obtenida": sorted(falta),
        "falta_esperada": sorted(esperado.falta),
        "extras_encontrados": f"{sum(extras_vistos)}/{len(extras_vistos)}",
    }


# ── Una corrida ──────────────────────────────────────────────────────────────────────────────


class _Registrado:
    def __init__(self, base: TranscriptorWhisper):
        self._base, self.ultima = base, None

    def transcribir(
        self, audio: Path, idioma: str | None = None, al_segmento: AlSegmento | None = None
    ) -> Transcripcion:
        self.ultima = self._base.transcribir(audio, idioma, al_segmento=al_segmento)
        return self.ultima


class _Cronometro:
    def __init__(self) -> None:
        self.marcas: list[tuple[str, float]] = []

    def __call__(self, etapa: str, porcentaje: int) -> None:
        if not self.marcas or self.marcas[-1][0] != etapa:
            self.marcas.append((etapa, time.perf_counter()))

    def segundos(self) -> dict[str, float]:
        return {e: round(b - a, 2) for (e, a), (_, b) in itertools.pairwise(self.marcas)}


@dataclass
class Corrida:
    config: str
    whisper: str
    video: str
    duracion_video_s: float = 0.0
    segundos: dict[str, float] = field(default_factory=dict)
    total_s: float = 0.0
    dispositivos: dict[str, Any] = field(default_factory=dict)
    compute_type: str | None = None
    ram_mb: float = 0.0
    ram_ollama_mb: float | None = None
    vram_base_mb: float | None = None
    vram_mb: float | None = None
    segmentacion: str | None = None
    cumplimiento: float | None = None
    semaforo: str | None = None
    conteo: dict[str, int] = field(default_factory=dict)
    criterio: dict[str, Any] = field(default_factory=dict)
    valida: bool = True
    notas: list[str] = field(default_factory=list)

    @property
    def tiempo_real(self) -> float | None:
        """Segundos de proceso por segundo de video."""
        return self.total_s / self.duracion_video_s if self.duracion_video_s else None

    @property
    def estimado_10_min_s(self) -> float | None:
        """Extrapolación lineal a 10 min. Sobrestima: la carga en frío no crece con el video."""
        x = self.tiempo_real
        return None if x is None else round(x * VIDEO_RNF01_S, 1)


def correr(
    config: str,
    whisper: str,
    clave: str,
    video: Path,
    sop: SOP,
    anotacion: dict[str, Any],
    base: Settings,
    timeout_llm: float,
    trabajo: Path,
) -> Corrida:
    settings = base.model_copy(
        update=CONFIGS[config] | {"whisper_modelo": whisper, "llm_timeout_s": timeout_llm}
    )
    corrida = Corrida(config=config, whisper=whisper, video=clave)
    llm = ClienteLLM.desde_settings(settings)
    try:
        if not llm.disponible(10):
            raise SystemExit(f"Ollama no responde en {llm.base_url} o no tiene {llm.modelo}")
        llm.descargar()  # carga en frío en cada corrida, como en la API
        transcriptor = _Registrado(TranscriptorWhisper(settings))
        cronometro = _Cronometro()
        carpeta = trabajo / config / whisper.replace("/", "_") / clave
        carpeta.mkdir(parents=True, exist_ok=True)
        gpu = get_hardware().gpu
        with Muestreo(con_gpu=gpu is not None) as muestreo:
            inicio = time.perf_counter()
            analisis: Analisis = analizar_video(video, 0, None, transcriptor, carpeta, cronometro)
            t = transcriptor.ultima
            dispositivos = Dispositivos(
                gpu=None if gpu is None else gpu.nombre,
                transcripcion="gpu" if t and t.dispositivo == "cuda" else "cpu",
                transcripcion_respaldo_cpu=bool(t and t.respaldo_cpu),
            )
            validacion = validar(
                analisis,
                sop,
                DependenciasValidacion(llm, JuezGemma(llm)),
                segundos_analisis=cronometro.segundos(),
                dispositivos=dispositivos,
            )
            corrida.total_s = round(time.perf_counter() - inicio, 2)
    finally:
        llm.close()

    guardado = validacion.resultado
    meta = guardado.metadatos
    corrida.duracion_video_s = analisis.duracion_s
    corrida.segundos = dict(meta.segundos)
    corrida.dispositivos = meta.dispositivos.model_dump() if meta.dispositivos else {}
    corrida.compute_type = t.compute_type if t else None
    corrida.ram_mb = round(muestreo.ram_mb)
    corrida.ram_ollama_mb = (
        None if muestreo.ram_ollama_mb is None else round(muestreo.ram_ollama_mb)
    )
    corrida.vram_base_mb, corrida.vram_mb = muestreo.vram_base_mb, muestreo.vram_mb
    corrida.segmentacion = meta.segmentacion
    corrida.cumplimiento = round(guardado.cumplimiento, 2)
    corrida.semaforo = guardado.semaforo
    corrida.conteo = dict(guardado.resultado.clasificacion.resumen.conteo)
    corrida.criterio = criterio(
        guardado, sop, esperado_de(anotacion, sop, analisis.duracion_s), settings
    )
    if meta.avisos:
        corrida.valida = False
        corrida.notas += [f"aviso {a.tipo}" for a in meta.avisos]
    if config == "cpu" and corrida.dispositivos.get("llm") == "gpu":
        corrida.valida = False
        corrida.notas.append("Ollama no respetó num_gpu=0: Gemma quedó en GPU")
    if corrida.dispositivos.get("transcripcion_respaldo_cpu"):
        corrida.notas.append("cuda falló y Whisper se repitió en CPU")
    return corrida


# ── Reporte ──────────────────────────────────────────────────────────────────────────────────


def _f(valor: float | None, decimales: int = 1) -> str:
    return "—" if valor is None else f"{valor:.{decimales}f}"


def tabla(corridas: list[Corrida], equipo: dict[str, Any]) -> str:
    gpu = equipo["gpu"]["nombre"] if equipo["gpu"] else "sin GPU"
    lineas = [
        f"# Medición CPU contra GPU · {equipo['fecha']}",
        "",
        f"Equipo: {equipo['cpu']}, {equipo['nucleos']} núcleos, {_f(equipo['ram_gb'])} GB de RAM, "
        f"{gpu}. Modelo LLM: `{equipo['llm_model']}`. Umbrales sin cambios.",
        "",
        "| Config | Whisper | Video | Whisper en | Gemma en | Transcribir s | Segmentar s "
        "| Emparejar s | Total s | × tiempo real | 10 min est. | RNF-01 | RAM MB | RAM Ollama MB "
        "| VRAM máx MB | % | Criterio | Válida |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in corridas:
        d, s, est = c.dispositivos, c.segundos, c.estimado_10_min_s
        rnf = "—" if est is None else ("cumple" if est < META_RNF01_S else "no cumple")
        lineas.append(
            f"| {c.config} | {c.whisper} ({c.compute_type}) | {c.video} | {d.get('transcripcion')} "
            f"| {d.get('llm')} | {_f(s.get('transcripcion'))} | {_f(s.get('segmentacion'))} "
            f"| {_f(s.get('emparejamiento'))} | {_f(c.total_s)} | {_f(c.tiempo_real, 2)} "
            f"| {_f(None if est is None else est / 60)} min | {rnf} | {c.ram_mb} "
            f"| {c.ram_ollama_mb or '—'} | {_f(c.vram_mb, 0)} | {_f(c.cumplimiento)} "
            f"{c.semaforo} | {'pasa' if c.criterio.get('pasa') else 'no pasa'} "
            f"| {'sí' if c.valida else 'no: ' + '; '.join(c.notas)} |"
        )
    lineas += ["", "## Mismo resultado entre corridas (RNF-07)", ""]
    for video in dict.fromkeys(c.video for c in corridas):
        de_video = [c for c in corridas if c.video == video]
        firmas = {
            (c.whisper, c.config): (c.cumplimiento, tuple(sorted(c.conteo.items())))
            for c in de_video
        }
        por_whisper: dict[str, set[Any]] = {}
        for (whisper, _), firma in firmas.items():
            por_whisper.setdefault(whisper, set()).add(firma)
        for whisper, distintas in por_whisper.items():
            estado = "igual" if len(distintas) == 1 else f"DISTINTO ({len(distintas)} resultados)"
            lineas.append(f"- {video}, Whisper {whisper}: {estado} entre corridas")
    lineas += [
        "",
        "Notas: el estimado de 10 min es lineal y sobrestima, porque las cargas en frío de Whisper "
        "y Gemma no crecen con el video. La RAM de Ollama solo se ve con Ollama nativo; en Docker "
        "queda en «—». La VRAM incluye la del escritorio (ver `vram_base_mb` en el JSON). "
        "Gemma no da siempre la misma segmentación (ADR-018): repite cada configuración "
        "antes de atribuir una diferencia al dispositivo.",
        "",
    ]
    return "\n".join(lineas)


def equipo_actual(settings: Settings) -> dict[str, Any]:
    import psutil

    hardware = get_hardware()
    plan = planear(settings, hardware)
    return {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cpu": platform.processor() or platform.machine(),
        "nucleos": hardware.nucleos,
        "ram_gb": psutil.virtual_memory().total / 2**30,
        "gpu": None if hardware.gpu is None else asdict(hardware.gpu),
        "plan": plan.como_dict(),
        "llm_model": settings.llm_model,
        "embedder": settings.embedder_model,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+", help="clave=ruta del video (clave de la anotación)")
    parser.add_argument("--sop", type=Path, required=True, help="SOP en Markdown (ADR-015)")
    parser.add_argument("--anotacion", type=Path, required=True, help="JSON de la anotación")
    parser.add_argument("--config", action="append", choices=sorted(CONFIGS), help="repetible")
    parser.add_argument("--whisper", action="append", help="modelo de Whisper; repetible")
    parser.add_argument("--timeout-llm", type=float, default=900.0, help="segundos por petición")
    parser.add_argument("--docs", action="store_true", help="copia el resumen a docs/adr/datos/")
    args = parser.parse_args(argv)

    base = get_settings()
    configs = args.config or ["cpu", "auto"]
    whispers = args.whisper or [base.whisper_modelo]
    sop = convertir_sop(args.sop.read_text(encoding="utf-8")).sop
    anotaciones = json.loads(args.anotacion.read_text(encoding="utf-8"))
    videos = []
    for par in args.videos:
        clave, _, ruta = par.partition("=")
        if clave not in anotaciones or not Path(ruta).is_file():
            parser.error(f"{par}: la clave no está en la anotación o el video no existe")
        videos.append((clave, Path(ruta)))

    equipo = equipo_actual(base)
    marca = datetime.now().strftime("%Y%m%d-%H%M")
    trabajo = SALIDA / marca
    corridas: list[Corrida] = []
    total = len(configs) * len(whispers) * len(videos)
    for config in configs:
        for whisper in whispers:
            for clave, video in videos:
                n = len(corridas) + 1
                print(f"[{n}/{total}] {config} · Whisper {whisper} · {clave}", file=sys.stderr)
                corrida = correr(
                    config,
                    whisper,
                    clave,
                    video,
                    sop,
                    anotaciones[clave],
                    base,
                    args.timeout_llm,
                    trabajo,
                )
                corridas.append(corrida)
                print(
                    f"        {corrida.total_s:.1f} s"
                    f" · Whisper {corrida.dispositivos.get('transcripcion')}"
                    f" · Gemma {corrida.dispositivos.get('llm')} · {corrida.cumplimiento} % "
                    f"{corrida.semaforo} · {'pasa' if corrida.criterio['pasa'] else 'no pasa'}",
                    file=sys.stderr,
                )

    datos = {
        "equipo": equipo,
        "timeout_llm_s": args.timeout_llm,
        "corridas": [
            asdict(c) | {"tiempo_real": c.tiempo_real, "estimado_10_min_s": c.estimado_10_min_s}
            for c in corridas
        ],
    }
    texto = tabla(corridas, equipo)
    destinos = [SALIDA] + ([DOCS] if args.docs else [])
    for carpeta in destinos:
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = f"medicion-dispositivos-{marca}"
        (carpeta / f"{nombre}.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n"
        )
        (carpeta / f"{nombre}.md").write_text(texto, "utf-8", newline="\n")
        print(f"  {carpeta / nombre}.md", file=sys.stderr)
    print(texto)
    return 0 if all(c.valida for c in corridas) else 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
