import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Descargas, FormatoDescarga } from './descargas';

describe('Descargas', () => {
  let fixture: ComponentFixture<Descargas>;

  async function crear(videoId: number, extras?: FormatoDescarga[]): Promise<void> {
    fixture = TestBed.createComponent(Descargas);
    fixture.componentRef.setInput('videoId', videoId);
    if (extras) {
      fixture.componentRef.setInput('extras', extras);
    }
    fixture.detectChanges();
    await fixture.whenStable();
  }

  const el = (): HTMLElement => fixture.nativeElement;
  const enlaces = (): HTMLAnchorElement[] => Array.from(el().querySelectorAll('a'));
  const menu = (): HTMLDetailsElement => el().querySelector('details')!;

  it('arma un enlace de descarga normal por formato, con la ruta de la API', async () => {
    await crear(12);

    expect(enlaces().map((a) => a.getAttribute('href'))).toEqual([
      '/api/videos/12/download/txt',
      '/api/videos/12/download/srt',
      '/api/videos/12/download/json',
    ]);
    for (const a of enlaces()) {
      // Sin valor: el nombre lo pone la API (`Content-Disposition`, el título del video).
      expect(a.getAttribute('download')).toBe('');
      expect(a.getAttribute('target')).toBeNull();
    }
    expect(enlaces().map((a) => a.querySelector('.etiqueta')!.textContent)).toEqual([
      'Transcripción (.txt)',
      'Subtítulos (.srt)',
      'Análisis (.json)',
    ]);
  });

  it('sigue al video si cambia', async () => {
    await crear(12);
    fixture.componentRef.setInput('videoId', 7);
    fixture.detectChanges();

    expect(enlaces()[1].getAttribute('href')).toBe('/api/videos/7/download/srt');
  });

  it('agrega los formatos extra al final (p. ej. el PDF de P5)', async () => {
    await crear(12, [
      { etiqueta: 'Reporte (.pdf)', descripcion: 'Para imprimir', url: '/api/videos/12/pdf' },
    ]);

    expect(enlaces().map((a) => a.getAttribute('href'))).toEqual([
      '/api/videos/12/download/txt',
      '/api/videos/12/download/srt',
      '/api/videos/12/download/json',
      '/api/videos/12/pdf',
    ]);
    expect(enlaces()[3].hasAttribute('download')).toBe(true);
    expect(enlaces()[3].textContent).toContain('Reporte (.pdf)');
  });

  it('un formato deshabilitado va sin enlace y dice por qué (PDF con cambios sin guardar)', async () => {
    await crear(12, [
      {
        etiqueta: 'SOP (.pdf)',
        descripcion: 'Guarda los cambios para descargar el PDF',
        url: '/api/sops/3/pdf',
        deshabilitado: true,
      },
    ]);

    expect(enlaces().map((a) => a.getAttribute('href'))).not.toContain('/api/sops/3/pdf');
    const opcion = el().querySelector('[aria-disabled="true"]')!;
    expect(opcion.textContent).toContain('SOP (.pdf)');
    expect(opcion.textContent).toContain('Guarda los cambios para descargar el PDF');
  });

  it('es un menú plegable que se cierra al elegir, con Escape y con un clic fuera', async () => {
    await crear(12);
    const resumen = el().querySelector('summary')!;
    expect(resumen.textContent).toContain('Descargar');
    expect(menu().open).toBe(false);

    menu().open = true;
    enlaces()[0].addEventListener('click', (e) => e.preventDefault()); // jsdom no navega
    enlaces()[0].click();
    expect(menu().open).toBe(false);

    menu().open = true;
    menu().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(menu().open).toBe(false);
    expect(document.activeElement).toBe(resumen);

    menu().open = true;
    el()
      .querySelector('ul')!
      .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(menu().open).toBe(true); // un clic dentro no lo cierra
    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(menu().open).toBe(false);
  });
});
