import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import ejemplo from '../../../../tests/fixtures/sop_generado_ejemplo.json';
import { SOP } from '../api/sop';
import { EstadoVideo, Proceso, SopDetalle } from '../api/tipos';
import { INTERVALO_MS, SopGenerado } from './sop-generado';

const ESTADO = '/api/videos/9';

function estado(proceso: Proceso, extra: Partial<EstadoVideo> = {}): EstadoVideo {
  return {
    id: 9,
    titulo: 'video_e',
    modo: 'generar',
    proceso,
    etapa: proceso === 'listo' ? 'listo' : 'sop_resumen',
    progreso: proceso === 'listo' ? 100 : 85,
    duracion: 227,
    idioma: 'en',
    error: null,
    creado: '2026-11-09T10:00:00Z',
    sop_id: proceso === 'listo' ? 21 : null,
    ...extra,
  };
}

function detalle(): SopDetalle {
  return {
    id: 21,
    codigo: 'SOP-0021',
    origen: 'generado',
    creado: '2026-11-09T10:05:00Z',
    metodo: null,
    advertencias: [
      { tipo: 'sop_incompleto', linea: null, mensaje: 'SOP incompleto: puntos y palabras clave' },
    ],
    en_biblioteca: false,
    generacion: { video_id: 9 },
    sop: structuredClone(ejemplo) as unknown as SOP,
  };
}

describe('SopGenerado', () => {
  let fixture: ComponentFixture<SopGenerado>;
  let http: HttpTestingController;

  beforeEach(async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    TestBed.configureTestingModule({
      imports: [SopGenerado],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: convertToParamMap({ id: '9' }) } },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SopGenerado);
    await fixture.whenStable();
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  function texto(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  async function responder(url: string, cuerpo: object): Promise<void> {
    http.expectOne(url).flush(cuerpo);
    await fixture.whenStable();
  }

  it('sigue el avance mientras se genera y luego abre el editor con el SOP', async () => {
    await responder(ESTADO, estado('procesando'));
    expect(texto()).toContain('Redactando el cuadro resumen…');
    expect(fixture.componentInstance.puedeSalir()).toBe(true);

    await vi.advanceTimersByTimeAsync(INTERVALO_MS);
    await responder(ESTADO, estado('listo'));
    await responder('/api/sops/21', detalle());
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('app-sop-editor')).not.toBeNull();
    expect(el.querySelector<HTMLInputElement>('#sop-titulo')!.value).toBe(ejemplo.titulo);
    expect(texto()).toContain('SOP incompleto: puntos y palabras clave');
    // Las miniaturas usan el video de la ruta.
    expect(el.querySelector('li.paso img')?.getAttribute('src')).toContain('/api/videos/9/thumb');
  });

  it('pregunta antes de salir si el editor tiene cambios sin guardar', async () => {
    await responder(ESTADO, estado('listo'));
    await responder('/api/sops/21', detalle());
    const titulo = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(
      '#sop-titulo',
    )!;
    titulo.value = 'Otro título';
    titulo.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(fixture.componentInstance.puedeSalir()).toBe(false);
  });

  it('nombra la etapa de imágenes en el avance', async () => {
    await responder(ESTADO, estado('procesando', { etapa: 'fotogramas', progreso: 38 }));
    expect(texto()).toContain('Describiendo imágenes…');
    await vi.advanceTimersByTimeAsync(INTERVALO_MS);
    await responder(ESTADO, estado('error', { error: 'x' }));
  });

  it('si la generación falla, muestra el error del video', async () => {
    await responder(ESTADO, estado('error', { error: 'LLM no disponible' }));
    expect(texto()).toContain('No se pudo generar el SOP: LLM no disponible');
  });
});
