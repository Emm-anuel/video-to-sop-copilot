import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, OnDestroy, computed, inject, signal } from '@angular/core';
import {
  Observable,
  Subject,
  Subscription,
  defer,
  repeat,
  retry,
  takeWhile,
  tap,
  throwError,
  timer,
} from 'rxjs';
import { ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { EstadoVideo } from '../api/tipos';
import { ERROR_REINICIO, esFinal, etiquetaEtapa } from './etapas';

/** Cada cuánto se consulta `GET /videos/{id}` mientras el video está en cola o en proceso. */
export const INTERVALO_MS = 1500;
/** Primera espera tras una falla de red; se duplica en cada intento seguido, hasta el tope. */
export const ESPERA_INICIAL_MS = 1500;
export const ESPERA_MAXIMA_MS = 30_000;

/** Espera antes del intento `intento` (1, 2, 3…): 1.5 s, 3 s, 6 s… hasta 30 s. */
export function espera(intento: number): number {
  return Math.min(ESPERA_MAXIMA_MS, ESPERA_INICIAL_MS * 2 ** (intento - 1));
}

/**
 * Una falla que vale la pena reintentar: sin conexión (la API se reinicia o la red se cortó) o
 * un 5xx (p. ej. el proxy sin API detrás). Un 404 o un 4xx no se arreglan esperando.
 */
export function reintentable(error: unknown): boolean {
  return error instanceof HttpErrorResponse && (error.status === 0 || error.status >= 500);
}

/** Un reintento en espera: cuántas fallas seguidas van y cuánto falta para el siguiente. */
export interface Reintento {
  intento: number;
  esperaMs: number;
  mensaje: string;
}

/**
 * La única fuente del avance de un video (RF-08): consulta `GET /videos/{id}` cada 1.5 s y se
 * detiene con "listo", "error" o "afinidad_baja", con `detener()` o al destruirse el componente
 * que lo provee (`providers: [AvanceVideo]`). Si la red falla o la API se reinicia, reintenta
 * con espera creciente; al volver, la API dice si el video quedó "interrumpido por reinicio".
 * El porcentaje que expone nunca retrocede dentro de un seguimiento. Sin WebSocket ni SSE.
 */
@Injectable()
export class AvanceVideo implements OnDestroy {
  private readonly api = inject(ApiService);
  private sondeo: Subscription | null = null;
  private reloj: Subscription | null = null;
  private readonly terminados = new Subject<EstadoVideo>();
  private readonly recibidos = new Subject<EstadoVideo>();

  /** El último estado recibido; null antes de la primera respuesta. */
  readonly estado = signal<EstadoVideo | null>(null);
  /** Una falla de red en curso (se está reintentando); null si la última consulta respondió. */
  readonly reintento = signal<Reintento | null>(null);
  /** Una falla que no se reintenta (p. ej. 404): la consulta se detuvo. */
  readonly errorConsulta = signal<string | null>(null);

  private readonly maximo = signal(0);
  /** Porcentaje del video que nunca baja dentro del mismo seguimiento; 100 con "listo". */
  readonly progreso = computed(() => this.maximo());
  readonly etiqueta = computed(() => etiquetaEtapa(this.estado()?.etapa));
  readonly final = computed(() => {
    const estado = this.estado();
    return estado != null && esFinal(estado.proceso);
  });
  /** El video quedó en error porque la API se reinició a la mitad (la cola vive en memoria). */
  readonly interrumpido = computed(() => {
    const estado = this.estado();
    return estado?.proceso === 'error' && estado.error === ERROR_REINICIO;
  });

  /**
   * Tiempo transcurrido medido en esta pantalla: empieza al ver el video en cola o en proceso y
   * se congela al llegar a un estado final o al fallar la consulta. No usa `creado` (la hora de
   * subida), que no cambia al repetir.
   */
  private readonly inicio = signal<number | null>(null);
  private readonly fin = signal<number | null>(null);
  private readonly ahora = signal(Date.now());
  readonly segundos = computed(() => {
    const inicio = this.inicio();
    return inicio == null ? null : ((this.fin() ?? this.ahora()) - inicio) / 1000;
  });

  /** Emite una vez el estado final de cada seguimiento. */
  readonly terminado: Observable<EstadoVideo> = this.terminados.asObservable();
  /** Emite cada estado recibido, también el final. */
  readonly cambios: Observable<EstadoVideo> = this.recibidos.asObservable();

  /** Empieza (o vuelve a empezar, p. ej. tras reprocesar) a seguir el video `id`. */
  seguir(id: number): void {
    this.detener();
    this.estado.set(null);
    this.reintento.set(null);
    this.errorConsulta.set(null);
    this.maximo.set(0);
    this.inicio.set(null);
    this.fin.set(null);
    this.sondeo = defer(() => this.api.estadoVideo(id))
      .pipe(
        retry({
          delay: (error: unknown, intento: number) => {
            if (!reintentable(error)) {
              return throwError(() => error);
            }
            const ms = espera(intento);
            this.reintento.set({ intento, esperaMs: ms, mensaje: mensajeDeError(error) });
            return timer(ms);
          },
        }),
        repeat({ delay: INTERVALO_MS }),
        tap((estado) => this.recibir(estado)),
        takeWhile((estado) => !esFinal(estado.proceso), true),
      )
      .subscribe({
        next: (estado) => {
          if (esFinal(estado.proceso)) {
            this.terminados.next(estado);
          }
        },
        error: (e: unknown) => {
          this.reintento.set(null);
          this.errorConsulta.set(mensajeDeError(e));
          this.congelar();
        },
      });
  }

  /** Deja de consultar y de contar el tiempo. */
  detener(): void {
    this.sondeo?.unsubscribe();
    this.sondeo = null;
    this.pararReloj();
  }

  ngOnDestroy(): void {
    this.detener();
    this.terminados.complete();
    this.recibidos.complete();
  }

  private recibir(estado: EstadoVideo): void {
    this.reintento.set(null);
    this.estado.set(estado);
    this.maximo.update((previo) =>
      estado.proceso === 'listo' ? 100 : Math.max(previo, estado.progreso),
    );
    if (!esFinal(estado.proceso)) {
      if (this.inicio() == null) {
        this.inicio.set(Date.now());
        this.ahora.set(Date.now());
        this.reloj = timer(1000, 1000).subscribe(() => this.ahora.set(Date.now()));
      }
    } else {
      this.congelar();
    }
    this.recibidos.next(estado);
  }

  private congelar(): void {
    if (this.inicio() != null && this.fin() == null) {
      this.fin.set(Date.now());
    }
    this.pararReloj();
  }

  private pararReloj(): void {
    this.reloj?.unsubscribe();
    this.reloj = null;
  }
}
