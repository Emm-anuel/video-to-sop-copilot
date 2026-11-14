import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SopResumen } from '../api/tipos';
import { SelectorSop } from './selector-sop';

const SOPS: SopResumen[] = [
  {
    id: 7,
    codigo: 'SOP-0007',
    titulo: 'Limpieza de la válvula',
    origen: 'cargado',
    creado: '2026-11-10T10:00:00Z',
    videos_validados: 0,
  },
  {
    id: 8,
    codigo: 'SOP-0008',
    titulo: 'Arranque de la bomba',
    origen: 'generado',
    creado: '2026-11-11T10:00:00Z',
    videos_validados: 0,
  },
];

describe('SelectorSop', () => {
  let fixture: ComponentFixture<SelectorSop>;
  let elegidos: number[];

  beforeEach(async () => {
    fixture = TestBed.createComponent(SelectorSop);
    fixture.componentRef.setInput('sops', SOPS);
    elegidos = [];
    fixture.componentInstance.elegir.subscribe((id) => elegidos.push(id));
    await fixture.whenStable();
  });

  function opciones(): string[] {
    return Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('.opcion .codigo'),
    ).map((c) => c.textContent ?? '');
  }

  async function buscar(texto: string): Promise<void> {
    const input = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(
      'input[type=search]',
    )!;
    input.value = texto;
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  it('muestra código y título y emite el elegido', async () => {
    expect(opciones()).toEqual(['SOP-0007', 'SOP-0008']);
    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLInputElement>('input[value="8"]')!
      .click();
    expect(elegidos).toEqual([8]);
  });

  it('busca por título o código; el elegido no se esconde', async () => {
    await buscar('valvula');
    expect(opciones()).toEqual(['SOP-0007']);
    await buscar('0008');
    expect(opciones()).toEqual(['SOP-0008']);

    fixture.componentRef.setInput('elegido', 7);
    await fixture.whenStable();
    expect(opciones()).toEqual(['SOP-0007', 'SOP-0008']);

    await buscar('nada');
    expect(opciones()).toEqual(['SOP-0007']);
  });

  it('sin coincidencias lo dice', async () => {
    await buscar('nada');
    expect((fixture.nativeElement as HTMLElement).textContent).toContain(
      'Ningún SOP coincide con «nada».',
    );
  });
});
