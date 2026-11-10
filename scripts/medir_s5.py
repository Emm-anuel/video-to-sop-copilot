r"""Medición de cierre de S5: los videos A–E de la §14 y los tiempos de RNF-01, con y sin GPU.

No mide nada nuevo: arma los scripts existentes en una sola corrida y deja una tabla de
aceptación. Cada repetición es la ruta completa, como en el procesador: Whisper (`preparar`), y
luego `validar` (A–D) o el modo generar (E: ficha → pasos → `generar_sop`), siempre con
segmentación nueva y con Gemma descargado antes de empezar (carga en frío, como la API).

Criterios por corrida (§14 del documento; una corrida no válida, con la segmentación de respaldo
o con avisos, cuenta como FALLA):

- A: ≥ `SEMAFORO_VERDE` y sin *Falta* (`medir_dispositivos.criterio`); afinidad ≥
  `AFINIDAD_MIN`; cero responsables *distinto*; cero *excede*.
- B: *Falta* exactamente en 2 y 6; un *Sobra* (la limpieza) dentro de su tramo anotado y ninguno
  más fuera de la intro y el cierre; 66.67 %.
- C: *fuera de orden* en 2 y 5; *distinto* solo en 4 y afinidad ≥ `AFINIDAD_MIN`
  (`medir_afinidad.criterio`); *excede* solo en 1 (`medir_tiempos.criterio`). Aparte, sin contar
  como falla: los *Sobra* y si alguno es el fragmento ya conocido ("Ahora entra mi compañera…").
- D: afinidad < `AFINIDAD_MIN`, detenida antes de segmentar y, al continuar, los 6 pasos del SOP
  en *Falta* (`medir_afinidad.criterio`).
- E (generar): idioma "en"; cuadro resumen y tabla de pasos llenos (`medir_sop_generado.
  completitud` y los campos de cada paso); cero advertencias `sin_traducir`; RNF-05 por tramos
  ≥ 80 % (`medir_sop_generado.comparar`). Secundarios: uno a uno, cobertura en orden y elementos
  de `equipo_operacion`.

Reproducibilidad (solo en la fase gpu): la primera corrida de A se regenera
`--regeneraciones` veces con su ficha y su segmentación (`POST /videos/{id}/validar`, ADR-022);
el porcentaje debe salir igual.

Tres modos, desde la raíz del repo y con el entorno activado:

    # Ollama en GPU (docker-compose.gpu.yml, profile llm) y sin otra API usando la GPU
    python scripts/medir_s5.py --fase gpu
    # Sin GPU: una corrida de A y una de E
    LLM_DISPOSITIVO=cpu WHISPER_DISPOSITIVO=cpu python scripts/medir_s5.py --fase cpu
    # Une las dos fases en docs/adr/datos/s5/medicion-s5-<fecha>.{md,json}
    python scripts/medir_s5.py --informe data/interim/s5/<gpu>.json data/interim/s5/<cpu>.json

Antes de medir, cada fase carga Gemma y pregunta a Ollama dónde quedó
(`medir_sop_generado.confirmar_dispositivo`); si no es donde se pidió, sale con código 3 sin
medir. Lo mismo después de cada corrida, guardando lo medido hasta ahí.

Las fases escriben en `data/interim/s5/` (ignorada por git). El informe lleva números, estados,
segundos, la ficha corta y citas cortas de los *Sobra* de C; los videos son del equipo, no del
cliente. No modifica código, datos de entrada ni la base.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from medir_afinidad import criterio as criterio_afinidad
from medir_afinidad import ficha, resumen_validacion
from medir_dispositivos import META_RNF01_S, VIDEO_RNF01_S, Muestreo, esperado_de
from medir_dispositivos import criterio as criterio_mvp
from medir_mvp import estado_git, preparar, sobra_falsos
from medir_reproducibilidad import comparable, huella
from medir_sop_generado import (
    GPU_NO_CONFIRMADA,
    Registro,
    comparar,
    completitud,
    confirmar_dispositivo,
    generar,
)
from medir_tiempos import criterio as criterio_tiempos
from medir_tiempos import excede_esperados, filas_de, tramos_anotados

from sopvid.contrato import SOP
from sopvid.lenguaje.emparejamiento import get_embedder
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.lenguaje.validacion import DependenciasValidacion, Detenida, Validacion, validar
from sopvid.plataforma.config import PROJECT_ROOT, Settings, get_settings
from sopvid.plataforma.hardware import get_hardware

SALIDA = PROJECT_ROOT / "data" / "interim" / "s5"
DOCS = PROJECT_ROOT / "docs" / "adr" / "datos" / "s5"
SOP_REFERENCIA = PROJECT_ROOT / "tests" / "fixtures" / "sop_filtro_agua.md"
ANOTACION = PROJECT_ROOT / "media" / "anotacion_ab.json"
VIDEOS = {
    "video_a": PROJECT_ROOT / "media" / "videos" / "VIDEO-A.mp4",
    "video_b": PROJECT_ROOT / "media" / "videos" / "VIDEO-B.mp4",
    "video_c": PROJECT_ROOT / "data" / "synthetic" / "video_c" / "VIDEO-C.mp4",
    "video_d": PROJECT_ROOT / "data" / "synthetic" / "video_d" / "VIDEO-D.mp4",
    "video_e": PROJECT_ROOT / "data" / "synthetic" / "video_e" / "VIDEO-E.mp4",
}
GENERAR = {"video_e"}
REPETICIONES = {
    "gpu": {"video_a": 3, "video_b": 3, "video_c": 3, "video_d": 3, "video_e": 2},
    "cpu": {"video_a": 1, "video_e": 1},
}
FUERA_DE_ORDEN_C = [2, 5]
PORCENTAJE_B = 66.67
RNF05_MIN = 80.0
# Settings que se publican en el informe (sin URLs, claves ni rutas).
SETTINGS_PUBLICOS = (
    "whisper_modelo",
    "whisper_modelo_cpu",
    "whisper_dispositivo",
    "whisper_compute_type",
    "llm_model",
    "llm_dispositivo",
    "llm_num_ctx",
    "llm_num_ctx_sop",
    "llm_timeout_s",
    "embedder_model",
    "umbral_bajo",
    "umbral_alto",
    "umbral_fusion",
    "sop_candado",
    "umbral_equipo",
    "semaforo_verde",
    "semaforo_amarillo",
    "afinidad_min",
    "afinidad_cos_cero",
    "afinidad_cos_cien",
    "afinidad_umbral_equipo",
    "tolerancia_tiempo",
    "umbral_rol",
    "umbral_rol_complemento",
    "umbral_horario",
)

logger = logging.getLogger("medir_s5")


# ── Utilidades ───────────────────────────────────────────────────────────────────────────────


def chequeo(nombre: str, pasa: bool, obtenido: Any, esperado: Any) -> dict[str, Any]:
    return {"nombre": nombre, "pasa": bool(pasa), "obtenido": obtenido, "esperado": esperado}


def git_detalle() -> dict[str, Any]:
    """`estado_git` más la lista de archivos con cambios sin commit."""
    datos = estado_git()
    try:
        salida = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
        datos["archivos_sin_commit"] = [linea.rstrip() for linea in salida.splitlines() if linea]
    except (OSError, subprocess.SubprocessError):
        datos["archivos_sin_commit"] = None
    return datos


def llamadas_de(registro: Registro) -> list[dict[str, Any]]:
    return [
        {"etapa": x.etapa, "s": x.segundos, "tokens": x.tokens_salida, "tok_s": x.tokens_por_s}
        for x in registro.llamadas
    ]


def resumen_tokens(llamadas: list[dict[str, Any]]) -> dict[str, Any]:
    tokens = [x["tokens"] for x in llamadas if x.get("tokens")]
    velocidades = [x["tok_s"] for x in llamadas if x.get("tok_s")]
    return {
        "llamadas": len(llamadas),
        "tokens_salida": sum(tokens),
        "tok_s_medio": round(statistics.mean(velocidades), 1) if velocidades else None,
    }


def tiempos_rnf01(total_s: float, duracion_s: float) -> dict[str, float | None]:
    factor = total_s / duracion_s if duracion_s else None
    return {
        "total_s": round(total_s, 1),
        "factor": None if factor is None else round(factor, 3),
        "estimado_10_min_s": None if factor is None else round(factor * VIDEO_RNF01_S, 1),
    }


# ── Validar (A–D) ────────────────────────────────────────────────────────────────────────────


def sobras_de(v: Validacion) -> list[dict[str, Any]]:
    """Los *Sobra* fuera de la intro y el cierre, con su segundo y una cita corta."""
    res = v.resultado.resultado
    sobras = []
    for paso in res.clasificacion.pasos:
        if paso.estado != "Sobra" or paso.marco_operador is not None:
            continue
        video = res.pasos_video[paso.indice_video] if paso.indice_video is not None else None
        texto = "" if video is None else f"{video.cita} {video.descripcion}"
        sobras.append(
            {
                "t": paso.t_inicio,
                "cita": "" if video is None else video.cita[:80],
                "conocido_compañera": "compañera" in texto.lower(),
            }
        )
    return sobras


def chequeos_validar(
    clave: str,
    v: Validacion,
    afinidad: Any,
    detenida: bool,
    antes_de_segmentar: bool,
    sop: SOP,
    anotacion: dict[str, Any],
    duracion_s: float,
    settings: Settings,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Los criterios de la §14 para A–D, cada uno con lo obtenido y lo esperado, y los datos que
    se informan aparte (no cuentan como falla)."""
    g = v.resultado
    resumen = resumen_validacion(v, sop)
    a = None if afinidad is None else afinidad.model_dump(mode="json")
    corrida_afinidad = {"afinidad": a, "validacion": resumen, "detenida": detenida}
    distintos = sorted(
        f["paso_sop"]
        for f in resumen["filas"]
        if f.get("responsable", {}).get("estado") == "distinto"
    )
    filas_t = filas_de(v, sop, tramos_anotados(anotacion, duracion_s))
    excede = sorted(f["paso_sop"] for f in filas_t if f.get("tiempo", {}).get("estado") == "excede")
    esperado = esperado_de(anotacion, sop, duracion_s)
    mvp = criterio_mvp(g, sop, esperado, settings)
    falsos = sobra_falsos(g, esperado)
    minimo = settings.afinidad_min
    valor = None if a is None else a["valor"]
    ch: list[dict[str, Any]] = []
    extra: dict[str, Any] = {}
    if clave == "video_a":
        ch.append(
            chequeo(
                "verde y sin Falta",
                mvp["pasa"],
                round(g.cumplimiento, 2),
                f"≥ {settings.semaforo_verde}, Falta []",
            )
        )
        ch.append(chequeo("afinidad", valor is not None and valor >= minimo, valor, f"≥ {minimo}"))
        ch.append(chequeo("responsables distinto", not distintos, distintos, []))
        ch.append(chequeo("excede", criterio_tiempos([], filas_t, True)[0], excede, []))
    elif clave == "video_b":
        ch.append(chequeo("Falta", mvp["falta_obtenida"] == [2, 6], mvp["falta_obtenida"], [2, 6]))
        ch.append(
            chequeo(
                "Sobra de la limpieza en su tramo",
                mvp["extras_encontrados"] == "1/1" and not falsos,
                {
                    "en_tramo": mvp["extras_encontrados"],
                    "otros_sobra_s": [round(t, 1) for t in falsos],
                },
                {"en_tramo": "1/1", "otros_sobra_s": []},
            )
        )
        ch.append(
            chequeo(
                "cumplimiento",
                abs(g.cumplimiento - PORCENTAJE_B) < 0.01,
                round(g.cumplimiento, 2),
                PORCENTAJE_B,
            )
        )
        extra["sobras"] = sobras_de(v)
    elif clave == "video_c":
        fuera = sorted(f["paso_sop"] for f in resumen["filas"] if f["fuera_de_orden"])
        ch.append(chequeo("fuera de orden", fuera == FUERA_DE_ORDEN_C, fuera, FUERA_DE_ORDEN_C))
        pasa_af, motivos = criterio_afinidad("distinto", corrida_afinidad, anotacion, sop, minimo)
        ch.append(
            chequeo(
                "afinidad y distinto",
                pasa_af,
                {"afinidad": valor, "distinto": distintos},
                {"afinidad": f"≥ {minimo}", "distinto": [4]},
            )
        )
        esperados = excede_esperados(anotacion)
        ch.append(
            chequeo("excede", criterio_tiempos(esperados, filas_t, True)[0], excede, esperados)
        )
        extra["sobras"] = sobras_de(v)
        if not pasa_af:
            extra["motivos_afinidad"] = motivos
    elif clave == "video_d":
        pasa_af, motivos = criterio_afinidad(
            "otro_procedimiento", corrida_afinidad, anotacion, sop, minimo
        )
        ch.append(
            chequeo(
                "afinidad baja, detenida y 6 Falta al continuar",
                pasa_af,
                {"afinidad": valor, "detenida": detenida, "falta": resumen["conteo"]["Falta"]},
                {"afinidad": f"< {minimo}", "detenida": True, "falta": len(sop.pasos)},
            )
        )
        ch.append(
            chequeo("detenida antes de segmentar", antes_de_segmentar, antes_de_segmentar, True)
        )
        if not pasa_af:
            extra["motivos_afinidad"] = motivos
    extra["roles"] = [f"{r['rol']}: {r['estado']}" for r in resumen["roles"]]
    extra["excede"] = excede
    extra["distinto"] = distintos
    return ch, extra


def correr_validar(
    clave: str,
    n: int,
    ruta: Path,
    sop: SOP,
    anotacion: dict[str, Any],
    settings: Settings,
    fase: str,
    trabajo: Path,
    embedder: Any,
) -> tuple[dict[str, Any], Validacion | None, Any]:
    """Una validación de punta a punta. Devuelve la corrida, la `Validacion` y el `Analisis`
    (None si falló)."""
    corrida: dict[str, Any] = {"video": clave, "n": n, "fase": fase, "modo": "validar"}
    deps = DependenciasValidacion.desde_settings(settings)
    deps.embedder = embedder
    registro = Registro(deps.llm)
    etapa = "transcripcion"

    def al_avanzar(nombre: str, _pct: int) -> None:
        nonlocal etapa
        etapa = registro.etapa = nombre

    v: Validacion | None = None
    analisis = None
    try:
        deps.llm.descargar()  # carga en frío, como la API
        with Muestreo(con_gpu=get_hardware().gpu is not None) as muestreo:
            inicio = time.perf_counter()
            analisis, segundos, dispositivos = preparar(
                clave, ruta, settings, trabajo / fase / f"{clave}-{n}"
            )
            corrida["duracion_s"] = analisis.duracion_s
            etapa = "contexto"
            resultado = validar(
                analisis,
                sop,
                deps,
                al_avanzar=al_avanzar,
                segundos_analisis=segundos,
                dispositivos=dispositivos,
            )
            detenida = isinstance(resultado, Detenida)
            antes_de_segmentar = True
            if detenida:
                d = resultado.detencion
                afinidad = d.afinidad
                antes_de_segmentar = "segmentacion" not in d.segundos
                corrida["hasta_detencion_s"] = round(time.perf_counter() - inicio, 1)
                corrida["segundos_detencion"] = d.segundos
                corrida["dispositivos_detencion"] = (
                    d.dispositivos.model_dump(mode="json") if d.dispositivos else {}
                )
                etapa = "continuar"
                resultado = validar(
                    analisis,
                    sop,
                    deps,
                    al_avanzar=al_avanzar,
                    dispositivos=dispositivos,
                    contexto=resultado.contexto,
                    continuar=True,
                )
            total = time.perf_counter() - inicio
        assert isinstance(resultado, Validacion)
        v = resultado
        g = v.resultado
        if not detenida:
            afinidad = g.afinidad
        res = g.resultado
        meta = g.metadatos
        valida = meta.segmentacion == "llm" and not meta.avisos
        chequeos, extra = chequeos_validar(
            clave,
            v,
            afinidad,
            detenida,
            antes_de_segmentar,
            sop,
            anotacion,
            analisis.duracion_s,
            settings,
        )
        if not valida:
            chequeos.insert(
                0,
                chequeo(
                    "corrida válida",
                    False,
                    {"segmentacion": meta.segmentacion, "avisos": [a.tipo for a in meta.avisos]},
                    {"segmentacion": "llm", "avisos": []},
                ),
            )
        llamadas = llamadas_de(registro)
        corrida |= {
            "cumplimiento": round(g.cumplimiento, 2),
            "semaforo": g.semaforo,
            "conteo": dict(res.clasificacion.resumen.conteo),
            "afinidad": None if afinidad is None else afinidad.valor,
            "detenida": detenida,
            "pasos_video_antes": len(v.pasos_video),
            "pasos_video_despues": len(res.pasos_video),
            "rescatados": res.clasificacion.resumen.rescatados,
            "rescate": any(f.rescate for f in res.fusiones),
            "segundos": meta.segundos,
            "dispositivos": meta.dispositivos.model_dump(mode="json") if meta.dispositivos else {},
            "llamadas": llamadas,
            "tokens": resumen_tokens(llamadas),
            "vram_base_mib": muestreo.vram_base_mb,
            "vram_pico_mib": muestreo.vram_mb,
            "valida": valida,
            "chequeos": chequeos,
            "datos": extra,
            "ficha": ficha(v.contexto),
            "pasa": all(c["pasa"] for c in chequeos),
        } | tiempos_rnf01(total, analisis.duracion_s)
    except Exception as exc:  # se anota y se sigue con la siguiente corrida
        corrida |= {
            "error": f"{type(exc).__name__}: {exc}",
            "etapa_error": etapa,
            "traza": traceback.format_exc(limit=4),
            "pasa": False,
        }
        logger.error("%s #%d falló en %s: %s", clave, n, etapa, corrida["error"])
    finally:
        deps.cerrar()
    return corrida, v, analisis


def reproducibilidad(
    v: Validacion, analisis: Any, sop: SOP, settings: Settings, embedder: Any, veces: int
) -> dict[str, Any]:
    """Regenera el reporte de `v` con su ficha y su segmentación (ADR-022), sin Whisper."""
    original = v.resultado
    dispositivos = original.metadatos.dispositivos
    regeneradas = []
    for _ in range(veces):
        deps = DependenciasValidacion.desde_settings(settings)
        deps.embedder = embedder
        try:
            deps.llm.descargar()
            otra = validar(
                analisis,
                sop,
                deps,
                dispositivos=dispositivos,
                contexto=v.contexto,
                segmentacion=v.segmentacion,
                continuar=True,
            )
            assert isinstance(otra, Validacion)
            regeneradas.append(
                {
                    "cumplimiento": round(otra.resultado.cumplimiento, 2),
                    "huella": huella(comparable(otra.resultado)),
                    "reusada": otra.resultado.metadatos.segmentacion_reusada,
                    "segundos": otra.resultado.metadatos.segundos,
                }
            )
        except Exception as exc:
            regeneradas.append({"error": f"{type(exc).__name__}: {exc}"})
        finally:
            deps.cerrar()
    porcentajes = {round(original.cumplimiento, 2)} | {
        r["cumplimiento"] for r in regeneradas if "cumplimiento" in r
    }
    return {
        "original": {
            "cumplimiento": round(original.cumplimiento, 2),
            "huella": huella(comparable(original)),
        },
        "regeneradas": regeneradas,
        "mismo_porcentaje": len(porcentajes) == 1 and all("error" not in r for r in regeneradas),
        "huellas_regeneradas_iguales": len({r.get("huella") for r in regeneradas}) == 1,
    }


# ── Generar (E) ──────────────────────────────────────────────────────────────────────────────


def faltantes_sop(sop: SOP, comp: dict[str, Any]) -> list[str]:
    """Qué del cuadro resumen o de la tabla de pasos quedó vacío."""
    faltan = [
        campo
        for campo in ("titulo", "objetivo", "alcance", "lugar", "horario", "responsable")
        if not comp.get(campo)
    ]
    faltan += [
        campo for campo in ("roles", "equipo", "riesgos", "en_caso_de_falla") if not comp.get(campo)
    ]
    if comp.get("duracion_total_min") is None:
        faltan.append("duracion_total_min")
    if comp["pasos_en_infinitivo"] != comp["pasos"]:
        faltan.append(f"infinitivo {comp['pasos_en_infinitivo']}/{comp['pasos']}")
    for p in sop.pasos:
        vacios = [
            c
            for c, valor in (
                ("descripcion", p.descripcion),
                ("responsable", p.responsable),
                ("t_inicio", p.t_inicio),
                ("t_fin", p.t_fin),
                ("cita", p.cita),
            )
            if valor in (None, "")
        ]
        if vacios:
            faltan.append(f"paso {p.numero}: {', '.join(vacios)}")
    return faltan


def correr_generar(
    clave: str,
    n: int,
    ruta: Path,
    referencia: SOP,
    anotacion: dict[str, Any],
    settings: Settings,
    fase: str,
    trabajo: Path,
) -> dict[str, Any]:
    corrida: dict[str, Any] = {"video": clave, "n": n, "fase": fase, "modo": "generar"}
    llm = ClienteLLM.desde_settings(settings)
    registro = Registro(llm)
    pedido_cpu = settings.llm_dispositivo == "cpu"
    etapa = "transcripcion"
    try:
        llm.descargar()
        with Muestreo(con_gpu=get_hardware().gpu is not None) as muestreo:
            inicio = time.perf_counter()
            analisis, segundos, dispositivos = preparar(
                clave, ruta, settings, trabajo / fase / f"{clave}-{n}"
            )
            etapa = "generar"
            # `generar` sale con GPU_NO_CONFIRMADA si Gemma no quedó donde se pidió.
            gen, generado = generar(
                clave, n, analisis, llm, registro, pedido_cpu, settings.sop_candado
            )
            total = time.perf_counter() - inicio
        etapa = "rnf05"
        registro.etapa = "rnf05"
        t = time.perf_counter()
        rnf05 = comparar(generado.sop, referencia, analisis, anotacion, llm)
        segundos_rnf05 = round(time.perf_counter() - t, 1)
        comp = completitud(generado.sop)
        faltan = faltantes_sop(generado.sop, comp)
        chequeos = [
            chequeo("idioma", analisis.idioma.codigo == "en", analisis.idioma.codigo, "en"),
            chequeo("cuadro resumen y tabla de pasos llenos", not faltan, faltan, []),
            chequeo(
                "sin valores en inglés (sin_traducir)", not gen.sin_traducir, gen.sin_traducir, []
            ),
            chequeo(
                "RNF-05 por tramos",
                rnf05["tramos_pct"] >= RNF05_MIN,
                rnf05["tramos_pct"],
                f"≥ {RNF05_MIN}",
            ),
        ]
        llamadas = gen.llamadas
        corrida |= {
            "duracion_s": analisis.duracion_s,
            "idioma": analisis.idioma.model_dump(),
            "pasos_video_antes": gen.pasos_video,
            "pasos_sop": gen.pasos_sop,
            "grupos": gen.agrupacion.get("grupos"),
            "segundos": segundos | gen.segundos,
            "segundos_rnf05_fuera_de_rnf01": segundos_rnf05,
            "dispositivos": dispositivos.model_copy(update={"llm": gen.dispositivo}).model_dump(
                mode="json"
            ),
            "llamadas": llamadas,
            "tokens": resumen_tokens(llamadas),
            "vram_base_mib": muestreo.vram_base_mb,
            "vram_pico_mib": muestreo.vram_mb,
            "vram_con_modelo_mib": gen.vram_mib,
            "chequeos": chequeos,
            "datos": {
                "rnf05_tramos": f"{rnf05['tramos_correctos']}/{rnf05['pasos_generados']} "
                f"({rnf05['tramos_pct']} %)",
                "uno_a_uno": f"{rnf05['correctos']}/{rnf05['pasos_generados']} ({rnf05['pct']} %)",
                "cobertura_en_orden": f"{len(rnf05['cobertura_en_orden'])}/"
                f"{rnf05['referencia_total']} ({rnf05['cobertura_pct']} %)",
                "equipo_operacion": len(gen.equipo_operacion),
                "equipo_operacion_nombres": gen.equipo_operacion,
                "pasos_generados": [p.nombre for p in generado.sop.pasos],
                "completitud": comp,
            },
            "pasa": all(c["pasa"] for c in chequeos),
        } | tiempos_rnf01(total, analisis.duracion_s)
    except Exception as exc:
        corrida |= {
            "error": f"{type(exc).__name__}: {exc}",
            "etapa_error": etapa,
            "traza": traceback.format_exc(limit=4),
            "pasa": False,
        }
        logger.error("%s #%d falló en %s: %s", clave, n, etapa, corrida["error"])
    finally:
        llm.close()
    return corrida


# ── Una fase ─────────────────────────────────────────────────────────────────────────────────


def guardar(datos: dict[str, Any], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n")


def fase(args: argparse.Namespace) -> int:
    settings = get_settings()
    pedido_cpu = settings.llm_dispositivo == "cpu"
    if (args.fase == "cpu") != pedido_cpu or (
        args.fase == "cpu" and settings.whisper_dispositivo != "cpu"
    ):
        print(
            f"--fase {args.fase} con LLM_DISPOSITIVO={settings.llm_dispositivo} y "
            f"WHISPER_DISPOSITIVO={settings.whisper_dispositivo}: no cuadra",
            file=sys.stderr,
        )
        return 2
    sop = convertir_sop(SOP_REFERENCIA.read_text(encoding="utf-8")).sop
    anotaciones = json.loads(ANOTACION.read_text(encoding="utf-8"))
    repeticiones = dict(REPETICIONES[args.fase])
    if args.videos:
        repeticiones = {v: repeticiones.get(v, 1) for v in args.videos}
    if args.repeticiones:
        repeticiones = dict.fromkeys(repeticiones, args.repeticiones)
    marca = datetime.now().strftime("%Y%m%d-%H%M")
    salida = SALIDA / f"s5-{marca}-{args.fase}.json"
    trabajo = SALIDA / marca
    gpu = get_hardware().gpu
    datos: dict[str, Any] = {
        "fase": args.fase,
        "inicio": datetime.now().isoformat(timespec="seconds"),
        "git": git_detalle(),
        "settings": {k: getattr(settings, k) for k in SETTINGS_PUBLICOS},
        "gpu": None if gpu is None else gpu.nombre,
        "repeticiones": repeticiones,
        "corridas": [],
        "reproducibilidad": None,
    }
    llm = ClienteLLM.desde_settings(settings)
    try:
        if not llm.disponible(10):
            print(f"Ollama no responde en {llm.base_url} o no tiene {llm.modelo}", file=sys.stderr)
            return 2
        # Sale con código 3 si Gemma no quedó donde se pidió.
        datos["dispositivo_gemma"], datos["ollama_ps"] = confirmar_dispositivo(llm, pedido_cpu)
    finally:
        llm.close()
    print(datos["ollama_ps"], file=sys.stderr)
    embedder = get_embedder()
    # MiniLM se carga una vez por proceso, como en la API (que lo mantiene entre trabajos): sin
    # esto, la primera corrida paga ~20 s de carga en "afinidad".
    embedder.embed(["calentar"])
    esperado_llm = "cpu" if pedido_cpu else "gpu"
    inicio_fase = time.perf_counter()
    for clave, veces in repeticiones.items():
        ruta = VIDEOS[clave]
        for n in range(1, veces + 1):
            print(f"{args.fase} · {clave} [{n}/{veces}]…", file=sys.stderr)
            if clave in GENERAR:
                corrida = correr_generar(
                    clave, n, ruta, sop, anotaciones[clave], settings, args.fase, trabajo
                )
                v = analisis = None
            else:
                corrida, v, analisis = correr_validar(
                    clave, n, ruta, sop, anotaciones[clave], settings, args.fase, trabajo, embedder
                )
            datos["corridas"].append(corrida)
            guardar(datos, salida)
            llm_en = corrida.get("dispositivos", {}).get("llm")
            print(
                f"  {corrida.get('cumplimiento', '—')} % · {corrida.get('total_s', '—')} s · "
                f"Gemma {llm_en} · {'PASA' if corrida['pasa'] else 'FALLA'}"
                + (f" · {corrida['error']}" if "error" in corrida else ""),
                file=sys.stderr,
            )
            if llm_en is not None and llm_en != esperado_llm:
                print(
                    f"Gemma quedó en {llm_en} y se esperaba {esperado_llm}: se detiene",
                    file=sys.stderr,
                )
                return GPU_NO_CONFIRMADA
            if clave == "video_a" and n == 1 and v is not None and args.fase == "gpu":
                print("  reproducibilidad con A·1…", file=sys.stderr)
                datos["reproducibilidad"] = reproducibilidad(
                    v, analisis, sop, settings, embedder, args.regeneraciones
                )
                guardar(datos, salida)
    datos["fin"] = datetime.now().isoformat(timespec="seconds")
    datos["segundos_fase"] = round(time.perf_counter() - inicio_fase, 1)
    guardar(datos, salida)
    print(f"escrito: {salida}", file=sys.stderr)
    return 0


# ── Informe ──────────────────────────────────────────────────────────────────────────────────

NOMBRE = {"video_a": "A", "video_b": "B", "video_c": "C", "video_d": "D", "video_e": "E"}


def _f(valor: Any, fmt: str = "g") -> str:
    return "—" if valor is None else format(valor, fmt)


def _v(valor: Any) -> Any:
    return round(valor, 2) if isinstance(valor, float) else valor


def _resumen_tiempos(corridas: list[dict[str, Any]]) -> dict[str, Any]:
    validas = [c for c in corridas if "total_s" in c]
    if not validas:
        return {}
    totales = [c["total_s"] for c in validas]
    factores = [c["factor"] for c in validas]
    estimados = [c["estimado_10_min_s"] for c in validas]
    return {
        "duracion_s": validas[0]["duracion_s"],
        "corridas": len(validas),
        "total_medio_s": round(statistics.mean(totales), 1),
        "total_min_s": min(totales),
        "total_max_s": max(totales),
        "factor_medio": round(statistics.mean(factores), 3),
        "estimado_10_min_s": round(statistics.mean(estimados), 1),
        "estimado_10_min_max_s": max(estimados),
        "cumple_rnf01": max(estimados) < META_RNF01_S,
    }


def armar_informe(fases: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    por_fase = {f["fase"]: f for f in fases}
    base = por_fase.get("gpu") or fases[0]
    git, s = base["git"], base["settings"]
    tiempos: dict[str, dict[str, Any]] = {}
    for f in fases:
        for clave in REPETICIONES[f["fase"]]:
            grupo = [c for c in f["corridas"] if c["video"] == clave]
            if grupo:
                tiempos.setdefault(f["fase"], {})[clave] = _resumen_tiempos(grupo)
    fallos = [
        {
            "fase": c["fase"],
            "video": NOMBRE[c["video"]],
            "n": c["n"],
            "etapa": c.get("etapa_error", "criterio"),
            "que": c.get("error")
            or "; ".join(
                f"{x['nombre']}: {_v(x['obtenido'])} (esperado {x['esperado']})"
                for x in c.get("chequeos", [])
                if not x["pasa"]
            ),
        }
        for f in fases
        for c in f["corridas"]
        if not c["pasa"]
    ]
    datos = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "git": git,
        "settings": s,
        "gpu": base["gpu"],
        "meta_rnf01": {"video_s": VIDEO_RNF01_S, "limite_s": META_RNF01_S},
        "fases": fases,
        "tiempos": tiempos,
        "fallos": fallos,
    }
    sin_commit = git.get("archivos_sin_commit") or []
    lineas = [
        f"# Medición de cierre de S5 · {datos['fecha']}",
        "",
        "Videos A–E de la §14 del documento SOP V1.0 y tiempos de RNF-01 con y sin GPU "
        "(`scripts/medir_s5.py`). Cada corrida es la ruta completa (Whisper → validar o generar) "
        "con segmentación nueva y Gemma en frío.",
        "",
        "## Cómo se midió",
        "",
        f"- Commit `{git.get('commit')}` en `{git.get('rama')}` · "
        f"{len(sin_commit)} archivo(s) con cambios sin commit"
        + (": " + ", ".join(f"`{x.strip()}`" for x in sin_commit) if sin_commit else "")
        + ".",
        f"- Whisper `{s['whisper_modelo']}` (CPU: `{s['whisper_modelo_cpu']}`) · LLM "
        f"`{s['llm_model']}` · embedder `{s['embedder_model']}` · GPU {base['gpu'] or 'ninguna'}.",
        "- Umbrales (Settings): "
        + ", ".join(
            f"`{k}`={v}" for k, v in s.items() if not k.startswith(("whisper", "llm", "embedder"))
        )
        + ".",
    ]
    for f in fases:
        lineas += [
            "",
            f"Fase **{f['fase']}** ({f['inicio']} → {f.get('fin', 'sin terminar')}, "
            f"{_f(f.get('segundos_fase'))} s) · "
            f"`LLM_DISPOSITIVO={f['settings']['llm_dispositivo']}` "
            f"· `WHISPER_DISPOSITIVO={f['settings']['whisper_dispositivo']}` · `ollama ps`:",
            "",
            "```",
            f.get("ollama_ps", ""),
            "```",
        ]
    lineas += [
        "",
        "## Aceptación (§14)",
        "",
        "| Video | Fase | Corridas que pasan | % por corrida | Resultado |",
        "|---|---|---|---|---|",
    ]
    for f in fases:
        for clave in REPETICIONES[f["fase"]]:
            grupo = [c for c in f["corridas"] if c["video"] == clave]
            if not grupo:
                continue
            pasan = sum(c["pasa"] for c in grupo)
            pcts = ", ".join(
                (
                    f"{_f(c.get('cumplimiento'))} %"
                    if c["modo"] == "validar"
                    else f"RNF-05 {c.get('datos', {}).get('rnf05_tramos', '—')}"
                )
                + f" {'PASA' if c['pasa'] else 'FALLA'}"
                for c in grupo
            )
            veredicto = "PASA" if pasan == len(grupo) else "FALLA"
            lineas.append(
                f"| {NOMBRE[clave]} | {f['fase']} | {pasan}/{len(grupo)} | {pcts} "
                f"| **{veredicto}** |"
            )
    lineas += ["", "### Criterios por corrida", ""]
    for f in fases:
        for c in f["corridas"]:
            cabeza = (
                f"- **{NOMBRE[c['video']]}·{c['n']} ({f['fase']})** "
                f"{'PASA' if c['pasa'] else 'FALLA'}"
            )
            if "error" in c:
                lineas.append(f"{cabeza} · error en `{c['etapa_error']}`: {c['error']}")
                continue
            lineas.append(cabeza)
            for x in c["chequeos"]:
                lineas.append(
                    f"  - {'✓' if x['pasa'] else '✗'} {x['nombre']}: {_v(x['obtenido'])} "
                    f"(esperado {x['esperado']})"
                )
            d = c.get("datos", {})
            if c["modo"] == "validar":
                lineas.append(
                    f"  - datos: afinidad {c['afinidad']}, conteo {c['conteo']}, pasos del video "
                    f"{c['pasos_video_antes']} → {c['pasos_video_despues']} al fusionar, rescate "
                    f"{'sí' if c['rescate'] else 'no'} ({c['rescatados']}), roles {d.get('roles')}"
                )
                if "sobras" in d and not d["sobras"]:
                    lineas.append(
                        "  - Sobra (sin intro ni cierre): ninguno"
                        + (
                            " (no salió el fragmento de «compañera»)"
                            if c["video"] == "video_c"
                            else ""
                        )
                    )
                for sobra in d.get("sobras", []):
                    lineas.append(
                        f"  - Sobra en {sobra['t']} s"
                        + (
                            " (el fragmento conocido de «compañera»; no cuenta)"
                            if sobra["conocido_compañera"]
                            else ""
                        )
                        + f": «{sobra['cita']}»"
                    )
            else:
                lineas.append(
                    f"  - datos: uno a uno {d['uno_a_uno']}, cobertura en orden "
                    f"{d['cobertura_en_orden']}, equipo_operacion {d['equipo_operacion']} "
                    f"elementos, {c['pasos_video_antes']} pasos del video → {c['pasos_sop']} "
                    "del SOP"
                )
    lineas += ["", "## Reproducibilidad (RNF-07, A·1 regenerado con su segmentación)", ""]
    r = (por_fase.get("gpu") or {}).get("reproducibilidad")
    if r:
        regs = ", ".join(
            x.get("error") or f"{x['cumplimiento']} % (huella {x['huella']})"
            for x in r["regeneradas"]
        )
        lineas += [
            f"Original {r['original']['cumplimiento']} % (huella {r['original']['huella']}); "
            f"regeneradas: {regs}.",
            "",
            f"**Mismo porcentaje: {'sí' if r['mismo_porcentaje'] else 'no'}** · huellas de las "
            f"regeneradas iguales entre sí: {'sí' if r['huellas_regeneradas_iguales'] else 'no'} "
            "(la redacción del juez puede variar, ADR-022).",
        ]
    else:
        lineas.append("No se midió.")
    lineas += [
        "",
        "## Tiempos (RNF-01: un video de 10 min en menos de 5 min)",
        "",
        "El factor es segundos de proceso ÷ segundos de video, de punta a punta (Whisper con su "
        "carga, ficha, pasos, emparejamiento con el juez o SOP generado). La extrapolación es "
        "lineal: sobrestima un poco, porque las cargas en frío no crecen con el video. MiniLM "
        "ya está cargado (como en la API); Whisper y Gemma se cargan en cada corrida. En D el "
        "total incluye la continuación (acción del usuario). RNF-05 de E no cuenta.",
        "",
        "| Fase | Video | Duración s | Corridas | Total medio s (mín–máx) | Factor "
        "| 10 min estimado | ¿Cumple < 300 s? |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for nombre_fase, grupo in tiempos.items():
        for clave, t in grupo.items():
            if not t:
                continue
            lineas.append(
                f"| {nombre_fase} | {NOMBRE[clave]} | {t['duracion_s']:.1f} | {t['corridas']} | "
                f"{t['total_medio_s']} ({t['total_min_s']}–{t['total_max_s']}) | "
                f"{t['factor_medio']} | {t['estimado_10_min_s'] / 60:.1f} min (peor "
                f"{t['estimado_10_min_max_s'] / 60:.1f}) "
                f"| {'sí' if t['cumple_rnf01'] else '**no**'} |"
            )
    for nombre_fase, grupo in tiempos.items():
        estimados = [t["estimado_10_min_max_s"] for t in grupo.values() if t]
        if estimados:
            peor = max(estimados)
            lineas.append(
                f"\n**{nombre_fase.upper()}: el peor caso estimado para 10 min es "
                f"{peor / 60:.1f} min → RNF-01 "
                f"{'se cumple' if peor < META_RNF01_S else 'NO se cumple'}.**"
            )
    lineas += [
        "",
        "### Por etapa, tokens y memoria",
        "",
        "| Fase | Video·n | Segundos por etapa | Llamadas a Gemma | Tokens de salida "
        "| tok/s medio | VRAM base → pico MiB | Whisper / Gemma |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for f in fases:
        for c in f["corridas"]:
            if "error" in c:
                continue
            etapas = ", ".join(f"{k} {v:g}" for k, v in c["segundos"].items())
            if "segundos_detencion" in c:  # D: hasta la detención y, aparte, al continuar
                detencion = ", ".join(f"{k} {v:g}" for k, v in c["segundos_detencion"].items())
                etapas = (
                    f"hasta detenerse ({c['hasta_detencion_s']} s): {detencion}; "
                    f"al continuar: {etapas}"
                )
            disp = c.get("dispositivos", {})
            lineas.append(
                f"| {f['fase']} | {NOMBRE[c['video']]}·{c['n']} | {etapas} | "
                f"{c['tokens']['llamadas']} | {c['tokens']['tokens_salida']} | "
                f"{_f(c['tokens']['tok_s_medio'])} | {_f(c['vram_base_mib'], '.0f')} → "
                f"{_f(c['vram_pico_mib'], '.0f')} "
                f"| {disp.get('transcripcion')} / {disp.get('llm')} |"
            )
    lineas += ["", "## Qué falló y por qué", ""]
    if fallos:
        lineas += ["| Fase | Video·n | Etapa | Qué |", "|---|---|---|---|"]
        lineas += [
            f"| {x['fase']} | {x['video']}·{x['n']} | {x['etapa']} | {x['que']} |" for x in fallos
        ]
    else:
        lineas.append("Ninguna corrida falló.")
    lineas += ["", "## Lectura y riesgos", "", "_(se completa a mano al leer los resultados)_", ""]
    return datos, "\n".join(lineas) + "\n"


def informe(rutas: list[Path]) -> int:
    fases = [json.loads(r.read_text(encoding="utf-8")) for r in rutas]
    datos, texto = armar_informe(fases)
    marca = datetime.now().strftime("%Y%m%d-%H%M")
    DOCS.mkdir(parents=True, exist_ok=True)
    guardar(datos, DOCS / f"medicion-s5-{marca}.json")
    (DOCS / f"medicion-s5-{marca}.md").write_text(texto, "utf-8", newline="\n")
    print(f"escrito: {DOCS / f'medicion-s5-{marca}.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--fase", choices=("gpu", "cpu"))
    modo.add_argument("--informe", type=Path, nargs="+", help="JSON de las fases")
    parser.add_argument("--videos", nargs="+", choices=sorted(VIDEOS), help="solo estos videos")
    parser.add_argument("--repeticiones", type=int, help="cambia las repeticiones de todos")
    parser.add_argument("--regeneraciones", type=int, default=2, help="RNF-07 con A·1")
    args = parser.parse_args(argv)
    if args.informe:
        return informe(args.informe)
    return fase(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
