import ejemplo from '../../../../tests/fixtures/sop_generado_ejemplo.json';
import { SOP } from '../api/sop';
import {
  Borrador,
  aBorrador,
  aSop,
  agregarPaso,
  confirmarCampo,
  confirmarDato,
  confirmarPaso,
  duracionTotal,
  editarDato,
  editarPaso,
  elementos,
  huella,
  leyenda,
  leyendaPaso,
  mover,
  quitar,
  restaurar,
  unirConSiguiente,
} from './edicion';

function sop(): SOP {
  return structuredClone(ejemplo) as unknown as SOP;
}

function unir(b: Borrador, i: number, responsable?: string): Borrador {
  const r = unirConSiguiente(b, i, responsable);
  if (!r.ok) {
    throw new Error('se esperaba unir sin preguntar');
  }
  return r.borrador;
}

describe('edición del SOP', () => {
  it('ida y vuelta: aSop(aBorrador(sop)) es el mismo SOP', () => {
    const original = sop();
    expect(huella(aSop(aBorrador(original)))).toBe(huella(original));
    expect(aSop(aBorrador(original)).resumen?.duracion_total_min).toBe(2.05);
  });

  describe('unir con el siguiente paso', () => {
    function conEvidencia(): SOP {
      const s = sop();
      s.pasos[0].evidencia = [
        {
          campo: 'equipo',
          valor: 'Guantes de nitrilo',
          cita: 'gloves',
          fuente: 'audio',
          confianza: 'alta',
          t: 21,
        },
        {
          campo: 'tiempo_esperado_min',
          valor: '0.19',
          cita: '',
          fuente: 'inferido',
          confianza: 'media',
          t: null,
        },
      ];
      s.pasos[1].evidencia = [
        {
          campo: 'equipo',
          valor: 'Llave de paso',
          cita: 'the valve',
          fuente: 'audio',
          confianza: 'alta',
          t: 34,
        },
      ];
      s.pasos[1].equipo = ['Llave de paso', 'guantes de nitrilo'];
      s.pasos[1].campos_inferidos = ['tiempo_esperado_min'];
      return s;
    }

    it('junta los dos pasos con las reglas de RF-26', () => {
      const b = unir(aBorrador(conEvidencia()), 0);
      const [p1, p2] = ejemplo.pasos;
      expect(b.pasos).toHaveLength(ejemplo.pasos.length - 1);
      const u = b.pasos[0];
      expect(u.nombre).toBe(p1.nombre);
      expect(u.descripcion).toBe(`${p1.descripcion} ${p2.descripcion}`);
      // Unión sin duplicados (sin distinguir mayúsculas).
      expect(u.equipo).toEqual(['Guantes de nitrilo', 'Lentes de seguridad', 'Llave de paso']);
      expect(u.puntos_validacion).toEqual([...p1.puntos_validacion, ...p2.puntos_validacion]);
      expect(u.tiempo_esperado_min).toBe(0.53);
      expect([u.t_inicio, u.t_fin]).toEqual([p1.t_inicio, p2.t_fin]);
      expect(u.confianza).toBe('media'); // la menor de media y alta
      expect(u.cita).toBe(p1.cita);
      expect(u.evidencia.map((e) => e.valor)).toEqual([
        'Guantes de nitrilo',
        '0.19',
        'Llave de paso',
      ]);
      expect(u.campos_inferidos).toEqual(['puntos_validacion', 'tiempo_esperado_min']);
      expect(u.responsable).toBe(p1.responsable);
    });

    it('los pasos de después se renumeran y los riesgos siguen a su paso', () => {
      // Riesgos en los pasos 3 y 5: al unir 2 y 3, apuntan a 2 y 4.
      const unido = aSop(unir(aBorrador(sop()), 1));
      expect(unido.pasos.map((p) => p.numero)).toEqual([1, 2, 3, 4, 5]);
      expect(unido.resumen?.riesgos?.map((r) => r.paso)).toEqual([2, 2, 4]);
    });

    it('si los responsables difieren, pregunta y usa el elegido', () => {
      const s = sop();
      s.pasos[1].responsable = 'Supervisor de turno';
      s.pasos[0].campos_inferidos = ['responsable'];
      s.pasos[0].evidencia = [
        {
          campo: 'responsable',
          valor: s.pasos[0].responsable,
          cita: '',
          fuente: 'inferido',
          confianza: 'baja',
          t: null,
        },
      ];
      s.pasos[1].evidencia = [
        {
          campo: 'responsable',
          valor: 'Supervisor de turno',
          cita: 'the supervisor',
          fuente: 'audio',
          confianza: 'alta',
          t: 40,
        },
      ];
      const b = aBorrador(s);
      const r = unirConSiguiente(b, 0);
      expect(r).toEqual({
        ok: false,
        responsables: [ejemplo.pasos[0].responsable, 'Supervisor de turno'],
      });

      const u = unir(b, 0, 'Supervisor de turno').pasos[0];
      expect(u.responsable).toBe('Supervisor de turno');
      expect(u.campos_inferidos).not.toContain('responsable');
      expect(u.evidencia.filter((e) => e.campo === 'responsable').map((e) => e.valor)).toEqual([
        'Supervisor de turno',
      ]);
    });

    it('con los pasos reordenados, el tramo es el mínimo y el máximo', () => {
      const b = mover(aBorrador(sop()), 3, 0); // el 4 primero, luego el 1
      const u = unir(b, 0).pasos[0];
      expect([u.t_inicio, u.t_fin]).toEqual([ejemplo.pasos[0].t_inicio, ejemplo.pasos[3].t_fin]);
      expect(u.nombre).toBe(ejemplo.pasos[3].nombre);
    });

    it('queda revisado solo si los dos lo estaban; un tiempo vacío no suma', () => {
      const s = sop();
      s.pasos[0].revisado = true;
      s.pasos[1].tiempo_esperado_min = null;
      const u = unir(aBorrador(s), 0).pasos[0];
      expect(u.revisado).toBe(false);
      expect(u.tiempo_esperado_min).toBe(ejemplo.pasos[0].tiempo_esperado_min);
    });

    it('el último paso no tiene siguiente', () => {
      const b = aBorrador(sop());
      expect(unir(b, b.pasos.length - 1)).toBe(b);
    });
  });

  it('mover cambia el orden y aSop renumera 1..n', () => {
    const b = mover(aBorrador(sop()), 0, 2);
    const s = aSop(b);
    expect(s.pasos.map((p) => p.nombre)).toEqual([
      ejemplo.pasos[1].nombre,
      ejemplo.pasos[2].nombre,
      ejemplo.pasos[0].nombre,
      ...ejemplo.pasos.slice(3).map((p) => p.nombre),
    ]);
    expect(s.pasos.map((p) => p.numero)).toEqual([1, 2, 3, 4, 5, 6]);
    // El riesgo del paso 3 (liberar la presión) sigue a su paso, que ahora es el 2.
    expect(s.resumen?.riesgos?.map((r) => r.paso)).toEqual([2, 2, 5]);
    expect(mover(b, 0, 99)).toBe(b);
  });

  it('quitar y deshacer: el paso vuelve a su lugar con sus riesgos', () => {
    const b = aBorrador(sop());
    const r = quitar(b, 2)!;
    const s = aSop(r.borrador);
    expect(s.pasos).toHaveLength(5);
    expect(s.resumen?.riesgos?.map((x) => x.paso)).toEqual([null, null, 4]);
    expect(s.resumen?.duracion_total_min).toBe(1.75); // recalculada sin el paso quitado
    expect(huella(aSop(restaurar(r.borrador, r.quitado)))).toBe(huella(aSop(b)));
  });

  it('no se quita el único paso', () => {
    let b = aBorrador(sop());
    while (b.pasos.length > 1) {
      b = quitar(b, 0)!.borrador;
    }
    expect(quitar(b, 0)).toBeNull();
  });

  it('un paso agregado va vacío, sin evidencia y revisado; la duración total queda sin suma parcial', () => {
    const b = agregarPaso(aBorrador(sop()), 0);
    expect(b.pasos[1]).toMatchObject({
      nombre: '',
      fuente: 'inferido',
      confianza: 'baja',
      revisado: true,
    });
    expect(new Set(b.pasos.map((p) => p.clave)).size).toBe(7);
    expect(aSop(b).resumen?.duracion_total_min).toBeNull();
  });

  describe('lo inferido (RF-25, ADR-025)', () => {
    it('editar un campo inferido lo saca de campos_inferidos y marca el paso revisado', () => {
      const b = aBorrador(sop());
      expect(b.pasos[0].campos_inferidos).toEqual(['puntos_validacion']);
      const e = editarPaso(b, 0, 'puntos_validacion', ['EPP completo']);
      expect(e.pasos[0].campos_inferidos).toEqual([]);
      expect(e.pasos[0].revisado).toBe(true);
      expect(leyendaPaso(e.pasos[0])).toBeNull(); // su confianza media ya no se resalta
    });

    it('quitar un elemento borra su evidencia; cambiar el tiempo a mano borra la del tiempo', () => {
      const s = sop();
      s.pasos[0].evidencia = [
        {
          campo: 'equipo',
          valor: 'Guantes de nitrilo',
          cita: 'gloves',
          fuente: 'audio',
          confianza: 'alta',
          t: 21,
        },
        {
          campo: 'equipo',
          valor: 'Lentes de seguridad',
          cita: 'glasses',
          fuente: 'audio',
          confianza: 'alta',
          t: 22,
        },
        {
          campo: 'tiempo_esperado_min',
          valor: '0.19',
          cita: '',
          fuente: 'inferido',
          confianza: 'media',
          t: null,
        },
      ];
      let b = editarPaso(aBorrador(s), 0, 'equipo', ['Lentes de seguridad']);
      expect(b.pasos[0].evidencia.map((e) => e.valor)).toEqual(['Lentes de seguridad', '0.19']);
      b = editarPaso(b, 0, 'tiempo_esperado_min', 1);
      expect(b.pasos[0].evidencia.map((e) => e.valor)).toEqual(['Lentes de seguridad']);
    });

    it('confirmar un campo o el paso, sin cambiar el valor', () => {
      const b = aBorrador(sop());
      expect(confirmarCampo(b, 0, 'puntos_validacion').pasos[0].campos_inferidos).toEqual([]);
      expect(confirmarCampo(b, 0, 'puntos_validacion').pasos[0].revisado).toBe(false);
      const p = confirmarPaso(b, 0).pasos[0];
      expect([p.campos_inferidos, p.revisado]).toEqual([[], true]);
      expect(p.puntos_validacion).toEqual(ejemplo.pasos[0].puntos_validacion);
    });

    it('un dato del resumen editado o confirmado queda revisado y deja de resaltarse', () => {
      const b = aBorrador(sop());
      expect(leyenda(b.resumen.alcance)).toBe('Inferido');
      expect(leyenda(confirmarDato(b, 'alcance').resumen.alcance)).toBeNull();
      const e = editarDato(b, 'alcance', 'Toda la línea');
      expect(e.resumen.alcance).toMatchObject({
        valor: 'Toda la línea',
        revisado: true,
        fuente: 'inferido',
      });
      expect(editarDato(b, 'lugar', '  ').resumen.lugar.valor).toBeNull();
      expect(aSop(e).resumen?.alcance?.revisado).toBe(true);
    });

    it('leyendas en texto: inferido, confianza baja o media', () => {
      expect(leyenda({ fuente: 'audio', confianza: 'media' })).toBe('Confianza media');
      expect(leyenda({ fuente: 'audio', confianza: 'alta' })).toBeNull();
      expect(leyenda({ fuente: 'inferido', confianza: 'baja', revisado: true })).toBeNull();
    });
  });

  it('con duración narrada por el operador, se conserva aunque se quiten pasos (ADR-021)', () => {
    const b = quitar(aBorrador(sop(), 3.5), 0)!.borrador;
    expect(aSop(b).resumen?.duracion_total_min).toBe(3.5);
    expect(duracionTotal([{ tiempo_esperado_min: null }], null, 3.5)).toBe(3.5);
  });

  it('duración total: suma, null con una suma parcial y la de antes si no hay tiempos', () => {
    expect(duracionTotal([{ tiempo_esperado_min: 0.1 }, { tiempo_esperado_min: 0.2 }], 9)).toBe(
      0.3,
    );
    expect(
      duracionTotal([{ tiempo_esperado_min: 0.1 }, { tiempo_esperado_min: null }], 9),
    ).toBeNull();
    expect(duracionTotal([{ tiempo_esperado_min: null }], 30)).toBe(30);
  });

  it('elementos desde chips: conserva descripciones y no repite', () => {
    const antes = [{ nombre: 'Llave', descripcion: 'de paso' }];
    expect(elementos(antes, ['Llave', 'Cubeta', 'llave'])).toEqual([
      { nombre: 'Llave', descripcion: 'de paso' },
      { nombre: 'Cubeta', descripcion: '' },
    ]);
  });
});
