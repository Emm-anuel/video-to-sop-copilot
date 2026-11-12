import { DecimalPipe } from '@angular/common';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { forkJoin, switchMap, takeWhile, timer } from 'rxjs';
import { API, ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { PasoSOP, SOP } from '../api/sop';
import { EstadoVideo, SopDetalle } from '../api/tipos';

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

/** Lo que muestra la evidencia de un dato: de dónde sale, qué tan sólido es y en qué segundo. */
export interface Evidencia {
  fuente?: string;
  confianza?: string;
  t?: number | null;
  cita?: string;
}

/**
 * SOP generado desde el video (RF-22 a RF-25, ADR-023), solo lectura: sigue el avance del video
 * y, cuando está listo, muestra el cuadro resumen, la tabla de pasos y los puntos y palabras
 * clave con sus menciones. Lo inferido (sin cita en el video) va resaltado para revisarlo. Un
 * botón guarda el SOP en la biblioteca (RF-27). La edición (RF-26) llega después.
 */
@Component({
  selector: 'app-sop-generado',
  imports: [DecimalPipe],
  templateUrl: './sop-generado.html',
  styleUrl: './sop-generado.scss',
})
export class SopGenerado {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly videoId = Number(inject(ActivatedRoute).snapshot.paramMap.get('id'));

  protected readonly video = signal<EstadoVideo | null>(null);
  protected readonly sop = signal<SOP | null>(null);
  protected readonly detalle = signal<SopDetalle | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly guardando = signal(false);

  protected readonly etapa = computed(() => {
    const etapa = this.video()?.etapa;
    return etapa ? (ETAPAS[etapa] ?? etapa) : 'En cola';
  });
  protected readonly enBiblioteca = computed(() => this.detalle()?.en_biblioteca ?? false);
  /** El video no tiene imagen (advertencia "sin_imagen", ADR-024): no hay miniaturas. */
  protected readonly sinImagen = computed(
    () => this.detalle()?.advertencias?.some((a) => a.tipo === 'sin_imagen') ?? false,
  );
  /** Pasos cuya miniatura no cargó: se ocultan en lugar de mostrar una imagen rota. */
  protected readonly miniaturasFallidas = signal<ReadonlySet<number>>(new Set());

  constructor() {
    timer(0, INTERVALO_MS)
      .pipe(
        switchMap(() => this.api.estadoVideo(this.videoId)),
        takeWhile((v) => v.proceso !== 'listo' && v.proceso !== 'error', true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (video) => {
          this.video.set(video);
          if (video.proceso === 'listo') {
            this.cargar(video);
          }
        },
        error: (e: unknown) =>
          this.error.set(`No se pudo consultar el video. ${mensajeDeError(e)}`),
      });
  }

  protected guardar(): void {
    const detalle = this.detalle();
    if (!detalle || this.guardando()) {
      return;
    }
    this.guardando.set(true);
    this.api
      .guardarEnBiblioteca(detalle.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (estado) => {
          this.guardando.set(false);
          this.detalle.set({ ...detalle, en_biblioteca: estado.en_biblioteca ?? true });
        },
        error: (e: unknown) => {
          this.guardando.set(false);
          this.error.set(`No se pudo guardar en la biblioteca. ${mensajeDeError(e)}`);
        },
      });
  }

  /** La evidencia de un campo de un paso (equipo, validación, tiempo, responsable). */
  protected evidencia(paso: PasoSOP, campo: string, valor?: string): Evidencia | null {
    return (
      paso.evidencia?.find(
        (e) => e.campo === campo && (valor === undefined || e.valor === valor),
      ) ?? null
    );
  }

  /** Miniatura del inicio del paso (`GET /videos/{id}/thumb`, ADR-024): se pide por segundo. */
  protected urlMiniatura(t: number): string {
    return `${API}/videos/${this.videoId}/thumb?t=${t}`;
  }

  protected ocultarMiniatura(numero: number): void {
    this.miniaturasFallidas.update((fallidas) => new Set(fallidas).add(numero));
  }

  protected inferido(paso: PasoSOP, campo: string): boolean {
    return paso.campos_inferidos?.includes(campo) ?? false;
  }

  /** Segundos como mm:ss, para leer las menciones. */
  protected mmss(t: number | null | undefined): string {
    if (t === null || t === undefined) {
      return '';
    }
    const s = Math.floor(t);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }

  /** "audio · alta · 00:12" para el título de una evidencia. */
  protected describir(e: Evidencia | null | undefined): string {
    if (!e) {
      return '';
    }
    const t = e.t !== null && e.t !== undefined ? ` · ${this.mmss(e.t)}` : '';
    const cita = e.cita ? ` · «${e.cita}»` : '';
    return `${e.fuente ?? 'documento'} · ${e.confianza ?? 'alta'}${t}${cita}`;
  }

  private cargar(video: EstadoVideo): void {
    if (video.sop_id === null || video.sop_id === undefined) {
      this.error.set('El video terminó sin SOP generado.');
      return;
    }
    forkJoin([this.api.sopGenerado(this.videoId), this.api.detalleSop(video.sop_id)])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ([sop, detalle]) => {
          this.sop.set(sop);
          this.detalle.set(detalle);
        },
        error: (e: unknown) => this.error.set(`No se pudo leer el SOP. ${mensajeDeError(e)}`),
      });
  }
}
