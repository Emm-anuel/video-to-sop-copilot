"""Roles del SOP y responsable por paso (RF-15, SOP V1.0 §5.4; ADR-020), sin LLM.

Por defecto MiniLM se sustituye por una bolsa de palabras (`dobles.VectorizadorPalabras`): dos
núcleos distintos ("técnico", "supervisor") no comparten palabras y quedan en 0, y la forma base
une "técnico" con "técnica" sin modelo. Las pruebas "lento" repiten la regla de roles con MiniLM
real (`pytest -m lento`).

Personas, nombres y frases son INVENTADOS por el equipo (CLAUDE.md §2.1).
"""

from pathlib import Path

import pytest

from dobles import _segmento, embedder_palabras
from sopvid.contrato import (
    ESTADOS,
    SOP,
    Clasificacion,
    Contexto,
    Elemento,
    Fusion,
    PasoSOP,
    PasoVideo,
    Persona,
    ResultadoEmparejamiento,
    ResultadoPaso,
    ResumenClasificacion,
    RolReporte,
)
from sopvid.lenguaje import personas as per
from sopvid.lenguaje.emparejamiento import Embedder
from sopvid.plataforma.config import Settings

TECNICO = "Técnico de mantenimiento"
SUPERVISOR = "Supervisor de turno"


@pytest.fixture
def comparador(tmp_path: Path) -> per.ComparadorRoles:
    return per.ComparadorRoles(embedder_palabras(tmp_path), Settings(_env_file=None))


# ── Cuándo dos roles coinciden ───────────────────────────────────────────────────────────────

CASOS_ROLES = [
    # Los cuatro casos de la decisión del 8 nov (ADR-020).
    ("técnico", "técnico de mantenimiento", True),  # uno sin complemento: basta el núcleo
    ("técnico de mantenimiento", "supervisor de mantenimiento", False),  # núcleos distintos
    ("ingeniera de calidad", "ingeniero de procesos", False),  # complementos distintos
    ("la supervisora", "supervisor de turno", True),  # artículo y género
    # Más casos generales.
    ("Técnico de mantenimiento", "técnica de mantenimiento", True),
    ("Supervisor de turno", "supervisor del turno matutino", True),  # complemento incluido
    ("Los técnicos de mantenimiento", "técnico de mantenimiento", True),  # plural
    ("Operador de llenadora", "técnico de mantenimiento", False),
]


@pytest.mark.parametrize(("a", "b", "esperado"), CASOS_ROLES)
def test_cuando_coinciden_dos_roles(
    comparador: per.ComparadorRoles, a: str, b: str, esperado: bool
) -> None:
    assert comparador.coinciden(a, b) is esperado
    assert comparador.coinciden(b, a) is esperado  # simétrico


def test_rol_vacio_no_se_compara(comparador: per.ComparadorRoles) -> None:
    assert comparador.comparar("el", TECNICO) is None
    assert comparador.comparar(None, TECNICO) is None
    assert comparador.comparar(TECNICO, "técnico de mantenimiento") == per.Comparacion(True, 1.0)


@pytest.mark.parametrize(
    ("palabra", "base"),
    [("técnico", "tecnic"), ("Técnica", "tecnic"), ("técnicos", "tecnic"),
     ("supervisora", "supervisor"), ("supervisores", "supervisor"), ("jefe", "jef"),
     ("jefa", "jef"), ("operadoras", "operador"), ("auxiliares", "auxiliar")],
)  # fmt: skip
def test_forma_base(palabra: str, base: str) -> None:
    assert per.forma_base(palabra) == base


def test_partir_rol() -> None:
    rol = per.partir_rol("La Supervisora del turno de noche")
    assert rol is not None
    assert (rol.nucleo, rol.nucleo_base) == ("supervisora", "supervisor")
    assert (rol.complemento, rol.complemento_base) == ("turno noche", {"turn", "noch"})
    assert per.partir_rol("técnico electricista").complemento == ""  # sin "de": sin complemento


# ── Roles del SOP entre las personas de la ficha ─────────────────────────────────────────────


def _persona(nombre: str, rol: str | None, participacion: str = "participa", t: float = 1.0,
             cita: str = "") -> Persona:  # fmt: skip
    return Persona(nombre=nombre, rol=rol, participacion=participacion, t=t, cita=cita)


def test_rol_presente_mencionado_y_ausente(comparador: per.ComparadorRoles) -> None:
    personas = [
        _persona("No identificado", "técnica de mantenimiento", t=2.0,
                 cita="soy técnica de mantenimiento y hoy cambio el filtro"),
        _persona("No identificado", "supervisor", "mencionado", t=40.0,
                 cita="si no cierra le aviso al supervisor"),
    ]  # fmt: skip
    roles = [Elemento(nombre=TECNICO), Elemento(nombre=SUPERVISOR), Elemento(nombre="Almacenista")]
    reporte = per.emparejar_roles(roles, personas, comparador=comparador)
    assert [(r.rol, r.estado, r.t) for r in reporte] == [
        (TECNICO, "presente", 2.0),
        (SUPERVISOR, "mencionado", 40.0),
        ("Almacenista", "ausente", None),
    ]
    presente = reporte[0]
    assert presente.persona == "técnica de mantenimiento"
    assert presente.cita == personas[0].cita and presente.confianza == "alta"
    assert reporte[2] == RolReporte(rol="Almacenista", estado="ausente")


def test_prefiere_a_quien_participa(comparador: per.ComparadorRoles) -> None:
    personas = [
        _persona("Beto", "técnico", "mencionado", t=1.0),
        _persona("Ana", "técnica de mantenimiento", t=5.0),
    ]
    [rol] = per.emparejar_roles([Elemento(nombre=TECNICO)], personas, comparador=comparador)
    assert (rol.estado, rol.persona, rol.t) == ("presente", "Ana (técnica de mantenimiento)", 5.0)


def test_persona_con_confianza_baja_cuenta_pero_el_rol_queda_bajo(
    comparador: per.ComparadorRoles,
) -> None:
    # El rol no aparece en su cita: lo infirió el LLM.
    inferida = _persona("No identificado", "técnico de mantenimiento", cita="ahora cierro la llave")
    [rol] = per.emparejar_roles([Elemento(nombre=TECNICO)], [inferida], comparador=comparador)
    assert (rol.estado, rol.confianza) == ("presente", "baja")
    de_fotograma = _persona("No identificado", "técnico de mantenimiento")  # sin cita
    assert per.confianza_del_rol(de_fotograma) == "media"


def test_con_pasos_segun_los_responsables_del_sop(comparador: per.ComparadorRoles) -> None:
    roles = [Elemento(nombre=TECNICO), Elemento(nombre=SUPERVISOR)]
    reporte = per.emparejar_roles(roles, [], comparador=comparador, responsables=[TECNICO])
    assert [(r.estado, r.con_pasos) for r in reporte] == [("ausente", True), ("ausente", False)]


def test_roles_del_sop_sin_seccion_de_roles() -> None:
    sop = SOP(
        titulo="Prueba",
        pasos=[
            PasoSOP(numero=1, nombre="Uno", responsable=TECNICO),
            PasoSOP(numero=2, nombre="Dos", responsable="técnico de mantenimiento"),
            PasoSOP(numero=3, nombre="Tres", responsable="No identificado"),
            PasoSOP(numero=4, nombre="Cuatro", responsable=SUPERVISOR),
        ],
    )
    assert [r.nombre for r in per.roles_del_sop(sop)] == [TECNICO, SUPERVISOR]


# ── Responsable por paso ─────────────────────────────────────────────────────────────────────

# Transcripción inventada: Ana narra en primera persona; en el segundo paso cuenta lo que hace
# Beto, en tercera persona.
SEGMENTOS = [
    _segmento(0, 0.0, 4.0, "Soy Ana, técnica de mantenimiento."),
    _segmento(1, 4.5, 9.0, "Cierro la llave de paso."),
    _segmento(2, 9.5, 14.0, "Beto retira la pieza del molde."),
    _segmento(3, 14.5, 19.0, "Coloco la pieza nueva y aprieto."),
]
ANA = _persona("Ana", "técnica de mantenimiento", t=0.0, cita="Soy Ana, técnica de mantenimiento")
BETO = _persona("Beto", "supervisor de turno", t=9.5, cita="Beto retira la pieza del molde")


def _paso(numero: int, segmento: int, responsable: str) -> PasoVideo:
    s = SEGMENTOS[segmento]
    return PasoVideo(numero=numero, nombre=f"Paso {numero}", descripcion="",
                     responsable=responsable, t_inicio=s.t_inicio, t_fin=s.t_fin,
                     cita=s.texto, fuente="audio", confianza="alta")  # fmt: skip


def _resultado(
    pasos: list[PasoVideo], fusiones: list[Fusion] | None = None
) -> ResultadoEmparejamiento:
    """Cada paso del video con el paso del SOP de su misma posición, como Cumple."""
    resultados = [
        ResultadoPaso(estado="Cumple", indice_sop=i, indice_video=i, similitud=0.9,
                      t_inicio=p.t_inicio, cita=p.cita, confianza="alta")
        for i, p in enumerate(pasos)
    ]  # fmt: skip
    conteo = dict.fromkeys(ESTADOS, 0)
    for r in resultados:
        conteo[r.estado] += 1
    return ResultadoEmparejamiento(
        clasificacion=Clasificacion(
            pasos=resultados,
            resumen=ResumenClasificacion(
                conteo=conteo, pares=len(pasos), pares_llm=0, pct_pares_llm=0.0
            ),
        ),  # fmt: skip
        fusiones=fusiones
        or [
            Fusion(
                numero=p.numero,
                originales=[p.numero],
                paso_sop=i + 1,
                citas=[p.cita],
                similitudes=[0.9],
            )
            for i, p in enumerate(pasos)
        ],  # fmt: skip
        pasos_video=pasos,
    )


def _sop(*responsables: str) -> SOP:
    return SOP(
        titulo="Cambio de la pieza",
        pasos=[PasoSOP(numero=i, nombre=f"Paso {i}", responsable=r)
               for i, r in enumerate(responsables, start=1)],
    )  # fmt: skip


def _estados(filas) -> list[tuple[str, str | None]]:
    return [(f.estado, f.observado) if f is not None else None for f in filas]


def test_un_solo_narrador_sin_nombre_nunca_da_distinto(comparador: per.ComparadorRoles) -> None:
    narrador = _persona("No identificado", "técnico de mantenimiento", t=0.0,
                        cita="soy técnico de mantenimiento")  # fmt: skip
    contexto = Contexto(personas=[narrador])
    genericos = ["el operador", "No identificado", "", TECNICO]
    pasos = [_paso(i + 1, i, r) for i, r in enumerate(genericos)]
    resultado = _resultado(pasos)

    mismo_rol = per.asignar_responsables(
        resultado, _sop(*[TECNICO] * 4), contexto, SEGMENTOS, comparador=comparador
    )
    assert {f.estado for f in mismo_rol} == {"coincide"}
    assert {f.observado for f in mismo_rol} == {"técnico de mantenimiento"}

    otro_rol = per.asignar_responsables(
        resultado, _sop(*[SUPERVISOR] * 4), contexto, SEGMENTOS, comparador=comparador
    )
    assert {f.estado for f in otro_rol} == {"no_identificado"}
    assert all("un solo narrador sin nombre" in f.nota for f in otro_rol)


def test_dos_personas_el_paso_en_tercera_persona_es_distinto(
    comparador: per.ComparadorRoles,
) -> None:
    contexto = Contexto(personas=[ANA, BETO])
    pasos = [_paso(1, 1, "Ana"), _paso(2, 2, ""), _paso(3, 3, "técnica de mantenimiento")]
    filas = per.asignar_responsables(
        _resultado(pasos), _sop(TECNICO, TECNICO, TECNICO), contexto, SEGMENTOS,
        comparador=comparador,
    )  # fmt: skip
    assert _estados(filas) == [
        ("coincide", "Ana (técnica de mantenimiento)"),
        ("distinto", "Beto (supervisor de turno)"),
        ("coincide", "Ana (técnica de mantenimiento)"),
    ]
    assert filas[1].nota.startswith("nombre en la narración del paso")
    assert filas[0].similitud == 1.0 and filas[1].similitud is not None


def test_paso_fusionado_toma_al_responsable_del_original_citado(
    comparador: per.ComparadorRoles,
) -> None:
    """Como en el video C: el original de Ana (el más parecido al paso del SOP, el que da la
    cita) se fusiona con un fragmento más largo en que se nombra a Beto. Cuenta Ana."""
    originales = [_paso(1, 1, "Ana"), _paso(2, 2, "Beto")]
    originales[1] = originales[1].model_copy(update={"t_fin": 19.0})  # Beto: más tiempo
    fusionado = originales[0].model_copy(update={"t_fin": 19.0})  # cita y nombre de Ana
    fusion = Fusion(numero=1, originales=[1, 2], paso_sop=1, citas=[p.cita for p in originales],
                    similitudes=[0.9, 0.6], responsables_distintos=["Ana", "Beto"])  # fmt: skip
    resultado = _resultado([fusionado], [fusion])
    contexto = Contexto(personas=[ANA, BETO])
    [fila] = per.asignar_responsables(
        resultado, _sop(TECNICO), contexto, SEGMENTOS, originales, comparador=comparador
    )
    assert (fila.estado, fila.observado) == ("coincide", "Ana (técnica de mantenimiento)")
    assert "paso fusionado con 2 responsables (Ana, Beto); se tomó el del original citado" in (
        fila.nota
    )
    # Con el responsable vacío, el nombre se busca solo en el tramo del original citado: "Beto"
    # se dice en el fragmento fusionado, pero no en el de Ana.
    sin_responsable = [p.model_copy(update={"responsable": ""}) for p in originales]
    vacio = resultado.model_copy(
        update={"pasos_video": [fusionado.model_copy(update={"responsable": ""})]}
    )
    [fila] = per.asignar_responsables(
        vacio, _sop(TECNICO), contexto, SEGMENTOS, sin_responsable, comparador=comparador
    )
    assert fila.estado != "distinto"


def test_falta_y_sobra_no_llevan_responsable(comparador: per.ComparadorRoles) -> None:
    pasos = [_paso(1, 1, "Ana"), _paso(2, 2, "Ana")]
    base = _resultado(pasos)
    cumple, _ = base.clasificacion.pasos
    resultados = [
        cumple,
        ResultadoPaso(estado="Falta", indice_sop=1),
        ResultadoPaso(estado="Sobra", indice_video=1, t_inicio=9.5, cita=pasos[1].cita,
                      confianza="alta"),
    ]  # fmt: skip
    conteo = dict.fromkeys(ESTADOS, 0) | {"Cumple": 1, "Falta": 1, "Sobra": 1}
    resultado = base.model_copy(
        update={
            "clasificacion": Clasificacion(
                pasos=resultados,
                resumen=ResumenClasificacion(conteo=conteo, pares=1, pares_llm=0,
                                             pct_pares_llm=0.0),
            )
        }
    )  # fmt: skip
    filas = per.asignar_responsables(
        resultado, _sop(TECNICO, TECNICO), Contexto(personas=[ANA]), SEGMENTOS,
        comparador=comparador,
    )  # fmt: skip
    assert filas[0] is not None and filas[1:] == [None, None]


def test_sin_ficha_el_rol_del_paso_basta_para_coincidir(comparador: per.ComparadorRoles) -> None:
    pasos = [_paso(1, 1, "Técnica de mantenimiento"), _paso(2, 2, ""), _paso(3, 3, "operador")]
    filas = per.asignar_responsables(
        _resultado(pasos), _sop(TECNICO, TECNICO, TECNICO), None, SEGMENTOS,
        comparador=comparador,
    )  # fmt: skip
    assert _estados(filas) == [
        ("coincide", "Técnica de mantenimiento"),
        ("no_identificado", None),
        ("no_identificado", None),  # un rol suelto que no coincide no es una persona
    ]


def test_nunca_inventa_un_nombre_que_no_esta_en_la_ficha(comparador: per.ComparadorRoles) -> None:
    # "Beto" se dice en la narración, pero la ficha solo tiene a Ana y a otra persona sin nombre.
    otra = _persona("No identificado", "supervisor de turno", t=3.0)
    filas = per.asignar_responsables(
        _resultado([_paso(1, 2, "")]), _sop(TECNICO), Contexto(personas=[ANA, otra]), SEGMENTOS,
        comparador=comparador,
    )  # fmt: skip
    assert _estados(filas) == [("no_identificado", None)]


def test_persona_sin_rol_queda_sin_identificar(comparador: per.ComparadorRoles) -> None:
    sin_rol = _persona("Beto", None, t=9.5)
    filas = per.asignar_responsables(
        _resultado([_paso(1, 2, "")]), _sop(TECNICO), Contexto(personas=[ANA, sin_rol]),
        SEGMENTOS, comparador=comparador,
    )  # fmt: skip
    assert _estados(filas) == [("no_identificado", None)]
    assert "la persona no tiene rol en la ficha" in filas[0].nota


def test_sop_sin_responsable(comparador: per.ComparadorRoles) -> None:
    [fila] = per.asignar_responsables(
        _resultado([_paso(1, 1, "Ana")]), _sop("No identificado"), Contexto(personas=[ANA]),
        SEGMENTOS, comparador=comparador,
    )  # fmt: skip
    assert (fila.estado, fila.nota) == ("no_identificado", "el SOP no indica responsable")


# ── MiniLM real (lento) ──────────────────────────────────────────────────────────────────────


@pytest.mark.lento
@pytest.mark.parametrize(("a", "b", "esperado"), CASOS_ROLES)
def test_minilm_cuando_coinciden_dos_roles(a: str, b: str, esperado: bool) -> None:
    comparador = per.ComparadorRoles(Embedder(), Settings(_env_file=None))
    comparacion = comparador.comparar(a, b)
    assert comparacion is not None
    print(f"{a!r} ~ {b!r}: {comparacion}")
    assert comparacion.coinciden is esperado


# ── Contrato: personas_con_diferencias (ADR-020) ─────────────────────────────────────────────


def test_solo_un_rol_ausente_con_pasos_cuenta_como_diferencia() -> None:
    import json

    from pydantic import ValidationError

    from sopvid.contrato import ReporteValidacion

    ruta = Path(__file__).parent / "fixtures" / "reporte_ejemplo.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    de_apoyo = {"rol": "Jefe de almacén", "estado": "ausente", "con_pasos": False}
    datos["roles"] = [*datos["roles"], de_apoyo]
    ReporteValidacion.model_validate(datos)  # el conteo no cambia
    datos["roles"][-1]["con_pasos"] = True
    with pytest.raises(ValidationError, match="el conteo no coincide"):
        ReporteValidacion.model_validate(datos)
