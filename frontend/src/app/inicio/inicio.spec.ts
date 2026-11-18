import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Inicio } from './inicio';

describe('Inicio', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [Inicio], providers: [provideRouter([])] });
  });

  it('lleva a las tres pantallas de la vista de carga y no a la búsqueda', () => {
    const fixture = TestBed.createComponent(Inicio);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const enlaces = Array.from(el.querySelectorAll<HTMLAnchorElement>('li a'));
    expect(el.querySelectorAll('li.tarjeta').length).toBe(3);
    expect(enlaces.map((a) => a.getAttribute('href'))).toEqual(['/nuevo', '/sops', '/videos']);
    expect(el.querySelector('h1')?.textContent).toBe('Inicio');
  });
});
