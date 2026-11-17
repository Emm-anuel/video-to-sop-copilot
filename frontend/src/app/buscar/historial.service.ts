import { Injectable, computed, signal } from '@angular/core';
import { RespuestaBusqueda, SopDeVideo } from '../api/busqueda';

/** Los filtros de una búsqueda (RF-37), con lo necesario para mostrarlos como chips. */
export interface FiltrosBusqueda {
  sop: SopDeVideo | null;
  video: { id: number; titulo: string } | null;
}

export const SIN_FILTROS: FiltrosBusqueda = { sop: null, video: null };

export type EstadoTurno = 'buscando' | 'listo' | 'error';

/** Una consulta de la conversación y lo que respondió la API. */
export interface Turno {
  clave: number;
  consulta: string;
  filtros: FiltrosBusqueda;
  estado: EstadoTurno;
  respuesta: RespuestaBusqueda | null;
  error: string | null;
}

/** Lo que se guarda en `sessionStorage`. `v1`: si cambia la forma, se cambia la clave. */
interface Guardado {
  turnos: Turno[];
  elegido: number | null;
  siguiente: number;
}

export const CLAVE_HISTORIAL = 'sopvid.busqueda.v1';
/** Turnos que se conservan; los más viejos se van primero. */
export const MAX_TURNOS = 30;
export const INTERRUMPIDA = 'La búsqueda se interrumpió al recargar la página.';

/**
 * El historial de búsquedas de la sesión (RF-36), en el navegador: sobrevive a navegar y volver
 * (el servicio es de la aplicación) y a recargar la pestaña (`sessionStorage`). Ninguna lectura
 * ni escritura del almacenamiento rompe la pantalla: todo va en `try/catch`. Si las respuestas no
 * caben, se guardan solo las consultas; si tampoco, el historial vive solo en memoria.
 */
@Injectable({ providedIn: 'root' })
export class HistorialBusqueda {
  private readonly estado = signal<Guardado>(leer());

  readonly turnos = computed(() => this.estado().turnos);
  /** La clave del turno cuyos resultados se ven; null si no hay. */
  readonly elegido = computed(() => this.estado().elegido);

  /** Agrega una consulta en `buscando` y la devuelve. */
  agregar(consulta: string, filtros: FiltrosBusqueda): Turno {
    const actual = this.estado();
    const turno: Turno = {
      clave: actual.siguiente,
      consulta,
      filtros,
      estado: 'buscando',
      respuesta: null,
      error: null,
    };
    this.cambiar({
      ...actual,
      turnos: [...actual.turnos, turno].slice(-MAX_TURNOS),
      siguiente: actual.siguiente + 1,
    });
    return turno;
  }

  actualizar(clave: number, cambios: Partial<Omit<Turno, 'clave'>>): void {
    const actual = this.estado();
    this.cambiar({
      ...actual,
      turnos: actual.turnos.map((t) => (t.clave === clave ? { ...t, ...cambios } : t)),
    });
  }

  elegir(clave: number | null): void {
    this.cambiar({ ...this.estado(), elegido: clave });
  }

  limpiar(): void {
    this.cambiar({ turnos: [], elegido: null, siguiente: this.estado().siguiente });
  }

  private cambiar(nuevo: Guardado): void {
    this.estado.set(nuevo);
    guardar(nuevo);
  }
}

function almacen(): Storage | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null; // p. ej. el navegador bloquea el almacenamiento del sitio
  }
}

function leer(): Guardado {
  const vacio: Guardado = { turnos: [], elegido: null, siguiente: 1 };
  try {
    const texto = almacen()?.getItem(CLAVE_HISTORIAL);
    if (!texto) {
      return vacio;
    }
    const datos = JSON.parse(texto) as Partial<Guardado>;
    if (!Array.isArray(datos.turnos)) {
      return vacio;
    }
    // Una búsqueda que seguía en curso al recargar ya no va a responder: se ofrece reintentarla.
    const turnos = datos.turnos.map((t) =>
      t.estado === 'buscando' ? { ...t, estado: 'error' as const, error: INTERRUMPIDA } : t,
    );
    const siguiente = Math.max(
      typeof datos.siguiente === 'number' ? datos.siguiente : 1,
      ...turnos.map((t) => t.clave + 1),
    );
    return { turnos, elegido: datos.elegido ?? null, siguiente };
  } catch {
    return vacio;
  }
}

function guardar(datos: Guardado): void {
  const destino = almacen();
  if (!destino) {
    return;
  }
  try {
    destino.setItem(CLAVE_HISTORIAL, JSON.stringify(datos));
  } catch {
    // Sin espacio: solo las consultas, sin respuestas (al volver se repiten con un clic).
    try {
      const ligero = { ...datos, turnos: datos.turnos.map((t) => ({ ...t, respuesta: null })) };
      destino.setItem(CLAVE_HISTORIAL, JSON.stringify(ligero));
    } catch {
      // Tampoco: el historial queda solo en memoria, que basta para navegar y volver.
    }
  }
}
