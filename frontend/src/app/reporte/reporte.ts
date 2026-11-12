import { DecimalPipe } from '@angular/common';
import { Component, ElementRef, computed, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { EMPTY, catchError, filter, map, switchMap } from 'rxjs';
import { API, ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import {
  Aviso,
  Dispositivos,
  Estado,
  FilaReporte,
  Imagenes,
  Llm,
  ReporteValidacion,
  Segundos,
  Semaforo,
  Tipo,
} from '../api/reporte-validacion';
import { AvanceVideo } from '../avance/avance.service';
import { etiquetaEtapa } from '../avance/etapas';

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
  transcripcion_no_referencia: 'Transcripción con un Whisper que no es el de referencia',
  imagenes_incompletas: 'Imágenes sin describir',
  sin_imagen: 'Video sin imagen',
};

/**
 * Avisos que solo informan y no vuelven provisional el reporte (`AVISOS_INFORMATIVOS` del
 * contrato, ADR-024): no van en el recuadro de "Reporte provisional".
 */
export const AVISOS_INFORMATIVOS: readonly Tipo[] = ['sin_imagen'];

/** Los avisos que vuelven provisional el reporte (fallas del sistema, ADR-019). */
export function avisosQueAfectan(avisos: readonly Aviso[] | undefined): Aviso[] {
  return (avisos ?? []).filter((a) => !AVISOS_INFORMATIVOS.includes(a.tipo));
}

/** El renglón "Imágenes" de "Cómo se obtuvo": "sí, N" o "no" (ADR-024). */
export function textoImagenes(imagenes: Imagenes | null | undefined): string {
  return imagenes?.descritas ? `sí, ${imagenes.cantidad ?? 0}` : 'no';
}

const ETIQUETA_MARCO = { intro: 'Intro del operador', cierre: 'Cierre del operador' } as const;

/** Dónde corrió un modelo (`metadatos.dispositivos`, ADR-018). */
const ETIQUETA_DISPOSITIVO: Record<Llm, string> = {
  gpu: 'GPU',
  cpu: 'CPU',
  desconocido: 'Desconocido',
};

/** Etapas de `metadatos.segundos`. */
type Etapa =
  | 'duracion'
  | 'audio'
  | 'transcripcion'
  | 'fotogramas'
  | 'contexto'
  | 'segmentacion'
  | 'emparejamiento'
  | 'miniaturas';

/** Orden en que corren las etapas (y en que se muestran). */
const ORDEN_ETAPAS: readonly Etapa[] = [
  'duracion',
  'audio',
  'transcripcion',
  'fotogramas',
  'contexto',
  'segmentacion',
  'emparejamiento',
  'miniaturas',
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
    nombre: etiquetaEtapa(clave),
    segundos: segundos[clave],
  }));
}

/** Suma de las etapas presentes: lo único que se calcula en "Cómo se obtuvo". */
export function totalSegundos(etapas: readonly TiempoEtapa[]): number {
  return etapas.reduce((suma, etapa) => suma + etapa.segundos, 0);
}

/** URL de la miniatura del segundo `t` del video (`GET /videos/{id}/thumb`, ADR-024). */
export function urlMiniatura(id: number, t: number): string {
  return `${API}/videos/${id}/thumb?t=${t}`;
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
 * video al lado. Mientras el video no está listo muestra un avance breve (el detalle está en
 * `/videos/:id/procesando`). El avance sale de `AvanceVideo`, que deja de consultar con "listo",
 * "error", "afinidad_baja" (el video parece no ser del SOP: se advierte y se ofrece continuar,
 * ADR-020) y al salir de la pantalla. Todo se muestra tal como viene de la API: el semáforo no se
 * recalcula y los segundos salen de la transcripción (regla 4 de CLAUDE.md).
 */
@Component({
  selector: 'app-reporte',
  imports: [DecimalPipe, RouterLink],
  providers: [AvanceVideo],
  templateUrl: './reporte.html',
  styleUrl: './reporte.scss',
})
export class Reporte {
  private readonly api = inject(ApiService);
  private readonly ruta = inject(ActivatedRoute);
  protected readonly avance = inject(AvanceVideo);
  private readonly reproductor = viewChild<ElementRef<HTMLVideoElement>>('reproductor');

  protected readonly videoId = signal<number | null>(null);
  protected readonly estado = this.avance.estado;
  protected readonly reporte = signal<ReporteValidacion | null>(null);
  private readonly errorReporte = signal<string | null>(null);
  /** Una falla de la consulta del estado (que no se reintenta), del reporte o de continuar. */
  protected readonly errorConsulta = computed(
    () => this.errorReporte() ?? this.avance.errorConsulta(),
  );
  /** Índice en `filas` de la última fila a la que se saltó. */
  protected readonly filaActiva = signal<number | null>(null);
  protected readonly videoNoDisponible = signal(false);
  /** Mientras se envía "Continuar de todos modos" (evita el doble envío). */
  protected readonly continuando = signal(false);

  /**
   * Tiempo de procesamiento medido en esta pantalla (`AvanceVideo.segundos`): empieza al ver el
   * video en cola o en proceso y se congela al terminar. Null si ya estaba listo al abrir.
   */
  protected readonly segundosProceso = this.avance.segundos;

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
      imagenes: textoImagenes(metadatos.imagenes),
    };
  });

  /** Avisos del recuadro "Reporte provisional": sin los informativos. */
  protected readonly avisosProvisional = computed(() =>
    avisosQueAfectan(this.reporte()?.metadatos.avisos),
  );

  /**
   * El video no tiene imagen (aviso "sin_imagen", ADR-024): no hay miniaturas y la columna no se
   * dibuja.
   */
  protected readonly sinImagen = computed(
    () => this.reporte()?.metadatos.avisos?.some((a) => a.tipo === 'sin_imagen') ?? false,
  );

  /** Filas cuya miniatura no cargó: se ocultan en lugar de mostrar una imagen rota. */
  protected readonly miniaturasFallidas = signal<ReadonlySet<number>>(new Set());

  protected readonly etiquetaSemaforo = ETIQUETA_SEMAFORO;
  protected readonly mmss = mmss;
  protected readonly formatoSegundos = formatoSegundos;
  protected readonly noRegistrado = NO_REGISTRADO;
  protected readonly claseDispositivo = CLASE_DISPOSITIVO;

  constructor() {
    this.ruta.paramMap
      .pipe(
        map((parametros) => Number(parametros.get('id'))),
        takeUntilDestroyed(),
      )
      .subscribe((id) => {
        this.videoId.set(id);
        this.reporte.set(null);
        this.errorReporte.set(null);
        this.filaActiva.set(null);
        this.videoNoDisponible.set(false);
        this.miniaturasFallidas.set(new Set());
        this.avance.seguir(id);
      });

    this.avance.terminado
      .pipe(
        filter((estado) => estado.proceso === 'listo'),
        switchMap((estado) =>
          this.api.reporte(estado.id).pipe(
            catchError((e: unknown) => {
              this.errorReporte.set(mensajeDeError(e));
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((reporte) => this.reporte.set(reporte));
  }

  /**
   * "Continuar de todos modos" (ADR-020): pide seguir la validación detenida por afinidad baja y
   * vuelve a consultar el estado hasta el reporte.
   */
  protected continuar(): void {
    const id = this.videoId();
    if (id == null || this.continuando()) {
      return;
    }
    this.continuando.set(true);
    this.errorReporte.set(null);
    this.api.continuarValidacion(id).subscribe({
      next: () => {
        this.continuando.set(false);
        this.avance.seguir(id);
      },
      error: (e: unknown) => {
        this.continuando.set(false);
        this.errorReporte.set(mensajeDeError(e));
      },
    });
  }

  protected urlVideo(id: number): string {
    return `${API}/videos/${id}/video`;
  }

  /** Miniatura del segundo de la fila (`GET /videos/{id}/thumb`, ADR-024): se pide por segundo. */
  protected urlMiniatura(id: number, t: number): string {
    return urlMiniatura(id, t);
  }

  protected ocultarMiniatura(indice: number): void {
    this.miniaturasFallidas.update((fallidas) => new Set(fallidas).add(indice));
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
