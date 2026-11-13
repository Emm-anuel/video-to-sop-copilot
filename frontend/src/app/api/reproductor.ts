/**
 * Por qué un `<video>` no se ve (RF-06, RF-20). AVI se acepta y se analiza, pero Chrome y Edge no
 * lo reproducen: el reproductor lo dice y ofrece descargarlo, y los segundos de cada hallazgo
 * siguen en pantalla. Convertirlo a MP4 sin recodificar queda para S6.
 *
 * `MediaError` código 4 (`MEDIA_ERR_SRC_NOT_SUPPORTED`) llega tanto con un formato que el
 * navegador no reproduce como con un archivo que no está (404). Para no decir "formato" cuando el
 * archivo falta, con el código 4 se pide su primer byte (`ApiService.videoDisponible`): si
 * responde, es el formato.
 */

/** `MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED`. */
export const SIN_SOPORTE = 4;

/** `formato`: el archivo está, pero el navegador no lo reproduce. `carga`: no se pudo cargar. */
export type FalloVideo = 'formato' | 'carga';

/** El código del `MediaError` del `<video>` que disparó `evento`, o `null`. */
export function codigoDeError(evento: Event): number | null {
  const video = evento.target as HTMLVideoElement | null;
  return video?.error?.code ?? null;
}
