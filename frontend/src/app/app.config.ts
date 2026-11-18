import { provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { accesoInterceptor } from './acceso/acceso.interceptor';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    // Un 401 lleva a la pantalla de la clave de la vista y luego de vuelta (§11, ADR-027).
    // XMLHttpRequest y no fetch (el valor por defecto desde Angular 21): fetch no avisa el avance
    // de una subida y la barra del video (RF-06) se quedaría quieta durante cada parte de 16 MB.
    provideHttpClient(withXhr(), withInterceptors([accesoInterceptor])),
  ],
};
