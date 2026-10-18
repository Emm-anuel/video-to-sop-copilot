"""Evalúa la segmentación en pasos (Fase 4, ADR-010): heurística vs. LLM. Resultado INDICATIVO.

Transcripciones inventadas de tests/fixtures/transcripciones/ con inicios de paso marcados a
mano. Para cada método mide F1 de fronteras a ±1 segmento (`segmentacion.f1_fronteras`) y, como
segunda vista, F1 en tiempo a ±2/4/6 s reutilizando `sopvid.features.pasos.label_phrases`.

Métodos:
  heuristica                  marcadores de transición + pausas (determinista, 1 corrida)
  <modelo> · prompt v1        prompt del benchmark de ADR-006
  <modelo> · prompt v2        v1 + regla explícita: aclaraciones, advertencias y comentarios
                              dentro de un paso no inician un paso nuevo

Cada combinación LLM corre 3 veces; se reporta la mediana y si los cortes fueron estables. Se
usa `segmentar()`, así que si el LLM falla o su propuesta es inválida se registra el respaldo.

Uso (con el profile "llm" arriba y los modelos descargados):
    python scripts/evaluar_segmentacion.py
    python scripts/evaluar_segmentacion.py --modelos gemma4:12b-it-qat --versiones v1
    python scripts/evaluar_segmentacion.py --tabla

Volver a correr un método reemplaza solo sus corridas; las demás se conservan.
"""

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from typing import Any

import benchmark_llm as bench  # mismo directorio: nvidia-smi y logs de Ollama
import httpx
import numpy as np
import pandas as pd

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
MODELOS = ("gemma4:e4b-it-q4_K_M", "qwen3.5:9b-q4_K_M")
REPETICIONES = 3


def cargar_fixtures() -> dict[str, dict[str, Any]]:
    """JSON de cada transcripción (etiquetas, inicios_paso…) más su `Analisis` en "analisis"."""
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        | {"analisis": cargar_transcripcion_prueba(p)}
        for p in sorted(FIXTURES.glob("*.json"))
    }


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
    modelos: list[str], versiones: list[str], contenedor: str, previos: dict[str, Any] | None
) -> dict[str, Any]:
    settings = get_settings()
    fixtures = cargar_fixtures()
    metodos_nuevos = {f"{m} · prompt {v}" for m in modelos for v in versiones}
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
        for version, regla in ((v, v == "v2") for v in versiones):
            for nombre, fx in fixtures.items():
                for rep in range(1, REPETICIONES + 1):
                    inicio = time.perf_counter()
                    r = segmentar(
                        fx["analisis"], cliente, fx["etiquetas"], regla_aclaraciones=regla
                    )
                    ids = segmentos_de_inicio(r.pasos, fx["analisis"])
                    corridas.append(
                        {
                            "metodo": f"{modelo} · prompt {version}",
                            "fixture": nombre,
                            "repeticion": rep,
                            "camino": r.metodo,
                            "motivo_respaldo": r.motivo_respaldo,
                            "intentos": r.intentos,
                            "segundos": round(time.perf_counter() - inicio, 2),
                            "ids": ids,
                            "titulos": [p.nombre for p in r.pasos],
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--tabla", action="store_true", help="solo imprime las tablas guardadas")
    ap.add_argument(
        "--recalcular",
        action="store_true",
        help="reevalúa los cortes guardados con la métrica actual (sin llamar al LLM)",
    )
    ap.add_argument("--modelos", nargs="+", default=list(MODELOS))
    ap.add_argument("--versiones", nargs="+", default=["v1", "v2"], choices=["v1", "v2"])
    ap.add_argument("--contenedor", default="sopvid-ollama-1", help="'' si Ollama es nativo")
    args = ap.parse_args()
    if args.recalcular:
        datos = json.loads(SALIDA.read_text(encoding="utf-8"))
        fixtures = cargar_fixtures()
        for c in datos["corridas"]:
            c.update(evaluar(c["ids"], fixtures[c["fixture"]]))
        datos["metricas_recalculadas"] = datetime.now(UTC).isoformat(timespec="seconds")
        SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    elif not args.tabla:
        previos = json.loads(SALIDA.read_text(encoding="utf-8")) if SALIDA.exists() else None
        datos = correr(args.modelos, args.versiones, args.contenedor, previos)
        SALIDA.parent.mkdir(parents=True, exist_ok=True)
        SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nResultados en {SALIDA}\n")
    tablas(json.loads(SALIDA.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
