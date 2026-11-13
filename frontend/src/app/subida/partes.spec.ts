import { HttpErrorResponse } from '@angular/common/http';
import {
  esperaReintento,
  megas,
  megasDe,
  offsetDe409,
  partes,
  reintentable,
  siguienteParte,
} from './partes';

const MIB = 1024 * 1024;

describe('partidor', () => {
  it('parte un archivo en partes exactas y una última corta', () => {
    expect(partes(10, 4)).toEqual([
      [0, 4],
      [4, 8],
      [8, 10],
    ]);
    expect(partes(12, 4)).toEqual([
      [0, 4],
      [4, 8],
      [8, 12],
    ]);
  });

  it('un archivo vacío no tiene partes y uno chico es una sola', () => {
    expect(partes(0, 4)).toEqual([]);
    expect(partes(3, 16 * MIB)).toEqual([[0, 3]]);
  });

  it('1 GB en partes de 16 MB son 64', () => {
    expect(partes(1024 * MIB, 16 * MIB)).toHaveLength(64);
  });

  it('sigue desde un offset en medio de una parte (reanudación)', () => {
    expect(siguienteParte(6, 10, 4)).toEqual([6, 10]);
    expect(siguienteParte(5, 20, 4)).toEqual([5, 9]);
    expect(siguienteParte(10, 10, 4)).toEqual([10, 10]);
  });

  it('rechaza un tamaño de parte no positivo', () => {
    expect(() => siguienteParte(0, 10, 0)).toThrow(RangeError);
  });
});

describe('reintentos', () => {
  it('espera 1, 2 y 4 s', () => {
    expect([1, 2, 3].map(esperaReintento)).toEqual([1000, 2000, 4000]);
  });

  it('reintenta sin conexión, 408, 429 y 5xx; no 404, 409, 413 ni 415', () => {
    const con = (status: number) => new HttpErrorResponse({ status });
    expect([0, 408, 429, 500, 503].map((s) => reintentable(con(s)))).toEqual([
      true,
      true,
      true,
      true,
      true,
    ]);
    expect([404, 409, 413, 415, 422].map((s) => reintentable(con(s)))).toEqual([
      false,
      false,
      false,
      false,
      false,
    ]);
    expect(reintentable(new Error('x'))).toBe(false);
  });

  it('lee el offset correcto de un 409', () => {
    const conflicto = new HttpErrorResponse({
      status: 409,
      error: { detail: { mensaje: 'se esperaba…', offset: 4096, tamano: 9000 } },
    });
    expect(offsetDe409(conflicto)).toBe(4096);
    expect(offsetDe409(new HttpErrorResponse({ status: 409, error: { detail: 'otro' } }))).toBe(
      null,
    );
    expect(offsetDe409(new HttpErrorResponse({ status: 500 }))).toBe(null);
  });
});

describe('megas', () => {
  it('muestra MB con un decimal', () => {
    expect(megas(0)).toBe('0.0');
    expect(megas(48 * MIB)).toBe('48.0');
    expect(megasDe(16 * MIB, 210.3 * MIB)).toBe('16.0 de 210.3 MB');
  });
});
