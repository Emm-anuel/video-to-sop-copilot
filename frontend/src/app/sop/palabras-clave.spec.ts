import { ComponentFixture, TestBed } from '@angular/core/testing';
import { PalabraClave } from '../api/sop';
import { PalabrasClave } from './palabras-clave';

const PALABRAS: PalabraClave[] = [
  { termino: 'manómetro', categoria: 'equipo', menciones: 2, t: [16.53, 61], literal: 'gauge' },
  { termino: 'purgar', categoria: 'accion', menciones: 1, t: [90], literal: '' },
];

describe('PalabrasClave', () => {
  let fixture: ComponentFixture<PalabrasClave>;

  async function crear(conVideo: boolean): Promise<HTMLElement> {
    fixture = TestBed.createComponent(PalabrasClave);
    fixture.componentRef.setInput('palabras', PALABRAS);
    fixture.componentRef.setInput('conVideo', conVideo);
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('cada palabra es una tarjeta con término, categoría, menciones y sus segundos', async () => {
    const el = await crear(true);
    const tarjetas = el.querySelectorAll('li.palabra');
    expect(tarjetas).toHaveLength(2);
    expect(tarjetas[0].textContent).toContain('manómetro');
    expect(tarjetas[0].textContent).toContain('2 menciones');
    expect(tarjetas[1].textContent).toContain('1 mención');
    expect(tarjetas[0].getAttribute('title')).toBe('Dicho como «gauge»');
    expect(tarjetas[0].querySelectorAll('.segundos button')).toHaveLength(2);
  });

  it('con video, un segundo abre el video ahí', async () => {
    const el = await crear(true);
    const abiertos: number[] = [];
    fixture.componentInstance.abrir.subscribe((t) => abiertos.push(t));
    el.querySelector<HTMLButtonElement>(
      'button[aria-label="Ver «manómetro» en el video en 01:01"]',
    )!.click();
    expect(abiertos).toEqual([61]);
  });

  it('sin video, los segundos son texto (y se parten en varias líneas)', async () => {
    const el = await crear(false);
    expect(el.querySelector('button')).toBeNull();
    expect(el.querySelectorAll('.segundos .t')).toHaveLength(3);
  });
});
