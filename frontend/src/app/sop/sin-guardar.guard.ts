import { CanDeactivateFn } from '@angular/router';

/** Pantalla que puede tener cambios sin guardar (el editor del SOP). */
export interface ConCambios {
  puedeSalir(): boolean;
}

export const PREGUNTA_SALIR = 'Hay cambios sin guardar en el SOP. ¿Salir sin guardarlos?';

/** Pregunta antes de salir de la ruta si hay cambios sin guardar (RF-26). */
export const sinGuardar: CanDeactivateFn<ConCambios> = (pantalla) =>
  pantalla.puedeSalir() || window.confirm(PREGUNTA_SALIR);
