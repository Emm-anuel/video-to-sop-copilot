r"""Graba las fixtures de regresión del rescate de un Falta (ADR-022): `rescate.json`.

Casos (videos del equipo, no del cliente):

- `a_<n>`: segmentaciones reales de Gemma del video A que dieron amarillo (el paso 6 en Falta)
  antes del rescate; salen de un JSON de `scripts/diagnosticar_juez.py` (`--juez`, `--corridas`).
- `b_adversario`: la segmentación real de B (que omite los pasos 2 y 6) con tres fragmentos de A
  insertados después del paso 5 ("purgo el aire", "ya sale solo agua", "suelto el botón"), con su
  transcripción: se parecen al paso 6 sin abrir la llave ni revisar fugas. El paso 6 debe seguir
  en Falta.

Para que la prueba corra sin LLM ni MiniLM, se graba lo que pidió `emparejar` con los modelos
reales: el vector MiniLM de cada texto (float16, por huella del texto) y el juicio de Gemma por
entrada exacta del juez (paso del SOP, nombre y descripción del paso del video, narración). Si
el código cambia y pide otro texto u otra entrada, la prueba falla y pide volver a grabar.

Uso, desde la raíz, con Ollama arriba:

    python scripts/grabar_rescate.py --sop tests/fixtures/sop_filtro_agua.md \
        --juez data/interim/juez/juez-20261109-0011.json --corridas 2 3 9 10 \
        --analisis-a data/interim/juez/video_a/analisis.json \
        --analisis-b data/interim/juez/video_b/analisis.json
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from sopvid.contrato import Analisis, Juicio, PasoSOP, PasoVideo, Segmento
from sopvid.lenguaje import emparejamiento as emp
from sopvid.lenguaje.juez import JuezGemma
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.percepcion.segmentacion import segmentar
from sopvid.plataforma.config import PROJECT_ROOT, get_settings

SALIDA = PROJECT_ROOT / "tests" / "fixtures" / "rescate.json"
# Fragmentos de A (números de los pasos originales de la corrida de `--corridas`, la primera)
# que se insertan en B para el caso adversario.
FRAGMENTOS_ADVERSARIO = ("Purgo el aire", "Ya sale solo agua", "Suelto el bot")


def huella(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()[:20]


def clave_juez(paso_sop: PasoSOP, paso_video: PasoVideo, narracion: str) -> str:
    return huella(f"{paso_sop.numero}\n{paso_video.nombre}\n{paso_video.descripcion}\n{narracion}")


def vector_a_texto(v: np.ndarray) -> str:
    return base64.b64encode(np.asarray(v, dtype=np.float16).tobytes()).decode()


def texto_a_vector(t: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(t), dtype=np.float16).astype(np.float32)


class VectorizadorGrabadora:
    """Vectoriza con MiniLM y graba cada vector por la huella de su texto."""

    def __init__(self, real: Any) -> None:
        self.real = real
        self.vectores: dict[str, str] = {}

    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray:
        x = self.real.encode(sentences, **kwargs)
        for texto, v in zip(sentences, x, strict=True):
            self.vectores[huella(texto)] = vector_a_texto(v)
        return x


class JuezGrabadora:
    """Juez Gemma que graba cada juicio por la entrada exacta."""

    def __init__(self, juez: JuezGemma) -> None:
        self.juez = juez
        self.juicios: dict[str, dict[str, Any]] = {}

    def juzgar(
        self, paso_sop: PasoSOP, paso_video: PasoVideo, similitud: float, narracion: str
    ) -> Juicio:
        juicio = self.juez.juzgar(paso_sop, paso_video, similitud, narracion)
        self.juicios[clave_juez(paso_sop, paso_video, narracion)] = juicio.model_dump(
            mode="json", exclude={"similitud"}
        )
        return juicio


def adversario(
    pasos_b: list[PasoVideo],
    analisis_b: Analisis,
    resultado_b: Any,
    fragmentos: list[PasoVideo],
    analisis_a: Analisis,
) -> tuple[list[PasoVideo], list[Segmento]]:
    """B con los fragmentos de A después del paso del video que empareja con el paso 5."""
    cinco = next(p for p in resultado_b.clasificacion.pasos if p.indice_sop == 4)
    ultimo = resultado_b.fusiones[cinco.indice_video].originales[-1]
    corte = next(p for p in pasos_b if p.numero == ultimo).t_fin
    inicio_a, fin_a = fragmentos[0].t_inicio, fragmentos[-1].t_fin
    desfase_frag = corte + 0.5 - inicio_a
    delta = (fin_a - inicio_a) + 1.0

    def mover(t: float, d: float) -> float:
        return round(t + d, 2)

    nuevos: list[PasoVideo] = []
    for p in pasos_b:
        if p.t_inicio < corte:
            nuevos.append(p)
    for f in fragmentos:
        nuevos.append(
            f.model_copy(
                update={
                    "t_inicio": mover(f.t_inicio, desfase_frag),
                    "t_fin": mover(f.t_fin, desfase_frag),
                    "responsable": pasos_b[0].responsable,
                }
            )
        )
    for p in pasos_b:
        if p.t_inicio >= corte:
            nuevos.append(
                p.model_copy(
                    update={"t_inicio": mover(p.t_inicio, delta), "t_fin": mover(p.t_fin, delta)}
                )
            )
    nuevos = [p.model_copy(update={"numero": n}) for n, p in enumerate(nuevos, start=1)]

    def segmento_movido(s: Segmento, d: float) -> dict[str, Any]:
        datos = s.model_dump(mode="json")
        datos["t_inicio"], datos["t_fin"] = mover(s.t_inicio, d), mover(s.t_fin, d)
        datos["palabras"] = [
            {**w, "t": mover(w["t"], d), "t_fin": mover(w["t_fin"], d)} for w in datos["palabras"]
        ]
        return datos

    segmentos = [segmento_movido(s, 0) for s in analisis_b.transcripcion if s.t_inicio < corte]
    segmentos += [
        segmento_movido(s, desfase_frag)
        for s in analisis_a.transcripcion
        if inicio_a <= s.t_inicio < fin_a
    ]
    segmentos += [
        segmento_movido(s, delta) for s in analisis_b.transcripcion if s.t_inicio >= corte
    ]
    for i, s in enumerate(segmentos):
        s["id"] = i
    return nuevos, [Segmento.model_validate(s) for s in segmentos]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sop", type=Path, required=True)
    parser.add_argument("--juez", type=Path, required=True, help="JSON de diagnosticar_juez.py")
    parser.add_argument("--corridas", type=int, nargs="+", required=True)
    parser.add_argument("--analisis-a", type=Path, required=True)
    parser.add_argument("--analisis-b", type=Path, required=True)
    args = parser.parse_args(argv)

    settings = get_settings()
    sop = convertir_sop(args.sop.read_text(encoding="utf-8")).sop
    diagnostico = json.loads(args.juez.read_text(encoding="utf-8"))
    analisis_a = Analisis.model_validate_json(args.analisis_a.read_text(encoding="utf-8"))
    analisis_b = Analisis.model_validate_json(args.analisis_b.read_text(encoding="utf-8"))
    real = emp.cargar_sentence_transformer(settings.embedder_model, settings.embedder_cache_path)
    grabadora = VectorizadorGrabadora(real)
    embedder = emp.Embedder(
        "grabado", settings.embedder_cache_path, cargador=lambda m, c: grabadora
    )
    llm = ClienteLLM.desde_settings()
    juez = JuezGrabadora(JuezGemma(llm))

    casos: dict[str, Any] = {}
    primera: list[PasoVideo] = []
    for n in args.corridas:
        corrida = next(c for c in diagnostico["corridas"] if c["repeticion"] == n)
        pasos = [PasoVideo.model_validate(p) for p in corrida["pasos_video_originales"]]
        primera = primera or pasos
        r = emp.emparejar(sop, pasos, embedder, juez=juez, transcripcion=analisis_a.transcripcion)
        casos[f"a_{n}"] = {
            "video": "a",
            "antes": corrida["cumplimiento"],
            "pasos_video": [p.model_dump(mode="json") for p in pasos],
        }
        print(f"a_{n}: {corrida['cumplimiento']} -> {emp_pct(r):.2f}", flush=True)

    llm.descargar()
    pasos_b = segmentar(analisis_b, llm).pasos
    r_b = emp.emparejar(sop, pasos_b, embedder, juez=juez, transcripcion=analisis_b.transcripcion)
    fragmentos = [
        next(p for p in primera if p.cita.startswith(inicio)) for inicio in FRAGMENTOS_ADVERSARIO
    ]
    pasos_adv, segmentos_adv = adversario(pasos_b, analisis_b, r_b, fragmentos, analisis_a)
    r_adv = emp.emparejar(sop, pasos_adv, embedder, juez=juez, transcripcion=segmentos_adv)
    casos["b_adversario"] = {
        "video": "b_adversario",
        "pasos_video": [p.model_dump(mode="json") for p in pasos_adv],
        "transcripcion": [s.model_dump(mode="json") for s in segmentos_adv],
    }
    seis = next(p for p in r_adv.clasificacion.pasos if p.indice_sop == 5)
    print(f"b_adversario: paso 6 {seis.estado}, {emp_pct(r_adv):.2f} %", flush=True)
    llm.descargar()
    llm.close()

    datos = {
        "descripcion": (
            "Fixtures de regresión del rescate de un Falta (ADR-022). Videos del equipo A y B; "
            "se regeneran con scripts/grabar_rescate.py."
        ),
        "modelos": {"embedder": settings.embedder_model, "llm": settings.llm_model},
        "umbrales": {"bajo": settings.umbral_bajo, "alto": settings.umbral_alto},
        "transcripcion_a": [s.model_dump(mode="json") for s in analisis_a.transcripcion],
        "casos": casos,
        "vectores": grabadora.vectores,
        "juicios": juez.juicios,
    }
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"escrito: {SALIDA} ({SALIDA.stat().st_size // 1024} KB)")
    return 0


def emp_pct(r: Any) -> float:
    from sopvid.lenguaje.reporte import porcentaje

    return porcentaje(r)


if __name__ == "__main__":
    sys.exit(main())
