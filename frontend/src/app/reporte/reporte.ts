import { DecimalPipe } from '@angular/common';
import { Component, ElementRef, computed, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { EMPTY, catchError, filter, map, switchMap, takeWhile, tap, timer } from 'rxjs';
import { API, ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import {
  Dispositivos,
  Estado,
  FilaReporte,
  Llm,
  ReporteValidacion,
  Segundos,
  Semaforo,
  Tipo,
} from '../api/reporte-validacion';
import { EstadoVideo } from '../api/tipos';

/** Cada cuánto se consulta `GET /videos/{id}` mientras el video está en cola o en proceso. */
export const INTERVALO_MS = 3000;

/** Estado de la fila tal como se muestra; "zona_gris" es un par que el juez no revisó. */
const ETIQUETA_ESTADO: Record<Estado, string> = {
  Cumple: 'Cumple',
  Parcial: 'Parcial',
  Falta: 'Falta',
  Sobra: 'Sobra',
  zona_gris: 'Sin revisar',
};

const ETIQUETA_SEMAFORO: Record<Semaforo, string> = {
  verde: 'Verde',
  amarillo: 'Amarillo',
  rojo: 'Rojo',
};

/** Tipos de `metadatos.avisos` en español (src/sopvid/contrato.py, `TipoAviso`). */
const ETIQUETA_AVISO: Record<Tipo, string> = {
  segmentacion_heuristica: 'Pasos del video por heurística (el modelo de lenguaje no respondió)',
  juez_sin_revisar: 'Pares sin revisar por el juez',
  pasos_sin_redactar: 'Pasos del video sin redactar',
  contexto_sin_generar: 'Ficha de contexto sin generar',
};

const ETIQUETA_MARCO = { intro: 'Intro del operador', cierre: 'Cierre del operador' } as const;

/** Dónde corrió un modelo (`metadatos.dispositivos`, ADR-018). */
const ETIQUETA_DISPOSITIVO: Record<Llm, string> = {
  gpu: 'GPU',
  cpu: 'CPU',
  desconocido: 'Desconocido',
};

/** Etapas de `metadatos.segundos`. */
type Etapa =
  'duracion' | 'audio' | 'transcripcion' | 'contexto' | 'segmentacion' | 'emparejamiento';

const ETIQUETA_ETAPA: Record<Etapa, string> = {
  duracion: 'Duración',
  audio: 'Audio',
  transcripcion: 'Transcripción',
  contexto: 'Ficha de contexto',
  segmentacion: 'Pasos del video',
  emparejamiento: 'Emparejamiento',
};

/** Orden en que corren las etapas (y en que se muestran). */
const ORDEN_ETAPAS: readonly Etapa[] = [
  'duracion',
  'audio',
  'transcripcion',
  'contexto',
  'segmentacion',
  'emparejamiento',
];

/** Color de la etiqueta del dispositivo, con las clases de los estados (reporte.scss). */
const CLASE_DISPOSITIVO: Record<DispositivoModelo['tipo'], string> = {
  gpu: 'estado-cumple',
  cpu: 'estado-sobra',
  respaldo: 'estado-parcial',
  otro: 'estado-zona_gris',
};

export const NO_REGISTRADO = 'No registrado (reporte anterior al 27 oct)';
export const NO_CORRIO = 'No corrió (solo se repitió la validación)';
export const RESPALDO_CPU = 'CPU (respaldo: falló la GPU)';

/** Una fila de "Dónde corrió": el modelo y su dispositivo ya como texto. */
export interface DispositivoModelo {
  clave: 'transcripcion' | 'llm' | 'embedder';
  modelo: string;
  texto: string;
  /** Solo para el color de la etiqueta; el texto ya dice lo mismo. */
  tipo: 'gpu' | 'cpu' | 'respaldo' | 'otro';
}

export interface TiempoEtapa {
  clave: Etapa;
  nombre: string;
  segundos: number;
}

function tipoDispositivo(dispositivo: Llm): DispositivoModelo['tipo'] {
  return dispositivo === 'desconocido' ? 'otro' : dispositivo;
}

/**
 * Dónde corrió cada modelo, tal como lo guardó el backend; `null` si el reporte no lo registró
 * (anterior al 27 oct). `transcripcion` en null: Whisper no corrió porque solo se repitió la
 * validación (ADR-019).
 */
export function dispositivosDeModelos(
  dispositivos: Dispositivos | null | undefined,
  modeloLlm: string | null | undefined,
): DispositivoModelo[] | null {
  if (!dispositivos) {
    return null;
  }
  let whisper: Pick<DispositivoModelo, 'texto' | 'tipo'>;
  if (dispositivos.transcripcion_respaldo_cpu) {
    whisper = { texto: RESPALDO_CPU, tipo: 'respaldo' };
  } else if (dispositivos.transcripcion == null) {
    whisper = { texto: NO_CORRIO, tipo: 'otro' };
  } else {
    whisper = {
      texto: ETIQUETA_DISPOSITIVO[dispositivos.transcripcion],
      tipo: tipoDispositivo(dispositivos.transcripcion),
    };
  }
  const llm = dispositivos.llm ?? 'desconocido';
  const embedder = dispositivos.embedder ?? 'desconocido';
  return [
    { clave: 'transcripcion', modelo: 'Transcripción (Whisper)', ...whisper },
    {
      clave: 'llm',
      modelo: `Pasos y juez (${modeloLlm ?? 'modelo de lenguaje'})`,
      texto: ETIQUETA_DISPOSITIVO[llm],
      tipo: tipoDispositivo(llm),
    },
    {
      clave: 'embedder',
      modelo: 'Emparejamiento (MiniLM)',
      texto: ETIQUETA_DISPOSITIVO[embedder],
      tipo: tipoDispositivo(embedder),
    },
  ];
}

/**
 * Las etapas presentes en `segundos`, en el orden en que corren. Al repetir solo la validación
 * faltan duracion, audio y transcripcion (y contexto, si se reusó la ficha guardada).
 */
export function etapasConTiempo(segundos: Segundos): TiempoEtapa[] {
  return ORDEN_ETAPAS.filter((clave) => typeof segundos[clave] === 'number').map((clave) => ({
    clave,
    nombre: ETIQUETA_ETAPA[clave],
    segundos: segundos[clave],
  }));
}

/** Suma de las etapas presentes: lo único que se calcula en "Cómo se obtuvo". */
export function totalSegundos(etapas: readonly TiempoEtapa[]): number {
  return etapas.reduce((suma, etapa) => suma + etapa.segundos, 0);
}

/** Segundos con un decimal: `11.8 s`. */
export function formatoSegundos(segundos: number): string {
  return `${segundos.toFixed(1)} s`;
}

/** Segundos de la transcripción como `mm:ss` (los minutos pueden pasar de 59). */
export function mmss(segundos: number): string {
  const total = Math.floor(segundos);
  const min = Math.floor(total / 60);
  const seg = total % 60;
  return `${String(min).padStart(2, '0')}:${String(seg).padStart(2, '0')}`;
}

/**
 * Reporte de validación (RF-20): semáforo, resumen y tabla paso a paso con cita y segundo, con el
 * video al lado. Mientras el video no está listo muestra el avance; la consulta se detiene con
 * "listo", con "error" y al salir de la pantalla. Todo se muestra tal como viene de la API: el
 * semáforo no se recalcula y los segundos salen de la transcripción (regla 4 de CLAUDE.md).
 */
@Component({
  selector: 'app-reporte',
  imports: [DecimalPipe],
  templateUrl: './reporte.html',
  styleUrl: './reporte.scss',
})
export class Reporte {
  private readonly api = inject(ApiService);
  private readonly ruta = inject(ActivatedRoute);
  private readonly reproductor = viewChild<ElementRef<HTMLVideoElement>>('reproductor');

  protected readonly videoId = signal<number | null>(null);
  protected readonly estado = signal<EstadoVideo | null>(null);
  protected readonly reporte = signal<ReporteValidacion | null>(null);
  protected readonly errorConsulta = signal<string | null>(null);
  /** Índice en `filas` de la última fila a la que se saltó. */
  protected readonly filaActiva = signal<number | null>(null);
  protected readonly videoNoDisponible = signal(false);

  /**
   * Tiempo de procesamiento medido en esta pantalla: empieza al ver el video en cola o en proceso
   * y se congela con "listo", "error" o una falla de la consulta. No usa `creado` (la hora de
   * subida), que no cambia al repetir la validación (`POST /videos/{id}/validar`).
   */
  private readonly inicio = signal<number | null>(null);
  private readonly fin = signal<number | null>(null);
  private readonly ahora = signal(Date.now());
  protected readonly segundosProceso = computed(() => {
    const inicio = this.inicio();
    return inicio == null ? null : ((this.fin() ?? this.ahora()) - inicio) / 1000;
  });

  /** Recuadro "Cómo se obtuvo": dónde corrió cada modelo y cuánto tardó cada etapa. */
  protected readonly comoSeObtuvo = computed(() => {
    const metadatos = this.reporte()?.metadatos;
    if (!metadatos) {
      return null;
    }
    const etapas = etapasConTiempo(metadatos.segundos ?? {});
    return {
      modelos: dispositivosDeModelos(metadatos.dispositivos, metadatos.modelo_llm),
      gpu: metadatos.dispositivos?.gpu ?? null,
      etapas,
      total: totalSegundos(etapas),
      heuristica: metadatos.segmentacion === 'heuristica',
    };
  });

  protected readonly etiquetaSemaforo = ETIQUETA_SEMAFORO;
  protected readonly mmss = mmss;
  protected readonly formatoSegundos = formatoSegundos;
  protected readonly noRegistrado = NO_REGISTRADO;
  protected readonly claseDispositivo = CLASE_DISPOSITIVO;

  constructor() {
    timer(0, 1000)
      .pipe(takeUntilDestroyed())
      .subscribe(() => {
        if (this.inicio() != null && this.fin() == null) {
          this.ahora.set(Date.now());
        }
      });

    this.ruta.paramMap
      .pipe(
        map((parametros) => Number(parametros.get('id'))),
        tap((id) => {
          this.videoId.set(id);
          this.estado.set(null);
          this.reporte.set(null);
          this.errorConsulta.set(null);
          this.filaActiva.set(null);
          this.videoNoDisponible.set(false);
          this.inicio.set(null);
          this.fin.set(null);
        }),
        switchMap((id) =>
          timer(0, INTERVALO_MS).pipe(
            switchMap(() => this.api.estadoVideo(id)),
            tap((estado) => {
              this.estado.set(estado);
              this.medirProceso(estado);
            }),
            takeWhile((estado) => estado.proceso !== 'listo' && estado.proceso !== 'error', true),
            filter((estado) => estado.proceso === 'listo'),
            switchMap(() => this.api.reporte(id)),
            catchError((e: unknown) => {
              this.detenerReloj();
              this.errorConsulta.set(mensajeDeError(e));
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((reporte) => this.reporte.set(reporte));
  }

  private medirProceso(estado: EstadoVideo): void {
    const enProceso = estado.proceso === 'en_cola' || estado.proceso === 'procesando';
    if (enProceso && this.inicio() == null) {
      this.inicio.set(Date.now());
      this.ahora.set(Date.now());
    } else if (!enProceso) {
      this.detenerReloj();
    }
  }

  private detenerReloj(): void {
    if (this.inicio() != null && this.fin() == null) {
      this.fin.set(Date.now());
    }
  }

  protected urlVideo(id: number): string {
    return `${API}/videos/${id}/video`;
  }

  protected etiquetaEstado(fila: FilaReporte): string {
    return fila.marco_operador ? ETIQUETA_MARCO[fila.marco_operador] : ETIQUETA_ESTADO[fila.estado];
  }

  protected claseEstado(fila: FilaReporte): string {
    return fila.marco_operador ? 'estado-marco' : `estado-${fila.estado.toLowerCase()}`;
  }

  protected etiquetaAviso(tipo: Tipo): string {
    return ETIQUETA_AVISO[tipo] ?? tipo;
  }

  protected tieneSegundo(fila: FilaReporte): boolean {
    return fila.t_inicio != null;
  }

  protected muestraJustificacion(fila: FilaReporte): boolean {
    return !!fila.justificacion && (fila.estado === 'Parcial' || fila.estado === 'zona_gris');
  }

  /** Salta al segundo de la fila y reproduce. Un Falta no tiene segundo en el video. */
  protected irA(fila: FilaReporte, indice: number): void {
    if (fila.t_inicio == null) {
      return;
    }
    this.filaActiva.set(indice);
    const video = this.reproductor()?.nativeElement;
    if (!video) {
      return;
    }
    video.currentTime = fila.t_inicio;
    // play() puede rechazarse (p. ej. si el video no cargó); el aviso ya lo da el evento error.
    void video.play()?.catch(() => undefined);
  }
}
