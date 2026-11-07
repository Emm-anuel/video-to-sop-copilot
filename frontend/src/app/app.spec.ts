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

  it('el reporte (dos columnas) pide todo el ancho; /nuevo no', () => {
    expect(routes.find((r) => r.path === 'videos/:id/reporte')?.data?.['ancho']).toBe(true);
    expect(routes.find((r) => r.path === 'nuevo')?.data?.['ancho']).toBeUndefined();
  });
});
