import { HttpClient, HttpEvent } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ReporteValidacion } from './reporte-validacion';
import { EstadoSop, EstadoVideo, VideoCreado } from './tipos';

/** Prefijo que el proxy de `ng serve` reenvía a la API sin `/api` (proxy.conf.json). */
export const API = '/api';

export interface SubidaVideo {
  archivo: File;
  titulo: string;
  sopId: number;
  /** ISO 639-1. Sin él, Whisper detecta el idioma. */
  idioma?: string;
}

/** Cliente de la API de SOPVID (rutas en docs/dev/api.md). */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  /**
   * `POST /sops` (RF-01, RF-03): SOP en .md, .txt, .pdf o .docx. Responde 202 con el SOP en
   * `en_cola`; la conversión sigue en `estadoSop`.
   */
  crearSop(archivo: File): Observable<EstadoSop> {
    const datos = new FormData();
    datos.append('archivo', archivo, archivo.name);
    return this.http.post<EstadoSop>(`${API}/sops`, datos);
  }

  /** `GET /sops/{id}/estado`: en_cola, convirtiendo, listo (con advertencias) o error. */
  estadoSop(id: number): Observable<EstadoSop> {
    return this.http.get<EstadoSop>(`${API}/sops/${id}/estado`);
  }

  /** `POST /videos` en modo validar, con los eventos de avance de la subida. */
  subirVideo(subida: SubidaVideo): Observable<HttpEvent<VideoCreado>> {
    const datos = new FormData();
    datos.append('archivo', subida.archivo, subida.archivo.name);
    datos.append('titulo', subida.titulo);
    datos.append('modo', 'validar');
    datos.append('sop_id', String(subida.sopId));
    if (subida.idioma) {
      datos.append('idioma', subida.idioma);
    }
    return this.http.post<VideoCreado>(`${API}/videos`, datos, {
      reportProgress: true,
      observe: 'events',
    });
  }

  /** `GET /videos/{id}`: proceso, etapa y progreso. */
  estadoVideo(id: number): Observable<EstadoVideo> {
    return this.http.get<EstadoVideo>(`${API}/videos/${id}`);
  }

  /**
   * `POST /videos/{id}/validar?continuar=true` (ADR-020): sigue una validación detenida por
   * afinidad baja, sin repetir la transcripción ni la ficha. 202 y el video vuelve a `en_cola`.
   */
  continuarValidacion(id: number): Observable<VideoCreado> {
    return this.http.post<VideoCreado>(`${API}/videos/${id}/validar`, null, {
      params: { continuar: 'true' },
    });
  }

  /** `GET /videos/{id}/reporte`: 409 mientras no está listo. */
  reporte(id: number): Observable<ReporteValidacion> {
    return this.http.get<ReporteValidacion>(`${API}/videos/${id}/reporte`);
  }
}
