import { Component, ElementRef, effect, inject, input, signal, viewChild } from '@angular/core';
import { API, ApiService } from '../api/api.service';
import { FalloVideo, SIN_SOPORTE, codigoDeError } from '../api/reproductor';

/** `HTMLMediaElement.HAVE_METADATA`: desde aquí el navegador ya sabe la duración y puede saltar. */
const HAVE_METADATA = 1;

/** Un salto que espera a que el video cargue sus metadatos. */
interface Salto {
  t: number;
  reproducir: boolean;
}

/**
 * El reproductor de un video de la API (`GET /videos/{id}/video`, con `Range`, así salta a
 * cualquier segundo): lo usan el reporte (RF-20) y la búsqueda (RF-36). Los segundos salen de la
 * transcripción, nunca de un modelo (regla 4).
 *
 * - `inicio`: el segundo al que salta, sin reproducir, con el primer `loadedmetadata` de ese video
 *   (el `?t=` de los QR del PDF, §11).
 * - `saltar(t)`: pone `currentTime` ya y reproduce. Si los metadatos todavía no llegan (p. ej. el
 *   video acaba de cambiar), además lo deja pendiente para `loadedmetadata`.
 * - Si el navegador no lo reproduce, distingue un formato sin soporte (p. ej. AVI: ofrece
 *   descargarlo) de un archivo que no cargó (`api/reproductor.ts`). `textoFormato` dice qué sigue
 *   disponible en la pantalla que lo usa.
 */
@Component({
  selector: 'app-reproductor',
  templateUrl: './reproductor.html',
  styleUrl: './reproductor.scss',
})
export class Reproductor {
  private readonly api = inject(ApiService);
  private readonly elemento = viewChild<ElementRef<HTMLVideoElement>>('video');

  readonly videoId = input.required<number>();
  readonly inicio = input<number | null>(null);
  readonly textoFormato = input('');
  /** Lo que se dice si el video no cargó; la pantalla puede agregar qué sigue disponible. */
  readonly textoCarga = input('No se pudo cargar el video.');
  /** Texto para lectores de pantalla (`aria-label` del `<video>`). */
  readonly etiqueta = input<string | null>(null);
  /**
   * El token `k` de un enlace del PDF (`/v/:id`, ADR-027): abre este video sin la clave de una
   * vista. Sin él, el video va con la cookie de la sesión.
   */
  readonly enlace = input<string | null>(null);

  /** Por qué no se ve el video (`formato`: p. ej. un AVI; `carga`: no cargó), o `null`. */
  protected readonly fallo = signal<FalloVideo | null>(null);
  private pendiente: Salto | null = null;
  /** El video al que ya se le aplicó `inicio`: solo la primera carga de cada uno. */
  private inicioAplicado: number | null = null;

  constructor() {
    // Otro video: se olvida lo del anterior (su fallo y un salto que ya no le corresponde).
    let anterior: number | null = null;
    effect(() => {
      const id = this.videoId();
      if (anterior !== null && anterior !== id) {
        this.fallo.set(null);
        this.pendiente = null;
      }
      anterior = id;
    });
  }

  protected url(id: number): string {
    const k = this.enlace();
    return `${API}/videos/${id}/video${k ? `?k=${encodeURIComponent(k)}` : ''}`;
  }

  /** Salta al segundo `t` y, salvo que se pida lo contrario, reproduce. */
  saltar(t: number, reproducir = true): void {
    const video = this.elemento()?.nativeElement;
    if (!video) {
      this.pendiente = { t, reproducir };
      return;
    }
    video.currentTime = t;
    this.pendiente = video.readyState < HAVE_METADATA ? { t, reproducir } : null;
    if (reproducir) {
      // play() puede rechazarse (p. ej. si el video no cargó); el aviso ya lo da el evento error.
      void video.play()?.catch(() => undefined);
    }
  }

  /** Los metadatos llegaron: el `inicio` de este video (una vez) o el salto pendiente. */
  protected alCargar(): void {
    this.fallo.set(null);
    const video = this.elemento()?.nativeElement;
    if (!video) {
      return;
    }
    const id = this.videoId();
    const inicio = this.inicio();
    if (this.pendiente !== null) {
      const { t } = this.pendiente;
      this.pendiente = null;
      video.currentTime = t;
      this.inicioAplicado = id;
    } else if (inicio !== null && this.inicioAplicado !== id) {
      video.currentTime = inicio;
      this.inicioAplicado = id;
    }
  }

  /**
   * El `<video>` no se pudo reproducir. Con `MediaError` 4 se pregunta si el archivo está: si
   * está, es el formato (p. ej. AVI) y se ofrece descargarlo; si no, no cargó.
   */
  protected alFallar(evento: Event): void {
    const id = this.videoId();
    if (codigoDeError(evento) !== SIN_SOPORTE) {
      this.fallo.set('carga');
      return;
    }
    this.api.videoDisponible(id, this.enlace()).subscribe((esta) => {
      if (this.videoId() === id) {
        this.fallo.set(esta ? 'formato' : 'carga');
      }
    });
  }
}
