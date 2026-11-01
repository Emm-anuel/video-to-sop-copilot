"""Calibra los umbrales del emparejamiento (ADR-012, ADR-013) con los videos anotados a mano.

Prueba una rejilla de `UMBRAL_BAJO`, `UMBRAL_ALTO` y `UMBRAL_FUSION` y elige la combinación que
mejor reproduce la anotación manual. No usa el LLM: así es determinista y corre sin GPU (el juez
de la zona gris solo vuelve a decidir pares después; no mueve la rejilla).

**Cómo se mide.** Para cada paso del video se busca el tramo anotado con el que más se encima; ese
tramo dice qué se esperaba ahí: un paso del SOP, nada (intro o cierre del operador, ADR-016) o un
paso de más (`"extra"`, el *Sobra* real del guion). Con eso se arma la verdad por paso del SOP: a
qué paso del video debería quedar emparejado. Después, para cada combinación de umbrales, se
cuentan los pares correctos, los equivocados y los que faltan, y se calcula F1 sobre pares
(SOP ↔ video):

    TP  par (SOP i, video j) con j el esperado para i
    FP  par que sobrevive a los umbrales pero no es el esperado (pares cruzados, pasos de más)
    FN  paso del SOP que se esperaba emparejado y no quedó emparejado

El F1 se promedia entre los videos (cada video pesa igual, no cada paso: un video con 20 pasos no
tapa a uno con 4). En empate gana la combinación más cercana a los valores actuales de la
configuración, para no mover umbrales por ruido; si los actuales ya ganan, el script lo dice y no
hay nada que cambiar.

**Uso**, desde la raíz del repo y con el entorno activado:

    python scripts/calibrar_umbrales.py \\
        --sop tests/fixtures/sop_filtro_agua.md --anotacion media/anotacion_ab.json \\
        video_a=media/video_a_v2 video_b=media/video_b_v2

Cada carpeta trae `analisis.json` (el `Analisis` del pipeline) y `resultado.json` con los pasos del
video en "segmentacion", igual que para `scripts/diagnosticar_emparejamiento.py`. La clave antes
del "=" es la de la anotación.

Salida: `docs/adr/datos/emparejamiento/calibracion.md` (la tabla, para el ADR) y
`calibracion.json` (todas las combinaciones), y en la terminal las líneas de `.env` con los valores
elegidos. No modifica código ni `.env`: los umbrales se aplican a mano (RNF-14 los lee de la
configuración).
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ValidationError

from sopvid.contrato import SOP, Analisis, Fusion, PasoVideo, ResultadoEmparejamiento
from sopvid.lenguaje import emparejamiento as emp
from sopvid.lenguaje.reporte import porcentaje, semaforo
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.plataforma.config import PROJECT_ROOT, Settings, get_settings

SALIDA = PROJECT_ROOT / "docs" / "adr" / "datos" / "emparejamiento"

# Rejilla por defecto: los valores actuales (0.55 / 0.75 / 0.55) y sus vecinos razonables. El 1.0
# de la fusión es el caso "no fusionar" (ADR-013): solo se unirían pasos con coseno exactamente 1,
# así que la rejilla también puede concluir que la fusión no está ayudando.
BAJOS = (0.45, 0.50, 0.55, 0.60, 0.65)
ALTOS = (0.65, 0.70, 0.75, 0.80, 0.85)
FUSIONES = (0.45, 0.50, 0.55, 0.60, 1.0)


# ── Anotación manual ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tramo:
    """Un tramo anotado a mano: desde `inicio` hasta el siguiente, y qué debía pasar ahí.

    `sop` es el número del paso del SOP (desde 1), `None` si es intro o cierre del operador
    (ADR-016) y `"extra"` si es un paso que el guion del video agrega a propósito (*Sobra*).
    """

    inicio: float
    fin: float
    nombre: str
    sop: int | str | None


def tramos_de(anotacion: dict[str, Any], duracion: float) -> list[Tramo]:
    """Los tramos de un video a partir de sus pasos anotados y la duración del video."""
    pasos = anotacion["pasos"]
    fines = [p["t"] for p in pasos[1:]] + [duracion]
    return [
        Tramo(p["t"], fin, p["nombre"], p.get("sop")) for p, fin in zip(pasos, fines, strict=True)
    ]


def tramo_mayor(paso: PasoVideo, tramos: list[Tramo]) -> Tramo:
    """El tramo anotado con el que más se encima el paso del video."""
    return max(tramos, key=lambda tr: min(tr.fin, paso.t_fin) - max(tr.inicio, paso.t_inicio))


def encime(paso: PasoVideo, tramo: Tramo) -> float:
    """Segundos compartidos entre el paso del video y el tramo anotado."""
    return min(tramo.fin, paso.t_fin) - max(tramo.inicio, paso.t_inicio)


def esperado_por_sop(pasos: list[PasoVideo], tramos: list[Tramo]) -> dict[int, int]:
    """Índice del SOP → índice del paso del video que la anotación espera para él (desde 0).

    Se recorre el video, no el SOP: cada paso del video aporta a lo más una pareja esperada, y los
    tramos de intro, cierre o `"extra"` no aportan ninguna. Si dos pasos del video caen en el mismo
    tramo del SOP (sobre-segmentación, el caso de ADR-013), gana el que más se encima y el otro
    queda como paso de más.
    """

    mejor: dict[int, tuple[float, int]] = {}
    for j, paso in enumerate(pasos):
        tramo = tramo_mayor(paso, tramos)
        if not isinstance(tramo.sop, int):
            continue
        ancho = encime(paso, tramo)
        anterior = mejor.get(tramo.sop)
        if anterior is None or ancho > anterior[0]:
            mejor[tramo.sop] = (ancho, j)
    return {numero - 1: j for numero, (_, j) in mejor.items()}


# ── Videos preparados ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Video:
    """Un video anotado, con lo que no depende de los umbrales ya calculado una sola vez."""

    clave: str
    pasos: list[PasoVideo]
    esperado: dict[int, int]
    duracion: float
    vectores_sop: np.ndarray
    vectores_video: np.ndarray


def cargar(clave: str, carpeta: Path, sop: SOP, anotacion: dict[str, Any], embedder: Any) -> Video:
    """Lee el análisis y los pasos de un video y calcula sus vectores."""
    analisis = Analisis.model_validate_json((carpeta / "analisis.json").read_text("utf-8"))
    datos = json.loads((carpeta / "resultado.json").read_text("utf-8"))
    pasos = [PasoVideo.model_validate(p) for p in datos["segmentacion"]["pasos"]]
    tramos = tramos_de(anotacion[clave], analisis.duracion_s)
    return Video(
        clave=clave,
        pasos=pasos,
        esperado=esperado_por_sop(pasos, tramos),
        duracion=analisis.duracion_s,
        vectores_sop=embedder.embed([emp.texto_para_embeber(p) for p in sop.pasos]),
        vectores_video=embedder.embed([emp.texto_para_embeber(p) for p in pasos]),
    )


# ── La cascada con unos umbrales dados ─────────────────────────────────────────────────────


def clasificar_con(
    asignacion: Any, sop: SOP, pasos: list[PasoVideo], bajo: float, alto: float
) -> Any:
    """`clasificar` con umbrales propios, sin tocar la configuración del proceso.

    `clasificar` lee `UMBRAL_BAJO` y `UMBRAL_ALTO` de `Settings`; aquí se le pasa un `Settings` con
    los valores de la rejilla (el modelo rechaza `bajo > alto`, y la rejilla ya descarta ese caso).
    """
    original = emp.get_settings
    emp.get_settings = lambda: Settings(umbral_bajo=bajo, umbral_alto=alto)
    try:
        return emp.clasificar(asignacion, sop.pasos, pasos)
    finally:
        emp.get_settings = original


class Cascada:
    """Vectoriza y fusiona una vez por `UMBRAL_FUSION`, y reutiliza el resultado en la rejilla.

    La fusión depende solo de `UMBRAL_FUSION`, y `asignar` de la matriz de los pasos ya fusionados:
    ambos se guardan por video y umbral de fusión, así la rejilla solo repite el húngaro y los
    umbrales, que son operaciones sobre matrices pequeñas.
    """

    def __init__(self, sop: SOP, embedder: Any) -> None:
        self._sop = sop
        self._embedder = embedder
        self._cache: dict[tuple[str, float], tuple[list[PasoVideo], list[Fusion], Any]] = {}

    def preparar(self, video: Video, fusion: float) -> tuple[list[PasoVideo], list[Fusion], Any]:
        clave = (video.clave, fusion)
        if clave not in self._cache:
            fusionados, fusiones = emp.fusionar(
                self._sop.pasos, video.pasos, self._embedder, umbral=fusion
            )
            vectores = (
                self._embedder.embed([emp.texto_para_embeber(p) for p in fusionados])
                if fusionados
                else np.zeros((0, video.vectores_sop.shape[1]))
            )
            self._cache[clave] = (
                fusionados,
                fusiones,
                emp.asignar(emp.similitud(video.vectores_sop, vectores)),
            )
        return self._cache[clave]

    def clasificacion(
        self, video: Video, bajo: float, alto: float, fusion: float
    ) -> tuple[list[PasoVideo], list[Fusion], Any]:
        """Los pasos fusionados, su registro y la clasificación, ya con el orden revisado."""
        fusionados, fusiones, asignacion = self.preparar(video, fusion)
        clasificacion = emp.orden(clasificar_con(asignacion, self._sop, fusionados, bajo, alto))
        return fusionados, fusiones, clasificacion


def medir(
    cascada: Cascada, video: Video, bajo: float, alto: float, fusion: float
) -> tuple[float, int, int, int]:
    """Corre la cascada sin LLM y devuelve (F1, TP, FP, FN) del video.

    Los `indice_video` de la clasificación apuntan a los pasos **fusionados**, así que la
    comparación con la anotación pasa por `Fusion.originales`: un par (SOP i, paso fusionado j)
    es correcto si el paso del video que la anotación espera para i está entre los originales de
    j. Un paso fusionado de más cuenta como FP y el paso del SOP que se quedó sin su pareja, como
    FN: así el informe también mide el daño de sobre-fusionar (ADR-013).
    """
    fusionados, fusiones, clasificacion = cascada.clasificacion(video, bajo, alto, fusion)
    indice = {paso.numero: j for j, paso in enumerate(video.pasos)}

    tp = fp = 0
    for resultado in clasificacion.pasos:
        if resultado.indice_sop is None or resultado.indice_video is None:
            continue
        originales = {indice[n] for n in fusiones[resultado.indice_video].originales if n in indice}
        if video.esperado.get(resultado.indice_sop) in originales:
            tp += 1
        else:
            fp += 1
    fn = len(video.esperado) - tp
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return f1, tp, fp, fn


# ── Rejilla e informe ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Ajuste:
    """Un punto de la rejilla con lo que produjo."""

    bajo: float
    alto: float
    fusion: float
    f1: float
    por_video: dict[str, float]
    tp: int
    fp: int
    fn: int

    @property
    def clave(self) -> tuple[float, float, float]:
        return (self.bajo, self.alto, self.fusion)


def _cerca_de_actual(ajuste: Ajuste, actual: tuple[float, float, float]) -> float:
    """Distancia a los umbrales configurados: desempata sin mover nada por ruido."""
    return sum(abs(a - b) for a, b in zip(ajuste.clave, actual, strict=True))


def calibrar(
    sop: SOP,
    videos: list[Video],
    embedder: Any,
    bajos: list[float],
    altos: list[float],
    fusiones: list[float],
) -> list[Ajuste]:
    """Recorre la rejilla y devuelve todos los ajustes, del mejor al peor."""
    cascada = Cascada(sop, embedder)
    ajustes: list[Ajuste] = []
    for bajo, alto, fusion in itertools.product(bajos, altos, fusiones):
        if bajo > alto:
            continue  # `Settings` lo rechaza: la zona gris quedaría vacía.
        resultados = {v.clave: medir(cascada, v, bajo, alto, fusion) for v in videos}
        ajustes.append(
            Ajuste(
                bajo=bajo,
                alto=alto,
                fusion=fusion,
                f1=sum(r[0] for r in resultados.values()) / len(resultados),
                por_video={c: r[0] for c, r in resultados.items()},
                tp=sum(r[1] for r in resultados.values()),
                fp=sum(r[2] for r in resultados.values()),
                fn=sum(r[3] for r in resultados.values()),
            )
        )
    actual = get_settings()
    actuales = (actual.umbral_bajo, actual.umbral_alto, actual.umbral_fusion)
    ajustes.sort(key=lambda a: (-round(a.f1, 6), _cerca_de_actual(a, actuales)))
    return ajustes


def _reporte(cascada: Cascada, video: Video, sop: SOP, ajuste: Ajuste) -> tuple[float, str]:
    """El % de cumplimiento y el semáforo que daría el reporte con estos umbrales."""
    fusionados, fusiones, clasificacion = cascada.clasificacion(
        video, ajuste.bajo, ajuste.alto, ajuste.fusion
    )
    resultado = ResultadoEmparejamiento(
        clasificacion=emp.marcar_marco(clasificacion),
        fusiones=fusiones,
        pasos_video=fusionados,
    )
    # Como el reporte: semáforo con el porcentaje sin redondear; se guardan dos decimales.
    crudo = porcentaje(resultado)
    pct = Decimal(str(crudo)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(pct), semaforo(crudo)


def _f1_de(ajustes: list[Ajuste], clave: tuple[float, float, float]) -> float:
    for ajuste in ajustes:
        if ajuste.clave == clave:
            return ajuste.f1
    return float("nan")


def informe(
    ajustes: list[Ajuste], videos: list[Video], sop: SOP, cascada: Cascada, limite: int = 15
) -> str:
    """La tabla para el ADR: los mejores ajustes y cómo queda cada video con el elegido."""
    actual = get_settings()
    actuales = (actual.umbral_bajo, actual.umbral_alto, actual.umbral_fusion)
    mejor = ajustes[0]
    f1_actual = _f1_de(ajustes, actuales)
    lineas = [
        "# Calibración de los umbrales del emparejamiento (ADR-012, ADR-013)",
        "",
        f"Videos: {', '.join(v.clave for v in videos)} · {len(videos)} anotados a mano · "
        f"SOP «{sop.titulo}» de {len(sop.pasos)} pasos · {len(ajustes)} combinaciones, sin LLM.",
        "",
        f"**Elegido:** `UMBRAL_BAJO={mejor.bajo:.2f}`, `UMBRAL_ALTO={mejor.alto:.2f}`, "
        f"`UMBRAL_FUSION={mejor.fusion:.2f}` — F1 medio {mejor.f1:.3f} "
        f"(TP {mejor.tp}, FP {mejor.fp}, FN {mejor.fn}).",
        "",
        f"Configuración actual: `{actuales[0]:.2f}` / `{actuales[1]:.2f}` / `{actuales[2]:.2f}` — "
        f"F1 {f1_actual:.3f}.",
        "",
    ]
    if f1_actual >= mejor.f1 - 1e-9:
        lineas += [
            "> Los valores actuales ya son los mejores de la rejilla: no hay que cambiar `.env`.",
            "",
        ]
    elif mejor.f1 - f1_actual < 0.01:
        lineas += [
            "> La mejora es menor que 0.01 de F1: dentro del ruido de una anotación de dos "
            "videos. Cambiar `.env` queda a criterio del equipo; conviene anotar C y D antes.",
            "",
        ]
    if mejor.fusion == 1.0:
        lineas += [
            "> **Aviso (ADR-013):** la mejor combinación apaga la fusión. Con estos videos, unir "
            "pasos consecutivos del video que caen en el mismo paso del SOP se lleva por delante "
            "pasos que sí estaban: mirar los FN de cada video y el diagnóstico de los Sobra antes "
            "de cambiar `UMBRAL_FUSION`; la regla de fusión es una decisión del equipo, no un "
            "umbral más.",
            "",
        ]
    lineas += [
        "| # | UMBRAL_BAJO | UMBRAL_ALTO | UMBRAL_FUSION | F1 | "
        + " | ".join(f"F1 {v.clave}" for v in videos)
        + " | TP | FP | FN |",
        "|---|---|---|---|---|---|" + "---|" * len(videos) + "---|---|---|",
    ]
    for i, ajuste in enumerate(ajustes[:limite], start=1):
        marca = " ✅" if ajuste.clave == mejor.clave else ""
        lineas.append(
            f"| {i} | {ajuste.bajo:.2f} | {ajuste.alto:.2f} | {ajuste.fusion:.2f} | "
            f"{ajuste.f1:.3f}{marca} | "
            + " | ".join(f"{ajuste.por_video[v.clave]:.3f}" for v in videos)
            + f" | {ajuste.tp} | {ajuste.fp} | {ajuste.fn} |"
        )
    lineas += [
        "",
        "## Cómo queda cada video con el ajuste elegido",
        "",
        "«Esperados» son los pares que pide la anotación; «vivos», los pares que sobreviven a los "
        "umbrales. El % y el semáforo son los del reporte (sección 5.6): sirven para comprobar el "
        "criterio del MVP (A ≥ 90 % en verde; B con 2 Falta y 1 Sobra).",
        "",
        "| Video | Pasos del video | Esperados | Vivos | F1 | % | Semáforo |",
        "|---|---|---|---|---|---|---|",
    ]
    for video in videos:
        f1, tp, fp, _ = medir(cascada, video, mejor.bajo, mejor.alto, mejor.fusion)
        pct, sem = _reporte(cascada, video, sop, mejor)
        lineas.append(
            f"| {video.clave} | {len(video.pasos)} | {len(video.esperado)} | {tp + fp} | "
            f"{f1:.3f} | {pct:.2f} | {sem} |"
        )
    lineas.append("")
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("videos", nargs="+", help="clave=carpeta, p. ej. video_a=media/video_a_v2")
    ap.add_argument("--sop", type=Path, required=True, help="SOP en Markdown o TXT (plantilla)")
    ap.add_argument("--anotacion", type=Path, required=True, help="JSON de la anotación manual")
    ap.add_argument("--bajos", default=",".join(map(str, BAJOS)), help="valores de UMBRAL_BAJO")
    ap.add_argument("--altos", default=",".join(map(str, ALTOS)), help="valores de UMBRAL_ALTO")
    ap.add_argument(
        "--fusiones", default=",".join(map(str, FUSIONES)), help="valores de UMBRAL_FUSION"
    )
    ap.add_argument("--salida", type=Path, default=SALIDA, help="carpeta del informe")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    sop = convertir_sop(args.sop.read_text("utf-8")).sop
    anotacion = json.loads(args.anotacion.read_text("utf-8"))
    entradas = [(c, Path(d)) for c, _, d in (v.partition("=") for v in args.videos)]
    faltan = [clave for clave, _ in entradas if clave not in anotacion]
    if faltan:
        print(f"La anotación no tiene: {', '.join(faltan)}", file=sys.stderr)
        return 1

    embedder = emp.get_embedder()
    try:
        videos = [cargar(c, d, sop, anotacion, embedder) for c, d in entradas]
    except (OSError, ValidationError, KeyError, ValueError) as exc:
        print(f"No se pudo leer un video: {type(exc).__name__}", file=sys.stderr)
        return 1

    ajustes = calibrar(
        sop,
        videos,
        embedder,
        [float(x) for x in args.bajos.split(",")],
        [float(x) for x in args.altos.split(",")],
        [float(x) for x in args.fusiones.split(",")],
    )
    if not ajustes:
        print("La rejilla quedó vacía: revisa --bajos, --altos y --fusiones", file=sys.stderr)
        return 1
    mejor = ajustes[0]
    texto = informe(ajustes, videos, sop, Cascada(sop, embedder))
    args.salida.mkdir(parents=True, exist_ok=True)
    (args.salida / "calibracion.md").write_text(texto, "utf-8")
    (args.salida / "calibracion.json").write_text(_json(ajustes, videos, sop, mejor), "utf-8")
    print(texto)
    print(
        f"# .env\n"
        f"UMBRAL_BAJO={mejor.bajo:.2f}\n"
        f"UMBRAL_ALTO={mejor.alto:.2f}\n"
        f"UMBRAL_FUSION={mejor.fusion:.2f}",
        file=sys.stderr,
    )
    return 0


def _json(ajustes: list[Ajuste], videos: list[Video], sop: SOP, mejor: Ajuste) -> str:
    """El JSON que respalda el ADR: la rejilla completa, para no repetir la corrida."""
    return (
        json.dumps(
            {
                "sop": sop.titulo,
                "videos": {
                    v.clave: {"pasos_del_video": len(v.pasos), "esperados": len(v.esperado)}
                    for v in videos
                },
                "elegido": {
                    "umbral_bajo": mejor.bajo,
                    "umbral_alto": mejor.alto,
                    "umbral_fusion": mejor.fusion,
                    "f1": round(mejor.f1, 6),
                },
                "ajustes": [
                    {
                        "umbral_bajo": a.bajo,
                        "umbral_alto": a.alto,
                        "umbral_fusion": a.fusion,
                        "f1": round(a.f1, 6),
                        "tp": a.tp,
                        "fp": a.fp,
                        "fn": a.fn,
                        "por_video": {c: round(f, 6) for c, f in a.por_video.items()},
                    }
                    for a in ajustes
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    sys.exit(main())
