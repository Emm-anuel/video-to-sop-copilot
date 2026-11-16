"""Índice de la búsqueda exacta (RF-32, RF-33): las palabras de un video publicado en `palabras`.

Publicar un video arma una fila por palabra de su transcripción, en el orden en que se dijo:

- `posicion` es consecutiva en **todo el video** (0, 1, 2…), no por segmento: una frase que cruza
  de un segmento al siguiente se encuentra igual.
- `palabra_normalizada` sale de `texto.forma_busqueda`, la misma función por la que pasa la
  consulta (sin acentos ni mayúsculas, sin signos, plural simple). No hay otra normalización.
- `palabra_original` es la palabra como la escribió Whisper (con acentos y signos), para mostrar
  la frase; `t_inicio` y `t_fin` son los suyos, sin redondear (RNF-03, regla 4 de CLAUDE.md).
- Una palabra de Whisper que da varios tokens al normalizar ("11:30" → "11" "30", "O-rings" →
  "o" "ring") da una fila por token, con posiciones seguidas y el mismo tiempo y original.
- Una palabra que queda vacía al normalizar (solo signos, "%", "°", un emoji, otra escritura) no
  se indexa ni gasta posición. Como la consulta pierde los mismos símbolos, una frase sigue
  coincidiendo: "50 % de carga" se busca como "50 de carga" y la encuentra, y "A — B" coincide con
  "A B". Lo que no se puede es buscar el símbolo solo.
- Un segmento sin tiempos por palabra (análisis viejos; hoy Whisper siempre los da) indexa los
  tokens de su texto con el inicio y el fin del segmento: ahí el segundo puede quedar a más de
  1 s de la palabra (RNF-03 no se garantiza).

`indexar` y `desindexar` no hacen commit: quien llama junta el índice y las columnas del video
(`publicar`, `despublicar`) en una sola transacción. Con `PUBLICAR_AL_TERMINAR=true`, el
trabajador publica cada video al quedar listo (`publicar_al_terminar`).

**Búsqueda (RF-33 a RF-35, RF-37; `POST /buscar`).** La consulta pasa por la misma
`forma_busqueda` (`normalizar_consulta`): sus tokens vacíos se descartan como en el índice. Una
frase de k tokens coincide donde hay k filas del mismo video con posiciones consecutivas y esas
formas en orden; todo en una sola sentencia SQL (`sql_busqueda`): un self-join por posición que
resuelven los índices de la 0002 (más allá de `TOKENS_UNIDOS`, un arreglo por candidato, para
que una frase larga no dispare la planificación), solo en videos publicados, la unión en cadena
de RF-35 con funciones de ventana por video (cada coincidencia que empieza a menos de `unir_s`
segundos de la anterior se une; con 0 no se une nada) y el total antes del tope. La frase de
contexto (RF-34) sale de una segunda sentencia que trae solo una ventana de filas alrededor de
cada resultado (`frases`); `armar_frase` vuelve a juntar en una palabra los tokens de "11:30".
"""

import logging
import unicodedata
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import Exists, delete, func, insert, select, text
from sqlalchemy.orm import Session

from sopvid.contrato import (
    Analisis,
    EstadoPublicacion,
    OpcionesBusqueda,
    SopDeVideo,
    VideoPublicado,
)
from sopvid.plataforma.modelos import Palabra, Sop, Video
from sopvid.plataforma.procesamiento import leer_analisis
from sopvid.texto import forma_busqueda

logger = logging.getLogger(__name__)

LARGO_PALABRA = 100  # `palabras.palabra_normalizada` y `palabra_original` son String(100)


@dataclass(frozen=True)
class PalabraIndice:
    """Una fila del índice, sin el video."""

    posicion: int
    palabra_normalizada: str
    palabra_original: str
    t_inicio: float
    t_fin: float


def palabras_indexables(analisis: Analisis) -> list[PalabraIndice]:
    """Las filas del índice de un análisis, en orden y con posiciones 0..n-1 (ver el módulo)."""
    crudas: list[tuple[str, float, float]] = []
    for segmento in analisis.transcripcion:
        if segmento.palabras:
            crudas += [(p.w, p.t, p.t_fin) for p in segmento.palabras]
        else:
            crudas += [(w, segmento.t_inicio, segmento.t_fin) for w in segmento.texto.split()]
    filas: list[PalabraIndice] = []
    for palabra, t_inicio, t_fin in crudas:
        original = palabra.strip()[:LARGO_PALABRA]
        for token in forma_busqueda(original).split():
            filas.append(
                PalabraIndice(len(filas), token[:LARGO_PALABRA], original, t_inicio, t_fin)
            )
    return filas


def indexar(session: Session, video: Video) -> int:
    """Reemplaza las palabras de `video` en el índice por las de su transcripción guardada, en
    bloque. Devuelve cuántas filas quedaron. No hace commit."""
    filas = palabras_indexables(leer_analisis(video))
    desindexar(session, video)
    if filas:
        session.execute(insert(Palabra), [{"video_id": video.id, **asdict(f)} for f in filas])
    return len(filas)


def desindexar(session: Session, video: Video) -> int:
    """Borra las palabras de `video` del índice. Devuelve cuántas había. No hace commit."""
    return session.execute(delete(Palabra).where(Palabra.video_id == video.id)).rowcount


def contar(session: Session, video: Video) -> int:
    """Cuántas palabras tiene `video` en el índice."""
    consulta = select(func.count()).select_from(Palabra).where(Palabra.video_id == video.id)
    return session.scalar(consulta) or 0


def publicar(session: Session, video: Video, ahora: datetime) -> EstadoPublicacion:
    """Indexa `video` y lo marca publicado en `ahora` (otra vez: reemplaza el índice y pone la
    fecha al día). Quien llama revisa que el análisis esté terminado y hace commit."""
    n = indexar(session, video)
    video.publicado, video.publicado_en = True, ahora
    return EstadoPublicacion(
        video_id=video.id, publicado=True, publicado_en=ahora, palabras_indexadas=n
    )


def despublicar(session: Session, video: Video) -> EstadoPublicacion:
    """Quita `video` del índice y lo marca sin publicar. Quien llama hace commit."""
    desindexar(session, video)
    video.publicado, video.publicado_en = False, None
    return EstadoPublicacion(video_id=video.id, publicado=False, palabras_indexadas=0)


def publicar_al_terminar(session: Session, video_id: int) -> None:
    """Gancho del trabajador con `PUBLICAR_AL_TERMINAR=true`: publica el video que acaba de
    quedar listo, salvo que ya estuviera publicado (repetir la validación no toca la
    transcripción). Hace commit."""
    video = session.get(Video, video_id, with_for_update=True)
    if video is None or video.publicado:
        return
    estado = publicar(session, video, datetime.now(UTC))
    session.commit()
    logger.info("Video %d publicado al terminar: %d palabras", video_id, estado.palabras_indexadas)


# ── Búsqueda ─────────────────────────────────────────────────────────────────────────────────

PALABRAS_CONTEXTO = 8  # palabras originales antes y después de la coincidencia (RF-34)
# Filas del índice que se traen a cada lado: una palabra original puede dar varios tokens
# ("11:30"), así que el doble de las palabras más una, para saber si la frase se recorta.
MARGEN_FILAS = 2 * PALABRAS_CONTEXTO + 1


def normalizar_consulta(texto: str) -> list[str]:
    """Los tokens que se buscan, en orden: `forma_busqueda` palabra por palabra, sin los que
    quedan vacíos (solo signos), igual que al indexar. Vacía si no queda nada que buscar."""
    return forma_busqueda(texto).split()


TOKENS_UNIDOS = 4  # tokens que se resuelven con self-join; los demás, con un solo arreglo


def sql_busqueda(k: int, *, por_video: bool = False, por_sop: bool = False) -> str:
    """La sentencia de `buscar` para una consulta de `k` tokens. Solo números entran al texto;
    la consulta va siempre como parámetro (`parametros_busqueda`).

    Los primeros `TOKENS_UNIDOS` tokens se encuentran con un self-join por posición (`:q0`…),
    que resuelve el índice `(palabra_normalizada, video_id, posicion)`. Si la consulta es más
    larga, cada candidato se confirma comparando el arreglo de formas de sus `k` posiciones con
    el de la consulta (`:tokens`), por el único `(video_id, posicion)`: un join por token haría
    crecer el tiempo de planificación con k (con 30 tokens, ~250 ms; con 250, ~40 s), y así
    queda constante.
    """
    if k < 1:
        raise ValueError("la consulta necesita al menos un token")
    filtros = (" AND v.id = :video_id" if por_video else "") + (
        " AND v.sop_id = :sop_id" if por_sop else ""
    )
    unidos = min(k, TOKENS_UNIDOS)
    uniones = "".join(
        f"\n  JOIN palabras p{i} ON p{i}.video_id = p0.video_id"
        f" AND p{i}.posicion = p0.posicion + {i} AND p{i}.palabra_normalizada = :q{i}"
        for i in range(1, unidos)
    )
    ultima, resto = f"p{unidos - 1}", ""
    if k > unidos:
        ultima = "pf"
        uniones += (
            "\n  JOIN palabras pf ON pf.video_id = p0.video_id"
            f" AND pf.posicion = p0.posicion + {k - 1}"
        )
        resto = (
            "\n    AND (SELECT array_agg(p.palabra_normalizada::text ORDER BY p.posicion)"
            "\n         FROM palabras p WHERE p.video_id = p0.video_id"
            f"\n           AND p.posicion BETWEEN p0.posicion AND p0.posicion + {k - 1})"
            " = CAST(:tokens AS text[])"
        )
    return f"""WITH coincidencias AS (
  SELECT p0.video_id, p0.posicion AS pos_ini, {ultima}.posicion AS pos_fin,
         p0.t_inicio, {ultima}.t_fin
  FROM palabras p0
  JOIN videos v ON v.id = p0.video_id AND v.publicado{filtros}{uniones}
  WHERE p0.palabra_normalizada = :q0{resto}
),
marcadas AS (
  SELECT c.*,
         CASE WHEN c.t_inicio - lag(c.t_inicio) OVER w < :unir_s THEN 0 ELSE 1 END AS nueva
  FROM coincidencias c
  WINDOW w AS (PARTITION BY c.video_id ORDER BY c.t_inicio, c.pos_ini)
),
cadenas AS (
  SELECT m.*, sum(m.nueva) OVER (PARTITION BY m.video_id
                                 ORDER BY m.t_inicio, m.pos_ini) AS cadena
  FROM marcadas m
),
unidas AS (
  SELECT DISTINCT ON (c.video_id, c.cadena)
         c.video_id, c.pos_ini, c.pos_fin, c.t_inicio, c.t_fin,
         count(*) OVER (PARTITION BY c.video_id, c.cadena) AS coincidencias
  FROM cadenas c
  ORDER BY c.video_id, c.cadena, c.t_inicio, c.pos_ini
)
SELECT u.video_id, u.pos_ini, u.pos_fin, u.t_inicio, u.t_fin, u.coincidencias,
       v.titulo, v.archivo, s.id AS sop_id, s.codigo AS sop_codigo, s.titulo AS sop_titulo,
       count(*) OVER () AS total
FROM unidas u
JOIN videos v ON v.id = u.video_id
LEFT JOIN sops s ON s.id = v.sop_id
ORDER BY v.creado DESC, v.id DESC, u.t_inicio, u.pos_ini
LIMIT :limite"""


def parametros_busqueda(
    tokens: Sequence[str],
    *,
    video_id: int | None = None,
    sop_id: int | None = None,
    unir_s: float,
    limite: int,
) -> dict[str, object]:
    """Los parámetros de `sql_busqueda` para `tokens` y los filtros."""
    parametros: dict[str, object] = {f"q{i}": t for i, t in enumerate(tokens[:TOKENS_UNIDOS])}
    if len(tokens) > TOKENS_UNIDOS:
        parametros["tokens"] = list(tokens)
    parametros |= {"unir_s": unir_s, "limite": limite}
    if video_id is not None:
        parametros["video_id"] = video_id
    if sop_id is not None:
        parametros["sop_id"] = sop_id
    return parametros


@dataclass(frozen=True)
class Coincidencia:
    """Un resultado de `buscar`: la primera coincidencia de su cadena (RF-35) y cuántas se
    unieron. `pos_ini`/`pos_fin` son las posiciones de su primer y último token en el índice."""

    video_id: int
    titulo: str
    archivo: str
    pos_ini: int
    pos_fin: int
    t_inicio: float
    t_fin: float
    coincidencias: int
    sop: SopDeVideo | None


def buscar(
    session: Session,
    tokens: Sequence[str],
    *,
    video_id: int | None = None,
    sop_id: int | None = None,
    unir_s: float,
    limite: int,
) -> tuple[int, list[Coincidencia]]:
    """Los resultados de la frase `tokens` (de `normalizar_consulta`) en los videos publicados,
    ya unidos (RF-35), por video (el más reciente primero) y dentro, por segundo; a lo más
    `limite`. Devuelve también el total antes del tope. Un filtro que no existe, sin publicar o
    que no se cruza con el otro da (0, [])."""
    if not tokens:
        raise ValueError("la consulta no tiene tokens")
    sql = sql_busqueda(len(tokens), por_video=video_id is not None, por_sop=sop_id is not None)
    filas = session.execute(
        text(sql),
        parametros_busqueda(tokens, video_id=video_id, sop_id=sop_id, unir_s=unir_s, limite=limite),
    ).all()
    total = filas[0].total if filas else 0
    return total, [
        Coincidencia(
            video_id=f.video_id,
            titulo=f.titulo,
            archivo=f.archivo,
            pos_ini=f.pos_ini,
            pos_fin=f.pos_fin,
            t_inicio=f.t_inicio,
            t_fin=f.t_fin,
            coincidencias=f.coincidencias,
            sop=(
                SopDeVideo(id=f.sop_id, codigo=f.sop_codigo, titulo=f.sop_titulo)
                if f.sop_id is not None
                else None
            ),
        )
        for f in filas
    ]


@dataclass(frozen=True)
class Frase:
    """La frase de un resultado (RF-34): `texto[rango[0]:rango[1]]` es la coincidencia, sin los
    signos de puntuación pegados al inicio de su primera palabra ni al final de la última."""

    texto: str
    rango: tuple[int, int]
    recorte_inicio: bool
    recorte_fin: bool


@dataclass(frozen=True)
class _PalabraOriginal:
    primera: int  # posición de su primer token
    ultima: int  # posición de su último token
    original: str


def _palabras_originales(
    filas: Sequence[tuple[int, str, str]], agrupar: bool = True
) -> list[_PalabraOriginal]:
    """Las filas `(posicion, palabra_normalizada, palabra_original)` de una ventana, en orden,
    vueltas palabras originales: los tokens de "11:30" ("11", "30") son una sola. Una fila que es
    la cola de una palabra que empezó antes de la ventana se salta; una palabra cortada al final
    de la ventana se descarta. Con `agrupar=False`, cada fila es una palabra."""
    palabras: list[_PalabraOriginal] = []
    i = 0
    while i < len(filas):
        posicion, normalizada, original = filas[i]
        tokens = forma_busqueda(original).split() if agrupar else []
        if len(tokens) <= 1:
            palabras.append(_PalabraOriginal(posicion, posicion, original))
            i += 1
            continue
        if normalizada != tokens[0]:  # cola de una palabra anterior a la ventana
            i += 1
            continue
        grupo = filas[i : i + len(tokens)]
        if len(grupo) < len(tokens):  # cortada al final de la ventana
            break
        completo = all(
            (p, n, o) == (posicion + j, tokens[j], original) for j, (p, n, o) in enumerate(grupo)
        )
        if not completo:  # no debería pasar: el índice se arma con la misma función
            palabras.append(_PalabraOriginal(posicion, posicion, original))
            i += 1
            continue
        palabras.append(_PalabraOriginal(posicion, grupo[-1][0], original))
        i += len(tokens)
    return palabras


def armar_frase(
    filas: Sequence[tuple[int, str, str]],
    pos_ini: int,
    pos_fin: int,
    ventana_hasta: int,
    contexto: int = PALABRAS_CONTEXTO,
) -> Frase:
    """La frase de la coincidencia de tokens `pos_ini`…`pos_fin` con hasta `contexto` palabras
    originales a cada lado, a partir de las filas de su ventana (`frases`). Al inicio o al final
    del video hay menos palabras, nunca índices negativos. `ventana_hasta`: la última posición
    que se pidió; si la ventana llegó a ella, se supone que el video sigue."""
    palabras = _palabras_originales(filas)
    dentro = [i for i, p in enumerate(palabras) if p.ultima >= pos_ini and p.primera <= pos_fin]
    if not dentro:  # una palabra de más tokens que el margen: sin agrupar
        palabras = _palabras_originales(filas, agrupar=False)
        dentro = [i for i, p in enumerate(palabras) if pos_ini <= p.primera <= pos_fin]
    a, b = dentro[0], dentro[-1]
    desde, hasta = max(0, a - contexto), min(len(palabras), b + 1 + contexto)
    antes = " ".join(p.original for p in palabras[desde:a])
    coincidencia = " ".join(p.original for p in palabras[a : b + 1])
    despues = " ".join(p.original for p in palabras[b + 1 : hasta])
    inicio = len(antes) + (1 if antes else 0)
    fin = inicio + len(coincidencia)
    texto = " ".join(t for t in (antes, coincidencia, despues) if t)
    inicio, fin = _sin_signos_en_bordes(texto, inicio, fin)
    ultima_fila = filas[-1][0]
    return Frase(
        texto=texto,
        rango=(inicio, fin),
        recorte_inicio=palabras[desde].primera > 0,
        recorte_fin=palabras[hasta - 1].ultima < ultima_fila or ultima_fila >= ventana_hasta,
    )


def _es_signo(caracter: str) -> bool:
    """Un signo de puntuación de Unicode (categorías P*: . , ; ¿ ? ¡ ! « » " ' ( ) …)."""
    return unicodedata.category(caracter).startswith("P")


def _sin_signos_en_bordes(texto: str, inicio: int, fin: int) -> tuple[int, int]:
    """El rango `[inicio, fin)` sin los signos de puntuación del principio y del final: se
    resalta «cartucho», no «cartucho.», ni las comillas de «“válvula». Los signos de en medio
    ("O-rings", "11:30") se quedan. Si el rango es solo signos, no se toca (nunca queda vacío)."""
    a, b = inicio, fin
    while a < b and _es_signo(texto[a]):
        a += 1
    while b > a and _es_signo(texto[b - 1]):
        b -= 1
    return (a, b) if a < b else (inicio, fin)


SQL_VENTANAS = """SELECT r.orden, p.posicion, p.palabra_normalizada, p.palabra_original
FROM unnest(CAST(:videos AS integer[]), CAST(:desde AS integer[]), CAST(:hasta AS integer[]))
     WITH ORDINALITY AS r(video_id, desde, hasta, orden)
JOIN palabras p ON p.video_id = r.video_id AND p.posicion BETWEEN r.desde AND r.hasta
ORDER BY r.orden, p.posicion"""


def frases(session: Session, coincidencias: Sequence[Coincidencia]) -> list[Frase]:
    """La frase de cada coincidencia, en el mismo orden, con una sola sentencia que trae solo
    `MARGEN_FILAS` filas a cada lado de cada una (nunca el video entero)."""
    if not coincidencias:
        return []
    hasta = [c.pos_fin + MARGEN_FILAS for c in coincidencias]
    ventanas: list[list[tuple[int, str, str]]] = [[] for _ in coincidencias]
    filas = session.execute(
        text(SQL_VENTANAS),
        {
            "videos": [c.video_id for c in coincidencias],
            "desde": [max(0, c.pos_ini - MARGEN_FILAS) for c in coincidencias],
            "hasta": hasta,
        },
    )
    for orden, posicion, normalizada, original in filas:
        ventanas[orden - 1].append((posicion, normalizada, original))
    return [
        armar_frase(ventana, c.pos_ini, c.pos_fin, tope)
        for ventana, c, tope in zip(ventanas, coincidencias, hasta, strict=True)
    ]


def opciones(session: Session) -> OpcionesBusqueda:
    """Los selectores de `/buscar` (RF-37): los videos publicados, el más reciente primero, y los
    SOP con al menos un video publicado (de referencia o generado), por número."""
    videos = session.execute(
        select(Video.id, Video.titulo, Video.sop_id)
        .where(Video.publicado)
        .order_by(Video.creado.desc(), Video.id.desc())
    ).all()
    sops = session.execute(
        select(Sop.id, Sop.codigo, Sop.titulo).where(_con_publicado()).order_by(Sop.id)
    ).all()
    return OpcionesBusqueda(
        videos=[VideoPublicado(id=i, titulo=t, sop_id=s) for i, t, s in videos],
        sops=[SopDeVideo(id=i, codigo=c, titulo=t) for i, c, t in sops],
    )


def _con_publicado() -> Exists:
    """`EXISTS`: el SOP de la fila tiene al menos un video publicado (de referencia o generado)."""
    return select(Video.id).where(Video.sop_id == Sop.id, Video.publicado).exists()


def video_publicado(session: Session, video_id: int) -> bool:
    """True si el video existe y está publicado: lo que la vista de búsqueda puede ver (ADR-027)."""
    return bool(session.scalar(select(Video.publicado).where(Video.id == video_id)))


def sop_con_publicado(session: Session, sop_id: int) -> bool:
    """True si el SOP existe y tiene un video publicado ("Ver SOP" de `/buscar`, ADR-027)."""
    return session.scalar(select(Sop.id).where(Sop.id == sop_id, _con_publicado())) is not None
