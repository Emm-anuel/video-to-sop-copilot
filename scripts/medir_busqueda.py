r"""Mide la búsqueda exacta (RNF-02: < 1 s con 50 videos; RNF-03: el segundo a menos de ±1 s).

Solo hace falta Postgres (migrado a la 0008); ni Whisper ni Ollama. Siembra 50 videos sintéticos
publicados, copiando las transcripciones de A–E con los tiempos desplazados `n × 13.7 s` (la copia 0
de cada clave queda sin desplazar), con el título `[medir_busqueda] <clave> #n`. Los borra al final,
también si algo falla o con Ctrl-C (y al empezar, los que hubiera dejado una corrida anterior), y
borra las filas de `busquedas` que se crearon durante la medición: no la corras contra una base en
la que alguien esté buscando a la vez.

Con `--palabras-por-video N`, cada video concatena las transcripciones de A–E en ciclo (cada una
empezando por una clave distinta, con 1 s de pausa entre piezas y el mismo desplazamiento por
vuelta) hasta tener al menos N palabras en el índice, cortando en el borde de un segmento: con
1500, unos 13 minutos de habla por video al ritmo de A–E y ~76 000 palabras en total.

Corre ~30 consultas sacadas del corpus de forma determinista: palabras comunes (las más
frecuentes), raras (una sola vez en A–E), frases de 2 a 4 palabras tomadas de la transcripción,
dos frases largas (12 y 40 palabras) y consultas sin resultados. Cada una `--repeticiones`
veces, después de 3 de calentamiento. Por cada una se guardan dos tiempos: el del servidor
(`milisegundos` de la respuesta: normalizar, las dos sentencias, armar la respuesta y registrar
en `busquedas`) y el de punta a punta (reloj alrededor de `POST /buscar` con `TestClient` sobre
la app real, sin lifespan: no arranca el trabajador ni toca videos reales). Informa p50 y p95
por tipo y en total, y el `EXPLAIN (ANALYZE, BUFFERS)` de la sentencia principal de la consulta
más lenta.

RNF-03: 10 palabras de la clave de referencia (la primera, A) que aparecen una sola vez en su
transcripción, repartidas a lo largo del video; se buscan con `video_id` de su copia sin desplazar y
el `t_inicio` del resultado se compara con el `t` de la palabra en el `analisis.json`.

Uso, desde la raíz del repo, con el entorno activado y la base arriba:

    python scripts/medir_busqueda.py \
        video_a=data/interim/imagenes/video_a.analisis.json \
        video_b=data/interim/imagenes/video_b.analisis.json \
        video_c=data/interim/imagenes/video_c.analisis.json \
        video_d=data/interim/imagenes/video_d.analisis.json \
        video_e=data/interim/imagenes/video_e.analisis.json

    python scripts/medir_busqueda.py --palabras-por-video 1500 \
        --anexar docs/adr/datos/s6/busqueda/medicion-busqueda-<fecha>.md video_a=… video_e=…

Salida: `docs/adr/datos/s6/busqueda/medicion-busqueda-<fecha>.md` y `.json` (`--salida` la
cambia), con una tabla que resume todas las corridas y el detalle de cada una, incluidas las
palabras y los minutos por video. `--anexar` agrega la corrida a un informe existente. A–E son
videos grabados por el equipo (no del cliente): las consultas van en el informe.

Código de salida: 0 si el p95 de punta a punta queda bajo 1 s y las 10 palabras de RNF-03 caen a
menos de ±1 s; 1 si no.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from medir_mvp import estado_git
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from sopvid.contrato import Analisis
from sopvid.lenguaje import busqueda
from sopvid.plataforma.api.main import create_app
from sopvid.plataforma.config import PROJECT_ROOT, get_settings
from sopvid.plataforma.db import get_sessionmaker
from sopvid.plataforma.modelos import Busqueda, Palabra, Video
from sopvid.plataforma.procesamiento import guardar_analisis
from sopvid.texto import forma_busqueda

logger = logging.getLogger("medir_busqueda")

PREFIJO = "[medir_busqueda]"
N_VIDEOS = 50
DESPLAZAMIENTO_S = 13.7
PAUSA_S = 1.0  # entre dos transcripciones concatenadas
UMBRAL_MS = 1000.0  # RNF-02
TOLERANCIA_S = 1.0  # RNF-03
CALENTAMIENTO = 3
SALIDA = PROJECT_ROOT / "docs" / "adr" / "datos" / "s6" / "busqueda"
SIN_RESULTADOS = [
    "zzxq",
    "xilófono",
    "válvula cuántica intergaláctica",
    "esta frase nadie la dijo nunca",
]


# ── Partes puras ─────────────────────────────────────────────────────────────────────────────


def desplazar(analisis: Analisis, segundos: float) -> Analisis:
    """El mismo análisis con todos los tiempos (segmentos y palabras) `segundos` después."""
    if segundos == 0:
        return analisis
    datos = analisis.model_dump(mode="json")
    for segmento in datos["transcripcion"]:
        segmento["t_inicio"] += segundos
        segmento["t_fin"] += segundos
        for palabra in segmento.get("palabras") or []:
            palabra["t"] += segundos
            palabra["t_fin"] += segundos
    datos["duracion_s"] = (datos.get("duracion_s") or 0.0) + segundos
    return Analisis.model_validate(datos)


def _tokens(segmento: dict[str, Any]) -> int:
    palabras = segmento.get("palabras") or []
    textos = [p["w"] for p in palabras] if palabras else segmento["texto"].split()
    return sum(len(forma_busqueda(w).split()) for w in textos)


def concatenar(piezas: Sequence[Analisis], objetivo: int, desde_s: float = 0.0) -> Analisis:
    """Un video largo: las transcripciones de `piezas` una tras otra (en ciclo, con `PAUSA_S`
    entre una y la siguiente) hasta llegar a `objetivo` tokens del índice, cortando en el borde
    de un segmento. La primera pieza conserva sus tiempos más `desde_s`; los ids se renumeran."""
    segmentos: list[dict[str, Any]] = []
    tokens = 0
    i = 0
    while tokens < objetivo:
        if i and i % len(piezas) == 0 and tokens == 0:
            raise ValueError("las piezas no tienen palabras que indexar")
        pieza = piezas[i % len(piezas)]
        i += 1
        if not pieza.transcripcion:
            continue
        inicio = pieza.transcripcion[0].t_inicio
        corrimiento = desde_s if not segmentos else segmentos[-1]["t_fin"] + PAUSA_S - inicio
        for segmento in pieza.transcripcion:
            if tokens >= objetivo:
                break
            datos = segmento.model_dump(mode="json")
            datos["id"] = len(segmentos)
            datos["t_inicio"] += corrimiento
            datos["t_fin"] += corrimiento
            for palabra in datos.get("palabras") or []:
                palabra["t"] += corrimiento
                palabra["t_fin"] += corrimiento
            segmentos.append(datos)
            tokens += _tokens(datos)
    base = piezas[0].model_dump(mode="json")
    base |= {"transcripcion": segmentos, "duracion_s": segmentos[-1]["t_fin"], "fotogramas": []}
    return Analisis.model_validate(base)


def videos_sinteticos(
    corpus: dict[str, Analisis], palabras_por_video: int | None = None, n_videos: int = N_VIDEOS
) -> list[tuple[str, Analisis, bool]]:
    """(etiqueta, análisis, es_referencia) de los videos a sembrar. Sin `palabras_por_video`,
    cada video es la copia de una clave (en ciclo) desplazada `vuelta × DESPLAZAMIENTO_S`; con él,
    cada video concatena las claves empezando por una distinta (`concatenar`). La referencia de
    RNF-03 es el video en que la primera clave empieza sin desplazar."""
    claves = list(corpus)
    videos = []
    for n in range(n_videos):
        vuelta = n // len(claves)
        corrimiento = round(vuelta * DESPLAZAMIENTO_S, 3)
        clave = claves[n % len(claves)]
        if palabras_por_video is None:
            analisis = desplazar(corpus[clave], corrimiento)
            videos.append((clave, analisis, vuelta == 0 and clave == claves[0]))
        else:
            orden = [corpus[claves[(n + j) % len(claves)]] for j in range(len(claves))]
            analisis = concatenar(orden, palabras_por_video, corrimiento)
            videos.append((f"{clave}+", analisis, n == 0))
    return videos


def palabras_de(analisis: Analisis) -> list[tuple[str, float]]:
    """Las palabras de Whisper en orden, con su segundo, sin las que quedan vacías al buscar."""
    return [
        (p.w.strip(), p.t)
        for s in analisis.transcripcion
        for p in s.palabras
        if forma_busqueda(p.w).split()
    ]


def _repartidas(elementos: Sequence[Any], n: int) -> list[Any]:
    """`n` elementos repartidos a lo largo de la secuencia (todos si hay menos)."""
    if len(elementos) <= n:
        return list(elementos)
    return [elementos[round(i * (len(elementos) - 1) / (n - 1))] for i in range(n)]


LARGAS = (12, 40)  # tokens de las frases largas (más de `busqueda.TOKENS_UNIDOS`)


def elegir_consultas(
    corpus: dict[str, Analisis], comunes: int = 8, raras: int = 8, frases: int = 10
) -> list[tuple[str, str]]:
    """(tipo, consulta) deterministas a partir de las transcripciones, sin repetir consultas:
    las palabras de un token más frecuentes, las que aparecen una sola vez en todo el corpus
    (repartidas), frases de 2 a 4 palabras seguidas (repartidas por clave), dos frases largas
    (`LARGAS`, desde la mitad de las dos primeras claves) y `SIN_RESULTADOS`."""
    por_clave = {clave: palabras_de(a) for clave, a in corpus.items()}
    cuenta: Counter[str] = Counter()
    original: dict[str, str] = {}
    for palabras in por_clave.values():
        for w, _ in palabras:
            tokens = forma_busqueda(w).split()
            if len(tokens) == 1:
                cuenta[tokens[0]] += 1
                original.setdefault(tokens[0], w)
    elegidas: list[tuple[str, str]] = [
        ("comun", original[t]) for t, _ in cuenta.most_common(comunes)
    ]
    unicas = [t for t in original if cuenta[t] == 1 and len(t) > 3]
    elegidas += [("rara", original[t]) for t in _repartidas(unicas, raras)]
    claves = list(por_clave)
    for i in range(frases):
        palabras = por_clave[claves[i % len(claves)]]
        largo = 2 + i % 3
        inicios = _repartidas(range(max(1, len(palabras) - largo)), frases)
        inicio = inicios[i % len(inicios)]
        elegidas.append(("frase", " ".join(w for w, _ in palabras[inicio : inicio + largo])))
    for clave, largo in zip(claves, LARGAS, strict=False):
        palabras = por_clave[clave]
        inicio = max(0, len(palabras) // 2 - largo // 2)
        elegidas.append(("frase_larga", " ".join(w for w, _ in palabras[inicio : inicio + largo])))
    elegidas += [("sin_resultados", c) for c in SIN_RESULTADOS]
    vistas: set[str] = set()
    return [(t, c) for t, c in elegidas if not (c in vistas or vistas.add(c))]


def palabras_rnf03(analisis: Analisis, n: int = 10) -> list[tuple[str, float]]:
    """`n` palabras de un solo token que aparecen una sola vez en `analisis`, repartidas a lo
    largo del video, con su segundo de Whisper."""
    palabras = palabras_de(analisis)
    cuenta = Counter(t for w, _ in palabras for t in forma_busqueda(w).split())
    unicas = [
        (w, t)
        for w, t in palabras
        if len(forma_busqueda(w).split()) == 1 and cuenta[forma_busqueda(w)] == 1
    ]
    return _repartidas(unicas, n)


def percentil(valores: Sequence[float], p: float) -> float:
    """Percentil `p` (0–100) con interpolación lineal entre rangos."""
    if not valores:
        raise ValueError("sin valores")
    orden = sorted(valores)
    k = (len(orden) - 1) * p / 100
    piso = int(k)
    techo = min(piso + 1, len(orden) - 1)
    return orden[piso] + (orden[techo] - orden[piso]) * (k - piso)


def resumen(valores: Sequence[float]) -> dict[str, float]:
    return {
        "n": len(valores),
        "p50": round(percentil(valores, 50), 2),
        "p95": round(percentil(valores, 95), 2),
        "max": round(max(valores), 2),
    }


# ── Base ─────────────────────────────────────────────────────────────────────────────────────


def limpiar(session: Session, busquedas_desde: int | None = None) -> int:
    """Borra los videos sembrados (y en cascada sus palabras) y, con `busquedas_desde`, las
    búsquedas registradas después de ese id. Devuelve cuántos videos borró."""
    borrados = session.execute(delete(Video).where(Video.titulo.startswith(PREFIJO))).rowcount
    if busquedas_desde is not None:
        session.execute(delete(Busqueda).where(Busqueda.id > busquedas_desde))
    session.commit()
    return borrados


def por_video(valores: Sequence[float], decimales: int = 0) -> dict[str, float]:
    """Mínimo, media y máximo de una cantidad por video."""
    return {
        "min": round(min(valores), decimales),
        "media": round(sum(valores) / len(valores), decimales),
        "max": round(max(valores), decimales),
    }


def sembrar(session: Session, videos: Sequence[tuple[str, Analisis, bool]]) -> dict[str, Any]:
    """Publica los videos de `videos_sinteticos`. Devuelve sus ids, el del video de referencia
    y las palabras indexadas y la duración por video."""
    ids: list[int] = []
    referencia: int | None = None
    palabras: list[int] = []
    ahora = datetime.now(UTC)
    for n, (etiqueta, analisis, es_referencia) in enumerate(videos):
        video = Video(titulo=f"{PREFIJO} {etiqueta} #{n:02d}", archivo="", modo="generar")
        video.proceso = "listo"
        guardar_analisis(video, analisis)
        session.add(video)
        session.flush()
        palabras.append(busqueda.publicar(session, video, ahora).palabras_indexadas)
        ids.append(video.id)
        if es_referencia:
            referencia = video.id
    session.commit()
    return {
        "ids": ids,
        "referencia": referencia,
        "palabras": sum(palabras),
        "palabras_por_video": por_video(palabras),
        "minutos_por_video": por_video([a.duracion_s / 60 for _, a, _ in videos], 1),
    }


def explicar(session: Session, consulta: str) -> str:
    """`EXPLAIN (ANALYZE, BUFFERS)` de la sentencia principal de `consulta`, sin filtros."""
    tokens = busqueda.normalizar_consulta(consulta)
    settings = get_settings()
    parametros = busqueda.parametros_busqueda(
        tokens, unir_s=settings.busqueda_unir_s, limite=settings.busqueda_max_resultados
    )
    sql = "EXPLAIN (ANALYZE, BUFFERS) " + busqueda.sql_busqueda(len(tokens))
    return "\n".join(fila[0] for fila in session.execute(text(sql), parametros))


# ── Medición ─────────────────────────────────────────────────────────────────────────────────


def _post(cliente: TestClient, cuerpo: dict[str, Any]) -> tuple[dict[str, Any], float]:
    inicio = time.perf_counter()
    r = cliente.post("/buscar", json=cuerpo)
    total_ms = (time.perf_counter() - inicio) * 1000
    r.raise_for_status()
    return r.json(), total_ms


def medir(args: argparse.Namespace) -> dict[str, Any]:
    corpus = _corpus(args.videos)
    referencia = next(iter(corpus))
    consultas = elegir_consultas(corpus)
    cliente = TestClient(create_app(recuperar_interrumpidos=False))
    fabrica = get_sessionmaker()
    with fabrica() as session:
        restos = limpiar(session)
        if restos:
            logger.warning("Se borraron %d videos de una corrida anterior", restos)
        busquedas_desde = session.scalar(select(func.coalesce(func.max(Busqueda.id), 0)))
        try:
            sembrado = sembrar(session, videos_sinteticos(corpus, args.palabras_por_video))
            publicados = session.scalar(
                select(func.count()).select_from(Video).where(Video.publicado)
            )
            indexadas = session.scalar(select(func.count()).select_from(Palabra))
            logger.info(
                "%d videos sembrados (%d palabras); %d publicados en total, %d palabras",
                len(sembrado["ids"]),
                sembrado["palabras"],
                publicados,
                indexadas,
            )
            for _, consulta in consultas[:CALENTAMIENTO]:
                _post(cliente, {"consulta": consulta})
            filas = []
            for tipo, consulta in consultas:
                servidor, punta = [], []
                for _ in range(args.repeticiones):
                    cuerpo, ms = _post(cliente, {"consulta": consulta})
                    servidor.append(cuerpo["milisegundos"])
                    punta.append(ms)
                filas.append(
                    {
                        "tipo": tipo,
                        "consulta": consulta,
                        "tokens": len(busqueda.normalizar_consulta(consulta)),
                        "total": cuerpo["total"],
                        "devueltos": len(cuerpo["resultados"]),
                        "servidor_ms": servidor,
                        "punta_ms": punta,
                    }
                )
                logger.info("%-14s %-40s %5d  %.1f ms", tipo, consulta, cuerpo["total"], ms)
            lenta = max(filas, key=lambda f: max(f["punta_ms"]))
            plan = explicar(session, lenta["consulta"])
            rnf03 = []
            video_ref = sembrado["referencia"]
            for palabra, t in palabras_rnf03(corpus[referencia]):
                cuerpo, _ = _post(cliente, {"consulta": palabra, "video_id": video_ref})
                encontrado = cuerpo["resultados"][0]["t_inicio"] if cuerpo["resultados"] else None
                dif = None if encontrado is None else round(encontrado - t, 3)
                rnf03.append(
                    {
                        "palabra": palabra,
                        "t_transcripcion": t,
                        "t_resultado": encontrado,
                        "diferencia_s": dif,
                        "pasa": dif is not None and abs(dif) < TOLERANCIA_S,
                    }
                )
        finally:
            borrados = limpiar(session, busquedas_desde)
            logger.info("Limpieza: %d videos sembrados borrados", borrados)
    todos_servidor = [ms for f in filas for ms in f["servidor_ms"]]
    todos_punta = [ms for f in filas for ms in f["punta_ms"]]

    def _de(tipo: str, campo: str) -> list[float]:
        return [ms for f in filas if f["tipo"] == tipo for ms in f[campo]]

    por_tipo = {
        tipo: {
            "servidor": resumen(_de(tipo, "servidor_ms")),
            "punta": resumen(_de(tipo, "punta_ms")),
        }
        for tipo in dict.fromkeys(f["tipo"] for f in filas)
    }
    total = {"servidor": resumen(todos_servidor), "punta": resumen(todos_punta)}
    return {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "git": estado_git(),
        "videos_sembrados": len(sembrado["ids"]),
        "modo": "copias" if args.palabras_por_video is None else "concatenadas",
        "palabras_objetivo": args.palabras_por_video,
        "palabras_sembradas": sembrado["palabras"],
        "palabras_por_video": sembrado["palabras_por_video"],
        "minutos_por_video": sembrado["minutos_por_video"],
        "videos_publicados": publicados,
        "palabras_indice": indexadas,
        "repeticiones": args.repeticiones,
        "unir_s": get_settings().busqueda_unir_s,
        "consultas": filas,
        "por_tipo": por_tipo,
        "total": total,
        "rnf02_pasa": total["punta"]["p95"] < UMBRAL_MS,
        "consulta_lenta": lenta["consulta"],
        "explain": plan,
        "referencia": referencia,
        "rnf03": rnf03,
        "rnf03_pasa": len(rnf03) == 10 and all(r["pasa"] for r in rnf03),
    }


def _rango(r: dict[str, float]) -> str:
    return f"{r['min']:g}–{r['max']:g} (media {r['media']:g})"


def completar(datos: dict[str, Any], corpus: dict[str, Analisis]) -> dict[str, Any]:
    """Una corrida guardada antes de que el informe dijera las palabras y los minutos por video
    (las copias de A–E): se calculan con los mismos `analisis.json`, que fijan el índice."""
    if "palabras_por_video" in datos:
        return datos
    videos = videos_sinteticos(corpus)
    palabras = [len(busqueda.palabras_indexables(a)) for _, a, _ in videos]
    return datos | {
        "modo": "copias",
        "palabras_objetivo": None,
        "palabras_por_video": por_video(palabras),
        "minutos_por_video": por_video([a.duracion_s / 60 for _, a, _ in videos], 1),
        "nota": "palabras y minutos por video calculados al anexar, con los mismos analisis.json",
    }


def _titulo(datos: dict[str, Any]) -> str:
    if datos["modo"] == "copias":
        return "copias de A–E (un video por transcripción)"
    return f"A–E concatenadas hasta ~{datos['palabras_objetivo']} palabras por video"


def _corrida(i: int, datos: dict[str, Any]) -> list[str]:
    git = datos["git"]
    t = datos["total"]
    lineas = [
        f"## Corrida {i}: {_titulo(datos)} ({datos['fecha']})",
        "",
        f"Commit `{(git['commit'] or '?')[:7]}` en `{git['rama']}`"
        f" ({git['cambios_sin_commit']} archivos con cambios sin commit).",
        "",
        f"- Índice: {datos['videos_publicados']} videos publicados"
        f" ({datos['videos_sembrados']} sembrados), {datos['palabras_indice']} palabras.",
        f"- **Palabras por video:** {_rango(datos['palabras_por_video'])};"
        f" minutos por video: {_rango(datos['minutos_por_video'])}.",
    ]
    if datos.get("nota"):
        lineas.append(f"  ({datos['nota']}.)")
    lineas += [
        f"- {len(datos['consultas'])} consultas × {datos['repeticiones']} repeticiones,"
        f" tras {CALENTAMIENTO} de calentamiento; `BUSQUEDA_UNIR_S={datos['unir_s']:g}`.",
        f"- **RNF-02 (< {UMBRAL_MS:.0f} ms):** {'pasa' if datos['rnf02_pasa'] else 'NO pasa'}"
        f" · punta a punta p50 {t['punta']['p50']} ms, p95 {t['punta']['p95']} ms"
        f" · servidor p50 {t['servidor']['p50']} ms, p95 {t['servidor']['p95']} ms.",
        f"- **RNF-03 (±{TOLERANCIA_S:g} s):** {'pasa' if datos['rnf03_pasa'] else 'NO pasa'}"
        f" ({sum(r['pasa'] for r in datos['rnf03'])} de {len(datos['rnf03'])}).",
        "",
        "### Por tipo de consulta (ms)",
        "",
        "| Tipo | n | Servidor p50 | Servidor p95 | Punta p50 | Punta p95 | Punta máx |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for tipo, r in [*datos["por_tipo"].items(), ("total", datos["total"])]:
        s, p = r["servidor"], r["punta"]
        lineas.append(
            f"| {tipo} | {p['n']} | {s['p50']} | {s['p95']} | {p['p50']} | {p['p95']} "
            f"| {p['max']} |"
        )
    lineas += [
        "",
        "### Consultas",
        "",
        "| Tipo | Consulta | Tokens | Total | Devueltos | Servidor p50 | Punta p50 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for f in datos["consultas"]:
        lineas.append(
            f"| {f['tipo']} | {f['consulta']} | {f['tokens']} | {f['total']} | {f['devueltos']} "
            f"| {percentil(f['servidor_ms'], 50):.2f} | {percentil(f['punta_ms'], 50):.2f} |"
        )
    donde = (
        "copia sin desplazar"
        if datos["modo"] == "copias"
        else "video 0, que empieza por ella sin desplazar; si la palabra se repite más adelante "
        "en el video, cuenta el primer resultado"
    )
    lineas += [
        "",
        f"### RNF-03: 10 palabras de {datos['referencia']} ({donde})",
        "",
        "| Palabra | t transcripción | t resultado | Diferencia (s) | Pasa |",
        "|---|---:|---:|---:|---|",
    ]
    for r in datos["rnf03"]:
        lineas.append(
            f"| {r['palabra']} | {r['t_transcripcion']} | {r['t_resultado']} "
            f"| {r['diferencia_s']} | {'sí' if r['pasa'] else 'no'} |"
        )
    lineas += [
        "",
        f"### EXPLAIN ANALYZE de la consulta más lenta: «{datos['consulta_lenta']}»",
        "",
        "Solo la sentencia principal (coincidencias, unión y orden); la de la frase trae a lo",
        "más 50 ventanas por el único `(video_id, posicion)`.",
        "",
        "```",
        datos["explain"],
        "```",
        "",
    ]
    return lineas


def informe(corridas: Sequence[dict[str, Any]]) -> str:
    """El informe en Markdown: un resumen de todas las corridas y el detalle de cada una."""
    lineas = [
        "# Medición de la búsqueda exacta (RNF-02, RNF-03)",
        "",
        "`scripts/medir_busqueda.py`, solo Postgres. Videos sintéticos publicados a partir de las",
        "transcripciones de A–E (videos del equipo); se borran al terminar.",
        "",
        "| Corrida | Videos | Palabras por video | Min por video | Palabras en el índice "
        "| Punta p50 | Punta p95 | Servidor p95 | RNF-02 | RNF-03 |",
        "|---|---:|---|---|---:|---:|---:|---:|---|---|",
    ]
    for i, d in enumerate(corridas, start=1):
        t = d["total"]
        lineas.append(
            f"| {i}: {_titulo(d)} | {d['videos_publicados']} | {_rango(d['palabras_por_video'])} "
            f"| {_rango(d['minutos_por_video'])} | {d['palabras_indice']} "
            f"| {t['punta']['p50']} ms | {t['punta']['p95']} ms | {t['servidor']['p95']} ms "
            f"| {'pasa' if d['rnf02_pasa'] else 'NO pasa'} "
            f"| {'pasa' if d['rnf03_pasa'] else 'NO pasa'} |"
        )
    lineas.append("")
    for i, d in enumerate(corridas, start=1):
        lineas += _corrida(i, d)
    return "\n".join(lineas)


def _corpus(videos: Sequence[str]) -> dict[str, Analisis]:
    return {
        clave: Analisis.model_validate_json(Path(ruta).read_text(encoding="utf-8"))
        for clave, ruta in (v.split("=", 1) for v in videos)
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+", help="clave=ruta del analisis.json (A primero)")
    parser.add_argument("--repeticiones", type=int, default=5)
    parser.add_argument(
        "--palabras-por-video",
        type=int,
        help="concatena A–E hasta este número de palabras por video (sin él, una copia por video)",
    )
    parser.add_argument(
        "--anexar", type=Path, help="informe existente (.md o .json) al que se agrega la corrida"
    )
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("sopvid").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    corridas: list[dict[str, Any]] = []
    if args.anexar is not None:
        base = args.anexar.with_suffix("")
        previo = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
        corpus = _corpus(args.videos)
        corridas = [completar(d, corpus) for d in previo.get("corridas", [previo])]
    else:
        args.salida.mkdir(parents=True, exist_ok=True)
        base = args.salida / f"medicion-busqueda-{datetime.now().strftime('%Y%m%d-%H%M')}"
    datos = medir(args)
    corridas.append(datos)
    base.with_suffix(".json").write_text(
        json.dumps({"corridas": corridas}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    base.with_suffix(".md").write_text(informe(corridas), encoding="utf-8")
    print(f"Informe: {base.with_suffix('.md')}")
    t = datos["total"]["punta"]
    print(
        f"Palabras por video: {_rango(datos['palabras_por_video'])}. "
        f"RNF-02: p50 {t['p50']} ms, p95 {t['p95']} ms: "
        f"{'pasa' if datos['rnf02_pasa'] else 'NO pasa'}; "
        f"RNF-03: {'pasa' if datos['rnf03_pasa'] else 'NO pasa'}"
    )
    return 0 if datos["rnf02_pasa"] and datos["rnf03_pasa"] else 1


if __name__ == "__main__":
    sys.exit(main())
