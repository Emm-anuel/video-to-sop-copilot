import { HttpErrorResponse } from '@angular/common/http';

/** Error de validación de FastAPI (422 con `detail` como lista). */
interface ErrorValidacion {
  loc?: (string | number)[];
  msg?: string;
}

const SIN_CONEXION = 'No hay conexión con la API (¿está corriendo en el puerto 8000?)';

/**
 * Convierte un error HTTP en un mensaje en español para la pantalla, sin trazas.
 * La API responde `{"detail": "..."}`, `{"detail": {"mensaje": ...}}` o, en los 422 de FastAPI,
 * `{"detail": [{"loc": [...], "msg": "..."}]}`.
 */
export function mensajeDeError(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) {
    return 'Ocurrió un error inesperado.';
  }
  const detalle = leerDetalle(error.error);
  switch (error.status) {
    case 0:
      return SIN_CONEXION;
    case 413:
      return conDetalle('Archivo demasiado grande', detalle);
    case 415:
      // La API dice "extensión no permitida; usa .md, .txt": se queda solo la parte de "usa …".
      return conDetalle('Extensión no permitida', detalle?.split('; ').at(-1));
    case 422:
      return conDetalle('La API rechazó los datos', detalle);
    case 404:
      return conDetalle('No encontrado', detalle);
    default:
      return `Error de la API (HTTP ${error.status}). Revisa el log de la API.`;
  }
}

function conDetalle(titulo: string, detalle: string | undefined): string {
  return detalle ? `${titulo}: ${detalle}.` : `${titulo}.`;
}

function leerDetalle(cuerpo: unknown): string | undefined {
  if (!cuerpo || typeof cuerpo !== 'object' || !('detail' in cuerpo)) {
    return undefined;
  }
  const detail = (cuerpo as { detail: unknown }).detail;
  if (typeof detail === 'string') {
    return detail.replace(/\.$/, '');
  }
  if (Array.isArray(detail)) {
    const partes = (detail as ErrorValidacion[])
      .filter((d) => d?.msg)
      .map((d) => {
        const campo = d.loc?.filter((p) => p !== 'body').join('.');
        return campo ? `${campo}: ${d.msg}` : d.msg;
      });
    return partes.length ? partes.join('; ') : undefined;
  }
  if (detail && typeof detail === 'object' && 'mensaje' in detail) {
    return String((detail as { mensaje: unknown }).mensaje);
  }
  return undefined;
}
