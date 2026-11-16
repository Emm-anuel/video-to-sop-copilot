import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { AccesoService, EstadoAcceso } from './acceso.service';

const CERRADAS: EstadoAcceso = {
  carga: { abierta: false, sesion: false },
  busqueda: { abierta: false, sesion: false },
};

describe('AccesoService (§11, ADR-027)', () => {
  let servicio: AccesoService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    servicio = TestBed.inject(AccesoService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('pregunta a GET /acceso una vez y guarda la respuesta hasta olvidar()', () => {
    const vistos: boolean[] = [];
    servicio.permite('carga').subscribe((v) => vistos.push(v));
    http.expectOne('/api/acceso').flush(CERRADAS);
    servicio.permite('busqueda').subscribe((v) => vistos.push(v));
    http.expectNone('/api/acceso');
    expect(vistos).toEqual([false, false]);
    expect(servicio.ultimo()).toEqual(CERRADAS);

    servicio.olvidar();
    expect(servicio.ultimo()).toBeNull();
    servicio.permite('carga').subscribe((v) => vistos.push(v));
    http.expectOne('/api/acceso').flush({ ...CERRADAS, carga: { abierta: false, sesion: true } });
    expect(vistos).toEqual([false, false, true]);
  });

  it('una vista abierta (sin clave) se permite sin sesión', () => {
    let puede: boolean | undefined;
    servicio.permite('busqueda').subscribe((v) => (puede = v));
    http.expectOne('/api/acceso').flush({
      ...CERRADAS,
      busqueda: { abierta: true, sesion: false },
    });
    expect(puede).toBe(true);
  });

  it('si GET /acceso falla, la siguiente consulta vuelve a preguntar', () => {
    servicio.estado().subscribe({ error: () => undefined });
    http.expectOne('/api/acceso').flush(null, { status: 0, statusText: 'Unknown Error' });
    servicio.estado().subscribe();
    http.expectOne('/api/acceso').flush(CERRADAS);
  });

  it('entrar y salir llaman a POST y DELETE /acceso y olvidan el estado', () => {
    servicio.estado().subscribe();
    http.expectOne('/api/acceso').flush(CERRADAS);

    servicio.entrar('carga', 'clave').subscribe();
    const post = http.expectOne((r) => r.url === '/api/acceso' && r.method === 'POST');
    expect(post.request.body).toEqual({ vista: 'carga', clave: 'clave' });
    post.flush(null, { status: 204, statusText: 'No Content' });
    expect(servicio.ultimo()).toBeNull();

    servicio.salir().subscribe();
    const borrar = http.expectOne((r) => r.url === '/api/acceso' && r.method === 'DELETE');
    expect(borrar.request.params.keys()).toEqual([]);
    borrar.flush(null, { status: 204, statusText: 'No Content' });
  });
});
