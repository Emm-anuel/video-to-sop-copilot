import { Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

@Component({
  imports: [RouterOutlet, RouterLink],
  selector: 'app-root',
  styleUrl: './app.scss',
  templateUrl: './app.html',
})
export class App {
  private readonly router = inject(Router);

  /** Si la ruta activa pide todo el ancho (`data: { ancho: true }`, p. ej. el reporte). */
  protected readonly ancho = toSignal(
    this.router.events.pipe(
      filter((evento) => evento instanceof NavigationEnd),
      map(() => {
        let ruta = this.router.routerState.snapshot.root;
        while (ruta.firstChild) {
          ruta = ruta.firstChild;
        }
        return ruta.data['ancho'] === true;
      }),
    ),
    { initialValue: false },
  );
}
