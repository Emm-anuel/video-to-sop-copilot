/**
 * Edición del SOP (RF-26, RF-04): funciones puras sobre un borrador, sin Angular. El editor
 * (`sop-editor.ts`) guarda el borrador en un signal y lo cambia solo con estas funciones.
 *
 * - Cada paso lleva una `clave` estable mientras se edita y los riesgos apuntan a esa clave,
 *   no al número: reordenar, unir o quitar no rompe el `paso` de un riesgo. `aSop` pone los
 *   números 1..n y el `paso` de cada riesgo al guardar; la persona no los escribe.
 * - `t_inicio` y `t_fin` salen del video y nunca se editan (regla 4 de CLAUDE.md); solo cambian
 *   al unir dos pasos (el mínimo y el máximo de los dos).
 * - Editar o confirmar un dato lo marca `revisado` (ADR-025) y, en un paso, saca el campo de
 *   `campos_inferidos`. La fuente, la confianza y la cita no se tocan (RF-25).
 */

import {
  Confianza3 as Confianza,
  Dato,
  Elemento,
  Evidencia1 as Evidencia,
  Falla,
  PalabraClave,
  PasoSOP,
  PuntoClave,
  Resumen,
  Riesgo,
  SOP,
} from '../api/sop';

/** Datos del cuadro resumen que se editan como texto. */
export const CAMPOS_DATO = [
  'objetivo',
  'alcance',
  'responsable',
  'lugar',
  'horario_frecuencia',
] as const;
export type CampoDato = (typeof CAMPOS_DATO)[number];

/** Campos de un paso que la persona edita (los tiempos del video, no). */
export type CampoPaso =
  'nombre' | 'descripcion' | 'responsable' | 'equipo' | 'puntos_validacion' | 'tiempo_esperado_min';

export type PasoBorrador = Required<Omit<PasoSOP, 'numero'>> & { clave: number };
export type RiesgoBorrador = Required<Omit<Riesgo, 'paso'>> & { pasoClave: number | null };
export type FallaBorrador = Required<Falla>;
export type PuntoBorrador = Required<PuntoClave>;

export interface ResumenBorrador {
  version: string;
  objetivo: Required<Dato>;
  alcance: Required<Dato>;
  responsable: Required<Dato>;
  lugar: Required<Dato>;
  horario_frecuencia: Required<Dato>;
  duracion_total_min: number | null;
  equipo_operacion: Elemento[];
  roles: Elemento[];
  personas: NonNullable<Resumen['personas']>;
  riesgos: RiesgoBorrador[];
  en_caso_de_falla: FallaBorrador[];
}

export interface Borrador {
  titulo: string;
  /**
   * La duración total que dijo el operador (`generacion.duracion_narrada`, ADR-021), o null.
   * No va en el SOP: solo decide la duración total que se muestra y que guarda la API.
   */
  duracionNarrada: number | null;
  resumen: ResumenBorrador;
  pasos: PasoBorrador[];
  puntos_clave: PuntoBorrador[];
  palabras_clave: PalabraClave[];
}

/** Un paso quitado, para deshacerlo en la misma sesión. */
export interface Quitado {
  paso: PasoBorrador;
  indice: number;
}

export type ResultadoUnion =
  { ok: true; borrador: Borrador } | { ok: false; responsables: [string, string] };

const ORDEN_CONFIANZA: Record<Confianza, number> = { baja: 0, media: 1, alta: 2 };

function dato(d: Dato | undefined): Required<Dato> {
  return {
    valor: d?.valor ?? null,
    confianza: d?.confianza ?? 'alta',
    fuente: d?.fuente ?? 'documento',
    t: d?.t ?? null,
    cita: d?.cita ?? '',
    revisado: d?.revisado ?? false,
  };
}

function pasoBorrador(p: PasoSOP, clave: number): PasoBorrador {
  return {
    clave,
    nombre: p.nombre,
    descripcion: p.descripcion ?? '',
    responsable: p.responsable,
    equipo: [...(p.equipo ?? [])],
    puntos_validacion: [...(p.puntos_validacion ?? [])],
    tiempo_esperado_min: p.tiempo_esperado_min ?? null,
    t_inicio: p.t_inicio ?? null,
    t_fin: p.t_fin ?? null,
    confianza: p.confianza ?? 'alta',
    campos_inferidos: [...(p.campos_inferidos ?? [])],
    cita: p.cita ?? '',
    fuente: p.fuente ?? 'documento',
    evidencia: (p.evidencia ?? []).map((e) => ({ ...e })),
    revisado: p.revisado ?? false,
  };
}

/** El SOP de la API como borrador: claves 1..n y los riesgos apuntando a la clave de su paso. */
export function aBorrador(sop: SOP, duracionNarrada: number | null = null): Borrador {
  const pasos = sop.pasos.map((p, i) => pasoBorrador(p, i + 1));
  const r = sop.resumen ?? {};
  return {
    titulo: sop.titulo,
    duracionNarrada,
    resumen: {
      version: r.version ?? '1.0',
      objetivo: dato(r.objetivo),
      alcance: dato(r.alcance),
      responsable: dato(r.responsable),
      lugar: dato(r.lugar),
      horario_frecuencia: dato(r.horario_frecuencia),
      duracion_total_min: r.duracion_total_min ?? null,
      equipo_operacion: (r.equipo_operacion ?? []).map((e) => ({ ...e })),
      roles: (r.roles ?? []).map((e) => ({ ...e })),
      personas: (r.personas ?? []).map((p) => ({ ...p })),
      riesgos: (r.riesgos ?? []).map(({ paso, ...x }) => ({
        descripcion: x.descripcion,
        nivel: x.nivel,
        control: x.control ?? '',
        cita: x.cita ?? '',
        fuente: x.fuente ?? 'documento',
        confianza: x.confianza ?? 'alta',
        t: x.t ?? null,
        revisado: x.revisado ?? false,
        // Un número fuera de rango no apunta a ningún paso.
        pasoClave: paso != null && paso >= 1 && paso <= pasos.length ? paso : null,
      })),
      en_caso_de_falla: (r.en_caso_de_falla ?? []).map((f) => ({
        situacion: f.situacion,
        accion: f.accion,
        cita: f.cita ?? '',
        fuente: f.fuente ?? 'documento',
        confianza: f.confianza ?? 'alta',
        t: f.t ?? null,
        revisado: f.revisado ?? false,
      })),
    },
    pasos,
    puntos_clave: (sop.puntos_clave ?? []).map((x) => ({
      texto: x.texto,
      t: x.t ?? null,
      cita: x.cita ?? '',
      fuente: x.fuente ?? 'documento',
      confianza: x.confianza ?? 'alta',
      revisado: x.revisado ?? false,
    })),
    palabras_clave: (sop.palabras_clave ?? []).map((x) => ({ ...x, t: [...(x.t ?? [])] })),
  };
}

/**
 * La duración total como la pone `PUT /sops/{id}` (ADR-025, `con_duracion_recalculada`): la
 * narrada por el operador si la hay (ADR-021: gana e incluye pausas); si no, la suma si todos los
 * pasos tienen tiempo, la que había si ninguno y null si solo algunos.
 */
export function duracionTotal(
  pasos: readonly { tiempo_esperado_min: number | null }[],
  actual: number | null,
  narrada: number | null = null,
): number | null {
  if (narrada !== null) {
    return narrada;
  }
  const esperados = pasos.map((p) => p.tiempo_esperado_min);
  if (esperados.every((e) => e === null)) {
    return actual;
  }
  if (esperados.some((e) => e === null)) {
    return null;
  }
  return redondear(esperados.reduce<number>((a, e) => a + (e ?? 0), 0));
}

/** El SOP del contrato listo para `PUT /sops/{id}`: números 1..n y riesgos según su paso. */
export function aSop(b: Borrador): SOP {
  const numero = new Map(b.pasos.map((p, i) => [p.clave, i + 1]));
  const pasos = b.pasos.map(({ clave, ...p }, i) => ({ numero: i + 1, ...p }));
  const { riesgos, ...resumen } = b.resumen;
  return {
    version_contrato: 1,
    titulo: b.titulo,
    resumen: {
      ...resumen,
      duracion_total_min: duracionTotal(b.pasos, b.resumen.duracion_total_min, b.duracionNarrada),
      riesgos: riesgos.map(({ pasoClave, ...x }) => ({
        ...x,
        paso: pasoClave === null ? null : (numero.get(pasoClave) ?? null),
      })),
    },
    pasos: pasos as SOP['pasos'],
    puntos_clave: b.puntos_clave,
    palabras_clave: b.palabras_clave,
  };
}

/**
 * JSON con las claves ordenadas y sin la duración total (la recalcula la API): sirve para saber
 * si hay cambios sin guardar y para comprobar que lo guardado es lo que se veía en pantalla.
 */
export function huella(sop: SOP): string {
  const copia = structuredClone(sop);
  if (copia.resumen) {
    delete copia.resumen.duracion_total_min;
  }
  return JSON.stringify(ordenado(copia));
}

function ordenado(x: unknown): unknown {
  if (Array.isArray(x)) {
    return x.map(ordenado);
  }
  if (x && typeof x === 'object') {
    return Object.fromEntries(
      Object.keys(x)
        .sort()
        .map((k) => [k, ordenado((x as Record<string, unknown>)[k])]),
    );
  }
  return x;
}

function redondear(x: number): number {
  return Math.round(x * 100) / 100;
}

function sinRepetir(valores: readonly string[]): string[] {
  const vistos = new Set<string>();
  const salida: string[] = [];
  for (const v of valores) {
    const clave = v.trim().toLocaleLowerCase('es');
    if (clave && !vistos.has(clave)) {
      vistos.add(clave);
      salida.push(v.trim());
    }
  }
  return salida;
}

function mismaEvidencia(a: Evidencia, b: Evidencia): boolean {
  return (
    a.campo === b.campo &&
    a.valor === b.valor &&
    (a.cita ?? '') === (b.cita ?? '') &&
    a.fuente === b.fuente &&
    a.confianza === b.confianza &&
    (a.t ?? null) === (b.t ?? null)
  );
}

function conPaso(b: Borrador, i: number, paso: PasoBorrador): Borrador {
  return { ...b, pasos: b.pasos.map((p, j) => (j === i ? paso : p)) };
}

/**
 * Une el paso `i` con el siguiente (la operación que vuelve usable al SOP generado, ADR-023):
 * nombre del primero; descripciones unidas; equipo, puntos de validación, evidencia y campos
 * inferidos sin repetir; tiempo sumado; el tramo del video de los dos (mínimo y máximo, así un
 * par reordenado no deja el rango al revés); confianza la menor; cita y fuente del primero. Los
 * riesgos del segundo pasan al unido.
 *
 * Si los responsables difieren y no se dice cuál usar, no une y devuelve los dos para preguntar.
 * El elegido cuenta como revisado: sale de `campos_inferidos` y solo queda su evidencia.
 */
export function unirConSiguiente(b: Borrador, i: number, responsable?: string): ResultadoUnion {
  const a = b.pasos[i];
  const s = b.pasos[i + 1];
  if (!a || !s) {
    return { ok: true, borrador: b };
  }
  const distintos = a.responsable.trim() !== s.responsable.trim();
  if (distintos && responsable === undefined) {
    return { ok: false, responsables: [a.responsable, s.responsable] };
  }
  const elegido = distintos ? responsable! : a.responsable;

  const evidencia = [...a.evidencia];
  for (const e of s.evidencia) {
    if (!evidencia.some((x) => mismaEvidencia(x, e))) {
      evidencia.push(e);
    }
  }
  // El responsable elegido entre dos distintos ya lo revisó una persona.
  const inferidos = sinRepetir([...a.campos_inferidos, ...s.campos_inferidos]).filter(
    (c) => !distintos || c !== 'responsable',
  );
  const tiempos = [a.tiempo_esperado_min, s.tiempo_esperado_min].filter(
    (t): t is number => t !== null,
  );
  const inicios = [a.t_inicio, s.t_inicio].filter((t): t is number => t !== null);
  const fines = [a.t_fin, s.t_fin].filter((t): t is number => t !== null);

  const unido: PasoBorrador = {
    ...a,
    descripcion: [a.descripcion.trim(), s.descripcion.trim()].filter(Boolean).join(' '),
    responsable: elegido,
    equipo: sinRepetir([...a.equipo, ...s.equipo]),
    puntos_validacion: sinRepetir([...a.puntos_validacion, ...s.puntos_validacion]),
    tiempo_esperado_min: tiempos.length ? redondear(tiempos.reduce((x, y) => x + y, 0)) : null,
    t_inicio: inicios.length ? Math.min(...inicios) : null,
    t_fin: fines.length ? Math.max(...fines) : null,
    confianza:
      ORDEN_CONFIANZA[s.confianza] < ORDEN_CONFIANZA[a.confianza] ? s.confianza : a.confianza,
    campos_inferidos: inferidos,
    evidencia: distintos
      ? evidencia.filter((e) => e.campo !== 'responsable' || e.valor === elegido)
      : evidencia,
    revisado: a.revisado && s.revisado,
  };

  const pasos = [...b.pasos.slice(0, i), unido, ...b.pasos.slice(i + 2)];
  const riesgos = b.resumen.riesgos.map((x) =>
    x.pasoClave === s.clave ? { ...x, pasoClave: a.clave } : x,
  );
  return { ok: true, borrador: { ...b, pasos, resumen: { ...b.resumen, riesgos } } };
}

/** Mueve el paso de la posición `de` a la posición `a` (arrastrar o subir y bajar). */
export function mover(b: Borrador, de: number, a: number): Borrador {
  if (de === a || de < 0 || a < 0 || de >= b.pasos.length || a >= b.pasos.length) {
    return b;
  }
  const pasos = [...b.pasos];
  const [paso] = pasos.splice(de, 1);
  pasos.splice(a, 0, paso);
  return { ...b, pasos };
}

/**
 * Quita el paso `i`. Los riesgos siguen apuntando a su clave (al guardar quedan sin paso), así
 * que deshacer los recupera. El SOP necesita al menos un paso: el último no se quita.
 */
export function quitar(b: Borrador, i: number): { borrador: Borrador; quitado: Quitado } | null {
  if (b.pasos.length <= 1 || !b.pasos[i]) {
    return null;
  }
  return {
    borrador: { ...b, pasos: b.pasos.filter((_, j) => j !== i) },
    quitado: { paso: b.pasos[i], indice: i },
  };
}

/** Deshace `quitar`: el paso vuelve a su posición (o al final, si ya no hay tantos). */
export function restaurar(b: Borrador, q: Quitado): Borrador {
  const pasos = [...b.pasos];
  pasos.splice(Math.min(q.indice, pasos.length), 0, q.paso);
  return { ...b, pasos };
}

/**
 * Agrega un paso vacío después de `despuesDe` (o al final). Sin evidencia: inferido con
 * confianza baja (regla 4), pero lo escribió una persona, así que va revisado.
 */
export function agregarPaso(b: Borrador, despuesDe = b.pasos.length - 1): Borrador {
  const clave = Math.max(0, ...b.pasos.map((p) => p.clave)) + 1;
  const nuevo: PasoBorrador = {
    clave,
    nombre: '',
    descripcion: '',
    responsable: '',
    equipo: [],
    puntos_validacion: [],
    tiempo_esperado_min: null,
    t_inicio: null,
    t_fin: null,
    confianza: 'baja',
    campos_inferidos: [],
    cita: '',
    fuente: 'inferido',
    evidencia: [],
    revisado: true,
  };
  const pasos = [...b.pasos];
  pasos.splice(despuesDe + 1, 0, nuevo);
  return { ...b, pasos };
}

/**
 * La persona edita un campo del paso: lo saca de `campos_inferidos` y marca el paso revisado.
 * La evidencia que ya no describe el dato se va: la de un elemento quitado de una lista, o la
 * del responsable o el tiempo si se cambian a mano (`Evidencia.valor` es el dato tal como quedó).
 */
export function editarPaso<C extends CampoPaso>(
  b: Borrador,
  i: number,
  campo: C,
  valor: PasoBorrador[C],
): Borrador {
  const p = b.pasos[i];
  if (!p) {
    return b;
  }
  let evidencia = p.evidencia;
  if (campo === 'equipo' || campo === 'puntos_validacion') {
    const lista = valor as string[];
    evidencia = evidencia.filter((e) => e.campo !== campo || lista.includes(e.valor));
  } else if (campo === 'responsable' || campo === 'tiempo_esperado_min') {
    evidencia = evidencia.filter((e) => e.campo !== campo);
  }
  return conPaso(b, i, {
    ...p,
    [campo]: valor,
    evidencia,
    campos_inferidos: p.campos_inferidos.filter((c) => c !== campo),
    revisado: true,
  });
}

/** La persona confirma un campo inferido sin cambiarlo: sale de `campos_inferidos`. */
export function confirmarCampo(b: Borrador, i: number, campo: string): Borrador {
  const p = b.pasos[i];
  if (!p) {
    return b;
  }
  return conPaso(b, i, { ...p, campos_inferidos: p.campos_inferidos.filter((c) => c !== campo) });
}

/** La persona confirma el paso entero: revisado y sin campos inferidos. */
export function confirmarPaso(b: Borrador, i: number): Borrador {
  const p = b.pasos[i];
  return p ? conPaso(b, i, { ...p, campos_inferidos: [], revisado: true }) : b;
}

/** Edita un dato del cuadro resumen (texto vacío → null) y lo marca revisado. */
export function editarDato(b: Borrador, campo: CampoDato, valor: string): Borrador {
  const limpio = valor.trim() === '' ? null : valor;
  return {
    ...b,
    resumen: { ...b.resumen, [campo]: { ...b.resumen[campo], valor: limpio, revisado: true } },
  };
}

export function confirmarDato(b: Borrador, campo: CampoDato): Borrador {
  return { ...b, resumen: { ...b.resumen, [campo]: { ...b.resumen[campo], revisado: true } } };
}

/** Equipo de operación o roles desde los chips: conserva la descripción de los que ya estaban. */
export function elementos(anteriores: readonly Elemento[], nombres: readonly string[]): Elemento[] {
  return sinRepetir(nombres).map(
    (nombre) => anteriores.find((e) => e.nombre === nombre) ?? { nombre, descripcion: '' },
  );
}

/** Lo que tiene evidencia propia en el resumen y en los puntos clave. */
interface ConEvidencia {
  fuente?: string;
  confianza?: string;
  revisado?: boolean;
}

/**
 * La leyenda de un dato que hay que revisar (RF-25): "Inferido", "Confianza baja" o "Confianza
 * media", o null si no se resalta (o si una persona ya lo revisó). Va como texto, no solo color.
 */
export function leyenda(x: ConEvidencia | null | undefined): string | null {
  if (!x || x.revisado) {
    return null;
  }
  if (x.fuente === 'inferido') {
    return 'Inferido';
  }
  if (x.confianza === 'baja' || x.confianza === 'media') {
    return `Confianza ${x.confianza}`;
  }
  return null;
}

/** La leyenda de la confianza del paso: solo si no se ha revisado. */
export function leyendaPaso(p: PasoBorrador): string | null {
  return !p.revisado && p.confianza !== 'alta' ? `Confianza ${p.confianza}` : null;
}

/** Segundos como mm:ss. */
export function mmss(t: number | null | undefined): string {
  if (t === null || t === undefined) {
    return '';
  }
  const s = Math.floor(t);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

/** "audio · alta · 00:12 · «cita»" para el título de una evidencia. */
export function describir(
  e: { fuente?: string; confianza?: string; t?: number | null; cita?: string } | null | undefined,
): string {
  if (!e) {
    return '';
  }
  const t = e.t !== null && e.t !== undefined ? ` · ${mmss(e.t)}` : '';
  const cita = e.cita ? ` · «${e.cita}»` : '';
  return `${e.fuente ?? 'documento'} · ${e.confianza ?? 'alta'}${t}${cita}`;
}

/** Riesgo nuevo: sin evidencia (inferido, confianza baja) y revisado, porque lo escribió alguien. */
export function riesgoNuevo(): RiesgoBorrador {
  return {
    descripcion: '',
    nivel: 'medio',
    control: '',
    cita: '',
    fuente: 'inferido',
    confianza: 'baja',
    t: null,
    revisado: true,
    pasoClave: null,
  };
}

export function fallaNueva(): FallaBorrador {
  return {
    situacion: '',
    accion: '',
    cita: '',
    fuente: 'inferido',
    confianza: 'baja',
    t: null,
    revisado: true,
  };
}
