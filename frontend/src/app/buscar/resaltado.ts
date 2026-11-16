/** La frase de un resultado partida para resaltar la coincidencia con nodos de texto. */
export interface PartesFrase {
  antes: string;
  coincidencia: string;
  despues: string;
}

/**
 * Parte `frase` en lo de antes, la coincidencia y lo de después según `rango` (RF-34).
 *
 * La API corta en Python (`frase[inicio:fin]`, fin exclusivo), que cuenta puntos de código; aquí
 * se corta igual con `Array.from`, no con índices UTF-16, para que un carácter fuera del plano
 * básico (p. ej. un emoji) no corra la marca. Con `recorteInicio`/`recorteFin` lleva "…" del lado
 * en que la frase sigue. Un rango que no cabe en la frase se ignora: la frase va sin marca.
 *
 * La plantilla pinta `{{ antes }}<mark>{{ coincidencia }}</mark>{{ despues }}`: solo texto, nunca
 * `innerHTML` con lo que manda el servidor.
 */
export function partesFrase(
  frase: string,
  rango: readonly unknown[],
  recorteInicio = false,
  recorteFin = false,
): PartesFrase {
  const letras = Array.from(frase);
  const [inicio, fin] = rango;
  const previo = recorteInicio ? '…' : '';
  const sigue = recorteFin ? '…' : '';
  if (
    typeof inicio !== 'number' ||
    typeof fin !== 'number' ||
    !Number.isInteger(inicio) ||
    !Number.isInteger(fin) ||
    inicio < 0 ||
    fin <= inicio ||
    fin > letras.length
  ) {
    return { antes: `${previo}${frase}${sigue}`, coincidencia: '', despues: '' };
  }
  return {
    antes: previo + letras.slice(0, inicio).join(''),
    coincidencia: letras.slice(inicio, fin).join(''),
    despues: letras.slice(fin).join('') + sigue,
  };
}
