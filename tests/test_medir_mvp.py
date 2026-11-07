"""Partes puras de `scripts/medir_mvp.py`: Sobra falsos, validez, resumen, veredicto, informe y
estado de git.

La medición de verdad necesita Whisper, Ollama y los videos A y B: se lanza a mano.
"""

import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sopvid.contrato import SOP, PasoSOP
from sopvid.plataforma.config import Settings

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import medir_mvp as mvp  # noqa: E402  (la ruta se ajusta arriba)

SOP_SEIS = SOP(
    titulo="Inventado",
    pasos=[PasoSOP(numero=n, nombre=f"Paso {n}", responsable="Técnico") for n in range(1, 7)],
)
# Como la de B: faltan 2 y 6 y hay un paso agregado entre 74 y 86 s.
ANOTACION_B = {
    "pasos": [
        {"sop": None, "t": 3.5},
        {"sop": 1, "t": 17.0},
        {"sop": 3, "t": 31.7},
        {"sop": 4, "t": 49.9},
        {"sop": "extra", "t": 74.1},
        {"sop": 5, "t": 85.9},
        {"sop": None, "t": 111.0},
    ]
}


def _fila(estado, indice_sop=None, t=None, marco=None):
    return SimpleNamespace(estado=estado, indice_sop=indice_sop, t_inicio=t, marco_operador=marco)


def _guardado(filas, cumplimiento, semaforo="rojo", segmentacion="llm", avisos=()):
    conteo = {}
    for f in filas:
        if f.marco_operador is None:
            conteo[f.estado] = conteo.get(f.estado, 0) + 1
    clasificacion = SimpleNamespace(pasos=filas, resumen=SimpleNamespace(conteo=conteo))
    return SimpleNamespace(
        resultado=SimpleNamespace(clasificacion=clasificacion),
        cumplimiento=cumplimiento,
        semaforo=semaforo,
        metadatos=SimpleNamespace(
            segmentacion=segmentacion,
            avisos=[SimpleNamespace(tipo=a) for a in avisos],
            dispositivos=None,
        ),
    )


FILAS_B = [
    _fila("Cumple", 0, 17.0),
    _fila("Falta", 1),
    _fila("Cumple", 2, 32.0),
    _fila("Cumple", 3, 50.0),
    _fila("Cumple", 4, 86.0),
    _fila("Falta", 5),
    _fila("Sobra", t=74.5),  # el paso agregado, en su tramo
    _fila("Sobra", t=51.2),  # fragmento de más
    _fila("Sobra", t=3.5, marco="intro"),
]


def _esperado_b():
    return mvp.esperado_de(ANOTACION_B, SOP_SEIS, 115.0)


def test_sobra_falsos_excluye_los_agregados_y_el_marco_del_operador():
    assert mvp.sobra_falsos(_guardado(FILAS_B, 66.7), _esperado_b()) == [51.2]


def test_anotar_b_pasa_y_cuenta_el_sobra_falso():
    corrida = mvp.anotar(
        mvp.Corrida("video_b", 1), _guardado(FILAS_B, 66.67), SOP_SEIS, _esperado_b(), Settings()
    )

    assert corrida.pasa
    assert corrida.criterio["falta_obtenida"] == [2, 6]
    assert corrida.criterio["extras_encontrados"] == "1/1"
    assert corrida.sobra_falsos == [51.2]
    assert corrida.cumplimiento == 66.67
    assert corrida.conteo["Sobra"] == 2  # la intro no cuenta


@pytest.mark.parametrize(
    ("segmentacion", "avisos"), [("heuristica", ()), ("llm", ("juez_sin_revisar",))]
)
def test_heuristica_o_avisos_hacen_la_corrida_no_valida(segmentacion, avisos):
    guardado = _guardado(FILAS_B, 66.67, segmentacion=segmentacion, avisos=avisos)
    corrida = mvp.anotar(mvp.Corrida("video_b", 1), guardado, SOP_SEIS, _esperado_b(), Settings())

    assert corrida.criterio["pasa"]  # el criterio se cumple...
    assert not corrida.valida
    assert not corrida.pasa  # ...pero la corrida no cuenta


def _corrida(video, n, pct, pasa=True, segmentacion="llm"):
    return mvp.Corrida(
        video,
        n,
        cumplimiento=pct,
        semaforo="verde" if pct >= 90 else "amarillo",
        criterio={"pasa": pasa, "falta_obtenida": [], "falta_esperada": []},
        segmentacion=segmentacion,
    )


def test_resumen_y_veredicto():
    corridas = [
        _corrida("video_a", 1, 100.0),
        _corrida("video_a", 2, 83.33, pasa=False),
        _corrida("video_a", 3, 100.0),
        _corrida("video_b", 1, 66.67),
    ]

    r = mvp.resumen(corridas)

    assert r["video_a"] == {
        "pasan": 2,
        "corridas": 3,
        "no_validas": 0,
        "cumplimiento_min": 83.33,
        "cumplimiento_max": 100.0,
        "semaforos": ["amarillo", "verde"],
    }
    assert r["video_b"]["pasan"] == 1
    assert mvp.veredicto(corridas) == "no pasa"
    assert mvp.codigo_salida(corridas) == 1


def test_codigo_de_salida():
    todas = [_corrida("video_a", 1, 100.0), _corrida("video_b", 1, 66.67)]
    con_heuristica = [*todas, _corrida("video_a", 2, 100.0, segmentacion="heuristica")]

    assert mvp.veredicto(todas) == "pasa"
    assert mvp.codigo_salida(todas) == 0
    assert mvp.veredicto(con_heuristica) == "no válida"
    assert mvp.codigo_salida(con_heuristica) == 2
    assert mvp.codigo_salida([]) == 2


def _datos(corridas, cambios=0):
    return {
        "fecha": "2026-11-07 12:00",
        "repeticiones": 1,
        "git": {"commit": "abc1234", "rama": "main", "cambios_sin_commit": cambios},
        "configuracion": {
            "whisper": "large-v3-turbo",
            "llm": "gemma4:e4b-it-q4_K_M",
            "embedder": "minilm",
            "umbral_bajo": 0.55,
            "umbral_alto": 0.75,
            "umbral_fusion": 0.55,
            "semaforo_verde": 90,
            "semaforo_amarillo": 70,
            "gpu": None,
        },
        "resumen": mvp.resumen(corridas),
    }


def test_informe_registra_el_commit_y_avisa_de_cambios_sin_commit():
    corridas = [_corrida("video_a", 1, 100.0)]

    limpio = mvp.informe(_datos(corridas), corridas)
    sucio = mvp.informe(_datos(corridas, cambios=3), corridas)

    assert "**Veredicto: pasa**" in limpio
    assert "Commit `abc1234` en la rama `main` · sin cambios sin commit" in limpio
    assert "**3 archivo(s) con cambios sin commit**" in sucio
    assert "| video_a | 1/1 | 0 | 100 % | verde |" in limpio
    assert "| video_a | 1 | 100 | verde |" in limpio


def test_informe_marca_la_corrida_no_valida():
    corridas = [_corrida("video_a", 1, 100.0, segmentacion="heuristica")]

    texto = mvp.informe(_datos(corridas), corridas)

    assert "**Veredicto: no válida**" in texto
    assert "(no válida: heuristica)" in texto


def test_estado_git_sin_git_o_fuera_de_un_repo(tmp_path, monkeypatch):
    # No basta una carpeta temporal: puede quedar dentro de otro repo (p. ej. el home).
    monkeypatch.setattr(mvp, "_git", lambda *args, raiz: None)

    assert mvp.estado_git(tmp_path) == {"commit": None, "rama": None, "cambios_sin_commit": None}


@pytest.mark.skipif(shutil.which("git") is None, reason="sin git")
def test_estado_git_cuenta_cambios_sin_commit_y_no_los_nuevos(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "prueba@example.com")
    git("config", "user.name", "Prueba")
    (tmp_path / "a.txt").write_text("uno\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "inicio")
    (tmp_path / "a.txt").write_text("dos\n")
    (tmp_path / "nuevo.txt").write_text("sin seguimiento\n")

    estado = mvp.estado_git(tmp_path)

    assert len(estado["commit"]) == 40
    assert estado["rama"] == "main"
    assert estado["cambios_sin_commit"] == 1
