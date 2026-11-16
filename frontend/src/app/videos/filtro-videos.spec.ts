import { VideoResumen } from '../api/video-resumen';
import { SIN_FILTROS, destino, opcionesSop, pasaFiltros } from './filtro-videos';

const base: VideoResumen = {
  id: 1,
  titulo: 'Limpieza del filtro de agua',
  creado: '2026-11-14T18:00:00Z',
  modo: 'validar',
  proceso: 'listo',
  sop: { id: 3, codigo: 'SOP-0003', titulo: 'Mantenimiento de la válvula' },
};

describe('filtro de videos', () => {
  it('busca sin acentos ni mayúsculas en el título y en el SOP', () => {
    expect(pasaFiltros(base, { ...SIN_FILTROS, texto: 'FILTRO de agua' })).toBe(true);
    expect(pasaFiltros(base, { ...SIN_FILTROS, texto: 'valvula' })).toBe(true);
    expect(pasaFiltros(base, { ...SIN_FILTROS, texto: 'sop-0003' })).toBe(true);
    expect(pasaFiltros(base, { ...SIN_FILTROS, texto: 'bomba' })).toBe(false);
    expect(pasaFiltros({ ...base, sop: null }, { ...SIN_FILTROS, texto: 'valvula' })).toBe(false);
  });

  it('filtra por modo, por estado (en cola y procesando juntos) y por SOP', () => {
    expect(pasaFiltros(base, { ...SIN_FILTROS, modo: 'generar' })).toBe(false);
    expect(pasaFiltros(base, { ...SIN_FILTROS, modo: 'validar' })).toBe(true);
    for (const proceso of ['en_cola', 'procesando'] as const) {
      expect(pasaFiltros({ ...base, proceso }, { ...SIN_FILTROS, estado: 'en_proceso' })).toBe(
        true,
      );
    }
    expect(pasaFiltros(base, { ...SIN_FILTROS, estado: 'en_proceso' })).toBe(false);
    expect(pasaFiltros(base, { ...SIN_FILTROS, estado: 'listo' })).toBe(true);
    expect(pasaFiltros(base, { ...SIN_FILTROS, sop: 3 })).toBe(true);
    expect(pasaFiltros(base, { ...SIN_FILTROS, sop: 4 })).toBe(false);
  });

  it('las opciones de SOP salen de la lista, sin repetir y por código', () => {
    const lista: VideoResumen[] = [
      { ...base, id: 1, sop: { id: 9, codigo: 'SOP-0009', titulo: null } },
      base,
      { ...base, id: 3 },
      { ...base, id: 4, sop: null },
    ];
    expect(opcionesSop(lista)).toEqual([
      { id: 3, etiqueta: 'SOP-0003 · Mantenimiento de la válvula' },
      { id: 9, etiqueta: 'SOP-0009' },
    ]);
  });

  it('cada estado lleva a su pantalla', () => {
    expect(destino(base)).toEqual({ ruta: ['/videos', 1, 'reporte'], etiqueta: 'Ver el reporte' });
    expect(destino({ ...base, modo: 'generar' })).toEqual({
      ruta: ['/videos', 1, 'sop'],
      etiqueta: 'Ver el SOP',
    });
    expect(destino({ ...base, proceso: 'afinidad_baja' })).toEqual({
      ruta: ['/videos', 1, 'reporte'],
      etiqueta: 'Ver el aviso',
    });
    expect(destino({ ...base, proceso: 'error' }).ruta).toEqual(['/videos', 1, 'procesando']);
    expect(destino({ ...base, proceso: 'en_cola' }).ruta).toEqual(['/videos', 1, 'procesando']);
    expect(destino({ ...base, proceso: 'procesando' }).etiqueta).toBe('Ver el avance');
  });
});
