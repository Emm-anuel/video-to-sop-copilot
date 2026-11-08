/**
 * Respuestas de la API escritas a mano según docs/dev/api.md y
 * src/sopvid/plataforma/api/{sops,videos}.py. `ReporteValidacion` no va aquí: se genera desde
 * el esquema (reporte-validacion.ts, `npm run tipos`).
 */

import { Afinidad } from './reporte-validacion';

/** Advertencia de la conversión del SOP (`POST /sops`): no detiene el flujo. */
export interface AdvertenciaSOP {
  tipo: string;
  linea: number | null;
  mensaje: string;
}

/** `POST /sops` → 201. */
export interface SopCreado {
  id: number;
  codigo: string;
  titulo: string;
  advertencias: AdvertenciaSOP[];
}

/** `afinidad_baja` (ADR-020): la validación se detuvo; quien carga decide si continúa. */
export type Proceso = 'en_cola' | 'procesando' | 'listo' | 'error' | 'afinidad_baja';

/** `POST /videos` y `POST /videos/{id}/validar` → 202. */
export interface VideoCreado {
  id: number;
  proceso: Proceso;
}

/**
 * `GET /videos/{id}`. `etapa`: duracion, audio, transcripcion, contexto (ficha de contexto, en
 * los dos modos); en modo validar también segmentacion, emparejamiento, reporte; al final listo.
 */
export interface EstadoVideo {
  id: number;
  titulo: string;
  modo: 'validar' | 'generar';
  proceso: Proceso;
  etapa: string | null;
  progreso: number;
  duracion: number | null;
  idioma: string | null;
  error: string | null;
  creado: string;
  /** Afinidad de contexto (ADR-020): con `afinidad_baja`, la de la detención; si no, la del reporte. */
  afinidad?: Afinidad | null;
}
