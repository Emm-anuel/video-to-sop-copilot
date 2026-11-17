import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Inicio } from './inicio';

describe('Inicio', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [Inicio], providers: [provideRouter([])] });
  });

  it('lleva a cada pantalla de la aplicación', () => {
    const fixture = TestBed.createComponent(Inicio);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const enlaces = Array.from(el.querySelectorAll<HTMLAnchorElement>('li a'));
    expect(enlaces.map((a) => a.getAttribute('href'))).toEqual([
      '/nuevo',
      '/sops',
      '/videos',
      '/buscar',
    ]);
    expect(el.querySelector('h1')?.textContent).toBe('Inicio');
  });
});
