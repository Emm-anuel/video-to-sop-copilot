import { DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  OnInit,
  Pipe,
  PipeTransform,
  afterNextRender,
  computed,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { switchMap, takeWhile, tap, timer } from 'rxjs';
import { API, ApiService } from '../api/api.service';
import { ErrorCampo, erroresPorCampo, mensajeDeError } from '../api/errores';
import { Elemento, Evidencia1 as Evidencia } from '../api/sop';
import { AdvertenciaSOP, SopDetalle } from '../api/tipos';
import { Chips } from './chips';
import { PalabrasClave } from './palabras-clave';
import {
  Borrador,
  CAMPOS_DATO,
  CampoDato,
  CampoPaso,
  FallaBorrador,
  PasoBorrador,
  PuntoBorrador,
  Quitado,
  RiesgoBorrador,
  aBorrador,
  aSop,
  agregarPaso,
  confirmarCampo,
  confirmarDato,
  confirmarPaso,
  describir,
  duracionTotal,
  editarDato,
  editarPaso,
  elementos,
  fallaNueva,
  huella,
  leyenda,
  leyendaPaso,
  mmss,
  mover,
  quitar,
  restaurar,
  riesgoNuevo,
  unirConSiguiente,
} from './edicion';
import { ConCambios } from './sin-guardar.guard';

/** Los minutos que dijo el operador como duración total (ADR-021), o null. */
export function duracionNarrada(detalle: SopDetalle): number | null {
  const valor = detalle.generacion?.duracion_narrada?.valor;
  const n = valor === null || valor === undefined ? NaN : Number(valor);
  return Number.isFinite(n) ? n : null;
}

/** Cada cuánto se consulta `GET /sops/{id}/estado` si el SOP todavía se está convirtiendo. */
export const SONDEO_EDITOR_MS = 2000;

const ETIQUETAS_DATO: Record<CampoDato, string> = {
  objetivo: 'Objetivo',
  alcance: 'Alcance',
  responsable: 'Responsable',
  lugar: 'Lugar',
  horario_frecuencia: 'Horario o frecuencia',
};

/** Advertencias de la conversión o de la generación, por tipo (RF-04). */
const TIPOS_ADVERTENCIA: Record<string, string> = {
  numeracion: 'Numeración de los pasos',
  clave_desconocida: 'Campos que no reconoce la plantilla',
  seccion_desconocida: 'Secciones que no reconoce la plantilla',
  tiempos: 'Tiempos',
  infinitivo: 'Pasos que no empiezan con un verbo en infinitivo',
  valor_invalido: 'Valores no válidos',
  paso_sin_evidencia: 'Pasos sin evidencia en el documento',
  sop_incompleto: 'SOP incompleto',
  sin_traducir: 'Sin traducir',
  sin_imagen: 'Sin imagen',
};

export interface GrupoAdvertencias {
  tipo: string;
  titulo: string;
  advertencias: AdvertenciaSOP[];
}

/** Los nombres de una lista de elementos, para los chips; pura, así no cambia en cada ciclo. */
@Pipe({ name: 'nombres' })
export class NombresPipe implements PipeTransform {
  transform(lista: readonly Elemento[]): string[] {
    return lista.map((e) => e.nombre);
  }
}

function aNumero(v: unknown): number | undefined {
  if (v === null || v === undefined || v === '') {
    return undefined;
  }
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

/**
 * Editor del SOP (RF-26 y RF-04), un solo componente para los dos casos:
 *
 * - SOP generado desde un video (`/videos/:id/sop`, dentro de `SopGenerado`): miniatura por paso,
 *   tramos del video y segundos de puntos y palabras clave que abren el video.
 * - SOP de referencia convertido de PDF, Word o texto (`/sops/:id`): advertencias por tipo, aviso
 *   si lo convirtió el modelo y "Usar para validar". Con `?video=N` (el video que ya se validó
 *   con este SOP), después de guardar ofrece revalidarlo con `POST /videos/{id}/validar`: el
 *   video no espera la corrección (ADR-019, ADR-022).
 *
 * El borrador vive en un signal y solo cambia con las funciones puras de `edicion.ts`. Guarda con
 * `PUT /sops/{id}`, relee el SOP y comprueba que quedó como se veía. Pregunta antes de salir si
 * hay cambios sin guardar (`sinGuardar` en las rutas y `beforeunload`).
 */
@Component({
  selector: 'app-sop-editor',
  imports: [Chips, DecimalPipe, NombresPipe, PalabrasClave],
  templateUrl: './sop-editor.html',
  styleUrl: './sop-editor.scss',
  host: { '(window:beforeunload)': 'alCerrar($event)' },
})
export class SopEditor implements OnInit, ConCambios {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);

  /** El sop_id (de la ruta `/sops/:id` o del video en `/videos/:id/sop`). */
  readonly id = input.required<number, unknown>({ transform: (v) => aNumero(v) ?? NaN });
  /** El video del SOP generado; si no llega, se toma de `generacion.video_id`. */
  readonly videoId = input<number | undefined, unknown>(undefined, { transform: aNumero });
  /** `?video=N`: el video validado con este SOP, para revalidarlo después de corregir. */
  readonly video = input<number | undefined, unknown>(undefined, { transform: aNumero });

  protected readonly camposDato = CAMPOS_DATO;
  protected readonly etiquetasDato = ETIQUETAS_DATO;
  protected readonly mmss = mmss;
  protected readonly describir = describir;
  protected readonly leyenda = leyenda;
  protected readonly leyendaPaso = leyendaPaso;

  protected readonly detalle = signal<SopDetalle | null>(null);
  protected readonly borrador = signal<Borrador | null>(null);
  private readonly guardado = signal('');
  protected readonly error = signal<string | null>(null);
  protected readonly aviso = signal<string | null>(null);
  protected readonly errores = signal<ErrorCampo[]>([]);
  protected readonly guardando = signal(false);
  protected readonly enviandoBiblioteca = signal(false);
  protected readonly revalidando = signal(false);
  protected readonly guardadoEnSesion = signal(false);
  protected readonly quitados = signal<Quitado[]>([]);
  protected readonly unionPendiente = signal<{
    indice: number;
    responsables: [string, string];
  } | null>(null);
  protected readonly miniaturasFallidas = signal<ReadonlySet<number>>(new Set());
  protected readonly arrastrando = signal<number | null>(null);

  private readonly dialogo = viewChild<ElementRef<HTMLDialogElement>>('dialogo');
  private readonly reproductor = viewChild<ElementRef<HTMLVideoElement>>('reproductor');
  private segundoPendiente: number | null = null;

  protected readonly sucio = computed(() => {
    const b = this.borrador();
    return b !== null && huella(aSop(b)) !== this.guardado();
  });
  protected readonly generado = computed(() => this.detalle()?.origen === 'generado');
  protected readonly enBiblioteca = computed(() => this.detalle()?.en_biblioteca ?? false);
  protected readonly idVideo = computed(
    () => this.videoId() ?? this.detalle()?.generacion?.video_id ?? null,
  );
  /** El video no tiene imagen (advertencia "sin_imagen", ADR-024): no se piden miniaturas. */
  protected readonly sinImagen = computed(
    () => this.detalle()?.advertencias?.some((a) => a.tipo === 'sin_imagen') ?? false,
  );
  protected readonly conMiniaturas = computed(() => this.idVideo() !== null && !this.sinImagen());
  protected readonly urlVideo = computed(() => {
    const id = this.idVideo();
    return id === null ? '' : `${API}/videos/${id}/video`;
  });
  protected readonly urlMarkdown = computed(() => this.api.urlMarkdown(this.id()));
  protected readonly grupos = computed<GrupoAdvertencias[]>(() => {
    const grupos = new Map<string, AdvertenciaSOP[]>();
    for (const a of this.detalle()?.advertencias ?? []) {
      grupos.set(a.tipo, [...(grupos.get(a.tipo) ?? []), a]);
    }
    return [...grupos].map(([tipo, advertencias]) => ({
      tipo,
      titulo: TIPOS_ADVERTENCIA[tipo] ?? tipo,
      advertencias,
    }));
  });
  /** La duración total como quedará al guardar (la recalcula la API, ADR-025). */
  protected readonly total = computed(() => {
    const b = this.borrador();
    return b ? duracionTotal(b.pasos, b.resumen.duracion_total_min, b.duracionNarrada) : null;
  });
  protected readonly ultimoQuitado = computed(() => this.quitados().at(-1) ?? null);

  ngOnInit(): void {
    this.cargar();
  }

  /** Para `sinGuardar` (CanDeactivate). */
  puedeSalir(): boolean {
    return !this.sucio();
  }

  protected alCerrar(evento: BeforeUnloadEvent): void {
    if (this.sucio()) {
      evento.preventDefault();
      evento.returnValue = '';
    }
  }

  // ── Cuadro resumen ────────────────────────────────────────────────────────────────────────

  protected editarTitulo(valor: string): void {
    this.cambiar((b) => ({ ...b, titulo: valor }));
  }

  protected editarVersion(valor: string): void {
    this.cambiar((b) => ({ ...b, resumen: { ...b.resumen, version: valor } }));
  }

  protected editarDato(campo: CampoDato, valor: string): void {
    this.cambiar((b) => editarDato(b, campo, valor));
  }

  protected confirmarDato(campo: CampoDato): void {
    this.cambiar((b) => confirmarDato(b, campo));
  }

  protected editarElementos(campo: 'equipo_operacion' | 'roles', nombres: string[]): void {
    this.cambiar((b) => ({
      ...b,
      resumen: { ...b.resumen, [campo]: elementos(b.resumen[campo], nombres) },
    }));
  }

  protected editarRiesgo(i: number, cambios: Partial<RiesgoBorrador>): void {
    this.cambiar((b) => ({
      ...b,
      resumen: {
        ...b.resumen,
        riesgos: b.resumen.riesgos.map((x, j) =>
          j === i ? { ...x, ...cambios, revisado: true } : x,
        ),
      },
    }));
  }

  protected pasoDeRiesgo(i: number, valor: string): void {
    this.editarRiesgo(i, { pasoClave: valor === '' ? null : Number(valor) });
  }

  protected agregarRiesgo(): void {
    this.cambiar((b) => ({
      ...b,
      resumen: { ...b.resumen, riesgos: [...b.resumen.riesgos, riesgoNuevo()] },
    }));
  }

  protected quitarRiesgo(i: number): void {
    this.cambiar((b) => ({
      ...b,
      resumen: { ...b.resumen, riesgos: b.resumen.riesgos.filter((_, j) => j !== i) },
    }));
  }

  protected editarFalla(i: number, cambios: Partial<FallaBorrador>): void {
    this.cambiar((b) => ({
      ...b,
      resumen: {
        ...b.resumen,
        en_caso_de_falla: b.resumen.en_caso_de_falla.map((x, j) =>
          j === i ? { ...x, ...cambios, revisado: true } : x,
        ),
      },
    }));
  }

  protected agregarFalla(): void {
    this.cambiar((b) => ({
      ...b,
      resumen: { ...b.resumen, en_caso_de_falla: [...b.resumen.en_caso_de_falla, fallaNueva()] },
    }));
  }

  protected quitarFalla(i: number): void {
    this.cambiar((b) => ({
      ...b,
      resumen: {
        ...b.resumen,
        en_caso_de_falla: b.resumen.en_caso_de_falla.filter((_, j) => j !== i),
      },
    }));
  }

  // ── Pasos ─────────────────────────────────────────────────────────────────────────────────

  protected editarPaso<C extends CampoPaso>(i: number, campo: C, valor: PasoBorrador[C]): void {
    this.cambiar((b) => editarPaso(b, i, campo, valor));
  }

  protected editarTiempo(i: number, valor: string): void {
    const n = valor.trim() === '' ? null : Number(valor);
    this.editarPaso(i, 'tiempo_esperado_min', n !== null && Number.isFinite(n) ? n : null);
  }

  protected confirmarCampo(i: number, campo: string): void {
    this.cambiar((b) => confirmarCampo(b, i, campo));
  }

  protected confirmarPaso(i: number): void {
    this.cambiar((b) => confirmarPaso(b, i));
  }

  protected inferido(p: PasoBorrador, campo: string): boolean {
    return p.campos_inferidos.includes(campo);
  }

  /** La evidencia de un campo del paso (el primer elemento que coincide con el valor). */
  protected evidencia(p: PasoBorrador, campo: string, valor?: string): Evidencia | null {
    return (
      p.evidencia.find((e) => e.campo === campo && (valor === undefined || e.valor === valor)) ??
      null
    );
  }

  protected subir(i: number): void {
    this.cambiar((b) => mover(b, i, i - 1));
  }

  protected bajar(i: number): void {
    this.cambiar((b) => mover(b, i, i + 1));
  }

  protected agregarPaso(despuesDe?: number): void {
    const b = this.borrador();
    if (!b) {
      return;
    }
    const nuevo = agregarPaso(b, despuesDe);
    this.cambiar(() => nuevo);
    const clave = nuevo.pasos[(despuesDe ?? b.pasos.length - 1) + 1].clave;
    this.enfocar(`paso-${clave}-nombre`);
  }

  protected quitarPaso(i: number): void {
    const b = this.borrador();
    const r = b ? quitar(b, i) : null;
    if (!r) {
      return;
    }
    this.cambiar(() => r.borrador);
    this.quitados.update((q) => [...q, r.quitado]);
  }

  protected deshacerQuitar(): void {
    const q = this.ultimoQuitado();
    if (!q) {
      return;
    }
    this.quitados.update((lista) => lista.slice(0, -1));
    this.cambiar((b) => restaurar(b, q));
  }

  /** "Unir con el siguiente paso": si los responsables difieren, pregunta cuál usar. */
  protected unir(i: number, responsable?: string): void {
    const b = this.borrador();
    if (!b) {
      return;
    }
    const r = unirConSiguiente(b, i, responsable);
    if (!r.ok) {
      this.unionPendiente.set({ indice: i, responsables: r.responsables });
      return;
    }
    this.unionPendiente.set(null);
    this.cambiar(() => r.borrador);
    // El nombre del paso unido es el del primero y se puede cambiar al instante.
    this.enfocar(`paso-${b.pasos[i].clave}-nombre`);
  }

  protected cancelarUnion(): void {
    this.unionPendiente.set(null);
  }

  protected iniciarArrastre(i: number, evento: DragEvent): void {
    this.arrastrando.set(i);
    evento.dataTransfer?.setData('text/plain', String(i));
    if (evento.dataTransfer) {
      evento.dataTransfer.effectAllowed = 'move';
    }
  }

  protected sobre(evento: DragEvent): void {
    if (this.arrastrando() !== null) {
      evento.preventDefault();
    }
  }

  protected soltar(i: number, evento: DragEvent): void {
    evento.preventDefault();
    const de = this.arrastrando();
    this.arrastrando.set(null);
    if (de !== null) {
      this.cambiar((b) => mover(b, de, i));
    }
  }

  protected terminarArrastre(): void {
    this.arrastrando.set(null);
  }

  protected urlMiniatura(t: number): string {
    return `${API}/videos/${this.idVideo()}/thumb?t=${t}`;
  }

  protected ocultarMiniatura(clave: number): void {
    this.miniaturasFallidas.update((f) => new Set(f).add(clave));
  }

  // ── Puntos clave ──────────────────────────────────────────────────────────────────────────

  protected editarPunto(i: number, cambios: Partial<PuntoBorrador>): void {
    this.cambiar((b) => ({
      ...b,
      puntos_clave: b.puntos_clave.map((x, j) =>
        j === i ? { ...x, ...cambios, revisado: true } : x,
      ),
    }));
  }

  protected quitarPunto(i: number): void {
    this.cambiar((b) => ({ ...b, puntos_clave: b.puntos_clave.filter((_, j) => j !== i) }));
  }

  /** Abre el video en ese segundo (RF-24). */
  protected abrirVideo(t: number): void {
    const dialogo = this.dialogo()?.nativeElement;
    const video = this.reproductor()?.nativeElement;
    if (!dialogo || !video) {
      return;
    }
    if (!dialogo.open && typeof dialogo.showModal === 'function') {
      dialogo.showModal();
    }
    if (video.readyState >= 1) {
      video.currentTime = t;
      void video.play?.()?.catch(() => undefined);
    } else {
      // Con preload="none", play() carga el video; el salto va al llegar los metadatos.
      this.segundoPendiente = t;
      void video.play?.()?.catch(() => undefined);
    }
  }

  protected alCargarVideo(): void {
    const video = this.reproductor()?.nativeElement;
    if (video && this.segundoPendiente !== null) {
      video.currentTime = this.segundoPendiente;
      this.segundoPendiente = null;
      void video.play?.()?.catch(() => undefined);
    }
  }

  protected cerrarVideo(): void {
    this.reproductor()?.nativeElement.pause?.();
    this.dialogo()?.nativeElement.close?.();
  }

  // ── Errores del 422 ───────────────────────────────────────────────────────────────────────

  /** El mensaje del 422 para un campo (p. ej. `'pasos', 3, 'nombre'`), o null. */
  protected errorEn(...ruta: (string | number)[]): string | null {
    const buscada = ruta.join('.');
    return this.errores().find((e) => e.ruta.join('.') === buscada)?.mensaje ?? null;
  }

  // ── Guardar, biblioteca, validar ──────────────────────────────────────────────────────────

  /**
   * `PUT /sops/{id}` con el SOP completo (números 1..n), luego `GET /sops/{id}` para comprobar
   * que el orden, las listas y los números quedaron como se veían. Un 422 marca cada campo sin
   * tocar lo editado; un 409 dice que el SOP todavía no está listo.
   */
  protected guardar(): void {
    const b = this.borrador();
    if (!b || this.guardando()) {
      return;
    }
    const enviado = aSop(b);
    let escrito = false;
    this.guardando.set(true);
    this.errores.set([]);
    this.error.set(null);
    this.aviso.set(null);
    this.api
      .corregirSop(this.id(), enviado)
      .pipe(
        tap(() => (escrito = true)),
        switchMap(() => this.api.detalleSop(this.id())),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (detalle) => {
          this.guardando.set(false);
          this.detalle.set(detalle);
          this.guardado.set(huella(detalle.sop));
          if (huella(detalle.sop) !== huella(enviado)) {
            this.error.set(
              'Se guardó, pero al releerlo no quedó como se ve en pantalla. Revisa los pasos y ' +
                'vuelve a guardar.',
            );
            return;
          }
          // La duración total la recalcula la API: se toma la suya.
          const total = detalle.sop.resumen?.duracion_total_min ?? null;
          this.borrador.update((actual) =>
            actual
              ? { ...actual, resumen: { ...actual.resumen, duracion_total_min: total } }
              : actual,
          );
          this.guardadoEnSesion.set(true);
          this.aviso.set('Cambios guardados.');
        },
        error: (e: unknown) => {
          this.guardando.set(false);
          if (escrito) {
            this.error.set(`Se guardó, pero no se pudo releer el SOP. ${mensajeDeError(e)}`);
          } else if (e instanceof HttpErrorResponse && e.status === 409) {
            this.error.set(
              'El SOP todavía no está listo: espera a que termine la conversión y vuelve a guardar.',
            );
          } else if (e instanceof HttpErrorResponse && e.status === 422) {
            this.errores.set(erroresPorCampo(e));
            this.error.set('La API rechazó el SOP: corrige lo marcado. Lo editado sigue aquí.');
          } else {
            this.error.set(`No se pudo guardar. ${mensajeDeError(e)}`);
          }
        },
      });
  }

  protected guardarEnBiblioteca(): void {
    const detalle = this.detalle();
    if (!detalle || this.enviandoBiblioteca() || this.sucio()) {
      return;
    }
    this.enviandoBiblioteca.set(true);
    this.api
      .guardarEnBiblioteca(detalle.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (estado) => {
          this.enviandoBiblioteca.set(false);
          this.detalle.set({ ...detalle, en_biblioteca: estado.en_biblioteca ?? true });
        },
        error: (e: unknown) => {
          this.enviandoBiblioteca.set(false);
          this.error.set(`No se pudo guardar en la biblioteca. ${mensajeDeError(e)}`);
        },
      });
  }

  /** "Usar para validar": a `/nuevo` con este SOP ya elegido. */
  protected usarParaValidar(): void {
    void this.router.navigate(['/nuevo'], { queryParams: { sop: this.id() } });
  }

  /** Repite la validación del video con el SOP corregido, sin Whisper (ADR-019, ADR-022). */
  protected revalidar(): void {
    const video = this.video();
    if (video === undefined || this.revalidando() || this.sucio()) {
      return;
    }
    this.revalidando.set(true);
    this.api
      .revalidar(video)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.revalidando.set(false);
          void this.router.navigate(['/videos', video, 'reporte']);
        },
        error: (e: unknown) => {
          this.revalidando.set(false);
          this.error.set(
            e instanceof HttpErrorResponse && e.status === 409
              ? 'El video todavía se está procesando. Cuando termine, vuelve a revalidarlo.'
              : `No se pudo revalidar el video. ${mensajeDeError(e)}`,
          );
        },
      });
  }

  // ── Carga ─────────────────────────────────────────────────────────────────────────────────

  private cargar(): void {
    this.api
      .detalleSop(this.id())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (detalle) => {
          this.detalle.set(detalle);
          this.borrador.set(aBorrador(detalle.sop, duracionNarrada(detalle)));
          this.guardado.set(huella(detalle.sop));
        },
        error: (e: unknown) => {
          if (e instanceof HttpErrorResponse && e.status === 409) {
            this.aviso.set('El SOP todavía se está convirtiendo…');
            this.esperarConversion();
          } else {
            this.error.set(`No se pudo leer el SOP. ${mensajeDeError(e)}`);
          }
        },
      });
  }

  private esperarConversion(): void {
    timer(SONDEO_EDITOR_MS, SONDEO_EDITOR_MS)
      .pipe(
        switchMap(() => this.api.estadoSop(this.id())),
        takeWhile((e) => e.estado !== 'listo' && e.estado !== 'error', true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (estado) => {
          if (estado.estado === 'listo') {
            this.aviso.set(null);
            this.cargar();
          } else if (estado.estado === 'error') {
            this.aviso.set(null);
            this.error.set(
              `No se pudo convertir el SOP ${estado.codigo}. ${estado.mensaje ?? ''}`.trim(),
            );
          }
        },
        error: (e: unknown) => this.error.set(`No se pudo consultar el SOP. ${mensajeDeError(e)}`),
      });
  }

  private cambiar(f: (b: Borrador) => Borrador): void {
    const b = this.borrador();
    if (b) {
      this.borrador.set(f(b));
      this.aviso.set(null);
    }
  }

  private enfocar(id: string): void {
    afterNextRender(() => document.getElementById(id)?.focus(), { injector: this.injector });
  }
}
