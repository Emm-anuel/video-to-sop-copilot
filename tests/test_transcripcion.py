"""Pruebas de `sopvid.percepcion.transcripcion` (RF-09, RF-10).

Las unitarias simulan el modelo de faster-whisper con segmentos y palabras inventados: no
descargan nada. La prueba `lento` usa el modelo real con el audio de SOPVID_AUDIO_PRUEBA (fuera
del repo) y se salta si la variable no apunta a un archivo. Para exigir que haya corrido en un
dispositivo (p. ej. que no cayó a CPU): SOPVID_DISPOSITIVO_ESPERADO=cuda.
"""

import gc
import logging
import os
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from sopvid.contrato import Analisis, Idioma
from sopvid.percepcion import transcripcion as tr
from sopvid.percepcion.medios import MedioInvalido
from sopvid.percepcion.transcripcion import (
    TranscriptorWhisper,
    elegir_dispositivo,
    escritor_txt,
    marca_tiempo,
    normalizar,
)
from sopvid.plataforma.config import PROJECT_ROOT, Settings


def palabra(w: str, t: float, t_fin: float) -> SimpleNamespace:
    return SimpleNamespace(word=w, start=t, end=t_fin)


def segmento(t: float, t_fin: float, texto: str, palabras=None) -> SimpleNamespace:
    return SimpleNamespace(start=t, end=t_fin, text=texto, words=palabras)


# Narración inventada; las palabras traen el espacio inicial, como las de faster-whisper.
CRUDOS = [
    segmento(
        0.0,
        4.5,
        " Primero reviso la presión del manómetro.",
        [palabra(" Primero", 0.0, 0.6), palabra(" reviso", 0.6, 1.1), palabra(" la", 1.1, 1.3)],
    ),
    segmento(4.2, 8.0, "  Después  cierro la válvula. ", [palabra(" Después", 4.2, 4.9)]),
    segmento(8.0, 9.0, "   "),
    segmento(9.5, 12.25, "Por último anoto la lectura.", [palabra(" Por", 9.5, 9.8)]),
]


class ModeloFalso:
    """Imita `WhisperModel.transcribe`: devuelve un generador de segmentos y la info."""

    def __init__(self, crudos, idioma="es", prob=0.973, duracion=12.5, error=None, antes=None):
        self.crudos, self.error, self.antes = crudos, error, antes
        self.info = SimpleNamespace(language=idioma, language_probability=prob, duration=duracion)
        self.llamadas: list[dict] = []

    def transcribe(self, audio: str, **kwargs):
        self.llamadas.append(kwargs)
        if self.error is not None:
            raise self.error

        def generar():
            for i, crudo in enumerate(self.crudos):
                if self.antes is not None:
                    self.antes(i)
                if isinstance(crudo, Exception):
                    raise crudo
                yield crudo

        return generar(), self.info


class FabricaFalsa:
    """Registra cada carga y entrega el modelo que corresponda al dispositivo."""

    def __init__(self, **modelos: ModeloFalso):
        self.modelos = modelos
        self.cargas: list[tuple[str, str, str, Path]] = []

    def __call__(self, modelo: str, dispositivo: str, compute_type: str, cache: Path):
        self.cargas.append((modelo, dispositivo, compute_type, cache))
        return self.modelos[dispositivo]


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    archivo = tmp_path / "audio.mp3"
    archivo.write_bytes(b"\x00")  # el modelo falso no lo lee
    return archivo


def ajustes(tmp_path: Path, **valores) -> Settings:
    """Ajustes de Whisper fijos: no dependen del perfil que tenga el `.env` de quien corre."""
    valores.setdefault("whisper_modelo", "small")
    valores.setdefault("whisper_dispositivo", "cpu")
    valores.setdefault("whisper_compute_type", "auto")
    return Settings(whisper_cache_dir=tmp_path / "whisper", **valores)


# ── Normalización ────────────────────────────────────────────────────────────


def test_normalizar_ids_texto_solapes_y_vacios() -> None:
    segmentos = normalizar(CRUDOS)

    assert [s.id for s in segmentos] == [0, 1, 2]
    assert [s.texto for s in segmentos] == [
        "Primero reviso la presión del manómetro.",
        "Después cierro la válvula.",
        "Por último anoto la lectura.",
    ]
    # El segundo empezaba en 4.2, antes del fin del primero (4.5): se recorta.
    assert (segmentos[1].t_inicio, segmentos[1].t_fin) == (4.5, 8.0)
    assert segmentos[1].palabras[0].t == 4.5
    assert [p.w for p in segmentos[0].palabras] == ["Primero", "reviso", "la"]
    Analisis(
        video_id=1,
        duracion_s=12.5,
        idioma=Idioma(codigo="es", confianza=1),
        transcripcion=segmentos,
    )


def test_normalizar_segmento_contenido_en_el_anterior() -> None:
    primero, segundo = normalizar([segmento(0.0, 5.0, "a"), segmento(1.0, 3.0, "b")])

    assert (segundo.t_inicio, segundo.t_fin) == (5.0, 5.0)
    assert segundo.t_inicio >= primero.t_fin


def test_normalizar_palabras_en_orden_y_dentro_del_segmento() -> None:
    crudas = [
        palabra(" uno", -0.5, 0.2),  # negativa
        palabra(" dos", 1.0, 0.8),  # fin antes del inicio
        palabra("  ", 1.1, 1.2),  # vacía
        palabra(" tres", 0.9, 1.4),  # empieza antes que la anterior
        palabra(" cuatro", 2.5, 9.0),  # termina después del segmento
    ]
    (seg,) = normalizar([segmento(0.0, 3.0, "uno dos tres cuatro", crudas)])

    assert [(p.w, p.t, p.t_fin) for p in seg.palabras] == [
        ("uno", 0.0, 0.2),
        ("dos", 1.0, 1.0),
        ("tres", 1.0, 1.4),
        ("cuatro", 2.5, 3.0),
    ]


def test_normalizar_tiempos_invalidos_y_redondeo() -> None:
    a, b = normalizar([segmento(-1.0, float("nan"), "a"), segmento(0.123456, 2.0000004, "b", None)])

    assert (a.t_inicio, a.t_fin) == (0.0, 0.0)
    assert (b.t_inicio, b.t_fin) == (0.123, 2.0)
    assert b.palabras == []


# ── TranscriptorWhisper con modelo simulado ─────────────────────────────────


def test_idioma_automatico(tmp_path: Path, audio: Path) -> None:
    modelo = ModeloFalso(CRUDOS)
    t = TranscriptorWhisper(ajustes(tmp_path), FabricaFalsa(cpu=modelo)).transcribir(audio)

    assert modelo.llamadas[0]["language"] is None
    assert t.idioma == Idioma(codigo="es", confianza=0.973, fijado_a_mano=False)
    assert (t.dispositivo, t.compute_type, t.respaldo_cpu) == ("cpu", "int8", False)
    assert t.duracion_s == 12.5
    assert [s.id for s in t.segmentos] == [0, 1, 2]


def test_idioma_fijado_a_mano(tmp_path: Path, audio: Path) -> None:
    modelo = ModeloFalso(CRUDOS, idioma="es", prob=1.0)
    t = TranscriptorWhisper(ajustes(tmp_path), FabricaFalsa(cpu=modelo)).transcribir(
        audio, idioma=" ES "
    )

    assert modelo.llamadas[0]["language"] == "es"
    assert t.idioma == Idioma(codigo="es", confianza=1.0, fijado_a_mano=True)


def test_parametros_reproducibles(tmp_path: Path, audio: Path) -> None:
    modelo = ModeloFalso(CRUDOS)
    fabrica = FabricaFalsa(cpu=modelo)
    TranscriptorWhisper(ajustes(tmp_path, whisper_modelo="tiny"), fabrica).transcribir(audio)

    llamada = modelo.llamadas[0]
    assert llamada["word_timestamps"] is True
    assert llamada["vad_filter"] is True
    assert llamada["temperature"] == 0.0
    assert llamada["beam_size"] == tr.BEAM
    assert llamada["condition_on_previous_text"] is False
    assert fabrica.cargas == [("tiny", "cpu", "int8", tmp_path / "whisper")]


def test_txt_se_escribe_mientras_avanza(tmp_path: Path, audio: Path) -> None:
    txt = tmp_path / "salida" / "transcripcion.txt"
    validos_antes = [0, 1, 2, 2]  # segmentos no vacíos entre los crudos anteriores a cada uno
    lineas_vistas: list[int] = []

    def antes(i: int) -> None:
        lineas_vistas.append(len(txt.read_text(encoding="utf-8").splitlines()))

    largo = [*CRUDOS, segmento(3725.4, 3727.0, "Fin.")]
    validos_antes.append(3)
    modelo = ModeloFalso(largo, antes=antes)
    with escritor_txt(txt) as al_segmento:
        TranscriptorWhisper(ajustes(tmp_path), FabricaFalsa(cpu=modelo)).transcribir(
            audio, al_segmento=al_segmento
        )

    assert lineas_vistas == validos_antes
    assert txt.read_bytes().decode("utf-8").split("\n") == [
        "[00:00] Primero reviso la presión del manómetro.",
        "[00:04] Después cierro la válvula.",
        "[00:09] Por último anoto la lectura.",
        "[62:05] Fin.",
        "",
    ]


@pytest.mark.parametrize(
    ("segundos", "marca"), [(0, "00:00"), (59.99, "00:59"), (60, "01:00"), (3725.4, "62:05")]
)
def test_marca_tiempo(segundos: float, marca: str) -> None:
    assert marca_tiempo(segundos) == marca


def test_modelo_liberado_al_terminar(tmp_path: Path, audio: Path) -> None:
    referencias: list[weakref.ref] = []

    def fabrica(*_args):
        modelo = ModeloFalso(CRUDOS)
        referencias.append(weakref.ref(modelo))
        return modelo

    transcriptor = TranscriptorWhisper(ajustes(tmp_path), fabrica)
    transcriptor.transcribir(audio)
    gc.collect()
    assert referencias[0]() is None


def test_modelo_liberado_si_falla(tmp_path: Path, audio: Path) -> None:
    referencias: list[weakref.ref] = []

    def fabrica(*_args):
        modelo = ModeloFalso([CRUDOS[0], ValueError("roto")])
        referencias.append(weakref.ref(modelo))
        return modelo

    with pytest.raises(ValueError):
        TranscriptorWhisper(ajustes(tmp_path), fabrica).transcribir(audio)
    gc.collect()
    assert referencias[0]() is None


def test_audio_inexistente(tmp_path: Path) -> None:
    transcriptor = TranscriptorWhisper(ajustes(tmp_path), FabricaFalsa())

    with pytest.raises(MedioInvalido, match="no existe"):
        transcriptor.transcribir(tmp_path / "no_existe.mp3")


def test_logs_sin_texto(tmp_path: Path, audio: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="sopvid")
    TranscriptorWhisper(ajustes(tmp_path), FabricaFalsa(cpu=ModeloFalso(CRUDOS))).transcribir(audio)

    mensajes = " ".join(r.getMessage() for r in caplog.records)
    assert "3 segmentos y 5 palabras" in mensajes
    for palabra_dicha in ("manómetro", "válvula", "lectura", "Primero"):
        assert palabra_dicha not in mensajes


# ── Dispositivo y respaldo a CPU ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("gpus", "dispositivo", "compute", "esperado"),
    [
        (0, "auto", "auto", ("cpu", "int8")),
        (1, "auto", "auto", ("cuda", "float16")),
        (1, "cpu", "auto", ("cpu", "int8")),
        (0, "cuda", "auto", ("cuda", "float16")),
        (1, "auto", "int8_float16", ("cuda", "int8_float16")),
    ],
)
def test_elegir_dispositivo(monkeypatch, gpus, dispositivo, compute, esperado) -> None:
    monkeypatch.setattr(tr, "_gpus_cuda", lambda: gpus)
    assert elegir_dispositivo(dispositivo, compute) == esperado


def test_respaldo_a_cpu_si_cuda_falla(
    tmp_path: Path, audio: Path, monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(tr, "_gpus_cuda", lambda: 1)
    fabrica = FabricaFalsa(
        cuda=ModeloFalso(CRUDOS, error=RuntimeError("Library cublas64_12.dll is not found")),
        cpu=ModeloFalso(CRUDOS),
    )
    ajuste = ajustes(tmp_path, whisper_dispositivo="auto", whisper_modelo="large-v3-turbo")

    t = TranscriptorWhisper(ajuste, fabrica).transcribir(audio)

    assert [(d, c) for _, d, c, _ in fabrica.cargas] == [("cuda", "float16"), ("cpu", "int8")]
    assert (t.dispositivo, t.compute_type, t.respaldo_cpu) == ("cpu", "int8", True)
    assert len(t.segmentos) == 3
    (aviso,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "large-v3-turbo" in aviso.getMessage()
    assert "RNF-01" in aviso.getMessage()


def test_sin_respaldo_si_cuda_es_explicito(tmp_path: Path, audio: Path) -> None:
    fabrica = FabricaFalsa(cuda=ModeloFalso(CRUDOS, error=RuntimeError("sin cuBLAS")))

    with pytest.raises(RuntimeError, match="sin cuBLAS"):
        TranscriptorWhisper(ajustes(tmp_path, whisper_dispositivo="cuda"), fabrica).transcribir(
            audio
        )
    assert len(fabrica.cargas) == 1


def test_sin_respaldo_si_ya_salieron_segmentos(tmp_path: Path, audio: Path, monkeypatch) -> None:
    monkeypatch.setattr(tr, "_gpus_cuda", lambda: 1)
    fabrica = FabricaFalsa(cuda=ModeloFalso([CRUDOS[0], RuntimeError("CUDA out of memory")]))
    lineas: list[str] = []

    with pytest.raises(RuntimeError, match="out of memory"):
        TranscriptorWhisper(ajustes(tmp_path, whisper_dispositivo="auto"), fabrica).transcribir(
            audio, al_segmento=lambda s: lineas.append(s.texto)
        )
    assert len(fabrica.cargas) == 1
    assert len(lineas) == 1  # el TXT no recibe segmentos repetidos


# ── Configuración ────────────────────────────────────────────────────────────


def test_config_de_whisper() -> None:
    ajuste = Settings(whisper_cache_dir=Path("models/whisper"))
    assert ajuste.whisper_cache_path == PROJECT_ROOT / "models" / "whisper"
    with pytest.raises(ValidationError):
        Settings(whisper_dispositivo="gpu")


# ── Modelo real (lento) ──────────────────────────────────────────────────────

AUDIO_PRUEBA = os.environ.get("SOPVID_AUDIO_PRUEBA", "")


@pytest.mark.lento
@pytest.mark.skipif(
    not AUDIO_PRUEBA or not Path(AUDIO_PRUEBA).is_file(),
    reason="SOPVID_AUDIO_PRUEBA no apunta a un archivo de audio",
)
def test_whisper_real(tmp_path: Path) -> None:
    txt = tmp_path / "transcripcion.txt"
    with escritor_txt(txt) as al_segmento:
        t = TranscriptorWhisper().transcribir(Path(AUDIO_PRUEBA), al_segmento=al_segmento)

    Analisis(video_id=1, duracion_s=t.duracion_s, idioma=t.idioma, transcripcion=t.segmentos)
    assert t.segmentos
    assert all(s.palabras for s in t.segmentos)
    assert 0 < t.idioma.confianza <= 1
    assert t.segmentos[-1].t_fin <= t.duracion_s + 0.5
    assert len(txt.read_text(encoding="utf-8").splitlines()) == len(t.segmentos)
    esperado = os.environ.get("SOPVID_DISPOSITIVO_ESPERADO")
    if esperado:
        assert t.dispositivo == esperado
        assert not t.respaldo_cpu
