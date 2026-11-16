import { Component, ElementRef, computed, inject, input, viewChild } from '@angular/core';
import { ApiService, TipoDescarga } from '../api/api.service';

/** Una opción del menú: un enlace de descarga normal (`<a href download>`). */
export interface FormatoDescarga {
  etiqueta: string;
  descripcion: string;
  url: string;
}

/** Los archivos de la transcripción (RF-31), en el orden del menú. */
export const TIPOS: readonly { tipo: TipoDescarga; etiqueta: string; descripcion: string }[] = [
  { tipo: 'txt', etiqueta: 'Transcripción (.txt)', descripcion: 'Texto con [mm:ss] por línea' },
  { tipo: 'srt', etiqueta: 'Subtítulos (.srt)', descripcion: 'Para abrir junto al video' },
  { tipo: 'json', etiqueta: 'Análisis (.json)', descripcion: 'Transcripción con tiempos' },
];

/**
 * Menú "Descargar" de un video (RF-31, §11 vista de carga): TXT, SRT y JSON de la transcripción
 * y los formatos que agregue quien lo usa en `extras` (en P5, el PDF). Va en el reporte y en el
 * SOP generado; la búsqueda no lo ofrece.
 *
 * Solo enlaces `download`: el navegador baja el archivo y toma el nombre de `Content-Disposition`
 * (el título del video). Nada se pide con JavaScript; el código solo cierra el menú al elegir,
 * con Escape o con un clic fuera. Es un `<details>`, así que abre y cierra también sin él.
 */
@Component({
  selector: 'app-descargas',
  templateUrl: './descargas.html',
  styleUrl: './descargas.scss',
  host: { '(document:click)': 'alClicFuera($event)' },
})
export class Descargas {
  private readonly api = inject(ApiService);
  private readonly menu = viewChild.required<ElementRef<HTMLDetailsElement>>('menu');

  readonly videoId = input.required<number>();
  /** Formatos además de TXT, SRT y JSON; van al final del menú. */
  readonly extras = input<readonly FormatoDescarga[]>([]);

  protected readonly formatos = computed<FormatoDescarga[]>(() => [
    ...TIPOS.map(({ tipo, etiqueta, descripcion }) => ({
      etiqueta,
      descripcion,
      url: this.api.urlDescarga(this.videoId(), tipo),
    })),
    ...this.extras(),
  ]);

  protected cerrar(enfocar = false): void {
    const menu = this.menu().nativeElement;
    if (!menu.open) {
      return;
    }
    menu.open = false;
    if (enfocar) {
      menu.querySelector('summary')?.focus();
    }
  }

  protected alClicFuera(evento: Event): void {
    if (!this.menu().nativeElement.contains(evento.target as Node | null)) {
      this.cerrar();
    }
  }
}
