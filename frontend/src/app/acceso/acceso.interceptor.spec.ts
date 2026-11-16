import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { accesoInterceptor } from './acceso.interceptor';
import { AccesoService, EstadoAcceso } from './acceso.service';

const CERRADAS: EstadoAcceso = {
  carga: { abierta: false, sesion: false },
  busqueda: { abierta: false, sesion: false },
};

@Component({ template: '' })
class Vacia {}

describe('accesoInterceptor (un 401 regresa a la clave, §11, ADR-027)', () => {
  let http: HttpTestingController;
  let cliente: HttpClient;
  let router: Router;

  beforeEach(async () => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([
          { path: 'videos/:id/reporte', component: Vacia, data: { vista: 'carga' } },
          { path: 'buscar', component: Vacia, data: { vista: 'busqueda' } },
          { path: 'v/:id', component: Vacia },
          { path: 'acceso', component: Vacia },
        ]),
        provideHttpClient(withInterceptors([accesoInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    cliente = TestBed.inject(HttpClient);
    router = TestBed.inject(Router);
  });

  afterEach(() => http.verify());

  /** Pide `url` y responde con `status`; devuelve el status del error que llegó a quien pidió. */
  function pedir(url: string, status: number): number | null {
    let recibido: number | null = null;
    cliente.get(url).subscribe({ error: (e: { status: number }) => (recibido = e.status) });
    http.expectOne(url).flush({ detail: 'x' }, { status, statusText: 'x' });
    return recibido;
  }

  it('un 401 en una pantalla de carga lleva a /acceso y luego de vuelta a esa URL', async () => {
    await router.navigateByUrl('/videos/7/reporte?t=30');
    const acceso = TestBed.inject(AccesoService);
    acceso.ultimo.set(CERRADAS);
    const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    expect(pedir('/api/videos/7/reporte', 401)).toBe(401); // el error sigue su camino

    expect(navegar).toHaveBeenCalledWith(['/acceso'], {
      queryParams: { vista: 'carga', volver: '/videos/7/reporte?t=30' },
    });
    expect(acceso.ultimo()).toBeNull(); // olvidó el estado: la sesión se cerró
  });

  it('en /buscar pide la clave de búsqueda', async () => {
    await router.navigateByUrl('/buscar');
    const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    pedir('/api/buscar/opciones', 401);
    expect(navegar).toHaveBeenCalledWith(['/acceso'], {
      queryParams: { vista: 'busqueda', volver: '/buscar' },
    });
  });

  it('no redirige en una pantalla sin vista (/v/:id) ni por la clave equivocada de /api/acceso', async () => {
    await router.navigateByUrl('/v/7');
    const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    expect(pedir('/api/videos/7', 401)).toBe(401);

    await router.navigateByUrl('/buscar');
    navegar.mockClear();
    expect(pedir('/api/acceso', 401)).toBe(401);
    expect(navegar).not.toHaveBeenCalled();
  });

  it('otros errores no redirigen', async () => {
    await router.navigateByUrl('/videos/7/reporte');
    const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    expect(pedir('/api/videos/7/reporte', 409)).toBe(409);
    expect(pedir('/api/videos/7/reporte', 403)).toBe(403);
    expect(navegar).not.toHaveBeenCalled();
  });
});
