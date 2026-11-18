import { DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { Observable, Subscription, exhaustMap, takeWhile, timer } from 'rxjs';
import { ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { EstadoPublicacion } from '../api/publicacion';
import { VideoResumen } from '../api/video-resumen';
import { etiquetaEtapa } from '../avance/etapas';
import { fechaCorta, fechaHora } from '../biblioteca/filtro';
import { Descargas, FormatoDescarga } from '../descargas/descargas';
import { ETIQUETA_SEMAFORO } from '../reporte/reporte';
import {
  Destino,
  FiltroEstado,
  FiltroModo,
  FiltrosVideos,
  SIN_FILTROS,
  destino,
  enProceso,
  opcionesSop,
  pasaFiltros,
} from './filtro-videos';

/** Cada cuánto se vuelve a pedir `GET /videos` mientras algún video está en cola o en proceso. */
export const SONDEO_VIDEOS_MS = 3000;

function conMayuscula(texto: string): string {
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

/** Lo que pasó al publicar, quitar o eliminar: `conflicto` (409, ámbar) explica por qué no se pudo. */
interface AvisoFila {
  texto: string;
  tipo: 'hecho' | 'conflicto' | 'error';
}

/** Una fila ya armada: el video, a dónde lleva y el PDF del menú "Descargar". */
interface Fila {
  video: VideoResumen;
  destino: Destino;
  extras: FormatoDescarga[];
}

/**
 * Lista de videos (pantalla 6, #29): del más reciente al más antiguo, con modo, SOP,
 * cumplimiento con semáforo (tal como viene de la API), estado, fecha, imágenes y si está
 * publicado. Cada fila lleva al avance, al reporte o al SOP generado según su estado (`destino`).
 *
 * Una sola consulta (`GET /videos`); la búsqueda y los filtros se aplican aquí, sobre esa lista.
 * Mientras algún video esté en cola o en proceso se vuelve a pedir cada 3 s, sin encimar
 * consultas; se detiene cuando ya no queda ninguno o al salir de la pantalla.
 *
 * "Publicar" / "Quitar de la búsqueda" (RF-32) solo con el video listo; con un 409 se muestra el
 * porqué de la API. Un video detenido por afinidad baja solo lleva a su aviso: "Continuar" está
 * en el reporte, para que se lea antes (RF-17).
 *
 * RNF-13: tarjetas por defecto y filas de tabla desde 60 rem del propio componente.
 */
@Component({
  selector: 'app-videos',
  imports: [DecimalPipe, Descargas, RouterLink],
  templateUrl: './videos.html',
  styleUrl: './videos.scss',
})
export class Videos implements OnInit {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** `null` mientras carga. */
  protected readonly videos = signal<VideoResumen[] | null>(null);
  protected readonly errorCarga = signal<string | null>(null);
  /** El refresco automático falló: la lista queda como estaba y se ofrece reintentar. */
  protected readonly errorSondeo = signal<string | null>(null);
  protected readonly filtros = signal<FiltrosVideos>(SIN_FILTROS);

  protected readonly opcionesSop = computed(() => opcionesSop(this.videos() ?? []));
  protected readonly enCurso = computed(
    () => (this.videos() ?? []).filter((v) => enProceso(v.proceso)).length,
  );
  protected readonly filas = computed<Fila[]>(() =>
    (this.videos() ?? [])
      .filter((v) => pasaFiltros(v, this.filtros()))
      .map((video) => ({ video, destino: destino(video), extras: this.extras(video) })),
  );

  protected readonly publicando = signal<ReadonlySet<number>>(new Set());
  /** El video que espera confirmación para eliminarse y el que se está eliminando. */
  protected readonly confirmando = signal<number | null>(null);
  protected readonly borrando = signal<number | null>(null);
  /** Lo que pasó al eliminar el último video (la fila ya no está para mostrarlo). */
  protected readonly resultadoBorrado = signal<string | null>(null);
  protected readonly avisos = signal<Readonly<Record<number, AvisoFila>>>({});

  protected readonly etiquetaSemaforo = ETIQUETA_SEMAFORO;
  protected readonly etiquetaEtapa = etiquetaEtapa;
  protected readonly fechaHora = fechaHora;
  protected readonly fechaCorta = fechaCorta;

  private sondeo: Subscription | null = null;

  ngOnInit(): void {
    this.recargar();
  }

  protected recargar(): void {
    this.errorCarga.set(null);
    this.errorSondeo.set(null);
    this.api
      .listarVideos()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (lista) => this.recibir(lista),
        error: (e: unknown) => {
          this.videos.set(null);
          this.errorCarga.set(`No se pudo leer la lista de videos. ${mensajeDeError(e)}`);
        },
      });
  }

  protected cambiarFiltro<K extends keyof FiltrosVideos>(campo: K, valor: FiltrosVideos[K]): void {
    this.filtros.update((f) => ({ ...f, [campo]: valor }));
  }

  protected cambiarModo(evento: Event): void {
    this.cambiarFiltro('modo', (evento.target as HTMLSelectElement).value as FiltroModo);
  }

  protected cambiarEstado(evento: Event): void {
    this.cambiarFiltro('estado', (evento.target as HTMLSelectElement).value as FiltroEstado);
  }

  protected cambiarSop(evento: Event): void {
    const valor = (evento.target as HTMLSelectElement).value;
    this.cambiarFiltro('sop', valor ? Number(valor) : null);
  }

  protected quitarFiltros(): void {
    this.filtros.set(SIN_FILTROS);
  }

  protected hayFiltros(): boolean {
    const f = this.filtros();
    return f.texto.trim() !== '' || f.modo !== 'todos' || f.estado !== 'todos' || f.sop !== null;
  }

  /** "Publicar" (POST) o "Quitar de la búsqueda" (DELETE), según cómo está el video. */
  protected alternarPublicacion(video: VideoResumen): void {
    if (this.publicando().has(video.id)) {
      return;
    }
    const publicar = !video.publicado;
    const pedido: Observable<EstadoPublicacion> = publicar
      ? this.api.publicar(video.id)
      : this.api.despublicar(video.id);
    this.publicando.update((s) => new Set(s).add(video.id));
    this.quitarAviso(video.id);
    pedido.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (estado) => {
        this.terminar(video.id);
        this.videos.update((lista) =>
          (lista ?? []).map((v) =>
            v.id === estado.video_id
              ? { ...v, publicado: estado.publicado, publicado_en: estado.publicado_en ?? null }
              : v,
          ),
        );
        const texto = estado.publicado
          ? `Publicado: ${estado.palabras_indexadas.toLocaleString('es-MX')} ${
              estado.palabras_indexadas === 1 ? 'palabra indexada' : 'palabras indexadas'
            } en la búsqueda.`
          : 'Quitado de la búsqueda.';
        this.ponerAviso(video.id, { texto, tipo: 'hecho' });
      },
      error: (e: unknown) => {
        this.terminar(video.id);
        const conflicto = e instanceof HttpErrorResponse && e.status === 409;
        const accion = publicar ? 'publicar' : 'quitar de la búsqueda';
        // Un 409 trae el porqué en una frase de la API (p. ej. el video volvió a procesarse): se
        // muestra tal cual y la lista se pide otra vez para ver su estado de ahora.
        this.ponerAviso(video.id, {
          texto: conflicto
            ? conMayuscula(mensajeDeError(e))
            : `No se pudo ${accion}. ${mensajeDeError(e)}`,
          tipo: conflicto ? 'conflicto' : 'error',
        });
        if (conflicto) {
          this.recargar();
        }
      },
    });
  }

  protected pedirConfirmacion(id: number): void {
    this.confirmando.set(id);
    this.resultadoBorrado.set(null);
    this.quitarAviso(id);
  }

  /** Elimina el video y, si nadie más lo usa, su SOP generado (`DELETE /videos/{id}`). */
  protected eliminar(video: VideoResumen): void {
    this.confirmando.set(null);
    this.borrando.set(video.id);
    this.api
      .borrarVideo(video.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.borrando.set(null);
          this.videos.update((lista) => (lista ?? []).filter((v) => v.id !== video.id));
          const sop = r.sop_eliminado
            ? ` También se eliminó el SOP ${r.sop_eliminado.codigo}.`
            : '';
          this.resultadoBorrado.set(
            `«${video.titulo}» eliminado.${sop} ${r.sop_conservado ?? ''}`.trim(),
          );
        },
        error: (e: unknown) => {
          this.borrando.set(null);
          const conflicto = e instanceof HttpErrorResponse && e.status === 409;
          this.ponerAviso(video.id, {
            texto: conflicto
              ? conMayuscula(mensajeDeError(e))
              : `No se pudo eliminar. ${mensajeDeError(e)}`,
            tipo: conflicto ? 'conflicto' : 'error',
          });
          if (conflicto) {
            this.recargar();
          }
        },
      });
  }

  /** La etiqueta del estado de un video en la lista. */
  protected estado(video: VideoResumen): string {
    switch (video.proceso) {
      case 'en_cola':
        return 'En cola';
      case 'procesando':
        return `Procesando · ${etiquetaEtapa(video.etapa)}`;
      case 'listo':
        return 'Listo';
      case 'afinidad_baja':
        return 'Detenido: el video parece no corresponder a su SOP';
      case 'error':
        return 'Error';
    }
  }

  private recibir(lista: VideoResumen[]): void {
    this.videos.set(lista);
    if (lista.some((v) => enProceso(v.proceso))) {
      this.sondear();
    }
  }

  /** Una sola consulta a la vez cada `SONDEO_VIDEOS_MS`, hasta que ningún video esté en proceso. */
  private sondear(): void {
    if (this.sondeo) {
      return;
    }
    this.sondeo = timer(SONDEO_VIDEOS_MS, SONDEO_VIDEOS_MS)
      .pipe(
        exhaustMap(() => this.api.listarVideos()),
        takeWhile((lista) => lista.some((v) => enProceso(v.proceso)), true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (lista) => {
          this.errorSondeo.set(null);
          this.videos.set(lista);
        },
        error: (e: unknown) => {
          this.sondeo = null;
          this.errorSondeo.set(`No se pudo actualizar la lista. ${mensajeDeError(e)}`);
        },
        complete: () => (this.sondeo = null),
      });
  }

  /** El PDF del menú "Descargar": el reporte (validar) o el SOP generado (generar), solo listo. */
  private extras(video: VideoResumen): FormatoDescarga[] {
    if (video.proceso !== 'listo') {
      return [];
    }
    return [
      video.modo === 'generar'
        ? {
            etiqueta: 'SOP (.pdf)',
            descripcion: 'Para imprimir, con QR al video',
            url: this.api.urlPdfVideo(video.id),
          }
        : {
            etiqueta: 'Reporte (.pdf)',
            descripcion: 'Para imprimir, con QR al segundo de cada hallazgo',
            url: this.api.urlPdfVideo(video.id),
          },
    ];
  }

  private terminar(id: number): void {
    this.publicando.update((s) => {
      const copia = new Set(s);
      copia.delete(id);
      return copia;
    });
  }

  private ponerAviso(id: number, aviso: AvisoFila): void {
    this.avisos.update((a) => ({ ...a, [id]: aviso }));
  }

  private quitarAviso(id: number): void {
    this.avisos.update((a) => {
      const { [id]: _, ...resto } = a;
      return resto;
    });
  }
}
