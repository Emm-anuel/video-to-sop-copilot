import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { EstadoVideo, EstimacionImagenes, Proceso, Salud } from '../api/tipos';
import { INTERVALO_MS } from '../avance/avance.service';
import { ERROR_REINICIO } from '../avance/etapas';
import { INTERVALO_TXT_MS, Procesando, duracionAproximada, textoDispositivos } from './procesando';

const ESTADO = '/api/videos/7';
const TXT = '/api/videos/7/transcripcion.txt';
const SALUD = '/api/health';

function estado(proceso: Proceso, extra: Partial<EstadoVideo> = {}): EstadoVideo {
  return {
    id: 7,
    titulo: 'video_a',
    modo: 'validar',
    proceso,
    etapa: proceso === 'listo' ? 'listo' : 'transcripcion',
    progreso: proceso === 'listo' ? 100 : 20,
    duracion: null,
    idioma: 'es',
    error: null,
    creado: '2026-11-12T10:00:00Z',
    sop_id: 3,
    analizar_imagenes: false,
    ...extra,
  };
}

const SALUD_GPU: Salud = {
  status: 'ok',
  db: 'ok',
  llm: 'ok',
  dispositivos: {
    gpu: { nombre: 'NVIDIA GeForce RTX 2070 SUPER', vram_mb: 8192 },
    transcripcion: 'cuda/float16',
    llm: 'auto',
    embedder: 'cpu',
    avisos: [],
  },
};

describe('funciones de Procesando', () => {
  it('textoDispositivos dice dónde corre cada modelo según /health', () => {
    expect(textoDispositivos(SALUD_GPU)).toEqual({
      whisper: 'GPU (NVIDIA GeForce RTX 2070 SUPER)',
      llm: 'GPU (NVIDIA GeForce RTX 2070 SUPER)',
    });
    const cpu: Salud = {
      ...SALUD_GPU,
      dispositivos: { ...SALUD_GPU.dispositivos!, gpu: null, transcripcion: 'cpu/int8' },
    };
    expect(textoDispositivos(cpu)).toEqual({
      whisper: 'CPU',
      llm: 'Lo decide Ollama (GPU si la ve)',
    });
    const forzada: Salud = {
      ...SALUD_GPU,
      dispositivos: { ...SALUD_GPU.dispositivos!, llm: 'cpu' },
    };
    expect(textoDispositivos(forzada)!.llm).toBe('CPU');
    expect(textoDispositivos(null)).toBeNull();
  });

  it('duracionAproximada redondea como el aviso de la estimación', () => {
    expect(duracionAproximada(0.2)).toBe('~1 s');
    expect(duracionAproximada(40.4)).toBe('~40 s');
    expect(duracionAproximada(240)).toBe('~4 min');
  });
});

describe('Procesando', () => {
  let fixture: ComponentFixture<Procesando>;
  let http: HttpTestingController;
  let navegar: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      imports: [Procesando],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: convertToParamMap({ id: '7' }) } },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(Procesando);
    fixture.detectChanges();
  });

  afterEach(() => {
    fixture.destroy();
    http.verify();
    vi.useRealTimers();
  });

  function pantalla(): HTMLElement {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  function texto(): string {
    return (pantalla().textContent ?? '').replace(/\s+/g, ' ');
  }

  function etapas(): string[] {
    return Array.from(pantalla().querySelectorAll<HTMLElement>('li.etapa')).map(
      (li) =>
        `${li.dataset['etapa']}:${li.classList.contains('hecha') ? 'hecha' : ''}${li.classList.contains('en_curso') ? 'en_curso' : ''}${li.classList.contains('pendiente') ? 'pendiente' : ''}${li.classList.contains('fallo') ? 'fallo' : ''}`,
    );
  }

  function boton(nombre: string): HTMLButtonElement | undefined {
    return Array.from(pantalla().querySelectorAll('button')).find((b) =>
      b.textContent?.includes(nombre),
    );
  }

  /** Las tres primeras peticiones: salud, estado y transcripción. */
  function arrancar(primero: EstadoVideo, txt = ''): void {
    http.expectOne(SALUD).flush(SALUD_GPU);
    http.expectOne(ESTADO).flush(primero);
    vi.advanceTimersByTime(0);
    http.expectOne(TXT).flush(txt);
  }

  /** Avanza al siguiente sondeo del estado y responde. La transcripción se responde vacía. */
  function siguiente(respuesta: EstadoVideo): void {
    vi.advanceTimersByTime(INTERVALO_MS);
    http.match(TXT).forEach((r) => r.flush(''));
    http.expectOne(ESTADO).flush(respuesta);
  }

  it('muestra las etapas del modo validar en orden, con la actual en curso', () => {
    arrancar(estado('procesando', { etapa: 'transcripcion', progreso: 20 }));
    expect(etapas()).toEqual([
      'duracion:hecha',
      'audio:hecha',
      'transcripcion:en_curso',
      'contexto:pendiente',
      'segmentacion:pendiente',
      'emparejamiento:pendiente',
      'reporte:pendiente',
    ]);
    expect(texto()).toContain('Transcripción');
    expect(pantalla().querySelector('[data-progreso]')?.textContent).toContain('20 %');
    expect(pantalla().querySelector('[data-dispositivo="whisper"]')?.textContent).toContain('GPU');
    expect(texto()).toContain('Validar contra el SOP');
  });

  it('la etapa de imágenes aparece solo si el video se subió con imágenes', () => {
    arrancar(estado('procesando'));
    expect(etapas().some((e) => e.startsWith('fotogramas'))).toBe(false);
    siguiente(estado('procesando', { analizar_imagenes: true }));
    expect(etapas()[3]).toBe('fotogramas:pendiente');
  });

  it('modo generar: termina con la redacción del SOP', () => {
    arrancar(estado('procesando', { modo: 'generar', etapa: 'sop_pasos', progreso: 70 }));
    expect(
      etapas()
        .map((e) => e.split(':')[0])
        .slice(-3),
    ).toEqual(['sop_pasos', 'sop_resumen', 'sop_claves']);
    expect(etapas().at(-3)).toBe('sop_pasos:en_curso');
  });

  it('el porcentaje en pantalla no retrocede', () => {
    arrancar(estado('procesando', { etapa: 'segmentacion', progreso: 55 }));
    siguiente(estado('procesando', { etapa: 'segmentacion', progreso: 40 }));
    expect(pantalla().querySelector('[data-progreso]')?.textContent).toContain('55 %');
  });

  describe('imágenes', () => {
    const IMAGENES = { etapa: 'fotogramas', duracion: 300, analizar_imagenes: true };
    const ESTIMACION: EstimacionImagenes = {
      imagenes_estimadas: 20,
      segundos_extra_gpu: 24,
      segundos_extra_cpu: 214,
      dispositivo: 'cpu',
      dispositivo_supuesto: false,
      aviso: '',
      analizar_imagenes_defecto: false,
    };

    function linea(): string | undefined {
      return pantalla().querySelector('[data-imagenes]')?.textContent?.replace(/\s+/g, ' ').trim();
    }

    it('muestra la cuenta de la API tal cual y lo que falta, sin hablar de lotes', () => {
      // El porcentaje no se usa para contar: 41 % no dice nada de 8 de 20.
      arrancar(
        estado('procesando', {
          ...IMAGENES,
          progreso: 41,
          imagenes_hechas: 8,
          imagenes_total: 20,
        }),
      );
      const pedido = http.expectOne((r) => r.url === '/api/videos/estimacion');
      expect(pedido.request.params.get('duracion_s')).toBe('300');
      expect(pedido.request.params.get('modo')).toBe('validar');
      expect(pedido.request.params.get('sop_id')).toBe('3');
      pedido.flush(ESTIMACION);
      // 12 por hacer en CPU a 214/20 s cada una: 128 s.
      expect(linea()).toBe('8 de 20 imágenes · faltan ~2 min');
      expect(texto()).not.toMatch(/lote/i);

      siguiente(
        estado('procesando', {
          ...IMAGENES,
          progreso: 43,
          imagenes_hechas: 16,
          imagenes_total: 20,
        }),
      );
      expect(linea()).toContain('16 de 20 imágenes');
      // La estimación se pide una sola vez.
      http.expectNone((r) => r.url === '/api/videos/estimacion');
    });

    it('al describirlas todas dice "20 de 20", sin tiempo restante', () => {
      arrancar(
        estado('procesando', {
          ...IMAGENES,
          progreso: 44,
          imagenes_hechas: 20,
          imagenes_total: 20,
        }),
      );
      http.expectOne((r) => r.url === '/api/videos/estimacion').flush(ESTIMACION);
      expect(linea()).toBe('20 de 20 imágenes');
    });

    it('sin la estimación muestra la cuenta igual; al pasar a la ficha desaparece', () => {
      arrancar(
        estado('procesando', { ...IMAGENES, progreso: 35, imagenes_hechas: 0, imagenes_total: 4 }),
      );
      http
        .expectOne((r) => r.url === '/api/videos/estimacion')
        .flush('x', { status: 500, statusText: 'Error' });
      expect(linea()).toBe('0 de 4 imágenes');
      siguiente(
        estado('procesando', {
          ...IMAGENES,
          etapa: 'contexto',
          progreso: 45,
          imagenes_hechas: 4,
          imagenes_total: 4,
        }),
      );
      expect(pantalla().querySelector('[data-imagenes]')).toBeNull();
    });
  });

  it('lee la transcripción cada ~2 s, la muestra y ofrece descargar el TXT parcial', () => {
    arrancar(estado('procesando'), '[00:00] Hola\n');
    expect(pantalla().querySelector('pre.txt')?.textContent).toContain('[00:00] Hola');
    const enlace = pantalla().querySelector<HTMLAnchorElement>('a[download]')!;
    expect(enlace.getAttribute('href')).toBe(TXT);
    expect(enlace.getAttribute('download')).toBe('transcripcion-7.txt');

    vi.advanceTimersByTime(INTERVALO_TXT_MS);
    http.match(ESTADO).forEach((r) => r.flush(estado('procesando')));
    http.expectOne(TXT).flush('[00:00] Hola\n[00:04] Quito la tapa\n');
    expect(pantalla().querySelector('pre.txt')?.textContent).toContain('Quito la tapa');
  });

  it('deja de leer la transcripción cuando el video pasa a los pasos', () => {
    arrancar(estado('procesando', { etapa: 'transcripcion', progreso: 30 }), '[00:00] Hola\n');
    vi.advanceTimersByTime(INTERVALO_MS);
    http.expectOne(ESTADO).flush(estado('procesando', { etapa: 'contexto', progreso: 40 }));
    // Ya pasó la transcripción: una lectura más (la del TXT completo) y se detiene.
    vi.advanceTimersByTime(INTERVALO_TXT_MS - INTERVALO_MS);
    http.expectOne(TXT).flush('[00:00] Hola\n[00:05] Fin\n');
    expect(pantalla().querySelector('pre.txt')?.textContent).toContain('[00:05] Fin');
    vi.advanceTimersByTime(INTERVALO_TXT_MS * 5);
    http.match(ESTADO).forEach((r) => r.flush(estado('procesando', { etapa: 'segmentacion' })));
    http.expectNone(TXT);
  });

  it('abierta después de la transcripción, la lee una sola vez', () => {
    arrancar(estado('procesando', { etapa: 'segmentacion', progreso: 50 }), '[00:00] Hola\n');
    vi.advanceTimersByTime(INTERVALO_TXT_MS * 5);
    http.match(ESTADO).forEach((r) => r.flush(estado('procesando', { etapa: 'segmentacion' })));
    http.expectNone(TXT);
  });

  describe('al terminar', () => {
    it('modo validar: va al reporte', () => {
      arrancar(estado('procesando', { etapa: 'reporte', progreso: 96 }));
      siguiente(estado('listo'));
      expect(navegar).toHaveBeenCalledWith(['/videos', 7, 'reporte'], { replaceUrl: true });
    });

    it('modo generar: va al editor del SOP generado', () => {
      arrancar(estado('procesando', { modo: 'generar', etapa: 'sop_claves', progreso: 93 }));
      siguiente(estado('listo', { modo: 'generar', sop_id: 21 }));
      expect(navegar).toHaveBeenCalledWith(['/videos', 7, 'sop'], { replaceUrl: true });
    });

    it('con afinidad baja: va al reporte, donde está el aviso con "Continuar"', () => {
      arrancar(estado('procesando', { etapa: 'contexto', progreso: 42 }));
      siguiente(estado('afinidad_baja', { etapa: 'afinidad', progreso: 50 }));
      expect(navegar).toHaveBeenCalledWith(['/videos', 7, 'reporte'], { replaceUrl: true });
    });

    it('con error no navega', () => {
      arrancar(estado('error', { etapa: 'segmentacion', error: 'x' }));
      expect(navegar).not.toHaveBeenCalled();
    });
  });

  describe('error', () => {
    const MENSAJE =
      'LLM no disponible: el análisis quedó guardado; repite la validación con POST /videos/7/validar cuando Ollama responda';

    it('muestra el mensaje tal cual y la etapa que falló', () => {
      arrancar(estado('error', { etapa: 'contexto', progreso: 40, error: MENSAJE }));
      expect(pantalla().querySelector('[data-error]')?.textContent?.trim()).toBe(MENSAJE);
      expect(etapas()[3]).toBe('contexto:fallo');
      expect(boton('Reprocesar')).toBeDefined();
    });

    it('"Reprocesar" en modo validar llama a /validar y vuelve a seguir el avance', () => {
      arrancar(estado('error', { etapa: 'contexto', progreso: 40, error: MENSAJE }));
      boton('Reprocesar')!.click();
      const pedido = http.expectOne(
        (r) => r.method === 'POST' && r.url === '/api/videos/7/validar',
      );
      expect(pedido.request.params.keys()).toEqual([]); // sin continuar ni segmentar
      expect(boton('Enviando')!.disabled).toBe(true);
      pedido.flush({ id: 7, proceso: 'en_cola' });

      http.expectOne(ESTADO).flush(estado('procesando', { etapa: 'contexto', progreso: 40 }));
      expect(pantalla().querySelector('[data-error]')).toBeNull();
      siguiente(estado('listo'));
      expect(navegar).toHaveBeenCalledWith(['/videos', 7, 'reporte'], { replaceUrl: true });
    });

    it('"Reprocesar" en modo generar llama a /generar', () => {
      arrancar(estado('error', { modo: 'generar', etapa: 'sop_pasos', error: 'x' }));
      boton('Reprocesar')!.click();
      http
        .expectOne((r) => r.method === 'POST' && r.url === '/api/videos/7/generar')
        .flush({ id: 7, proceso: 'en_cola', sop_id: 21 });
      http.expectOne(ESTADO).flush(estado('procesando', { modo: 'generar', etapa: 'sop_pasos' }));
    });

    it('si no hay análisis guardado, muestra el 409 de la API y no repite Whisper', () => {
      arrancar(estado('error', { etapa: 'transcripcion', error: ERROR_REINICIO }));
      expect(texto()).toContain('interrumpido por reinicio');
      expect(texto()).toContain('La API se reinició mientras procesaba el video.');
      boton('Reprocesar')!.click();
      http
        .expectOne((r) => r.method === 'POST' && r.url === '/api/videos/7/validar')
        .flush(
          { detail: 'el video no tiene análisis guardado: vuelve a subirlo' },
          { status: 409, statusText: 'Conflict' },
        );
      expect(pantalla().querySelector('[data-error-reproceso]')?.textContent).toContain(
        'el video no tiene análisis guardado: vuelve a subirlo.',
      );
      expect(boton('Reprocesar')!.disabled).toBe(false);
      http.expectNone(ESTADO);
    });
  });

  it('sin conexión avisa del reintento y sigue cuando la API vuelve', () => {
    http.expectOne(SALUD).flush(SALUD_GPU);
    http.expectOne(ESTADO).error(new ProgressEvent('error'), { status: 0, statusText: '' });
    vi.advanceTimersByTime(0);
    http.expectOne(TXT).error(new ProgressEvent('error'), { status: 0, statusText: '' });
    expect(pantalla().querySelector('[data-reintento]')?.textContent).toContain(
      'Reintento 1 en 1.5 s',
    );
    vi.advanceTimersByTime(1500);
    http.expectOne(ESTADO).flush(estado('procesando'));
    expect(pantalla().querySelector('[data-reintento]')).toBeNull();
  });

  it('deja de consultar al salir de la pantalla', () => {
    arrancar(estado('procesando'));
    fixture.destroy();
    vi.advanceTimersByTime(INTERVALO_MS * 10);
    http.expectNone(ESTADO);
    http.expectNone(TXT);
  });
});
