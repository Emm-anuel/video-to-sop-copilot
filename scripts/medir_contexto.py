r"""Mide la ficha de contexto (RF-12) con Gemma 4 en CPU y en GPU y deja la evidencia (ADR-018).

Dos partes, para separar efectos:

a) **Solo el LLM.** Si la ruta termina en `.json`, se toma como un `Analisis` ya calculado
   (p. ej. `media/video_a_v3/analisis.json`) y se corre solo `generar_contexto`: la misma
   transcripción en las dos configuraciones, así que cualquier diferencia es de Gemma.
b) **Ruta completa.** Si la ruta es un video, corre Whisper (con el modelo de cada configuración) y
   después `validar` contra `--sop`, como la API: ficha → pasos → emparejamiento. Da los segundos
   de cada etapa (RNF-01) y muestra si el cambio de modelo de Whisper altera la ficha.

Configuraciones (`--config`, se puede repetir):

- `gpu`: Gemma donde lo ponga Ollama (`LLM_DISPOSITIVO=auto`) y Whisper `large-v3-turbo` en cuda
  (float16).
- `cpu`: Gemma en CPU (`LLM_DISPOSITIVO=cpu`, `num_gpu=0`) y Whisper con su modelo por defecto
  (`small`, int8) en CPU.

Con `--prompt` (se puede repetir) se comparan versiones del prompt en la parte a; la ruta completa
usa siempre el de producción (`PROMPT`). Con más de una versión, el informe agrega una tabla por
versión: datos con valor, datos inferidos, el lugar, tokens de salida y segundos.

La lógica de la etapa no cambia con el dispositivo (RNF-07): mismo prompt, esquema y cortes. Gemma
se descarga antes de cada corrida, como en la API (la ficha es la primera llamada tras cargar el
modelo, así que la espera al primer token incluye la carga en frío). Hoy no hay fotogramas
(RF-11): cada corrida registra `fotogramas: 0`.

Uso, desde la raíz del repo, con el entorno activado y Ollama arriba:

    python scripts/medir_contexto.py --config gpu --config cpu \
        video_a=media/video_a_v3/analisis.json video_b=media/video_b_v3/analisis.json
    python scripts/medir_contexto.py --config gpu --config cpu \
        --sop tests/fixtures/sop_filtro_agua.md \
        video_a=media/videos/VIDEO-A.mp4 video_b=media/videos/VIDEO-B.mp4

Salida en `data/interim/contexto/` (ignorada por git): `contexto-<fecha>.json` (con las fichas) y
`contexto-<fecha>.md` (tablas y comparación CPU contra GPU campo por campo). Con `--docs`, también
en `docs/adr/datos/contexto/`. Solo usar con videos del equipo: la ficha lleva citas del audio.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from medir_mvp import estado_git, preparar

from sopvid.contrato import SOP
from sopvid.lenguaje.juez import JuezGemma
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.lenguaje.validacion import DependenciasValidacion, validar
from sopvid.percepcion.contexto import PROMPT, ResultadoContexto, generar_contexto
from sopvid.plataforma.config import PROJECT_ROOT, Settings, get_settings
from sopvid.plataforma.hardware import get_hardware
from sopvid.texto import comparable

SALIDA = PROJECT_ROOT / "data" / "interim" / "contexto"
DOCS = PROJECT_ROOT / "docs" / "adr" / "datos" / "contexto"
DATOS = ("actividad", "tema", "lugar", "horario_mencionado", "proposito", "resumen")
AVISO_PRIMER_TOKEN_S = 120  # con fotogramas se acercaría al corte de 180 s

CONFIGS: dict[str, dict[str, Any]] = {
    "gpu": {
        "llm_dispositivo": "auto",
        "whisper_dispositivo": "cuda",
        "whisper_modelo": "large-v3-turbo",
        "whisper_modelo_cpu": "large-v3-turbo",
        "whisper_compute_type": "float16",
    },
    "cpu": {
        "llm_dispositivo": "cpu",
        "whisper_dispositivo": "cpu",
        "whisper_modelo": "small",
        "whisper_modelo_cpu": "small",  # el valor por defecto en CPU hasta el 8 nov (ADR-018)
        "whisper_compute_type": "int8",
    },
}

logger = logging.getLogger("medir_contexto")


@dataclass
class Corrida:
    video: str
    config: str
    repeticion: int
    entrada: str  # "analisis" (parte a) o "video" (parte b)
    prompt: str = PROMPT
    whisper: dict[str, Any] | None = None
    llm_dispositivo: str = "desconocido"
    fotogramas: int = 0
    generado: bool = False
    motivo: str | None = None
    intentos: int = 0
    tokens_entrada: int | None = None
    tokens_salida: int | None = None
    primer_token_s: float | None = None
    tokens_por_s: float | None = None
    segundos_contexto: float = 0.0
    segundos_etapas: dict[str, float] = field(default_factory=dict)
    citas_no_verificadas: int = 0
    personas_descartadas: int = 0
    ficha: dict[str, Any] = field(default_factory=dict)

    def anotar(self, r: ResultadoContexto) -> None:
        self.fotogramas, self.generado, self.motivo = r.fotogramas, r.generado, r.motivo
        self.intentos, self.tokens_entrada, self.tokens_salida = (
            r.intentos,
            r.tokens_entrada,
            r.tokens_salida,
        )
        self.primer_token_s, self.tokens_por_s = r.primer_token_s, r.tokens_por_s
        self.citas_no_verificadas = r.citas_no_verificadas
        self.personas_descartadas = r.personas_descartadas
        self.ficha = r.contexto.model_dump(mode="json")

    @property
    def total_s(self) -> float:
        return round(sum(self.segundos_etapas.values()), 1)


# ── Corridas ─────────────────────────────────────────────────────────────────────────────────


def solo_llm(
    clave: str,
    ruta: Path,
    config: str,
    n: int,
    settings: Settings,
    llm: ClienteLLM,
    version: str = PROMPT,
) -> Corrida:
    """Parte a: `generar_contexto` sobre el `Analisis` guardado, con Gemma en frío."""
    analisis, _, _ = preparar(clave, ruta, settings, SALIDA)
    llm.descargar()
    corrida = Corrida(clave, config, n, "analisis", prompt=version)
    inicio = time.perf_counter()
    try:
        resultado = generar_contexto(analisis, llm, version=version)
        corrida.llm_dispositivo = llm.dispositivo_cargado()
    finally:
        llm.descargar()
    corrida.segundos_contexto = round(time.perf_counter() - inicio, 2)
    corrida.segundos_etapas = {"contexto": corrida.segundos_contexto}
    corrida.anotar(resultado)
    return corrida


def ruta_completa(
    clave: str,
    ruta: Path,
    config: str,
    n: int,
    settings: Settings,
    llm: ClienteLLM,
    sop: SOP,
    trabajo: Path,
) -> Corrida:
    """Parte b: Whisper con el modelo de la configuración y después `validar` (como la API)."""
    llm.descargar()  # Whisper y Gemma nunca a la vez (ADR-014)
    analisis, segundos, dispositivos = preparar(f"{clave}-{config}-{n}", ruta, settings, trabajo)
    validacion = validar(
        analisis,
        sop,
        DependenciasValidacion(llm, JuezGemma(llm)),
        segundos_analisis=segundos,
        dispositivos=dispositivos,
    )
    meta = validacion.resultado.metadatos
    corrida = Corrida(clave, config, n, "video")
    corrida.whisper = {
        "modelo": analisis.modelo_transcripcion,
        "dispositivo": meta.dispositivos.transcripcion if meta.dispositivos else None,
        "respaldo_cpu": bool(meta.dispositivos and meta.dispositivos.transcripcion_respaldo_cpu),
        "compute_type": settings.whisper_compute_type,
    }
    corrida.llm_dispositivo = meta.dispositivos.llm if meta.dispositivos else "desconocido"
    corrida.segundos_etapas = dict(meta.segundos)
    corrida.segundos_contexto = meta.segundos.get("contexto", 0.0)
    if validacion.resultado_contexto is not None:
        corrida.anotar(validacion.resultado_contexto)
    return corrida


# ── Comparación CPU contra GPU ───────────────────────────────────────────────────────────────


def _personas(ficha: dict[str, Any]) -> list[tuple[str, str, str]]:
    return sorted(
        (comparable(p["nombre"]), comparable(p["rol"] or ""), p["participacion"])
        for p in ficha.get("personas", [])
    )


def comparar(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Diferencias campo por campo entre dos fichas (a = gpu, b = cpu)."""
    datos = {}
    for campo in DATOS:
        da, db = a[campo], b[campo]
        datos[campo] = {
            "con_valor": [da["valor"] is not None, db["valor"] is not None],
            "fuente": [da["fuente"], db["fuente"]],
            "mismo_valor": comparable(da["valor"] or "") == comparable(db["valor"] or ""),
        }
    equipos_a = {comparable(e["nombre"]) for e in a["equipos"]}
    equipos_b = {comparable(e["nombre"]) for e in b["equipos"]}
    return {
        "mismas_personas": _personas(a) == _personas(b),
        "personas": [_personas(a), _personas(b)],
        "datos": datos,
        "equipos_comunes": len(equipos_a & equipos_b),
        "equipos_solo": [sorted(equipos_a - equipos_b), sorted(equipos_b - equipos_a)],
    }


def _primera(
    corridas: Sequence[Corrida], video: str, entrada: str, prompt: str, config: str
) -> Corrida | None:
    clave = (video, entrada, prompt, config)
    return next((c for c in corridas if (c.video, c.entrada, c.prompt, c.config) == clave), None)


def comparaciones(corridas: Sequence[Corrida]) -> list[dict[str, Any]]:
    """Primera corrida de gpu contra primera de cpu, por video, entrada y prompt."""
    salida = []
    for video, entrada, prompt in sorted({(c.video, c.entrada, c.prompt) for c in corridas}):
        gpu = _primera(corridas, video, entrada, prompt, "gpu")
        cpu = _primera(corridas, video, entrada, prompt, "cpu")
        if gpu and cpu and gpu.generado and cpu.generado:
            salida.append(
                {"video": video, "entrada": entrada, "prompt": prompt}
                | comparar(gpu.ficha, cpu.ficha)
            )
    return salida


def por_prompt(corridas: Sequence[Corrida]) -> list[dict[str, Any]]:
    """Por video, configuración y prompt: datos con valor e inferidos (sin el resumen), el lugar
    de cada corrida, tokens de salida y segundos de la ficha (promedios de las corridas)."""
    filas = []
    claves = sorted({(c.video, c.config, c.prompt) for c in corridas if c.generado})
    for video, config, prompt in claves:
        grupo = [
            c
            for c in corridas
            if (c.video, c.config, c.prompt) == (video, config, prompt) and c.generado
        ]
        datos = [[c.ficha[k] for k in DATOS if k != "resumen"] for c in grupo]
        n = len(grupo)
        filas.append(
            {
                "video": video,
                "config": config,
                "prompt": prompt,
                "corridas": n,
                "con_valor": sum(sum(d["valor"] is not None for d in f) for f in datos) / n,
                "inferidos": sum(
                    sum(d["valor"] is not None and d["fuente"] == "inferido" for d in f)
                    for f in datos
                )
                / n,
                "alta": sum(sum(d["confianza"] == "alta" for d in f) for f in datos) / n,
                "media": sum(
                    sum(d["valor"] is not None and d["confianza"] == "media" for d in f)
                    for f in datos
                )
                / n,
                "lugar": [
                    f"{c.ficha['lugar']['valor']} ({c.ficha['lugar']['fuente']}, "
                    f"{c.ficha['lugar']['confianza']})"
                    if c.ficha["lugar"]["valor"]
                    else "—"
                    for c in grupo
                ],
                "tokens_salida": sum(c.tokens_salida or 0 for c in grupo) / n,
                "segundos": sum(c.segundos_contexto for c in grupo) / n,
            }
        )
    return filas


# ── Informe ──────────────────────────────────────────────────────────────────────────────────


def _f(valor: Any) -> str:
    if valor is None:
        return "—"
    return f"{valor:g}" if isinstance(valor, float) else str(valor)


def informe(datos: dict[str, Any], corridas: Sequence[Corrida]) -> str:
    git = datos["git"]
    sin_commit = git["cambios_sin_commit"]
    lineas = [
        f"# Ficha de contexto en CPU y en GPU · {datos['fecha']}",
        "",
        f"- Commit `{git['commit'] or 'desconocido'}` en `{git['rama'] or '—'}`"
        + (f" · {sin_commit} archivo(s) sin commit" if sin_commit else "")
        + f". Prompt(s) {', '.join(f'`{x}`' for x in datos['prompts'])}, LLM `{datos['llm']}`,"
        f" GPU: {datos['gpu'] or 'ninguna'}.",
        "- Gemma se descarga antes de cada corrida: la espera al primer token incluye la carga.",
        "- Fotogramas en la entrada: 0 en todas las corridas (RF-11 aún no existe).",
        "",
        "## Corridas",
        "",
        "| Video | Entrada | Prompt | Config | # | Whisper | Gemma | Tokens entrada | Tokens "
        "salida | Primer token (s) | Tokens/s | Ficha (s) | Total (s) | Intentos | Personas | "
        "Datos con cita |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in corridas:
        whisper = f"{c.whisper['modelo']} · {c.whisper['dispositivo']}" if c.whisper else "—"
        con_cita = sum(c.ficha.get(k, {}).get("fuente") in ("audio", "visual") for k in DATOS)
        lineas.append(
            f"| {c.video} | {c.entrada} | {c.prompt} | {c.config} | {c.repeticion} | {whisper} | "
            f"{c.llm_dispositivo} | {_f(c.tokens_entrada)} | {_f(c.tokens_salida)} | "
            f"{_f(c.primer_token_s)} | {_f(c.tokens_por_s)} | {_f(c.segundos_contexto)} | "
            f"{_f(c.total_s)} | {c.intentos}{'' if c.generado else f' ({c.motivo})'} | "
            f"{len(c.ficha.get('personas', []))} | {con_cita}/{len(DATOS)} |"
        )
    completas = [c for c in corridas if c.entrada == "video"]
    if completas:
        lineas += [
            "",
            "## Ruta completa: segundos por etapa",
            "",
            "| Video | Config | duracion | audio | transcripcion | contexto | segmentacion | "
            "emparejamiento | Total | Ficha / total |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        etapas = (
            "duracion",
            "audio",
            "transcripcion",
            "contexto",
            "segmentacion",
            "emparejamiento",
        )
        for c in completas:
            seg = c.segundos_etapas
            parte = f"{100 * seg.get('contexto', 0) / c.total_s:.0f} %" if c.total_s else "—"
            lineas.append(
                f"| {c.video} | {c.config} | "
                + " | ".join(_f(seg.get(e)) for e in etapas)
                + f" | {_f(c.total_s)} | {parte} |"
            )
    if datos["comparaciones"]:
        lineas += ["", "## CPU contra GPU, campo por campo", ""]
        for comp in datos["comparaciones"]:
            lineas.append(
                f"### {comp['video']} · {comp['entrada']} · {comp['prompt']} · "
                f"{'mismas personas' if comp['mismas_personas'] else '**personas distintas**'}"
            )
            lineas += [
                "",
                "| Dato | Con valor (gpu / cpu) | Fuente (gpu / cpu) | Mismo valor |",
                "|---|---|---|---|",
            ]
            for campo, d in comp["datos"].items():
                lineas.append(
                    f"| {campo} | {' / '.join('sí' if x else 'no' for x in d['con_valor'])} | "
                    f"{' / '.join(d['fuente'])} | {'sí' if d['mismo_valor'] else 'no'} |"
                )
            solo_gpu, solo_cpu = comp["equipos_solo"]
            lineas += [
                "",
                f"Personas (nombre, rol, participación): gpu {comp['personas'][0]} · "
                f"cpu {comp['personas'][1]}.",
                f"Equipos en común: {comp['equipos_comunes']}; solo gpu: {solo_gpu or '—'}; "
                f"solo cpu: {solo_cpu or '—'}.",
                "",
            ]
    if len(datos["prompts"]) > 1:
        lineas += [
            "",
            "## Por versión del prompt (promedio de las corridas; 5 datos sin el resumen)",
            "",
            "| Video | Config | Prompt | Corridas | Con valor | Inferidos | Alta | Media | Lugar "
            "| Tokens salida | Ficha (s) |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for f in datos["por_prompt"]:
            lineas.append(
                f"| {f['video']} | {f['config']} | {f['prompt']} | {f['corridas']} | "
                f"{f['con_valor']:g} | {f['inferidos']:g} | {f['alta']:g} | {f['media']:g} | "
                f"{'; '.join(f['lugar'])} | {f['tokens_salida']:.0f} | {f['segundos']:.1f} |"
            )
    lentos = [c for c in corridas if c.primer_token_s and c.primer_token_s > AVISO_PRIMER_TOKEN_S]
    if lentos:
        lineas += [
            "",
            f"**Aviso:** la espera al primer token pasó de {AVISO_PRIMER_TOKEN_S} s en "
            + ", ".join(f"{c.video}/{c.config}" for c in lentos)
            + "; con fotogramas se acercará al corte de 180 s.",
        ]
    lineas += ["", "Las fichas completas están en el .json de esta medición.", ""]
    return "\n".join(lineas)


# ── Principal ────────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+", help="clave=ruta del video o de su analisis.json")
    parser.add_argument(
        "--config", action="append", choices=sorted(CONFIGS), help="gpu, cpu o las dos"
    )
    parser.add_argument("--repeticiones", type=int, default=1, help="corridas por configuración")
    parser.add_argument(
        "--prompt", action="append", help=f"versión del prompt (parte a); por defecto {PROMPT}"
    )
    parser.add_argument("--sop", type=Path, help="SOP en Markdown, para la ruta completa")
    parser.add_argument(
        "--docs", action="store_true", help="copia el informe a docs/adr/datos/contexto/"
    )
    args = parser.parse_args(argv)
    configs = args.config or ["gpu"]
    prompts = args.prompt or [PROMPT]
    entradas = []
    for par in args.videos:
        clave, _, ruta = par.partition("=")
        if not clave or not Path(ruta).is_file():
            parser.error(f"{par}: usa clave=ruta a un archivo que exista")
        entradas.append((clave, Path(ruta)))
    if any(r.suffix.lower() != ".json" for _, r in entradas) and args.sop is None:
        parser.error("la ruta completa (un video) necesita --sop")
    sop = convertir_sop(args.sop.read_text(encoding="utf-8")).sop if args.sop else None

    base = get_settings()
    marca = datetime.now().strftime("%Y%m%d-%H%M")
    corridas: list[Corrida] = []
    for config in configs:
        settings = base.model_copy(update=CONFIGS[config])
        llm = ClienteLLM.desde_settings(settings)
        try:
            if not llm.disponible(10):
                print(f"Ollama no responde en {llm.base_url} o sin {llm.modelo}", file=sys.stderr)
                return 2
            for clave, ruta, version, n in (
                (c, r, v, n)
                for c, r in entradas
                for v in (prompts if r.suffix.lower() == ".json" else [PROMPT])
                for n in range(1, args.repeticiones + 1)
            ):
                print(f"{clave} · {version} · {config} · {n}/{args.repeticiones}…", file=sys.stderr)
                if ruta.suffix.lower() == ".json":
                    corrida = solo_llm(clave, ruta, config, n, settings, llm, version)
                else:
                    assert sop is not None
                    corrida = ruta_completa(
                        clave, ruta, config, n, settings, llm, sop, SALIDA / marca
                    )
                corridas.append(corrida)
                print(
                    f"  Gemma {corrida.llm_dispositivo} · {corrida.tokens_entrada} → "
                    f"{corrida.tokens_salida} tokens · primer token {corrida.primer_token_s} s"
                    f" · ficha {corrida.segundos_contexto} s · total {corrida.total_s} s"
                    f"{'' if corrida.generado else f' · SIN FICHA ({corrida.motivo})'}",
                    file=sys.stderr,
                )
        finally:
            llm.close()

    gpu = get_hardware().gpu
    datos = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "git": estado_git(),
        "prompts": prompts,
        "llm": base.llm_model,
        "gpu": None if gpu is None else gpu.nombre,
        "configs": {c: CONFIGS[c] for c in configs},
        "corridas": [asdict(c) | {"total_s": c.total_s} for c in corridas],
    }
    datos["comparaciones"] = comparaciones(corridas)
    datos["por_prompt"] = por_prompt(corridas)
    texto = informe(datos, corridas)
    for carpeta in [SALIDA] + ([DOCS] if args.docs else []):
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = f"contexto-{marca}"
        (carpeta / f"{nombre}.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n"
        )
        (carpeta / f"{nombre}.md").write_text(texto, "utf-8", newline="\n")
        print(f"  {carpeta / nombre}.md", file=sys.stderr)
    print(texto)
    return 0 if all(c.generado for c in corridas) else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
