/* Generado desde docs/contrato/sop.schema.json con `npm run tipos:sop`. No editar a mano. */

export type VersionContrato = 1;
export type Titulo = string;
export type Version = string;
export type Valor = string | null;
export type Confianza = "alta" | "media" | "baja";
export type Fuente = "documento" | "audio" | "visual" | "inferido";
export type T = number | null;
export type Cita = string;
/**
 * Una persona lo editó o lo confirmó en el editor (ADR-025).
 */
export type Revisado = boolean;
export type DuracionTotalMin = number | null;
export type Nombre = string;
export type Descripcion = string;
export type EquipoOperacion = Elemento[];
export type Roles = Elemento[];
export type Nombre1 = string;
export type Rol = string | null;
export type Participacion = "participa" | "mencionado";
/**
 * Segundos desde el inicio del video.
 */
export type T1 = number;
export type Cita1 = string;
export type Personas = Persona[];
export type Descripcion1 = string;
export type Nivel = "alto" | "medio" | "bajo";
export type Paso = number | null;
export type Control = string;
export type Cita2 = string;
export type Fuente1 = "documento" | "audio" | "visual" | "inferido";
export type Confianza1 = "alta" | "media" | "baja";
export type T2 = number | null;
/**
 * Una persona lo editó o lo confirmó en el editor (ADR-025).
 */
export type Revisado1 = boolean;
export type Riesgos = Riesgo[];
export type Situacion = string;
export type Accion = string;
export type Cita3 = string;
export type Fuente2 = "documento" | "audio" | "visual" | "inferido";
export type Confianza2 = "alta" | "media" | "baja";
export type T3 = number | null;
/**
 * Una persona lo editó o lo confirmó en el editor (ADR-025).
 */
export type Revisado2 = boolean;
export type EnCasoDeFalla = Falla[];
/**
 * @minItems 1
 */
export type Pasos = [PasoSOP, ...PasoSOP[]];
export type Numero = number;
export type Nombre2 = string;
export type Descripcion2 = string;
export type Responsable = string;
export type Equipo = string[];
export type PuntosValidacion = string[];
export type TiempoEsperadoMin = number | null;
export type TInicio = number | null;
export type TFin = number | null;
export type Confianza3 = "alta" | "media" | "baja";
export type CamposInferidos = string[];
export type Cita4 = string;
export type Fuente3 = "documento" | "audio" | "visual" | "inferido";
export type Campo = "equipo" | "puntos_validacion" | "tiempo_esperado_min" | "responsable";
export type Valor1 = string;
export type Cita5 = string;
export type Fuente4 = "documento" | "audio" | "visual" | "inferido";
export type Confianza4 = "alta" | "media" | "baja";
export type T4 = number | null;
export type Evidencia = Evidencia1[];
/**
 * Una persona lo editó o lo confirmó en el editor (ADR-025).
 */
export type Revisado3 = boolean;
export type Texto = string;
export type T5 = number | null;
export type Cita6 = string;
export type Fuente5 = "documento" | "audio" | "visual" | "inferido";
export type Confianza5 = "alta" | "media" | "baja";
/**
 * Una persona lo editó o lo confirmó en el editor (ADR-025).
 */
export type Revisado4 = boolean;
export type PuntosClave = PuntoClave[];
export type Termino = string;
export type Categoria = "equipo" | "accion" | "seguridad" | "calidad" | "lugar" | "material" | "otro";
export type Menciones = number;
/**
 * Items: Segundos desde el inicio del video.
 */
export type T6 = number[];
export type Literal = string;
export type PalabrasClave = PalabraClave[];

/**
 * SOP de referencia (cargado) o generado desde el video.
 */
export interface SOP {
  version_contrato?: VersionContrato;
  titulo: Titulo;
  resumen?: Resumen;
  pasos: Pasos;
  puntos_clave?: PuntosClave;
  palabras_clave?: PalabrasClave;
}
/**
 * Cuadro resumen (RF-22). `version` es la del SOP ("1.0" en uno generado, §6).
 */
export interface Resumen {
  version?: Version;
  objetivo?: Dato;
  alcance?: Dato1;
  responsable?: Dato2;
  lugar?: Dato3;
  horario_frecuencia?: Dato4;
  duracion_total_min?: DuracionTotalMin;
  equipo_operacion?: EquipoOperacion;
  roles?: Roles;
  personas?: Personas;
  riesgos?: Riesgos;
  en_caso_de_falla?: EnCasoDeFalla;
}
/**
 * Dato del resumen con su evidencia: de dónde sale, qué tan sólido es y en qué segundo.
 *
 * `cita` es la frase de la transcripción que lo respalda, en el idioma original (SOP generado,
 * ADR-023); vacía en un SOP cargado y en la ficha de contexto.
 */
export interface Dato {
  valor?: Valor;
  confianza?: Confianza;
  fuente?: Fuente;
  t?: T;
  cita?: Cita;
  revisado?: Revisado;
}
/**
 * Dato del resumen con su evidencia: de dónde sale, qué tan sólido es y en qué segundo.
 *
 * `cita` es la frase de la transcripción que lo respalda, en el idioma original (SOP generado,
 * ADR-023); vacía en un SOP cargado y en la ficha de contexto.
 */
export interface Dato1 {
  valor?: Valor;
  confianza?: Confianza;
  fuente?: Fuente;
  t?: T;
  cita?: Cita;
  revisado?: Revisado;
}
/**
 * Dato del resumen con su evidencia: de dónde sale, qué tan sólido es y en qué segundo.
 *
 * `cita` es la frase de la transcripción que lo respalda, en el idioma original (SOP generado,
 * ADR-023); vacía en un SOP cargado y en la ficha de contexto.
 */
export interface Dato2 {
  valor?: Valor;
  confianza?: Confianza;
  fuente?: Fuente;
  t?: T;
  cita?: Cita;
  revisado?: Revisado;
}
/**
 * Dato del resumen con su evidencia: de dónde sale, qué tan sólido es y en qué segundo.
 *
 * `cita` es la frase de la transcripción que lo respalda, en el idioma original (SOP generado,
 * ADR-023); vacía en un SOP cargado y en la ficha de contexto.
 */
export interface Dato3 {
  valor?: Valor;
  confianza?: Confianza;
  fuente?: Fuente;
  t?: T;
  cita?: Cita;
  revisado?: Revisado;
}
/**
 * Dato del resumen con su evidencia: de dónde sale, qué tan sólido es y en qué segundo.
 *
 * `cita` es la frase de la transcripción que lo respalda, en el idioma original (SOP generado,
 * ADR-023); vacía en un SOP cargado y en la ficha de contexto.
 */
export interface Dato4 {
  valor?: Valor;
  confianza?: Confianza;
  fuente?: Fuente;
  t?: T;
  cita?: Cita;
  revisado?: Revisado;
}
/**
 * Equipo de operación o rol del SOP.
 */
export interface Elemento {
  nombre: Nombre;
  descripcion?: Descripcion;
}
/**
 * Persona identificada en el video (RF-12, §5.4).
 *
 * `nombre` es el que se dice o "No identificado"; `rol`, el que se dice o se infiere, o `None`.
 * `t` y `cita` salen de la transcripción (regla 4): el segundo y la frase donde aparece. La cita
 * solo va vacía si la persona se identificó por un fotograma (entonces `t` es el del fotograma).
 */
export interface Persona {
  nombre?: Nombre1;
  rol?: Rol;
  participacion: Participacion;
  t: T1;
  cita?: Cita1;
}
/**
 * Punto de riesgo. `cita`, `fuente`, `confianza` y `t` son su evidencia en el SOP generado
 * (ADR-023); un SOP cargado los deja en "", "documento", "alta" y None.
 */
export interface Riesgo {
  descripcion: Descripcion1;
  nivel: Nivel;
  paso?: Paso;
  control?: Control;
  cita?: Cita2;
  fuente?: Fuente1;
  confianza?: Confianza1;
  t?: T2;
  revisado?: Revisado1;
}
/**
 * Qué hacer en caso de falla, con su evidencia como en `Riesgo`.
 */
export interface Falla {
  situacion: Situacion;
  accion: Accion;
  cita?: Cita3;
  fuente?: Fuente2;
  confianza?: Confianza2;
  t?: T3;
  revisado?: Revisado2;
}
/**
 * Paso del SOP. Sin tiempos si el SOP se cargó; con tiempos si se generó desde el video.
 *
 * En el SOP generado (ADR-023), `cita` y `fuente` son la evidencia del paso (la cita de sus
 * pasos del video) y `evidencia`, la de cada elemento de `equipo` y `puntos_validacion`, del
 * tiempo y del responsable. Lo que no tiene evidencia va además en `campos_inferidos`, para que
 * la pantalla lo resalte. Un SOP cargado deja "", "documento" y [].
 *
 * En el editor (RF-26, ADR-025), editar o confirmar un campo lo saca de `campos_inferidos`, y
 * `revisado` dice que una persona revisó el paso: su confianza baja o media deja de resaltarse.
 */
export interface PasoSOP {
  numero: Numero;
  nombre: Nombre2;
  descripcion?: Descripcion2;
  responsable: Responsable;
  equipo?: Equipo;
  puntos_validacion?: PuntosValidacion;
  tiempo_esperado_min?: TiempoEsperadoMin;
  t_inicio?: TInicio;
  t_fin?: TFin;
  confianza?: Confianza3;
  campos_inferidos?: CamposInferidos;
  cita?: Cita4;
  fuente?: Fuente3;
  evidencia?: Evidencia;
  revisado?: Revisado3;
}
/**
 * De dónde sale un dato de un paso del SOP generado (RF-25, ADR-023): `valor` es el dato tal
 * como quedó en el paso (un elemento de `equipo` o de `puntos_validacion`, los minutos o el
 * responsable) y `cita`, la frase de la transcripción que lo respalda, en el idioma original.
 * Con fuente "audio" o "visual" lleva su segundo; "inferido", sin cita ni segundo.
 */
export interface Evidencia1 {
  campo: Campo;
  valor: Valor1;
  cita?: Cita5;
  fuente: Fuente4;
  confianza: Confianza4;
  t?: T4;
}
/**
 * Punto clave (RF-24). En el SOP generado, `t`, `cita`, `fuente` y `confianza` son su
 * evidencia (ADR-023).
 */
export interface PuntoClave {
  texto: Texto;
  t?: T5;
  cita?: Cita6;
  fuente?: Fuente5;
  confianza?: Confianza5;
  revisado?: Revisado4;
}
/**
 * Palabra clave del SOP. En el SOP generado, `t` es el segundo de cada mención en el audio
 * (RF-24), en orden, y `menciones` es cuántas hay; en uno cargado, 0 y `[]`.
 *
 * `termino` va en español; `literal` es la forma en que se dijo en el video (en su idioma y como
 * la transcribió Whisper), con la que se cuentan las menciones (ADR-023). Vacía en un SOP
 * cargado.
 */
export interface PalabraClave {
  termino: Termino;
  categoria: Categoria;
  menciones?: Menciones;
  t?: T6;
  literal?: Literal;
}
