import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { segundoDeConsulta } from '../api/reproductor';

/**
 * `/v/:id?t=N` (§11): el destino de los QR y de los enlaces del PDF (RF-29, RF-30). No tiene
 * reproductor propio: pregunta el modo del video y lleva al reporte (validar) o al SOP generado
 * (generar) con `?t=`, y esas pantallas abren su video en ese segundo. Reemplaza la URL, así que
 * "Atrás" no vuelve aquí. No exige que el video esté publicado (decisión de #21).
 */
@Component({
  selector: 'app-ver',
  template: `
    @if (error(); as mensaje) {
      <p class="error" role="alert">No se pudo abrir el video. {{ mensaje }}</p>
    } @else {
      <p role="status">Abriendo el video…</p>
    }
  `,
})
export class Ver {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  protected readonly error = signal<string | null>(null);

  constructor() {
    const ruta = inject(ActivatedRoute).snapshot;
    const id = Number(ruta.paramMap.get('id'));
    const t = segundoDeConsulta(ruta.queryParamMap.get('t'));
    this.api
      .estadoVideo(id)
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (video) => {
          const pantalla = video.modo === 'validar' ? 'reporte' : 'sop';
          void this.router.navigate(['/videos', id, pantalla], {
            queryParams: t === null ? {} : { t },
            replaceUrl: true,
          });
        },
        error: (e: unknown) => this.error.set(mensajeDeError(e)),
      });
  }
}
