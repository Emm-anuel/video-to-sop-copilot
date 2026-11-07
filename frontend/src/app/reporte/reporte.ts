import { DecimalPipe } from '@angular/common';
import { Component, ElementRef, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { EMPTY, catchError, filter, map, switchMap, takeWhile, tap, timer } from 'rxjs';
import { API, ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { Estado, FilaReporte, ReporteValidacion, Semaforo, Tipo } from '../api/reporte-validacion';
import { EstadoVideo } from '../api/tipos';

/** Cada cuánto se consulta `GET /videos/{id}` mientras el video está en cola o en proceso. */
export const INTERVALO_MS = 3000;

/** Estado de la fila tal como se muestra; "zona_gris" es un par que el juez no revisó. */
const ETIQUETA_ESTADO: Record<Estado, string> = {
  Cumple: 'Cumple',
  Parcial: 'Parcial',
  Falta: 'Falta',
  Sobra: 'Sobra',
  zona_gris: 'Sin revisar',
};

const ETIQUETA_SEMAFORO: Record<Semaforo, string> = {
  verde: 'Verde',
  amarillo: 'Amarillo',
  rojo: 'Rojo',
};

/** Tipos de `metadatos.avisos` en español (src/sopvid/contrato.py, `TipoAviso`). */
const ETIQUETA_AVISO: Record<Tipo, string> = {
  segmentacion_heuristica: 'Pasos del video por heurística (el modelo de lenguaje no respondió)',
  juez_sin_revisar: 'Pares sin revisar por el juez',
  pasos_sin_redactar: 'Pasos del video sin redactar',
};

const ETIQUETA_MARCO = { intro: 'Intro del operador', cierre: 'Cierre del operador' } as const;

/** Segundos de la transcripción como `mm:ss` (los minutos pueden pasar de 59). */
export function mmss(segundos: number): string {
  const total = Math.floor(segundos);
  const min = Math.floor(total / 60);
  const seg = total % 60;
  return `${String(min).padStart(2, '0')}:${String(seg).padStart(2, '0')}`;
}

/**
 * Reporte de validación (RF-20): semáforo, resumen y tabla paso a paso con cita y segundo, con el
 * video al lado. Mientras el video no está listo muestra el avance; la consulta se detiene con
 * "listo", con "error" y al salir de la pantalla. Todo se muestra tal como viene de la API: el
 * semáforo no se recalcula y los segundos salen de la transcripción (regla 4 de CLAUDE.md).
 */
@Component({
  selector: 'app-reporte',
  imports: [DecimalPipe],
  templateUrl: './reporte.html',
  styleUrl: './reporte.scss',
})
export class Reporte {
  private readonly api = inject(ApiService);
  private readonly ruta = inject(ActivatedRoute);
  private readonly reproductor = viewChild<ElementRef<HTMLVideoElement>>('reproductor');

  protected readonly videoId = signal<number | null>(null);
  protected readonly estado = signal<EstadoVideo | null>(null);
  protected readonly reporte = signal<ReporteValidacion | null>(null);
  protected readonly errorConsulta = signal<string | null>(null);
  /** Índice en `filas` de la última fila a la que se saltó. */
  protected readonly filaActiva = signal<number | null>(null);
  protected readonly videoNoDisponible = signal(false);

  protected readonly etiquetaSemaforo = ETIQUETA_SEMAFORO;
  protected readonly mmss = mmss;

  constructor() {
    this.ruta.paramMap
      .pipe(
        map((parametros) => Number(parametros.get('id'))),
        tap((id) => {
          this.videoId.set(id);
          this.estado.set(null);
          this.reporte.set(null);
          this.errorConsulta.set(null);
          this.filaActiva.set(null);
          this.videoNoDisponible.set(false);
        }),
        switchMap((id) =>
          timer(0, INTERVALO_MS).pipe(
            switchMap(() => this.api.estadoVideo(id)),
            tap((estado) => this.estado.set(estado)),
            takeWhile((estado) => estado.proceso !== 'listo' && estado.proceso !== 'error', true),
            filter((estado) => estado.proceso === 'listo'),
            switchMap(() => this.api.reporte(id)),
            catchError((e: unknown) => {
              this.errorConsulta.set(mensajeDeError(e));
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((reporte) => this.reporte.set(reporte));
  }

  protected urlVideo(id: number): string {
    return `${API}/videos/${id}/video`;
  }

  protected etiquetaEstado(fila: FilaReporte): string {
    return fila.marco_operador ? ETIQUETA_MARCO[fila.marco_operador] : ETIQUETA_ESTADO[fila.estado];
  }

  protected claseEstado(fila: FilaReporte): string {
    return fila.marco_operador ? 'estado-marco' : `estado-${fila.estado.toLowerCase()}`;
  }

  protected etiquetaAviso(tipo: Tipo): string {
    return ETIQUETA_AVISO[tipo] ?? tipo;
  }

  protected tieneSegundo(fila: FilaReporte): boolean {
    return fila.t_inicio != null;
  }

  protected muestraJustificacion(fila: FilaReporte): boolean {
    return !!fila.justificacion && (fila.estado === 'Parcial' || fila.estado === 'zona_gris');
  }

  /** Salta al segundo de la fila y reproduce. Un Falta no tiene segundo en el video. */
  protected irA(fila: FilaReporte, indice: number): void {
    if (fila.t_inicio == null) {
      return;
    }
    this.filaActiva.set(indice);
    const video = this.reproductor()?.nativeElement;
    if (!video) {
      return;
    }
    video.currentTime = fila.t_inicio;
    // play() puede rechazarse (p. ej. si el video no cargó); el aviso ya lo da el evento error.
    void video.play()?.catch(() => undefined);
  }
}
