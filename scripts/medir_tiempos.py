r"""Mide los tiempos del reporte (RF-16, ADR-021) con videos reales.

Prueba de aceptación, no calibración: el código no conoce ningún video ni ninguna frase. Por cada
video, Whisper corre una vez (`preparar` de `medir_mvp.py`) y la validación de producción
(`validar`: ficha, afinidad, pasos con Gemma 4, emparejamiento con el juez, personas y tiempos)
corre `--repeticiones` veces, descargando Gemma antes de cada una, como la API. Los tiempos son
código y MiniLM; lo que varía entre corridas son las fronteras de los pasos que elige Gemma.

Criterio, según la anotación de cada video (`--anotacion`): si algún paso trae
`esperado_tiempo: "Excede"` (video C), los pasos del SOP en *excede* deben ser exactamente esos;
si ninguno lo trae (A, B), la corrida solo informa (cuántos en_tiempo, menor y excede, y por qué
excede alguno). Una corrida con la segmentación de respaldo o con avisos no es válida.

Además compara, por paso emparejado, el tramo que eligió Gemma (inicio y duración medida) con el
tramo anotado a mano: del inicio anotado de ese paso al inicio anotado de lo siguiente (paso,
*Sobra*, cierre) o al final del video. El tramo anotado incluye la pausa después de hablar; el
medido no (ADR-021), así que se espera un poco más corto.

Uso, desde la raíz del repo, con el entorno activado y Ollama arriba:

    python scripts/medir_tiempos.py --sop tests/fixtures/sop_filtro_agua.md \
        --anotacion media/anotacion_ab.json --repeticiones 3 --docs \
        video_a=media/videos/VIDEO-A.mp4 video_b=media/videos/VIDEO-B.mp4 \
        video_c=data/synthetic/video_c/VIDEO-C.mp4

La clave antes del "=" es la de la anotación. Si la ruta termina en `.json`, se toma como un
`Analisis` ya calculado y no se corre Whisper.

Salida en `data/interim/tiempos/` (ignorada por git): `tiempos-<fecha>.json` y `.md`; con
`--docs`, también en `docs/adr/datos/tiempos/`. Los videos son del equipo (no del cliente); aun
así el informe solo lleva números de paso, segundos, estados y, si la hay, la cita corta de una
duración narrada. No modifica código, datos de entrada ni la base.

Código de salida: 0 si todas las corridas son válidas y pasan; 1 si alguna no pasa; 2 si alguna
no es válida (heurística o avisos), aunque las demás pasen.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from medir_mvp import estado_git, preparar

from sopvid.contrato import SOP
from sopvid.lenguaje.emparejamiento import get_embedder
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.lenguaje.validacion import DependenciasValidacion, Detenida, Validacion, validar
from sopvid.plataforma.config import PROJECT_ROOT, get_settings

logger = logging.getLogger("medir_tiempos")

# Holgura (s) para decir que un tramo de Gemma empieza antes o termina después del anotado.
HOLGURA_S = 2.0


def _sop(ruta: Path) -> SOP:
    return convertir_sop(ruta.read_text(encoding="utf-8")).sop


def excede_esperados(anotacion: dict[str, Any]) -> list[int] | None:
    """Los pasos del SOP anotados con `esperado_tiempo: "Excede"`, o None si no hay criterio."""
    pasos = anotacion.get("pasos", [])
    if not any("esperado_tiempo" in p for p in pasos):
        return None
    return sorted(p["sop"] for p in pasos if p.get("esperado_tiempo") == "Excede")


def tramos_anotados(anotacion: dict[str, Any], duracion_s: float) -> dict[int, tuple[float, float]]:
    """Paso del SOP → (inicio, fin) anotados: del inicio del paso al inicio de lo siguiente
    (cualquier entrada anotada, en orden de tiempo) o al final del video."""
    entradas = sorted(anotacion.get("pasos", []), key=lambda p: p["t"])
    fin_video = anotacion.get("duracion_s") or duracion_s
    tramos: dict[int, tuple[float, float]] = {}
    for i, entrada in enumerate(entradas):
        if isinstance(entrada.get("sop"), int):
            fin = entradas[i + 1]["t"] if i + 1 < len(entradas) else fin_video
            tramos[entrada["sop"]] = (float(entrada["t"]), float(fin))
    return tramos


def filas_de(v: Validacion, sop: SOP, anotados: dict[int, tuple[float, float]]) -> list[dict]:
    """Una fila por resultado de la clasificación, con el tramo de Gemma, el tiempo y, si hay,
    el tramo anotado del mismo paso del SOP."""
    g = v.resultado
    res = g.resultado
    tiempos = g.tiempos or [None] * len(res.clasificacion.pasos)
    filas = []
    for paso, tiempo in zip(res.clasificacion.pasos, tiempos, strict=True):
        fila: dict[str, Any] = {
            "estado": paso.estado,
            "paso_sop": None if paso.indice_sop is None else sop.pasos[paso.indice_sop].numero,
            "paso_video": None if paso.indice_video is None else paso.indice_video + 1,
            "fuera_de_orden": paso.fuera_de_orden,
            "marco_operador": paso.marco_operador,
        }
        if paso.indice_video is not None:
            video = res.pasos_video[paso.indice_video]
            fila["tramo"] = [video.t_inicio, video.t_fin]
            fila["originales"] = res.fusiones[paso.indice_video].originales
        if tiempo is not None:
            fila["tiempo"] = tiempo.model_dump(mode="json")
        if fila["paso_sop"] in anotados and "tramo" in fila:
            inicio, fin = anotados[fila["paso_sop"]]
            fila["anotado"] = [inicio, fin]
            fila["dif_inicio_s"] = round(fila["tramo"][0] - inicio, 2)
            fila["dif_duracion_s"] = round(
                (fila["tramo"][1] - fila["tramo"][0]) - (fin - inicio), 2
            )
        filas.append(fila)
    return filas


def por_que_excede(fila: dict[str, Any]) -> list[str]:
    """Explicaciones de un *excede* que se pueden leer del tramo: fusión, tramo que empieza antes
    del inicio anotado (intro u otro paso pegado) o que pasa al siguiente paso anotado."""
    notas = []
    if len(fila.get("originales", [])) > 1:
        notas.append(f"fusión de {len(fila['originales'])} pasos del video")
    if fila.get("tiempo", {}).get("origen") == "narrado":
        notas.append("duración narrada")
    if "anotado" in fila:
        (t0, t1), (a0, a1) = fila["tramo"], fila["anotado"]
        if t0 < a0 - HOLGURA_S:
            notas.append(f"empieza {a0 - t0:.1f} s antes del inicio anotado")
        if t1 > a1 + HOLGURA_S:
            notas.append(f"termina {t1 - a1:.1f} s después del inicio anotado de lo siguiente")
    return notas or ["el paso duró más que lo esperado"]


def criterio(
    esperados: list[int] | None, filas: list[dict[str, Any]], valida: bool
) -> tuple[bool, list[str]]:
    """(pasa, motivos). Sin criterio de la anotación, pasa si la corrida es válida."""
    motivos = [] if valida else ["corrida no válida (heurística o avisos)"]
    if esperados is not None:
        excede = sorted(
            f["paso_sop"] for f in filas if f.get("tiempo", {}).get("estado") == "excede"
        )
        if excede != esperados:
            motivos.append(f"excede en los pasos {excede}; se esperaban {esperados}")
    return not motivos, motivos


def corrida_de(
    clave: str,
    repeticion: int,
    v: Validacion,
    sop: SOP,
    anotacion: dict[str, Any],
    duracion_s: float,
) -> dict[str, Any]:
    g = v.resultado
    filas = filas_de(v, sop, tramos_anotados(anotacion, duracion_s))
    estados = Counter(f["tiempo"]["estado"] for f in filas if "tiempo" in f)
    for fila in filas:
        if fila.get("tiempo", {}).get("estado") == "excede":
            fila["por_que"] = por_que_excede(fila)
    valida = g.metadatos.segmentacion == "llm" and not g.metadatos.avisos
    pasa, motivos = criterio(excede_esperados(anotacion), filas, valida)
    return {
        "video": clave,
        "repeticion": repeticion,
        "duracion_s": duracion_s,
        "cumplimiento": round(g.cumplimiento, 2),
        "conteo": dict(g.resultado.clasificacion.resumen.conteo),
        "estados_tiempo": {e: estados.get(e, 0) for e in ("en_tiempo", "menor", "excede")}
        | ({"sin_referencia": estados["sin_referencia"]} if estados["sin_referencia"] else {}),
        "fuera_de_tiempo": estados.get("excede", 0),
        "total": None if g.tiempo_total is None else g.tiempo_total.model_dump(mode="json"),
        "horario": None if g.horario is None else g.horario.model_dump(mode="json"),
        "filas": filas,
        "avisos": [a.tipo for a in g.metadatos.avisos],
        "segmentacion": g.metadatos.segmentacion,
        "valida": valida,
        "pasa": pasa,
        "motivos": motivos,
    }


def medir(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    sop = _sop(args.sop)
    anotaciones = json.loads(args.anotacion.read_text(encoding="utf-8"))
    embedder = get_embedder()
    trabajo = PROJECT_ROOT / "data" / "interim" / "tiempos"
    corridas = []
    for entrada in args.videos:
        clave, _, ruta = entrada.partition("=")
        analisis, segundos, dispositivos = preparar(
            clave, Path(ruta), settings, trabajo, args.idioma
        )
        for repeticion in range(1, args.repeticiones + 1):
            deps = DependenciasValidacion.desde_settings(settings)
            deps.embedder = embedder
            try:
                deps.llm.descargar()
                inicio = time.perf_counter()
                v = validar(
                    analisis, sop, deps, segundos_analisis=segundos, dispositivos=dispositivos
                )
                if isinstance(v, Detenida):  # no se espera con estos videos: se sigue igual
                    v = validar(
                        analisis,
                        sop,
                        deps,
                        dispositivos=dispositivos,
                        contexto=v.contexto,
                        continuar=True,
                    )
                total_s = round(time.perf_counter() - inicio, 2)
            finally:
                deps.cerrar()
            assert isinstance(v, Validacion)
            corrida = corrida_de(
                clave, repeticion, v, sop, anotaciones.get(clave, {}), analisis.duracion_s
            )
            corrida["segundos_total"] = total_s
            corridas.append(corrida)
            logger.info(
                "%s #%d: %s; %s",
                clave,
                repeticion,
                corrida["estados_tiempo"],
                "pasa" if corrida["pasa"] else f"NO pasa: {corrida['motivos']}",
            )
    return {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "git": estado_git(),
        "sop": args.sop.as_posix(),
        "anotacion": args.anotacion.as_posix(),
        "modelos": {
            "llm": settings.llm_model,
            "embedder": settings.embedder_model,
            "whisper": settings.whisper_modelo,
        },
        "umbrales": {
            "tolerancia_tiempo": settings.tolerancia_tiempo,
            "umbral_horario": settings.umbral_horario,
        },
        "corridas": corridas,
    }


def _min(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:.2f}"


def informe(datos: dict[str, Any]) -> str:
    lineas = [
        f"# Tiempos con videos reales ({datos['fecha']})",
        "",
        f"Commit `{datos['git'].get('commit')}`"
        + (" (con cambios sin commit)" if datos["git"].get("cambios_sin_commit") else "")
        + f". SOP: `{datos['sop']}`. Modelos: {datos['modelos']}. Umbrales: {datos['umbrales']}.",
        "",
        "| Video · rep. | Cumpl. | en_tiempo / menor / excede | Excede en"
        " | Total (obs./esp., estado) | Horario | Criterio |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in datos["corridas"]:
        e = c["estados_tiempo"]
        excede = [
            f["paso_sop"] for f in c["filas"] if f.get("tiempo", {}).get("estado") == "excede"
        ]
        t = c["total"] or {}
        h = c["horario"] or {}
        lineas.append(
            f"| {c['video']} · {c['repeticion']} | {c['cumplimiento']} "
            f"| {e['en_tiempo']} / {e['menor']} / {e['excede']} | {excede or '—'} "
            f"| {_min(t.get('observado_min'))} / {_min(t.get('esperado_min'))}, {t.get('estado')} "
            f"| {h.get('estado')} "
            f"| {'pasa' if c['pasa'] else 'NO: ' + '; '.join(c['motivos'])} |"
        )
    lineas += ["", "## Pasos emparejados: tramo de Gemma contra el anotado", ""]
    for c in datos["corridas"]:
        lineas += [
            f"### {c['video']} · {c['repeticion']}",
            "",
            "| SOP ↔ video | Estado | Tramo Gemma (s) | Originales | Observado (min, origen)"
            " | Tiempo | Anotado (s) | Δ inicio (s) | Δ duración (s) | Por qué excede |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for f in c["filas"]:
            if "tiempo" not in f:
                continue
            tiempo = f["tiempo"]
            anotado = f.get("anotado")
            origen = tiempo["origen"] + (f": «{tiempo['cita']}»" if tiempo["cita"] else "")
            lineas.append(
                f"| {f['paso_sop']} ↔ {f['paso_video']} | {f['estado']}"
                + (" (fuera de orden)" if f["fuera_de_orden"] else "")
                + f" | {f['tramo'][0]:.1f}–{f['tramo'][1]:.1f} | {f['originales']} "
                f"| {tiempo['observado_min']:.2f} ({origen}) | {tiempo['estado']} "
                f"| {f'{anotado[0]:.1f}–{anotado[1]:.1f}' if anotado else '—'} "
                f"| {f.get('dif_inicio_s', '—')} | {f.get('dif_duracion_s', '—')} "
                f"| {'; '.join(f.get('por_que', [])) or '—'} |"
            )
        lineas.append("")
    return "\n".join(lineas) + "\n"


def codigo_salida(corridas: list[dict[str, Any]]) -> int:
    if not all(c["valida"] for c in corridas):
        return 2
    return 0 if all(c["pasa"] for c in corridas) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+", help="clave=ruta del video o de su analisis.json")
    parser.add_argument("--sop", type=Path, required=True, help="SOP en Markdown (ADR-015)")
    parser.add_argument("--anotacion", type=Path, required=True, help="JSON de la anotación")
    parser.add_argument("--repeticiones", type=int, default=3, help="validaciones por video")
    parser.add_argument("--idioma", help="ISO 639-1 para Whisper; sin él, lo detecta")
    parser.add_argument("--docs", action="store_true", help="copiar a docs/adr/datos/tiempos/")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    datos = medir(args)
    sello = datetime.now().strftime("%Y%m%d-%H%M")
    destinos = [PROJECT_ROOT / "data" / "interim" / "tiempos"]
    if args.docs:
        destinos.append(PROJECT_ROOT / "docs" / "adr" / "datos" / "tiempos")
    for carpeta in destinos:
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"tiempos-{sello}.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (carpeta / f"tiempos-{sello}.md").write_text(informe(datos), encoding="utf-8")
        print(f"escrito: {carpeta / f'tiempos-{sello}.md'}")
    return codigo_salida(datos["corridas"])


if __name__ == "__main__":
    sys.exit(main())
