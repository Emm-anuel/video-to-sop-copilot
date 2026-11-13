import { HttpErrorResponse, HttpEvent, HttpEventType } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, Subscriber, Subscription } from 'rxjs';
import { ApiService, CamposVideo } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { EstadoSubida, VideoCreado } from '../api/tipos';
import {
  REACOMODOS_MAX,
  REINTENTOS,
  esperaReintento,
  megasDe,
  offsetDe409,
  reintentable,
  siguienteParte,
} from './partes';

/** Lo que va pasando en una subida por partes. */
export type EventoSubida =
  /** La subida quedó abierta (o se retomó): guarda `uploadId` para reanudar si algo falla. */
  | { tipo: 'abierta'; uploadId: string; recibidos: number; total: number }
  /** Bytes que ya salieron, incluida la parte en vuelo. */
  | { tipo: 'avance'; enviados: number; total: number }
  /** Una parte falló y se reintenta en `esperaMs` (intento 1, 2 o 3 de `REINTENTOS`). */
  | { tipo: 'reintento'; intento: number; esperaMs: number }
  /** `POST /videos` aceptó el video (202). */
  | { tipo: 'creado'; video: VideoCreado };

/**
 * La subida falló. Con `uploadId`, lo recibido sigue en la API: `subir(…, uploadId)` reanuda desde
 * ahí. Sin él (subida rechazada o vencida), hay que empezar de nuevo.
 */
export class ErrorSubida extends Error {
  constructor(
    mensaje: string,
    readonly uploadId: string | null,
    readonly recibidos: number,
    readonly total: number,
    readonly causa: unknown,
  ) {
    super(mensaje);
    this.name = 'ErrorSubida';
  }
}

/** Se canceló la subida (desuscripción): ninguna petición más. */
class Cancelada extends Error {}

/**
 * Subida del video por partes (RF-06): `POST /uploads`, `PUT /uploads/{id}?offset=N` en secuencia
 * con `Blob.slice` y, al completar, `POST /videos` con `upload_id`.
 *
 * Cada parte se reintenta hasta `REINTENTOS` veces con espera creciente (1, 2, 4 s); antes de cada
 * reintento se pregunta `GET /uploads/{id}`, así que una parte que sí llegó (se perdió la
 * respuesta) no se repite. Un 409 trae el offset correcto y se sigue desde ahí. Desuscribirse
 * aborta la petición en vuelo; borrar lo recibido (`DELETE`) le toca a quien cancela, que es quien
 * sabe si quiere reanudar.
 */
@Injectable({ providedIn: 'root' })
export class SubidaPorPartes {
  private readonly api = inject(ApiService);

  /**
   * Sube `archivo` y crea el video con `campos`. Con `uploadId` (de un `ErrorSubida` anterior),
   * reanuda esa subida si sigue en la API y es del mismo tamaño; si no, abre otra.
   */
  subir(archivo: File, campos: CamposVideo, uploadId?: string | null): Observable<EventoSubida> {
    return new Observable<EventoSubida>((suscriptor) => {
      const vuelo = new Vuelo();
      this.correr(archivo, campos, uploadId ?? null, suscriptor, vuelo).then(
        () => suscriptor.complete(),
        (error: unknown) => {
          if (!(error instanceof Cancelada)) {
            suscriptor.error(error);
          }
        },
      );
      return () => vuelo.cancelar();
    });
  }

  private async correr(
    archivo: File,
    campos: CamposVideo,
    previo: string | null,
    suscriptor: Subscriber<EventoSubida>,
    vuelo: Vuelo,
  ): Promise<void> {
    const total = archivo.size;
    let estado = previo ? await this.retomar(previo, total, vuelo) : null;
    if (!estado) {
      try {
        estado = await vuelo.pedir(this.api.crearSubida(archivo.name, total));
      } catch (e) {
        throw new ErrorSubida(`No se pudo subir el video. ${mensajeDeError(e)}`, null, 0, total, e);
      }
    }
    const uploadId = estado.upload_id;
    const tamanoParte = estado.tamano_parte;
    let offset = estado.recibidos;
    suscriptor.next({ tipo: 'abierta', uploadId, recibidos: offset, total });
    suscriptor.next({ tipo: 'avance', enviados: offset, total });

    let fallos = 0;
    let reacomodos = 0;
    while (offset < total) {
      const [inicio, fin] = siguienteParte(offset, total, tamanoParte);
      try {
        const recibido = await vuelo.pedirEventos(
          this.api.enviarParte(uploadId, inicio, archivo.slice(inicio, fin)),
          (cargados) =>
            suscriptor.next({ tipo: 'avance', enviados: Math.min(inicio + cargados, fin), total }),
        );
        offset = recibido.recibidos;
        fallos = 0;
        reacomodos = 0;
        suscriptor.next({ tipo: 'avance', enviados: offset, total });
      } catch (e) {
        if (e instanceof Cancelada) {
          throw e;
        }
        const correcto = offsetDe409(e);
        if (correcto !== null && reacomodos < REACOMODOS_MAX) {
          reacomodos++;
          offset = correcto;
          suscriptor.next({ tipo: 'avance', enviados: offset, total });
          continue;
        }
        if (!reintentable(e) || fallos >= REINTENTOS) {
          throw this.fallo(e, uploadId, offset, total);
        }
        fallos++;
        const esperaMs = esperaReintento(fallos);
        suscriptor.next({ tipo: 'reintento', intento: fallos, esperaMs });
        await vuelo.esperar(esperaMs);
        // Reanuda desde lo que la API tiene; sin respuesta, desde donde iba.
        try {
          offset = (await vuelo.pedir(this.api.estadoSubida(uploadId))).recibidos;
          suscriptor.next({ tipo: 'avance', enviados: offset, total });
        } catch (consulta) {
          if (consulta instanceof Cancelada) {
            throw consulta;
          }
        }
      }
    }

    try {
      const video = await vuelo.pedir(this.api.crearVideo(uploadId, campos));
      suscriptor.next({ tipo: 'creado', video });
    } catch (e) {
      if (e instanceof Cancelada) {
        throw e;
      }
      // La subida sigue completa en la API (salvo un 422 de "no es un video", que la descarta:
      // al reintentar, `retomar` ve el 404 y empieza otra).
      throw new ErrorSubida(
        `El video subió, pero no se pudo registrar. ${mensajeDeError(e)}`,
        uploadId,
        total,
        total,
        e,
      );
    }
  }

  /** La subida anterior si sigue en la API y es de este archivo; si no, `null` (se abre otra). */
  private async retomar(
    uploadId: string,
    total: number,
    vuelo: Vuelo,
  ): Promise<EstadoSubida | null> {
    try {
      const estado = await vuelo.pedir(this.api.estadoSubida(uploadId));
      return estado.tamano === total ? estado : null;
    } catch (e) {
      if (e instanceof Cancelada) {
        throw e;
      }
      if (e instanceof HttpErrorResponse && e.status === 404) {
        return null;
      }
      throw new ErrorSubida(
        `No se pudo retomar la subida. ${mensajeDeError(e)}`,
        uploadId,
        0,
        total,
        e,
      );
    }
  }

  private fallo(error: unknown, uploadId: string, offset: number, total: number): ErrorSubida {
    if (reintentable(error)) {
      return new ErrorSubida(
        `Se perdió la conexión con la API después de ${REINTENTOS} reintentos. Van ` +
          `${megasDe(offset, total)}; al reintentar, la subida sigue desde ahí.`,
        uploadId,
        offset,
        total,
        error,
      );
    }
    const vencida = error instanceof HttpErrorResponse && error.status === 404;
    return new ErrorSubida(
      vencida
        ? 'La subida ya no está en la API (se canceló o caducó): al reintentar empieza de nuevo.'
        : `No se pudo subir el video. ${mensajeDeError(error)}`,
      vencida ? null : uploadId,
      offset,
      total,
      error,
    );
  }
}

/** La petición o la espera en curso de una subida, para cortarlas al cancelar. */
class Vuelo {
  private cancelada = false;
  private actual: Subscription | null = null;
  private reloj: ReturnType<typeof setTimeout> | null = null;
  private rechazar: ((e: unknown) => void) | null = null;

  cancelar(): void {
    this.cancelada = true;
    this.actual?.unsubscribe();
    if (this.reloj !== null) {
      clearTimeout(this.reloj);
    }
    this.rechazar?.(new Cancelada());
  }

  /** El primer valor de `peticion` como promesa; desuscribirse la aborta. */
  pedir<T>(peticion: Observable<T>): Promise<T> {
    return this.envolver<T>((resolver, rechazar) =>
      peticion.subscribe({ next: resolver, error: rechazar }),
    );
  }

  /** El cuerpo de la respuesta de `peticion` (con `observe: 'events'`), avisando el avance. */
  pedirEventos<T>(
    peticion: Observable<HttpEvent<T>>,
    alAvanzar: (cargados: number) => void,
  ): Promise<T> {
    return this.envolver<T>((resolver, rechazar) =>
      peticion.subscribe({
        next: (evento) => {
          if (evento.type === HttpEventType.UploadProgress) {
            alAvanzar(evento.loaded);
          } else if (evento.type === HttpEventType.Response) {
            resolver(evento.body as T);
          }
        },
        error: rechazar,
      }),
    );
  }

  esperar(ms: number): Promise<void> {
    if (this.cancelada) {
      return Promise.reject(new Cancelada());
    }
    return new Promise<void>((resolver, rechazar) => {
      this.rechazar = rechazar;
      this.reloj = setTimeout(() => {
        this.reloj = null;
        this.rechazar = null;
        resolver();
      }, ms);
    });
  }

  private envolver<T>(
    iniciar: (resolver: (v: T) => void, rechazar: (e: unknown) => void) => Subscription,
  ): Promise<T> {
    if (this.cancelada) {
      return Promise.reject(new Cancelada());
    }
    return new Promise<T>((resolver, rechazar) => {
      this.rechazar = rechazar;
      this.actual = iniciar(
        (valor) => {
          this.rechazar = null;
          resolver(valor);
        },
        (error) => {
          this.rechazar = null;
          rechazar(error);
        },
      );
    });
  }
}
