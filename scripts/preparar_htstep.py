"""Prepara los datos del clasificador de inicio de paso (avances 2-5).

Fuentes públicas:
  - HT-Step (pasos con inicio/fin en segundos), CC-BY-NC 4.0:
    https://github.com/facebookresearch/htstep
  - Transcripciones ASR de HowTo100M (frases con segundo de inicio), Apache-2.0:
    https://huggingface.co/datasets/Jazzcharles/HowTo100M_llama3_refined_caption

Paso previo (descarga reanudable, ~9 GB; si se corta, vuelve a correr el mismo comando):
    curl.exe -L -C - -o data/raw/htstep/htm_llama3_refined.json ^
      https://huggingface.co/datasets/Jazzcharles/HowTo100M_llama3_refined_caption/resolve/main/htm_llama3_refined.json

Uso:
    python scripts/preparar_htstep.py

Salida (data/interim/htstep/, ignorado por git):
    asr_htstep.parquet    una fila por frase: vid, start_second, text
    pasos_htstep.parquet  una fila por paso anotado: vid, activity, subset, duration, step_id,
                          start, end, partial
Después de correrlo, el archivo de 9 GB se puede borrar.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data" / "raw" / "htstep"
OUT = RAIZ / "data" / "interim" / "htstep"
HTSTEP_URL = "https://raw.githubusercontent.com/facebookresearch/htstep/main/data/annotations.json"
ASR_PATH = RAW / "htm_llama3_refined.json"
CHUNK = 64 * 1024 * 1024

# Cada registro es plano: "N": {"vid": "...", "start_second": ..., "text": "...", ...}
REGISTRO = re.compile(rb'"\d+": (\{"vid": "([^"]+)"[^{}]*\})')


def cargar_pasos() -> dict:
    RAW.mkdir(parents=True, exist_ok=True)
    destino = RAW / "htstep_annotations.json"
    if not destino.exists():
        urllib.request.urlretrieve(HTSTEP_URL, destino)
    return json.loads(destino.read_text(encoding="utf-8"))


def tabla_pasos(ann: dict) -> pd.DataFrame:
    filas = [
        {
            "vid": vid,
            "activity": v["activity"],
            "subset": v["subset"],
            "duration": v["duration"],
            "step_id": a["id"],
            "start": a["segment"][0],
            "end": a["segment"][1],
            "partial": a["partial"],
        }
        for vid, v in ann.items()
        for a in v["annotations"]
    ]
    return pd.DataFrame(filas).sort_values(["vid", "start"]).reset_index(drop=True)


def filtrar_asr(ids: set[str]) -> pd.DataFrame:
    if not ASR_PATH.exists():
        raise SystemExit(f"No encuentro {ASR_PATH}. Descárgalo primero (ver docstring).")
    total = ASR_PATH.stat().st_size
    ids_b = {i.encode() for i in ids}
    filas, cola, leidos, vistos, t0 = [], b"", 0, 0, time.time()
    with ASR_PATH.open("rb") as f:
        while bloque := f.read(CHUNK):
            leidos += len(bloque)
            buf = cola + bloque
            fin = 0
            for m in REGISTRO.finditer(buf):
                vistos += 1
                fin = m.end()
                if m.group(2) in ids_b:
                    r = json.loads(m.group(1))
                    filas.append(
                        {"vid": r["vid"], "start_second": r["start_second"], "text": r["text"]}
                    )
            cola = buf[fin:]
            print(
                f"\r  {leidos / 1e9:5.2f}/{total / 1e9:.2f} GB | registros {vistos:,} | "
                f"conservados {len(filas):,} | {leidos / 1e6 / (time.time() - t0):.0f} MB/s",
                end="",
                flush=True,
            )
    print()
    df = pd.DataFrame(filas).drop_duplicates()
    return df.sort_values(["vid", "start_second"], kind="stable").reset_index(drop=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("1) HT-Step")
    ann = cargar_pasos()
    pasos = tabla_pasos(ann)
    print(f"  {pasos.vid.nunique():,} videos, {len(pasos):,} pasos")

    print("2) Filtrando transcripciones (solo videos de HT-Step)")
    asr = filtrar_asr(set(ann))
    con_asr = set(asr.vid)
    pasos = pasos[pasos.vid.isin(con_asr)].reset_index(drop=True)

    asr.to_parquet(OUT / "asr_htstep.parquet", index=False)
    pasos.to_parquet(OUT / "pasos_htstep.parquet", index=False)

    por_video = asr.groupby("vid").size()
    print("3) Resumen")
    print(f"  videos con pasos y transcripción: {len(con_asr):,} de {len(ann):,}")
    print(f"  frases: {len(asr):,} | mediana por video: {por_video.median():.0f}")
    print(f"  pasos en esos videos: {len(pasos):,}")
    print(f"  subsets: {pasos.drop_duplicates('vid').subset.value_counts().to_dict()}")
    print(f"  guardado en {OUT}")


if __name__ == "__main__":
    main()
