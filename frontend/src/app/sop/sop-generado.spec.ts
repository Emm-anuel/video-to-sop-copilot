import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
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

/** El ejemplo con un paso cuyo tiempo y un punto de validación no tienen evidencia. */
function sopConInferidos(): SOP {
  const sop = structuredClone(ejemplo) as unknown as SOP;
  const paso = sop.pasos[0];
  paso.campos_inferidos = ['puntos_validacion', 'tiempo_esperado_min'];
  paso.evidencia = [
    {
      campo: 'puntos_validacion',
      valor: paso.puntos_validacion![0],
      cita: '',
      fuente: 'inferido',
      confianza: 'baja',
      t: null,
    },
    {
      campo: 'equipo',
      valor: paso.equipo![0],
      cita: 'I put on nitrile gloves',
      fuente: 'audio',
      confianza: 'alta',
      t: 53,
    },
  ];
  return sop;
}

function detalle(enBiblioteca = false): SopDetalle {
  return {
    id: 21,
    codigo: 'SOP-0021',
    origen: 'generado',
    creado: '2026-11-09T10:05:00Z',
    metodo: null,
    advertencias: [
      { tipo: 'sop_incompleto', linea: null, mensaje: 'SOP incompleto: puntos y palabras clave' },
    ],
    en_biblioteca: enBiblioteca,
    sop: sopConInferidos(),
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

  async function listo(enBiblioteca = false): Promise<void> {
    await responder(ESTADO, estado('listo'));
    await responder('/api/videos/9/sop', sopConInferidos());
    await responder('/api/sops/21', detalle(enBiblioteca));
  }

  it('sigue el avance mientras se genera y luego muestra el SOP', async () => {
    await responder(ESTADO, estado('procesando'));
    expect(texto()).toContain('Redactando el cuadro resumen…');

    await vi.advanceTimersByTimeAsync(INTERVALO_MS);
    await listo();
    expect(texto()).toContain(ejemplo.titulo);
    expect(texto()).toContain('SOP-0021');
    expect(texto()).toContain('versión 1.0');
    expect(texto()).toContain('SOP incompleto: puntos y palabras clave');
  });

  it('muestra el cuadro resumen, la tabla de pasos y las palabras clave con sus menciones', async () => {
    await listo();
    const el = fixture.nativeElement as HTMLElement;
    expect(texto()).toContain(ejemplo.resumen.objetivo.valor);
    expect(texto()).toContain('Supervisor de turno');
    expect(el.querySelectorAll('table.pasos tbody tr').length).toBe(ejemplo.pasos.length);
    const manometro = ejemplo.palabras_clave[0];
    expect(texto()).toContain(manometro.termino);
    expect(texto()).toContain('00:16'); // su primera mención, 16.53 s
  });

  it('resalta lo inferido y muestra la evidencia de lo que se dijo', async () => {
    await listo();
    const fila = (fixture.nativeElement as HTMLElement).querySelector('table.pasos tbody tr')!;
    const celdas = fila.querySelectorAll('td');
    const fichas = Array.from(fila.querySelectorAll('.ficha'));
    const validacion = fichas.find((f) => f.textContent?.includes('EPP completo'))!;
    expect(validacion.classList).toContain('inferido');
    const guantes = fichas.find((f) => f.textContent?.includes('Guantes de nitrilo'))!;
    expect(guantes.classList).not.toContain('inferido');
    expect(guantes.getAttribute('title')).toBe('audio · alta · 00:53 · «I put on nitrile gloves»');
    expect(celdas[7].classList).toContain('inferido'); // el tiempo, medido (tras la miniatura)
  });

  it('cada paso lleva la miniatura de su inicio, con carga diferida', async () => {
    await listo();
    const el = fixture.nativeElement as HTMLElement;
    const imgs = Array.from(el.querySelectorAll<HTMLImageElement>('table.pasos tbody img'));
    expect(imgs).toHaveLength(ejemplo.pasos.length);
    expect(imgs[0].getAttribute('src')).toBe(`/api/videos/9/thumb?t=${ejemplo.pasos[0].t_inicio}`);
    expect(imgs[0].getAttribute('loading')).toBe('lazy');
    imgs[0].dispatchEvent(new Event('error'));
    await fixture.whenStable();
    expect(el.querySelectorAll('table.pasos tbody img')).toHaveLength(ejemplo.pasos.length - 1);
  });

  it('con la advertencia "sin_imagen" no hay columna de miniatura', async () => {
    await responder(ESTADO, estado('listo'));
    await responder('/api/videos/9/sop', sopConInferidos());
    const sinImagen = detalle();
    sinImagen.advertencias = [
      ...sinImagen.advertencias,
      { tipo: 'sin_imagen', linea: null, mensaje: 'el video no tiene imagen visible' },
    ];
    await responder('/api/sops/21', sinImagen);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.col-miniatura')).toBeNull();
    expect(el.querySelector('table.pasos img')).toBeNull();
  });

  it('nombra la etapa de imágenes en el avance', async () => {
    await responder(ESTADO, estado('procesando', { etapa: 'fotogramas', progreso: 38 }));
    expect(texto()).toContain('Describiendo imágenes…');
    await vi.advanceTimersByTimeAsync(INTERVALO_MS);
    await responder(ESTADO, estado('error', { error: 'x' }));
  });

  it('guarda el SOP en la biblioteca', async () => {
    await listo();
    const boton = (fixture.nativeElement as HTMLElement).querySelector('button')!;
    expect(boton.textContent).toContain('Guardar en la biblioteca');
    boton.click();
    await fixture.whenStable();
    const req = http.expectOne({ method: 'POST', url: '/api/sops/21/biblioteca' });
    req.flush({ id: 21, codigo: 'SOP-0021', estado: 'listo', en_biblioteca: true });
    await fixture.whenStable();
    expect(texto()).toContain('Guardado en la biblioteca');
    expect((fixture.nativeElement as HTMLElement).querySelector('button')).toBeNull();
  });

  it('un SOP que ya está en la biblioteca no ofrece guardarlo', async () => {
    await listo(true);
    expect(texto()).toContain('Guardado en la biblioteca');
  });

  it('si la generación falla, muestra el error del video', async () => {
    await responder(ESTADO, estado('error', { error: 'LLM no disponible' }));
    expect(texto()).toContain('No se pudo generar el SOP: LLM no disponible');
  });
});
