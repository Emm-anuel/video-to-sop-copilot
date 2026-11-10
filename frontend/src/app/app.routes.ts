import { Routes } from '@angular/router';
import { Nuevo } from './nuevo/nuevo';
import { Reporte } from './reporte/reporte';
import { SopGenerado } from './sop/sop-generado';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'nuevo' },
  { path: 'nuevo', component: Nuevo, title: 'Nuevo análisis · SOPVID' },
  {
    path: 'videos/:id/reporte',
    component: Reporte,
    // Dos columnas (tabla y video): la pantalla usa todo el ancho (app.html).
    data: { ancho: true },
    title: 'Reporte de validación · SOPVID',
  },
  { path: 'videos/:id/sop', component: SopGenerado, title: 'SOP generado · SOPVID' },
];
