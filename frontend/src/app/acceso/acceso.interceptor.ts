import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { API } from '../api/api.service';
import { vistaDeRuta } from './acceso.guard';
import { AccesoService, Vista } from './acceso.service';

/** La vista que pide la pantalla en curso (la ruta más profunda), o null. */
function vistaActiva(router: Router): Vista | null {
  let ruta = router.routerState.snapshot.root;
  while (ruta.firstChild) {
    ruta = ruta.firstChild;
  }
  return vistaDeRuta(ruta);
}

/**
 * Un 401 de la API (falta la clave o la sesión se cerró, §11, ADR-027) en una pantalla que pide
 * una vista lleva a `/acceso?vista=…&volver=<url>`; con la clave, vuelve a esa pantalla. El error
 * sigue su camino igual. No redirige los 401 de `/api/acceso` (clave equivocada) ni los de una
 * pantalla sin vista, como `/v/:id`, que pregunta sin pedir la clave.
 */
export const accesoInterceptor: HttpInterceptorFn = (pedido, siguiente) => {
  const router = inject(Router);
  const acceso = inject(AccesoService);
  return siguiente(pedido).pipe(
    catchError((error: unknown) => {
      const deLaApi = pedido.url.startsWith(`${API}/`) && !pedido.url.startsWith(`${API}/acceso`);
      if (error instanceof HttpErrorResponse && error.status === 401 && deLaApi) {
        const vista = vistaActiva(router);
        if (vista !== null) {
          acceso.olvidar();
          void router.navigate(['/acceso'], { queryParams: { vista, volver: router.url } });
        }
      }
      return throwError(() => error);
    }),
  );
};
