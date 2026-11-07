/* Generado desde docs/contrato/reporte.schema.json con `npm run tipos`. No editar a mano. */

export type VersionContrato = 1;
export type VideoId = number;
export type Id = number;
export type Codigo = string;
export type Titulo = string;
export type Numero = number;
export type Nombre = string;
export type Descripcion = string;
export type Pasos = PasoSOPReporte[];
export type Cumplimiento = number;
export type Semaforo = "verde" | "amarillo" | "rojo";
export type Provisional = boolean;
export type Afinidad = number | null;
export type Cumple = number;
export type Parcial = number;
export type FueraDeOrden = number;
export type Falta = number;
export type Sobra = number;
export type SinRevisar = number;
export type MarcoOperador = number;
export type Estado = "Cumple" | "Parcial" | "Falta" | "Sobra" | "zona_gris";
export type PasoSop = number | null;
export type NombreSop = string | null;
export type PasoVideo = number | null;
export type NombreVideo = string | null;
export type TInicio = number | null;
export type Cita = string;
export type Confianza = ("alta" | "media" | "baja") | null;
export type FueraDeOrden1 = boolean;
export type MarcoOperador1 = ("intro" | "cierre") | null;
export type Justificacion = string | null;
export type Filas = FilaReporte[];
export type Segmentacion = "llm" | "heuristica";
export type MotivoRespaldo = string | null;
export type ModeloLlm = string | null;
export type Embedder = string;
export type Bajo = number;
export type Alto = number;
export type Fusion = number;
export type SemaforoVerde = number;
export type SemaforoAmarillo = number;
export type Tipo = "segmentacion_heuristica" | "juez_sin_revisar" | "pasos_sin_redactar";
export type Detalle = string;
export type Avisos = Aviso[];
export type Gpu = string | null;
export type Transcripcion = ("cpu" | "gpu" | "desconocido") | null;
export type TranscripcionRespaldoCpu = boolean;
export type Llm = "cpu" | "gpu" | "desconocido";
export type Embedder1 = "cpu";
export type Creado = string;

/**
 * Respuesta de `GET /videos/{id}/reporte`.
 *
 * `cumplimiento` es el guardado (dos decimales); `semaforo`, el calculado con el valor sin
 * redondear. `provisional` es true si hay avisos (ADR-019). `afinidad` queda en `None` hasta
 * RF-17 (post-MVP).
 */
export interface ReporteValidacion {
  version_contrato?: VersionContrato;
  video_id: VideoId;
  sop: SOPReporte;
  cumplimiento: Cumplimiento;
  semaforo: Semaforo;
  provisional: Provisional;
  afinidad?: Afinidad;
  conteo: ConteoReporte;
  filas: Filas;
  metadatos: MetadatosValidacion;
  creado: Creado;
}
export interface SOPReporte {
  id: Id;
  codigo: Codigo;
  titulo: Titulo;
  pasos: Pasos;
}
export interface PasoSOPReporte {
  numero: Numero;
  nombre: Nombre;
  descripcion?: Descripcion;
}
/**
 * Conteo de la clasificación. `sobra` no incluye los de `marco_operador` (ADR-016).
 */
export interface ConteoReporte {
  cumple: Cumple;
  parcial: Parcial;
  fuera_de_orden: FueraDeOrden;
  falta: Falta;
  sobra: Sobra;
  sin_revisar: SinRevisar;
  marco_operador: MarcoOperador;
}
/**
 * Una fila de la tabla del reporte: un `ResultadoPaso`, en el mismo orden.
 *
 * `paso_sop` es el número del paso del SOP (desde 1), sin él en un Sobra; `paso_video`, el
 * número del paso del video ya fusionado, sin él en un Falta. `t_inicio` y `cita` salen solo de
 * la transcripción (regla 4). Un zona_gris se muestra como "sin revisar". `justificacion` es la
 * del juez cuando decidió el par.
 */
export interface FilaReporte {
  estado: Estado;
  paso_sop?: PasoSop;
  nombre_sop?: NombreSop;
  paso_video?: PasoVideo;
  nombre_video?: NombreVideo;
  t_inicio?: TInicio;
  cita?: Cita;
  confianza?: Confianza;
  fuera_de_orden?: FueraDeOrden1;
  marco_operador?: MarcoOperador1;
  justificacion?: Justificacion;
}
/**
 * Cómo se obtuvo el reporte: segmentación, modelos, umbrales, tiempos y avisos.
 *
 * `segundos` lleva lo que tardó cada etapa (duracion, audio, transcripcion, segmentacion,
 * emparejamiento); al repetir solo la validación (ADR-019) no trae las del análisis. Lo que
 * tardó el juez va aparte, en `resultado.clasificacion.resumen.segundos_juez`.
 */
export interface MetadatosValidacion {
  segmentacion: Segmentacion;
  motivo_respaldo?: MotivoRespaldo;
  modelo_llm?: ModeloLlm;
  embedder: Embedder;
  umbrales: Umbrales;
  segundos: Segundos;
  avisos?: Avisos;
  dispositivos?: Dispositivos | null;
}
/**
 * Los umbrales de la configuración con que se calculó el reporte (RNF-14).
 */
export interface Umbrales {
  bajo: Bajo;
  alto: Alto;
  fusion: Fusion;
  semaforo_verde: SemaforoVerde;
  semaforo_amarillo: SemaforoAmarillo;
}
export interface Segundos {
  [k: string]: number;
}
/**
 * Falla del sistema que afecta al reporte. `detalle` no lleva texto del video ni del SOP.
 */
export interface Aviso {
  tipo: Tipo;
  detalle: Detalle;
}
/**
 * Dónde corrió de verdad cada modelo de este reporte (ADR-018).
 *
 * La GPU cambia la velocidad, no el resultado: el modelo es el mismo en cualquier dispositivo
 * (RNF-07). `gpu` es la que vio la API (`nvidia-smi`), o None. `transcripcion` va en None al
 * repetir solo la validación (ADR-019), porque Whisper no corrió; `transcripcion_respaldo_cpu`
 * es true si cuda falló y Whisper se repitió en CPU (su tiempo no sirve para RNF-01).
 */
export interface Dispositivos {
  gpu?: Gpu;
  transcripcion?: Transcripcion;
  transcripcion_respaldo_cpu?: TranscripcionRespaldoCpu;
  llm?: Llm;
  embedder?: Embedder1;
}
