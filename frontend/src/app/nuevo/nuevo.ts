import { HttpEventType } from '@angular/common/http';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { AdvertenciaSOP, SopCreado } from '../api/tipos';

export const TITULO_MAX = 300;

/**
 * Subir SOP y video (MVP): `POST /sops` y luego `POST /videos` con `modo=validar` y el `sop_id`.
 * Con el 202 navega al reporte. Si falla el video, el SOP ya guardado se reutiliza al reintentar.
 */
@Component({
  selector: 'app-nuevo',
  imports: [ReactiveFormsModule],
  templateUrl: './nuevo.html',
  styleUrl: './nuevo.scss',
})
export class Nuevo {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly tituloMax = TITULO_MAX;
  protected readonly form = new FormGroup({
    titulo: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(TITULO_MAX), Validators.pattern(/\S/)],
    }),
    idioma: new FormControl<'' | 'es' | 'en'>('', { nonNullable: true }),
  });

  protected readonly archivoSop = signal<File | null>(null);
  protected readonly archivoVideo = signal<File | null>(null);
  /** SOP ya guardado: si falla el video, el reintento no lo vuelve a subir. */
  protected readonly sopGuardado = signal<SopCreado | null>(null);
  protected readonly advertencias = signal<AdvertenciaSOP[]>([]);
  protected readonly enviando = signal(false);
  protected readonly progreso = signal<number | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly intentado = signal(false);

  /** Título que se puso solo con el nombre del video; si el usuario lo cambia, no se toca. */
  private tituloAutomatico = '';

  protected elegirSop(evento: Event): void {
    this.archivoSop.set(primerArchivo(evento));
    // Otro archivo de SOP: hay que guardarlo de nuevo.
    this.sopGuardado.set(null);
    this.advertencias.set([]);
  }

  protected elegirVideo(evento: Event): void {
    const archivo = primerArchivo(evento);
    this.archivoVideo.set(archivo);
    const titulo = this.form.controls.titulo;
    if (archivo && (titulo.value === '' || titulo.value === this.tituloAutomatico)) {
      this.tituloAutomatico = sinExtension(archivo.name).slice(0, TITULO_MAX);
      titulo.setValue(this.tituloAutomatico);
    }
  }

  protected validar(): void {
    this.intentado.set(true);
    const sop = this.archivoSop();
    const video = this.archivoVideo();
    if (this.enviando() || !sop || !video || this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.enviando.set(true);
    this.error.set(null);

    const guardado = this.sopGuardado();
    if (guardado) {
      this.subirVideo(guardado, video);
      return;
    }
    this.api
      .crearSop(sop)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (creado) => {
          this.sopGuardado.set(creado);
          this.advertencias.set(creado.advertencias);
          this.subirVideo(creado, video);
        },
        error: (e: unknown) => this.fallo(`No se pudo guardar el SOP. ${mensajeDeError(e)}`),
      });
  }

  private subirVideo(sop: SopCreado, video: File): void {
    const { titulo, idioma } = this.form.getRawValue();
    this.progreso.set(0);
    this.api
      .subirVideo({
        archivo: video,
        titulo: titulo.trim(),
        sopId: sop.id,
        idioma: idioma || undefined,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (evento) => {
          if (evento.type === HttpEventType.UploadProgress) {
            const total = evento.total ?? video.size;
            this.progreso.set(total ? Math.round((100 * evento.loaded) / total) : 0);
          } else if (evento.type === HttpEventType.Response && evento.body) {
            this.progreso.set(100);
            void this.router.navigate(['/videos', evento.body.id, 'reporte']);
          }
        },
        error: (e: unknown) => this.fallo(`No se pudo subir el video. ${mensajeDeError(e)}`),
      });
  }

  private fallo(mensaje: string): void {
    this.error.set(mensaje);
    this.enviando.set(false);
    this.progreso.set(null);
  }
}

function primerArchivo(evento: Event): File | null {
  return (evento.target as HTMLInputElement).files?.item(0) ?? null;
}

function sinExtension(nombre: string): string {
  const punto = nombre.lastIndexOf('.');
  return punto > 0 ? nombre.slice(0, punto) : nombre;
}
