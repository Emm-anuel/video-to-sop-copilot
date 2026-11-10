import { HttpEventType, provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { EstadoSop, VideoCreado } from '../api/tipos';
import { Nuevo, SONDEO_SOP_MS } from './nuevo';

const SOP_EN_COLA: EstadoSop = {
  id: 3,
  codigo: 'SOP-0003',
  estado: 'en_cola',
  titulo: null,
  metodo: null,
  mensaje: null,
  advertencias: [],
};
const SOP_LISTO: EstadoSop = {
  ...SOP_EN_COLA,
  estado: 'listo',
  titulo: 'Cambio del cartucho',
  metodo: 'plantilla',
};
const SOP_CON_ADVERTENCIAS: EstadoSop = {
  ...SOP_LISTO,
  metodo: 'llm',
  advertencias: [{ tipo: 'paso_sin_evidencia', linea: null, mensaje: 'el paso 4 no tiene cita' }],
};
const SOP_ERROR: EstadoSop = {
  ...SOP_EN_COLA,
  estado: 'error',
  mensaje: 'El PDF no tiene texto: súbelo en Markdown con la plantilla.',
};
const VIDEO_CREADO: VideoCreado = { id: 12, proceso: 'en_cola' };
const ACEPTADO = { status: 202, statusText: 'Accepted' };

describe('Nuevo', () => {
  let fixture: ComponentFixture<Nuevo>;
  let http: HttpTestingController;
  let navegar: ReturnType<typeof vi.spyOn>;

  beforeEach(async () => {
    // El reloj avanza solo (whenStable funciona) y el sondeo se adelanta a mano.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    TestBed.configureTestingModule({
      imports: [Nuevo],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(Nuevo);
    await fixture.whenStable();
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  function elegir(selector: string, archivo: File): void {
    const input = fixture.nativeElement.querySelector(selector) as HTMLInputElement;
    Object.defineProperty(input, 'files', {
      configurable: true,
      value: { item: (i: number) => (i === 0 ? archivo : null), length: 1 },
    });
    input.dispatchEvent(new Event('change'));
  }

  async function llenarYValidar(sop = 'sop_filtro.pdf'): Promise<void> {
    elegir('#sop', new File(['%PDF'], sop, { type: 'application/pdf' }));
    elegir('#video', new File(['video'], 'video_b.mp4', { type: 'video/mp4' }));
    await validar();
  }

  async function validar(): Promise<void> {
    (fixture.nativeElement.querySelector('button[type=submit]') as HTMLButtonElement).click();
    await fixture.whenStable();
  }

  async function flush(req: TestRequest, cuerpo: object, estado = ACEPTADO): Promise<void> {
    req.flush(cuerpo, estado);
    await fixture.whenStable();
  }

  /** Adelanta el sondeo y responde la consulta del estado del SOP. */
  async function sondeo(estado: EstadoSop): Promise<void> {
    await vi.advanceTimersByTimeAsync(SONDEO_SOP_MS);
    await flush(http.expectOne({ method: 'GET', url: `/api/sops/${estado.id}/estado` }), estado);
  }

  function texto(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  function boton(): HTMLButtonElement {
    return fixture.nativeElement.querySelector('button');
  }

  it('con "No tengo SOP" sube el video en modo generar, sin SOP, y va a la vista del SOP', async () => {
    const casilla = fixture.nativeElement.querySelector('#sin-sop') as HTMLInputElement;
    casilla.checked = true;
    casilla.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('#sop')).toBeNull();
    expect(boton().textContent).toContain('Generar SOP');

    elegir('#video', new File(['video'], 'video_e.mp4', { type: 'video/mp4' }));
    await validar();
    http.expectNone({ method: 'POST', url: '/api/sops' });
    const video = http.expectOne({ method: 'POST', url: '/api/videos' });
    const datos = video.request.body as FormData;
    expect(datos.get('modo')).toBe('generar');
    expect(datos.has('sop_id')).toBe(false);
    expect(datos.get('titulo')).toBe('video_e');
    await flush(video, VIDEO_CREADO);
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'sop']);
  });

  it('acepta SOP en Markdown, texto, PDF y Word', () => {
    const input = fixture.nativeElement.querySelector('#sop') as HTMLInputElement;
    expect(input.accept).toBe('.md,.txt,.pdf,.docx');
  });

  it('sube el SOP y el video sin esperar la conversión, consulta cada 2 s y navega al quedar listo', async () => {
    await llenarYValidar();
    expect(boton().disabled).toBe(true);

    const sop = http.expectOne({ method: 'POST', url: '/api/sops' });
    expect((sop.request.body as FormData).get('archivo')).toBeInstanceOf(File);
    await flush(sop, SOP_EN_COLA);
    expect(texto()).toContain('Convirtiendo el SOP…');

    // El video sale de inmediato, con el SOP todavía en cola.
    const video = http.expectOne({ method: 'POST', url: '/api/videos' });
    const datos = video.request.body as FormData;
    expect(datos.get('modo')).toBe('validar');
    expect(datos.get('sop_id')).toBe('3');
    expect(datos.get('titulo')).toBe('video_b');
    expect(datos.has('idioma')).toBe(false);
    expect(video.request.reportProgress).toBe(true);
    video.event({ type: HttpEventType.UploadProgress, loaded: 40, total: 100 });
    await fixture.whenStable();
    expect(texto()).toContain('Subiendo el video: 40 %');

    await flush(video, VIDEO_CREADO);
    expect(navegar).not.toHaveBeenCalled(); // falta el SOP
    expect(texto()).toContain('Video subido. Falta que termine la conversión del SOP.');

    await sondeo({ ...SOP_EN_COLA, estado: 'convirtiendo' });
    expect(texto()).toContain('Convirtiendo el SOP…');
    expect(navegar).not.toHaveBeenCalled();

    await sondeo(SOP_LISTO);
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
    // Terminó: no hay más consultas.
    await vi.advanceTimersByTimeAsync(3 * SONDEO_SOP_MS);
    http.expectNone('/api/sops/3/estado');
  });

  it('con advertencias las muestra y espera a "Ver el reporte"', async () => {
    await llenarYValidar();
    await flush(http.expectOne('/api/sops'), SOP_EN_COLA);
    await sondeo(SOP_CON_ADVERTENCIAS);
    expect(texto()).toContain('SOP guardado como SOP-0003: Cambio del cartucho');
    expect(texto()).toContain('lo convirtió el modelo');
    expect(texto()).toContain('el paso 4 no tiene cita');

    await flush(http.expectOne('/api/videos'), VIDEO_CREADO);
    expect(navegar).not.toHaveBeenCalled();
    expect(boton().textContent).toContain('Ver el reporte');
    boton().click();
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
  });

  it('si la conversión falla, muestra el mensaje, cancela la subida y pide otro SOP', async () => {
    await llenarYValidar();
    await flush(http.expectOne('/api/sops'), SOP_EN_COLA);
    const video = http.expectOne('/api/videos');

    await sondeo(SOP_ERROR);
    expect(video.cancelled).toBe(true);
    expect(texto()).toContain(
      'No se pudo convertir el SOP SOP-0003. El PDF no tiene texto: súbelo en Markdown con la plantilla.',
    );
    expect(texto()).not.toContain('El SOP ya quedó guardado');
    expect(boton().disabled).toBe(false);
    expect(navegar).not.toHaveBeenCalled();

    // El reintento vuelve a subir el SOP y el video.
    await validar();
    await flush(http.expectOne({ method: 'POST', url: '/api/sops' }), SOP_EN_COLA);
    http.expectOne('/api/videos');
    await sondeo(SOP_LISTO);
  });

  it('si la conversión falla con el video ya subido, avisa que no se validará', async () => {
    await llenarYValidar();
    await flush(http.expectOne('/api/sops'), SOP_EN_COLA);
    await flush(http.expectOne('/api/videos'), VIDEO_CREADO);
    await sondeo(SOP_ERROR);
    expect(texto()).toContain('El video ya se había subido, pero no se validará con ese SOP.');
    expect(navegar).not.toHaveBeenCalled();
  });

  it('manda el idioma solo si se eligió', async () => {
    const select = fixture.nativeElement.querySelector('#idioma') as HTMLSelectElement;
    select.value = 'es';
    select.dispatchEvent(new Event('change'));
    await llenarYValidar('sop_filtro.md');
    await flush(http.expectOne('/api/sops'), SOP_LISTO);
    const video = http.expectOne('/api/videos');
    expect((video.request.body as FormData).get('idioma')).toBe('es');
    await flush(video, VIDEO_CREADO);
    // Un SOP que ya llega listo no se consulta.
    http.expectNone('/api/sops/3/estado');
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
  });

  it('con 422 en /sops muestra el mensaje de la API y no llama a /videos', async () => {
    await llenarYValidar();
    await flush(
      http.expectOne('/api/sops'),
      { detail: 'el PDF no tiene texto (¿es escaneado?)' },
      { status: 422, statusText: 'Unprocessable Entity' },
    );

    http.expectNone('/api/videos');
    expect(texto()).toContain(
      'No se pudo guardar el SOP. La API rechazó los datos: el PDF no tiene texto (¿es escaneado?).',
    );
    expect(boton().disabled).toBe(false);
    expect(navegar).not.toHaveBeenCalled();
  });

  it('si falla /videos, el reintento sube solo el video con el mismo sop_id', async () => {
    await llenarYValidar();
    await flush(http.expectOne('/api/sops'), SOP_EN_COLA);
    await flush(
      http.expectOne('/api/videos'),
      { detail: 'el video pasa del límite de 1024 MB' },
      { status: 413, statusText: 'Content Too Large' },
    );
    expect(texto()).toContain(
      'No se pudo subir el video. Archivo demasiado grande: el video pasa del límite de 1024 MB.',
    );
    expect(texto()).toContain('El SOP ya quedó guardado');
    expect(boton().disabled).toBe(false);

    // La conversión sigue mientras tanto.
    await sondeo(SOP_LISTO);
    await validar();
    http.expectNone({ method: 'POST', url: '/api/sops' });
    const reintento = http.expectOne('/api/videos');
    expect((reintento.request.body as FormData).get('sop_id')).toBe('3');
    await flush(reintento, VIDEO_CREADO);
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
  });

  it('sin archivos no llama a la API', async () => {
    await validar();
    expect(texto()).toContain('Elige el archivo del SOP.');
    expect(texto()).toContain('Elige el archivo del video.');
    http.expectNone('/api/sops');
  });
});
