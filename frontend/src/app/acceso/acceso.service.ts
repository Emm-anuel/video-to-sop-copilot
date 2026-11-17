import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, catchError, map, shareReplay, tap, throwError } from 'rxjs';
import { API } from '../api/api.service';

/** Las dos vistas de §11: la de carga (SOP, subidas, videos) y la de búsqueda (`/buscar`). */
export type Vista = 'carga' | 'busqueda';

/** `abierta`: la vista no tiene clave (desarrollo). `sesion`: el navegador ya trae su cookie. */
export interface EstadoVista {
  abierta: boolean;
  sesion: boolean;
}

/** `GET /acceso` (ADR-027). */
export interface EstadoAcceso {
  carga: EstadoVista;
  busqueda: EstadoVista;
}

/** Cómo se nombra cada vista en pantalla. */
export const NOMBRE_VISTA: Record<Vista, string> = { carga: 'carga', busqueda: 'búsqueda' };

/** Si `valor` es una vista (p. ej. el `?vista=` de `/acceso`). */
export function esVista(valor: unknown): valor is Vista {
  return valor === 'carga' || valor === 'busqueda';
}

/**
 * Clave de acceso por vista (§11, ADR-027). La clave nunca se guarda en el navegador: `POST
 * /acceso` deja una cookie HttpOnly que la API acepta en lugar de `X-Clave-Acceso`, también en
 * `<img>`, `<video>` y descargas. Como el código no ve esa cookie, pregunta a `GET /acceso` qué
 * vistas están abiertas o con sesión; la respuesta se guarda hasta `olvidar()` (un 401, entrar o
 * salir).
 */
@Injectable({ providedIn: 'root' })
export class AccesoService {
  private readonly http = inject(HttpClient);
  private consulta: Observable<EstadoAcceso> | null = null;

  /** El último estado que dio la API, o null (para mostrar "Salir" en la barra). */
  readonly ultimo = signal<EstadoAcceso | null>(null);

  /** `GET /acceso`, una vez hasta `olvidar()`; si falla, la siguiente vuelve a preguntar. */
  estado(): Observable<EstadoAcceso> {
    this.consulta ??= this.http.get<EstadoAcceso>(`${API}/acceso`).pipe(
      tap((estado) => this.ultimo.set(estado)),
      catchError((error: unknown) => {
        this.consulta = null;
        return throwError(() => error);
      }),
      shareReplay({ bufferSize: 1, refCount: false }),
    );
    return this.consulta;
  }

  /** Si se puede entrar a `vista` sin pedir la clave (abierta o con sesión). */
  permite(vista: Vista): Observable<boolean> {
    return this.estado().pipe(map((estado) => estado[vista].abierta || estado[vista].sesion));
  }

  /** `POST /acceso`: 204 con la clave correcta (deja la cookie); 401 si no lo es. */
  entrar(vista: Vista, clave: string): Observable<void> {
    return this.http.post<void>(`${API}/acceso`, { vista, clave }).pipe(tap(() => this.olvidar()));
  }

  /** `DELETE /acceso`: cierra la sesión de `vista` (o de las dos). */
  salir(vista?: Vista): Observable<void> {
    const params: Record<string, string> = vista ? { vista } : {};
    return this.http.delete<void>(`${API}/acceso`, { params }).pipe(tap(() => this.olvidar()));
  }

  /** Olvida el estado guardado: la próxima consulta vuelve a preguntar a la API. */
  olvidar(): void {
    this.consulta = null;
    this.ultimo.set(null);
  }
}
