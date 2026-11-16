import { Component, inject, viewChild } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AvanceVideo } from '../avance/avance.service';
import { ConCambios } from './sin-guardar.guard';
import { SopEditor } from './sop-editor';

/**
 * SOP generado desde el video (`/videos/:id/sop`, RF-22 a RF-27, ADR-023): sigue el avance del
 * video con `AvanceVideo` (la misma fuente y la misma tabla de etapas que Procesando y el
 * reporte) y, cuando está listo, abre el editor (`SopEditor`, RF-26) con el SOP generado.
 */
@Component({
  selector: 'app-sop-generado',
  imports: [SopEditor, RouterLink],
  providers: [AvanceVideo],
  templateUrl: './sop-generado.html',
  styleUrl: './sop-generado.scss',
})
export class SopGenerado implements ConCambios {
  protected readonly avance = inject(AvanceVideo);
  private readonly ruta = inject(ActivatedRoute).snapshot;
  protected readonly videoId = Number(this.ruta.paramMap.get('id'));
  /** `?t=N` (de `/v/:id`, un QR del PDF): el editor abre el video en ese segundo. */
  protected readonly t = this.ruta.queryParamMap.get('t') ?? undefined;
  private readonly editor = viewChild(SopEditor);

  constructor() {
    this.avance.seguir(this.videoId);
  }

  /** Para `sinGuardar`: lo que diga el editor. */
  puedeSalir(): boolean {
    return this.editor()?.puedeSalir() ?? true;
  }
}
