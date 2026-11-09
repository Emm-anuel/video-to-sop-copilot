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
export type Valor = number;
export type Explicacion = string;
export type BajoUmbral = boolean;
export type Cumple = number;
export type Parcial = number;
export type FueraDeOrden = number;
export type Falta = number;
export type Sobra = number;
export type SinRevisar = number;
export type MarcoOperador = number;
export type PersonasConDiferencias = number;
export type PasosFueraDeTiempo = number;
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
export type Esperado = string;
export type Observado = string | null;
export type Estado1 = "coincide" | "distinto" | "no_identificado";
export type Similitud = number | null;
export type Nota = string;
export type EsperadoMin = number | null;
export type ObservadoMin = number;
export type Origen = "narrado" | "medido";
export type Estado2 = "en_tiempo" | "excede" | "menor" | "sin_referencia";
export type Cita1 = string;
export type Filas = FilaReporte[];
export type Rol = string;
export type Estado3 = "presente" | "mencionado" | "ausente";
export type T = number | null;
export type Cita2 = string;
export type Persona = string | null;
export type Similitud1 = number | null;
export type Confianza1 = ("alta" | "media" | "baja") | null;
export type ConPasos = boolean;
export type Roles = RolReporte[];
export type EsperadoMin1 = number | null;
export type ObservadoMin1 = number;
export type Estado4 = "en_tiempo" | "excede" | "menor" | "sin_referencia";
export type Esperado1 = string | null;
export type Observado1 = string | null;
export type Estado5 = "coincide" | "distinto" | "no_mencionado" | "sin_referencia";
export type T1 = number | null;
export type Cita3 = string;
export type Segmentacion = "llm" | "heuristica";
export type MotivoRespaldo = string | null;
export type ModeloLlm = string | null;
export type Embedder = string;
export type Bajo = number;
export type Alto = number;
export type Fusion = number;
export type SemaforoVerde = number;
export type SemaforoAmarillo = number;
export type AfinidadMin = number | null;
export type ToleranciaTiempo = number | null;
export type UmbralRol = number | null;
export type AfinidadCosCero = number | null;
export type AfinidadCosCien = number | null;
export type AfinidadUmbralEquipo = number | null;
export type UmbralRolComplemento = number | null;
export type UmbralHorario = number | null;
export type Tipo =
  | "segmentacion_heuristica"
  | "juez_sin_revisar"
  | "pasos_sin_redactar"
  | "contexto_sin_generar"
  | "transcripcion_no_referencia";
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
 * redondear. `provisional` es true si hay avisos (ADR-019).
 *
 * `afinidad` (RF-17), `roles` (RF-15), `tiempo_total` y `horario` (RF-16) siguen la sección 10
 * del documento; en los reportes guardados antes de ADR-020 y ADR-021 quedan en `None` o `[]`,
 * igual que `responsable` y `tiempo` de cada fila.
 */
export interface ReporteValidacion {
  version_contrato?: VersionContrato;
  video_id: VideoId;
  sop: SOPReporte;
  cumplimiento: Cumplimiento;
  semaforo: Semaforo;
  provisional: Provisional;
  afinidad?: Afinidad | null;
  conteo: ConteoReporte;
  filas: Filas;
  roles?: Roles;
  tiempo_total?: TiempoTotal | null;
  horario?: Horario | null;
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
 * ¿El video es de este SOP? (§5.2, RF-17, ADR-020). `valor` entero de 0 a 100, como la
 * columna `reportes.afinidad`; `bajo_umbral` es `valor < AFINIDAD_MIN` (la app advierte).
 *
 * `explicacion` la arma el código con lo que comparó. `componentes` lleva el valor 0–100 de cada
 * componente que se pudo calcular ("global", "actividad", "objetivo", "equipos"); vacío en las
 * afinidades anteriores a ADR-020.
 */
export interface Afinidad {
  valor: Valor;
  explicacion: Explicacion;
  bajo_umbral: BajoUmbral;
  componentes?: Componentes;
}
export interface Componentes {
  [k: string]: number;
}
/**
 * Conteo de la clasificación. `sobra` no incluye los de `marco_operador` (ADR-016).
 *
 * `personas_con_diferencias` y `pasos_fuera_de_tiempo` van junto al porcentaje (§5.6): las
 * filas con responsable "distinto" más los roles "ausente" que son responsables de algún paso
 * (`RolReporte.con_pasos`, ADR-020), y las filas con tiempo "excede" (ADR-021: "menor" es más
 * rápido de lo esperado, no un incumplimiento). 0 en los reportes que no los calculaban.
 */
export interface ConteoReporte {
  cumple: Cumple;
  parcial: Parcial;
  fuera_de_orden: FueraDeOrden;
  falta: Falta;
  sobra: Sobra;
  sin_revisar: SinRevisar;
  marco_operador: MarcoOperador;
  personas_con_diferencias?: PersonasConDiferencias;
  pasos_fuera_de_tiempo?: PasosFueraDeTiempo;
}
/**
 * Una fila de la tabla del reporte: un `ResultadoPaso`, en el mismo orden.
 *
 * `paso_sop` es el número del paso del SOP (desde 1), sin él en un Sobra; `paso_video`, el
 * número del paso del video ya fusionado, sin él en un Falta. `t_inicio` y `cita` salen solo de
 * la transcripción (regla 4). Un zona_gris se muestra como "sin revisar". `justificacion` es la
 * del juez cuando decidió el par.
 *
 * `responsable` y `tiempo` (RF-15, RF-16) solo van en un par (Cumple, Parcial, zona_gris): un
 * Falta no tiene paso del video y un Sobra no tiene paso del SOP. Quedan en `None` en los
 * reportes guardados antes de ADR-020 y ADR-021.
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
  responsable?: ResponsableFila | null;
  tiempo?: TiempoFila | null;
}
/**
 * Responsable del paso del SOP frente a quien lo hace en el video (§5.4, RF-15).
 *
 * `esperado` es el del SOP; `observado`, quien lo hace en el video ("Nombre (rol)" o el rol;
 * `None` si no se sabe, y entonces el estado es "no_identificado" y no hay similitud).
 * `similitud` es la de los roles comparados (ADR-020: la menor entre núcleo y complemento).
 * `nota` dice cómo se identificó a la persona y los casos especiales (paso fusionado con varios
 * responsables, un solo narrador sin nombre…); vacía en los reportes anteriores a ADR-020.
 */
export interface ResponsableFila {
  esperado: Esperado;
  observado?: Observado;
  estado: Estado1;
  similitud?: Similitud;
  nota?: Nota;
}
/**
 * Duración del paso en el video frente al tiempo esperado del SOP (§5.5, RF-16).
 *
 * `observado_min` es la que narra el operador ("narrado", con la frase en `cita`, regla 4) o
 * t_fin − t_inicio del paso del video ya fusionado ("medido", sin cita); si el operador narra
 * la duración, esa gana siempre (§5.5, ADR-021). Sin tiempo esperado en el SOP, el estado es
 * "sin_referencia". Solo "excede" cuenta como fuera de tiempo; "menor" se muestra, pero no es
 * un incumplimiento.
 */
export interface TiempoFila {
  esperado_min?: EsperadoMin;
  observado_min: ObservadoMin;
  origen: Origen;
  estado: Estado2;
  cita?: Cita1;
}
/**
 * Un rol del SOP entre las personas del video (§5.4, RF-15; ADR-020).
 *
 * Presente o mencionado llevan el segundo (y la frase, si se dijo) donde aparece la persona
 * (regla 4), `persona` ("Nombre (rol)" o el rol), la `similitud` de los roles y la `confianza`
 * del rol de la persona ("baja" si no aparece en su cita: lo infirió el LLM); ausente no lleva
 * nada de eso.
 *
 * `con_pasos` es true si el rol es responsable de algún paso del SOP. Solo un rol ausente con
 * pasos cuenta en `personas_con_diferencias`: uno de apoyo o de escalamiento (p. ej. un
 * supervisor que solo atiende si algo falla) se muestra, pero no suma (decisión del 8 nov,
 * ADR-020). Por defecto true: los reportes anteriores conservan su conteo.
 */
export interface RolReporte {
  rol: Rol;
  estado: Estado3;
  t?: T;
  cita?: Cita2;
  persona?: Persona;
  similitud?: Similitud1;
  confianza?: Confianza1;
  con_pasos?: ConPasos;
}
/**
 * Duración total del procedimiento frente a la del SOP (§5.5, ADR-021): la suma de lo
 * observado en los pares (Falta y Sobra no suman) frente a `resumen.duracion_total_min` o, si
 * el SOP no lo trae, la suma de los esperados cuando todos los pasos lo tienen.
 */
export interface TiempoTotal {
  esperado_min?: EsperadoMin1;
  observado_min: ObservadoMin1;
  estado: Estado4;
}
/**
 * Horario o frecuencia del SOP frente a lo que se dice en el video (§5.5).
 *
 * Sin horario en el SOP, "sin_referencia". Si el SOP lo define y el video no lo menciona,
 * "no_mencionado". Lo observado lleva su segundo y su frase de la transcripción (regla 4).
 */
export interface Horario {
  esperado?: Esperado1;
  observado?: Observado1;
  estado: Estado5;
  t?: T1;
  cita?: Cita3;
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
  afinidad_min?: AfinidadMin;
  tolerancia_tiempo?: ToleranciaTiempo;
  umbral_rol?: UmbralRol;
  afinidad_cos_cero?: AfinidadCosCero;
  afinidad_cos_cien?: AfinidadCosCien;
  afinidad_umbral_equipo?: AfinidadUmbralEquipo;
  umbral_rol_complemento?: UmbralRolComplemento;
  umbral_horario?: UmbralHorario;
}
export interface Segundos {
  [k: string]: number;
}
/**
 * Falla del sistema que afecta al resultado. `detalle` no lleva texto del video ni del SOP.
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
