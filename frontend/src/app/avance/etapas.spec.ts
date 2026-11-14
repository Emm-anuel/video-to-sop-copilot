import { estadoEtapas, etapasDelModo, etiquetaEtapa } from './etapas';

describe('etapasDelModo', () => {
  it('validar sin imágenes: análisis y luego ficha, pasos, emparejamiento y reporte', () => {
    expect(etapasDelModo('validar', false)).toEqual([
      'duracion',
      'audio',
      'transcripcion',
      'contexto',
      'segmentacion',
      'emparejamiento',
      'reporte',
    ]);
  });

  it('"fotogramas" solo aparece con imágenes, entre la transcripción y la ficha', () => {
    expect(etapasDelModo('validar', true)).toEqual([
      'duracion',
      'audio',
      'transcripcion',
      'fotogramas',
      'contexto',
      'segmentacion',
      'emparejamiento',
      'reporte',
    ]);
    expect(etapasDelModo('generar', false)).not.toContain('fotogramas');
    expect(etapasDelModo('generar', true)).toContain('fotogramas');
  });

  it('generar termina con la redacción del SOP', () => {
    expect(etapasDelModo('generar', false)).toEqual([
      'duracion',
      'audio',
      'transcripcion',
      'contexto',
      'segmentacion',
      'sop_pasos',
      'sop_resumen',
      'sop_claves',
    ]);
  });
});

describe('estadoEtapas', () => {
  const lista = etapasDelModo('validar', false);
  const estados = (etapa: string | null, proceso: Parameters<typeof estadoEtapas>[2]) =>
    estadoEtapas(lista, etapa, proceso).map((e) => e.estado);

  it('antes de la etapa: hechas; la actual en curso; después pendientes', () => {
    expect(estados('segmentacion', 'procesando')).toEqual([
      'hecha',
      'hecha',
      'hecha',
      'hecha',
      'en_curso',
      'pendiente',
      'pendiente',
    ]);
  });

  it('en cola sin etapa: todas pendientes; listo: todas hechas', () => {
    expect(new Set(estados(null, 'en_cola'))).toEqual(new Set(['pendiente']));
    expect(new Set(estados('listo', 'listo'))).toEqual(new Set(['hecha']));
  });

  it('con error marca la etapa en que falló', () => {
    expect(estados('audio', 'error')).toEqual([
      'hecha',
      'fallo',
      'pendiente',
      'pendiente',
      'pendiente',
      'pendiente',
      'pendiente',
    ]);
  });

  it('con afinidad baja la ficha quedó hecha y los pasos del video detenidos', () => {
    expect(estados('afinidad', 'afinidad_baja')).toEqual([
      'hecha',
      'hecha',
      'hecha',
      'hecha',
      'detenida',
      'pendiente',
      'pendiente',
    ]);
  });

  it('nombra cada etapa en español con la tabla única', () => {
    expect(estadoEtapas(lista, null, 'en_cola').map((e) => e.nombre)).toEqual([
      'Duración del video',
      'Audio',
      'Transcripción',
      'Ficha de contexto',
      'Pasos del video',
      'Emparejamiento',
      'Reporte',
    ]);
    expect(etiquetaEtapa('sop_resumen')).toBe('Cuadro resumen');
    expect(etiquetaEtapa(null)).toBe('En cola');
    expect(etiquetaEtapa('nueva')).toBe('nueva');
  });
});
