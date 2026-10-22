"""Base de MiniLM (S2): `Embedder` y `similitud`; fusión de pasos del video (S3, ADR-013) y
sus umbrales en la configuración.

Todas las pruebas usan un vectorizador simulado y no descargan nada, salvo la marcada como
"lento" (se corre con `pytest -m lento`; la primera vez baja ~470 MB a EMBEDDER_CACHE_DIR).
"""

import hashlib
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from sopvid.contrato import PasoSOP, PasoVideo
from sopvid.lenguaje import emparejamiento as emp
from sopvid.plataforma import config
from sopvid.texto import NO_IDENTIFICADO


class VectorizadorFalso:
    """Bolsa de palabras con hash a 384 dimensiones: textos con palabras en común se parecen."""

    def __init__(self) -> None:
        self.llamadas: list[list[str]] = []

    def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray:
        self.llamadas.append(list(sentences))
        x = np.zeros((len(sentences), emp.DIMENSION), dtype=np.float64)
        for i, texto in enumerate(sentences):
            for palabra in texto.lower().split():
                h = int(hashlib.md5(palabra.encode()).hexdigest(), 16)
                x[i, h % emp.DIMENSION] += 1.0
        return 3.0 * x  # sin normalizar a propósito


@pytest.fixture
def falso() -> VectorizadorFalso:
    return VectorizadorFalso()


@pytest.fixture
def cargas() -> list[tuple[str, Path]]:
    return []


@pytest.fixture
def embedder(
    falso: VectorizadorFalso, cargas: list[tuple[str, Path]], tmp_path: Path
) -> emp.Embedder:
    def cargador(modelo: str, cache_dir: Path) -> VectorizadorFalso:
        cargas.append((modelo, cache_dir))
        return falso

    return emp.Embedder("modelo-falso", tmp_path, cargador=cargador)


# ── Embedder ─────────────────────────────────────────────────────────────────────────────────


def test_crear_el_embedder_no_carga_el_modelo(embedder, cargas):
    assert not embedder.cargado
    assert cargas == []
    assert embedder.segundos_carga is None


def test_el_modelo_se_carga_una_sola_vez(embedder, cargas, falso, tmp_path):
    embedder.embed(["cerrar la válvula"])
    embedder.embed(["abrir la válvula", "purgar la línea"])
    embedder.cargar()
    assert cargas == [("modelo-falso", tmp_path)]
    assert len(falso.llamadas) == 2
    assert embedder.cargado and embedder.segundos_carga is not None


def test_embed_devuelve_filas_normalizadas_en_float32(embedder):
    x = embedder.embed(["cerrar la válvula", "colocar el cartucho nuevo", "purgar"])
    assert x.shape == (3, emp.DIMENSION)
    assert x.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(x, axis=1), 1.0, rtol=1e-6)


def test_embed_sin_textos_no_carga_el_modelo(embedder, cargas):
    x = embedder.embed([])
    assert x.shape == (0, emp.DIMENSION)
    assert cargas == []


def test_embed_conserva_el_orden_y_acepta_tuplas(embedder, falso):
    textos = ("uno dos", "tres", "cuatro cinco seis")
    x = embedder.embed(textos)
    assert falso.llamadas == [list(textos)]
    np.testing.assert_allclose(x[1], embedder.embed(["tres"])[0])


def test_un_texto_que_da_vector_cero_queda_en_cero(embedder):
    x = embedder.embed(["", "cerrar la válvula"])
    assert not x[0].any()
    assert np.linalg.norm(x[1]) == pytest.approx(1.0)


def test_cargador_por_defecto_usa_cpu_y_la_carpeta_de_cache(monkeypatch, tmp_path):
    """Sustituye el paquete `sentence_transformers` para no importar torch ni descargar nada."""
    recibido: dict[str, Any] = {}

    class SentenceTransformerFalso:
        def __init__(self, modelo: str, **kwargs: Any) -> None:
            recibido.update(modelo=modelo, **kwargs)

        def encode(self, sentences: list[str], **kwargs: Any) -> np.ndarray:
            return np.ones((len(sentences), emp.DIMENSION))

    falso = types.ModuleType("sentence_transformers")
    falso.SentenceTransformer = SentenceTransformerFalso  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", falso)

    x = emp.Embedder("org/minilm", tmp_path / "pesos").embed(["hola"])
    assert recibido == {
        "modelo": "org/minilm",
        "device": "cpu",
        "cache_folder": str(tmp_path / "pesos"),
    }
    assert x.shape == (1, emp.DIMENSION)


def test_sin_argumentos_usa_la_configuracion(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBEDDER_MODEL", "org/otro-modelo")
    monkeypatch.setenv("EMBEDDER_CACHE_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    try:
        e = emp.Embedder()
    finally:
        config.get_settings.cache_clear()
    assert e.modelo == "org/otro-modelo"
    assert e.cache_dir == tmp_path


def test_carpeta_de_cache_relativa_se_resuelve_contra_la_raiz(monkeypatch):
    monkeypatch.setenv("EMBEDDER_CACHE_DIR", "models/embedder")
    settings = config.Settings()
    assert settings.embedder_cache_path == config.PROJECT_ROOT / "models/embedder"


def test_get_embedder_devuelve_siempre_el_mismo_sin_cargar():
    emp.get_embedder.cache_clear()
    try:
        assert emp.get_embedder() is emp.get_embedder()
        assert not emp.get_embedder().cargado
    finally:
        emp.get_embedder.cache_clear()


def test_importar_el_modulo_no_importa_torch():
    """La API importa este módulo al arrancar; torch solo se carga con el modelo."""
    codigo = (
        "import sys, sopvid.lenguaje.emparejamiento; "
        "assert 'torch' not in sys.modules and 'sentence_transformers' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", codigo], check=True)


# ── similitud ────────────────────────────────────────────────────────────────────────────────


def test_similitud_es_una_matriz_m_por_n():
    rng = np.random.default_rng(0)
    s = emp.similitud(rng.normal(size=(3, 8)), rng.normal(size=(5, 8)))
    assert s.shape == (3, 5)
    assert np.all(s <= 1.0) and np.all(s >= -1.0)


def test_similitud_coseno_de_casos_conocidos():
    a = np.array([[1.0, 0.0], [0.0, 2.0], [1.0, 1.0]])
    b = np.array([[3.0, 0.0], [0.0, -1.0]])
    esperado = np.array([[1.0, 0.0], [0.0, -1.0], [np.sqrt(0.5), -np.sqrt(0.5)]])
    np.testing.assert_allclose(emp.similitud(a, b), esperado, atol=1e-6)


def test_similitud_no_depende_de_la_escala_y_es_simetrica():
    rng = np.random.default_rng(1)
    a, b = rng.normal(size=(4, 16)), rng.normal(size=(6, 16))
    np.testing.assert_allclose(emp.similitud(10 * a, 0.1 * b), emp.similitud(a, b), atol=1e-6)
    np.testing.assert_allclose(emp.similitud(b, a), emp.similitud(a, b).T, atol=1e-6)


def test_similitud_consigo_mismo_da_uno_en_la_diagonal(embedder):
    x = embedder.embed(["cerrar la válvula", "colocar el cartucho", "purgar la línea"])
    np.testing.assert_allclose(np.diag(emp.similitud(x, x)), 1.0, atol=1e-6)


def test_similitud_con_una_fila_de_ceros_da_cero():
    s = emp.similitud(np.zeros((1, 4)), np.array([[1.0, 2.0, 3.0, 4.0]]))
    assert s.tolist() == [[0.0]]


def test_similitud_acepta_un_solo_vector():
    assert emp.similitud(np.array([1.0, 0.0]), np.array([[1.0, 0.0], [0.0, 1.0]])).shape == (1, 2)


def test_similitud_rechaza_dimensiones_distintas():
    with pytest.raises(ValueError, match="dimensiones"):
        emp.similitud(np.ones((2, 3)), np.ones((2, 4)))


# ── texto_para_embeber ───────────────────────────────────────────────────────────────────────


def _paso_sop(**cambios: Any) -> PasoSOP:
    datos = {"numero": 2, "nombre": "Cerrar la llave de paso", "responsable": "Técnico"}
    return PasoSOP.model_validate({**datos, **cambios})


def _paso_video(**cambios: Any) -> PasoVideo:
    datos = {
        "numero": 2,
        "nombre": "Cerrar la llave de paso",
        "descripcion": "",
        "responsable": "Técnica",
        "t_inicio": 33.44,
        "t_fin": 54.2,
        "cita": "Ahora cierro la llave de paso",
        "fuente": "audio",
        "confianza": "alta",
    }
    return PasoVideo.model_validate({**datos, **cambios})


@pytest.mark.parametrize("crear", [_paso_sop, _paso_video], ids=["sop", "video"])
def test_texto_para_embeber_une_nombre_y_descripcion(crear):
    paso = crear(descripcion="Girar la llave a la derecha hasta el tope.")
    assert emp.texto_para_embeber(paso) == (
        "Cerrar la llave de paso. Girar la llave a la derecha hasta el tope."
    )


@pytest.mark.parametrize("crear", [_paso_sop, _paso_video], ids=["sop", "video"])
@pytest.mark.parametrize("descripcion", ["", "   ", "\n\t"])
def test_texto_para_embeber_sin_descripcion_es_solo_el_nombre(crear, descripcion):
    assert emp.texto_para_embeber(crear(descripcion=descripcion)) == "Cerrar la llave de paso"


@pytest.mark.parametrize("crear", [_paso_sop, _paso_video], ids=["sop", "video"])
def test_texto_para_embeber_colapsa_espacios(crear):
    paso = crear(nombre="  Cerrar   la llave\tde paso ", descripcion="Girar\na la  derecha. ")
    assert emp.texto_para_embeber(paso) == "Cerrar la llave de paso. Girar a la derecha."


@pytest.mark.parametrize("crear", [_paso_sop, _paso_video], ids=["sop", "video"])
@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [
        ("Cerrar la llave de paso.", "Cerrar la llave de paso. Girar a la derecha."),
        ("¿Cerró la llave?", "¿Cerró la llave? Girar a la derecha."),
        ("¡Cerrar la llave!", "¡Cerrar la llave! Girar a la derecha."),
        ("Cerrar la llave de paso. ", "Cerrar la llave de paso. Girar a la derecha."),
    ],
)
def test_texto_para_embeber_no_duplica_el_cierre_del_nombre(crear, nombre, esperado):
    paso = crear(nombre=nombre, descripcion="Girar a la derecha.")
    assert emp.texto_para_embeber(paso) == esperado
    assert ".." not in emp.texto_para_embeber(paso)


def test_texto_para_embeber_no_usa_la_cita_ni_el_responsable():
    texto = emp.texto_para_embeber(_paso_video(descripcion="Girar a la derecha."))
    assert "Ahora cierro" not in texto and "Técnica" not in texto


def test_texto_para_embeber_no_carga_el_modelo(embedder, cargas):
    emp.texto_para_embeber(_paso_sop())
    assert cargas == [] and not embedder.cargado


# ── Umbrales en la configuración ─────────────────────────────────────────────────────────────


def test_umbrales_por_defecto(monkeypatch):
    for variable in ("UMBRAL_BAJO", "UMBRAL_ALTO", "UMBRAL_FUSION"):
        monkeypatch.delenv(variable, raising=False)
    settings = config.Settings(_env_file=None)
    assert (settings.umbral_bajo, settings.umbral_alto, settings.umbral_fusion) == (
        0.55,
        0.75,
        0.55,
    )


def test_umbrales_se_leen_del_entorno(monkeypatch):
    monkeypatch.setenv("UMBRAL_BAJO", "0.5")
    monkeypatch.setenv("UMBRAL_ALTO", "0.8")
    monkeypatch.setenv("UMBRAL_FUSION", "0.6")
    settings = config.Settings(_env_file=None)
    assert (settings.umbral_bajo, settings.umbral_alto, settings.umbral_fusion) == (0.5, 0.8, 0.6)


def test_umbral_bajo_igual_al_alto_es_valido():
    assert config.Settings(_env_file=None, umbral_bajo=0.7, umbral_alto=0.7).umbral_alto == 0.7


def test_umbral_bajo_mayor_que_el_alto_falla():
    with pytest.raises(ValidationError, match="UMBRAL_BAJO"):
        config.Settings(_env_file=None, umbral_bajo=0.8, umbral_alto=0.7)


@pytest.mark.parametrize(
    "umbral", [{"umbral_bajo": -0.1}, {"umbral_alto": 1.2}, {"umbral_fusion": 1.01}]
)
def test_umbral_fuera_de_0_a_1_falla(umbral):
    with pytest.raises(ValidationError):
        config.Settings(_env_file=None, **umbral)


# ── fusionar (ADR-013) ───────────────────────────────────────────────────────────────────────

# SOP inventado "Cambio del cartucho del filtro de agua".
SOP_FILTRO = [
    _paso_sop(
        numero=1,
        nombre="Cerrar la llave de paso",
        descripcion="Girar la llave de paso del agua hasta cerrarla.",
    ),
    _paso_sop(
        numero=2,
        nombre="Retirar el cartucho usado",
        descripcion="Desenroscar el vaso del filtro y sacar el cartucho usado.",
    ),
    _paso_sop(
        numero=3,
        nombre="Colocar el cartucho nuevo",
        descripcion="Meter el cartucho nuevo en el vaso y enroscar el vaso.",
    ),
    _paso_sop(
        numero=4,
        nombre="Abrir la llave y purgar",
        descripcion="Abrir la llave de paso y dejar correr el agua un minuto.",
    ),
]
# Pasos del video: (nombre, descripción, cita). "desenroscar" y "sacar" son el paso 2 del SOP
# partido en dos, como sobre-segmenta Gemma 4 (ADR-010).
VIDEO_FILTRO = {
    "cerrar": (
        "Cerrar la llave de paso",
        "Cierro la llave de paso del agua.",
        "Primero cierro la llave de paso",
    ),
    "desenroscar": (
        "Desenroscar el vaso del filtro",
        "Desenroscar el vaso del filtro y sacarlo.",
        "Ahora desenrosco el vaso del filtro",
    ),
    "sacar": (
        "Sacar el cartucho usado",
        "Sacar el cartucho usado del vaso.",
        "Saco el cartucho usado del vaso",
    ),
    "colocar": (
        "Colocar el cartucho nuevo",
        "Meter el cartucho nuevo en el vaso.",
        "Meto el cartucho nuevo en el vaso",
    ),
    "abrir": (
        "Abrir la llave y purgar",
        "Abrir la llave y dejar correr el agua.",
        "Abro la llave y dejo correr el agua",
    ),
}


def _video(*claves: str) -> list[PasoVideo]:
    """Pasos del video en el orden dado: el paso n va del segundo 10n al 10n + 8."""
    pasos = []
    for numero, clave in enumerate(claves, start=1):
        nombre, descripcion, cita = VIDEO_FILTRO[clave]
        pasos.append(
            _paso_video(
                numero=numero,
                nombre=nombre,
                descripcion=descripcion,
                cita=cita,
                t_inicio=10.0 * numero,
                t_fin=10.0 * numero + 8,
            )
        )
    return pasos


def test_paso_partido_en_dos_se_fusiona(embedder):
    video = _video("cerrar", "desenroscar", "sacar", "colocar", "abrir")
    pasos, registro = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.55)

    assert [r.originales for r in registro] == [[1], [2, 3], [4], [5]]
    assert [r.paso_sop for r in registro] == [1, 2, 3, 4]
    assert [p.numero for p in pasos] == [r.numero for r in registro] == [1, 2, 3, 4]
    fusionado = pasos[1]
    assert fusionado.nombre == "Sacar el cartucho usado"  # el más parecido al paso 2 del SOP
    assert fusionado.descripcion == (
        "Desenroscar el vaso del filtro y sacarlo. Sacar el cartucho usado del vaso."
    )
    assert fusionado.cita == "Ahora desenrosco el vaso del filtro … Saco el cartucho usado del vaso"
    assert registro[1].citas == [video[1].cita, video[2].cita]
    assert registro[1].similitudes[1] > registro[1].similitudes[0] >= 0.55


def test_los_pasos_sin_fusionar_solo_cambian_de_numero(embedder):
    video = _video("cerrar", "desenroscar", "sacar", "colocar", "abrir")
    pasos, _ = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.55)
    assert pasos[0] == video[0]
    assert pasos[2] == video[3].model_copy(update={"numero": 3})
    assert pasos[3] == video[4].model_copy(update={"numero": 4})


def test_dos_pasos_distintos_consecutivos_no_se_fusionan(embedder):
    video = _video("cerrar", "desenroscar", "colocar", "abrir")
    pasos, registro = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.55)
    assert pasos == video
    assert [r.originales for r in registro] == [[1], [2], [3], [4]]
    assert [r.paso_sop for r in registro] == [1, 2, 3, 4]


def test_pasos_no_consecutivos_con_el_mismo_paso_del_sop_no_se_fusionan(embedder):
    video = _video("desenroscar", "cerrar", "sacar")
    pasos, registro = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.55)
    assert pasos == video
    assert [r.paso_sop for r in registro] == [2, 1, 2]


def test_tiempos_del_fusionado_son_el_minimo_y_el_maximo_de_los_originales(embedder):
    desenroscar, sacar = _video("desenroscar", "sacar")
    # El primero termina después que el segundo: el fin es el mayor, no el del último.
    desenroscar = desenroscar.model_copy(update={"t_inicio": 40.5, "t_fin": 61.25})
    sacar = sacar.model_copy(update={"t_inicio": 45.0, "t_fin": 58.75})
    (paso,), _ = emp.fusionar(SOP_FILTRO, [desenroscar, sacar], embedder, umbral=0.55)
    assert paso.t_inicio == min(desenroscar.t_inicio, sacar.t_inicio) == 40.5
    assert paso.t_fin == max(desenroscar.t_fin, sacar.t_fin) == 61.25


def test_tiempos_del_fusionado_en_orden_son_el_inicio_del_primero_y_el_fin_del_ultimo(embedder):
    video = _video("desenroscar", "sacar")
    (paso,), _ = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.55)
    assert (paso.t_inicio, paso.t_fin) == (video[0].t_inicio, video[1].t_fin) == (10.0, 28.0)


@pytest.mark.parametrize(
    ("primero", "segundo", "esperado"),
    [
        ({"confianza": "alta"}, {"confianza": "media"}, {"confianza": "media"}),
        ({"confianza": "baja"}, {"confianza": "alta"}, {"confianza": "baja"}),
        ({"fuente": "audio"}, {"fuente": "visual"}, {"fuente": "visual"}),
        ({"fuente": "inferido"}, {"fuente": "audio"}, {"fuente": "inferido"}),
        ({"responsable": "Técnica"}, {"responsable": "Técnica"}, {"responsable": "Técnica"}),
        (
            {"responsable": "Técnica"},
            {"responsable": "Supervisor"},
            {"responsable": "Técnica, Supervisor"},
        ),
        ({"responsable": NO_IDENTIFICADO}, {}, {"responsable": "Técnica"}),
        (
            {"responsable": NO_IDENTIFICADO},
            {"responsable": NO_IDENTIFICADO},
            {"responsable": NO_IDENTIFICADO},
        ),
        ({"cita": ""}, {}, {"cita": "Saco el cartucho usado del vaso"}),
    ],
)
def test_el_fusionado_une_la_evidencia(embedder, primero, segundo, esperado):
    desenroscar, sacar = _video("desenroscar", "sacar")
    video = [desenroscar.model_copy(update=primero), sacar.model_copy(update=segundo)]
    (paso,), (fusion,) = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.55)
    assert paso.model_dump(include=set(esperado)) == esperado
    assert fusion.citas == [p.cita for p in video]


def test_coseno_bajo_el_umbral_no_fusiona(embedder):
    video = _video("desenroscar", "sacar")  # cosenos 0.64 y 0.77 con el vectorizador falso
    pasos, registro = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.7)
    assert pasos == video
    assert [r.originales for r in registro] == [[1], [2]]


def test_el_umbral_por_defecto_sale_de_la_configuracion(monkeypatch, embedder):
    video = _video("desenroscar", "sacar")
    monkeypatch.setenv("UMBRAL_FUSION", "0.99")
    config.get_settings.cache_clear()
    try:
        pasos, _ = emp.fusionar(SOP_FILTRO, video, embedder)
    finally:
        config.get_settings.cache_clear()
    assert pasos == video


def test_fusionar_vectoriza_todo_en_una_sola_llamada(embedder, falso):
    emp.fusionar(SOP_FILTRO, _video("cerrar", "desenroscar"), embedder, umbral=0.55)
    assert len(falso.llamadas) == 1
    assert len(falso.llamadas[0]) == len(SOP_FILTRO) + 2


def test_fusionar_sin_pasos_del_video_no_carga_el_modelo(embedder, cargas):
    assert emp.fusionar(SOP_FILTRO, [], embedder) == ([], [])
    assert cargas == []


def test_fusionar_sin_pasos_del_sop_falla(embedder):
    with pytest.raises(ValueError, match="SOP"):
        emp.fusionar([], _video("cerrar"), embedder)


def test_fusionar_pasos_del_video_fuera_de_orden_falla(embedder):
    cerrar, desenroscar = _video("cerrar", "desenroscar")
    with pytest.raises(ValueError, match="fuera de orden"):
        emp.fusionar(SOP_FILTRO, [desenroscar, cerrar], embedder)


# ── Modelo real (lento) ──────────────────────────────────────────────────────────────────────


@pytest.mark.lento
def test_minilm_real_distingue_parafrasis_de_otro_paso():
    e = emp.Embedder()
    x = e.embed(["cerrar la llave de paso", "cierro la válvula", "coloco el cartucho nuevo"])
    assert x.shape == (3, emp.DIMENSION)
    np.testing.assert_allclose(np.linalg.norm(x, axis=1), 1.0, rtol=1e-5)
    s = emp.similitud(x[:1], x[1:])[0]
    assert s[0] > s[1], f"válvula {s[0]:.3f} vs cartucho {s[1]:.3f}"


@pytest.mark.lento
def test_minilm_real_fusiona_el_paso_partido():
    video = _video("cerrar", "desenroscar", "sacar", "colocar", "abrir")
    pasos, registro = emp.fusionar(SOP_FILTRO, video, emp.Embedder(), umbral=0.55)
    assert [r.originales for r in registro] == [[1], [2, 3], [4], [5]], registro
    assert [r.paso_sop for r in registro] == [1, 2, 3, 4]
    assert (pasos[1].t_inicio, pasos[1].t_fin) == (video[1].t_inicio, video[2].t_fin)
