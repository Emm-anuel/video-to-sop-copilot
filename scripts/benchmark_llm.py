"""Benchmark del LLM local para ADR-006. Corre desde el host contra LLM_BASE_URL.

Para cada modelo (ya descargado en Ollama) mide tres tareas en español sobre una transcripción
INVENTADA (tests/fixtures/transcripciones/cambio_cuchilla.json):

  (a) resumen     resumir ~1,500 palabras (texto libre)
  (b) segmentar   elegir segmentos donde empieza cada paso -> [{"segmento_id", "nombre", ...}]
  (c) rag         responder solo con fragmentos dados y citar sus ids -> JSON

Metodología: descarga de la GPU todos los modelos, registra la VRAM libre, hace una corrida de
calentamiento (descartada; mide la carga) y luego 3 repeticiones por tarea, en streaming para
medir el tiempo a primer token. Las métricas de tiempo y tokens salen de los campos de Ollama.
Cada repetición antepone "[corrida N]" al mensaje de sistema para que llama-server no reutilice
el prefijo en caché y la evaluación del prompt se mida completa.

La VRAM real sale de nvidia-smi (antes y después de cargar) y las capas en GPU de los logs del
contenedor ("offloaded N/M layers"). La cifra de /api/ps se guarda, pero en Ollama 0.40.2 con el
runner llamacpp no es confiable.

Uso (con el profile "llm" arriba):
    python scripts/benchmark_llm.py --variante fa_on --modelos gemma4:e4b-it-q4_K_M qwen3:8b-q4_K_M
    python scripts/benchmark_llm.py --tabla        # tablas Markdown con todo lo guardado

Los resultados crudos van a docs/adr/datos/benchmark_llm/<variante>.json.
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from sopvid.lenguaje.llm import SEMILLA, ClienteLLM
from sopvid.percepcion.segmentacion import (
    ESQUEMA_PASOS,
    cargar_transcripcion_prueba,
    construir_mensajes,
    f1_fronteras,
)
from sopvid.plataforma.config import PROJECT_ROOT, get_settings

FIXTURE = PROJECT_ROOT / "tests/fixtures/transcripciones/cambio_cuchilla.json"
SALIDA = PROJECT_ROOT / "docs/adr/datos/benchmark_llm"
REPETICIONES = 3
# Tope de tokens generados solo para el benchmark: corta salidas desbocadas (done_reason=length
# cuenta como fallo). Alcanza incluso para marcar los 60 segmentos como pasos con JSON indentado.
NUM_PREDICT = 3000

SISTEMA = (
    "Eres un asistente técnico de una planta industrial. Respondes en español, con precisión y "
    "sin inventar datos."
)

# (a) Hechos clave que un buen resumen debería conservar (búsqueda sin acentos ni mayúsculas).
HECHOS_RESUMEN = {
    "bloqueo con candado": r"candado|bloque",
    "guantes anticorte": r"guante",
    "torque 12 N·m": r"\b(12|doce)\s*(n\s*[·.]?\s*m|newton)",
    "holgura 0.05 mm": r"0[.,]05|cinco centesimas",
    "sentido de giro": r"sentido|flecha",
    "rosca izquierda": r"izquierda",
    "prueba en vacio": r"vacio",
    "ancho 120 mm": r"\b(120|ciento veinte)\b",
    "desecho punzocortante": r"contenedor|punzocortante|desech",
    "bitacora": r"bitacora",
}

# (c) Fragmentos recuperados (ids del fixture), pregunta y fragmento que la responde.
FRAGMENTOS_RAG = [6, 8, 25, 38, 39, 42, 49, 58]
PREGUNTA_RAG = "¿A qué torque se aprieta la tuerca de la cuchilla nueva y con qué herramienta?"
CITA_CORRECTA_RAG = 38
ESQUEMA_RAG = {
    "type": "object",
    "properties": {
        "respuesta": {"type": "string"},
        "citas": {"type": "array", "items": {"type": "integer"}},
        "encontrado": {"type": "boolean"},
    },
    "required": ["respuesta", "citas", "encontrado"],
    "additionalProperties": False,
}


# ── Tareas ──────────────────────────────────────────────────────────────────────────────────


def cargar_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def tareas(fx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Mensajes, esquema y evaluador de cada tarea."""
    texto = " ".join(s["texto"] for s in fx["segmentos"])
    # (b) usa el prompt del benchmark original de ADR-006: sin la regla de aclaraciones.
    segmentar_msgs = construir_mensajes(
        cargar_transcripcion_prueba(FIXTURE), fx["etiquetas"], regla_aclaraciones=False
    )
    por_id = {s["id"]: s for s in fx["segmentos"]}
    fragmentos = "\n".join(f"[id {i}] {por_id[i]['texto']}" for i in FRAGMENTOS_RAG)

    return {
        "a_resumen": {
            "sistema": SISTEMA,
            "usuario": (
                "A continuación está la transcripción de un video de capacitación narrado por un "
                f"técnico.\n\nTranscripción:\n{texto}\n\n"
                "Escribe un resumen en español de máximo 200 palabras con el objetivo del "
                "procedimiento, los pasos principales en orden, las advertencias de seguridad y "
                "los valores numéricos importantes (torques, holguras, medidas)."
            ),
            "esquema": None,
            "evaluar": evaluar_resumen,
        },
        "b_segmentar": {
            "sistema": segmentar_msgs[0]["content"],
            "usuario": segmentar_msgs[1]["content"],
            "esquema": ESQUEMA_PASOS,
            "evaluar": lambda salida: evaluar_segmentacion(salida, fx),
        },
        "c_rag": {
            "sistema": (
                SISTEMA + " Responde solo con la información de los fragmentos. Si no contienen "
                'la respuesta, responde "no encontré", con encontrado=false y sin citas.'
            ),
            "usuario": (
                f"Fragmentos:\n{fragmentos}\n\nPregunta: {PREGUNTA_RAG}\n\n"
                "Responde en JSON con: respuesta (texto breve en español), citas (lista de ids de "
                "los fragmentos que la respaldan) y encontrado (true o false)."
            ),
            "esquema": ESQUEMA_RAG,
            "evaluar": evaluar_rag,
        },
    }


def _normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_acentos.lower()


def evaluar_resumen(salida: str) -> dict[str, Any]:
    norm = _normalizar(salida)
    presentes = [h for h, patron in HECHOS_RESUMEN.items() if re.search(patron, norm)]
    return {
        "valido": bool(salida.strip()),
        "palabras": len(salida.split()),
        "hechos_presentes": len(presentes),
        "hechos_total": len(HECHOS_RESUMEN),
        "hechos_faltantes": [h for h in HECHOS_RESUMEN if h not in presentes],
    }


def evaluar_segmentacion(salida: str, fx: dict[str, Any]) -> dict[str, Any]:
    try:
        datos = json.loads(salida)
    except json.JSONDecodeError:
        return {"valido": False, "json_valido": False}
    forma_ok = isinstance(datos, list) and all(
        isinstance(d, dict)
        and isinstance(d.get("segmento_id"), int)
        and isinstance(d.get("nombre"), str)
        for d in datos
    )
    if not forma_ok:
        return {"valido": False, "json_valido": True, "forma_valida": False}
    ids = [d["segmento_id"] for d in datos]
    existentes = {s["id"] for s in fx["segmentos"]}
    ids_existen = all(i in existentes for i in ids)
    creciente = all(a < b for a, b in zip(ids, ids[1:], strict=False))
    sin_duplicados = len(ids) == len(set(ids))
    return {
        "valido": ids_existen and creciente and sin_duplicados and bool(ids),
        "json_valido": True,
        "forma_valida": True,
        "ids_existen": ids_existen,
        "orden_creciente": creciente,
        "sin_duplicados": sin_duplicados,
        "n_pasos": len(ids),
        "n_pasos_reales": len(fx["inicios_paso"]),
        "ids": ids,
        **f1_fronteras(ids, fx["inicios_paso"]),
    }


def evaluar_rag(salida: str) -> dict[str, Any]:
    try:
        datos = json.loads(salida)
    except json.JSONDecodeError:
        return {"valido": False, "json_valido": False}
    citas = datos.get("citas") if isinstance(datos, dict) else None
    if not isinstance(citas, list) or not all(isinstance(c, int) for c in citas):
        return {"valido": False, "json_valido": True, "forma_valida": False}
    ids_existen = bool(citas) and all(c in FRAGMENTOS_RAG for c in citas)
    respuesta = _normalizar(str(datos.get("respuesta", "")))
    return {
        "valido": ids_existen,
        "json_valido": True,
        "forma_valida": True,
        "citas": citas,
        "ids_existen": ids_existen,
        "cita_correcta": CITA_CORRECTA_RAG in citas,
        "encontrado": datos.get("encontrado"),
        "menciona_12_y_torquimetro": bool(
            re.search(r"\b(12|doce)\b", respuesta) and "torquimetro" in respuesta
        ),
    }


# ── Medición ────────────────────────────────────────────────────────────────────────────────


def nvidia_smi() -> dict[str, Any]:
    """VRAM usada/libre/total en MiB según nvidia-smi (None si no hay nvidia-smi)."""
    try:
        salida = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.used,memory.free,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {"usada_mib": None, "libre_mib": None}
    nombre, driver, usada, libre, total = [x.strip() for x in salida.splitlines()[0].split(",")]
    return {
        "gpu": nombre,
        "driver": driver,
        "usada_mib": int(usada),
        "libre_mib": int(libre),
        "total_mib": int(total),
    }


def docker_logs(contenedor: str, desde: float) -> str:
    try:
        r = subprocess.run(
            ["docker", "logs", "--since", f"{desde:.0f}", contenedor],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout + r.stderr


def analizar_logs(logs: str) -> dict[str, Any]:
    """Datos de carga del último llama-server que arrancó (modelo principal y cabeza MTP)."""
    inicio = logs.rfind("starting llama-server")
    if inicio == -1:
        inicio = logs.rfind("starting runner")
    tramo = logs[inicio:] if inicio != -1 else logs
    cmd = re.search(r'cmd="([^"]+)"', tramo)
    cmd = cmd.group(1) if cmd else ""
    capas = re.findall(r"offloaded (\d+)/(\d+) layers to GPU", tramo)
    buffers_cuda = re.findall(r"CUDA0 model buffer size =\s*([\d.]+) MiB", tramo)
    buffers_cpu = re.findall(
        r"(?:CPU|CPU_Mapped|CUDA_Host) model buffer size =\s*([\d.]+) MiB", tramo
    )
    kv = re.findall(r"CUDA0 KV buffer size =\s*([\d.]+) MiB", tramo)
    computo = re.search(r"CUDA0 compute buffer size =\s*([\d.]+) MiB", tramo)
    mmproj = re.search(r"worst-case memory usage of mmproj is ([\d.]+) MiB", tramo)
    flash = re.search(r"--flash-attn (\w+)", cmd)
    cache_k = re.search(r"--cache-type-k (\w+)", cmd)
    principal = capas[0] if capas else None
    return {
        "runner": "llama-server" if "llama-server" in cmd else ("ollama" if cmd else None),
        "capas_gpu": f"{principal[0]}/{principal[1]}" if principal else None,
        "todas_las_capas_en_gpu": bool(principal) and principal[0] == principal[1],
        "mtp": "--spec-type draft-mtp" in cmd,
        "capas_gpu_mtp": f"{capas[1][0]}/{capas[1][1]}" if len(capas) > 1 else None,
        "flash_attn": flash.group(1) if flash else None,
        "cache_type_k": cache_k.group(1) if cache_k else None,
        "proyector_vision": "--mmproj" in cmd,
        "buffer_modelo_gpu_mib": float(buffers_cuda[0]) if buffers_cuda else None,
        "buffer_modelo_cpu_mib": float(buffers_cpu[0]) if buffers_cpu else None,
        "kv_gpu_mib": round(sum(float(x) for x in kv[:2]), 2) if kv else None,
        "computo_gpu_mib": float(computo.group(1)) if computo else None,
        "mmproj_peor_caso_mib": float(mmproj.group(1)) if mmproj else None,
        "num_ctx": int(m.group(1)) if (m := re.search(r" -c (\d+)", cmd)) else None,
    }


def descargar_todo(http: httpx.Client) -> None:
    """Saca de la GPU los modelos cargados y espera a que /api/ps quede vacío."""
    for m in http.get("/api/ps").json().get("models", []):
        http.post("/api/generate", json={"model": m["name"], "keep_alive": 0})
    for _ in range(60):
        if not http.get("/api/ps").json().get("models"):
            break
        time.sleep(1)
    time.sleep(3)  # margen para que el driver libere la memoria


def llamar(http: httpx.Client, cuerpo: dict[str, Any]) -> dict[str, Any]:
    """Una llamada en streaming: tiempo a primer token (cliente) y métricas de Ollama."""
    inicio = time.perf_counter()
    ttft = None
    partes, pensamiento, final = [], 0, {}
    with http.stream("POST", "/api/chat", json=cuerpo) as r:
        r.raise_for_status()
        for linea in r.iter_lines():
            if not linea:
                continue
            evento = json.loads(linea)
            if "error" in evento:
                raise RuntimeError(evento["error"])
            mensaje = evento.get("message", {})
            pensamiento += len(mensaje.get("thinking", "") or "")
            contenido = mensaje.get("content", "")
            if contenido:
                if ttft is None:
                    ttft = time.perf_counter() - inicio
                partes.append(contenido)
            if evento.get("done"):
                final = evento
    total = time.perf_counter() - inicio
    s = lambda campo: final.get(campo, 0) / 1e9  # noqa: E731
    return {
        "salida": "".join(partes),
        "caracteres_pensamiento": pensamiento,
        "ttft_s": round(ttft, 3) if ttft is not None else None,
        "total_s": round(total, 3),
        "carga_s": round(s("load_duration"), 3),
        "prompt_tokens": final.get("prompt_eval_count"),
        "prompt_s": round(s("prompt_eval_duration"), 3),
        "eval_tokens": final.get("eval_count"),
        "eval_s": round(s("eval_duration"), 3),
        "tok_s": round(final["eval_count"] / s("eval_duration"), 1)
        if final.get("eval_count") and final.get("eval_duration")
        else None,
        "prefill_tok_s": round(final["prompt_eval_count"] / s("prompt_eval_duration"), 1)
        if final.get("prompt_eval_count") and final.get("prompt_eval_duration")
        else None,
        "done_reason": final.get("done_reason"),
    }


def correr_tarea(
    http: httpx.Client, cliente: ClienteLLM, tarea: dict[str, Any], corrida: str
) -> dict[str, Any]:
    mensajes = [
        {"role": "system", "content": f"[corrida {corrida}] {tarea['sistema']}"},
        {"role": "user", "content": tarea["usuario"]},
    ]
    cuerpo = cliente.cuerpo(mensajes, esquema=tarea["esquema"], stream=True)
    cuerpo["options"]["num_predict"] = NUM_PREDICT
    try:
        r = llamar(http, cuerpo)
    except (httpx.HTTPError, RuntimeError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:300], "valido": False}
    r["evaluacion"] = tarea["evaluar"](r["salida"])
    if r["done_reason"] == "length":
        r["evaluacion"]["valido"] = False
    return r


def mediana(valores: list[float | None]) -> float | None:
    v = [x for x in valores if x is not None]
    return round(statistics.median(v), 3) if v else None


def correr_modelo(
    http: httpx.Client, modelo: str, contenedor: str, fx: dict[str, Any]
) -> dict[str, Any]:
    print(f"\n== {modelo}", flush=True)
    descargar_todo(http)
    vram_antes = nvidia_smi()
    print(f"   VRAM libre antes de cargar: {vram_antes['libre_mib']} MiB", flush=True)
    t_logs = time.time() - 2
    cliente = ClienteLLM(get_settings().llm_base_url, modelo, num_ctx=get_settings().llm_num_ctx)
    lista = tareas(fx)

    calentamiento = {}
    for nombre, tarea in lista.items():
        calentamiento[nombre] = correr_tarea(http, cliente, tarea, "calentamiento")
        r = calentamiento[nombre]
        print(f"   calentamiento {nombre}: {r.get('total_s')} s (carga {r.get('carga_s')} s)")

    vram_cargado = nvidia_smi()
    ps = next((m for m in http.get("/api/ps").json().get("models", []) if m["name"] == modelo), {})
    logs = analizar_logs(docker_logs(contenedor, t_logs)) if contenedor else {}
    disco = next(
        (m["size"] for m in http.get("/api/tags").json()["models"] if m["name"] == modelo), None
    )

    corridas = []
    for rep in range(1, REPETICIONES + 1):
        for nombre, tarea in lista.items():
            libre = nvidia_smi()["libre_mib"]
            r = correr_tarea(http, cliente, tarea, str(rep))
            r.update({"tarea": nombre, "repeticion": rep, "vram_libre_antes_mib": libre})
            corridas.append(r)
            print(
                f"   rep {rep} {nombre}: ttft {r.get('ttft_s')} s, {r.get('tok_s')} tok/s, "
                f"total {r.get('total_s')} s, válido={r.get('evaluacion', r).get('valido')}",
                flush=True,
            )
    cliente.close()

    resumen = {}
    for nombre in lista:
        rs = [c for c in corridas if c["tarea"] == nombre and "error" not in c]
        resumen[nombre] = {
            campo: mediana([c[campo] for c in rs])
            for campo in ("ttft_s", "total_s", "tok_s", "prefill_tok_s", "prompt_tokens")
        } | {
            "validas": sum(c["evaluacion"]["valido"] for c in rs),
            "repeticiones": REPETICIONES,
        }

    return {
        "modelo": modelo,
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "disco_bytes": disco,
        "carga_s": calentamiento["a_resumen"].get("carga_s"),
        "vram_antes": vram_antes,
        "vram_cargado": vram_cargado,
        "vram_delta_mib": (
            vram_cargado["usada_mib"] - vram_antes["usada_mib"]
            if vram_antes.get("usada_mib") is not None
            else None
        ),
        "api_ps": {
            "size": ps.get("size"),
            "size_vram": ps.get("size_vram"),
            "nota": "No confiable en Ollama 0.40.2 con el runner llamacpp; usar vram_delta_mib.",
        },
        "logs": logs,
        "calentamiento": calentamiento,
        "corridas": corridas,
        "mediana": resumen,
    }


# ── Tablas ──────────────────────────────────────────────────────────────────────────────────


def _fmt(x: Any, nd: int = 1) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def tabla(carpeta: Path) -> None:
    filas_r, filas_c = [], []
    for archivo in sorted(carpeta.glob("*.json")):
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        for m in datos["modelos"]:
            lg, md = m["logs"], m["mediana"]
            nombre = f"`{m['modelo']}`" + (" ᴹᵀᴾ" if lg.get("mtp") else "")
            filas_r.append(
                f"| {nombre} | {datos['variante']} | {_fmt(lg.get('flash_attn'))} "
                f"| {_fmt((m['disco_bytes'] or 0) / 1e9)} | {_fmt(lg.get('capas_gpu'))} "
                f"| {_fmt(m['vram_delta_mib'] / 1024 if m['vram_delta_mib'] else None, 2)} "
                f"| {_fmt((m['api_ps']['size_vram'] or 0) / 2**30, 2)} "
                f"| {_fmt(m['vram_antes']['libre_mib'])} | {_fmt(m['carga_s'])} "
                + " ".join(
                    f"| {_fmt(md[t]['ttft_s'], 2)} | {_fmt(md[t]['tok_s'])} "
                    f"| {_fmt(md[t]['total_s'])}"
                    for t in ("a_resumen", "b_segmentar", "c_rag")
                )
                + " |"
            )
            ev = {
                t: [
                    c["evaluacion"]
                    for c in m["corridas"]
                    if c.get("tarea") == t and "evaluacion" in c
                ]
                for t in ("a_resumen", "b_segmentar", "c_rag")
            }
            a, b, c = ev["a_resumen"], ev["b_segmentar"], ev["c_rag"]
            filas_c.append(
                f"| {nombre} | {datos['variante']} "
                f"| {mediana([e['hechos_presentes'] for e in a])}/{len(HECHOS_RESUMEN)} "
                f"| {mediana([e['palabras'] for e in a])} "
                f"| {sum(e.get('json_valido', False) for e in b)}/{len(b)} "
                f"| {sum(e['valido'] for e in b)}/{len(b)} "
                f"| {mediana([e.get('n_pasos') for e in b])} "
                f"| {mediana([e.get('f1') for e in b])} "
                f"| {sum(e.get('json_valido', False) for e in c)}/{len(c)} "
                f"| {sum(e.get('ids_existen', False) for e in c)}/{len(c)} "
                f"| {sum(e.get('cita_correcta', False) for e in c)}/{len(c)} "
                f"| {len({tuple(e.get('ids') or ()) for e in b}) == 1} |"
            )
    print(
        "| Modelo | Variante | FA | Disco GB | Capas GPU | VRAM real GiB | /api/ps GiB* "
        "| VRAM libre antes MiB | Carga s "
        "| (a) TTFT s | (a) tok/s | (a) total s | (b) TTFT s | (b) tok/s | (b) total s "
        "| (c) TTFT s | (c) tok/s | (c) total s |"
    )
    print("|" + "---|" * 18)
    print("\n".join(filas_r))
    print()
    print(
        "| Modelo | Variante | (a) hechos | (a) palabras | (b) JSON válido "
        "| (b) válido (ids, orden) "
        "| (b) pasos (12 reales) | (b) F1 ±1 | (c) JSON válido | (c) ids existen "
        "| (c) cita correcta | (b) mismos cortes en 3 reps |"
    )
    print("|" + "---|" * 12)
    print("\n".join(filas_c))


# ── Entrada ─────────────────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--modelos", nargs="+", help="etiquetas ya descargadas en Ollama")
    ap.add_argument("--variante", default="fa_off", help="nombre del archivo de resultados")
    ap.add_argument("--contenedor", default="sopvid-ollama-1", help="'' si Ollama es nativo")
    ap.add_argument("--tabla", action="store_true", help="imprime las tablas y termina")
    ap.add_argument("--salida", type=Path, default=SALIDA, help="carpeta de resultados")
    args = ap.parse_args()

    if args.tabla:
        tabla(args.salida)
        return
    if not args.modelos:
        ap.error("indica --modelos o --tabla")

    settings = get_settings()
    fx = cargar_fixture()
    args.salida.mkdir(parents=True, exist_ok=True)
    archivo = args.salida / f"{args.variante}.json"
    # Volver a correr un modelo reemplaza solo su entrada; los demás se conservan.
    previos = []
    if archivo.exists():
        previos = json.loads(archivo.read_text(encoding="utf-8"))["modelos"]
        previos = [m for m in previos if m["modelo"] not in args.modelos]
    with httpx.Client(base_url=settings.llm_base_url, timeout=settings.llm_timeout_s) as http:
        datos = {
            "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
            "variante": args.variante,
            "ollama": http.get("/api/version").json().get("version"),
            "host": nvidia_smi(),
            "parametros": {
                "num_ctx": settings.llm_num_ctx,
                "timeout_s": settings.llm_timeout_s,
                "temperature": 0,
                "seed": SEMILLA,
                "think": False,
                "num_predict": NUM_PREDICT,
                "repeticiones": REPETICIONES,
                "fixture": FIXTURE.relative_to(PROJECT_ROOT).as_posix(),
            },
            "modelos": previos,
        }
        for modelo in args.modelos:
            datos["modelos"].append(correr_modelo(http, modelo, args.contenedor, fx))
            archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        descargar_todo(http)
    print(f"\nResultados en {archivo}")


if __name__ == "__main__":
    sys.exit(main())
