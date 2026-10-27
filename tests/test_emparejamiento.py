"""Base de MiniLM (S2): `Embedder` y `similitud`; fusión de pasos del video (S3, ADR-013),
asignación con el algoritmo húngaro, clasificación por umbrales, orden y `emparejar` (S3,
ADR-012), y los umbrales en la configuración.

Todas las pruebas usan un vectorizador simulado y no descargan nada, salvo la marcada como
"lento" (se corre con `pytest -m lento`; la primera vez baja ~470 MB a EMBEDDER_CACHE_DIR).
"""

import hashlib
import subprocess
import sys
import types
from itertools import combinations, pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError
from scipy.optimize import linear_sum_assignment

from sopvid.contrato import SOP, Clasificacion, Par, PasoSOP, PasoVideo, ResultadoPaso
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


def _paso_video_sin_cita(**cambios: Any) -> PasoVideo:
    """Paso del video sin cita: su texto se arma igual que el de un paso del SOP."""
    return _paso_video(**{"cita": "", "confianza": "baja", **cambios})


@pytest.mark.parametrize("crear", [_paso_sop, _paso_video_sin_cita], ids=["sop", "video"])
def test_texto_para_embeber_une_nombre_y_descripcion(crear):
    paso = crear(descripcion="Girar la llave a la derecha hasta el tope.")
    assert emp.texto_para_embeber(paso) == (
        "Cerrar la llave de paso. Girar la llave a la derecha hasta el tope."
    )


@pytest.mark.parametrize("crear", [_paso_sop, _paso_video_sin_cita], ids=["sop", "video"])
@pytest.mark.parametrize("descripcion", ["", "   ", "\n\t"])
def test_texto_para_embeber_sin_descripcion_es_solo_el_nombre(crear, descripcion):
    assert emp.texto_para_embeber(crear(descripcion=descripcion)) == "Cerrar la llave de paso"


@pytest.mark.parametrize("crear", [_paso_sop, _paso_video_sin_cita], ids=["sop", "video"])
def test_texto_para_embeber_colapsa_espacios(crear):
    paso = crear(nombre="  Cerrar   la llave\tde paso ", descripcion="Girar\na la  derecha. ")
    assert emp.texto_para_embeber(paso) == "Cerrar la llave de paso. Girar a la derecha."


@pytest.mark.parametrize("crear", [_paso_sop, _paso_video_sin_cita], ids=["sop", "video"])
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


def test_texto_del_paso_del_video_agrega_la_cita():
    paso = _paso_video(descripcion="Girar a la derecha.")
    assert emp.texto_para_embeber(paso) == (
        "Cerrar la llave de paso. Girar a la derecha. Ahora cierro la llave de paso"
    )


def test_texto_del_paso_del_video_sin_descripcion_es_nombre_y_cita():
    assert emp.texto_para_embeber(_paso_video()) == (
        "Cerrar la llave de paso. Ahora cierro la llave de paso"
    )


@pytest.mark.parametrize(
    ("descripcion", "cita", "esperado"),
    [
        (
            "Girar a la derecha",
            "¿La cerré?",
            "Cerrar la llave de paso. Girar a la derecha. ¿La cerré?",
        ),
        ("¡Girar!", "  Ya   la cerré.  ", "Cerrar la llave de paso. ¡Girar! Ya la cerré."),
    ],
)
def test_texto_del_paso_del_video_no_duplica_puntos_y_colapsa_espacios(descripcion, cita, esperado):
    texto = emp.texto_para_embeber(_paso_video(descripcion=descripcion, cita=cita))
    assert texto == esperado
    assert ".." not in texto


def test_texto_para_embeber_no_usa_el_responsable():
    assert "Técnica" not in emp.texto_para_embeber(_paso_video(descripcion="Girar a la derecha."))


def test_la_cita_acerca_un_paso_con_descripcion_generica_a_su_paso_del_sop(embedder):
    # Caso del video A (ADR-012): Gemma resumió "me pongo los guantes de nitrilo y los lentes"
    # como "equipo de protección personal"; solo la cita trae las palabras que usa el SOP.
    epp = _paso_sop(
        numero=1,
        nombre="Ponerse guantes y lentes",
        descripcion="Colocarse los guantes de nitrilo y los lentes de seguridad.",
    )
    llave = _paso_sop(descripcion="Girar la llave de paso a la derecha hasta el tope.")
    paso = _paso_video(
        numero=1,
        nombre="Puesta de equipo de protección",
        descripcion="Colocarse el equipo de protección personal necesario.",
        cita="me pongo los guantes de nitrilo y los lentes de seguridad",
    )
    vectores_sop = embedder.embed([emp.texto_para_embeber(p) for p in (epp, llave)])

    def coseno(p: PasoVideo) -> np.ndarray:
        return emp.similitud(embedder.embed([emp.texto_para_embeber(p)]), vectores_sop)[0]

    sin_cita = coseno(paso.model_copy(update={"cita": ""}))
    con_cita = coseno(paso)
    assert con_cita[0] > sin_cita[0]
    assert con_cita.argmax() == 0  # el paso del SOP más parecido es el de EPP


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
    assert fusionado.cita == video[2].cita  # la cita del más parecido, sin unir
    assert fusionado.responsable == video[2].responsable
    assert registro[1].citas == [video[1].cita, video[2].cita]
    assert registro[1].responsables_distintos == []
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
    ],
)
def test_el_fusionado_une_la_evidencia(embedder, primero, segundo, esperado):
    desenroscar, sacar = _video("desenroscar", "sacar")
    video = [desenroscar.model_copy(update=primero), sacar.model_copy(update=segundo)]
    (paso,), (fusion,) = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.55)
    assert paso.model_dump(include=set(esperado)) == esperado
    assert fusion.citas == [p.cita for p in video]


@pytest.mark.parametrize(
    "claves",
    [
        ("cerrar", "desenroscar", "sacar", "colocar", "abrir"),
        ("desenroscar", "sacar"),
        ("sacar", "desenroscar"),
        ("desenroscar", "cerrar", "sacar"),
    ],
)
def test_la_cita_de_cada_paso_es_exactamente_una_de_las_originales(embedder, claves):
    video = _video(*claves)
    pasos, registro = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.55)
    citas_originales = {p.cita for p in video}
    for paso, fusion in zip(pasos, registro, strict=True):
        assert paso.cita in fusion.citas
        assert paso.cita in citas_originales


def test_la_cita_y_el_responsable_salen_del_original_mas_parecido(embedder):
    desenroscar, sacar = _video("desenroscar", "sacar")  # cosenos 0.64 y 0.77: gana "sacar"
    video = [
        desenroscar.model_copy(update={"responsable": "Supervisor"}),
        sacar.model_copy(update={"responsable": "Técnica"}),
    ]
    (paso,), (fusion,) = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.55)
    assert (paso.cita, paso.responsable) == (sacar.cita, "Técnica")
    assert fusion.citas == [desenroscar.cita, sacar.cita]


def test_en_empate_de_coseno_la_cita_es_la_del_primero(embedder):
    primero, segundo = _video("sacar", "sacar")  # mismo texto: mismo coseno
    # La cita también se vectoriza: la del segundo difiere solo en mayúsculas, que el
    # vectorizador falso ignora, así que el coseno sigue empatado.
    segundo = segundo.model_copy(update={"cita": primero.cita.upper(), "responsable": "Ayudante"})
    (paso,), (fusion,) = emp.fusionar(SOP_FILTRO, [primero, segundo], embedder, umbral=0.55)
    assert fusion.similitudes[0] == fusion.similitudes[1]
    assert (paso.cita, paso.responsable) == (primero.cita, primero.responsable)


@pytest.mark.parametrize(
    ("responsables", "distintos", "responsable"),
    [
        (("Técnica", "Técnica"), [], "Técnica"),
        (("Supervisor", "Técnica"), ["Supervisor", "Técnica"], "Técnica"),
        ((NO_IDENTIFICADO, "Técnica"), [NO_IDENTIFICADO, "Técnica"], "Técnica"),
        (("Técnica", NO_IDENTIFICADO), ["Técnica", NO_IDENTIFICADO], NO_IDENTIFICADO),
    ],
)
def test_responsables_distintos_quedan_en_el_registro(
    embedder, responsables, distintos, responsable
):
    video = [
        p.model_copy(update={"responsable": r})
        for p, r in zip(_video("desenroscar", "sacar"), responsables, strict=True)
    ]
    (paso,), (fusion,) = emp.fusionar(SOP_FILTRO, video, embedder, umbral=0.55)
    assert fusion.responsables_distintos == distintos
    assert paso.responsable == responsable  # el de "sacar", el más parecido; nunca concatenado
    assert "," not in paso.responsable


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


# ── asignar (algoritmo húngaro, ADR-012) ─────────────────────────────────────────────────────

# Los 6 pasos completos del SOP inventado del cambio de cartucho, como texto para embeber.
PASOS_CARTUCHO = [
    "Cerrar la llave de paso. Girar la llave de paso del agua hasta cerrarla.",
    "Liberar la presión. Abrir el grifo de la cocina hasta que deje de salir agua.",
    "Retirar el cartucho usado. Desenroscar el vaso del filtro y sacar el cartucho usado.",
    "Limpiar el vaso. Lavar el vaso con agua y revisar el empaque.",
    "Colocar el cartucho nuevo. Meter el cartucho nuevo en el vaso y enroscar el vaso.",
    "Abrir la llave y purgar. Abrir la llave de paso y dejar correr el agua un minuto.",
]
PASO_EXTRA = "Anotar la fecha. Escribir la fecha del cambio en la etiqueta del filtro."


def _matriz(embedder, sop: list[str], video: list[str]) -> np.ndarray:
    return emp.similitud(embedder.embed(sop), embedder.embed(video))


def _parejas(asignacion: emp.Asignacion) -> list[tuple[int, int]]:
    return [(p.indice_sop, p.indice_video) for p in asignacion.pares]


def test_seis_pasos_identicos_dan_la_diagonal(embedder):
    asignacion = emp.asignar(_matriz(embedder, PASOS_CARTUCHO, PASOS_CARTUCHO))
    assert _parejas(asignacion) == [(i, i) for i in range(6)]
    assert [p.similitud for p in asignacion.pares] == pytest.approx([1.0] * 6)
    assert asignacion.sop_sin_pareja == asignacion.video_sin_pareja == []


def test_dos_pasos_omitidos_quedan_sin_pareja_en_el_sop(embedder):
    video = [t for i, t in enumerate(PASOS_CARTUCHO) if i not in (1, 3)]
    asignacion = emp.asignar(_matriz(embedder, PASOS_CARTUCHO, video))
    assert _parejas(asignacion) == [(0, 0), (2, 1), (4, 2), (5, 3)]
    assert asignacion.sop_sin_pareja == [1, 3]
    assert asignacion.video_sin_pareja == []


def test_un_paso_extra_queda_sin_pareja_en_el_video(embedder):
    video = [*PASOS_CARTUCHO[:3], PASO_EXTRA, *PASOS_CARTUCHO[3:]]
    asignacion = emp.asignar(_matriz(embedder, PASOS_CARTUCHO, video))
    assert _parejas(asignacion) == [(0, 0), (1, 1), (2, 2), (3, 4), (4, 5), (5, 6)]
    assert asignacion.sop_sin_pareja == []
    assert asignacion.video_sin_pareja == [3]


def _voraz(s: np.ndarray) -> list[tuple[int, int]]:
    """Toma la pareja más parecida que quede libre, una y otra vez."""
    libres_sop, libres_video, parejas = set(range(s.shape[0])), set(range(s.shape[1])), []
    while libres_sop and libres_video:
        i, j = max(
            ((i, j) for i in libres_sop for j in libres_video), key=lambda par: s[par[0], par[1]]
        )
        parejas.append((i, j))
        libres_sop.remove(i)
        libres_video.remove(j)
    return sorted(parejas)


def test_el_hungaro_acierta_donde_el_voraz_falla():
    """El SOP tiene "Cerrar la llave de paso" (fila 0) y "Cerrar la llave del filtro" (fila 1).
    En el video, el paso 0 ("Cierro la llave") se parece a los dos (0.90 y 0.85), pero el paso 1
    ("Cierro la llave de paso del agua") solo al primero (0.85; con el segundo, 0.20). La fila 2
    ("Purgar") empareja sin ambigüedad con el paso 2 (0.80).

    El voraz toma primero el 0.90 (fila 0 con paso 0) y deja la fila 1 con el paso 1 a 0.20:
    total 1.90, y bajo el umbral de 0.55 eso sería un *Falta* y un *Sobra* falsos. El húngaro
    cruza las dos primeras parejas (0.85 + 0.85) y suma 2.50: las tres parejas pasan el umbral.
    """
    s = np.array(
        [
            [0.90, 0.85, 0.10],
            [0.85, 0.20, 0.10],
            [0.10, 0.10, 0.80],
        ]
    )
    voraz = _voraz(s)
    asignacion = emp.asignar(s)
    assert voraz == [(0, 0), (1, 1), (2, 2)]
    assert _parejas(asignacion) == [(0, 1), (1, 0), (2, 2)]
    assert sum(s[i, j] for i, j in voraz) == pytest.approx(1.90)
    assert sum(p.similitud for p in asignacion.pares) == pytest.approx(2.50)
    assert all(p.similitud >= 0.55 for p in asignacion.pares)


def test_asignar_es_determinista(embedder):
    rng = np.random.default_rng(7)
    s = np.round(rng.uniform(-1, 1, size=(7, 5)), 1)  # redondeada: con muchos empates
    assert emp.asignar(s) == emp.asignar(s.copy())
    video = [*PASOS_CARTUCHO[:3], PASO_EXTRA, *PASOS_CARTUCHO[3:]]
    m = _matriz(embedder, PASOS_CARTUCHO, video)
    assert emp.asignar(m) == emp.asignar(m)


@pytest.mark.parametrize(
    ("s", "esperado"),
    [
        (np.ones((2, 2)), [(0, 0), (1, 1)]),
        (np.full((3, 3), 0.7), [(0, 0), (1, 1), (2, 2)]),
        (np.full((2, 4), 0.6), [(0, 0), (1, 1)]),
        (np.full((4, 2), 0.6), [(0, 0), (1, 1)]),
        # Un paso del SOP repetido (filas 0 y 2 iguales) y dos pasos del video iguales: gana
        # la asignación que no cruza el orden.
        (np.array([[0.9, 0.2, 0.9], [0.2, 0.8, 0.2], [0.9, 0.2, 0.9]]), [(0, 0), (1, 1), (2, 2)]),
    ],
)
def test_en_empate_gana_la_asignacion_que_respeta_el_orden(s, esperado):
    assert _parejas(emp.asignar(s)) == esperado


@pytest.mark.parametrize(
    ("s", "esperado"),
    [
        # Filas 0 y 1 iguales (un paso del SOP repetido): scipy solo las cruza.
        (
            [
                [0.2, 0.9, 0.2, 0.9],
                [0.2, 0.9, 0.2, 0.9],
                [0.2, 0.9, 0.9, 0.9],
                [0.2, 0.9, 0.9, 0.9],
            ],
            [(0, 0), (1, 1), (2, 2), (3, 3)],
        ),
        # La fila 1 empata entre los pasos 0 y 1 del video: gana el más cercano en posición.
        ([[0.2, 0.2, 0.9], [0.9, 0.9, 0.2]], [(0, 2), (1, 1)]),
    ],
)
def test_el_desempate_decide_donde_scipy_solo_cruzaria_el_orden(s, esperado):
    s = np.array(s)
    sop, video = linear_sum_assignment(s, maximize=True)
    sin_desempate = list(zip(sop.tolist(), video.tolist(), strict=True))
    asignacion = emp.asignar(s)
    assert sin_desempate != esperado  # el caso de verdad depende del desempate
    assert _parejas(asignacion) == esperado
    assert sum(p.similitud for p in asignacion.pares) == pytest.approx(
        sum(s[i, j] for i, j in sin_desempate)
    )


def test_el_desempate_no_le_gana_a_una_diferencia_real_de_similitud():
    # Cruzar suma 1.2 + 0.0000020 más que no cruzar: gana cruzar aunque rompa el orden.
    s = np.array([[0.5, 0.600002], [0.6, 0.5]])
    assert _parejas(emp.asignar(s)) == [(0, 1), (1, 0)]


def test_la_similitud_del_par_es_la_de_la_matriz_sin_redondear():
    s = np.array([[0.123456789, -0.5], [-0.5, 0.987654321]])
    assert [p.similitud for p in emp.asignar(s).pares] == [0.123456789, 0.987654321]


@pytest.mark.parametrize(("m", "n"), [(0, 3), (3, 0), (0, 0)])
def test_asignar_sin_pasos_de_un_lado_deja_todo_sin_pareja(m, n):
    assert emp.asignar(np.zeros((m, n))) == emp.Asignacion([], list(range(m)), list(range(n)))


@pytest.mark.parametrize(
    "matriz",
    [np.ones(3), np.ones((2, 2, 2)), np.array([[0.5, np.nan]]), np.array([[1.5, 0.2]])],
    ids=["1d", "3d", "nan", "fuera_de_rango"],
)
def test_asignar_rechaza_matrices_invalidas(matriz):
    with pytest.raises(ValueError):
        emp.asignar(matriz)


# ── clasificar (cascada, ADR-012) ────────────────────────────────────────────────────────────


@pytest.fixture
def umbrales(monkeypatch):
    """Fija UMBRAL_BAJO, UMBRAL_ALTO y UMBRAL_FUSION (por defecto 0.55, 0.75 y 0.55, sin
    importar el `.env`)."""

    def fijar(bajo: float, alto: float, fusion: float = 0.55) -> None:
        monkeypatch.setenv("UMBRAL_BAJO", str(bajo))
        monkeypatch.setenv("UMBRAL_ALTO", str(alto))
        monkeypatch.setenv("UMBRAL_FUSION", str(fusion))
        config.get_settings.cache_clear()

    fijar(0.55, 0.75)
    yield fijar
    config.get_settings.cache_clear()


def _sop_n(m: int) -> list[PasoSOP]:
    return [_paso_sop(numero=i, nombre=f"Paso {i} del SOP") for i in range(1, m + 1)]


def _video_n(n: int, **cambios: Any) -> list[PasoVideo]:
    """Pasos del video inventados: el paso j (desde 0) empieza en 10j + 3.5 s."""
    return [
        _paso_video(
            numero=j + 1,
            t_inicio=10.0 * j + 3.5,
            t_fin=10.0 * j + 9,
            cita=f"Cita del paso {j + 1}",
            **cambios,
        )
        for j in range(n)
    ]


def _un_par(similitud: float) -> emp.Asignacion:
    return emp.Asignacion([Par(indice_sop=0, indice_video=0, similitud=similitud)], [], [])


@pytest.mark.parametrize(
    ("similitud", "estado"), [(0.55, "zona_gris"), (0.749, "zona_gris"), (0.75, "Cumple")]
)
def test_par_en_el_borde_de_los_umbrales(umbrales, similitud, estado):
    video = _video_n(1, confianza="media")
    pasos = emp.clasificar(_un_par(similitud), _sop_n(1), video).pasos
    assert pasos == [
        ResultadoPaso(
            estado=estado,
            indice_sop=0,
            indice_video=0,
            similitud=similitud,
            t_inicio=video[0].t_inicio,
            cita=video[0].cita,
            confianza="media",
        )
    ]


def test_par_bajo_el_umbral_se_rompe_en_falta_y_sobra(umbrales):
    video = _video_n(1)
    clasificacion = emp.clasificar(_un_par(0.549), _sop_n(1), video)
    assert clasificacion.pasos == [
        ResultadoPaso(estado="Falta", indice_sop=0),
        ResultadoPaso(
            estado="Sobra",
            indice_video=0,
            t_inicio=video[0].t_inicio,
            cita=video[0].cita,
            confianza="alta",
        ),
    ]
    # El par roto cuenta como par evaluado, pero no va al LLM.
    assert (clasificacion.resumen.pares, clasificacion.resumen.pares_llm) == (1, 0)


def test_paso_del_sop_sin_pareja_falta(umbrales):
    clasificacion = emp.clasificar(emp.Asignacion([], [0], []), _sop_n(1), [])
    (falta,) = clasificacion.pasos
    assert falta == ResultadoPaso(estado="Falta", indice_sop=0)
    assert (falta.indice_video, falta.similitud, falta.t_inicio, falta.cita) == (
        None,
        None,
        None,
        "",
    )
    assert falta.confianza is None


@pytest.mark.parametrize(
    ("cita", "confianza"),
    [("Aquí anoto la fecha en la etiqueta", "media"), ("", "baja"), ("   ", "baja")],
    ids=["con_cita", "sin_cita", "cita_en_blanco"],
)
def test_paso_del_video_sin_pareja_sobra(umbrales, cita, confianza):
    video = [_paso_video(numero=1, t_inicio=72.25, t_fin=80.0, cita=cita, confianza="media")]
    (sobra,) = emp.clasificar(emp.Asignacion([], [], [0]), [], video).pasos
    assert sobra == ResultadoPaso(
        estado="Sobra", indice_video=0, t_inicio=72.25, cita=cita, confianza=confianza
    )


def test_cambiar_los_umbrales_por_entorno_cambia_la_clasificacion(umbrales):
    sop, video, asignacion = _sop_n(1), _video_n(1), _un_par(0.6)

    def estados() -> list[str]:
        return [p.estado for p in emp.clasificar(asignacion, sop, video).pasos]

    assert estados() == ["zona_gris"]
    umbrales(0.65, 0.9)
    assert estados() == ["Falta", "Sobra"]
    umbrales(0.3, 0.6)
    assert estados() == ["Cumple"]
    umbrales(0.6, 0.6)  # umbrales iguales: no hay zona gris
    assert estados() == ["Cumple"]


def test_clasificar_de_punta_a_punta_desde_una_matriz(umbrales):
    """4 pasos del SOP y 5 del video. El húngaro forma la diagonal y el paso 4 del video queda
    sin pareja; la clasificación rompe el par (2, 2) por similitud baja."""
    s = np.array(
        [
            [0.92, 0.10, 0.05, 0.00, 0.10],
            [0.10, 0.62, 0.10, 0.05, 0.00],
            [0.05, 0.10, 0.40, 0.10, 0.05],
            [0.00, 0.05, 0.10, 0.80, 0.20],
        ]
    )
    video = _video_n(5)
    video[4] = video[4].model_copy(update={"cita": ""})
    asignacion = emp.asignar(s)
    assert _parejas(asignacion) == [(0, 0), (1, 1), (2, 2), (3, 3)]

    clasificacion = emp.clasificar(asignacion, _sop_n(4), video)

    estados = [(p.estado, p.indice_sop, p.indice_video) for p in clasificacion.pasos]
    assert estados == [
        ("Cumple", 0, 0),
        ("zona_gris", 1, 1),
        ("Falta", 2, None),
        ("Cumple", 3, 3),
        ("Sobra", None, 2),
        ("Sobra", None, 4),
    ]
    assert [p.similitud for p in clasificacion.pasos] == [0.92, 0.62, None, 0.80, None, None]
    # Regla 4: cada tiempo y cada cita es la de un paso del video.
    for p in clasificacion.pasos:
        if p.indice_video is not None:
            origen = video[p.indice_video]
            assert (p.t_inicio, p.cita) == (origen.t_inicio, origen.cita)
    assert clasificacion.pasos[-1].confianza == "baja"  # Sobra sin cita
    assert clasificacion.resumen.conteo == {
        "Cumple": 2,
        "Parcial": 0,
        "Falta": 1,
        "Sobra": 2,
        "zona_gris": 1,
    }
    assert (clasificacion.resumen.pares, clasificacion.resumen.pares_llm) == (4, 1)
    assert clasificacion.resumen.pct_pares_llm == pytest.approx(25.0)


def test_clasificar_el_texto_identico_da_cumple_y_el_extra_sobra(embedder, umbrales):
    video_textos = [*PASOS_CARTUCHO[:3], PASO_EXTRA, *PASOS_CARTUCHO[3:]]
    asignacion = emp.asignar(_matriz(embedder, PASOS_CARTUCHO, video_textos))
    clasificacion = emp.clasificar(asignacion, _sop_n(6), _video_n(7))
    assert [p.estado for p in clasificacion.pasos] == ["Cumple"] * 6 + ["Sobra"]
    assert clasificacion.pasos[-1].indice_video == 3
    assert clasificacion.resumen.pct_pares_llm == 0.0


def test_clasificar_sin_pasos_no_divide_entre_cero(umbrales):
    clasificacion = emp.clasificar(emp.Asignacion([], [], []), [], [])
    assert clasificacion.pasos == []
    assert clasificacion.resumen.pares == 0
    assert clasificacion.resumen.pct_pares_llm == 0.0


@pytest.mark.parametrize(
    "asignacion",
    [
        emp.Asignacion([Par(indice_sop=0, indice_video=5, similitud=0.9)], [1], []),
        emp.Asignacion([Par(indice_sop=0, indice_video=0, similitud=0.9)], [], []),
        emp.Asignacion([Par(indice_sop=0, indice_video=0, similitud=0.9)], [0, 1], []),
    ],
    ids=["indice_fuera_de_rango", "falta_un_paso_del_sop", "paso_repetido"],
)
def test_clasificar_rechaza_una_asignacion_de_otra_matriz(umbrales, asignacion):
    with pytest.raises(ValueError, match="asignación"):
        emp.clasificar(asignacion, _sop_n(2), _video_n(1))


# ── orden (ADR-012, punto 5) ─────────────────────────────────────────────────────────────────


def _en_orden_del_video(*orden_sop: int) -> Clasificacion:
    """Todos los pasos emparejados (Cumple): el paso j del video es el `orden_sop[j]` del SOP."""
    n = len(orden_sop)
    pares = sorted(
        (Par(indice_sop=i, indice_video=j, similitud=0.9) for j, i in enumerate(orden_sop)),
        key=lambda p: p.indice_sop,
    )
    return emp.clasificar(emp.Asignacion(pares, [], []), _sop_n(n), _video_n(n))


def _marcados(clasificacion: Clasificacion) -> list[tuple[int | None, int | None, int | None]]:
    """(indice_sop, posición esperada, posición observada) de los pasos fuera de orden."""
    return [
        (p.indice_sop, p.posicion_esperada, p.posicion_observada)
        for p in clasificacion.pasos
        if p.fuera_de_orden
    ]


def test_orden_correcto_no_marca_ninguno(umbrales):
    resultado = emp.orden(_en_orden_del_video(0, 1, 2, 3, 4))
    assert _marcados(resultado) == []
    assert resultado.resumen.fuera_de_orden == 0


def test_dos_pasos_invertidos_marcan_exactamente_uno(umbrales):
    clasificacion = _en_orden_del_video(0, 2, 1, 3)
    resultado = emp.orden(clasificacion)
    # Entre [0, 2, 3] y [0, 1, 3] se conserva la que deja fuera lo que llegó más tarde: el 1.
    assert _marcados(resultado) == [(1, 1, 2)]
    assert resultado.resumen.fuera_de_orden == 1
    assert resultado.resumen.conteo == clasificacion.resumen.conteo


def test_un_paso_movido_al_final_marca_solo_ese(umbrales):
    assert _marcados(emp.orden(_en_orden_del_video(0, 2, 3, 4, 1))) == [(1, 1, 4)]


def test_un_paso_movido_al_principio_marca_solo_ese(umbrales):
    assert _marcados(emp.orden(_en_orden_del_video(3, 0, 1, 2))) == [(3, 3, 0)]


def test_entre_subsecuencias_del_mismo_largo_quedan_fuera_las_mas_tardias(umbrales):
    # [1, 0, 3, 2] tiene cuatro de largo 2; se conserva la de las posiciones 0 y 2 (pasos 1 y 3).
    assert _marcados(emp.orden(_en_orden_del_video(1, 0, 3, 2))) == [(0, 0, 1), (2, 2, 3)]


def test_falta_y_sobra_no_participan_en_el_orden(umbrales):
    """SOP de 4 y video de 4: el paso 0 del SOP (zona gris) va en el video después del 1; el
    par (2, 3) se rompe, el paso 3 del SOP no tiene pareja y el paso 0 del video sobra."""
    asignacion = emp.Asignacion(
        [
            Par(indice_sop=0, indice_video=2, similitud=0.6),
            Par(indice_sop=1, indice_video=1, similitud=0.9),
            Par(indice_sop=2, indice_video=3, similitud=0.3),
        ],
        [3],
        [0],
    )
    resultado = emp.orden(emp.clasificar(asignacion, _sop_n(4), _video_n(4)))
    assert [(p.estado, p.fuera_de_orden) for p in resultado.pasos] == [
        ("zona_gris", True),
        ("Cumple", False),
        ("Falta", False),
        ("Falta", False),
        ("Sobra", False),
        ("Sobra", False),
    ]
    assert _marcados(resultado) == [(0, 0, 1)]
    for p in resultado.pasos:
        if p.estado in ("Falta", "Sobra"):
            assert (p.posicion_esperada, p.posicion_observada) == (None, None)


def test_empate_en_t_inicio_lo_decide_indice_video(umbrales):
    video = [_paso_video(numero=n, t_inicio=5.0, t_fin=9.0, cita=f"Cita {n}") for n in (1, 2)]
    cruzados = emp.Asignacion(
        [
            Par(indice_sop=0, indice_video=1, similitud=0.9),
            Par(indice_sop=1, indice_video=0, similitud=0.9),
        ],
        [],
        [],
    )
    derechos = emp.Asignacion(
        [
            Par(indice_sop=0, indice_video=0, similitud=0.9),
            Par(indice_sop=1, indice_video=1, similitud=0.9),
        ],
        [],
        [],
    )
    assert _marcados(emp.orden(emp.clasificar(cruzados, _sop_n(2), video))) == [(0, 0, 1)]
    assert _marcados(emp.orden(emp.clasificar(derechos, _sop_n(2), video))) == []


def test_orden_es_determinista_y_no_modifica_la_entrada(umbrales):
    clasificacion = _en_orden_del_video(2, 0, 3, 1, 4)
    antes = clasificacion.model_dump()
    resultado = emp.orden(clasificacion)
    assert resultado == emp.orden(clasificacion)
    assert emp.orden(resultado) == resultado  # recalcula la marca desde cero
    assert resultado is not clasificacion
    assert clasificacion.model_dump() == antes
    assert [(p.estado, p.similitud) for p in resultado.pasos] == [
        (p.estado, p.similitud) for p in clasificacion.pasos
    ]


def _subsecuencias_maximas(secuencia: list[int]) -> list[tuple[int, ...]]:
    """Todas las subsecuencias estrictamente crecientes de largo máximo (fuerza bruta)."""
    for largo in range(len(secuencia), -1, -1):
        crecientes = [
            posiciones
            for posiciones in combinations(range(len(secuencia)), largo)
            if all(secuencia[a] < secuencia[b] for a, b in pairwise(posiciones))
        ]
        if crecientes:
            return crecientes
    return [()]


def test_subsecuencia_creciente_es_la_mas_larga_y_la_menor_por_posicion():
    rng = np.random.default_rng(42)
    for n in [0, 1, 2, 3, 5, 8] * 20:
        secuencia = rng.permutation(n).tolist()
        assert tuple(emp._subsecuencia_creciente(secuencia)) == min(
            _subsecuencias_maximas(secuencia)
        ), secuencia


def test_subsecuencia_creciente_larga_coincide_con_la_programacion_dinamica():
    secuencia = np.random.default_rng(7).permutation(400).tolist()
    largo = [1] * len(secuencia)  # O(n²): largo de la más larga que termina en i
    for i in range(len(secuencia)):
        for j in range(i):
            if secuencia[j] < secuencia[i]:
                largo[i] = max(largo[i], largo[j] + 1)
    elegidas = emp._subsecuencia_creciente(secuencia)
    assert len(elegidas) == max(largo)
    assert all(secuencia[a] < secuencia[b] for a, b in pairwise(elegidas))


# ── emparejar: la cascada completa sin juez ──────────────────────────────────────────────────

SOP_CARTUCHO = SOP(
    titulo="Cambio del cartucho del filtro de agua",
    pasos=[
        _paso_sop(numero=i, nombre=nombre, descripcion=descripcion)
        for i, (nombre, descripcion) in enumerate(
            (texto.split(". ", 1) for texto in PASOS_CARTUCHO), start=1
        )
    ],
)
# Pasos del video sobre SOP_CARTUCHO: (nombre, descripción, cita).
VIDEO_CARTUCHO = {
    "cerrar": (
        "Cerrar la llave de paso",
        "Giro la llave de paso del agua hasta cerrarla.",
        "Primero cierro la llave de paso",
    ),
    "liberar": (
        "Liberar la presión",
        "Abro el grifo de la cocina hasta que deja de salir agua.",
        "Abro el grifo para sacar la presión",
    ),
    "retirar": (
        "Retirar el cartucho usado",
        "Desenrosco el vaso del filtro y saco el cartucho usado.",
        "Desenrosco el vaso y saco el cartucho",
    ),
    "desenroscar": (
        "Desenroscar el vaso del filtro",
        "Desenroscar el vaso del filtro para sacar el cartucho.",
        "Ahora desenrosco el vaso del filtro",
    ),
    "sacar": (
        "Sacar el cartucho usado",
        "Sacar el cartucho usado del vaso del filtro.",
        "Saco el cartucho usado del vaso",
    ),
    "limpiar": (
        "Limpiar el vaso",
        "Lavo el vaso con agua y reviso el empaque.",
        "Lavo el vaso y reviso el empaque",
    ),
    "carcasa": (
        "Limpiar la carcasa",
        "Pasar un trapo seco por la carcasa exterior hasta quitar el polvo.",
        "Le paso un trapo a la carcasa",
    ),
    "colocar": (
        "Colocar el cartucho nuevo",
        "Meto el cartucho nuevo en el vaso y enrosco el vaso.",
        "Meto el cartucho nuevo",
    ),
    "abrir": (
        "Abrir la llave y purgar",
        "Abro la llave de paso y dejo correr el agua un minuto.",
        "Abro la llave y dejo correr el agua",
    ),
}
# Video B del plan (§7): omite los pasos 2 y 6, agrega "limpiar la carcasa" y parte el 3 en dos.
VIDEO_B = ("cerrar", "desenroscar", "sacar", "limpiar", "carcasa", "colocar")
# Video C reducido: solo las inversiones, dos pares separados (2↔3 y 5↔6), como se graba C para
# dar los 2 *Fuera de orden* de la sección 14 del documento (cada inversión marca un paso).
VIDEO_C = ("cerrar", "retirar", "liberar", "limpiar", "abrir", "colocar")
# (indice_sop, posición esperada, posición observada): queda marcado el que llegó tarde de cada
# par, "Liberar la presión" y "Colocar el cartucho nuevo".
MARCADOS_C = [(1, 1, 2), (4, 4, 5)]


def _video_cartucho(*claves: str) -> list[PasoVideo]:
    """Pasos del video en el orden dado: el paso n va del segundo 10n al 10n + 8."""
    return [
        _paso_video(
            numero=n,
            nombre=VIDEO_CARTUCHO[clave][0],
            descripcion=VIDEO_CARTUCHO[clave][1],
            cita=VIDEO_CARTUCHO[clave][2],
            t_inicio=10.0 * n,
            t_fin=10.0 * n + 8,
        )
        for n, clave in enumerate(claves, start=1)
    ]


def test_video_b_da_dos_falta_un_sobra_y_una_fusion(embedder, umbrales):
    video = _video_cartucho(*VIDEO_B)
    resultado = emp.emparejar(SOP_CARTUCHO, video, embedder)
    clasificacion = resultado.clasificacion

    assert [f.originales for f in resultado.fusiones] == [[1], [2, 3], [4], [5], [6]]
    assert sum(len(f.originales) > 1 for f in resultado.fusiones) == 1
    assert resultado.fusiones[1].paso_sop == 3
    assert clasificacion.resumen.conteo["Falta"] == 2
    assert clasificacion.resumen.conteo["Sobra"] == 1
    assert clasificacion.resumen.fuera_de_orden == 0
    assert [p.indice_sop for p in clasificacion.pasos if p.estado == "Falta"] == [1, 5]
    (sobra,) = [p for p in clasificacion.pasos if p.estado == "Sobra"]
    assert (sobra.t_inicio, sobra.cita) == (video[4].t_inicio, video[4].cita)  # la carcasa
    # El paso partido empieza donde empieza la primera mitad (regla 4).
    (retirar,) = [p for p in clasificacion.pasos if p.indice_sop == 2]
    assert retirar.t_inicio == video[1].t_inicio
    assert resultado.pasos_video[retirar.indice_video].t_fin == video[2].t_fin


def test_video_c_con_dos_inversiones_separadas_marca_dos_fuera_de_orden(embedder, umbrales):
    resultado = emp.emparejar(SOP_CARTUCHO, _video_cartucho(*VIDEO_C), embedder)
    clasificacion = resultado.clasificacion
    assert all(len(f.originales) == 1 for f in resultado.fusiones)
    assert clasificacion.resumen.conteo["Cumple"] == 6
    assert clasificacion.resumen.fuera_de_orden == 2
    assert _marcados(clasificacion) == MARCADOS_C


def test_emparejar_vectoriza_el_sop_una_sola_vez(embedder, falso, umbrales):
    emp.emparejar(SOP_CARTUCHO, _video_cartucho(*VIDEO_B), embedder)
    textos = [t for llamada in falso.llamadas for t in llamada]
    for paso in SOP_CARTUCHO.pasos:
        assert textos.count(emp.texto_para_embeber(paso)) == 1
    # Una llamada para fusionar (SOP + video) y otra para los pasos ya fusionados.
    assert len(falso.llamadas) == 2


def test_emparejar_sin_embedder_usa_el_del_proceso(monkeypatch, embedder, umbrales):
    monkeypatch.setattr(emp, "get_embedder", lambda: embedder)
    video = _video_cartucho(*VIDEO_C)
    assert emp.emparejar(SOP_CARTUCHO, video) == emp.emparejar(SOP_CARTUCHO, video, embedder)


def test_emparejar_sin_pasos_del_video_deja_todo_en_falta(embedder, cargas, umbrales):
    resultado = emp.emparejar(SOP_CARTUCHO, [], embedder)
    assert [p.estado for p in resultado.clasificacion.pasos] == ["Falta"] * 6
    assert (resultado.fusiones, resultado.pasos_video) == ([], [])
    assert cargas == []


def test_emparejar_es_determinista(embedder, umbrales):
    video = _video_cartucho(*VIDEO_B)
    assert emp.emparejar(SOP_CARTUCHO, video, embedder) == emp.emparejar(
        SOP_CARTUCHO, video, embedder
    )


def test_emparejador_minilm_cumple_la_interfaz(embedder, cargas, umbrales):
    emparejador: emp.Emparejador = emp.EmparejadorMiniLM(embedder)
    video = _video_cartucho(*VIDEO_C)
    assert emparejador.emparejar(SOP_CARTUCHO, video) == emp.emparejar(
        SOP_CARTUCHO, video, embedder
    )
    emp.EmparejadorMiniLM()  # sin embedder no carga nada al crearse
    assert len(cargas) == 1


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
    assert pasos[1].cita in (video[1].cita, video[2].cita)


@pytest.mark.lento
def test_minilm_real_la_cita_lleva_al_paso_de_epp():
    """Paso 2 del video A (ADR-012): sin la cita, 0.52 con "Ponerse guantes y lentes" (bajo
    UMBRAL_BAJO, Falta + Sobra); con la cita, 0.86."""
    from sopvid.lenguaje.sop_markdown import convertir_sop

    ruta = Path(__file__).parent / "fixtures" / "sop_filtro_agua.md"
    epp = convertir_sop(ruta.read_text("utf-8")).sop.pasos[0]
    paso = _paso_video(
        numero=2,
        nombre="Puesta de equipo de protección",
        descripcion=(
            "Colocarse el equipo de protección personal necesario antes de manipular el filtro."
        ),
        cita="me pongo los guantes de nitrilo y los lentes de seguridad",
    )
    e = emp.Embedder()
    sop = e.embed([emp.texto_para_embeber(epp)])
    sin_cita = paso.model_copy(update={"cita": "", "confianza": "baja"})
    antes = emp.similitud(e.embed([emp.texto_para_embeber(sin_cita)]), sop)[0, 0]
    despues = emp.similitud(e.embed([emp.texto_para_embeber(paso)]), sop)[0, 0]
    assert antes == pytest.approx(0.52, abs=0.01)
    assert despues == pytest.approx(0.86, abs=0.01)


@pytest.mark.lento
def test_minilm_real_empareja_el_video_c(umbrales):
    """Video C reducido con MiniLM real: todos Cumple, ninguna fusión, dos fuera de orden."""
    resultado = emp.emparejar(SOP_CARTUCHO, _video_cartucho(*VIDEO_C), emp.Embedder())
    clasificacion = resultado.clasificacion
    assert all(len(f.originales) == 1 for f in resultado.fusiones), resultado.fusiones
    assert clasificacion.resumen.conteo["Cumple"] == 6, clasificacion.resumen
    assert clasificacion.resumen.fuera_de_orden == 2
    assert _marcados(clasificacion) == MARCADOS_C
