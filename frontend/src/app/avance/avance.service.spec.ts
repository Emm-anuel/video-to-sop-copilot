import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, inject } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { EstadoVideo, Proceso } from '../api/tipos';
import { AvanceVideo, ESPERA_MAXIMA_MS, INTERVALO_MS, espera } from './avance.service';
import { ERROR_REINICIO } from './etapas';

const ESTADO = '/api/videos/7';

function estado(proceso: Proceso, extra: Partial<EstadoVideo> = {}): EstadoVideo {
  return {
    id: 7,
    titulo: 'video_a',
    modo: 'validar',
    proceso,
    etapa: proceso === 'listo' ? 'listo' : 'transcripcion',
    progreso: proceso === 'listo' ? 100 : 30,
    duracion: null,
    idioma: 'es',
    error: null,
    creado: '2026-11-12T10:00:00Z',
    analizar_imagenes: false,
    ...extra,
  };
}

/** Un componente que provee el servicio, como Procesando, el reporte y el SOP generado. */
@Component({ selector: 'app-anfitrion', template: '', providers: [AvanceVideo] })
class Anfitrion {
  readonly avance = inject(AvanceVideo);
}

describe('espera', () => {
  it('crece al doble en cada intento seguido, hasta el tope', () => {
    expect([1, 2, 3, 4].map(espera)).toEqual([1500, 3000, 6000, 12_000]);
    expect(espera(10)).toBe(ESPERA_MAXIMA_MS);
  });
});

describe('AvanceVideo', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  function crear() {
    const fixture = TestBed.createComponent(Anfitrion);
    const avance = fixture.componentInstance.avance;
    avance.seguir(7);
    return { fixture, avance };
  }

  function sinConexion(): void {
    http.expectOne(ESTADO).error(new ProgressEvent('error'), { status: 0, statusText: '' });
  }

  it('consulta cada 1.5 s mientras el video está en proceso', () => {
    const { avance } = crear();
    http.expectOne(ESTADO).flush(estado('en_cola', { etapa: null, progreso: 0 }));
    expect(avance.etiqueta()).toBe('En cola');
    vi.advanceTimersByTime(INTERVALO_MS - 1);
    http.expectNone(ESTADO);
    vi.advanceTimersByTime(1);
    http.expectOne(ESTADO).flush(estado('procesando'));
    expect(avance.etiqueta()).toBe('Transcripción');
    vi.advanceTimersByTime(INTERVALO_MS);
    http.expectOne(ESTADO).flush(estado('listo'));
  });

  for (const proceso of ['listo', 'error', 'afinidad_baja'] as const) {
    it(`se detiene con "${proceso}" y lo avisa una sola vez`, () => {
      const { avance } = crear();
      const terminados: Proceso[] = [];
      avance.terminado.subscribe((e) => terminados.push(e.proceso));
      http.expectOne(ESTADO).flush(estado('procesando'));
      vi.advanceTimersByTime(INTERVALO_MS);
      http.expectOne(ESTADO).flush(estado(proceso, { etapa: 'afinidad', progreso: 50 }));
      expect(avance.final()).toBe(true);
      vi.advanceTimersByTime(INTERVALO_MS * 20);
      http.expectNone(ESTADO);
      expect(terminados).toEqual([proceso]);
    });
  }

  it('afinidad baja (bug de reporte.ts): no sigue consultando aunque pase mucho tiempo', () => {
    crear();
    http.expectOne(ESTADO).flush(estado('afinidad_baja', { etapa: 'afinidad', progreso: 50 }));
    vi.advanceTimersByTime(10 * 60_000);
    http.expectNone(ESTADO);
  });

  it('se detiene al destruirse el componente que lo provee', () => {
    const { fixture } = crear();
    http.expectOne(ESTADO).flush(estado('procesando'));
    fixture.destroy();
    vi.advanceTimersByTime(INTERVALO_MS * 10);
    http.expectNone(ESTADO);
  });

  it('se detiene con detener() y vuelve a empezar con seguir()', () => {
    const { avance } = crear();
    http.expectOne(ESTADO).flush(estado('procesando', { progreso: 60 }));
    avance.detener();
    vi.advanceTimersByTime(INTERVALO_MS * 5);
    http.expectNone(ESTADO);
    avance.seguir(7);
    expect(avance.progreso()).toBe(0); // un seguimiento nuevo (p. ej. tras reprocesar) arranca de cero
    http.expectOne(ESTADO).flush(estado('procesando', { progreso: 40 }));
    expect(avance.progreso()).toBe(40);
    avance.detener();
  });

  it('el porcentaje nunca retrocede y llega a 100 con "listo"', () => {
    const { avance } = crear();
    const vistos: number[] = [];
    for (const progreso of [12, 40, 35, 40, 55]) {
      http.expectOne(ESTADO).flush(estado('procesando', { progreso }));
      vistos.push(avance.progreso());
      vi.advanceTimersByTime(INTERVALO_MS);
    }
    expect(vistos).toEqual([12, 40, 40, 40, 55]);
    http.expectOne(ESTADO).flush(estado('listo', { progreso: 0 }));
    expect(avance.progreso()).toBe(100);
  });

  it('sin red reintenta con espera creciente y vuelve al ritmo normal al responder', () => {
    const { avance } = crear();
    http.expectOne(ESTADO).flush(estado('procesando'));
    vi.advanceTimersByTime(INTERVALO_MS);

    sinConexion();
    expect(avance.reintento()).toMatchObject({ intento: 1, esperaMs: 1500 });
    expect(avance.reintento()!.mensaje).toContain('No hay conexión con la API');
    vi.advanceTimersByTime(1499);
    http.expectNone(ESTADO);
    vi.advanceTimersByTime(1);
    sinConexion();
    expect(avance.reintento()).toMatchObject({ intento: 2, esperaMs: 3000 });
    vi.advanceTimersByTime(2999);
    http.expectNone(ESTADO);
    vi.advanceTimersByTime(1);
    http.expectOne(ESTADO).flush('Bad Gateway', { status: 502, statusText: 'Bad Gateway' });
    expect(avance.reintento()).toMatchObject({ intento: 3, esperaMs: 6000 });
    vi.advanceTimersByTime(6000);

    http.expectOne(ESTADO).flush(estado('procesando', { progreso: 33 }));
    expect(avance.reintento()).toBeNull();
    expect(avance.errorConsulta()).toBeNull();
    vi.advanceTimersByTime(INTERVALO_MS);
    // Tras responder, la cuenta de intentos vuelve a empezar.
    sinConexion();
    expect(avance.reintento()).toMatchObject({ intento: 1, esperaMs: 1500 });
    avance.detener();
  });

  it('si la API se reinició a la mitad, al volver dice "interrumpido por reinicio"', () => {
    const { avance } = crear();
    http.expectOne(ESTADO).flush(estado('procesando'));
    vi.advanceTimersByTime(INTERVALO_MS);
    sinConexion();
    expect(avance.interrumpido()).toBe(false);
    vi.advanceTimersByTime(1500);
    http.expectOne(ESTADO).flush(estado('error', { error: ERROR_REINICIO }));
    expect(avance.interrumpido()).toBe(true);
    expect(avance.reintento()).toBeNull();
    vi.advanceTimersByTime(INTERVALO_MS * 5);
    http.expectNone(ESTADO);
  });

  it('un 404 no se reintenta: la consulta se detiene con el mensaje', () => {
    const { avance } = crear();
    http
      .expectOne(ESTADO)
      .flush({ detail: 'video no encontrado' }, { status: 404, statusText: 'Not Found' });
    expect(avance.errorConsulta()).toBe('No encontrado: video no encontrado.');
    vi.advanceTimersByTime(INTERVALO_MS * 10);
    http.expectNone(ESTADO);
  });

  it('cuenta el tiempo mientras procesa y lo congela al terminar', () => {
    const { avance } = crear();
    http.expectOne(ESTADO).flush(estado('en_cola'));
    expect(avance.segundos()).toBe(0);
    vi.advanceTimersByTime(INTERVALO_MS);
    http.expectOne(ESTADO).flush(estado('procesando'));
    vi.advanceTimersByTime(INTERVALO_MS);
    http.expectOne(ESTADO).flush(estado('error', { error: 'x' }));
    expect(avance.segundos()).toBe(3);
    vi.advanceTimersByTime(10_000);
    expect(avance.segundos()).toBe(3);
  });

  it('si ya estaba listo al abrir, no hay tiempo que medir', () => {
    const { avance } = crear();
    http.expectOne(ESTADO).flush(estado('listo'));
    expect(avance.segundos()).toBeNull();
  });
});
