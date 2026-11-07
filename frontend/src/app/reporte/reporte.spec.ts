import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';
import ejemplo from '../../../../tests/fixtures/reporte_ejemplo.json';
import ejemploProvisional from '../../../../tests/fixtures/reporte_ejemplo_provisional.json';
import { ReporteValidacion } from '../api/reporte-validacion';
import { EstadoVideo, Proceso } from '../api/tipos';
import { INTERVALO_MS, Reporte, mmss } from './reporte';

const ESTADO = '/api/videos/7';
const REPORTE = '/api/videos/7/reporte';

// Los ejemplos se regeneran con scripts/ejemplo_reporte.py; no se editan aquí.
const NORMAL = ejemplo as ReporteValidacion;
const PROVISIONAL = ejemploProvisional as ReporteValidacion;

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

describe('mmss', () => {
  it('convierte segundos de la transcripción a mm:ss', () => {
    expect(mmss(0.4)).toBe('00:00');
    expect(mmss(74.2)).toBe('01:14');
    expect(mmss(152.16)).toBe('02:32');
    expect(mmss(3725)).toBe('62:05');
  });
});

describe('Reporte', () => {
  let fixture: ComponentFixture<Reporte>;
  let http: HttpTestingController;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      imports: [Reporte],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ id: '7' })) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Reporte);
    fixture.detectChanges();
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  function pantalla(): HTMLElement {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  function texto(): string {
    return pantalla().textContent ?? '';
  }

  function filas(): HTMLTableRowElement[] {
    return Array.from(pantalla().querySelectorAll<HTMLTableRowElement>('tbody tr'));
  }

  function conteo(nombre: string): string {
    return pantalla().querySelector(`[data-conteo="${nombre}"]`)?.textContent?.trim() ?? '';
  }

  function llegaReporte(reporte: ReporteValidacion): void {
    vi.advanceTimersByTime(0);
    http.expectOne(ESTADO).flush(estado('listo'));
    http.expectOne(REPORTE).flush(reporte);
  }

  it('consulta cada 3 s y, con "listo", pide el reporte y lo muestra', () => {
    vi.advanceTimersByTime(0);
    http.expectOne(ESTADO).flush(estado('procesando'));
    expect(texto()).toContain('procesando');
    expect(texto()).toContain('transcripcion');
    expect(texto()).toContain('Progreso: 30 %');
    http.expectNone(REPORTE);

    vi.advanceTimersByTime(INTERVALO_MS);
    http.expectOne(ESTADO).flush(estado('procesando', { etapa: 'segmentacion', progreso: 45 }));
    expect(texto()).toContain('Progreso: 45 %');
    http.expectNone(REPORTE);

    vi.advanceTimersByTime(INTERVALO_MS);
    http.expectOne(ESTADO).flush(estado('listo'));
    http.expectOne(REPORTE).flush(NORMAL);

    expect(texto()).toContain('SOP-0001');
    expect(texto()).toContain('Cambio del cartucho del filtro de agua');
    expect(filas()).toHaveLength(NORMAL.filas.length);
    expect(texto()).not.toContain('Progreso:');

    vi.advanceTimersByTime(INTERVALO_MS * 3);
    http.expectNone(ESTADO);
  });

  it('el video se puede ver desde el inicio, mientras se procesa', () => {
    vi.advanceTimersByTime(0);
    http.expectOne(ESTADO).flush(estado('en_cola'));
    const video = pantalla().querySelector('video') as HTMLVideoElement;
    expect(video.getAttribute('src')).toBe('/api/videos/7/video');
    expect(video.getAttribute('preload')).toBe('metadata');
    expect(video.hasAttribute('controls')).toBe(true);
  });

  it('con el ejemplo normal muestra cumplimiento, semáforo y conteo tal como vienen', () => {
    llegaReporte(NORMAL);
    const el = pantalla();

    expect(el.querySelector('.porcentaje')?.textContent).toContain('71.43 %');
    expect(el.querySelector('.semaforo-amarillo')).not.toBeNull();
    expect(el.querySelector('.semaforo-texto')?.textContent).toContain('Amarillo');
    expect(el.querySelector('.avisos')).toBeNull();
    expect(texto()).not.toContain('Afinidad');

    expect(texto()).toContain('5 de 7 pasos cumplen');
    expect(conteo('parcial')).toBe(String(NORMAL.conteo.parcial));
    expect(conteo('falta')).toBe(String(NORMAL.conteo.falta));
    expect(conteo('sobra')).toBe(String(NORMAL.conteo.sobra));
    expect(conteo('sin_revisar')).toBe(String(NORMAL.conteo.sin_revisar));
    expect(conteo('fuera_de_orden')).toBe(String(NORMAL.conteo.fuera_de_orden));
  });

  it('pinta cada fila con su estado, marca, cita y segundo', () => {
    llegaReporte(NORMAL);
    const f = filas();

    // Fila 0: Cumple y fuera de orden (la marca va junto al estado, no es otro estado).
    expect(f[0].querySelector('.estado-etiqueta')?.textContent?.trim()).toBe('Cumple');
    expect(f[0].querySelector('.marca-orden')?.textContent).toContain('Fuera de orden');
    expect(pantalla().querySelectorAll('.marca-orden')).toHaveLength(1);
    expect(f[0].textContent).toContain('1. Cerrar la llave de paso');
    expect(f[0].textContent).toContain('Cierre de la llave de paso');
    expect(f[0].textContent).toContain('“cierro la llave de paso que está antes del filtro”');
    expect(f[0].querySelector('button.segundo')?.textContent?.trim()).toBe('00:33');

    // Fila 2: Parcial con la justificación debajo de la cita.
    expect(f[2].querySelector('.estado-etiqueta')?.textContent?.trim()).toBe('Parcial');
    expect(f[2].querySelector('.justificacion')?.textContent).toContain(
      'no menciona colocar la cubeta',
    );

    // Fila 6: Falta, sin paso del video, sin segundo ni botón.
    expect(f[6].querySelector('.estado-etiqueta')?.textContent?.trim()).toBe('Falta');
    expect(f[6].querySelector('button')).toBeNull();
    expect(f[6].textContent).not.toMatch(/\d\d:\d\d/);
    expect(f[6].children[3].textContent?.trim()).toBe('—');
    expect(f[6].classList).not.toContain('con-segundo');

    // Filas 7 y 9: intro y cierre en gris, con su etiqueta y no como Sobra.
    expect(f[7].classList).toContain('marco');
    expect(f[7].querySelector('.estado-etiqueta')?.textContent?.trim()).toBe('Intro del operador');
    expect(f[9].classList).toContain('marco');
    expect(f[9].querySelector('.estado-etiqueta')?.textContent?.trim()).toBe('Cierre del operador');

    // Fila 8: la única Sobra que cuenta; sin paso del SOP.
    expect(f[8].classList).not.toContain('marco');
    expect(f[8].querySelector('.estado-etiqueta')?.textContent?.trim()).toBe('Sobra');
    expect(f[8].children[2].textContent?.trim()).toBe('—');
    const sobras = f.filter((fila) => fila.querySelector('.estado-sobra'));
    expect(sobras).toHaveLength(NORMAL.conteo.sobra);

    // Espacio para la miniatura (S5), sin imagen.
    expect(f[0].querySelector('.miniatura')).not.toBeNull();
    expect(pantalla().querySelector('tbody img')).toBeNull();
  });

  it('con el ejemplo provisional muestra el aviso y la zona gris como "Sin revisar"', () => {
    llegaReporte(PROVISIONAL);
    const el = pantalla();

    const avisos = el.querySelector('.avisos');
    expect(avisos).not.toBeNull();
    expect(avisos?.textContent).toContain('Reporte provisional');
    expect(avisos?.textContent).toContain(
      'Pares sin revisar por el juez: 1 pares de la zona gris sin revisar (llm_no_disponible: 1)',
    );
    expect(el.querySelector('.porcentaje')?.textContent).toContain('64.29 %');
    expect(el.querySelector('.semaforo-rojo')).not.toBeNull();
    expect(conteo('sin_revisar')).toBe('1');

    const zonaGris = filas()[2];
    expect(zonaGris.querySelector('.estado-etiqueta')?.textContent?.trim()).toBe('Sin revisar');
    expect(texto()).not.toContain('zona_gris');
  });

  it('al dar clic en una fila con segundo, el video salta ahí, reproduce y la fila se resalta', () => {
    llegaReporte(NORMAL);
    const video = pantalla().querySelector('video') as HTMLVideoElement;
    let actual = 0;
    const fijar = vi.fn((valor: number) => (actual = valor));
    Object.defineProperty(video, 'currentTime', {
      configurable: true,
      get: () => actual,
      set: fijar,
    });
    const reproducir = vi.spyOn(video, 'play').mockResolvedValue(undefined);

    filas()[8].click();
    expect(fijar).toHaveBeenCalledWith(47.68);
    expect(video.currentTime).toBe(47.68);
    expect(reproducir).toHaveBeenCalledTimes(1);
    expect(filas()[8].classList).toContain('activa');

    // El mm:ss es un botón (accesible con teclado) que hace lo mismo.
    (filas()[2].querySelector('button.segundo') as HTMLButtonElement).click();
    expect(video.currentTime).toBe(55.51);
    expect(filas()[2].classList).toContain('activa');
    expect(filas()[8].classList).not.toContain('activa');

    // Un Falta no tiene segundo: no mueve el video.
    filas()[6].click();
    expect(video.currentTime).toBe(55.51);
    expect(reproducir).toHaveBeenCalledTimes(2);
    expect(filas()[6].classList).not.toContain('activa');
  });

  it('si el video no carga, avisa junto al reproductor y la tabla sigue', () => {
    llegaReporte(NORMAL);
    expect(pantalla().querySelector('.aviso-video')).toBeNull();

    pantalla().querySelector('video')?.dispatchEvent(new Event('error'));

    expect(pantalla().querySelector('.aviso-video')?.textContent).toContain(
      'No se pudo cargar el video',
    );
    expect(filas()).toHaveLength(NORMAL.filas.length);
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
