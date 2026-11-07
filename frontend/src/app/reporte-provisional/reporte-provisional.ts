// Provisional. Lo reemplaza la pantalla del reporte (RF-20, Sara). Ver frontend/README.md

import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { EMPTY, catchError, filter, map, switchMap, takeWhile, tap, timer } from 'rxjs';
import { ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { ReporteValidacion } from '../api/reporte-validacion';
import { EstadoVideo } from '../api/tipos';

/** Cada cuánto se consulta `GET /videos/{id}` mientras el video está en cola o en proceso. */
export const INTERVALO_MS = 3000;

/**
 * Estado del video y, al terminar, cumplimiento, semáforo y conteo tal como vienen de la API
 * (sin recalcular). La consulta se detiene con "listo", con "error" y al salir de la pantalla.
 */
@Component({
  selector: 'app-reporte-provisional',
  templateUrl: './reporte-provisional.html',
  styleUrl: './reporte-provisional.scss',
})
export class ReporteProvisional {
  private readonly api = inject(ApiService);
  private readonly ruta = inject(ActivatedRoute);

  protected readonly videoId = signal<number | null>(null);
  protected readonly estado = signal<EstadoVideo | null>(null);
  protected readonly reporte = signal<ReporteValidacion | null>(null);
  protected readonly errorConsulta = signal<string | null>(null);

  constructor() {
    this.ruta.paramMap
      .pipe(
        map((parametros) => Number(parametros.get('id'))),
        tap((id) => {
          this.videoId.set(id);
          this.estado.set(null);
          this.reporte.set(null);
          this.errorConsulta.set(null);
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
}
