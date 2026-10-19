"""Experimento MiniLM para fronteras (19 oct, ADR-010). Resultado INDICATIVO: n=4.

Compara, en las 3 transcripciones inventadas de la Fase 4 más analisis_ejemplo:

  heurística            marcadores de transición + pausas (segmentacion.segmentar_heuristica)
  Gemma (opción A)      cortes YA GUARDADOS en pasos_video.json, variante "opción A + prompt de
                        redacción final" (3 repeticiones); no se llama a Ollama
  M1                    TextTiling con embeddings MiniLM (fronteras_minilm.inicios_texttiling)
  M2                    fusión de los cortes de Gemma con MiniLM (fronteras_minilm.fusionar_inicios)

Selección de parámetros (fijada antes de medir):

- Valores por defecto: k=2, c=0.5, u=0.6 (commit 6ff2f9f, anterior a esta medición).
- Barrido: c en {0, 0.25, 0.5, 0.75, 1.0} (M1, con k=2); u en {0.5, 0.55, …, 0.75} (M2).
- Validación dejando una fuera: para cada transcripción, se elige el valor con mejor F1 agregado
  (±1 segmento) en las otras 3 (en M2, mediana de las 3 repeticiones) y se mide en la que quedó
  fuera. Empate: el valor más cercano al de por defecto; si sigue, el menor. Ese es el F1
  honesto. El "mejor del barrido" elige con las 4 a la vez y es OPTIMISTA.

Métricas: las de scripts/evaluar_segmentacion.py (`evaluar`): F1 de fronteras a ±1 segmento, F1
en tiempo a ±2 s, falsos positivos y no detectados. Milisegundos por transcripción: mediana de
5 corridas de la función completa (embeddings incluidos) con el modelo ya cargado; la carga del
modelo se reporta aparte. En M2 son los ms de MiniLM, que se suman a los segundos de Gemma.

Uso (desde la raíz, con el .venv; la primera vez descarga MiniLM a EMBEDDER_CACHE_DIR):
    python scripts/evaluar_fronteras_minilm.py
    python scripts/evaluar_fronteras_minilm.py --tabla
"""

import argparse
import json
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import evaluar_segmentacion as ev  # mismo directorio: fixtures y métrica de la Fase 4
import torch

from sopvid.lenguaje.emparejamiento import Embedder
from sopvid.percepcion import fronteras_minilm as fm
from sopvid.percepcion.segmentacion import segmentar_heuristica, segmentos_de_inicio
from sopvid.plataforma.config import PROJECT_ROOT

DATOS = PROJECT_ROOT / "docs/adr/datos/segmentacion"
PASOS_VIDEO = DATOS / "pasos_video.json"
SALIDA = DATOS / "fronteras_minilm.json"
METODO_GEMMA = "gemma4:e4b-it-q4_K_M · opción A"  # = "opción A + prompt de redacción final"
COMMIT_DEFECTOS = "6ff2f9f"
DEFECTO = {"c": fm.C_PROFUNDIDAD, "u": fm.U_FUSION}
REJILLA = {"c": [0.0, 0.25, 0.5, 0.75, 1.0], "u": [0.5, 0.55, 0.6, 0.65, 0.7, 0.75]}
METODO_DE = {"c": "M1", "u": "M2"}
REPETICIONES_TIEMPO = 5


def _ms(funcion: Callable[[], Any]) -> float:
    tiempos = []
    for _ in range(REPETICIONES_TIEMPO):
        inicio = time.perf_counter()
        funcion()
        tiempos.append(1000 * (time.perf_counter() - inicio))
    return round(statistics.median(tiempos), 1)


def correr() -> dict[str, Any]:
    fixtures = ev.cargar_fixtures(incluir_ejemplo=True)
    guardadas = json.loads(PASOS_VIDEO.read_text(encoding="utf-8"))
    gemma = [c for c in guardadas["corridas"] if c["metodo"] == METODO_GEMMA]
    assert {c["fixture"] for c in gemma} == set(fixtures), "faltan corridas de Gemma"

    embedder = Embedder()
    embedder.cargar()
    embedder.embed(["calentamiento"])  # la primera inferencia paga inicializaciones de torch
    print(f"MiniLM cargado en {embedder.segundos_carga:.1f} s", flush=True)

    corridas: list[dict[str, Any]] = []
    tiempos: dict[str, dict[str, float]] = {}
    diagnostico: dict[str, dict[str, list[float]]] = {}

    def agregar(metodo: str, fixture: str, rep: int, ids: list[int], **extra: Any) -> None:
        corridas.append(
            {"metodo": metodo, "fixture": fixture, "repeticion": rep, "ids": ids, **extra}
            | ev.evaluar(ids, fixtures[fixture])
        )

    for nombre, fx in fixtures.items():
        a = fx["analisis"]
        agregar("heuristica", nombre, 1, segmentos_de_inicio(segmentar_heuristica(a), a))
        de_gemma = sorted(
            (c for c in gemma if c["fixture"] == nombre), key=lambda c: c["repeticion"]
        )
        for c in de_gemma:
            agregar("gemma", nombre, c["repeticion"], c["ids"], segundos=c["segundos"])

        x = fm.embeber_segmentos(a, embedder)
        posicion = {s.id: i for i, s in enumerate(a.transcripcion)}
        a_ids = [s.id for s in a.transcripcion]
        for c in REJILLA["c"]:
            agregar("M1", nombre, 1, [a_ids[p] for p in fm.cortes_texttiling(x, c=c)], c=c)
        for u in REJILLA["u"]:
            for g in de_gemma:
                fusion = fm.fusionar_cortes(x, [posicion[i] for i in g["ids"]], u=u)
                agregar("M2", nombre, g["repeticion"], [a_ids[p] for p in fusion], u=u)

        # Diagnóstico de M2: coseno en cada corte de Gemma (repetición 1), real o de más.
        g1 = next(c for c in corridas if c["metodo"] == "gemma" and c["fixture"] == nombre)
        sims = fm.cosenos_entre_pasos(x, [posicion[i] for i in g1["ids"]])
        diagnostico[nombre] = {"cortes_reales": [], "cortes_de_mas": []}
        for i, s in zip(g1["ids"][1:], sims, strict=True):
            clave = "cortes_de_mas" if i in g1["falsos_positivos"] else "cortes_reales"
            diagnostico[nombre][clave].append(round(s, 3))

        tiempos[nombre] = {
            "segmentos": len(a.transcripcion),
            "embeddings_ms": _ms(lambda a=a: fm.embeber_segmentos(a, embedder)),
            "M1_ms": _ms(lambda a=a: fm.inicios_texttiling(a, embedder)),
            "M2_ms": _ms(lambda a=a, g=de_gemma[0]: fm.fusionar_inicios(a, g["ids"], embedder)),
            "gemma_s": round(statistics.median(c["segundos"] for c in de_gemma), 2),
        }
        print(f"{nombre}: {tiempos[nombre]}", flush=True)

    return {
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "nota": (
            "Resultado INDICATIVO: 4 transcripciones inventadas (n=4), inicios marcados a mano. "
            "El 'mejor del barrido' es optimista: elige con las mismas 4 transcripciones."
        ),
        "parametros": {
            "por_defecto": {"k": fm.K_VENTANA, **DEFECTO},
            "por_defecto_fijados_en_commit": COMMIT_DEFECTOS,
            "rejilla": REJILLA,
            "separacion_min": fm.SEPARACION_MIN,
            "seleccion": (
                "Dejando una fuera: mejor F1 agregado (±1 segmento) en las otras 3; en M2, mediana "
                "de las 3 repeticiones. Empate: más cercano al valor por defecto; luego el menor."
            ),
            "cortes_gemma": f"{PASOS_VIDEO.name}, método '{METODO_GEMMA}' (3 repeticiones)",
            "embedder": embedder.modelo,
            "dispositivo": "cpu",
            "torch": torch.__version__,
            "tolerancia_segmentos": 1,
            "repeticiones_tiempo": REPETICIONES_TIEMPO,
        },
        "carga_modelo_s": round(embedder.segundos_carga or 0.0, 2),
        "fixtures": {n: {"inicios_paso": fx["inicios_paso"]} for n, fx in fixtures.items()},
        "tiempos": tiempos,
        "diagnostico_m2": diagnostico,
        "corridas": corridas,
    }


# ── Agregados y selección ───────────────────────────────────────────────────────────────────


def _f1(tp: int, n_pred: int, n_real: int) -> float:
    p, r = tp / n_pred if n_pred else 0.0, tp / n_real if n_real else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def agregado(cs: list[dict[str, Any]]) -> dict[str, float]:
    """Métricas agregadas (micro) por repetición y su mediana entre repeticiones."""
    por_rep = []
    for rep in sorted({c["repeticion"] for c in cs}):
        rs = [c for c in cs if c["repeticion"] == rep]
        n_pred, n_real = sum(c["n_predichos"] for c in rs), sum(c["n_reales"] for c in rs)
        tp, tp2 = sum(c["tp"] for c in rs), sum(c["f1_tiempo_2s"]["tp"] for c in rs)
        por_rep.append(
            {
                "f1": _f1(tp, n_pred, n_real),
                "f1_2s": _f1(tp2, n_pred, n_real),
                "p": tp / n_pred if n_pred else 0.0,
                "r": tp / n_real if n_real else 0.0,
                "fp": sum(len(c["falsos_positivos"]) for c in rs),
                "nd": sum(len(c["no_detectados"]) for c in rs),
                "pred": n_pred,
            }
        )
    return {k: statistics.median(r[k] for r in por_rep) for k in por_rep[0]}


def _de(datos: dict[str, Any], metodo: str, **filtro: Any) -> list[dict[str, Any]]:
    return [
        c
        for c in datos["corridas"]
        if c["metodo"] == metodo and all(c.get(k) == v for k, v in filtro.items())
    ]


def elegir(datos: dict[str, Any], param: str, fixtures: list[str]) -> tuple[float, float]:
    """Valor de la rejilla con mejor F1 agregado en `fixtures` (desempate fijado) y ese F1."""
    metodo = METODO_DE[param]

    def puntaje(v: float) -> float:
        cs = [c for c in _de(datos, metodo, **{param: v}) if c["fixture"] in fixtures]
        return round(agregado(cs)["f1"], 9)

    defecto = datos["parametros"]["por_defecto"][param]
    mejor = min(
        datos["parametros"]["rejilla"][param],
        key=lambda v: (-puntaje(v), abs(v - defecto), v),
    )
    return mejor, puntaje(mejor)


def seleccion(datos: dict[str, Any], param: str) -> dict[str, Any]:
    """Dejando una fuera: valor elegido con las otras 3 y corridas de la que quedó fuera."""
    fixtures = list(datos["fixtures"])
    metodo = METODO_DE[param]
    por_fixture, fuera = {}, []
    for f in fixtures:
        v, f1_entrenamiento = elegir(datos, param, [g for g in fixtures if g != f])
        cs = [c for c in _de(datos, metodo, **{param: v}) if c["fixture"] == f]
        fuera += cs
        por_fixture[f] = {"valor": v, "f1_otras_3": f1_entrenamiento, **agregado(cs)}
    mejor, _ = elegir(datos, param, fixtures)
    return {"por_fixture": por_fixture, "corridas_fuera": fuera, "mejor_barrido": mejor}


# ── Tablas ──────────────────────────────────────────────────────────────────────────────────


def filas(datos: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]], str]]:
    """(nombre, corridas, ms) de cada fila de la comparación."""
    t = datos["tiempos"]
    fixtures = list(datos["fixtures"])

    def ms(clave: str) -> str:
        return f"{statistics.median(t[f][clave] for f in fixtures):.0f}"

    gemma_s = statistics.median(t[f]["gemma_s"] for f in fixtures)
    resultado = [
        ("Heurística", _de(datos, "heuristica"), "< 10"),
        ("Gemma (opción A)", _de(datos, "gemma"), f"{1000 * gemma_s:,.0f}"),
    ]
    for param in ("c", "u"):
        metodo, sel = METODO_DE[param], seleccion(datos, param)
        defecto = datos["parametros"]["por_defecto"][param]
        extra = "Gemma + " if param == "u" else ""
        tiempo = extra + ms(f"{metodo}_ms")
        elegidos = sorted({x["valor"] for x in sel["por_fixture"].values()})
        resultado += [
            (
                f"{metodo} · por defecto ({param}={defecto:g})",
                _de(datos, metodo, **{param: defecto}),
                tiempo,
            ),
            (
                f"{metodo} · dejando una fuera ({param} ∈ {{{_lista(elegidos)}}})",
                sel["corridas_fuera"],
                tiempo,
            ),
            (
                f"{metodo} · mejor del barrido ({param}={sel['mejor_barrido']:g}) · OPTIMISTA",
                _de(datos, metodo, **{param: sel["mejor_barrido"]}),
                tiempo,
            ),
        ]
    return resultado


def _lista(valores: list[float]) -> str:
    return ", ".join(f"{v:g}" for v in valores)


def tablas(datos: dict[str, Any]) -> None:
    fixtures = list(datos["fixtures"])
    print(
        "\nExperimento MiniLM para fronteras. INDICATIVO, n=4 transcripciones inventadas. "
        "Gemma y M2: mediana de 3 repeticiones.\n"
    )
    print("Total (agregado micro de las 4 transcripciones)\n")
    print(
        "| Método | F1 ±1 seg | F1 ±2 s | P | R | Pasos predichos | FP | ND "
        "| ms por transcripción |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    reales = sum(len(fx["inicios_paso"]) for fx in datos["fixtures"].values())
    for nombre, cs, ms in filas(datos):
        a = agregado(cs)
        print(
            f"| {nombre} | **{a['f1']:.3f}** | {a['f1_2s']:.3f} | {a['p']:.3f} | {a['r']:.3f} "
            f"| {a['pred']:g} / {reales} | {a['fp']:g} | {a['nd']:g} | {ms} |"
        )

    print("\nPor transcripción: F1 ±1 segmento (FP / ND)\n")
    print("| Método | " + " | ".join(fixtures) + " |")
    print("|---|" + "---|" * len(fixtures))
    for nombre, cs, _ in filas(datos):
        celdas = []
        for f in fixtures:
            a = agregado([c for c in cs if c["fixture"] == f])
            celdas.append(f"{a['f1']:.3f} ({a['fp']:g} / {a['nd']:g})")
        print(f"| {nombre} | " + " | ".join(celdas) + " |")

    print(
        "\nValidación dejando una fuera: valor elegido con las otras 3 y F1 en la que quedó fuera\n"
    )
    print(
        "| Transcripción fuera | c elegido (F1 otras 3) | F1 M1 fuera "
        "| u elegido (F1 otras 3) | F1 M2 fuera |"
    )
    print("|---|---|---|---|---|")
    s1, s2 = seleccion(datos, "c")["por_fixture"], seleccion(datos, "u")["por_fixture"]
    for f in fixtures:
        print(
            f"| {f} | {s1[f]['valor']:g} ({s1[f]['f1_otras_3']:.3f}) | {s1[f]['f1']:.3f} "
            f"| {s2[f]['valor']:g} ({s2[f]['f1_otras_3']:.3f}) | {s2[f]['f1']:.3f} |"
        )

    print("\nBarrido completo (agregado de las 4; optimista)\n")
    print("| Método | Valor | F1 ±1 seg | F1 ±2 s | FP | ND | Pasos predichos |")
    print("|---|---|---|---|---|---|---|")
    for param in ("c", "u"):
        for v in datos["parametros"]["rejilla"][param]:
            a = agregado(_de(datos, METODO_DE[param], **{param: v}))
            print(
                f"| {METODO_DE[param]} | {param}={v:g} | {a['f1']:.3f} | {a['f1_2s']:.3f} "
                f"| {a['fp']:g} | {a['nd']:g} | {a['pred']:g} |"
            )

    print(f"\nCarga de MiniLM (CPU, desde la caché): {datos['carga_modelo_s']} s, aparte.\n")
    print("| Transcripción | Segmentos | Embeddings ms | M1 ms | M2 ms | Gemma s |")
    print("|---|---|---|---|---|---|")
    for f, t in datos["tiempos"].items():
        print(
            f"| {f} | {t['segmentos']} | {t['embeddings_ms']} | {t['M1_ms']} | {t['M2_ms']} "
            f"| {t['gemma_s']} |"
        )

    print(
        "\nDiagnóstico de M2: coseno entre pasos vecinos en cada corte de Gemma (repetición 1). "
        "M2 solo funciona si los cortes de más tienen coseno mayor que los reales.\n"
    )
    print("| Transcripción | Cortes reales: n · mediana · rango | De más: n · mediana · rango |")
    print("|---|---|---|")

    def resumen(xs: list[float]) -> str:
        if not xs:
            return "0 · — · —"
        return f"{len(xs)} · {statistics.median(xs):.2f} · {min(xs):.2f}–{max(xs):.2f}"

    for f, dg in datos["diagnostico_m2"].items():
        print(f"| {f} | {resumen(dg['cortes_reales'])} | {resumen(dg['cortes_de_mas'])} |")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--tabla", action="store_true", help="solo imprime las tablas guardadas")
    args = ap.parse_args()
    if not args.tabla:
        datos = correr()
        SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nResultados en {SALIDA}")
    tablas(json.loads(SALIDA.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
