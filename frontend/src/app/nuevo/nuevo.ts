import { HttpEventType } from '@angular/common/http';
import { Component, DestroyRef, OnInit, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import {
  Subscription,
  catchError,
  distinctUntilChanged,
  of,
  switchMap,
  takeWhile,
  tap,
  timer,
} from 'rxjs';
import { ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { METADATOS_VIDEO, MetadatosVideo } from '../api/metadatos-video';
import {
  EstadoSop,
  EstimacionImagenes,
  PedidoEstimacion,
  SopResumen,
  VideoCreado,
} from '../api/tipos';
import { SelectorSop } from './selector-sop';

export const TITULO_MAX = 300;
/** Cada cuánto se consulta `GET /sops/{id}/estado` mientras el SOP se convierte. */
export const SONDEO_SOP_MS = 2000;

/** De dónde sale el SOP de referencia (RF-07): tres modos excluyentes. */
export type ModoNuevo = 'biblioteca' | 'subir' | 'generar';

/**
 * Nuevo análisis (RF-07): el SOP de referencia sale de uno de tres modos excluyentes.
 *
 * - **De la biblioteca** (`GET /sops`): el SOP ya está listo; `POST /videos` con `modo=validar` y
 *   su `sop_id`, sin `POST /sops`, y al 202 va al reporte. Es el modo inicial si la biblioteca
 *   tiene algo. Con `?sop=ID` ("Usar para validar" del editor o de la biblioteca) llega elegido.
 * - **Subir uno ahora:** `POST /sops` (202) y, sin esperar a la conversión, `POST /videos` con el
 *   `sop_id`; mientras tanto consulta el estado del SOP cada 2 s. Navega al reporte cuando el video
 *   ya subió y el SOP quedó listo sin advertencias; con advertencias, las muestra y espera a "Ver el
 *   reporte". Si la conversión falla, cancela la subida y pide otro SOP. Si falla el video, el SOP
 *   ya guardado se reutiliza al reintentar. Si el SOP quedó con advertencias o lo convirtió el
 *   modelo, ofrece revisarlo en `/sops/:id?video=N` (RF-04): el video no espera la corrección.
 * - **No tengo SOP** (ADR-023): el video sube con `modo=generar` y se va a `/videos/:id/sop`.
 *
 * En los tres: título obligatorio y consentimiento obligatorio (RNF-16) antes de subir.
 *
 * Imágenes (ADR-024): al elegir el video se leen su duración y si tiene imagen en el navegador,
 * antes de subirlo, y se pide `GET /videos/estimacion` (de nuevo al cambiar de video, de modo o
 * de SOP). La casilla arranca con el valor de la instalación y nunca se deshabilita por falta de
 * GPU, solo informa; se deshabilita si el archivo no tiene imagen. `analizar_imagenes` viaja
 * siempre en `POST /videos`, también en `false`.
 */
@Component({
  selector: 'app-nuevo',
  imports: [ReactiveFormsModule, RouterLink, SelectorSop],
  templateUrl: './nuevo.html',
  styleUrl: './nuevo.scss',
})
export class Nuevo implements OnInit {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly leerMetadatos = inject(METADATOS_VIDEO);

  /** `?sop=ID`: un SOP ya guardado, elegido desde el editor o la biblioteca. */
  readonly sopInicial = input<number | undefined, unknown>(undefined, {
    alias: 'sop',
    transform: (v: unknown) => {
      const n = v === null || v === undefined || v === '' ? NaN : Number(v);
      return Number.isInteger(n) && n > 0 ? n : undefined;
    },
  });

  protected readonly tituloMax = TITULO_MAX;
  protected readonly form = new FormGroup({
    titulo: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(TITULO_MAX), Validators.pattern(/\S/)],
    }),
    idioma: new FormControl<'' | 'es' | 'en'>('', { nonNullable: true }),
    /** RNF-16: las personas del video saben que se grabó y aceptan el análisis. */
    consentimiento: new FormControl(false, {
      nonNullable: true,
      validators: [Validators.requiredTrue],
    }),
  });

  protected readonly modo = signal<ModoNuevo>('biblioteca');
  /** La biblioteca (`GET /sops`); `null` mientras carga. */
  protected readonly sops = signal<SopResumen[] | null>(null);
  protected readonly errorBiblioteca = signal<string | null>(null);
  /** El SOP de `?sop=ID` si no está en la lista (p. ej. todavía se convierte). */
  private readonly sopDelEnlace = signal<SopResumen | null>(null);
  protected readonly opcionesBiblioteca = computed(() => {
    const lista = this.sops() ?? [];
    const extra = this.sopDelEnlace();
    return extra && !lista.some((s) => s.id === extra.id) ? [extra, ...lista] : lista;
  });
  protected readonly sopBiblioteca = signal<number | null>(null);

  protected readonly archivoSop = signal<File | null>(null);
  protected readonly archivoVideo = signal<File | null>(null);
  /** El SOP subido ahora, con su último estado: si falla el video, el reintento no lo vuelve a subir. */
  protected readonly sop = signal<EstadoSop | null>(null);
  /** El video ya aceptado por la API (202): falta solo que el SOP quede listo. */
  protected readonly video = signal<VideoCreado | null>(null);
  protected readonly enviando = signal(false);
  protected readonly progreso = signal<number | null>(null);
  protected readonly error = signal<string | null>(null);
  /** El video ya había subido cuando falló la conversión: no se validará con ese SOP. */
  protected readonly videoSinSop = signal(false);
  protected readonly intentado = signal(false);

  // ── Imágenes (ADR-024) ──
  /** `undefined`: leyendo (o sin video); `null`: el navegador no pudo leer el archivo. */
  protected readonly metadatos = signal<MetadatosVideo | null | undefined>(undefined);
  protected readonly analizarImagenes = signal(false);
  protected readonly estimacion = signal<EstimacionImagenes | null>(null);
  protected readonly estimando = signal(false);
  protected readonly estimacionFallo = signal(false);
  protected readonly sinImagen = computed(() => this.metadatos()?.conImagen === false);
  /** "≈ N imágenes · +X s" con la casilla prendida; "(estimado)" si no se supo si hay GPU. */
  protected readonly indicador = computed(() => {
    const e = this.estimacion();
    if (!e || !this.analizarImagenes() || this.sinImagen()) {
      return null;
    }
    const segundos = e.dispositivo === 'gpu' ? e.segundos_extra_gpu : e.segundos_extra_cpu;
    const estimado = e.dispositivo_supuesto ? ' (estimado)' : '';
    return `≈ ${e.imagenes_estimadas} imágenes · +${duracionCorta(segundos)}${estimado}`;
  });
  /** El aviso del servidor, en ámbar, sin GPU o si no se supo. */
  protected readonly avisoImagenes = computed(() => {
    const e = this.estimacion();
    return e && this.analizarImagenes() && !this.sinImagen() && e.dispositivo !== 'gpu'
      ? e.aviso
      : null;
  });

  protected readonly convirtiendo = computed(() => {
    const estado = this.sop()?.estado;
    return estado === 'en_cola' || estado === 'convirtiendo';
  });
  protected readonly advertencias = computed(() =>
    this.modo() === 'subir' && this.sop()?.estado === 'listo' ? this.sop()!.advertencias : [],
  );
  /** Video subido y SOP listo con advertencias: se muestran y se sigue con "Ver el reporte". */
  protected readonly listoParaVer = computed(
    () => this.video() !== null && this.sop()?.estado === 'listo',
  );
  /** Revisar el SOP en el editor: listo con advertencias o convertido por el modelo (RF-04). */
  protected readonly conviene = computed(() => {
    const s = this.sop();
    return s?.estado === 'listo' && (s.advertencias.length > 0 || s.metodo === 'llm');
  });

  /** Título que se puso solo con el nombre del video; si el usuario lo cambia, no se toca. */
  private tituloAutomatico = '';
  /** La persona eligió un modo o tocó la casilla: ya no se cambian solos. */
  private modoTocado = false;
  private casillaTocada = false;
  private sondeo: Subscription | null = null;
  private subida: Subscription | null = null;

  /** Lo que se le pregunta a la estimación; `null` sin duración. */
  private readonly pedido = computed<PedidoEstimacion | null>(() => {
    const m = this.metadatos();
    if (!m) {
      return null;
    }
    const modo = this.modo();
    const sopId = modo === 'biblioteca' ? (this.sopBiblioteca() ?? undefined) : undefined;
    return {
      duracionS: m.duracion,
      modo: modo === 'generar' ? 'generar' : 'validar',
      sopId,
      sinImagen: !m.conImagen,
    };
  });

  constructor() {
    toObservable(this.pedido)
      .pipe(
        distinctUntilChanged((a, b) => JSON.stringify(a) === JSON.stringify(b)),
        tap((p) => {
          this.estimacion.set(null);
          this.estimacionFallo.set(false);
          this.estimando.set(p !== null);
        }),
        switchMap((p) =>
          p === null
            ? of(null)
            : this.api.estimarImagenes(p).pipe(
                catchError(() => {
                  this.estimacionFallo.set(true);
                  return of(null);
                }),
              ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((e) => {
        this.estimando.set(false);
        this.estimacion.set(e);
        if (e && !this.casillaTocada && !this.sinImagen()) {
          this.analizarImagenes.set(e.analizar_imagenes_defecto);
        }
      });
  }

  ngOnInit(): void {
    this.api
      .listarSops()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (lista) => {
          this.sops.set(lista);
          this.modoPorDefecto();
        },
        error: (e: unknown) => {
          this.sops.set([]);
          this.errorBiblioteca.set(`No se pudo leer la biblioteca. ${mensajeDeError(e)}`);
          this.modoPorDefecto();
        },
      });

    const id = this.sopInicial();
    if (id === undefined) {
      return;
    }
    this.api
      .estadoSop(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (estado) => {
          if (estado.estado === 'error') {
            this.error.set(`El SOP ${estado.codigo} no se pudo convertir: elige otro.`);
          } else if (estado.en_biblioteca === false) {
            this.error.set(
              `El SOP ${estado.codigo} no está en la biblioteca: guárdalo desde el editor antes de usarlo.`,
            );
          } else {
            this.sopDelEnlace.set({
              id: estado.id,
              codigo: estado.codigo,
              titulo: estado.titulo ?? 'Todavía se está convirtiendo',
              origen: estado.origen ?? 'cargado',
              creado: '',
              videos_validados: 0,
            });
            this.sopBiblioteca.set(estado.id);
            this.modo.set('biblioteca');
          }
        },
        error: (e: unknown) => this.error.set(`No se pudo leer el SOP ${id}. ${mensajeDeError(e)}`),
      });
  }

  protected cambiarModo(modo: ModoNuevo): void {
    this.modoTocado = true;
    this.modo.set(modo);
    this.error.set(null);
  }

  protected elegirDeBiblioteca(id: number): void {
    this.sopBiblioteca.set(id);
    this.error.set(null);
  }

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
    this.metadatos.set(undefined);
    const titulo = this.form.controls.titulo;
    if (archivo && (titulo.value === '' || titulo.value === this.tituloAutomatico)) {
      this.tituloAutomatico = sinExtension(archivo.name).slice(0, TITULO_MAX);
      titulo.setValue(this.tituloAutomatico);
    }
    if (!archivo) {
      return;
    }
    // Antes de subirlo: duración y si tiene imagen, para la estimación.
    void this.leerMetadatos(archivo).then((m) => {
      if (this.archivoVideo() !== archivo) {
        return; // ya eligió otro
      }
      if (m?.conImagen === false) {
        this.analizarImagenes.set(false);
      }
      this.metadatos.set(m);
    });
  }

  protected cambiarImagenes(evento: Event): void {
    this.casillaTocada = true;
    this.analizarImagenes.set((evento.target as HTMLInputElement).checked);
  }

  protected validar(): void {
    this.intentado.set(true);
    const video = this.archivoVideo();
    const modo = this.modo();
    const sinSop =
      (modo === 'biblioteca' && this.sopBiblioteca() === null) ||
      (modo === 'subir' && !this.archivoSop() && !this.sop());
    if (this.enviando() || !video || this.form.invalid || sinSop) {
      this.form.markAllAsTouched();
      return;
    }
    this.enviando.set(true);
    this.error.set(null);
    this.videoSinSop.set(false);

    if (modo === 'generar') {
      // Va a la vista del SOP generado, que sigue el avance.
      this.enviar(undefined, (creado) => this.navegar(['/videos', creado.id, 'sop']));
      return;
    }
    if (modo === 'biblioteca') {
      // El SOP ya está en la biblioteca: no hay conversión que esperar.
      const id = this.sopBiblioteca()!;
      this.enviar(id, (creado) => this.navegar(['/videos', creado.id, 'reporte']));
      return;
    }

    const guardado = this.sop();
    if (guardado) {
      this.seguir(guardado);
      return;
    }
    this.api
      .crearSop(this.archivoSop()!)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (creado) => {
          this.sop.set(creado);
          this.seguir(creado);
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

  /** El modo inicial al llegar la biblioteca, si nadie eligió otro ni llegó un `?sop=ID`. */
  private modoPorDefecto(): void {
    if (!this.modoTocado && this.sopBiblioteca() === null) {
      this.modo.set(this.opcionesBiblioteca().length ? 'biblioteca' : 'subir');
    }
  }

  private navegar(ruta: unknown[]): void {
    this.enviando.set(false);
    void this.router.navigate(ruta);
  }

  /** Sigue la conversión del SOP subido (si no terminó) y sube el video (si no subió), en paralelo. */
  private seguir(sop: EstadoSop): void {
    if (sop.estado !== 'listo' && !this.sondeo) {
      this.sondearSop(sop.id);
    }
    if (this.video()) {
      this.alTerminar();
    } else {
      this.enviar(sop.id, (creado) => {
        this.progreso.set(100);
        this.video.set(creado);
        this.alTerminar();
      });
    }
  }

  /** `POST /videos` con el avance de la subida; `sopId` undefined es modo generar. */
  private enviar(sopId: number | undefined, alSubir: (creado: VideoCreado) => void): void {
    const video = this.archivoVideo()!;
    const { titulo, idioma } = this.form.getRawValue();
    this.progreso.set(0);
    this.subida = this.api
      .subirVideo({
        archivo: video,
        titulo: titulo.trim(),
        sopId,
        idioma: idioma || undefined,
        analizarImagenes: this.analizarImagenes() && !this.sinImagen(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (evento) => {
          if (evento.type === HttpEventType.UploadProgress) {
            const total = evento.total ?? video.size;
            this.progreso.set(total ? Math.round((100 * evento.loaded) / total) : 0);
          } else if (evento.type === HttpEventType.Response && evento.body) {
            this.subida = null;
            alSubir(evento.body);
          }
        },
        error: (e: unknown) => {
          this.subida = null;
          this.fallo(`No se pudo subir el video. ${mensajeDeError(e)}`);
        },
      });
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

/** "~40 s" o "~4 min", con el mismo redondeo que el aviso de la API. */
export function duracionCorta(segundos: number): string {
  return segundos < 90
    ? `${Math.max(Math.round(segundos), 1)} s`
    : `${Math.round(segundos / 60)} min`;
}

function primerArchivo(evento: Event): File | null {
  return (evento.target as HTMLInputElement).files?.item(0) ?? null;
}

function sinExtension(nombre: string): string {
  const punto = nombre.lastIndexOf('.');
  return punto > 0 ? nombre.slice(0, punto) : nombre;
}
