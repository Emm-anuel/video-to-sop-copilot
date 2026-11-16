import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import {
  Data,
  NavigationEnd,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet,
} from '@angular/router';
import { filter, map } from 'rxjs';
import { AccesoService } from './acceso/acceso.service';

@Component({
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  selector: 'app-root',
  styleUrl: './app.scss',
  templateUrl: './app.html',
})
export class App {
  private readonly router = inject(Router);
  private readonly acceso = inject(AccesoService);

  /** Los `data` de la ruta activa (la más profunda). */
  private readonly datos = toSignal(
    this.router.events.pipe(
      filter((evento) => evento instanceof NavigationEnd),
      map(() => {
        let ruta = this.router.routerState.snapshot.root;
        while (ruta.firstChild) {
          ruta = ruta.firstChild;
        }
        return ruta.data;
      }),
    ),
    { initialValue: {} as Data },
  );

  /** Si la ruta activa pide todo el ancho (`data: { ancho: true }`, p. ej. el reporte). */
  protected readonly ancho = computed(() => this.datos()['ancho'] === true);

  /**
   * La vista de consulta (`data: { consulta: true }`, `/buscar`): sin la barra ni el menú de la
   * vista de carga; la pantalla trae su propio encabezado (también `/acceso` y `/v/:id`). Cada
   * vista pide su clave (#30, ADR-027): la ruta lo dice con `data: { vista }` y lo revisa
   * `requiereVista`.
   */
  protected readonly consulta = computed(() => this.datos()['consulta'] === true);

  /** "Salir" solo si la vista de carga tiene clave y esta sesión la escribió. */
  protected readonly conSesionDeCarga = computed(() => this.acceso.ultimo()?.carga.sesion === true);

  /** Cierra la sesión de la vista de carga (`DELETE /acceso`) y vuelve a pedir la clave. */
  protected salir(): void {
    this.acceso.salir('carga').subscribe({
      next: () => void this.router.navigate(['/acceso'], { queryParams: { vista: 'carga' } }),
      error: () => undefined,
    });
  }
}
