import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { EstadoAcceso } from '../acceso/acceso.service';
import { EstadoVideo } from '../api/tipos';
import { Ver } from './ver';

function estado(modo: EstadoVideo['modo']): EstadoVideo {
  return {
    id: 12,
    titulo: 'video_a',
    modo,
    proceso: 'listo',
    etapa: 'listo',
    progreso: 100,
    duracion: 90,
    idioma: 'es',
    error: null,
    creado: '2026-11-15T10:00:00Z',
  };
}

function acceso(carga: Partial<EstadoAcceso['carga']>): EstadoAcceso {
  return {
    carga: { abierta: false, sesion: false, ...carga },
    busqueda: { abierta: false, sesion: false },
  };
}

describe('Ver (/v/:id?t=&k=, destino de los QR del PDF)', () => {
  let fixture: ComponentFixture<Ver>;
  let http: HttpTestingController;

  function crear(consulta: Record<string, string>): void {
    TestBed.configureTestingModule({
      imports: [Ver],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              paramMap: convertToParamMap({ id: '12' }),
              queryParamMap: convertToParamMap(consulta),
            },
          },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Ver);
    fixture.detectChanges();
  }

  afterEach(() => http.verify());

  const el = () => fixture.nativeElement as HTMLElement;
  const abrir = () => el().querySelector<HTMLAnchorElement>('.abrir a');

  it('sin sesión de carga: solo el video en el segundo, con el token del enlace', () => {
    crear({ t: '55.5', k: 'tok_en-1' });
    http.expectOne('/api/acceso').flush(acceso({}));
    fixture.detectChanges();

    expect(el().querySelector('video')?.getAttribute('src')).toBe(
      '/api/videos/12/video?k=tok_en-1',
    );
    expect(el().textContent).toContain('Desde el segundo 00:55');
    expect(abrir()).toBeNull();
    http.expectNone('/api/videos/12'); // no pregunta por el video sin la vista de carga
  });

  it('con la sesión de carga, modo validar: ofrece abrir el reporte en ese segundo', () => {
    crear({ t: '55.5', k: 'tok' });
    http.expectOne('/api/acceso').flush(acceso({ sesion: true }));
    http.expectOne('/api/videos/12').flush(estado('validar'));
    fixture.detectChanges();

    expect(el().querySelector('h1')?.textContent).toContain('video_a');
    expect(abrir()?.textContent).toContain('Abrir el reporte');
    expect(abrir()?.getAttribute('href')).toBe('/videos/12/reporte?t=55.5');
  });

  it('con la vista de carga abierta, modo generar: ofrece abrir el SOP', () => {
    crear({ t: '0.0' });
    http.expectOne('/api/acceso').flush(acceso({ abierta: true }));
    http.expectOne('/api/videos/12').flush(estado('generar'));
    fixture.detectChanges();

    expect(el().querySelector('video')?.getAttribute('src')).toBe('/api/videos/12/video');
    expect(abrir()?.textContent).toContain('Abrir el SOP');
    expect(abrir()?.getAttribute('href')).toBe('/videos/12/sop?t=0');
  });

  it('sin t (o con uno inválido) abre el video desde el principio, sin segundo', () => {
    crear({ t: 'abc' });
    http.expectOne('/api/acceso').flush(acceso({ sesion: true }));
    http.expectOne('/api/videos/12').flush(estado('validar'));
    fixture.detectChanges();

    expect(el().querySelector('.segundo')).toBeNull();
    expect(abrir()?.getAttribute('href')).toBe('/videos/12/reporte');
  });

  it('si la API no responde se queda con el reproductor, sin enlaces', () => {
    crear({ t: '3' });
    http.expectOne('/api/acceso').flush(null, { status: 0, statusText: 'Unknown Error' });
    fixture.detectChanges();

    expect(el().querySelector('video')).not.toBeNull();
    expect(abrir()).toBeNull();
  });
});
