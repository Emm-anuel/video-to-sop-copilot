"""Rescate de un Falta en los fragmentos contiguos del video (ADR-022), sin LLM ni MiniLM.

Un vectorizador por palabras clave reproduce el mecanismo real: Gemma parte un paso en
fragmentos que, cada uno, se parecen poco al paso del SOP (coseno < `UMBRAL_FUSION`, así que la
fusión no los une), pero unidos se parecen mucho. Un juez guionado decide por el contenido de la
narración. Los pasos son inventados (nada del cliente).
"""

from pathlib import Path

import numpy as np
import pytest

from sopvid.contrato import (
    SOP,
    FilaReporte,
    Fusion,
    Juicio,
    PasoSOP,
    PasoVideo,
    ResultadoEmparejamiento,
    Segmento,
)
from sopvid.lenguaje import emparejamiento as emp
from sopvid.lenguaje.reporte import porcentaje
from sopvid.texto import comparable

# Una dimensión por palabra clave (por raíz); la última evita vectores en cero.
CLAVES = ("guante", "valvul", "llave", "aire", "fuga", "papel", "mesa")


class VectorizadorClaves:
    """Vector 0/1 por palabra clave presente en el texto (sin acentos)."""

    def encode(self, sentences: list[str], **kwargs: object) -> np.ndarray:
        x = np.zeros((len(sentences), emp.DIMENSION))
        for i, texto in enumerate(sentences):
            normal = comparable(texto)
            for k, clave in enumerate(CLAVES):
                x[i, k] = 1.0 if clave in normal else 0.0
            x[i, len(CLAVES)] = 0.01
        return x


@pytest.fixture
def embedder(tmp_path: Path) -> emp.Embedder:
    vectorizador = VectorizadorClaves()
    return emp.Embedder("claves", tmp_path, cargador=lambda m, c: vectorizador)


SOP_TRES = SOP(
    titulo="Cambio de filtro",
    pasos=[
        PasoSOP(numero=1, nombre="Ponerse guantes", responsable="Operador"),
        PasoSOP(numero=2, nombre="Cerrar la valvula", responsable="Operador"),
        # Cuatro claves: un fragmento con una sola da 0.5; con fuga y papel, 0.71 (zona gris).
        PasoSOP(
            numero=3,
            nombre="Revisar fugas",
            descripcion="Abrir la llave, purgar el aire y revisar fugas con papel",
            responsable="Operador",
        ),
    ],
)

GUANTES = "Me pongo los guantes"
VALVULA = "Cierro la valvula"
LLAVE = "Abro la llave despacio"
AIRE = "Purgo el aire"
FUGAS = "Reviso fugas con papel"
MESA = "Limpio la mesa"


def video(*citas: str) -> tuple[list[PasoVideo], list[Segmento]]:
    """Un paso por cita (5 s, con 1 s de pausa) y su segmento con la misma frase."""
    pasos, segmentos = [], []
    for n, cita in enumerate(citas, start=1):
        t = (n - 1) * 6.0
        pasos.append(
            PasoVideo(
                numero=n,
                nombre=cita,
                descripcion=cita,
                responsable="Operador",
                t_inicio=t,
                t_fin=t + 5.0,
                cita=cita,
                fuente="audio",
                confianza="alta",
            )
        )
        segmentos.append(Segmento(id=n - 1, t_inicio=t, t_fin=t + 5.0, texto=cita))
    return pasos, segmentos


class JuezGuionado:
    """Decide por la narración: Cumple si están las tres acciones del paso 3, no_corresponde si
    no. `caido` responde con un respaldo de Ollama caído."""

    def __init__(self, *, rechazar_todo: bool = False, caido: bool = False) -> None:
        self.rechazar_todo = rechazar_todo
        self.caido = caido
        self.llamadas: list[tuple[int, str]] = []

    def juzgar(
        self, paso_sop: PasoSOP, paso_video: PasoVideo, similitud: float, narracion: str
    ) -> Juicio:
        self.llamadas.append((paso_sop.numero, narracion))
        if self.caido:
            return Juicio(
                origen="respaldo",
                similitud=similitud,
                prompt="juez_zona_gris_v1",
                intentos=1,
                motivo="llm_no_disponible",
            )
        completa = all(c in narracion for c in ("llave", "aire", "fugas"))
        veredicto = "Cumple" if completa and not self.rechazar_todo else "no_corresponde"
        return Juicio(
            origen="llm",
            veredicto=veredicto,
            justificacion="guionado",
            cita=narracion,
            similitud=similitud,
            prompt="juez_zona_gris_v1",
            intentos=1,
        )


def emparejar(citas: tuple[str, ...], embedder: emp.Embedder, juez: JuezGuionado):
    pasos, segmentos = video(*citas)
    return emp.emparejar(SOP_TRES, pasos, embedder, juez=juez, transcripcion=segmentos)


def fila_sop(r: ResultadoEmparejamiento, numero: int):
    return next(p for p in r.clasificacion.pasos if p.indice_sop == numero - 1)


def test_rescata_el_paso_partido_y_lo_confirma_el_juez(embedder: emp.Embedder) -> None:
    juez = JuezGuionado()
    r = emparejar((GUANTES, VALVULA, LLAVE, AIRE, FUGAS), embedder, juez)

    tres = fila_sop(r, 3)
    assert tres.estado == "Cumple"
    rescatado = r.pasos_video[tres.indice_video]
    # El paso rescatado une los tres fragmentos: del inicio del primero al fin del último.
    assert (rescatado.t_inicio, rescatado.t_fin) == (12.0, 29.0)
    fusion = r.fusiones[tres.indice_video]
    assert fusion.rescate is True and fusion.originales == [3, 4, 5] and fusion.paso_sop == 3
    assert tres.juicio is not None and tres.juicio.veredicto == "Cumple"
    assert tres.similitud == pytest.approx(1.0, abs=1e-3)
    # Los fragmentos ya no salen como Sobra; el porcentaje es 100.
    assert r.clasificacion.resumen.conteo["Sobra"] == 0
    assert porcentaje(r) == 100
    resumen = r.clasificacion.resumen
    assert resumen.rescatados == 1
    # El juez vio primero el fragmento de fugas (zona gris, lo rechazó) y luego la ventana
    # completa: dos llamadas, que cuentan en pares_llm y en los veredictos.
    assert [n for n, _ in juez.llamadas] == [3, 3]
    assert juez.llamadas[1][1] == f"{LLAVE} {AIRE} {FUGAS}"
    assert resumen.pares_llm == 2
    assert resumen.juez["no_corresponde"] == 1 and resumen.juez["Cumple"] == 1


def test_los_demas_juicios_se_conservan_sin_volver_a_juzgar(embedder: emp.Embedder) -> None:
    juez = JuezGuionado()
    r = emparejar((GUANTES, VALVULA, LLAVE, AIRE, FUGAS, MESA), embedder, juez)
    # Guantes y válvula, Cumple sin juez; el juez solo se llamó para el paso 3 (dos veces).
    assert [fila_sop(r, n).estado for n in (1, 2, 3)] == ["Cumple", "Cumple", "Cumple"]
    assert len(juez.llamadas) == 2
    assert fila_sop(r, 1).juicio is None
    # "Limpio la mesa", después del par rescatado, sigue como Sobra (cierre).
    sobras = [p for p in r.clasificacion.pasos if p.estado == "Sobra"]
    assert [r.pasos_video[p.indice_video].cita for p in sobras] == [MESA]


def test_una_ventana_bajo_umbral_alto_no_se_rescata_ni_va_al_juez(embedder: emp.Embedder) -> None:
    # Prueba adversaria: purga el aire y abre la llave, pero no revisa fugas. Unidos dan 0.71,
    # parecido pero bajo UMBRAL_ALTO: el paso sigue en Falta y no se le pregunta al juez.
    juez = JuezGuionado()
    r = emparejar((GUANTES, VALVULA, LLAVE, AIRE), embedder, juez)
    assert fila_sop(r, 3).estado == "Falta"
    assert juez.llamadas == []
    assert r.clasificacion.resumen.rescatados == 0
    assert not any(f.rescate for f in r.fusiones)


def test_si_el_juez_rechaza_la_ventana_sigue_en_falta(embedder: emp.Embedder) -> None:
    juez = JuezGuionado(rechazar_todo=True)
    r = emparejar((GUANTES, VALVULA, LLAVE, AIRE, FUGAS), embedder, juez)
    assert fila_sop(r, 3).estado == "Falta"
    resumen = r.clasificacion.resumen
    assert len(juez.llamadas) == 2  # el fragmento y la ventana
    assert resumen.rescatados == 0 and resumen.juez["no_corresponde"] == 2
    assert resumen.pares_llm == 2
    assert not any(f.rescate for f in r.fusiones)
    assert resumen.conteo["Sobra"] + resumen.marco_operador == 3  # los fragmentos siguen


def test_sin_anclas_no_se_busca(embedder: emp.Embedder) -> None:
    # Solo fragmentos sueltos del paso 3, ningún otro paso: nada que anclar.
    juez = JuezGuionado()
    r = emparejar((LLAVE, AIRE, MESA), embedder, juez)
    assert [fila_sop(r, n).estado for n in (1, 2, 3)] == ["Falta", "Falta", "Falta"]
    assert juez.llamadas == []
    assert r.clasificacion.resumen.rescatados == 0


def test_la_region_respeta_las_anclas(embedder: emp.Embedder) -> None:
    # Los fragmentos del paso 3 están antes del par del paso 2: fuera de su región (después del
    # paso 2). No se rescata con evidencia que va en otro lugar del video.
    juez = JuezGuionado()
    r = emparejar((GUANTES, LLAVE, AIRE, FUGAS, VALVULA), embedder, juez)
    tres = fila_sop(r, 3)
    assert tres.estado == "Falta"
    assert r.clasificacion.resumen.rescatados == 0
    assert len(juez.llamadas) == 1  # solo el fragmento de fugas, en la zona gris


def test_con_ollama_caido_el_rescate_queda_sin_revisar(embedder: emp.Embedder) -> None:
    juez = JuezGuionado(caido=True)
    r = emparejar((GUANTES, VALVULA, LLAVE, AIRE, FUGAS), embedder, juez)
    tres = fila_sop(r, 3)
    # El fragmento de fugas quedó sin revisar con el juez caído; no hay Falta que rescatar.
    assert tres.estado == "zona_gris"
    assert r.clasificacion.resumen.rescatados == 0


def test_el_rescate_sin_revisar_cuando_el_juez_se_cae_en_el_rescate(
    embedder: emp.Embedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    class JuezQueSeCae(JuezGuionado):
        def juzgar(self, paso_sop, paso_video, similitud, narracion):
            self.caido = len(self.llamadas) >= 1
            return super().juzgar(paso_sop, paso_video, similitud, narracion)

    juez = JuezQueSeCae()
    r = emparejar((GUANTES, VALVULA, LLAVE, AIRE, FUGAS), embedder, juez)
    tres = fila_sop(r, 3)
    assert tres.estado == "zona_gris"
    assert tres.juicio is not None and tres.juicio.motivo == "llm_no_disponible"
    assert r.fusiones[tres.indice_video].rescate is True
    resumen = r.clasificacion.resumen
    assert resumen.rescatados == 1 and resumen.juez["respaldo"] == resumen.conteo["zona_gris"] == 1


# ── Contrato ─────────────────────────────────────────────────────────────────────────────────


def test_fusion_y_fila_sin_rescate_por_defecto() -> None:
    fusion = Fusion(numero=1, originales=[1], paso_sop=1, citas=["x"], similitudes=[0.9])
    assert fusion.rescate is False
    assert FilaReporte(estado="Cumple").rescatado is False


def test_rescatado_solo_en_un_par() -> None:
    with pytest.raises(ValueError, match="rescate solo van en un par"):
        FilaReporte(estado="Sobra", rescatado=True)
    assert FilaReporte(estado="zona_gris", rescatado=True).rescatado


def test_el_resumen_cuadra_con_las_fusiones_rescatadas(embedder: emp.Embedder) -> None:
    r = emparejar((GUANTES, VALVULA, LLAVE, AIRE, FUGAS), embedder, JuezGuionado())
    datos = r.model_dump()
    datos["fusiones"][-1]["rescate"] = False
    with pytest.raises(ValueError, match="rescatados"):
        ResultadoEmparejamiento.model_validate(datos)
