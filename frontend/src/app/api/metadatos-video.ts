import { InjectionToken } from '@angular/core';

/** Lo que el navegador sabe del video antes de subirlo. */
export interface MetadatosVideo {
  /** Segundos (`HTMLVideoElement.duration`). */
  duracion: number;
  /** `videoWidth > 0` tras `loadedmetadata`: con 0 el archivo solo trae audio. */
  conImagen: boolean;
}

/** Lee la duración y si hay imagen; `null` si el navegador no pudo (formato, archivo dañado). */
export type LectorMetadatos = (archivo: File) => Promise<MetadatosVideo | null>;

/** Si el navegador no responde en este tiempo, se sigue sin estimación. */
export const ESPERA_METADATOS_MS = 10_000;

/**
 * Lector de metadatos para `/nuevo` (ADR-024): un `<video preload="metadata">` con una URL del
 * archivo local, sin subir nada. Las pruebas lo sustituyen (jsdom no carga medios).
 */
export const METADATOS_VIDEO = new InjectionToken<LectorMetadatos>('METADATOS_VIDEO', {
  providedIn: 'root',
  factory: () => leerMetadatos,
});

export function leerMetadatos(archivo: File): Promise<MetadatosVideo | null> {
  return new Promise((resolver) => {
    const video = document.createElement('video');
    const url = URL.createObjectURL(archivo);
    let espera: ReturnType<typeof setTimeout> | undefined;
    const terminar = (resultado: MetadatosVideo | null): void => {
      clearTimeout(espera);
      video.onloadedmetadata = null;
      video.onerror = null;
      video.removeAttribute('src');
      video.load();
      URL.revokeObjectURL(url);
      resolver(resultado);
    };
    video.preload = 'metadata';
    video.muted = true;
    video.onloadedmetadata = () => {
      const duracion = video.duration;
      terminar(
        Number.isFinite(duracion) && duracion > 0
          ? { duracion, conImagen: video.videoWidth > 0 }
          : null,
      );
    };
    video.onerror = () => terminar(null);
    espera = setTimeout(() => terminar(null), ESPERA_METADATOS_MS);
    video.src = url;
  });
}
