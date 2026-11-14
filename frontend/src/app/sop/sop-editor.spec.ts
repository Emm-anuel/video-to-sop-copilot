import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import ejemplo from '../../../../tests/fixtures/sop_generado_ejemplo.json';
import { SOP } from '../api/sop';
import { AdvertenciaSOP, SopDetalle } from '../api/tipos';
import { SONDEO_EDITOR_MS, SopEditor } from './sop-editor';

const DETALLE = '/api/sops/21';

function sopEjemplo(): SOP {
  return structuredClone(ejemplo) as unknown as SOP;
}

function detalle(extra: Partial<SopDetalle> = {}, sop = sopEjemplo()): SopDetalle {
  return {
    id: 21,
    codigo: 'SOP-0021',
    origen: 'generado',
    creado: '2026-11-09T10:05:00Z',
    metodo: null,
    advertencias: [],
    en_biblioteca: false,
    generacion: { video_id: 9 },
    sop,
    ...extra,
  };
}

describe('SopEditor', () => {
  let fixture: ComponentFixture<SopEditor>;
  let http: HttpTestingController;
  let navegar: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    TestBed.configureTestingModule({
      imports: [SopEditor],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  async function abrir(
    d: SopDetalle = detalle(),
    entradas: Record<string, unknown> = {},
  ): Promise<void> {
    fixture = TestBed.createComponent(SopEditor);
    fixture.componentRef.setInput('id', 21);
    for (const [k, v] of Object.entries(entradas)) {
      fixture.componentRef.setInput(k, v);
    }
    await fixture.whenStable();
    http.expectOne(DETALLE).flush(d);
    await fixture.whenStable();
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function texto(): string {
    return el().textContent ?? '';
  }

  function pasos(): HTMLElement[] {
    return Array.from(el().querySelectorAll<HTMLElement>('li.paso'));
  }

  function nombres(): string[] {
    return pasos().map((p) => p.querySelector<HTMLInputElement>('input[id$="-nombre"]')!.value);
  }

  function boton(texto: string, dentro: ParentNode = el()): HTMLButtonElement {
    const b = Array.from(dentro.querySelectorAll<HTMLButtonElement>('button')).find(
      (x) => x.textContent?.trim() === texto || x.getAttribute('aria-label') === texto,
    );
    if (!b) {
      throw new Error(`no hay botón «${texto}»`);
    }
    return b;
  }

  async function clic(b: HTMLElement): Promise<void> {
    b.click();
    await fixture.whenStable();
  }

  async function escribir(selector: string, valor: string, evento = 'input'): Promise<void> {
    const campo = el().querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!;
    campo.value = valor;
    campo.dispatchEvent(new Event(evento));
    await fixture.whenStable();
  }

  /** Guarda y responde el PUT; devuelve el cuerpo enviado. El GET de relectura queda pendiente. */
  async function guardar(): Promise<SOP> {
    await clic(boton('Guardar cambios'));
    const req = http.expectOne({ method: 'PUT', url: DETALLE });
    const cuerpo = req.request.body as SOP;
    req.flush(detalle({}, cuerpo));
    await fixture.whenStable();
    return cuerpo;
  }

  async function releer(sop: SOP, extra: Partial<SopDetalle> = {}): Promise<void> {
    http.expectOne({ method: 'GET', url: DETALLE }).flush(detalle(extra, sop));
    await fixture.whenStable();
  }

  it('muestra el SOP con miniaturas diferidas y las palabras clave con menciones y segundos', async () => {
    await abrir();
    expect(el().querySelector<HTMLInputElement>('#sop-titulo')!.value).toBe(ejemplo.titulo);
    expect(texto()).toContain('SOP-0021');
    expect(texto()).toContain('generado desde el video 9');
    expect(nombres()).toEqual(ejemplo.pasos.map((p) => p.nombre));

    const imgs = Array.from(el().querySelectorAll<HTMLImageElement>('li.paso img'));
    expect(imgs).toHaveLength(ejemplo.pasos.length);
    expect(imgs[0].getAttribute('src')).toBe(`/api/videos/9/thumb?t=${ejemplo.pasos[0].t_inicio}`);
    expect(imgs[0].getAttribute('loading')).toBe('lazy');
    imgs[0].dispatchEvent(new Event('error'));
    await fixture.whenStable();
    expect(el().querySelectorAll('li.paso img')).toHaveLength(ejemplo.pasos.length - 1);

    // Palabras clave como tarjetas (RNF-13): término, categoría, menciones y segundos.
    const fila = Array.from(el().querySelectorAll('li.palabra')).find((li) =>
      li.textContent?.includes(ejemplo.palabras_clave[0].termino),
    )!;
    expect(fila.textContent).toContain(`${ejemplo.palabras_clave[0].menciones} menciones`);
    expect(fila.textContent).toContain(ejemplo.palabras_clave[0].categoria);
    // Cada mención es un botón que abre el video en ese segundo (16.53 s).
    expect(boton('00:16', fila)).toBeTruthy();
  });

  it('si el navegador no reproduce el formato del video (AVI), el diálogo lo dice y ofrece descargarlo', async () => {
    await abrir();
    const video = el().querySelector<HTMLVideoElement>('dialog video')!;
    Object.defineProperty(video, 'error', { configurable: true, value: { code: 4 } });
    video.dispatchEvent(new Event('error'));
    const sonda = http.expectOne('/api/videos/9/video');
    expect(sonda.request.headers.get('Range')).toBe('bytes=0-0');
    sonda.flush(new Blob(['R']), { status: 206, statusText: 'Partial Content' });
    await fixture.whenStable();

    const aviso = el().querySelector('dialog .aviso-video')!;
    expect(aviso.textContent).toContain('El navegador no reproduce este formato.');
    const enlace = aviso.querySelector<HTMLAnchorElement>('a.descargar-video')!;
    expect(enlace.getAttribute('href')).toBe('/api/videos/9/video');
    expect(enlace.hasAttribute('download')).toBe(true);
    // Los segundos siguen a la vista en el SOP.
    expect(nombres()).toEqual(ejemplo.pasos.map((p) => p.nombre));
  });

  it('con otro error del video, el diálogo dice que no cargó sin consultar el archivo', async () => {
    await abrir();
    el().querySelector('dialog video')!.dispatchEvent(new Event('error'));
    await fixture.whenStable();
    http.expectNone('/api/videos/9/video');
    expect(el().querySelector('dialog .aviso-video')!.textContent).toContain(
      'No se pudo cargar el video.',
    );
    expect(el().querySelector('a.descargar-video')).toBeNull();
  });

  it('con la advertencia "sin_imagen" no pide miniaturas', async () => {
    const sinImagen: AdvertenciaSOP = {
      tipo: 'sin_imagen',
      linea: null,
      mensaje: 'sin imagen visible',
    };
    await abrir(detalle({ advertencias: [sinImagen] }));
    expect(el().querySelector('li.paso img')).toBeNull();
  });

  it('resalta lo inferido y lo de confianza media con una leyenda de texto', async () => {
    await abrir();
    const alcance = el().querySelector('#dato-alcance')!.closest('.campo')!;
    expect(alcance.classList).toContain('revisar');
    expect(alcance.textContent).toContain('Inferido');
    const paso1 = pasos()[0];
    expect(paso1.textContent).toContain('Confianza media');
    expect(paso1.querySelector('.revisar')?.textContent).toContain('Puntos de validación');
  });

  it('une un paso con el siguiente y los de después se renumeran al guardar', async () => {
    await abrir();
    await clic(boton('Unir con el siguiente paso', pasos()[0]));
    expect(pasos()).toHaveLength(ejemplo.pasos.length - 1);
    expect(nombres()[0]).toBe(ejemplo.pasos[0].nombre);
    expect(pasos()[0].textContent).toContain('00:20–00:53'); // tramo de los dos
    expect(document.activeElement?.id).toBe('paso-1-nombre'); // el nombre, listo para cambiarlo

    const cuerpo = await guardar();
    expect(cuerpo.pasos.map((p) => p.numero)).toEqual([1, 2, 3, 4, 5]);
    expect(cuerpo.pasos[0].descripcion).toBe(
      `${ejemplo.pasos[0].descripcion} ${ejemplo.pasos[1].descripcion}`,
    );
    expect(cuerpo.resumen?.riesgos?.map((r) => r.paso)).toEqual([2, 2, 4]);
    await releer(cuerpo);
    expect(texto()).toContain('Cambios guardados.');
  });

  it('si los responsables difieren, pregunta cuál usar antes de unir', async () => {
    const sop = sopEjemplo();
    sop.pasos[1].responsable = 'Supervisor de turno';
    await abrir(detalle({}, sop));
    await clic(boton('Unir con el siguiente paso', pasos()[0]));
    expect(pasos()).toHaveLength(ejemplo.pasos.length);
    expect(texto()).toContain('tienen responsables distintos');
    await clic(boton('Supervisor de turno', pasos()[0]));
    expect(pasos()).toHaveLength(ejemplo.pasos.length - 1);
    expect(pasos()[0].querySelector<HTMLInputElement>('input[id$="-responsable"]')!.value).toBe(
      'Supervisor de turno',
    );
  });

  it('reordena con subir y bajar', async () => {
    await abrir();
    await clic(boton('Bajar el paso 1'));
    expect(nombres().slice(0, 2)).toEqual([ejemplo.pasos[1].nombre, ejemplo.pasos[0].nombre]);
    expect(boton('Subir el paso 1').disabled).toBe(true);
    await clic(boton('Subir el paso 2'));
    expect(nombres()).toEqual(ejemplo.pasos.map((p) => p.nombre));
  });

  it('quita un paso y lo deshace en la misma sesión', async () => {
    await abrir();
    await clic(boton('Quitar paso', pasos()[2]));
    expect(nombres()).not.toContain(ejemplo.pasos[2].nombre);
    expect(texto()).toContain(`Quitaste el paso «${ejemplo.pasos[2].nombre}»`);
    await clic(boton('Deshacer'));
    expect(nombres()).toEqual(ejemplo.pasos.map((p) => p.nombre));
    expect(texto()).not.toContain('Quitaste el paso');
  });

  it('un dato inferido editado sale de campos_inferidos y queda revisado', async () => {
    await abrir();
    // Quitar un punto de validación inferido del paso 1 lo edita.
    const punto = ejemplo.pasos[0].puntos_validacion[0];
    await clic(boton(`Quitar ${punto}`, pasos()[0]));
    await escribir('#dato-alcance', 'Toda la línea de enjuague');

    const cuerpo = await guardar();
    expect(cuerpo.pasos[0].campos_inferidos).toEqual([]);
    expect(cuerpo.pasos[0].revisado).toBe(true);
    expect(cuerpo.resumen?.alcance).toMatchObject({
      valor: 'Toda la línea de enjuague',
      revisado: true,
      fuente: 'inferido', // la fuente no cambia (RF-25, ADR-025)
    });
    await releer(cuerpo);
    expect(el().querySelector('#dato-alcance')!.closest('.campo')!.classList).not.toContain(
      'revisar',
    );
  });

  it('un 422 marca cada campo sin perder lo editado', async () => {
    await abrir();
    await escribir('input[id="paso-1-nombre"]', '');
    await clic(boton('Guardar cambios'));
    http.expectOne({ method: 'PUT', url: DETALLE }).flush(
      {
        detail: [
          { loc: ['body', 'pasos', 0, 'nombre'], msg: 'String should have at least 1 character' },
        ],
      },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await fixture.whenStable();
    expect(texto()).toContain('Paso 1 · nombre: String should have at least 1 character');
    const nombre = el().querySelector<HTMLInputElement>('input[id="paso-1-nombre"]')!;
    expect(nombre.classList).toContain('con-error');
    // Lo editado sigue: otro cambio y el botón de guardar sigue activo.
    expect(nombres()).toHaveLength(ejemplo.pasos.length);
    expect(boton('Guardar cambios').disabled).toBe(false);
  });

  it('un 409 dice que el SOP todavía no está listo', async () => {
    await abrir();
    await escribir('#sop-titulo', 'Otro título');
    await clic(boton('Guardar cambios'));
    http
      .expectOne({ method: 'PUT', url: DETALLE })
      .flush(
        { detail: { mensaje: 'el SOP no está listo' } },
        { status: 409, statusText: 'Conflict' },
      );
    await fixture.whenStable();
    expect(texto()).toContain('El SOP todavía no está listo');
    expect(el().querySelector<HTMLInputElement>('#sop-titulo')!.value).toBe('Otro título');
  });

  it('avisa si lo releído no quedó como se veía en pantalla', async () => {
    await abrir();
    await clic(boton('Bajar el paso 1'));
    await guardar();
    await releer(sopEjemplo()); // la API devolvió el orden de antes
    expect(texto()).toContain('no quedó como se ve en pantalla');
    expect(boton('Guardar cambios').disabled).toBe(false);
  });

  it('con cambios sin guardar no deja pasar a la biblioteca, descargar ni salir sin preguntar', async () => {
    await abrir();
    expect(boton('Guardar en la biblioteca').disabled).toBe(false);
    expect(el().querySelector('a.boton')?.getAttribute('href')).toBe('/api/sops/21.md');
    expect(fixture.componentInstance.puedeSalir()).toBe(true);

    await escribir('#sop-titulo', 'Otro título');
    expect(boton('Guardar en la biblioteca').disabled).toBe(true);
    expect(el().querySelector('a.boton')).toBeNull();
    expect(texto()).toContain('Hay cambios sin guardar');
    expect(fixture.componentInstance.puedeSalir()).toBe(false);
  });

  it('guarda en la biblioteca y luego lo usa para validar', async () => {
    await abrir();
    expect(boton('Usar para validar').disabled).toBe(true); // fuera de la biblioteca: 422
    await clic(boton('Guardar en la biblioteca'));
    http
      .expectOne({ method: 'POST', url: '/api/sops/21/biblioteca' })
      .flush({ id: 21, codigo: 'SOP-0021', estado: 'listo', en_biblioteca: true });
    await fixture.whenStable();
    expect(texto()).toContain('En la biblioteca');
    await clic(boton('Usar para validar'));
    expect(navegar).toHaveBeenCalledWith(['/nuevo'], { queryParams: { sop: 21 } });
  });

  describe('SOP de referencia (RF-04)', () => {
    function convertido(): SopDetalle {
      const sop = sopEjemplo();
      for (const p of sop.pasos) {
        p.t_inicio = null;
        p.t_fin = null;
      }
      return detalle(
        {
          origen: 'cargado',
          metodo: 'llm',
          en_biblioteca: true,
          generacion: null,
          advertencias: [
            { tipo: 'infinitivo', linea: 4, mensaje: 'el paso 1 no empieza con un verbo' },
            { tipo: 'infinitivo', linea: 9, mensaje: 'el paso 3 no empieza con un verbo' },
            { tipo: 'tiempos', linea: null, mensaje: 'la suma no cuadra con el total' },
          ],
        },
        sop,
      );
    }

    it('agrupa las advertencias por tipo, con su línea, y avisa que lo convirtió el modelo', async () => {
      await abrir(convertido());
      expect(texto()).toContain('lo convirtió el modelo, revísalo');
      expect(texto()).toContain('Pasos que no empiezan con un verbo en infinitivo (2)');
      expect(texto()).toContain('Línea 4:');
      expect(texto()).toContain('Tiempos (1)');
      expect(texto()).toContain('SOP de referencia');
      expect(el().querySelector('li.paso img')).toBeNull();
      expect(el().querySelector('dialog')).toBeNull();
    });

    it('con ?video=N, después de guardar ofrece revalidar el video sin esperar', async () => {
      await abrir(convertido(), { video: '12' });
      expect(texto()).toContain('El video 12 ya se está validando con este SOP');
      await escribir('input[id="paso-1-nombre"]', 'Ponerse el equipo de protección');
      const cuerpo = await guardar();
      await releer(cuerpo, { origen: 'cargado', metodo: 'llm', generacion: null });

      await clic(boton('Revalidar el video 12'));
      http
        .expectOne({ method: 'POST', url: '/api/videos/12/validar' })
        .flush({ id: 12, proceso: 'en_cola' }, { status: 202, statusText: 'Accepted' });
      await fixture.whenStable();
      expect(navegar).toHaveBeenCalledWith(['/videos', 12, 'reporte']);
    });

    it('si el video sigue en proceso, la revalidación da 409 y lo dice', async () => {
      await abrir(convertido(), { video: 12 });
      await escribir('#sop-titulo', 'Otro título');
      await releer(await guardar());
      await clic(boton('Revalidar el video 12'));
      http
        .expectOne({ method: 'POST', url: '/api/videos/12/validar' })
        .flush({ detail: 'en proceso' }, { status: 409, statusText: 'Conflict' });
      await fixture.whenStable();
      expect(texto()).toContain('El video todavía se está procesando');
    });
  });

  it('si el SOP todavía se convierte, espera y lo abre al quedar listo', async () => {
    fixture = TestBed.createComponent(SopEditor);
    fixture.componentRef.setInput('id', 21);
    await fixture.whenStable();
    http
      .expectOne(DETALLE)
      .flush({ detail: { mensaje: 'no listo' } }, { status: 409, statusText: 'Conflict' });
    await fixture.whenStable();
    expect(texto()).toContain('todavía se está convirtiendo');

    await vi.advanceTimersByTimeAsync(SONDEO_EDITOR_MS);
    http.expectOne('/api/sops/21/estado').flush({
      id: 21,
      codigo: 'SOP-0021',
      estado: 'listo',
      titulo: 'x',
      metodo: 'plantilla',
      mensaje: null,
      advertencias: [],
    });
    await fixture.whenStable();
    http.expectOne(DETALLE).flush(detalle());
    await fixture.whenStable();
    expect(pasos()).toHaveLength(ejemplo.pasos.length);
  });
});
