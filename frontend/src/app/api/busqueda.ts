/* Generado desde docs/contrato/busqueda.schema.json con `npm run tipos:busqueda`. No editar a mano. */

export type Consulta = string;
export type ConsultaNormalizada = string;
export type Total = number;
export type Id = number;
export type Titulo = string;
export type Id1 = number;
export type Codigo = string;
export type Titulo1 = string | null;
export type TInicio = number;
export type TFin = number;
export type Miniatura = string | null;
export type Frase = string;
/**
 * @minItems 2
 * @maxItems 2
 */
export type Rango = [unknown, unknown];
export type RecorteInicio = boolean;
export type RecorteFin = boolean;
export type Coincidencias = number;
export type Resultados = ResultadoBusqueda[];
export type Milisegundos = number;

/**
 * Respuesta de `POST /buscar`. `consulta_normalizada`: las palabras como se buscaron
 * (`texto.forma_busqueda`). `total`: resultados ya unidos (RF-35), antes del tope
 * `BUSQUEDA_MAX_RESULTADOS`; `resultados` trae a lo más ese tope, por video (el más reciente
 * primero) y dentro, por segundo. `milisegundos`: lo que tardó del lado del servidor.
 */
export interface RespuestaBusqueda {
  consulta: Consulta;
  consulta_normalizada: ConsultaNormalizada;
  total: Total;
  resultados: Resultados;
  milisegundos: Milisegundos;
}
/**
 * Una coincidencia (RF-34) o una cadena de coincidencias del mismo video unidas (RF-35).
 *
 * `t_inicio` es el de la primera palabra de la coincidencia y `t_fin` el de la última, tal cual
 * de Whisper (RNF-03). `miniatura` es la ruta de `GET /videos/{id}/thumb?t=`, o None si el
 * video no tiene imagen. `frase`: hasta 8 palabras originales antes y después, sin HTML;
 * `frase[rango[0]:rango[1]]` es la coincidencia (fin exclusivo, palabras originales completas
 * sin los signos de puntuación del inicio de la primera ni del final de la última).
 * `recorte_inicio` / `recorte_fin`: hay más palabras antes o después de la frase. Unida,
 * conserva todo de la primera coincidencia de la cadena y `coincidencias` dice cuántas se
 * unieron (1 si va sola).
 */
export interface ResultadoBusqueda {
  video: VideoDeBusqueda;
  sop?: SopDeVideo | null;
  t_inicio: TInicio;
  t_fin: TFin;
  miniatura?: Miniatura;
  frase: Frase;
  rango: Rango;
  recorte_inicio?: RecorteInicio;
  recorte_fin?: RecorteFin;
  coincidencias?: Coincidencias;
}
export interface VideoDeBusqueda {
  id: Id;
  titulo: Titulo;
}
/**
 * El SOP de un video en la lista: el de referencia (validar) o el generado (generar).
 * `titulo` es None mientras el SOP se convierte o se redacta.
 */
export interface SopDeVideo {
  id: Id1;
  codigo: Codigo;
  titulo?: Titulo1;
}
