import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RespuestaBusqueda } from '../api/busqueda';
import { OpcionesBusqueda } from '../api/busqueda-opciones';
import { Buscar } from './buscar';

const OPCIONES_URL = '/api/buscar/opciones';
const BUSCAR_URL = '/api/buscar';

const OPCIONES: OpcionesBusqueda = {
  videos: [
    { id: 5, titulo: 'Limpieza del filtro de agua', sop_id: 3 },
    { id: 6, titulo: 'Arranque de la bomba', sop_id: 9 },
  ],
  sops: [
    { id: 3, codigo: 'SOP-0003', titulo: 'Mantenimiento de la válvula' },
    { id: 9, codigo: 'SOP-0009', titulo: 'Arranque de la bomba' },
  ],
};

const RESPUESTA: RespuestaBusqueda = {
  consulta: 'valvula',
  consulta_normalizada: 'valvula',
  total: 2,
  milisegundos: 3.2,
  resultados: [
    {
      video: { id: 5, titulo: 'Limpieza del filtro de agua' },
      sop: { id: 3, codigo: 'SOP-0003', titulo: 'Mantenimiento de la válvula' },
      t_inicio: 74.2,
      t_fin: 74.9,
      miniatura: '/videos/5/thumb?t=74.20',
      // frase[14:21] en Python es "válvula".
      frase: 'luego abre la válvula, de alivio',
      rango: [14, 21],
      recorte_inicio: true,
      recorte_fin: false,
      coincidencias: 2,
    },
    {
      video: { id: 6, titulo: 'Arranque de la bomba' },
      sop: null,
      t_inicio: 42,
      t_fin: 42.6,
      miniatura: null,
      frase: 'cierra la <b>válvula</b> y espera',
      rango: [13, 20],
      recorte_inicio: false,
      recorte_fin: true,
      coincidencias: 1,
    },
  ],
};

const SIN_RESULTADOS: RespuestaBusqueda = {
  consulta: 'carcaza',
  consulta_normalizada: 'carcaza',
  total: 0,
  milisegundos: 1,
  resultados: [],
};

describe('Buscar', () => {
  let fixture: ComponentFixture<Buscar>;
  let http: HttpTestingController;

  beforeEach(async () => {
    sessionStorage.clear();
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    TestBed.configureTestingModule({
      imports: [Buscar],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = await crear();
  });

  afterEach(() => {
    http.verify();
    vi.restoreAllMocks();
  });

  async function crear(opciones: OpcionesBusqueda = OPCIONES): Promise<ComponentFixture<Buscar>> {
    const nuevo = TestBed.createComponent(Buscar);
    await nuevo.whenStable();
    http.expectOne(OPCIONES_URL).flush(opciones);
    await nuevo.whenStable();
    return nuevo;
  }

  const pantalla = () => fixture.nativeElement as HTMLElement;
  const caja = () => pantalla().querySelector<HTMLInputElement>('#consulta')!;
  const burbujas = (clase: 'persona' | 'sistema') =>
    Array.from(pantalla().querySelectorAll<HTMLElement>(`.burbuja.${clase}`));
  const resultados = () => Array.from(pantalla().querySelectorAll<HTMLElement>('button.resultado'));

  async function escribir(texto: string): Promise<void> {
    caja().value = texto;
    caja().dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  /** Escribe y envía con Enter (el `submit` del formulario) y devuelve el POST. */
  async function buscar(texto: string): Promise<TestRequest> {
    await escribir(texto);
    pantalla()
      .querySelector('form')!
      .dispatchEvent(new Event('submit', { cancelable: true }));
    await fixture.whenStable();
    return http.expectOne(BUSCAR_URL);
  }

  async function responder(pedido: TestRequest, respuesta: RespuestaBusqueda): Promise<void> {
    pedido.flush(respuesta);
    await fixture.whenStable();
  }

  async function elegir(etiqueta: string, valor: string): Promise<void> {
    const select = pantalla().querySelector<HTMLSelectElement>(`select[aria-label="${etiqueta}"]`)!;
    select.value = valor;
    select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
  }

  it('Enter envía la consulta, la muestra como burbuja y el foco vuelve a la caja', async () => {
    const enviar = pantalla().querySelector<HTMLButtonElement>('button.enviar')!;
    expect(enviar.disabled).toBe(true);

    const pedido = await buscar('  valvula ');
    expect(pedido.request.method).toBe('POST');
    expect(pedido.request.body).toEqual({ consulta: 'valvula' });
    expect(burbujas('persona')[0].querySelector('.consulta')?.textContent).toBe('valvula');
    expect(burbujas('sistema')[0].textContent).toContain('Buscando…');
    expect(caja().value).toBe('');
    expect(document.activeElement).toBe(caja());

    await responder(pedido, RESPUESTA);
    expect(burbujas('sistema')[0].textContent).toContain('2 coincidencias en 2 videos.');
    expect(resultados()).toHaveLength(2);
  });

  it('cada resultado: título, mm:ss, la frase con la coincidencia resaltada y ×N', async () => {
    await responder(await buscar('valvula'), RESPUESTA);
    const [primero, segundo] = resultados();

    expect(primero.querySelector('.titulo')?.textContent).toBe('Limpieza del filtro de agua');
    expect(primero.querySelector('.segundo')?.textContent).toBe('01:14');
    const frase = primero.querySelector('.frase')!;
    expect(frase.querySelector('mark')?.textContent).toBe('válvula');
    // Sin espacios de más alrededor de la marca y con "…" donde la frase sigue.
    expect(frase.textContent).toBe('…luego abre la válvula, de alivio');
    expect(primero.querySelector('.unidas')?.textContent).toBe('×2');
    expect(primero.querySelector('.unidas')?.getAttribute('aria-label')).toBe(
      '2 coincidencias unidas',
    );

    // El texto del servidor nunca se interpreta como HTML.
    const otra = segundo.querySelector('.frase')!;
    expect(otra.querySelector('b')).toBeNull();
    expect(otra.querySelector('mark')?.textContent).toBe('válvula');
    expect(otra.textContent).toBe('cierra la <b>válvula</b> y espera…');
    expect(segundo.querySelector('.unidas')).toBeNull();
  });

  it('miniatura con carga diferida; sin imagen o si falla, la tarjeta no deja hueco', async () => {
    await responder(await buscar('valvula'), RESPUESTA);
    const [primero, segundo] = resultados();
    const img = primero.querySelector('img.miniatura')!;
    expect(img.getAttribute('loading')).toBe('lazy');
    expect(img.getAttribute('src')).toBe('/api/videos/5/thumb?t=74.20');
    expect(segundo.querySelector('img')).toBeNull();

    img.dispatchEvent(new Event('error'));
    await fixture.whenStable();
    expect(resultados()[0].querySelector('img')).toBeNull();
    expect(resultados()[0].querySelector('.titulo')).not.toBeNull();
  });

  it('al elegir un resultado el video aparece aquí y salta a ese segundo', async () => {
    await responder(await buscar('valvula'), RESPUESTA);
    expect(pantalla().querySelector('app-reproductor')).toBeNull();

    resultados()[0].click();
    await fixture.whenStable();
    const video = () => pantalla().querySelector<HTMLVideoElement>('app-reproductor video')!;
    expect(video().getAttribute('src')).toBe('/api/videos/5/video');
    expect(resultados()[0].classList).toContain('activo');
    let actual = 0;
    Object.defineProperty(video(), 'currentTime', {
      configurable: true,
      get: () => actual,
      set: (valor: number) => (actual = valor),
    });
    video().dispatchEvent(new Event('loadedmetadata'));
    expect(video().currentTime).toBe(74.2);
    expect(pantalla().querySelector('.visor-pie')?.textContent).toContain('01:14');

    // "Ver SOP": el PDF del SOP en otra pestaña, para verlo (inline), no para descargarlo.
    const sop = pantalla().querySelector<HTMLAnchorElement>('a.ver-sop')!;
    expect(sop.getAttribute('href')).toBe('/api/sops/3/pdf?ver=true');
    expect(sop.getAttribute('target')).toBe('_blank');
    expect(sop.getAttribute('rel')).toBe('noopener');

    // Otro video: cambia el archivo y salta al segundo de ese resultado; sin SOP no hay enlace.
    resultados()[1].click();
    await fixture.whenStable();
    expect(video().getAttribute('src')).toBe('/api/videos/6/video');
    Object.defineProperty(video(), 'currentTime', {
      configurable: true,
      get: () => actual,
      set: (valor: number) => (actual = valor),
    });
    video().dispatchEvent(new Event('loadedmetadata'));
    expect(actual).toBe(42);
    expect(pantalla().querySelector('a.ver-sop')).toBeNull();
  });

  it('no enlaza a la vista de carga: solo a archivos de la API', async () => {
    await responder(await buscar('valvula'), RESPUESTA);
    resultados()[0].click();
    await fixture.whenStable();
    const enlaces = Array.from(pantalla().querySelectorAll('a[href]')).map((a) =>
      a.getAttribute('href'),
    );
    expect(enlaces.length).toBeGreaterThan(0);
    for (const href of enlaces) {
      expect(href).toMatch(/^\/api\//);
    }
    expect(pantalla().querySelector('[routerlink], [ng-reflect-router-link]')).toBeNull();
  });

  it('el historial sobrevive a salir y volver; Repetir y Limpiar', async () => {
    await responder(await buscar('valvula'), RESPUESTA);
    fixture.destroy();

    fixture = await crear();
    expect(burbujas('persona').map((b) => b.querySelector('.consulta')?.textContent)).toEqual([
      'valvula',
    ]);
    expect(resultados()).toHaveLength(2);

    burbujas('persona')[0].querySelector<HTMLButtonElement>('button.repetir')!.click();
    await fixture.whenStable();
    const otra = http.expectOne(BUSCAR_URL);
    expect(otra.request.body).toEqual({ consulta: 'valvula' });
    expect(document.activeElement).toBe(caja());
    await responder(otra, SIN_RESULTADOS);
    expect(burbujas('persona')).toHaveLength(2);

    pantalla().querySelector<HTMLButtonElement>('button.limpiar')!.click();
    await fixture.whenStable();
    expect(burbujas('persona')).toHaveLength(0);
    expect(resultados()).toHaveLength(0);
    expect(document.activeElement).toBe(caja());
  });

  it('filtros por SOP y por video como chips; van en el POST y en la burbuja', async () => {
    await elegir('Filtrar por SOP', '3');
    const chips = () =>
      Array.from(pantalla().querySelectorAll('.filtros .chip')).map((c) =>
        c.textContent?.replace('×', '').trim(),
      );
    expect(chips()).toEqual(['SOP: SOP-0003 · Mantenimiento de la válvula']);
    // Con un SOP elegido, el selector de video solo ofrece sus videos.
    const videos = Array.from(
      pantalla().querySelectorAll<HTMLOptionElement>(
        'select[aria-label="Filtrar por video"] option',
      ),
    ).map((o) => o.textContent?.trim());
    expect(videos).toEqual(['+ Video', 'Limpieza del filtro de agua']);
    await elegir('Filtrar por video', '5');
    expect(chips()).toEqual([
      'SOP: SOP-0003 · Mantenimiento de la válvula',
      'Video: Limpieza del filtro de agua',
    ]);

    const pedido = await buscar('carcaza');
    expect(pedido.request.body).toEqual({ consulta: 'carcaza', video_id: 5, sop_id: 3 });
    await responder(pedido, SIN_RESULTADOS);
    const persona = burbujas('persona')[0];
    expect(persona.querySelectorAll('.chip')).toHaveLength(2);
    expect(burbujas('sistema')[0].textContent).toContain(
      'No encontré «carcaza». Revisa la ortografía o quita los filtros.',
    );

    // Quitar los filtros: la siguiente búsqueda es en todo y su burbuja no lleva chips.
    Array.from(pantalla().querySelectorAll<HTMLButtonElement>('.filtros button'))
      .find((b) => b.textContent?.trim() === 'Quitar filtros')!
      .click();
    await fixture.whenStable();
    expect(chips()).toEqual([]);
    const todo = await buscar('carcaza');
    expect(todo.request.body).toEqual({ consulta: 'carcaza' });
    await responder(todo, SIN_RESULTADOS);
    expect(burbujas('persona')[1].querySelector('.chip')).toBeNull();
    expect(burbujas('sistema')[1].textContent).toContain(
      'No encontré «carcaza». Revisa la ortografía.',
    );
  });

  it('sin videos publicados lo avisa, sin filtros ni enlaces', async () => {
    fixture.destroy();
    fixture = await crear({ videos: [], sops: [] });
    const aviso = pantalla().querySelector('.aviso-publicados')!;
    expect(aviso.textContent).toContain('Todavía no hay videos publicados');
    expect(pantalla().querySelector('.filtros')).toBeNull();
    expect(pantalla().querySelectorAll('a')).toHaveLength(0);

    await responder(await buscar('valvula'), { ...SIN_RESULTADOS, consulta: 'valvula' });
    expect(burbujas('sistema')[0].textContent).toContain(
      'No encontré «valvula»: todavía no hay videos publicados.',
    );
  });

  it('un error de la API se dice en el chat y se puede reintentar', async () => {
    const pedido = await buscar('valvula');
    pedido.flush(null, { status: 500, statusText: 'Error' });
    await fixture.whenStable();
    const sistema = burbujas('sistema')[0];
    expect(sistema.classList).toContain('fallo');
    expect(sistema.textContent).toContain('Error de la API (HTTP 500)');

    sistema.querySelector<HTMLButtonElement>('button')!.click();
    await fixture.whenStable();
    const otra = http.expectOne(BUSCAR_URL);
    expect(otra.request.body).toEqual({ consulta: 'valvula' });
    await responder(otra, RESPUESTA);
    expect(burbujas('sistema')).toHaveLength(1);
    expect(burbujas('sistema')[0].textContent).toContain('2 coincidencias');
    expect(resultados()).toHaveLength(2);
  });

  it('un 400 (solo signos) muestra la frase de la API', async () => {
    const pedido = await buscar('¿?');
    pedido.flush(
      {
        detail: 'La consulta no tiene palabras que buscar: escribe al menos una palabra o número.',
      },
      { status: 400, statusText: 'Bad Request' },
    );
    await fixture.whenStable();
    expect(burbujas('sistema')[0].textContent).toContain(
      'La consulta no tiene palabras que buscar: escribe al menos una palabra o número.',
    );
  });

  it('si no cargan los filtros, la búsqueda sigue en todo', async () => {
    fixture.destroy();
    const otro = TestBed.createComponent(Buscar);
    await otro.whenStable();
    http.expectOne(OPCIONES_URL).flush(null, { status: 500, statusText: 'Error' });
    await otro.whenStable();
    fixture = otro;
    expect(pantalla().querySelector('.nota-filtros')?.textContent).toContain(
      'No se pudieron cargar los filtros',
    );
    expect(pantalla().querySelector('.filtros')).toBeNull();
    const pedido = await buscar('valvula');
    expect(pedido.request.body).toEqual({ consulta: 'valvula' });
    pedido.flush(RESPUESTA);
  });
});
