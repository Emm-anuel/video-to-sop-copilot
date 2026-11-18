import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Data, Route, Router, provideRouter } from '@angular/router';
import { requiereVista } from './acceso/acceso.guard';
import { AccesoService } from './acceso/acceso.service';
import { App } from './app';
import { routes } from './app.routes';

@Component({ template: '' })
class Vacia {}

/** La ruta con `path` (en el nivel de arriba o como hija) y su `data` con la heredada del padre. */
function ruta(path: string): { ruta: Route; data: Data; padre: Route | null } | undefined {
  for (const r of routes) {
    if (r.path === path && !r.children) {
      return { ruta: r, data: r.data ?? {}, padre: null };
    }
    const hija = r.children?.find((h) => h.path === path);
    if (hija) {
      return { ruta: hija, data: { ...r.data, ...hija.data }, padre: r };
    }
  }
  return undefined;
}

describe('App', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'ancha', component: Vacia, data: { ancho: true } },
          { path: 'normal', component: Vacia },
          { path: 'consulta', component: Vacia, data: { ancho: true, consulta: true } },
        ]),
      ],
    });
  });

  async function main(ruta: string): Promise<HTMLElement> {
    const fixture = TestBed.createComponent(App);
    await TestBed.inject(Router).navigateByUrl(ruta);
    fixture.detectChanges();
    return (fixture.nativeElement as HTMLElement).querySelector('main') as HTMLElement;
  }

  it('usa todo el ancho solo en las rutas con data.ancho', async () => {
    expect((await main('/ancha')).classList).toContain('ancho');
    expect((await main('/normal')).classList).not.toContain('ancho');
  });

  it('el menú lleva a la biblioteca, a un nuevo análisis y a los videos (sin Búsqueda)', async () => {
    const fixture = TestBed.createComponent(App);
    await TestBed.inject(Router).navigateByUrl('/normal');
    fixture.detectChanges();
    const enlaces = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>('nav a'),
    );
    expect(enlaces.map((a) => [a.textContent?.trim(), a.getAttribute('href')])).toEqual([
      ['Biblioteca', '/sops'],
      ['Nuevo análisis', '/nuevo'],
      ['Videos', '/videos'],
    ]);
    expect(enlaces.some((a) => a.getAttribute('aria-current') === 'page')).toBe(false);
  });

  it('/buscar, /v/:id y /acceso no llevan la barra principal (sin data.menu)', () => {
    for (const path of ['buscar', 'v/:id', 'acceso']) {
      expect(ruta(path)?.data['consulta'], path).toBe(true);
      expect(ruta(path)?.data['menu'], path).toBeUndefined();
    }
  });

  it('la vista de consulta no muestra la barra ni el menú de la vista de carga', async () => {
    const fixture = TestBed.createComponent(App);
    const router = TestBed.inject(Router);
    await router.navigateByUrl('/consulta');
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('header.barra')).toBeNull();
    expect(el.querySelector('nav')).toBeNull();
    expect(el.querySelector('main')?.classList).toContain('consulta');

    await router.navigateByUrl('/normal');
    fixture.detectChanges();
    expect(el.querySelector('header.barra')).not.toBeNull();
  });

  it('/videos y /buscar usan todo el ancho; solo /buscar es la vista de consulta', () => {
    expect(ruta('videos')?.data).toEqual({ ancho: true, vista: 'carga' });
    expect(ruta('buscar')?.data).toEqual({ ancho: true, consulta: true, vista: 'busqueda' });
  });

  it('la biblioteca (/sops) usa todo el ancho y no choca con el editor (/sops/:id)', () => {
    expect(ruta('sops')?.data['ancho']).toBe(true);
    expect(ruta('sops/:id')).toBeDefined();
  });

  it('el reporte (dos columnas) pide todo el ancho; /nuevo no', () => {
    expect(ruta('videos/:id/reporte')?.data['ancho']).toBe(true);
    expect(ruta('nuevo')?.data['ancho']).toBeUndefined();
  });

  it('cada pantalla de carga pide la clave de carga; /buscar la de búsqueda (#30)', () => {
    const carga = [
      '',
      'nuevo',
      'sops',
      'videos',
      'videos/:id/procesando',
      'videos/:id/reporte',
      'videos/:id/sop',
      'sops/:id',
    ];
    for (const path of carga) {
      const r = ruta(path);
      expect(r?.data['vista'], path).toBe('carga');
      expect(r?.padre?.canActivateChild, path).toEqual([requiereVista]);
    }
    expect(ruta('buscar')?.ruta.canActivate).toEqual([requiereVista]);
  });

  it('la raíz es Inicio (no redirige a /nuevo) y una URL desconocida cae en ella', () => {
    expect(routes.some((r) => r.path === '' && r.redirectTo !== undefined)).toBe(false);
    expect(ruta('')?.ruta.pathMatch).toBe('full');
    expect(routes.at(-1)).toEqual({ path: '**', redirectTo: '' });
  });

  it('/acceso y /v/:id no piden clave y van sin el menú de carga', () => {
    for (const path of ['acceso', 'v/:id']) {
      const r = ruta(path);
      expect(r?.padre, path).toBeNull();
      expect(r?.ruta.canActivate, path).toBeUndefined();
      expect(r?.data['vista'], path).toBeUndefined();
      expect(r?.data['consulta'], path).toBe(true);
    }
  });

  it('"Salir" aparece solo con sesión de carga y cierra la sesión', async () => {
    const fixture = TestBed.createComponent(App);
    const router = TestBed.inject(Router);
    await router.navigateByUrl('/normal');
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('button.salir')).toBeNull();

    const acceso = TestBed.inject(AccesoService);
    acceso.ultimo.set({
      carga: { abierta: false, sesion: true },
      busqueda: { abierta: false, sesion: false },
    });
    fixture.detectChanges();
    const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    el.querySelector<HTMLButtonElement>('button.salir')?.click();
    const http = TestBed.inject(HttpTestingController);
    const pedido = http.expectOne((r) => r.url === '/api/acceso' && r.method === 'DELETE');
    expect(pedido.request.params.get('vista')).toBe('carga');
    pedido.flush(null, { status: 204, statusText: 'No Content' });

    expect(navegar).toHaveBeenCalledWith(['/acceso'], { queryParams: { vista: 'carga' } });
    http.verify();
  });
});
