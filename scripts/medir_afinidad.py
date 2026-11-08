r"""Mide la afinidad de contexto y las personas (RF-15, RF-17; ADR-020) con videos reales.

Pruebas de aceptación, no calibración: el código no conoce ningún video. Por cada video, Whisper
corre una vez (`preparar` de `medir_mvp.py`) y la validación de producción (`validar`: ficha de
contexto, afinidad, pasos, emparejamiento con el juez, roles y responsables) corre
`--repeticiones` veces, descargando Gemma antes de cada una, como la API. Si la validación se
detiene por afinidad baja, se repite con `continuar=True` y la ficha guardada, como
`POST /videos/{id}/validar?continuar=true`.

Además, la afinidad de la ficha de cada corrida contra cada `--sop-extra` (p. ej. los SOP
inventados de café y minisplit), sin repetir nada más.

Criterios, según la anotación de cada video (`--anotacion`):

- con un paso anotado con `esperado_persona: "Distinto"` (video C): exactamente esos pasos del SOP
  en *distinto* y ningún otro;
- sin ningún paso del SOP anotado (otro procedimiento, video D): afinidad < `AFINIDAD_MIN`, la
  validación se detiene y, al continuar, todos los pasos del SOP en *Falta*;
- los demás (A, B): afinidad ≥ `AFINIDAD_MIN`, el rol de los pasos *presente* y cero *distinto*.

Uso, desde la raíz del repo, con el entorno activado y Ollama arriba:

    python scripts/medir_afinidad.py --sop tests/fixtures/sop_filtro_agua.md \
        --sop-extra tests/fixtures/sop_otro_procedimiento.md \
        --sop-extra tests/fixtures/sop_procedimiento_cercano.md \
        --anotacion media/anotacion_ab.json --docs \
        video_a=media/videos/VIDEO-A.mp4 video_b=media/videos/VIDEO-B.mp4 \
        video_c=data/synthetic/video_c/VIDEO-C.mp4 video_d=data/synthetic/video_d/VIDEO-D.mp4

Salida en `data/interim/afinidad/` (ignorada por git): `afinidad-<fecha>.json` y `.md`; con
`--docs`, también en `docs/adr/datos/afinidad/`. Los videos son del equipo (no del cliente); aun
así el informe no copia la transcripción: solo la ficha (valores cortos), estados, números de
paso, segundos, y el responsable que escribió la segmentación.

Código de salida: 0 si todas las corridas pasan su criterio; 1 si alguna no.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from medir_mvp import estado_git, preparar

from sopvid.contrato import SOP, Contexto
from sopvid.lenguaje.afinidad import afinidad
from sopvid.lenguaje.emparejamiento import get_embedder
from sopvid.lenguaje.sop_markdown import convertir_sop
from sopvid.lenguaje.validacion import DependenciasValidacion, Detenida, Validacion, validar
from sopvid.plataforma.config import PROJECT_ROOT, get_settings

logger = logging.getLogger("medir_afinidad")


def _sop(ruta: Path) -> SOP:
    return convertir_sop(ruta.read_text(encoding="utf-8")).sop


def tipo_de(anotacion: dict[str, Any]) -> str:
    """ "distinto" (C), "otro_procedimiento" (D) o "mismo" (A, B), según la anotación."""
    pasos = anotacion.get("pasos", [])
    if any(p.get("esperado_persona") == "Distinto" for p in pasos):
        return "distinto"
    if not any(p.get("sop") for p in pasos):
        return "otro_procedimiento"
    return "mismo"


def ficha(contexto: Contexto) -> dict[str, Any]:
    def dato(d: Any) -> dict[str, Any]:
        return {"valor": d.valor, "fuente": d.fuente, "confianza": d.confianza}

    return {
        **{c: dato(getattr(contexto, c)) for c in ("actividad", "tema", "lugar", "proposito")},
        "equipos": [e.nombre for e in contexto.equipos],
        "personas": [
            {"nombre": p.nombre, "rol": p.rol, "participacion": p.participacion, "t": p.t}
            for p in contexto.personas
        ],
    }


def resumen_validacion(v: Validacion, sop: SOP) -> dict[str, Any]:
    g = v.resultado
    res = g.resultado
    pasos_video = res.pasos_video
    filas = []
    for paso, responsable in zip(res.clasificacion.pasos, g.responsables or [], strict=False):
        fila: dict[str, Any] = {
            "estado": paso.estado,
            "paso_sop": None if paso.indice_sop is None else sop.pasos[paso.indice_sop].numero,
            "paso_video": None if paso.indice_video is None else paso.indice_video + 1,
            "t_inicio": paso.t_inicio,
            "fuera_de_orden": paso.fuera_de_orden,
            "marco_operador": paso.marco_operador,
        }
        if responsable is not None:
            fila["responsable"] = responsable.model_dump(mode="json")
            fila["responsable_del_paso"] = pasos_video[paso.indice_video].responsable
        filas.append(fila)
    conteo_resp = Counter(f["responsable"]["estado"] for f in filas if "responsable" in f)
    return {
        "cumplimiento": round(g.cumplimiento, 2),
        "semaforo": g.semaforo,
        "conteo": dict(res.clasificacion.resumen.conteo),
        "responsables": dict(conteo_resp),
        "personas_con_diferencias": (
            conteo_resp.get("distinto", 0)
            + sum(r.estado == "ausente" and r.con_pasos for r in g.roles)
        ),
        "roles": [r.model_dump(mode="json") for r in g.roles],
        "filas": filas,
        "avisos": [a.tipo for a in g.metadatos.avisos],
        "segmentacion": g.metadatos.segmentacion,
        "segundos": g.metadatos.segundos,
    }


def criterio(
    tipo: str, corrida: dict[str, Any], anotacion: dict[str, Any], sop: SOP, minimo: float
) -> tuple[bool, list[str]]:
    """(pasa, motivos de lo que no pasa)."""
    motivos: list[str] = []
    a = corrida["afinidad"]
    final = corrida["validacion"]
    distintos = sorted(
        f["paso_sop"]
        for f in final["filas"]
        if f.get("responsable", {}).get("estado") == "distinto"
    )
    if tipo == "otro_procedimiento":
        if a is None or a["valor"] >= minimo:
            motivos.append(f"afinidad {a and a['valor']} no queda bajo {minimo}")
        if not corrida["detenida"]:
            motivos.append("la validación no se detuvo")
        if final["conteo"]["Falta"] != len(sop.pasos):
            motivos.append(f"{final['conteo']['Falta']} Falta de {len(sop.pasos)} pasos del SOP")
        return not motivos, motivos
    if a is None or a["valor"] < minimo:
        motivos.append(f"afinidad {a and a['valor']} bajo {minimo}")
    if tipo == "distinto":
        esperados = sorted(
            p["sop"] for p in anotacion["pasos"] if p.get("esperado_persona") == "Distinto"
        )
        if distintos != esperados:
            motivos.append(f"distinto en los pasos {distintos}; se esperaban {esperados}")
    else:
        if distintos:
            motivos.append(f"distinto en los pasos {distintos}")
        con_pasos = [r for r in final["roles"] if r["con_pasos"]]
        if not con_pasos or any(r["estado"] != "presente" for r in con_pasos):
            motivos.append("un rol con pasos no quedó presente")
    return not motivos, motivos


def medir(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    sop = _sop(args.sop)
    extras = {ruta.stem: _sop(ruta) for ruta in args.sop_extra}
    anotacion = json.loads(args.anotacion.read_text(encoding="utf-8"))
    embedder = get_embedder()
    trabajo = PROJECT_ROOT / "data" / "interim" / "afinidad"
    corridas = []
    for entrada in args.videos:
        clave, _, ruta = entrada.partition("=")
        analisis, segundos, dispositivos = preparar(
            clave, Path(ruta), settings, trabajo, args.idioma
        )
        tipo = tipo_de(anotacion.get(clave, {}))
        for repeticion in range(1, args.repeticiones + 1):
            deps = DependenciasValidacion.desde_settings(settings)
            deps.embedder = embedder
            try:
                deps.llm.descargar()
                inicio = time.perf_counter()
                v = validar(
                    analisis, sop, deps, segundos_analisis=segundos, dispositivos=dispositivos
                )
                detenida = isinstance(v, Detenida)
                contexto = v.contexto
                a = v.detencion.afinidad if detenida else v.resultado.afinidad
                if detenida:
                    v = validar(
                        analisis,
                        sop,
                        deps,
                        dispositivos=dispositivos,
                        contexto=contexto,
                        continuar=True,
                    )
                total = round(time.perf_counter() - inicio, 2)
            finally:
                deps.cerrar()
            assert isinstance(v, Validacion)
            corrida = {
                "video": clave,
                "tipo": tipo,
                "repeticion": repeticion,
                "duracion_s": analisis.duracion_s,
                "ficha": ficha(contexto),
                "afinidad": None if a is None else a.model_dump(mode="json"),
                "detenida": detenida,
                "afinidad_extra": {
                    nombre: (
                        r.model_dump(mode="json")
                        if (r := afinidad(otro, contexto, embedder))
                        else None
                    )
                    for nombre, otro in extras.items()
                },
                "validacion": resumen_validacion(v, sop),
                "segundos_total": total,
            }
            pasa, motivos = criterio(
                tipo, corrida, anotacion.get(clave, {}), sop, settings.afinidad_min
            )
            corrida["pasa"], corrida["motivos"] = pasa, motivos
            corridas.append(corrida)
            logger.info(
                "%s #%d: afinidad %s, %s",
                clave,
                repeticion,
                corrida["afinidad"] and corrida["afinidad"]["valor"],
                "pasa" if pasa else f"NO pasa: {motivos}",
            )
    return {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "git": estado_git(),
        "sop": args.sop.as_posix(),
        "sop_extra": [r.as_posix() for r in args.sop_extra],
        "modelos": {
            "llm": settings.llm_model,
            "embedder": settings.embedder_model,
            "whisper": settings.whisper_modelo,
        },
        "umbrales": {
            "afinidad_min": settings.afinidad_min,
            "afinidad_cos_cero": settings.afinidad_cos_cero,
            "afinidad_cos_cien": settings.afinidad_cos_cien,
            "afinidad_umbral_equipo": settings.afinidad_umbral_equipo,
            "umbral_rol": settings.umbral_rol,
            "umbral_rol_complemento": settings.umbral_rol_complemento,
        },
        "corridas": corridas,
    }


def informe(datos: dict[str, Any]) -> str:
    lineas = [
        f"# Afinidad y personas con videos reales ({datos['fecha']})",
        "",
        f"Commit `{datos['git'].get('commit')}`"
        + (" (con cambios sin commit)" if datos["git"].get("cambios_sin_commit") else "")
        + f". SOP: `{datos['sop']}`. Modelos: {datos['modelos']}. Umbrales: {datos['umbrales']}.",
        "",
        "| Video · rep. | Afinidad (componentes) | Detenida | Cumpl. | Falta/Sobra | Roles"
        " | Responsables | Personas con dif. | Criterio |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in datos["corridas"]:
        a, v = c["afinidad"], c["validacion"]
        roles = ", ".join(
            f"{r['rol']}: {r['estado']}" + ("" if r["con_pasos"] else " (sin pasos)")
            for r in v["roles"]
        )
        lineas.append(
            f"| {c['video']} · {c['repeticion']} "
            f"| {a and a['valor']} {a and a['componentes']} "
            f"| {'sí' if c['detenida'] else 'no'} | {v['cumplimiento']} "
            f"| {v['conteo']['Falta']}/{v['conteo']['Sobra']} | {roles} | {v['responsables']} "
            f"| {v['personas_con_diferencias']} "
            f"| {'pasa' if c['pasa'] else 'NO: ' + '; '.join(c['motivos'])} |"
        )
    lineas += ["", "## Explicaciones y fichas", ""]
    for c in datos["corridas"]:
        a = c["afinidad"]
        lineas.append(f"### {c['video']} · {c['repeticion']}")
        lineas.append("")
        lineas.append(f"- Afinidad contra el SOP: {a and a['valor']} · {a and a['explicacion']}")
        for nombre, extra in c["afinidad_extra"].items():
            lineas.append(
                f"- Contra `{nombre}`: {extra and extra['valor']} "
                f"{extra and extra['componentes']} · {extra and extra['explicacion']}"
            )
        f = c["ficha"]
        lineas.append(
            f"- Ficha: actividad {f['actividad']}; propósito {f['proposito']}; "
            f"lugar {f['lugar']}; equipos {f['equipos']}; personas {f['personas']}"
        )
        lineas.append("- Responsables por paso emparejado:")
        for fila in c["validacion"]["filas"]:
            if "responsable" in fila:
                r = fila["responsable"]
                lineas.append(
                    f"  - SOP {fila['paso_sop']} ↔ video {fila['paso_video']} ({fila['estado']}):"
                    f" {r['estado']}, observado {r['observado']!r}, responsable del paso "
                    f"{fila['responsable_del_paso']!r}; nota: {r['nota']}"
                )
        lineas.append("")
    return "\n".join(lineas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+", help="clave=ruta del video o de su analisis.json")
    parser.add_argument("--sop", type=Path, required=True, help="SOP en Markdown (ADR-015)")
    parser.add_argument(
        "--sop-extra",
        type=Path,
        action="append",
        default=[],
        help="otro SOP contra el que medir solo la afinidad (repetible)",
    )
    parser.add_argument("--anotacion", type=Path, required=True, help="JSON de la anotación")
    parser.add_argument("--repeticiones", type=int, default=1, help="validaciones por video")
    parser.add_argument("--idioma", help="ISO 639-1 para Whisper; sin él, lo detecta")
    parser.add_argument("--docs", action="store_true", help="copiar a docs/adr/datos/afinidad/")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    datos = medir(args)
    sello = datetime.now().strftime("%Y%m%d-%H%M")
    destinos = [PROJECT_ROOT / "data" / "interim" / "afinidad"]
    if args.docs:
        destinos.append(PROJECT_ROOT / "docs" / "adr" / "datos" / "afinidad")
    for carpeta in destinos:
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"afinidad-{sello}.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (carpeta / f"afinidad-{sello}.md").write_text(informe(datos), encoding="utf-8")
        print(f"escrito: {carpeta / f'afinidad-{sello}.md'}")
    return 0 if all(c["pasa"] for c in datos["corridas"]) else 1


if __name__ == "__main__":
    sys.exit(main())
