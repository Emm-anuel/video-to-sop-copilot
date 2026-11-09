r"""Diagnostica el juez de la zona gris (ADR-012) con un video real: ¿por qué un mismo par da
veredictos distintos entre corridas con temperatura 0 y semilla fija?

Corre la validación de producción (`validar`) `--repeticiones` veces sobre el mismo `Analisis`
(Whisper una vez), descargando Gemma antes de cada una, como la API, y graba:

- cada llamada al juez: el par (paso del SOP y del video), el coseno, los mensajes exactos que van
  a Gemma y el texto crudo que responde, con el veredicto;
- los pasos del video de cada corrida (antes y después de fusionar) y el resultado de cada paso
  del SOP (estado, paso del video, coseno, juicio).

Luego agrupa las llamadas por par y dice, para cada par juzgado en más de una corrida, si la
entrada al juez fue idéntica y si la salida también. Con `--par N` el informe se centra en el
paso N del SOP (en qué corridas llegó al juez, con qué paso del video y con qué coseno).

Uso, desde la raíz del repo, con el entorno activado y Ollama arriba:

    python scripts/diagnosticar_juez.py --sop tests/fixtures/sop_filtro_agua.md \
        --repeticiones 6 --par 6 video_a=media/videos/VIDEO-A.mp4

Salida en `data/interim/juez/` (ignorada por git): `juez-<fecha>.json` (con el texto de la
transcripción: los videos son del equipo, no del cliente) y `juez-<fecha>.md`. No modifica código,
datos de entrada ni la base.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from medir_mvp import estado_git, preparar

from sopvid.contrato import SOP, PasoSOP, PasoVideo
from sopvid.lenguaje.emparejamiento import get_embedder
from sopvid.lenguaje.juez import ESQUEMA_JUEZ, Juez, construir_mensajes
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.lenguaje.validacion import DependenciasValidacion, Detenida, validar
from sopvid.plataforma.config import PROJECT_ROOT, get_settings

logger = logging.getLogger("diagnosticar_juez")
SALIDA = PROJECT_ROOT / "data" / "interim" / "juez"


def huella(objeto: Any) -> str:
    """Huella corta de un objeto JSON, para comparar entradas y salidas entre corridas."""
    texto = json.dumps(objeto, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(texto.encode()).hexdigest()[:12]


class JuezGrabado:
    """Envuelve al juez de producción y graba cada llamada con su entrada y su juicio."""

    def __init__(self, juez: Juez, prompt: Any, crudas: list[str]) -> None:
        self._juez = juez
        self._prompt = prompt
        self._crudas = crudas
        self.llamadas: list[dict[str, Any]] = []

    def juzgar(
        self, paso_sop: PasoSOP, paso_video: PasoVideo, similitud: float, narracion: str
    ) -> Any:
        antes = len(self._crudas)
        juicio = self._juez.juzgar(paso_sop, paso_video, similitud, narracion)
        mensajes = construir_mensajes(self._prompt, paso_sop, paso_video, narracion)
        self.llamadas.append(
            {
                "paso_sop": paso_sop.numero,
                "paso_video": paso_video.model_dump(mode="json"),
                "similitud": round(similitud, 4),
                "mensajes": mensajes,
                "entrada": huella(mensajes),
                "respuestas_crudas": self._crudas[antes:],
                "salida": huella(self._crudas[antes:]),
                "juicio": juicio.model_dump(mode="json"),
            }
        )
        return juicio


def grabar_chat(llm: Any, crudas: list[str]) -> None:
    """Graba el texto crudo de cada respuesta del juez (las llamadas con su esquema)."""
    original = llm.chat

    def chat(mensajes: Any, *args: Any, **kwargs: Any) -> Any:
        respuesta = original(mensajes, *args, **kwargs)
        if kwargs.get("esquema") is ESQUEMA_JUEZ:
            crudas.append(respuesta.texto)
        return respuesta

    llm.chat = chat


def corrida(v: Any, sop: SOP, llamadas: list[dict[str, Any]], repeticion: int) -> dict[str, Any]:
    g = v.resultado
    res = g.resultado
    pasos_sop = []
    for paso in res.clasificacion.pasos:
        if paso.indice_sop is None:
            continue
        pasos_sop.append(
            {
                "paso_sop": sop.pasos[paso.indice_sop].numero,
                "estado": paso.estado,
                "paso_video": None if paso.indice_video is None else paso.indice_video + 1,
                "similitud": paso.similitud,
                "juicio": None if paso.juicio is None else paso.juicio.model_dump(mode="json"),
            }
        )
    return {
        "repeticion": repeticion,
        "cumplimiento": round(g.cumplimiento, 2),
        "semaforo": g.semaforo,
        "conteo": dict(res.clasificacion.resumen.conteo),
        "pasos_video_originales": [p.model_dump(mode="json") for p in v.pasos_video],
        "pasos_video": [p.model_dump(mode="json") for p in res.pasos_video],
        "fusiones": [f.model_dump(mode="json") for f in res.fusiones],
        "pasos_sop": pasos_sop,
        "llamadas_juez": llamadas,
        "huella_pasos_video": huella([p.model_dump(mode="json") for p in v.pasos_video]),
    }


def comparar(corridas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Por cada paso del SOP juzgado en más de una corrida: entradas y salidas distintas."""
    por_par: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for c in corridas:
        for llamada in c["llamadas_juez"]:
            por_par[llamada["paso_sop"]].append((c["repeticion"], llamada))
    filas = []
    for paso, llamadas in sorted(por_par.items()):
        por_entrada: dict[str, set[str]] = defaultdict(set)
        for _, llamada in llamadas:
            por_entrada[llamada["entrada"]].add(llamada["salida"])
        filas.append(
            {
                "paso_sop": paso,
                "corridas": [r for r, _ in llamadas],
                "veredictos": [
                    (r, ll["juicio"]["veredicto"] or ll["juicio"]["motivo"]) for r, ll in llamadas
                ],
                "entradas_distintas": len(por_entrada),
                "misma_entrada_salidas_distintas": any(len(s) > 1 for s in por_entrada.values()),
            }
        )
    return filas


def informe(datos: dict[str, Any], par: int | None) -> str:
    lineas = [
        f"# Diagnóstico del juez ({datos['fecha']})",
        "",
        f"Commit `{datos['git'].get('commit')}`. Video `{datos['video']}`. Modelo "
        f"`{datos['modelo']}`. Umbrales bajo {datos['umbrales']['bajo']}, alto "
        f"{datos['umbrales']['alto']}.",
        "",
        "| Corrida | Cumpl. | Semáforo | Pasos del video (huella) | Llamadas al juez |",
        "|---|---|---|---|---|",
    ]
    for c in datos["corridas"]:
        juzgados = ", ".join(
            f"SOP {ll['paso_sop']}↔v{ll['paso_video']['numero']} ({ll['similitud']:.3f}): "
            f"{ll['juicio']['veredicto'] or ll['juicio']['motivo']}"
            for ll in c["llamadas_juez"]
        )
        lineas.append(
            f"| {c['repeticion']} | {c['cumplimiento']} | {c['semaforo']} "
            f"| {c['huella_pasos_video']} | {juzgados or '—'} |"
        )
    lineas += ["", "## Por par juzgado", ""]
    lineas += [
        "| Paso SOP | Corridas | Veredictos | Entradas distintas | Misma entrada, salida distinta |"
    ]
    lineas += ["|---|---|---|---|---|"]
    for f in datos["comparacion"]:
        lineas.append(
            f"| {f['paso_sop']} | {f['corridas']} | {f['veredictos']} | {f['entradas_distintas']} "
            f"| {'sí' if f['misma_entrada_salidas_distintas'] else 'no'} |"
        )
    if par is not None:
        lineas += ["", f"## Paso {par} del SOP en cada corrida", ""]
        for c in datos["corridas"]:
            fila = next(p for p in c["pasos_sop"] if p["paso_sop"] == par)
            lineas.append(
                f"- Corrida {c['repeticion']}: {fila['estado']}, paso del video "
                f"{fila['paso_video']}, coseno {fila['similitud']}, juicio "
                f"{fila['juicio'] and (fila['juicio']['veredicto'] or fila['juicio']['motivo'])}"
            )
    return "\n".join(lineas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video", help="clave=ruta del video o de su analisis.json")
    parser.add_argument("--sop", type=Path, required=True, help="SOP en Markdown (ADR-015)")
    parser.add_argument("--repeticiones", type=int, default=6)
    parser.add_argument("--par", type=int, help="paso del SOP en el que centrar el informe")
    parser.add_argument("--idioma", help="ISO 639-1 para Whisper; sin él, lo detecta")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = get_settings()
    sop = convertir_sop(args.sop.read_text(encoding="utf-8")).sop
    clave, _, ruta = args.video.partition("=")
    analisis, segundos, dispositivos = preparar(clave, Path(ruta), settings, SALIDA, args.idioma)
    (SALIDA / clave).mkdir(parents=True, exist_ok=True)
    (SALIDA / clave / "analisis.json").write_text(analisis.model_dump_json(), encoding="utf-8")
    embedder = get_embedder()
    corridas = []
    for repeticion in range(1, args.repeticiones + 1):
        deps = DependenciasValidacion.desde_settings(settings)
        deps.embedder = embedder
        crudas: list[str] = []
        grabar_chat(deps.llm, crudas)
        grabado = JuezGrabado(deps.juez, deps.juez.prompt, crudas)
        deps.juez = grabado
        try:
            deps.llm.descargar()
            v = validar(analisis, sop, deps, segundos_analisis=segundos, dispositivos=dispositivos)
            if isinstance(v, Detenida):
                v = validar(analisis, sop, deps, contexto=v.contexto, continuar=True)
        finally:
            deps.cerrar()
        corridas.append(corrida(v, sop, grabado.llamadas, repeticion))
        logger.info("Corrida %d: %.2f %%", repeticion, v.resultado.cumplimiento)
    datos = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "git": estado_git(),
        "video": clave,
        "modelo": settings.llm_model,
        "umbrales": {"bajo": settings.umbral_bajo, "alto": settings.umbral_alto},
        "corridas": corridas,
        "comparacion": comparar(corridas),
    }
    sello = datetime.now().strftime("%Y%m%d-%H%M")
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / f"juez-{sello}.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (SALIDA / f"juez-{sello}.md").write_text(informe(datos, args.par), encoding="utf-8")
    print(f"escrito: {SALIDA / f'juez-{sello}.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
