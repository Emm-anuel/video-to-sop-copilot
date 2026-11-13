import { HttpEventType, provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Subscription } from 'rxjs';
import { CamposVideo } from '../api/api.service';
import { EstadoSubida, VideoCreado } from '../api/tipos';
import { ErrorSubida, EventoSubida, SubidaPorPartes } from './subida.service';

const CAMPOS: CamposVideo = { titulo: 'Filtro', sopId: 7, analizarImagenes: true };
const VIDEO: VideoCreado = { id: 12, proceso: 'en_cola' };
const OK = { status: 200, statusText: 'OK' };
const SIN_RED = { status: 0, statusText: 'Unknown Error' };

describe('SubidaPorPartes', () => {
  let http: HttpTestingController;
  let servicio: SubidaPorPartes;
  let eventos: EventoSubida[];
  let error: unknown;
  let completo: boolean;
  let suscripcion: Subscription;
  /** 10 bytes en partes de 4: [0,4) [4,8) [8,10). */
  const archivo = new File(['0123456789'], 'operador.avi', { type: 'video/x-msvideo' });

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    servicio = TestBed.inject(SubidaPorPartes);
    eventos = [];
    error = undefined;
    completo = false;
  });

  afterEach(() => {
    suscripcion?.unsubscribe();
    http.verify();
    vi.useRealTimers();
  });

  function subir(uploadId?: string): void {
    suscripcion = servicio.subir(archivo, CAMPOS, uploadId).subscribe({
      next: (e) => eventos.push(e),
      error: (e: unknown) => (error = e),
      complete: () => (completo = true),
    });
  }

  /** Deja correr las promesas del servicio hasta la siguiente petición. */
  async function tic(ms = 0): Promise<void> {
    await vi.advanceTimersByTimeAsync(ms);
  }

  function estado(recibidos: number): EstadoSubida {
    return {
      upload_id: 'u1',
      tamano: 10,
      tamano_parte: 4,
      recibidos,
      completo: recibidos === 10,
    };
  }

  function parte(offset: number): TestRequest {
    return http.expectOne(
      (r) =>
        r.method === 'PUT' && r.url === '/api/uploads/u1' && r.params.get('offset') === `${offset}`,
    );
  }

  async function abrir(): Promise<void> {
    const req = http.expectOne({ method: 'POST', url: '/api/uploads' });
    expect(req.request.body).toEqual({ nombre: 'operador.avi', tamano: 10 });
    req.flush(estado(0), { status: 201, statusText: 'Created' });
    await tic();
  }

  async function aceptar(offset: number, recibidos: number): Promise<TestRequest> {
    const req = parte(offset);
    req.flush(estado(recibidos), OK);
    await tic();
    return req;
  }

  async function crearVideo(): Promise<FormData> {
    const req = http.expectOne({ method: 'POST', url: '/api/videos' });
    const datos = req.request.body as FormData;
    req.flush(VIDEO, { status: 202, statusText: 'Accepted' });
    await tic();
    return datos;
  }

  function enviados(): number[] {
    return eventos.flatMap((e) => (e.tipo === 'avance' ? [e.enviados] : []));
  }

  it('manda las tres partes en orden con Blob.slice y crea el video con upload_id', async () => {
    subir();
    await abrir();
    expect(eventos[0]).toEqual({ tipo: 'abierta', uploadId: 'u1', recibidos: 0, total: 10 });

    const primera = parte(0);
    expect(primera.request.body).toBeInstanceOf(Blob);
    expect(await (primera.request.body as Blob).text()).toBe('0123');
    expect(primera.request.headers.get('Content-Type')).toBe('application/octet-stream');
    expect(primera.request.reportProgress).toBe(true);
    primera.event({ type: HttpEventType.UploadProgress, loaded: 2, total: 4 });
    primera.flush(estado(4), OK);
    await tic();
    const segunda = parte(4);
    expect(await (segunda.request.body as Blob).text()).toBe('4567');
    segunda.flush(estado(8), OK);
    await tic();
    const tercera = parte(8);
    expect(await (tercera.request.body as Blob).text()).toBe('89');
    tercera.flush(estado(10), OK);
    await tic();

    const datos = await crearVideo();
    expect(datos.get('upload_id')).toBe('u1');
    expect(datos.get('modo')).toBe('validar');
    expect(datos.get('sop_id')).toBe('7');
    expect(datos.get('analizar_imagenes')).toBe('true');
    expect(datos.has('archivo')).toBe(false);
    expect(eventos.at(-1)).toEqual({ tipo: 'creado', video: VIDEO });
    expect(enviados()).toEqual([0, 2, 4, 8, 10]);
    expect(completo).toBe(true);
  });

  it('reintenta una parte con espera de 1, 2 y 4 s y reanuda desde lo que dice la API', async () => {
    subir();
    await abrir();
    await aceptar(0, 4);

    parte(4).error(new ProgressEvent('error'), SIN_RED);
    await tic();
    expect(eventos.at(-1)).toEqual({ tipo: 'reintento', intento: 1, esperaMs: 1000 });
    await tic(999);
    http.expectNone('/api/uploads/u1');
    await tic(1);
    // La parte sí había llegado (se perdió la respuesta): la API dice 8 y no se repite.
    http.expectOne({ method: 'GET', url: '/api/uploads/u1' }).flush(estado(8), OK);
    await tic();
    http.expectNone((r) => r.method === 'PUT' && r.params.get('offset') === '4');
    await aceptar(8, 10);
    await crearVideo();
    expect(completo).toBe(true);
  });

  it('tras el tercer reintento fallido da un ErrorSubida reanudable con lo ya recibido', async () => {
    subir();
    await abrir();
    await aceptar(0, 4);

    for (const espera of [1000, 2000, 4000]) {
      parte(4).error(new ProgressEvent('error'), SIN_RED);
      await tic(espera);
      http
        .expectOne({ method: 'GET', url: '/api/uploads/u1' })
        .error(new ProgressEvent('error'), SIN_RED);
      await tic();
    }
    expect(eventos.filter((e) => e.tipo === 'reintento').map((e) => e.esperaMs)).toEqual([
      1000, 2000, 4000,
    ]);
    parte(4).error(new ProgressEvent('error'), SIN_RED);
    await tic();

    expect(error).toBeInstanceOf(ErrorSubida);
    const e = error as ErrorSubida;
    expect([e.uploadId, e.recibidos, e.total]).toEqual(['u1', 4, 10]);
    expect(e.message).toContain('después de 3 reintentos');
    expect(e.message).toContain('al reintentar, la subida sigue desde ahí');
  });

  it('reanuda una subida anterior desde GET /uploads sin volver a mandar lo recibido', async () => {
    subir('u1');
    http.expectOne({ method: 'GET', url: '/api/uploads/u1' }).flush(estado(8), OK);
    await tic();
    http.expectNone({ method: 'POST', url: '/api/uploads' });
    expect(eventos[0]).toEqual({ tipo: 'abierta', uploadId: 'u1', recibidos: 8, total: 10 });

    await aceptar(8, 10);
    await crearVideo();
    expect(completo).toBe(true);
  });

  it('si la subida anterior ya no existe, empieza otra', async () => {
    subir('vieja');
    http
      .expectOne({ method: 'GET', url: '/api/uploads/vieja' })
      .flush({ detail: 'no existe' }, { status: 404, statusText: 'Not Found' });
    await tic();
    await abrir();
    await aceptar(0, 4);
    await aceptar(4, 8);
    await aceptar(8, 10);
    await crearVideo();
    expect(completo).toBe(true);
  });

  it('un 409 reacomoda el offset al que dice la API, sin contar como fallo', async () => {
    subir();
    await abrir();
    parte(0).flush(
      { detail: { mensaje: 'se esperaba la parte en el offset 8', offset: 8, tamano: 10 } },
      { status: 409, statusText: 'Conflict' },
    );
    await tic();
    expect(eventos.some((e) => e.tipo === 'reintento')).toBe(false);
    await aceptar(8, 10);
    await crearVideo();
    expect(completo).toBe(true);
  });

  it('un 413 no se reintenta', async () => {
    subir();
    await abrir();
    parte(0).flush(
      { detail: 'la parte pasa del tamaño de parte (4 bytes)' },
      { status: 413, statusText: 'Payload Too Large' },
    );
    await tic(10_000);
    http.expectNone('/api/uploads/u1');
    expect(error).toBeInstanceOf(ErrorSubida);
    expect((error as ErrorSubida).message).toContain('Archivo demasiado grande');
  });

  it('cancelar aborta la parte en vuelo y no manda nada más', async () => {
    subir();
    await abrir();
    const enVuelo = parte(0);
    suscripcion.unsubscribe();
    expect(enVuelo.cancelled).toBe(true);
    await tic(10_000);
    http.expectNone(() => true);
    expect(error).toBeUndefined();
  });

  it('cancelar durante la espera de un reintento no consulta la API', async () => {
    subir();
    await abrir();
    parte(0).error(new ProgressEvent('error'), SIN_RED);
    await tic();
    suscripcion.unsubscribe();
    await tic(10_000);
    http.expectNone(() => true);
    expect(error).toBeUndefined();
  });
});
