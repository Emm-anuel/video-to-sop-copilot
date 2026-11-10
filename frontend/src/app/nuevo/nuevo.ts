import { HttpEventType } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { Subscription, switchMap, takeWhile, timer } from 'rxjs';
import { ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { EstadoSop, VideoCreado } from '../api/tipos';

export const TITULO_MAX = 300;
/** Cada cuánto se consulta `GET /sops/{id}/estado` mientras el SOP se convierte. */
export const SONDEO_SOP_MS = 2000;

/**
 * Subir SOP y video (MVP): `POST /sops` (202) y, sin esperar a la conversión, `POST /videos` con
 * `modo=validar` y el `sop_id`; mientras tanto consulta el estado del SOP cada 2 s. Navega al
 * reporte cuando el video ya subió y el SOP quedó listo sin advertencias; con advertencias, las
 * muestra y espera a "Ver el reporte". Si la conversión falla, cancela la subida y pide otro SOP.
 * Si falla el video, el SOP ya guardado se reutiliza al reintentar.
 *
 * Con "No tengo SOP" (ADR-023) no se pide SOP: el video sube con `modo=generar` y, al aceptarlo
 * la API, se va a la vista del SOP generado (`/videos/:id/sop`), que sigue el avance.
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

  /** "No tengo SOP": el SOP se genera desde el video. */
  protected readonly sinSop = signal(false);
  protected readonly archivoSop = signal<File | null>(null);
  protected readonly archivoVideo = signal<File | null>(null);
  /** El SOP ya guardado, con su último estado: si falla el video, el reintento no lo vuelve a subir. */
  protected readonly sop = signal<EstadoSop | null>(null);
  /** El video ya aceptado por la API (202): falta solo que el SOP quede listo. */
  protected readonly video = signal<VideoCreado | null>(null);
  protected readonly enviando = signal(false);
  protected readonly progreso = signal<number | null>(null);
  protected readonly error = signal<string | null>(null);
  /** El video ya había subido cuando falló la conversión: no se validará con ese SOP. */
  protected readonly videoSinSop = signal(false);
  protected readonly intentado = signal(false);

  protected readonly convirtiendo = computed(() => {
    const estado = this.sop()?.estado;
    return estado === 'en_cola' || estado === 'convirtiendo';
  });
  protected readonly advertencias = computed(() =>
    this.sop()?.estado === 'listo' ? this.sop()!.advertencias : [],
  );
  /** Video subido y SOP listo con advertencias: se muestran y se sigue con "Ver el reporte". */
  protected readonly listoParaVer = computed(
    () => this.video() !== null && this.sop()?.estado === 'listo',
  );

  /** Título que se puso solo con el nombre del video; si el usuario lo cambia, no se toca. */
  private tituloAutomatico = '';
  private sondeo: Subscription | null = null;
  private subida: Subscription | null = null;

  protected elegirSop(evento: Event): void {
    this.archivoSop.set(primerArchivo(evento));
    // Otro archivo de SOP: hay que guardarlo de nuevo.
    this.detenerSondeo();
    this.sop.set(null);
  }

  protected elegirVideo(evento: Event): void {
    const archivo = primerArchivo(evento);
    this.archivoVideo.set(archivo);
    this.video.set(null);
    const titulo = this.form.controls.titulo;
    if (archivo && (titulo.value === '' || titulo.value === this.tituloAutomatico)) {
      this.tituloAutomatico = sinExtension(archivo.name).slice(0, TITULO_MAX);
      titulo.setValue(this.tituloAutomatico);
    }
  }

  protected cambiarSinSop(evento: Event): void {
    this.sinSop.set((evento.target as HTMLInputElement).checked);
    this.error.set(null);
  }

  protected validar(): void {
    if (this.sinSop()) {
      this.generar();
      return;
    }
    this.intentado.set(true);
    const archivoSop = this.archivoSop();
    const video = this.archivoVideo();
    if (this.enviando() || !archivoSop || !video || this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.enviando.set(true);
    this.error.set(null);
    this.videoSinSop.set(false);

    const guardado = this.sop();
    if (guardado) {
      this.seguir(guardado, video);
      return;
    }
    this.api
      .crearSop(archivoSop)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (creado) => {
          this.sop.set(creado);
          this.seguir(creado, video);
        },
        error: (e: unknown) => this.fallo(`No se pudo guardar el SOP. ${mensajeDeError(e)}`),
      });
  }

  protected verReporte(): void {
    const video = this.video();
    if (video) {
      void this.router.navigate(['/videos', video.id, 'reporte']);
    }
  }

  /** "No tengo SOP": sube el video en modo generar y va a la vista del SOP generado. */
  private generar(): void {
    this.intentado.set(true);
    const video = this.archivoVideo();
    if (this.enviando() || !video || this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const { titulo, idioma } = this.form.getRawValue();
    this.enviando.set(true);
    this.error.set(null);
    this.progreso.set(0);
    this.subida = this.api
      .subirVideo({ archivo: video, titulo: titulo.trim(), idioma: idioma || undefined })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (evento) => {
          if (evento.type === HttpEventType.UploadProgress) {
            const total = evento.total ?? video.size;
            this.progreso.set(total ? Math.round((100 * evento.loaded) / total) : 0);
          } else if (evento.type === HttpEventType.Response && evento.body) {
            this.subida = null;
            this.enviando.set(false);
            void this.router.navigate(['/videos', evento.body.id, 'sop']);
          }
        },
        error: (e: unknown) => {
          this.subida = null;
          this.fallo(`No se pudo subir el video. ${mensajeDeError(e)}`);
        },
      });
  }

  /** Sigue la conversión del SOP (si no terminó) y sube el video (si no subió), en paralelo. */
  private seguir(sop: EstadoSop, video: File): void {
    if (sop.estado !== 'listo' && !this.sondeo) {
      this.sondearSop(sop.id);
    }
    if (this.video()) {
      this.alTerminar();
    } else {
      this.subirVideo(sop, video);
    }
  }

  private sondearSop(id: number): void {
    this.sondeo = timer(SONDEO_SOP_MS, SONDEO_SOP_MS)
      .pipe(
        switchMap(() => this.api.estadoSop(id)),
        takeWhile((estado) => estado.estado !== 'listo' && estado.estado !== 'error', true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (estado) => {
          this.sop.set(estado);
          if (estado.estado === 'error') {
            this.falloSop(estado);
          } else if (estado.estado === 'listo') {
            this.sondeo = null;
            this.alTerminar();
          }
        },
        error: (e: unknown) => {
          this.sondeo = null;
          this.fallo(`No se pudo consultar el estado del SOP. ${mensajeDeError(e)}`);
        },
      });
  }

  private subirVideo(sop: EstadoSop, video: File): void {
    const { titulo, idioma } = this.form.getRawValue();
    this.progreso.set(0);
    this.subida = this.api
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
            this.subida = null;
            this.video.set(evento.body);
            this.alTerminar();
          }
        },
        error: (e: unknown) => {
          this.subida = null;
          this.fallo(`No se pudo subir el video. ${mensajeDeError(e)}`);
        },
      });
  }

  /** Con el video subido y el SOP listo: al reporte, salvo que haya advertencias que leer. */
  private alTerminar(): void {
    if (!this.video() || this.sop()?.estado !== 'listo') {
      return;
    }
    this.enviando.set(false);
    if (this.advertencias().length === 0) {
      this.verReporte();
    }
  }

  private falloSop(estado: EstadoSop): void {
    this.sondeo = null;
    this.subida?.unsubscribe();
    this.subida = null;
    this.videoSinSop.set(this.video() !== null);
    // El SOP no sirve: el reintento sube otro (o el mismo, corregido) y el video otra vez.
    this.sop.set(null);
    this.video.set(null);
    this.fallo(`No se pudo convertir el SOP ${estado.codigo}. ${estado.mensaje ?? ''}`.trim());
  }

  private detenerSondeo(): void {
    this.sondeo?.unsubscribe();
    this.sondeo = null;
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
