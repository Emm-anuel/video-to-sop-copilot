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
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from sopvid.contrato import SOP, Analisis, PasoVideo, ResultadoEmparejamiento, ResultadoPaso
from sopvid.lenguaje import emparejamiento as emp
from sopvid.lenguaje.juez import JuezGemma, narracion_de
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.plataforma.config import PROJECT_ROOT, get_settings

SALIDA = PROJECT_ROOT / "data" / "interim" / "diagnostico"


# ── Porcentaje de cumplimiento (documento SOP V1.0, sección 5.6) ─────────────────────────────


def porcentaje(resultado: ResultadoEmparejamiento, n_sop: int) -> float:
    """(Cumple + 0.5 × (Parcial + Fuera de orden)) / pasos del SOP × 100.

    Fuera de orden es una marca: un Cumple o Parcial marcado cuenta 0.5 una sola vez. Los Sobra
    no restan; Falta y los zona_gris (con o sin respaldo) cuentan 0.
    """
    puntos = 0.0
    for p in resultado.clasificacion.pasos:
        if p.estado == "Cumple":
            puntos += 0.5 if p.fuera_de_orden else 1.0
        elif p.estado == "Parcial":
            puntos += 0.5
    return 100 * puntos / n_sop


def semaforo(pct: float) -> str:
    return "verde" if pct >= 90 else "amarillo" if pct >= 70 else "rojo"


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
        pct = porcentaje(r, n)
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
                pct = porcentaje(r, len(sop.pasos))
                lineas.append(
                    f"| {clave} | {variante} | {'sí' if con_juez else 'no'} | {conteo} | "
                    f"{pct:.1f} ({semaforo(pct)}) | {faltas or '–'} | "
                    f"{'; '.join(sobras) or '–'} | {fuera or '–'} | {clas.resumen.pares_llm} | "
                    f"{len(sobra_sin_marco(r))} |"
                )
    return "\n".join(lineas) + "\n"


def main() -> int:
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
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    sop = convertir_sop(args.sop.read_text("utf-8")).sop
    anotacion = json.loads(args.anotacion.read_text("utf-8"))
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
