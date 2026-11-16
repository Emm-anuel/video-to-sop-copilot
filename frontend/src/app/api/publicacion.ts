/* Generado desde docs/contrato/publicacion.schema.json con `npm run tipos:publicacion`. No editar a mano. */

export type VideoId = number;
export type Publicado = boolean;
export type PublicadoEn = string | null;
export type PalabrasIndexadas = number;

/**
 * Respuesta de `POST /videos/{id}/publicar` (RF-32) y de `DELETE /videos/{id}/publicar`.
 *
 * `palabras_indexadas`: las filas que el video tiene en el índice de búsqueda exacta (una por
 * token de `forma_busqueda`; 0 al quitarlo). `publicado_en` va si y solo si está publicado.
 */
export interface EstadoPublicacion {
  video_id: VideoId;
  publicado: Publicado;
  publicado_en?: PublicadoEn;
  palabras_indexadas: PalabrasIndexadas;
}
