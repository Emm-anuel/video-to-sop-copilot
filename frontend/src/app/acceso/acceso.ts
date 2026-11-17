import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { mensajeDeError } from '../api/errores';
import { AccesoService, NOMBRE_VISTA, Vista, esVista } from './acceso.service';

/** Adónde va cada vista si `volver` no sirve. */
const INICIO: Record<Vista, string> = { carga: '/nuevo', busqueda: '/buscar' };

/**
 * Adónde volver tras escribir la clave: `volver` si es una ruta de la app ("/…", sin "//" ni "/\"
 * que el navegador leería como otro sitio, y no la misma `/acceso`); si no, el inicio de la vista.
 */
export function destinoSeguro(volver: string | null, vista: Vista): string {
  if (
    volver !== null &&
    volver.startsWith('/') &&
    !volver.startsWith('//') &&
    !volver.startsWith('/\\') &&
    !volver.startsWith('/acceso')
  ) {
    return volver;
  }
  return INICIO[vista];
}

/**
 * `/acceso?vista=…&volver=…` (§11, ADR-027): pide la clave de una vista y vuelve a donde iba. La
 * clave viaja una vez a `POST /acceso`, que deja una cookie de sesión; el navegador no la guarda.
 * Si la vista está abierta (sin clave) o ya hay sesión, sigue de largo.
 */
@Component({
  selector: 'app-acceso',
  templateUrl: './acceso.html',
  styleUrl: './acceso.scss',
})
export class Acceso {
  private readonly acceso = inject(AccesoService);
  private readonly router = inject(Router);

  protected readonly vista: Vista;
  protected readonly nombre: string;
  private readonly destino: string;
  protected readonly clave = signal('');
  protected readonly enviando = signal(false);
  protected readonly error = signal<string | null>(null);

  constructor() {
    const consulta = inject(ActivatedRoute).snapshot.queryParamMap;
    const vista = consulta.get('vista');
    this.vista = esVista(vista) ? vista : 'carga';
    this.nombre = NOMBRE_VISTA[this.vista];
    this.destino = destinoSeguro(consulta.get('volver'), this.vista);
    this.acceso
      .permite(this.vista)
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (puede) => {
          if (puede) {
            this.seguir();
          }
        },
        error: () => undefined, // se intenta al enviar la clave
      });
  }

  protected escribir(evento: Event): void {
    this.clave.set((evento.target as HTMLInputElement).value);
    this.error.set(null);
  }

  protected entrar(evento: Event): void {
    evento.preventDefault();
    const clave = this.clave().trim();
    if (!clave || this.enviando()) {
      return;
    }
    this.enviando.set(true);
    this.error.set(null);
    this.acceso.entrar(this.vista, clave).subscribe({
      next: () => this.seguir(),
      error: (e: unknown) => {
        this.enviando.set(false);
        this.error.set(
          e instanceof HttpErrorResponse && e.status === 401
            ? 'La clave no es correcta.'
            : mensajeDeError(e),
        );
      },
    });
  }

  private seguir(): void {
    void this.router.navigateByUrl(this.destino, { replaceUrl: true });
  }
}
