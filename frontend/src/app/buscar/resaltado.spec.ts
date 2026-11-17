import { partesFrase } from './resaltado';

describe('partesFrase', () => {
  it('corta la coincidencia con acentos como la corta Python', () => {
    const frase = 'luego abre la válvula de alivio';
    // 'válvula' empieza en 14 y tiene 7 caracteres: frase[14:21] en Python.
    expect(partesFrase(frase, [14, 21])).toEqual({
      antes: 'luego abre la ',
      coincidencia: 'válvula',
      despues: ' de alivio',
    });
  });

  it('cuenta puntos de código: un emoji antes no corre la marca', () => {
    const frase = '🙂 cierra la válvula';
    // En Python el emoji es un solo carácter: 'válvula' es frase[12:19].
    expect(partesFrase(frase, [12, 19]).coincidencia).toBe('válvula');
  });

  it('pone "…" del lado en que la frase sigue', () => {
    const partes = partesFrase('abre la válvula', [8, 15], true, true);
    expect(partes.antes).toBe('…abre la ');
    expect(partes.despues).toBe('…');
  });

  it('con un rango que no cabe, la frase va entera y sin marca', () => {
    for (const rango of [
      [3, 99],
      [5, 5],
      [-1, 2],
      ['a', 3],
      [1.5, 3],
    ]) {
      expect(partesFrase('abre la válvula', rango, true)).toEqual({
        antes: '…abre la válvula',
        coincidencia: '',
        despues: '',
      });
    }
  });
});
