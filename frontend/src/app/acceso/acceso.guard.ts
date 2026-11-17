import { inject } from '@angular/core';
import {
  ActivatedRouteSnapshot,
  CanActivateChildFn,
  CanActivateFn,
  Router,
  RouterStateSnapshot,
} from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { AccesoService, Vista, esVista } from './acceso.service';

/**
 * La vista que pide la ruta (`data: { vista }`) o null. En una ruta hija de un padre sin
 * componente, `data` ya trae la del padre.
 */
export function vistaDeRuta(ruta: ActivatedRouteSnapshot): Vista | null {
  const vista: unknown = ruta.data['vista'];
  return esVista(vista) ? vista : null;
}

function revisar(ruta: ActivatedRouteSnapshot, estado: RouterStateSnapshot) {
  const vista = vistaDeRuta(ruta);
  if (vista === null) {
    return of(true);
  }
  const router = inject(Router);
  return inject(AccesoService)
    .permite(vista)
    .pipe(
      map(
        (puede) =>
          puede ||
          router.createUrlTree(['/acceso'], { queryParams: { vista, volver: estado.url } }),
      ),
      // Sin respuesta de la API (apagada, sin red), la pantalla entra y dice qué pasa al pedir
      // sus datos; si falta la clave, el 401 la manda a /acceso (interceptor).
      catchError(() => of(true)),
    );
}

/**
 * Antes de entrar a una ruta con `data: { vista }` (§11, ADR-027): con la vista abierta o con
 * sesión, pasa; si no, lleva a `/acceso?vista=…&volver=<url>`, que vuelve aquí con la clave.
 */
export const requiereVista: CanActivateFn & CanActivateChildFn = (ruta, estado) =>
  revisar(ruta, estado);
