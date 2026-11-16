import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { App } from './app';
import { routes } from './app.routes';

@Component({ template: '' })
class Vacia {}

describe('App', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [App],
      providers: [
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

  it('el menú lleva a la biblioteca, a un nuevo análisis y a los videos', async () => {
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
    expect(routes.find((r) => r.path === 'videos')?.data).toEqual({ ancho: true });
    expect(routes.find((r) => r.path === 'buscar')?.data).toEqual({ ancho: true, consulta: true });
  });

  it('la biblioteca (/sops) usa todo el ancho y no choca con el editor (/sops/:id)', () => {
    expect(routes.find((r) => r.path === 'sops')?.data?.['ancho']).toBe(true);
    expect(routes.find((r) => r.path === 'sops/:id')).toBeDefined();
  });

  it('el reporte (dos columnas) pide todo el ancho; /nuevo no', () => {
    expect(routes.find((r) => r.path === 'videos/:id/reporte')?.data?.['ancho']).toBe(true);
    expect(routes.find((r) => r.path === 'nuevo')?.data?.['ancho']).toBeUndefined();
  });
});
