import { HttpClient, HttpEvent } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ReporteValidacion } from './reporte-validacion';
import { SOP } from './sop';
import { EstadoSop, EstadoVideo, SopDetalle, VideoCreado } from './tipos';

/** Prefijo que el proxy de `ng serve` reenvía a la API sin `/api` (proxy.conf.json). */
export const API = '/api';

export interface SubidaVideo {
  archivo: File;
  titulo: string;
  /** Con SOP, modo validar; sin él, modo generar ("No tengo SOP", ADR-023). */
  sopId?: number;
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

  /**
   * `POST /videos` con los eventos de avance de la subida: modo validar con `sopId`; sin él,
   * modo generar (el SOP sale del video).
   */
  subirVideo(subida: SubidaVideo): Observable<HttpEvent<VideoCreado>> {
    const datos = new FormData();
    datos.append('archivo', subida.archivo, subida.archivo.name);
    datos.append('titulo', subida.titulo);
    if (subida.sopId === undefined) {
      datos.append('modo', 'generar');
    } else {
      datos.append('modo', 'validar');
      datos.append('sop_id', String(subida.sopId));
    }
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

  /** `GET /videos/{id}/sop`: el SOP generado (modo generar); 409 mientras no está listo. */
  sopGenerado(videoId: number): Observable<SOP> {
    return this.http.get<SOP>(`${API}/videos/${videoId}/sop`);
  }

  /** `GET /sops/{id}`: el SOP con su código, sus advertencias y si está en la biblioteca. */
  detalleSop(id: number): Observable<SopDetalle> {
    return this.http.get<SopDetalle>(`${API}/sops/${id}`);
  }

  /**
   * `PUT /sops/{id}` (RF-04, RF-26): guarda el SOP completo. 422 si no cumple el contrato (con el
   * `detail` por campo), 409 si todavía no está listo. La API recalcula la duración total.
   */
  corregirSop(id: number, sop: SOP): Observable<SopDetalle> {
    return this.http.put<SopDetalle>(`${API}/sops/${id}`, sop);
  }

  /** `GET /sops/{id}.md`: el SOP guardado en la plantilla Markdown (ADR-015), para descargarlo. */
  urlMarkdown(id: number): string {
    return `${API}/sops/${id}.md`;
  }

  /**
   * `POST /videos/{id}/validar` (ADR-019, ADR-022): repite la validación contra el SOP guardado,
   * sin Whisper y con la segmentación guardada. 202; 409 si el video sigue en cola o procesando.
   */
  revalidar(videoId: number): Observable<VideoCreado> {
    return this.http.post<VideoCreado>(`${API}/videos/${videoId}/validar`, null);
  }

  /** `POST /sops/{id}/biblioteca` (RF-27): desde ahí sirve como referencia de otros videos. */
  guardarEnBiblioteca(id: number): Observable<EstadoSop> {
    return this.http.post<EstadoSop>(`${API}/sops/${id}/biblioteca`, null);
  }

  /** `GET /videos/{id}/reporte`: 409 mientras no está listo. */
  reporte(id: number): Observable<ReporteValidacion> {
    return this.http.get<ReporteValidacion>(`${API}/videos/${id}/reporte`);
  }
}
