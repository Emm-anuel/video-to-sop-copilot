import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
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

describe('Ver (/v/:id?t=, destino de los QR del PDF)', () => {
  let fixture: ComponentFixture<Ver>;
  let http: HttpTestingController;
  let navegar: ReturnType<typeof vi.spyOn>;

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
    navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(Ver);
    fixture.detectChanges();
  }

  afterEach(() => http.verify());

  it('modo validar: va al reporte con el segundo y reemplaza la URL', () => {
    crear({ t: '55.5' });
    http.expectOne('/api/videos/12').flush(estado('validar'));

    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte'], {
      queryParams: { t: 55.5 },
      replaceUrl: true,
    });
  });

  it('modo generar: va al SOP generado (el editor abre el video en t)', () => {
    crear({ t: '0.0' });
    http.expectOne('/api/videos/12').flush(estado('generar'));

    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'sop'], {
      queryParams: { t: 0 },
      replaceUrl: true,
    });
  });

  it('sin t (o con uno inválido) abre la pantalla sin segundo', () => {
    crear({ t: 'abc' });
    http.expectOne('/api/videos/12').flush(estado('validar'));

    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte'], {
      queryParams: {},
      replaceUrl: true,
    });
  });

  it('si el video no existe lo dice', () => {
    crear({ t: '3' });
    http
      .expectOne('/api/videos/12')
      .flush({ detail: 'video no encontrado' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    expect(navegar).not.toHaveBeenCalled();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('No se pudo abrir');
  });
});
