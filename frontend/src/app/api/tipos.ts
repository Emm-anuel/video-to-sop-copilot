/**
 * Respuestas de la API escritas a mano según docs/dev/api.md y
 * src/sopvid/plataforma/api/{sops,videos}.py. `ReporteValidacion` no va aquí: se genera desde
 * el esquema (reporte-validacion.ts, `npm run tipos`).
 */

import { Afinidad } from './reporte-validacion';
import { SOP } from './sop';

/** Advertencia de la conversión del SOP (`AvisoConversion`): no detiene el flujo. */
export interface AdvertenciaSOP {
  tipo: string;
  linea: number | null;
  mensaje: string;
}

/** Dónde va la conversión del SOP; `listo` y `error` son finales. */
export type EstadoConversionSop = 'en_cola' | 'convirtiendo' | 'listo' | 'error';

/**
 * `POST /sops` → 202 y `GET /sops/{id}/estado` (`EstadoSop`, docs/contrato/sop_estado.schema.json).
 * `titulo`, `metodo` y `advertencias` llegan con `listo`; `mensaje`, con `error`.
 */
export interface EstadoSop {
  id: number;
  codigo: string;
  estado: EstadoConversionSop;
  titulo: string | null;
  /** `llm`: el SOP no seguía la plantilla y lo convirtió Gemma 4 (conviene revisarlo, RF-04). */
  metodo: 'plantilla' | 'llm' | null;
  mensaje: string | null;
  advertencias: AdvertenciaSOP[];
  /** `generado`: salió de un video en modo "No tengo SOP" (ADR-023). */
  origen?: 'cargado' | 'generado';
  /** Si sirve como referencia de otros videos (RF-27); un generado entra al guardarlo. */
  en_biblioteca?: boolean;
}

/**
 * Lo que la pantalla usa de `generacion` (`GeneracionSOP`, ADR-023): el video del que salió.
 * `grupos` registra lo que hizo el modelo y no refleja las ediciones (ADR-025).
 */
export interface GeneracionSop {
  video_id: number;
  /** La duración total que dijo el operador, en minutos como texto (ADR-021); gana al editar. */
  duracion_narrada?: { valor: string | null } | null;
}

/** `GET /sops/{id}`: el SOP del contrato con su código y sus advertencias. */
export interface SopDetalle {
  id: number;
  codigo: string;
  origen: 'cargado' | 'generado';
  creado: string;
  metodo: 'plantilla' | 'llm' | null;
  advertencias: AdvertenciaSOP[];
  en_biblioteca: boolean;
  /** Solo en un SOP generado desde un video; null en uno cargado. */
  generacion?: GeneracionSop | null;
  sop: SOP;
}

/** `afinidad_baja` (ADR-020): la validación se detuvo; quien carga decide si continúa. */
export type Proceso = 'en_cola' | 'procesando' | 'listo' | 'error' | 'afinidad_baja';

/** `POST /videos` y `POST /videos/{id}/validar` → 202. */
export interface VideoCreado {
  id: number;
  proceso: Proceso;
  sop_id?: number | null;
}

/**
 * `GET /videos/{id}`. `etapa`: duracion, audio, transcripcion, contexto, segmentacion; en modo
 * validar también emparejamiento y reporte; en modo generar sop_pasos, sop_resumen y sop_claves;
 * al final listo. `sop_id`: el SOP de referencia o, en modo generar, el generado.
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
  sop_id?: number | null;
}
