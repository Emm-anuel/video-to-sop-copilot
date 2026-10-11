"""Prepara datos del clasificador de inicio de paso con transcripción COMPLETA (subtítulos .vtt).

Fuentes públicas:
  - HT-Step (pasos con inicio/fin en segundos), CC-BY-NC 4.0:
    https://github.com/facebookresearch/htstep
  - Subtítulos .vtt de YouTube (ASR completa, con tiempo por palabra) publicados en
    https://huggingface.co/datasets/TornadoLabs/howto100m (términos académicos de la fuente)
Solo ~130 videos están en ambas fuentes.

Uso:
    python scripts/preparar_htstep_vtt.py

Salida (data/interim/htstep_vtt/, ignorado por git):
    palabras.parquet  una fila por palabra: vid, idx_palabra, t (segundo de inicio), palabra
    pasos.parquet     una fila por paso HT-Step de esos videos: vid, activity, subset, duration,
                      step_id, start, end, partial
La segmentación de palabras en "segmentos de habla" se hace después, en sopvid.features.pasos.
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data" / "raw" / "htstep"
VTT_DIR = RAW / "vtt"
OUT = RAIZ / "data" / "interim" / "htstep_vtt"
HTSTEP_URL = "https://raw.githubusercontent.com/facebookresearch/htstep/main/data/annotations.json"
META_URL = "https://huggingface.co/datasets/TornadoLabs/howto100m/resolve/main/metadata.jsonl"

CUE = re.compile(r"(\d+):(\d\d):(\d\d\.\d+) --> (\d+):(\d\d):(\d\d\.\d+)")
TAG_T = re.compile(r"<(\d+):(\d\d):(\d\d\.\d+)>")
RUIDO = re.compile(r"\[[^\]]*\]")  # [Music], [Applause], ...


def _seg(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


def bajar(url: str, destino: Path) -> Path:
    if not destino.exists() or destino.stat().st_size == 0:
        destino.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, destino)
    return destino


def parsear_vtt(texto: str) -> list[tuple[float, str]]:
    """Devuelve [(t_inicio, palabra)] a partir de un .vtt de YouTube con subtítulos 'rodantes'.

    En cada cue, la última línea trae el texto nuevo. Si tiene etiquetas <hh:mm:ss.mmm>, cada
    palabra lleva su tiempo; la primera usa el inicio del cue. Los cues de ~10 ms solo repiten
    la línea anterior y se ignoran.
    """
    palabras: list[tuple[float, str]] = []
    bloques = texto.replace("\r\n", "\n").split("\n\n")
    ultima = ""
    for b in bloques:
        lineas = b.strip("\n").split("\n")
        m = next((CUE.search(linea) for linea in lineas if CUE.search(linea)), None)
        if not m:
            continue
        ini, fin = _seg(*m.groups()[:3]), _seg(*m.groups()[3:])
        cuerpo = [linea for linea in lineas if not CUE.search(linea)]
        if not cuerpo or fin - ini < 0.02:
            continue
        nueva = cuerpo[-1]
        if "<c>" in nueva:
            partes = TAG_T.split(nueva)
            # partes = [palabra0, h, m, s, palabra1, h, m, s, palabra2, ...]
            items = [(ini, partes[0])]
            for i in range(1, len(partes) - 3, 4):
                items.append((_seg(partes[i], partes[i + 1], partes[i + 2]), partes[i + 3]))
            for t, w in items:
                w = re.sub(r"</?c>", "", w)
                w = RUIDO.sub("", w).strip()
                if w:
                    palabras.extend((t, x) for x in w.split())
            ultima = re.sub(r"<[^>]+>", "", nueva).strip()
        else:
            limpio = RUIDO.sub("", nueva).strip()
            if limpio and limpio != ultima and limpio != RUIDO.sub("", ultima).strip():
                palabras.extend((ini, x) for x in limpio.split())
                ultima = nueva.strip()
    return palabras


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ann = json.loads(bajar(HTSTEP_URL, RAW / "htstep_annotations.json").read_text(encoding="utf-8"))
    meta_path = bajar(META_URL, RAW / "tornado_metadata.jsonl")
    meta = [
        json.loads(linea)
        for linea in meta_path.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]
    comunes = [m for m in meta if m.get("subtitle_url") and m["video_id"] in ann]
    print(f"videos en ambas fuentes: {len(comunes)}")

    filas, fallas = [], []
    for i, m in enumerate(comunes, 1):
        vid = m["video_id"]
        try:
            vtt = bajar(m["subtitle_url"], VTT_DIR / f"{vid}.vtt").read_text(
                encoding="utf-8", errors="ignore"
            )
            pal = parsear_vtt(vtt)
            filas += [
                {"vid": vid, "idx_palabra": j, "t": t, "palabra": w} for j, (t, w) in enumerate(pal)
            ]
            if not pal:
                fallas.append((vid, "sin palabras"))
        except Exception as e:  # noqa: BLE001
            fallas.append((vid, type(e).__name__))
        print(f"\r  {i}/{len(comunes)} subtítulos", end="", flush=True)
    print()

    palabras = pd.DataFrame(filas)
    vids = set(palabras.vid) if len(palabras) else set()
    pasos = (
        pd.DataFrame(
            [
                {
                    "vid": v,
                    "activity": ann[v]["activity"],
                    "subset": ann[v]["subset"],
                    "duration": ann[v]["duration"],
                    "step_id": a["id"],
                    "start": a["segment"][0],
                    "end": a["segment"][1],
                    "partial": a["partial"],
                }
                for v in sorted(vids)
                for a in ann[v]["annotations"]
            ]
        )
        .sort_values(["vid", "start"])
        .reset_index(drop=True)
    )

    palabras.to_parquet(OUT / "palabras.parquet", index=False)
    pasos.to_parquet(OUT / "pasos.parquet", index=False)

    dur = pasos.drop_duplicates("vid").set_index("vid").duration
    wpm = palabras.groupby("vid").size() / (dur / 60)
    print("Resumen")
    print(
        f"  videos con palabras: {len(vids)} | palabras: {len(palabras):,} | pasos: {len(pasos):,}"
    )
    print(f"  palabras por minuto (mediana): {wpm.median():.0f}  (habla normal: 120-160)")
    print(f"  subsets: {pasos.drop_duplicates('vid').subset.value_counts().to_dict()}")
    if fallas:
        print(f"  fallas ({len(fallas)}): {fallas[:10]}")
    ej = palabras[palabras.vid == palabras.vid.iloc[0]].head(25)
    print("  ejemplo:", " ".join(f"{w}@{t:.1f}" for t, w in zip(ej.t, ej.palabra, strict=False)))
    print(f"  guardado en {OUT}")


if __name__ == "__main__":
    main()
