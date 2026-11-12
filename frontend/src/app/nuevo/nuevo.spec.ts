import { HttpEventType, provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { METADATOS_VIDEO, MetadatosVideo } from '../api/metadatos-video';
import { EstadoSop, EstimacionImagenes, SopResumen, VideoCreado } from '../api/tipos';
import { Nuevo, SONDEO_SOP_MS, duracionCorta } from './nuevo';

const SOP_EN_COLA: EstadoSop = {
  id: 3,
  codigo: 'SOP-0003',
  estado: 'en_cola',
  titulo: null,
  metodo: null,
  mensaje: null,
  advertencias: [],
};
const SOP_LISTO: EstadoSop = {
  ...SOP_EN_COLA,
  estado: 'listo',
  titulo: 'Cambio del cartucho',
  metodo: 'plantilla',
};
const SOP_CON_ADVERTENCIAS: EstadoSop = {
  ...SOP_LISTO,
  metodo: 'llm',
  advertencias: [{ tipo: 'paso_sin_evidencia', linea: null, mensaje: 'el paso 4 no tiene cita' }],
};
const SOP_ERROR: EstadoSop = {
  ...SOP_EN_COLA,
  estado: 'error',
  mensaje: 'El PDF no tiene texto: súbelo en Markdown con la plantilla.',
};
const SOP_A: SopResumen = {
  id: 7,
  codigo: 'SOP-0007',
  titulo: 'Limpieza de la carcasa',
  origen: 'cargado',
  creado: '2026-11-10T10:00:00Z',
  videos_validados: 2,
};
const SOP_B: SopResumen = {
  id: 8,
  codigo: 'SOP-0008',
  titulo: 'Arranque de la bomba',
  origen: 'generado',
  creado: '2026-11-11T10:00:00Z',
  videos_validados: 0,
};
const VIDEO_CREADO: VideoCreado = { id: 12, proceso: 'en_cola' };
const ACEPTADO = { status: 202, statusText: 'Accepted' };
const CON_IMAGEN: MetadatosVideo = { duracion: 135, conImagen: true };
const ESTIMACION: EstimacionImagenes = {
  imagenes_estimadas: 6,
  segundos_extra_gpu: 9,
  segundos_extra_cpu: 90,
  dispositivo: 'gpu',
  dispositivo_supuesto: false,
  aviso: 'Con GPU: describir 6 imágenes sumará ~9 s.',
  analizar_imagenes_defecto: false,
};
const SIN_GPU: EstimacionImagenes = {
  ...ESTIMACION,
  dispositivo: 'cpu',
  aviso: 'Sin GPU: describir 6 imágenes sumará ~2 min.',
};

describe('Nuevo', () => {
  let fixture: ComponentFixture<Nuevo>;
  let http: HttpTestingController;
  let navegar: ReturnType<typeof vi.spyOn>;
  /** Lo que "lee el navegador" del video; por defecto nada (sin estimación). */
  let metadatos: MetadatosVideo | null;

  beforeEach(async () => {
    // El reloj avanza solo (whenStable funciona) y el sondeo se adelanta a mano.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    metadatos = null;
    TestBed.configureTestingModule({
      imports: [Nuevo],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: METADATOS_VIDEO, useValue: () => Promise.resolve(metadatos) },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    // La biblioteca vacía: empieza en "Subir uno ahora", el camino del MVP.
    await crear([]);
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  /** Monta la pantalla y responde `GET /sops` con `lista`; con `sop`, como `?sop=ID`. */
  async function crear(lista: SopResumen[], sop?: number): Promise<void> {
    fixture = TestBed.createComponent(Nuevo);
    if (sop !== undefined) {
      fixture.componentRef.setInput('sop', String(sop));
    }
    await fixture.whenStable();
    await flush(http.expectOne({ method: 'GET', url: '/api/sops' }), lista, {
      status: 200,
      statusText: 'OK',
    });
  }

  function el<T extends HTMLElement = HTMLElement>(selector: string): T | null {
    return (fixture.nativeElement as HTMLElement).querySelector<T>(selector);
  }

  async function elegir(selector: string, archivo: File): Promise<void> {
    const input = el<HTMLInputElement>(selector)!;
    Object.defineProperty(input, 'files', {
      configurable: true,
      value: { item: (i: number) => (i === 0 ? archivo : null), length: 1 },
    });
    input.dispatchEvent(new Event('change'));
    await fixture.whenStable();
  }

  async function clic(selector: string): Promise<void> {
    el(selector)!.click();
    await fixture.whenStable();
  }

  async function aceptar(): Promise<void> {
    await clic('#consentimiento');
  }

  async function elegirVideo(nombre = 'video_b.mp4'): Promise<void> {
    await elegir('#video', new File(['video'], nombre, { type: 'video/mp4' }));
  }

  async function llenarYValidar(sop = 'sop_filtro.pdf'): Promise<void> {
    await elegir('#sop', new File(['%PDF'], sop, { type: 'application/pdf' }));
    await elegirVideo();
    await aceptar();
    await validar();
  }

  async function validar(): Promise<void> {
    el<HTMLButtonElement>('button[type=submit]')!.click();
    await fixture.whenStable();
  }

  async function flush(req: TestRequest, cuerpo: object, estado = ACEPTADO): Promise<void> {
    req.flush(cuerpo, estado);
    await fixture.whenStable();
  }

  /** Adelanta el sondeo y responde la consulta del estado del SOP. */
  async function sondeo(estado: EstadoSop): Promise<void> {
    await vi.advanceTimersByTimeAsync(SONDEO_SOP_MS);
    await flush(http.expectOne({ method: 'GET', url: `/api/sops/${estado.id}/estado` }), estado);
  }

  /** La consulta de la estimación pendiente (y la responde con `cuerpo`, si viene). */
  async function estimacion(cuerpo?: EstimacionImagenes): Promise<TestRequest> {
    const req = http.expectOne((r) => r.url === '/api/videos/estimacion');
    if (cuerpo) {
      await flush(req, cuerpo, { status: 200, statusText: 'OK' });
    }
    return req;
  }

  function texto(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  function boton(): HTMLButtonElement {
    return el<HTMLButtonElement>('button')!;
  }

  function casilla(): HTMLInputElement {
    return el<HTMLInputElement>('#imagenes')!;
  }

  function enviado(req: TestRequest): FormData {
    return req.request.body as FormData;
  }

  // ── Los tres modos (RF-07) ──

  it('con la biblioteca vacía empieza en "Subir uno ahora"', () => {
    expect(el<HTMLInputElement>('#modo-subir')!.checked).toBe(true);
    expect(el('#sop')).not.toBeNull();
    expect(texto()).toContain('Validar un video contra un SOP');
  });

  it('con SOP en la biblioteca empieza ahí y valida con el elegido, sin POST /sops', async () => {
    await crear([SOP_A, SOP_B]);
    expect(el<HTMLInputElement>('#modo-biblioteca')!.checked).toBe(true);
    expect(el('#sop')).toBeNull();
    expect(texto()).toContain('SOP-0007');
    expect(texto()).toContain('Arranque de la bomba');

    await clic('input[name="sop-referencia"][value="8"]');
    await elegirVideo();
    await aceptar();
    await validar();

    http.expectNone({ method: 'POST', url: '/api/sops' });
    const video = http.expectOne({ method: 'POST', url: '/api/videos' });
    expect(enviado(video).get('modo')).toBe('validar');
    expect(enviado(video).get('sop_id')).toBe('8');
    expect(enviado(video).get('analizar_imagenes')).toBe('false');
    await flush(video, VIDEO_CREADO);
    // El SOP ya está listo: no hay conversión que consultar.
    http.expectNone('/api/sops/8/estado');
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
  });

  it('en "De la biblioteca" sin elegir SOP no sube nada', async () => {
    await crear([SOP_A]);
    await elegirVideo();
    await aceptar();
    await validar();
    expect(texto()).toContain('Elige un SOP de la biblioteca.');
    http.expectNone({ method: 'POST', url: '/api/videos' });
  });

  it('si la biblioteca no responde, lo dice y empieza en "Subir uno ahora"', async () => {
    fixture = TestBed.createComponent(Nuevo);
    await fixture.whenStable();
    await flush(
      http.expectOne('/api/sops'),
      { detail: 'falló' },
      { status: 500, statusText: 'Error' },
    );
    expect(el<HTMLInputElement>('#modo-subir')!.checked).toBe(true);
    await clic('#modo-biblioteca');
    expect(texto()).toContain('No se pudo leer la biblioteca.');
  });

  it('con "No tengo SOP" sube el video en modo generar, sin SOP, y va a la vista del SOP', async () => {
    await clic('#modo-generar');
    expect(el('#sop')).toBeNull();
    expect(boton().textContent).toContain('Generar SOP');

    await elegirVideo('video_e.mp4');
    await aceptar();
    await validar();
    http.expectNone({ method: 'POST', url: '/api/sops' });
    const video = http.expectOne({ method: 'POST', url: '/api/videos' });
    const datos = enviado(video);
    expect(datos.get('modo')).toBe('generar');
    expect(datos.has('sop_id')).toBe(false);
    expect(datos.get('titulo')).toBe('video_e');
    expect(datos.get('analizar_imagenes')).toBe('false');
    await flush(video, VIDEO_CREADO);
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'sop']);
  });

  it('acepta SOP en Markdown, texto, PDF y Word', () => {
    expect(el<HTMLInputElement>('#sop')!.accept).toBe('.md,.txt,.pdf,.docx');
  });

  // ── Título y consentimiento, obligatorios en los tres modos ──

  it('sin el consentimiento (RNF-16) no sube nada', async () => {
    await elegir('#sop', new File(['# SOP'], 'sop.md'));
    await elegirVideo();
    await validar();
    expect(texto()).toContain('Confirma el consentimiento para poder subir el video.');
    http.expectNone('/api/sops');
    http.expectNone('/api/videos');

    // RNF-16: el aviso dice que los rostros y las voces son datos personales.
    expect(el('label[for=consentimiento]')!.textContent).toContain('datos personales (LFPDPPP)');
    await aceptar();
    expect(texto()).not.toContain('Confirma el consentimiento');
  });

  it.each(['subir', 'biblioteca', 'generar'])('sin título no sube (modo %s)', async (modo) => {
    await crear([SOP_A]);
    await clic(`#modo-${modo}`);
    if (modo === 'subir') {
      await elegir('#sop', new File(['# SOP'], 'sop.md'));
    } else if (modo === 'biblioteca') {
      await clic('input[name="sop-referencia"][value="7"]');
    }
    await elegirVideo();
    const titulo = el<HTMLInputElement>('#titulo')!;
    titulo.value = '   ';
    titulo.dispatchEvent(new Event('input'));
    await aceptar();
    await validar();
    expect(texto()).toContain('El título debe tener de 1 a 300 caracteres.');
    http.expectNone('/api/sops');
    http.expectNone('/api/videos');
  });

  // ── Subir uno ahora (el camino del MVP) ──

  it('sube el SOP y el video sin esperar la conversión, consulta cada 2 s y navega al quedar listo', async () => {
    await llenarYValidar();
    expect(boton().disabled).toBe(true);

    const sop = http.expectOne({ method: 'POST', url: '/api/sops' });
    expect(enviado(sop).get('archivo')).toBeInstanceOf(File);
    await flush(sop, SOP_EN_COLA);
    expect(texto()).toContain('Convirtiendo el SOP…');

    // El video sale de inmediato, con el SOP todavía en cola.
    const video = http.expectOne({ method: 'POST', url: '/api/videos' });
    const datos = enviado(video);
    expect(datos.get('modo')).toBe('validar');
    expect(datos.get('sop_id')).toBe('3');
    expect(datos.get('titulo')).toBe('video_b');
    expect(datos.has('idioma')).toBe(false);
    expect(video.request.reportProgress).toBe(true);
    video.event({ type: HttpEventType.UploadProgress, loaded: 40, total: 100 });
    await fixture.whenStable();
    expect(texto()).toContain('Subiendo el video: 40 %');

    await flush(video, VIDEO_CREADO);
    expect(navegar).not.toHaveBeenCalled(); // falta el SOP
    expect(texto()).toContain('Video subido. Falta que termine la conversión del SOP.');

    await sondeo({ ...SOP_EN_COLA, estado: 'convirtiendo' });
    expect(texto()).toContain('Convirtiendo el SOP…');
    expect(navegar).not.toHaveBeenCalled();

    await sondeo(SOP_LISTO);
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
    // Terminó: no hay más consultas.
    await vi.advanceTimersByTimeAsync(3 * SONDEO_SOP_MS);
    http.expectNone('/api/sops/3/estado');
  });

  it('con advertencias las muestra y espera a "Ver el reporte"', async () => {
    await llenarYValidar();
    await flush(http.expectOne('/api/sops'), SOP_EN_COLA);
    await sondeo(SOP_CON_ADVERTENCIAS);
    expect(texto()).toContain('SOP guardado como SOP-0003: Cambio del cartucho');
    expect(texto()).toContain('lo convirtió el modelo');
    expect(texto()).toContain('el paso 4 no tiene cita');

    await flush(http.expectOne('/api/videos'), VIDEO_CREADO);
    expect(navegar).not.toHaveBeenCalled();
    // RF-04: se puede revisar el SOP sin detener el video; desde ahí se revalida.
    const revisar = el<HTMLAnchorElement>('.revisar a')!;
    expect(revisar.getAttribute('href')).toBe('/sops/3?video=12');
    expect(boton().textContent).toContain('Ver el reporte');
    boton().click();
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
  });

  it('si la conversión falla, muestra el mensaje, cancela la subida y pide otro SOP', async () => {
    await llenarYValidar();
    await flush(http.expectOne('/api/sops'), SOP_EN_COLA);
    const video = http.expectOne('/api/videos');

    await sondeo(SOP_ERROR);
    expect(video.cancelled).toBe(true);
    expect(texto()).toContain(
      'No se pudo convertir el SOP SOP-0003. El PDF no tiene texto: súbelo en Markdown con la plantilla.',
    );
    expect(texto()).not.toContain('El SOP ya quedó guardado');
    expect(boton().disabled).toBe(false);
    expect(navegar).not.toHaveBeenCalled();

    // El reintento vuelve a subir el SOP y el video.
    await validar();
    await flush(http.expectOne({ method: 'POST', url: '/api/sops' }), SOP_EN_COLA);
    http.expectOne('/api/videos');
    await sondeo(SOP_LISTO);
  });

  it('si la conversión falla con el video ya subido, avisa que no se validará', async () => {
    await llenarYValidar();
    await flush(http.expectOne('/api/sops'), SOP_EN_COLA);
    await flush(http.expectOne('/api/videos'), VIDEO_CREADO);
    await sondeo(SOP_ERROR);
    expect(texto()).toContain('El video ya se había subido, pero no se validará con ese SOP.');
    expect(navegar).not.toHaveBeenCalled();
  });

  it('manda el idioma solo si se eligió', async () => {
    const select = el<HTMLSelectElement>('#idioma')!;
    select.value = 'es';
    select.dispatchEvent(new Event('change'));
    await llenarYValidar('sop_filtro.md');
    await flush(http.expectOne('/api/sops'), SOP_LISTO);
    const video = http.expectOne('/api/videos');
    expect(enviado(video).get('idioma')).toBe('es');
    await flush(video, VIDEO_CREADO);
    // Un SOP que ya llega listo no se consulta.
    http.expectNone('/api/sops/3/estado');
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
  });

  it('con 422 en /sops muestra el mensaje de la API y no llama a /videos', async () => {
    await llenarYValidar();
    await flush(
      http.expectOne('/api/sops'),
      { detail: 'el PDF no tiene texto (¿es escaneado?)' },
      { status: 422, statusText: 'Unprocessable Entity' },
    );

    http.expectNone('/api/videos');
    expect(texto()).toContain(
      'No se pudo guardar el SOP. La API rechazó los datos: el PDF no tiene texto (¿es escaneado?).',
    );
    expect(boton().disabled).toBe(false);
    expect(navegar).not.toHaveBeenCalled();
  });

  it('si falla /videos, el reintento sube solo el video con el mismo sop_id', async () => {
    await llenarYValidar();
    await flush(http.expectOne('/api/sops'), SOP_EN_COLA);
    await flush(
      http.expectOne('/api/videos'),
      { detail: 'el video pasa del límite de 1024 MB' },
      { status: 413, statusText: 'Content Too Large' },
    );
    expect(texto()).toContain(
      'No se pudo subir el video. Archivo demasiado grande: el video pasa del límite de 1024 MB.',
    );
    expect(texto()).toContain('El SOP ya quedó guardado');
    expect(boton().disabled).toBe(false);

    // La conversión sigue mientras tanto.
    await sondeo(SOP_LISTO);
    await validar();
    http.expectNone({ method: 'POST', url: '/api/sops' });
    const reintento = http.expectOne('/api/videos');
    expect(enviado(reintento).get('sop_id')).toBe('3');
    await flush(reintento, VIDEO_CREADO);
    expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
  });

  it('sin archivos no llama a la API', async () => {
    await aceptar();
    await validar();
    expect(texto()).toContain('Elige el archivo del SOP.');
    expect(texto()).toContain('Elige el archivo del video.');
    http.expectNone('/api/sops');
  });

  // ── ?sop=ID ("Usar para validar" del editor o de la biblioteca) ──

  describe('con ?sop=ID', () => {
    async function conSop(lista: SopResumen[], estado: EstadoSop): Promise<void> {
      await crear(lista, estado.id);
      await flush(http.expectOne({ method: 'GET', url: `/api/sops/${estado.id}/estado` }), estado);
    }

    it('llega en "De la biblioteca" con ese SOP elegido y sube solo el video', async () => {
      await conSop([SOP_A], { ...SOP_LISTO, en_biblioteca: true });
      expect(el<HTMLInputElement>('#modo-biblioteca')!.checked).toBe(true);
      expect(el('#sop')).toBeNull();
      expect(el<HTMLInputElement>('input[name="sop-referencia"][value="3"]')!.checked).toBe(true);
      expect(texto()).toContain('Cambio del cartucho');

      await elegirVideo('video_e.mp4');
      await aceptar();
      await validar();
      http.expectNone({ method: 'POST', url: '/api/sops' });
      const video = http.expectOne({ method: 'POST', url: '/api/videos' });
      expect(enviado(video).get('sop_id')).toBe('3');
      await flush(video, VIDEO_CREADO);
      expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
    });

    it('se puede elegir otro SOP de la lista', async () => {
      await conSop([SOP_A], SOP_LISTO);
      await clic('input[name="sop-referencia"][value="7"]');
      await elegirVideo();
      await aceptar();
      await validar();
      expect(enviado(http.expectOne('/api/videos')).get('sop_id')).toBe('7');
    });

    it('un SOP generado fuera de la biblioteca no se puede usar', async () => {
      await conSop([], { ...SOP_LISTO, origen: 'generado', en_biblioteca: false });
      expect(texto()).toContain('no está en la biblioteca');
      expect(el<HTMLInputElement>('#modo-subir')!.checked).toBe(true);
      expect(el('#sop')).not.toBeNull();
    });
  });

  // ── Imágenes (ADR-024) ──

  describe('casilla de imágenes', () => {
    it('aparece al elegir el video, con la duración leída en el navegador y apagada por defecto', async () => {
      expect(el('#imagenes')).toBeNull();
      metadatos = CON_IMAGEN;
      await elegirVideo();
      const req = await estimacion();
      expect(req.request.params.get('duracion_s')).toBe('135');
      expect(req.request.params.get('modo')).toBe('validar');
      expect(req.request.params.has('sop_id')).toBe(false);
      expect(req.request.params.has('sin_imagen')).toBe(false);
      await flush(req, ESTIMACION, { status: 200, statusText: 'OK' });

      expect(casilla().checked).toBe(false);
      expect(casilla().disabled).toBe(false);
      // Apagada: sin indicador ni aviso.
      expect(texto()).not.toContain('≈');
      expect(el('.aviso-ambar')).toBeNull();
    });

    it('arranca prendida si la instalación lo pide y muestra "≈ N imágenes · +X s" con GPU', async () => {
      metadatos = CON_IMAGEN;
      await elegirVideo();
      await estimacion({ ...ESTIMACION, analizar_imagenes_defecto: true });
      expect(casilla().checked).toBe(true);
      expect(el('.indicador')!.textContent).toBe('≈ 6 imágenes · +9 s');
      expect(el('.aviso-ambar')).toBeNull();
    });

    it('sin GPU muestra el aviso del servidor en ámbar y no se deshabilita', async () => {
      metadatos = CON_IMAGEN;
      await elegirVideo();
      await estimacion(SIN_GPU);
      await clic('#imagenes');
      expect(el('.indicador')!.textContent).toBe('≈ 6 imágenes · +2 min');
      expect(el('.aviso-ambar')!.textContent).toBe('Sin GPU: describir 6 imágenes sumará ~2 min.');
      expect(casilla().disabled).toBe(false);
    });

    it('con dispositivo supuesto lo dice con la palabra "estimado"', async () => {
      metadatos = CON_IMAGEN;
      await elegirVideo();
      await estimacion({
        ...SIN_GPU,
        dispositivo_supuesto: true,
        aviso:
          'No se pudo saber si hay GPU: describir 6 imágenes sumará ~9 s con GPU o ~2 min sin ella.',
      });
      await clic('#imagenes');
      expect(el('.indicador')!.textContent).toBe('≈ 6 imágenes · +2 min (estimado)');
      expect(el('.aviso-ambar')!.textContent).toContain('No se pudo saber si hay GPU');
      expect(casilla().disabled).toBe(false);
    });

    it('recalcula al cambiar de SOP y de modo', async () => {
      await crear([SOP_A, SOP_B]);
      metadatos = CON_IMAGEN;
      await elegirVideo();
      await estimacion(ESTIMACION); // validar, todavía sin SOP elegido

      await clic('input[name="sop-referencia"][value="7"]');
      let req = await estimacion();
      expect(req.request.params.get('sop_id')).toBe('7');
      await flush(req, ESTIMACION, { status: 200, statusText: 'OK' });

      await clic('input[name="sop-referencia"][value="8"]');
      req = await estimacion();
      expect(req.request.params.get('sop_id')).toBe('8');
      await flush(req, ESTIMACION, { status: 200, statusText: 'OK' });

      await clic('#modo-generar');
      req = await estimacion();
      expect(req.request.params.get('modo')).toBe('generar');
      expect(req.request.params.has('sop_id')).toBe(false);
      await flush(req, ESTIMACION, { status: 200, statusText: 'OK' });

      // "Subir uno ahora": validar sin sop_id (el SOP todavía no existe).
      await clic('#modo-subir');
      req = await estimacion();
      expect(req.request.params.get('modo')).toBe('validar');
      expect(req.request.params.has('sop_id')).toBe(false);
      await flush(req, ESTIMACION, { status: 200, statusText: 'OK' });
    });

    it('recalcula al cambiar de video', async () => {
      metadatos = CON_IMAGEN;
      await elegirVideo();
      await estimacion(ESTIMACION);
      metadatos = { duracion: 600, conImagen: true };
      await elegirVideo('otro.mp4');
      const req = await estimacion();
      expect(req.request.params.get('duracion_s')).toBe('600');
      await flush(req, ESTIMACION, { status: 200, statusText: 'OK' });
    });

    it('un archivo sin imagen deshabilita la casilla con el motivo y pide la estimación con sin_imagen', async () => {
      await clic('#modo-generar');
      metadatos = { duracion: 60, conImagen: false };
      await elegirVideo('solo_audio.mp4');
      const req = await estimacion();
      expect(req.request.params.get('sin_imagen')).toBe('true');
      await flush(
        req,
        { ...ESTIMACION, imagenes_estimadas: 0, analizar_imagenes_defecto: true },
        { status: 200, statusText: 'OK' },
      );

      expect(casilla().disabled).toBe(true);
      expect(casilla().checked).toBe(false);
      expect(texto()).toContain('este archivo no tiene imagen');
      expect(texto()).not.toContain('≈');

      await aceptar();
      await validar();
      expect(enviado(http.expectOne('/api/videos')).get('analizar_imagenes')).toBe('false');
    });

    it('prendida, analizar_imagenes viaja en true', async () => {
      await clic('#modo-generar');
      metadatos = CON_IMAGEN;
      await elegirVideo();
      await estimacion(ESTIMACION);
      await clic('#imagenes');
      await aceptar();
      await validar();
      expect(enviado(http.expectOne('/api/videos')).get('analizar_imagenes')).toBe('true');
    });

    it('lo que eligió la persona no lo pisa una estimación nueva', async () => {
      metadatos = CON_IMAGEN;
      await elegirVideo();
      await estimacion(ESTIMACION);
      await clic('#imagenes'); // la prende
      await clic('#modo-generar');
      await estimacion({ ...ESTIMACION, analizar_imagenes_defecto: false });
      expect(casilla().checked).toBe(true);
    });

    it('si el navegador no lee la duración, no pide estimación y la casilla sigue usable', async () => {
      await elegirVideo('raro.mkv');
      http.expectNone((r) => r.url === '/api/videos/estimacion');
      expect(casilla().disabled).toBe(false);
      await clic('#imagenes');
      expect(texto()).toContain('Sin estimación: el navegador no pudo leer la duración del video.');
    });
  });

  it('duracionCorta redondea como la API', () => {
    expect(duracionCorta(0.4)).toBe('1 s');
    expect(duracionCorta(9)).toBe('9 s');
    expect(duracionCorta(89)).toBe('89 s');
    expect(duracionCorta(90)).toBe('2 min');
    expect(duracionCorta(300)).toBe('5 min');
  });
});
