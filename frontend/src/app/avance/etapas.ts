/**
 * La única tabla de etapas del frontend: nombres en español y orden real según el modo. La usan
 * el avance en vivo (`AvanceVideo`, la pantalla Procesando, el reporte y el SOP generado) y el
 * recuadro "Cómo se obtuvo" del reporte (`metadatos.segundos`). Las claves son las de
 * `videos.etapa` (src/sopvid/percepcion/pipeline.py, lenguaje/validacion.py y
 * plataforma/procesamiento.py).
 */

import { Proceso } from '../api/tipos';

/** Procesos con los que se deja de consultar el estado. */
export const FINALES: readonly Proceso[] = ['listo', 'error', 'afinidad_baja'];

export function esFinal(proceso: Proceso): boolean {
  return FINALES.includes(proceso);
}

/** Mensaje con que la API deja en error un video que procesaba al reiniciarse (`ERROR_REINICIO`). */
export const ERROR_REINICIO = 'interrumpido por reinicio';

export const ETIQUETA_ETAPA: Readonly<Record<string, string>> = {
  duracion: 'Duración del video',
  audio: 'Audio',
  transcripcion: 'Transcripción',
  fotogramas: 'Descripción de imágenes',
  contexto: 'Ficha de contexto',
  afinidad: 'Afinidad con el SOP',
  segmentacion: 'Pasos del video',
  emparejamiento: 'Emparejamiento',
  reporte: 'Reporte',
  sop_pasos: 'Redacción de los pasos',
  sop_resumen: 'Cuadro resumen',
  sop_claves: 'Puntos y palabras clave',
  miniaturas: 'Miniaturas',
  listo: 'Listo',
};

/** El nombre de una etapa; una que no está en la tabla se muestra con su clave. */
export function etiquetaEtapa(etapa: string | null | undefined): string {
  if (!etapa) {
    return 'En cola';
  }
  return ETIQUETA_ETAPA[etapa] ?? etapa;
}

const ANALISIS = ['duracion', 'audio', 'transcripcion'] as const;
const VALIDAR = ['contexto', 'segmentacion', 'emparejamiento', 'reporte'] as const;
const GENERAR = ['contexto', 'segmentacion', 'sop_pasos', 'sop_resumen', 'sop_claves'] as const;

/**
 * Las etapas en el orden en que corren. "fotogramas" solo si se pidió describir imágenes
 * (`analizar_imagenes` de `GET /videos/{id}`, ya resuelto por la API).
 */
export function etapasDelModo(modo: 'validar' | 'generar', imagenes: boolean): string[] {
  return [
    ...ANALISIS,
    ...(imagenes ? ['fotogramas'] : []),
    ...(modo === 'validar' ? VALIDAR : GENERAR),
  ];
}

export type EstadoEtapa = 'pendiente' | 'en_curso' | 'hecha' | 'fallo' | 'detenida';

export interface EtapaVista {
  clave: string;
  nombre: string;
  estado: EstadoEtapa;
}

/**
 * Cada etapa de `lista` como pendiente, en curso o hecha según la etapa actual. Con "error", la
 * etapa en que falló; con "afinidad_baja", la validación se detuvo tras la ficha (la etapa
 * "afinidad" no es de la lista: los pasos del video quedan detenidos). Con "listo", todas hechas.
 */
export function estadoEtapas(
  lista: readonly string[],
  etapa: string | null,
  proceso: Proceso,
): EtapaVista[] {
  const vista = (clave: string, estado: EstadoEtapa): EtapaVista => ({
    clave,
    nombre: etiquetaEtapa(clave),
    estado,
  });
  if (proceso === 'listo') {
    return lista.map((clave) => vista(clave, 'hecha'));
  }
  const actual = etapa === 'afinidad' ? lista.indexOf('segmentacion') : lista.indexOf(etapa ?? '');
  const enCurso: EstadoEtapa =
    proceso === 'error' ? 'fallo' : proceso === 'afinidad_baja' ? 'detenida' : 'en_curso';
  return lista.map((clave, i) => {
    if (actual < 0) {
      return vista(clave, 'pendiente');
    }
    return vista(clave, i < actual ? 'hecha' : i === actual ? enCurso : 'pendiente');
  });
}
