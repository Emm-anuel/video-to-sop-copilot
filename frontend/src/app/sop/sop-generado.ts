import { Component, DestroyRef, computed, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { switchMap, takeWhile, timer } from 'rxjs';
import { ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { EstadoVideo } from '../api/tipos';
import { ConCambios } from './sin-guardar.guard';
import { SopEditor } from './sop-editor';

/** Cada cuánto se consulta `GET /videos/{id}` mientras se genera el SOP. */
export const INTERVALO_MS = 3000;

/** Etapas del modo generar en español (docs/dev/api.md). */
const ETAPAS: Record<string, string> = {
  duracion: 'Leyendo el video',
  audio: 'Extrayendo el audio',
  transcripcion: 'Transcribiendo',
  fotogramas: 'Describiendo imágenes',
  contexto: 'Ficha de contexto',
  segmentacion: 'Pasos del video',
  sop_pasos: 'Redactando los pasos',
  sop_resumen: 'Redactando el cuadro resumen',
  sop_claves: 'Puntos y palabras clave',
};

/**
 * SOP generado desde el video (`/videos/:id/sop`, RF-22 a RF-27, ADR-023): sigue el avance del
 * video y, cuando está listo, abre el editor (`SopEditor`, RF-26) con el SOP generado.
 */
@Component({
  selector: 'app-sop-generado',
  imports: [SopEditor],
  templateUrl: './sop-generado.html',
  styleUrl: './sop-generado.scss',
})
export class SopGenerado implements ConCambios {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly videoId = Number(inject(ActivatedRoute).snapshot.paramMap.get('id'));

  protected readonly video = signal<EstadoVideo | null>(null);
  protected readonly error = signal<string | null>(null);
  private readonly editor = viewChild(SopEditor);

  protected readonly etapa = computed(() => {
    const etapa = this.video()?.etapa;
    return etapa ? (ETAPAS[etapa] ?? etapa) : 'En cola';
  });

  constructor() {
    timer(0, INTERVALO_MS)
      .pipe(
        switchMap(() => this.api.estadoVideo(this.videoId)),
        takeWhile((v) => v.proceso !== 'listo' && v.proceso !== 'error', true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (video) => this.video.set(video),
        error: (e: unknown) =>
          this.error.set(`No se pudo consultar el video. ${mensajeDeError(e)}`),
      });
  }

  /** Para `sinGuardar`: lo que diga el editor. */
  puedeSalir(): boolean {
    return this.editor()?.puedeSalir() ?? true;
  }
}
