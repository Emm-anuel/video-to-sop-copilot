import { HttpErrorResponse } from '@angular/common/http';

/** Reintentos por parte antes de rendirse (RF-06): con espera creciente de 1, 2 y 4 s. */
export const REINTENTOS = 3;
export const ESPERA_BASE_MS = 1000;
/** Veces seguidas que un 409 puede reacomodar el offset sin avanzar, para no ciclar. */
export const REACOMODOS_MAX = 3;
const MIB = 1024 * 1024;

/** La parte que sigue desde `offset`: `[inicio, fin)`, de `tamanoParte` bytes o menos al final. */
export function siguienteParte(
  offset: number,
  tamano: number,
  tamanoParte: number,
): [number, number] {
  if (tamanoParte <= 0) {
    throw new RangeError('tamanoParte debe ser positivo');
  }
  const inicio = Math.min(Math.max(offset, 0), tamano);
  return [inicio, Math.min(inicio + tamanoParte, tamano)];
}

/** Todas las partes de un archivo de `tamano` bytes, desde 0 (vacío → ninguna). */
export function partes(tamano: number, tamanoParte: number): [number, number][] {
  const lista: [number, number][] = [];
  for (let offset = 0; offset < tamano;) {
    const parte = siguienteParte(offset, tamano, tamanoParte);
    lista.push(parte);
    offset = parte[1];
  }
  return lista;
}

/** Espera antes del reintento `intento` (1, 2, 3): 1 s, 2 s, 4 s. */
export function esperaReintento(intento: number): number {
  return ESPERA_BASE_MS * 2 ** (intento - 1);
}

/**
 * Una falla que se arregla reintentando: sin conexión (status 0: red caída, modo offline), tiempo
 * agotado, demasiadas peticiones o un 5xx. Un 404, 413 o 415 no cambia esperando.
 */
export function reintentable(error: unknown): boolean {
  return (
    error instanceof HttpErrorResponse &&
    (error.status === 0 || error.status === 408 || error.status === 429 || error.status >= 500)
  );
}

/** El offset correcto de un 409 de la API (`detail.offset`), o `null` si no lo trae. */
export function offsetDe409(error: unknown): number | null {
  if (!(error instanceof HttpErrorResponse) || error.status !== 409) {
    return null;
  }
  const detail = (error.error as { detail?: { offset?: unknown } } | null)?.detail;
  const offset = detail?.offset;
  return typeof offset === 'number' && Number.isInteger(offset) && offset >= 0 ? offset : null;
}

/** Bytes en MB (MiB, como `SUBIDA_MAX_MB`) con un decimal: "48.0". */
export function megas(bytes: number): string {
  return (bytes / MIB).toFixed(1);
}

/** "48.0 de 210.3 MB". */
export function megasDe(enviados: number, total: number): string {
  return `${megas(enviados)} de ${megas(total)} MB`;
}
