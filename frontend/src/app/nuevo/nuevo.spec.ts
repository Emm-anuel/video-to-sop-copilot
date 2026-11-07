import { HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { SopCreado, VideoCreado } from '../api/tipos';
import { Nuevo } from './nuevo';

const SOP_CREADO: SopCreado = {
  id: 3,
  codigo: 'SOP-0003',
  titulo: 'Cambio del cartucho',
  advertencias: [
    { tipo: 'paso_sin_descripcion', linea: 12, mensaje: 'el paso 4 no tiene descripción' },
  ],
};
const VIDEO_CREADO: VideoCreado = { id: 12, proceso: 'en_cola' };

describe('Nuevo', () => {
  let fixture: ComponentFixture<Nuevo>;
  let http: HttpTestingController;
  let navegar: ReturnType<typeof vi.spyOn>;

  beforeEach(async () => {
    TestBed.configureTestingModule({
      imports: [Nuevo],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(Nuevo);
    await fixture.whenStable();
  });

  afterEach(() => http.verify());

  function elegir(selector: string, archivo: File): void {
    const input = fixture.nativeElement.querySelector(selector) as HTMLInputElement;
    Object.defineProperty(input, 'files', {
      configurable: true,
      value: { item: (i: number) => (i === 0 ? archivo : null), length: 1 },
    });
    input.dispatchEvent(new Event('change'));
  }

  async function llenarYValidar(): Promise<void> {
    elegir('#sop', new File(['# SOP'], 'sop_filtro.md', { type: 'text/markdown' }));
    elegir('#video', new File(['video'], 'video_b.mp4', { type: 'video/mp4' }));
    await validar();
  }

  async function validar(): Promise<void> {
    (fixture.nativeElement.querySelector('button[type=submit]') as HTMLButtonElement).click();
    await fixture.whenStable();
  }

  function texto(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  function boton(): HTMLButtonElement {
    return fixture.nativeElement.querySelector('button[type=submit]');
  }

  it('sube el SOP, luego el video con sop_id y modo=validar, y navega al reporte', async () => {
    await llenarYValidar();
    expect(boton().disabled).toBe(true);

    const sop = http.expectOne({ method: 'POST', url: '/api/sops' });
    expect((sop.request.body as FormData).get('archivo')).toBeInstanceOf(File);
    sop.flush(SOP_CREADO, { status: 201, statusText: 'Created' });
    await fixture.whenStable();

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
    expect(texto()).toContain('Línea 12: el paso 4 no tiene descripción');

    video.flush(VIDEO_CREADO, { status: 202, statusText: 'Accepted' });
    await fixture.whenStable();
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
  });

  it('manda el idioma solo si se eligió', async () => {
    const select = fixture.nativeElement.querySelector('#idioma') as HTMLSelectElement;
    select.value = 'es';
    select.dispatchEvent(new Event('change'));
    await llenarYValidar();
    http.expectOne('/api/sops').flush(SOP_CREADO, { status: 201, statusText: 'Created' });
    const video = http.expectOne('/api/videos');
    expect((video.request.body as FormData).get('idioma')).toBe('es');
    video.flush(VIDEO_CREADO, { status: 202, statusText: 'Accepted' });
  });

  it('con 422 en /sops muestra el mensaje de la API y no llama a /videos', async () => {
    await llenarYValidar();
    http
      .expectOne('/api/sops')
      .flush(
        { detail: 'falta la sección "## Pasos"' },
        { status: 422, statusText: 'Unprocessable Entity' },
      );
    await fixture.whenStable();

    http.expectNone('/api/videos');
    expect(texto()).toContain(
      'No se pudo guardar el SOP. La API rechazó los datos: falta la sección "## Pasos".',
    );
    expect(boton().disabled).toBe(false);
    expect(navegar).not.toHaveBeenCalled();
  });

  it('si falla /videos, el reintento sube solo el video con el mismo sop_id', async () => {
    await llenarYValidar();
    http.expectOne('/api/sops').flush(SOP_CREADO, { status: 201, statusText: 'Created' });
    await fixture.whenStable();
    http
      .expectOne('/api/videos')
      .flush(
        { detail: 'el video pasa del límite de 1024 MB' },
        { status: 413, statusText: 'Content Too Large' },
      );
    await fixture.whenStable();
    expect(texto()).toContain(
      'No se pudo subir el video. Archivo demasiado grande: el video pasa del límite de 1024 MB.',
    );
    expect(boton().disabled).toBe(false);

    await validar();
    http.expectNone('/api/sops');
    const reintento = http.expectOne('/api/videos');
    expect((reintento.request.body as FormData).get('sop_id')).toBe('3');
    reintento.flush(VIDEO_CREADO, { status: 202, statusText: 'Accepted' });
    await fixture.whenStable();
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
  });

  it('sin archivos no llama a la API', async () => {
    await validar();
    expect(texto()).toContain('Elige el archivo del SOP.');
    expect(texto()).toContain('Elige el archivo del video.');
    http.expectNone('/api/sops');
  });
});
