import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { EstadoPublicacion } from '../api/publicacion';
import { VideoResumen } from '../api/video-resumen';
import { SONDEO_VIDEOS_MS, Videos } from './videos';

const LISTA = '/api/videos';

const VALIDADO: VideoResumen = {
  id: 7,
  titulo: 'Limpieza del filtro de agua',
  creado: '2026-11-14T18:02:00Z',
  duracion: 312,
  modo: 'validar',
  proceso: 'listo',
  etapa: 'listo',
  cumplimiento: 100,
  semaforo: 'verde',
  sop: { id: 3, codigo: 'SOP-0003', titulo: 'Mantenimiento de la válvula' },
  analizar_imagenes: false,
  publicado: false,
  publicado_en: null,
};
const GENERADO: VideoResumen = {
  id: 8,
  titulo: 'Arranque de la bomba',
  creado: '2026-11-13T10:00:00Z',
  modo: 'generar',
  proceso: 'listo',
  sop: { id: 9, codigo: 'SOP-0009', titulo: 'Arranque de la bomba' },
  analizar_imagenes: true,
  publicado: true,
  publicado_en: '2026-11-13T11:00:00Z',
};
const PROCESANDO: VideoResumen = {
  id: 9,
  titulo: 'Cambio de cartucho',
  creado: '2026-11-15T09:00:00Z',
  modo: 'validar',
  proceso: 'procesando',
  etapa: 'segmentacion',
  sop: { id: 3, codigo: 'SOP-0003', titulo: 'Mantenimiento de la válvula' },
};
const AFINIDAD: VideoResumen = {
  id: 10,
  titulo: 'Video de otra línea',
  creado: '2026-11-12T09:00:00Z',
  modo: 'validar',
  proceso: 'afinidad_baja',
  etapa: 'afinidad',
  sop: { id: 3, codigo: 'SOP-0003', titulo: 'Mantenimiento de la válvula' },
};
const ERROR: VideoResumen = {
  id: 11,
  titulo: 'Prueba sin modelo',
  creado: '2026-11-11T09:00:00Z',
  modo: 'validar',
  proceso: 'error',
  error: 'LLM no disponible',
  sop: null,
};

describe('Videos', () => {
  let fixture: ComponentFixture<Videos>;
  let http: HttpTestingController;

  beforeEach(async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    TestBed.configureTestingModule({
      imports: [Videos],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Videos);
    await fixture.whenStable();
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  const pantalla = () => fixture.nativeElement as HTMLElement;
  const filas = () => Array.from(pantalla().querySelectorAll<HTMLElement>('li.video'));
  const titulos = () => filas().map((f) => f.querySelector('.titulo')?.textContent?.trim());

  async function llega(lista: VideoResumen[]): Promise<void> {
    http.expectOne(LISTA).flush(lista);
    await fixture.whenStable();
  }

  function elegir(selector: string, valor: string): void {
    const select = pantalla().querySelector<HTMLSelectElement>(selector)!;
    select.value = valor;
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();
  }

  it('muestra la lista tal como llega, con cumplimiento, estado, imágenes y publicado', async () => {
    await llega([VALIDADO, GENERADO, ERROR]);

    expect(titulos()).toEqual([
      'Limpieza del filtro de agua',
      'Arranque de la bomba',
      'Prueba sin modelo',
    ]);
    const [validado, generado, error] = filas();
    expect(validado.querySelector('.cumplimiento')?.textContent).toContain('100.00 %');
    expect(validado.querySelector('.semaforo-verde')).not.toBeNull();
    expect(validado.querySelector('.semaforo-texto')?.textContent).toContain('Verde');
    expect(validado.querySelector('.sop')?.textContent).toContain('SOP-0003');
    expect(validado.querySelector('.imagenes')?.textContent).toContain('No');
    expect(validado.querySelector('.publicado')?.textContent).toContain('No publicado');
    expect(generado.querySelector('.cumplimiento')?.textContent).toContain('—');
    expect(generado.querySelector('.imagenes')?.textContent).toContain('Sí');
    expect(generado.querySelector('.publicado')?.textContent).toContain('Publicado');
    expect(error.querySelector('.estado')?.textContent).toContain('LLM no disponible');
    expect(error.querySelector('.sop')?.textContent).toContain('Sin SOP');
  });

  it('cada fila lleva a su pantalla según el estado', async () => {
    await llega([VALIDADO, GENERADO, PROCESANDO, AFINIDAD, ERROR]);
    const destinos = filas().map((f) => {
      const boton = f.querySelector<HTMLAnchorElement>('.acciones a.boton')!;
      return [boton.textContent?.trim(), boton.getAttribute('href')];
    });
    expect(destinos).toEqual([
      ['Ver el reporte', '/videos/7/reporte'],
      ['Ver el SOP', '/videos/8/sop'],
      ['Ver el avance', '/videos/9/procesando'],
      ['Ver el aviso', '/videos/10/reporte'],
      ['Ver el error', '/videos/11/procesando'],
    ]);
    expect(filas()[0].querySelector('a.titulo')?.getAttribute('href')).toBe('/videos/7/reporte');
  });

  it('afinidad baja lo dice y solo lleva al aviso: no continúa desde la lista', async () => {
    await llega([AFINIDAD]);
    const fila = filas()[0];
    expect(fila.querySelector('.estado')?.textContent).toContain(
      'el video parece no corresponder a su SOP',
    );
    const botones = Array.from(fila.querySelectorAll('button')).map((b) => b.textContent?.trim());
    expect(botones.some((b) => b?.includes('Continuar'))).toBe(false);
    expect(botones).not.toContain('Publicar');
  });

  it('filtra por texto sin acentos, modo, estado y SOP, y quita los filtros', async () => {
    await llega([VALIDADO, GENERADO, ERROR]);
    const buscar = pantalla().querySelector<HTMLInputElement>('#buscar-video')!;
    buscar.value = 'VALVULA';
    buscar.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(titulos()).toEqual(['Limpieza del filtro de agua']);

    buscar.value = '';
    buscar.dispatchEvent(new Event('input'));
    elegir('#filtro-modo', 'generar');
    expect(titulos()).toEqual(['Arranque de la bomba']);

    elegir('#filtro-modo', 'todos');
    elegir('#filtro-estado', 'error');
    expect(titulos()).toEqual(['Prueba sin modelo']);

    elegir('#filtro-estado', 'todos');
    const opciones = Array.from(
      pantalla().querySelectorAll<HTMLOptionElement>('#filtro-sop option'),
    ).map((o) => o.textContent?.trim());
    expect(opciones).toEqual([
      'Todos',
      'SOP-0003 · Mantenimiento de la válvula',
      'SOP-0009 · Arranque de la bomba',
    ]);
    elegir('#filtro-sop', '9');
    expect(titulos()).toEqual(['Arranque de la bomba']);
    expect(pantalla().querySelector('.conteo')?.textContent).toContain('1 de 3 videos');

    (pantalla().querySelector('.conteo button') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(titulos()).toHaveLength(3);
  });

  it('publica un video listo y muestra las palabras indexadas; luego lo quita', async () => {
    await llega([VALIDADO, PROCESANDO]);
    expect(filas()[1].querySelector('button.publicar')).toBeNull(); // no está listo
    const boton = () => filas()[0].querySelector<HTMLButtonElement>('button.publicar')!;
    expect(boton().textContent?.trim()).toBe('Publicar');

    boton().click();
    fixture.detectChanges();
    expect(boton().disabled).toBe(true);
    const pedido = http.expectOne('/api/videos/7/publicar');
    expect(pedido.request.method).toBe('POST');
    const publicado: EstadoPublicacion = {
      video_id: 7,
      publicado: true,
      publicado_en: '2026-11-15T20:00:00Z',
      palabras_indexadas: 1234,
    };
    pedido.flush(publicado);
    fixture.detectChanges();

    expect(boton().textContent?.trim()).toBe('Quitar de la búsqueda');
    expect(filas()[0].querySelector('.aviso.hecho')?.textContent).toContain(
      'Publicado: 1,234 palabras indexadas',
    );
    expect(filas()[0].querySelector('.publicado')?.textContent).toContain('Publicado');

    boton().click();
    const quitar = http.expectOne('/api/videos/7/publicar');
    expect(quitar.request.method).toBe('DELETE');
    quitar.flush({ video_id: 7, publicado: false, publicado_en: null, palabras_indexadas: 0 });
    fixture.detectChanges();
    expect(boton().textContent?.trim()).toBe('Publicar');
    expect(filas()[0].querySelector('.aviso.hecho')?.textContent).toContain(
      'Quitado de la búsqueda',
    );
  });

  it('un 409 al publicar muestra el detail de la API en ámbar y vuelve a pedir la lista', async () => {
    await llega([VALIDADO]);
    filas()[0].querySelector<HTMLButtonElement>('button.publicar')!.click();
    http.expectOne('/api/videos/7/publicar').flush(
      {
        detail: {
          mensaje: 'el análisis no ha terminado: publica el video cuando esté listo',
          proceso: 'procesando',
        },
      },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();

    const aviso = filas()[0].querySelector('.aviso')!;
    expect(aviso.classList).toContain('conflicto');
    expect(aviso.getAttribute('role')).toBe('alert');
    expect(aviso.textContent?.trim()).toBe(
      'El análisis no ha terminado: publica el video cuando esté listo.',
    );
    await llega([{ ...VALIDADO, proceso: 'procesando' }]);
    expect(filas()[0].querySelector('button.publicar')).toBeNull();
  });

  describe('eliminar', () => {
    const eliminar = (fila: HTMLElement) =>
      fila.querySelector<HTMLButtonElement>('button[aria-label^="Eliminar"]');
    const boton = (selector: string) => pantalla().querySelector<HTMLButtonElement>(selector)!;
    const confirmar = () =>
      Array.from(pantalla().querySelectorAll<HTMLButtonElement>('button.peligro'))[0];

    it('pide confirmación, elimina el video y dice que también se fue su SOP', async () => {
      await llega([VALIDADO, GENERADO]);
      eliminar(filas()[1])!.click();
      fixture.detectChanges();
      expect(filas()[1].querySelector('.confirmar')?.textContent).toContain(
        'y el SOP generado si nadie más lo usa',
      );
      http.expectNone('/api/videos/8'); // todavía no se pidió nada

      confirmar().click();
      fixture.detectChanges();
      const pedido = http.expectOne('/api/videos/8');
      expect(pedido.request.method).toBe('DELETE');
      pedido.flush({
        id: 8,
        sop_eliminado: { id: 9, codigo: 'SOP-0009', titulo: 'Arranque de la bomba' },
        sop_conservado: null,
      });
      fixture.detectChanges();

      expect(titulos()).toEqual(['Limpieza del filtro de agua']);
      const aviso = pantalla().querySelector('.aviso.hecho')!.textContent;
      expect(aviso).toContain('«Arranque de la bomba» eliminado.');
      expect(aviso).toContain('También se eliminó el SOP SOP-0009.');
    });

    it('cancelar no pide nada; un video en proceso no ofrece eliminar', async () => {
      await llega([VALIDADO, PROCESANDO]);
      expect(eliminar(filas()[1])).toBeNull();
      eliminar(filas()[0])!.click();
      fixture.detectChanges();
      Array.from(pantalla().querySelectorAll<HTMLButtonElement>('.confirmar button'))
        .find((b) => b.textContent?.trim() === 'Cancelar')!
        .click();
      fixture.detectChanges();
      expect(eliminar(filas()[0])).not.toBeNull();
      expect(pantalla().querySelector('.confirmar')).toBeNull();
      expect(boton('li.video')).toBeTruthy();
    });

    it('un 409 se muestra en ámbar, conserva la fila y vuelve a pedir la lista', async () => {
      await llega([VALIDADO]);
      eliminar(filas()[0])!.click();
      fixture.detectChanges();
      confirmar().click();
      http.expectOne('/api/videos/7').flush(
        {
          detail: {
            mensaje: 'el video está en proceso: espera a que termine para eliminarlo',
            proceso: 'procesando',
          },
        },
        { status: 409, statusText: 'Conflict' },
      );
      fixture.detectChanges();

      const aviso = filas()[0].querySelector('.aviso')!;
      expect(aviso.classList).toContain('conflicto');
      await llega([{ ...VALIDADO, proceso: 'procesando' }]);
      expect(eliminar(filas()[0])).toBeNull();
    });
  });

  it('descargas con el PDF solo con el video listo', async () => {
    await llega([VALIDADO, GENERADO, AFINIDAD, ERROR]);
    const opciones = (fila: HTMLElement) =>
      Array.from(fila.querySelectorAll<HTMLAnchorElement>('app-descargas a.opcion')).map((a) => [
        a.querySelector('.etiqueta')?.textContent?.trim(),
        a.getAttribute('href'),
      ]);
    const [validado, generado, afinidad, error] = filas();
    expect(opciones(validado)).toContainEqual(['Reporte (.pdf)', '/api/videos/7/pdf']);
    expect(opciones(generado)).toContainEqual(['SOP (.pdf)', '/api/videos/8/pdf']);
    expect(opciones(afinidad).map(([e]) => e)).toEqual([
      'Transcripción (.txt)',
      'Subtítulos (.srt)',
      'Análisis (.json)',
    ]);
    expect(error.querySelector('app-descargas')).toBeNull();
  });

  it('sin videos invita a Nuevo análisis', async () => {
    await llega([]);
    const vacia = pantalla().querySelector('.vacia')!;
    expect(vacia.textContent).toContain('Todavía no hay videos');
    expect(vacia.querySelector('a')?.getAttribute('href')).toBe('/nuevo');
  });

  it('si no carga lo dice y se puede reintentar', async () => {
    http.expectOne(LISTA).flush(null, { status: 500, statusText: 'Error' });
    await fixture.whenStable();
    expect(pantalla().querySelector('.error')?.textContent).toContain(
      'No se pudo leer la lista de videos',
    );
    (pantalla().querySelector('.error button') as HTMLButtonElement).click();
    await llega([VALIDADO]);
    expect(filas()).toHaveLength(1);
  });

  describe('refresco', () => {
    it('con un video en proceso pide la lista cada 3 s y se detiene cuando ninguno queda', async () => {
      await llega([PROCESANDO, VALIDADO]);
      expect(pantalla().querySelector('.conteo')?.textContent).toContain('1 en proceso');

      await vi.advanceTimersByTimeAsync(SONDEO_VIDEOS_MS - 100);
      http.expectNone(LISTA);
      await vi.advanceTimersByTimeAsync(100);
      await llega([{ ...PROCESANDO, etapa: 'emparejamiento' }, VALIDADO]);
      expect(filas()[0].querySelector('.estado')?.textContent).toContain('Emparejamiento');

      await vi.advanceTimersByTimeAsync(SONDEO_VIDEOS_MS);
      await llega([
        { ...PROCESANDO, proceso: 'listo', cumplimiento: 91.67, semaforo: 'amarillo' },
        VALIDADO,
      ]);
      expect(filas()[0].querySelector('.cumplimiento')?.textContent).toContain('91.67 %');

      await vi.advanceTimersByTimeAsync(SONDEO_VIDEOS_MS * 3);
      http.expectNone(LISTA);
    });

    it('sin videos en proceso no consulta otra vez', async () => {
      await llega([VALIDADO]);
      await vi.advanceTimersByTimeAsync(SONDEO_VIDEOS_MS * 3);
      http.expectNone(LISTA);
    });

    it('se detiene al salir de la pantalla', async () => {
      await llega([PROCESANDO]);
      fixture.destroy();
      await vi.advanceTimersByTimeAsync(SONDEO_VIDEOS_MS * 3);
      http.expectNone(LISTA);
    });

    it('nunca encima dos consultas: espera la respuesta antes de pedir otra', async () => {
      await llega([PROCESANDO]);
      await vi.advanceTimersByTimeAsync(SONDEO_VIDEOS_MS * 3);
      const pendientes = http.match(LISTA);
      expect(pendientes).toHaveLength(1);
      pendientes[0].flush([{ ...PROCESANDO, proceso: 'listo' }]);
      await fixture.whenStable();
    });
  });
});
