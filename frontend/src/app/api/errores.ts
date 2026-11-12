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
    case 409:
      // La API ya explica el conflicto en una frase (p. ej. por qué no se puede borrar un SOP).
      return detalle ? conPunto(detalle) : 'La operación no se puede hacer en el estado actual.';
    default:
      return `Error de la API (HTTP ${error.status}). Revisa el log de la API.`;
  }
}

/** Un error del 422 ubicado en el SOP: la ruta sin `body`, cómo se llama en pantalla y qué pasa. */
export interface ErrorCampo {
  ruta: (string | number)[];
  etiqueta: string;
  mensaje: string;
}

const NOMBRES: Record<string, string> = {
  titulo: 'Título',
  resumen: 'Cuadro resumen',
  version: 'versión',
  objetivo: 'objetivo',
  alcance: 'alcance',
  responsable: 'responsable',
  lugar: 'lugar',
  horario_frecuencia: 'horario o frecuencia',
  valor: 'valor',
  nombre: 'nombre',
  descripcion: 'descripción',
  equipo: 'equipo',
  puntos_validacion: 'puntos de validación',
  tiempo_esperado_min: 'tiempo (min)',
  situacion: 'situación',
  accion: 'acción',
  control: 'control',
  nivel: 'nivel',
  texto: 'texto',
};

const LISTAS: Record<string, string> = {
  pasos: 'Paso',
  riesgos: 'Riesgo',
  en_caso_de_falla: 'Falla',
  equipo_operacion: 'Equipo de operación',
  roles: 'Rol',
  puntos_clave: 'Punto clave',
  palabras_clave: 'Palabra clave',
};

/** "pasos.3.nombre" → "Paso 4 · nombre" (los índices se muestran desde 1, como en pantalla). */
export function etiquetaDeRuta(ruta: readonly (string | number)[]): string {
  const partes: string[] = [];
  for (let i = 0; i < ruta.length; i++) {
    const p = ruta[i];
    const siguiente = ruta[i + 1];
    if (typeof p === 'string' && LISTAS[p] && typeof siguiente === 'number') {
      partes.push(`${LISTAS[p]} ${siguiente + 1}`);
      i++;
    } else if (typeof p === 'string' && p !== 'resumen') {
      partes.push(NOMBRES[p] ?? p);
    }
  }
  return partes.join(' · ');
}

/**
 * El 422 de `PUT /sops/{id}` campo por campo. Un `detail` de texto (p. ej. el título demasiado
 * largo) llega como un solo error sin ruta. Cualquier otro error: lista vacía.
 */
export function erroresPorCampo(error: unknown): ErrorCampo[] {
  if (!(error instanceof HttpErrorResponse) || error.status !== 422) {
    return [];
  }
  const cuerpo = error.error as { detail?: unknown } | null;
  const detail = cuerpo && typeof cuerpo === 'object' ? cuerpo.detail : undefined;
  if (typeof detail === 'string') {
    return [{ ruta: [], etiqueta: '', mensaje: detail }];
  }
  if (!Array.isArray(detail)) {
    return [];
  }
  return (detail as ErrorValidacion[])
    .filter((d) => d?.msg)
    .map((d) => {
      const ruta = (d.loc ?? []).filter((p) => p !== 'body');
      return { ruta, etiqueta: etiquetaDeRuta(ruta), mensaje: d.msg! };
    });
}

function conPunto(texto: string): string {
  return /[.!?]$/.test(texto) ? texto : `${texto}.`;
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
