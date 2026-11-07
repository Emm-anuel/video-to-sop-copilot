import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';
import { ReporteValidacion } from '../api/reporte-validacion';
import { EstadoVideo, Proceso } from '../api/tipos';
import { INTERVALO_MS, ReporteProvisional } from './reporte-provisional';

const ESTADO = '/api/videos/7';
const REPORTE = '/api/videos/7/reporte';

function estado(proceso: Proceso, extra: Partial<EstadoVideo> = {}): EstadoVideo {
  return {
    id: 7,
    titulo: 'video_b',
    modo: 'validar',
    proceso,
    etapa: proceso === 'listo' ? 'listo' : 'transcripcion',
    progreso: proceso === 'listo' ? 100 : 30,
    duracion: 90,
    idioma: 'es',
    error: null,
    creado: '2026-11-07T10:00:00Z',
    ...extra,
  };
}

const REPORTE_B: ReporteValidacion = {
  video_id: 7,
  sop: { id: 3, codigo: 'SOP-0003', titulo: 'Cambio del cartucho', pasos: [] },
  cumplimiento: 66.67,
  semaforo: 'rojo',
  provisional: true,
  conteo: {
    cumple: 4,
    parcial: 0,
    fuera_de_orden: 0,
    falta: 2,
    sobra: 1,
    sin_revisar: 0,
    marco_operador: 2,
  },
  filas: [],
  metadatos: {
    segmentacion: 'llm',
    embedder: 'paraphrase-multilingual-MiniLM-L12-v2',
    umbrales: { bajo: 0.55, alto: 0.75, fusion: 0.8, semaforo_verde: 90, semaforo_amarillo: 70 },
    segundos: {},
    avisos: [{ tipo: 'juez_sin_revisar', detalle: 'Ollama no respondió' }],
  },
  creado: '2026-11-07T10:05:00Z',
};

describe('ReporteProvisional', () => {
  let fixture: ComponentFixture<ReporteProvisional>;
  let http: HttpTestingController;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      imports: [ReporteProvisional],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ id: '7' })) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ReporteProvisional);
    fixture.detectChanges();
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  function texto(): string {
    fixture.detectChanges();
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  it('consulta cada 3 s y, con "listo", pide el reporte y lo muestra tal como viene', () => {
    vi.advanceTimersByTime(0);
    http.expectOne(ESTADO).flush(estado('procesando'));
    expect(texto()).toContain('procesando');
    expect(texto()).toContain('transcripcion');
    expect(texto()).toContain('Progreso: 30 %');
    http.expectNone(REPORTE);

    vi.advanceTimersByTime(INTERVALO_MS);
    http.expectOne(ESTADO).flush(estado('listo'));
    http.expectOne(REPORTE).flush(REPORTE_B);

    const pantalla = texto();
    expect(pantalla).toContain('66.67 %');
    expect(pantalla).toContain('rojo');
    expect(pantalla).toContain('Pantalla provisional: la tabla con el video la hace RF-20');
    expect(pantalla).toContain('juez_sin_revisar: Ollama no respondió');
    expect(fixture.nativeElement.querySelector('.semaforo-rojo')).not.toBeNull();

    vi.advanceTimersByTime(INTERVALO_MS * 3);
    http.expectNone(ESTADO);
  });

  it('con "error" muestra el mensaje y deja de consultar', () => {
    vi.advanceTimersByTime(0);
    http
      .expectOne(ESTADO)
      .flush(estado('error', { error: 'video.mp4: el video no tiene pista de audio' }));

    expect(texto()).toContain('video.mp4: el video no tiene pista de audio');
    vi.advanceTimersByTime(INTERVALO_MS * 3);
    http.expectNone(ESTADO);
    http.expectNone(REPORTE);
  });

  it('deja de consultar al salir de la pantalla', () => {
    vi.advanceTimersByTime(0);
    http.expectOne(ESTADO).flush(estado('en_cola'));
    fixture.destroy();
    vi.advanceTimersByTime(INTERVALO_MS * 3);
    http.expectNone(ESTADO);
  });

  it('sin conexión con la API muestra el aviso en español', () => {
    vi.advanceTimersByTime(0);
    http.expectOne(ESTADO).error(new ProgressEvent('error'), { status: 0, statusText: '' });
    expect(texto()).toContain('No hay conexión con la API (¿está corriendo en el puerto 8000?)');
    vi.advanceTimersByTime(INTERVALO_MS);
    http.expectNone(ESTADO);
  });
});
