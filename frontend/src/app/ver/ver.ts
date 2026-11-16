import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { EMPTY, catchError, filter, switchMap } from 'rxjs';
import { AccesoService } from '../acceso/acceso.service';
import { ApiService } from '../api/api.service';
import { segundoDeConsulta } from '../api/reproductor';
import { EstadoVideo } from '../api/tipos';
import { mmss } from '../reporte/reporte';
import { Reproductor } from '../reproductor/reproductor';

/**
 * `/v/:id?t=N&k=…` (§11, RF-29, RF-30, ADR-027): el destino de los QR y de los enlaces del PDF.
 * Página mínima, sin el menú de la vista de carga: el video en el segundo `t`. El token `k` (lo
 * firma la API con `SECRETO_ENLACES`) abre solo este video y su miniatura, sin clave; sin
 * `SECRETO_ENLACES`, el enlace va sin `k` y el video queda abierto, como en desarrollo.
 *
 * Si la sesión ya tiene la clave de carga (o la vista está abierta), ofrece además "Abrir el
 * reporte" (validar) o "Abrir el SOP" (generar) con `?t=`. Sin ella no pide la clave: la ruta no
 * tiene `data.vista`, así que un 401 no lleva a `/acceso`. No exige que el video esté publicado
 * (decisión de #21).
 */
@Component({
  selector: 'app-ver',
  imports: [Reproductor, RouterLink],
  templateUrl: './ver.html',
  styleUrl: './ver.scss',
})
export class Ver {
  private readonly api = inject(ApiService);
  private readonly acceso = inject(AccesoService);

  protected readonly id: number;
  protected readonly t: number | null;
  protected readonly k: string | null;
  protected readonly mmss = mmss;
  /** El video, solo si la sesión tiene la vista de carga (`GET /videos/{id}` la pide). */
  protected readonly video = signal<EstadoVideo | null>(null);

  /** "Abrir el reporte" o "Abrir el SOP", con su ruta, o null sin la vista de carga. */
  protected readonly abrir = computed(() => {
    const video = this.video();
    if (video === null) {
      return null;
    }
    const validar = video.modo === 'validar';
    return {
      ruta: ['/videos', this.id, validar ? 'reporte' : 'sop'],
      texto: validar ? 'Abrir el reporte' : 'Abrir el SOP',
    };
  });

  protected readonly consulta = computed(() => (this.t === null ? {} : { t: this.t }));

  constructor() {
    const ruta = inject(ActivatedRoute).snapshot;
    this.id = Number(ruta.paramMap.get('id'));
    this.t = segundoDeConsulta(ruta.queryParamMap.get('t'));
    this.k = ruta.queryParamMap.get('k') || null;
    this.acceso
      .estado()
      .pipe(
        filter((estado) => estado.carga.abierta || estado.carga.sesion),
        switchMap(() => this.api.estadoVideo(this.id)),
        // Sin la API o sin el video, la página se queda con el reproductor (que dice si no carga).
        catchError(() => EMPTY),
        takeUntilDestroyed(),
      )
      .subscribe((video) => this.video.set(video));
  }
}
