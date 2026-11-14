"""Partes puras de `scripts/medir_imagenes.py`: segundos por imagen, recomendación e informe.

La medición de verdad necesita Ollama y los videos del equipo: se lanza a mano. Las corridas de
aquí son inventadas.
"""

import sys
from dataclasses import asdict
from pathlib import Path

from sopvid.contrato import Contexto, Dato, Elemento

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import medir_imagenes as mi  # noqa: E402  (la ruta se ajusta arriba)


def _ficha(lugar: Dato | None = None, equipos: tuple[str, ...] = ("Cubeta",)) -> dict:
    return Contexto(
        actividad=Dato(valor="Cambio de cartucho", confianza="alta", fuente="audio", t=1.0),
        lugar=lugar or Contexto().lugar,
        equipos=[Elemento(nombre=e) for e in equipos],
    ).model_dump(mode="json")


def _par(config: str = "gpu", video: str = "video_c") -> tuple[mi.Corrida, mi.Corrida]:
    sin = mi.Corrida(
        video=video, config=config, con_imagenes=False, segundos_contexto=10.0,
        contexto_generado=True, ficha=_ficha(), afinidad=94,
    )  # fmt: skip
    con = mi.Corrida(
        video=video, config=config, con_imagenes=True, imagenes_pedidas=6, imagenes_descritas=6,
        segundos_fotogramas=9.0, segundos_contexto=13.0, contexto_generado=True,
        ficha=_ficha(
            Dato(valor="Cuarto de bombas", confianza="media", fuente="visual", t=12.5),
            ("Cubeta", "Manómetro"),
        ),
        afinidad=96,
        descripciones=[
            {"t": 12.5, "descripcion": "Operador junto a un tablero", "personas": 1,
             "equipos": ["manómetro"], "texto_visible": ["BOMBA B-12"], "riesgos": []},
        ],
    )  # fmt: skip
    return con, sin


def test_por_imagen_bruto_y_extra() -> None:
    con, sin = _par()
    assert mi.por_imagen(con, sin) == {"bruto": 1.5, "extra": 2.0, "extra_total": 12.0}
    vacia = mi.Corrida(video="v", config="gpu", con_imagenes=True)
    assert mi.por_imagen(vacia, sin)["extra"] is None


def test_pares_y_recomendacion_por_dispositivo() -> None:
    gpu = _par("gpu")
    cpu_con, cpu_sin = _par("cpu")
    cpu_con.segundos_fotogramas, cpu_con.segundos_contexto = 90.0, 70.0
    cpu_sin.segundos_contexto = 60.0
    fallida = mi.Corrida(video="video_d", config="gpu", con_imagenes=True, error="LLMError")
    corridas = [*gpu, cpu_con, cpu_sin, fallida]
    assert len(mi.pares(corridas)) == 2  # la fallida no tiene par
    assert mi.recomendacion(corridas) == {"seg_imagen_gpu": 2.0, "seg_imagen_cpu": 16.7}
    assert mi.recomendacion([]) == {"seg_imagen_gpu": None, "seg_imagen_cpu": None}


def test_estimacion_contra_el_extra_real() -> None:
    con, sin = _par()
    assert mi.estimacion(con, sin, 1.5) == {"estimado": 9.0, "real": 12.0, "error": -3.0}


def test_informe_con_tiempos_ficha_y_descripciones() -> None:
    con, sin = _par()
    datos = {
        "fecha": "2026-11-11T00:00:00",
        "git": {"commit": "abc123", "cambios_sin_commit": 2},
        "settings": {
            "llm_model": "gemma4:e4b-it-q4_K_M", "fotogramas_lote": 8, "fotogramas_lado_px": 512,
            "seg_imagen_gpu": 1.5, "seg_imagen_cpu": 15.0,
        },
        "corridas": [asdict(sin), asdict(con)],
    }  # fmt: skip
    texto = mi.informe(datos)
    assert "(con cambios sin commit)" in texto
    assert "| video_c | gpu (desconocido) | 6 (6) | 9 | 13 / 10 | 12 | 1.5 / 2 | 9 | -3 |" in texto
    assert "`SEG_IMAGEN_GPU=2`" in texto
    assert "| 94 → 96 | lugar |" in texto  # el lugar sale de una imagen
    assert "| — / manometro |" in texto  # equipo solo con imágenes (normalizado)
    assert "| 12.5 | Operador junto a un tablero | 1 | manómetro | BOMBA B-12 | — |" in texto
