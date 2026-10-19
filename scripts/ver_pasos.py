"""Visor de la extracción de pasos del video (RF-13): entrada y resultado en una página HTML.

Toma un JSON de entrada, corre `segmentar()` y escribe una página con la transcripción a la
izquierda y los pasos a la derecha. Cada paso tiene su color en la transcripción, la cita
resaltada y, si hay inicios anotados a mano, se marcan los aciertos y los pasos de más.

Uso, desde la raíz del repo y con el entorno activado:

    python scripts/ver_pasos.py tests/fixtures/analisis_ejemplo.json
    python scripts/ver_pasos.py tests/fixtures/transcripciones/cambio_cuchilla.json
    python scripts/ver_pasos.py entrada.json --sin-llm            # solo la heurística
    python scripts/ver_pasos.py entrada.json --referencia 4,6,9   # inicios reales a mano
    python scripts/ver_pasos.py entrada.json --resultado data/interim/visor/entrada.pasos.json

Entradas aceptadas: un `Analisis` del contrato (la salida del pipeline de video) o una
transcripción de prueba de tests/fixtures/transcripciones/ (trae sus propios inicios reales).
Con Ollama apagado se usa la heurística y la página lo dice.

Salida: data/interim/visor/<nombre>.html y <nombre>.pasos.json (carpeta ignorada por git).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import unicodedata
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sopvid.contrato import Analisis, PasoVideo
from sopvid.lenguaje.llm import ClienteLLM
from sopvid.percepcion.segmentacion import (
    cargar_transcripcion_prueba,
    f1_fronteras,
    segmentar,
    segmentos_de_inicio,
)

SALIDA = Path("data/interim/visor")
# Inicios anotados a mano de los ejemplos que no los traen dentro del JSON.
REFERENCIAS_CONOCIDAS = {"analisis_ejemplo": [4, 6, 9, 12, 17, 21]}
TONOS = (212, 28, 152, 280, 350, 95, 190, 45)  # un tono por paso, se repite después de 8


# ── Entrada y ejecución ──────────────────────────────────────────────────────────────────────


@dataclass
class Entrada:
    nombre: str
    analisis: Analisis
    etiquetas: dict[str, str]
    referencia: list[int] | None


def cargar_entrada(ruta: Path, referencia: list[int] | None) -> Entrada:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if "transcripcion" in datos:
        analisis = Analisis.model_validate(datos)
        etiquetas: dict[str, str] = {}
        ref = REFERENCIAS_CONOCIDAS.get(ruta.stem)
    elif "segmentos" in datos:
        analisis = cargar_transcripcion_prueba(ruta)
        etiquetas = datos.get("etiquetas", {})
        ref = datos.get("inicios_paso")
    else:
        sys.exit(f"{ruta}: no parece un Analisis ni una transcripción de prueba.")
    return Entrada(ruta.stem, analisis, etiquetas, referencia or ref)


def correr(entrada: Entrada, sin_llm: bool) -> dict[str, Any]:
    cliente: ClienteLLM | None = None
    aviso = None
    if not sin_llm:
        cliente = ClienteLLM.desde_settings()
        if not cliente.disponible(timeout_s=5):
            aviso = f"Ollama no responde o no tiene {cliente.modelo}: se usó la heurística."
            print(aviso, file=sys.stderr)
            cliente.close()
            cliente = None
    inicio = time.perf_counter()
    try:
        r = segmentar(entrada.analisis, cliente, entrada.etiquetas or None)
    finally:
        if cliente is not None:
            cliente.close()
    return {
        "metodo": r.metodo,
        "modelo": r.modelo,
        "motivo_respaldo": r.motivo_respaldo or aviso,
        "intentos": r.intentos,
        "intentos_redaccion": r.intentos_redaccion,
        "pasos_sin_redactar": r.pasos_sin_redactar,
        "segundos": round(time.perf_counter() - inicio, 1),
        "pasos": [p.model_dump() for p in r.pasos],
    }


# ── Cita resaltada ───────────────────────────────────────────────────────────────────────────


def _norm(palabra: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", palabra).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", sin_acentos.lower())


def marcar_citas(analisis: Analisis, pasos: list[PasoVideo]) -> dict[tuple[int, int], int]:
    """(id de segmento, posición de la palabra) → número de paso cuya cita la contiene.

    Busca la cita como secuencia contigua de palabras normalizadas, primero dentro del paso y
    luego en toda la transcripción, igual que la verificación de confianza."""
    fichas = [
        (s.id, i, _norm(w))
        for s in analisis.transcripcion
        for i, w in enumerate(s.texto.split())
        if _norm(w)
    ]
    marcas: dict[tuple[int, int], int] = {}
    for p in pasos:
        cita = [n for n in (_norm(w) for w in p.cita.split()) if n]
        if not cita:
            continue
        dentro = [k for k, (sid, _, _) in enumerate(fichas) if _en_paso(analisis, sid, p)]
        candidatos = dentro + [k for k in range(len(fichas)) if k not in set(dentro)]
        for k in candidatos:
            if [f[2] for f in fichas[k : k + len(cita)]] == cita:
                for sid, i, _ in fichas[k : k + len(cita)]:
                    marcas[(sid, i)] = p.numero
                break
    return marcas


def _en_paso(analisis: Analisis, sid: int, p: PasoVideo) -> bool:
    s = next(s for s in analisis.transcripcion if s.id == sid)
    return p.t_inicio - 1e-6 <= s.t_inicio and s.t_fin <= p.t_fin + 1e-6


# ── Página ───────────────────────────────────────────────────────────────────────────────────


def mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def tono(numero: int) -> int:
    return TONOS[(numero - 1) % len(TONOS)]


def pagina(entrada: Entrada, res: dict[str, Any]) -> str:
    a = entrada.analisis
    pasos = [PasoVideo.model_validate(p) for p in res["pasos"]]
    duracion = a.duracion_s or (a.transcripcion[-1].t_fin if a.transcripcion else 1.0)
    paso_de = {
        s.id: next((p.numero for p in pasos if _en_paso(a, s.id, p)), None) for s in a.transcripcion
    }
    inicios = segmentos_de_inicio(pasos, a) if pasos else []
    inicio_de = dict(zip(inicios, (p.numero for p in pasos), strict=True))
    marcas = marcar_citas(a, pasos)
    ref = entrada.referencia or []
    metricas = f1_fronteras(inicios, ref) if ref else None
    sobran = set(metricas["falsos_positivos"]) if metricas else set()
    faltan = set(metricas["no_detectados"]) if metricas else set()
    e = html.escape

    # Resumen
    conteo = {c: sum(p.confianza == c for p in pasos) for c in ("alta", "media", "baja")}
    if res["metodo"] == "llm":
        camino = f"LLM · {e(res['modelo'] or '')}"
        llamadas = f"{res['intentos']} + {res['intentos_redaccion']} llamadas"
    else:
        camino = "Heurística de respaldo"
        llamadas = e(res.get("motivo_respaldo") or "")
    fichas_resumen = [
        ("Pasos", str(len(pasos))),
        ("Segmentos", str(len(a.transcripcion))),
        ("Duración", mmss(duracion)),
        ("Tiempo de proceso", f"{res['segundos']} s"),
        ("Confianza alta / media / baja", "{alta} / {media} / {baja}".format(**conteo)),
    ]
    if metricas:
        fichas_resumen.insert(1, ("Pasos reales (a mano)", str(len(ref))))
        fichas_resumen.append(("F1 de fronteras", f"{metricas['f1']:.2f}"))
    resumen = "".join(
        f'<div class="kpi"><div class="v">{v}</div><div class="l">{e(etiqueta)}</div></div>'
        for etiqueta, v in fichas_resumen
    )

    # Línea de tiempo
    bloques = "".join(
        f'<a class="blk" href="#paso-{p.numero}" style="--h:{tono(p.numero)};'
        f"left:{100 * p.t_inicio / duracion:.3f}%;"
        f'width:{max(100 * (p.t_fin - p.t_inicio) / duracion, 0.4):.3f}%" '
        f'title="Paso {p.numero} · {e(p.nombre)} · {mmss(p.t_inicio)}–{mmss(p.t_fin)}">'
        f"<span>{p.numero}</span></a>"
        for p in pasos
    )
    t_de = {s.id: s.t_inicio for s in a.transcripcion}
    marcas_ref = "".join(
        f'<i class="tick" style="left:{100 * t_de[r] / duracion:.3f}%" '
        f'title="Inicio real · segmento {r} · {mmss(t_de[r])}"></i>'
        for r in ref
        if r in t_de
    )

    # Transcripción
    filas = []
    for s in a.transcripcion:
        n = paso_de[s.id]
        palabras: list[str] = []
        abierta: int | None = None  # paso cuya cita se está resaltando
        for i, w in enumerate(s.texto.split()):
            m = marcas.get((s.id, i))
            prefijo = ""
            if m != abierta:
                if abierta is not None:
                    palabras[-1] += "</mark>"
                if m is not None:
                    prefijo = f'<mark style="--h:{tono(m)}">'
                abierta = m
            palabras.append(prefijo + e(w))
        if abierta is not None:
            palabras[-1] += "</mark>"
        insignias = ""
        if s.id in inicio_de:
            clase = "ins sobra" if s.id in sobran else "ins"
            nota = " · de más" if s.id in sobran else ""
            insignias += (
                f'<a class="{clase}" href="#paso-{inicio_de[s.id]}" '
                f'style="--h:{tono(inicio_de[s.id])}">▶ Paso {inicio_de[s.id]}{nota}</a>'
            )
        if s.id in ref:
            clase = "ins real falta" if s.id in faltan else "ins real"
            nota = " · no detectado" if s.id in faltan else ""
            insignias += f'<span class="{clase}">★ inicio real{nota}</span>'
        estilo = f' style="--h:{tono(n)}"' if n else ""
        clase = "seg en-paso" if n else "seg"
        filas.append(
            f'<div class="{clase}" id="seg-{s.id}" data-paso="{n or ""}"{estilo}>'
            f'<div class="meta"><b>[{s.id}]</b><span>{mmss(s.t_inicio)}</span></div>'
            f'<div class="txt">{insignias and f"<div class=ins-row>{insignias}</div>"}'
            f"{' '.join(palabras)}</div></div>"
        )

    # Pasos
    tarjetas = []
    for p, sid in zip(pasos, inicios, strict=True):
        nota_fuente = {"audio": "audio", "visual": "imagen", "inferido": "inferido"}[p.fuente]
        cita = (
            f'<blockquote style="--h:{tono(p.numero)}">“{e(p.cita)}”</blockquote>'
            if p.cita
            else '<p class="vacio">Sin cita</p>'
        )
        tarjetas.append(
            f'<article class="card" id="paso-{p.numero}" data-seg="{sid}" '
            f'style="--h:{tono(p.numero)}">'
            f'<header><span class="num">{p.numero}</span><h3>{e(p.nombre)}</h3>'
            f'<span class="pill {p.confianza}">{p.confianza}</span></header>'
            f'<div class="datos"><span>⏱ {mmss(p.t_inicio)}–{mmss(p.t_fin)}</span>'
            f"<span>👤 {e(p.responsable)}</span><span>Fuente: {nota_fuente}</span>"
            f"<span>Desde el segmento {sid}</span></div>"
            f"<p>{e(p.descripcion) or '<span class=vacio>Sin descripción</span>'}</p>"
            f"{cita}</article>"
        )

    aviso = ""
    if res["metodo"] != "llm":
        aviso = (
            '<div class="aviso">Estos pasos los hizo la <b>heurística de respaldo</b>, no el '
            f"LLM. Motivo: {e(res.get('motivo_respaldo') or 'sin cliente LLM')}. "
            "Levanta Ollama (docker compose --profile llm up -d) y vuelve a correr.</div>"
        )
    if res.get("pasos_sin_redactar"):
        aviso += (
            f'<div class="aviso">{res["pasos_sin_redactar"]} paso(s) quedaron sin redactar: '
            "conservan las fronteras pero sin descripción ni cita.</div>"
        )
    leyenda_ref = (
        '<span><i class="tick demo"></i>Inicio real (anotado a mano)</span>'
        '<span><b class="ins sobra demo">▶ de más</b>Paso que no está en la anotación</span>'
        if ref
        else "<span>Sin anotación a mano: no se calcula F1.</span>"
    )

    return PLANTILLA.format(
        titulo=e(entrada.nombre),
        camino=camino,
        llamadas=llamadas,
        idioma=e(f"{a.idioma.codigo} ({a.idioma.confianza:.0%})"),
        resumen=resumen,
        aviso=aviso,
        bloques=bloques,
        marcas_ref=marcas_ref,
        fin=mmss(duracion),
        leyenda_ref=leyenda_ref,
        filas="\n".join(filas),
        tarjetas="\n".join(tarjetas) or '<p class="vacio">No salió ningún paso.</p>',
    )


PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pasos · {titulo}</title>
<style>
:root{{--bg:#f5f6f8;--panel:#fff;--panel2:#f0f2f5;--line:#dde1e7;--ink:#1b2430;--ink2:#556070;
--ink3:#7c8695;--acc:#2f5d8a;--ok:#2e7d55;--okb:#e5f3eb;--warn:#a96a12;--warnb:#fbf1df;
--bad:#b03a32;--badb:#f8e6e4;--band-s:70%;--band-l:95%;--mark-l:82%;--strong-l:42%}}
@media (prefers-color-scheme:dark){{:root{{--bg:#11151b;--panel:#181d25;--panel2:#1e2430;
--line:#2b3340;--ink:#e6eaf0;--ink2:#a9b2bf;--ink3:#808a98;--acc:#7fa8d1;--ok:#6cc296;
--okb:#18291f;--warn:#e0a94f;--warnb:#2c2416;--bad:#e3827a;--badb:#2d1b1a;--band-s:30%;
--band-l:18%;--mark-l:32%;--strong-l:68%;color-scheme:dark}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
font:14.5px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:1400px;margin:0 auto;padding:24px 20px 60px}}
h1{{font-size:24px;margin:0}} .sub{{color:var(--ink2);margin:4px 0 16px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}}
.kpi{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}}
.kpi .v{{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}}
.kpi .l{{font-size:12px;color:var(--ink2)}}
.aviso{{background:var(--warnb);border-left:3px solid var(--warn);padding:10px 14px;
border-radius:0 8px 8px 0;margin:0 0 12px}}
.tl-wrap{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:16px}}
.tl{{position:relative;height:34px;background:var(--panel2);border-radius:6px}}
.blk{{position:absolute;top:4px;bottom:4px;border-radius:4px;text-decoration:none;
background:hsl(var(--h) var(--band-s) calc(var(--band-l) - 12%));
border:1px solid hsl(var(--h) 60% var(--strong-l));overflow:hidden;
display:flex;align-items:center;justify-content:center}}
.blk span{{font-size:11px;font-weight:700;color:hsl(var(--h) 60% var(--strong-l))}}
.tick{{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--ink);opacity:.8}}
.tick::before{{content:"★";position:absolute;top:-14px;left:-5px;font-size:10px;font-style:normal}}
.tl-ejes{{display:flex;justify-content:space-between;font-size:11.5px;color:var(--ink3);margin-top:4px}}
.leyenda{{display:flex;flex-wrap:wrap;gap:16px;font-size:12.5px;color:var(--ink2);margin-top:10px}}
.leyenda span{{display:inline-flex;gap:6px;align-items:center}}
.tick.demo{{position:relative;display:inline-block;height:14px;top:0;bottom:0}}
.tick.demo::before{{display:none}}
.cols{{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:16px;align-items:start}}
.col h2{{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink3);margin:0 0 8px}}
.lista{{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.pasos{{position:sticky;top:12px;max-height:calc(100vh - 24px);overflow-y:auto;display:grid;gap:10px;padding-right:4px}}
.seg{{display:grid;grid-template-columns:62px minmax(0,1fr);gap:8px;padding:8px 12px;
border-bottom:1px solid var(--line);border-left:4px solid transparent;cursor:pointer}}
.seg:last-child{{border-bottom:none}}
.seg.en-paso{{background:hsl(var(--h) var(--band-s) var(--band-l));
border-left-color:hsl(var(--h) 60% var(--strong-l))}}
.seg .meta{{font-size:12px;color:var(--ink3);display:flex;flex-direction:column;font-variant-numeric:tabular-nums}}
.seg .meta b{{color:var(--ink2)}}
mark{{background:hsl(var(--h) 75% var(--mark-l));color:inherit;border-radius:3px;padding:0 2px}}
.ins-row{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:4px}}
.ins{{font-size:11.5px;font-weight:700;padding:1px 8px;border-radius:99px;text-decoration:none;
color:hsl(var(--h) 60% var(--strong-l));border:1px solid hsl(var(--h) 60% var(--strong-l));background:var(--panel)}}
.ins.sobra{{color:var(--bad);border-color:var(--bad);background:var(--badb)}}
.ins.real{{color:var(--ink);border-color:var(--ink3)}}
.ins.real.falta{{color:var(--bad);border-color:var(--bad);background:var(--badb)}}
.ins.demo{{font-size:11px}}
.card{{background:var(--panel);border:1px solid var(--line);border-top:4px solid hsl(var(--h) 60% var(--strong-l));
border-radius:10px;padding:12px 14px;scroll-margin-top:12px;cursor:pointer}}
.card header{{display:flex;align-items:center;gap:10px}}
.card h3{{margin:0;font-size:15px;flex:1}}
.num{{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-weight:700;font-size:13px;flex:none;
background:hsl(var(--h) var(--band-s) calc(var(--band-l) - 6%));color:hsl(var(--h) 60% var(--strong-l))}}
.datos{{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;color:var(--ink2);margin:6px 0}}
.card p{{margin:6px 0}}
blockquote{{margin:8px 0 0;padding:6px 10px;border-left:3px solid hsl(var(--h) 60% var(--strong-l));
background:var(--panel2);border-radius:0 6px 6px 0;font-style:italic}}
.pill{{font-size:11.5px;font-weight:700;padding:2px 9px;border-radius:99px}}
.pill.alta{{background:var(--okb);color:var(--ok)}} .pill.media{{background:var(--warnb);color:var(--warn)}}
.pill.baja{{background:var(--badb);color:var(--bad)}}
.vacio{{color:var(--ink3);font-style:italic}}
.flash{{outline:2px solid var(--acc);outline-offset:-2px}}
@media (max-width:900px){{.cols{{grid-template-columns:minmax(0,1fr)}} .pasos{{position:static;max-height:none}}}}
</style></head><body><main>
<h1>Extracción de pasos · {titulo}</h1>
<p class="sub">{camino} · {llamadas} · idioma {idioma}</p>
<div class="kpis">{resumen}</div>
{aviso}
<div class="tl-wrap"><div class="tl">{bloques}{marcas_ref}</div>
<div class="tl-ejes"><span>00:00</span><span>{fin}</span></div>
<div class="leyenda"><span>Cada color es un paso. En la transcripción, la cita del paso aparece resaltada.</span>{leyenda_ref}</div></div>
<div class="cols">
<section class="col"><h2>Entrada · transcripción</h2><div class="lista">{filas}</div></section>
<section class="col"><h2>Salida · pasos</h2><div class="pasos">{tarjetas}</div></section>
</div></main>
<script>
function flash(el){{if(!el)return;el.scrollIntoView({{behavior:"smooth",block:"center"}});
el.classList.add("flash");setTimeout(()=>el.classList.remove("flash"),1200);}}
document.querySelectorAll(".card").forEach(c=>c.addEventListener("click",ev=>{{
if(ev.target.closest("a"))return;flash(document.getElementById("seg-"+c.dataset.seg));}}));
document.querySelectorAll(".seg[data-paso]").forEach(s=>s.addEventListener("click",ev=>{{
if(ev.target.closest("a")||!s.dataset.paso)return;flash(document.getElementById("paso-"+s.dataset.paso));}}));
</script></body></html>
"""  # noqa: E501 (CSS de una línea por regla)


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("entrada", type=Path, help="Analisis JSON o transcripción de prueba")
    ap.add_argument("--sin-llm", action="store_true", help="solo la heurística, sin Ollama")
    ap.add_argument("--referencia", help="ids de segmento donde empieza cada paso real: 4,6,9")
    ap.add_argument("--resultado", type=Path, help="pasos.json guardado: no vuelve a correr")
    ap.add_argument("--no-abrir", action="store_true", help="no abrir el navegador")
    args = ap.parse_args()

    ref = [int(x) for x in args.referencia.split(",")] if args.referencia else None
    entrada = cargar_entrada(args.entrada, ref)
    SALIDA.mkdir(parents=True, exist_ok=True)

    if args.resultado:
        res = json.loads(args.resultado.read_text(encoding="utf-8"))
    else:
        res = correr(entrada, args.sin_llm)
        destino = SALIDA / f"{entrada.nombre}.pasos.json"
        destino.write_text(
            json.dumps({"entrada": str(args.entrada), **res}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"Pasos: {destino}")

    salida = SALIDA / f"{entrada.nombre}.html"
    salida.write_text(pagina(entrada, res), encoding="utf-8")
    print(f"Página: {salida}")
    if not args.no_abrir:
        webbrowser.open(salida.resolve().as_uri())


if __name__ == "__main__":
    main()
