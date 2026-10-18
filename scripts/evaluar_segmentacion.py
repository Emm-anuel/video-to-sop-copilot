"""Evalúa la segmentación en pasos (Fase 4, ADR-010): heurística vs. LLM. Resultado INDICATIVO.

Transcripciones inventadas de tests/fixtures/transcripciones/ con inicios de paso marcados a
mano. Para cada método mide F1 de fronteras a ±1 segmento (`segmentacion.f1_fronteras`) y, como
segunda vista, F1 en tiempo a ±2/4/6 s reutilizando `sopvid.features.pasos.label_phrases`.

Métodos (`--versiones`):
  heuristica                  marcadores de transición + pausas (determinista, 1 corrida)
  <modelo> · prompt v1        una llamada: cortes con la regla del prompt v1 de ADR-006 (en la
                              Fase 4, solo segmento y título; desde RF-13, los cinco campos)
  <modelo> · prompt v2        v1 + regla explícita: aclaraciones, advertencias y comentarios
                              dentro de un paso no inician un paso nuevo
  <modelo> · opción A         dos llamadas (ADR-010): fronteras con el prompt v1 de la Fase 4
                              y, aparte, la redacción de cada paso

Cada combinación LLM corre 3 veces; se reporta la mediana y si los cortes fueron estables. Se
usa `segmentar()`, así que si el LLM falla o su propuesta es inválida se registra el respaldo.

Con `--incluir-ejemplo` se agrega tests/fixtures/analisis_ejemplo.json (contrato `Analisis`,
inicios de paso anotados en tests/fixtures/README.md, sin etiquetas).

Uso (con el profile "llm" arriba y los modelos descargados):
    python scripts/evaluar_segmentacion.py
    python scripts/evaluar_segmentacion.py --modelos gemma4:12b-it-qat --versiones v1
    python scripts/evaluar_segmentacion.py --tabla
    python scripts/evaluar_segmentacion.py --modelos gemma4:e4b-it-q4_K_M --versiones v1
        --incluir-ejemplo --salida docs/adr/datos/segmentacion/pasos_video.json

Volver a correr un método reemplaza solo sus corridas; las demás se conservan.
"""

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import benchmark_llm as bench  # mismo directorio: nvidia-smi y logs de Ollama
import httpx
import numpy as np
import pandas as pd

from sopvid.contrato import Analisis
from sopvid.features import pasos as fp
from sopvid.lenguaje.llm import SEMILLA, ClienteLLM
from sopvid.percepcion.segmentacion import (
    cargar_transcripcion_prueba,
    f1_fronteras,
    segmentar,
    segmentar_heuristica,
    segmentos_de_inicio,
)
from sopvid.plataforma.config import PROJECT_ROOT, get_settings

FIXTURES = PROJECT_ROOT / "tests/fixtures/transcripciones"
SALIDA = PROJECT_ROOT / "docs/adr/datos/segmentacion/fase4.json"
EJEMPLO = PROJECT_ROOT / "tests/fixtures/analisis_ejemplo.json"
INICIOS_EJEMPLO = [4, 6, 9, 12, 17, 21]  # anotados a mano en tests/fixtures/README.md
MODELOS = ("gemma4:e4b-it-q4_K_M", "qwen3.5:9b-q4_K_M")
REPETICIONES = 3
NOMBRES = {"v1": "prompt v1", "v2": "prompt v2", "a": "opción A"}  # --versiones


def cargar_fixtures(incluir_ejemplo: bool = False) -> dict[str, dict[str, Any]]:
    """JSON de cada transcripción (etiquetas, inicios_paso…) más su `Analisis` en "analisis"."""
    fixtures = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        | {"analisis": cargar_transcripcion_prueba(p)}
        for p in sorted(FIXTURES.glob("*.json"))
    }
    if incluir_ejemplo:
        analisis = Analisis.model_validate_json(EJEMPLO.read_text(encoding="utf-8"))
        fixtures[EJEMPLO.stem] = {
            "segmentos": [s.model_dump(exclude={"palabras"}) for s in analisis.transcripcion],
            "etiquetas": {},
            "inicios_paso": INICIOS_EJEMPLO,
            "analisis": analisis,
        }
    return fixtures


def f1_tiempo(t_predichos: list[float], t_reales: list[float], tol: float) -> dict[str, float]:
    """F1 en segundos con la asignación de `features.pasos`: cada inicio real marca el predicho
    más cercano a ≤ tol s; un predicho cuenta una sola vez aunque lo marquen dos inicios."""
    frases = pd.DataFrame({fp.VID: "v", "t_inicio": sorted(t_predichos)})
    reales = pd.DataFrame(
        {
            fp.VID: "v",
            "step_id": range(len(t_reales)),
            "start": t_reales,
            "end": np.nan,
            "partial": False,
        }
    )
    tp = int(fp.label_phrases(frases, reales, tol).sum()) if len(frases) else 0
    p = tp / len(t_predichos) if t_predichos else 0.0
    r = tp / len(t_reales) if t_reales else 0.0
    return {"tp": tp, "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}


def evaluar(ids: list[int], fx: dict[str, Any]) -> dict[str, Any]:
    t_de = {s["id"]: s["t_inicio"] for s in fx["segmentos"]}
    t_pred = [t_de[i] for i in ids]
    t_real = [t_de[i] for i in fx["inicios_paso"]]
    return f1_fronteras(ids, fx["inicios_paso"]) | {
        f"f1_tiempo_{tol}s": f1_tiempo(t_pred, t_real, tol) for tol in fp.TOLERANCIAS
    }


def medir_carga(modelo: str, contenedor: str) -> dict[str, Any]:
    """Capas en GPU y VRAM real del modelo (mismo método que el benchmark de ADR-006)."""
    settings = get_settings()
    with httpx.Client(base_url=settings.llm_base_url, timeout=settings.llm_timeout_s) as http:
        bench.descargar_todo(http)
        antes = bench.nvidia_smi()
        desde = time.time() - 2
        inicio = time.perf_counter()
        http.post(
            "/api/chat",
            json={
                "model": modelo,
                "messages": [{"role": "user", "content": "hola"}],
                "stream": False,
                "options": {"num_ctx": settings.llm_num_ctx, "num_predict": 1},
            },
        ).raise_for_status()
        carga_s = round(time.perf_counter() - inicio, 1)
        despues = bench.nvidia_smi()
    logs = bench.analizar_logs(bench.docker_logs(contenedor, desde)) if contenedor else {}
    return {
        "capas_gpu": logs.get("capas_gpu"),
        "flash_attn": logs.get("flash_attn"),
        "mtp": logs.get("mtp"),
        "vram_libre_antes_mib": antes.get("libre_mib"),
        "vram_real_mib": (
            despues["usada_mib"] - antes["usada_mib"]
            if antes.get("usada_mib") is not None
            else None
        ),
        "carga_s": carga_s,
    }


def correr(
    modelos: list[str],
    versiones: list[str],
    contenedor: str,
    previos: dict[str, Any] | None,
    incluir_ejemplo: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    fixtures = cargar_fixtures(incluir_ejemplo)
    metodos_nuevos = {f"{m} · {NOMBRES[v]}" for m in modelos for v in versiones}
    corridas = [
        c
        for c in (previos or {}).get("corridas", [])
        if c["metodo"] != "heuristica" and c["metodo"] not in metodos_nuevos
    ]
    hardware = (previos or {}).get("hardware", {})

    for nombre, fx in fixtures.items():
        pasos = segmentar_heuristica(fx["analisis"])
        ids = segmentos_de_inicio(pasos, fx["analisis"])
        corridas.append(
            {
                "metodo": "heuristica",
                "fixture": nombre,
                "repeticion": 1,
                "camino": "heuristica",
                "ids": ids,
                "titulos": [p.nombre for p in pasos],
                "confianzas": [p.confianza for p in pasos],
                **evaluar(ids, fx),
            }
        )

    for modelo in modelos:
        hardware[modelo] = medir_carga(modelo, contenedor)
        print(f"{modelo}: {hardware[modelo]}", flush=True)
        cliente = ClienteLLM(
            settings.llm_base_url,
            modelo,
            timeout_s=settings.llm_timeout_s,
            num_ctx=settings.llm_num_ctx,
        )
        for version in versiones:
            for nombre, fx in fixtures.items():
                for rep in range(1, REPETICIONES + 1):
                    inicio = time.perf_counter()
                    r = segmentar(
                        fx["analisis"],
                        cliente,
                        fx["etiquetas"],
                        regla_aclaraciones=version == "v2",
                        dos_llamadas=version == "a",
                    )
                    ids = segmentos_de_inicio(r.pasos, fx["analisis"])
                    corridas.append(
                        {
                            "metodo": f"{modelo} · {NOMBRES[version]}",
                            "fixture": nombre,
                            "repeticion": rep,
                            "camino": r.metodo,
                            "motivo_respaldo": r.motivo_respaldo,
                            "intentos": r.intentos,
                            "intentos_redaccion": r.intentos_redaccion,
                            "motivo_sin_redaccion": r.motivo_sin_redaccion,
                            "pasos_sin_redactar": r.pasos_sin_redactar,
                            "segundos": round(time.perf_counter() - inicio, 2),
                            "ids": ids,
                            "titulos": [p.nombre for p in r.pasos],
                            "confianzas": [p.confianza for p in r.pasos],
                            **evaluar(ids, fx),
                        }
                    )
                    c = corridas[-1]
                    print(
                        f"{c['metodo']:42} {nombre:26} rep {rep}: F1 {c['f1']:.3f} "
                        f"FP {len(c['falsos_positivos'])} ND {len(c['no_detectados'])} "
                        f"({c['camino']}, {c['segundos']} s)",
                        flush=True,
                    )
        cliente.close()

    return {
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "nota": "Resultado indicativo: 3 transcripciones inventadas, inicios marcados a mano.",
        "parametros": {
            "num_ctx": settings.llm_num_ctx,
            "temperature": 0,
            "seed": SEMILLA,
            "think": False,
            "repeticiones_llm": REPETICIONES,
            "tolerancia_segmentos": 1,
            "tolerancias_tiempo_s": list(fp.TOLERANCIAS),
        },
        "fixtures": {
            n: {"segmentos": len(fx["segmentos"]), "inicios_paso": fx["inicios_paso"]}
            for n, fx in fixtures.items()
        },
        "hardware": hardware,
        "corridas": sorted(corridas, key=lambda c: c["metodo"] != "heuristica"),
    }


# ── Tablas ──────────────────────────────────────────────────────────────────────────────────


def _mediana(xs: list[float]) -> float:
    return round(statistics.median(xs), 3)


def tablas(datos: dict[str, Any]) -> None:
    corridas = datos["corridas"]
    fixtures = list(datos["fixtures"])
    metodos = list(dict.fromkeys(c["metodo"] for c in corridas))

    def de(metodo: str, fixture: str | None = None) -> list[dict[str, Any]]:
        return [
            c
            for c in corridas
            if c["metodo"] == metodo and (fixture is None or c["fixture"] == fixture)
        ]

    def agregado(metodo: str, rep: int) -> dict[str, float]:
        cs = [c for c in de(metodo) if c["repeticion"] == rep]
        tp = sum(c["tp"] for c in cs)
        n_pred = sum(c["n_predichos"] for c in cs)
        n_real = sum(c["n_reales"] for c in cs)
        p, r = tp / n_pred if n_pred else 0.0, tp / n_real if n_real else 0.0
        return {
            "p": p,
            "r": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "fp": sum(len(c["falsos_positivos"]) for c in cs),
            "nd": sum(len(c["no_detectados"]) for c in cs),
        }

    print(
        "F1 de fronteras a ±1 segmento (mediana de 3 repeticiones en los LLM). INDICATIVO, n=3.\n"
    )
    print(
        "| Método | " + " | ".join(fixtures) + " | Agregado P | R | F1 | FP | ND | Respaldos "
        "| s por transcripción |"
    )
    print("|---|" + "---|" * (len(fixtures) + 7))
    for m in metodos:
        reps = sorted({c["repeticion"] for c in de(m)})
        aggs = [agregado(m, rep) for rep in reps]
        celdas = [_mediana([c["f1"] for c in de(m, f)]) for f in fixtures]
        respaldos = sum(c["camino"] != "llm" for c in de(m)) if m != "heuristica" else "—"
        med = {k: _mediana([a[k] for a in aggs]) for k in ("p", "r", "f1", "fp", "nd")}
        segundos = [c["segundos"] for c in de(m) if "segundos" in c]
        tiempo = f"{_mediana(segundos):.1f}" if segundos else "< 0.01"
        print(
            f"| {m} | "
            + " | ".join(f"{x:.3f}" for x in celdas)
            + f" | {med['p']:.3f} | {med['r']:.3f} | **{med['f1']:.3f}** "
            f"| {med['fp']:g} | {med['nd']:g} | {respaldos} | {tiempo} |"
        )

    print("\nF1 en tiempo (agregado, mediana): asignación de sopvid.features.pasos.label_phrases\n")
    print("| Método | " + " | ".join(f"±{t} s" for t in fp.TOLERANCIAS) + " |")
    print("|---|" + "---|" * len(fp.TOLERANCIAS))
    for m in metodos:
        fila = []
        for tol in fp.TOLERANCIAS:
            por_rep = []
            for rep in sorted({c["repeticion"] for c in de(m)}):
                cs = [c for c in de(m) if c["repeticion"] == rep]
                tp = sum(c[f"f1_tiempo_{tol}s"]["tp"] for c in cs)
                n_pred = sum(c["n_predichos"] for c in cs)
                n_real = sum(c["n_reales"] for c in cs)
                p, r = tp / n_pred if n_pred else 0.0, tp / n_real if n_real else 0.0
                por_rep.append(2 * p * r / (p + r) if p + r else 0.0)
            fila.append(f"{_mediana(por_rep):.3f}")
        print(f"| {m} | " + " | ".join(fila) + " |")

    print("\nCarga en GPU (FA según el compose; misma medición que ADR-006)\n")
    print("| Modelo | Capas en GPU | FA | MTP | VRAM real MiB | VRAM libre antes MiB | Carga s |")
    print("|---|---|---|---|---|---|---|")
    for modelo, h in datos.get("hardware", {}).items():
        print(
            f"| {modelo} | {h['capas_gpu']} | {h['flash_attn']} | {h['mtp']} "
            f"| {h['vram_real_mib']} | {h['vram_libre_antes_mib']} | {h['carga_s']} |"
        )

    print("\nAciertos y errores (repetición 1; 'estable' = mismos cortes en las 3 repeticiones)\n")
    print(
        "| Método | Transcripción | Reales | Predichos | Falsos positivos | No detectados "
        "| Estable |"
    )
    print("|---|---|---|---|---|---|---|")
    for m in metodos:
        for f in fixtures:
            cs = sorted(de(m, f), key=lambda c: c["repeticion"])
            c = cs[0]
            estable = len({tuple(x["ids"]) for x in cs}) == 1 if len(cs) > 1 else "—"
            print(
                f"| {m} | {f} | {c['n_reales']} | {c['n_predichos']} "
                f"| {c['falsos_positivos'] or '—'} | {c['no_detectados'] or '—'} | {estable} |"
            )

    if any("confianzas" in c for c in corridas):
        tabla_por_transcripcion(datos)


def tabla_por_transcripcion(datos: dict[str, Any]) -> None:
    """Métricas de la extracción por transcripción (corridas con nivel de confianza)."""
    print("\nPor transcripción (medianas de las repeticiones; intentos y confianza sobre todas)\n")
    print(
        "| Método | Transcripción | F1 ±1 seg | F1 ±2 s | FP | ND | Intentos prom. "
        "| % alta / media / baja | % sin redactar | Heurística | s por transcripción |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    corridas = [c for c in datos["corridas"] if "confianzas" in c]
    for m in dict.fromkeys(c["metodo"] for c in corridas):
        for f in datos["fixtures"]:
            cs = [c for c in corridas if c["metodo"] == m and c["fixture"] == f]
            if not cs:
                continue
            niveles = [n for c in cs for n in c["confianzas"]]
            pct = " / ".join(
                f"{100 * niveles.count(n) / len(niveles):.0f}" for n in ("alta", "media", "baja")
            )
            intentos = [c["intentos"] for c in cs if "intentos" in c]
            redaccion = [c["intentos_redaccion"] for c in cs if c.get("intentos_redaccion")]
            segundos = [c["segundos"] for c in cs if "segundos" in c]
            heuristica = sum(c["camino"] != "llm" for c in cs) if m != "heuristica" else "—"
            prom_intentos = f"{statistics.mean(intentos):.2f}" if intentos else "—"
            if redaccion:
                prom_intentos += f" + {statistics.mean(redaccion):.2f}"
            tiempo = f"{_mediana(segundos):.1f}" if segundos else "< 0.01"
            sin_redactar = _pct_sin_redactar(cs)
            print(
                f"| {m} | {f} | {_mediana([c['f1'] for c in cs]):.3f} "
                f"| {_mediana([c['f1_tiempo_2s']['f1'] for c in cs]):.3f} "
                f"| {_mediana([len(c['falsos_positivos']) for c in cs]):g} "
                f"| {_mediana([len(c['no_detectados']) for c in cs]):g} "
                f"| {prom_intentos} | {pct} | {sin_redactar} | {heuristica} | {tiempo} |"
            )


def _pct_sin_redactar(corridas: list[dict[str, Any]]) -> str:
    """% de pasos que quedaron sin redactar (solo opción A). Las corridas de la primera versión
    no guardaban el conteo: ahí la redacción era de todo o nada."""
    con_redaccion = [c for c in corridas if "intentos_redaccion" in c and c["intentos_redaccion"]]
    if not con_redaccion:
        return "—"
    total = sum(len(c["confianzas"]) for c in con_redaccion)
    sin = sum(
        c.get("pasos_sin_redactar", len(c["confianzas"]) if c.get("motivo_sin_redaccion") else 0)
        for c in con_redaccion
    )
    return f"{100 * sin / total:.0f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--tabla", action="store_true", help="solo imprime las tablas guardadas")
    ap.add_argument(
        "--recalcular",
        action="store_true",
        help="reevalúa los cortes guardados con la métrica actual (sin llamar al LLM)",
    )
    ap.add_argument("--modelos", nargs="+", default=list(MODELOS))
    ap.add_argument("--versiones", nargs="+", default=["v1", "v2"], choices=list(NOMBRES))
    ap.add_argument("--contenedor", default="sopvid-ollama-1", help="'' si Ollama es nativo")
    ap.add_argument(
        "--incluir-ejemplo",
        action="store_true",
        help="agrega tests/fixtures/analisis_ejemplo.json a las transcripciones",
    )
    ap.add_argument(
        "--salida", type=Path, default=SALIDA, help=f"JSON de resultados (por defecto {SALIDA})"
    )
    args = ap.parse_args()
    salida = args.salida if args.salida.is_absolute() else PROJECT_ROOT / args.salida
    if args.recalcular:
        datos = json.loads(salida.read_text(encoding="utf-8"))
        fixtures = cargar_fixtures(incluir_ejemplo=EJEMPLO.stem in datos["fixtures"])
        for c in datos["corridas"]:
            c.update(evaluar(c["ids"], fixtures[c["fixture"]]))
        datos["metricas_recalculadas"] = datetime.now(UTC).isoformat(timespec="seconds")
        salida.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    elif not args.tabla:
        previos = json.loads(salida.read_text(encoding="utf-8")) if salida.exists() else None
        datos = correr(args.modelos, args.versiones, args.contenedor, previos, args.incluir_ejemplo)
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nResultados en {salida}\n")
    tablas(json.loads(salida.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
