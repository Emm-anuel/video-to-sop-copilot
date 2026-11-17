import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { Acceso, destinoSeguro } from './acceso';
import { EstadoAcceso } from './acceso.service';

const CERRADAS: EstadoAcceso = {
  carga: { abierta: false, sesion: false },
  busqueda: { abierta: false, sesion: false },
};

describe('destinoSeguro', () => {
  it('vuelve a una ruta de la app', () => {
    expect(destinoSeguro('/videos/3/reporte?t=12', 'carga')).toBe('/videos/3/reporte?t=12');
  });

  it('nunca a otro sitio ni a /acceso; sin volver, al inicio de la vista', () => {
    for (const malo of ['//otro.sitio/x', '/\\otro.sitio', 'https://otro.sitio', '/acceso?x=1']) {
      expect(destinoSeguro(malo, 'carga'), malo).toBe('/nuevo');
    }
    expect(destinoSeguro(null, 'busqueda')).toBe('/buscar');
  });
});

describe('Acceso (/acceso, pantalla de la clave)', () => {
  let fixture: ComponentFixture<Acceso>;
  let http: HttpTestingController;
  let navegar: ReturnType<typeof vi.spyOn>;

  function crear(consulta: Record<string, string>): void {
    TestBed.configureTestingModule({
      imports: [Acceso],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: convertToParamMap(consulta) } },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    navegar = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    fixture = TestBed.createComponent(Acceso);
    fixture.detectChanges();
  }

  afterEach(() => http.verify());

  const el = () => fixture.nativeElement as HTMLElement;

  function escribirYEnviar(clave: string): void {
    const campo = el().querySelector<HTMLInputElement>('input#clave')!;
    campo.value = clave;
    campo.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    el().querySelector('form')!.dispatchEvent(new Event('submit'));
  }

  it('con la clave correcta deja la sesión y vuelve a donde iba', () => {
    crear({ vista: 'carga', volver: '/videos/7/reporte?t=30' });
    http.expectOne('/api/acceso').flush(CERRADAS);
    expect(el().querySelector('h1')?.textContent).toContain('Vista de carga');
    expect(el().querySelector('input#clave')?.getAttribute('type')).toBe('password');

    escribirYEnviar(' clave-corta ');
    const post = http.expectOne((r) => r.url === '/api/acceso' && r.method === 'POST');
    expect(post.request.body).toEqual({ vista: 'carga', clave: 'clave-corta' });
    post.flush(null, { status: 204, statusText: 'No Content' });

    expect(navegar).toHaveBeenCalledWith('/videos/7/reporte?t=30', { replaceUrl: true });
  });

  it('con una clave equivocada lo dice y se queda', () => {
    crear({ vista: 'busqueda', volver: '/buscar' });
    http.expectOne('/api/acceso').flush(CERRADAS);
    expect(el().querySelector('h1')?.textContent).toContain('Vista de búsqueda');

    escribirYEnviar('otra');
    http
      .expectOne((r) => r.url === '/api/acceso' && r.method === 'POST')
      .flush(
        { detail: 'La clave de la vista de búsqueda no es correcta.' },
        {
          status: 401,
          statusText: 'Unauthorized',
        },
      );
    fixture.detectChanges();

    expect(el().querySelector('[role="alert"]')?.textContent).toContain('La clave no es correcta.');
    expect(navegar).not.toHaveBeenCalled();
  });

  it('si la vista ya está abierta o con sesión, sigue sin pedir la clave', () => {
    crear({ vista: 'carga', volver: '/sops' });
    http.expectOne('/api/acceso').flush({ ...CERRADAS, carga: { abierta: true, sesion: false } });
    expect(navegar).toHaveBeenCalledWith('/sops', { replaceUrl: true });
  });

  it('con un volver externo, al entrar va al inicio de la vista', () => {
    crear({ vista: 'carga', volver: '//otro.sitio' });
    http.expectOne('/api/acceso').flush(CERRADAS);
    escribirYEnviar('clave');
    http
      .expectOne((r) => r.url === '/api/acceso' && r.method === 'POST')
      .flush(null, { status: 204, statusText: 'No Content' });
    expect(navegar).toHaveBeenCalledWith('/nuevo', { replaceUrl: true });
  });
});
