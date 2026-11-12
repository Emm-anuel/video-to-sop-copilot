r"""Mide el SOP generado desde el video (RF-22 a RF-25, RF-27; RNF-05; ADR-023) con Gemma real.

Por cada video (clave=ruta del video o de su `analisis.json`): Whisper una vez (es determinista),
y `--repeticiones` corridas del modo generar con el código de producción, descargando Gemma antes
de cada una (carga en frío, como la API): ficha de contexto → pasos del video → SOP generado. Por
corrida registra los segundos, los tokens de salida y los tokens/s de cada llamada, el total, el
número de pasos del video y la VRAM usada (`nvidia-smi`, con el modelo cargado).

**Punto 0 (GPU).** Antes de medir hace una llamada corta y pregunta a Ollama dónde quedó el modelo
(`ClienteLLM.dispositivo_cargado`, la columna PROCESSOR de `ollama ps`), y vuelve a preguntar en
cada corrida antes de descargarlo. Si Gemma quedó en CPU sin `LLM_DISPOSITIVO=cpu`, se detiene
sin medir (código 3).

Con `--referencia` (el SOP escrito a mano) y una anotación con la clave del video, mide RNF-05
("al menos 80 % de los pasos generados coinciden con los que narra el operador") de dos formas:

- **Por tramos (principal, ADR-023).** Un paso generado es correcto si cae dentro del tramo
  anotado de un solo paso de referencia (de su segundo al siguiente segundo anotado, con
  `TOLERANCIA_TRAMO_S` en cada borde: la anotación está verificada a ±0.8 s) y respeta el orden
  (su paso de referencia no es anterior al de un paso correcto previo). Un SOP más detallado que
  el de referencia no se castiga; uno que mezcla pasos de referencia, sí.
- **Uno a uno (secundario, más estricto).** MiniLM, húngaro, umbrales y el juez de la zona gris,
  como el emparejamiento de la validación, pero sin fusión ni rescate. Correcto si su par es
  *Cumple* o *Parcial*, no está fuera de orden y su punto medio cae en el tramo de ese paso de
  referencia: cada paso de más es *Sobra*.

Además, la cobertura en orden (pasos de referencia con un par *Cumple* o *Parcial* en orden).

Con `--validar clave=ruta`, valida ese video contra el SOP generado en la primera corrida del
primer video, o contra el primer SOP de `--sop-editado` (uso cruzado, RF-27), con `validar` de
producción. El SOP pasa antes por JSON, como lo guarda la biblioteca (`sops.contenido`) y lo
vuelve a leer la validación.

Con `--sop-editado clave=ORIGEN` (se repite por video), ese video no genera un SOP nuevo: mide
RNF-05 sobre el SOP que alguien corrigió en el editor (RF-26, ADR-025), el número que va al
informe final. ORIGEN es un `sop_id` (se lee de `sops.contenido` en la base del `.env`) o un
archivo JSON: el `SOP` del contrato, la respuesta de `GET /sops/{id}` (`{"sop": ...}`) o el
archivo que deja este script por corrida. El video se sigue pasando como argumento (su
`analisis.json` o el video) para los tramos y el juez. Un paso agregado a mano sin tiempos no
cae en ningún tramo: cuenta como incorrecto. Unir pasos es válido; quitar pasos baja el
denominador (ADR-025), así que el informe trae también la referencia cubierta.

`--candado si|no` fija el candado de la agrupación (ADR-023; por defecto, `SOP_CANDADO`). El
informe trae, por corrida, las etiquetas de Gemma, los grupos y los pasos que partió el candado.

Uso (desde la raíz, con el entorno activado, `make up-gpu` y la API detenida). Con un SOP
editado (sop_id 42), sin generar:

    python scripts/medir_sop_generado.py --referencia tests/fixtures/sop_filtro_agua.md \
        --anotacion media/anotacion_ab.json --sop-editado video_e=42 \
        video_e=data/interim/sop_generado/<fecha>/video_e/analisis.json

Generando:

    python scripts/medir_sop_generado.py --repeticiones 3 \
        --referencia tests/fixtures/sop_filtro_agua.md --anotacion media/anotacion_ab.json \
        --validar video_a=data/interim/sop_generado/<fecha>/video_a/analisis.json \
        video_e=data/synthetic/video_e/VIDEO-E.mp4

Salida en `data/interim/sop_generado/<fecha>/` (ignorada por git): los análisis, los SOP
generados y el informe. Con `--docs`, el informe y los SOP también en
`docs/adr/datos/sop_generado/` (videos grabados por el equipo, sin material del cliente).
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from medir_mvp import estado_git, preparar

from sopvid.contrato import SOP, Analisis, Dispositivos, PasoVideo
from sopvid.lenguaje.emparejamiento import (
    asignar,
    clasificar,
    get_embedder,
    orden,
    similitud,
    texto_para_embeber,
)
from sopvid.lenguaje.juez import JuezGemma, aplicar_juez
from sopvid.lenguaje.llm import ClienteLLM, RespuestaLLM, tokens_por_segundo
from sopvid.lenguaje.sop_generado import PROMPT_AGRUPAR, SOPGenerado, generar_sop
from sopvid.lenguaje.sop_markdown import convertir_sop, empieza_con_infinitivo
from sopvid.lenguaje.validacion import DependenciasValidacion, validar
from sopvid.percepcion.contexto import generar_contexto
from sopvid.percepcion.segmentacion import segmentar
from sopvid.plataforma.config import PROJECT_ROOT, get_settings
from sopvid.plataforma.db import get_sessionmaker
from sopvid.plataforma.hardware import get_hardware
from sopvid.plataforma.modelos import Sop

SALIDA = PROJECT_ROOT / "data" / "interim" / "sop_generado"
DOCS = PROJECT_ROOT / "docs" / "adr" / "datos" / "sop_generado"
GPU_NO_CONFIRMADA = 3
TOLERANCIA_TRAMO_S = 1.0  # bordes del tramo anotado; la anotación está verificada a ±0.8 s

logger = logging.getLogger("medir_sop_generado")


# ── Llamadas registradas ─────────────────────────────────────────────────────────────────────


@dataclass
class Llamada:
    etapa: str
    segundos: float
    tokens_salida: int | None
    tokens_por_s: float | None


class Registro:
    """Envuelve `chat` y `chat_en_flujo` del cliente para anotar cada llamada con la etapa
    actual (la ficha, la segmentación y las cuatro del SOP)."""

    def __init__(self, llm: ClienteLLM):
        self.etapa = "?"
        self.llamadas: list[Llamada] = []
        for nombre in ("chat", "chat_en_flujo"):
            setattr(llm, nombre, self._envolver(getattr(llm, nombre)))

    def _envolver(self, metodo: Callable[..., RespuestaLLM]) -> Callable[..., RespuestaLLM]:
        def envuelto(*args: Any, **kwargs: Any) -> RespuestaLLM:
            inicio = time.perf_counter()
            respuesta = metodo(*args, **kwargs)
            m = respuesta.metricas
            self.llamadas.append(
                Llamada(
                    self.etapa,
                    round(time.perf_counter() - inicio, 2),
                    m.get("eval_count"),
                    None if (v := tokens_por_segundo(m)) is None else round(v, 1),
                )
            )
            return respuesta

        return envuelto


def vram_mib() -> int | None:
    try:
        salida = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        return int(salida.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def ollama_ps() -> str:
    try:
        return subprocess.run(
            ["docker", "compose", "exec", "-T", "ollama", "ollama", "ps"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=PROJECT_ROOT,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "(no se pudo consultar)"


def confirmar_dispositivo(llm: ClienteLLM, pedido_cpu: bool) -> tuple[str, str]:
    """Carga Gemma con una llamada corta y pregunta dónde quedó. Devuelve (dispositivo, ollama
    ps). Si quedó en CPU sin pedirlo, sale con `GPU_NO_CONFIRMADA`."""
    llm.chat([{"role": "user", "content": "Responde solo: ok"}])
    dispositivo = llm.dispositivo_cargado()
    ps = ollama_ps()
    if dispositivo != ("cpu" if pedido_cpu else "gpu"):
        print(
            f"Gemma quedó en {dispositivo} y se esperaba {'cpu' if pedido_cpu else 'gpu'}; no se "
            f"mide.\n{ps}",
            file=sys.stderr,
        )
        sys.exit(GPU_NO_CONFIRMADA)
    llm.descargar()
    return dispositivo, ps


# ── Una corrida del modo generar ─────────────────────────────────────────────────────────────


@dataclass
class Corrida:
    video: str
    n: int
    dispositivo: str
    vram_mib: int | None = None
    pasos_video: int = 0
    pasos_sop: int = 0
    segundos: dict[str, float] = field(default_factory=dict)
    llamadas: list[dict[str, Any]] = field(default_factory=list)
    agrupacion: dict[str, Any] = field(default_factory=dict)
    equipo_operacion: list[str] = field(default_factory=list)
    sin_traducir: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    archivo_sop: str = ""


def generar(
    clave: str,
    n: int,
    analisis: Analisis,
    llm: ClienteLLM,
    registro: Registro,
    pedido_cpu: bool,
    candado: bool,
) -> tuple[Corrida, SOPGenerado]:
    llm.descargar()  # carga en frío, como la API
    registro.llamadas.clear()
    segundos: dict[str, float] = {}
    inicio = time.perf_counter()
    registro.etapa = "contexto"
    contexto = generar_contexto(analisis, llm)
    segundos["contexto"] = round(time.perf_counter() - inicio, 2)
    t = time.perf_counter()
    registro.etapa = "segmentacion"
    segmentacion = segmentar(analisis, llm)
    segundos["segmentacion"] = round(time.perf_counter() - t, 2)
    t = time.perf_counter()

    def avanzar(etapa: str) -> None:
        registro.etapa = etapa

    generado = generar_sop(
        analisis,
        segmentacion.pasos,
        llm,
        contexto.contexto if contexto.generado else None,
        candado=candado,
        al_avanzar=avanzar,
    )
    segundos["sop"] = round(time.perf_counter() - t, 2)
    segundos["total_gemma"] = round(time.perf_counter() - inicio, 2)
    dispositivo = llm.dispositivo_cargado()
    vram = vram_mib()
    llm.descargar()
    if dispositivo != ("cpu" if pedido_cpu else "gpu"):
        print(f"{clave} [{n}]: Gemma quedó en {dispositivo}; se detiene", file=sys.stderr)
        sys.exit(GPU_NO_CONFIRMADA)
    # La ficha y la segmentación, del registro; las del SOP, de `GeneracionSOP` (con sus
    # reintentos sumados en cada llamada).
    llamadas = [
        {"etapa": x.etapa, "s": x.segundos, "tokens": x.tokens_salida, "tok_s": x.tokens_por_s}
        for x in registro.llamadas
        if x.etapa in ("contexto", "segmentacion")
    ]
    llamadas += [
        {
            "etapa": x.etapa + ("" if x.ok else f" (falló: {x.motivo})"),
            "s": x.segundos,
            "tokens": x.tokens_salida,
            "tok_s": x.tokens_por_s,
            "intentos": x.intentos,
        }
        for x in generado.generacion.llamadas
    ]
    corrida = Corrida(
        clave,
        n,
        dispositivo,
        vram,
        len(segmentacion.pasos),
        len(generado.sop.pasos),
        segundos,
        llamadas,
        [f"{a.tipo}: {a.mensaje}" for a in generado.advertencias],
    )
    corrida.equipo_operacion = [e.nombre for e in generado.sop.resumen.equipo_operacion]
    corrida.sin_traducir = [a.mensaje for a in generado.advertencias if a.tipo == "sin_traducir"]
    g = generado.generacion
    corrida.agrupacion = {
        "metodo": g.agrupacion,
        "etiquetas": list(g.etiquetas),
        "grupos": g.grupos,
        "fuera": [f"{f.paso_video} {f.tipo}" for f in g.fuera],
        "candado": g.candado,
        "cortes_candado": g.cortes_candado,
    }
    return corrida, generado


# ── RNF-05: pasos generados contra el SOP escrito a mano ─────────────────────────────────────


def como_paso_video(sop: SOP) -> list[PasoVideo]:
    return [
        PasoVideo(
            numero=p.numero,
            nombre=p.nombre,
            descripcion=p.descripcion,
            responsable=p.responsable,
            t_inicio=p.t_inicio or 0.0,
            t_fin=p.t_fin or 0.0,
            cita=p.cita,
            fuente="inferido" if p.fuente == "documento" else p.fuente,
            confianza=p.confianza,
        )
        for p in sop.pasos
    ]


def tramos_anotados(anotacion: dict[str, Any], duracion: float) -> dict[int, tuple[float, float]]:
    """De cada paso de referencia: del segundo anotado al siguiente segundo anotado (o al final)."""
    pasos = anotacion["pasos"]
    tramos = {}
    for a, b in zip(pasos, [*pasos[1:], {"t": duracion}], strict=True):
        if a.get("sop") is not None:
            tramos[a["sop"]] = (a["t"], b["t"])
    return tramos


def paso_del_tramo(
    t_inicio: float,
    t_fin: float,
    tramos: dict[int, tuple[float, float]],
    tolerancia: float = TOLERANCIA_TRAMO_S,
) -> int | None:
    """El paso de referencia cuyo tramo contiene todo [t_inicio, t_fin], con `tolerancia` en cada
    borde; None si el paso generado se sale de todos (mezcla pasos de referencia o cae en la
    presentación o el cierre). Si por la tolerancia cabe en dos, gana el de su punto medio."""
    dentro = [
        r for r, (a, b) in tramos.items() if a - tolerancia <= t_inicio and t_fin <= b + tolerancia
    ]
    if len(dentro) > 1:
        medio = (t_inicio + t_fin) / 2
        return next((r for r in dentro if tramos[r][0] <= medio < tramos[r][1]), dentro[0])
    return dentro[0] if dentro else None


def correctos_por_tramos(
    pasos: list[tuple[float | None, float | None]],
    tramos: dict[int, tuple[float, float]],
    tolerancia: float = TOLERANCIA_TRAMO_S,
) -> list[tuple[int | None, bool]]:
    """RNF-05 por tramos: por cada paso generado (inicio, fin), en orden, su paso de referencia y
    si es correcto: cae dentro del tramo de un solo paso de referencia y ese paso no es anterior
    al de un paso correcto previo. Un paso sin tiempos (agregado a mano en el editor) no cae en
    ningún tramo: incorrecto."""
    resultado: list[tuple[int | None, bool]] = []
    ultimo = 0
    for t_inicio, t_fin in pasos:
        if t_inicio is None or t_fin is None:
            resultado.append((None, False))
            continue
        ref = paso_del_tramo(t_inicio, t_fin, tramos, tolerancia)
        correcto = ref is not None and ref >= ultimo
        if ref is not None and correcto:
            ultimo = ref
        resultado.append((ref, correcto))
    return resultado


def cobertura_en_orden(filas: list[dict[str, Any]]) -> list[int]:
    """Dato secundario de RNF-05 (para el paper): los pasos de referencia cubiertos en orden, es
    decir, con un paso generado emparejado como *Cumple* o *Parcial* que no está fuera de orden.
    No exige que caiga en el tramo anotado ni penaliza los pasos generados de más."""
    return sorted(
        {
            f["referencia"]
            for f in filas
            if f["referencia"] is not None
            and f["estado"] in ("Cumple", "Parcial")
            and not f["fuera_de_orden"]
        }
    )


def comparar(
    generado: SOP,
    referencia: SOP,
    analisis: Analisis,
    anotacion: dict[str, Any],
    llm: ClienteLLM,
) -> dict[str, Any]:
    pasos = como_paso_video(generado)
    embedder = get_embedder()
    x = embedder.embed([texto_para_embeber(p) for p in (*referencia.pasos, *pasos)])
    matriz = similitud(x[: len(referencia.pasos)], x[len(referencia.pasos) :])
    clasificacion = clasificar(asignar(matriz), referencia.pasos, pasos)
    clasificacion = aplicar_juez(
        clasificacion, referencia.pasos, pasos, analisis.transcripcion, JuezGemma(llm)
    )
    clasificacion = orden(clasificacion)
    llm.descargar()
    tramos = tramos_anotados(anotacion, analisis.duracion_s)
    por_tramos = correctos_por_tramos([(p.t_inicio, p.t_fin) for p in generado.pasos], tramos)
    por_video = {r.indice_video: r for r in clasificacion.pasos if r.indice_video is not None}
    filas = []
    for i, p in enumerate(generado.pasos):
        r = por_video.get(i)
        ref = r.indice_sop + 1 if r and r.indice_sop is not None else None
        con_tiempos = p.t_inicio is not None and p.t_fin is not None
        medio = ((p.t_inicio or 0) + (p.t_fin or 0)) / 2
        en_tramo = con_tiempos and ref is not None and tramos[ref][0] <= medio < tramos[ref][1]
        estado = r.estado if r else "?"
        correcto = estado in ("Cumple", "Parcial") and not r.fuera_de_orden and en_tramo
        filas.append(
            {
                "paso": p.numero,
                "nombre": p.nombre,
                "t_inicio": p.t_inicio,
                "t_fin": p.t_fin,
                "referencia": ref,
                "nombre_referencia": referencia.pasos[ref - 1].nombre if ref else None,
                "estado": estado,
                "similitud": None if r is None or r.similitud is None else round(r.similitud, 3),
                "fuera_de_orden": bool(r and r.fuera_de_orden),
                "en_tramo": en_tramo,
                "correcto": correcto,
                "ref_tramo": por_tramos[i][0],
                "correcto_tramo": por_tramos[i][1],
            }
        )
    faltan = [
        r.indice_sop + 1
        for r in clasificacion.pasos
        if r.estado == "Falta" and r.indice_sop is not None
    ]
    correctos = sum(f["correcto"] for f in filas)
    cubiertos = cobertura_en_orden(filas)
    tramos_ok = sum(ok for _, ok in por_tramos)
    return {
        "pasos_generados": len(filas),
        "tramos_correctos": tramos_ok,
        "tramos_pct": round(100 * tramos_ok / len(filas), 1) if filas else 0.0,
        "correctos": correctos,
        "pct": round(100 * correctos / len(filas), 1) if filas else 0.0,
        "referencia_cubierta": len(referencia.pasos) - len(faltan),
        "referencia_faltan": faltan,
        "referencia_total": len(referencia.pasos),
        "cobertura_en_orden": cubiertos,
        "cobertura_pct": round(100 * len(cubiertos) / len(referencia.pasos), 1),
        "filas": filas,
    }


def leer_sop_editado(origen: str) -> SOP:
    """El SOP corregido en el editor: por `sop_id` (de `sops.contenido`) o desde un archivo JSON
    con el `SOP` del contrato, la respuesta de `GET /sops/{id}` o el archivo de una corrida (los
    dos últimos lo traen en `"sop"`)."""
    if origen.isdigit():
        with get_sessionmaker()() as session:
            fila = session.get(Sop, int(origen))
            if fila is None or fila.contenido is None:
                raise SystemExit(f"el SOP {origen} no existe o no está listo")
            return SOP.model_validate(fila.contenido)
    ruta = Path(origen)
    if not ruta.is_file():
        raise SystemExit(f"--sop-editado: {origen} no es un sop_id ni un archivo")
    datos = json.loads(ruta.read_text("utf-8"))
    return SOP.model_validate(datos["sop"] if "pasos" not in datos and "sop" in datos else datos)


def ediciones(pares: list[str]) -> dict[str, str]:
    """`clave=ORIGEN` de cada `--sop-editado`."""
    salida = {}
    for par in pares:
        clave, _, origen = par.partition("=")
        if not clave or not origen:
            raise SystemExit(f"--sop-editado espera clave=ORIGEN (llegó {par!r})")
        salida[clave] = origen
    return salida


def completitud(sop: SOP) -> dict[str, Any]:
    """Qué del cuadro resumen y de la tabla de pasos quedó lleno (§14, video E)."""
    r = sop.resumen
    return {
        "titulo": sop.titulo,
        "objetivo": r.objetivo.valor,
        "alcance": r.alcance.valor,
        "lugar": r.lugar.valor,
        "horario": r.horario_frecuencia.valor,
        "responsable": r.responsable.valor,
        "roles": [e.nombre for e in r.roles],
        "equipo": len(r.equipo_operacion),
        "riesgos": len(r.riesgos),
        "en_caso_de_falla": len(r.en_caso_de_falla),
        "duracion_total_min": r.duracion_total_min,
        "pasos_en_infinitivo": sum(empieza_con_infinitivo(p.nombre) for p in sop.pasos),
        "pasos": len(sop.pasos),
        "puntos_clave": len(sop.puntos_clave),
        "palabras_clave": len(sop.palabras_clave),
        "inferidos": sum(len(p.campos_inferidos) for p in sop.pasos),
    }


# ── Informe ──────────────────────────────────────────────────────────────────────────────────


def _tramo(f: dict[str, Any]) -> str:
    if f["t_inicio"] is None or f["t_fin"] is None:
        return "sin tiempos"
    return f"{f['t_inicio']:.1f}–{f['t_fin']:.1f}"


def informe(datos: dict[str, Any]) -> str:
    lineas = [
        f"# SOP generado · medición {datos['fecha']}",
        "",
        f"Commit `{datos['git'].get('commit')}`"
        + (
            f" ({datos['git']['cambios_sin_commit']} archivos con cambios sin commit)"
            if datos["git"].get("cambios_sin_commit")
            else ""
        )
        + f" · LLM `{datos['configuracion']['llm']}` · `LLM_DISPOSITIVO="
        f"{datos['configuracion']['llm_dispositivo']}` · GPU {datos['configuracion']['gpu']}",
        "",
        f"Agrupación `{datos['configuracion']['prompt_agrupar']}` · candado "
        f"{'sí' if datos['configuracion']['candado'] else 'no'} (`UMBRAL_FUSION="
        f"{datos['configuracion']['umbral_fusion']}`)",
        "",
        "## Punto 0: dónde quedó Gemma",
        "",
        "```",
        datos["ollama_ps"],
        "```",
        "",
        "## Corridas",
        "",
        "| Video | n | Gemma | VRAM MiB | Pasos del video | Pasos del SOP | Ficha s | Pasos s | "
        "SOP s | Total Gemma s | Advertencias | Equipo de operación | Sin traducir |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in datos["corridas"]:
        s = c["segundos"]
        lineas.append(
            f"| {c['video']} | {c['n']} | {c['dispositivo']} | {c['vram_mib']} | "
            f"{c['pasos_video']} | {c['pasos_sop']} | {s.get('contexto')} | "
            f"{s.get('segmentacion')} | {s.get('sop')} | {s.get('total_gemma')} | "
            f"{len(c['advertencias'])} | {len(c.get('equipo_operacion', []))} | "
            f"{len(c.get('sin_traducir', []))} |"
        )
    lineas += [
        "",
        "## Agrupación (etiqueta de Gemma por paso del video → grupos)",
        "",
        "| Video | n | Etiquetas | Grupos | Fuera | Cortes del candado |",
        "|---|---|---|---|---|---|",
    ]
    abreviada = {
        "nuevo": "N",
        "continua": "c",
        "introduccion": "i",
        "cierre": "x",
        "entrevistador": "e",
        "comentario": "o",
    }
    for c in datos["corridas"]:
        a = c.get("agrupacion") or {}
        etiquetas = " ".join(abreviada.get(e, e) for e in a.get("etiquetas", [])) or "—"
        grupos = " ".join(
            f"{g[0]}" if len(g) == 1 else f"{g[0]}–{g[-1]}" for g in a.get("grupos", [])
        )
        lineas.append(
            f"| {c['video']} | {c['n']} | `{etiquetas}` | {grupos} | "
            f"{', '.join(a.get('fuera', [])) or '—'} | {a.get('cortes_candado') or '—'} |"
        )
    lineas += [
        "",
        "Etiquetas: N nuevo, c continua, i introducción, x cierre, e entrevistador, o comentario.",
    ]
    lineas += ["", "## Equipo de operación y valores sin traducir", ""]
    for c in datos["corridas"]:
        lineas.append(
            f"- {c['video']} [{c['n']}]: {len(c.get('equipo_operacion', []))} elementos: "
            + "; ".join(c.get("equipo_operacion", []))
        )
        lineas += [f"  - sin traducir · {m}" for m in c.get("sin_traducir", [])]
    if datos.get("editados"):
        lineas += [
            "",
            "## SOP editados (RF-26)",
            "",
            "Medidos sin generar: el SOP que quedó tras la revisión en el editor. Unir pasos es "
            "válido; quitar pasos baja el denominador (ADR-025): ver la referencia cubierta.",
            "",
        ]
        lineas += [
            f"- {clave}: {e['pasos']} pasos, de `{e['origen']}`"
            for clave, e in datos["editados"].items()
        ]
    lineas += ["", "## Llamadas (segundos · tokens de salida · tokens/s)", ""]
    for c in datos["corridas"]:
        partes = [f"{x['etapa']} {x['s']} s · {x['tokens']} · {x['tok_s']}" for x in c["llamadas"]]
        lineas.append(f"- {c['video']} [{c['n']}]: " + "; ".join(partes))
    for clave, info in datos.get("idiomas", {}).items():
        lineas.append(
            f"\nIdioma de {clave}: `{info['codigo']}` (confianza {info['confianza']:.2f})"
        )
    for clave, comp in datos.get("completitud", {}).items():
        lineas += ["", f"## Cuadro resumen y tabla de pasos · {clave}", ""]
        lineas += [f"- {k}: {v}" for k, v in comp.items()]
    if datos.get("rnf05"):
        lineas += [
            "",
            "## Resumen RNF-05",
            "",
            "Principal: por tramos (dentro del tramo de un solo paso de referencia, ±"
            f"{TOLERANCIA_TRAMO_S:g} s, en orden). Secundarios: uno a uno (húngaro, más estricto) "
            "y cobertura en orden.",
            "",
            "| Corrida | Pasos generados | RNF-05 por tramos | Uno a uno | Cobertura en orden |",
            "|---|---|---|---|---|",
        ]
        for clave, rnf in datos["rnf05"].items():
            total = rnf.get("referencia_total", 6)
            cubiertos = rnf.get("cobertura_en_orden", [])
            lineas.append(
                f"| {clave} | {rnf['pasos_generados']} | {rnf.get('tramos_correctos')} "
                f"({rnf.get('tramos_pct')} %) | {rnf['correctos']} ({rnf['pct']} %) | "
                f"{len(cubiertos)} de {total} ({rnf.get('cobertura_pct')} %) |"
            )
    for clave, rnf in datos.get("rnf05", {}).items():
        lineas += [
            "",
            f"## RNF-05 · {clave}: por tramos {rnf.get('tramos_correctos')} de "
            f"{rnf['pasos_generados']} ({rnf.get('tramos_pct')} %); uno a uno {rnf['correctos']} "
            f"({rnf['pct']} %); referencia cubierta "
            f"{rnf['referencia_cubierta']} de {rnf.get('referencia_total', 6)}, faltan "
            f"{rnf['referencia_faltan']}; cubierta en orden {rnf.get('cobertura_en_orden')}",
            "",
            "| Paso | Nombre | Tramo s | Dentro del paso de ref. | Correcto (tramos) | "
            "Par uno a uno | Estado | Coseno | Fuera de orden | En su tramo | "
            "Correcto (uno a uno) |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for f in rnf["filas"]:
            lineas.append(
                f"| {f['paso']} | {f['nombre']} | {_tramo(f)} | "
                f"{f.get('ref_tramo') or '—'} | {'sí' if f.get('correcto_tramo') else 'no'} | "
                f"{f['referencia']} {f['nombre_referencia'] or ''} | {f['estado']} | "
                f"{f['similitud']} | {'sí' if f['fuera_de_orden'] else 'no'} | "
                f"{'sí' if f['en_tramo'] else 'no'} | {'sí' if f['correcto'] else 'no'} |"
            )
    if cruzado := datos.get("uso_cruzado"):
        lineas += [
            "",
            f"## Uso cruzado: {cruzado['video']} contra el SOP generado de {cruzado['sop_de']} "
            f"({cruzado['pasos_sop']} pasos, leído de JSON como en la biblioteca)",
            "",
            f"{cruzado['cumplimiento']} % · {cruzado['semaforo']} · conteo {cruzado['conteo']}",
            "",
            "| Paso del SOP | Estado | Paso del video | t | Fuera de orden |",
            "|---|---|---|---|---|",
        ]
        lineas += [
            f"| {f['paso_sop']} | {f['estado']} | {f['paso_video']} | {f['t']} | "
            f"{'sí' if f['fuera_de_orden'] else 'no'} |"
            for f in cruzado["filas"]
        ]
    return "\n".join(lineas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+", help="clave=ruta del video o de su analisis.json")
    parser.add_argument("--repeticiones", type=int, default=1)
    parser.add_argument("--referencia", type=Path, help="SOP escrito a mano (RNF-05)")
    parser.add_argument("--anotacion", type=Path, help="JSON de la anotación (tramos)")
    parser.add_argument("--validar", help="clave=ruta: video a validar contra el SOP generado")
    parser.add_argument("--docs", action="store_true", help="copia a docs/adr/datos/sop_generado/")
    parser.add_argument(
        "--candado", choices=("si", "no"), help="candado de la agrupación (por defecto SOP_CANDADO)"
    )
    parser.add_argument(
        "--sop-editado",
        action="append",
        default=[],
        metavar="CLAVE=ORIGEN",
        help="mide RNF-05 sobre un SOP corregido (sop_id o JSON) en lugar de generar uno",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    candado = settings.sop_candado if args.candado is None else args.candado == "si"
    pedido_cpu = settings.llm_dispositivo == "cpu"
    marca = datetime.now().strftime("%Y%m%d-%H%M")
    carpeta = SALIDA / marca
    carpeta.mkdir(parents=True, exist_ok=True)
    referencia = convertir_sop(args.referencia.read_text("utf-8")).sop if args.referencia else None
    editados = {c: (o, leer_sop_editado(o)) for c, o in ediciones(args.sop_editado).items()}
    anotaciones = json.loads(args.anotacion.read_text("utf-8")) if args.anotacion else {}
    gpu = get_hardware().gpu

    llm = ClienteLLM.desde_settings(settings)
    registro = Registro(llm)
    datos: dict[str, Any] = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "git": estado_git(),
        "configuracion": {
            "llm": settings.llm_model,
            "llm_dispositivo": settings.llm_dispositivo,
            "whisper": settings.whisper_modelo,
            "gpu": None if gpu is None else gpu.nombre,
            "prompt_agrupar": PROMPT_AGRUPAR,
            "candado": candado,
            "umbral_fusion": settings.umbral_fusion,
        },
        "corridas": [],
        "idiomas": {},
        "completitud": {},
        "rnf05": {},
        "editados": {c: {"origen": o, "pasos": len(x.pasos)} for c, (o, x) in editados.items()},
    }
    primero: tuple[str, SOP] | None = None
    try:
        if not llm.disponible(10):
            print(f"Ollama no responde o no tiene {llm.modelo}", file=sys.stderr)
            return 2
        _, datos["ollama_ps"] = confirmar_dispositivo(llm, pedido_cpu)
        print(datos["ollama_ps"], file=sys.stderr)
        for par in args.videos:
            clave, _, ruta = par.partition("=")
            analisis, _, _ = preparar(clave, Path(ruta), settings, carpeta)
            (carpeta / clave).mkdir(parents=True, exist_ok=True)
            (carpeta / clave / "analisis.json").write_text(
                analisis.model_dump_json(indent=2), "utf-8", newline="\n"
            )
            datos["idiomas"][clave] = analisis.idioma.model_dump()
            if clave in editados:
                # RF-26: el SOP corregido en el editor, sin generar otro.
                editado = editados[clave][1]
                datos["completitud"][f"{clave} (editado)"] = completitud(editado)
                if referencia is not None and clave in anotaciones:
                    datos["rnf05"][f"{clave} (editado)"] = comparar(
                        editado, referencia, analisis, anotaciones[clave], llm
                    )
                print(f"{clave}: SOP editado, {len(editado.pasos)} pasos", file=sys.stderr)
                primero = primero or (f"{clave} (editado)", editado)  # --validar lo usa
                continue
            for n in range(1, args.repeticiones + 1):
                corrida, generado = generar(clave, n, analisis, llm, registro, pedido_cpu, candado)
                nombre = f"{clave}-{n}{'-cpu' if pedido_cpu else ''}.json"
                (carpeta / nombre).write_text(
                    json.dumps(
                        {
                            "sop": generado.sop.model_dump(mode="json"),
                            "advertencias": [a.model_dump() for a in generado.advertencias],
                            "generacion": generado.generacion.model_dump(mode="json"),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    "utf-8",
                    newline="\n",
                )
                corrida.archivo_sop = nombre
                datos["corridas"].append(corrida.__dict__)
                print(
                    f"{clave} [{n}]: {corrida.pasos_video} pasos del video → {corrida.pasos_sop} "
                    f"del SOP, {corrida.segundos['total_gemma']} s ({corrida.dispositivo}), "
                    f"grupos {corrida.agrupacion['grupos']}, cortes "
                    f"{corrida.agrupacion['cortes_candado']}",
                    file=sys.stderr,
                )
                if n == 1:
                    datos["completitud"][clave] = completitud(generado.sop)
                    primero = primero or (clave, generado.sop)
                if referencia is not None and clave in anotaciones:
                    datos["rnf05"][f"{clave} [{n}]"] = comparar(
                        generado.sop, referencia, analisis, anotaciones[clave], llm
                    )
        if args.validar and primero is not None:
            clave, _, ruta = args.validar.partition("=")
            analisis, segundos, dispositivos = preparar(clave, Path(ruta), settings, carpeta)
            llm.descargar()
            # Como lo guarda la biblioteca (`sops.contenido`) y lo lee la validación.
            de_biblioteca = SOP.model_validate(primero[1].model_dump(mode="json"))
            validacion = validar(
                analisis,
                de_biblioteca,
                DependenciasValidacion(llm, JuezGemma(llm)),
                segundos_analisis=segundos,
                dispositivos=dispositivos or Dispositivos(),
            )
            r = validacion.resultado
            pasos = r.resultado.clasificacion.pasos
            datos["uso_cruzado"] = {
                "video": clave,
                "sop_de": primero[0],
                "pasos_sop": len(de_biblioteca.pasos),
                "cumplimiento": round(r.cumplimiento, 2),
                "semaforo": r.semaforo,
                "conteo": dict(r.resultado.clasificacion.resumen.conteo),
                "filas": [
                    {
                        "paso_sop": None if p.indice_sop is None else p.indice_sop + 1,
                        "estado": p.estado + (f" ({p.marco_operador})" if p.marco_operador else ""),
                        "paso_video": None if p.indice_video is None else p.indice_video + 1,
                        "t": p.t_inicio,
                        "fuera_de_orden": p.fuera_de_orden,
                    }
                    for p in pasos
                ],
            }
    finally:
        llm.close()

    texto = informe(datos)
    sufijo = "-cpu" if pedido_cpu else ""
    destinos = [carpeta] + ([DOCS] if args.docs else [])
    for destino in destinos:
        destino.mkdir(parents=True, exist_ok=True)
        base = f"sop-generado-{marca}{sufijo}"
        (destino / f"{base}.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n"
        )
        (destino / f"{base}.md").write_text(texto, "utf-8", newline="\n")
        if destino == DOCS:
            for c in datos["corridas"]:
                (DOCS / f"{marca}-{c['archivo_sop']}").write_text(
                    (carpeta / c["archivo_sop"]).read_text("utf-8"),
                    "utf-8",
                    newline="\n",
                )
    print(texto)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
