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

@Component({
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  selector: 'app-root',
  styleUrl: './app.scss',
  templateUrl: './app.html',
})
export class App {
  private readonly router = inject(Router);

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
   * vista de carga; la pantalla trae su propio encabezado. La separación de verdad llega con la
   * clave de acceso (#30).
   */
  protected readonly consulta = computed(() => this.datos()['consulta'] === true);
}
