import { Proceso, VideoResumen } from '../api/video-resumen';
import { normalizar } from '../biblioteca/filtro';

export type FiltroModo = 'todos' | 'validar' | 'generar';
/** `en_proceso` junta "en_cola" y "procesando": para quien mira la lista es lo mismo. */
export type FiltroEstado = 'todos' | 'en_proceso' | 'listo' | 'afinidad_baja' | 'error';

export interface FiltrosVideos {
  texto: string;
  modo: FiltroModo;
  estado: FiltroEstado;
  /** Id del SOP, o null para todos. */
  sop: number | null;
}

export const SIN_FILTROS: FiltrosVideos = { texto: '', modo: 'todos', estado: 'todos', sop: null };

/** En cola o procesando: mientras quede alguno, la lista se refresca sola. */
export function enProceso(proceso: Proceso): boolean {
  return proceso === 'en_cola' || proceso === 'procesando';
}

/**
 * Si el video pasa los filtros. El texto se busca sin acentos ni mayúsculas en el título del
 * video y en el código y el título de su SOP.
 */
export function pasaFiltros(video: VideoResumen, filtros: FiltrosVideos): boolean {
  if (filtros.modo !== 'todos' && video.modo !== filtros.modo) {
    return false;
  }
  if (filtros.estado !== 'todos') {
    const estado = enProceso(video.proceso) ? 'en_proceso' : video.proceso;
    if (estado !== filtros.estado) {
      return false;
    }
  }
  if (filtros.sop !== null && video.sop?.id !== filtros.sop) {
    return false;
  }
  const q = normalizar(filtros.texto);
  if (!q) {
    return true;
  }
  return [video.titulo, video.sop?.codigo ?? '', video.sop?.titulo ?? ''].some((campo) =>
    normalizar(campo).includes(q),
  );
}

/** Un SOP del filtro: los que aparecen en la lista, sin repetir, por código. */
export interface OpcionSop {
  id: number;
  etiqueta: string;
}

export function opcionesSop(videos: readonly VideoResumen[]): OpcionSop[] {
  const vistos = new Map<number, OpcionSop>();
  for (const v of videos) {
    if (v.sop && !vistos.has(v.sop.id)) {
      const titulo = v.sop.titulo ? ` · ${v.sop.titulo}` : '';
      vistos.set(v.sop.id, { id: v.sop.id, etiqueta: `${v.sop.codigo}${titulo}` });
    }
  }
  return [...vistos.values()].sort((a, b) => a.etiqueta.localeCompare(b.etiqueta, 'es'));
}

/** A dónde lleva la fila y cómo se llama el botón. */
export interface Destino {
  ruta: (string | number)[];
  etiqueta: string;
}

/**
 * En cola o procesando → el avance; listo → el reporte (validar) o el SOP generado (generar);
 * afinidad baja → el reporte, donde está el aviso completo y "Continuar" (RF-17: se lee antes de
 * seguir); error → el avance, que muestra el mensaje y "Reprocesar".
 */
export function destino(video: VideoResumen): Destino {
  const base = ['/videos', video.id];
  switch (video.proceso) {
    case 'listo':
      return video.modo === 'generar'
        ? { ruta: [...base, 'sop'], etiqueta: 'Ver el SOP' }
        : { ruta: [...base, 'reporte'], etiqueta: 'Ver el reporte' };
    case 'afinidad_baja':
      return { ruta: [...base, 'reporte'], etiqueta: 'Ver el aviso' };
    case 'error':
      return { ruta: [...base, 'procesando'], etiqueta: 'Ver el error' };
    default:
      return { ruta: [...base, 'procesando'], etiqueta: 'Ver el avance' };
  }
}
