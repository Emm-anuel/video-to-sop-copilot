import { Routes } from '@angular/router';
import { Nuevo } from './nuevo/nuevo';
import { ReporteProvisional } from './reporte-provisional/reporte-provisional';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'nuevo' },
  { path: 'nuevo', component: Nuevo, title: 'Nuevo análisis · SOPVID' },
  {
    path: 'videos/:id/reporte',
    component: ReporteProvisional,
    title: 'Reporte de validación · SOPVID',
  },
];
