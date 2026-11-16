import { TestBed } from '@angular/core/testing';
import { RespuestaBusqueda } from '../api/busqueda';
import {
  CLAVE_HISTORIAL,
  HistorialBusqueda,
  INTERRUMPIDA,
  MAX_TURNOS,
  SIN_FILTROS,
} from './historial.service';

const RESPUESTA: RespuestaBusqueda = {
  consulta: 'valvula',
  consulta_normalizada: 'valvula',
  total: 0,
  resultados: [],
  milisegundos: 2,
};

/** Una instancia nueva del servicio, como al recargar la pestaña. */
function nuevo(): HistorialBusqueda {
  TestBed.resetTestingModule();
  return TestBed.inject(HistorialBusqueda);
}

describe('HistorialBusqueda', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it('guarda los turnos en sessionStorage y los recupera en otra instancia', () => {
    const historial = nuevo();
    const turno = historial.agregar('válvula', SIN_FILTROS);
    historial.actualizar(turno.clave, { estado: 'listo', respuesta: RESPUESTA });
    historial.elegir(turno.clave);

    const otro = nuevo();
    expect(otro.turnos()).toEqual([
      expect.objectContaining({ consulta: 'válvula', estado: 'listo', respuesta: RESPUESTA }),
    ]);
    expect(otro.elegido()).toBe(turno.clave);
    // Las claves siguen sin repetirse.
    expect(otro.agregar('bomba', SIN_FILTROS).clave).toBeGreaterThan(turno.clave);
  });

  it('una búsqueda que seguía en curso al recargar queda como error para reintentarla', () => {
    nuevo().agregar('válvula', SIN_FILTROS);
    expect(nuevo().turnos()[0]).toEqual(
      expect.objectContaining({ estado: 'error', error: INTERRUMPIDA }),
    );
  });

  it('conserva solo los últimos turnos', () => {
    const historial = nuevo();
    for (let i = 0; i < MAX_TURNOS + 5; i++) {
      historial.agregar(`consulta ${i}`, SIN_FILTROS);
    }
    expect(historial.turnos()).toHaveLength(MAX_TURNOS);
    expect(historial.turnos()[0].consulta).toBe('consulta 5');
  });

  it('sin espacio guarda sin respuestas; si el almacenamiento falla, sigue en memoria', () => {
    const historial = nuevo();
    const original = Storage.prototype.setItem;
    const guardar = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
      this: Storage,
      clave: string,
      valor: string,
    ) {
      if (valor.includes('"resultados"')) {
        throw new DOMException('lleno', 'QuotaExceededError');
      }
      original.call(this, clave, valor);
    });
    const turno = historial.agregar('válvula', SIN_FILTROS);
    historial.actualizar(turno.clave, { estado: 'listo', respuesta: RESPUESTA });

    expect(historial.turnos()[0].respuesta).toEqual(RESPUESTA);
    const guardado = JSON.parse(sessionStorage.getItem(CLAVE_HISTORIAL)!);
    expect(guardado.turnos[0]).toEqual(
      expect.objectContaining({ estado: 'listo', respuesta: null }),
    );

    guardar.mockImplementation(() => {
      throw new Error('bloqueado');
    });
    expect(() => historial.agregar('bomba', SIN_FILTROS)).not.toThrow();
    expect(historial.turnos()).toHaveLength(2);

    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqueado');
    });
    expect(nuevo().turnos()).toEqual([]);
  });

  it('limpiar borra la conversación, también la guardada', () => {
    const historial = nuevo();
    historial.agregar('válvula', SIN_FILTROS);
    historial.limpiar();
    expect(historial.turnos()).toEqual([]);
    expect(nuevo().turnos()).toEqual([]);
  });
});
