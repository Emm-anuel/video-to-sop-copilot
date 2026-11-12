import {
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { EMPTY, catchError, exhaustMap, filter, map, switchMap, takeWhile, tap, timer } from 'rxjs';
import { ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { EstimacionImagenes, Salud } from '../api/tipos';
import { AvanceVideo } from '../avance/avance.service';
import { estadoEtapas, etapasDelModo } from '../avance/etapas';
import { mmss } from '../reporte/reporte';

/** Cada cuánto se vuelve a leer la transcripción mientras Whisper escribe. */
export const INTERVALO_TXT_MS = 2000;

/** Etapas hasta la transcripción: mientras el video esté en una de estas, el TXT puede crecer. */
const HASTA_TRANSCRIPCION: readonly (string | null)[] = [
  null,
  'duracion',
  'audio',
  'transcripcion',
];

/** Distancia al fondo (px) con la que la transcripción se sigue desplazando sola. */
const PEGADO_PX = 24;

const TEXTO_ESTADO = {
  pendiente: 'pendiente',
  en_curso: 'en curso',
  hecha: 'hecha',
  fallo: 'falló',
  detenida: 'detenida',
} as const;

/** Dónde corre cada modelo, como texto, según el plan de `GET /health` (ADR-018). */
export function textoDispositivos(salud: Salud | null): { whisper: string; llm: string } | null {
  const d = salud?.dispositivos;
  if (!d) {
    return null;
  }
  const gpu = d.gpu ? ` (${d.gpu.nombre})` : '';
  const whisper = d.transcripcion.startsWith('cuda') ? `GPU${gpu}` : 'CPU';
  let llm: string;
  if (d.llm === 'cpu') {
    llm = 'CPU';
  } else if (d.gpu) {
    llm = `GPU${gpu}`;
  } else {
    llm = 'Lo decide Ollama (GPU si la ve)';
  }
  return { whisper, llm };
}

/** "~40 s" o "~4 min", como el aviso de la estimación. */
export function duracionAproximada(segundos: number): string {
  if (segundos < 90) {
    return `~${Math.max(Math.round(segundos), 1)} s`;
  }
  return `~${Math.round(segundos / 60)} min`;
}

/**
 * Pantalla Procesando (`/videos/:id/procesando`, RF-08): etapas en el orden real del modo,
 * porcentaje que no retrocede, tiempo transcurrido, dispositivo y la transcripción en vivo. El
 * avance sale de `AvanceVideo` (la misma fuente que el reporte y el SOP generado). Al terminar
 * va al reporte (validar, o afinidad baja, donde está el aviso con "Continuar") o al editor del
 * SOP generado (generar). Con error muestra el mensaje de la API tal cual y "Reprocesar", que
 * repite la validación o la generación sin Whisper (ADR-019).
 */
@Component({
  selector: 'app-procesando',
  imports: [RouterLink],
  providers: [AvanceVideo],
  templateUrl: './procesando.html',
  styleUrl: './procesando.scss',
})
export class Procesando {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly injector = inject(Injector);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly avance = inject(AvanceVideo);
  protected readonly videoId = Number(inject(ActivatedRoute).snapshot.paramMap.get('id'));
  private readonly cajaTxt = viewChild<ElementRef<HTMLElement>>('cajaTxt');

  protected readonly salud = signal<Salud | null>(null);
  protected readonly transcripcion = signal('');
  protected readonly reprocesando = signal(false);
  protected readonly errorReproceso = signal<string | null>(null);
  private readonly estimacion = signal<EstimacionImagenes | null>(null);
  private estimacionPedida = false;

  protected readonly mmss = mmss;
  protected readonly textoEstado = TEXTO_ESTADO;
  protected readonly urlTxt = this.api.urlTranscripcion(this.videoId);

  protected readonly etapas = computed(() => {
    const e = this.avance.estado();
    if (!e) {
      return [];
    }
    return estadoEtapas(etapasDelModo(e.modo, !!e.analizar_imagenes), e.etapa, e.proceso);
  });

  protected readonly dispositivos = computed(() => textoDispositivos(this.salud()));

  /**
   * "8 de 20 imágenes · faltan ~1 min" mientras se describen las imágenes (ADR-024). La cuenta es
   * la de la API tal cual (`imagenes_hechas`, `imagenes_total`): salta de varias en varias porque
   * así se describen. Lo que falta usa los segundos por imagen de la estimación, si llegó.
   */
  protected readonly imagenes = computed(() => {
    const e = this.avance.estado();
    if (!e || e.etapa !== 'fotogramas' || e.proceso !== 'procesando') {
      return null;
    }
    const total = e.imagenes_total;
    const hechas = e.imagenes_hechas;
    if (total == null || hechas == null || total <= 0) {
      return null;
    }
    const est = this.estimacion();
    let faltan: string | null = null;
    if (est && est.imagenes_estimadas > 0 && hechas < total) {
      const extra = est.dispositivo === 'gpu' ? est.segundos_extra_gpu : est.segundos_extra_cpu;
      faltan = `faltan ${duracionAproximada(((total - hechas) * extra) / est.imagenes_estimadas)}`;
    }
    return {
      texto: `${hechas} de ${total} imágenes`,
      faltan,
      supuesto: !!faltan && !!est?.dispositivo_supuesto,
    };
  });

  constructor() {
    this.api
      .salud()
      .pipe(
        catchError(() => EMPTY),
        takeUntilDestroyed(),
      )
      .subscribe((salud) => this.salud.set(salud));

    this.avance.terminado.pipe(takeUntilDestroyed()).subscribe((estado) => {
      if (estado.proceso === 'listo' && estado.modo === 'generar') {
        void this.router.navigate(['/videos', estado.id, 'sop'], { replaceUrl: true });
      } else if (estado.proceso === 'listo' || estado.proceso === 'afinidad_baja') {
        void this.router.navigate(['/videos', estado.id, 'reporte'], { replaceUrl: true });
      }
    });

    this.avance.seguir(this.videoId);
    this.leerTranscripcion();
    this.vigilarImagenes();
  }

  /** "Reprocesar": repite la validación o la generación con el análisis guardado (ADR-019). */
  protected reprocesar(): void {
    const e = this.avance.estado();
    if (!e || this.reprocesando()) {
      return;
    }
    this.reprocesando.set(true);
    this.errorReproceso.set(null);
    const pedido = e.modo === 'validar' ? this.api.revalidar(e.id) : this.api.regenerar(e.id);
    pedido.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        this.reprocesando.set(false);
        this.estimacion.set(null);
        this.estimacionPedida = false;
        this.avance.seguir(e.id);
      },
      error: (err: unknown) => {
        this.reprocesando.set(false);
        this.errorReproceso.set(mensajeDeError(err));
      },
    });
  }

  /**
   * Lee el TXT cada ~2 s mientras Whisper puede seguir escribiendo; una lectura más al pasar de
   * la transcripción (o al terminar) y se detiene. Una falla de red solo se salta esa lectura.
   */
  private leerTranscripcion(): void {
    timer(0, INTERVALO_TXT_MS)
      .pipe(
        exhaustMap(() => {
          const ultima = this.transcripcionCerrada();
          return this.api.transcripcionTxt(this.videoId).pipe(
            map((texto) => ({ texto, ultima })),
            catchError(() => EMPTY),
          );
        }),
        takeWhile(({ ultima }) => !ultima, true),
        takeUntilDestroyed(),
      )
      .subscribe(({ texto }) => this.mostrarTranscripcion(texto));
  }

  private transcripcionCerrada(): boolean {
    const e = this.avance.estado();
    if (!e) {
      return false;
    }
    return (
      this.avance.final() || (e.proceso === 'procesando' && !HASTA_TRANSCRIPCION.includes(e.etapa))
    );
  }

  private mostrarTranscripcion(texto: string): void {
    if (texto === this.transcripcion()) {
      return;
    }
    const caja = this.cajaTxt()?.nativeElement;
    const pegado = !caja || caja.scrollHeight - caja.scrollTop - caja.clientHeight <= PEGADO_PX;
    this.transcripcion.set(texto);
    if (pegado) {
      afterNextRender(
        () => {
          const el = this.cajaTxt()?.nativeElement;
          if (el) {
            el.scrollTop = el.scrollHeight;
          }
        },
        { injector: this.injector },
      );
    }
  }

  /**
   * Con imágenes activas, al llegar a "fotogramas" pide una vez la estimación que ya existe
   * (`GET /videos/estimacion`): los segundos por imagen con y sin GPU, para lo que falta. La duración ya está guardada
   * en ese punto (la etapa corre después del análisis).
   */
  private vigilarImagenes(): void {
    this.avance.cambios
      .pipe(
        filter(
          (e) =>
            !this.estimacionPedida &&
            !!e.analizar_imagenes &&
            e.etapa === 'fotogramas' &&
            e.duracion != null,
        ),
        tap(() => (this.estimacionPedida = true)),
        switchMap((e) =>
          this.api
            .estimarImagenes({
              duracionS: e.duracion!,
              modo: e.modo,
              sopId: e.modo === 'validar' ? (e.sop_id ?? undefined) : undefined,
            })
            .pipe(catchError(() => EMPTY)),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((est) => this.estimacion.set(est));
  }
}
