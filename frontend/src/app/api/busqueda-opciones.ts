/* Generado desde docs/contrato/busqueda_opciones.schema.json con `npm run tipos:busqueda`. No editar a mano. */

export type Id = number;
export type Titulo = string;
export type SopId = number | null;
export type Videos = VideoPublicado[];
export type Id1 = number;
export type Codigo = string;
export type Titulo1 = string | null;
export type Sops = SopDeVideo[];

/**
 * `GET /buscar/opciones` (RF-37): los videos publicados (el más reciente primero) y los SOP
 * con al menos un video publicado (por código).
 */
export interface OpcionesBusqueda {
  videos: Videos;
  sops: Sops;
}
/**
 * Un video del selector de `/buscar`: publicado, con su SOP (de referencia o generado).
 */
export interface VideoPublicado {
  id: Id;
  titulo: Titulo;
  sop_id?: SopId;
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
