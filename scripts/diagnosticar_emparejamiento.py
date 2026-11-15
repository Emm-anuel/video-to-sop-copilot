"""Diagnóstico de los Sobra del emparejamiento (ADR-012, ADR-013) en videos anotados a mano.

Corre `emparejar` dos veces por video, sin juez y con `JuezGemma`, sobre los pasos del video ya
extraídos (no vuelve a segmentar, para que el diagnóstico sea reproducible). Para cada corrida da
el conteo por estado, el % de cumplimiento con su semáforo, los pares que fueron al juez y
`segundos_juez`. Para cada Sobra explica de dónde sale: el paso del SOP más parecido y quién lo
tiene, si la fusión (ADR-013) lo consideró y por qué no lo unió, si el juez rompió el par y en
qué tramo de la anotación manual cae (intro, cierre o un paso del SOP).

Uso, desde la raíz del repo y con el entorno activado:

    python scripts/diagnosticar_emparejamiento.py \\
        --sop tests/fixtures/sop_filtro_agua.md --anotacion media/anotacion_ab.json \\
        video_a=media/video_a_v2 video_b=media/video_b_v2

Cada carpeta trae `analisis.json` (el `Analisis` del pipeline) y `resultado.json` con los pasos
del video en "segmentacion". La clave antes del "=" es la de la anotación. `--sin-juez` salta la
corrida con Gemma 4.

Salida: data/interim/diagnostico/<clave>.md y <clave>.json (carpeta ignorada por git). No
modifica código de producción ni datos de entrada.

`--variantes-texto` (#11) compara variantes del texto vectorizado del paso del video con las
segmentaciones guardadas en la base (Postgres arriba; sin Gemma). Cada posicional es
`nombre=VIDEO_ID:SOP:CLAVE`, con SOP = `ref` (el de `--sop`) o `SOP_ID@CLAVE_ORIGEN` (un SOP
generado y la clave de la anotación del video desde el que se generó):

    python scripts/diagnosticar_emparejamiento.py --variantes-texto \\
        --sop tests/fixtures/sop_filtro_agua.md --anotacion media/anotacion_ab.json \\
        --citas-corregidas tests/fixtures/emparejamiento_e.json \\
        --docs docs/adr/datos/s6/emparejamiento \\
        a8275=8275:ref:video_a e8659-8158=8659:8158@video_e:video_e

Salida: data/interim/diagnostico/variantes_texto.{md,json} y, con `--docs`, una copia ahí.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from sopvid.contrato import (
    SOP,
    Analisis,
    PasoSOP,
    PasoVideo,
    ResultadoEmparejamiento,
    ResultadoPaso,
)
from sopvid.lenguaje import emparejamiento as emp
from sopvid.lenguaje.juez import JuezGemma, narracion_de
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.reporte import porcentaje, semaforo
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.plataforma.config import PROJECT_ROOT, get_settings

SALIDA = PROJECT_ROOT / "data" / "interim" / "diagnostico"


# ── Tramos de la anotación manual ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tramo:
    inicio: float
    fin: float
    nombre: str
    sop: int | str | None  # número del paso del SOP; None en Intro y Cierre; "extra" en B

    @property
    def etiqueta(self) -> str:
        if self.sop is None:
            return self.nombre  # Intro o Cierre
        return f"{self.nombre} (SOP {self.sop})" if isinstance(self.sop, int) else self.nombre


def tramos_de(anotacion: dict[str, Any], duracion: float) -> list[Tramo]:
    pasos = anotacion["pasos"]
    fines = [p["t"] for p in pasos[1:]] + [duracion]
    return [Tramo(p["t"], fin, p["nombre"], p["sop"]) for p, fin in zip(pasos, fines, strict=True)]


def tramo_en(t: float, tramos: list[Tramo]) -> Tramo:
    """El tramo que contiene `t` (antes del primero, el primero)."""
    dentro = [tr for tr in tramos if tr.inicio <= t]
    return dentro[-1] if dentro else tramos[0]


def tramo_mayor(paso: PasoVideo, tramos: list[Tramo]) -> Tramo:
    """El tramo con el que más se encima el paso."""
    return max(tramos, key=lambda tr: min(tr.fin, paso.t_fin) - max(tr.inicio, paso.t_inicio))


# ── Diagnóstico de un video ──────────────────────────────────────────────────────────────────


def mmss(t: float | None) -> str:
    return "–" if t is None else f"{int(t // 60):02d}:{t % 60:04.1f}"


@dataclass
class Corrida:
    nombre: str
    resultado: ResultadoEmparejamiento
    asignacion: emp.Asignacion
    matriz: np.ndarray  # SOP × pasos fusionados (la que usa `asignar`)


def correr(
    sop: SOP,
    pasos: list[PasoVideo],
    analisis: Analisis,
    embedder: emp.Embedder,
    juez: JuezGemma | None,
) -> Corrida:
    resultado = emp.emparejar(
        sop, pasos, embedder, juez=juez, transcripcion=analisis.transcripcion if juez else ()
    )
    fusionados = resultado.pasos_video
    vectores_sop = embedder.embed([emp.texto_para_embeber(p) for p in sop.pasos])
    vectores_video = embedder.embed([emp.texto_para_embeber(p) for p in fusionados])
    matriz = emp.similitud(vectores_sop, vectores_video)
    return Corrida("con juez" if juez else "sin juez", resultado, emp.asignar(matriz), matriz)


def quien_tiene(resultado: ResultadoEmparejamiento, indice_sop: int) -> str:
    paso = next(p for p in resultado.clasificacion.pasos if p.indice_sop == indice_sop)
    if paso.indice_video is None:
        return f"nadie ({paso.estado})"
    numero = resultado.pasos_video[paso.indice_video].numero
    originales = _rango(resultado.fusiones[paso.indice_video].originales)
    marca = ", fuera de orden" if paso.fuera_de_orden else ""
    return f"video {numero} (orig. {originales}; {paso.estado}, {paso.similitud:.2f}{marca})"


def _rango(numeros: list[int]) -> str:
    return str(numeros[0]) if len(numeros) == 1 else f"{numeros[0]}–{numeros[-1]}"


def por_que_sobra(corrida: Corrida, sobra: ResultadoPaso, umbral_bajo: float) -> str:
    j = sobra.indice_video
    if sobra.juicio is not None:
        return f"el juez rompió el par (no_corresponde, coseno {sobra.juicio.similitud:.2f})"
    par = next((p for p in corrida.asignacion.pares if p.indice_video == j), None)
    if par is None:
        return "sin pareja en el húngaro (más pasos del video que del SOP)"
    if par.similitud < umbral_bajo:
        return (
            f"par roto por coseno: SOP {par.indice_sop + 1} con {par.similitud:.2f} < {umbral_bajo}"
        )
    return "?"


def fusion_de(
    corrida: Corrida,
    j: int,
    pasos: list[PasoVideo],
    sop_orig: np.ndarray,
    umbral: float,
) -> tuple[str, str]:
    """(consecutivo, fusión) para el paso fusionado `j`.

    Consecutivo: si el paso anterior o el siguiente (ya fusionados) tienen el mismo mejor paso
    del SOP. Fusión: con los pasos originales vecinos, si la regla de ADR-013 los habría unido
    (mismo mejor paso del SOP y los dos con coseno ≥ umbral) y, si no, por qué.
    """
    fusionados = corrida.resultado.pasos_video
    mejor_f = corrida.matriz.argmax(axis=0)  # mejor SOP por paso fusionado
    vecinos = []
    for k in (j - 1, j + 1):
        if 0 <= k < len(fusionados) and mejor_f[k] == mejor_f[j]:
            vecinos.append(f"video {fusionados[k].numero} (SOP {mejor_f[k] + 1})")
    consecutivo = "sí: " + ", ".join(vecinos) if vecinos else "no"

    registro = corrida.resultado.fusiones[j]
    indice = {p.numero: i for i, p in enumerate(pasos)}
    originales = [indice[n] for n in registro.originales]
    mejor_o = sop_orig.argmax(axis=1)
    coseno_o = sop_orig.max(axis=1)
    notas = []
    if len(originales) > 1:
        notas.append(f"unió los originales {registro.originales}")
    extremos = ((originales[0] - 1, originales[0]), (originales[-1] + 1, originales[-1]))
    for vecino, propio in extremos:
        if not 0 <= vecino < len(pasos):
            continue
        n_v = pasos[vecino].numero
        if mejor_o[vecino] != mejor_o[propio]:
            notas.append(
                f"con el {n_v}: mejor SOP distinto ({mejor_o[propio] + 1} vs {mejor_o[vecino] + 1})"
            )
        elif min(coseno_o[vecino], coseno_o[propio]) < umbral:
            notas.append(
                f"con el {n_v}: mismo SOP {mejor_o[propio] + 1}, pero coseno "
                f"{coseno_o[propio]:.2f}/{coseno_o[vecino]:.2f} < {umbral}"
            )
        else:
            notas.append(f"con el {n_v}: cumplía la regla (¿?)")
    return consecutivo, "; ".join(notas) or "sin vecinos"


def diagnosticar(
    clave: str,
    carpeta: Path,
    sop: SOP,
    anotacion: dict[str, Any],
    embedder: emp.Embedder,
    juez: JuezGemma | None,
) -> tuple[str, dict[str, Any]]:
    analisis = Analisis.model_validate_json((carpeta / "analisis.json").read_text("utf-8"))
    resultado_json = json.loads((carpeta / "resultado.json").read_text("utf-8"))
    pasos = [PasoVideo.model_validate(p) for p in resultado_json["segmentacion"]["pasos"]]
    tramos = tramos_de(anotacion[clave], analisis.duracion_s)
    settings = get_settings()

    v_sop = embedder.embed([emp.texto_para_embeber(p) for p in sop.pasos])
    v_orig = embedder.embed([emp.texto_para_embeber(p) for p in pasos])
    sop_orig = emp.similitud(v_orig, v_sop)  # originales × SOP (la que usa `fusionar`)

    corridas = [correr(sop, pasos, analisis, embedder, None)]
    if juez is not None:
        corridas.append(correr(sop, pasos, analisis, embedder, juez))

    n = len(sop.pasos)
    lineas = [
        f"# Diagnóstico de {clave} ({carpeta.as_posix()})",
        "",
        f"Esperado (anotación): {anotacion[clave]['esperado']}. "
        f"{len(analisis.transcripcion)} segmentos, {len(pasos)} pasos del video "
        f"({resultado_json['segmentacion']['modelo']}), {n} pasos del SOP. Umbrales "
        f"{settings.umbral_bajo} / {settings.umbral_alto}, fusión {settings.umbral_fusion}.",
        "",
        "## Pasos del video (originales)",
        "",
        "| # | t | Paso del video | Cita | Tramo anotado | Mejor SOP | Coseno |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, p in enumerate(pasos):
        k = int(sop_orig[i].argmax())
        lineas.append(
            f"| {p.numero} | {mmss(p.t_inicio)}–{mmss(p.t_fin)} | {p.nombre} | {p.cita} | "
            f"{tramo_mayor(p, tramos).etiqueta} | {k + 1}. {sop.pasos[k].nombre} | "
            f"{sop_orig[i, k]:.2f} |"
        )

    datos: dict[str, Any] = {"clave": clave, "carpeta": carpeta.as_posix(), "corridas": []}
    for c in corridas:
        r = c.resultado
        resumen = r.clasificacion.resumen
        pct = porcentaje(r)
        lineas += [
            "",
            f"## Corrida {c.nombre}",
            "",
            f"- Conteo: {', '.join(f'{e} {v}' for e, v in resumen.conteo.items())}; "
            f"fuera de orden {resumen.fuera_de_orden}",
            f"- Cumplimiento: **{pct:.1f} %** ({semaforo(pct)})",
            f"- Pares al juez: {resumen.pares_llm} de {resumen.pares}"
            + (f"; veredictos {resumen.juez}" if resumen.juez else ""),
            "- segundos_juez: "
            + ("None" if resumen.segundos_juez is None else f"{resumen.segundos_juez:.1f}"),
            f"- Fusión: {len(pasos)} → {len(r.pasos_video)} pasos del video",
            f"- Marco del operador (ADR-016, fuera del conteo de Sobra): {resumen.marco_operador}",
            "",
            "| SOP | Estado | Video | Coseno | Orden | Juez |",
            "|---|---|---|---|---|---|",
        ]
        for p in r.clasificacion.pasos:
            if p.indice_sop is None:
                continue
            video = "–"
            if p.indice_video is not None:
                originales = r.fusiones[p.indice_video].originales
                video = f"{r.pasos_video[p.indice_video].numero} (orig. {_rango(originales)})"
            orden = "fuera" if p.fuera_de_orden else ""
            juicio = ""
            if p.juicio is not None:
                juicio = p.juicio.veredicto or f"respaldo ({p.juicio.motivo})"
                if p.juicio.justificacion:
                    juicio += f": {p.juicio.justificacion}"
            sim = "–" if p.similitud is None else f"{p.similitud:.2f}"
            lineas.append(
                f"| {p.indice_sop + 1}. {sop.pasos[p.indice_sop].nombre} | {p.estado} | {video} | "
                f"{sim} | {orden} | {juicio} |"
            )

        sobras = [p for p in r.clasificacion.pasos if p.estado == "Sobra"]
        lineas += [
            "",
            f"### Sobra ({len(sobras)}, de ellos {resumen.marco_operador} de marco)",
            "",
            "| Video (orig.) | t_inicio | Paso del video | Mejor SOP (coseno) "
            "| Quién tiene ese SOP | Por qué es Sobra | Consecutivo mismo SOP | Fusión "
            "| Tramo anotado | Marco |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        filas = []
        for s in sobras:
            j = s.indice_video
            assert j is not None
            paso = r.pasos_video[j]
            k = int(c.matriz[:, j].argmax())
            consecutivo, fusion = fusion_de(c, j, pasos, sop_orig, settings.umbral_fusion)
            fila = {
                "video": paso.numero,
                "originales": r.fusiones[j].originales,
                "t_inicio": paso.t_inicio,
                "nombre": paso.nombre,
                "cita": paso.cita,
                "mejor_sop": k + 1,
                "coseno": round(float(c.matriz[k, j]), 3),
                "quien_tiene": quien_tiene(r, k),
                "por_que": por_que_sobra(c, s, settings.umbral_bajo),
                "consecutivo": consecutivo,
                "fusion": fusion,
                "tramo_inicio": tramo_en(paso.t_inicio, tramos).etiqueta,
                "tramo_mayor": tramo_mayor(paso, tramos).etiqueta,
                "marco_operador": s.marco_operador,
            }
            filas.append(fila)
            tramo = fila["tramo_mayor"]
            if fila["tramo_inicio"] != tramo:
                tramo += f" (empieza en {fila['tramo_inicio']})"
            lineas.append(
                f"| {paso.numero} ({', '.join(map(str, fila['originales']))}) | "
                f"{mmss(paso.t_inicio)} | {paso.nombre} — «{paso.cita}» | "
                f"{k + 1}. {sop.pasos[k].nombre} ({fila['coseno']:.2f}) | {fila['quien_tiene']} | "
                f"{fila['por_que']} | {consecutivo} | {fusion} | {tramo} | "
                f"{s.marco_operador or '–'} |"
            )
        datos["corridas"].append(
            {
                "corrida": c.nombre,
                "conteo": resumen.conteo,
                "fuera_de_orden": resumen.fuera_de_orden,
                "porcentaje": round(pct, 1),
                "semaforo": semaforo(pct),
                "pares": resumen.pares,
                "pares_llm": resumen.pares_llm,
                "juez": resumen.juez,
                "segundos_juez": resumen.segundos_juez,
                "marco_operador": resumen.marco_operador,
                "sobra": filas,
                "emparejamiento": r.model_dump(mode="json"),
            }
        )
    return "\n".join(lineas) + "\n", datos


# ── Experimentos (solo en este script; no cambian código de producción) ──────────────────────

# Texto que se vectoriza de cada paso del video. "descripcion" es el de producción
# (`texto_para_embeber`: nombre + descripción que redactó Gemma); las otras agregan o usan lo que
# dijo el operador. Los pasos del SOP siempre usan `texto_para_embeber`.
VARIANTES = ("descripcion", "cita", "narracion", "solo_narracion")


def texto_variante(variante: str, transcripcion: list) -> Any:
    original = emp.texto_para_embeber

    def texto(paso: Any) -> str:
        base = original(paso)
        if not isinstance(paso, PasoVideo) or variante == "descripcion":
            return base
        if variante == "cita":
            return f"{base} {paso.cita}".strip()
        narracion = narracion_de(paso, transcripcion)
        if variante == "narracion":
            return f"{base} {narracion}".strip()
        return narracion or base

    return texto


def sobra_sin_marco(resultado: ResultadoEmparejamiento) -> list[ResultadoPaso]:
    """Los Sobra que quedan si se descartan los que empiezan antes del primer paso emparejado
    o después del último (intro y cierre del operador)."""
    emparejados = [
        p.t_inicio
        for p in resultado.clasificacion.pasos
        if p.indice_sop is not None and p.indice_video is not None and p.t_inicio is not None
    ]
    if not emparejados:
        return []
    primero, ultimo = min(emparejados), max(emparejados)
    return [
        p
        for p in resultado.clasificacion.pasos
        if p.estado == "Sobra" and p.t_inicio is not None and primero <= p.t_inicio <= ultimo
    ]


def experimentos(
    videos: list[tuple[str, Path]],
    sop: SOP,
    anotacion: dict[str, Any],
    embedder: emp.Embedder,
    juez: JuezGemma | None,
) -> str:
    lineas = [
        "# Experimentos",
        "",
        "Falta por número del paso del SOP; Sobra por números originales del video y el tramo "
        "anotado con el que más se encima. «Sin marco» = Sobra que quedan al descartar los que "
        "empiezan antes del primer paso emparejado o después del último.",
        "",
        "| Video | Texto del video | Juez | Conteo | % | Falta | Sobra | Fuera de orden "
        "| Al juez | Sobra sin marco |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for clave, carpeta in videos:
        analisis = Analisis.model_validate_json((carpeta / "analisis.json").read_text("utf-8"))
        datos = json.loads((carpeta / "resultado.json").read_text("utf-8"))
        pasos = [PasoVideo.model_validate(p) for p in datos["segmentacion"]["pasos"]]
        tramos = tramos_de(anotacion[clave], analisis.duracion_s)
        for variante in VARIANTES:
            for con_juez in (False, True) if juez else (False,):
                texto = texto_variante(variante, analisis.transcripcion)
                with mock.patch.object(emp, "texto_para_embeber", texto):
                    r = emp.emparejar(
                        sop,
                        pasos,
                        embedder,
                        juez=juez if con_juez else None,
                        transcripcion=analisis.transcripcion if con_juez else (),
                    )
                clas = r.clasificacion
                faltas = [
                    p.indice_sop + 1
                    for p in clas.pasos
                    if p.estado == "Falta" and p.indice_sop is not None
                ]
                sobras = [
                    f"{_rango(r.fusiones[p.indice_video].originales)} → "
                    f"{tramo_mayor(r.pasos_video[p.indice_video], tramos).nombre}"
                    for p in clas.pasos
                    if p.estado == "Sobra" and p.indice_video is not None
                ]
                fuera = [
                    p.indice_sop + 1
                    for p in clas.pasos
                    if p.fuera_de_orden and p.indice_sop is not None
                ]
                conteo = ", ".join(f"{e} {v}" for e, v in clas.resumen.conteo.items() if v)
                pct = porcentaje(r)
                lineas.append(
                    f"| {clave} | {variante} | {'sí' if con_juez else 'no'} | {conteo} | "
                    f"{pct:.1f} ({semaforo(pct)}) | {faltas or '–'} | "
                    f"{'; '.join(sobras) or '–'} | {fuera or '–'} | {clas.resumen.pares_llm} | "
                    f"{len(sobra_sin_marco(r))} |"
                )
    return "\n".join(lineas) + "\n"


# ── Variantes del texto vectorizado del paso del video (#11) ─────────────────────────────────
#
# Cada variante da la matriz de coseno SOP × pasos del video. La cascada sin juez corre con esa
# matriz y las funciones de producción: `_fusionar` (con `similitud` parcheada para que use la
# matriz de la variante), `asignar`, `clasificar`, `orden` y `marcar_marco`. Con la variante "a"
# el resultado tiene que ser el de `emparejar(juez=None)` y con "b" el de `emparejar` con el
# texto sin cita; si no, el script aborta (`autocomprobar`). El rescate (ADR-022) solo corre con
# juez y queda fuera. Las segmentaciones salen de la base (`videos.pasos_video`, ADR-022): todas
# las variantes ven exactamente los mismos pasos y no se llama a Gemma.

IDIOMA_SOP = get_settings().sop_idioma  # SOP_IDIOMA (ADR-026): en 1.0, "es"
PESOS_CITA = (0.2, 0.35, 0.5)
VARIANTES_TEXTO: dict[str, str] = {
    "a": "nombre + descripción + cita (actual)",
    "b": "nombre + descripción, sin cita",
    **{f"c{w:.2f}": f"vector {1 - w:.2f}·(sin cita) + {w:.2f}·(cita)" for w in PESOS_CITA},
    "d": f"cita solo si el idioma del video es el del SOP ({IDIOMA_SOP})",
    "e": "max(coseno con cita, coseno sin cita)",
    "f": f"e si el idioma del video no es el del SOP ({IDIOMA_SOP}); si lo es, a",
}
SALIDA_VARIANTES = "variantes_texto"


# El de producción, guardado aquí porque `autocomprobar` parchea `emp.texto_para_embeber`.
_TEXTO_PRODUCCION = emp.texto_para_embeber


def texto_sin_cita(paso: PasoVideo) -> str:
    """`texto_para_embeber` del paso del video sin su cita: "nombre. descripción"."""
    return _TEXTO_PRODUCCION(paso.model_copy(update={"cita": ""}))


def texto_cita(paso: PasoVideo) -> str:
    return " ".join(paso.cita.split())


class Vectores:
    """MiniLM con caché por texto: la fusión arma textos nuevos y las variantes los repiten."""

    def __init__(self, embedder: Any) -> None:
        self._embedder = embedder
        self._cache: dict[str, np.ndarray] = {}

    def __call__(self, textos: list[str]) -> np.ndarray:
        faltan = [t for t in dict.fromkeys(textos) if t not in self._cache]
        if faltan:
            for t, v in zip(faltan, self._embedder.embed(faltan), strict=True):
                self._cache[t] = v
        if not textos:
            return np.zeros((0, emp.DIMENSION), dtype=np.float32)
        return np.stack([self._cache[t] for t in textos])


def matriz_variante(
    variante: str, v_sop: np.ndarray, pasos: list[PasoVideo], idioma: str, vec: Vectores
) -> np.ndarray:
    """Coseno SOP × `pasos` con el texto o el vector de la variante (ver `VARIANTES_TEXTO`)."""
    if variante not in VARIANTES_TEXTO:
        raise ValueError(f"variante desconocida: {variante}")
    if not pasos:
        return np.zeros((len(v_sop), 0))
    con = emp.similitud(v_sop, vec([emp.texto_para_embeber(p) for p in pasos]))
    v_sin = vec([texto_sin_cita(p) for p in pasos])
    sin = emp.similitud(v_sop, v_sin)
    if variante == "a":
        return con
    if variante == "b":
        return sin
    if variante == "d":
        return con if idioma.lower().startswith(IDIOMA_SOP) else sin
    if variante == "e":
        return np.maximum(con, sin)
    if variante == "f":
        return con if idioma.lower().startswith(IDIOMA_SOP) else np.maximum(con, sin)
    w = float(variante[1:])
    v_cita = vec([texto_cita(p) or texto_sin_cita(p) for p in pasos])
    return emp.similitud(v_sop, (1 - w) * v_sin + w * v_cita)


@dataclass
class CorridaVariante:
    resultado: ResultadoEmparejamiento
    asignacion: emp.Asignacion
    matriz_orig: np.ndarray  # SOP × pasos originales (la que usa la fusión)
    matriz: np.ndarray  # SOP × pasos fusionados (la que usa `asignar`)


def cascada_variante(sop: SOP, pasos: list[PasoVideo], matriz: Any) -> CorridaVariante:
    """`emparejar` sin juez, con la matriz SOP × video que da `matriz(pasos)`."""
    emp._verificar_fusion(sop.pasos, pasos)
    s = matriz(pasos)
    # `_fusionar` calcula `similitud(vectores_video, vectores_sop)`: se le da la de la variante.
    with mock.patch.object(emp, "similitud", lambda _a, _b: s.T):
        fusionados, fusiones = emp._fusionar(sop.pasos, pasos, np.empty(0), np.empty(0), None)
    m = matriz(fusionados)
    asignacion = emp.asignar(m)
    clas = emp.marcar_marco(emp.orden(emp.clasificar(asignacion, sop.pasos, fusionados)))
    resultado = ResultadoEmparejamiento(
        clasificacion=clas, fusiones=fusiones, pasos_video=fusionados
    )
    return CorridaVariante(resultado, asignacion, s, m)


def mismo_resultado(
    x: ResultadoEmparejamiento, y: ResultadoEmparejamiento, tol: float = 1e-4
) -> bool:
    """Igual estado, pares, orden, marco y fusión; similitudes iguales hasta `tol` (MiniLM en
    lotes distintos no da los mismos bits)."""
    if [f.originales for f in x.fusiones] != [f.originales for f in y.fusiones]:
        return False
    if [p.cita for p in x.pasos_video] != [p.cita for p in y.pasos_video]:
        return False
    if len(x.clasificacion.pasos) != len(y.clasificacion.pasos):
        return False
    for p, q in zip(x.clasificacion.pasos, y.clasificacion.pasos, strict=True):
        clave_p = (p.estado, p.indice_sop, p.indice_video, p.fuera_de_orden, p.marco_operador)
        clave_q = (q.estado, q.indice_sop, q.indice_video, q.fuera_de_orden, q.marco_operador)
        if clave_p != clave_q:
            return False
        if (p.similitud is None) != (q.similitud is None):
            return False
        if p.similitud is not None and abs(p.similitud - (q.similitud or 0)) > tol:
            return False
    return True


# ── Verdad por la anotación manual ───────────────────────────────────────────────────────────


@dataclass
class Verdad:
    """Qué par es correcto según la anotación (sin mirar cosenos).

    - Paso del video → el tramo anotado con el que más se encima (`tramo_mayor`).
    - Paso del SOP → su número si es el SOP de referencia; en un SOP generado, el tramo anotado
      del video de origen que contiene el punto medio de su `t_inicio`–`t_fin`.
    - Si el SOP se generó desde la misma grabación (`mismo_video`), un par correcto además tiene
      que encimarse en el tiempo con el paso del SOP: así no basta con caer en el mismo paso de
      referencia que otro de los varios pasos del SOP generado.
    """

    tramos: list[Tramo]
    ref_sop: list[int | str | None]
    spans_sop: list[tuple[float, float] | None]
    mismo_video: bool

    @classmethod
    def de(
        cls,
        sop: SOP,
        tramos: list[Tramo],
        tramos_origen: list[Tramo] | None,
        mismo_video: bool,
    ) -> Verdad:
        refs: list[int | str | None] = []
        spans: list[tuple[float, float] | None] = []
        for i, p in enumerate(sop.pasos):
            if tramos_origen is None:
                refs.append(i + 1)
                spans.append(None)
            elif p.t_inicio is None or p.t_fin is None:
                refs.append(None)
                spans.append(None)
            else:
                refs.append(tramo_en((p.t_inicio + p.t_fin) / 2, tramos_origen).sop)
                spans.append((p.t_inicio, p.t_fin))
        return cls(tramos, refs, spans, mismo_video)

    def ref_video(self, paso: PasoVideo) -> int | str | None:
        return tramo_mayor(paso, self.tramos).sop

    def correcto(self, i: int, paso: PasoVideo) -> bool:
        ref = self.ref_sop[i]
        if not isinstance(ref, int) or self.ref_video(paso) != ref:
            return False
        span = self.spans_sop[i]
        if self.mismo_video and span is not None:
            return min(span[1], paso.t_fin) - max(span[0], paso.t_inicio) > 0
        return True

    def presente(self, i: int, originales: list[PasoVideo]) -> bool:
        return any(self.correcto(i, p) for p in originales)


# De mejor a peor. Un par equivocado en zona gris vale lo mismo que un error: depende de que el
# juez lo rompa, y si lo rompe queda como Falta + Sobra.
RANGO = {"bien": 0, "juez": 1, "juez✗": 2, "mal": 2}


def zona(similitud_par: float | None, bajo: float, alto: float) -> str:
    if similitud_par is None or similitud_par < bajo:
        return "sin pareja"
    return "aceptado" if similitud_par >= alto else "gris"


def etiquetar(
    corrida: CorridaVariante, verdad: Verdad, originales: list[PasoVideo], bajo: float, alto: float
) -> list[dict[str, Any]]:
    """Por paso del SOP: zona del par del húngaro y si quedó bien, mal o pendiente del juez.

    bien = aceptado con el par correcto, o sin pareja y de verdad ausente; mal = aceptado con un
    par equivocado, o sin pareja estando presente; juez = zona gris con el par correcto (el juez
    debe confirmarlo); juez✗ = zona gris con un par equivocado (el juez debe romperlo). Rango
    (`RANGO`): bien < juez < juez✗ = mal. `coseno_correcto` es el mejor coseno de un paso
    original correcto (sin depender de la asignación).
    """
    r = corrida.resultado
    pares = {p.indice_sop: p for p in corrida.asignacion.pares}
    filas = []
    for i in range(corrida.matriz.shape[0]):
        par = pares.get(i)
        sim = None if par is None else par.similitud
        paso = None if par is None else r.pasos_video[par.indice_video]
        correcto = paso is not None and verdad.correcto(i, paso)
        z = zona(sim, bajo, alto)
        presente = verdad.presente(i, originales)
        if z == "aceptado":
            etiqueta = "bien" if correcto else "mal"
        elif z == "gris":
            etiqueta = "juez" if correcto else "juez✗"
        else:
            etiqueta = "mal" if presente else "bien"
        buenos = [k for k, p in enumerate(originales) if verdad.correcto(i, p)]
        cos_correcto = max((float(corrida.matriz_orig[i, k]) for k in buenos), default=None)
        filas.append(
            {
                "paso_sop": i + 1,
                "zona": z,
                "etiqueta": etiqueta,
                "par_correcto": correcto,
                "presente": presente,
                "coseno": None if sim is None else round(float(sim), 3),
                "video": None if par is None else r.pasos_video[par.indice_video].numero,
                "originales": None if par is None else r.fusiones[par.indice_video].originales,
                "coseno_correcto": None if cos_correcto is None else round(cos_correcto, 3),
            }
        )
    return filas


# ── Casos desde la base ──────────────────────────────────────────────────────────────────────


@dataclass
class Caso:
    nombre: str
    grupo: str
    video_id: int
    clave: str
    sop_etiqueta: str
    sop: SOP
    analisis: Analisis
    pasos: list[PasoVideo]
    formato: str  # "llm" (SegmentacionGuardada) o "lista" (anterior a ADR-022)
    verdad: Verdad


def _corto(clave: str) -> str:
    return clave.removeprefix("video_").upper()


def cargar_caso(texto: str, sop_ref: SOP, anotacion: dict[str, Any], session: Any) -> Caso:
    """`nombre=VIDEO_ID:SOP:CLAVE`, con SOP = `ref` (el de `--sop`) o `SOP_ID@CLAVE_ORIGEN` (un
    SOP generado, con la clave de la anotación del video desde el que se generó)."""
    from sopvid.contrato import SegmentacionGuardada
    from sopvid.plataforma.modelos import Sop, Video
    from sopvid.plataforma.procesamiento import leer_analisis

    nombre, _, resto = texto.partition("=")
    video_txt, sop_txt, clave = resto.split(":")
    video = session.get(Video, int(video_txt))
    if video is None or video.pasos_video is None:
        raise SystemExit(f"{nombre}: el video {video_txt} no existe o no tiene pasos guardados")
    if isinstance(video.pasos_video, dict):
        seg = SegmentacionGuardada.model_validate(video.pasos_video)
        if not seg.reusable:
            raise SystemExit(f"{nombre}: la segmentación del video {video.id} no es del LLM")
        pasos, formato = seg.pasos, "llm"
    else:
        pasos = [PasoVideo.model_validate(p) for p in video.pasos_video]
        formato = "lista"
    analisis = leer_analisis(video)
    tramos = tramos_de(anotacion[clave], analisis.duracion_s)
    if sop_txt == "ref":
        sop, etiqueta, verdad = sop_ref, "ref", Verdad.de(sop_ref, tramos, None, False)
    else:
        sop_id, _, origen = sop_txt.partition("@")
        fila = session.get(Sop, int(sop_id))
        if fila is None or fila.contenido is None or not origen:
            raise SystemExit(f"{nombre}: SOP {sop_txt} inválido (usa SOP_ID@CLAVE_ORIGEN)")
        sop = SOP.model_validate(fila.contenido)
        dur_origen = anotacion[origen].get("duracion_s", analisis.duracion_s)
        verdad = Verdad.de(sop, tramos, tramos_de(anotacion[origen], dur_origen), origen == clave)
        etiqueta = fila.codigo
    return Caso(
        nombre=nombre,
        grupo=f"{_corto(clave)}×{etiqueta}",
        video_id=video.id,
        clave=clave,
        sop_etiqueta=etiqueta,
        sop=sop,
        analisis=analisis,
        pasos=pasos,
        formato=formato,
        verdad=verdad,
    )


# ── Medición de un caso con todas las variantes ──────────────────────────────────────────────


def autocomprobar(caso: Caso, corridas: dict[str, CorridaVariante], embedder: Any) -> None:
    """La cascada de este script reproduce `emparejar(juez=None)` con "a", y con "b" lo que da
    `emparejar` con el texto sin cita. Si no, aborta: la comparación no valdría."""
    real = emp.emparejar(caso.sop, caso.pasos, embedder)
    if not mismo_resultado(corridas["a"].resultado, real):
        raise SystemExit(f"{caso.nombre}: la variante a no reproduce emparejar(juez=None)")

    original = emp.texto_para_embeber

    def sin_cita(paso: Any) -> str:
        return texto_sin_cita(paso) if isinstance(paso, PasoVideo) else original(paso)

    with mock.patch.object(emp, "texto_para_embeber", sin_cita):
        real_b = emp.emparejar(caso.sop, caso.pasos, embedder)
    if not mismo_resultado(corridas["b"].resultado, real_b):
        raise SystemExit(f"{caso.nombre}: la variante b no reproduce emparejar sin cita")

    # La variante f es la de producción con EMPAREJAR_TEXTO=max_si_otro_idioma (ADR-026).
    if get_settings().emparejar_texto == "max_si_otro_idioma":
        real_f = emp.emparejar(caso.sop, caso.pasos, embedder, idioma=caso.analisis.idioma.codigo)
        if not mismo_resultado(corridas["f"].resultado, real_f):
            raise SystemExit(f"{caso.nombre}: la variante f no reproduce emparejar en producción")


def medir_caso(caso: Caso, vec: Vectores, embedder: Any, bajo: float, alto: float) -> dict:
    v_sop = vec([emp.texto_para_embeber(p) for p in caso.sop.pasos])
    idioma = caso.analisis.idioma.codigo
    corridas = {
        v: cascada_variante(
            caso.sop,
            caso.pasos,
            lambda pasos, v=v: matriz_variante(v, v_sop, pasos, idioma, vec),
        )
        for v in VARIANTES_TEXTO
    }
    autocomprobar(caso, corridas, embedder)
    variantes = {}
    for v, c in corridas.items():
        r = c.resultado
        variantes[v] = {
            "porcentaje": round(porcentaje(r), 2),
            "pares_llm": r.clasificacion.resumen.pares_llm,
            "pares": r.clasificacion.resumen.pares,
            "sobra": r.clasificacion.resumen.conteo["Sobra"],
            "falta": r.clasificacion.resumen.conteo["Falta"],
            "fusion": [f.originales for f in r.fusiones],
            "citas_fusion": [p.cita for p in r.pasos_video],
            "filas": etiquetar(c, caso.verdad, caso.pasos, bajo, alto),
        }
    base = variantes["a"]
    for d in variantes.values():
        d["comparado_con_a"] = comparar_con_a(base, d)
    return {
        "nombre": caso.nombre,
        "grupo": caso.grupo,
        "video_id": caso.video_id,
        "formato": caso.formato,
        "idioma": idioma,
        "pasos_video": len(caso.pasos),
        "pasos_sop": len(caso.sop.pasos),
        "variantes": variantes,
    }


def comparar_con_a(base: dict[str, Any], otra: dict[str, Any]) -> dict[str, Any]:
    """Cambios de zona, transiciones de etiqueta, pares equivocados que suben y cambios en la
    fusión (grupos distintos; con los mismos grupos, cita del representante distinta)."""
    transiciones: Counter[str] = Counter()
    cambios_zona = equivocados_suben = graves = mejoras = 0
    for fa, fo in zip(base["filas"], otra["filas"], strict=True):
        if fa["zona"] != fo["zona"]:
            cambios_zona += 1
        if fa["etiqueta"] != fo["etiqueta"]:
            transiciones[f"{fa['etiqueta']}→{fo['etiqueta']}"] += 1
        graves += RANGO[fo["etiqueta"]] > RANGO[fa["etiqueta"]]
        mejoras += RANGO[fo["etiqueta"]] < RANGO[fa["etiqueta"]]
        sube = fo["zona"] in ("gris", "aceptado") and not fo["par_correcto"]
        estaba = fa["zona"] in ("gris", "aceptado") and not fa["par_correcto"]
        if sube and not estaba:
            equivocados_suben += 1
    mismos_grupos = base["fusion"] == otra["fusion"]
    citas = (
        sum(a != b for a, b in zip(base["citas_fusion"], otra["citas_fusion"], strict=True))
        if mismos_grupos
        else None
    )
    return {
        "cambios_zona": cambios_zona,
        "transiciones": dict(transiciones),
        "graves": graves,
        "mejoras": mejoras,
        "equivocados_suben": equivocados_suben,
        "fusion_igual": mismos_grupos,
        "citas_representante_distintas": citas,
        "delta_pares_llm": otra["pares_llm"] - base["pares_llm"],
    }


# ── Control de causa (#11, punto 8): cita de Whisper contra la corregida ─────────────────────


def control_causa(ruta: Path, embedder: Any) -> list[dict[str, Any]]:
    """Coseno del paso del SOP contra el paso del video con cada cita del fixture y sin cita.

    Si con la cita corregida en inglés el coseno vuelve al de sin cita o más, el daño era el ruido
    de Whisper; si sigue bajo y solo la traducción al español lo levanta, era el idioma."""
    datos = json.loads(ruta.read_text("utf-8"))
    filas = []
    for par in datos["pares"]:
        sop = PasoSOP(numero=1, responsable="-", **par["sop"])
        texto_sop = emp.texto_para_embeber(sop)
        base = PasoVideo(
            numero=1,
            responsable="-",
            t_inicio=0,
            t_fin=1,
            cita="",
            fuente="audio",
            confianza="baja",
            **par["video"],
        )
        textos = {"sin cita": emp.texto_para_embeber(base)}
        for nombre, cita in par["citas"].items():
            textos[nombre] = emp.texto_para_embeber(base.model_copy(update={"cita": cita}))
        v = embedder.embed([texto_sop, *textos.values()])
        cosenos = emp.similitud(v[:1], v[1:])[0]
        filas.append(
            {
                "id": par["id"],
                "cosenos": {k: round(float(c), 3) for k, c in zip(textos, cosenos, strict=True)},
            }
        )
    return filas


# ── Informe ──────────────────────────────────────────────────────────────────────────────────


def resumen_por_grupo(casos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filas = []
    grupos = list(dict.fromkeys(c["grupo"] for c in casos))
    for g in grupos:
        del_grupo = [c for c in casos if c["grupo"] == g]
        for v in VARIANTES_TEXTO:
            trans: Counter[str] = Counter()
            zona_n = suben = pares_llm = sobra = fusion_cambia = citas = graves = mejoras = 0
            pct = []
            for c in del_grupo:
                d = c["variantes"][v]
                comp = d["comparado_con_a"]
                trans.update(comp["transiciones"])
                graves += comp["graves"]
                mejoras += comp["mejoras"]
                zona_n += comp["cambios_zona"]
                suben += comp["equivocados_suben"]
                pares_llm += d["pares_llm"]
                sobra += d["sobra"]
                fusion_cambia += not comp["fusion_igual"]
                citas += comp["citas_representante_distintas"] or 0
                pct.append(d["porcentaje"])
            filas.append(
                {
                    "grupo": g,
                    "variante": v,
                    "segmentaciones": len(del_grupo),
                    "cambios_zona": zona_n,
                    "transiciones": dict(trans),
                    "graves": graves,
                    "mejoras": mejoras,
                    "equivocados_suben": suben,
                    "pares_llm": pares_llm,
                    "sobra": sobra,
                    "pct": pct,
                    "fusion_cambia": fusion_cambia,
                    "citas_representante": citas,
                }
            )
    return filas


def _pcts(valores: list[float]) -> str:
    if len(set(valores)) == 1:
        return f"{valores[0]:g}"
    return f"{min(valores):g}–{max(valores):g} (media {sum(valores) / len(valores):.1f})"


def informe_variantes(datos: dict[str, Any]) -> str:
    s = datos["settings"]
    lineas = [
        "# Variantes del texto vectorizado del paso del video (#11)",
        "",
        "`scripts/diagnosticar_emparejamiento.py --variantes-texto`. Cascada sin juez (fusión → "
        "húngaro → umbrales → orden → marco) con las segmentaciones guardadas en la base "
        "(`videos.pasos_video`, ADR-022): todas las variantes ven los mismos pasos; solo MiniLM y "
        "código, sin Gemma. Autocomprobación: la variante a reproduce `emparejar(juez=None)` y la "
        "b, `emparejar` con el texto sin cita, en cada caso.",
        "",
        f"- Commit `{datos['git'].get('commit')}` en `{datos['git'].get('rama')}`"
        f" · cambios sin commit: {datos['git'].get('cambios_sin_commit')}",
        f"- Embedder `{s['embedder_model']}` · umbrales {s['umbral_bajo']} / {s['umbral_alto']}"
        f" · fusión {s['umbral_fusion']} · idioma del SOP para la variante d: `{IDIOMA_SOP}`",
        "- Verdad: el tramo anotado a mano (`media/anotacion_ab.json`) con el que más se encima "
        "cada paso del video; en un SOP generado, el tramo del punto medio de cada paso en el "
        "video de origen y, si es la misma grabación, además encimarse en el tiempo.",
        "- Etiqueta por paso del SOP: **bien** (aceptado ≥ alto con el par correcto, o sin pareja "
        "y ausente de verdad), **mal** (aceptado con par equivocado, o sin pareja estando "
        "presente), **juez** (zona gris con el par correcto) o **juez✗** (zona gris con un par "
        "equivocado). Rango bien < juez < juez✗ = mal; «graves» = pasos que bajan de rango "
        "respecto de a, «mejoras» = los que suben.",
        "",
        "## Variantes",
        "",
        *[f"- **{k}**: {v}" for k, v in VARIANTES_TEXTO.items()],
        "",
        "## Casos",
        "",
        "| Caso | Grupo | Video | Formato | Idioma | Pasos del video | Pasos del SOP |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in datos["casos"]:
        lineas.append(
            f"| {c['nombre']} | {c['grupo']} | {c['video_id']} | {c['formato']} | "
            f"{c['idioma']} | {c['pasos_video']} | {c['pasos_sop']} |"
        )
    lineas += [
        "",
        "## Resumen por grupo y variante (respecto de a)",
        "",
        "| Grupo | Var. | Segm. | Cambios de zona | Graves | Mejoras | Transiciones "
        "| Equivocados que suben | Pares al juez | Sobra | % sin juez | Fusión cambia "
        "| Citas de representante |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for f in datos["resumen"]:
        trans = ", ".join(f"{k} {n}" for k, n in sorted(f["transiciones"].items())) or "–"
        lineas.append(
            f"| {f['grupo']} | {f['variante']} | {f['segmentaciones']} | {f['cambios_zona']} | "
            f"{f['graves']} | {f['mejoras']} | {trans} | {f['equivocados_suben']} | "
            f"{f['pares_llm']} | {f['sobra']} | {_pcts(f['pct'])} | {f['fusion_cambia']} | "
            f"{f['citas_representante']} |"
        )
    lineas += [
        "",
        "## Pasos que cambian respecto de a",
        "",
        "Zona/etiqueta (coseno del par) por variante; solo los pasos del SOP con algún cambio de "
        "zona o etiqueta. «cc» = mejor coseno de un paso original correcto.",
        "",
    ]
    for c in datos["casos"]:
        filas_a = c["variantes"]["a"]["filas"]
        cambian = [
            i
            for i in range(len(filas_a))
            if any(
                (c["variantes"][v]["filas"][i]["zona"], c["variantes"][v]["filas"][i]["etiqueta"])
                != (filas_a[i]["zona"], filas_a[i]["etiqueta"])
                for v in VARIANTES_TEXTO
            )
        ]
        if not cambian:
            continue
        lineas += [
            f"### {c['nombre']} ({c['grupo']}, video {c['video_id']})",
            "",
            "| SOP | " + " | ".join(VARIANTES_TEXTO) + " |",
            "|---|" + "---|" * len(VARIANTES_TEXTO),
        ]
        for i in cambian:
            celdas = []
            for v in VARIANTES_TEXTO:
                f = c["variantes"][v]["filas"][i]
                cos = "–" if f["coseno"] is None else f"{f['coseno']:.2f}"
                cc = "–" if f["coseno_correcto"] is None else f"{f['coseno_correcto']:.2f}"
                par = "✓" if f["par_correcto"] else "✗"
                celdas.append(f"{f['zona']}/{f['etiqueta']} {cos} {par} (cc {cc})")
            lineas.append(f"| {i + 1} | " + " | ".join(celdas) + " |")
        lineas.append("")
    if datos.get("caidas"):
        lineas += [
            "## Caída del coseno del par correcto por la cita (b − a > 0.2)",
            "",
            "| Caso | Paso del SOP | a (con cita) | b (sin cita) | b − a |",
            "|---|---|---|---|---|",
            *[
                f"| {x['caso']} | {x['paso_sop']} | {x['a']:.3f} | {x['b']:.3f} | "
                f"{x['b'] - x['a']:+.3f} |"
                for x in datos["caidas"]
            ],
            "",
        ]
    if datos.get("control"):
        nombres = list(datos["control"][0]["cosenos"])
        lineas += [
            "## Control de causa: cita de Whisper contra la corregida (fixture del equipo)",
            "",
            "| Par | " + " | ".join(nombres) + " |",
            "|---|" + "---|" * len(nombres),
            *[
                f"| {x['id']} | " + " | ".join(f"{x['cosenos'][n]:.3f}" for n in nombres) + " |"
                for x in datos["control"]
            ],
            "",
        ]
    return "\n".join(lineas) + "\n"


def caidas_por_cita(casos: list[dict[str, Any]], umbral: float = 0.2) -> list[dict[str, Any]]:
    """Pasos del SOP cuyo mejor coseno con un paso correcto baja más de `umbral` por la cita."""
    filas = []
    for c in casos:
        for fa, fb in zip(c["variantes"]["a"]["filas"], c["variantes"]["b"]["filas"], strict=True):
            a, b = fa["coseno_correcto"], fb["coseno_correcto"]
            if a is not None and b is not None and b - a > umbral:
                filas.append({"caso": c["nombre"], "paso_sop": fa["paso_sop"], "a": a, "b": b})
    return filas


def variantes_texto(args: argparse.Namespace, sop_ref: SOP, anotacion: dict[str, Any]) -> int:
    from medir_mvp import estado_git

    from sopvid.plataforma.db import get_sessionmaker

    settings = get_settings()
    embedder = emp.get_embedder()
    vec = Vectores(embedder)
    with get_sessionmaker()() as session:
        casos = [cargar_caso(t, sop_ref, anotacion, session) for t in args.videos]
    medidos = []
    for caso in casos:
        print(f"{caso.nombre}: {len(caso.pasos)} pasos ({caso.formato})", file=sys.stderr)
        medidos.append(medir_caso(caso, vec, embedder, settings.umbral_bajo, settings.umbral_alto))
    datos: dict[str, Any] = {
        "git": estado_git(),
        "settings": {
            k: getattr(settings, k)
            for k in ("embedder_model", "umbral_bajo", "umbral_alto", "umbral_fusion")
        },
        "idioma_sop": IDIOMA_SOP,
        "variantes": VARIANTES_TEXTO,
        "casos": medidos,
        "resumen": resumen_por_grupo(medidos),
        "caidas": caidas_por_cita(medidos),
    }
    if args.citas_corregidas:
        datos["control"] = control_causa(args.citas_corregidas, embedder)
    texto = informe_variantes(datos)
    destinos = [SALIDA] + ([args.docs] if args.docs else [])
    for d in destinos:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{SALIDA_VARIANTES}.md").write_text(texto, "utf-8", newline="\n")
        (d / f"{SALIDA_VARIANTES}.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n"
        )
    print(texto)
    print("Salida en " + ", ".join(d.as_posix() for d in destinos), file=sys.stderr)
    return 0


def con_juez_por_modo(
    caso: Caso, embedder: Any, juez: JuezGemma, modos: tuple[str, ...]
) -> dict[str, Any]:
    """`emparejar` de producción, con el juez real y el rescate, en cada `EMPAREJAR_TEXTO`.

    Por paso del SOP: estado final, el paso del video que recibió (originales), si es el
    correcto según la anotación, el coseno y lo que dijo el juez, si lo llamaron."""
    base = get_settings()
    por_modo = {}
    for modo in modos:
        ajustes = base.model_copy(update={"emparejar_texto": modo})
        with mock.patch.object(emp, "get_settings", lambda a=ajustes: a):
            r = emp.emparejar(
                caso.sop,
                caso.pasos,
                embedder,
                juez=juez,
                transcripcion=caso.analisis.transcripcion,
                idioma=caso.analisis.idioma.codigo,
            )
        filas = []
        for p in r.clasificacion.pasos:
            if p.indice_sop is None:
                continue
            paso = None if p.indice_video is None else r.pasos_video[p.indice_video]
            filas.append(
                {
                    "paso_sop": p.indice_sop + 1,
                    "estado": p.estado,
                    "originales": None
                    if p.indice_video is None
                    else r.fusiones[p.indice_video].originales,
                    "correcto": paso is not None and caso.verdad.correcto(p.indice_sop, paso),
                    "presente": caso.verdad.presente(p.indice_sop, caso.pasos),
                    "coseno": None if p.similitud is None else round(p.similitud, 3),
                    "juez": None
                    if p.juicio is None
                    else (p.juicio.veredicto or f"respaldo ({p.juicio.motivo})"),
                    "justificacion": None if p.juicio is None else p.juicio.justificacion,
                    "rescatado": bool(
                        p.indice_video is not None and r.fusiones[p.indice_video].rescate
                    ),
                }
            )
        resumen = r.clasificacion.resumen
        por_modo[modo] = {
            "porcentaje": round(porcentaje(r), 2),
            "conteo": resumen.conteo,
            "pares_llm": resumen.pares_llm,
            "juez": resumen.juez,
            "rescatados": resumen.rescatados,
            "filas": filas,
        }
    return {"nombre": caso.nombre, "grupo": caso.grupo, "video_id": caso.video_id, **por_modo}


def informe_juez(datos: dict[str, Any]) -> str:
    modos = datos["modos"]
    lineas = [
        "# Emparejamiento con el juez real por EMPAREJAR_TEXTO (#11, ADR-026)",
        "",
        "`scripts/diagnosticar_emparejamiento.py --variantes-texto --juez`: `emparejar` de "
        "producción (fusión, húngaro, umbrales, juez Gemma 4 de la zona gris y rescate) con la "
        "segmentación guardada, una vez por valor de `EMPAREJAR_TEXTO`.",
        "",
        f"- Commit `{datos['git'].get('commit')}` · LLM `{datos['llm']}` · cambios sin commit: "
        f"{datos['git'].get('cambios_sin_commit')}",
        "",
    ]
    for c in datos["casos"]:
        lineas += [f"## {c['nombre']} ({c['grupo']}, video {c['video_id']})", ""]
        for m in modos:
            d = c[m]
            lineas.append(
                f"- **{m}**: {d['porcentaje']} %, conteo {d['conteo']}, al juez "
                f"{d['pares_llm']} ({d['juez']}), rescatados {d['rescatados']}"
            )
        lineas += [
            "",
            "| SOP | " + " | ".join(modos) + " |",
            "|---|" + "---|" * len(modos),
        ]
        for i in range(len(c[modos[0]]["filas"])):
            celdas = []
            for m in modos:
                f = c[m]["filas"][i]
                par = "–" if f["originales"] is None else f"{f['originales']}"
                marca = "✓" if f["correcto"] else "✗"
                cos = "–" if f["coseno"] is None else f"{f['coseno']:.2f}"
                juez = f", juez: {f['juez']}" if f["juez"] else ""
                celdas.append(f"{f['estado']} {par} {marca} {cos}{juez}")
            lineas.append(f"| {i + 1} | " + " | ".join(celdas) + " |")
        lineas.append("")
    return "\n".join(lineas) + "\n"


def variantes_con_juez(args: argparse.Namespace, sop_ref: SOP, anotacion: dict[str, Any]) -> int:
    from medir_mvp import estado_git

    from sopvid.plataforma.db import get_sessionmaker

    llm = ClienteLLM.desde_settings()
    if not llm.disponible(timeout_s=10):
        print("Ollama no responde o no tiene LLM_MODEL", file=sys.stderr)
        llm.close()
        return 1
    modos = ("cita", "max_si_otro_idioma")
    try:
        juez = JuezGemma(llm)
        embedder = emp.get_embedder()
        with get_sessionmaker()() as session:
            casos = [cargar_caso(t, sop_ref, anotacion, session) for t in args.videos]
        medidos = []
        for caso in casos:
            print(f"{caso.nombre}: juez real con {modos}", file=sys.stderr)
            medidos.append(con_juez_por_modo(caso, embedder, juez, modos))
        datos = {
            "git": estado_git(),
            "llm": get_settings().llm_model,
            "dispositivo": llm.dispositivo_cargado(),
            "modos": modos,
            "casos": medidos,
        }
    finally:
        llm.descargar()
        llm.close()
    texto = informe_juez(datos)
    destinos = [SALIDA] + ([args.docs] if args.docs else [])
    for d in destinos:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{SALIDA_VARIANTES}_juez.md").write_text(texto, "utf-8", newline="\n")
        (d / f"{SALIDA_VARIANTES}_juez.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n"
        )
    print(texto)
    return 0


def main() -> int:
    # La consola de Windows usa cp1252 y no puede imprimir "→" ni "–" del reporte.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("videos", nargs="+", help="clave=carpeta, p. ej. video_a=media/video_a_v2")
    ap.add_argument("--sop", type=Path, required=True, help="SOP en Markdown o TXT (plantilla)")
    ap.add_argument("--anotacion", type=Path, required=True, help="JSON de la anotación manual")
    ap.add_argument("--sin-juez", action="store_true", help="solo la corrida sin juez")
    ap.add_argument(
        "--experimentos",
        action="store_true",
        help="compara variantes del texto del paso del video y el filtro de intro y cierre",
    )
    ap.add_argument(
        "--variantes-texto",
        action="store_true",
        help="#11: compara variantes del texto vectorizado con segmentaciones de la base; cada "
        "posicional es nombre=VIDEO_ID:SOP:CLAVE (SOP = ref o SOP_ID@CLAVE_ORIGEN)",
    )
    ap.add_argument(
        "--citas-corregidas",
        type=Path,
        help="con --variantes-texto: fixture del control de causa (cita de Whisper y corregida)",
    )
    ap.add_argument(
        "--docs", type=Path, help="con --variantes-texto: copia el informe en esta carpeta"
    )
    ap.add_argument(
        "--juez",
        action="store_true",
        help="con --variantes-texto: emparejar de producción con el juez real (Ollama), con "
        "EMPAREJAR_TEXTO=cita y =max_si_otro_idioma",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    sop = convertir_sop(args.sop.read_text("utf-8")).sop
    anotacion = json.loads(args.anotacion.read_text("utf-8"))
    if args.variantes_texto and args.juez:
        return variantes_con_juez(args, sop, anotacion)
    if args.variantes_texto:
        return variantes_texto(args, sop, anotacion)
    embedder = emp.get_embedder()
    SALIDA.mkdir(parents=True, exist_ok=True)

    llm = None if args.sin_juez else ClienteLLM.desde_settings()
    if llm is not None and not llm.disponible(timeout_s=10):
        print("Ollama no responde o no tiene LLM_MODEL: usa --sin-juez", file=sys.stderr)
        llm.close()
        return 1
    try:
        juez = JuezGemma(llm) if llm is not None else None
        if args.experimentos:
            videos = [(c, Path(d)) for c, _, d in (v.partition("=") for v in args.videos)]
            texto = experimentos(videos, sop, anotacion, embedder, juez)
            (SALIDA / "experimentos.md").write_text(texto, "utf-8")
            print(texto)
            return 0
        for entrada in args.videos:
            clave, _, carpeta = entrada.partition("=")
            texto, datos = diagnosticar(clave, Path(carpeta), sop, anotacion, embedder, juez)
            (SALIDA / f"{clave}.md").write_text(texto, "utf-8")
            (SALIDA / f"{clave}.json").write_text(
                json.dumps(datos, ensure_ascii=False, indent=2) + "\n", "utf-8"
            )
            print(texto)
    finally:
        if llm is not None:
            llm.close()
    print(f"Salida en {SALIDA.relative_to(PROJECT_ROOT).as_posix()}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
