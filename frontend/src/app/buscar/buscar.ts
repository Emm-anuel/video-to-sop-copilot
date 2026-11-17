import {
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { AccesoService } from '../acceso/acceso.service';
import { ApiService } from '../api/api.service';
import { ResultadoBusqueda, SopDeVideo } from '../api/busqueda';
import { OpcionesBusqueda, VideoPublicado } from '../api/busqueda-opciones';
import { mensajeDeError } from '../api/errores';
import { mmss } from '../reporte/reporte';
import { Reproductor } from '../reproductor/reproductor';
import { FiltrosBusqueda, HistorialBusqueda, Turno } from './historial.service';
import { PartesFrase, partesFrase } from './resaltado';

/** Largo máximo de la consulta (`LARGO_CONSULTA` de la API). */
export const LARGO_CONSULTA = 500;

/** Un resultado listo para pintar. */
interface ResultadoVista {
  indice: number;
  resultado: ResultadoBusqueda;
  partes: PartesFrase;
  miniatura: string | null;
}

/** El resultado elegido: de qué turno y cuál, para marcarlo y abrir su video. */
interface Seleccion {
  turno: number;
  indice: number;
  resultado: ResultadoBusqueda;
}

/**
 * Búsqueda en los videos publicados (pantalla 7, RF-36), con apariencia de chat: la conversación
 * a la izquierda con la caja abajo y los resultados (RF-34) a la derecha; a 360 px, debajo. Cada
 * resultado lleva miniatura, título, segundo, la frase con la coincidencia resaltada y "×N" si se
 * unieron coincidencias (RF-35). Al elegir uno, el video aparece aquí mismo en ese segundo y,
 * si tiene SOP, "Ver SOP" abre su PDF en otra pestaña.
 *
 * Filtros por SOP y por video (RF-37, `GET /buscar/opciones`) como chips sobre la caja; cada
 * burbuja muestra los suyos. El historial es de la sesión, en el navegador (`HistorialBusqueda`).
 *
 * Es la vista de consulta (RNF-11): no ofrece subir, editar ni publicar, ni enlaza a la vista de
 * carga (`/nuevo`, `/videos`, `/sops`, el reporte, el editor ni `/v/`).
 */
@Component({
  selector: 'app-buscar',
  imports: [Reproductor],
  templateUrl: './buscar.html',
  styleUrl: './buscar.scss',
})
export class Buscar {
  private readonly api = inject(ApiService);
  private readonly historial = inject(HistorialBusqueda);
  private readonly injector = inject(Injector);
  private readonly destroyRef = inject(DestroyRef);
  private readonly caja = viewChild<ElementRef<HTMLInputElement>>('caja');
  private readonly conversacion = viewChild<ElementRef<HTMLElement>>('conversacion');
  private readonly reproductor = viewChild(Reproductor);
  private readonly acceso = inject(AccesoService);
  private readonly router = inject(Router);

  /** "Salir" solo si la vista de búsqueda tiene clave y esta sesión la escribió (#30). */
  protected readonly conSesion = computed(() => this.acceso.ultimo()?.busqueda.sesion === true);

  protected readonly largo = LARGO_CONSULTA;
  protected readonly mmss = mmss;
  protected readonly texto = signal('');
  protected readonly turnos = this.historial.turnos;

  /** `null` mientras carga o si falló (entonces `errorOpciones`). */
  protected readonly opciones = signal<OpcionesBusqueda | null>(null);
  protected readonly errorOpciones = signal<string | null>(null);
  protected readonly filtroSop = signal<SopDeVideo | null>(null);
  protected readonly filtroVideo = signal<VideoPublicado | null>(null);
  protected readonly hayFiltros = computed(
    () => this.filtroSop() !== null || this.filtroVideo() !== null,
  );
  /** Con un SOP elegido, solo sus videos (de referencia o generado, como filtra la API). */
  protected readonly videosFiltro = computed(() => {
    const videos = this.opciones()?.videos ?? [];
    const sop = this.filtroSop();
    return sop === null ? videos : videos.filter((v) => v.sop_id === sop.id);
  });
  protected readonly sinPublicados = computed(() => this.opciones()?.videos.length === 0);

  protected readonly buscando = computed(() => this.turnos().some((t) => t.estado === 'buscando'));
  /** El turno cuyos resultados se ven: el elegido o, si no, el último que respondió. */
  protected readonly turnoVisible = computed<Turno | null>(() => {
    const turnos = this.turnos();
    const elegido = this.historial.elegido();
    return (
      turnos.find((t) => t.clave === elegido) ??
      [...turnos].reverse().find((t) => t.estado === 'listo') ??
      null
    );
  });
  protected readonly resultados = computed<ResultadoVista[]>(() =>
    (this.turnoVisible()?.respuesta?.resultados ?? []).map((resultado, indice) => ({
      indice,
      resultado,
      partes: partesFrase(
        resultado.frase,
        resultado.rango,
        resultado.recorte_inicio,
        resultado.recorte_fin,
      ),
      miniatura: resultado.miniatura ? this.api.urlDeRuta(resultado.miniatura) : null,
    })),
  );

  protected readonly seleccion = signal<Seleccion | null>(null);
  /** Miniaturas que no cargaron: la tarjeta sigue, sin hueco. */
  protected readonly miniaturasFallidas = signal<ReadonlySet<string>>(new Set());

  constructor() {
    this.cargarOpciones();
    // Al volver con historial, la conversación abre en el último mensaje.
    afterNextRender(() => this.alFinal());
  }

  protected cargarOpciones(): void {
    this.errorOpciones.set(null);
    this.api
      .opcionesBusqueda()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (opciones) => this.opciones.set(opciones),
        error: (e: unknown) =>
          this.errorOpciones.set(
            `No se pudieron cargar los filtros; la búsqueda sigue en todo. ${mensajeDeError(e)}`,
          ),
      });
  }

  /** Enter o el botón: busca lo escrito con los filtros elegidos. */
  protected enviar(evento: Event): void {
    evento.preventDefault();
    const consulta = this.texto().trim();
    if (!consulta || this.buscando()) {
      this.enfocar();
      return;
    }
    this.texto.set('');
    this.lanzar(consulta, { sop: this.filtroSop(), video: this.filtroVideo() });
  }

  /** "Repetir": la misma consulta con sus mismos filtros, como una burbuja nueva. */
  protected repetir(turno: Turno): void {
    if (this.buscando()) {
      return;
    }
    this.lanzar(turno.consulta, turno.filtros);
  }

  /** "Reintentar" un turno que falló, en su mismo lugar. */
  protected reintentar(turno: Turno): void {
    if (this.buscando()) {
      return;
    }
    this.historial.actualizar(turno.clave, { estado: 'buscando', error: null, respuesta: null });
    this.ejecutar(turno);
    this.enfocar();
  }

  /** Cierra la sesión de la vista de búsqueda (`DELETE /acceso`) y vuelve a pedir la clave. */
  protected salir(): void {
    this.acceso.salir('busqueda').subscribe({
      next: () => void this.router.navigate(['/acceso'], { queryParams: { vista: 'busqueda' } }),
      error: () => undefined,
    });
  }

  protected limpiar(): void {
    this.historial.limpiar();
    this.seleccion.set(null);
    this.enfocar();
  }

  protected verResultados(turno: Turno): void {
    if (turno.estado === 'listo' && turno.respuesta) {
      this.historial.elegir(turno.clave);
    }
  }

  protected elegirSop(evento: Event): void {
    const select = evento.target as HTMLSelectElement;
    const id = Number(select.value);
    select.value = '';
    const sop = this.opciones()?.sops.find((s) => s.id === id) ?? null;
    if (sop) {
      this.filtroSop.set(sop);
    }
  }

  protected elegirVideo(evento: Event): void {
    const select = evento.target as HTMLSelectElement;
    const id = Number(select.value);
    select.value = '';
    const video = this.opciones()?.videos.find((v) => v.id === id) ?? null;
    if (video) {
      this.filtroVideo.set(video);
    }
  }

  protected quitarFiltros(): void {
    this.filtroSop.set(null);
    this.filtroVideo.set(null);
    this.enfocar();
  }

  /** Abre el video del resultado aquí mismo, en su segundo. */
  protected elegirResultado(turno: Turno, vista: ResultadoVista): void {
    const anterior = this.seleccion();
    const { resultado } = vista;
    this.seleccion.set({ turno: turno.clave, indice: vista.indice, resultado });
    if (anterior?.resultado.video.id === resultado.video.id) {
      this.reproductor()?.saltar(resultado.t_inicio);
    } else {
      // Otro video (o el primero): el reproductor aparece o cambia de archivo en el siguiente
      // render; ahí se pide el salto, que espera a los metadatos si hace falta.
      afterNextRender(() => this.reproductor()?.saltar(resultado.t_inicio), {
        injector: this.injector,
      });
    }
  }

  protected activo(turno: Turno | null, indice: number): boolean {
    const s = this.seleccion();
    return turno !== null && s?.turno === turno.clave && s.indice === indice;
  }

  protected ocultarMiniatura(url: string): void {
    this.miniaturasFallidas.update((s) => new Set(s).add(url));
  }

  protected urlSop(id: number): string {
    return this.api.urlPdfSop(id, { ver: true });
  }

  /** Cuántos videos distintos hay en los resultados. */
  protected videosEn(turno: Turno): number {
    return new Set(turno.respuesta?.resultados.map((r) => r.video.id)).size;
  }

  /** Lo que dice el chat sin resultados: sugiere revisar la ortografía o quitar los filtros. */
  protected sinResultados(turno: Turno): string {
    if (this.sinPublicados()) {
      return `No encontré «${turno.consulta}»: todavía no hay videos publicados.`;
    }
    const filtros = this.tieneFiltros(turno.filtros) ? ' o quita los filtros' : '';
    return `No encontré «${turno.consulta}». Revisa la ortografía${filtros}.`;
  }

  protected tieneFiltros(filtros: FiltrosBusqueda): boolean {
    return filtros.sop !== null || filtros.video !== null;
  }

  protected etiquetaSop(sop: SopDeVideo): string {
    return sop.titulo ? `${sop.codigo} · ${sop.titulo}` : sop.codigo;
  }

  private lanzar(consulta: string, filtros: FiltrosBusqueda): void {
    const turno = this.historial.agregar(consulta, filtros);
    this.ejecutar(turno);
    this.enfocar();
    afterNextRender(() => this.alFinal(), { injector: this.injector });
  }

  private alFinal(): void {
    const lista = this.conversacion()?.nativeElement;
    lista?.scrollTo?.({ top: lista.scrollHeight });
  }

  /**
   * `POST /buscar`. No se cancela al salir de la pantalla: la respuesta llega al historial (que
   * es de la aplicación) y se ve al volver.
   */
  private ejecutar(turno: Turno): void {
    this.api
      .buscar({
        consulta: turno.consulta,
        videoId: turno.filtros.video?.id,
        sopId: turno.filtros.sop?.id,
      })
      .subscribe({
        next: (respuesta) => {
          this.historial.actualizar(turno.clave, { estado: 'listo', respuesta, error: null });
          this.historial.elegir(turno.clave);
        },
        error: (e: unknown) =>
          this.historial.actualizar(turno.clave, { estado: 'error', error: mensajeDeError(e) }),
      });
  }

  private enfocar(): void {
    this.caja()?.nativeElement.focus();
  }
}
