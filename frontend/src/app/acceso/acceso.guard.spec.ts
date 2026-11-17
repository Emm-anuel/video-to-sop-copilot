import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import {
  ActivatedRouteSnapshot,
  Router,
  RouterStateSnapshot,
  UrlTree,
  provideRouter,
} from '@angular/router';
import { Observable, isObservable } from 'rxjs';
import { requiereVista } from './acceso.guard';
import { EstadoAcceso } from './acceso.service';

const CERRADAS: EstadoAcceso = {
  carga: { abierta: false, sesion: false },
  busqueda: { abierta: false, sesion: false },
};

/** Corre el guard para una ruta con `data` y la URL a la que se iba. */
function revisar(data: Record<string, unknown>, url: string): (boolean | UrlTree)[] {
  const ruta = { data } as unknown as ActivatedRouteSnapshot;
  const estado = { url } as RouterStateSnapshot;
  const salida = TestBed.runInInjectionContext(() => requiereVista(ruta, estado));
  const valores: (boolean | UrlTree)[] = [];
  expect(isObservable(salida)).toBe(true);
  (salida as Observable<boolean | UrlTree>).subscribe((v) => valores.push(v));
  return valores;
}

describe('requiereVista (guard de §11, ADR-027)', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('sin data.vista deja pasar sin preguntar', () => {
    expect(revisar({}, '/v/3')).toEqual([true]);
    http.expectNone('/api/acceso');
  });

  it('con la vista abierta (clave vacía) no pide nada', () => {
    const valores = revisar({ vista: 'carga' }, '/nuevo');
    http.expectOne('/api/acceso').flush({ ...CERRADAS, carga: { abierta: true, sesion: false } });
    expect(valores).toEqual([true]);
  });

  it('con la sesión de la vista pasa', () => {
    const valores = revisar({ vista: 'busqueda' }, '/buscar');
    http
      .expectOne('/api/acceso')
      .flush({ ...CERRADAS, busqueda: { abierta: false, sesion: true } });
    expect(valores).toEqual([true]);
  });

  it('sin sesión lleva a /acceso con la vista y adónde volver', () => {
    const valores = revisar({ vista: 'carga' }, '/videos/3/reporte?t=12');
    // La sesión de la otra vista no sirve.
    http
      .expectOne('/api/acceso')
      .flush({ ...CERRADAS, busqueda: { abierta: false, sesion: true } });
    expect(valores).toHaveLength(1);
    const destino = TestBed.inject(Router).serializeUrl(valores[0] as UrlTree);
    expect(destino).toBe('/acceso?vista=carga&volver=%2Fvideos%2F3%2Freporte%3Ft%3D12');
  });

  it('sin respuesta de la API deja entrar (la pantalla dirá que no hay conexión)', () => {
    const valores = revisar({ vista: 'carga' }, '/sops');
    http.expectOne('/api/acceso').flush(null, { status: 0, statusText: 'Unknown Error' });
    expect(valores).toEqual([true]);
  });
});
