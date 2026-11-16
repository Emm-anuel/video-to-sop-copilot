import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Reproductor } from './reproductor';

/** `currentTime` y `readyState` controlables: jsdom no carga medios. */
function simular(video: HTMLVideoElement, readyState = 0) {
  let actual = 0;
  const fijar = vi.fn((valor: number) => (actual = valor));
  Object.defineProperty(video, 'currentTime', {
    configurable: true,
    get: () => actual,
    set: fijar,
  });
  Object.defineProperty(video, 'readyState', { configurable: true, get: () => readyState });
  const reproducir = vi.spyOn(video, 'play').mockResolvedValue(undefined);
  return { fijar, reproducir, leer: () => actual };
}

describe('Reproductor', () => {
  let fixture: ComponentFixture<Reproductor>;
  let http: HttpTestingController;

  beforeEach(async () => {
    TestBed.configureTestingModule({
      imports: [Reproductor],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Reproductor);
    fixture.componentRef.setInput('videoId', 5);
    fixture.componentRef.setInput('textoFormato', 'Los resultados siguen en la lista.');
    await fixture.whenStable();
  });

  afterEach(() => http.verify());

  const video = () => (fixture.nativeElement as HTMLElement).querySelector('video')!;
  const aviso = () => (fixture.nativeElement as HTMLElement).querySelector('.aviso-video');

  it('pide el video a la API con Range (el src de GET /videos/{id}/video)', () => {
    expect(video().getAttribute('src')).toBe('/api/videos/5/video');
    expect(video().getAttribute('preload')).toBe('metadata');
  });

  it('con los metadatos cargados salta ya y reproduce', () => {
    const v = simular(video(), 1);

    fixture.componentInstance.saltar(74.2);

    expect(v.leer()).toBe(74.2);
    expect(v.reproducir).toHaveBeenCalledTimes(1);
    // Nada pendiente: otra carga de metadatos no lo mueve.
    v.fijar.mockClear();
    video().dispatchEvent(new Event('loadedmetadata'));
    expect(v.fijar).not.toHaveBeenCalled();
  });

  it('antes de los metadatos lo deja pendiente y lo aplica al cargar', () => {
    const v = simular(video(), 0);

    fixture.componentInstance.saltar(12.5);
    expect(v.leer()).toBe(12.5);

    // El navegador vuelve a 0 al empezar a cargar; con los metadatos, al segundo pedido.
    v.fijar(0);
    video().dispatchEvent(new Event('loadedmetadata'));
    expect(v.leer()).toBe(12.5);
  });

  it('`inicio` salta sin reproducir con la primera carga de ese video', async () => {
    fixture.componentRef.setInput('inicio', 55.5);
    await fixture.whenStable();
    const v = simular(video(), 0);

    video().dispatchEvent(new Event('loadedmetadata'));
    expect(v.leer()).toBe(55.5);
    expect(v.reproducir).not.toHaveBeenCalled();

    v.fijar(80);
    video().dispatchEvent(new Event('loadedmetadata'));
    expect(v.leer()).toBe(80);
  });

  it('si no carga lo dice; al cambiar de video el aviso se va', async () => {
    video().dispatchEvent(new Event('error'));
    fixture.detectChanges();
    expect(aviso()?.textContent).toContain('No se pudo cargar el video.');

    fixture.componentRef.setInput('videoId', 6);
    await fixture.whenStable();
    expect(video().getAttribute('src')).toBe('/api/videos/6/video');
    expect(aviso()).toBeNull();
  });

  it('un formato sin soporte (AVI) lo dice y ofrece descargarlo', () => {
    Object.defineProperty(video(), 'error', { configurable: true, value: { code: 4 } });
    video().dispatchEvent(new Event('error'));
    const sonda = http.expectOne('/api/videos/5/video');
    expect(sonda.request.headers.get('Range')).toBe('bytes=0-0');
    sonda.flush(new Blob(['R']), { status: 206, statusText: 'Partial Content' });
    fixture.detectChanges();

    expect(aviso()?.textContent).toContain('El navegador no reproduce este formato.');
    expect(aviso()?.textContent).toContain('Los resultados siguen en la lista.');
    const enlace = aviso()?.querySelector('a.descargar-video');
    expect(enlace?.getAttribute('href')).toBe('/api/videos/5/video');
    expect(enlace?.hasAttribute('download')).toBe(true);
  });
});
