import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { EstadoSop, SopResumen } from '../api/tipos';
import { SONDEO_SOP_MS } from '../nuevo/nuevo';
import { Biblioteca } from './biblioteca';
import { coincide, normalizar } from './filtro';

const CARGADO: SopResumen = {
  id: 7,
  codigo: 'SOP-0007',
  titulo: 'Limpieza de la válvula de alivio',
  origen: 'cargado',
  creado: '2026-11-10T10:00:00Z',
  videos_validados: 2,
};
const GENERADO: SopResumen = {
  id: 8,
  codigo: 'SOP-0008',
  titulo: 'Arranque de la bomba',
  origen: 'generado',
  creado: '2026-11-11T10:00:00Z',
  videos_validados: 1,
};
const OK = { status: 200, statusText: 'OK' };
const SOP_EN_COLA: EstadoSop = {
  id: 9,
  codigo: 'SOP-0009',
  estado: 'en_cola',
  titulo: null,
  metodo: null,
  mensaje: null,
  advertencias: [],
};

describe('Biblioteca', () => {
  let fixture: ComponentFixture<Biblioteca>;
  let http: HttpTestingController;

  beforeEach(async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    TestBed.configureTestingModule({
      imports: [Biblioteca],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Biblioteca);
    await fixture.whenStable();
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  async function flush(req: TestRequest, cuerpo: unknown, estado = OK): Promise<void> {
    req.flush(cuerpo as object, estado);
    await fixture.whenStable();
  }

  async function lista(sops: SopResumen[]): Promise<void> {
    await flush(http.expectOne({ method: 'GET', url: '/api/sops' }), sops);
  }

  function raiz(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function texto(): string {
    return raiz().textContent ?? '';
  }

  function filas(): HTMLElement[] {
    return Array.from(raiz().querySelectorAll<HTMLElement>('li.sop'));
  }

  function fila(codigo: string): HTMLElement {
    return filas().find((f) => f.textContent?.includes(codigo))!;
  }

  function botonEn(contenedor: HTMLElement, etiqueta: string): HTMLButtonElement {
    return Array.from(contenedor.querySelectorAll('button')).find((b) =>
      b.textContent?.includes(etiqueta),
    )!;
  }

  async function clic(boton: HTMLElement): Promise<void> {
    boton.click();
    await fixture.whenStable();
  }

  async function escribir(selector: string, valor: string, evento = 'input'): Promise<void> {
    const control = raiz().querySelector<HTMLInputElement | HTMLSelectElement>(selector)!;
    control.value = valor;
    control.dispatchEvent(new Event(evento));
    await fixture.whenStable();
  }

  async function subir(...archivos: File[]): Promise<void> {
    const input = raiz().querySelector<HTMLInputElement>('#subir-sop')!;
    Object.defineProperty(input, 'files', {
      configurable: true,
      value: { item: (i: number) => archivos[i] ?? null, length: archivos.length },
    });
    input.dispatchEvent(new Event('change'));
    await fixture.whenStable();
  }

  it('lista los SOP con código, título, origen, fecha, validados y sus acciones', async () => {
    await lista([GENERADO, CARGADO]);
    expect(filas()).toHaveLength(2);
    const f = fila('SOP-0007');
    expect(f.textContent).toContain('Limpieza de la válvula de alivio');
    expect(f.textContent).toContain('Cargado');
    expect(f.textContent).toContain('2 videos validados');
    expect(f.querySelector('time')!.getAttribute('datetime')).toBe(CARGADO.creado);
    expect(fila('SOP-0008').textContent).toContain('Generado desde un video');
    expect(fila('SOP-0008').textContent).toContain('1 video validado');

    const enlaces = Array.from(f.querySelectorAll('a')).map((a) => [
      a.textContent?.trim(),
      a.getAttribute('href'),
    ]);
    expect(enlaces).toEqual([
      ['Ver o editar', '/sops/7'],
      ['Usar para validar', '/nuevo?sop=7'],
    ]);
    expect(texto()).toContain('2 de 2 SOP');
  });

  it('busca por título o código sin importar acentos ni mayúsculas', async () => {
    await lista([GENERADO, CARGADO]);
    await escribir('#buscar', 'VALVULA');
    expect(filas().map((f) => f.querySelector('.codigo')!.textContent)).toEqual(['SOP-0007']);
    await escribir('#buscar', '0008');
    expect(filas().map((f) => f.querySelector('.codigo')!.textContent)).toEqual(['SOP-0008']);
    expect(texto()).toContain('1 de 2 SOP');
    await escribir('#buscar', 'no existe');
    expect(filas()).toHaveLength(0);
    expect(texto()).toContain('Ningún SOP coincide con la búsqueda.');
  });

  it('filtra por origen', async () => {
    await lista([GENERADO, CARGADO]);
    await escribir('#origen', 'generado', 'change');
    expect(filas().map((f) => f.querySelector('.codigo')!.textContent)).toEqual(['SOP-0008']);
    await escribir('#origen', 'cargado', 'change');
    expect(filas().map((f) => f.querySelector('.codigo')!.textContent)).toEqual(['SOP-0007']);
    await escribir('#origen', 'todos', 'change');
    expect(filas()).toHaveLength(2);
  });

  it('vacía, invita a subir o generar uno', async () => {
    await lista([]);
    expect(texto()).toContain('Todavía no hay SOP');
    expect(raiz().querySelector('.vacia a')!.getAttribute('href')).toBe('/nuevo');
  });

  it('si la lista falla, lo dice y deja reintentar', async () => {
    await flush(http.expectOne('/api/sops'), { detail: 'x' }, { status: 500, statusText: 'Error' });
    expect(texto()).toContain('No se pudo leer la biblioteca.');
    await clic(botonEn(raiz(), 'Reintentar'));
    await lista([CARGADO]);
    expect(filas()).toHaveLength(1);
  });

  it('eliminar pide confirmación en la fila y, con 204, la quita', async () => {
    await lista([GENERADO, CARGADO]);
    await clic(botonEn(fila('SOP-0007'), 'Eliminar'));
    expect(fila('SOP-0007').textContent).toContain('¿Eliminar SOP-0007?');
    // Un SOP cargado: la persona sabe que también se borra el archivo, no solo la fila.
    expect(fila('SOP-0007').textContent).toContain('también el archivo original que se subió');
    expect(fila('SOP-0007').textContent).toContain('No se puede deshacer.');
    http.expectNone({ method: 'DELETE' });

    await clic(botonEn(fila('SOP-0007'), 'Cancelar'));
    expect(fila('SOP-0007').textContent).not.toContain('¿Eliminar');
    http.expectNone({ method: 'DELETE' });

    await clic(botonEn(fila('SOP-0007'), 'Eliminar'));
    await clic(botonEn(fila('SOP-0007'), 'Sí, eliminar'));
    const req = http.expectOne({ method: 'DELETE', url: '/api/sops/7' });
    await flush(req, null, { status: 204, statusText: 'No Content' });
    expect(filas().map((f) => f.querySelector('.codigo')!.textContent)).toEqual(['SOP-0008']);
    expect(raiz().querySelector('[role=status].sr-only')!.textContent).toContain(
      'SOP-0007 eliminado.',
    );
  });

  it('un SOP generado no promete borrar un archivo que no tiene', async () => {
    await lista([GENERADO]);
    await clic(botonEn(fila('SOP-0008'), 'Eliminar'));
    expect(fila('SOP-0008').textContent).toContain('Se borra de la biblioteca.');
    expect(fila('SOP-0008').textContent).not.toContain('archivo original');
    await clic(botonEn(fila('SOP-0008'), 'Cancelar'));
  });

  it('con 409 explica en la fila por qué no se puede eliminar, en ámbar', async () => {
    await lista([CARGADO]);
    await clic(botonEn(fila('SOP-0007'), 'Eliminar'));
    await clic(botonEn(fila('SOP-0007'), 'Sí, eliminar'));
    await flush(
      http.expectOne({ method: 'DELETE', url: '/api/sops/7' }),
      {
        detail: {
          mensaje:
            'El SOP SOP-0007 no se puede eliminar: 2 videos lo usan como referencia y sus 2 reportes dependen de él.',
          videos: 2,
          reportes: 2,
        },
      },
      { status: 409, statusText: 'Conflict' },
    );
    const aviso = fila('SOP-0007').querySelector('.aviso')!;
    expect(aviso.classList).toContain('conflicto');
    expect(aviso.textContent).toBe(
      'El SOP SOP-0007 no se puede eliminar: 2 videos lo usan como referencia y sus 2 reportes dependen de él.',
    );
    expect(aviso.textContent).not.toContain('HTTP');
    expect(filas()).toHaveLength(1);
  });

  it('otro error al eliminar sale como error, no como conflicto', async () => {
    await lista([CARGADO]);
    await clic(botonEn(fila('SOP-0007'), 'Eliminar'));
    await clic(botonEn(fila('SOP-0007'), 'Sí, eliminar'));
    await flush(http.expectOne({ method: 'DELETE' }), null, { status: 0, statusText: '' });
    const aviso = fila('SOP-0007').querySelector('.aviso')!;
    expect(aviso.classList).not.toContain('conflicto');
    expect(aviso.textContent).toContain('No se pudo eliminar SOP-0007.');
  });

  it('"Subir SOP" deja una fila con la conversión hasta que termina y luego recarga', async () => {
    await lista([CARGADO]);
    await subir(new File(['# SOP'], 'arranque.pdf'));
    expect(raiz().querySelector('.subida')!.textContent).toContain('Subiendo…');

    const post = http.expectOne({ method: 'POST', url: '/api/sops' });
    expect((post.request.body as FormData).get('archivo')).toBeInstanceOf(File);
    await flush(post, SOP_EN_COLA, { status: 202, statusText: 'Accepted' });
    expect(raiz().querySelector('.subida')!.textContent).toContain(
      'SOP-0009 · En cola para convertir…',
    );

    await vi.advanceTimersByTimeAsync(SONDEO_SOP_MS);
    await flush(http.expectOne('/api/sops/9/estado'), { ...SOP_EN_COLA, estado: 'convirtiendo' });
    expect(raiz().querySelector('.subida')!.textContent).toContain('Convirtiendo…');

    await vi.advanceTimersByTimeAsync(SONDEO_SOP_MS);
    await flush(http.expectOne('/api/sops/9/estado'), {
      ...SOP_EN_COLA,
      estado: 'listo',
      titulo: 'Arranque en frío',
      metodo: 'llm',
    });
    expect(raiz().querySelector('.subida')).toBeNull();
    await lista([
      { ...CARGADO, id: 9, codigo: 'SOP-0009', titulo: 'Arranque en frío', videos_validados: 0 },
      CARGADO,
    ]);
    const nueva = fila('SOP-0009');
    expect(nueva.classList).toContain('nuevo');
    expect(nueva.textContent).toContain('Nuevo');
    expect(nueva.textContent).toContain('lo convirtió el modelo');
    expect(nueva.querySelector('.revisar a')!.getAttribute('href')).toBe('/sops/9');
    // Terminó: no hay más consultas.
    await vi.advanceTimersByTimeAsync(3 * SONDEO_SOP_MS);
    http.expectNone('/api/sops/9/estado');
  });

  it('si la conversión falla, muestra el mensaje y "Descartar" borra el SOP en error', async () => {
    await lista([]);
    await subir(new File(['%PDF'], 'escaneado.pdf'));
    await flush(http.expectOne({ method: 'POST', url: '/api/sops' }), SOP_EN_COLA, {
      status: 202,
      statusText: 'Accepted',
    });
    await vi.advanceTimersByTimeAsync(SONDEO_SOP_MS);
    await flush(http.expectOne('/api/sops/9/estado'), {
      ...SOP_EN_COLA,
      estado: 'error',
      mensaje: 'El PDF no tiene texto: súbelo en Markdown con la plantilla.',
    });
    const subida = raiz().querySelector<HTMLElement>('.subida')!;
    expect(subida.classList).toContain('fallo');
    expect(subida.textContent).toContain('No se pudo convertir');
    expect(subida.textContent).toContain('El PDF no tiene texto');

    await clic(botonEn(subida, 'Descartar'));
    await flush(http.expectOne({ method: 'DELETE', url: '/api/sops/9' }), null, {
      status: 204,
      statusText: 'No Content',
    });
    expect(raiz().querySelector('.subida')).toBeNull();
  });

  it('un archivo rechazado se descarta sin llamar a DELETE', async () => {
    await lista([]);
    await subir(new File(['x'], 'sop.xlsx'));
    await flush(
      http.expectOne({ method: 'POST', url: '/api/sops' }),
      { detail: 'extensión no permitida; usa .md, .txt, .pdf, .docx' },
      { status: 415, statusText: 'Unsupported Media Type' },
    );
    const subida = raiz().querySelector<HTMLElement>('.subida')!;
    expect(subida.textContent).toContain('No se pudo subir. Extensión no permitida');
    await clic(botonEn(subida, 'Descartar'));
    http.expectNone({ method: 'DELETE' });
    expect(raiz().querySelector('.subida')).toBeNull();
  });

  it('sube varios a la vez, cada uno con su fila', async () => {
    await lista([]);
    await subir(new File(['a'], 'a.md'), new File(['b'], 'b.md'));
    expect(raiz().querySelectorAll('.subida')).toHaveLength(2);
    const posts = http.match({ method: 'POST', url: '/api/sops' });
    expect(posts).toHaveLength(2);
    posts[0].flush(
      { ...SOP_EN_COLA, estado: 'error', mensaje: 'falló' },
      { status: 202, statusText: 'Accepted' },
    );
    posts[1].flush(
      { ...SOP_EN_COLA, id: 10, codigo: 'SOP-0010', estado: 'error', mensaje: 'falló' },
      { status: 202, statusText: 'Accepted' },
    );
    await fixture.whenStable();
    expect(raiz().querySelectorAll('.subida.fallo')).toHaveLength(2);
  });
});

describe('filtro', () => {
  it('normaliza acentos, mayúsculas y espacios', () => {
    expect(normalizar('  Válvula   de ALIVIO ')).toBe('valvula de alivio');
  });

  it('coincide por título o código; vacío coincide con todo', () => {
    expect(coincide(CARGADO, 'alivio')).toBe(true);
    expect(coincide(CARGADO, 'sop-0007')).toBe(true);
    expect(coincide(CARGADO, '')).toBe(true);
    expect(coincide(CARGADO, 'bomba')).toBe(false);
  });
});
