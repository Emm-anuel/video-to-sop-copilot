import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { switchMap, takeWhile, timer } from 'rxjs';
import { ApiService } from '../api/api.service';
import { mensajeDeError } from '../api/errores';
import { EstadoSop, SopResumen } from '../api/tipos';
import { SONDEO_SOP_MS } from '../nuevo/nuevo';
import { coincide, fechaCorta } from './filtro';

export type FiltroOrigen = 'todos' | 'cargado' | 'generado';

/** Un SOP que se está subiendo desde la biblioteca: su fila provisional hasta que termina. */
export interface SubidaSop {
  clave: number;
  nombre: string;
  /** Último estado de la conversión; `null` mientras `POST /sops` no responde. */
  estado: EstadoSop | null;
  /** El rechazo de `POST /sops` (extensión, tamaño, archivo ilegible). */
  error: string | null;
}

/** Aviso en la fila de un SOP: `conflicto` (409, ámbar) explica por qué no se pudo borrar. */
interface AvisoFila {
  texto: string;
  conflicto: boolean;
}

/**
 * Biblioteca de SOP (RF-05, pantalla 1): los SOP listos y guardados (`GET /sops`), con búsqueda
 * por título o código y filtro por origen. Por SOP: ver o editar (`/sops/:id`), usar para validar
 * (`/nuevo?sop=ID`) y eliminar con confirmación en la propia fila; si algún video lo usa, la API
 * responde 409 y la fila muestra el porqué en ámbar, no un error genérico.
 *
 * "Subir SOP" usa la carga asíncrona (`POST /sops`, 202) y deja una fila provisional que consulta
 * `GET /sops/{id}/estado` cada 2 s hasta que termina: con `listo` recarga la lista y marca el SOP
 * como nuevo (con advertencias o convertido por el modelo, invita a revisarlo); con `error`
 * muestra el mensaje y "Descartar" lo borra (nadie lo usa).
 *
 * RNF-13: tarjetas por defecto y filas de tabla desde 60 rem del propio componente (container
 * query, no el ancho de la ventana); todo lo que se toca mide al menos 36 px.
 */
@Component({
  selector: 'app-biblioteca',
  imports: [RouterLink],
  templateUrl: './biblioteca.html',
  styleUrl: './biblioteca.scss',
})
export class Biblioteca implements OnInit {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** `null` mientras carga. */
  protected readonly sops = signal<SopResumen[] | null>(null);
  protected readonly errorCarga = signal<string | null>(null);
  protected readonly consulta = signal('');
  protected readonly origen = signal<FiltroOrigen>('todos');
  protected readonly visibles = computed(() =>
    (this.sops() ?? []).filter(
      (s) =>
        (this.origen() === 'todos' || s.origen === this.origen()) && coincide(s, this.consulta()),
    ),
  );

  protected readonly subidas = signal<SubidaSop[]>([]);
  /** Los que se subieron en esta visita, con su estado final (advertencias, método). */
  protected readonly recientes = signal<ReadonlyMap<number, EstadoSop>>(new Map());

  protected readonly confirmando = signal<number | null>(null);
  protected readonly borrando = signal<number | null>(null);
  protected readonly avisos = signal<Readonly<Record<number, AvisoFila>>>({});
  /** Lo que se anuncia a los lectores de pantalla (p. ej. "SOP-0003 eliminado."). */
  protected readonly anuncio = signal('');

  protected readonly fechaCorta = fechaCorta;
  private siguienteClave = 1;

  ngOnInit(): void {
    this.recargar();
  }

  protected recargar(): void {
    this.errorCarga.set(null);
    this.api
      .listarSops()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (lista) => this.sops.set(lista),
        error: (e: unknown) => {
          this.sops.set(null);
          this.errorCarga.set(`No se pudo leer la biblioteca. ${mensajeDeError(e)}`);
        },
      });
  }

  protected cambiarOrigen(evento: Event): void {
    this.origen.set((evento.target as HTMLSelectElement).value as FiltroOrigen);
  }

  protected pedirConfirmacion(id: number): void {
    this.confirmando.set(id);
    this.quitarAviso(id);
  }

  protected eliminar(sop: SopResumen): void {
    this.confirmando.set(null);
    this.borrando.set(sop.id);
    this.api
      .borrarSop(sop.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.borrando.set(null);
          this.sops.update((lista) => (lista ?? []).filter((s) => s.id !== sop.id));
          this.anuncio.set(`${sop.codigo} eliminado.`);
        },
        error: (e: unknown) => {
          this.borrando.set(null);
          const conflicto = e instanceof HttpErrorResponse && e.status === 409;
          const texto = conflicto
            ? mensajeDeError(e)
            : `No se pudo eliminar ${sop.codigo}. ${mensajeDeError(e)}`;
          this.avisos.update((a) => ({ ...a, [sop.id]: { texto, conflicto } }));
        },
      });
  }

  /** "Subir SOP": uno o varios archivos, cada uno con su fila provisional. */
  protected subir(evento: Event): void {
    const input = evento.target as HTMLInputElement;
    const archivos = Array.from({ length: input.files?.length ?? 0 }, (_, i) =>
      input.files!.item(i),
    ).filter((a): a is File => a !== null);
    input.value = ''; // el mismo archivo se puede volver a elegir
    for (const archivo of archivos) {
      this.subirUno(archivo);
    }
  }

  protected descartar(subida: SubidaSop): void {
    this.quitarSubida(subida.clave);
    const id = subida.estado?.estado === 'error' ? subida.estado.id : null;
    if (id !== null) {
      // Un SOP en error no lo usa nadie: se borra para no dejar filas huérfanas en la base.
      this.api
        .borrarSop(id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({ error: () => {} });
    }
  }

  protected etapa(subida: SubidaSop): string {
    switch (subida.estado?.estado) {
      case undefined:
        return 'Subiendo…';
      case 'en_cola':
        return 'En cola para convertir…';
      case 'convirtiendo':
        return 'Convirtiendo…';
      case 'error':
        return 'No se pudo convertir';
      default:
        return 'Listo';
    }
  }

  private subirUno(archivo: File): void {
    const clave = this.siguienteClave++;
    this.subidas.update((s) => [{ clave, nombre: archivo.name, estado: null, error: null }, ...s]);
    this.api
      .crearSop(archivo)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (estado) => {
          this.actualizar(clave, estado);
          if (estado.estado !== 'listo' && estado.estado !== 'error') {
            this.sondear(clave, estado.id);
          }
        },
        error: (e: unknown) =>
          this.cambiarSubida(clave, { error: `No se pudo subir. ${mensajeDeError(e)}` }),
      });
  }

  private sondear(clave: number, id: number): void {
    timer(SONDEO_SOP_MS, SONDEO_SOP_MS)
      .pipe(
        switchMap(() => this.api.estadoSop(id)),
        takeWhile((estado) => estado.estado !== 'listo' && estado.estado !== 'error', true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (estado) => this.actualizar(clave, estado),
        error: (e: unknown) =>
          this.cambiarSubida(clave, {
            error: `No se pudo consultar la conversión. ${mensajeDeError(e)}`,
          }),
      });
  }

  /** Nuevo estado de una subida; con `listo` la fila provisional deja su lugar al SOP de la lista. */
  private actualizar(clave: number, estado: EstadoSop): void {
    if (estado.estado !== 'listo') {
      this.cambiarSubida(clave, { estado });
      return;
    }
    this.quitarSubida(clave);
    this.recientes.update((r) => new Map(r).set(estado.id, estado));
    this.anuncio.set(`${estado.codigo} listo: ${estado.titulo ?? ''}`.trim());
    this.recargar();
  }

  private cambiarSubida(clave: number, cambios: Partial<SubidaSop>): void {
    this.subidas.update((s) => s.map((x) => (x.clave === clave ? { ...x, ...cambios } : x)));
  }

  private quitarSubida(clave: number): void {
    this.subidas.update((s) => s.filter((x) => x.clave !== clave));
  }

  private quitarAviso(id: number): void {
    this.avisos.update((a) => {
      const { [id]: _, ...resto } = a;
      return resto;
    });
  }
}
