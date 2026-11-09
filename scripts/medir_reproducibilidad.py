r"""Mide RNF-07 ("mismo porcentaje en dos corridas") en dos niveles, con videos reales.

1. **Reproducibilidad del reporte:** de cada validación nueva, `--regeneraciones` validaciones más
   que reusan su segmentación y su ficha de contexto, como `POST /videos/{id}/validar` (RNF-07,
   ADR-022). Las regeneraciones deben dar entre sí el mismo `ResultadoValidacion`, sin contar los
   segundos ni la marca `segmentacion_reusada`. Aparte se informa si son iguales a la validación
   original: ahí el juez corre después de la ficha y la segmentación en la misma carga de Gemma,
   y su redacción puede cambiar aunque la entrada sea la misma (ADR-022).
2. **Estabilidad del análisis:** `--repeticiones` validaciones con segmentación nueva de Gemma.
   El porcentaje se informa como rango (la segmentación de Gemma no es determinista, ADR-022).

Whisper corre una vez por video (`preparar` de `medir_mvp.py`); Gemma se descarga antes de cada
validación, como la API. Uso, con Ollama arriba:

    python scripts/medir_reproducibilidad.py --sop tests/fixtures/sop_filtro_agua.md \
        --repeticiones 6 --regeneraciones 2 --docs video_a=media/videos/VIDEO-A.mp4

Salida en `data/interim/rnf07/` y, con `--docs`, en `docs/adr/datos/rnf07/`: solo porcentajes,
semáforos, conteos, huellas y segundos, sin texto del video ni del SOP.
Código de salida: 0 si las regeneraciones de cada validación son idénticas entre sí; 1 si no.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from medir_mvp import estado_git, preparar

from sopvid.contrato import ResultadoValidacion
from sopvid.lenguaje.emparejamiento import get_embedder
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.lenguaje.validacion import DependenciasValidacion, Detenida, Validacion, validar
from sopvid.plataforma.config import PROJECT_ROOT, get_settings

logger = logging.getLogger("medir_reproducibilidad")
SALIDA = PROJECT_ROOT / "data" / "interim" / "rnf07"


def comparable(resultado: ResultadoValidacion) -> dict[str, Any]:
    """El resultado sin lo que cambia aunque el reporte sea el mismo: los segundos de cada etapa
    y del juez, y la marca de segmentación reusada."""
    datos = resultado.model_dump(mode="json")
    datos["metadatos"].pop("segundos", None)
    datos["metadatos"].pop("segmentacion_reusada", None)
    datos["resultado"]["clasificacion"]["resumen"].pop("segundos_juez", None)
    return datos


def huella(datos: Any) -> str:
    texto = json.dumps(datos, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(texto.encode()).hexdigest()[:12]


def rango(valores: list[float]) -> str:
    if not valores:
        return "—"
    menor, mayor = min(valores), max(valores)
    return f"{menor:.2f} %" if menor == mayor else f"{menor:.2f}–{mayor:.2f} %"


def _validar(analisis: Any, sop: Any, deps: Any, **kwargs: Any) -> Validacion:
    v = validar(analisis, sop, deps, **kwargs)
    if isinstance(v, Detenida):  # otro procedimiento (D): se sigue, como al continuar
        v = validar(analisis, sop, deps, **{**kwargs, "contexto": v.contexto, "continuar": True})
    assert isinstance(v, Validacion)
    return v


def medir(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    sop = convertir_sop(args.sop.read_text(encoding="utf-8")).sop
    embedder = get_embedder()
    videos = []
    for entrada in args.videos:
        clave, _, ruta = entrada.partition("=")
        analisis, segundos, dispositivos = preparar(
            clave, Path(ruta), settings, SALIDA, args.idioma
        )
        corridas = []
        for repeticion in range(1, args.repeticiones + 1):
            deps = DependenciasValidacion.desde_settings(settings)
            deps.embedder = embedder
            try:
                deps.llm.descargar()
                nueva = _validar(
                    analisis, sop, deps, segundos_analisis=segundos, dispositivos=dispositivos
                )
                base = huella(comparable(nueva.resultado))
                regeneradas = []
                for _ in range(args.regeneraciones):
                    deps.llm.descargar()
                    otra = _validar(
                        analisis,
                        sop,
                        deps,
                        dispositivos=dispositivos,
                        contexto=nueva.contexto,
                        segmentacion=nueva.segmentacion,
                        continuar=True,
                    )
                    regeneradas.append(
                        {
                            "huella": huella(comparable(otra.resultado)),
                            "reusada": otra.resultado.metadatos.segmentacion_reusada,
                            "cumplimiento": round(otra.resultado.cumplimiento, 2),
                            "segundos": otra.resultado.metadatos.segundos,
                        }
                    )
            finally:
                deps.cerrar()
            g = nueva.resultado
            corrida = {
                "repeticion": repeticion,
                "cumplimiento": round(g.cumplimiento, 2),
                "semaforo": g.semaforo,
                "conteo": dict(g.resultado.clasificacion.resumen.conteo),
                "rescatados": g.resultado.clasificacion.resumen.rescatados,
                "pasos_video": len(nueva.pasos_video),
                "huella": base,
                "regeneradas": regeneradas,
                "identicas": len({r["huella"] for r in regeneradas}) <= 1,
                "igual_a_la_original": all(r["huella"] == base for r in regeneradas),
            }
            corridas.append(corrida)
            logger.info(
                "%s #%d: %.2f %% (%d pasos); regeneradas idénticas: %s",
                clave,
                repeticion,
                g.cumplimiento,
                len(nueva.pasos_video),
                corrida["identicas"],
            )
        videos.append({"video": clave, "corridas": corridas})
    return {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "git": estado_git(),
        "sop": args.sop.as_posix(),
        "modelos": {"llm": settings.llm_model, "embedder": settings.embedder_model},
        "videos": videos,
    }


def informe(datos: dict[str, Any]) -> str:
    lineas = [
        f"# RNF-07: reproducibilidad del reporte y estabilidad del análisis ({datos['fecha']})",
        "",
        f"Commit `{datos['git'].get('commit')}`"
        + (" (con cambios sin commit)" if datos["git"].get("cambios_sin_commit") else "")
        + f". SOP: `{datos['sop']}`. Modelos: {datos['modelos']}.",
        "",
        "| Video | Segmentaciones nuevas | Porcentaje (rango) | Semáforos | Pasos del video"
        " | Regeneraciones idénticas entre sí | Iguales a la original |",
        "|---|---|---|---|---|---|---|",
    ]
    for v in datos["videos"]:
        c = v["corridas"]
        identicas = sum(x["identicas"] for x in c)
        originales = sum(x["igual_a_la_original"] for x in c)
        lineas.append(
            f"| {v['video']} | {len(c)} | {rango([x['cumplimiento'] for x in c])} "
            f"| {dict(Counter(x['semaforo'] for x in c))} "
            f"| {dict(sorted(Counter(x['pasos_video'] for x in c).items()))} "
            f"| {identicas}/{len(c)} | {originales}/{len(c)} |"
        )
    lineas += ["", "## Corridas", ""]
    lineas += ["| Video · rep. | % | Semáforo | Pasos | Rescatados | Huella | Regeneradas |"]
    lineas += ["|---|---|---|---|---|---|---|"]
    for v in datos["videos"]:
        for x in v["corridas"]:
            regeneradas = ", ".join(
                ("= original" if r["huella"] == x["huella"] else r["huella"])
                + ("" if r["reusada"] else " (sin reusar)")
                for r in x["regeneradas"]
            )
            lineas.append(
                f"| {v['video']} · {x['repeticion']} | {x['cumplimiento']} | {x['semaforo']} "
                f"| {x['pasos_video']} | {x['rescatados']} | {x['huella']} | {regeneradas} |"
            )
    return "\n".join(lineas) + "\n"


def todas_identicas(datos: dict[str, Any]) -> bool:
    return all(x["identicas"] for v in datos["videos"] for x in v["corridas"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+", help="clave=ruta del video o de su analisis.json")
    parser.add_argument("--sop", type=Path, required=True)
    parser.add_argument("--repeticiones", type=int, default=6, help="segmentaciones nuevas")
    parser.add_argument("--regeneraciones", type=int, default=2, help="por segmentación")
    parser.add_argument("--idioma")
    parser.add_argument("--docs", action="store_true", help="copiar a docs/adr/datos/rnf07/")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    datos = medir(args)
    sello = datetime.now().strftime("%Y%m%d-%H%M")
    destinos = [SALIDA] + ([PROJECT_ROOT / "docs" / "adr" / "datos" / "rnf07"] if args.docs else [])
    for carpeta in destinos:
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"rnf07-{sello}.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (carpeta / f"rnf07-{sello}.md").write_text(informe(datos), encoding="utf-8")
        print(f"escrito: {carpeta / f'rnf07-{sello}.md'}")
    return 0 if todas_identicas(datos) else 1


if __name__ == "__main__":
    sys.exit(main())
