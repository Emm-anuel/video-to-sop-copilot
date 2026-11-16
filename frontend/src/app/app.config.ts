import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { accesoInterceptor } from './acceso/acceso.interceptor';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    // Un 401 lleva a la pantalla de la clave de la vista y luego de vuelta (§11, ADR-027).
    provideHttpClient(withInterceptors([accesoInterceptor])),
  ],
};
