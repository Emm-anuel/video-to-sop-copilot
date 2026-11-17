/* Generado desde docs/contrato/video_resumen.schema.json con `npm run tipos:videos`. No editar a mano. */

export type Id = number;
export type Titulo = string;
export type Creado = string;
export type Duracion = number | null;
export type Modo = "validar" | "generar";
export type Proceso = "en_cola" | "procesando" | "listo" | "error" | "afinidad_baja";
export type Etapa = string | null;
export type Error = string | null;
export type Cumplimiento = number | null;
export type Semaforo = ("verde" | "amarillo" | "rojo") | null;
export type Id1 = number;
export type Codigo = string;
export type Titulo1 = string | null;
export type AnalizarImagenes = boolean;
export type Publicado = boolean;
export type PublicadoEn = string | null;

/**
 * Un video en `GET /videos` (pantalla 6), del más reciente al más antiguo.
 *
 * `cumplimiento` (el porcentaje) y `semaforo` solo van con `proceso` "listo" y un reporte de
 * validación: None en modo generar, en una detención por afinidad baja (sin cumplimiento) y
 * mientras se repite la validación. `analizar_imagenes`: si se describieron imágenes (ADR-024;
 * false en los videos anteriores a la columna). `publicado_en`: la última vez que se publicó,
 * None si no está publicado.
 */
export interface VideoResumen {
  id: Id;
  titulo: Titulo;
  creado: Creado;
  duracion?: Duracion;
  modo: Modo;
  proceso: Proceso;
  etapa?: Etapa;
  error?: Error;
  cumplimiento?: Cumplimiento;
  semaforo?: Semaforo;
  sop?: SopDeVideo | null;
  analizar_imagenes?: AnalizarImagenes;
  publicado?: Publicado;
  publicado_en?: PublicadoEn;
}
/**
 * El SOP de un video en la lista: el de referencia (validar) o el generado (generar).
 * `titulo` es None mientras el SOP se convierte o se redacta.
 */
export interface SopDeVideo {
  id: Id1;
  codigo: Codigo;
  titulo?: Titulo1;
}
